#!/usr/bin/env python3
"""Check the audit trail behind a proposed research gap.

This checks internal links and minimum evidence gates. It cannot judge source
accuracy, search recall, scientific importance, or whether a gap is real.
"""
import argparse
import json
import re
import sys
from pathlib import Path

DISPOSITIONS = {'not_a_gap', 'early_signal', 'supported_candidate', 'insufficient_evidence'}
ACCESS = {'full_text', 'selected_full_text', 'abstract', 'metadata', 'unavailable'}
RELATIONS = {'direct_precedent', 'partial_precedent', 'adjacent_precedent', 'counterevidence', 'analogy_only'}
QUERY_STATES = {'complete', 'bounded_partial', 'valid_zero_results', 'rate_limited', 'bot_blocked', 'source_failed', 'failed', 'not_run'}
SUCCESS = {'complete', 'bounded_partial', 'valid_zero_results'}
EVIDENCE_ROLES = {'result', 'method', 'assumption', 'limitation', 'author_future_work', 'context'}
KILL_FAMILIES = {'closure', 'adversarial', 'alternate_vocabulary', 'citation_trail'}
_STOPWORDS = frozenset({
    'the', 'and', 'for', 'that', 'this', 'with', 'from', 'into', 'are', 'was',
    'were', 'been', 'have', 'has', 'had', 'not', 'but', 'can', 'will', 'only',
    'such', 'when', 'where', 'which', 'than', 'then', 'they', 'their', 'there',
    'these', 'those', 'both', 'each', 'some', 'more', 'most', 'other', 'about',
    'under', 'over', 'across', 'between', 'through', 'during', 'before', 'after',
})
_NEGATION_TOKENS = frozenset({
    'no', 'not', 'never', 'without', 'lack', 'lacks', 'lacked', 'lacking',
    'cannot', 'none', 'neither', 'nor',
    'cant', 'dont', 'doesnt', 'didnt', 'isnt', 'arent', 'wasnt', 'werent',
    'wont', 'wouldnt', 'couldnt', 'shouldnt', 'havent', 'hasnt', 'hadnt',
    'mustnt', 'neednt',
    "can't", "don't", "doesn't", "didn't", "isn't", "aren't", "wasn't", "weren't",
    "won't", "wouldn't", "couldn't", "shouldn't", "haven't", "hasn't", "hadn't",
    "mustn't", "needn't",
})
_CONTRACTION_CANON = {
    "can't": 'cant', "don't": 'dont', "doesn't": 'doesnt', "didn't": 'didnt',
    "isn't": 'isnt', "aren't": 'arent', "wasn't": 'wasnt', "weren't": 'werent',
    "won't": 'wont', "wouldn't": 'wouldnt', "couldn't": 'couldnt', "shouldn't": 'shouldnt',
    "haven't": 'havent', "hasn't": 'hasnt', "hadn't": 'hadnt',
    "mustn't": 'mustnt', "needn't": 'neednt',
}
_PRE_NEG_CUE_RE = re.compile(
    r"\b(?:no|not|never|neither|nor|without|lack(?:s|ed|ing)?|cannot|"
    r"can't|cant|don't|dont|doesn't|doesnt|didn't|didnt|isn't|isnt|aren't|arent|"
    r"wasn't|wasnt|weren't|werent|won't|wont|wouldn't|wouldnt|couldn't|couldnt|"
    r"shouldn't|shouldnt|haven't|havent|hasn't|hasnt|hadn't|hadnt|mustn't|mustnt|needn't|neednt|"
    r"(?:fail(?:s|ed|ing)?|unable)\s+to|never\s+observe(?:d|s)?(?:\s+that)?|"
    r"not\s+(?:true|the\s+case|observe[ds]?|found|shown|supported)(?:\s+that)?)\b",
    re.I,
)
_FAIL_TO_RE = re.compile(r'\b(?:fail(?:s|ed|ing)?|unable)\s+to\b', re.I)
_SENTENCE_BOUNDARY_RE = re.compile(
    r'[!?;]+(?:\s+|$)|'
    r'(?<!\be\.g)(?<!\bi\.e)(?<!\bcf)(?<!\bsec)(?<!\bfig)'
    r'(?<!\beq)(?<!\bal)(?<!\bdr)(?<!\bmr)(?<!\bvs)(?<!\bno)\.(?:\s+|$)',
    re.I,
)


