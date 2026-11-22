#!/usr/bin/env python3
"""Bounded multi-index scholarly discovery with rate-limit pacing, 4-ID dedup, and explicit failure states.

Adapted / ported patterns:
- sgha (Apache-2.0): multi-key transitive record deduplication (DOI, bare arXiv, OpenAlex, S2, title).
- research-paper-lifecycle-skills (Apache-2.0): per-host polite rate pacing, Retry-After backoff,
  DBLP API parsing, preprint_only & unresolved-keep classification.
- vane (MIT): mode routing (speed/balanced/quality) and 3-query fan-out WITHOUT silent similarity=1.0 fallback.
- lit-gap (No License — clean-room behavioral spec only): require_abstract=False default,
  OpenAlex abstract_inverted_index reconstruction, DOI+title cross-matching, Retry-After handling.

This is a discovery helper, not a systematic review or novelty oracle.
"""
from __future__ import annotations

import argparse
import email.utils
import html
import json
import os
import re
import sys
import tempfile
import threading
import time
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

import defusedxml.ElementTree as DET
from defusedxml.common import DefusedXmlException

SOURCES = ('s2', 'openalex', 'crossref', 'europepmc', 'arxiv', 'pubmed', 'acl', 'huggingface', 'dblp')
SOURCE_ALIASES = {
    'acl_anthology': 'acl',
    'hf': 'huggingface',
    'hf_papers': 'huggingface',
    'huggingface_papers': 'huggingface',
}
ENDPOINTS = {
    's2': 'https://api.semanticscholar.org/graph/v1/paper/search',
    'openalex': 'https://api.openalex.org/works',
    'crossref': 'https://api.crossref.org/works',
    'europepmc': 'https://www.ebi.ac.uk/europepmc/webservices/rest/search',
    'arxiv': 'https://export.arxiv.org/api/query',
    'pubmed': 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi',
    'acl': 'https://api.crossref.org/works',
    'huggingface': 'https://huggingface.co/api/papers/search',
    'dblp': 'https://dblp.org/search/publ/api',
}

DEFAULT_MIN_INTERVALS = {
    'api.semanticscholar.org': 1.1,
    'export.arxiv.org': 3.0,
    'dblp.org': 2.0,
    'api.crossref.org': 1.0,
    'api.openalex.org': 0.5,
    'eutils.ncbi.nlm.nih.gov': 0.35,
    'www.ebi.ac.uk': 0.5,
    'aclanthology.org': 1.0,
    'huggingface.co': 0.5,
}
RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}
PREPRINT_SOURCES = {'arxiv', 'huggingface'}
MODES = ('speed', 'balanced', 'quality')

_HOST_LOCK = threading.Lock()
_HOST_LAST_CALL: dict[str, float] = {}

ARXIV_DOI_RE = re.compile(r'^10\.48550/arxiv\.(.+)$', re.I)
ARXIV_ID_RE = re.compile(
    r'^(?:https?://arxiv\.org/(?:abs|pdf)/|arxiv:)?'
    r'(\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z-]+)?/\d{7})(?:v\d+)?(?:\.pdf)?$',
    re.I,
)
ACL_DOI_RE = re.compile(r'^10\.18653/(?:v1/)?(.+)$', re.I)
ANUBIS_MARKERS = (
    b'anubis_version',
    b'anubis_challenge',
    b'/.within.website/x/xess/',
    b'/.within.website/x/cmd/anubis/',
    b'Making sure you&#39;re not a bot!',
    b"Making sure you're not a bot!",
    b'cf-browser-verification',
    b'_cf_chl_opt',
    b'<title>Just a moment...</title>',
    b'Attention Required! | Cloudflare',
)


def normalize_source_name(name: str) -> str:
    if not isinstance(name, str):
        raise ValueError('unsupported source')
    key = name.strip().lower()
    mapped = SOURCE_ALIASES.get(key, key)
    if mapped not in SOURCES:
        raise ValueError(f'unsupported source: {name}')
    return mapped


def normalize_doi(value: str | None) -> str:
    if not isinstance(value, str):
        return ''
    value = value.strip().lower()
    value = re.sub(r'^https?://(?:dx\.)?doi\.org/', '', value)
    return value.removeprefix('doi:').strip()


def extract_arxiv_from_doi(doi: str | None) -> str | None:
    norm = normalize_doi(doi)
    if not norm:
        return None
    m = ARXIV_DOI_RE.match(norm)
    if not m:
        return None
    return re.sub(r'v\d+$', '', m.group(1), flags=re.I).lower()


def normalize_arxiv_id(value: str | None) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    val = value.strip()
    from_doi = extract_arxiv_from_doi(val)
    if from_doi:
        return from_doi
    m = ARXIV_ID_RE.match(val)
    if m:
        return m.group(1).lower()
    val = val.rsplit('/', 1)[-1].removeprefix('arxiv:').removeprefix('arXiv:')
    val = re.sub(r'v\d+$', '', val, flags=re.I).lower()
    if re.fullmatch(r'\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z-]+)?/\d{7}', val):
        return val
    return None


def normalize_title(title: str | None) -> str:
    if not isinstance(title, str):
        return ''
    text = unicodedata.normalize('NFKC', title).casefold()
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'[^\w\s]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


_PREPRINT_VENUES = frozenset({
    'arxiv',
    'arxiv.org',
    'arxiv (cornell university)',
    'corr',
    'biorxiv',
    'medrxiv',
    'chemrxiv',
    'techrxiv',
    'research square',
    'preprints.org',
    'ssrn',
})


def _is_preprint_venue(venue: str | None) -> bool:
    if not isinstance(venue, str) or not venue.strip():
        return False
    return venue.strip().lower() in _PREPRINT_VENUES


def is_preprint_doi(doi: str | None) -> bool:
    norm = normalize_doi(doi)
    return bool(norm and ARXIV_DOI_RE.match(norm))


def normalize_source_id(source, value):
    source = normalize_source_name(source) if source not in SOURCES else source
    value = value.strip()
    if source == 'arxiv':
        norm = normalize_arxiv_id(value)
        if norm:
            return norm
        value = value.rsplit('/', 1)[-1].removeprefix('arxiv:')
        return re.sub(r'v\d+$', '', value, flags=re.IGNORECASE).lower()
    if source == 'openalex':
        return value.rsplit('/', 1)[-1].lower()
    if source == 'crossref':
        return normalize_doi(value)
    if source == 'acl':
        return value.removeprefix('acl:').lower()
    if source == 'huggingface':
        return value.removeprefix('hf:').lower()
    return value.lower()


CANONICAL_SOURCE_STATUSES = (
    'complete',
    'bounded_partial',
    'valid_zero_results',
    'rate_limited',
    'bot_blocked',
    'source_failed',
)


def canonicalize_source_status(raw_status: str | None, returned: int = 0) -> str:
    raw = str(raw_status or '').strip()
    low = raw.lower()
    try:
        count = 0 if isinstance(returned, bool) else int(returned or 0)
    except (TypeError, ValueError):
        count = 0
    if low in CANONICAL_SOURCE_STATUSES:
        return low
    if low == 'ok':
        return 'complete' if count > 0 else 'valid_zero_results'
    if low in {'http_429', 'partial_http_429'}:
        return 'rate_limited'
    if (
        low in {'cloudflare', 'anubis', 'partial_cloudflare', 'partial_anubis', 'partial_bot_blocked'}
        or low.startswith('bot_blocked')
        or low.startswith('bot_challenge')
        or low.startswith('partial_bot_blocked')
        or low.startswith('partial_bot_challenge')
    ):
        return 'bot_blocked'
    if low in {'repeated_page', 'missing_or_repeated_cursor', 'truncated_api_cap'}:
        return 'bounded_partial'
    if low.startswith('partial_'):
        return 'bounded_partial' if count > 0 else 'source_failed'
    return 'source_failed'


def status_category(status: str | None, returned: int = 1) -> str:
    return canonicalize_source_status(status, returned=returned)


