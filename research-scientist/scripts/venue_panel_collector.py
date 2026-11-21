#!/usr/bin/env python3
"""Collect a same-track accepted-paper panel scaffold from PMLR, ACL Anthology, or DBLP.

Builds a provenance-tracked panel skeleton compatible with compare_venue_novelty.py.
Collected entries carry reading_basis='metadata_only' and null reviewer ratings so
un-read panels can never pass novelty or fit verification silently.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

MAX_BYTES = 32_000_000
MAX_OFFLINE_BYTES = 32_000_000
USER_AGENT = 'ResearchScientistSkill/2.8 (venue-panel-collector)'
VOID_TAGS = {
    'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
    'link', 'meta', 'param', 'source', 'track', 'wbr',
}
BLOCK_TAGS = {'br', 'p', 'div', 'li', 'tr', 'td', 'th', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'header', 'section'}


class PanelCollectionError(RuntimeError):
    """Structured collection failure with explicit error_code and CLI exit code."""

    def __init__(self, error_code: str, message: str, *, exit_code: int = 1, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.error_code = error_code
        self.exit_code = exit_code
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {'error_code': self.error_code, 'error': str(self)}
        if self.details:
            payload.update(self.details)
        return payload


class _Node:
    __slots__ = ('tag', 'attrs', 'children')

    def __init__(self, tag: str, attrs: dict[str, str] | None = None):
        self.tag = tag
        self.attrs = attrs or {}
        self.children: list[_Node | str] = []

    def classes(self) -> set[str]:
        raw = self.attrs.get('class', '')
        return {c for c in raw.split() if c}

    def has_class(self, name: str) -> bool:
        return name in self.classes()

    def text_content(self) -> str:
        parts: list[str] = []

        def _walk(item: _Node | str) -> None:
            if isinstance(item, str):
                parts.append(item)
                return
            if item.tag in {'script', 'style'}:
                return
            if item.tag in BLOCK_TAGS:
                parts.append(' ')
            for child in item.children:
                _walk(child)
            if item.tag in BLOCK_TAGS:
                parts.append(' ')

        _walk(self)
        return re.sub(r'\s+', ' ', ''.join(parts)).strip()

    def iter_nodes(self):
        yield self
        for child in self.children:
            if isinstance(child, _Node):
                yield from child.iter_nodes()

    def find_all(self, tag: str | None = None, *, class_name: str | None = None, attr_id: str | None = None):
        results: list[_Node] = []
        for node in self.iter_nodes():
            if node is self:
                continue
            if tag is not None and node.tag != tag:
                continue
            if class_name is not None and not node.has_class(class_name):
                continue
            if attr_id is not None and node.attrs.get('id') != attr_id:
                continue
            results.append(node)
        return results

    def find_first(self, tag: str | None = None, *, class_name: str | None = None, attr_id: str | None = None) -> _Node | None:
        for node in self.iter_nodes():
            if node is self:
                continue
            if tag is not None and node.tag != tag:
                continue
            if class_name is not None and not node.has_class(class_name):
                continue
            if attr_id is not None and node.attrs.get('id') != attr_id:
                continue
            return node
        return None


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node('document')
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_l = tag.lower()
        attr_map = {k.lower(): (v if v is not None else '') for k, v in attrs}
        node = _Node(tag_l, attr_map)
        self.stack[-1].children.append(node)
        if tag_l not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_l = tag.lower()
        attr_map = {k.lower(): (v if v is not None else '') for k, v in attrs}
        self.stack[-1].children.append(_Node(tag_l, attr_map))

    def handle_endtag(self, tag: str) -> None:
        tag_l = tag.lower()
        if tag_l in VOID_TAGS:
            return
        for idx in range(len(self.stack) - 1, 0, -1):
            if self.stack[idx].tag == tag_l:
                del self.stack[idx:]
                break

    def handle_data(self, data: str) -> None:
        if data:
            self.stack[-1].children.append(data)


def _parse_html_tree(raw_html: str) -> _Node:
    builder = _TreeBuilder()
    builder.feed(raw_html)
    builder.close()
    return builder.root


def valid_url(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = urlparse(value.strip())
        return parsed.scheme == 'https' and bool(parsed.hostname) and not parsed.username and not parsed.password
    except ValueError:
        return False


def _validate_venue_id(venue_id: Any) -> str:
    if not isinstance(venue_id, str) or not venue_id.strip():
        raise PanelCollectionError('invalid_arguments', 'venue-id must be a nonblank string', exit_code=2)
    vid = venue_id.strip()
    if any(ch.isspace() for ch in vid) or '..' in vid or '://' in vid or vid.startswith('/'):
        raise PanelCollectionError('invalid_arguments', f'invalid venue-id: {venue_id!r}', exit_code=2)
    return vid


def resolve_source_url(source: str, venue_id: str) -> str:
    vid = _validate_venue_id(venue_id)
    if source == 'pmlr':
        clean = vid.strip('/')
        if clean.isdigit():
            clean = f'v{clean}'
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', clean):
            raise PanelCollectionError('invalid_arguments', f'invalid PMLR venue-id: {venue_id!r}', exit_code=2)
        url = f'https://proceedings.mlr.press/{clean}/'
    elif source == 'acl':
        clean = vid.strip('/')
        if clean.startswith('events/'):
            url = f'https://aclanthology.org/{clean}/'
        elif clean.startswith('volumes/'):
            url = f'https://aclanthology.org/{clean}/'
        elif '.' in clean:
            url = f'https://aclanthology.org/volumes/{clean}/'
        else:
            url = f'https://aclanthology.org/events/{clean}/'
    elif source == 'dblp':
        clean = vid.strip('/')
        if clean.startswith('db/'):
            clean = clean[3:]
        if not clean:
            raise PanelCollectionError('invalid_arguments', f'invalid DBLP venue-id: {venue_id!r}', exit_code=2)
        if clean.endswith('.xml') or clean.endswith('.html'):
            url = f'https://dblp.org/db/{clean}'
        else:
            url = f'https://dblp.org/db/{clean}.html'
    else:
        raise PanelCollectionError('invalid_arguments', f'unsupported source: {source!r}', exit_code=2)

    if not valid_url(url):
        raise PanelCollectionError('invalid_arguments', f'resolved non-HTTPS or invalid URL: {url}', exit_code=2)
    return url


def _detect_challenge_or_bad_body(status_code: int, headers: dict[str, str], body_bytes: bytes, source_url: str) -> str:
    if not body_bytes or not body_bytes.strip():
        raise PanelCollectionError(
            'empty_or_malformed_html',
            f'Empty response body from {source_url}',
            details={'http_status': status_code, 'source_url': source_url},
        )
    if b'\x00' in body_bytes[:4096] or body_bytes.lstrip().startswith(b'%PDF'):
        raise PanelCollectionError(
            'empty_or_malformed_html',
            f'Binary or non-HTML/XML payload received from {source_url}',
            details={'http_status': status_code, 'source_url': source_url},
        )
    try:
        text = body_bytes.decode('utf-8')
    except UnicodeDecodeError:
        text = body_bytes.decode('utf-8', errors='replace')
    lower = text.lower()
    headers_l = {str(k).lower(): str(v) for k, v in (headers or {}).items()}

    if (
        status_code == 202
        or '/.within.website/' in lower
        or 'anubis_challenge' in lower
        or "making sure you're not a bot!" in lower
        or 'making sure you&#39;re not a bot!' in lower
        or ('refresh' in headers_l and 'anubis' in headers_l['refresh'].lower())
    ):
        raise PanelCollectionError(
            'bot_challenge_anubis',
            f'Anubis bot challenge blocked access to {source_url} (use --offline-html with a saved page)',
            details={'challenge_provider': 'anubis', 'http_status': status_code, 'source_url': source_url},
        )

    cf_markers = ('just a moment', 'checking your browser', 'enable javascript and cookies', '__cf_chl_', 'cf-challenge')
    if (
        (
            (status_code in (403, 503) or 'cf-mitigated' in headers_l)
            and (any(m in lower for m in cf_markers) or 'cf-ray' in headers_l)
        )
        or ('just a moment' in lower and 'enable javascript and cookies' in lower)
    ):
        raise PanelCollectionError(
            'bot_challenge_cloudflare',
            f'Cloudflare/WAF challenge blocked access to {source_url}',
            details={'challenge_provider': 'cloudflare', 'http_status': status_code, 'source_url': source_url},
        )

    if status_code == 429:
        raise PanelCollectionError(
            'rate_limited_429',
            f'HTTP 429 rate limited by {source_url}',
            details={'http_status': 429, 'retry_after': headers_l.get('retry-after'), 'source_url': source_url},
        )
    if status_code == 403:
        raise PanelCollectionError('http_403', f'HTTP 403 forbidden at {source_url}', details={'http_status': 403, 'source_url': source_url})
    if status_code == 404:
        raise PanelCollectionError('http_404', f'HTTP 404 not found at {source_url}', details={'http_status': 404, 'source_url': source_url})
    if 500 <= status_code < 600:
        raise PanelCollectionError('http_5xx', f'HTTP {status_code} server error at {source_url}', details={'http_status': status_code, 'source_url': source_url})
    if status_code >= 400:
        raise PanelCollectionError(f'http_{status_code}', f'HTTP {status_code} error at {source_url}', details={'http_status': status_code, 'source_url': source_url})
    return text


def _check_js_shell(text: str, source_url: str) -> None:
    lower = text.lower()
    spa_markers = ('id="root"', "id='root'", 'id=root', 'id="app"', "id='app'", 'id=app', 'id="__next"', 'id=__next')
    if ('<noscript' in lower and ('enable javascript' in lower or 'requires javascript' in lower or 'javascript is disabled' in lower)) or (
        any(marker in lower for marker in spa_markers) and len(re.sub(r'<[^>]+>', '', text).strip()) < 400
    ):
        raise PanelCollectionError(
            'js_rendered_shell',
            f'JS-rendered SPA shell detected without static proceedings entries at {source_url}',
            details={'source_url': source_url},
        )


def fetch_url(url: str, timeout: int = 20) -> dict[str, Any]:
    if not valid_url(url):
        raise PanelCollectionError('invalid_arguments', f'Only HTTPS URLs are permitted: {url}', exit_code=2)
    req = Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'})
    try:
        with urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, 'status', None) or resp.getcode()
            final_url = resp.geturl() or url
            headers = {k.lower(): v for k, v in resp.headers.items()} if resp.headers else {}
            body = resp.read(MAX_BYTES + 1)
    except HTTPError as exc:
        final_url = exc.geturl() or url
        if not valid_url(final_url):
            raise PanelCollectionError('redirected_to_non_https_url', f'Redirected to non-HTTPS URL: {final_url}')
        headers = {k.lower(): v for k, v in exc.headers.items()} if exc.headers else {}
        try:
            body = exc.read(MAX_BYTES + 1)
        except Exception:
            body = b''
        return {'status_code': exc.code, 'headers': headers, 'final_url': final_url, 'body': body}
    except (URLError, TimeoutError, OSError) as exc:
        raise PanelCollectionError('network_failure', f'Network failure fetching {url}: {exc}', details={'source_url': url}) from exc

    if not valid_url(final_url):
        raise PanelCollectionError('redirected_to_non_https_url', f'Redirected to non-HTTPS URL: {final_url}', details={'final_url': final_url})
    if len(body) > MAX_BYTES:
        raise PanelCollectionError('response_too_large', f'Response exceeded {MAX_BYTES} bytes at {url}', details={'source_url': url})
    return {'status_code': status, 'headers': headers, 'final_url': final_url, 'body': body}


def _year_from_text(text: str) -> int | None:
    matches = re.findall(r'\b((?:19|20)\d{2})\b', text or '')
    if matches:
        return int(matches[-1])
    return None


def _upgrade_https_url(raw_url: str, base_url: str) -> str | None:
    if not isinstance(raw_url, str) or not raw_url.strip():
        return None
    resolved = urljoin(base_url, raw_url.strip())
    if resolved.startswith('http://dx.doi.org/'):
        resolved = 'https://doi.org/' + resolved[len('http://dx.doi.org/'):]
    elif resolved.startswith('http://doi.org/'):
        resolved = 'https://doi.org/' + resolved[len('http://doi.org/'):]
    elif resolved.startswith('http://dblp.org/'):
        resolved = 'https://dblp.org/' + resolved[len('http://dblp.org/'):]
    elif resolved.startswith('http://proceedings.mlr.press/'):
        resolved = 'https://proceedings.mlr.press/' + resolved[len('http://proceedings.mlr.press/'):]
    elif resolved.startswith('http://aclanthology.org/'):
        resolved = 'https://aclanthology.org/' + resolved[len('http://aclanthology.org/'):]
    return resolved if valid_url(resolved) else None


def _extract_doi(url: str | None) -> str | None:
    if not url:
        return None
    m = re.match(r'^https?://(?:dx\.)?doi\.org/(.+)$', url.strip(), flags=re.IGNORECASE)
    return m.group(1) if m else None


_PMLR_FRONTMATTER_EXACT = {
    'preface', 'frontmatter', 'front matter', 'editorial', 'foreword', 'table of contents',
}
_SECONDARY_TRACK_RE = re.compile(
    r'\b(?:workshops?|tutorials?|demos?|demonstrations?|findings|companions?|doctoral\s+consortium)\b',
    re.IGNORECASE,
)


def _infer_pmlr_volume_track(h2_text: str, venue_name: str) -> str:
    combined = f'{h2_text} {venue_name}'.lower()
    if re.search(r'\bworkshops?\b', combined):
        return 'Workshop'
    if re.search(r'\btutorials?\b', combined):
        return 'Tutorials'
    if re.search(r'\bdemos?\b|\bdemonstrations?\b', combined):
        return 'Demo'
    return 'Main'


def _infer_dblp_secondary_track(text: str) -> str:
    inferred = _infer_pmlr_volume_track('', text)
    if inferred != 'Main':
        return inferred
    lower = text.lower()
    if re.search(r'\bfindings\b', lower):
        return 'Findings'
    if re.search(r'\bdoctoral\s+consortium\b', lower):
        return 'Doctoral Consortium'
    if re.search(r'\bcompanions?\b', lower):
        return 'Companion'
    return 'Workshop'


def parse_pmlr_html(html_text: str, source_url: str, venue_id: str, track_filter: str | None = None, year_override: int | None = None) -> dict[str, Any]:
    tree = _parse_html_tree(html_text)
    wrapper = tree.find_first('div', class_name='wrapper') or tree
    h2 = wrapper.find_first('h2') or tree.find_first('h2')
    h2_text = h2.text_content() if h2 else ''
    venue_name = re.sub(r'^Volume\s+\d+\s*:\s*', '', h2_text, flags=re.IGNORECASE).strip() or f'PMLR {venue_id}'
    header_year = _year_from_text(h2_text)

    paper_divs = tree.find_all('div', class_name='paper')
    if not paper_divs:
        _check_js_shell(html_text, source_url)
        raise PanelCollectionError('empty_or_malformed_html', f'No PMLR div.paper entries found at {source_url}', details={'source_url': source_url})

    volume_track = _infer_pmlr_volume_track(h2_text, venue_name)
    if track_filter and track_filter.strip():
        req = track_filter.strip()
        req_l = req.lower()
        canonical_track = req
        combined_hdr = f'{h2_text} {venue_name}'.lower()
        if (
            (req_l == 'main' and volume_track != 'Main')
            or (req_l in ('workshop', 'workshops') and volume_track != 'Workshop')
            or (req_l != volume_track.lower() and req_l not in combined_hdr)
        ):
            return {
                'venue_name': venue_name,
                'year': year_override or header_year,
                'track': canonical_track,
                'screened_count': len(paper_divs),
                'frontmatter_skipped': 0,
                'track_filtered_out': len(paper_divs),
                'papers': [],
            }
    else:
        canonical_track = volume_track

    papers: list[dict[str, Any]] = []
    year_filtered_out = 0
    frontmatter_skipped = 0
    valid_entries_seen = 0

    for idx, div in enumerate(paper_divs, start=1):
        p_title = div.find_first('p', class_name='title')
        title = p_title.text_content() if p_title else ''
        if not title:
            continue
        span_authors = div.find_first('span', class_name='authors')
        authors_raw = span_authors.text_content() if span_authors else ''
        authors = [a.strip() for a in authors_raw.replace('\u00a0', ' ').split(',') if a.strip()]

        span_info = div.find_first('span', class_name='info')
        info_text = span_info.text_content() if span_info else ''
        pages_match = re.search(r':\s*(\d+\s*[-\u2013]\s*\d+)\b', info_text)
        pages = re.sub(r'\s+', '', pages_match.group(1)).replace('\u2013', '-') if pages_match else None

        abs_url = None
        main_pdf_url = None
        supp_pdf_url = None
        openreview_url = None
        for link in div.find_all('a'):
            href = link.attrs.get('href', '')
            if not href:
                continue
            resolved = _upgrade_https_url(href, source_url)
            if not resolved:
                continue
            link_text = link.text_content().strip().lower()
            href_path = urlparse(resolved).path.lower()
            if link_text in ('abs', 'abstract'):
                abs_url = abs_url or resolved
            elif 'openreview' in link_text or 'openreview.net' in resolved.lower():
                openreview_url = openreview_url or resolved
            elif 'pdf' in link_text or href_path.endswith('.pdf'):
                is_supp = (
                    'supp' in link_text
                    or 'appendix' in link_text
                    or bool(re.search(r'(?:^|[-_])supp(?:lementary)?\.pdf$', href_path))
                )
                if not is_supp and (link_text in ('pdf', 'download pdf') or 'download pdf' in link_text or href_path.endswith('.pdf')):
                    main_pdf_url = main_pdf_url or resolved
                else:
                    supp_pdf_url = supp_pdf_url or resolved

        pdf_url = main_pdf_url or supp_pdf_url
        official_url = abs_url or pdf_url
        if not official_url:
            continue
        valid_entries_seen += 1

        title_norm = re.sub(r'\s+', ' ', title).strip().lower().rstrip('.:')
        is_frontmatter = (
            not openreview_url
            and (
                title_norm in _PMLR_FRONTMATTER_EXACT
                or title_norm.startswith(('preface:', 'preface ', 'editorial:', 'front matter'))
            )
        )
        if is_frontmatter:
            frontmatter_skipped += 1
            continue

        slug = urlparse(official_url).path.strip('/')
        if slug.endswith('.html'):
            slug = slug[:-5]
        paper_slug = slug.split('/')[-1] if '/' in slug else f'paper-{idx}'

        paper_year = year_override or _year_from_text(info_text) or header_year
        if paper_year is None:
            m_slug_yr = re.search(r'(\d{2})[a-z]?$', paper_slug)
            if m_slug_yr:
                yy = int(m_slug_yr.group(1))
                paper_year = (2000 + yy) if yy < 50 else (1900 + yy)

        if year_override is not None and paper_year != year_override:
            year_filtered_out += 1
            continue

        papers.append({
            'id': f'pmlr:{slug or f"{venue_id}/{idx}"}',
            'title': title,
            'authors': authors,
            'venue': venue_name,
            'venue_id': venue_id,
            'year': paper_year,
            'track': canonical_track,
            'section': None,
            'pages': pages,
            'doi': None,
            'official_acceptance_url': official_url,
            'source_url': source_url,
            'pdf_url': pdf_url,
            'openreview_url': openreview_url,
            'abstract': None,
            'reading_basis': 'metadata_only',
            'provenance': {
                'source': 'pmlr',
                'source_url': source_url,
                'paper_slug': paper_slug,
            },
        })

    if valid_entries_seen == 0:
        raise PanelCollectionError('empty_or_malformed_html', f'PMLR entries lacked valid titles or HTTPS URLs at {source_url}')

    inferred_year = year_override or (papers[0]['year'] if papers and papers[0]['year'] else header_year)
    return {
        'venue_name': venue_name,
        'year': inferred_year,
        'track': canonical_track,
        'screened_count': len(paper_divs),
        'frontmatter_skipped': frontmatter_skipped,
        'track_filtered_out': year_filtered_out,
        'papers': papers,
    }


def _classify_acl_track(vol_id: str, vol_title: str) -> str:
    vid = (vol_id or '').lower()
    title = (vol_title or '').lower()
    if 'findings' in vid or title.startswith('findings of'):
        return 'Findings'
    if 'srw' in vid or 'student research workshop' in title:
        return 'SRW'
    if 'demo' in vid or 'demonstration' in title:
        return 'Demo'
    if 'tutorial' in vid or 'tutorial' in title:
        return 'Tutorials'
    if 'industry' in vid or 'industry' in title:
        return 'Industry'
    if (
        re.search(r'(?:^|-)(?:main|long|short)$', vid)
        or re.fullmatch(r'[pce]\d{2}-1', vid)
        or ('workshop' not in title and ('long papers' in title or 'short papers' in title or 'main conference' in title or 'volume 1' in title))
    ):
        return 'Main'
    if re.match(r'^w\d{2}-\d+', vid) or '-ws' in vid or 'workshop' in title or vid:
        return 'Workshop'
    return 'Main'


def _acl_year_from_slug(slug: str, fallback_text: str) -> int | None:
    m_mod = re.match(r'^((?:19|20)\d{2})\.', slug)
    if m_mod:
        return int(m_mod.group(1))
    m_leg = re.match(r'^[a-z](\d{2})-', slug, flags=re.IGNORECASE)
    if m_leg:
        yy = int(m_leg.group(1))
        return (1900 + yy) if yy >= 60 else (2000 + yy)
    return _year_from_text(fallback_text)


def parse_acl_html(html_text: str, source_url: str, venue_id: str, track_filter: str | None = None, year_override: int | None = None) -> dict[str, Any]:
    tree = _parse_html_tree(html_text)
    main_sec = tree.find_first('section', attr_id='main') or tree
    h2_title = main_sec.find_first('h2', attr_id='title') or tree.find_first('h2')
    venue_name = h2_title.text_content() if h2_title else f'ACL Anthology {venue_id}'

    # Build abstract lookup map from collapse divs anywhere under main_sec.
    abstract_map: dict[str, str] = {}
    for node in main_sec.find_all('div'):
        nid = node.attrs.get('id', '')
        if nid.startswith('abstract-') or node.has_class('abstract-collapse'):
            body = node.find_first('div', class_name='card-body') or node
            txt = body.text_content()
            if nid and txt:
                abstract_map[f'#{nid}'] = txt

    # Identify volume containers: <div id="..."> containing an <h4> heading and paper rows
    # without nesting other volume containers (works directly under <section id="main"> or wrapped).
    def _has_nested_volume(div_node: _Node) -> bool:
        for child in div_node.find_all('div'):
            cid = child.attrs.get('id', '')
            if (
                cid
                and not cid.startswith('abstract-')
                and child.find_first('h4') is not None
                and child.find_first(class_name='d-sm-flex') is not None
            ):
                return True
        return False

    volume_blocks: list[tuple[str, str, list[_Node]]] = []
    seen_row_ids: set[int] = set()
    for node in main_sec.find_all('div'):
        vid = node.attrs.get('id', '')
        if not vid or vid.startswith('abstract-'):
            continue
        direct_h4 = next(
            (ch for ch in node.children if isinstance(ch, _Node) and ch.tag == 'h4'),
            None,
        )
        vol_h4 = direct_h4 or (None if _has_nested_volume(node) else node.find_first('h4'))
        if vol_h4 is None:
            continue
        rows = [
            n for n in node.iter_nodes()
            if n.tag in ('div', 'p') and n.has_class('d-sm-flex') and id(n) not in seen_row_ids
        ]
        if rows:
            for r in rows:
                seen_row_ids.add(id(r))
            vol_title = vol_h4.text_content() or vid
            volume_blocks.append((vid, vol_title, rows))

    # Single-volume page (/volumes/2025.acl-long/) or flat test fixture without outer <div id="...">
    if not volume_blocks:
        rows = [
            n for n in main_sec.iter_nodes()
            if n.tag in ('div', 'p') and n.has_class('d-sm-flex')
        ]
        if rows:
            vol_id = venue_id.strip('/').split('/')[-1]
            volume_blocks.append((vol_id, venue_name, rows))

    if not volume_blocks:
        _check_js_shell(html_text, source_url)
        raise PanelCollectionError('empty_or_malformed_html', f'No ACL Anthology paper rows found at {source_url}', details={'source_url': source_url})

    parsed_candidates: list[dict[str, Any]] = []
    frontmatter_skipped = 0

    for vol_id, vol_title, rows in volume_blocks:
        vol_track = _classify_acl_track(vol_id, vol_title)
        for row in rows:
            # Find title link inside <strong><a>...</a></strong> or first non-button <a>
            strong = row.find_first('strong')
            title_link = strong.find_first('a') if strong else None
            if title_link is None:
                for a in row.find_all('a'):
                    href = a.attrs.get('href', '')
                    if href and not href.startswith('#') and not href.endswith('.pdf') and not href.endswith('.bib') and '/people/' not in href:
                        title_link = a
                        break
            if title_link is None:
                continue

            href = title_link.attrs.get('href', '')
            title = title_link.text_content()
            if not title or not href:
                continue

            slug = urlparse(href).path.strip('/')
            pdf_url = None
            has_abs = False
            abs_text = None
            authors: list[str] = []

            for link in row.find_all('a'):
                l_href = link.attrs.get('href', '')
                l_text = link.text_content().strip()
                l_lower = l_text.lower()
                if '/people/' in l_href:
                    if l_text:
                        authors.append(l_text)
                elif l_lower == 'pdf' or link.attrs.get('title', '').lower() == 'open pdf' or l_href.lower().endswith('.pdf'):
                    pdf_url = pdf_url or _upgrade_https_url(l_href, 'https://aclanthology.org/')
                elif l_lower == 'abs' or link.attrs.get('title', '').lower() == 'show abstract' or l_href.startswith('#abstract-') or link.attrs.get('data-bs-target', '').startswith('#abstract-'):
                    has_abs = True
                    target_id = link.attrs.get('data-bs-target') or l_href
                    if target_id in abstract_map:
                        abs_text = abstract_map[target_id]

            is_frontmatter = bool(
                re.search(r'\.0$', slug)
                or re.match(r'^[A-Za-z]\d{2}-\d000$', slug)
                or (not has_abs and re.match(r'^(?:proceedings|findings)\s+of\b', title, flags=re.IGNORECASE))
            )
            if is_frontmatter:
                frontmatter_skipped += 1
                continue

            if not authors:
                # Fallback: parse pipe-separated author names if /people/ links absent
                for span in row.find_all('span', class_name='d-block'):
                    full_txt = span.text_content()
                    if title in full_txt:
                        tail = full_txt.split(title, 1)[1].strip()
                        if tail:
                            authors = [a.strip() for a in tail.split('|') if a.strip()]
                        break

            official_url = _upgrade_https_url(href, 'https://aclanthology.org/')
            if not official_url:
                continue
            paper_year = year_override or _acl_year_from_slug(slug, f'{vol_id} {vol_title} {venue_name}')

            parsed_candidates.append({
                'id': f'acl:{slug}',
                'title': title,
                'authors': authors,
                'venue': venue_name,
                'venue_id': venue_id,
                'year': paper_year,
                'vol_id': vol_id,
                'vol_title': vol_title,
                'vol_track': vol_track,
                'section': vol_title,
                'pages': None,
                'doi': None,
                'official_acceptance_url': official_url,
                'source_url': source_url,
                'pdf_url': pdf_url,
                'openreview_url': None,
                'abstract': abs_text,
                'reading_basis': 'metadata_only',
                'provenance': {
                    'source': 'acl',
                    'source_url': source_url,
                    'volume_id': vol_id,
                    'paper_slug': slug,
                },
            })

    if not parsed_candidates:
        raise PanelCollectionError('empty_or_malformed_html', f'No ACL Anthology papers remained after frontmatter filtering at {source_url}')

    if track_filter and track_filter.strip():
        req = track_filter.strip()
        req_l = req.lower()
        canonical_track = req
        track_matched = [
            p for p in parsed_candidates
            if p['vol_track'].lower() == req_l or req_l in p['vol_id'].lower() or req_l in p['vol_title'].lower()
        ]
    else:
        has_main = any(p['vol_track'] == 'Main' for p in parsed_candidates)
        canonical_track = 'Main' if has_main else parsed_candidates[0]['vol_track']
        track_matched = [p for p in parsed_candidates if p['vol_track'] == canonical_track]

    if year_override is not None:
        final_list = [p for p in track_matched if p['year'] == year_override]
    else:
        final_list = track_matched

    track_filtered_out = len(parsed_candidates) - len(final_list)
    cleaned_papers: list[dict[str, Any]] = []
    for p in final_list:
        p_copy = dict(p)
        p_copy.pop('vol_id', None)
        p_copy.pop('vol_title', None)
        p_copy.pop('vol_track', None)
        p_copy['track'] = canonical_track
        cleaned_papers.append(p_copy)

    inferred_year = year_override or (cleaned_papers[0]['year'] if cleaned_papers and cleaned_papers[0]['year'] else _year_from_text(venue_name))
    return {
        'venue_name': venue_name,
        'year': inferred_year,
        'track': canonical_track,
        'screened_count': len(parsed_candidates),
        'frontmatter_skipped': frontmatter_skipped,
        'track_filtered_out': track_filtered_out,
        'papers': cleaned_papers,
    }


def _strip_dblp_trailing_dot(title: str) -> str:
    t = re.sub(r'\s+', ' ', title).strip()
    if t.endswith('...') or t.endswith('..'):
        return t
    return t[:-1].rstrip() if t.endswith('.') else t


def _parse_dblp_xml(xml_text: str, source_url: str, venue_id: str, track_filter: str | None = None, year_override: int | None = None) -> dict[str, Any]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise PanelCollectionError('malformed_xml', f'Malformed DBLP XML at {source_url}: {exc}', details={'source_url': source_url}) from exc

    venue_name: str | None = None
    proc = root.find('.//proceedings')
    if proc is not None:
        proc_title = ''.join(proc.find('title').itertext()).strip() if proc.find('title') is not None else ''
        proc_bt = (proc.findtext('booktitle') or '').strip()
        if proc_bt or proc_title:
            venue_name = _strip_dblp_trailing_dot(proc_bt or proc_title)

    frontmatter_skipped = len(root.findall('.//proceedings'))
    raw_entries = [el for el in root.iter() if el.tag in ('inproceedings', 'article')]
    if not raw_entries:
        raise PanelCollectionError('empty_or_malformed_html', f'No <inproceedings> or <article> entries found in DBLP XML at {source_url}')

    parsed_candidates: list[dict[str, Any]] = []
    for idx, elem in enumerate(raw_entries, start=1):
        title_el = elem.find('title')
        title = _strip_dblp_trailing_dot(''.join(title_el.itertext())) if title_el is not None else ''
        if not title:
            continue
        key = elem.attrib.get('key', '') or f'{venue_id}/{idx}'
        authors = [
            ''.join(a.itertext()).strip()
            for a in elem.findall('author')
            if ''.join(a.itertext()).strip()
        ]
        year_txt = (elem.findtext('year') or '').strip()
        paper_year = int(year_txt) if year_txt.isdigit() else year_override
        pages = (elem.findtext('pages') or '').strip() or None
        section = (elem.findtext('booktitle') or elem.findtext('journal') or '').strip() or None

        ee_urls = []
        for ee in elem.findall('ee'):
            if ee.text and ee.text.strip():
                upgraded = _upgrade_https_url(ee.text.strip(), source_url)
                if upgraded:
                    ee_urls.append(upgraded)

        pdf_url = next((u for u in ee_urls if urlparse(u).path.lower().endswith('.pdf')), None)
        doi = next((d for d in (_extract_doi(u) for u in ee_urls) if d), None)
        official_url = ee_urls[0] if ee_urls else f'https://dblp.org/rec/{key}.html'

        parsed_candidates.append({
            'id': f'dblp:{key}',
            'title': title,
            'authors': authors,
            'venue': venue_name or '',
            'venue_id': venue_id,
            'year': paper_year,
            'section': section,
            'pages': pages,
            'doi': doi,
            'official_acceptance_url': official_url,
            'source_url': source_url,
            'pdf_url': pdf_url,
            'openreview_url': next((u for u in ee_urls if 'openreview.net' in u.lower()), None),
            'abstract': None,
            'reading_basis': 'metadata_only',
            'provenance': {
                'source': 'dblp',
                'source_url': source_url,
                'dblp_key': key,
            },
        })

    if track_filter and track_filter.strip():
        req = track_filter.strip()
        req_l = req.lower()
        canonical_track = req
        filtered = [p for p in parsed_candidates if req_l in (p.get('section') or '').lower()]
    else:
        sections = {p['section'] for p in parsed_candidates if p.get('section')}
        if len(sections) > 1:
            non_secondary = [
                p for p in parsed_candidates
                if not (p.get('section') and _SECONDARY_TRACK_RE.search(p['section']))
            ]
            if non_secondary:
                filtered = non_secondary
                canonical_track = 'Main'
            else:
                filtered = parsed_candidates
                canonical_track = _infer_dblp_secondary_track(' '.join(sorted(sections)))
        elif len(sections) == 1:
            only_sec = next(iter(sections))
            filtered = parsed_candidates
            if _SECONDARY_TRACK_RE.search(only_sec):
                canonical_track = _infer_dblp_secondary_track(only_sec)
            else:
                canonical_track = 'Main'
        else:
            canonical_track = 'Main'
            filtered = parsed_candidates

    if year_override is not None:
        filtered = [p for p in filtered if p['year'] == year_override]

    if not venue_name:
        venue_name = next((p['section'] for p in filtered if p.get('section')), None) or f'DBLP {venue_id}'

    for p in filtered:
        p['venue'] = venue_name
        p['track'] = canonical_track

    inferred_year = year_override or (filtered[0]['year'] if filtered and filtered[0]['year'] else _year_from_text(venue_name))
    return {
        'venue_name': venue_name,
        'year': inferred_year,
        'track': canonical_track,
        'screened_count': len(parsed_candidates),
        'frontmatter_skipped': frontmatter_skipped,
        'track_filtered_out': len(parsed_candidates) - len(filtered),
        'papers': filtered,
    }


def parse_dblp_toc(raw_text: str, source_url: str, venue_id: str, track_filter: str | None = None, year_override: int | None = None) -> dict[str, Any]:
    stripped = raw_text.lstrip()
    if stripped.startswith('<?xml') or '<dblp' in stripped[:600].lower():
        return _parse_dblp_xml(raw_text, source_url, venue_id, track_filter=track_filter, year_override=year_override)

    tree = _parse_html_tree(raw_text)
    h1 = tree.find_first('h1')
    venue_name = _strip_dblp_trailing_dot(h1.text_content()) if h1 else f'DBLP {venue_id}'

    current_section: str | None = None
    parsed_candidates: list[dict[str, Any]] = []
    frontmatter_skipped = 0

    for node in tree.iter_nodes():
        if node.tag in ('h2', 'h3'):
            sec_txt = node.text_content()
            if sec_txt:
                current_section = sec_txt
            continue
        if node.tag == 'li' and node.has_class('entry'):
            if node.has_class('editor'):
                frontmatter_skipped += 1
                continue
            if not (node.has_class('inproceedings') or node.has_class('article')):
                continue

            key = node.attrs.get('id', '') or f'{venue_id}/{len(parsed_candidates) + 1}'
            title_span = node.find_first('span', class_name='title')
            title = _strip_dblp_trailing_dot(title_span.text_content()) if title_span else ''
            if not title:
                continue

            authors: list[str] = []
            for a_span in node.find_all('span'):
                if a_span.attrs.get('itemprop') == 'author':
                    name_node = a_span.find_first('span')
                    a_name = name_node.text_content() if name_node else a_span.text_content()
                    if a_name and a_name not in authors:
                        authors.append(a_name)

            pages = None
            paper_year = None
            for sp in node.find_all('span'):
                prop = sp.attrs.get('itemprop')
                if prop == 'pagination' and not pages:
                    pages = sp.text_content() or None
                elif prop == 'datePublished' and paper_year is None:
                    yr_txt = sp.text_content()
                    if yr_txt.isdigit():
                        paper_year = int(yr_txt)
            if paper_year is None:
                paper_year = year_override or _year_from_text(venue_name) or _year_from_text(venue_id)

            ee_urls: list[str] = []
            for li_ee in node.find_all('li', class_name='ee'):
                for a in li_ee.find_all('a'):
                    upgraded = _upgrade_https_url(a.attrs.get('href', ''), source_url)
                    if upgraded and upgraded not in ee_urls:
                        ee_urls.append(upgraded)

            pdf_url = next((u for u in ee_urls if urlparse(u).path.lower().endswith('.pdf')), None)
            doi = next((d for d in (_extract_doi(u) for u in ee_urls) if d), None)
            official_url = ee_urls[0] if ee_urls else f'https://dblp.org/rec/{key}.html'

            parsed_candidates.append({
                'id': f'dblp:{key}',
                'title': title,
                'authors': authors,
                'venue': venue_name,
                'venue_id': venue_id,
                'year': paper_year,
                'section': current_section,
                'pages': pages,
                'doi': doi,
                'official_acceptance_url': official_url,
                'source_url': source_url,
                'pdf_url': pdf_url,
                'openreview_url': next((u for u in ee_urls if 'openreview.net' in u.lower()), None),
                'abstract': None,
                'reading_basis': 'metadata_only',
                'provenance': {
                    'source': 'dblp',
                    'source_url': source_url,
                    'dblp_key': key,
                },
            })

    if not parsed_candidates:
        _check_js_shell(raw_text, source_url)
        raise PanelCollectionError('empty_or_malformed_html', f'No DBLP paper entries found at {source_url}', details={'source_url': source_url})

    if track_filter and track_filter.strip():
        req = track_filter.strip()
        req_l = req.lower()
        canonical_track = req
        filtered = [p for p in parsed_candidates if req_l in (p.get('section') or '').lower()]
    else:
        sections = {p['section'] for p in parsed_candidates if p.get('section')}
        if len(sections) > 1:
            non_secondary = [
                p for p in parsed_candidates
                if not (p.get('section') and _SECONDARY_TRACK_RE.search(p['section']))
            ]
            if non_secondary:
                filtered = non_secondary
                rem_sections = {p['section'] for p in filtered if p.get('section')}
                canonical_track = (
                    next(iter(rem_sections))
                    if len(rem_sections) == 1 and 'main' not in next(iter(rem_sections)).lower()
                    else 'Main'
                )
            else:
                filtered = parsed_candidates
                canonical_track = 'Workshop'
        elif len(sections) == 1:
            only_sec = next(iter(sections))
            canonical_track = 'Main' if 'main' in only_sec.lower() else only_sec
            filtered = parsed_candidates
        else:
            canonical_track = 'Main'
            filtered = parsed_candidates

    if year_override is not None:
        filtered = [p for p in filtered if p['year'] == year_override]

    for p in filtered:
        p['track'] = canonical_track

    inferred_year = year_override or (filtered[0]['year'] if filtered and filtered[0]['year'] else _year_from_text(venue_name))
    return {
        'venue_name': venue_name,
        'year': inferred_year,
        'track': canonical_track,
        'screened_count': len(parsed_candidates),
        'frontmatter_skipped': frontmatter_skipped,
        'track_filtered_out': len(parsed_candidates) - len(filtered),
        'papers': filtered,
    }


def collect_panel(
    source: str,
    venue_id: str,
    *,
    limit: int = 5,
    track: str | None = None,
    year: int | None = None,
    offline_html: str | Path | None = None,
    timeout: int = 20,
    transport=None,
) -> dict[str, Any]:
    if source not in ('pmlr', 'acl', 'dblp'):
        raise PanelCollectionError('invalid_arguments', f'Unsupported source: {source!r}', exit_code=2)
    if type(limit) is not int or limit < 5:
        raise PanelCollectionError('invalid_arguments', '--limit must be an integer >= 5', exit_code=2)
    if type(timeout) is not int or not (1 <= timeout <= 120):
        raise PanelCollectionError('invalid_arguments', '--timeout must be an integer between 1 and 120', exit_code=2)
    now = datetime.now(timezone.utc)
    if year is not None and (type(year) is not int or not (1900 <= year <= now.year + 2)):
        raise PanelCollectionError('invalid_arguments', f'Invalid --year: {year!r}', exit_code=2)

    source_url = resolve_source_url(source, venue_id)

    if offline_html is not None:
        offline_path = Path(offline_html).expanduser()
        try:
            if not offline_path.is_file():
                raise PanelCollectionError('offline_file_error', f'Offline file not found: {offline_html}', exit_code=2)
            size = offline_path.stat().st_size
            if size > MAX_OFFLINE_BYTES:
                raise PanelCollectionError('offline_file_error', f'Offline file exceeds {MAX_OFFLINE_BYTES} bytes', exit_code=2)
            body_bytes = offline_path.read_bytes()
        except PanelCollectionError:
            raise
        except OSError as exc:
            raise PanelCollectionError('offline_file_error', f'Cannot read offline file {offline_html}: {exc}', exit_code=2) from exc
        status_code = 200
        headers: dict[str, str] = {}
        final_url = source_url
        fetch_status = 'offline_fixture'
        offline_str = str(offline_path)
    else:
        fetcher = transport or fetch_url
        resp = fetcher(source_url, timeout=timeout)
        status_code = int(resp.get('status_code', 200))
        headers = resp.get('headers') or {}
        final_url = resp.get('final_url') or source_url
        if not valid_url(final_url):
            raise PanelCollectionError('redirected_to_non_https_url', f'Redirected to non-HTTPS URL: {final_url}')
        raw_body = resp.get('body', b'')
        body_bytes = raw_body.encode('utf-8') if isinstance(raw_body, str) else raw_body
        fetch_status = 'ok'
        offline_str = None

    body_text = _detect_challenge_or_bad_body(status_code, headers, body_bytes, source_url)
    body_sha256 = hashlib.sha256(body_bytes).hexdigest()

    if source == 'pmlr':
        parsed = parse_pmlr_html(body_text, source_url, venue_id, track_filter=track, year_override=year)
    elif source == 'acl':
        parsed = parse_acl_html(body_text, source_url, venue_id, track_filter=track, year_override=year)
    else:
        parsed = parse_dblp_toc(body_text, source_url, venue_id, track_filter=track, year_override=year)

    collected_papers = parsed['papers']
    required_count = max(5, limit)
    if len(collected_papers) < required_count:
        raise PanelCollectionError(
            'insufficient_panel_papers',
            f'Collected {len(collected_papers)} papers for track {parsed["track"]!r}, need at least {required_count}',
            exit_code=1,
            details={
                'found_count': len(collected_papers),
                'required_count': required_count,
                'screened_count': parsed['screened_count'],
                'track': parsed['track'],
            },
        )

    selected_papers = collected_papers[:limit]
    timestamp_iso = now.isoformat()
    manifest = f'venue_panel_collector:{source}:{venue_id}'
    for p in selected_papers:
        p['provenance']['collected_at_utc'] = timestamp_iso

    accepted_panel = [
        {
            'id': p['id'],
            'title': p['title'],
            'authors': p['authors'],
            'official_acceptance_url': p['official_acceptance_url'],
            'pdf_url': p['pdf_url'],
            'track': p['track'],
            'year': p['year'],
            'reading_basis': 'metadata_only',
            'claim': None,
            'contribution_type': None,
            'score': None,
            'low': None,
            'high': None,
            'closest_work_id': None,
            'closest_work_locator': None,
            'contribution_delta': None,
            'search_manifest': manifest,
            'score_reason': None,
            'assessment_boundary': None,
            'assessed_at_utc': None,
        }
        for p in selected_papers
    ]

    edition_str = str(parsed['year']) if parsed['year'] is not None else 'unknown'
    return {
        'schema': 'research_scientist_venue_panel_v1',
        'source': source,
        'venue_id': venue_id,
        'venue_name': parsed['venue_name'],
        'track': parsed['track'],
        'year': parsed['year'],
        'collected_at': timestamp_iso,
        'collected_at_utc': timestamp_iso,
        'source_url': source_url,
        'paper_count': len(selected_papers),
        'screened_count': parsed['screened_count'],
        'provenance': {
            'collector': 'venue_panel_collector.py',
            'source': source,
            'venue_id': venue_id,
            'source_url': source_url,
            'final_url': final_url,
            'fetched_at_utc': timestamp_iso,
            'http_status': status_code,
            'fetch_status': fetch_status,
            'sha256': body_sha256,
            'offline_html': offline_str,
            'track_filter': track,
            'limit': limit,
            'frontmatter_skipped': parsed['frontmatter_skipped'],
            'track_filtered_out': parsed['track_filtered_out'],
        },
        'papers': selected_papers,
        'venue': {
            'name': parsed['venue_name'],
            'edition': edition_str,
            'track': parsed['track'],
            'official_cfp_url': None,
            'checked_at_utc': timestamp_iso,
        },
        'panel_selection': {
            'search_manifest': manifest,
            'inclusion_rule': (
                f'Collected from official proceedings TOC (source={source}, venue_id={venue_id}, '
                f'track={parsed["track"]}, limit={limit})'
            ),
            'exclusion_log': (
                f'frontmatter_skipped={parsed["frontmatter_skipped"]}; '
                f'track_filtered_out={parsed["track_filtered_out"]}'
            ),
            'date_window': edition_str,
            'screened_count': parsed['screened_count'],
            'rubric_version': 'unscored_panel_scaffold',
            'calibration_notes': 'Metadata collected only; full-text reading and /10 novelty ratings must be supplied by reviewer.',
            'selection_bias': 'Ordered proceedings slice (first N matching entries); check selection diversity before scoring.',
        },
        'accepted_panel': accepted_panel,
    }


def _compact_output(payload: dict[str, Any], out_path: str | None = None) -> dict[str, Any]:
    return {
        'compact': True,
        'schema': payload.get('schema'),
        'source': payload.get('source'),
        'venue_id': payload.get('venue_id'),
        'venue_name': payload.get('venue_name'),
        'track': payload.get('track'),
        'year': payload.get('year'),
        'source_url': payload.get('source_url'),
        'paper_count': payload.get('paper_count'),
        'screened_count': payload.get('screened_count'),
        'sample_papers': [
            {
                'id': p.get('id'),
                'title': p.get('title'),
                'official_acceptance_url': p.get('official_acceptance_url'),
                'pdf_url': p.get('pdf_url'),
            }
            for p in (payload.get('papers') or [])[:5]
        ],
        'artifact_path': out_path,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, choices=('pmlr', 'acl', 'dblp'), help='Official proceedings source')
    parser.add_argument('--venue-id', required=True, help='Proceedings/event ID (e.g. v235, acl-2025, conf/icml/icml2024)')
    parser.add_argument('--limit', type=int, default=5, help='Minimum/target number of panel papers (>= 5)')
    parser.add_argument('--out', default=None, help='Optional output JSON file path')
    parser.add_argument('--track', default=None, help='Track or session filter (e.g. Main, Findings, Workshop)')
    parser.add_argument('--year', type=int, default=None, help='Optional 4-digit year filter/override')
    parser.add_argument('--offline-html', default=None, help='Local saved HTML/XML proceedings page for offline parsing')
    parser.add_argument('--timeout', type=int, default=20, help='HTTP request timeout in seconds (1..120)')
    parser.add_argument('--compact', action='store_true', help='Emit compact bounded summary JSON to stdout')
    args = parser.parse_args(argv)

    try:
        payload = collect_panel(
            args.source,
            args.venue_id,
            limit=args.limit,
            track=args.track,
            year=args.year,
            offline_html=args.offline_html,
            timeout=args.timeout,
        )
    except PanelCollectionError as exc:
        print(json.dumps(exc.to_dict(), ensure_ascii=False), file=sys.stderr)
        return exc.exit_code
    except (ValueError, OSError, UnicodeError) as exc:
        print(json.dumps({'error_code': 'invalid_arguments', 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

    rendered = json.dumps(payload, indent=2, ensure_ascii=False)
    out_str = None
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered + '\n', encoding='utf-8')
        out_str = str(out_path)
    if args.compact:
        print(json.dumps(_compact_output(payload, out_str), ensure_ascii=False))
    else:
        print(rendered)
    return 0


if __name__ == '__main__':
    sys.exit(main())
