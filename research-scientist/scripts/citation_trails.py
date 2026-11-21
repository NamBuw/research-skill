#!/usr/bin/env python3
"""Bounded OpenAlex backward/forward citation expansion for one work ID."""
from __future__ import annotations

import argparse
import email.utils
import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

BASE = 'https://api.openalex.org/works'
ID_PATTERN = re.compile(r'^W[0-9]+$')
WID_EXTRACT_RE = re.compile(r'(?:^|/)(W[0-9]+)(?:[/?#]|$)', re.I)

_HOST_LOCK = threading.Lock()
_HOST_LAST_CALL: dict[str, float] = {}
RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}


def oa_headers():
    email_addr = os.environ.get('CONTACT_EMAIL', '').strip()
    ua = 'ResearchScientistSkill/2.0 (citation-trails)'
    if email_addr:
        ua = f'ResearchScientistSkill/2.0 (citation-trails; mailto:{email_addr})'
    headers = {'Accept': 'application/json', 'User-Agent': ua}
    key = os.environ.get('OPENALEX_API_KEY')
    if key:
        headers['Authorization'] = 'Bearer ' + key
    return headers


def extract_wid(url_or_id):
    if not isinstance(url_or_id, str):
        return None
    m = WID_EXTRACT_RE.search(url_or_id.strip())
    return m.group(1).upper() if m else None


def parse_retry_after(value, now=None):
    if not value:
        return None
    text = str(value).strip()
    try:
        delay = float(text)
        return max(0.0, min(delay, 30.0))
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


def _throttle_host(host, min_interval, sleep_fn):
    if not host or min_interval <= 0:
        return
    with _HOST_LOCK:
        now = time.monotonic()
        last = _HOST_LAST_CALL.get(host)
        wait = (last + min_interval - now) if last is not None else 0.0
        if wait > 0:
            sleep_fn(wait)
        _HOST_LAST_CALL[host] = time.monotonic()


def polite_get(url, params=None, timeout=20, min_interval=0.25, max_retries=3, sleep_fn=time.sleep):
    headers = oa_headers()
    full_url = url
    if params:
        full_url = url + ('&' if '?' in url else '?') + urlencode(params)
    host = (urlparse(full_url).hostname or '').lower()
    last_exc = None
    for attempt in range(max_retries + 1):
        _throttle_host(host, min_interval, sleep_fn)
        try:
            with urlopen(Request(full_url, headers=headers), timeout=timeout) as response:
                data = json.load(response)
            if not isinstance(data, dict):
                raise RuntimeError('unexpected_body')
            return data
        except HTTPError as exc:
            last_exc = RuntimeError(f'http_{exc.code}')
            if exc.code in RETRYABLE_HTTP_CODES and attempt < max_retries:
                ra = parse_retry_after(exc.headers.get('Retry-After') if exc.headers else None)
                backoff = ra if ra is not None else min(30.0, 1.0 * (2 ** attempt))
                sleep_fn(backoff)
                continue
            raise last_exc from exc
        except (URLError, TimeoutError, OSError) as exc:
            last_exc = RuntimeError('network_failure')
            if attempt < max_retries:
                sleep_fn(min(30.0, 1.0 * (2 ** attempt)))
                continue
            raise last_exc from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RuntimeError('invalid_json') from exc
    if last_exc is not None:
        raise last_exc
    raise RuntimeError('network_failure')


def get(url, params=None, timeout=20):
    return polite_get(url, params=params, timeout=timeout)

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
    parser.add_argument('--out', type=Path, help='Optional path to write JSON report')
    args = parser.parse_args()
    try:
        report = expand(args.work_id, args.pages, args.page_size)
        rendered = json.dumps(report, ensure_ascii=False)
        if args.out is not None:
            out_path = args.out.expanduser().resolve()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(rendered, encoding='utf-8')
        print(rendered)
    except (ValueError, OSError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        sys.exit(2)
