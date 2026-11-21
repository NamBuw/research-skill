#!/usr/bin/env python3
# Incorporates and adapts components from research-paper-lifecycle-skills
# (https://github.com/ShaishavMaisuria/research-paper-lifecycle-skills,
#  commit cf30d6452cc6fd0570dd760eb65696f4a3485398, Apache-2.0):
#   - skills/parse-cfp/scripts/fetch_cfp.py (gzip decompression, 429/503 Retry-After
#     backoff, HTML structured text extraction)
#   - skills/select-venue/scripts/dblp_venue_lookup.py (DBLP venue & TOC lookup)
#
# Copyright 2026 Shaishav Maisuria
# Licensed under the Apache License, Version 2.0 (the "License").
# NOTICE: This product includes research-paper lifecycle agent skills originally
# developed by Shaishav Maisuria.
#
# Modified for research-scientist (M4_1): added per-hop redirect chain recording
# and HTTPS validation, same-host stale-year redirect detection, multi-signal
# JS-rendered dynamic page detection, CFP candidate signal extraction,
# non-crashing DBLP Anubis 202 / rate-limit / unreachable handling, and
# F20 --compact / --out / --artifacts-dir externalization.
"""Capture dated text snapshots of venue CFP, policy and fee pages.

The caller must establish that a source is official for the correct edition and
track. A capture proves only what was returned by a URL at the recorded time.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_BYTES = 5_000_000
MAX_TEXT_CHARS = 500_000
MAX_PDF_PAGES = 50

DBLP_BASE = 'https://dblp.org/search'
DEFAULT_USER_AGENT = 'ResearchScientistSkill/2.8 (venue-source-capture)'

SKIP_TAGS = ('script', 'style', 'noscript', 'svg', 'template', 'iframe', 'head')
CFP_HEADINGS = {'h1': '#', 'h2': '##', 'h3': '###', 'h4': '####', 'h5': '#####', 'h6': '######'}
CFP_BLOCK_TAGS = {
    'p', 'div', 'section', 'article', 'ul', 'ol', 'table', 'thead', 'tbody',
    'blockquote', 'pre', 'dt', 'dd', 'dl', 'figure', 'figcaption', 'header',
    'footer', 'nav', 'main', 'aside', 'form', 'fieldset',
}

NON_EDITION_QUERY_KEYS = {
    'id', 'paper_id', 'submission_id', 'user_id', 'page_id', 'post_id', 'pid',
    'p', 'page', 'offset', 'limit', 'port', 'v', 'ver', 'version', 'build',
    'rev', 'token', 'session', '_t', 'date', 'updated', 'ts', 'timestamp',
}

NON_YEAR_SLUG_PREFIXES = {
    'jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'sept', 'oct',
    'nov', 'dec', 'vol', 'ver', 'part', 'pt', 'step', 'page', 'pg', 'pp', 'id',
    'pid', 'paper', 'sub', 'issue', 'fig', 'sec', 'ch', 'track', 'room', 'hall',
    'day', 'item', 'node', 'post', 'port', 'rfc', 'iso', 'utf', 'win', 'mac',
    'ubuntu', 'cuda', 'py', 'v',
}
NON_YEAR_COMMON_WORDS = NON_YEAR_SLUG_PREFIXES | {
    'january', 'february', 'march', 'april', 'june', 'july', 'august',
    'september', 'october', 'november', 'december', 'top', 'for', 'last',
    'next', 'first', 'second', 'third', 'best', 'only', 'just', 'about',
    'around', 'over', 'under', 'above', 'below', 'more', 'than', 'less',
    'at', 'by', 'on', 'in', 'of', 'to', 'from', 'with', 'plus', 'save',
    'tier', 'rank', 'week', 'weeks', 'month', 'months', 'year', 'years',
    'days', 'hours', 'line', 'lines', 'table', 'slide', 'slides', 'section',
    'group', 'phase', 'round', 'level', 'grade', 'class', 'batch', 'epoch',
    'epochs', 'layer', 'layers', 'head', 'heads', 'token', 'tokens', 'model',
    'seat', 'seats', 'code', 'note', 'notes', 'rule', 'rules', 'case', 'cases',
    'unit', 'units', 'task', 'tasks', 'slot', 'slots', 'zone', 'mode', 'type',
    'list', 'card', 'date', 'time', 'free', 'paid', 'full', 'late', 'early',
    'open', 'main', 'core', 'base', 'root', 'home', 'info', 'help', 'usd',
    'eur', 'gbp', 'age', 'min', 'max', 'up', 'edition', 'volume',
}

SPA_MOUNT_IDS = {'root', 'app', '__next', '__nuxt', 'app-root', 'svelte'}
SPA_MOUNT_ATTRS = {'data-reactroot', 'ng-app', 'ng-version', 'data-v-app'}
PRICING_CONTAINER_IDS = {
    'earlyregistration', 'lateregistration', 'pricing-table', 'pricing_table',
    'fee-table', 'fee_table', 'registration-fees', 'registration_fees',
    'pricing-container', 'pricing_container',
}
BUNDLE_SCRIPT_RE = re.compile(
    r'(?:_next/static|static/js|webpack|vite|chunk|bundle|app\.js|main\.js|runtime\.js)',
    re.I,
)
HYDRATION_MARKER_RE = re.compile(
    r'(?:__NEXT_DATA__|__NUXT__|__INITIAL_STATE__|__APOLLO_STATE__)',
)
NOSCRIPT_JS_RE = re.compile(
    r'\b(?:enable\s+javascript|javascript\s+(?:is\s+)?required|requires?\s+javascript|'
    r'javascript\s+must\s+be\s+enabled|turn\s+on\s+javascript|without\s+javascript|'
    r'activate\s+javascript)\b',
    re.I,
)
LOADING_PLACEHOLDER_RE = re.compile(
    r'(?:\b(?:loading\s+(?:[a-z]+\s+){0,3}(?:fees?|pricing|rates?|registration|cfp|dates?|content|page|table|details|data)|'
    r'please\s+wait\s+while|fetching\s+(?:[a-z]+\s+){0,2}(?:data|pricing|rates?|fees?|registration))\b|'
    r'\bloading\.\.\.)',
    re.I,
)
CALCULATOR_PLACEHOLDER_RE = re.compile(
    r'\b(?:(?:pricing|fee|registration)\s+calculator|calculate\s+your\s+fee|'
    r'(?:select|choose)\s+(?:your\s+)?(?:[a-z]+\s+){0,2}(?:category|tier|option|level|country|membership|type)\s+'
    r'to\s+(?:view|see|calculate|compute|display|show))\b',
    re.I,
)
CURRENCY_AMOUNT_RE = re.compile(
    r'(?:[$€£]\s*\d+(?:[.,]\d+)?|\b\d+(?:[.,]\d+)?\s*(?:USD|EUR|GBP|CAD|AUD)\b)',
    re.I,
)
STATIC_FEE_OR_CFP_RE = re.compile(
    r'(?:no\s+(?:publication|submission|author|page)\s+fees?|free\s+to\s+publish|'
    r'[$€£]\s*\d+|\b(?:USD|EUR|GBP)\s*\d+|\b\d+\s*(?:USD|EUR|GBP)\b|'
    r'\b(?:deadline|submission|camera[- ]ready|AoE|UTC[+-]\d+)\b)',
    re.I,
)
SUBMISSION_SYSTEM_PATTERNS = (
    ('openreview', re.compile(r'openreview\.net/(?:group|venue)\?id=', re.I)),
    ('cmt', re.compile(r'cmt3\.research\.microsoft\.com/', re.I)),
    ('easychair', re.compile(r'easychair\.org/(?:conferences/|my/conference\?conf=)', re.I)),
    ('hotcrp', re.compile(r'(?:\.hotcrp\.com|/hotcrp(?:/|$|\?))', re.I)),
    ('pcs', re.compile(r'precisionconference\.com', re.I)),
    ('scholarone', re.compile(r'mc\.manuscriptcentral\.com/', re.I)),
)

_last_dblp_request_at = 0.0


class _NonHttpsRedirectError(Exception):
    """Raised immediately when an HTTP redirect targets a non-HTTPS or credentialed URL."""


def _user_agent() -> str:
    email = os.environ.get('CONTACT_EMAIL', '').strip()
    if email and '@' in email and '.' in email.rsplit('@', 1)[-1]:
        return f'research-scientist-skill (mailto:{email})'
    return DEFAULT_USER_AGENT


def valid_url(value):
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme == 'https' and bool(parsed.hostname) and not parsed.username and not parsed.password


def _normalized_host_port(url: str) -> tuple[str, int]:
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower().rstrip('.')
    if parsed.port is not None:
        port = parsed.port
    elif parsed.scheme == 'https':
        port = 443
    elif parsed.scheme == 'http':
        port = 80
    else:
        port = 0
    return host, port


def _is_anubis_challenge(raw_html_or_text: str) -> bool:
    lower = raw_html_or_text.lower()
    return any(
        marker in lower
        for marker in (
            'anubis_challenge',
            '/.within.website/x/cmd/anubis/',
            "making sure you're not a bot",
            'making sure you&#39;re not a bot',
            'github.com/techarohq/anubis',
        )
    )


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        tag_l = tag.lower()
        if tag_l in SKIP_TAGS:
            self.hidden += 1
        elif not self.hidden and tag_l in ('p', 'div', 'br', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'tr', 'td', 'th', 'section', 'article'):
            self.parts.append(' ')

    def handle_endtag(self, tag):
        tag_l = tag.lower()
        if tag_l in SKIP_TAGS:
            self.hidden = max(0, self.hidden - 1)
        elif not self.hidden and tag_l in ('p', 'div', 'li', 'tr', 'section', 'article'):
            self.parts.append(' ')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


class CFPTextExtractor(HTMLParser):
    """Markdown-ish CFP text preserving headings, lists, tables, strikethrough, and absolute links."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0
        self.href: str | None = None
        self.links: list[str] = []
        self._in_tr = False
        self._first_cell = False

    def handle_starttag(self, tag, attrs):
        tag_l = tag.lower()
        if tag_l in SKIP_TAGS:
            self.skip += 1
            return
        if self.skip:
            return
        if tag_l in CFP_HEADINGS:
            self.out.append(f'\n\n{CFP_HEADINGS[tag_l]} ')
        elif tag_l == 'li':
            self.out.append('\n- ')
        elif tag_l == 'tr':
            self.out.append('\n| ')
            self._in_tr = True
            self._first_cell = True
        elif tag_l in ('td', 'th'):
            if self._in_tr and self._first_cell:
                self._first_cell = False
            else:
                self.out.append(' | ')
        elif tag_l in ('s', 'del', 'strike'):
            self.out.append('~~')
        elif tag_l == 'br':
            self.out.append('\n')
        elif tag_l in CFP_BLOCK_TAGS:
            self.out.append('\n')
        elif tag_l == 'a':
            href = dict(attrs).get('href') or ''
            if href.startswith(('http://', 'https://')):
                self.href = href
                self.links.append(href)

    def handle_endtag(self, tag):
        tag_l = tag.lower()
        if tag_l in SKIP_TAGS:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag_l == 'a' and self.href:
            self.out.append(f' [{self.href}]')
            self.href = None
        elif tag_l in ('s', 'del', 'strike'):
            self.out.append('~~')
        elif tag_l == 'tr':
            if self._in_tr:
                self.out.append(' |\n')
                self._in_tr = False
                self._first_cell = False
        elif tag_l in CFP_BLOCK_TAGS or tag_l in CFP_HEADINGS:
            self.out.append('\n')

    def handle_data(self, data):
        if not self.skip and data:
            self.out.append(data)


