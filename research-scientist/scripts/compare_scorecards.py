#!/usr/bin/env python3
"""Check scorecard completeness and ranking sensitivity under declared weights."""
import argparse
import html
import json
import re
import sys
import unicodedata
from decimal import BasicContext, Decimal, ROUND_HALF_UP, localcontext
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
    eff_target_id, profiles, scenario_scores, issues_by_pid, eff_min_related, eff_strict
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
            for d in DIMENSIONS
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
                for d in DIMENSIONS
            }

    warnings = []
    if target_item is not None and isinstance(target_item.get('ratings'), dict):
        t_nov = target_item['ratings'].get('novelty')
        if type(t_nov) is int and t_nov >= 7:
            contrib_delta = target_item.get('contribution_delta') or target_item.get('target_contribution_delta')
            if not isinstance(contrib_delta, str) or not contrib_delta.strip():
                warnings.append('novelty_inflation_risk:missing_contribution_delta')
            if dim_deltas_vs_max is not None and (
                (dim_deltas_vs_max['soundness'] is not None and dim_deltas_vs_max['soundness'] < 0)
                or (dim_deltas_vs_max['evidence'] is not None and dim_deltas_vs_max['evidence'] < 0)
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


def compare(
    document,
    sources_dir=None,
    target_id=None,
    strict_related_panel=None,
    min_related=None,
):
    if not isinstance(document, dict) or not isinstance(document.get('profiles'), list) or len(document['profiles']) < 2:
        raise ValueError('at least two profiles are required')
    scenarios = document.get('weight_scenarios')
    if not isinstance(scenarios, list) or not scenarios:
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
            score_input = {'weights': weights, 'ratings': item['ratings']}
            if 'status' in item:
                score_input['status'] = item['status']
            if 'object_type' in item:
                score_input['object_type'] = item['object_type']
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
        if not isinstance(locators, dict) or set(locators) != set(DIMENSIONS):
            _record_issue(f'evidence_locators_incomplete:{pid}', pid)
        else:
            for dimension in DIMENSIONS:
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
    if (eff_strict or eff_min_related is not None) and eff_target_id is None:
        _record_issue('target_id_required_for_strict_related_panel', None)

    if eff_target_id is not None:
        target_exists = any(p['id'] == eff_target_id for p in profiles)
        if not target_exists:
            _record_issue(f'target_profile_not_found:{eff_target_id}', None)
        related_work_comparison, target_unscored_cw, scored_related_ids = _build_related_work_comparison(
            eff_target_id, profiles, scenario_scores, issues_by_pid, eff_min_related, eff_strict
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

    missing_rating_only = bool(issues) and all(iss.startswith('missing_rating:') for iss in issues)
    if issues:
        out = {
            'status': 'not_comparable',
            'issues': sorted(set(issues)),
            'rankings': [],
            'submission_readiness': _build_per_paper_readiness(profiles, scenario_scores, issues_by_pid),
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
        'submission_readiness': _build_per_paper_readiness(profiles, scenario_scores, issues_by_pid),
        'unscored_closest_work_ids': unscored_by_profile,
        'warning': 'No source text or rating is verified. Stability applies only to the supplied weight scenarios, not all defensible weights or reviewer judgments.',
    }
    if related_work_comparison is not None:
        out['related_work_comparison'] = related_work_comparison
    if locator_verification is not None:
        out['locator_verification'] = locator_verification
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
    issues = result.get('issues') or []
    sr_items = list((result.get('submission_readiness') or {}).items())
    max_sr = 6 if len(sr_items) > 6 else len(sr_items)
    compact_sr = {}
    for pid, entry in sr_items[:max_sr]:
        compact_sr[pid] = {
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

    # Deterministic budget enforcement (< 4096 UTF-8 bytes)
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
        elif trim_stage == 5:
            compact['issues'] = compact['issues'][:2]
            compact['issues_truncated'] = max(0, len(issues) - len(compact['issues']))
            compact['unscored_closest_work_ids'] = {
                k: v[:2] for k, v in list(compact['unscored_closest_work_ids'].items())[:3]
            }
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scorecards_json')
    parser.add_argument('--sources-dir', default=None, help='Optional directory of local source files (.txt, .md, .json, .pdf) for locator verification')
    parser.add_argument('--target-id', default=None, help='Optional target profile ID for closest-related-work comparison')
    parser.add_argument('--strict-related-panel', action='store_true', help='Require target closest_work entries and >= min-related distinct full-text profiles to be scored')
    parser.add_argument('--min-related', type=int, default=None, help='Minimum distinct scored related profiles required (default: 3 with --strict-related-panel)')
    parser.add_argument('--out', default=None, help='Optional output JSON file path for full report')
    parser.add_argument('--compact', action='store_true', help='Emit compact bounded summary JSON to stdout')
    args = parser.parse_args(argv)
    try:
        sc_path = Path(_require_nonempty_path(args.scorecards_json, 'scorecards_json'))
        if args.out is not None:
            _require_nonempty_path(args.out, '--out')
        if args.sources_dir is not None:
            _require_nonempty_path(args.sources_dir, '--sources-dir')
        if args.target_id is not None:
            _require_nonempty_path(args.target_id, '--target-id')
        result = compare(
            json.loads(sc_path.read_text(encoding='utf-8'), parse_constant=_reject_nonfinite),
            sources_dir=args.sources_dir,
            target_id=args.target_id,
            strict_related_panel=(True if args.strict_related_panel else None),
            min_related=args.min_related,
        )
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
    return 0 if result['status'] == 'structurally_comparable' else 1


if __name__ == '__main__':
    sys.exit(main())
