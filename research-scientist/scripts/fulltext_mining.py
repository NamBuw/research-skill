#!/usr/bin/env python3
"""Fulltext section mining (Europe PMC JATS XML + PDF slice fallback), Scite tallies, and retraction verification.

Clean-room behavioral implementation of:
- Europe PMC JATS XML <sec> section mining (defusedxml) and PDF heading-slice fallback
- Scite.ai citation tallies endpoint (api.scite.ai/tallies/{doi})
- Crossref + OpenAlex + optional local Retraction Watch CSV retraction verification
  (CSV matching pattern adapted from paper-qa, Apache-2.0)
"""
from __future__ import annotations

import argparse
import csv
import email.utils
import json
import os
import re
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

import defusedxml.ElementTree as DET
from defusedxml.common import DefusedXmlException

EPMC_SEARCH_URL = 'https://www.ebi.ac.uk/europepmc/webservices/rest/search'
EPMC_XML_TEMPLATE = 'https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML'
SCITE_TALLIES_TEMPLATE = 'https://api.scite.ai/tallies/{doi}'
CROSSREF_WORKS_URL = 'https://api.crossref.org/works/{doi}'
OPENALEX_DOI_URL = 'https://api.openalex.org/works/doi:{doi}'

MAX_XML_BYTES = 25_000_000
MAX_JSON_BYTES = 8_000_000
RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}
_HOST_LOCK = threading.Lock()
_HOST_LAST_CALL: dict[str, float] = {}

TARGET_BUCKETS = ('Discussion', 'Limitations', 'Future Work', 'Conclusion')

ADMISSION_RE = re.compile(
    r'\b(limitation|limitations|fails? to|does not (?:scale|generali[sz]e|hold)|'
    r'remains? (?:open|unclear|challenging)|future work|we did not|cannot handle|out of scope|'
    r'threat(?:s)? to validity|caveat|shortcoming)\b',
    re.I,
)

PDF_HEADING_RE = re.compile(
    r'(?im)^[ \t]*(?:\d+(?:\.\d+)*\.?[ \t]+|[IVX]+\.[ \t]+)?'
    r'(general[ \t]+discussion|discussion(?:[ \t]+and[ \t]+(?:limitations|conclusions?|future[ \t]+work))?|'
    r'limitations?(?:[ \t]+and[ \t]+future[ \t]+work)?|threats?[ \t]+to[ \t]+validity|'
    r'future[ \t]+(?:work|directions?|research)|conclusions?(?:[ \t]+and[ \t]+future[ \t]+work)?)'
    r'[ \t]*[:.\-–—]?[ \t]*$'
)

PDF_STOP_RE = re.compile(
    r'(?im)^[ \t]*(?:\d+(?:\.\d+)*\.?[ \t]+|[IVX]+\.[ \t]+)?'
    r'(references|bibliography|acknowledg(?:e)?ments?|appendix|supplementary[ \t]+material|ethics[ \t]+statement)'
    r'[ \t]*[:.\-–—]?[ \t]*$'
)


def normalize_doi(value: str | None) -> str:
    if not isinstance(value, str):
        return ''
    text = value.strip()
    text = re.sub(r'^https?://(?:dx\.)?doi\.org/', '', text, flags=re.I)
    text = re.sub(r'^doi:', '', text, flags=re.I)
    return text.strip().lower()


def _normalize_pmcid(value: str | None) -> str:
    if not isinstance(value, str):
        return ''
    m = re.search(r'(PMC\d+)', value.strip(), re.I)
    return m.group(1).upper() if m else ''


def _parse_retry_after(value, now=None):
    if not value:
        return None
    text = str(value).strip()
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


def _throttle_host(host: str, min_interval: float = 0.25, sleep_fn=time.sleep):
    if not host or min_interval <= 0:
        return
    with _HOST_LOCK:
        now = time.monotonic()
        last = _HOST_LAST_CALL.get(host)
        wait = (last + min_interval - now) if last is not None else 0.0
        if wait > 0:
            sleep_fn(wait)
        _HOST_LAST_CALL[host] = time.monotonic()