def _nonblank(value):
    return isinstance(value, str) and bool(value.strip())


def _unscreened(query):
    retrieved, inspected = query.get('retrieved'), query.get('inspected')
    return (isinstance(retrieved, int) and not isinstance(retrieved, bool) and
            isinstance(inspected, int) and not isinstance(inspected, bool) and
            inspected < retrieved)


def _objects_by_id(items, label, errors):
    if not isinstance(items, list):
        errors.append(f'{label}:must_be_list')
        return {}
    indexed = {}
    for item in items:
        if not isinstance(item, dict) or not _nonblank(item.get('id')):
            errors.append(f'{label}:invalid_item_or_id')
            continue
        identifier = item['id']
        if identifier in indexed:
            errors.append(f'{label}:duplicate_id:{identifier}')
        indexed[identifier] = item
    return indexed


def _ids(item, field, label, known, errors):
    value = item.get(field)
    if not isinstance(value, list) or any(not _nonblank(x) for x in value):
        errors.append(f'{label}:{field}:must_be_id_list')
        return []
    for identifier in value:
        if identifier not in known:
            errors.append(f'{label}:{field}:unknown_id:{identifier}')
    return value


def _norm_ws(text):
    return re.sub(r'\s+', ' ', str(text or '')).casefold().strip()


def _content_tokens(text):
    return [t for t in re.findall(r'[a-z0-9]{3,}', str(text or '').casefold()) if t not in _STOPWORDS]


def _block_text(block):
    if not isinstance(block, dict):
        return ''
    parts = [str(block.get('text') or ''), str(block.get('caption') or '')]
    if isinstance(block.get('headers'), list):
        parts.extend(str(x) for x in block['headers'])
    if isinstance(block.get('rows'), list):
        for row in block['rows']:
            if isinstance(row, list):
                parts.extend(str(c) for c in row)
    return ' '.join(p for p in parts if p)


def _index_evidence_dir(evidence_dir):
    ev_path = Path(evidence_dir)
    if not ev_path.is_dir():
        raise ValueError(f'evidence_dir not found: {evidence_dir}')
    docs = []
    for json_file in sorted(ev_path.rglob('*.json')):
        raw = json.loads(json_file.read_text(encoding='utf-8'))
        pages_map = {}
        meta_parts = [json_file.stem]
        num_pages = 0
        if isinstance(raw, dict) and isinstance(raw.get('pages'), list):
            num_pages = len(raw['pages'])
            for k in ('source_path', 'title', 'source_id', 'doi', 'arxiv_id', 'openalex_id'):
                if raw.get(k):
                    meta_parts.append(str(raw[k]))
            for p_idx, page_blocks in enumerate(raw['pages']):
                if not isinstance(page_blocks, list):
                    continue
                for block in page_blocks:
                    if not isinstance(block, dict):
                        continue
                    idx = block.get('page_idx') if isinstance(block.get('page_idx'), int) else p_idx
                    pages_map.setdefault(idx, []).append(_block_text(block))
        elif isinstance(raw, list):
            for block in raw:
                if not isinstance(block, dict):
                    continue
                idx = block.get('page_idx') if isinstance(block.get('page_idx'), int) else 0
                pages_map.setdefault(idx, []).append(_block_text(block))
            num_pages = (max(pages_map.keys()) + 1) if pages_map else 0
        else:
            continue
        all_text = ' '.join(meta_parts + [' '.join(v) for v in pages_map.values()])
        docs.append({
            'path': json_file,
            'stem_norm': re.sub(r'[^a-z0-9]+', '', json_file.stem.casefold()),
            'pages_map': {k: _norm_ws(' '.join(v)) for k, v in pages_map.items()},
            'all_text': _norm_ws(all_text),
            'num_pages': num_pages,
        })
    return docs