def to_structured_text(doc: str) -> tuple[str, list[str]]:
    parser = CFPTextExtractor()
    parser.feed(doc)
    parser.close()
    text = ''.join(parser.out)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r' ?\n ?', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip(), list(dict.fromkeys(parser.links))


_DATE_TIME_CUE_RE = re.compile(
    r'(?:\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2}\b|'
    r'\b20[23]\d[-/]\d{1,2}[-/]\d{1,2}\b|\b(?:AoE|UTC[+-]\d{1,2}|\d{1,2}:\d{2}|TBA|rolling)\b)',
    re.I,
)
_DEADLINE_LINE_RE = re.compile(
    r'(?:\b(?:deadline|submission|abstract|full[- ]paper|notification|rebuttal|camera[- ]ready)\b|'
    r'\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+20[23]\d\b)',
    re.I,
)


def extract_cfp_signals(structured_text: str, raw_html: str = '', links: list[str] | None = None) -> dict:
    """Extract candidate CFP cues tagged candidate_extracted_unverified."""
    body_urls = [
        u.rstrip('.,;)')
        for u in re.findall(r'https?://[^\s\]"\'<>]+', structured_text)
    ]
    if links is None:
        raw_urls = [
            u.rstrip('.,;)')
            for u in re.findall(r'https?://[^\s\]"\'<>]+', raw_html)
        ]
        all_links = list(dict.fromkeys(body_urls + raw_urls))
    else:
        all_links = list(dict.fromkeys(list(links) + body_urls))
    lines = [line.strip() for line in structured_text.splitlines() if line.strip()]
    deadlines: list[str] = []
    for line in lines:
        had_strike = '~~' in line
        active_line = re.sub(r'\s+', ' ', re.sub(r'~~.*?~~', ' ', line)).strip()
        # Clean empty table cells or standalone list bullets left after removing ~~...~~
        active_plain = re.sub(r'^[|\-\s]+|[|\s]+$', '', active_line).strip()
        if not active_plain:
            continue
        if re.match(r'^#{1,6}\s+', active_line) and not _DATE_TIME_CUE_RE.search(active_line):
            continue
        if had_strike and not _DATE_TIME_CUE_RE.search(active_plain):
            continue
        if _DEADLINE_LINE_RE.search(active_plain):
            deadlines.append(active_line if had_strike else line)
        if len(deadlines) >= 20:
            break
    timezones = sorted(set(re.findall(r'\b(?:AoE|UTC[+-]\d{1,2}(?::\d{2})?|PST|PDT|PT|EST|EDT|ET|GMT|UTC)\b', structured_text)))
    page_limits = [
        line for line in lines
        if re.search(r'\b(?:\d+\s+pages?|page\s+limit|references|appendi(?:x|ces)|checklist|impact\s+statement)\b', line, re.I)
    ][:15]
    submission_systems: dict[str, list[str]] = {}
    for link in all_links:
        for system_name, pat in SUBMISSION_SYSTEM_PATTERNS:
            if pat.search(link):
                submission_systems.setdefault(system_name, [])
                if link not in submission_systems[system_name]:
                    submission_systems[system_name].append(link)
    return {
        'verification_status': 'candidate_extracted_unverified',
        'deadlines': deadlines,
        'timezones': timezones,
        'page_limits': page_limits,
        'submission_systems': submission_systems,
    }


