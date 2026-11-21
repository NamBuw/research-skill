#!/usr/bin/env python3
"""Capture dated text snapshots of venue CFP, policy and fee pages.

The caller must establish that a source is official for the correct edition and
track. A capture proves only what was returned by a URL at the recorded time.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

MAX_BYTES = 5_000_000
MAX_TEXT_CHARS = 500_000
MAX_PDF_PAGES = 50


def valid_url(value):
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme == 'https' and bool(parsed.hostname) and not parsed.username and not parsed.password


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript', 'svg'):
            self.hidden += 1
        elif not self.hidden and tag in ('p', 'div', 'br', 'li', 'h1', 'h2', 'h3', 'h4', 'tr', 'td'):
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript', 'svg'):
            self.hidden = max(0, self.hidden - 1)
        elif not self.hidden and tag in ('p', 'div', 'li', 'tr'):
            self.parts.append(' ')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def extract_text(body, content_type):
    kind = content_type.split(';', 1)[0].strip().lower()
    if kind == 'application/pdf' or body.startswith(b'%PDF-'):
        try:
            import fitz
        except ImportError:
            return '', 'pdf_extractor_unavailable'
        try:
            doc = fitz.open(stream=body, filetype='pdf')
            text = ' '.join(page.get_text('text') for page in list(doc)[:MAX_PDF_PAGES])
            status = 'pdf_text_bounded_partial' if len(doc) > MAX_PDF_PAGES else 'pdf_text_extracted'
        except (RuntimeError, ValueError):
            return '', 'pdf_extraction_failed'
    elif kind in ('text/html', 'application/xhtml+xml', 'text/plain') or body.lstrip().startswith(b'<!DOCTYPE html'):
        decoded = body.decode('utf-8', errors='replace')
        if kind == 'text/plain':
            text, status = decoded, 'plain_text_extracted'
        else:
            parser = PageText()
            parser.feed(decoded)
            text, status = ' '.join(parser.parts), 'html_text_extracted'
    else:
        return '', 'unsupported_content_type'
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return '', 'no_extractable_text'
    if len(text) > MAX_TEXT_CHARS:
        return text[:MAX_TEXT_CHARS], status + '_truncated'
    return text, status


def fetch(url, timeout=20):
    request = Request(url, headers={'Accept': 'text/html, text/plain, application/pdf',
                                    'User-Agent': 'ResearchScientistSkill/2.5 (venue-source-capture)'})
    try:
        with urlopen(request, timeout=timeout) as response:
            final_url = response.geturl()
            if not valid_url(final_url):
                raise RuntimeError('redirected_to_non_https_url')
            body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise RuntimeError('response_too_large')
            return {'final_url': final_url, 'content_type': response.headers.get('Content-Type', ''),
                    'body': body, 'http_status': response.status}
    except HTTPError as exc:
        raise RuntimeError(f'http_{exc.code}') from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError('network_failure') from exc


def capture_url(url, transport=fetch):
    if not valid_url(url):
        raise ValueError('source URL must be HTTPS without embedded credentials')
    checked = datetime.now(timezone.utc).isoformat()
    try:
        response = transport(url)
        body = response['body']
        final_url = response['final_url']
        if not valid_url(final_url):
            raise RuntimeError('redirected_to_non_https_url')
        if not isinstance(body, bytes) or len(body) > MAX_BYTES:
            raise RuntimeError('invalid_or_oversized_response')
        if response.get('http_status') != 200:
            raise RuntimeError(f"http_{response.get('http_status')}")
        content_type = response.get('content_type', '')
        text, status = extract_text(body, content_type)
        return {'requested_url': url, 'final_url': final_url, 'fetched_at_utc': checked,
                'http_status': 200, 'content_type': content_type,
                'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body),
                'redirected_to_different_host': urlparse(url).hostname != urlparse(final_url).hostname,
                'extraction_status': status, 'text': text}
    except (RuntimeError, KeyError, TypeError) as exc:
        return {'requested_url': url, 'fetched_at_utc': checked,
                'extraction_status': 'fetch_failed', 'error': str(exc), 'text': ''}


def urls_from_dossier(dossier):
    if not isinstance(dossier, dict):
        raise ValueError('dossier must be an object')
    urls = [dossier.get('official_cfp_url')]
    for fee in dossier.get('fees', []):
        if isinstance(fee, dict) and fee.get('source_url'):
            urls.append(fee['source_url'])
    for claim in dossier.get('evidence_claims', []):
        if isinstance(claim, dict) and claim.get('source_url'):
            urls.append(claim['source_url'])
    urls.extend(dossier.get('additional_source_urls', []))
    if not urls or any(not valid_url(url) for url in urls):
        raise ValueError('all source URLs must be HTTPS without embedded credentials')
    return list(dict.fromkeys(urls))


def capture_dossier(dossier, transport=fetch):
    urls = urls_from_dossier(dossier)
    return {'format': 'research_scientist_venue_sources_v1',
            'captured_at_utc': datetime.now(timezone.utc).isoformat(),
            'sources': [capture_url(url, transport) for url in urls],
            'warning': ('A snapshot records returned text and a content hash, not official status, correct edition, '
                        'track eligibility, date interpretation, complete fees, or currentness after capture. '
                        'Inspect the original page/PDF and its context before recommending a venue.')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dossier_json')
    args = parser.parse_args()
    try:
        dossier = json.loads(Path(args.dossier_json).read_text(encoding='utf-8'))
        print(json.dumps(capture_dossier(dossier), ensure_ascii=False))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