def _candidate_tokens(entry):
    tokens = []
    for key in ('source_id', 'study_id'):
        val = str(entry.get(key) or '').strip()
        if not val:
            continue
        tokens.append(val)
        stripped = re.sub(r'^https?://(?:openalex\.org|doi\.org|arxiv\.org/abs)/', '', val, flags=re.I)
        stripped = re.sub(r'^(?:arxiv|doi):', '', stripped, flags=re.I)
        if stripped and stripped != val:
            tokens.append(stripped)
        norm = re.sub(r'[^a-z0-9]+', '', stripped.casefold())
        if len(norm) >= 5:
            tokens.append(norm)
    locator = str(entry.get('locator') or '')
    for m in re.findall(r'([A-Za-z0-9][A-Za-z0-9._-]{2,})\.(?:pdf|json|txt)', locator, flags=re.I):
        tokens.append(m)
        tokens.append(re.sub(r'_?(?:excerpt|blocks|paper)$', '', m, flags=re.I))
    return [t for t in tokens if len(t) >= 4]


def _match_docs(entry, docs):
    tokens = _candidate_tokens(entry)
    matched = []
    for doc in docs:
        stem = doc['stem_norm']
        all_text = doc['all_text']
        hit = False
        for tok in tokens:
            tok_alnum = re.sub(r'[^a-z0-9]+', '', tok.casefold())
            if tok_alnum and len(tok_alnum) >= 4 and (tok_alnum == stem or tok_alnum in stem or (len(stem) >= 6 and stem in tok_alnum)):
                hit = True
                break
            if len(tok) >= 5 and tok.casefold() in all_text:
                hit = True
                break
        if hit:
            matched.append(doc)
    return matched


def _anchor_ok(locator, search_text):
    for m in re.finditer(r'\b(equation|eq\.?|section|table|figure|fig\.?)\s*\(?(\d+(?:\.\d+)*)\)?', locator, flags=re.I):
        kind = m.group(1).casefold().rstrip('.')
        num = m.group(2).casefold()
        if kind in {'eq', 'equation'}:
            if not re.search(rf'\b(?:equation|eq\.?)\s*\(?\s*{re.escape(num)}\s*\)?', search_text):
                return False
        elif kind in {'fig', 'figure'}:
            if not re.search(rf'\b(?:figure|fig\.?)\s*\(?\s*{re.escape(num)}\s*\)?', search_text):
                return False
        else:
            if not re.search(rf'\b{re.escape(kind)}\s*\(?\s*{re.escape(num)}\s*\)?', search_text):
                return False
    return True


def _negation_tokens(text):
    norm = str(text or '').replace('\u2019', "'").replace('\u2018', "'").casefold()
    out = set()
    for tok in re.findall(r"[a-z0-9']+", norm):
        if tok in {'lacks', 'lacked', 'lacking'}:
            out.add('lack')
        elif tok in _CONTRACTION_CANON:
            out.add(_CONTRACTION_CANON[tok])
        elif tok in _NEGATION_TOKENS:
            out.add(tok)
    return out


def _sentence_spans(text):
    spans = []
    start = 0
    for m in _SENTENCE_BOUNDARY_RE.finditer(text):
        end = m.start() + len(m.group(0).rstrip())
        if end > start:
            spans.append((start, end))
        start = m.end()
    if start < len(text) and text[start:].strip():
        spans.append((start, len(text)))
    return spans or [(0, len(text))]


def _split_sentences(text):
    norm = _norm_ws(text)
    if not norm:
        return []
    return [norm[s:e].strip() for s, e in _sentence_spans(norm) if norm[s:e].strip()]


def _polarity_compatible(norm_target, window_text, strict_quote):
    t_neg = _negation_tokens(norm_target)
    w_neg = _negation_tokens(window_text)
    t_fail = bool(_FAIL_TO_RE.search(norm_target))
    w_fail = bool(_FAIL_TO_RE.search(window_text))
    if t_neg:
        if strict_quote and not t_neg.issubset(w_neg):
            return False
        if not strict_quote and not w_neg and not w_fail:
            return False
    elif w_neg or (w_fail and not t_fail):
        return False
    return True