class _DynamicHTMLInspector(HTMLParser):
    """Single-pass HTML structure inspector for JS-rendered/AJAX shell detection."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.in_script = False
        self.in_noscript = False
        self.in_table = False
        self.in_cell = False
        self.external_script_count = 0
        self.inline_script_bytes = 0
        self.bundle_script_hits: list[str] = []
        self.hydration_markers: list[str] = []
        self.noscript_parts: list[str] = []
        self.table_count = 0
        self.nonempty_cell_count = 0
        self.nonempty_td_count = 0
        self.cell_tag: str | None = None
        self.cell_parts: list[str] = []
        self.has_static_fee_table = False
        self._tag_stack: list[str] = []
        self._spa_stack: list[tuple[int, str, list[str]]] = []
        self._pricing_stack: list[tuple[int, str, list[str]]] = []
        self.spa_mounts_seen: list[str] = []
        self.empty_spa_mounts: list[str] = []
        self.empty_pricing_containers: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag_l = tag.lower()
        attr_map = {k.lower(): (v or '') for k, v in attrs}
        self._tag_stack.append(tag_l)
        depth = len(self._tag_stack)

        if tag_l == 'script':
            self.in_script = True
            self.skip_depth += 1
            src = attr_map.get('src', '')
            if src:
                self.external_script_count += 1
                if BUNDLE_SCRIPT_RE.search(src):
                    self.bundle_script_hits.append(src)
            if attr_map.get('id', '') in ('__NEXT_DATA__', '__NUXT_DATA__'):
                self.hydration_markers.append(attr_map['id'])
            return

        if tag_l == 'noscript':
            self.in_noscript = True
            self.skip_depth += 1
            return

        if tag_l in ('style', 'svg', 'template', 'iframe', 'head'):
            self.skip_depth += 1
            return

        elem_id = attr_map.get('id', '').strip()
        classes = [c.strip().lower() for c in attr_map.get('class', '').split() if c.strip()]

        spa_label = None
        if elem_id.lower() in SPA_MOUNT_IDS:
            spa_label = f'id={elem_id}'
        elif tag_l == 'app-root':
            spa_label = 'tag=app-root'
        elif any(a in attr_map for a in SPA_MOUNT_ATTRS):
            matched_attr = next(a for a in SPA_MOUNT_ATTRS if a in attr_map)
            spa_label = f'attr={matched_attr}'
        elif attr_map.get('data-server-rendered', '').lower() == 'false':
            spa_label = 'data-server-rendered=false'
        if spa_label:
            self.spa_mounts_seen.append(spa_label)
            self._spa_stack.append([depth, spa_label, [], 0, False])

        pricing_label = None
        if elem_id.lower() in PRICING_CONTAINER_IDS:
            pricing_label = elem_id
        else:
            for c in classes:
                if c in PRICING_CONTAINER_IDS:
                    pricing_label = c
                    break
        if pricing_label:
            self._pricing_stack.append((depth, pricing_label, []))

        if tag_l in ('table', 'tbody'):
            self.table_count += 1
            self.in_table = True
        elif tag_l in ('td', 'th'):
            self.in_cell = True
            self.cell_tag = tag_l
            self.cell_parts = []

    def _close_spa_mount(
        self,
        label: str,
        parts: list[str],
        mount_td_count: int,
        mount_has_fee_table: bool,
    ) -> None:
        inner = re.sub(r'\s+', ' ', ''.join(parts)).strip()
        has_static_mount_content = (
            mount_td_count > 0
            or mount_has_fee_table
            or bool(CURRENCY_AMOUNT_RE.search(inner))
            or bool(STATIC_FEE_OR_CFP_RE.search(inner))
        )
        is_truly_empty = len(inner) < 25 and not (mount_td_count > 0 and mount_has_fee_table)
        is_empty_without_signals = len(inner) < 100 and not has_static_mount_content
        if (is_truly_empty or is_empty_without_signals) and label not in self.empty_spa_mounts:
            self.empty_spa_mounts.append(label)

    def handle_endtag(self, tag):
        tag_l = tag.lower()

        if tag_l == 'script' and self.in_script:
            self.in_script = False
            self.skip_depth = max(0, self.skip_depth - 1)
        elif tag_l == 'noscript' and self.in_noscript:
            self.in_noscript = False
            self.skip_depth = max(0, self.skip_depth - 1)
        elif tag_l in ('style', 'svg', 'template', 'iframe', 'head'):
            self.skip_depth = max(0, self.skip_depth - 1)

        if tag_l in ('td', 'th') and self.in_cell:
            cell_text = re.sub(r'\s+', ' ', ''.join(self.cell_parts)).strip()
            if cell_text:
                self.nonempty_cell_count += 1
                is_td = self.cell_tag == 'td' or tag_l == 'td'
                has_currency = bool(CURRENCY_AMOUNT_RE.search(cell_text))
                if is_td:
                    self.nonempty_td_count += 1
                if has_currency:
                    self.has_static_fee_table = True
                for spa_entry in self._spa_stack:
                    if is_td:
                        spa_entry[3] += 1
                    if has_currency:
                        spa_entry[4] = True
            self.in_cell = False
            self.cell_tag = None
            self.cell_parts = []

        # Pop matching tag from stack cleanly
        popped_depth = len(self._tag_stack)
        if self._tag_stack:
            if self._tag_stack[-1] == tag_l:
                self._tag_stack.pop()
            elif tag_l in self._tag_stack:
                idx = len(self._tag_stack) - 1 - self._tag_stack[::-1].index(tag_l)
                popped_depth = idx + 1
                del self._tag_stack[idx:]

        while self._spa_stack and self._spa_stack[-1][0] >= popped_depth:
            _, label, parts, mount_td_count, mount_has_fee_table = self._spa_stack.pop()
            self._close_spa_mount(label, parts, mount_td_count, mount_has_fee_table)

        while self._pricing_stack and self._pricing_stack[-1][0] >= popped_depth:
            _, label, parts = self._pricing_stack.pop()
            inner = re.sub(r'\s+', ' ', ''.join(parts)).strip()
            is_loading_only = (
                len(inner) < 200
                and bool(LOADING_PLACEHOLDER_RE.search(inner))
                and not CURRENCY_AMOUNT_RE.search(inner)
            )
            if (len(inner) < 15 or is_loading_only) and label not in self.empty_pricing_containers:
                self.empty_pricing_containers.append(label)

    def handle_data(self, data):
        if self.in_script:
            self.inline_script_bytes += len(data.encode('utf-8', errors='replace'))
            m = HYDRATION_MARKER_RE.search(data)
            if m and m.group(0) not in self.hydration_markers:
                self.hydration_markers.append(m.group(0))
            return
        if self.in_noscript:
            self.noscript_parts.append(data)
            return
        if self.skip_depth:
            return
        if self.in_cell:
            self.cell_parts.append(data)
        for spa_entry in self._spa_stack:
            spa_entry[2].append(data)
        for _, _, parts in self._pricing_stack:
            parts.append(data)

    def finalize(self) -> None:
        while self._spa_stack:
            _, label, parts, mount_td_count, mount_has_fee_table = self._spa_stack.pop()
            self._close_spa_mount(label, parts, mount_td_count, mount_has_fee_table)
        while self._pricing_stack:
            _, label, parts = self._pricing_stack.pop()
            inner = re.sub(r'\s+', ' ', ''.join(parts)).strip()
            is_loading_only = (
                len(inner) < 200
                and bool(LOADING_PLACEHOLDER_RE.search(inner))
                and not CURRENCY_AMOUNT_RE.search(inner)
            )
            if (len(inner) < 15 or is_loading_only) and label not in self.empty_pricing_containers:
                self.empty_pricing_containers.append(label)


def detect_js_rendered(raw_html: str, extracted_text: str, extraction_status: str) -> tuple[bool, list[str]]:
    """Detect JS-rendered SPAs, AJAX pricing shells, and bot/challenge interstitials.

    Uses positive dynamic signals only (never flags short static pages purely on len < 500).
    """
    if not isinstance(raw_html, str) or not raw_html.strip():
        return False, []
    if extraction_status.startswith(('pdf_', 'plain_text_', 'unsupported_', 'fetch_failed')):
        return False, []

    inspector = _DynamicHTMLInspector()
    inspector.feed(raw_html)
    inspector.close()
    inspector.finalize()

    signals: list[str] = []
    raw_lower = raw_html.lower()
    text_norm = re.sub(r'\s+', ' ', extracted_text or '').strip()
    text_lower = text_norm.lower()
    has_script_tag = '<script' in raw_lower
    has_static_prose = bool(STATIC_FEE_OR_CFP_RE.search(text_norm))

    # 1. Empty pricing / AJAX containers (NeurIPS / ICML 2026 live pattern)
    for label in inspector.empty_pricing_containers:
        signals.append(f'empty_pricing_container:{label}')
    if ('pricingspinner' in raw_lower or 'fa-spinner' in raw_lower) and any(
        tok in raw_lower for tok in ('getpricing', 'early_invoice_html', 'late_invoice_html', '$.ajax', 'fetch(')
    ):
        signals.append('ajax_pricing_loader')
    elif any(tok in raw_lower for tok in ('early_invoice_html', 'late_invoice_html', 'getpricing(')) and not inspector.has_static_fee_table:
        signals.append('ajax_pricing_script')

    # 2. Empty SPA mount containers
    for label in inspector.empty_spa_mounts:
        signals.append(f'empty_spa_mount:{label}')

    # 3. <noscript> JS-required warning (skip SSR-rendered pages unless empty SPA mount or dynamic pricing warning without static content)
    noscript_text = re.sub(r'\s+', ' ', ' '.join(inspector.noscript_parts)).strip()
    if noscript_text and NOSCRIPT_JS_RE.search(noscript_text):
        is_ssr_rendered = (
            not inspector.empty_spa_mounts
            and (len(text_norm) >= 400 or inspector.has_static_fee_table or has_static_prose)
        )
        if (
            bool(inspector.empty_spa_mounts)
            or not is_ssr_rendered
            or (
                not inspector.has_static_fee_table
                and not has_static_prose
                and bool(re.search(r'\b(?:fee|pricing|registration|cfp|deadline|calculator)\b', noscript_text, re.I))
            )
        ):
            signals.append('noscript_requires_js')

    # 4. Dynamic loading / interactive calculator placeholders
    if LOADING_PLACEHOLDER_RE.search(text_norm) and (len(text_norm) < 1000 or not inspector.has_static_fee_table):
        signals.append('dynamic_loading_placeholder')
    if CALCULATOR_PLACEHOLDER_RE.search(text_norm) and not inspector.has_static_fee_table:
        signals.append('dynamic_calculator_placeholder')

    # 5. JS challenge / bot walls
    for marker in (
        'anubis_challenge',
        '/.within.website/x/cmd/anubis/',
        "making sure you're not a bot",
        'making sure you&#39;re not a bot',
        'just a moment',
        'checking your browser',
        'cf-browser-verification',
        'verify you are human',
        'enable cookies and javascript',
    ):
        if marker in raw_lower or marker in text_lower:
            if len(text_norm) < 1500 or 'anubis' in marker or 'cf-browser-verification' in marker:
                signals.append(f'js_challenge_wall:{marker}')
                break

    # 6. Empty HTML or sparse body with scripts / hydration markers / empty table
    if extraction_status == 'no_extractable_text' and has_script_tag:
        signals.append('empty_html_with_scripts')

    if (
        inspector.table_count > 0
        and inspector.nonempty_td_count == 0
        and has_script_tag
        and not inspector.has_static_fee_table
    ):
        signals.append('empty_table_with_scripts')

    has_nonempty_ssr_mount = bool(inspector.spa_mounts_seen) and not inspector.empty_spa_mounts
    if (
        len(text_norm) < 200
        and not inspector.has_static_fee_table
        and not has_static_prose
        and not has_nonempty_ssr_mount
        and (
            bool(inspector.bundle_script_hits)
            or bool(inspector.hydration_markers)
            or (inspector.external_script_count >= 2 and inspector.inline_script_bytes >= 1500)
            or (
                inspector.inline_script_bytes >= 1500
                and (inspector.inline_script_bytes / max(len(text_norm), 1)) > 10
            )
        )
    ):
        signals.append('sparse_body_with_js_shell')

    deduped = list(dict.fromkeys(signals))
    return bool(deduped), deduped


def extract_url_years(url: str) -> list[int]:
    """Extract normalized 4-digit conference/edition years from URL path & query only."""
    if not isinstance(url, str) or not url:
        return []
    parsed = urlparse(url)
    # Filter non-edition query parameters; keep year/edition/track/conf params
    kept_params = []
    if parsed.query:
        for k, v in parse_qsl(parsed.query, keep_blank_values=True):
            kl = k.lower()
            if kl in NON_EDITION_QUERY_KEYS or kl.startswith('utm_'):
                continue
            kept_params.append((k, v))
    filtered_query = urlencode(kept_params)
    target = parsed.path + ('?' + filtered_query if filtered_query else '')

    # 1. Strip date tails (-MM-DD or /MM/DD) attached to YYYY so 2026-02-15 -> 2026
    target = re.sub(
        r'(?<!\d)(20[0-3]\d)[-/](?:0?[1-9]|1[0-2])[-/](?:0?[1-9]|[12]\d|3[01])(?!\d)',
        r'\1 ',
        target,
    )
    # 2. Strip standalone MM-DD / MM/DD calendar dates (e.g. 02-15 -> 02-16)
    target = re.sub(
        r'(?<!\d)(?:0?[1-9]|1[0-2])[-/](?:0?[1-9]|[12]\d|3[01])(?!\d)',
        ' ',
        target,
    )
    # 3. Mask ID/version path segments (e.g. /paper/2025, /v235, /node/2025)
    target = re.sub(
        r'(?i)/(?:paper|papers|node|p|id|submission|submissions|track|page|vol|volume|v)/20[0-3]\d(?=/|$|\?)',
        '/ ',
        target,
    )
    target = re.sub(r'(?i)/v\d+(?=/|$|\?)', '/ ', target)
    target = re.sub(r'(?i)\b(?:paper|id|node|build|ver|version|rev)[-_]?20[0-3]\d\b', ' ', target)

    years: list[int] = []
    # 4. Extract 4-digit years (supports icml2026, kdd2027, /2027/, ?year=2027, aaai-2027)
    for m in re.finditer(r'(?<!\d)(20[0-3]\d)(?!\d)', target):
        years.append(int(m.group(1)))

    # Mask 4-digit years before matching 2-digit slug years
    masked = re.sub(r'(?<!\d)20[0-3]\d(?!\d)', ' ', target)
    # 5. Extract venue/slug-attached 2-digit years (e.g. aaai-27 -> 2027)
    for m in re.finditer(r'(?<![a-z0-9])([a-z]{2,15})[-_]?([2-3]\d)(?!\d|[-/]\d{2})', masked, re.I):
        prefix = m.group(1).lower()
        if prefix in NON_YEAR_SLUG_PREFIXES:
            continue
        years.append(2000 + int(m.group(2)))

    return sorted(set(years))


def _extract_title_h1_years(raw_html: str) -> list[int]:
    """Extract explicit conference years from HTML <title> and <h1> tags only."""
    if not raw_html:
        return []
    snippets = re.findall(r'<(?:title|h1)\b[^>]*>(.*?)</(?:title|h1)>', raw_html, re.I | re.S)
    if not snippets:
        return []
    combined = re.sub(r'<[^>]+>', ' ', ' '.join(snippets))
    years: list[int] = []
    for m in re.finditer(r'(?<!\d)(20[0-3]\d)(?!\d)', combined):
        years.append(int(m.group(1)))
    masked = re.sub(r'(?<!\d)20[0-3]\d(?!\d)', ' ', combined)
    for m in re.finditer(r'(?<![a-z0-9])([a-z]{2,15})[-_]?([2-3]\d)(?!\d|[-/]\d{2})', masked, re.I):
        if m.group(1).lower() not in NON_YEAR_SLUG_PREFIXES:
            years.append(2000 + int(m.group(2)))
    for m in re.finditer(r'(?<![a-z0-9])([a-z]{2,15})\s+([2-3]\d)(?!\d|[-/]\d{2}|st\b|nd\b|rd\b|th\b|%)', masked, re.I):
        if m.group(1).lower() not in NON_YEAR_COMMON_WORDS:
            years.append(2000 + int(m.group(2)))
    return sorted(set(years))


def _normalize_redirect_chain(requested_url: str, final_url: str, raw_chain) -> list[dict]:
    if raw_chain is None:
        if final_url == requested_url:
            return []
        return [{'from_url': requested_url, 'status': None, 'location': final_url, 'to_url': final_url}]
    normalized = []
    for item in raw_chain:
        if isinstance(item, dict):
            normalized.append({
                'from_url': item.get('from_url', ''),
                'status': item.get('status', item.get('http_status')),
                'location': item.get('location', item.get('to_url', '')),
                'to_url': item.get('to_url', item.get('location', '')),
            })
        elif isinstance(item, str):
            normalized.append({'from_url': '', 'status': None, 'location': item, 'to_url': item})
    return normalized


def detect_same_host_path_redirect_year_mismatch(
    requested_url: str,
    final_url: str,
    redirect_chain=None,
    raw_html: str = '',
) -> tuple[bool, dict | None]:
    """Detect edition/year drift across same-host HTTP redirects (e.g. aaai-27 -> aaai-25)."""
    req_host, req_port = _normalized_host_port(requested_url)
    fin_host, fin_port = _normalized_host_port(final_url)
    if not req_host or (req_host, req_port) != (fin_host, fin_port):
        return False, None

    hops = _normalize_redirect_chain(requested_url, final_url, redirect_chain)
    if final_url == requested_url and not hops:
        return False, None

    req_years = extract_url_years(requested_url)
    fin_years = extract_url_years(final_url)

    chain_urls: list[str] = [requested_url]
    for hop in hops:
        for key in ('from_url', 'to_url'):
            u = hop.get(key)
            if isinstance(u, str) and u and u not in chain_urls:
                chain_urls.append(u)
    if final_url and final_url not in chain_urls:
        chain_urls.append(final_url)

    hop_years = []
    drifted_hops = []
    for u in chain_urls:
        u_host = _normalized_host_port(u)
        u_years = extract_url_years(u)
        hop_years.append({'url': u, 'years': u_years})
        if u_host == (req_host, req_port) and req_years and u_years and set(u_years) != set(req_years):
            drifted_hops.append({'url': u, 'years': u_years})

    if req_years and ((fin_years and set(fin_years) != set(req_years)) or drifted_hops):
        return True, {
            'requested_url': requested_url,
            'final_url': final_url,
            'requested_years': req_years,
            'final_years': fin_years,
            'hop_years': hop_years,
            'drifted_hops': drifted_hops,
            'reason': 'url_path_edition_year_changed_across_same_host_redirect',
        }

    # Check if e.g. /2027/cfp redirected to undated /cfp whose <title>/<h1> declares a stale year
    if req_years and not fin_years and raw_html:
        title_years = _extract_title_h1_years(raw_html)
        if title_years and not (set(title_years) & set(req_years)):
            return True, {
                'requested_url': requested_url,
                'final_url': final_url,
                'requested_years': req_years,
                'final_years': fin_years,
                'page_title_h1_years': title_years,
                'hop_years': hop_years,
                'reason': 'same_host_redirect_to_undated_url_with_stale_page_title_year',
            }

    return False, None


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
    elif kind in ('text/html', 'application/xhtml+xml', 'text/plain') or body.lstrip().startswith((b'<!DOCTYPE html', b'<html')):
        decoded = body.decode('utf-8', errors='replace')
        if kind == 'text/plain':
            text, status = decoded, 'plain_text_extracted'
        else:
            parser = PageText()
            parser.feed(decoded)
            parser.close()
            text, status = ' '.join(parser.parts), 'html_text_extracted'
    else:
        return '', 'unsupported_content_type'
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return '', 'no_extractable_text'
    if len(text) > MAX_TEXT_CHARS:
        return text[:MAX_TEXT_CHARS], status + '_truncated'
    return text, status


class _RecordingRedirectHandler(HTTPRedirectHandler):
    """Per-call redirect handler recording every hop and blocking non-HTTPS targets."""

    def __init__(self) -> None:
        super().__init__()
        self.hops: list[dict] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not valid_url(newurl):
            if fp is not None:
                try:
                    fp.close()
                except OSError:
                    pass
            raise _NonHttpsRedirectError('redirected_to_non_https_url')
        location = ''
        if headers is not None:
            location = headers.get('Location') or headers.get('URI') or ''
        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_req is not None:
            if not valid_url(new_req.full_url):
                raise _NonHttpsRedirectError('redirected_to_non_https_url')
            self.hops.append({
                'from_url': req.full_url,
                'status': int(code),
                'location': location or newurl,
                'to_url': new_req.full_url,
            })
        return new_req


def _maybe_decompress_gzip(body: bytes, content_encoding: str) -> bytes:
    encodings = [part.strip().lower() for part in (content_encoding or '').split(',') if part.strip()]
    if 'gzip' in encodings:
        try:
            body = gzip.decompress(body)
        except OSError as exc:
            raise RuntimeError('gzip_decompression_failed') from exc
        if len(body) > MAX_BYTES:
            raise RuntimeError('response_too_large')
    return body


def fetch(url, timeout=20, opener_factory=None, max_retries=2):
    headers = {
        'Accept': 'text/html, application/xhtml+xml, text/plain, application/pdf',
        'Accept-Encoding': 'gzip, identity',
        'User-Agent': _user_agent(),
    }
    delay = 1.0
    for attempt in range(max_retries + 1):
        handler = _RecordingRedirectHandler()
        opener = opener_factory(handler) if opener_factory is not None else build_opener(handler)
        request = Request(url, headers=headers)
        try:
            with opener.open(request, timeout=timeout) as response:
                final_url = response.geturl()
                if not valid_url(final_url):
                    raise RuntimeError('redirected_to_non_https_url')
                body = response.read(MAX_BYTES + 1)
                if len(body) > MAX_BYTES:
                    raise RuntimeError('response_too_large')
                body = _maybe_decompress_gzip(body, response.headers.get('Content-Encoding', ''))
                return {
                    'final_url': final_url,
                    'redirect_chain': list(handler.hops),
                    'content_type': response.headers.get('Content-Type', ''),
                    'body': body,
                    'http_status': response.status,
                }
        except _NonHttpsRedirectError as exc:
            raise RuntimeError('redirected_to_non_https_url') from exc
        except HTTPError as exc:
            if exc.code in (429, 503) and attempt < max_retries:
                retry_after = exc.headers.get('Retry-After') if exc.headers else None
                try:
                    pause = min(max(float(retry_after), 0.0), 30.0) if retry_after is not None else delay
                except ValueError:
                    pause = delay
                if pause > 0:
                    time.sleep(pause)
                delay = min(delay * 2.0, 30.0)
                continue
            if exc.code in (202, 403, 503):
                try:
                    err_body = exc.read(MAX_BYTES + 1)
                    if len(err_body) <= MAX_BYTES:
                        err_body = _maybe_decompress_gzip(err_body, exc.headers.get('Content-Encoding', '') if exc.headers else '')
                        decoded_err = err_body.decode('utf-8', errors='replace')
                        if _is_anubis_challenge(decoded_err):
                            return {
                                'final_url': exc.geturl() or url,
                                'redirect_chain': list(handler.hops),
                                'content_type': exc.headers.get('Content-Type', '') if exc.headers else 'text/html',
                                'body': err_body,
                                'http_status': exc.code,
                            }
                except (OSError, RuntimeError):
                    pass
            raise RuntimeError(f'http_{exc.code}') from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise RuntimeError('network_failure') from exc
    raise RuntimeError('http_429')


def _write_source_artifacts(
    artifacts_dir: str | Path | None,
    url: str,
    body: bytes,
    content_type: str,
    is_html_like: bool,
    text: str,
) -> tuple[str | None, str | None]:
    if not artifacts_dir:
        return None, None
    out_dir = Path(artifacts_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]
    kind = (content_type or '').split(';', 1)[0].strip().lower()
    if kind == 'application/pdf' or body.startswith(b'%PDF-'):
        ext = '.pdf'
    elif is_html_like:
        ext = '.html'
    elif kind == 'text/plain':
        ext = '.txt'
    else:
        ext = '.bin'
    raw_path = out_dir / f'{digest}_raw{ext}'
    raw_path.write_bytes(body)
    text_path_str: str | None = None
    if isinstance(text, str) and text:
        text_path = out_dir / f'{digest}_text.txt'
        text_path.write_text(text, encoding='utf-8')
        text_path_str = str(text_path)
    return str(raw_path), text_path_str


def capture_url(url, transport=fetch, artifacts_dir=None):
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

        raw_chain = response.get('redirect_chain')
        redirect_chain = _normalize_redirect_chain(url, final_url, raw_chain)

        # Cross-host check across ALL URLs in the chain (catches A -> B -> A bounces)
        req_hp = _normalized_host_port(url)
        chain_urls = [url, final_url]
        for hop in redirect_chain:
            if hop.get('from_url'):
                chain_urls.append(hop['from_url'])
            if hop.get('to_url'):
                chain_urls.append(hop['to_url'])
        redirected_diff_host = any(_normalized_host_port(u) != req_hp for u in chain_urls if u)

        content_type = response.get('content_type', '')
        kind = content_type.split(';', 1)[0].strip().lower()
        is_html_like = (
            kind in ('text/html', 'application/xhtml+xml')
            or body.lstrip().startswith((b'<!DOCTYPE html', b'<html'))
        )
        decoded_html = body.decode('utf-8', errors='replace') if is_html_like else ''

        http_status = response.get('http_status')
        if http_status in (202, 403, 503) and _is_anubis_challenge(decoded_html or body.decode('utf-8', errors='replace')):
            year_mismatch, year_details = detect_same_host_path_redirect_year_mismatch(
                url, final_url, redirect_chain, decoded_html
            )
            artifact_path, _ = _write_source_artifacts(artifacts_dir, url, body, content_type, is_html_like, '')
            snap = {
                'requested_url': url,
                'final_url': final_url,
                'fetched_at_utc': checked,
                'http_status': http_status,
                'content_type': content_type,
                'sha256': hashlib.sha256(body).hexdigest(),
                'bytes': len(body),
                'redirect_chain': redirect_chain,
                'redirected_to_different_host': redirected_diff_host,
                'same_host_path_redirect_year_mismatch': year_mismatch,
                'same_host_path_redirect_year_mismatch_details': year_details,
                'requested_url_years': extract_url_years(url),
                'final_url_years': extract_url_years(final_url),
                'js_rendered_suspected': False,
                'unverified_dynamic_page': False,
                'js_rendered_signals': ['anubis_challenge'],
                'extraction_status': 'bot_blocked_anubis',
                'text': '',
            }
            if artifact_path:
                snap['artifact_path'] = artifact_path
            return snap

        if http_status != 200:
            raise RuntimeError(f'http_{http_status}')

        text, status = extract_text(body, content_type)
        year_mismatch, year_details = detect_same_host_path_redirect_year_mismatch(
            url, final_url, redirect_chain, decoded_html
        )
        if is_html_like:
            js_suspected, js_signals = detect_js_rendered(decoded_html, text, status)
            structured_text, links = to_structured_text(decoded_html)
            cfp_signals = extract_cfp_signals(structured_text, decoded_html, links)
        else:
            js_suspected, js_signals = False, []
            structured_text, cfp_signals = None, None

        artifact_path, text_path = _write_source_artifacts(
            artifacts_dir, url, body, content_type, is_html_like, text
        )

        snapshot = {
            'requested_url': url,
            'final_url': final_url,
            'fetched_at_utc': checked,
            'http_status': 200,
            'content_type': content_type,
            'sha256': hashlib.sha256(body).hexdigest(),
            'bytes': len(body),
            'redirect_chain': redirect_chain,
            'redirected_to_different_host': redirected_diff_host,
            'same_host_path_redirect_year_mismatch': year_mismatch,
            'same_host_path_redirect_year_mismatch_details': year_details,
            'requested_url_years': extract_url_years(url),
            'final_url_years': extract_url_years(final_url),
            'js_rendered_suspected': js_suspected,
            'unverified_dynamic_page': js_suspected,
            'js_rendered_signals': js_signals,
            'extraction_status': status,
            'text': text,
        }
        if artifact_path:
            snapshot['artifact_path'] = artifact_path
        if text_path:
            snapshot['text_path'] = text_path
        if structured_text is not None:
            snapshot['structured_text'] = structured_text[:MAX_TEXT_CHARS]
        if cfp_signals is not None:
            snapshot['cfp_signals'] = cfp_signals
        return snapshot
    except (RuntimeError, KeyError, TypeError) as exc:
        return {
            'requested_url': url,
            'fetched_at_utc': checked,
            'redirect_chain': [],
            'redirected_to_different_host': False,
            'same_host_path_redirect_year_mismatch': False,
            'same_host_path_redirect_year_mismatch_details': None,
            'requested_url_years': extract_url_years(url),
            'final_url_years': [],
            'js_rendered_suspected': False,
            'unverified_dynamic_page': False,
            'js_rendered_signals': [],
            'extraction_status': 'fetch_failed',
            'error': str(exc),
            'text': '',
        }


def _dblp_fetch_json(url: str, transport=None, timeout: int = 20, max_retries: int = 2, min_interval: float = 0.0) -> dict:
    global _last_dblp_request_at
    if min_interval > 0 and transport is None:
        wait = min_interval - (time.monotonic() - _last_dblp_request_at)
        if wait > 0:
            time.sleep(wait)
    if transport is not None:
        try:
            resp = transport(url)
            status = resp.get('http_status', 200)
            body_bytes = resp.get('body', b'')
            if isinstance(body_bytes, str):
                body_str = body_bytes
            else:
                body_str = body_bytes.decode('utf-8', errors='replace')
        except RuntimeError as exc:
            err = str(exc)
            if err == 'http_429':
                return {'status': 'rate_limited', 'http_status': 429, 'error': err}
            return {'status': 'unreachable', 'http_status': None, 'error': err}
        except (OSError, TimeoutError, ValueError, TypeError) as exc:
            return {'status': 'unreachable', 'http_status': None, 'error': str(exc)}
    else:
        _last_dblp_request_at = time.monotonic()
        delay = 1.0
        resp = None
        for attempt in range(max_retries + 1):
            req = Request(url, headers={'User-Agent': _user_agent(), 'Accept': 'application/json'})
            opener = build_opener(_RecordingRedirectHandler())
            try:
                with opener.open(req, timeout=timeout) as response:
                    raw = response.read(MAX_BYTES + 1)
                    if len(raw) > MAX_BYTES:
                        return {'status': 'source_failed', 'http_status': response.status, 'error': 'response_too_large'}
                    raw = _maybe_decompress_gzip(raw, response.headers.get('Content-Encoding', ''))
                    status = response.status
                    body_str = raw.decode('utf-8', errors='replace')
                    resp = {'http_status': status, 'content_type': response.headers.get('Content-Type', '')}
                    break
            except HTTPError as exc:
                if exc.code in (429, 503) and attempt < max_retries:
                    retry_after = exc.headers.get('Retry-After') if exc.headers else None
                    try:
                        pause = min(max(float(retry_after), 0.0), 30.0) if retry_after is not None else delay
                    except ValueError:
                        pause = delay
                    if pause > 0:
                        time.sleep(pause)
                    delay = min(delay * 2.0, 30.0)
                    continue
                if exc.code == 429:
                    return {'status': 'rate_limited', 'http_status': 429, 'error': f'http_{exc.code}'}
                if exc.code in (202, 403, 503):
                    try:
                        err_body = exc.read(MAX_BYTES + 1)
                        if len(err_body) <= MAX_BYTES:
                            err_body = _maybe_decompress_gzip(
                                err_body,
                                exc.headers.get('Content-Encoding', '') if exc.headers else '',
                            )
                            err_text = err_body.decode('utf-8', errors='replace')
                            if _is_anubis_challenge(err_text):
                                return {
                                    'status': 'bot_blocked',
                                    'http_status': exc.code,
                                    'reason': 'anubis_challenge',
                                }
                    except (OSError, RuntimeError):
                        pass
                return {'status': 'source_failed', 'http_status': exc.code, 'error': f'http_{exc.code}'}
            except (URLError, TimeoutError, OSError) as exc:
                return {'status': 'unreachable', 'http_status': None, 'error': str(exc)}
            except (RuntimeError, _NonHttpsRedirectError) as exc:
                return {'status': 'source_failed', 'http_status': None, 'error': str(exc)}
        if resp is None:
            return {'status': 'rate_limited', 'http_status': 429, 'error': 'rate_limited'}

    if status == 202 or _is_anubis_challenge(body_str):
        return {
            'status': 'bot_blocked',
            'http_status': status,
            'reason': 'anubis_challenge',
        }
    if status == 429:
        return {'status': 'rate_limited', 'http_status': 429, 'error': 'http_429'}
    if status != 200:
        return {'status': 'source_failed', 'http_status': status, 'error': f'http_{status}'}
    try:
        data = json.loads(body_str)
    except json.JSONDecodeError as exc:
        if _is_anubis_challenge(body_str) or '<html' in body_str.lower():
            return {'status': 'bot_blocked', 'http_status': status, 'reason': 'non_json_html_challenge'}
        return {'status': 'source_failed', 'http_status': status, 'error': f'invalid_json: {exc}'}
    return {'status': 'ok', 'http_status': 200, 'data': data}


def lookup_dblp_venue(query: str, max_hits: int = 10, transport=None, timeout: int = 20, max_retries: int = 2) -> dict:
    """Resolve a venue name/acronym via DBLP without calling sys.exit() or input()."""
    if not isinstance(query, str) or not query.strip():
        return {'status': 'source_failed', 'query': query, 'error': 'empty_query', 'results': []}
    url = f"{DBLP_BASE}/venue/api?{urlencode({'q': query.strip(), 'format': 'json', 'h': max_hits})}"
    res = _dblp_fetch_json(url, transport=transport, timeout=timeout, max_retries=max_retries)
    if res['status'] != 'ok':
        out = {k: v for k, v in res.items() if k != 'data'}
        out.update({'query': query, 'results': []})
        return out
    body = res['data']
    result_obj = body.get('result') if isinstance(body, dict) else None
    hits_obj = result_obj.get('hits') if isinstance(result_obj, dict) else None
    if not isinstance(hits_obj, dict):
        return {'status': 'source_failed', 'http_status': 200, 'query': query, 'error': 'malformed_dblp_json', 'results': []}
    hits = hits_obj.get('hit', [])
    if isinstance(hits, dict):
        hits = [hits]
    elif not isinstance(hits, list):
        hits = []
    results = []
    for hit in hits:
        info = hit.get('info', {}) if isinstance(hit, dict) else {}
        if not isinstance(info, dict):
            continue
        v_url = info.get('url', '') or ''
        match = re.search(r'/db/((?:conf|journals|series)/[^/]+)', v_url) if isinstance(v_url, str) else None
        results.append({
            'venue': info.get('venue'),
            'acronym': info.get('acronym'),
            'type': info.get('type'),
            'dblp_key': match.group(1) if match else None,
            'url': v_url,
        })
    return {'status': 'ok', 'http_status': 200, 'query': query, 'results': results}


def lookup_dblp_toc_count(dblp_key: str, year: int, bht: str | None = None, transport=None, timeout: int = 20, max_retries: int = 2) -> dict:
    """Count papers in one year's DBLP proceedings TOC without calling sys.exit()."""
    if not isinstance(dblp_key, str) or not dblp_key.strip():
        return {'status': 'source_failed', 'dblp_key': dblp_key, 'year': year, 'paper_count': None, 'error': 'empty_dblp_key'}
    year_int = None
    if not isinstance(year, bool):
        try:
            year_int = int(year)
        except (TypeError, ValueError):
            year_int = None
    if bht:
        toc_bht = bht
    else:
        if year_int is None:
            return {'status': 'source_failed', 'dblp_key': dblp_key, 'year': year, 'paper_count': None, 'error': 'invalid_year'}
        base = dblp_key.rstrip('/').split('/')[-1]
        toc_bht = f'db/{dblp_key.strip("/")}/{base}{year_int}.bht'
    url = f"{DBLP_BASE}/publ/api?{urlencode({'q': f'toc:{toc_bht}:', 'format': 'json', 'h': 1})}"
    res = _dblp_fetch_json(url, transport=transport, timeout=timeout, max_retries=max_retries)
    if res['status'] != 'ok':
        out = {k: v for k, v in res.items() if k != 'data'}
        out.update({'dblp_key': dblp_key, 'year': year_int if year_int is not None else year, 'bht': toc_bht, 'paper_count': None})
        return out
    body = res['data']
    result_obj = body.get('result') if isinstance(body, dict) else None
    hits_obj = result_obj.get('hits') if isinstance(result_obj, dict) else None
    if not isinstance(hits_obj, dict):
        return {'status': 'source_failed', 'http_status': 200, 'dblp_key': dblp_key, 'year': year_int if year_int is not None else year, 'bht': toc_bht, 'paper_count': None, 'error': 'malformed_dblp_json'}
    try:
        total = int(hits_obj.get('@total', 0))
    except (TypeError, ValueError):
        return {'status': 'source_failed', 'http_status': 200, 'dblp_key': dblp_key, 'year': year_int if year_int is not None else year, 'bht': toc_bht, 'paper_count': None, 'error': 'malformed_dblp_json'}
    return {
        'status': 'ok',
        'http_status': 200,
        'dblp_key': dblp_key,
        'year': year_int if year_int is not None else year,
        'bht': toc_bht,
        'paper_count': total,
    }


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


