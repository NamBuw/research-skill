#!/usr/bin/env python3
"""Cross-check a gap record's search rows against an actual campaign artifact.

The campaign is a local API-output record, not a signed provider transcript.
This detects transcription and coverage-state errors, not literature recall.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from check_gap_record import check as check_gap_record

SUCCESS = {'complete', 'bounded_partial', 'valid_zero_results'}
_QUERY_FIELD_PREFIX_RE = re.compile(r'(?:^|(?<=[\s(]))[a-z_]{1,12}:', re.I)
_QUERY_STOPWORDS = frozenset({
    'and', 'or', 'not', 'the', 'a', 'an', 'of', 'in', 'on', 'for', 'to', 'with',
    'by', 'from', 'as', 'is', 'are', 'was', 'were', 'be', 'via', 'vs', 'into',
    'under', 'over', 'between', 'across', 'than', 'that', 'this',
})


def _query_content_tokens(text):
    cleaned = _QUERY_FIELD_PREFIX_RE.sub(' ', str(text or ''))
    return [t for t in re.findall(r'[a-z0-9]+', cleaned.casefold()) if t not in _QUERY_STOPWORDS]


def _extract_balanced_paren(text, open_idx):
    depth = 0
    for idx in range(open_idx, len(text)):
        if text[idx] == '(':
            depth += 1
        elif text[idx] == ')':
            depth -= 1
            if depth == 0:
                return text[open_idx + 1:idx]
    return text[open_idx + 1:]


def _negated_query_tokens(text):
    raw = str(text or '')
    negated = set()
    for m in re.finditer(r'\bNOT(?:\s+[a-z_]{1,12}:)?\s*\(', raw, flags=re.I):
        negated.update(_query_content_tokens(_extract_balanced_paren(raw, m.end() - 1)))
    for m in re.finditer(r'(?:^|[\s(])-(?:[a-z_]{1,12}:\s*)?\(', raw, flags=re.I):
        negated.update(_query_content_tokens(_extract_balanced_paren(raw, m.end() - 1)))
    for m in re.finditer(r'\bNOT\s+(?:[a-z_]{1,12}:\s*)?"([^"]+)"', raw, flags=re.I):
        negated.update(_query_content_tokens(m.group(1)))
    for m in re.finditer(r'\bNOT\s+(?:[a-z_]{1,12}:\s*)?([a-z0-9-]+)', raw, flags=re.I):
        negated.update(_query_content_tokens(m.group(1)))
    for m in re.finditer(r'(?:^|[\s(])-(?:[a-z_]{1,12}:\s*)?"([^"]+)"', raw, flags=re.I):
        negated.update(_query_content_tokens(m.group(1)))
    for m in re.finditer(r'(?:^|[\s(])-(?:[a-z_]{1,12}:\s*)?([a-z0-9-]+)', raw, flags=re.I):
        negated.update(_query_content_tokens(m.group(1)))
    return negated


def _executed_query_matches(q_text, run_query, executed):
    if not isinstance(q_text, str) or not isinstance(executed, str):
        return False
    q_neg = _negated_query_tokens(q_text)
    e_neg = _negated_query_tokens(executed)
    if q_text == executed:
        if isinstance(run_query, str) and q_text != run_query:
            q_content = set(_query_content_tokens(q_text))
            r_content = set(_query_content_tokens(run_query))
            if not q_content or not r_content:
                return False
            if (len(q_content & r_content) / len(q_content)) < 0.6:
                return False
            if q_content & (_negated_query_tokens(run_query) - q_neg):
                return False
        return True
    if not (isinstance(run_query, str) and q_text == run_query):
        return False
    q_content = set(_query_content_tokens(q_text))
    if not q_content:
        return False
    e_content = set(_query_content_tokens(executed))
    if not q_content.issubset(e_content):
        return False
    if q_content & (e_neg - q_neg):
        return False
    return True


def mapped_status(raw):
    if isinstance(raw, str) and raw in SUCCESS:
        return raw
    if raw in {'rate_limited', 'http_429', 'partial_http_429'}:
        return 'rate_limited'
    if raw in {'bot_blocked', 'cloudflare', 'anubis', 'partial_bot_blocked', 'partial_cloudflare', 'partial_anubis'}:
        return 'bot_blocked'
    if raw == 'source_failed':
        return 'source_failed'
    return 'failed'


def check(record, campaign, campaign_sha256=None):
    if not isinstance(record, dict) or not isinstance(campaign, dict):
        raise ValueError('gap record and campaign must be objects')
    base = check_gap_record(record)
    errors = list(base['errors'])
    warnings = list(base['warnings'])
    if campaign.get('format') != 'research_scientist_search_campaign_v1':
        errors.append('campaign:invalid_format')
    runs = campaign.get('query_runs')
    if not isinstance(runs, list) or not runs:
        errors.append('campaign:query_runs_missing')
        runs = []
    by_id = {}
    for run in runs:
        if not isinstance(run, dict) or not isinstance(run.get('id'), str):
            errors.append('campaign:invalid_query_run')
            continue
        if run['id'] in by_id:
            errors.append(f"campaign:duplicate_query_run_id:{run['id']}")
        by_id[run['id']] = run
    queries = record.get('queries')
    if not isinstance(queries, list):
        queries = []
    verified_query_ids = set()
    for query in queries:
        if not isinstance(query, dict) or not isinstance(query.get('id'), str):
            continue
        qid = query['id']
        run_id = query.get('campaign_query_id')
        if not isinstance(run_id, str) or run_id not in by_id:
            errors.append(f'queries:{qid}:missing_or_unknown_campaign_query_id')
            continue
        run = by_id[run_id]
        source = query.get('source')
        sources = run.get('sources')
        if not isinstance(sources, dict) or not isinstance(source, str) or source not in sources:
            errors.append(f'queries:{qid}:source_not_in_campaign_run')
            continue
        state = sources[source]
        if not isinstance(state, dict):
            errors.append(f'queries:{qid}:invalid_campaign_source_state')
            continue
        row_ok = True
        executed = state.get('executed_query')
        run_query = run.get('query')
        q_text = query.get('query')
        if not _executed_query_matches(q_text, run_query, executed):
            errors.append(f'queries:{qid}:executed_query_mismatch')
            row_ok = False
        if query.get('family') != run.get('family'):
            errors.append(f'queries:{qid}:query_family_mismatch')
            row_ok = False
        mapped = mapped_status(state.get('status'))
        if query.get('status') != mapped and not (mapped in {'bot_blocked', 'source_failed'} and query.get('status') == 'failed'):
            errors.append(f'queries:{qid}:status_mismatch:{state.get("status")}')
            row_ok = False
        if query.get('retrieved') != state.get('returned'):
            errors.append(f'queries:{qid}:returned_count_mismatch')
            row_ok = False
        if row_ok:
            verified_query_ids.add(qid)
    seeds = campaign.get('known_seed_checks')
    if not isinstance(seeds, list):
        errors.append('campaign:known_seed_checks_missing')
        seeds = []
    invalid_seeds = [
        item for item in seeds
        if not isinstance(item, dict)
        or not isinstance(item.get('status'), str) or not item['status'].strip()
        or not isinstance(item.get('seed'), dict) or not item['seed']
    ]
    if invalid_seeds:
        errors.append('campaign:invalid_known_seed_check_entry')
    missed = [item for item in seeds if not isinstance(item, dict) or item.get('status') != 'retrieved']
    if not seeds:
        warnings.append('campaign:no_known_positive_control; query recall remains untested')
    if missed:
        warnings.append(f'campaign:{len(missed)}_known_positive_controls_not_retrieved')
    candidates = record.get('candidates')
    if not isinstance(candidates, list):
        candidates = []
    query_by_id = {q.get('id'): q for q in queries if isinstance(q, dict) and isinstance(q.get('id'), str)}
    for candidate in candidates:
        if not isinstance(candidate, dict) or candidate.get('disposition') != 'supported_candidate':
            continue
        cid = candidate.get('id', '?')
        if not seeds:
            errors.append(f'candidates:{cid}:known_positive_control_missing')
        if missed:
            errors.append(f'candidates:{cid}:known_positive_control_missed')
        search_ids = candidate.get('search_query_ids')
        if not isinstance(search_ids, list) or not search_ids or any(not isinstance(qid, str) for qid in search_ids):
            errors.append(f'candidates:{cid}:search_query_ids_required')
            search_ids = []
        if any(qid not in verified_query_ids for qid in search_ids):
            errors.append(f'candidates:{cid}:search_query_ids_not_campaign_verified')
        kill_ids = candidate.get('kill_query_ids') if isinstance(candidate.get('kill_query_ids'), list) else []
        if any(qid not in search_ids for qid in kill_ids):
            errors.append(f'candidates:{cid}:kill_queries_not_in_candidate_search_set')
        linked_success = [qid for qid in kill_ids
                          if qid in verified_query_ids and query_by_id.get(qid, {}).get('status') in SUCCESS]
        if not linked_success:
            errors.append(f'candidates:{cid}:no_campaign_verified_successful_kill_search')
        verified_sources = {query_by_id[qid].get('source') for qid in search_ids if qid in verified_query_ids
                            if query_by_id[qid].get('status') in SUCCESS}
        if len(verified_sources) < 2 and not candidate.get('coverage_exception'):
            errors.append(f'candidates:{cid}:fewer_than_two_campaign_verified_sources')
    return {'valid_structure_and_manifest': not errors, 'errors': errors, 'warnings': warnings,
            'campaign_sha256': campaign_sha256, 'verified_query_rows': len(verified_query_ids),
            'known_positive_controls': len(seeds), 'known_positive_controls_missed': len(missed),
            'scope': ('This cross-check verifies declared rows against one local campaign JSON. It cannot verify '
                      'provider authenticity, papers screened, full-text reading, prior-art recall, a gap or novelty.')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gap_record_json')
    parser.add_argument('campaign_json')
    args = parser.parse_args()
    try:
        record = json.loads(Path(args.gap_record_json).read_text(encoding='utf-8'))
        raw = Path(args.campaign_json).read_bytes()
        campaign = json.loads(raw)
        result = check(record, campaign, hashlib.sha256(raw).hexdigest())
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result['valid_structure_and_manifest'] else 1
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
