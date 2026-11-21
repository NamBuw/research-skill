#!/usr/bin/env python3
"""Local PDF layout, table, OCR, figure/caption, and equation block extraction.

Adapted / ported patterns:
- paper-qa (Apache-2.0): clean_invalid_unicode, Shannon entropy text gate (maybe_is_text).
- Clean-room PyMuPDF + pdfplumber + tesseract pipeline producing MinerU Content List V2-compatible items.
- Optional external `mineru` CLI wrapper (--use-mineru) with zero MinerU source code copied.
- Clean-room PyMuPDF figure/caption pairing with mandatory visual_check_required=True.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

FORMAT = 'research_scientist_pdf_blocks_v1'
MATH_SYMBOLS_RE = re.compile(r'[=≈≠≤≥∑∏∫∂∇∈∉⊂⊆∪∩→⇒⇔α-ωΑ-Ω]')
EQUATION_NUM_RE = re.compile(r'\(\d+(?:\.\d+)?\)\s*$')
TABLE_CAPTION_RE = re.compile(r'^\s*(?:Table|Tab\.?)\s+\d+\b', re.I)
FIG_CAPTION_RE = re.compile(r'^\s*(?:Figure|Fig\.?|Chart|Diagram)\s+\d+\b', re.I)


def clean_invalid_unicode(text: str) -> str:
    """Strip NUL bytes and surrogate codepoints (paper-qa Apache-2.0)."""
    if not isinstance(text, str):
        return ''
    return ''.join(ch for ch in text if ch != '\x00' and not (0xD800 <= ord(ch) <= 0xDFFF))


def shannon_entropy(text: str) -> float:
    """Compute character-level Shannon entropy over non-space characters (paper-qa Apache-2.0)."""
    s = re.sub(r'\s+', '', text or '')
    if not s:
        return 0.0
    counts = Counter(s)
    total = len(s)
    return -sum((cnt / total) * math.log2(cnt / total) for cnt in counts.values())


def maybe_is_text(text: str, thresh: float = 2.5, min_chars: int = 20) -> bool:
    """Filter corrupted/gibberish text via Shannon entropy while preserving short headings/equations."""
    s = re.sub(r'\s+', '', clean_invalid_unicode(text))
    if not s:
        return False
    if len(s) >= 8 and len(set(s)) <= 2:
        return False
    ent = shannon_entropy(s)
    if ent >= 8.0:
        return False
    if len(s) >= min_chars and ent <= thresh:
        return False
    return True


def _bbox_center(bbox: list[float]) -> tuple[float, float]:
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def _point_in_bbox(px: float, py: float, bbox: list[float], tol: float = 2.0) -> bool:
    return (bbox[0] - tol) <= px <= (bbox[2] + tol) and (bbox[1] - tol) <= py <= (bbox[3] + tol)


def _overlap_min_ratio(a: list[float], b: list[float]) -> float:
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    area_a = max((a[2] - a[0]) * (a[3] - a[1]), 1e-6)
    area_b = max((b[2] - b[0]) * (b[3] - b[1]), 1e-6)
    return inter / min(area_a, area_b)


def _rect_distance(a: list[float], b: list[float]) -> float:
    dx = max(0.0, max(a[0] - b[2], b[0] - a[2]))
    dy = max(0.0, max(a[1] - b[3], b[1] - a[3]))
    return math.hypot(dx, dy)


def _looks_like_equation(text: str) -> bool:
    s = text.strip()
    if not s or len(s) > 400:
        return False
    sym_count = len(MATH_SYMBOLS_RE.findall(s))
    has_num_tag = bool(EQUATION_NUM_RE.search(s))
    sentence_ends = len(re.findall(r'[.!?]\s+[A-Z]', s))
    if sentence_ends >= 2:
        return False
    return sym_count >= 2 or (sym_count >= 1 and has_num_tag)


def _rows_to_html_and_text(rows: list[list[str | None]]) -> tuple[str, str]:
    clean_rows = []
    for row in rows or []:
        if not isinstance(row, list):
            continue
        cells = [clean_invalid_unicode(str(c or '')).strip() for c in row]
        if any(cells):
            clean_rows.append(cells)
    if not clean_rows:
        return '', ''
    html_parts = ['<table>']
    text_lines = []
    for r_idx, cells in enumerate(clean_rows):
        tag = 'th' if r_idx == 0 else 'td'
        row_html = ''.join(f'<{tag}>{html.escape(c)}</{tag}>' for c in cells)
        html_parts.append(f'<tr>{row_html}</tr>')
        text_lines.append('| ' + ' | '.join(cells) + ' |')
    html_parts.append('</table>')
    return ''.join(html_parts), '\n'.join(text_lines)


def _ocr_page_blocks(page, page_idx: int, digest: str, ocr_lang: str) -> tuple[list[dict], str]:
    tesseract_bin = shutil.which('tesseract')
    if not tesseract_bin:
        return [], 'tesseract_not_found'
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return [], 'pytesseract_or_pil_not_installed'

    dpi = 200
    scale = 72.0 / dpi
    pix = page.get_pixmap(dpi=dpi)
    mode = 'RGBA' if pix.alpha else 'RGB'
    pil_img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
    data = pytesseract.image_to_data(pil_img, lang=ocr_lang, output_type=pytesseract.Output.DICT)
    n = len(data.get('text', []))
    grouped: dict[tuple[int, int], list[dict]] = {}
    for i in range(n):
        word = clean_invalid_unicode(str(data['text'][i] or '')).strip()
        if not word:
            continue
        bnum = int(data['block_num'][i])
        pnum = int(data['par_num'][i])
        left = float(data['left'][i]) * scale
        top = float(data['top'][i]) * scale
        width = float(data['width'][i]) * scale
        height = float(data['height'][i]) * scale
        grouped.setdefault((bnum, pnum), []).append({
            'word': word,
            'bbox': [left, top, left + width, top + height],
        })

    items = []
    for _, entries in sorted(grouped.items()):
        text = ' '.join(e['word'] for e in entries).strip()
        if not text or not maybe_is_text(text):
            continue
        x0 = min(e['bbox'][0] for e in entries)
        y0 = min(e['bbox'][1] for e in entries)
        x1 = max(e['bbox'][2] for e in entries)
        y1 = max(e['bbox'][3] for e in entries)
        bbox = [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)]
        items.append({
            'type': 'paragraph',
            'page_idx': page_idx,
            'bbox': bbox,
            'text': text,
            'ocr_used': True,
            'visual_check_required': True,
            'metadata': {
                'source_pdf_sha256': digest,
                'extraction_method': 'tesseract_ocr',
                'entropy': round(shannon_entropy(text), 4),
            },
            'content': {'paragraph_content': [{'content': text}]},
        })
    return items, 'ok'


def _run_external_mineru(pdf_path: Path, max_pages: int) -> dict:
    mineru_bin = shutil.which('mineru')
    if not mineru_bin:
        raise RuntimeError('mineru_cli_not_found')
    raw = pdf_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_dir = Path(tmp_dir)
        # Support MinerU 4.x (`mineru parse <pdf> -o <out> --json`) and legacy (`mineru -p <pdf> -o <out>`)
        cmd = [mineru_bin, 'parse', str(pdf_path), '-o', str(out_dir), '--json']
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            legacy_cmd = [mineru_bin, '-p', str(pdf_path), '-o', str(out_dir)]
            proc2 = subprocess.run(legacy_cmd, capture_output=True, text=True, timeout=300)
            if proc2.returncode != 0:
                detail = (proc.stderr or proc2.stderr or proc.stdout or 'mineru failed').strip()[:500]
                raise RuntimeError(f'mineru_cli_failed:{detail}')
        json_files = sorted(out_dir.rglob('*content_list*.json')) or sorted(out_dir.rglob('*.json'))
        if not json_files:
            raise RuntimeError('mineru_cli_failed:no_json_output')
        payload = json.loads(json_files[0].read_text(encoding='utf-8'))
        if isinstance(payload, list) and all(isinstance(p, list) for p in payload):
            pages = payload
        elif isinstance(payload, list) and all(isinstance(it, dict) for it in payload):
            if not payload:
                pages = []
            else:
                by_page: dict[int, list[dict]] = {}
                for it in payload:
                    raw_pidx = it.get('page_idx', 0)
                    pidx = raw_pidx if isinstance(raw_pidx, int) and not isinstance(raw_pidx, bool) and raw_pidx >= 0 else 0
                    by_page.setdefault(pidx, []).append(it)
                max_pidx = max(by_page)
                pages = [by_page.get(idx, []) for idx in range(max_pidx + 1)]
        elif isinstance(payload, list):
            pages = [payload]
        else:
            pages = []
        pages = pages[:max_pages]
        tables_extracted = 0
        figures_detected = 0
        equations_detected = 0
        for page_items in pages:
            if not isinstance(page_items, list):
                continue
            for item in page_items:
                if not isinstance(item, dict):
                    continue
                kind = str(item.get('type') or '').strip().lower()
                if kind == 'table':
                    tables_extracted += 1
                elif kind in {'image', 'chart', 'figure'}:
                    figures_detected += 1
                elif kind in {'equation', 'equation_interline'}:
                    equations_detected += 1
        return {
            'format': FORMAT,
            'extractor': 'external_mineru_cli',
            'extracted_at_utc': datetime.now(timezone.utc).isoformat(),
            'source_pdf_sha256': digest,
            'source_pdf_bytes': len(raw),
            'total_pages': len(pages),
            'pages_extracted': len(pages),
            'status': 'extracted_mineru_cli',
            'pages_with_little_text_one_based': [],
            'pages_with_image_blocks': [],
            'ocr_pages_one_based': [],
            'ocr_status': 'mineru_cli',
            'tables_extracted': tables_extracted,
            'figures_detected': figures_detected,
            'equations_detected': equations_detected,
            'dropped_low_entropy_blocks': 0,
            'pages': pages,
            'warning': 'Extracted via external mineru CLI. Visually inspect decisive original PDF pages.',
        }


def extract(
    pdf_path,
    max_pages: int = 200,
    *,
    tables: bool = False,
    ocr: bool = False,
    ocr_lang: str = 'eng',
    use_mineru: bool = False,
) -> dict:
    if not isinstance(max_pages, int) or isinstance(max_pages, bool) or not 1 <= max_pages <= 1000:
        raise ValueError('max_pages must be 1..1000')
    raw_path = Path(pdf_path).expanduser()
    if raw_path.is_symlink():
        raise ValueError('input PDF must not be a symlink')
    path = raw_path.resolve()
    if not path.is_file() or path.suffix.lower() != '.pdf':
        raise ValueError('input must be an existing PDF file')
    if path.stat().st_size > 100_000_000:
        raise ValueError('PDF exceeds 100 MB local extraction limit')
    if use_mineru:
        return _run_external_mineru(path, max_pages)
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError('PyMuPDF is required for local PDF extraction') from exc

    pdfplumber_mod = None
    if tables:
        try:
            import pdfplumber as pdfplumber_mod
        except ImportError as exc:
            raise RuntimeError('pdfplumber is required when --tables is enabled') from exc

    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    pages: list[list[dict]] = []
    empty_pages: list[int] = []
    image_counts: list[dict] = []
    ocr_pages: list[int] = []
    ocr_status = 'not_requested'
    tables_extracted = 0
    figures_detected = 0
    equations_detected = 0
    dropped_low_entropy = 0
    plumber_doc = None

    try:
        with fitz.open(path) as document:
            if document.needs_pass:
                raise ValueError('encrypted PDF requires authorized decryption before extraction')
            if pdfplumber_mod is not None:
                plumber_doc = pdfplumber_mod.open(str(path))
            total = len(document)
            for index in range(min(total, max_pages)):
                page = document[index]
                items: list[dict] = []
                table_bboxes: list[list[float]] = []

                # Collect raw text blocks first for caption pairing & prose/equation parsing
                raw_text_blocks: list[tuple[list[float], str]] = []
                image_block_bboxes: list[list[float]] = []
                image_count = 0
                for block in page.get_text('blocks'):
                    if len(block) < 7:
                        continue
                    x0, y0, x1, y1, content, _, kind = block[:7]
                    bbox = [round(float(v), 2) for v in (x0, y0, x1, y1)]
                    if kind != 0:
                        image_count += 1
                        image_block_bboxes.append(bbox)
                        continue
                    if not isinstance(content, str):
                        continue
                    cleaned = clean_invalid_unicode(content).strip()
                    if not cleaned:
                        continue
                    raw_text_blocks.append((bbox, cleaned))

                # 1. Optional pdfplumber tables
                extracted_text_chars = 0
                if plumber_doc is not None and index < len(plumber_doc.pages):
                    p_page = plumber_doc.pages[index]
                    try:
                        found_tables = p_page.find_tables() or []
                    except Exception:
                        found_tables = []
                    for tbl in found_tables:
                        tbbox = [round(float(v), 2) for v in tbl.bbox]
                        rows = tbl.extract() or []
                        tbl_html, tbl_text = _rows_to_html_and_text(rows)
                        if not tbl_text:
                            continue
                        table_bboxes.append(tbbox)
                        # Pair nearest Table N caption
                        best_cap = None
                        best_dist = 70.0
                        for t_bbox, t_str in raw_text_blocks:
                            if TABLE_CAPTION_RE.match(t_str):
                                dist = _rect_distance(tbbox, t_bbox)
                                if dist < best_dist:
                                    best_dist = dist
                                    best_cap = t_str
                        caption_spans = [{'type': 'text', 'content': best_cap}] if best_cap else []
                        full_text = f'{best_cap}\n{tbl_text}'.strip() if best_cap else tbl_text
                        tables_extracted += 1
                        extracted_text_chars += len(tbl_text)
                        items.append({
                            'type': 'table',
                            'page_idx': index,
                            'bbox': tbbox,
                            'text': full_text,
                            'ocr_used': False,
                            'visual_check_required': True,
                            'metadata': {
                                'source_pdf_sha256': digest,
                                'extraction_method': 'pdfplumber_table',
                                'entropy': round(shannon_entropy(full_text), 4),
                            },
                            'content': {
                                'table_caption': caption_spans,
                                'html': tbl_html,
                                'rows': rows,
                            },
                        })

                # 2. Text / equation blocks (excluding cell blocks inside detected table bboxes)
                for bbox, cleaned in raw_text_blocks:
                    cx, cy = _bbox_center(bbox)
                    if any(_point_in_bbox(cx, cy, tb) for tb in table_bboxes):
                        continue
                    if not maybe_is_text(cleaned):
                        dropped_low_entropy += 1
                        continue
                    if _looks_like_equation(cleaned):
                        equations_detected += 1
                        extracted_text_chars += len(cleaned)
                        items.append({
                            'type': 'equation',
                            'page_idx': index,
                            'bbox': bbox,
                            'text': cleaned,
                            'ocr_used': False,
                            'visual_check_required': True,
                            'metadata': {
                                'source_pdf_sha256': digest,
                                'extraction_method': 'pymupdf_equation_heuristic',
                                'entropy': round(shannon_entropy(cleaned), 4),
                            },
                            'content': {'math_content': cleaned, 'math_type': 'heuristic_text'},
                        })
                    else:
                        extracted_text_chars += len(cleaned)
                        items.append({
                            'type': 'paragraph',
                            'page_idx': index,
                            'bbox': bbox,
                            'text': cleaned,
                            'ocr_used': False,
                            'visual_check_required': True,
                            'metadata': {
                                'source_pdf_sha256': digest,
                                'extraction_method': 'pymupdf_text_block',
                                'entropy': round(shannon_entropy(cleaned), 4),
                            },
                            'content': {'paragraph_content': [{'content': cleaned}]},
                        })

                # 3. Clean-room figure/image detection (images + non-table drawing clusters)
                candidate_fig_boxes: list[list[float]] = []
                try:
                    for info in page.get_image_info(xrefs=True) or []:
                        ib = info.get('bbox')
                        if ib and len(ib) == 4:
                            box = [round(float(v), 2) for v in ib]
                            if (box[2] - box[0]) >= 20 and (box[3] - box[1]) >= 20:
                                candidate_fig_boxes.append(box)
                except Exception:
                    pass
                for ib in image_block_bboxes:
                    if (ib[2] - ib[0]) >= 20 and (ib[3] - ib[1]) >= 20:
                        if not any(_overlap_min_ratio(ib, existing) >= 0.5 for existing in candidate_fig_boxes):
                            candidate_fig_boxes.append(ib)
                try:
                    for rect in page.cluster_drawings(x_tolerance=25, y_tolerance=25) or []:
                        box = [round(float(v), 2) for v in (rect.x0, rect.y0, rect.x1, rect.y1)]
                        if (box[2] - box[0]) < 20 or (box[3] - box[1]) < 20:
                            continue
                        if any(_overlap_min_ratio(box, tb) >= 0.5 for tb in table_bboxes):
                            continue
                        if not any(_overlap_min_ratio(box, existing) >= 0.5 for existing in candidate_fig_boxes):
                            candidate_fig_boxes.append(box)
                except Exception:
                    pass

                for fbox in candidate_fig_boxes:
                    best_cap = None
                    best_dist = 80.0
                    for t_bbox, t_str in raw_text_blocks:
                        if FIG_CAPTION_RE.match(t_str):
                            dist = _rect_distance(fbox, t_bbox)
                            if dist < best_dist:
                                best_dist = dist
                                best_cap = t_str
                    caption_spans = [{'type': 'text', 'content': best_cap}] if best_cap else []
                    fig_text = best_cap or f'[Image/figure region on page {index + 1}]'
                    figures_detected += 1
                    items.append({
                        'type': 'image',
                        'page_idx': index,
                        'bbox': fbox,
                        'text': fig_text,
                        'ocr_used': False,
                        'visual_check_required': True,
                        'metadata': {
                            'source_pdf_sha256': digest,
                            'extraction_method': 'pymupdf_figure_region',
                            'entropy': round(shannon_entropy(fig_text), 4),
                        },
                        'content': {
                            'image_caption': caption_spans,
                            'image_footnote': [],
                            'image_source': {'path': ''},
                        },
                    })

                # 4. OCR fallback on low-text pages when --ocr enabled
                if extracted_text_chars < 50:
                    if ocr:
                        ocr_items, status_str = _ocr_page_blocks(page, index, digest, ocr_lang)
                        ocr_status = status_str
                        if ocr_items:
                            items.extend(ocr_items)
                            ocr_pages.append(index + 1)
                            extracted_text_chars += sum(len(it['text']) for it in ocr_items)
                    if extracted_text_chars < 50:
                        empty_pages.append(index + 1)

                # Sort items top-to-bottom, left-to-right for readable order
                items.sort(key=lambda it: (it['bbox'][1], it['bbox'][0]))
                pages.append(items)
                if image_count or candidate_fig_boxes:
                    image_counts.append({
                        'page_one_based': index + 1,
                        'image_blocks': max(image_count, len(candidate_fig_boxes)),
                    })
    except (RuntimeError, ValueError):
        raise
    except Exception as exc:
        raise RuntimeError(f'pdf_extraction_failure:{type(exc).__name__}') from exc
    finally:
        if plumber_doc is not None:
            try:
                plumber_doc.close()
            except Exception:
                pass

    return {
        'format': FORMAT,
        'extractor': f'PyMuPDF {getattr(fitz, "VersionBind", "unknown")}',
        'extracted_at_utc': datetime.now(timezone.utc).isoformat(),
        'source_pdf_sha256': digest,
        'source_pdf_bytes': len(raw),
        'total_pages': total,
        'pages_extracted': len(pages),
        'status': 'bounded_partial' if len(pages) < total else 'extracted_text_blocks',
        'pages_with_little_text_one_based': empty_pages,
        'pages_with_image_blocks': image_counts,
        'ocr_pages_one_based': ocr_pages,
        'ocr_status': ocr_status,
        'tables_extracted': tables_extracted,
        'figures_detected': figures_detected,
        'equations_detected': equations_detected,
        'dropped_low_entropy_blocks': dropped_low_entropy,
        'pages': pages,
        'warning': (
            'Local PyMuPDF/pdfplumber/tesseract extraction lead. Tables, equations, figures, OCR spans, '
            'and reading order carry visual_check_required=True; inspect decisive original PDF pages before citing.'
        ),
    }


def _auto_artifact_path(prefix: str) -> Path:
    art_dir = Path(tempfile.gettempdir()) / 'research_scientist_artifacts'
    art_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f'{prefix}_', suffix='.json', dir=str(art_dir))
    os.close(fd)
    return Path(tmp_name).resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf')
    parser.add_argument('--out', '--output', dest='output', type=Path, help='Output JSON path (required unless --compact is used)')
    parser.add_argument('--max-pages', type=int, default=200)
    parser.add_argument('--tables', action='store_true', help='Enable pdfplumber table extraction')
    parser.add_argument('--ocr', action='store_true', help='Enable tesseract OCR fallback on low-text pages')
    parser.add_argument('--ocr-lang', default='eng', help='Tesseract OCR language (default: eng)')
    parser.add_argument('--use-mineru', action='store_true', help='Invoke external mineru CLI if installed on PATH')
    parser.add_argument('--v2-only', action='store_true', help='Write bare MinerU Content List V2 pages list to --out')
    parser.add_argument('--overwrite', action='store_true', help='Allow overwriting existing output file')
    parser.add_argument('--compact', action='store_true', help='Write full blocks JSON to --out (or auto-artifact) and print compact stdout JSON')
    args = parser.parse_args()
    if args.output is None and not args.compact:
        parser.error('the following arguments are required: --out/--output (unless --compact is specified)')
    try:
        if args.output is not None:
            raw_out = args.output.expanduser()
            if raw_out.is_symlink():
                raise ValueError('output path must not be a symlink')
            destination = raw_out.resolve()
            if not args.overwrite and raw_out.exists():
                raise ValueError('output exists; refusing to overwrite')
            if not destination.parent.is_dir():
                raise ValueError('output parent directory does not exist')
        else:
            destination = None
        report = extract(
            args.pdf,
            args.max_pages,
            tables=args.tables,
            ocr=args.ocr,
            ocr_lang=args.ocr_lang,
            use_mineru=args.use_mineru,
        )
        auto_created = False
        if destination is None:
            destination = _auto_artifact_path('extract_pdf_blocks')
            auto_created = True
        payload = report['pages'] if args.v2_only else report
        mode = 'w' if (args.overwrite or auto_created) else 'x'
        with destination.open(mode, encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False)
        if args.compact:
            compact = {
                'compact': True,
                'artifact_path': str(destination),
                'status': report['status'],
                'pages_extracted': report['pages_extracted'],
                'total_pages': report['total_pages'],
                'tables_extracted': report['tables_extracted'],
                'figures_detected': report['figures_detected'],
                'equations_detected': report['equations_detected'],
                'ocr_pages_one_based': report['ocr_pages_one_based'],
                'dropped_low_entropy_blocks': report['dropped_low_entropy_blocks'],
                'source_pdf_sha256': report['source_pdf_sha256'],
            }
            print(json.dumps(compact, ensure_ascii=False, separators=(',', ':')))
        else:
            print(json.dumps({key: value for key, value in report.items() if key != 'pages'}, ensure_ascii=False))
        return 0
    except RuntimeError as exc:
        msg = str(exc)
        status = 'mineru_cli_not_found' if msg == 'mineru_cli_not_found' else 'extraction_error'
        print(json.dumps({'error': msg, 'status': status}), file=sys.stderr)
        return 2
    except (ValueError, OSError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
