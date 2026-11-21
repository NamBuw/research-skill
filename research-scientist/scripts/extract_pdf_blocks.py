#!/usr/bin/env python3
"""Extract inspectable PDF text blocks locally with PyMuPDF; no OCR or truth check."""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

FORMAT = 'research_scientist_pdf_blocks_v1'

def extract(pdf_path, max_pages=200):
    if not isinstance(max_pages, int) or isinstance(max_pages, bool) or not 1 <= max_pages <= 1000:
        raise ValueError('max_pages must be 1..1000')
    path = Path(pdf_path).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() != '.pdf':
        raise ValueError('input must be an existing PDF file')
    if path.stat().st_size > 100_000_000:
        raise ValueError('PDF exceeds 100 MB local extraction limit')
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError('PyMuPDF is required for local PDF extraction') from exc
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    pages, empty_pages, image_counts = [], [], []
    try:
        with fitz.open(path) as document:
            if document.needs_pass:
                raise ValueError('encrypted PDF requires authorized decryption before extraction')
            total = len(document)
            for index in range(min(total, max_pages)):
                page = document[index]
                items, image_count = [], 0
                for block in page.get_text('blocks'):
                    if len(block) < 7:
                        continue
                    x0, y0, x1, y1, content, _, kind = block[:7]
                    if kind != 0:
                        image_count += 1
                        continue
                    if not isinstance(content, str) or not content.strip():
                        continue
                    items.append({'type': 'paragraph', 'page_idx': index, 'visual_check_required': True,
                                  'bbox': [round(float(x), 2) for x in (x0, y0, x1, y1)],
                                  'content': {'paragraph_content': [{'content': content.strip()}]}})
                pages.append(items)
                if sum(len(item['content']['paragraph_content'][0]['content']) for item in items) < 50:
                    empty_pages.append(index + 1)
                if image_count:
                    image_counts.append({'page_one_based': index + 1, 'image_blocks': image_count})
    except (RuntimeError, ValueError):
        raise
    except Exception as exc:
        raise RuntimeError(f'pdf_extraction_failure:{type(exc).__name__}') from exc
    return {'format': FORMAT, 'extractor': f'PyMuPDF {getattr(fitz, "VersionBind", "unknown")}',
            'extracted_at_utc': datetime.now(timezone.utc).isoformat(),
            'source_pdf_sha256': digest, 'source_pdf_bytes': len(raw),
            'total_pages': total, 'pages_extracted': len(pages),
            'status': 'bounded_partial' if len(pages) < total else 'extracted_text_blocks',
            'pages_with_little_text_one_based': empty_pages,
            'pages_with_image_blocks': image_counts,
            'pages': pages,
            'warning': ('Text-block extraction only. Scans may require OCR; reading order, tables, equations, '
                        'footnotes and images may be wrong or absent. Visually inspect decisive original PDF pages. '
                        'This file is an extraction lead, not a verified paper or MinerU output.')}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--max-pages', type=int, default=200)
    args = parser.parse_args()
    try:
        destination = args.output.expanduser().resolve()
        if args.output.exists() or args.output.is_symlink():
            raise ValueError('output exists; refusing to overwrite')
        if not destination.parent.is_dir():
            raise ValueError('output parent directory does not exist')
        report = extract(args.pdf, args.max_pages)
        with destination.open('x', encoding='utf-8') as handle:
            json.dump(report, handle, ensure_ascii=False)
        print(json.dumps({key: value for key, value in report.items() if key != 'pages'}, ensure_ascii=False))
    except (ValueError, RuntimeError, OSError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        sys.exit(2)
