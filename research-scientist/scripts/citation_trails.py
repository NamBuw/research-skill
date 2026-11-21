#!/usr/bin/env python3
"""Bounded OpenAlex backward/forward citation expansion for one work ID."""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = 'https://api.openalex.org/works'
ID_PATTERN = re.compile(r'^W[0-9]+$')

def get(url, params=None, timeout=20):
    headers = {'Accept': 'application/json', 'User-Agent': 'ResearchScientistSkill/2.0 (citation-trails)'}
    key = os.environ.get('OPENALEX_API_KEY')
    if key:
        headers['Authorization'] = 'Bearer ' + key
    if params:
        url += '?' + urlencode(params)
    try:
        with urlopen(Request(url, headers=headers), timeout=timeout) as response:
            data = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f'http_{exc.code}') from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError('network_failure') from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError('invalid_json') from exc
    if not isinstance(data, dict):
        raise RuntimeError('unexpected_body')
    return data

def expand(work_id, pages=1, page_size=25, transport=get):
    if not ID_PATTERN.fullmatch(work_id):
        raise ValueError('work_id must be a short OpenAlex W-number')
    if not 1 <= pages <= 5 or not 1 <= page_size <= 100:
        raise ValueError('pages must be 1..5 and page_size 1..100')
    report = {'seed': work_id, 'checked_at_utc': datetime.now(timezone.utc).isoformat(),
              'backward_ids': [], 'forward_records': [],
              'backward_status': 'unchecked', 'forward_status': 'unchecked',
              'forward_pages_read': 0, 'forward_reported_total': None}
    try:
        work = transport(f'{BASE}/{work_id}')
        if not isinstance(work.get('referenced_works'), list):
            raise RuntimeError('missing_referenced_works')
        report['backward_ids'] = [x for x in work['referenced_works'] if isinstance(x, str)]
        report['backward_status'] = 'retrieved_ids_not_full_reference_list'
        report['seed_title'] = work.get('display_name')
    except RuntimeError as exc:
        report['backward_status'] = str(exc)
    seen_pages = set()
    for page in range(1, pages + 1):
        try:
            data = transport(BASE, {'filter': f'cites:{work_id}', 'per_page': page_size, 'page': page})
            raw = data.get('results')
            if not isinstance(raw, list):
                raise RuntimeError('missing_result_list')
            ids = tuple(x.get('id') for x in raw if isinstance(x, dict))
            if ids and ids in seen_pages:
                report['forward_status'] = 'repeated_page'
                break
            seen_pages.add(ids)
            meta = data.get('meta')
            if not isinstance(meta, dict):
                raise RuntimeError('missing_meta')
            count = meta.get('count')
            if not isinstance(count, int) or count < 0:
                raise RuntimeError('missing_or_invalid_total')
            report['forward_reported_total'] = count
            report['forward_pages_read'] += 1
            report['forward_records'].extend({'id': x.get('id'), 'title': x.get('display_name'), 'year': x.get('publication_year'), 'doi': x.get('doi')}
                                             for x in raw if isinstance(x, dict) and x.get('id'))
            report['forward_status'] = ('valid_zero_results' if count == 0 else
                                        'bounded_partial' if len(report['forward_records']) < count else 'complete')
            if not raw or len(report['forward_records']) >= count:
                break
        except RuntimeError as exc:
            report['forward_status'] = str(exc) if not report['forward_pages_read'] else 'partial_' + str(exc)
            break
    report['warning'] = 'Citation edges are discovery leads. OpenAlex matched references may be shorter than the printed bibliography. Read original papers and resolve work/version identity before judging novelty.'
    return report

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('work_id')
    parser.add_argument('--pages', type=int, default=1)
    parser.add_argument('--page-size', type=int, default=25)
    args = parser.parse_args()
    try:
        print(json.dumps(expand(args.work_id, args.pages, args.page_size)))
    except ValueError as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        sys.exit(2)
