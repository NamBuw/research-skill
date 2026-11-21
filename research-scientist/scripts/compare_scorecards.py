#!/usr/bin/env python3
"""Check scorecard completeness and ranking sensitivity under declared weights."""
import argparse
import html
import json
import re
import sys
import unicodedata
from decimal import BasicContext, Decimal, localcontext
from pathlib import Path

from score_math import DIMENSIONS, score

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


def compare(document, sources_dir=None):
    if not isinstance(document, dict) or not isinstance(document.get('profiles'), list) or len(document['profiles']) < 2:
        raise ValueError('at least two profiles are required')
    scenarios = document.get('weight_scenarios')
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError('weight_scenarios must be a nonempty list')
    profiles = document['profiles']
    for item in profiles:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id'].strip():
            raise ValueError('each profile needs a nonblank id')
        if 'ratings' not in item:
            raise ValueError(f'missing ratings for profile {item["id"]}')

    # Validate weights and ratings upfront so invalid ratings/weights are never masked
    # by early structural issues (e.g. reading_basis != 'full_text' or missing locators).
    scenario_scores = []
    for weights in scenarios:
        per_profile = []
        for item in profiles:
            calculated = score({'weights': weights, 'ratings': item['ratings']})
            per_profile.append((item['id'], calculated))
        scenario_scores.append(per_profile)

    issues = []
    ids = set()
    for item in profiles:
        pid = item['id']
        if pid in ids:
            issues.append(f'duplicate_profile:{pid}')
        ids.add(pid)
        if item.get('reading_basis') != 'full_text':
            issues.append(f'full_text_not_confirmed:{pid}')
        if not isinstance(item.get('closest_work'), list) or not item['closest_work']:
            issues.append(f'closest_work_missing:{pid}')
        elif any(not isinstance(x, str) or not x.strip() for x in item['closest_work']):
            issues.append(f'invalid_closest_work:{pid}')
        locators = item.get('evidence_locators')
        if not isinstance(locators, dict) or set(locators) != set(DIMENSIONS):
            issues.append(f'evidence_locators_incomplete:{pid}')
        else:
            for dimension in DIMENSIONS:
                value = locators[dimension]
                if not isinstance(value, list) or not value or any(not isinstance(x, str) or not x.strip() for x in value):
                    issues.append(f'missing_locator:{pid}:{dimension}')

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
            for dimension in DIMENSIONS:
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
                        issues.append(f'locator_unverified:{pid}:{dimension}:{loc_idx}:{reason}')
        locator_verification = {
            'sources_dir': str(index['root']),
            'sources_indexed': index['sources_indexed'],
            'skipped_files': index['skipped_files'],
            'checked': checked,
            'verified': verified,
            'failed': failed,
        }

    if issues:
        out = {
            'status': 'not_comparable',
            'issues': sorted(set(issues)),
            'rankings': [],
            'warning': 'This structural checker cannot validate the locators, closest-work equivalence, or ratings.',
        }
        if locator_verification is not None:
            out['locator_verification'] = locator_verification
        return out

    rankings = []
    for index, per_profile in enumerate(scenario_scores):
        results = []
        for pid, calculated in per_profile:
            if calculated['status'] != 'calculated':
                issues.append(f'missing_rating:{pid}')
            else:
                results.append((pid, calculated['weighted_unrounded']))
        if issues:
            continue
        with localcontext(BasicContext) as ctx:
            ctx.prec = 28
            ordered = sorted(results, key=lambda x: (-Decimal(x[1]), x[0]))
        rankings.append({
            'scenario': index + 1,
            'ordered': [{'id': pid, 'weighted_unrounded': raw} for pid, raw in ordered],
            'top_tied': len(ordered) > 1 and ordered[0][1] == ordered[1][1],
        })
    if issues:
        out = {
            'status': 'not_comparable',
            'issues': sorted(set(issues)),
            'rankings': [],
            'warning': 'Missing ratings cannot be silently reweighted.',
        }
        if locator_verification is not None:
            out['locator_verification'] = locator_verification
        return out

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
        'warning': 'No source text or rating is verified. Stability applies only to the supplied weight scenarios, not all defensible weights or reviewer judgments.',
    }
    if locator_verification is not None:
        out['locator_verification'] = locator_verification
    return out


def _compact_output(result, out_path=None):
    issues = result.get('issues') or []
    return {
        'compact': True,
        'status': result.get('status'),
        'ranking_sensitivity': result.get('ranking_sensitivity'),
        'rankings': (result.get('rankings') or [])[:10],
        'locator_verification': result.get('locator_verification'),
        'issue_count': len(issues),
        'issues': issues[:20],
        'issues_truncated': max(0, len(issues) - 20),
        'artifact_path': out_path,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scorecards_json')
    parser.add_argument('--sources-dir', default=None, help='Optional directory of local source files (.txt, .md, .json, .pdf) for locator verification')
    parser.add_argument('--out', default=None, help='Optional output JSON file path for full report')
    parser.add_argument('--compact', action='store_true', help='Emit compact bounded summary JSON to stdout')
    args = parser.parse_args(argv)
    try:
        result = compare(
            json.loads(Path(args.scorecards_json).read_text(encoding='utf-8')),
            sources_dir=args.sources_dir,
        )
        full_rendered = json.dumps(result, ensure_ascii=False)
        out_str = None
        if args.out:
            out_path = Path(args.out)
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
    return 0 if result['status'] == 'structurally_comparable' else 1


if __name__ == '__main__':
    sys.exit(main())