def parse_retry_after(header_value: str | None, now: datetime | None = None) -> float | None:
    if not header_value:
        return None
    text = str(header_value).strip()
    try:
        return max(0.0, min(float(text), 30.0))
    except ValueError:
        pass
    try:
        dt = email.utils.parsedate_to_datetime(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        ref = now if now is not None else datetime.now(timezone.utc)
        return max(0.0, min((dt - ref).total_seconds(), 30.0))
    except (TypeError, ValueError):
        return None


def _ratelimit_cache_path() -> Path | None:
    base = os.environ.get('RESEARCH_SCIENTIST_CACHE_DIR', '').strip()
    if base:
        return Path(base).expanduser() / '_ratelimit.json'
    home = os.environ.get('HOME', '').strip()
    if not home:
        return None
    return Path(home) / '.cache' / 'research-scientist' / '_ratelimit.json'


def _load_persisted_timestamps() -> dict[str, float]:
    path = _ratelimit_cache_path()
    if path is None or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(data, dict):
            return {str(k): float(v) for k, v in data.items() if isinstance(v, (int, float))}
    except (OSError, ValueError, TypeError):
        pass
    return {}


def _save_persisted_timestamps(timestamps: dict[str, float]) -> None:
    path = _ratelimit_cache_path()
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(timestamps), encoding='utf-8')
    except OSError:
        pass


def _throttle_host(host: str, min_interval: float, sleep_fn=time.sleep) -> None:
    if not host or min_interval <= 0:
        return
    with _HOST_LOCK:
        now = time.time()
        last = _HOST_LAST_CALL.get(host)
        if last is None:
            persisted = _load_persisted_timestamps()
            last = persisted.get(host)
        wait = (last + min_interval - now) if last is not None else 0.0
        if wait > 0:
            sleep_fn(wait)
        updated = time.time()
        _HOST_LAST_CALL[host] = updated
        persisted = _load_persisted_timestamps()
        persisted[host] = updated
        _save_persisted_timestamps(persisted)


def _is_bot_blocked(status: int, content_type: str, body_bytes: bytes) -> bool:
    ct = (content_type or '').lower()
    if status == 202 and 'html' in ct:
        return True
    head = body_bytes[:8192]
    return any(marker in head for marker in ANUBIS_MARKERS)


def _read(url, headers, timeout, xml=False, max_bytes=8_000_000, raw_text=False,
          max_retries=3, base_backoff=1.0, sleep_fn=time.sleep):
    host = (urlparse(url).hostname or '').lower()
    min_interval = DEFAULT_MIN_INTERVALS.get(host, 0.25)
    if host == 'api.semanticscholar.org' and not os.environ.get('S2_API_KEY'):
        min_interval = 2.0

    for attempt in range(max_retries + 1):
        _throttle_host(host, min_interval, sleep_fn=sleep_fn)
        try:
            with urlopen(Request(url, headers=headers), timeout=timeout) as response:
                status = getattr(response, 'status', 200)
                ct = response.headers.get('Content-Type', '') if getattr(response, 'headers', None) else ''
                body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise RuntimeError('response_too_large')
            if _is_bot_blocked(status, ct, body):
                raise RuntimeError('bot_blocked')
            if raw_text:
                return body.decode('utf-8', errors='replace')
            if xml:
                try:
                    return DET.fromstring(body)
                except (DefusedXmlException, ET.ParseError, ValueError) as exc:
                    raise RuntimeError('invalid_xml') from exc
            try:
                return json.loads(body)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise RuntimeError('invalid_json') from exc
        except HTTPError as exc:
            err_body = b''
            try:
                err_body = exc.read(8192)
            except Exception:
                pass
            ct = exc.headers.get('Content-Type', '') if exc.headers else ''
            if _is_bot_blocked(exc.code, ct, err_body):
                raise RuntimeError('bot_blocked') from exc
            if exc.code in RETRYABLE_HTTP_CODES and attempt < max_retries:
                ra = parse_retry_after(exc.headers.get('Retry-After') if exc.headers else None)
                backoff = ra if ra is not None else min(30.0, base_backoff * (2 ** attempt))
                sleep_fn(backoff)
                continue
            raise RuntimeError(f'http_{exc.code}') from exc
        except (URLError, TimeoutError, OSError) as exc:
            if attempt < max_retries:
                sleep_fn(min(30.0, base_backoff * (2 ** attempt)))
                continue
            raise RuntimeError('network_failure') from exc
    raise RuntimeError('network_failure')


def _reconstruct_openalex_abstract(inverted_index: dict | None) -> str | None:
    """Reconstruct abstract text from OpenAlex inverted index (clean-room spec)."""
    if not isinstance(inverted_index, dict) or not inverted_index:
        return None
    pairs = []
    for word, positions in inverted_index.items():
        if isinstance(word, str) and isinstance(positions, list):
            for pos in positions:
                if isinstance(pos, int):
                    pairs.append((pos, word))
    if not pairs:
        return None
    pairs.sort(key=lambda x: x[0])
    return ' '.join(w for _, w in pairs).strip() or None


def _strip_tags(text: str | None) -> str | None:
    if not isinstance(text, str) or not text.strip():
        return None
    cleaned = html.unescape(re.sub(r'<[^>]+>', ' ', text))
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned or None


def _parse_acl_html(html_text: str, filter_query: str | None = None, url_kind: str = 'events') -> dict:
    """Parse ACL Anthology event/volume HTML pages extracting title, ID, abstract, authors, PDF."""
    # Extract volume/paper anchors like href=/2025.acl-long.1/ or href="/2025.acl-long.1/"
    # and inline <div ... id=abstract-2025--acl-long--1 ...>...</div>
    abstract_map: dict[str, str] = {}
    abs_re = re.compile(
        r'<div[^>]+id=["\']?abstract-([A-Za-z0-9._-]+)["\']?[^>]*>(.*?)</div>',
        re.I | re.S,
    )
    for m in abs_re.finditer(html_text):
        key = m.group(1).replace('--', '.').lower()
        abs_txt = _strip_tags(m.group(2))
        if abs_txt:
            abstract_map[key] = abs_txt

    paper_re = re.compile(
        r'<a[^>]+href=["\']?/((?:19|20)\d{2}\.[a-z0-9-]+(?:\.\d+)?)["\'/][^>]*>(.*?)</a>',
        re.I | re.S,
    )
    seen_ids = set()
    items = []
    filter_terms = [t.casefold() for t in re.findall(r'[^\W_]+', filter_query or '') if len(t) >= 2]
    for m in paper_re.finditer(html_text):
        pid = m.group(1).strip('/')
        if pid.endswith('.pdf') or pid.endswith('.bib') or pid in seen_ids:
            continue
        title = _strip_tags(m.group(2))
        if not title or len(title) < 4 or title.lower() in {'pdf', 'bib', 'abs', 'abstract'}:
            continue
        seen_ids.add(pid)
        abstract = abstract_map.get(pid.lower()) or abstract_map.get(pid.replace('.', '--').lower())
        if filter_terms:
            haystack = f'{title} {abstract or ""}'.casefold()
            if not all(term in haystack for term in filter_terms):
                continue
        year_match = re.match(r'^((?:19|20)\d{2})\.', pid)
        year = int(year_match.group(1)) if year_match else None
        doi = f'10.18653/v1/{pid}' if re.match(r'^20\d{2}\.', pid) else None
        items.append({
            'id': pid,
            'title': title,
            'abstract': abstract,
            'year': year,
            'doi': doi,
            'url': f'https://aclanthology.org/{pid}/',
            'pdf_url': f'https://aclanthology.org/{pid}.pdf',
            'venue': 'ACL Anthology',
        })
    return {'records': items, 'total': len(items), 'html_kind': url_kind}