def _http_fetch(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    expect_json: bool = True,
    max_bytes: int = MAX_JSON_BYTES,
    timeout: int = 20,
    min_interval: float = 0.25,
    max_retries: int = 3,
    sleep_fn=time.sleep,
):
    req_headers = {'User-Agent': 'ResearchScientistSkill/2.6 (fulltext-mining)'}
    email_addr = os.environ.get('CONTACT_EMAIL', '').strip()
    if email_addr:
        req_headers['User-Agent'] = f'ResearchScientistSkill/2.6 (fulltext-mining; mailto:{email_addr})'
    if headers:
        req_headers.update(headers)
    host = (urlparse(url).hostname or '').lower()
    for attempt in range(max_retries + 1):
        _throttle_host(host, min_interval=min_interval, sleep_fn=sleep_fn)
        try:
            with urlopen(Request(url, headers=req_headers), timeout=timeout) as resp:
                body = resp.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise RuntimeError('oversized')
            if expect_json:
                try:
                    return json.loads(body)
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise RuntimeError('invalid_json') from exc
            return body.decode('utf-8', errors='replace')
        except HTTPError as exc:
            if exc.code in RETRYABLE_HTTP_CODES and attempt < max_retries:
                ra = _parse_retry_after(exc.headers.get('Retry-After') if exc.headers else None)
                sleep_fn(ra if ra is not None else min(30.0, 1.0 * (2 ** attempt)))
                continue
            if exc.code == 429:
                raise RuntimeError('rate_limited') from exc
            if exc.code == 404:
                raise RuntimeError('not_found') from exc
            raise RuntimeError(f'http_{exc.code}') from exc
        except (URLError, TimeoutError, OSError) as exc:
            if attempt < max_retries:
                sleep_fn(min(30.0, 1.0 * (2 ** attempt)))
                continue
            raise RuntimeError('network_failure') from exc
    raise RuntimeError('network_failure')


def _classify_section(sec_type: str, title: str) -> str | None:
    st = (sec_type or '').strip().lower()
    tl = (title or '').strip().lower()
    if any(k in tl for k in ('limitation', 'threat to validity', 'threats to validity', 'caveat', 'shortcoming')) or 'limitation' in st:
        return 'Limitations'
    if any(k in tl for k in ('future work', 'future direction', 'future research', 'open problem', 'open question')) or 'future' in st:
        return 'Future Work'
    if 'conclusion' in tl or st in {'conclusions', 'conclusion'}:
        return 'Conclusion'
    if 'discussion' in tl or st in {'discussion', 'disc'}:
        return 'Discussion'
    return None


def _local_tag(tag: str) -> str:
    return tag.rsplit('}', 1)[-1] if '}' in tag else tag


def _extract_node_text_excluding_children(elem: ET.Element, excluded_secs: set[int]) -> str:
    parts = []
    if elem.text and elem.text.strip():
        parts.append(elem.text.strip())
    for child in elem:
        tag = _local_tag(child.tag)
        if tag == 'sec' and id(child) in excluded_secs:
            if child.tail and child.tail.strip():
                parts.append(child.tail.strip())
            continue
        if tag == 'title':
            if child.tail and child.tail.strip():
                parts.append(child.tail.strip())
            continue
        inner = _extract_node_text_excluding_children(child, excluded_secs)
        if inner:
            parts.append(inner)
        if child.tail and child.tail.strip():
            parts.append(child.tail.strip())
    return re.sub(r'\s+', ' ', ' '.join(parts)).strip()


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    head = max_chars // 2
    tail = max_chars - head - 24
    return text[:head].rstrip() + '\n...[truncated]...\n' + text[-max(tail, 0):].lstrip()


def _extract_admissions(texts: list[str]) -> list[str]:
    hits = []
    seen = set()
    for block in texts:
        for sent in re.split(r'(?<=[.!?])\s+', block):
            s = sent.strip()
            if len(s) >= 20 and ADMISSION_RE.search(s) and s not in seen:
                seen.add(s)
                hits.append(s)
                if len(hits) >= 25:
                    return hits
    return hits


