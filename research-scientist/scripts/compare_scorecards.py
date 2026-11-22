#!/usr/bin/env python3
"""Check scorecard completeness and ranking sensitivity under declared weights."""
import argparse
import hashlib
import html
import json
import math
import re
import sys
import unicodedata
from decimal import BasicContext, Decimal, ROUND_HALF_UP, localcontext
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from score_math import (
    DEFAULT_IDEA_WEIGHTS,
    DIMENSIONS,
    FATAL_THRESHOLDS,
    HEX64_RE,
    IDEA_DIMENSIONS,
    IDEA_FATAL_THRESHOLDS,
    SUBFIELD_PRESETS,
    VENUE_TYPE_PROFILES,
    build_evidence_anchor_table,
    compute_deal_breaker_sensitivity,
    compute_merit_vs_packaging,
    detect_halo_sanity_warnings,
    diff_scorecards,
    evaluate_subfield_readiness,
    evaluate_venue_profile_checks,
    resolve_venue_type,
    score,
    score_section_diagnostics,
    simulate_reviewer_panel,
    simulate_what_if_roi,
    translate_to_native_scales,
)

IDEA_GOAL_MODES = ('safe_fast_publish', 'high_risk_q1_top_tier', 'low_compute_constrained')
_CANONICAL_PORTFOLIO_ANGLE = {
    'minimal_fix': 'minimal_fix',
    'minimal_fix_f19': 'minimal_fix',
    'high_novelty_mechanism': 'high_novelty_mechanism',
    'high_novelty_mechanism_q1': 'high_novelty_mechanism',
    'benchmark_diagnostic_analysis': 'benchmark_diagnostic_analysis',
    'low_gpu_fallback': 'low_gpu_fallback',
}
_ROOT_CAUSE_BARRIERS = {'theoretical_limit', 'measurement_gap', 'data_supervision_gap', 'compute_infra_barrier'}
_SO_WHAT_IMPACTS = {'decision_changing', 'marginal_gain'}
_DURABILITY_LEVELS = {'durable_structural_limit', 'high_scaling_erasure_risk'}

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover - environment dependent
    fitz = None

try:
    import pdfplumber
except ImportError:  # pragma: no cover - optional table supplement
    pdfplumber = None

SOURCE_EXTENSIONS = {'.txt', '.md', '.json', '.pdf'}
VENUE_FAILURE_STATUSES = {
    'fetch_failed',
    'pdf_extractor_unavailable',
    'pdf_extraction_failed',
    'unsupported_content_type',
    'no_extractable_text',
    'unverified_dynamic_page',
    'js_rendered_suspected',
    'stale_redirect',
    'bot_blocked_anubis',
    'bot_blocked',
    'rate_limited',
    'unreachable',
    'source_failed',
}


def _normalized(value):
    return re.sub(r'\s+', ' ', str(value)).strip()


def _contains_exact_quote(text, quote):
    quote = _normalized(quote)
    if not quote:
        return False
    left = r'(?<!\w)' if quote[0].isalnum() else ''
    right = r'(?!\w)' if quote[-1].isalnum() else ''
    return re.search(left + re.escape(quote) + right, _normalized(text)) is not None


def _spans(value):
    if not isinstance(value, list):
        return ''
    return ''.join(
        item.get('content', '')
        for item in value
        if isinstance(item, dict) and isinstance(item.get('content'), str)
    )


def _v2_text(item):
    content = item.get('content')
    if not isinstance(content, dict):
        return ''
    kind = item.get('type')
    if kind == 'paragraph':
        return _spans(content.get('paragraph_content'))
    if kind == 'title':
        return _spans(content.get('title_content'))
    if kind == 'page_footnote':
        return _spans(content.get('page_footnote_content'))
    if kind in ('equation', 'equation_interline'):
        for key in ('math_content', 'latex', 'text', 'content'):
            val = content.get(key)
            if isinstance(val, str) and val.strip():
                return val
        return ''
    if kind == 'list':
        return ' '.join(
            _spans(x.get('item_content'))
            for x in content.get('list_items', [])
            if isinstance(x, dict)
        )
    if kind == 'table':
        parts = [_spans(content.get('table_caption')), _spans(content.get('table_footnote'))]
        html_source = content.get('html')
        if isinstance(html_source, str):
            parts.append(re.sub(r'<[^>]+>', ' ', html_source))
        return ' '.join(parts)
    if kind in {'image', 'chart'}:
        return ' '.join(_spans(content.get(f'{kind}_{suffix}')) for suffix in ('caption', 'footnote'))
    if kind in {'algorithm', 'code'}:
        key = 'algorithm_content' if kind == 'algorithm' else 'code_content'
        return _spans(content.get(key))
    return ''


def _extract_mineru_pages(payload):
    if isinstance(payload, dict) and payload.get('format') == 'research_scientist_pdf_blocks_v1':
        payload = payload.get('pages')
    if not isinstance(payload, list):
        return None
    if payload and all(isinstance(x, dict) for x in payload):
        pages = [payload]
        flat = True
    elif all(isinstance(page, list) for page in payload):
        pages = payload
        flat = False
    else:
        return None

    page_chunks = {}
    max_page = 0
    for page_number, page in enumerate(pages, start=1):
        for item in page:
            if not isinstance(item, dict):
                continue
            text = html.unescape(_v2_text(item)).strip()
            if not text:
                continue
            raw_idx = item.get('page_idx') if flat else item.get('page_idx', page_number - 1)
            page_num = raw_idx + 1 if isinstance(raw_idx, int) and raw_idx >= 0 else page_number
            max_page = max(max_page, page_num)
            page_chunks.setdefault(page_num, []).append(text)
    if not page_chunks:
        return None
    pages_norm = {p: _normalized(' '.join(chunks)) for p, chunks in page_chunks.items()}
    return pages_norm, max(max_page, len(pages) if not flat else max_page)


def _extract_pdf_pages(path):
    if fitz is None:
        raise RuntimeError('PyMuPDF (fitz) is required to verify .pdf sources')
    pages_raw = {}
    pdf_errors = (RuntimeError, ValueError)
    file_data_err = getattr(fitz, 'FileDataError', None)
    if isinstance(file_data_err, type) and issubclass(file_data_err, BaseException):
        pdf_errors = (RuntimeError, ValueError, file_data_err)
    try:
        doc = fitz.open(str(path))
    except pdf_errors as exc:
        raise ValueError(f'Corrupt or unreadable PDF ({path.name}): {exc}') from exc
    try:
        if not getattr(doc, 'is_pdf', True):
            raise ValueError(f'Not a valid PDF ({path.name})')
        if doc.needs_pass:
            raise ValueError(f'Encrypted PDF cannot be verified: {path.name}')
        num_pages = len(doc)
        for idx in range(num_pages):
            page_num = idx + 1
            text = doc[idx].get_text('text') or ''
            pages_raw[page_num] = [text]
    except pdf_errors as exc:
        if isinstance(exc, ValueError) and str(exc).startswith(('Not a valid PDF', 'Encrypted PDF')):
            raise
        raise ValueError(f'Corrupt or unreadable PDF ({path.name}): {exc}') from exc
    finally:
        doc.close()

    if pdfplumber is not None:
        try:
            with pdfplumber.open(str(path)) as plumber_doc:
                for idx, p_page in enumerate(plumber_doc.pages):
                    page_num = idx + 1
                    if page_num not in pages_raw:
                        continue
                    tables = p_page.extract_tables() or []
                    for table in tables:
                        for row in table or []:
                            if row:
                                row_text = ' '.join(str(cell) for cell in row if cell)
                                if row_text.strip():
                                    pages_raw[page_num].append(row_text)
        except Exception:
            pass

    pages_norm = {p: _normalized(' '.join(parts)) for p, parts in pages_raw.items()}
    return pages_norm, num_pages


