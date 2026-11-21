#!/usr/bin/env python3
"""Collect OpenAlex publication-source leads from a bounded related-paper query."""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = 'https://api.openalex.org/works'

def fetch(params, timeout=20):
    headers = {'Accept': 'application/json', 'User-Agent': 'ResearchScientistSkill/2.1 (venue-leads)'}
    if os.environ.get('OPENALEX_API_KEY'):
        headers['Authorization'] = 'Bearer ' + os.environ['OPENALEX_API_KEY']
    try:
        with urlopen(Request(API + '?' + urlencode(params), headers=headers), timeout=timeout) as response:
            result = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f'http_{exc.code}') from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError('network_failure') from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError('invalid_json') from exc
    if not isinstance(result, dict):
        raise RuntimeError('unexpected_body')
    return result

def collect(query, pages=1, page_size=25, transport=fetch):
    if not isinstance(query, str) or not query.strip() or len(query) > 500:
        raise ValueError('query must contain 1..500 nonblank characters')
    if not 1 <= pages <= 5 or not 1 <= page_size <= 100:
        raise ValueError('pages must be 1..5 and page_size 1..100')
    output = {'query': query, 'checked_at_utc': datetime.now(timezone.utc).isoformat(),
              'status': 'unchecked', 'pages_read': 0, 'reported_total': None,
              'related_works_read_as_metadata': 0, 'source_leads': [], 'works_without_primary_source': 0}
    groups, seen_pages, seen_works = {}, set(), set()
    for page in range(1, pages + 1):
        try:
            data = transport({'search': query, 'per_page': page_size, 'page': page})
            raw = data.get('results')
            count = (data.get('meta') or {}).get('count')
            if not isinstance(raw, list) or not isinstance(count, int) or count < 0:
                raise RuntimeError('invalid_page')
            signature = tuple(w.get('id') for w in raw if isinstance(w, dict))
            if signature and signature in seen_pages:
                output['status'] = 'repeated_page'
                break
            seen_pages.add(signature)
            output['pages_read'] += 1
            output['reported_total'] = count
            for work in raw:
                if not isinstance(work, dict) or not isinstance(work.get('id'), str) or work['id'] in seen_works:
                    continue
                seen_works.add(work['id'])
                location = work.get('primary_location')
                source = location.get('source') if isinstance(location, dict) else None
                if not isinstance(source, dict) or not isinstance(source.get('id'), str):
                    output['works_without_primary_source'] += 1
                    continue
                source_id = source['id']
                row = groups.setdefault(source_id, {'source_id': source_id, 'name': source.get('display_name'),
                                                    'source_type': source.get('type'), 'related_work_ids': [],
                                                    'years': []})
                row['related_work_ids'].append(work['id'])
                if isinstance(work.get('publication_year'), int):
                    row['years'].append(work['publication_year'])
            output['status'] = 'valid_zero_results' if count == 0 else ('bounded_partial' if len(seen_works) < count else 'complete')
            if not raw or len(seen_works) >= count:
                break
        except RuntimeError as exc:
            output['status'] = str(exc) if not output['pages_read'] else 'partial_' + str(exc)
            break
    output['related_works_read_as_metadata'] = len(seen_works)
    for row in groups.values():
        row['sample_count'] = len(row['related_work_ids'])
        row['sample_year_range'] = [min(row['years']), max(row['years'])] if row['years'] else None
        del row['years']
    output['source_leads'] = sorted(groups.values(), key=lambda x: (-x['sample_count'], str(x['name']), x['source_id']))
    output['warning'] = ('Metadata-frequency leads only: OpenAlex search ranking and primary-location coverage bias this sample. '
                         'A source is not an eligible submission venue merely because it hosted a related work. '
                         'Verify official current CFP/aims, edition, track, dates, policy, cost and manuscript fit before recommendation.')
    return output

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('query')
    parser.add_argument('--pages', type=int, default=1)
    parser.add_argument('--page-size', type=int, default=25)
    args = parser.parse_args()
    try:
        print(json.dumps(collect(args.query, args.pages, args.page_size), ensure_ascii=False))
    except ValueError as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        sys.exit(2)