def extract_jats_sections(xml_text: str, max_chars: int = 7000) -> dict:
    sections = {k: [] for k in TARGET_BUCKETS}
    section_titles = []
    try:
        root = DET.fromstring(xml_text)
    except (DefusedXmlException, ET.ParseError, ValueError):
        return {
            'status': 'xml_parse_error',
            'sections': sections,
            'section_titles': section_titles,
            'admission_sentences': [],
        }

    body = None
    for elem in root.iter():
        if _local_tag(elem.tag) == 'body':
            body = elem
            break
    if body is None:
        return {
            'status': 'no_body',
            'sections': sections,
            'section_titles': section_titles,
            'admission_sentences': [],
        }

    # Walk <sec> elements; track child sections claimed by a more specific target bucket
    def _walk_sec(sec_elem: ET.Element, parent_bucket: str | None) -> set[int]:
        sec_type = sec_elem.attrib.get('sec-type', '')
        title_el = next((c for c in sec_elem if _local_tag(c.tag) == 'title'), None)
        title_text = ''.join(title_el.itertext()).strip() if title_el is not None else ''
        if title_text:
            section_titles.append(title_text)
        bucket = _classify_section(sec_type, title_text)

        child_secs = [c for c in sec_elem if _local_tag(c.tag) == 'sec']
        claimed_by_subbucket: set[int] = set()

        effective_bucket = bucket or parent_bucket
        for child in child_secs:
            claimed_by_subbucket |= _walk_sec(child, effective_bucket)

        # Collect if this node introduces a bucket (either no parent bucket, or a distinct more specific bucket)
        should_collect = bucket is not None and (parent_bucket is None or bucket != parent_bucket)
        if should_collect:
            txt = _extract_node_text_excluding_children(sec_elem, claimed_by_subbucket)
            if txt:
                sections[bucket].append(_truncate_text(txt, max_chars))
            claimed_by_subbucket.add(id(sec_elem))
        return claimed_by_subbucket

    for top_sec in body:
        if _local_tag(top_sec.tag) == 'sec':
            _walk_sec(top_sec, None)

    all_texts = [t for vals in sections.values() for t in vals]
    status = 'ok' if all_texts else 'no_target_sections'
    return {
        'status': status,
        'sections': sections,
        'section_titles': section_titles,
        'admission_sentences': _extract_admissions(all_texts),
    }


def extract_pdf_sections(pdf_path_or_bytes, max_pages: int = 60, max_chars: int = 7000) -> dict:
    sections = {k: [] for k in TARGET_BUCKETS}
    pages_text = []
    try:
        try:
            import fitz
            if isinstance(pdf_path_or_bytes, (bytes, bytearray)):
                doc = fitz.open(stream=bytes(pdf_path_or_bytes), filetype='pdf')
            else:
                doc = fitz.open(str(pdf_path_or_bytes))
            with doc:
                if doc.needs_pass:
                    return {'status': 'pdf_parse_error', 'sections': sections, 'admission_sentences': [], 'pages_scanned': 0}
                for i in range(min(len(doc), max_pages)):
                    pages_text.append(doc[i].get_text('text') or '')
        except ImportError:
            import pypdf
            import io
            stream = io.BytesIO(pdf_path_or_bytes) if isinstance(pdf_path_or_bytes, (bytes, bytearray)) else open(pdf_path_or_bytes, 'rb')
            with stream:
                reader = pypdf.PdfReader(stream)
                for i in range(min(len(reader.pages), max_pages)):
                    pages_text.append(reader.pages[i].extract_text() or '')
    except Exception:
        return {'status': 'pdf_parse_error', 'sections': sections, 'admission_sentences': [], 'pages_scanned': 0}

    full_text = '\n'.join(pages_text)[:400_000]
    if len(full_text.strip()) < 40:
        return {'status': 'insufficient_text', 'sections': sections, 'admission_sentences': [], 'pages_scanned': len(pages_text)}

    start_offset = int(len(full_text) * 0.2) if len(full_text) >= 1000 else 0
    matches = list(PDF_HEADING_RE.finditer(full_text, pos=start_offset))
    if not matches and start_offset > 0:
        matches = list(PDF_HEADING_RE.finditer(full_text, pos=0))

    if not matches:
        admissions = _extract_admissions([full_text])
        return {
            'status': 'no_target_sections',
            'sections': sections,
            'admission_sentences': admissions,
            'pages_scanned': len(pages_text),
        }

    stop_matches = [m.start() for m in PDF_STOP_RE.finditer(full_text)]
    for idx, match in enumerate(matches):
        heading = match.group(1)
        bucket = _classify_section('', heading)
        if not bucket:
            continue
        body_start = match.end()
        candidates_end = [len(full_text)]
        if idx + 1 < len(matches):
            candidates_end.append(matches[idx + 1].start())
        for stop_pos in stop_matches:
            if stop_pos > body_start:
                candidates_end.append(stop_pos)
                break
        body_end = min(candidates_end)
        snippet = re.sub(r'\s+', ' ', full_text[body_start:body_end]).strip()
        if snippet:
            sections[bucket].append(_truncate_text(snippet, max_chars))

    all_texts = [t for vals in sections.values() for t in vals]
    admissions = _extract_admissions(all_texts if all_texts else [full_text])
    return {
        'status': 'ok' if all_texts else 'no_target_sections',
        'sections': sections,
        'admission_sentences': admissions,
        'pages_scanned': len(pages_text),
    }