def fetch(source, params, timeout=20, max_retries=3, sleep_fn=time.sleep):
    source = normalize_source_name(source) if source not in SOURCES else source
    email_addr = os.environ.get('CONTACT_EMAIL', '').strip()
    ua = 'ResearchScientistSkill/2.1 (scholarly-discovery)'
    if email_addr:
        ua = f'ResearchScientistSkill/2.1 (scholarly-discovery; mailto:{email_addr})'
    headers = {'Accept': 'application/json, application/atom+xml', 'User-Agent': ua}
    if source == 's2' and os.environ.get('S2_API_KEY'):
        headers['x-api-key'] = os.environ['S2_API_KEY']
    if source == 'openalex' and os.environ.get('OPENALEX_API_KEY'):
        headers['Authorization'] = 'Bearer ' + os.environ['OPENALEX_API_KEY']

    # Special ACL direct event/volume HTML mode
    if source == 'acl' and isinstance(params, dict) and params.get('_acl_direct_url'):
        direct_url = params['_acl_direct_url']
        html_headers = {'Accept': 'text/html,application/xhtml+xml', 'User-Agent': ua}
        body_text = _read(
            direct_url, html_headers, max(timeout, 30),
            max_bytes=32_000_000, raw_text=True, max_retries=max_retries, sleep_fn=sleep_fn,
        )
        return _parse_acl_html(body_text, filter_query=params.get('_acl_filter'), url_kind=params.get('_acl_kind', 'events'))

    req_params = dict(params or {})
    if email_addr and source in {'crossref', 'openalex', 'acl'} and 'mailto' not in req_params:
        req_params['mailto'] = email_addr
    if source == 'pubmed' and os.environ.get('NCBI_API_KEY') and 'api_key' not in req_params:
        req_params['api_key'] = os.environ['NCBI_API_KEY']

    url = ENDPOINTS[source] + '?' + urlencode(req_params)
    if source == 'arxiv':
        root = _read(url, headers, timeout, xml=True, max_retries=max_retries, sleep_fn=sleep_fn)
        atom = '{http://www.w3.org/2005/Atom}'
        arxiv_ns = '{http://arxiv.org/schemas/atom}'
        total_text = root.findtext('{http://a9.com/-/spec/opensearch/1.1/}totalResults')
        if total_text is None or not total_text.isdigit():
            raise RuntimeError('missing_or_invalid_total')
        entries = []
        for entry in root.findall(atom + 'entry'):
            authors = [
                a.findtext(atom + 'name').strip()
                for a in entry.findall(atom + 'author')
                if a.findtext(atom + 'name')
            ]
            pdf_url = None
            for link in entry.findall(atom + 'link'):
                if link.attrib.get('title') == 'pdf' or link.attrib.get('type') == 'application/pdf':
                    pdf_url = link.attrib.get('href')
                    break
            entries.append({
                'id': entry.findtext(atom + 'id'),
                'title': re.sub(r'\s+', ' ', entry.findtext(atom + 'title') or '').strip() or None,
                'summary': re.sub(r'\s+', ' ', entry.findtext(atom + 'summary') or '').strip() or None,
                'published': entry.findtext(atom + 'published'),
                'authors': authors,
                'doi': entry.findtext(arxiv_ns + 'doi'),
                'journal_ref': entry.findtext(arxiv_ns + 'journal_ref'),
                'pdf_url': pdf_url,
            })
        return {'entries': entries, 'total': int(total_text)}

    if source == 'pubmed':
        search_data = _read(url, headers, timeout, max_retries=max_retries, sleep_fn=sleep_fn)
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
        if os.environ.get('NCBI_API_KEY'):
            summary_params['api_key'] = os.environ['NCBI_API_KEY']
        summary_url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?' + urlencode(summary_params)
        summary_data = _read(summary_url, headers, timeout, max_retries=max_retries, sleep_fn=sleep_fn)
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
            authors = [a.get('name') for a in item.get('authors', []) if isinstance(a, dict) and a.get('name')]
            records.append({
                'id': pmid,
                'title': item.get('title'),
                'year': item.get('pubdate'),
                'doi': doi,
                'authors': authors,
                'venue': item.get('fulljournalname') or item.get('source'),
            })
        return {'records': records, 'total': int(count), 'query_translation': search_result.get('querytranslation')}

    return _read(url, headers, timeout, max_retries=max_retries, sleep_fn=sleep_fn)


def request_params(source, query, size, page, cursor=None, raw_arxiv=False, require_abstract=False, pages=1):
    source = normalize_source_name(source) if source not in SOURCES else source
    if source == 's2':
        return {
            'query': query.replace('-', ' '),
            'limit': size,
            'offset': (page - 1) * size,
            'fields': 'title,year,authors,abstract,externalIds,url,publicationDate,venue,publicationTypes,citationCount,openAccessPdf',
        }
    if source == 'openalex':
        params = {'search': query, 'per_page': size, 'page': page}
        if require_abstract:
            params['filter'] = 'has_abstract:true'
        return params
    if source == 'crossref':
        return {'query.bibliographic': query, 'rows': size, 'offset': (page - 1) * size}
    if source == 'arxiv':
        terms = re.findall(r'[^\W_]+', query, re.UNICODE)
        if not terms:
            raise ValueError('arxiv query has no searchable terms')
        return {
            'search_query': query if raw_arxiv else ' AND '.join('all:' + term for term in terms),
            'start': (page - 1) * size,
            'max_results': size,
            'sortBy': 'relevance',
        }
    if source == 'pubmed':
        return {
            'db': 'pubmed',
            'term': query,
            'retstart': (page - 1) * size,
            'retmax': size,
            'retmode': 'json',
            'sort': 'relevance',
            'tool': 'research-scientist-skill',
        }
    if source == 'acl':
        m = re.match(r'^(event|volume):([A-Za-z0-9._-]+)(?:\s+(.*))?$', query.strip(), re.I)
        if m:
            kind = 'events' if m.group(1).lower() == 'event' else 'volumes'
            slug = m.group(2)
            trailing = (m.group(3) or '').strip()
            return {
                '_acl_direct_url': f'https://aclanthology.org/{kind}/{slug}/',
                '_acl_kind': kind,
                '_acl_filter': trailing or None,
                'query.bibliographic': query,
            }
        return {
            'query.bibliographic': query,
            'filter': 'prefix:10.18653',
            'rows': size,
            'offset': (page - 1) * size,
        }
    if source == 'huggingface':
        return {'q': query, 'limit': min(size * pages, 120)}
    if source == 'dblp':
        return {'q': query, 'format': 'json', 'h': size, 'f': (page - 1) * size}
    return {'query': query, 'format': 'json', 'pageSize': size, 'resultType': 'core', 'cursorMark': cursor or '*'}


def _parse_year(value) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and len(value) >= 4 and value[:4].isdigit():
        return int(value[:4])
    return None


def _base_record(
    *,
    source: str,
    source_id: str,
    title: str,
    year: int | None,
    doi: str | None,
    abstract: str | None = None,
    authors: list[str] | None = None,
    venue: str | None = None,
    url: str | None = None,
    pdf_url: str | None = None,
    arxiv_id: str | None = None,
    openalex_id: str | None = None,
    s2_id: str | None = None,
    dblp_key: str | None = None,
    acl_id: str | None = None,
    pmid: str | None = None,
    preprint_only: bool = False,
    retraction_status: str = 'unchecked',
) -> dict:
    norm_doi = normalize_doi(doi) or None
    if not arxiv_id and norm_doi:
        arxiv_id = extract_arxiv_from_doi(norm_doi)
    if arxiv_id:
        arxiv_id = normalize_arxiv_id(arxiv_id) or arxiv_id.lower()
    return {
        'source': source,
        'source_id': str(source_id),
        'title': title,
        'year': year,
        'doi': norm_doi,
        'abstract': abstract,
        'authors': authors or [],
        'venue': venue,
        'url': url,
        'pdf_url': pdf_url,
        'arxiv_id': arxiv_id,
        'openalex_id': openalex_id,
        's2_id': s2_id,
        'dblp_key': dblp_key,
        'acl_id': acl_id,
        'pmid': pmid,
        'preprint_only': bool(preprint_only),
        'retraction_status': retraction_status,
        'scite_tallies': {
            'supporting': None,
            'mentioning': None,
            'contradicting': None,
            'status': 'unchecked',
        },
        'normalized_title': normalize_title(title),
        'ranking_basis': 'provider_order',
    }