def _text_matches(target, search_text, strict_quote=False):
    norm_target = _norm_ws(target)
    if not norm_target:
        return True
    t_neg = _negation_tokens(norm_target)
    t_fail = bool(_FAIL_TO_RE.search(norm_target))
    spans = _sentence_spans(search_text)
    pos = 0
    while True:
        idx = search_text.find(norm_target, pos)
        if idx == -1:
            break
        match_end = idx + len(norm_target)
        sent_start = max((s for s, _ in spans if s <= idx), default=0)
        sent_end = next((e for _, e in spans if match_end <= e), len(search_text))
        prefix_window = search_text[max(sent_start, idx - 80):idx]
        containing_sent = search_text[sent_start:sent_end]
        prefix_norm = prefix_window.replace('\u2019', "'").replace('\u2018', "'")
        pre_cue = bool(_PRE_NEG_CUE_RE.search(prefix_norm))
        prefix_neg = _negation_tokens(prefix_window)
        extra_sent_neg = _negation_tokens(containing_sent) - t_neg
        has_new_fail = bool(_FAIL_TO_RE.search(containing_sent)) and not t_fail
        if not (pre_cue and ((prefix_neg - t_neg) or _FAIL_TO_RE.search(prefix_norm))) and not extra_sent_neg and not has_new_fail:
            return True
        pos = idx + 1

    t_tokens = _content_tokens(norm_target)
    if not t_tokens:
        return False
    threshold = 0.85 if strict_quote else 0.75
    min_hits = min(3, len(t_tokens))
    t_token_set = set(t_tokens)
    segments = _split_sentences(search_text) or [search_text]
    n_target_sents = max(1, len(_split_sentences(norm_target)))
    max_win = min(len(segments), n_target_sents if strict_quote else max(2, n_target_sents))
    windows = []
    for win_size in range(1, max_win + 1):
        for i in range(len(segments) - win_size + 1):
            win_segs = segments[i:i + win_size]
            if win_size > 1 and not all(t_token_set & set(_content_tokens(seg)) for seg in win_segs):
                continue
            windows.append(' '.join(win_segs))
    if not strict_quote and len(segments) > max_win:
        contributing = [seg for seg in segments if t_token_set & set(_content_tokens(seg))]
        if contributing:
            windows.append(' '.join(contributing))
    for win in windows:
        s_tokens = set(_content_tokens(win))
        hits = sum(1 for tok in t_tokens if tok in s_tokens)
        if (hits / len(t_tokens)) >= threshold and hits >= min_hits:
            if _polarity_compatible(norm_target, win, strict_quote):
                return True
    return False


def _verify_evidence_dir(evidence, evidence_dir, errors, warnings, candidates=None, works=None):
    docs = _index_evidence_dir(evidence_dir)
    if not docs:
        errors.append('evidence_dir:no_json_files_found')
        return
    matched_eids = set()
    for eid, entry in evidence.items():
        if entry.get('access') not in {'full_text', 'selected_full_text'}:
            continue
        matched_docs = _match_docs(entry, docs)
        if not matched_docs:
            warnings.append(f'evidence:{eid}:no_local_file_in_evidence_dir')
            continue
        matched_eids.add(eid)
        locator = str(entry.get('locator') or '')
        page_match = re.search(r'\bpage\s+(\d+)\b', locator, flags=re.I)
        page_num = int(page_match.group(1)) if page_match else None
        quote = entry.get('quote')
        claim = entry.get('claim')
        target = quote if _nonblank(quote) else claim
        strict_quote = _nonblank(quote)
        page_in_range = False
        text_found = False
        for doc in matched_docs:
            if page_num is not None:
                if page_num < 1 or (doc['num_pages'] and page_num > doc['num_pages']):
                    continue
                page_in_range = True
                search_text = doc['pages_map'].get(page_num - 1, '')
            else:
                page_in_range = True
                search_text = doc['all_text']
            if _text_matches(target, search_text, strict_quote=strict_quote) and _anchor_ok(locator, search_text):
                text_found = True
                break
        if page_num is not None and not page_in_range:
            errors.append(f'evidence:{eid}:locator_page_out_of_range')
        elif not text_found:
            errors.append(f'evidence:{eid}:locator_quote_not_found')

    for cid, candidate in (candidates or {}).items():
        if not isinstance(candidate, dict) or candidate.get('disposition') != 'supported_candidate':
            continue
        cand_eids = set()
        for eid in (candidate.get('support_evidence_ids') or []):
            if isinstance(eid, str):
                cand_eids.add(eid)
        for wid in (candidate.get('closest_work_ids') or []):
            work = (works or {}).get(wid) or {}
            ev_list = work.get('evidence_ids') if isinstance(work.get('evidence_ids'), list) else []
            for eid in ev_list:
                if isinstance(eid, str):
                    cand_eids.add(eid)
        cand_ft_eids = {
            eid for eid in cand_eids
            if eid in evidence and evidence[eid].get('access') in {'full_text', 'selected_full_text'}
        }
        if cand_ft_eids and not (cand_ft_eids & matched_eids):
            errors.append(f'candidates:{cid}:evidence_dir:no_candidate_evidence_matched')