def fetch_epmc_jats(pmcid: str | None = None, doi: str | None = None, transport=None) -> tuple[str | None, str | None, str]:
    norm_pmcid = _normalize_pmcid(pmcid)
    norm_doi = normalize_doi(doi)

    def _call(url: str, expect_json: bool):
        if transport is not None:
            return transport(url, expect_json=expect_json)
        return _http_fetch(url, expect_json=expect_json, max_bytes=MAX_XML_BYTES)

    if not norm_pmcid:
        if not norm_doi:
            return None, None, 'no_pmcid'
        search_url = EPMC_SEARCH_URL + '?' + urlencode({
            'query': f'DOI:"{norm_doi}" AND OPEN_ACCESS:y',
            'format': 'json',
            'pageSize': 1,
        })
        try:
            data = _call(search_url, True)
        except RuntimeError as exc:
            return None, None, str(exc)
        results = ((data.get('resultList') or {}).get('result')) if isinstance(data, dict) else None
        if not isinstance(results, list) or not results:
            return None, None, 'no_pmcid'
        norm_pmcid = _normalize_pmcid(results[0].get('pmcid'))
        if not norm_pmcid:
            return None, None, 'no_pmcid'

    xml_url = EPMC_XML_TEMPLATE.format(pmcid=norm_pmcid)
    try:
        xml_text = _call(xml_url, False)
    except RuntimeError as exc:
        return norm_pmcid, None, str(exc)
    if not isinstance(xml_text, str) or not xml_text.strip():
        return norm_pmcid, None, 'not_found'
    return norm_pmcid, xml_text, 'ok'


def fetch_scite_tallies(doi: str | None, transport=None) -> dict:
    empty = {
        'supporting': None,
        'mentioning': None,
        'contradicting': None,
        'unclassified': None,
        'total': None,
        'citing_publications': None,
        'status': 'no_doi',
    }
    norm_doi = normalize_doi(doi)
    if not norm_doi:
        return empty
    url = SCITE_TALLIES_TEMPLATE.format(doi=quote(norm_doi, safe=''))
    headers = {'Accept': 'application/json'}
    api_key = os.environ.get('SCITE_API_KEY', '').strip()
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    try:
        if transport is not None:
            data = transport(url, headers=headers)
        else:
            data = _http_fetch(url, headers=headers, expect_json=True)
    except RuntimeError as exc:
        return {**empty, 'status': str(exc)}
    if not isinstance(data, dict):
        return {**empty, 'status': 'invalid_json'}
    return {
        'supporting': data.get('supporting'),
        'mentioning': data.get('mentioning'),
        'contradicting': data.get('contradicting'),
        'unclassified': data.get('unclassified'),
        'total': data.get('total'),
        'citing_publications': data.get('citingPublications'),
        'status': 'ok',
    }


def load_retraction_csv(csv_path: str | Path) -> set[str]:
    """Load retracted DOIs from a Retraction Watch CSV (paper-qa Apache-2.0 pattern)."""
    retracted: set[str] = set()
    path = Path(csv_path).expanduser().resolve()
    with path.open('r', encoding='utf-8', errors='replace', newline='') as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            nature = (row.get('RetractionNature') or '').strip().lower()
            if nature != 'retraction':
                continue
            for col in ('OriginalPaperDOI', 'RetractionDOI'):
                d = normalize_doi(row.get(col))
                if d:
                    retracted.add(d)
    return retracted