def index_sources_dir(sources_dir):
    if not isinstance(sources_dir, (str, Path)) or not str(sources_dir).strip():
        raise ValueError('sources_dir must be a nonblank directory path')
    root = Path(sources_dir).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f'sources directory not found: {sources_dir}')

    paper_sources = []
    venue_snapshots = {}
    skipped_files = []
    by_key = {}

    def _register_keys(entry, rel_posix, path_obj):
        for key in (
            rel_posix,
            rel_posix.lower(),
            path_obj.name,
            path_obj.name.lower(),
            path_obj.stem,
            path_obj.stem.lower(),
        ):
            if key:
                by_key.setdefault(key, []).append(entry)

    for path in sorted(root.rglob('*')):
        rel_posix = path.relative_to(root).as_posix()
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            skipped_files.append({'path': rel_posix, 'reason': 'broken_symlink'})
            continue
        if not resolved.is_relative_to(root):
            skipped_files.append({'path': rel_posix, 'reason': 'symlink_outside_sources_dir'})
            continue
        if not resolved.is_file():
            continue
        suffix = resolved.suffix.lower()
        if suffix not in SOURCE_EXTENSIONS:
            continue
        try:
            if suffix in {'.txt', '.md'}:
                raw_text = resolved.read_text(encoding='utf-8')
                lines = raw_text.splitlines()
                full_text = _normalized(raw_text)
                if not full_text:
                    skipped_files.append({'path': rel_posix, 'reason': 'empty_text'})
                    continue
                entry = {
                    'rel_path': rel_posix,
                    'name': path.name,
                    'stem': path.stem,
                    'kind': 'text',
                    'lines': lines,
                    'full_text': full_text,
                }
                paper_sources.append(entry)
                _register_keys(entry, rel_posix, path)
            elif suffix == '.json':
                payload = json.loads(resolved.read_text(encoding='utf-8'))
                if isinstance(payload, dict) and payload.get('format') == 'research_scientist_venue_sources_v1':
                    sources_list = payload.get('sources')
                    if not isinstance(sources_list, list):
                        skipped_files.append({'path': rel_posix, 'reason': 'invalid_venue_bundle'})
                        continue
                    bundle_texts = []
                    for snap in sources_list:
                        if not isinstance(snap, dict):
                            continue
                        snap_text = _normalized(snap.get('text', '')) if isinstance(snap.get('text'), str) else ''
                        snap_record = {
                            'requested_url': snap.get('requested_url'),
                            'final_url': snap.get('final_url'),
                            'text': snap_text,
                            'extraction_status': snap.get('extraction_status', ''),
                            'same_host_path_redirect_year_mismatch': bool(
                                snap.get('same_host_path_redirect_year_mismatch')
                            ),
                            'js_rendered_suspected': bool(snap.get('js_rendered_suspected')),
                            'unverified_dynamic_page': bool(snap.get('unverified_dynamic_page')),
                            'rel_path': rel_posix,
                        }
                        for url_key in (snap.get('requested_url'), snap.get('final_url')):
                            if isinstance(url_key, str) and url_key.strip():
                                venue_snapshots[url_key.strip()] = snap_record
                        if snap_text and not _snapshot_is_blocked(snap_record):
                            bundle_texts.append(snap_text)
                    if bundle_texts:
                        entry = {
                            'rel_path': rel_posix,
                            'name': path.name,
                            'stem': path.stem,
                            'kind': 'venue_bundle',
                            'full_text': _normalized(' '.join(bundle_texts)),
                        }
                        _register_keys(entry, rel_posix, path)
                else:
                    extracted = _extract_mineru_pages(payload)
                    if extracted is None:
                        skipped_files.append({'path': rel_posix, 'reason': 'unrecognized_json_schema'})
                        continue
                    pages_norm, num_pages = extracted
                    full_text = _normalized(' '.join(pages_norm[p] for p in sorted(pages_norm)))
                    entry = {
                        'rel_path': rel_posix,
                        'name': path.name,
                        'stem': path.stem,
                        'kind': 'pages',
                        'pages': pages_norm,
                        'num_pages': num_pages,
                        'full_text': full_text,
                    }
                    paper_sources.append(entry)
                    _register_keys(entry, rel_posix, path)
            elif suffix == '.pdf':
                pages_norm, num_pages = _extract_pdf_pages(resolved)
                full_text = _normalized(' '.join(pages_norm[p] for p in sorted(pages_norm)))
                if not full_text:
                    skipped_files.append({'path': rel_posix, 'reason': 'empty_pdf_text'})
                    continue
                entry = {
                    'rel_path': rel_posix,
                    'name': path.name,
                    'stem': path.stem,
                    'kind': 'pages',
                    'pages': pages_norm,
                    'num_pages': num_pages,
                    'full_text': full_text,
                }
                paper_sources.append(entry)
                _register_keys(entry, rel_posix, path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            skipped_files.append({'path': rel_posix, 'reason': type(exc).__name__})

    sources_indexed = len(paper_sources) + len(venue_snapshots)
    if sources_indexed == 0:
        raise ValueError(f'sources directory contains no readable .txt/.md/.json/.pdf sources: {sources_dir}')
    return {
        'root': root,
        'paper_sources': paper_sources,
        'venue_snapshots': venue_snapshots,
        'by_key': by_key,
        'sources_indexed': sources_indexed,
        'skipped_files': skipped_files,
    }


def _parse_anchors(text):
    matched_spans = []
    page_range = None
    line_range = None

    page_patterns = (
        re.compile(r'#page=(\d+)(?:\s*[-\u2013]\s*(\d+))?', re.IGNORECASE),
        re.compile(r'\bpages?\s+(\d+)(?:\s*[-\u2013]\s*(\d+))?\b', re.IGNORECASE),
        re.compile(r'\bp\.?\s*(\d+)(?:\s*[-\u2013]\s*(\d+))?\b', re.IGNORECASE),
        re.compile(r'\bpage_idx\s*[:=]\s*(\d+)(?:\s*[-\u2013]\s*(\d+))?\b', re.IGNORECASE),
    )
    for idx, pat in enumerate(page_patterns):
        match = pat.search(text)
        if match:
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else start
            if idx == 3:
                start += 1
                end += 1
            page_range = (start, end)
            matched_spans.append(match.group(0))
            break

    line_patterns = (
        re.compile(r'#L(\d+)(?:-L?(\d+))?', re.IGNORECASE),
        re.compile(r'\blines?\s+(\d+)(?:\s*[-\u2013]\s*(\d+))?\b', re.IGNORECASE),
        re.compile(r'\.(?:txt|md|json|pdf)(:(\d+)(?:-(\d+))?)(?=\s|$|:|,)', re.IGNORECASE),
    )
    for idx, pat in enumerate(line_patterns):
        match = pat.search(text)
        if match:
            if idx == 2:
                start = int(match.group(2))
                end = int(match.group(3)) if match.group(3) else start
                matched_spans.append(match.group(1))
            else:
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else start
                matched_spans.append(match.group(0))
            line_range = (start, end)
            break

    return page_range, line_range, matched_spans


_QUOTE_SPAN_RE = re.compile(
    r'"([^"]*)"|«([^»]*)»|`([^`]*)`|(?<!\w)\'([^\']*)\'(?!\w)'
)


def _extract_quotes(text):
    quotes = []
    for match in _QUOTE_SPAN_RE.finditer(text):
        candidate = next((g for g in match.groups() if g is not None), '')
        if len(_normalized(candidate)) >= 3:
            quotes.append(candidate)
    return quotes


_FILE_TOKEN_RE = re.compile(r'([\w./-]+\.(?:pdf|json|md|txt))', flags=re.IGNORECASE)
_TRAVERSAL_TAIL = r'(?:$|[^\w.-])'
_URI_OR_SUBPATH_STARTER = (
    r'(?:file:|\.\.' + _TRAVERSAL_TAIL + r'|~[/\\]|[A-Za-z]:[/\\]|\\\\)'
)
_URI_OR_PATH_STARTER = (
    r'(?:/(?!\s)|' + _URI_OR_SUBPATH_STARTER + r')'
)
_URL_MASK_RE = re.compile(
    r'https?://(?!' + _URI_OR_PATH_STARTER + r')'
    r'(?:(?![<>{}|\\^`"\[\];\s?#])'
    r'(?!/' + _URI_OR_PATH_STARTER + r')'
    r'(?![^\w./-]' + _URI_OR_PATH_STARTER + r').)+'
    r'(?:[?#](?!' + _URI_OR_PATH_STARTER + r')'
    r'(?:(?![<>{}|\\^`"\[\];\s])'
    r'(?!/' + _URI_OR_SUBPATH_STARTER + r')'
    r'(?![^\w./=-]' + _URI_OR_PATH_STARTER + r')'
    r'(?!=' + _URI_OR_SUBPATH_STARTER + r').)*)?',
    re.IGNORECASE,
)
_UNSAFE_DELIM = r'[^\w.-]'


def _strip_quoted_spans(text):
    return _QUOTE_SPAN_RE.sub(' ', text)


def _snapshot_is_blocked(snap):
    if snap.get('same_host_path_redirect_year_mismatch'):
        return True
    if snap.get('js_rendered_suspected') or snap.get('unverified_dynamic_page'):
        return True
    ext_status = str(snap.get('extraction_status') or '').strip().lower()
    if ext_status in VENUE_FAILURE_STATUSES or ext_status.startswith(('bot_blocked', 'http_', 'network_', 'stale_', 'unverified_')):
        return True
    if not snap.get('text'):
        return True
    return False


def verify_locator(locator, index, default_source_ids=(), source_url=None, extra_quotes=(), require_url_snapshot=False):
    dict_quotes = []
    struct_page_range = None
    struct_line_range = None
    if isinstance(locator, dict):
        for int_key in ('page', 'line_start', 'line_end'):
            if int_key in locator and locator[int_key] is not None:
                if type(locator[int_key]) is not int:
                    return False, f'invalid_{int_key}_type'
                if locator[int_key] < 1:
                    return False, 'anchor_out_of_bounds'
        if locator.get('line_end') is not None and locator.get('line_start') is None:
            return False, 'anchor_out_of_bounds'
        if (
            type(locator.get('line_start')) is int
            and type(locator.get('line_end')) is int
            and locator['line_end'] < locator['line_start']
        ):
            return False, 'anchor_out_of_bounds'
        if type(locator.get('page')) is int:
            struct_page_range = (locator['page'], locator['page'])
        if type(locator.get('line_start')) is int:
            end_line = locator['line_end'] if type(locator.get('line_end')) is int else locator['line_start']
            struct_line_range = (locator['line_start'], end_line)
        if 'quote' in locator and locator['quote'] is not None:
            raw_quote = locator['quote']
            if not isinstance(raw_quote, str):
                return False, 'invalid_quote_type'
            if '\x00' in raw_quote:
                return False, 'unsafe_source_path'
            norm_quote = _normalized(raw_quote)
            if not norm_quote:
                return False, 'blank_quote'
            if len(norm_quote) < 3:
                return False, 'quote_too_short'
            dict_quotes.append(raw_quote)
        parts = []
        if isinstance(locator.get('source'), str):
            parts.append(locator['source'])
        for text_key in ('locator', 'text', 'section', 'table', 'figure'):
            val = locator.get(text_key)
            if isinstance(val, str) and val.strip():
                parts.append(val)
        text = ' '.join(parts).strip()
    elif isinstance(locator, str):
        text = locator.strip()
    else:
        return False, 'invalid_locator_type'

    if not text and not dict_quotes and struct_page_range is None and struct_line_range is None:
        return False, 'blank_locator'
    if '\x00' in text:
        return False, 'unsafe_source_path'

    unquoted_text = _strip_quoted_spans(text)
    if any(
        unicodedata.category(ch) == 'Cf'
        or (unicodedata.category(ch) == 'Cc' and ch not in '\t\n\r')
        for ch in unquoted_text
    ):
        return False, 'unsafe_source_path'
    path_check_text = _URL_MASK_RE.sub(' ', unquoted_text)
    if re.search(rf'(?:^|{_UNSAFE_DELIM})\.\.{_TRAVERSAL_TAIL}', path_check_text):
        return False, 'unsafe_source_path'
    if re.search(rf'(?:^|{_UNSAFE_DELIM})(?:/(?!\s)|~[/\\]|[A-Za-z]:[/\\]|\\\\)', path_check_text):
        return False, 'unsafe_source_path'
    if re.search(rf'(?:^|{_UNSAFE_DELIM})file:', path_check_text, re.IGNORECASE):
        return False, 'unsafe_source_path'

    explicit_files = _FILE_TOKEN_RE.findall(path_check_text)
    candidates = None

    if explicit_files:
        matched = []
        for fname in explicit_files:
            if fname.startswith('/') or '\\' in fname:
                return False, 'unsafe_source_path'
            cleaned = fname
            while cleaned.startswith('./'):
                cleaned = cleaned[2:]
            hits = index['by_key'].get(cleaned) or index['by_key'].get(cleaned.lower())
            if not hits and '/' not in cleaned:
                hits = index['by_key'].get(cleaned.lower())
            if not hits:
                return False, 'source_not_found'
            for entry in hits:
                if entry not in matched:
                    matched.append(entry)
        candidates = matched

    if require_url_snapshot:
        if not source_url or source_url not in index['venue_snapshots']:
            return False, 'source_snapshot_missing'
        snap = index['venue_snapshots'][source_url]
        if _snapshot_is_blocked(snap):
            return False, 'unverified_or_stale_venue_snapshot'
        if explicit_files and any(c.get('rel_path') != snap['rel_path'] for c in (candidates or [])):
            return False, 'source_snapshot_mismatch'
        candidates = [{
            'rel_path': snap['rel_path'],
            'name': source_url,
            'kind': 'venue_snapshot',
            'full_text': snap['text'],
        }]
    elif source_url:
        if source_url in index['venue_snapshots']:
            snap = index['venue_snapshots'][source_url]
            if _snapshot_is_blocked(snap):
                return False, 'unverified_or_stale_venue_snapshot'
            if candidates is None:
                candidates = [{
                    'rel_path': snap['rel_path'],
                    'name': source_url,
                    'kind': 'venue_snapshot',
                    'full_text': snap['text'],
                }]

    if candidates is None:
        id_matched = []
        has_nonblank_default_id = False
        for sid in default_source_ids:
            if not isinstance(sid, str) or not sid.strip():
                continue
            has_nonblank_default_id = True
            sid_clean = sid.strip()
            hits = index['by_key'].get(sid_clean) or index['by_key'].get(sid_clean.lower())
            if hits:
                for entry in hits:
                    if entry not in id_matched:
                        id_matched.append(entry)
        if id_matched:
            candidates = id_matched
        elif has_nonblank_default_id:
            return False, 'source_not_scoped'
        else:
            candidates = list(index['paper_sources'])

    if not candidates:
        return False, 'source_not_found'

    anchor_text = _FILE_TOKEN_RE.sub(lambda m: '_FILE_' + Path(m.group(1)).suffix, path_check_text)
    parsed_page_range, parsed_line_range, anchor_spans = _parse_anchors(anchor_text)
    if struct_page_range is not None:
        if parsed_page_range is not None and parsed_page_range != struct_page_range:
            return False, 'anchor_out_of_bounds'
        page_range = struct_page_range
    else:
        page_range = parsed_page_range
    if struct_line_range is not None:
        if parsed_line_range is not None and parsed_line_range != struct_line_range:
            return False, 'anchor_out_of_bounds'
        line_range = struct_line_range
    else:
        line_range = parsed_line_range
    if page_range and (page_range[0] < 1 or page_range[1] < page_range[0]):
        return False, 'anchor_out_of_bounds'
    if line_range and (line_range[0] < 1 or line_range[1] < line_range[0]):
        return False, 'anchor_out_of_bounds'

    in_bounds_windows = []
    for entry in candidates:
        window = entry['full_text']
        if page_range is not None:
            if entry['kind'] != 'pages':
                continue
            start_p, end_p = page_range
            if end_p > entry['num_pages']:
                continue
            page_texts = [entry['pages'][p] for p in range(start_p, end_p + 1) if p in entry['pages']]
            window = _normalized(' '.join(page_texts))
            if not window:
                continue
        if line_range is not None:
            if entry['kind'] != 'text':
                continue
            start_l, end_l = line_range
            if end_l > len(entry['lines']):
                continue
            window = _normalized(' '.join(entry['lines'][start_l - 1:end_l]))
            if not window:
                continue
        in_bounds_windows.append(window)

    if not in_bounds_windows:
        return False, 'anchor_out_of_bounds'

    inline_quotes = _extract_quotes(text)
    quotes = list(dict_quotes) + list(inline_quotes)
    extra_list = [eq for eq in extra_quotes if isinstance(eq, str) and len(_normalized(eq)) >= 3]
    quotes.extend(extra_list)

    residual = path_check_text
    residual = _FILE_TOKEN_RE.sub(' ', residual)
    for span in anchor_spans:
        residual = residual.replace(span, ' ', 1)
    residual = re.sub(r'^[\s:;,|\-]+|[\s:;,|\-]+$', '', residual)
    residual = _normalized(residual)

    if quotes:
        matched_quote_only = False
        for window in in_bounds_windows:
            if all(_contains_exact_quote(window, q) for q in quotes):
                if not inline_quotes and not dict_quotes and extra_list and residual:
                    if _contains_exact_quote(window, residual):
                        return True, 'verified'
                    matched_quote_only = True
                    continue
                return True, 'verified'
        return False, ('text_not_found' if matched_quote_only else 'quote_not_found')

    if not residual:
        return False, 'missing_verifiable_text'

    for window in in_bounds_windows:
        if _contains_exact_quote(window, residual):
            return True, 'verified'
    return False, 'text_not_found'


def _build_per_paper_readiness(profiles, scenario_scores, issues_by_pid):
    per_paper = {}
    for p_idx, item in enumerate(profiles):
        pid = item['id']
        if pid in per_paper:
            continue
        primary = scenario_scores[0][p_idx][1]
        sr = dict(primary['submission_readiness'])
        bands_across = [
            scenario_scores[s][p_idx][1]['submission_readiness']['band']
            for s in range(len(scenario_scores))
        ]
        pid_issues = sorted(set(issues_by_pid.get(pid, [])))
        if pid_issues or primary['status'] != 'calculated':
            sr['ready_for_top_tier_main_track'] = False
            sr['ready_for_findings_or_tier_a'] = False
            if not sr['fatal_gate_triggered']:
                sr['band'] = (
                    'not_comparable_missing_dimension'
                    if primary['status'] == 'not_comparable'
                    else 'not_comparable_structural_gate'
                )
            if pid_issues:
                sr['guidance'] = (
                    f"Blocked by comparison gate ({', '.join(pid_issues[:3])}). "
                    + sr['guidance']
                )
        per_paper[pid] = {
            'overall': primary['overall'],
            'weighted_unrounded': primary.get('weighted_unrounded'),
            **sr,
            'structural_gate_passed': (not pid_issues and primary['status'] == 'calculated'),
            'profile_issues': pid_issues,
            'bands_across_scenarios': bands_across,
            'band_stable_across_scenarios': len(set(bands_across)) == 1,
        }
    return per_paper


def _build_related_work_comparison(
    eff_target_id, profiles, scenario_scores, issues_by_pid, eff_min_related, eff_strict, *, active_dims=DIMENSIONS
):
    target_idx = None
    for idx, item in enumerate(profiles):
        if item['id'] == eff_target_id:
            target_idx = idx
            break
    target_item = profiles[target_idx] if target_idx is not None else None
    target_sc = scenario_scores[0][target_idx][1] if target_idx is not None else None

    qualified = []
    for idx, item in enumerate(profiles):
        pid = item['id']
        if pid == eff_target_id:
            continue
        if issues_by_pid.get(pid):
            continue
        sc = scenario_scores[0][idx][1]
        if sc.get('status') != 'calculated':
            continue
        qualified.append((item, sc))

    scored_related_ids = [item['id'] for item, _ in qualified]
    scored_set = set(scored_related_ids)
    target_unscored_cw = []
    seen_cw = set()
    if target_item is not None and isinstance(target_item.get('closest_work'), list):
        for cw in target_item['closest_work']:
            if not isinstance(cw, str):
                continue
            cw_s = cw.strip()
            if not cw_s or cw_s == eff_target_id or cw_s in seen_cw:
                continue
            seen_cw.add(cw_s)
            if cw_s not in scored_set:
                target_unscored_cw.append(cw_s)

    best_related_overall = None
    target_delta_vs_best = None
    max_related_by_dim = None
    dim_deltas_vs_max = None

    if qualified:
        with localcontext(BasicContext) as ctx:
            ctx.prec = 28
            best_dec = max(Decimal(sc['weighted_unrounded']) for _, sc in qualified)
            best_q = best_dec.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        best_related_overall = float(str(best_q))
        max_related_by_dim = {
            d: max(item['ratings'][d] for item, _ in qualified)
            for d in active_dims
        }
        if target_sc is not None and target_sc.get('status') == 'calculated':
            with localcontext(BasicContext) as ctx:
                ctx.prec = 28
                delta_dec = (Decimal(target_sc['weighted_unrounded']) - best_dec).quantize(
                    Decimal('0.01'), rounding=ROUND_HALF_UP
                )
            target_delta_vs_best = float(str(delta_dec))
        if target_item is not None and isinstance(target_item.get('ratings'), dict):
            dim_deltas_vs_max = {
                d: (
                    target_item['ratings'][d] - max_related_by_dim[d]
                    if type(target_item['ratings'].get(d)) is int
                    else None
                )
                for d in active_dims
            }

    warnings = []
    if target_item is not None and isinstance(target_item.get('ratings'), dict):
        t_nov = target_item['ratings'].get('novelty')
        if type(t_nov) is int and t_nov >= 7:
            contrib_delta = target_item.get('contribution_delta') or target_item.get('target_contribution_delta')
            if not isinstance(contrib_delta, str) or not contrib_delta.strip():
                warnings.append('novelty_inflation_risk:missing_contribution_delta')
            snd_key = 'soundness' if 'soundness' in active_dims else 'feasibility'
            ev_key = 'evidence' if 'evidence' in active_dims else 'evidence_coverage'
            if dim_deltas_vs_max is not None and (
                (dim_deltas_vs_max.get(snd_key) is not None and dim_deltas_vs_max[snd_key] < 0)
                or (dim_deltas_vs_max.get(ev_key) is not None and dim_deltas_vs_max[ev_key] < 0)
            ):
                rationale = (
                    target_item.get('baseline_tradeoff_explanation')
                    or target_item.get('tradeoff_explanation')
                    or target_item.get('soundness_evidence_gap_explanation')
                )
                if not isinstance(rationale, str) or not rationale.strip():
                    warnings.append('novelty_inflation_risk:soundness_or_evidence_trails_related_baseline')
    if not eff_strict and target_unscored_cw:
        warnings.append(f'unscored_closest_work_present:{len(target_unscored_cw)}')
    if not eff_strict and len(scored_related_ids) < 3:
        warnings.append(f'fewer_than_three_scored_related_papers:{len(scored_related_ids)}')

    return {
        'target_id': eff_target_id,
        'strict_related_panel': eff_strict,
        'min_related': eff_min_related,
        'scored_related_ids': scored_related_ids,
        'unscored_closest_work_ids': target_unscored_cw,
        'best_related_overall': best_related_overall,
        'max_related_by_dimension': max_related_by_dim,
        'target_delta_vs_best_related_overall': target_delta_vs_best,
        'dimension_deltas_vs_max_related': dim_deltas_vs_max,
        'novelty_inflation_warnings': warnings,
    }, target_unscored_cw, scored_related_ids


def _tok_set(text):
    return {t for t in re.findall(r'[a-z0-9]+', str(text or '').lower()) if len(t) > 1}


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _normalize_seed_bundle_document(doc):
    """Convert research_scientist_idea_seed_bundle_v1 (or gap_pipeline output) into scorecards-compatible dict."""
    bundle = doc.get('idea_seed_bundle') if (isinstance(doc.get('idea_seed_bundle'), dict) and 'seeds' not in doc) else doc
    seeds = bundle.get('seeds')
    if not isinstance(seeds, list) or not seeds:
        raise ValueError('idea_seed_bundle must contain a non-empty seeds list')

    profiles = []
    for seed in seeds:
        if not isinstance(seed, dict):
            raise ValueError('each seed in idea_seed_bundle must be a JSON object')
        gid = str(seed.get('gap_id') or '').strip()
        cw_ids = list(seed.get('closest_work_ids') or [])
        pab = seed.get('prior_art_boundary') if isinstance(seed.get('prior_art_boundary'), dict) else {}
        if not cw_ids and isinstance(pab.get('closest_work_ids'), list):
            cw_ids = list(pab['closest_work_ids'])
        sv = seed.get('subfield_vetting') if isinstance(seed.get('subfield_vetting'), dict) else {}
        covered = {c: True for c in (sv.get('covered_checks') or []) if isinstance(c, str)}
        portfolio = seed.get('idea_portfolio')
        if isinstance(portfolio, list) and portfolio:
            for item in portfolio:
                if not isinstance(item, dict):
                    continue
                prof = dict(item)
                raw_id = item.get('id')
                if not isinstance(raw_id, str) or not raw_id.strip():
                    alt_id = item.get('idea_id')
                    if isinstance(alt_id, str) and alt_id.strip():
                        prof['id'] = alt_id.strip()
                if not isinstance(prof.get('gap_id'), str) or not prof['gap_id'].strip():
                    prof['gap_id'] = gid
                if not isinstance(prof.get('object_type'), str) or not prof['object_type'].strip():
                    prof['object_type'] = 'idea'
                if not isinstance(prof.get('status'), str) or not prof['status'].strip():
                    prof['status'] = 'idea'
                if not isinstance(prof.get('reading_basis'), str) or not prof['reading_basis'].strip():
                    prof['reading_basis'] = 'full_text'
                if not prof.get('closest_work'):
                    prof['closest_work'] = list(cw_ids)
                raw_r = prof.get('ratings')
                if raw_r is None:
                    prof['ratings'] = {d: None for d in IDEA_DIMENSIONS}
                elif (
                    isinstance(raw_r, dict)
                    and set(raw_r).issubset(set(IDEA_DIMENSIONS))
                    and len(raw_r) < len(IDEA_DIMENSIONS)
                ):
                    prof['ratings'] = {d: raw_r.get(d) for d in IDEA_DIMENSIONS}
                if 'evidence_locators' not in prof or prof['evidence_locators'] is None:
                    prof['evidence_locators'] = {}
                for inherit_k in (
                    'resource_feasibility', 'durability_12_24m', 'so_what_decision_impact',
                    'gap_tier_ceiling', 'pre_mortem', 'root_cause_barrier',
                ):
                    if inherit_k not in prof and inherit_k in seed:
                        prof[inherit_k] = seed[inherit_k]
                if covered and 'subfield_checks' not in prof:
                    prof['subfield_checks'] = covered
                profiles.append(prof)
        else:
            profiles.append({
                'id': gid or f'seed_{len(profiles) + 1}',
                'gap_id': gid,
                'object_type': 'idea',
                'status': 'idea',
                'reading_basis': 'full_text',
                'closest_work': list(cw_ids),
                'title': str(seed.get('claim') or gid),
                'summary': str(seed.get('claim') or ''),
                'ratings': {d: None for d in IDEA_DIMENSIONS},
                'evidence_locators': {},
                'resource_feasibility': seed.get('resource_feasibility'),
                'durability_12_24m': seed.get('durability_12_24m'),
                'so_what_decision_impact': seed.get('so_what_decision_impact'),
                'gap_tier_ceiling': seed.get('gap_tier_ceiling'),
                'pre_mortem': seed.get('pre_mortem'),
                'subfield_checks': covered,
            })

    normalized = {
        'mode': 'idea',
        'profiles': profiles,
        'weight_scenarios': doc.get('weight_scenarios') or bundle.get('weight_scenarios') or [dict(DEFAULT_IDEA_WEIGHTS)],
        'idea_seed_bundle': bundle,
    }
    for passthrough in ('goal', 'subfield_preset', 'venue_type', 'portfolio_mode', 'target_id'):
        val = doc.get(passthrough) if doc.get(passthrough) is not None else bundle.get(passthrough)
        if val is not None:
            normalized[passthrough] = val
    return normalized


def _validate_pre_mortem_obj(pm):
    if not isinstance(pm, dict):
        return ['pre_mortem_must_be_object']
    errs = []
    fms = pm.get('top_failure_modes')
    if not isinstance(fms, list) or len([x for x in fms if isinstance(x, str) and x.strip()]) < 3:
        errs.append('top_failure_modes_lt_3')
    kexp = pm.get('killer_experiment')
    if not isinstance(kexp, dict):
        errs.append('killer_experiment_missing')
    else:
        dur = kexp.get('duration_days')
        if isinstance(dur, bool) or not isinstance(dur, (int, float)) or not math.isfinite(float(dur)) or dur <= 0 or dur > 2:
            errs.append('killer_experiment_duration_not_1_to_2_days')
        kt = kexp.get('kill_threshold')
        if not isinstance(kt, str) or not kt.strip():
            errs.append('killer_experiment_kill_threshold_missing')
    pivot = pm.get('pivot_path')
    if not isinstance(pivot, str) or not pivot.strip():
        errs.append('pivot_path_missing')
    return errs


def _validate_idea_linkage_and_portfolio(
    profiles,
    *,
    sources_dir=None,
    gap_record=None,
    question_card=None,
    idea_seed_bundle=None,
    require_idea_portfolio=False,
    require_pre_mortem=False,
    record_issue_fn=None,
):
    linkage = {
        'gap_record_checked': False,
        'gap_record_valid': None,
        'question_card_checked': False,
        'question_card_valid': None,
        'seed_bundle_linked': False,
        'seed_count': 0,
        'trajectory_tree_generations_count': 0,
        'support_ids': [],
        'cited_ids': [],
        'closest_work_ids': [],
        'f32_lenses': [],
        'portfolio_distinct_ideas': 0,
        'portfolio_distinct_angles': [],
        'pre_mortem_warnings': [],
    }
    known_gap_ids = set()

    if gap_record is not None:
        import check_gap_record
        linkage['gap_record_checked'] = True
        ev_dir = None
        if sources_dir is not None:
            s_root = Path(sources_dir).expanduser().resolve()
            if s_root.is_dir() and any(s_root.rglob('*.json')):
                ev_dir = sources_dir
        gr_res = check_gap_record.check(gap_record, evidence_dir=ev_dir)
        linkage['gap_record_valid'] = bool(gr_res.get('valid_structure'))
        if not gr_res.get('valid_structure'):
            for err in gr_res.get('errors') or ['invalid_gap_record']:
                record_issue_fn(f'gap_record_invalid:{err}', None)
        for cand in gap_record.get('candidates') or []:
            if isinstance(cand, dict) and isinstance(cand.get('id'), str) and cand['id'].strip():
                known_gap_ids.add(cand['id'].strip())
        for ev in gap_record.get('evidence') or []:
            if isinstance(ev, dict) and isinstance(ev.get('id'), str):
                linkage['support_ids'].append(ev['id'])

    if question_card is not None:
        import check_question_card
        linkage['question_card_checked'] = True
        qc_res = check_question_card.check(question_card)
        linkage['question_card_valid'] = bool(qc_res.get('valid_structure'))
        if not qc_res.get('valid_structure'):
            for err in qc_res.get('errors') or ['invalid_question_card']:
                record_issue_fn(f'question_card_invalid:{err}', None)
        qc_gid = question_card.get('gap_id')
        if isinstance(qc_gid, str) and qc_gid.strip() and known_gap_ids and qc_gid.strip() not in known_gap_ids:
            record_issue_fn(f'question_card_unlinked_gap_id:{qc_gid.strip()}', None)
        qc_iid = question_card.get('idea_id')
        prof_ids = {p['id'] for p in profiles}
        if isinstance(qc_iid, str) and qc_iid.strip() and qc_iid.strip() not in prof_ids:
            record_issue_fn(f'question_card_unlinked_idea_id:{qc_iid.strip()}', None)

    if idea_seed_bundle is not None:
        bundle = (
            idea_seed_bundle.get('idea_seed_bundle')
            if isinstance(idea_seed_bundle, dict) and 'idea_seed_bundle' in idea_seed_bundle and 'seeds' not in idea_seed_bundle
            else idea_seed_bundle
        )
        if not isinstance(bundle, dict) or bundle.get('schema') != 'research_scientist_idea_seed_bundle_v1':
            record_issue_fn('invalid_idea_seed_bundle_schema', None)
        else:
            linkage['seed_bundle_linked'] = True
            seeds = bundle.get('seeds') if isinstance(bundle.get('seeds'), list) else []
            linkage['seed_count'] = len(seeds)
            if not seeds:
                record_issue_fn('idea_seed_bundle_empty_seeds', None)
            traj_trees = bundle.get('trajectory_trees')
            if isinstance(traj_trees, dict):
                for tk, tv in traj_trees.items():
                    if not isinstance(tv, dict) or not isinstance(tv.get('generations'), list) or not tv['generations']:
                        record_issue_fn(f'invalid_trajectory_tree:{tk}', None)
            for s_idx, seed in enumerate(seeds):
                if not isinstance(seed, dict):
                    continue
                gid = str(seed.get('gap_id') or f'seed_{s_idx}').strip()
                known_gap_ids.add(gid)
                tt = seed.get('trajectory_tree')
                if tt is not None:
                    if not isinstance(tt, dict) or not isinstance(tt.get('generations'), list) or not tt['generations']:
                        record_issue_fn(f'invalid_seed_trajectory_tree:{gid}', None)
                    else:
                        linkage['trajectory_tree_generations_count'] += len(tt['generations'])
                pab = seed.get('prior_art_boundary')
                if not isinstance(pab, dict):
                    record_issue_fn(f'missing_prior_art_boundary:{gid}', None)
                else:
                    for key_name in ('support_ids', 'cited_ids', 'closest_work_ids'):
                        vals = [str(x).strip() for x in (pab.get(key_name) or []) if isinstance(x, str) and x.strip()]
                        for v in vals:
                            if v not in linkage[key_name]:
                                linkage[key_name].append(v)
                ft_digests = seed.get('full_text_digests')
                if isinstance(ft_digests, dict):
                    for cw in seed.get('closest_work_ids') or []:
                        dig = ft_digests.get(cw)
                        basis_ok = isinstance(dig, dict) and (
                            dig.get('reading_basis') in ('full_text', 'selected_full_text')
                            or dig.get('access') in ('full_text', 'selected_full_text')
                        )
                        if not basis_ok:
                            record_issue_fn(f'seed_closest_work_not_full_text:{gid}:{cw}', None)
                rcb = seed.get('root_cause_barrier')
                sw = seed.get('so_what_decision_impact')
                dur = seed.get('durability_12_24m')
                if rcb is not None and rcb not in _ROOT_CAUSE_BARRIERS:
                    record_issue_fn(f'invalid_f32_root_cause_barrier:{gid}:{rcb}', None)
                if sw is not None and sw not in _SO_WHAT_IMPACTS:
                    record_issue_fn(f'invalid_f32_so_what:{gid}:{sw}', None)
                if dur is not None and dur not in _DURABILITY_LEVELS:
                    record_issue_fn(f'invalid_f32_durability:{gid}:{dur}', None)
                linkage['f32_lenses'].append({
                    'gap_id': gid,
                    'root_cause_barrier': rcb,
                    'why_now_enabler': seed.get('why_now_enabler'),
                    'so_what_decision_impact': sw,
                    'durability_12_24m': dur,
                })

    if known_gap_ids:
        for item in profiles:
            gid = item.get('gap_id')
            if isinstance(gid, str) and gid.strip() and gid.strip() not in known_gap_ids:
                record_issue_fn(f'unlinked_gap_id:{item["id"]}:{gid.strip()}', item['id'])

    # F28 portfolio & pre-mortem checks (validated per gap_id group)
    grouped_profiles = {}
    for item in profiles:
        raw_gid = item.get('gap_id')
        g_key = raw_gid.strip() if isinstance(raw_gid, str) and raw_gid.strip() else ''
        grouped_profiles.setdefault(g_key, []).append(item)

    all_distinct_ideas = 0
    all_distinct_angles = set()
    portfolio_by_gap = {}
    multi_group = len(grouped_profiles) > 1
    for g_key, g_profiles in grouped_profiles.items():
        g_distinct_toks = []
        g_distinct_angles = set()
        for item in g_profiles:
            raw_angle = str(item.get('angle') or item.get('canonical_angle') or '').strip()
            canon = _CANONICAL_PORTFOLIO_ANGLE.get(raw_angle)
            summary_blob = ' '.join(
                str(item.get(k) or '').strip()
                for k in ('title', 'mechanism_summary', 'summary')
                if isinstance(item.get(k), str) and str(item.get(k)).strip()
            )
            toks = _tok_set(summary_blob or item['id'])
            redundant = bool(toks) and any(_jaccard(toks, prev) >= 0.80 for prev in g_distinct_toks)
            if redundant:
                if require_idea_portfolio:
                    record_issue_fn(f'idea_portfolio_redundant_idea:{item["id"]}', item['id'])
            else:
                g_distinct_toks.append(toks)
                if canon:
                    g_distinct_angles.add(canon)
                elif raw_angle and require_idea_portfolio:
                    record_issue_fn(f'invalid_portfolio_angle:{item["id"]}:{raw_angle}', item['id'])

            pm = item.get('pre_mortem')
            if pm is not None:
                pm_errs = _validate_pre_mortem_obj(pm)
                if pm_errs:
                    msg = f'incomplete_pre_mortem:{item["id"]}:{",".join(pm_errs)}'
                    if require_pre_mortem:
                        record_issue_fn(msg, item['id'])
                    else:
                        linkage['pre_mortem_warnings'].append(msg)
            elif require_pre_mortem:
                record_issue_fn(f'missing_pre_mortem:{item["id"]}', item['id'])

        all_distinct_ideas += len(g_distinct_toks)
        all_distinct_angles.update(g_distinct_angles)
        portfolio_by_gap[g_key or '_default'] = {
            'total_ideas': len(g_profiles),
            'distinct_ideas': len(g_distinct_toks),
            'distinct_angles': sorted(g_distinct_angles),
        }
        if require_idea_portfolio:
            if len(g_distinct_toks) < 3 or len(g_distinct_angles) < 3 or len(g_profiles) > 4:
                if multi_group:
                    record_issue_fn(
                        f'tunnel_vision_idea_portfolio:{g_key or "default"}:ideas={len(g_distinct_toks)},angles={len(g_distinct_angles)},total={len(g_profiles)}',
                        None,
                    )
                else:
                    record_issue_fn(
                        f'tunnel_vision_idea_portfolio:ideas={len(g_distinct_toks)},angles={len(g_distinct_angles)}',
                        None,
                    )

    linkage['portfolio_distinct_ideas'] = all_distinct_ideas
    linkage['portfolio_distinct_angles'] = sorted(all_distinct_angles)
    linkage['portfolio_by_gap'] = portfolio_by_gap

    return linkage


def _extract_finite_gpu_hours(item):
    res = item.get('resource_feasibility') if isinstance(item.get('resource_feasibility'), dict) else {}
    gpu_h = item.get('required_gpu_hours')
    if isinstance(gpu_h, bool) or not isinstance(gpu_h, (int, float)) or not math.isfinite(float(gpu_h)) or float(gpu_h) < 0:
        gpu_h = res.get('required_gpu_hours')
    if isinstance(gpu_h, (int, float)) and not isinstance(gpu_h, bool) and math.isfinite(float(gpu_h)) and float(gpu_h) >= 0:
        return Decimal(str(gpu_h))
    return None


def _compute_pareto_frontier(profiles, scenario_scores, goal):
    """Compute goal-conditioned non-dominated Pareto frontier across ideas (Decimal-safe)."""
    eff_goal = (goal or 'safe_fast_publish').strip().lower()
    if eff_goal not in IDEA_GOAL_MODES:
        raise ValueError(f'Unknown --goal: {goal!r}')

    entries = []
    with localcontext(BasicContext) as ctx:
        ctx.prec = 28
        max_known_gpu = Decimal(0)
        for item in profiles:
            g_dec = _extract_finite_gpu_hours(item)
            if g_dec is not None and g_dec > max_known_gpu:
                max_known_gpu = g_dec
        for idx, item in enumerate(profiles):
            pid = item['id']
            sc = scenario_scores[0][idx][1]
            if sc.get('status') != 'calculated':
                continue
            r = item['ratings']
            w_dec = Decimal(sc['weighted_unrounded'])
            raw_angle = str(item.get('canonical_angle') or item.get('angle') or '').strip()
            canon_angle = _CANONICAL_PORTFOLIO_ANGLE.get(raw_angle, raw_angle)
            gtags = {str(x).strip().lower() for x in (item.get('goal_tags') or []) if isinstance(x, str)}

            if eff_goal == 'safe_fast_publish':
                tag_bonus = Decimal(1) if ('safe_fast_publish' in gtags or canon_angle in {'minimal_fix', 'benchmark_diagnostic_analysis'}) else Decimal(0)
                vec = (
                    Decimal(r.get('feasibility', r.get('soundness', 0))),
                    Decimal(r.get('answerability', r.get('evidence', 0))),
                    Decimal(r.get('evidence_coverage', r.get('evidence', 0))),
                    Decimal(r.get('falsifiability', r.get('transparency', 0))),
                    w_dec,
                    tag_bonus,
                )
                tie_score = Decimal(vec[0]) * Decimal(3) + Decimal(vec[1]) * Decimal(2) + w_dec + tag_bonus
            elif eff_goal == 'high_risk_q1_top_tier':
                dur = str(item.get('durability_12_24m') or '').strip()
                so_what = str(item.get('so_what_decision_impact') or '').strip()
                dur_score = Decimal(1) if dur == 'durable_structural_limit' else (Decimal(-1) if dur == 'high_scaling_erasure_risk' else Decimal(0))
                impact_bonus = Decimal(-1) if so_what == 'marginal_gain' else (Decimal(1) if so_what == 'decision_changing' else Decimal(0))
                vec = (
                    Decimal(r.get('novelty', 0)),
                    Decimal(r.get('importance', 0)),
                    Decimal(r.get('falsifiability', r.get('soundness', 0))),
                    w_dec,
                    dur_score + impact_bonus,
                )
                tie_score = Decimal(vec[0]) * Decimal(3) + Decimal(vec[1]) * Decimal(2) + w_dec + dur_score + impact_bonus
            else:  # low_compute_constrained
                res = item.get('resource_feasibility') if isinstance(item.get('resource_feasibility'), dict) else {}
                infeasible = res.get('infeasible_under_user_resources') is True
                feasible_flag = Decimal(0) if infeasible else Decimal(1)
                gpu_dec = _extract_finite_gpu_hours(item)
                if gpu_dec is not None:
                    compute_reported = Decimal(1)
                    compute_inv = Decimal(-1) * gpu_dec
                    tie_compute = compute_inv
                else:
                    compute_reported = Decimal(0)
                    compute_inv = Decimal(0)
                    tag_tie = Decimal('0.5') if ('low_compute_constrained' in gtags or canon_angle == 'low_gpu_fallback') else Decimal(0)
                    tie_compute = Decimal(-1) * (max_known_gpu + Decimal(1)) + tag_tie
                vec = (
                    feasible_flag,
                    Decimal(r.get('feasibility', r.get('soundness', 0))),
                    Decimal(r.get('answerability', r.get('evidence', 0))),
                    Decimal(r.get('evidence_coverage', r.get('evidence', 0))),
                    compute_reported,
                    compute_inv,
                )
                tie_score = (
                    feasible_flag * Decimal(10000)
                    + Decimal(vec[1]) * Decimal(3)
                    + Decimal(vec[2]) * Decimal(2)
                    + tie_compute
                    + w_dec * Decimal('0.5')
                )

            entries.append({'id': pid, 'vec': vec, 'tie_score': tie_score, 'weighted': str(w_dec)})

        dominance_map = {e['id']: [] for e in entries}
        for a in entries:
            for b in entries:
                if a['id'] == b['id']:
                    continue
                if all(x >= y for x, y in zip(a['vec'], b['vec'])) and any(x > y for x, y in zip(a['vec'], b['vec'])):
                    dominance_map[b['id']].append(a['id'])

        frontier_ids = [e['id'] for e in entries if not dominance_map[e['id']]]
        dominated_ids = [e['id'] for e in entries if dominance_map[e['id']]]
        goal_ranked = sorted(
            entries,
            key=lambda e: (1 if dominance_map[e['id']] else 0, -e['tie_score'], e['id']),
        )

    return {
        'goal': eff_goal,
        'frontier_ids': frontier_ids,
        'dominated_ids': dominated_ids,
        'dominance_map': dominance_map,
        'goal_ranked_ids': [e['id'] for e in goal_ranked],
    }


def _extract_profile_for_diff(doc, preferred_id=None):
    if not isinstance(doc, dict):
        raise ValueError('Revision document must be a JSON object')
    if 'profiles' in doc:
        profiles = doc.get('profiles')
        if not isinstance(profiles, list) or not profiles:
            raise ValueError('Revision document profiles list is empty')
        target_id = preferred_id or doc.get('target_id')
        chosen = None
        if target_id:
            for p in profiles:
                if isinstance(p, dict) and p.get('id') == target_id:
                    chosen = p
                    break
            if chosen is None:
                raise ValueError(f'Profile {target_id!r} not found in revision document')
        else:
            chosen = profiles[0]
        vtype = doc.get('venue_type') if doc.get('venue_type') is not None else doc.get('venue_profile')
        r = chosen.get('ratings') if isinstance(chosen.get('ratings'), dict) else {}
        scenarios = doc.get('weight_scenarios')
        if isinstance(scenarios, list) and scenarios:
            weights = scenarios[0]
        elif set(r) == set(IDEA_DIMENSIONS):
            weights = dict(DEFAULT_IDEA_WEIGHTS)
        elif vtype in VENUE_TYPE_PROFILES:
            weights = dict(VENUE_TYPE_PROFILES[vtype]['weights'])
        else:
            weights = None
        return chosen, weights
    if 'ratings' in doc:
        vtype = doc.get('venue_type') if doc.get('venue_type') is not None else doc.get('venue_profile')
        r = doc.get('ratings') if isinstance(doc.get('ratings'), dict) else {}
        weights = doc.get('weights')
        if weights is None and set(r) == set(IDEA_DIMENSIONS):
            weights = dict(DEFAULT_IDEA_WEIGHTS)
        if weights is None and vtype in VENUE_TYPE_PROFILES:
            weights = dict(VENUE_TYPE_PROFILES[vtype]['weights'])
        return doc, weights
    raise ValueError('Revision document must contain ratings or profiles')


def _validate_receipt_entry(rec, sources_root, receipt_errors, *, allow_hash_alias=True):
    """Validate receipt path safety and (when sources_root is provided) disk existence & SHA-256."""
    if not isinstance(rec, dict):
        return True
    if 'path' in rec and rec['path'] is not None:
        raw_path = rec['path']
        if not isinstance(raw_path, str) or not raw_path.strip():
            receipt_errors.append(f'unsafe_receipt_path:{raw_path!r}')
            return False
        p_str = raw_path.strip()
        if (
            '\x00' in p_str
            or '\\' in p_str
            or p_str.startswith('~')
            or p_str.lower().startswith('file:')
            or (len(p_str) >= 2 and p_str[1] == ':')
        ):
            receipt_errors.append(f'unsafe_receipt_path:{p_str}')
            return False
        p_path = Path(p_str)
        if p_path.is_absolute() or '..' in p_path.parts:
            receipt_errors.append(f'unsafe_receipt_path:{p_str}')
            return False
        if sources_root is not None:
            resolved = (sources_root / p_path).resolve()
            if not resolved.is_relative_to(sources_root) or not resolved.is_file():
                receipt_errors.append(f'missing_receipt_file:{p_str}')
                return False
            actual_sha = hashlib.sha256(resolved.read_bytes()).hexdigest().lower()
            raw_decl = rec.get('sha256') if not allow_hash_alias else (rec.get('sha256') or rec.get('hash'))
            decl_sha = str(raw_decl or '').strip().lower()
            if decl_sha.startswith('sha256:'):
                decl_sha = decl_sha.split(':', 1)[1].strip()
            if actual_sha != decl_sha:
                receipt_errors.append(f'receipt_sha256_mismatch:{p_str}')
                return False
    return True


def _sanitize_v2_receipts(v2_prof, sources_root):
    v2_clean = dict(v2_prof)
    receipt_errors = []
    for key in ('run_receipts', 'experiment_receipts', 'receipts'):
        raw_val = v2_prof.get(key)
        if isinstance(raw_val, list):
            v2_clean[key] = [
                rec for rec in raw_val
                if _validate_receipt_entry(rec, sources_root, receipt_errors, allow_hash_alias=True)
            ]
        elif isinstance(raw_val, dict):
            if _validate_receipt_entry(raw_val, sources_root, receipt_errors, allow_hash_alias=True):
                v2_clean[key] = raw_val
            else:
                v2_clean.pop(key, None)
    rev_ev = v2_prof.get('revision_evidence')
    if isinstance(rev_ev, dict):
        cleaned_rev = {}
        for dim, entry in rev_ev.items():
            if isinstance(entry, list):
                cleaned_rev[dim] = [
                    it for it in entry
                    if _validate_receipt_entry(it, sources_root, receipt_errors, allow_hash_alias=False)
                ]
            elif _validate_receipt_entry(entry, sources_root, receipt_errors, allow_hash_alias=False):
                cleaned_rev[dim] = entry
        v2_clean['revision_evidence'] = cleaned_rev
    return v2_clean, receipt_errors


def revision_diff(v1_doc, v2_doc, *, sources_dir=None, target_id=None):
    """Compare v1 vs v2 scorecards, check new locators/SHA-256 receipts, and flag suspected grade inflation."""
    eff_tid = target_id
    if eff_tid is None and isinstance(v2_doc, dict) and isinstance(v2_doc.get('target_id'), str):
        eff_tid = v2_doc['target_id'].strip()
    elif eff_tid is None and isinstance(v1_doc, dict) and isinstance(v1_doc.get('target_id'), str):
        eff_tid = v1_doc['target_id'].strip()

    v1_prof, v1_w = _extract_profile_for_diff(v1_doc, eff_tid)
    v2_prof, v2_w = _extract_profile_for_diff(v2_doc, eff_tid)
    weights = v2_w if v2_w is not None else v1_w
    if weights is None:
        raise ValueError('weights are required in v1 or v2 for revision diff')

    r1 = v1_prof.get('ratings') if isinstance(v1_prof.get('ratings'), dict) else {}
    r2 = v2_prof.get('ratings') if isinstance(v2_prof.get('ratings'), dict) else {}
    if set(r1) == set(IDEA_DIMENSIONS) and set(r2) == set(IDEA_DIMENSIONS):
        active_dims = IDEA_DIMENSIONS
        fatal_thresholds = IDEA_FATAL_THRESHOLDS
    else:
        active_dims = DIMENSIONS
        fatal_thresholds = FATAL_THRESHOLDS

    verified_loc_set = None
    locator_verification = None
    sources_root = None
    if sources_dir is not None:
        index = index_sources_dir(sources_dir)
        sources_root = index['root']
        pid = v2_prof.get('id') or eff_tid
        v1_locs = v1_prof.get('evidence_locators') if isinstance(v1_prof.get('evidence_locators'), dict) else {}
        v2_locs = v2_prof.get('evidence_locators') if isinstance(v2_prof.get('evidence_locators'), dict) else {}
        verified_loc_set = set()
        checked, verified, failed = 0, 0, 0
        failed_new = []
        for d in active_dims:
            old_set = {x.strip() for x in (v1_locs.get(d) or []) if isinstance(x, str) and x.strip()}
            for loc in (v2_locs.get(d) or []):
                if not isinstance(loc, str) or not loc.strip():
                    continue
                loc_s = loc.strip()
                if loc_s in old_set:
                    continue
                checked += 1
                ok, reason = verify_locator(loc_s, index, default_source_ids=(pid,) if pid else ())
                if ok:
                    verified += 1
                    verified_loc_set.add((d, loc_s))
                else:
                    failed += 1
                    failed_new.append(f'{d}:{loc_s}:{reason}')
        locator_verification = {
            'sources_dir': str(index['root']),
            'sources_indexed': index['sources_indexed'],
            'checked': checked,
            'verified': verified,
            'failed': failed,
            'failed_new_locators': failed_new,
        }

    # Verify receipt path safety unconditionally and disk SHA-256 digests when sources_dir is supplied
    v2_clean, receipt_errors = _sanitize_v2_receipts(v2_prof, sources_root)

    diff_res = diff_scorecards(
        v1_prof,
        v2_clean,
        weights,
        active_dims=active_dims,
        fatal_thresholds=fatal_thresholds,
        verified_v2_locators=verified_loc_set,
    )
    if receipt_errors:
        diff_res['receipt_verification_errors'] = receipt_errors
        diff_res['inflation_warnings'].extend(receipt_errors)
        diff_res['suspected_grade_inflation'] = True
        diff_res['status'] = 'grade_inflation_suspected'
    if locator_verification is not None:
        diff_res['locator_verification'] = locator_verification
        if locator_verification['failed'] > 0 and diff_res['suspected_grade_inflation']:
            diff_res['inflation_warnings'].append(
                f"unverified_new_locators:{locator_verification['failed']}"
            )
    diff_res['mode'] = 'revision_diff'
    diff_res['target_id'] = v2_prof.get('id') or eff_tid or 'target'
    return diff_res


def compare(
    document,
    sources_dir=None,
    target_id=None,
    strict_related_panel=None,
    min_related=None,
    *,
    venue_type=None,
    mode=None,
    goal=None,
    subfield_preset=None,
    gap_record=None,
    question_card=None,
    idea_seed_bundle=None,
    require_idea_portfolio=False,
    require_pre_mortem=False,
    what_if=False,
):
    if not isinstance(document, dict):
        raise ValueError('document must be a JSON object')

    if (
        document.get('schema') in {'research_scientist_idea_seed_bundle_v1', 'research_scientist_gap_pipeline_v1'}
        or ('seeds' in document and 'profiles' not in document)
        or (isinstance(document.get('idea_seed_bundle'), dict) and 'profiles' not in document)
    ):
        document = _normalize_seed_bundle_document(document)

    eff_mode_raw = (mode if mode is not None else document.get('mode') or 'auto')
    if type(eff_mode_raw) is not str or not eff_mode_raw.strip():
        raise ValueError('mode must be a nonblank string')
    eff_mode_raw = eff_mode_raw.strip().lower()
    if eff_mode_raw not in {'auto', 'paper', 'idea'}:
        raise ValueError(f'Unknown mode: {eff_mode_raw!r}')

    eff_vtype = resolve_venue_type(venue_type if venue_type is not None else (document.get('venue_type') or document.get('venue_profile')))
    eff_preset = subfield_preset if subfield_preset is not None else document.get('subfield_preset')
    if eff_preset is not None:
        evaluate_subfield_readiness(eff_preset)  # validate preset upfront

    eff_goal = goal if goal is not None else document.get('goal')
    if eff_goal is not None and (type(eff_goal) is not str or eff_goal.strip().lower() not in IDEA_GOAL_MODES):
        raise ValueError(f'Unknown goal: {eff_goal!r}')

    if not isinstance(document.get('profiles'), list) or len(document['profiles']) < 2:
        raise ValueError('at least two profiles are required')

    profiles = document['profiles']
    for item in profiles:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id'].strip():
            raise ValueError('each profile needs a nonblank id')
        if 'ratings' not in item:
            raise ValueError(f'missing ratings for profile {item["id"]}')

    has_idea_dim_profiles = any(
        isinstance(p.get('ratings'), dict) and set(p['ratings']) == set(IDEA_DIMENSIONS)
        for p in profiles
    )
    if eff_mode_raw == 'idea':
        eff_mode = 'idea'
    elif eff_mode_raw == 'paper':
        eff_mode = 'paper'
    elif has_idea_dim_profiles:
        eff_mode = 'idea'
    else:
        eff_mode = 'paper'

    active_dims = IDEA_DIMENSIONS if (eff_mode == 'idea' and has_idea_dim_profiles) else DIMENSIONS
    fatal_thresholds = IDEA_FATAL_THRESHOLDS if active_dims == IDEA_DIMENSIONS else FATAL_THRESHOLDS

    scenarios = document.get('weight_scenarios')
    if scenarios is None:
        if active_dims == IDEA_DIMENSIONS:
            scenarios = [dict(DEFAULT_IDEA_WEIGHTS)]
        elif eff_vtype is not None:
            scenarios = [dict(VENUE_TYPE_PROFILES[eff_vtype]['weights'])]
        else:
            raise ValueError('weight_scenarios must be a nonempty list')
    elif not isinstance(scenarios, list) or not scenarios:
        raise ValueError('weight_scenarios must be a nonempty list')

    raw_target = target_id if target_id is not None else document.get('target_id')
    if raw_target is not None:
        if not isinstance(raw_target, str) or not raw_target.strip():
            raise ValueError('target_id must be a nonblank string')
        eff_target_id = raw_target.strip()
    else:
        eff_target_id = None

    if strict_related_panel is not None:
        if type(strict_related_panel) is not bool:
            raise ValueError('strict_related_panel must be a boolean')
        eff_strict = strict_related_panel
    elif 'strict_related_panel' in document and document['strict_related_panel'] is not None:
        if type(document['strict_related_panel']) is not bool:
            raise ValueError('strict_related_panel must be a boolean')
        eff_strict = document['strict_related_panel']
    else:
        eff_strict = False

    raw_min = min_related if min_related is not None else document.get('min_related')
    if raw_min is not None:
        if type(raw_min) is not int or raw_min < 1:
            raise ValueError('min_related must be an integer >= 1')
        eff_min_related = raw_min
    else:
        eff_min_related = 3 if eff_strict else None

    # Validate weights and ratings upfront so invalid ratings/weights are never masked
    # by early structural issues (e.g. reading_basis != 'full_text' or missing locators).
    scenario_scores = []
    for weights in scenarios:
        per_profile = []
        for item in profiles:
            score_input = {'weights': weights, 'ratings': item['ratings']}
            if 'status' in item:
                score_input['status'] = item['status']
            if 'object_type' in item:
                score_input['object_type'] = item['object_type']
            if eff_mode == 'idea':
                score_input['mode'] = 'idea'
            if eff_vtype is not None:
                score_input['venue_type'] = eff_vtype
                for vc_k in ('venue_checks', 'dataset_checks', 'ethics_license_verified', 't1_t2_verified'):
                    if vc_k in item:
                        score_input[vc_k] = item[vc_k]
                    elif vc_k in document:
                        score_input[vc_k] = document[vc_k]
            if eff_preset is not None:
                score_input['subfield_preset'] = eff_preset
                if 'subfield_checks' in item:
                    score_input['subfield_checks'] = item['subfield_checks']
                elif 'subfield_checks' in document:
                    score_input['subfield_checks'] = document['subfield_checks']
            if 'reviewer_panel' in item:
                score_input['reviewer_panel'] = item['reviewer_panel']
            if 'reviewer_confidence' in item:
                score_input['reviewer_confidence'] = item['reviewer_confidence']
            if 'confidence' in item:
                score_input['confidence'] = item['confidence']
            if 'section_diagnostics' in item:
                score_input['section_diagnostics'] = item['section_diagnostics']
            if 'gap_tier_ceiling' in item:
                score_input['gap_tier_ceiling'] = item['gap_tier_ceiling']
            if 'resource_feasibility' in item:
                score_input['resource_feasibility'] = item['resource_feasibility']
            for ctx_k in ('closest_work', 'reading_basis', 'evidence_locators', 'evidence_rigor', 'has_ci_or_error_bars', 'has_ablation', 'seed_count', 'ablation_results', 'notes', 'evidence_notes'):
                if ctx_k in item:
                    score_input[ctx_k] = item[ctx_k]
            calculated = score(score_input)
            per_profile.append((item['id'], calculated))
        scenario_scores.append(per_profile)

    issues = []
    issues_by_pid = {}

    def _record_issue(msg, pid=None):
        issues.append(msg)
        if pid is not None:
            issues_by_pid.setdefault(pid, []).append(msg)

    ids = set()
    for item in profiles:
        pid = item['id']
        if pid in ids:
            _record_issue(f'duplicate_profile:{pid}', pid)
        ids.add(pid)
        if item.get('reading_basis') != 'full_text':
            _record_issue(f'full_text_not_confirmed:{pid}', pid)
        if not isinstance(item.get('closest_work'), list) or not item['closest_work']:
            _record_issue(f'closest_work_missing:{pid}', pid)
        elif any(not isinstance(x, str) or not x.strip() for x in item['closest_work']):
            _record_issue(f'invalid_closest_work:{pid}', pid)
        else:
            if any(x.strip() == pid for x in item['closest_work']):
                _record_issue(f'closest_work_self_reference:{pid}', pid)
        locators = item.get('evidence_locators')
        if not isinstance(locators, dict) or set(locators) != set(active_dims):
            _record_issue(f'evidence_locators_incomplete:{pid}', pid)
        else:
            for dimension in active_dims:
                value = locators[dimension]
                if not isinstance(value, list) or not value or any(not isinstance(x, str) or not x.strip() for x in value):
                    _record_issue(f'missing_locator:{pid}:{dimension}', pid)

    locator_verification = None
    if sources_dir is not None:
        index = index_sources_dir(sources_dir)
        checked = 0
        verified = 0
        failed = 0
        for item in profiles:
            pid = item['id']
            locators = item.get('evidence_locators')
            if not isinstance(locators, dict):
                continue
            for dimension in active_dims:
                value = locators.get(dimension)
                if not isinstance(value, list):
                    continue
                for loc_idx, loc in enumerate(value):
                    if not isinstance(loc, str) or not loc.strip():
                        continue
                    checked += 1
                    ok, reason = verify_locator(loc, index, default_source_ids=(pid,))
                    if ok:
                        verified += 1
                    else:
                        failed += 1
                        _record_issue(f'locator_unverified:{pid}:{dimension}:{loc_idx}:{reason}', pid)
        locator_verification = {
            'sources_dir': str(index['root']),
            'sources_indexed': index['sources_indexed'],
            'skipped_files': index['skipped_files'],
            'checked': checked,
            'verified': verified,
            'failed': failed,
        }

    for per_profile in scenario_scores:
        for pid, calculated in per_profile:
            if calculated['status'] != 'calculated':
                _record_issue(f'missing_rating:{pid}', pid)

    valid_profile_ids = {p['id'] for p in profiles}
    unscored_by_profile = {}
    for item in profiles:
        pid = item['id']
        if pid in unscored_by_profile:
            continue
        unscored = []
        seen_cw = set()
        if isinstance(item.get('closest_work'), list):
            for cw in item['closest_work']:
                if not isinstance(cw, str):
                    continue
                cw_s = cw.strip()
                if not cw_s or cw_s == pid or cw_s in seen_cw:
                    continue
                seen_cw.add(cw_s)
                if cw_s not in valid_profile_ids:
                    unscored.append(cw_s)
        unscored_by_profile[pid] = unscored

    related_work_comparison = None
    target_unscored_cw = []
    scored_related_ids = []
    if (eff_strict or eff_min_related is not None) and eff_target_id is None:
        _record_issue('target_id_required_for_strict_related_panel', None)

    if eff_target_id is not None:
        target_exists = any(p['id'] == eff_target_id for p in profiles)
        if not target_exists:
            _record_issue(f'target_profile_not_found:{eff_target_id}', None)
        related_work_comparison, target_unscored_cw, scored_related_ids = _build_related_work_comparison(
            eff_target_id, profiles, scenario_scores, issues_by_pid, eff_min_related, eff_strict,
            active_dims=active_dims,
        )
        if target_exists and (eff_strict or eff_min_related is not None):
            if eff_strict:
                for cw_id in target_unscored_cw:
                    _record_issue(f'unscored_closest_work:{cw_id}', eff_target_id)
            if eff_min_related is not None and len(scored_related_ids) < eff_min_related:
                _record_issue(
                    f'insufficient_scored_related_papers:{len(scored_related_ids)}<{eff_min_related}',
                    eff_target_id,
                )

    eff_gap_rec = gap_record if gap_record is not None else document.get('gap_record')
    eff_q_card = question_card if question_card is not None else document.get('question_card')
    eff_seed_bundle = idea_seed_bundle if idea_seed_bundle is not None else document.get('idea_seed_bundle')
    eff_req_portfolio = bool(require_idea_portfolio or document.get('require_idea_portfolio') or document.get('portfolio_mode'))
    eff_req_pm = bool(require_pre_mortem or document.get('require_pre_mortem'))

    linkage_summary = None
    if eff_mode == 'idea' or any(x is not None for x in (eff_gap_rec, eff_q_card, eff_seed_bundle)) or eff_req_portfolio or eff_req_pm:
        linkage_summary = _validate_idea_linkage_and_portfolio(
            profiles,
            sources_dir=sources_dir,
            gap_record=eff_gap_rec,
            question_card=eff_q_card,
            idea_seed_bundle=eff_seed_bundle,
            require_idea_portfolio=eff_req_portfolio,
            require_pre_mortem=eff_req_pm,
            record_issue_fn=_record_issue,
        )

    # Halo-effect sanity warnings (non-blocking)
    sanity_warnings_by_pid = {}
    all_sanity_warnings = []
    for idx, item in enumerate(profiles):
        pid = item['id']
        rel_cnt = len(scored_related_ids) if (eff_target_id == pid) else None
        unr_cnt = len(target_unscored_cw) if (eff_target_id == pid) else None
        sw = detect_halo_sanity_warnings(
            item['ratings'],
            item,
            active_dims=active_dims,
            related_count=rel_cnt,
            unread_closest_count=unr_cnt,
        )
        if sw:
            sanity_warnings_by_pid[pid] = sw
            for msg in sw:
                all_sanity_warnings.append(f'{pid}:{msg}')

    per_paper_sr = _build_per_paper_readiness(profiles, scenario_scores, issues_by_pid)
    # Propagate idea_viability_band & archival block when in idea mode
    if eff_mode == 'idea':
        for idx, item in enumerate(profiles):
            pid = item['id']
            sc0 = scenario_scores[0][idx][1]
            if pid in per_paper_sr:
                if 'idea_viability_band' in sc0:
                    per_paper_sr[pid]['idea_viability_band'] = sc0['idea_viability_band']
                per_paper_sr[pid]['ready_for_top_tier_main_track'] = False
                per_paper_sr[pid]['ready_for_findings_or_tier_a'] = False
                per_paper_sr[pid]['fatal_gate_triggered'] = True

    # Build M9A enrichments cleanly outside rankings[*]['ordered']
    reviewer_panels = {}
    section_diags = {}
    native_scales_map = {}
    merit_packaging_map = {}
    deal_breaker_map = {}
    what_if_map = {}
    for idx, item in enumerate(profiles):
        pid = item['id']
        sc0 = scenario_scores[0][idx][1]
        if 'reviewer_panel_analysis' in sc0:
            reviewer_panels[pid] = sc0['reviewer_panel_analysis']
        if 'section_diagnostics' in sc0:
            section_diags[pid] = sc0['section_diagnostics']
        if 'native_venue_scales' in sc0:
            native_scales_map[pid] = sc0['native_venue_scales']
        if 'merit_vs_packaging' in sc0:
            merit_packaging_map[pid] = sc0['merit_vs_packaging']
        if 'deal_breaker_sensitivity' in sc0:
            deal_breaker_map[pid] = sc0['deal_breaker_sensitivity']
        if 'what_if_roi' in sc0 and (what_if or pid == eff_target_id or idx == 0):
            what_if_map[pid] = sc0['what_if_roi']

    subfield_readiness_top = None
    if eff_preset is not None:
        target_prof = next((p for p in profiles if p['id'] == eff_target_id), profiles[0])
        merged_checks = dict(document.get('subfield_checks') or {})
        if isinstance(target_prof.get('subfield_checks'), dict):
            merged_checks.update(target_prof['subfield_checks'])
        subfield_readiness_top = evaluate_subfield_readiness(eff_preset, merged_checks)

    evidence_anchor_table = None
    target_for_anchor = next((p for p in profiles if p['id'] == eff_target_id), None)
    if target_for_anchor is not None and isinstance(document.get('evidence_anchors'), list):
        evidence_anchor_table = build_evidence_anchor_table(target_for_anchor, document['evidence_anchors'])
    elif target_for_anchor is not None:
        anchor_cands = [
            p for p in profiles
            if p['id'] != eff_target_id
            and (isinstance(p.get('evidence_profile'), dict) or isinstance(p.get('evidence_anchors'), dict))
        ]
        if len(anchor_cands) >= 2:
            evidence_anchor_table = build_evidence_anchor_table(target_for_anchor, anchor_cands[:3])

    def _attach_m9a_fields(out_dict):
        if eff_mode != 'paper':
            out_dict['mode'] = eff_mode
        if eff_vtype is not None:
            out_dict['venue_type'] = eff_vtype
            out_dict['venue_type_profile'] = evaluate_venue_profile_checks(eff_vtype, document)
        if eff_preset is not None:
            out_dict['subfield_preset'] = eff_preset
            out_dict['subfield_readiness'] = subfield_readiness_top
        if sanity_warnings_by_pid:
            out_dict['sanity_warnings'] = sanity_warnings_by_pid
            out_dict['sanity_warnings_list'] = all_sanity_warnings
        if native_scales_map:
            out_dict['native_venue_scales'] = native_scales_map
        if merit_packaging_map:
            out_dict['merit_vs_packaging'] = merit_packaging_map
        if deal_breaker_map:
            out_dict['deal_breaker_sensitivity'] = deal_breaker_map
        if what_if_map:
            out_dict['what_if_roi'] = what_if_map
        if reviewer_panels:
            out_dict['reviewer_panel_analysis'] = reviewer_panels
        if section_diags:
            out_dict['section_diagnostics'] = section_diags
        if evidence_anchor_table is not None:
            out_dict['evidence_anchor_table'] = evidence_anchor_table
        if linkage_summary is not None:
            out_dict['linkage_summary'] = linkage_summary

    missing_rating_only = bool(issues) and all(iss.startswith('missing_rating:') for iss in issues)
    if issues:
        out = {
            'status': 'not_comparable',
            'issues': sorted(set(issues)),
            'rankings': [],
            'submission_readiness': per_paper_sr,
            'unscored_closest_work_ids': unscored_by_profile,
            'warning': (
                'Missing ratings cannot be silently reweighted.'
                if missing_rating_only
                else 'This structural checker cannot validate the locators, closest-work equivalence, or ratings.'
            ),
        }
        if related_work_comparison is not None:
            out['related_work_comparison'] = related_work_comparison
        if locator_verification is not None:
            out['locator_verification'] = locator_verification
        _attach_m9a_fields(out)
        return out

    rankings = []
    for index, per_profile in enumerate(scenario_scores):
        results = [(pid, calculated['weighted_unrounded']) for pid, calculated in per_profile]
        with localcontext(BasicContext) as ctx:
            ctx.prec = 28
            ordered = sorted(results, key=lambda x: (-Decimal(x[1]), x[0]))
        rankings.append({
            'scenario': index + 1,
            'ordered': [{'id': pid, 'weighted_unrounded': raw} for pid, raw in ordered],
            'top_tied': len(ordered) > 1 and ordered[0][1] == ordered[1][1],
        })

    leaders = {
        tuple(
            row['id']
            for row in ranking['ordered']
            if row['weighted_unrounded'] == ranking['ordered'][0]['weighted_unrounded']
        )
        for ranking in rankings
    }
    out = {
        'status': 'structurally_comparable',
        'rankings': rankings,
        'ranking_sensitivity': 'stable_top_within_supplied_weights' if len(leaders) == 1 else 'top_changes_across_supplied_weights',
        'submission_readiness': per_paper_sr,
        'unscored_closest_work_ids': unscored_by_profile,
        'warning': 'No source text or rating is verified. Stability applies only to the supplied weight scenarios, not all defensible weights or reviewer judgments.',
    }
    if related_work_comparison is not None:
        out['related_work_comparison'] = related_work_comparison
    if locator_verification is not None:
        out['locator_verification'] = locator_verification
    _attach_m9a_fields(out)
    if eff_mode == 'idea' or eff_goal is not None:
        out['pareto_frontier'] = _compute_pareto_frontier(profiles, scenario_scores, eff_goal)
    return out


def _encoded_utf8_len(obj):
    return len(json.dumps(obj, ensure_ascii=False).encode('utf-8'))


def _truncate_artifact_path(path_str, max_bytes=180):
    if not isinstance(path_str, str):
        return path_str
    if len(path_str.encode('utf-8')) <= max_bytes:
        return path_str
    name = Path(path_str).name
    candidate = '.../' + name if name else ''
    if candidate and len(candidate.encode('utf-8')) <= max_bytes:
        return candidate
    suffix = path_str
    while len(('...' + suffix).encode('utf-8')) > max_bytes and len(suffix) > 1:
        suffix = suffix[max(1, len(suffix) // 4):]
    return '...' + suffix


def _compact_output(result, out_path=None):
    if result.get('mode') == 'revision_diff':
        compact = {
            'compact': True,
            'mode': 'revision_diff',
            'status': result.get('status'),
            'target_id': result.get('target_id'),
            'suspected_grade_inflation': result.get('suspected_grade_inflation'),
            'v1_weighted_unrounded': result.get('v1_weighted_unrounded'),
            'v2_weighted_unrounded': result.get('v2_weighted_unrounded'),
            'weighted_delta': result.get('weighted_delta'),
            'dimension_deltas': result.get('dimension_deltas'),
            'unsubstantiated_gain_dimensions': result.get('unsubstantiated_gain_dimensions'),
            'inflation_warnings': (result.get('inflation_warnings') or [])[:10],
            'resolved_fatal_dimensions': result.get('resolved_fatal_dimensions'),
            'remaining_fatal_dimensions': result.get('remaining_fatal_dimensions'),
            'resolved_v1_defects': (result.get('resolved_v1_defects') or [])[:8],
            'remaining_v1_defects': (result.get('remaining_v1_defects') or [])[:8],
            'artifact_path': out_path,
        }
        trim = 0
        while _encoded_utf8_len(compact) > 3950:
            if trim == 0:
                compact['artifact_path'] = _truncate_artifact_path(compact.get('artifact_path'), 180)
                compact['inflation_warnings'] = [w[:100] for w in compact['inflation_warnings'][:4]]
            elif trim == 1:
                compact['resolved_v1_defects'] = compact['resolved_v1_defects'][:3]
                compact['remaining_v1_defects'] = compact['remaining_v1_defects'][:3]
            else:
                compact['inflation_warnings'] = []
                compact['resolved_v1_defects'] = []
                compact['remaining_v1_defects'] = []
                compact['artifact_path'] = _truncate_artifact_path(compact.get('artifact_path'), 64)
                if _encoded_utf8_len(compact) > 3950:
                    compact['artifact_path'] = None
                break
            trim += 1
        return compact

    issues = result.get('issues') or []
    sr_items = list((result.get('submission_readiness') or {}).items())
    max_sr = 6 if len(sr_items) > 6 else len(sr_items)
    compact_sr = {}
    for pid, entry in sr_items[:max_sr]:
        row = {
            'overall': entry.get('overall'),
            'weighted_unrounded': entry.get('weighted_unrounded'),
            'band': entry.get('band'),
            'ready_for_top_tier_main_track': entry.get('ready_for_top_tier_main_track'),
            'ready_for_findings_or_tier_a': entry.get('ready_for_findings_or_tier_a'),
            'fatal_gate_triggered': entry.get('fatal_gate_triggered'),
            'fatal_dimensions': entry.get('fatal_dimensions'),
            'bottleneck_dimensions': entry.get('bottleneck_dimensions'),
            'delta_to_competitive_top_tier': entry.get('delta_to_competitive_top_tier'),
            'structural_gate_passed': entry.get('structural_gate_passed'),
            'band_stable_across_scenarios': entry.get('band_stable_across_scenarios'),
            'guidance': (entry.get('guidance') or '')[:140],
        }
        if 'idea_viability_band' in entry:
            row['idea_viability_band'] = entry['idea_viability_band']
        compact_sr[pid] = row
    raw_rankings = result.get('rankings') or []
    compact_rankings = [
        {
            'scenario': r.get('scenario'),
            'ordered': (r.get('ordered') or [])[:10],
            'top_tied': r.get('top_tied'),
        }
        for r in raw_rankings[:5]
    ]
    raw_unscored = result.get('unscored_closest_work_ids') or {}
    compact_unscored = {
        k: v[:5]
        for k, v in list(raw_unscored.items())[:8]
        if v
    }
    rwc = result.get('related_work_comparison')
    compact_rwc = None
    if isinstance(rwc, dict):
        compact_rwc = {
            'target_id': rwc.get('target_id'),
            'strict_related_panel': rwc.get('strict_related_panel'),
            'min_related': rwc.get('min_related'),
            'scored_related_ids': (rwc.get('scored_related_ids') or [])[:10],
            'scored_related_count': len(rwc.get('scored_related_ids') or []),
            'unscored_closest_work_ids': (rwc.get('unscored_closest_work_ids') or [])[:10],
            'best_related_overall': rwc.get('best_related_overall'),
            'target_delta_vs_best_related_overall': rwc.get('target_delta_vs_best_related_overall'),
            'max_related_by_dimension': rwc.get('max_related_by_dimension'),
            'dimension_deltas_vs_max_related': rwc.get('dimension_deltas_vs_max_related'),
            'novelty_inflation_warnings': (rwc.get('novelty_inflation_warnings') or [])[:10],
        }

    loc_ver = result.get('locator_verification')
    loc_summary = None
    if isinstance(loc_ver, dict):
        loc_summary = {k: v for k, v in loc_ver.items() if k != 'skipped_files'}
        if isinstance(loc_ver.get('skipped_files'), list):
            loc_summary['skipped_files_count'] = len(loc_ver['skipped_files'])

    compact = {
        'compact': True,
        'status': result.get('status'),
        'ranking_sensitivity': result.get('ranking_sensitivity'),
        'rankings': compact_rankings,
        'submission_readiness': compact_sr,
        'submission_readiness_truncated': max(0, len(sr_items) - len(compact_sr)),
        'unscored_closest_work_ids': compact_unscored,
        'related_work_comparison': compact_rwc,
        'locator_verification': loc_summary,
        'issue_count': len(issues),
        'issues': issues[:15],
        'issues_truncated': max(0, len(issues) - min(15, len(issues))),
        'artifact_path': out_path,
    }
    for opt_k in ('mode', 'venue_type', 'subfield_preset'):
        if result.get(opt_k) is not None:
            compact[opt_k] = result[opt_k]
    if isinstance(result.get('subfield_readiness'), dict):
        sfr = result['subfield_readiness']
        compact['subfield_readiness'] = {
            'preset': sfr.get('preset'),
            'passed_count': len(sfr.get('passed_checks') or []),
            'failed_checks': sfr.get('failed_checks'),
            'missing_checks': sfr.get('missing_checks'),
            'subfield_checks_passed': sfr.get('subfield_checks_passed'),
        }
    if isinstance(result.get('pareto_frontier'), dict):
        pf = result['pareto_frontier']
        compact['pareto_frontier'] = {
            'goal': pf.get('goal'),
            'frontier_ids': (pf.get('frontier_ids') or [])[:8],
            'goal_ranked_ids': (pf.get('goal_ranked_ids') or [])[:8],
        }
    if result.get('sanity_warnings_list'):
        compact['sanity_warnings'] = result['sanity_warnings_list'][:8]
    if isinstance(result.get('reviewer_panel_analysis'), dict):
        compact['reviewer_panel_summary'] = {
            pid: {
                'confidence_weighted_mean': rpa.get('confidence_weighted_mean'),
                'variance_risk': rpa.get('variance_risk'),
                'assassin_reviewer_flag': rpa.get('assassin_reviewer_flag'),
                'meta_review_verdict': rpa.get('meta_review_verdict'),
            }
            for pid, rpa in list(result['reviewer_panel_analysis'].items())[:3]
        }
    if isinstance(result.get('linkage_summary'), dict):
        ls = result['linkage_summary']
        compact['linkage_summary'] = {
            'gap_record_valid': ls.get('gap_record_valid'),
            'question_card_valid': ls.get('question_card_valid'),
            'seed_bundle_linked': ls.get('seed_bundle_linked'),
            'portfolio_distinct_ideas': ls.get('portfolio_distinct_ideas'),
            'portfolio_distinct_angles': ls.get('portfolio_distinct_angles'),
        }

    # Deterministic budget enforcement (< 4096 UTF-8 bytes)
    m9a_opt_keys = (
        'reviewer_panel_summary',
        'sanity_warnings',
        'linkage_summary',
        'subfield_readiness',
        'pareto_frontier',
    )
    trim_stage = 0
    while _encoded_utf8_len(compact) > 3950:
        if trim_stage == 0:
            compact['artifact_path'] = _truncate_artifact_path(compact.get('artifact_path'), 180)
            if _encoded_utf8_len(compact) > 3950:
                for row in compact['submission_readiness'].values():
                    row.pop('guidance', None)
        elif trim_stage == 1:
            if compact['issues']:
                compact['issues'] = [s[:100] for s in compact['issues'][:5]]
                compact['issues_truncated'] = max(0, len(issues) - len(compact['issues']))
        elif trim_stage == 2:
            if compact['rankings']:
                compact['rankings'] = compact['rankings'][:2]
                for r in compact['rankings']:
                    r['ordered'] = (r.get('ordered') or [])[:5]
        elif trim_stage == 3:
            if len(compact['submission_readiness']) > 3:
                keep_ids = []
                t_id = (compact_rwc or {}).get('target_id')
                if t_id and t_id in compact['submission_readiness']:
                    keep_ids.append(t_id)
                for pid in list(compact['submission_readiness']):
                    if pid not in keep_ids and len(keep_ids) < 3:
                        keep_ids.append(pid)
                compact['submission_readiness'] = {k: compact['submission_readiness'][k] for k in keep_ids}
                compact['submission_readiness_truncated'] = max(0, len(sr_items) - len(compact['submission_readiness']))
        elif trim_stage == 4:
            if compact['rankings']:
                compact['rankings'] = compact['rankings'][:1]
                compact['rankings'][0]['ordered'] = (compact['rankings'][0].get('ordered') or [])[:3]
            for mk in m9a_opt_keys[:3]:
                compact.pop(mk, None)
        elif trim_stage == 5:
            compact['issues'] = compact['issues'][:2]
            compact['issues_truncated'] = max(0, len(issues) - len(compact['issues']))
            compact['unscored_closest_work_ids'] = {
                k: v[:2] for k, v in list(compact['unscored_closest_work_ids'].items())[:3]
            }
            for mk in m9a_opt_keys:
                compact.pop(mk, None)
        elif trim_stage == 6:
            if isinstance(compact['related_work_comparison'], dict):
                rw = compact['related_work_comparison']
                rw['scored_related_ids'] = rw['scored_related_ids'][:3]
                rw['unscored_closest_work_ids'] = rw['unscored_closest_work_ids'][:3]
                rw['novelty_inflation_warnings'] = rw['novelty_inflation_warnings'][:3]
                if _encoded_utf8_len(compact) > 3950:
                    rw.pop('dimension_deltas_vs_max_related', None)
                    rw.pop('max_related_by_dimension', None)
        elif trim_stage == 7:
            if len(compact['submission_readiness']) > 1:
                first_k = next(iter(compact['submission_readiness']))
                compact['submission_readiness'] = {first_k: compact['submission_readiness'][first_k]}
                compact['submission_readiness_truncated'] = max(0, len(sr_items) - 1)
        elif trim_stage == 8:
            compact['issues'] = []
            compact['issues_truncated'] = len(issues)
            compact['unscored_closest_work_ids'] = {}
            if isinstance(compact.get('locator_verification'), dict):
                compact['locator_verification'].pop('sources_dir', None)
        elif trim_stage == 9:
            compact['artifact_path'] = _truncate_artifact_path(compact.get('artifact_path'), 64)
            compact['rankings'] = []
        else:
            compact['related_work_comparison'] = None
            compact['locator_verification'] = (
                {'skipped_files_count': loc_summary['skipped_files_count']}
                if isinstance(loc_summary, dict) and 'skipped_files_count' in loc_summary
                else None
            )
            if _encoded_utf8_len(compact) > 3950:
                compact['locator_verification'] = None
                compact['artifact_path'] = None
            break
        trim_stage += 1
    return compact


def _reject_nonfinite(token):
    raise ValueError(f'Non-finite JSON constant not allowed: {token}')


def _require_nonempty_path(val, flag):
    if not isinstance(val, str) or not val.strip():
        raise ValueError(f'Empty or invalid path for {flag}')
    return val.strip()


def _load_json_file(path_str, flag):
    p = Path(_require_nonempty_path(path_str, flag))
    return json.loads(p.read_text(encoding='utf-8'), parse_constant=_reject_nonfinite)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scorecards_json', nargs='?', default=None)
    parser.add_argument('--sources-dir', default=None, help='Optional directory of local source files (.txt, .md, .json, .pdf) for locator verification')
    parser.add_argument('--target-id', default=None, help='Optional target profile ID for closest-related-work comparison')
    parser.add_argument('--strict-related-panel', action='store_true', help='Require target closest_work entries and >= min-related distinct full-text profiles to be scored')
    parser.add_argument('--min-related', type=int, default=None, help='Minimum distinct scored related profiles required (default: 3 with --strict-related-panel)')
    parser.add_argument('--venue-type', default=None, choices=sorted(VENUE_TYPE_PROFILES), help='Optional venue-type profile')
    parser.add_argument('--venue-profile', default=None, choices=sorted(VENUE_TYPE_PROFILES), help='Alias for --venue-type')
    parser.add_argument('--mode', default=None, choices=['auto', 'paper', 'idea'], help='Comparison mode (paper or idea)')
    parser.add_argument('--goal', default=None, choices=sorted(IDEA_GOAL_MODES), help='Goal-conditioned Pareto ranking mode for idea evaluation')
    parser.add_argument('--subfield-preset', default=None, choices=sorted(SUBFIELD_PRESETS), help='Optional AI/CS subfield depth preset')
    parser.add_argument('--gap-record', default=None, help='Optional gap_record.json for idea mode linkage validation')
    parser.add_argument('--question-card', default=None, help='Optional question_card.json for idea mode linkage validation')
    parser.add_argument('--idea-seed-bundle', default=None, help='Optional research_scientist_idea_seed_bundle_v1 JSON for linkage')
    parser.add_argument('--seed-bundle', default=None, help='Alias for --idea-seed-bundle')
    parser.add_argument('--require-idea-portfolio', action='store_true', help='Require 3-4 non-redundant ideas across >=3 angles in idea mode')
    parser.add_argument('--require-pre-mortem', action='store_true', help='Require pre_mortem (top_failure_modes, 1-2d killer_experiment, pivot_path) in idea mode')
    parser.add_argument('--what-if', action='store_true', help='Include What-If Score-Lift ROI simulations for all profiles')
    parser.add_argument('--revision-diff', nargs=2, metavar=('V1_JSON', 'V2_JSON'), default=None, help='Compare v1 vs v2 scorecards and audit against grade inflation')
    parser.add_argument('--out', default=None, help='Optional output JSON file path for full report')
    parser.add_argument('--compact', action='store_true', help='Emit compact bounded summary JSON to stdout')
    args = parser.parse_args(argv)
    try:
        if args.out is not None:
            _require_nonempty_path(args.out, '--out')
        if args.sources_dir is not None:
            _require_nonempty_path(args.sources_dir, '--sources-dir')
        if args.target_id is not None:
            _require_nonempty_path(args.target_id, '--target-id')
        if args.venue_type and args.venue_profile and args.venue_type != args.venue_profile:
            raise ValueError('--venue-type and --venue-profile cannot conflict')
        if args.idea_seed_bundle and args.seed_bundle and args.idea_seed_bundle != args.seed_bundle:
            raise ValueError('--idea-seed-bundle and --seed-bundle cannot conflict')

        if args.revision_diff is not None:
            if args.scorecards_json is not None:
                raise ValueError('Provide either scorecards_json or --revision-diff, not both')
            v1_doc = _load_json_file(args.revision_diff[0], '--revision-diff v1')
            v2_doc = _load_json_file(args.revision_diff[1], '--revision-diff v2')
            result = revision_diff(v1_doc, v2_doc, sources_dir=args.sources_dir, target_id=args.target_id)
            passed = result['status'] == 'verified_revision'
        else:
            if args.scorecards_json is None:
                raise ValueError('scorecards_json is required unless --revision-diff is provided')
            sc_doc = _load_json_file(args.scorecards_json, 'scorecards_json')
            gap_rec = _load_json_file(args.gap_record, '--gap-record') if args.gap_record is not None else None
            q_card = _load_json_file(args.question_card, '--question-card') if args.question_card is not None else None
            seed_path = args.idea_seed_bundle or args.seed_bundle
            seed_bundle = _load_json_file(seed_path, '--idea-seed-bundle') if seed_path is not None else None
            result = compare(
                sc_doc,
                sources_dir=args.sources_dir,
                target_id=args.target_id,
                strict_related_panel=(True if args.strict_related_panel else None),
                min_related=args.min_related,
                venue_type=(args.venue_type or args.venue_profile),
                mode=args.mode,
                goal=args.goal,
                subfield_preset=args.subfield_preset,
                gap_record=gap_rec,
                question_card=q_card,
                idea_seed_bundle=seed_bundle,
                require_idea_portfolio=bool(args.require_idea_portfolio),
                require_pre_mortem=bool(args.require_pre_mortem),
                what_if=bool(args.what_if),
            )
            passed = result['status'] == 'structurally_comparable'

        full_rendered = json.dumps(result, ensure_ascii=False)
        out_str = None
        if args.out is not None:
            out_path = Path(args.out.strip())
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(full_rendered + '\n', encoding='utf-8')
            out_str = str(out_path)
        if args.compact:
            print(json.dumps(_compact_output(result, out_str), ensure_ascii=False))
        else:
            print(full_rendered)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
