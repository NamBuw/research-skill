#!/usr/bin/env python3
"""Bounded multi-index discovery with explicit failures and provenance.

This is a discovery helper, not a systematic review or novelty oracle.
Queries are sent to external scholarly services; use only authorized topics.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SOURCES = ('s2', 'openalex', 'crossref', 'europepmc')
ENDPOINTS = {
    's2': 'https://api.semanticscholar.org/graph/v1/paper/search',
    'openalex': 'https://api.openalex.org/works',
    'crossref': 'https://api.crossref.org/works',
    'europepmc': 'https://www.ebi.ac.uk/europepmc/webservices/rest/search',
}

def fetch(source, params, timeout=20):
    headers = {'Accept': 'application/json', 'User-Agent': 'ResearchScientistSkill/2.0 (scholarly-discovery)'}
    if source == 's2' and os.environ.get('S2_API_KEY'):
        headers['x-api-key'] = os.environ['S2_API_KEY']
    if source == 'openalex' and os.environ.get('OPENALEX_API_KEY'):
        params['api_key'] = os.environ['OPENALEX_API_KEY']
    url = ENDPOINTS[source] + '?' + urlencode(params)
    try:
        with urlopen(Request(url, headers=headers), timeout=timeout) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f'http_{exc.code}') from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError('network_failure') from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError('invalid_json') from exc

def request_params(source, query, size, page, cursor=None):
    if source == 's2':
        return {'query': query.replace('-', ' '), 'limit': size, 'offset': (page - 1) * size,
                'fields': 'title,year,authors,abstract,externalIds,url,publicationDate'}
    if source == 'openalex':
        return {'search': query, 'per_page': size, 'page': page}
    if source == 'crossref':
        return {'query.bibliographic': query, 'rows': size, 'offset': (page - 1) * size}
    return {'query': query, 'format': 'json', 'pageSize': size, 'resultType': 'core', 'cursorMark': cursor or '*'}

def parse(source, data):
    if not isinstance(data, dict):
        raise ValueError('unexpected_body')
    if source == 's2':
        raw, total = data.get('data'), data.get('total')
    elif source == 'openalex':
        raw, total = data.get('results'), (data.get('meta') or {}).get('count')
    elif source == 'crossref':
        msg = data.get('message') or {}
        raw, total = msg.get('items'), msg.get('total-results')
    else:
        raw, total = (data.get('resultList') or {}).get('result'), data.get('hitCount')
    if not isinstance(raw, list):
        raise ValueError('missing_result_list')
    out = []
    for paper in raw:
        if not isinstance(paper, dict):
            continue
        if source == 's2':
            ids = paper.get('externalIds') or {}
            title, doi, identifier, year = paper.get('title'), ids.get('DOI'), paper.get('paperId'), paper.get('year')
        elif source == 'openalex':
            title, doi, identifier, year = paper.get('display_name'), paper.get('doi'), paper.get('id'), paper.get('publication_year')
        elif source == 'crossref':
            title, doi, identifier = next(iter(paper.get('title') or []), None), paper.get('DOI'), paper.get('DOI')
            date_parts = ((paper.get('published') or {}).get('date-parts') or [[]])[0]
            year = date_parts[0] if date_parts else None
        else:
            title, doi, identifier, year = paper.get('title'), paper.get('doi'), f"{paper.get('source')}:{paper.get('id')}", paper.get('pubYear')
        if title and identifier:
            out.append({'source': source, 'source_id': str(identifier), 'title': title,
                        'year': year, 'doi': str(doi).removeprefix('https://doi.org/').lower() if doi else None})
    return out, total

def search(query, sources=SOURCES, size=20, pages=1, transport=fetch):
    if not query.strip() or len(query) > 500:
        raise ValueError('query must contain 1..500 nonblank characters')
    if not 1 <= size <= 100 or not 1 <= pages <= 5:
        raise ValueError('size must be 1..100 and pages 1..5')
    result = {'query': query, 'checked_at_utc': datetime.now(timezone.utc).isoformat(),
              'sources': {}, 'records': [], 'doi_duplicate_groups': {}}
    for source in sources:
        if source not in SOURCES:
            raise ValueError('unsupported source')
        state = {'status': 'complete', 'pages_requested': pages, 'pages_read': 0,
                 'returned': 0, 'reported_total': None, 'access': 'key' if os.environ.get({'s2':'S2_API_KEY','openalex':'OPENALEX_API_KEY'}.get(source,'')) else 'keyless'}
        result['sources'][source] = state
        cursor = '*'
        seen_pages = set()
        for page in range(1, pages + 1):
            if source == 's2' and (page - 1) * size >= 1000:
                state['status'] = 'truncated_api_cap'; break
            try:
                data = transport(source, request_params(source, query, size, page, cursor))
                papers, total = parse(source, data)
            except (RuntimeError, ValueError) as exc:
                state['status'] = str(exc) if state['pages_read'] == 0 else 'partial_' + str(exc)
                break
            signature = tuple(paper['source_id'] for paper in papers)
            if signature and signature in seen_pages:
                state['status'] = 'repeated_page'
                break
            seen_pages.add(signature)
            state['pages_read'] += 1
            state['returned'] += len(papers)
            state['reported_total'] = total
            result['records'].extend(papers)
            if not papers or (isinstance(total, int) and page * size >= total):
                break
            if source == 'europepmc':
                next_cursor = data.get('nextCursorMark')
                if not next_cursor or next_cursor == cursor:
                    state['status'] = 'missing_or_repeated_cursor'
                    break
                cursor = next_cursor
        if state['status'] == 'complete' and state['pages_read'] and state['returned'] == 0:
            state['status'] = 'valid_zero_results'
        elif state['status'] == 'complete' and state['pages_read'] == pages and isinstance(state['reported_total'], int) and state['returned'] < state['reported_total']:
            state['status'] = 'bounded_partial'
    doi_groups = {}
    for index, paper in enumerate(result['records']):
        if paper['doi']:
            doi_groups.setdefault(paper['doi'], []).append(index)
    result['doi_duplicate_groups'] = {doi: positions for doi, positions in doi_groups.items() if len(positions) > 1}
    result['warning'] = 'Discovery records only. DOI groups are candidate duplicates; resolve versions and study identity manually. Failures and bounded pages are unchecked coverage, never evidence of no prior work.'
    return result

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('query')
    parser.add_argument('--source', action='append', choices=SOURCES)
    parser.add_argument('--size', type=int, default=20)
    parser.add_argument('--pages', type=int, default=1)
    args = parser.parse_args()
    try:
        print(json.dumps(search(args.query, args.source or SOURCES, args.size, args.pages), ensure_ascii=False))
    except ValueError as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        sys.exit(2)