def capture_dossier(dossier, transport=fetch, artifacts_dir=None):
    urls = urls_from_dossier(dossier)
    return {
        'format': 'research_scientist_venue_sources_v1',
        'captured_at_utc': datetime.now(timezone.utc).isoformat(),
        'sources': [capture_url(url, transport, artifacts_dir=artifacts_dir) for url in urls],
        'warning': (
            'A snapshot records returned text and a content hash, not official status, correct edition, '
            'track eligibility, date interpretation, complete fees, or currentness after capture. '
            'Inspect the original page/PDF and its context before recommending a venue.'
        ),
    }


def _truncate_str(value, limit: int) -> str | None:
    if value is None:
        return None
    s = str(value)
    return s if len(s) <= limit else s[: max(0, limit - 3)] + '...'


def _compact_dblp_summary(dblp_res: dict) -> dict:
    raw_results = dblp_res.get('results')
    results = raw_results if isinstance(raw_results, list) else []
    summary = {
        'status': dblp_res.get('status'),
        'query': _truncate_str(dblp_res.get('query'), 120),
        'result_count': len(results),
        'results': results[:5],
    }
    for opt_key in ('http_status', 'reason', 'error', 'toc_count'):
        if opt_key in dblp_res:
            val = dblp_res[opt_key]
            summary[opt_key] = _truncate_str(val, 160) if isinstance(val, str) else val
    return summary