def parse(source, data):
    source = normalize_source_name(source) if source not in SOURCES else source
    if source == 'huggingface':
        if isinstance(data, list):
            raw, total = data, len(data)
        elif isinstance(data, dict):
            raw = data.get('items') if isinstance(data.get('items'), list) else data.get('papers')
            total = data.get('total', len(raw) if isinstance(raw, list) else None)
        else:
            raise ValueError('unexpected_body')
    elif not isinstance(data, dict):
        raise ValueError('unexpected_body')
    elif source == 's2':
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
    elif source == 'acl':
        if 'records' in data:
            raw, total = data.get('records'), data.get('total')
        else:
            msg = data.get('message') or {}
            raw, total = msg.get('items'), msg.get('total-results')
    elif source == 'dblp':
        hits = ((data.get('result') or {}).get('hits')) if isinstance(data.get('result'), dict) else None
        if not isinstance(hits, dict):
            raise ValueError('missing_result_list')
        raw_total = hits.get('@total')
        try:
            total = int(raw_total)
        except (TypeError, ValueError):
            total = None
        hit = hits.get('hit')
        if hit is None:
            raw = []
        elif isinstance(hit, dict):
            raw = [hit]
        elif isinstance(hit, list):
            raw = hit
        else:
            raw = None
    else:
        raw, total = data.get('records'), data.get('total')

    if not isinstance(raw, list):
        raise ValueError('missing_result_list')
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        raise ValueError('missing_or_invalid_total')

    out = []
    for paper in raw:
        if not isinstance(paper, dict):
            continue
        if source == 's2':
            ids = paper.get('externalIds') or {}
            title = paper.get('title')
            doi = ids.get('DOI')
            identifier = paper.get('paperId')
            year = _parse_year(paper.get('year'))
            if title and identifier:
                authors = [a.get('name') for a in (paper.get('authors') or []) if isinstance(a, dict) and a.get('name')]
                pub_types = [str(t).lower() for t in (paper.get('publicationTypes') or []) if t]
                arxiv_id = normalize_arxiv_id(ids.get('ArXiv')) if ids.get('ArXiv') else None
                oa_pdf = paper.get('openAccessPdf') if isinstance(paper.get('openAccessPdf'), dict) else {}
                venue = paper.get('venue') or None
                venue_is_preprint = not venue or _is_preprint_venue(venue)
                preprint_only = bool(
                    ((arxiv_id or (doi and is_preprint_doi(doi))) and venue_is_preprint and (not doi or is_preprint_doi(doi)))
                    or (pub_types and all(t == 'preprint' for t in pub_types))
                )
                out.append(_base_record(
                    source=source,
                    source_id=str(identifier),
                    title=title,
                    year=year,
                    doi=doi,
                    abstract=paper.get('abstract'),
                    authors=authors,
                    venue=venue,
                    url=paper.get('url'),
                    pdf_url=oa_pdf.get('url'),
                    arxiv_id=arxiv_id,
                    s2_id=str(identifier),
                    preprint_only=preprint_only,
                ))
        elif source == 'openalex':
            title = paper.get('display_name') or paper.get('title')
            doi = paper.get('doi')
            identifier = paper.get('id')
            year = _parse_year(paper.get('publication_year'))
            if title and identifier:
                ids_obj = paper.get('ids') if isinstance(paper.get('ids'), dict) else {}
                oa_wid = str(identifier).rsplit('/', 1)[-1].upper()
                arxiv_id = normalize_arxiv_id(ids_obj.get('arxiv')) if ids_obj.get('arxiv') else None
                if not arxiv_id and doi:
                    arxiv_id = extract_arxiv_from_doi(doi)
                abstract = _reconstruct_openalex_abstract(paper.get('abstract_inverted_index'))
                authors = [
                    (a.get('author') or {}).get('display_name')
                    for a in (paper.get('authorships') or [])
                    if isinstance(a, dict) and isinstance(a.get('author'), dict) and (a.get('author') or {}).get('display_name')
                ]
                primary_loc = paper.get('primary_location') if isinstance(paper.get('primary_location'), dict) else {}
                loc_source = primary_loc.get('source') if isinstance(primary_loc.get('source'), dict) else {}
                venue = loc_source.get('display_name')
                pdf_url = primary_loc.get('pdf_url')
                oa_type = str(paper.get('type') or '').lower()
                retracted = paper.get('is_retracted')
                ret_status = 'retracted' if retracted is True else ('clean' if retracted is False else 'unchecked')
                norm_doi = normalize_doi(doi)
                preprint_only = (oa_type == 'preprint') or (bool(norm_doi) and is_preprint_doi(norm_doi))
                out.append(_base_record(
                    source=source,
                    source_id=str(identifier),
                    title=title,
                    year=year,
                    doi=doi,
                    abstract=abstract,
                    authors=authors,
                    venue=venue,
                    url=str(identifier),
                    pdf_url=pdf_url,
                    arxiv_id=arxiv_id,
                    openalex_id=oa_wid,
                    preprint_only=preprint_only,
                    retraction_status=ret_status,
                ))
        elif source == 'crossref':
            title = next(iter(paper.get('title') or []), None)
            doi = paper.get('DOI')
            identifier = doi
            date_parts = ((paper.get('published') or {}).get('date-parts') or [[]])[0]
            year = _parse_year(date_parts[0] if date_parts else None)
            if title and identifier:
                authors = [
                    ' '.join(p for p in (a.get('given'), a.get('family')) if p)
                    for a in (paper.get('author') or [])
                    if isinstance(a, dict) and (a.get('given') or a.get('family'))
                ]
                venue = next(iter(paper.get('container-title') or []), None)
                cr_type = str(paper.get('type') or '').lower()
                preprint_only = (cr_type == 'posted-content') or is_preprint_doi(doi)
                out.append(_base_record(
                    source=source,
                    source_id=str(identifier),
                    title=title,
                    year=year,
                    doi=doi,
                    abstract=_strip_tags(paper.get('abstract')),
                    authors=authors,
                    venue=venue,
                    url=paper.get('URL'),
                    preprint_only=preprint_only,
                ))
        elif source == 'europepmc':
            title = paper.get('title')
            doi = paper.get('doi')
            identifier = f"{paper.get('source')}:{paper.get('id')}" if paper.get('source') and paper.get('id') else None
            year = _parse_year(paper.get('pubYear'))
            if title and identifier:
                pub_type = str(paper.get('pubType') or '').lower()
                preprint_only = (paper.get('source') == 'PPR') or ('preprint' in pub_type)
                out.append(_base_record(
                    source=source,
                    source_id=str(identifier),
                    title=title,
                    year=year,
                    doi=doi,
                    abstract=_strip_tags(paper.get('abstractText')),
                    venue=paper.get('journalTitle'),
                    pmid=str(paper.get('pmid')) if paper.get('pmid') else None,
                    preprint_only=preprint_only,
                ))
        elif source == 'arxiv':
            title = paper.get('title')
            identifier = paper.get('id')
            year = _parse_year(paper.get('published'))
            doi = paper.get('doi')
            if isinstance(identifier, str):
                identifier = 'arxiv:' + identifier.rsplit('/', 1)[-1]
            if title and identifier:
                bare_arxiv = normalize_arxiv_id(identifier)
                journal_ref = paper.get('journal_ref')
                norm_doi = normalize_doi(doi)
                preprint_only = not bool(journal_ref or (norm_doi and not is_preprint_doi(norm_doi)))
                out.append(_base_record(
                    source=source,
                    source_id=str(identifier),
                    title=title,
                    year=year,
                    doi=norm_doi or None,
                    abstract=paper.get('summary'),
                    authors=paper.get('authors') or [],
                    venue=journal_ref,
                    url=f'https://arxiv.org/abs/{bare_arxiv}' if bare_arxiv else None,
                    pdf_url=paper.get('pdf_url') or (f'https://arxiv.org/pdf/{bare_arxiv}' if bare_arxiv else None),
                    arxiv_id=bare_arxiv,
                    preprint_only=preprint_only,
                ))
        elif source == 'acl':
            if 'id' in paper and 'DOI' not in paper:
                pid = str(paper['id'])
                title = paper.get('title')
                if title and pid:
                    out.append(_base_record(
                        source='acl',
                        source_id=f'acl:{pid}',
                        title=title,
                        year=_parse_year(paper.get('year')),
                        doi=paper.get('doi'),
                        abstract=paper.get('abstract'),
                        authors=paper.get('authors') or [],
                        venue=paper.get('venue') or 'ACL Anthology',
                        url=paper.get('url'),
                        pdf_url=paper.get('pdf_url'),
                        acl_id=pid,
                        preprint_only=False,
                    ))
            else:
                title = next(iter(paper.get('title') or []), None)
                doi = paper.get('DOI')
                date_parts = ((paper.get('published') or {}).get('date-parts') or [[]])[0]
                year = _parse_year(date_parts[0] if date_parts else None)
                if title and doi:
                    m = ACL_DOI_RE.match(str(doi).strip())
                    acl_id = m.group(1) if m else str(doi)
                    authors = [
                        ' '.join(p for p in (a.get('given'), a.get('family')) if p)
                        for a in (paper.get('author') or [])
                        if isinstance(a, dict) and (a.get('given') or a.get('family'))
                    ]
                    out.append(_base_record(
                        source='acl',
                        source_id=f'acl:{acl_id}',
                        title=title,
                        year=year,
                        doi=doi,
                        abstract=_strip_tags(paper.get('abstract')),
                        authors=authors,
                        venue=next(iter(paper.get('container-title') or []), None) or 'ACL Anthology',
                        url=f'https://aclanthology.org/{acl_id}/' if m else paper.get('URL'),
                        pdf_url=f'https://aclanthology.org/{acl_id}.pdf' if m else None,
                        acl_id=acl_id,
                        preprint_only=False,
                    ))
        elif source == 'huggingface':
            inner = paper.get('paper') if isinstance(paper.get('paper'), dict) else paper
            pid = inner.get('id') or paper.get('id')
            title = inner.get('title') or paper.get('title')
            if title and pid:
                pid_str = str(pid).strip()
                arxiv_id = normalize_arxiv_id(pid_str)
                year = _parse_year(inner.get('publishedAt') or paper.get('publishedAt'))
                authors = [
                    a.get('name') for a in (inner.get('authors') or [])
                    if isinstance(a, dict) and a.get('name')
                ]
                out.append(_base_record(
                    source='huggingface',
                    source_id=f'hf:{pid_str}',
                    title=title,
                    year=year,
                    doi=f'10.48550/arxiv.{arxiv_id}' if arxiv_id else None,
                    abstract=inner.get('summary') or inner.get('abstract'),
                    authors=authors,
                    venue='HuggingFace Papers',
                    url=f'https://huggingface.co/papers/{pid_str}',
                    pdf_url=f'https://arxiv.org/pdf/{arxiv_id}' if arxiv_id else None,
                    arxiv_id=arxiv_id,
                    preprint_only=True,
                ))
        elif source == 'dblp':
            info = paper.get('info') if isinstance(paper.get('info'), dict) else paper
            raw_title = info.get('title')
            if isinstance(raw_title, dict):
                raw_title = raw_title.get('#text') or raw_title.get('text')
            title = raw_title.strip().rstrip('.') if isinstance(raw_title, str) else None
            dblp_key = info.get('key') or paper.get('@id')
            if title and dblp_key:
                dblp_key_str = str(dblp_key).strip()
                doi = info.get('doi')
                year = _parse_year(info.get('year'))
                authors_block = (info.get('authors') or {}).get('author') if isinstance(info.get('authors'), dict) else None
                if isinstance(authors_block, dict):
                    authors_block = [authors_block]
                authors = []
                if isinstance(authors_block, list):
                    for a in authors_block:
                        if isinstance(a, dict) and a.get('text'):
                            authors.append(a['text'])
                        elif isinstance(a, str):
                            authors.append(a)
                ee = info.get('ee')
                if isinstance(ee, list):
                    ee = ee[0] if ee else None
                norm_doi = normalize_doi(doi)
                preprint_only = dblp_key_str.lower().startswith('journals/corr/') and not (norm_doi and not is_preprint_doi(norm_doi))
                out.append(_base_record(
                    source='dblp',
                    source_id=dblp_key_str,
                    title=title,
                    year=year,
                    doi=norm_doi or None,
                    authors=authors,
                    venue=info.get('venue'),
                    url=ee if isinstance(ee, str) else info.get('url'),
                    dblp_key=dblp_key_str,
                    preprint_only=preprint_only,
                ))
        else:  # pubmed
            title = paper.get('title')
            doi = paper.get('doi')
            identifier = f"pmid:{paper.get('id')}" if paper.get('id') else None
            year = _parse_year(paper.get('year'))
            if title and identifier:
                out.append(_base_record(
                    source=source,
                    source_id=str(identifier),
                    title=title,
                    year=year,
                    doi=doi,
                    authors=paper.get('authors') or [],
                    venue=paper.get('venue'),
                    pmid=str(paper.get('id')),
                    preprint_only=False,
                ))

    if raw and not out:
        raise ValueError('no_valid_records_in_nonempty_page')
    return out, total


