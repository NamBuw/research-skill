#!/usr/bin/env python3
"""Resolve OpenAlex open-access PDF leads and optionally download one safely.

Metadata and an OA flag are leads, not proof of full-text availability, version
equivalence, correct extraction, or permission for uses beyond reading.
"""
from __future__ import annotations

import argparse
import email.utils
import hashlib
import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

API = 'https://api.openalex.org/works/'
MAX_METADATA_BYTES = 5_000_000
MAX_PDF_BYTES = 30_000_000
RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}
_HOST_LOCK = threading.Lock()
_HOST_LAST_CALL: dict[str, float] = {}


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


def _throttle_host(host, min_interval=0.25, sleep_fn=time.sleep):
    if not host or min_interval <= 0:
        return
    with _HOST_LOCK:
        now = time.monotonic()
        last = _HOST_LAST_CALL.get(host)
        wait = (last + min_interval - now) if last is not None else 0.0
        if wait > 0:
            sleep_fn(wait)
        _HOST_LAST_CALL[host] = time.monotonic()


def _normalize_pmcid(value):
    if not isinstance(value, str):
        return None
    match = re.search(r'(PMC\d+)', value.strip(), re.I)
    return match.group(1).upper() if match else None


def _https_url(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = urlparse(value)
        return parsed.scheme == 'https' and bool(parsed.hostname) and not parsed.username and not parsed.password
    except ValueError:
        return False


def normalize_identifier(identifier):
    if not isinstance(identifier, str) or not identifier.strip():
        raise ValueError('identifier must be a DOI or OpenAlex work ID')
    value = identifier.strip()
    if re.fullmatch(r'(?:https://openalex\.org/)?W\d+', value, re.I):
        return 'https://openalex.org/' + value.rsplit('/', 1)[-1].upper()
    value = re.sub(r'^https?://(?:dx\.)?doi\.org/', '', value, flags=re.I)
    value = re.sub(r'^doi:', '', value, flags=re.I)
    if not re.fullmatch(r'10\.\d{4,9}/\S+', value, re.I):
        raise ValueError('identifier must be a DOI or OpenAlex work ID')
    return 'https://doi.org/' + value.lower()


def fetch_work(identifier, timeout=20, max_retries=3, sleep_fn=time.sleep):
    normalized = normalize_identifier(identifier)
    url = API + quote(normalized, safe=':/')
    email_addr = os.environ.get('CONTACT_EMAIL', '').strip()
    ua = 'ResearchScientistSkill/2.6 (oa-resolution)'
    if email_addr:
        ua = f'ResearchScientistSkill/2.6 (oa-resolution; mailto:{email_addr})'
    headers = {'Accept': 'application/json', 'User-Agent': ua}
    if os.environ.get('OPENALEX_API_KEY'):
        headers['Authorization'] = 'Bearer ' + os.environ['OPENALEX_API_KEY']
    host = (urlparse(url).hostname or '').lower()
    for attempt in range(max_retries + 1):
        _throttle_host(host, min_interval=0.25, sleep_fn=sleep_fn)
        try:
            with urlopen(Request(url, headers=headers), timeout=timeout) as response:
                body = response.read(MAX_METADATA_BYTES + 1)
            if len(body) > MAX_METADATA_BYTES:
                raise RuntimeError('metadata_response_too_large')
            result = json.loads(body)
            if not isinstance(result, dict) or not isinstance(result.get('id'), str):
                raise RuntimeError('invalid_work_response')
            return result
        except HTTPError as exc:
            if exc.code in RETRYABLE_HTTP_CODES and attempt < max_retries:
                ra = _parse_retry_after(exc.headers.get('Retry-After') if exc.headers else None)
                sleep_fn(ra if ra is not None else min(30.0, 1.0 * (2 ** attempt)))
                continue
            raise RuntimeError(f'http_{exc.code}') from exc
        except (URLError, TimeoutError, OSError) as exc:
            if attempt < max_retries:
                sleep_fn(min(30.0, 1.0 * (2 ** attempt)))
                continue
            raise RuntimeError('network_failure') from exc
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError('invalid_json') from exc
    raise RuntimeError('network_failure')


def resolve(identifier, transport=fetch_work):
    normalized = normalize_identifier(identifier)
    result = {'requested_identifier': identifier, 'normalized_identifier': normalized,
              'checked_at_utc': datetime.now(timezone.utc).isoformat(),
              'status': 'unchecked', 'work': None, 'oa_pdf_candidates': [],
              'jats_xml_url': None,
              'warning': ('OpenAlex OA locations are metadata leads. Check the returned version, licensing and actual '
                          'PDF body; a missing OA PDF does not mean the paper is unavailable or irrelevant.')}
    try:
        work = transport(normalized)
        if not isinstance(work, dict) or not isinstance(work.get('id'), str):
            raise RuntimeError('invalid_work_response')
        oa_status = work.get('open_access')
        ids_obj = work.get('ids') if isinstance(work.get('ids'), dict) else {}
        pmcid = _normalize_pmcid(ids_obj.get('pmcid'))
        is_retracted = work.get('is_retracted') if isinstance(work.get('is_retracted'), bool) else None
        result['work'] = {'openalex_id': work['id'], 'doi': work.get('doi'), 'title': work.get('title'),
                          'publication_year': work.get('publication_year'),
                          'open_access_status': oa_status.get('oa_status') if isinstance(oa_status, dict) else None,
                          'pmcid': pmcid,
                          'is_retracted': is_retracted}
        if pmcid:
            result['jats_xml_url'] = f'https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML'
        work_id = work['id']
        if not re.fullmatch(r'https://openalex\.org/W\d+', work_id, re.I):
            result['status'] = 'invalid_work_identity'
            return result
        if normalized.startswith('https://openalex.org/'):
            identity_matches = work_id.lower() == normalized.lower()
        else:
            try:
                identity_matches = normalize_identifier(work.get('doi')) == normalized
            except ValueError:
                identity_matches = False
        if not identity_matches:
            result['status'] = 'identity_mismatch_or_missing'
            return result
        locations = [work.get('best_oa_location'), work.get('primary_location')]
        locations.extend(work.get('locations') or [])
        seen = set()
        for location in locations:
            if not isinstance(location, dict) or location.get('is_oa') is not True:
                continue
            pdf_url = location.get('pdf_url')
            if not isinstance(pdf_url, str) or not pdf_url or pdf_url in seen:
                continue
            seen.add(pdf_url)
            source = location.get('source') or {}
            result['oa_pdf_candidates'].append({
                'pdf_url': pdf_url, 'downloadable_https': _https_url(pdf_url),
                'landing_page_url': location.get('landing_page_url'),
                'location_id': location.get('id'), 'version': location.get('version'),
                'license': location.get('license'), 'is_accepted': location.get('is_accepted'),
                'is_published': location.get('is_published'),
                'source_name': source.get('display_name') if isinstance(source, dict) else None})
        result['status'] = 'oa_pdf_leads_found' if result['oa_pdf_candidates'] else 'no_oa_pdf_reported'
    except RuntimeError as exc:
        result['status'] = str(exc)
    return result


def download_pdf(candidate, destination, transport=None):
    if not isinstance(candidate, dict) or candidate.get('downloadable_https') is not True:
        raise ValueError('candidate has no approved HTTPS OA PDF lead')
    url = candidate.get('pdf_url')
    if not _https_url(url):
        raise ValueError('PDF URL must be HTTPS without embedded credentials')
    destination = Path(destination)
    if destination.exists():
        raise ValueError('destination already exists; choose a new path')
    if transport is None:
        def transport(pdf_url, max_retries=3, sleep_fn=time.sleep):
            request = Request(pdf_url, headers={'Accept': 'application/pdf',
                                                'User-Agent': 'ResearchScientistSkill/2.6 (oa-pdf-download)'})
            host = (urlparse(pdf_url).hostname or '').lower()
            for attempt in range(max_retries + 1):
                _throttle_host(host, min_interval=0.25, sleep_fn=sleep_fn)
                try:
                    with urlopen(request, timeout=30) as response:
                        final_url = response.geturl()
                        body = response.read(MAX_PDF_BYTES + 1)
                        content_type = response.headers.get('Content-Type', '')
                        status = response.status
                    return {'final_url': final_url, 'body': body, 'content_type': content_type, 'http_status': status}
                except HTTPError as exc:
                    if exc.code in RETRYABLE_HTTP_CODES and attempt < max_retries:
                        ra = _parse_retry_after(exc.headers.get('Retry-After') if exc.headers else None)
                        sleep_fn(ra if ra is not None else min(30.0, 1.0 * (2 ** attempt)))
                        continue
                    raise RuntimeError(f'http_{exc.code}') from exc
                except (URLError, TimeoutError, OSError) as exc:
                    if attempt < max_retries:
                        sleep_fn(min(30.0, 1.0 * (2 ** attempt)))
                        continue
                    raise RuntimeError('network_failure') from exc
            raise RuntimeError('network_failure')
    response = transport(url)
    body = response.get('body')
    if response.get('http_status') != 200:
        raise RuntimeError(f"http_{response.get('http_status')}")
    if not _https_url(response.get('final_url')):
        raise RuntimeError('pdf_redirected_to_non_https_url')
    if not isinstance(body, bytes) or len(body) > MAX_PDF_BYTES:
        raise RuntimeError('invalid_or_oversized_pdf_response')
    if not body.startswith(b'%PDF-'):
        raise RuntimeError('response_is_not_pdf')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('xb') as stream:
        stream.write(body)
    return {'path': str(destination.resolve()), 'requested_pdf_url': url,
            'final_pdf_url': response['final_url'], 'content_type': response.get('content_type'),
            'downloaded_at_utc': datetime.now(timezone.utc).isoformat(),
            'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body),
            'version_as_reported': candidate.get('version'), 'license_as_reported': candidate.get('license'),
            'warning': 'Check PDF title, DOI, version, pages and original layout before citing or comparing methods.'}


def download_candidates(candidates, destination, downloader=download_pdf):
    eligible = [candidate for candidate in candidates if candidate.get('downloadable_https') is True]
    if not eligible:
        return {'download': {'status': 'no_https_oa_pdf_candidate'}, 'download_attempts_failed': []}
    attempts = []
    for candidate in eligible:
        try:
            receipt = downloader(candidate, destination)
            return {'download': {'status': 'downloaded', **receipt}, 'download_attempts_failed': attempts}
        except (ValueError, RuntimeError, OSError) as exc:
            attempts.append({'pdf_url': candidate.get('pdf_url'), 'error': str(exc)})
    return {'download': {'status': 'download_failed'}, 'download_attempts_failed': attempts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('identifier', help='DOI or OpenAlex W ID')
    parser.add_argument('--download-dir', help='Download the first HTTPS OA PDF candidate into this directory')
    args = parser.parse_args()
    try:
        output = resolve(args.identifier)
        if args.download_dir and output['status'] == 'oa_pdf_leads_found':
            work_id = output['work']['openalex_id'].rsplit('/', 1)[-1]
            output.update(download_candidates(output['oa_pdf_candidates'], Path(args.download_dir) / f'{work_id}.pdf'))
        print(json.dumps(output, ensure_ascii=False))
    except (ValueError, OSError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
