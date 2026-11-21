#!/usr/bin/env python3
"""Bounded multi-index discovery with explicit failures and provenance.

This is a discovery helper, not a systematic review or novelty oracle.
Queries are sent to external scholarly services; use only authorized topics.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SOURCES = ('s2', 'openalex', 'crossref', 'europepmc', 'arxiv', 'pubmed')
ENDPOINTS = {
    's2': 'https://api.semanticscholar.org/graph/v1/paper/search',
    'openalex': 'https://api.openalex.org/works',
    'crossref': 'https://api.crossref.org/works',
    'europepmc': 'https://www.ebi.ac.uk/europepmc/webservices/rest/search',
    'arxiv': 'https://export.arxiv.org/api/query',
    'pubmed': 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi',
}

def _read(url, headers, timeout, xml=False):
    with urlopen(Request(url, headers=headers), timeout=timeout) as response:
        body = response.read(8_000_001)
    if len(body) > 8_000_000:
        raise RuntimeError('response_too_large')
    if xml:
        try:
            return ET.fromstring(body)
        except ET.ParseError as exc:
            raise RuntimeError('invalid_xml') from exc
    try:
        return json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError('invalid_json') from exc

def fetch(source, params, timeout=20):
    headers = {'Accept': 'application/json, application/atom+xml', 'User-Agent': 'ResearchScientistSkill/2.1 (scholarly-discovery)'}
    if source == 's2' and os.environ.get('S2_API_KEY'):
        headers['x-api-key'] = os.environ['S2_API_KEY']
    if source == 'openalex' and os.environ.get('OPENALEX_API_KEY'):
        headers['Authorization'] = 'Bearer ' + os.environ['OPENALEX_API_KEY']
    url = ENDPOINTS[source] + '?' + urlencode(params)
    try:
        if source == 'arxiv':
            root = _read(url, headers, timeout, xml=True)
            atom = '{http://www.w3.org/2005/Atom}'
            total_text = root.findtext('{http://a9.com/-/spec/opensearch/1.1/}totalResults')
            if total_text is None or not total_text.isdigit():
                raise RuntimeError('missing_or_invalid_total')
            entries = []
            for entry in root.findall(atom + 'entry'):
                entries.append({'id': entry.findtext(atom + 'id'), 'title': entry.findtext(atom + 'title'),
                                'published': entry.findtext(atom + 'published')})
            return {'entries': entries, 'total': int(total_text)}
        if source == 'pubmed':
            search_data = _read(url, headers, timeout)
            search_result = search_data.get('esearchresult') if isinstance(search_data, dict) else None
            if not isinstance(search_result, dict):
                raise RuntimeError('missing_esearch_result')
            ids = search_result.get('idlist')
            count = search_result.get('count')
            if not isinstance(ids, list) or not str(count).isdigit():
                raise RuntimeError('invalid_esearch_result')
            if not ids:
                return {'records': [], 'total': int(count), 'query_translation': search_result.get('querytranslation')}
            summary_params = {'db': 'pubmed', 'id': ','.join(ids), 'retmode': 'json', 'tool': 'research-scientist-skill'}
            summary_url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?' + urlencode(summary_params)
            summary_data = _read(summary_url, headers, timeout)
            summary = summary_data.get('result') if isinstance(summary_data, dict) else None
            if not isinstance(summary, dict):
                raise RuntimeError('missing_esummary_result')
            records = []
            for pmid in ids:
                item = summary.get(pmid)
                if not isinstance(item, dict):
                    raise RuntimeError('incomplete_esummary_result')
                doi = next((x.get('value') for x in item.get('articleids', [])
                            if isinstance(x, dict) and x.get('idtype') == 'doi'), None)
                records.append({'id': pmid, 'title': item.get('title'), 'year': item.get('pubdate'), 'doi': doi})
            return {'records': records, 'total': int(count), 'query_translation': search_result.get('querytranslation')}
        return _read(url, headers, timeout)
    except HTTPError as exc:
        raise RuntimeError(f'http_{exc.code}') from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError('network_failure') from exc

def request_params(source, query, size, page, cursor=None, raw_arxiv=False):
    if source == 's2':
        return {'query': query.replace('-', ' '), 'limit': size, 'offset': (page - 1) * size,
                'fields': 'title,year,authors,abstract,externalIds,url,publicationDate'}
    if source == 'openalex':
        return {'search': query, 'per_page': size, 'page': page}
    if source == 'crossref':
        return {'query.bibliographic': query, 'rows': size, 'offset': (page - 1) * size}
    if source == 'arxiv':
        terms = re.findall(r'[^\W_]+', query, re.UNICODE)
        if not terms:
            raise ValueError('arxiv query has no searchable terms')
        return {'search_query': query if raw_arxiv else ' AND '.join('all:' + term for term in terms),
                'start': (page - 1) * size, 'max_results': size, 'sortBy': 'relevance'}
    if source == 'pubmed':
        params = {'db': 'pubmed', 'term': query, 'retstart': (page - 1) * size,
                  'retmax': size, 'retmode': 'json', 'sort': 'relevance',
                  'tool': 'research-scientist-skill'}
        return params
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
    elif source == 'europepmc':
        raw, total = (data.get('resultList') or {}).get('result'), data.get('hitCount')
    elif source == 'arxiv':
        raw, total = data.get('entries'), data.get('total')
    else:
        raw, total = data.get('records'), data.get('total')
    if not isinstance(raw, list):
        raise ValueError('missing_result_list')
    if not isinstance(total, int) or total < 0:
        raise ValueError('missing_or_invalid_total')
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
        elif source == 'europepmc':
            title, doi, identifier, year = paper.get('title'), paper.get('doi'), (f"{paper.get('source')}:{paper.get('id')}" if paper.get('source') and paper.get('id') else None), paper.get('pubYear')
        elif source == 'arxiv':
            title, doi, identifier, year = paper.get('title'), None, paper.get('id'), paper.get('published')
            if isinstance(identifier, str):
                identifier = 'arxiv:' + identifier.rsplit('/', 1)[-1]
        else:
            title, doi, identifier, year = paper.get('title'), paper.get('doi'), (f"pmid:{paper.get('id')}" if paper.get('id') else None), paper.get('year')
        if isinstance(year, str) and len(year) >= 4 and year[:4].isdigit():
            year = int(year[:4])
        if title and identifier:
            out.append({'source': source, 'source_id': str(identifier), 'title': title,
                        'year': year, 'doi': str(doi).removeprefix('https://doi.org/').lower() if doi else None})
    if raw and not out:
        raise ValueError('no_valid_records_in_nonempty_page')
    return out, total

def normalize_doi(value):
    value = value.strip().lower()
    value = re.sub(r'^https?://(?:dx\.)?doi\.org/', '', value)
    return value.removeprefix('doi:')

def normalize_source_id(source, value):
    value = value.strip()
    if source == 'arxiv':
        value = value.rsplit('/', 1)[-1].removeprefix('arxiv:')
        return re.sub(r'v\d+$', '', value, flags=re.IGNORECASE).lower()
    if source == 'openalex':
        return value.rsplit('/', 1)[-1].lower()
    if source == 'crossref':
        return normalize_doi(value)
    return value.lower()

def check_known_seeds(records, source_states, known_dois=(), known_source_ids=()):
    """Exact identifier checks within this run; a miss never certifies absence."""
    checks = []
    for requested in known_dois:
        if not isinstance(requested, str) or not normalize_doi(requested):
            raise ValueError('known DOI must be nonblank')
        key = normalize_doi(requested)
        matches = [r for r in records if r['doi'] and normalize_doi(r['doi']) == key]
        checks.append({'kind': 'doi', 'requested': requested,
                       'status': 'retrieved' if matches else 'not_retrieved_in_this_run',
                       'matched_source_ids': [r['source_id'] for r in matches]})
    for source, requested in known_source_ids:
        if source not in SOURCES or not isinstance(requested, str) or not requested.strip():
            raise ValueError('known source ID needs a supported source and nonblank ID')
        key = normalize_source_id(source, requested)
        matches = [r for r in records if r['source'] == source and normalize_source_id(source, r['source_id']) == key]
        checks.append({'kind': 'source_id', 'source': source, 'requested': requested,
                       'source_status': source_states.get(source, {}).get('status', 'not_queried'),
                       'status': 'retrieved' if matches else 'not_retrieved_in_this_run',
                       'matched_source_ids': [r['source_id'] for r in matches]})
    return checks

def search(query, sources=SOURCES, size=20, pages=1, transport=fetch, source_queries=None,
           known_dois=(), known_source_ids=()):
    if not query.strip() or len(query) > 500:
        raise ValueError('query must contain 1..500 nonblank characters')
    if not 1 <= size <= 100 or not 1 <= pages <= 5:
        raise ValueError('size must be 1..100 and pages 1..5')
    source_queries = source_queries or {}
    if not isinstance(source_queries, dict) or any(k not in SOURCES or not isinstance(v, str) or not v.strip() or len(v) > 500
                                                 for k, v in source_queries.items()):
        raise ValueError('source_queries must map supported sources to nonblank queries of at most 500 characters')
    known_dois = tuple(known_dois)
    known_source_ids = tuple(known_source_ids)
    if any(not isinstance(pair, (tuple, list)) or len(pair) != 2 for pair in known_source_ids):
        raise ValueError('known source IDs must be SOURCE=ID pairs')
    for requested in known_dois:
        if not isinstance(requested, str) or not normalize_doi(requested):
            raise ValueError('known DOI must be nonblank')
    for source, requested in known_source_ids:
        if source not in SOURCES or not isinstance(requested, str) or not requested.strip():
            raise ValueError('known source ID needs a supported source and nonblank ID')
    result = {'query': query, 'checked_at_utc': datetime.now(timezone.utc).isoformat(),
              'sources': {}, 'records': [], 'doi_duplicate_groups': {}}
    for source in sources:
        if source not in SOURCES:
            raise ValueError('unsupported source')
        state = {'status': 'complete', 'pages_requested': pages, 'pages_read': 0,
                 'returned': 0, 'reported_total': None, 'access': 'key' if os.environ.get({'s2':'S2_API_KEY','openalex':'OPENALEX_API_KEY'}.get(source,'')) else 'keyless'}
        result['sources'][source] = state
        selected_query = source_queries.get(source, query)
        cursor = '*'
        seen_pages = set()
        for page in range(1, pages + 1):
            if source == 's2' and (page - 1) * size >= 1000:
                state['status'] = 'truncated_api_cap'; break
            try:
                params = request_params(source, selected_query, size, page, cursor,
                                        raw_arxiv=source == 'arxiv' and source in source_queries)
                state['executed_query'] = params.get({'arxiv': 'search_query', 'pubmed': 'term', 'crossref': 'query.bibliographic', 'europepmc': 'query', 'openalex': 'search', 's2': 'query'}[source])
                data = transport(source, params)
                papers, total = parse(source, data)
                if source == 'pubmed' and isinstance(data.get('query_translation'), str):
                    state['provider_query_translation'] = data['query_translation']
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
    result['known_seed_checks'] = check_known_seeds(result['records'], result['sources'], known_dois, known_source_ids)
    result['warning'] = ('Discovery records only. A complete status covers only the executed query, not the topic or known relevant works; '
                         'test known seeds and reformulate missed queries. DOI groups are candidate duplicates; resolve versions and study identity manually. '
                         'Failures and bounded pages are unchecked coverage, never evidence of no prior work.')
    return result

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('query')
    parser.add_argument('--source', action='append', choices=SOURCES)
    parser.add_argument('--query-for', action='append', metavar='SOURCE=QUERY',
                        help='Override the query for one source; repeat per source')
    parser.add_argument('--known-doi', action='append', metavar='DOI',
                        help='Check whether an exact known DOI occurs in this run; repeatable')
    parser.add_argument('--known-source-id', action='append', metavar='SOURCE=ID',
                        help='Check an exact source ID (arXiv versions are linked); repeatable')
    parser.add_argument('--size', type=int, default=20)
    parser.add_argument('--pages', type=int, default=1)
    args = parser.parse_args()
    try:
        source_queries = {}
        for item in args.query_for or []:
            if '=' not in item:
                raise ValueError('--query-for needs SOURCE=QUERY')
            source, value = item.split('=', 1)
            if source in source_queries:
                raise ValueError('duplicate --query-for source')
            source_queries[source] = value
        known_ids = []
        for item in args.known_source_id or []:
            if '=' not in item:
                raise ValueError('--known-source-id needs SOURCE=ID')
            known_ids.append(tuple(item.split('=', 1)))
        print(json.dumps(search(args.query, args.source or SOURCES, args.size, args.pages,
                                source_queries=source_queries, known_dois=args.known_doi or (),
                                known_source_ids=known_ids), ensure_ascii=False))
    except ValueError as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        sys.exit(2)