def check(record, evidence_dir=None):
    if not isinstance(record, dict):
        raise ValueError('record must be a JSON object')
    errors, warnings = [], []
    for field in ('scope', 'search_date', 'coverage_limits', 'next_check'):
        if not _nonblank(record.get(field)):
            errors.append(f'missing_or_blank:{field}')
    queries = _objects_by_id(record.get('queries'), 'queries', errors)
    evidence = _objects_by_id(record.get('evidence'), 'evidence', errors)
    works = _objects_by_id(record.get('closest_works'), 'closest_works', errors)
    candidates = _objects_by_id(record.get('candidates'), 'candidates', errors)

    for qid, query in queries.items():
        for field in ('source', 'query', 'family'):
            if not _nonblank(query.get(field)):
                errors.append(f'queries:{qid}:missing_{field}')
        if query.get('status') not in QUERY_STATES:
            errors.append(f'queries:{qid}:invalid_status')
        returned, inspected = query.get('retrieved'), query.get('inspected')
        if not isinstance(returned, int) or isinstance(returned, bool) or returned < 0:
            errors.append(f'queries:{qid}:invalid_retrieved_count')
        if not isinstance(inspected, int) or isinstance(inspected, bool) or inspected < 0:
            errors.append(f'queries:{qid}:invalid_inspected_count')
        if isinstance(returned, int) and isinstance(inspected, int) and inspected > returned:
            errors.append(f'queries:{qid}:inspected_exceeds_retrieved')
        if query.get('status') == 'valid_zero_results' and returned != 0:
            errors.append(f'queries:{qid}:zero_status_with_hits')
    for eid, entry in evidence.items():
        for field in ('source_id', 'study_id', 'locator', 'claim'):
            if not _nonblank(entry.get(field)):
                errors.append(f'evidence:{eid}:missing_{field}')
        if entry.get('access') not in ACCESS:
            errors.append(f'evidence:{eid}:invalid_access')
        if entry.get('role') not in EVIDENCE_ROLES:
            errors.append(f'evidence:{eid}:invalid_role')
    for wid, work in works.items():
        if not _nonblank(work.get('source_id')):
            errors.append(f'closest_works:{wid}:missing_source_id')
        if work.get('relation') not in RELATIONS:
            errors.append(f'closest_works:{wid}:invalid_relation')
        if work.get('access') not in ACCESS:
            errors.append(f'closest_works:{wid}:invalid_access')
        if not _nonblank(work.get('difference')):
            errors.append(f'closest_works:{wid}:missing_difference')
        linked = _ids(work, 'evidence_ids', f'closest_works:{wid}', evidence, errors)
        for eid in linked:
            if evidence.get(eid, {}).get('source_id') != work.get('source_id'):
                errors.append(f'closest_works:{wid}:evidence_source_mismatch:{eid}')

    for cid, candidate in candidates.items():
        prefix = f'candidates:{cid}'
        disposition = candidate.get('disposition')
        if disposition not in DISPOSITIONS:
            errors.append(f'{prefix}:invalid_disposition')
        for field in ('claim', 'type', 'rationale', 'engineering_status'):
            if not _nonblank(candidate.get(field)):
                errors.append(f'{prefix}:missing_{field}')
        support = _ids(candidate, 'support_evidence_ids', prefix, evidence, errors)
        counter = _ids(candidate, 'counter_evidence_ids', prefix, evidence, errors)
        close = _ids(candidate, 'closest_work_ids', prefix, works, errors)
        kill = _ids(candidate, 'kill_query_ids', prefix, queries, errors)
        if disposition != 'supported_candidate':
            continue
        if not support:
            errors.append(f'{prefix}:no_support_evidence')
        elif not any(evidence.get(eid, {}).get('access') in {'full_text', 'selected_full_text'} for eid in support):
            errors.append(f'{prefix}:support_not_checked_in_full_text')
        if support and all(evidence.get(eid, {}).get('role') == 'author_future_work' for eid in support):
            errors.append(f'{prefix}:author_future_work_alone_cannot_establish_gap')
        if not close:
            errors.append(f'{prefix}:no_closest_work_assessed')
        elif not all(works.get(wid, {}).get('access') in {'full_text', 'selected_full_text'} and
                     isinstance(works.get(wid, {}).get('evidence_ids'), list) and
                     any(evidence.get(eid, {}).get('access') in {'full_text', 'selected_full_text'}
                         for eid in (works.get(wid, {}).get('evidence_ids') or []))
                     for wid in close):
            errors.append(f'{prefix}:closest_work_unread')
        if close and any(not works.get(wid, {}).get('evidence_ids') for wid in close):
            errors.append(f'{prefix}:closest_work_has_no_locator_evidence')
        if any(works.get(wid, {}).get('relation') == 'direct_precedent' for wid in close):
            errors.append(f'{prefix}:direct_precedent_conflicts_with_positive_gap')
        if not kill or not any(queries.get(qid, {}).get('status') in SUCCESS and
                               queries.get(qid, {}).get('family') in KILL_FAMILIES for qid in kill):
            errors.append(f'{prefix}:no_completed_kill_search')
        if any(queries.get(qid, {}).get('status') in SUCCESS and _unscreened(queries.get(qid, {}))
               for qid in kill):
            errors.append(f'{prefix}:kill_search_retrieved_records_unscreened')
        successful_queries = [q for q in queries.values() if q.get('status') in SUCCESS]
        source_count = len({q.get('source') for q in successful_queries if _nonblank(q.get('source'))})
        family_count = len({q.get('family') for q in successful_queries if _nonblank(q.get('family'))})
        if (source_count < 2 or family_count < 2) and not _nonblank(candidate.get('coverage_exception')):
            errors.append(f'{prefix}:single_source_or_query_family_without_exception')
        elif source_count < 2 or family_count < 2:
            warnings.append(f'{prefix}:coverage_exception_requires_scientific_review')
        if not _nonblank(candidate.get('consequence')) or not _nonblank(candidate.get('answer_path')):
            errors.append(f'{prefix}:missing_consequence_or_answer_path')
        if candidate.get('trigger') == 'failed_implementation' and candidate.get('engineering_status') not in {'implementation_checked', 'protocol_matched'}:
            errors.append(f'{prefix}:engineering_failure_unresolved')
        if not counter:
            warnings.append(f'{prefix}:counterevidence_queue_empty; explain whether a search found none')
        if any(queries.get(qid, {}).get('status') == 'bounded_partial' for qid in kill):
            warnings.append(f'{prefix}:kill_search_bounded_partial; inspect unexamined results')

    if evidence_dir is not None:
        _verify_evidence_dir(evidence, evidence_dir, errors, warnings, candidates=candidates, works=works)

    return {'valid_structure': not errors, 'errors': errors, 'warnings': warnings,
            'scope': 'Structural audit only; a passing record is not a verified gap or novelty certificate.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('record_json')
    parser.add_argument('--evidence-dir', type=Path, default=None,
                        help='Directory of extracted PDF/JSON blocks to verify full-text locators and quotes')
    args = parser.parse_args()
    try:
        record = json.loads(Path(args.record_json).read_text(encoding='utf-8'))
        result = check(record, evidence_dir=args.evidence_dir)
        print(json.dumps(result))
        sys.exit(0 if result['valid_structure'] else 1)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        sys.exit(2)