def _has_crossref_retraction(msg: dict) -> tuple[bool, list[dict]]:
    evidence = []
    if str(msg.get('type') or '').strip().lower() == 'retraction':
        evidence.append({'source': 'crossref', 'field': 'type', 'detail': 'retraction'})
    for field in ('updated-by', 'update-to'):
        updates = msg.get(field)
        if isinstance(updates, list):
            for upd in updates:
                if isinstance(upd, dict):
                    utype = str(upd.get('type') or '').strip().lower()
                    ulabel = str(upd.get('label') or '').strip().lower()
                    if 'retract' in utype or 'withdraw' in utype or 'retract' in ulabel:
                        evidence.append({'source': 'crossref', 'field': field, 'detail': upd})
    rel = msg.get('relation')
    if isinstance(rel, dict):
        for key in ('is-retracted-by', 'is-retraction-of'):
            if rel.get(key):
                evidence.append({'source': 'crossref', 'field': f'relation.{key}', 'detail': rel.get(key)})
    return bool(evidence), evidence


def check_retraction(
    doi: str | None,
    cr_transport=None,
    oa_transport=None,
    retraction_csv_set: set[str] | None = None,
) -> dict:
    """Verify retraction status across optional CSV, Crossref, and OpenAlex.

    Strict invariant: NEVER returns 'clean' when lookups fail with 429/5xx/network/parse errors
    or when DOI is missing.
    """
    norm_doi = normalize_doi(doi)
    if not norm_doi:
        return {
            'status': 'unchecked',
            'evidence': [],
            'sources_checked': {'csv': 'skipped', 'crossref': 'no_doi', 'openalex': 'no_doi'},
        }

    evidence: list[dict] = []
    sources_checked = {'csv': 'skipped', 'crossref': 'skipped', 'openalex': 'skipped'}

    if retraction_csv_set is not None:
        sources_checked['csv'] = 'checked'
        if norm_doi in retraction_csv_set:
            evidence.append({'source': 'retraction_watch_csv', 'doi': norm_doi})
            return {'status': 'retracted', 'evidence': evidence, 'sources_checked': sources_checked}

    run_cr = cr_transport is not None or oa_transport is None
    run_oa = oa_transport is not None or cr_transport is None

    cr_status = 'skipped'
    if run_cr:
        cr_url = CROSSREF_WORKS_URL.format(doi=quote(norm_doi, safe=''))
        try:
            cr_data = cr_transport(cr_url) if cr_transport is not None else _http_fetch(cr_url, expect_json=True)
            msg = cr_data.get('message') if isinstance(cr_data, dict) else None
            if not isinstance(msg, dict):
                cr_status = 'invalid_json'
            else:
                cr_status = 'ok'
                is_ret, cr_ev = _has_crossref_retraction(msg)
                if is_ret:
                    evidence.extend(cr_ev)
        except RuntimeError as exc:
            cr_status = str(exc)
        sources_checked['crossref'] = cr_status

    oa_status = 'skipped'
    oa_is_retracted: bool | None = None
    if run_oa:
        oa_url = OPENALEX_DOI_URL.format(doi=quote(norm_doi, safe='')) + '?select=id,doi,is_retracted,title'
        headers = {}
        if os.environ.get('OPENALEX_API_KEY'):
            headers['Authorization'] = 'Bearer ' + os.environ['OPENALEX_API_KEY']
        try:
            oa_data = oa_transport(oa_url) if oa_transport is not None else _http_fetch(oa_url, headers=headers, expect_json=True)
            if not isinstance(oa_data, dict) or not isinstance(oa_data.get('id'), str):
                oa_status = 'invalid_json'
            else:
                oa_status = 'ok'
                raw_ret = oa_data.get('is_retracted')
                if isinstance(raw_ret, bool):
                    oa_is_retracted = raw_ret
                if oa_is_retracted is True:
                    evidence.append({'source': 'openalex', 'field': 'is_retracted', 'detail': True})
        except RuntimeError as exc:
            oa_status = str(exc)
        sources_checked['openalex'] = oa_status

    if evidence:
        return {'status': 'retracted', 'evidence': evidence, 'sources_checked': sources_checked}

    # Strict clean rules:
    # 1) Crossref returned 200 valid work JSON without retraction AND OpenAlex did not error (ok/not_found/skipped)
    # 2) Crossref returned 404 (not_found, e.g. DataCite/arXiv DOI) AND OpenAlex returned 200 valid JSON with is_retracted is False
    cr_clean = (cr_status == 'ok' and oa_status in ('ok', 'not_found', 'skipped'))
    oa_clean = (cr_status in ('not_found', 'skipped') and oa_status == 'ok' and oa_is_retracted is False)
    if cr_clean or oa_clean:
        return {'status': 'clean', 'evidence': [], 'sources_checked': sources_checked}

    return {'status': 'unchecked', 'evidence': [], 'sources_checked': sources_checked}