def _compact_capture_summary(output: dict, bundle_path: str | None = None, artifacts_dir: str | None = None, has_dossier: bool = True) -> dict:
    if not has_dossier:
        compact = _compact_dblp_summary(output)
        if bundle_path:
            compact['bundle_path'] = bundle_path
        while len(json.dumps(compact, ensure_ascii=False).encode('utf-8')) > 3950 and compact.get('results'):
            compact['results'].pop()
            compact['results_truncated'] = True
        return compact

    raw_sources = output.get('sources')
    sources = raw_sources if isinstance(raw_sources, list) else []
    blocked_statuses = {
        'bot_blocked_anubis', 'fetch_failed', 'pdf_extractor_unavailable',
        'pdf_extraction_failed', 'unsupported_content_type', 'no_extractable_text',
    }
    blocked_count = sum(
        1 for s in sources if isinstance(s, dict) and (
            s.get('same_host_path_redirect_year_mismatch')
            or s.get('redirected_to_different_host')
            or s.get('js_rendered_suspected')
            or s.get('unverified_dynamic_page')
            or s.get('extraction_status') in blocked_statuses
        )
    )
    compact_sources = []
    for s in sources[:5]:
        if not isinstance(s, dict):
            continue
        text_val = s.get('text')
        raw_js_sigs = s.get('js_rendered_signals')
        js_sigs = [_truncate_str(sig, 80) for sig in raw_js_sigs[:5]] if isinstance(raw_js_sigs, list) else []
        entry = {
            'requested_url': _truncate_str(s.get('requested_url'), 240),
            'final_url': _truncate_str(s.get('final_url'), 240),
            'fetched_at_utc': s.get('fetched_at_utc'),
            'http_status': s.get('http_status'),
            'extraction_status': s.get('extraction_status'),
            'sha256': s.get('sha256'),
            'bytes': s.get('bytes'),
            'text_chars': len(text_val) if isinstance(text_val, str) else 0,
            'redirected_to_different_host': bool(s.get('redirected_to_different_host')),
            'same_host_path_redirect_year_mismatch': bool(s.get('same_host_path_redirect_year_mismatch')),
            'js_rendered_suspected': bool(s.get('js_rendered_suspected')),
            'unverified_dynamic_page': bool(s.get('unverified_dynamic_page')),
            'js_rendered_signals': js_sigs,
        }
        sigs = s.get('cfp_signals')
        if isinstance(sigs, dict):
            raw_deadlines = sigs.get('deadlines')
            deadlines_count = len(raw_deadlines) if isinstance(raw_deadlines, list) else 0
            raw_tz = sigs.get('timezones')
            if isinstance(raw_tz, (list, tuple, set)):
                tz_list = [_truncate_str(x, 32) for x in list(raw_tz)[:8]]
            elif isinstance(raw_tz, str) and raw_tz.strip():
                tz_list = [_truncate_str(raw_tz.strip(), 32)]
            else:
                tz_list = []
            raw_sub = sigs.get('submission_systems')
            if isinstance(raw_sub, dict):
                sub_keys = sorted(_truncate_str(k, 48) or '' for k in raw_sub.keys())[:8]
            elif isinstance(raw_sub, (list, tuple, set)):
                sub_keys = sorted(_truncate_str(k, 48) or '' for k in raw_sub)[:8]
            elif isinstance(raw_sub, str) and raw_sub.strip():
                sub_keys = [_truncate_str(raw_sub.strip(), 48) or '']
            else:
                sub_keys = []
            entry['cfp_signals_summary'] = {
                'deadlines_count': deadlines_count,
                'timezones': tz_list,
                'submission_systems': sub_keys,
            }
        if s.get('error'):
            entry['error'] = _truncate_str(s.get('error'), 160)
        if s.get('artifact_path'):
            entry['artifact_path'] = s['artifact_path']
        if s.get('text_path'):
            entry['text_path'] = s['text_path']
        compact_sources.append(entry)

    compact = {
        'format': output.get('format'),
        'captured_at_utc': output.get('captured_at_utc'),
        'source_count': len(sources),
        'blocked_count': blocked_count,
        'sources': compact_sources,
    }
    if len(sources) > len(compact_sources):
        compact['sources_truncated'] = True
    if bundle_path:
        compact['bundle_path'] = bundle_path
    if artifacts_dir:
        compact['artifacts_dir'] = artifacts_dir
    if 'dblp_lookup' in output and isinstance(output['dblp_lookup'], dict):
        compact['dblp_lookup'] = _compact_dblp_summary(output['dblp_lookup'])

    while len(json.dumps(compact, ensure_ascii=False).encode('utf-8')) > 3950 and compact['sources']:
        compact['sources'].pop()
        compact['sources_truncated'] = True
    if len(json.dumps(compact, ensure_ascii=False).encode('utf-8')) > 3950 and 'dblp_lookup' in compact:
        if isinstance(compact['dblp_lookup'], dict) and compact['dblp_lookup'].get('results'):
            compact['dblp_lookup']['results'] = []
            compact['dblp_lookup']['results_truncated'] = True
    return compact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dossier_json', nargs='?', help='Path to venue dossier JSON')
    parser.add_argument('--dblp-lookup', metavar='QUERY', help='Optional DBLP venue name/acronym lookup')
    parser.add_argument('--dblp-year', type=int, help='Optional proceedings year for DBLP TOC count')
    parser.add_argument('--out', metavar='BUNDLE_JSON', help='Write full JSON bundle/output to disk')
    parser.add_argument('--artifacts-dir', metavar='DIR', help='Write raw HTML/text payloads to disk under DIR')
    parser.add_argument('--compact', action='store_true', help='Print bounded compact summary to stdout')
    args = parser.parse_args()
    if not args.dossier_json and not args.dblp_lookup:
        print(json.dumps({'error': 'dossier_json or --dblp-lookup is required'}), file=sys.stderr)
        return 2
    try:
        output = {}
        if args.dossier_json:
            dossier = json.loads(Path(args.dossier_json).read_text(encoding='utf-8'))
            output = capture_dossier(dossier, artifacts_dir=args.artifacts_dir)
        if args.dblp_lookup:
            dblp_res = lookup_dblp_venue(args.dblp_lookup)
            if args.dblp_year is not None and dblp_res.get('status') == 'ok' and dblp_res.get('results'):
                first_key = next((r.get('dblp_key') for r in dblp_res['results'] if r.get('dblp_key')), None)
                if first_key:
                    dblp_res['toc_count'] = lookup_dblp_toc_count(first_key, args.dblp_year)
            if args.dossier_json:
                output['dblp_lookup'] = dblp_res
            else:
                output = dblp_res
        bundle_path_str = None
        if args.out:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(output, ensure_ascii=False), encoding='utf-8')
            bundle_path_str = str(out_path)
        elif args.compact:
            fd, tmp_name = tempfile.mkstemp(prefix='capture_venue_sources_', suffix='.json')
            with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                fh.write(json.dumps(output, ensure_ascii=False))
            bundle_path_str = tmp_name
        if args.compact:
            stdout_payload = _compact_capture_summary(
                output,
                bundle_path=bundle_path_str,
                artifacts_dir=str(Path(args.artifacts_dir)) if args.artifacts_dir else None,
                has_dossier=bool(args.dossier_json),
            )
        else:
            stdout_payload = output
        print(json.dumps(stdout_payload, ensure_ascii=False))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError, AttributeError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