def compute_dedup_key(rec: dict) -> str:
    doi = normalize_doi(rec.get('doi'))
    arxiv_id = normalize_arxiv_id(rec.get('arxiv_id')) if rec.get('arxiv_id') else extract_arxiv_from_doi(doi)
    if doi and not is_preprint_doi(doi):
        return f'doi:{doi}'
    if arxiv_id:
        return f'arxiv:{arxiv_id}'
    if doi:
        return f'doi:{doi}'
    if rec.get('dblp_key'):
        return f"dblp:{str(rec['dblp_key']).lower()}"
    if rec.get('openalex_id'):
        return f"openalex:{str(rec['openalex_id']).lower()}"
    if rec.get('s2_id'):
        return f"s2:{str(rec['s2_id']).lower()}"
    if rec.get('pmid'):
        return f"pmid:{str(rec['pmid']).lower()}"
    if rec.get('acl_id'):
        return f"acl:{str(rec['acl_id']).lower()}"
    nt = rec.get('normalized_title') or normalize_title(rec.get('title'))
    return f'title:{nt}'


def _enrich_ids_from_record(rec: dict) -> dict:
    copy = dict(rec)
    source = copy.get('source', '')
    sid = str(copy.get('source_id') or '')
    doi = normalize_doi(copy.get('doi')) or None
    copy['doi'] = doi
    if not copy.get('arxiv_id'):
        if source == 'arxiv' or sid.lower().startswith('arxiv:'):
            copy['arxiv_id'] = normalize_arxiv_id(sid)
        elif doi:
            copy['arxiv_id'] = extract_arxiv_from_doi(doi)
    if copy.get('arxiv_id'):
        copy['arxiv_id'] = normalize_arxiv_id(copy['arxiv_id']) or str(copy['arxiv_id']).lower()
    if copy.get('openalex_id'):
        copy['openalex_id'] = str(copy['openalex_id']).strip().rsplit('/', 1)[-1].upper()
    elif source == 'openalex' and sid:
        copy['openalex_id'] = sid.strip().rsplit('/', 1)[-1].upper()
    if not copy.get('s2_id') and source == 's2':
        copy['s2_id'] = sid
    if not copy.get('dblp_key') and source == 'dblp':
        copy['dblp_key'] = sid
    if not copy.get('acl_id') and source == 'acl':
        copy['acl_id'] = sid.removeprefix('acl:')
    if not copy.get('pmid') and source == 'pubmed':
        copy['pmid'] = sid.removeprefix('pmid:')
    if not copy.get('normalized_title'):
        copy['normalized_title'] = normalize_title(copy.get('title'))
    if 'preprint_only' not in copy:
        copy['preprint_only'] = bool(
            source in PREPRINT_SOURCES
            or (doi and is_preprint_doi(doi))
            or (copy.get('dblp_key', '').lower().startswith('journals/corr/'))
        )
    return copy


def _has_published_doi_conflict(a: dict, b: dict) -> bool:
    da, db = normalize_doi(a.get('doi')), normalize_doi(b.get('doi'))
    if da and db and da != db and not is_preprint_doi(da) and not is_preprint_doi(db):
        return True
    return False