def mine_corpus(
    dois: list[str] = (),
    pmcids: list[str] = (),
    pdfs: list[str] = (),
    *,
    retraction_csv_set: set[str] | None = None,
    skip_scite: bool = False,
    skip_retraction: bool = False,
    skip_fulltext: bool = False,
    max_section_chars: int = 7000,
    epmc_transport=None,
    scite_transport=None,
    cr_transport=None,
    oa_transport=None,
) -> dict:
    items = []

    for raw_doi in dois:
        norm_doi = normalize_doi(raw_doi)
        if not norm_doi:
            continue
        sections = {k: [] for k in TARGET_BUCKETS}
        admissions = []
        ft_status = 'skipped'
        pmcid = None
        if not skip_fulltext:
            pmcid, xml_text, fetch_status = fetch_epmc_jats(doi=norm_doi, transport=epmc_transport)
            if fetch_status == 'ok' and xml_text:
                parsed = extract_jats_sections(xml_text, max_chars=max_section_chars)
                ft_status = parsed['status']
                sections = parsed['sections']
                admissions = parsed['admission_sentences']
            else:
                ft_status = fetch_status
        scite = fetch_scite_tallies(norm_doi, transport=scite_transport) if not skip_scite else {
            'supporting': None, 'mentioning': None, 'contradicting': None,
            'unclassified': None, 'total': None, 'citing_publications': None, 'status': 'skipped'
        }
        ret = check_retraction(
            norm_doi, cr_transport=cr_transport, oa_transport=oa_transport, retraction_csv_set=retraction_csv_set
        ) if not skip_retraction else {'status': 'unchecked', 'evidence': [], 'sources_checked': {}}
        items.append({
            'identifier': norm_doi,
            'doi': norm_doi,
            'pmcid': pmcid,
            'extraction_source': 'epmc_jats' if ft_status == 'ok' else 'none',
            'fulltext_status': ft_status,
            'sections': sections,
            'admission_sentences': admissions,
            'scite_tallies': scite,
            'retraction_status': ret['status'],
            'retraction_evidence': ret['evidence'],
            'retraction_sources_checked': ret['sources_checked'],
        })

    for raw_pmcid in pmcids:
        norm_pmcid = _normalize_pmcid(raw_pmcid)
        if not norm_pmcid:
            continue
        sections = {k: [] for k in TARGET_BUCKETS}
        admissions = []
        ft_status = 'skipped'
        if not skip_fulltext:
            _, xml_text, fetch_status = fetch_epmc_jats(pmcid=norm_pmcid, transport=epmc_transport)
            if fetch_status == 'ok' and xml_text:
                parsed = extract_jats_sections(xml_text, max_chars=max_section_chars)
                ft_status = parsed['status']
                sections = parsed['sections']
                admissions = parsed['admission_sentences']
            else:
                ft_status = fetch_status
        items.append({
            'identifier': norm_pmcid,
            'doi': None,
            'pmcid': norm_pmcid,
            'extraction_source': 'epmc_jats' if ft_status == 'ok' else 'none',
            'fulltext_status': ft_status,
            'sections': sections,
            'admission_sentences': admissions,
            'scite_tallies': {'supporting': None, 'mentioning': None, 'contradicting': None,
                              'unclassified': None, 'total': None, 'citing_publications': None, 'status': 'no_doi'},
            'retraction_status': 'unchecked',
            'retraction_evidence': [],
            'retraction_sources_checked': {'csv': 'skipped', 'crossref': 'no_doi', 'openalex': 'no_doi'},
        })

    for raw_pdf in pdfs:
        pdf_path = Path(raw_pdf).expanduser().resolve()
        parsed = extract_pdf_sections(pdf_path, max_chars=max_section_chars) if not skip_fulltext else {
            'status': 'skipped', 'sections': {k: [] for k in TARGET_BUCKETS}, 'admission_sentences': []
        }
        items.append({
            'identifier': str(pdf_path),
            'doi': None,
            'pmcid': None,
            'extraction_source': 'pdf_slice' if parsed['status'] == 'ok' else 'none',
            'fulltext_status': parsed['status'],
            'sections': parsed['sections'],
            'admission_sentences': parsed['admission_sentences'],
            'scite_tallies': {'supporting': None, 'mentioning': None, 'contradicting': None,
                              'unclassified': None, 'total': None, 'citing_publications': None, 'status': 'no_doi'},
            'retraction_status': 'unchecked',
            'retraction_evidence': [],
            'retraction_sources_checked': {'csv': 'skipped', 'crossref': 'no_doi', 'openalex': 'no_doi'},
        })

    summary = {
        'total': len(items),
        'extracted': sum(1 for it in items if it['fulltext_status'] == 'ok'),
        'retracted': sum(1 for it in items if it['retraction_status'] == 'retracted'),
        'clean': sum(1 for it in items if it['retraction_status'] == 'clean'),
        'unchecked': sum(1 for it in items if it['retraction_status'] == 'unchecked'),
        'scite_ok': sum(1 for it in items if it['scite_tallies'].get('status') == 'ok'),
    }
    return {
        'schema': 'research_scientist_fulltext_mining_v1',
        'checked_at_utc': datetime.now(timezone.utc).isoformat(),
        'items': items,
        'summary': summary,
        'warning': (
            'Extracted sections and Scite tallies are discovery/triage aids. '
            'Unchecked retraction status never certifies a paper as clean; inspect original full text before citing.'
        ),
    }


