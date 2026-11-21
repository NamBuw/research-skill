#!/usr/bin/env python3
"""Run a bounded, auditable multi-query scholarly discovery campaign.

This collects search leads and exact-identifier positive controls. It does not
screen papers, read full text, or establish novelty or search completeness.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from search_papers import SOURCES, normalize_doi, normalize_source_id, search

SUCCESS_STATES = {'complete', 'bounded_partial', 'valid_zero_results'}
FULL_QUERY_STATES = {'complete', 'valid_zero_results'}


def validate_plan(plan):
    if not isinstance(plan, dict):
        raise ValueError('campaign plan must be an object')
    question = plan.get('question')
    if not isinstance(question, str) or not question.strip():
        raise ValueError('question must be nonblank')
    queries = plan.get('queries')
    if not isinstance(queries, list) or not 1 <= len(queries) <= 100:
        raise ValueError('queries must contain 1..100 entries')
    seen_ids = set()
    for item in queries:
        if not isinstance(item, dict):
            raise ValueError('each query must be an object')
        qid, family, query = (item.get(k) for k in ('id', 'family', 'query'))
        if any(not isinstance(v, str) or not v.strip() for v in (qid, family, query)):
            raise ValueError('every query needs nonblank id, family and query')
        if len(query) > 500:
            raise ValueError(f'{qid}: query must be at most 500 characters')
        if qid in seen_ids:
            raise ValueError('duplicate query id')
        seen_ids.add(qid)
        sources = item.get('sources', list(SOURCES))
        if (not isinstance(sources, list) or not sources or
                any(not isinstance(s, str) or s not in SOURCES for s in sources) or
                len(sources) != len(set(sources))):
            raise ValueError(f'{qid}: sources must be a nonempty unique list of supported sources')
        overrides = item.get('query_for', {})
        if not isinstance(overrides, dict) or any(s not in sources or not isinstance(q, str) or not q.strip() or len(q) > 500 for s, q in overrides.items()):
            raise ValueError(f'{qid}: query_for must map selected sources to nonblank queries')
        if not isinstance(item.get('size', 20), int) or not 1 <= item.get('size', 20) <= 100:
            raise ValueError(f'{qid}: size must be 1..100')
        if not isinstance(item.get('pages', 1), int) or not 1 <= item.get('pages', 1) <= 5:
            raise ValueError(f'{qid}: pages must be 1..5')
    seeds = plan.get('known_seeds', [])
    if not isinstance(seeds, list):
        raise ValueError('known_seeds must be a list')
    for seed in seeds:
        if not isinstance(seed, dict):
            raise ValueError('each known seed must be an object')
        if set(seed) == {'doi'}:
            if not isinstance(seed['doi'], str) or not normalize_doi(seed['doi']):
                raise ValueError('known seed DOI must be nonblank')
        elif set(seed) == {'source', 'source_id'}:
            if seed['source'] not in SOURCES or not isinstance(seed['source_id'], str) or not seed['source_id'].strip():
                raise ValueError('known seed source and source_id must be valid')
        else:
            raise ValueError('known seed must contain DOI or source and source_id only')
    return queries, seeds


def _seed_key(seed):
    if 'doi' in seed:
        return ('doi', normalize_doi(seed['doi']))
    return ('source_id', seed['source'], normalize_source_id(seed['source'], seed['source_id']))


def run_campaign(plan, search_fn=search):
    queries, seeds = validate_plan(plan)
    output = {'format': 'research_scientist_search_campaign_v1', 'question': plan['question'],
              'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'query_runs': [],
              'source_records': [], 'doi_candidate_groups': {}, 'known_seed_checks': [],
              'coverage': {}}
    by_source_id = {}
    seed_dois = [s['doi'] for s in seeds if 'doi' in s]
    seed_ids = [(s['source'], s['source_id']) for s in seeds if 'source_id' in s]
    for item in queries:
        qid = item['id']
        result = search_fn(item['query'], tuple(item.get('sources', SOURCES)), item.get('size', 20),
                           item.get('pages', 1), source_queries=item.get('query_for', {}),
                           known_dois=seed_dois, known_source_ids=seed_ids)
        output['query_runs'].append({'id': qid, 'family': item['family'], 'query': item['query'],
                                     'checked_at_utc': result['checked_at_utc'], 'sources': result['sources'],
                                     'returned_records': len(result['records']),
                                     'known_seed_checks': result['known_seed_checks']})
        for record in result['records']:
            key = (record['source'], record['source_id'])
            if key not in by_source_id:
                entry = dict(record)
                entry['discovered_by'] = [qid]
                entry['metadata_conflicts'] = []
                by_source_id[key] = entry
            else:
                entry = by_source_id[key]
                if qid not in entry['discovered_by']:
                    entry['discovered_by'].append(qid)
                if any(entry.get(field) != record.get(field) for field in ('title', 'year', 'doi')):
                    entry['metadata_conflicts'].append({'query_id': qid, 'title': record.get('title'),
                                                        'year': record.get('year'), 'doi': record.get('doi')})
    output['source_records'] = list(by_source_id.values())
    doi_groups = defaultdict(list)
    for record in output['source_records']:
        if record.get('doi'):
            doi_groups[normalize_doi(record['doi'])].append({'source': record['source'],
                                                             'source_id': record['source_id']})
    output['doi_candidate_groups'] = {doi: group for doi, group in doi_groups.items() if len(group) > 1}
    all_source_states = [(run['id'], source, state['status']) for run in output['query_runs']
                         for source, state in run['sources'].items()]
    for seed in seeds:
        key = _seed_key(seed)
        matched_runs = []
        for run in output['query_runs']:
            if any(check['status'] == 'retrieved' and
                   ((key[0] == 'doi' and check['kind'] == 'doi' and normalize_doi(check['requested']) == key[1]) or
                    (key[0] == 'source_id' and check['kind'] == 'source_id' and check['source'] == key[1] and
                     normalize_source_id(key[1], check['requested']) == key[2]))
                   for check in run['known_seed_checks']):
                matched_runs.append(run['id'])
        if matched_runs:
            status = 'retrieved'
        elif key[0] == 'source_id' and not any(source == key[1] for _, source, _ in all_source_states):
            status = 'source_not_queried'
        elif key[0] == 'source_id' and not any(source == key[1] and state in SUCCESS_STATES
                                                for _, source, state in all_source_states):
            status = 'source_unavailable'
        elif not any(state in SUCCESS_STATES for _, _, state in all_source_states):
            status = 'all_sources_unavailable'
        else:
            status = 'not_retrieved_in_campaign'
        output['known_seed_checks'].append({'seed': seed, 'status': status, 'retrieved_in_query_ids': matched_runs})
    output['coverage'] = {
        'query_count': len(queries), 'query_families': sorted({q['family'] for q in queries}),
        'raw_record_count': sum(run['returned_records'] for run in output['query_runs']),
        'distinct_source_record_count': len(output['source_records']),
        'failed_or_partial_source_runs': [{'query_id': qid, 'source': source, 'status': state}
                                          for qid, source, state in all_source_states if state not in FULL_QUERY_STATES],
    }
    output['warning'] = ('Records are discovery leads. Exact DOI groups are candidate duplicates, not merged studies. '
                         'Known-seed misses, failed sources, and bounded results require diagnosis; none proves absence of prior work. '
                         'Query-family count and source-record count are not measures of recall or scientific independence.')
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan_json', help='JSON campaign plan')
    args = parser.parse_args()
    try:
        plan = json.loads(Path(args.plan_json).read_text(encoding='utf-8'))
        print(json.dumps(run_campaign(plan), ensure_ascii=False))
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