def deduplicate_records(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """Transitive 4-ID + bare-arXiv + normalized-title deduplication (sgha Apache-2.0 pattern).

    Returns (merged_results, dedup_groups).
    Retains title-only records with resolution='unresolved-keep' (never silently drops them).
    """
    clusters: list[dict] = []
    by_doi: dict[str, int] = {}
    by_arxiv: dict[str, int] = {}
    by_openalex: dict[str, int] = {}
    by_s2: dict[str, int] = {}
    by_dblp: dict[str, int] = {}
    by_acl: dict[str, int] = {}
    by_pmid: dict[str, int] = {}
    by_title: dict[str, list[int]] = {}

    def _register(idx: int, rec: dict) -> None:
        if rec.get('doi'):
            by_doi.setdefault(rec['doi'], idx)
        if rec.get('arxiv_id'):
            by_arxiv.setdefault(rec['arxiv_id'], idx)
        if rec.get('openalex_id'):
            by_openalex.setdefault(rec['openalex_id'].lower(), idx)
        if rec.get('s2_id'):
            by_s2.setdefault(rec['s2_id'].lower(), idx)
        if rec.get('dblp_key'):
            by_dblp.setdefault(rec['dblp_key'].lower(), idx)
        if rec.get('acl_id'):
            by_acl.setdefault(rec['acl_id'].lower(), idx)
        if rec.get('pmid'):
            by_pmid.setdefault(rec['pmid'].lower(), idx)
        nt = rec.get('normalized_title') or ''
        if len(nt) >= 10:
            bucket = by_title.setdefault(nt, [])
            if idx not in bucket:
                bucket.append(idx)

    def _find_match(rec: dict) -> int | None:
        for map_dict, key in (
            (by_doi, rec.get('doi')),
            (by_arxiv, rec.get('arxiv_id')),
            (by_openalex, rec.get('openalex_id', '').lower() if rec.get('openalex_id') else None),
            (by_s2, rec.get('s2_id', '').lower() if rec.get('s2_id') else None),
            (by_dblp, rec.get('dblp_key', '').lower() if rec.get('dblp_key') else None),
            (by_acl, rec.get('acl_id', '').lower() if rec.get('acl_id') else None),
            (by_pmid, rec.get('pmid', '').lower() if rec.get('pmid') else None),
        ):
            if key and key in map_dict:
                cand_idx = map_dict[key]
                if not _has_published_doi_conflict(clusters[cand_idx]['merged'], rec):
                    return cand_idx
        nt = rec.get('normalized_title') or ''
        if len(nt) >= 10 and nt in by_title:
            for cand_idx in by_title[nt]:
                existing = clusters[cand_idx]['merged']
                if _has_published_doi_conflict(existing, rec):
                    continue
                ya, yb = existing.get('year'), rec.get('year')
                if isinstance(ya, int) and isinstance(yb, int) and abs(ya - yb) > 2:
                    continue
                return cand_idx
        return None

    for raw_idx, raw_rec in enumerate(records):
        rec = _enrich_ids_from_record(raw_rec)
        match_idx = _find_match(rec)
        if match_idx is None:
            has_id = any(rec.get(k) for k in ('doi', 'arxiv_id', 'openalex_id', 's2_id', 'dblp_key', 'acl_id', 'pmid'))
            merged = dict(rec)
            merged['sources_seen'] = [rec['source']] if rec.get('source') else []
            merged['source_ids'] = [{'source': rec.get('source'), 'source_id': rec.get('source_id')}]
            merged['discovered_by'] = list(rec.get('discovered_by') or [])
            merged['resolution'] = 'resolved' if has_id else 'unresolved-keep'
            merged['ranking_basis'] = 'provider_order'
            merged.setdefault('retraction_status', 'unchecked')
            merged.setdefault('scite_tallies', {'supporting': None, 'mentioning': None, 'contradicting': None, 'status': 'unchecked'})
            merged['dedup_key'] = compute_dedup_key(merged)
            cluster_idx = len(clusters)
            clusters.append({
                'merged': merged,
                'members': [{'source': rec.get('source'), 'source_id': rec.get('source_id'), 'index': raw_idx}],
                'preprint_flags': [bool(rec.get('preprint_only'))],
            })
            _register(cluster_idx, merged)
        else:
            cluster = clusters[match_idx]
            existing = cluster['merged']
            cluster['members'].append({'source': rec.get('source'), 'source_id': rec.get('source_id'), 'index': raw_idx})
            cluster['preprint_flags'].append(bool(rec.get('preprint_only')))
            if rec.get('source') and rec['source'] not in existing['sources_seen']:
                existing['sources_seen'].append(rec['source'])
            sid_pair = {'source': rec.get('source'), 'source_id': rec.get('source_id')}
            if sid_pair not in existing['source_ids']:
                existing['source_ids'].append(sid_pair)
            for qid in (rec.get('discovered_by') or []):
                if qid not in existing['discovered_by']:
                    existing['discovered_by'].append(qid)
            # Prefer non-preprint DOI over 10.48550/arxiv.* DOI
            if rec.get('doi'):
                if not existing.get('doi') or (is_preprint_doi(existing['doi']) and not is_preprint_doi(rec['doi'])):
                    existing['doi'] = rec['doi']
            for id_field in ('arxiv_id', 'openalex_id', 's2_id', 'dblp_key', 'acl_id', 'pmid'):
                if not existing.get(id_field) and rec.get(id_field):
                    existing[id_field] = rec[id_field]
            if not existing.get('abstract') and rec.get('abstract'):
                existing['abstract'] = rec['abstract']
            if not existing.get('authors') and rec.get('authors'):
                existing['authors'] = rec['authors']
            if existing.get('year') is None and rec.get('year') is not None:
                existing['year'] = rec['year']
            if not existing.get('venue') and rec.get('venue'):
                existing['venue'] = rec['venue']
            if not existing.get('url') and rec.get('url'):
                existing['url'] = rec['url']
            if not existing.get('pdf_url') and rec.get('pdf_url'):
                existing['pdf_url'] = rec['pdf_url']
            # Combine retraction status conservatively
            if rec.get('retraction_status') == 'retracted' or existing.get('retraction_status') == 'retracted':
                existing['retraction_status'] = 'retracted'
            elif existing.get('retraction_status') == 'unchecked' and rec.get('retraction_status') == 'clean':
                existing['retraction_status'] = 'clean'
            existing['preprint_only'] = all(cluster['preprint_flags'])
            has_id = any(existing.get(k) for k in ('doi', 'arxiv_id', 'openalex_id', 's2_id', 'dblp_key', 'acl_id', 'pmid'))
            existing['resolution'] = 'resolved' if has_id else 'unresolved-keep'
            existing['dedup_key'] = compute_dedup_key(existing)
            _register(match_idx, existing)

    merged_results = [c['merged'] for c in clusters]
    dedup_groups = [
        {
            'dedup_key': c['merged']['dedup_key'],
            'member_count': len(c['members']),
            'sources_seen': c['merged']['sources_seen'],
            'members': c['members'],
        }
        for c in clusters if len(c['members']) > 1
    ]
    return merged_results, dedup_groups


def build_fanout_queries(query: str) -> list[str]:
    """Build up to 3 deterministic query variants (Vane MIT academicSearch 3-query fan-out pattern)."""
    q = re.sub(r'\s+', ' ', query.strip())
    variants = [q]
    unhyphenated = re.sub(r'[-_/]+', ' ', q)
    unhyphenated = re.sub(r'\s+', ' ', unhyphenated).strip()
    if unhyphenated and unhyphenated not in variants:
        variants.append(unhyphenated)
    stop = {'a', 'an', 'the', 'of', 'for', 'in', 'on', 'with', 'to', 'and', 'or', 'using', 'via', 'based', 'is', 'are'}
    tokens = [t for t in re.findall(r'[^\W_]+', unhyphenated, re.UNICODE) if t.lower() not in stop]
    core = ' '.join(tokens[:6]).strip()
    if core and core not in variants:
        variants.append(core)
    return variants[:3]


def check_known_seeds(records, source_states, known_dois=(), known_source_ids=()):
    """Exact identifier checks within this run; a miss never certifies absence."""
    checks = []
    for requested in known_dois:
        if not isinstance(requested, str) or not normalize_doi(requested):
            raise ValueError('known DOI must be nonblank')
        key = normalize_doi(requested)
        arxiv_from_doi = extract_arxiv_from_doi(key)
        matches = [
            r for r in records
            if (r.get('doi') and normalize_doi(r['doi']) == key)
            or (arxiv_from_doi and r.get('arxiv_id') and normalize_arxiv_id(r['arxiv_id']) == arxiv_from_doi)
            or (arxiv_from_doi and r.get('source') == 'arxiv' and normalize_source_id('arxiv', r.get('source_id', '')) == arxiv_from_doi)
        ]
        checks.append({
            'kind': 'doi',
            'requested': requested,
            'status': 'retrieved' if matches else 'not_retrieved_in_this_run',
            'matched_source_ids': [r['source_id'] for r in matches],
        })
    for raw_source, requested in known_source_ids:
        source = normalize_source_name(raw_source) if raw_source not in SOURCES else raw_source
        if not isinstance(requested, str) or not requested.strip():
            raise ValueError('known source ID needs a supported source and nonblank ID')
        key = normalize_source_id(source, requested)
        matches = [
            r for r in records
            if r['source'] == source and normalize_source_id(source, r['source_id']) == key
        ]
        src_state = source_states.get(source, {})
        entry = {
            'kind': 'source_id',
            'source': source,
            'requested': requested,
            'source_status': src_state.get('status', 'not_queried'),
            'status': 'retrieved' if matches else 'not_retrieved_in_this_run',
            'matched_source_ids': [r['source_id'] for r in matches],
        }
        if 'raw_status' in src_state:
            entry['source_raw_status'] = src_state['raw_status']
        checks.append(entry)
    return checks


def _executed_query_for(source: str, params: dict) -> str | None:
    key_map = {
        'arxiv': 'search_query',
        'pubmed': 'term',
        'crossref': 'query.bibliographic',
        'europepmc': 'query',
        'openalex': 'search',
        's2': 'query',
        'acl': 'query.bibliographic',
        'huggingface': 'q',
        'dblp': 'q',
    }
    return params.get(key_map[source])


def search(
    query,
    sources=SOURCES,
    size=20,
    pages=1,
    transport=fetch,
    source_queries=None,
    known_dois=(),
    known_source_ids=(),
    *,
    mode='balanced',
    fanout=None,
    fanout_queries=None,
    require_abstract=False,
    enrich_scite=False,
    enrich_retraction=False,
):
    if not isinstance(query, str) or not query.strip() or len(query) > 500:
        raise ValueError('query must contain 1..500 nonblank characters')
    if not 1 <= size <= 100 or not 1 <= pages <= 5:
        raise ValueError('size must be 1..100 and pages 1..5')
    if mode not in MODES:
        raise ValueError(f'mode must be one of {MODES}')
    normalized_sources = tuple(normalize_source_name(s) if s not in SOURCES else s for s in sources)
    source_queries = source_queries or {}
    if not isinstance(source_queries, dict):
        raise ValueError('source_queries must be a dict')
    norm_source_queries = {}
    for k, v in source_queries.items():
        nk = normalize_source_name(k) if k not in SOURCES else k
        if not isinstance(v, str) or not v.strip() or len(v) > 500:
            raise ValueError('source_queries must map supported sources to nonblank queries of at most 500 characters')
        norm_source_queries[nk] = v

    if fanout_queries is not None:
        if not isinstance(fanout_queries, (list, tuple)) or not 1 <= len(fanout_queries) <= 3:
            raise ValueError('fanout_queries must contain 1..3 nonblank strings')
        executed_queries = [q.strip() for q in fanout_queries if isinstance(q, str) and q.strip()]
        if len(executed_queries) != len(fanout_queries):
            raise ValueError('fanout_queries must contain nonblank strings')
    elif fanout is True or (fanout is None and mode == 'quality'):
        executed_queries = build_fanout_queries(query)
    else:
        executed_queries = [query.strip()]

    known_dois = tuple(known_dois)
    known_source_ids = tuple(known_source_ids)
    if any(not isinstance(pair, (tuple, list)) or len(pair) != 2 for pair in known_source_ids):
        raise ValueError('known source IDs must be SOURCE=ID pairs')
    for requested in known_dois:
        if not isinstance(requested, str) or not normalize_doi(requested):
            raise ValueError('known DOI must be nonblank')
    norm_known_source_ids = []
    for raw_source, requested in known_source_ids:
        src = normalize_source_name(raw_source) if raw_source not in SOURCES else raw_source
        if not isinstance(requested, str) or not requested.strip():
            raise ValueError('known source ID needs a supported source and nonblank ID')
        norm_known_source_ids.append((src, requested))

    result = {
        'schema': 'research_scientist_search_v2',
        'query': query,
        'mode': mode,
        'require_abstract': bool(require_abstract),
        'executed_queries': executed_queries,
        'checked_at_utc': datetime.now(timezone.utc).isoformat(),
        'sources': {},
        'records': [],
        'doi_duplicate_groups': {},
        'dedup_groups': [],
        'results': [],
        'known_seed_checks': [],
    }

    for source in normalized_sources:
        state = {
            'status': 'complete',
            'status_category': 'complete',
            'pages_requested': pages,
            'pages_read': 0,
            'returned': 0,
            'reported_total': None,
            'access': 'key' if os.environ.get({'s2': 'S2_API_KEY', 'openalex': 'OPENALEX_API_KEY'}.get(source, '')) else 'keyless',
        }
        result['sources'][source] = state
        query_list = [norm_source_queries[source]] if source in norm_source_queries else executed_queries
        seen_source_ids_for_source = set()
        any_variant_bounded_partial = False

        for q_variant in query_list:
            cursor = '*'
            seen_pages = set()
            variant_pages_read = 0
            variant_fetched = 0
            variant_total = None
            is_acl_direct = False
            for page in range(1, pages + 1):
                if source == 's2' and (page - 1) * size >= 1000:
                    state['status'] = 'truncated_api_cap'
                    break
                if source == 'huggingface' and page > 1:
                    break
                if is_acl_direct and page > 1:
                    break
                try:
                    params = request_params(
                        source, q_variant, size, page, cursor,
                        raw_arxiv=(source == 'arxiv' and source in norm_source_queries),
                        require_abstract=require_abstract,
                        pages=pages,
                    )
                    if source == 'acl' and isinstance(params, dict) and params.get('_acl_direct_url'):
                        is_acl_direct = True
                    state['executed_query'] = _executed_query_for(source, params)
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
                variant_pages_read += 1
                variant_fetched += len(papers)
                variant_total = total
                state['pages_read'] += 1
                new_papers = [p for p in papers if p['source_id'] not in seen_source_ids_for_source]
                for p in new_papers:
                    seen_source_ids_for_source.add(p['source_id'])
                state['returned'] += len(new_papers)
                if isinstance(total, int):
                    state['reported_total'] = total if state['reported_total'] is None else max(state['reported_total'], total)
                result['records'].extend(new_papers)
                if not papers or (isinstance(total, int) and page * size >= total):
                    break
                if source == 'europepmc':
                    next_cursor = data.get('nextCursorMark')
                    if not next_cursor or next_cursor == cursor:
                        state['status'] = 'missing_or_repeated_cursor'
                        break
                    cursor = next_cursor
            if (
                state['status'] == 'complete'
                and isinstance(variant_total, int)
                and variant_fetched < variant_total
                and (variant_pages_read == pages or source == 'huggingface' or is_acl_direct)
            ):
                any_variant_bounded_partial = True
            if state['status'] != 'complete':
                break

        raw_status = state['status']
        if raw_status == 'complete' and state['pages_read'] and state['returned'] == 0:
            raw_status = 'valid_zero_results'
        elif raw_status == 'complete' and any_variant_bounded_partial:
            raw_status = 'bounded_partial'
        canonical = canonicalize_source_status(raw_status, returned=state['returned'])
        state['status'] = canonical
        state['status_category'] = canonical
        state['raw_status'] = raw_status
        state['detail'] = raw_status
        http_match = re.search(r'(?:^|_)http_(\d{3})$', raw_status)
        if http_match:
            state['http_status'] = int(http_match.group(1))

    doi_groups = {}
    for index, paper in enumerate(result['records']):
        if paper['doi']:
            doi_groups.setdefault(paper['doi'], []).append(index)
    result['doi_duplicate_groups'] = {doi: positions for doi, positions in doi_groups.items() if len(positions) > 1}

    merged_results, dedup_groups = deduplicate_records(result['records'])
    if enrich_scite or enrich_retraction:
        try:
            from fulltext_mining import check_retraction, fetch_scite_tallies
        except ImportError:
            import importlib.util
            _ft_path = Path(__file__).resolve().parent / 'fulltext_mining.py'
            _ft_spec = importlib.util.spec_from_file_location('fulltext_mining', _ft_path)
            _ft_mod = importlib.util.module_from_spec(_ft_spec)
            _ft_spec.loader.exec_module(_ft_mod)
            check_retraction = _ft_mod.check_retraction
            fetch_scite_tallies = _ft_mod.fetch_scite_tallies
        scite_cache: dict[str, dict] = {}
        retraction_cache: dict[str, str] = {}
        by_src_sid: dict[tuple[str | None, str | None], dict] = {}
        for item in merged_results:
            doi = normalize_doi(item.get('doi'))
            if enrich_scite and doi:
                if doi not in scite_cache:
                    scite_cache[doi] = fetch_scite_tallies(doi)
                item['scite_tallies'] = dict(scite_cache[doi])
            if enrich_retraction and doi and item.get('retraction_status') != 'retracted':
                if doi not in retraction_cache:
                    retraction_cache[doi] = check_retraction(doi)['status']
                item['retraction_status'] = retraction_cache[doi]
            for sid_entry in item.get('source_ids') or []:
                by_src_sid[(sid_entry.get('source'), sid_entry.get('source_id'))] = item
        for rec in result['records']:
            merged_item = by_src_sid.get((rec.get('source'), rec.get('source_id')))
            rec_doi = normalize_doi(rec.get('doi'))
            if enrich_scite:
                if rec_doi:
                    if rec_doi not in scite_cache:
                        scite_cache[rec_doi] = fetch_scite_tallies(rec_doi)
                    rec['scite_tallies'] = dict(scite_cache[rec_doi])
                elif merged_item and merged_item.get('scite_tallies'):
                    rec['scite_tallies'] = dict(merged_item['scite_tallies'])
            if enrich_retraction:
                if merged_item and merged_item.get('retraction_status') == 'retracted':
                    rec['retraction_status'] = 'retracted'
                elif rec.get('retraction_status') != 'retracted':
                    if rec_doi:
                        if rec_doi not in retraction_cache:
                            retraction_cache[rec_doi] = check_retraction(rec_doi)['status']
                        rec['retraction_status'] = retraction_cache[rec_doi]
                    elif merged_item and merged_item.get('retraction_status') and merged_item['retraction_status'] != 'unchecked':
                        rec['retraction_status'] = merged_item['retraction_status']

    result['results'] = merged_results
    result['dedup_groups'] = dedup_groups
    result['known_seed_checks'] = check_known_seeds(result['records'], result['sources'], known_dois, norm_known_source_ids)
    result['warning'] = (
        'Discovery records only. A complete status covers only the executed query, not the topic or known relevant works; '
        'test known seeds and reformulate missed queries. DOI and dedup groups are candidate duplicates; resolve versions and study identity manually. '
        'Failures, bot blocks, and bounded pages are unchecked coverage, never evidence of no prior work.'
    )
    return result


def _auto_artifact_path(prefix: str) -> Path:
    art_dir = Path(tempfile.gettempdir()) / 'research_scientist_artifacts'
    art_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f'{prefix}_', suffix='.json', dir=str(art_dir))
    os.close(fd)
    return Path(tmp_name).resolve()