def _auto_artifact_path(prefix: str) -> Path:
    art_dir = Path(tempfile.gettempdir()) / 'research_scientist_artifacts'
    art_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f'{prefix}_', suffix='.json', dir=str(art_dir))
    os.close(fd)
    return Path(tmp_name).resolve()


def compact_mining_summary(report: dict, artifact_path: Path) -> dict:
    compact_items = []
    for it in report.get('items', []):
        secs = it.get('sections') or {}
        section_char_counts = {
            k: sum(len(s) for s in (v or []))
            for k, v in secs.items()
        }
        compact_items.append({
            'identifier': it.get('identifier'),
            'doi': it.get('doi'),
            'pmcid': it.get('pmcid'),
            'fulltext_status': it.get('fulltext_status'),
            'retraction_status': it.get('retraction_status'),
            'scite_tallies': it.get('scite_tallies'),
            'section_char_counts': section_char_counts,
            'admission_sentence_count': len(it.get('admission_sentences') or []),
        })
    return {
        'compact': True,
        'schema': report.get('schema'),
        'artifact_path': str(artifact_path),
        'summary': report.get('summary'),
        'items': compact_items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dois', nargs='+', default=[])
    parser.add_argument('--pmcids', nargs='+', default=[])
    parser.add_argument('--pdfs', nargs='+', default=[])
    parser.add_argument('--out', type=Path)
    parser.add_argument('--retraction-csv', type=Path)
    parser.add_argument('--skip-scite', action='store_true')
    parser.add_argument('--skip-retraction', action='store_true')
    parser.add_argument('--skip-fulltext', action='store_true')
    parser.add_argument('--max-section-chars', type=int, default=7000)
    parser.add_argument('--compact', action='store_true', help='Write full sections JSON to --out (or auto-artifact) and print bounded compact summary')
    args = parser.parse_args()
    if not (args.dois or args.pmcids or args.pdfs):
        print(json.dumps({'error': 'at least one of --dois, --pmcids, or --pdfs is required'}), file=sys.stderr)
        return 2
    try:
        csv_set = load_retraction_csv(args.retraction_csv) if args.retraction_csv else None
        report = mine_corpus(
            dois=args.dois,
            pmcids=args.pmcids,
            pdfs=args.pdfs,
            retraction_csv_set=csv_set,
            skip_scite=args.skip_scite,
            skip_retraction=args.skip_retraction,
            skip_fulltext=args.skip_fulltext,
            max_section_chars=args.max_section_chars,
        )
        rendered = json.dumps(report, ensure_ascii=False)
        out_path = args.out.expanduser().resolve() if args.out is not None else (_auto_artifact_path('fulltext_mining') if args.compact else None)
        if out_path is not None:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(rendered, encoding='utf-8')
        if args.compact:
            print(json.dumps(compact_mining_summary(report, out_path), ensure_ascii=False, separators=(',', ':')))
        else:
            print(rendered)
        return 0
    except (ValueError, OSError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