def _preview_text(text: str | None, max_chars: int = 200) -> str | None:
    if not isinstance(text, str):
        return None
    cleaned = re.sub(r'\s+', ' ', text).strip()
    if not cleaned:
        return None
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars - 3].rstrip() + '...'


def compact_search_summary(payload: dict, artifact_path: Path) -> dict:
    top_results = []
    for item in payload.get('results', [])[:10]:
        top_results.append({
            'dedup_key': item.get('dedup_key'),
            'title': item.get('title'),
            'year': item.get('year'),
            'doi': item.get('doi'),
            'arxiv_id': item.get('arxiv_id'),
            'preprint_only': item.get('preprint_only'),
            'retraction_status': item.get('retraction_status'),
            'abstract_preview': _preview_text(item.get('abstract'), 200),
        })
    return {
        'compact': True,
        'schema': payload.get('schema'),
        'artifact_path': str(artifact_path),
        'query': payload.get('query'),
        'mode': payload.get('mode'),
        'source_statuses': {
            src: st.get('status_category') or status_category(st.get('status', ''), returned=st.get('returned', 1))
            for src, st in (payload.get('sources') or {}).items()
        },
        'total_results': len(payload.get('results', [])),
        'dedup_groups_count': len(payload.get('dedup_groups', [])),
        'known_seed_checks': payload.get('known_seed_checks', []),
        'top_results': top_results,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('query')
    parser.add_argument('--source', action='append', help='Source name (repeatable). Defaults to all 9 sources.')
    parser.add_argument('--query-for', action='append', metavar='SOURCE=QUERY',
                        help='Override the query for one source; repeat per source')
    parser.add_argument('--known-doi', action='append', metavar='DOI',
                        help='Check whether an exact known DOI occurs in this run; repeatable')
    parser.add_argument('--known-source-id', action='append', metavar='SOURCE=ID',
                        help='Check an exact source ID (arXiv versions are linked); repeatable')
    parser.add_argument('--size', type=int, default=20)
    parser.add_argument('--pages', type=int, default=1)
    parser.add_argument('--mode', choices=MODES, default='balanced')
    parser.add_argument('--fanout', action='store_true', help='Enable 3-query fan-out (also active in quality mode)')
    parser.add_argument('--fanout-query', action='append', metavar='QUERY', help='Explicit fan-out variant (max 3)')
    parser.add_argument('--require-abstract', action='store_true', help='Require OpenAlex has_abstract:true filter (default False)')
    parser.add_argument('--enrich-scite', action='store_true', help='Fetch Scite tallies for results with DOIs')
    parser.add_argument('--enrich-retraction', action='store_true', help='Check Crossref/OpenAlex retraction status for results with DOIs')
    parser.add_argument('--out', type=Path, help='Optional path to write JSON output')
    parser.add_argument('--compact', action='store_true', help='Write full JSON to --out (or auto-artifact) and print bounded compact summary')
    args = parser.parse_args()
    auto_out_path = None
    try:
        out_path = args.out.expanduser().resolve() if args.out is not None else None
        if out_path is not None and out_path.exists() and out_path.is_dir():
            raise ValueError('output path must not be a directory')
        selected_sources = tuple(normalize_source_name(s) for s in args.source) if args.source else SOURCES
        source_queries = {}
        for item in args.query_for or []:
            if '=' not in item:
                raise ValueError('--query-for needs SOURCE=QUERY')
            source, value = item.split('=', 1)
            norm_src = normalize_source_name(source)
            if norm_src in source_queries:
                raise ValueError('duplicate --query-for source')
            source_queries[norm_src] = value
        known_ids = []
        for item in args.known_source_id or []:
            if '=' not in item:
                raise ValueError('--known-source-id needs SOURCE=ID')
            src, val = item.split('=', 1)
            known_ids.append((normalize_source_name(src), val))
        payload = search(
            args.query,
            selected_sources,
            args.size,
            args.pages,
            source_queries=source_queries,
            known_dois=args.known_doi or (),
            known_source_ids=known_ids,
            mode=args.mode,
            fanout=True if args.fanout else None,
            fanout_queries=args.fanout_query,
            require_abstract=args.require_abstract,
            enrich_scite=args.enrich_scite,
            enrich_retraction=args.enrich_retraction,
        )
        rendered = json.dumps(payload, ensure_ascii=False)
        if out_path is None and args.compact:
            auto_out_path = _auto_artifact_path('search_papers')
            out_path = auto_out_path
        if out_path is not None:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(rendered, encoding='utf-8')
        if args.compact:
            print(json.dumps(compact_search_summary(payload, out_path), ensure_ascii=False, separators=(',', ':')))
        else:
            print(rendered)
    except (ValueError, OSError) as exc:
        if auto_out_path is not None:
            try:
                auto_out_path.unlink(missing_ok=True)
            except OSError:
                pass
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        sys.exit(2)
