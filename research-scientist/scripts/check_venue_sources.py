#!/usr/bin/env python3
# Incorporates and adapts verification conventions aligned with
# research-paper-lifecycle-skills (Apache-2.0, Copyright 2026 Shaishav Maisuria,
# commit cf30d6452cc6fd0570dd760eb65696f4a3485398).
# Modified for research-scientist (M4_1): blocks same-host stale-year redirects,
# JS-rendered/unverified dynamic pages, missing/failed/stale/cross-host snapshots,
# and Anubis bot-blocked captures across all dossier CFP, mandatory fee, and
# evidence-claim URLs; adds F20 --compact and --out report externalization.
"""Match venue dossier quotes against captured official-source candidates.

Exact text matching is a provenance check, not a judgment that the URL is
official or that a date, fee, policy, or fit claim was interpreted correctly.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse

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


def _normalized(value):
    return re.sub(r'\s+', ' ', value).strip()


def _contains_exact_quote(text, quote):
    quote = _normalized(quote)
    if not quote:
        return False
    left = r'(?<!\w)' if quote[0].isalnum() else ''
    right = r'(?!\w)' if quote[-1].isalnum() else ''
    return re.search(left + re.escape(quote) + right, _normalized(text)) is not None


def _parse_time(value):
    if not isinstance(value, str):
        raise ValueError('snapshot time missing')
    date = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if date.utcoffset() is None:
        raise ValueError('snapshot time lacks timezone')
    return date


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


def _extract_url_years(url: str) -> list[int]:
    if not isinstance(url, str) or not url:
        return []
    parsed = urlparse(url)
    kept_params = []
    if parsed.query:
        for k, v in parse_qsl(parsed.query, keep_blank_values=True):
            kl = k.lower()
            if kl in NON_EDITION_QUERY_KEYS or kl.startswith('utm_'):
                continue
            kept_params.append((k, v))
    filtered_query = urlencode(kept_params)
    target = parsed.path + ('?' + filtered_query if filtered_query else '')
    target = re.sub(
        r'(?<!\d)(20[0-3]\d)[-/](?:0?[1-9]|1[0-2])[-/](?:0?[1-9]|[12]\d|3[01])(?!\d)',
        r'\1 ',
        target,
    )
    target = re.sub(
        r'(?<!\d)(?:0?[1-9]|1[0-2])[-/](?:0?[1-9]|[12]\d|3[01])(?!\d)',
        ' ',
        target,
    )
    target = re.sub(
        r'(?i)/(?:paper|papers|node|p|id|submission|submissions|track|page|vol|volume|v)/20[0-3]\d(?=/|$|\?)',
        '/ ',
        target,
    )
    target = re.sub(r'(?i)/v\d+(?=/|$|\?)', '/ ', target)
    target = re.sub(r'(?i)\b(?:paper|id|node|build|ver|version|rev)[-_]?20[0-3]\d\b', ' ', target)
    years = [int(m.group(1)) for m in re.finditer(r'(?<!\d)(20[0-3]\d)(?!\d)', target)]
    masked = re.sub(r'(?<!\d)20[0-3]\d(?!\d)', ' ', target)
    for m in re.finditer(r'(?<![a-z0-9])([a-z]{2,15})[-_]?([2-3]\d)(?!\d|[-/]\d{2})', masked, re.I):
        if m.group(1).lower() not in NON_YEAR_SLUG_PREFIXES:
            years.append(2000 + int(m.group(2)))
    return sorted(set(years))


def _edition_years(dossier: dict) -> list[int]:
    edition = dossier.get('edition')
    if not isinstance(edition, str):
        return []
    years = [int(m.group(1)) for m in re.finditer(r'(?<!\d)(20[0-3]\d)(?!\d)', edition)]
    masked = re.sub(r'(?<!\d)20[0-3]\d(?!\d)', ' ', edition)
    for m in re.finditer(r'(?<![a-z0-9])([a-z]{2,15})[-_\s]?([2-3]\d)(?!\d|[-/]\d{2})', masked, re.I):
        if m.group(1).lower() not in NON_YEAR_COMMON_WORDS:
            years.append(2000 + int(m.group(2)))
    return sorted(set(years))


def _edition_year(dossier: dict) -> int | None:
    years = _edition_years(dossier)
    return years[0] if years else None


def _extract_text_years(text: str) -> list[int]:
    if not isinstance(text, str) or not text:
        return []
    venue_years: list[int] = []
    for m in re.finditer(r'(?<![a-z0-9])([a-z]{2,15})[-_\s]?(20[0-3]\d)(?!\d)', text, re.I):
        if m.group(1).lower() not in NON_YEAR_COMMON_WORDS:
            venue_years.append(int(m.group(2)))
    masked = re.sub(r'(?<!\d)20[0-3]\d(?!\d)', ' ', text)
    for m in re.finditer(r'(?<![a-z0-9])([a-z]{2,15})[-_]?([2-3]\d)(?!\d|[-/]\d{2})', masked, re.I):
        if m.group(1).lower() not in NON_YEAR_SLUG_PREFIXES:
            venue_years.append(2000 + int(m.group(2)))
    for m in re.finditer(r'(?<![a-z0-9])([a-z]{2,15})\s+([2-3]\d)(?!\d|[-/]\d{2}|st\b|nd\b|rd\b|th\b|%)', masked, re.I):
        if m.group(1).lower() not in NON_YEAR_COMMON_WORDS:
            venue_years.append(2000 + int(m.group(2)))
    if venue_years:
        return sorted(set(venue_years))
    return sorted({int(m.group(1)) for m in re.finditer(r'(?<!\d)(20[0-3]\d)(?!\d)', text)})


def _is_different_host_redirect(snapshot: dict) -> bool:
    if snapshot.get('redirected_to_different_host'):
        return True
    req_url = snapshot.get('requested_url') or ''
    if not req_url:
        return False
    req_hp = _normalized_host_port(req_url)
    if not req_hp[0]:
        return False
    urls_to_check = []
    fin_url = snapshot.get('final_url') or ''
    if fin_url:
        urls_to_check.append(fin_url)
    for hop in snapshot.get('redirect_chain') or []:
        if isinstance(hop, dict):
            for key in ('from_url', 'to_url', 'location'):
                u = hop.get(key)
                if isinstance(u, str) and u:
                    urls_to_check.append(u)
        elif isinstance(hop, str) and hop:
            urls_to_check.append(hop)
    for u in urls_to_check:
        hp = _normalized_host_port(u)
        if hp[0] and hp != req_hp:
            return True
    return False


def _snapshot_year_mismatch(snapshot: dict, edition_year: int | list[int] | None) -> tuple[bool, dict | None]:
    if snapshot.get('same_host_path_redirect_year_mismatch'):
        return True, snapshot.get('same_host_path_redirect_year_mismatch_details')

    req_url = snapshot.get('requested_url') or ''
    fin_url = snapshot.get('final_url') or req_url
    if not req_url or not fin_url:
        return False, None

    if isinstance(edition_year, list):
        ed_years = edition_year
    elif isinstance(edition_year, int):
        ed_years = [edition_year]
    else:
        ed_years = []

    req_hp = _normalized_host_port(req_url)
    fin_hp = _normalized_host_port(fin_url)
    if not req_hp[0] or req_hp != fin_hp:
        return False, None

    req_years = _extract_url_years(req_url)
    stored_req = snapshot.get('requested_url_years')
    if isinstance(stored_req, list) and stored_req:
        req_years = sorted(set(req_years) | {y for y in stored_req if isinstance(y, int) and not isinstance(y, bool)})
    fin_years = _extract_url_years(fin_url)
    stored_fin = snapshot.get('final_url_years')
    if isinstance(stored_fin, list) and stored_fin:
        fin_years = sorted(set(fin_years) | {y for y in stored_fin if isinstance(y, int) and not isinstance(y, bool)})

    if ed_years and fin_years and not (set(ed_years) & set(fin_years)):
        return True, {
            'requested_url': req_url,
            'final_url': fin_url,
            'edition_years': ed_years,
            'final_years': fin_years,
            'reason': 'dossier_edition_year_conflicts_with_final_url',
        }

    chain = snapshot.get('redirect_chain') or []
    redirected = (fin_url != req_url) or bool(chain)
    if not redirected:
        return False, None

    chain_urls = [req_url, fin_url]
    for hop in chain:
        if isinstance(hop, dict):
            for key in ('from_url', 'to_url', 'location'):
                u = hop.get(key)
                if isinstance(u, str) and u and u not in chain_urls:
                    chain_urls.append(u)
        elif isinstance(hop, str) and hop not in chain_urls:
            chain_urls.append(hop)

    expected_years = set(req_years) if req_years else set(ed_years)
    drifted_hops = []
    for u in chain_urls:
        u_hp = _normalized_host_port(u)
        if u_hp == req_hp or (not u_hp[0] and u.startswith('/')):
            u_years = _extract_url_years(u)
            if expected_years and u_years and not (set(u_years) & expected_years):
                drifted_hops.append({'url': u, 'years': u_years})

    if expected_years and ((req_years and fin_years and set(fin_years) != set(req_years)) or drifted_hops):
        return True, {
            'requested_url': req_url,
            'final_url': fin_url,
            'requested_years': req_years,
            'final_years': fin_years,
            'edition_years': ed_years,
            'drifted_hops': drifted_hops,
            'reason': 'url_path_edition_year_changed_across_same_host_redirect',
        }

    if (req_years or ed_years) and not fin_years:
        text_years = _extract_text_years(snapshot.get('text') or '')
        expected_years = set(req_years) | set(ed_years)
        if text_years and not (set(text_years) & expected_years):
            return True, {
                'requested_url': req_url,
                'final_url': fin_url,
                'requested_years': req_years,
                'final_years': fin_years,
                'edition_years': ed_years,
                'snapshot_text_years': text_years,
                'reason': 'same_host_redirect_to_undated_url_with_conflicting_text_year',
            }

    return False, None


def _validate_bundle_snapshots(sources: list) -> None:
    for idx, snap in enumerate(sources):
        if not isinstance(snap, dict):
            raise ValueError(f'source snapshot at index {idx} must be an object')
        for url_field in ('requested_url', 'final_url'):
            val = snap.get(url_field)
            if val is not None and not isinstance(val, str):
                raise ValueError(f'source snapshot {idx} {url_field} must be a string')
        chain = snap.get('redirect_chain')
        if chain is not None:
            if not isinstance(chain, list) or not all(isinstance(hop, (dict, str)) for hop in chain):
                raise ValueError(f'source snapshot {idx} redirect_chain must be a list of objects or strings')
            for hop in chain:
                if isinstance(hop, dict):
                    for key in ('from_url', 'to_url', 'location'):
                        hv = hop.get(key)
                        if hv is not None and not isinstance(hv, str):
                            raise ValueError(f'source snapshot {idx} redirect_chain {key} must be a string')


def _field_value(dossier, field):
    if field in ('venue', 'edition', 'track', 'scope', 'eligibility', 'policy'):
        return dossier.get(field)
    if field.startswith('milestones.'):
        return (dossier.get('milestones') or {}).get(field.split('.', 1)[1])
    if field.startswith('fees.'):
        category = field.split('.', 1)[1]
        fees = dossier.get('fees', [])
        if not isinstance(fees, list):
            raise ValueError('fees must be a list')
        return next((fee.get('amount') for fee in fees
                     if isinstance(fee, dict) and fee.get('category') == category), None)
    return None


def _critical_fields(dossier):
    required = {'venue', 'edition', 'track'}
    milestones = dossier.get('milestones') or {}
    for field in ('abstract_registration', 'full_paper'):
        if milestones.get(field) is not None:
            required.add('milestones.' + field)
    fees = dossier.get('fees', [])
    if not isinstance(fees, list):
        raise ValueError('fees must be a list')
    for fee in fees:
        if isinstance(fee, dict) and fee.get('mandatory') is True and fee.get('amount') is not None:
            required.add('fees.' + str(fee.get('category')))
    for field in ('scope', 'eligibility', 'policy'):
        if dossier.get(field):
            required.add(field)
    return required


def check(dossier, bundle, as_of=None):
    if not isinstance(dossier, dict) or not isinstance(bundle, dict):
        raise ValueError('dossier and capture bundle must be objects')
    if bundle.get('format') != 'research_scientist_venue_sources_v1' or not isinstance(bundle.get('sources'), list):
        raise ValueError('invalid venue source bundle')
    _validate_bundle_snapshots(bundle['sources'])
    claims = dossier.get('evidence_claims', [])
    if not isinstance(claims, list):
        raise ValueError('evidence_claims must be a list')
    fees = dossier.get('fees', [])
    if not isinstance(fees, list):
        raise ValueError('fees must be a list')
    captures = {s.get('requested_url'): s for s in bundle['sources'] if isinstance(s, dict)}
    max_age = dossier.get('max_source_age_days', 30)
    if isinstance(max_age, bool) or not isinstance(max_age, int) or max_age < 0:
        raise ValueError('max_source_age_days must be a nonnegative integer')
    as_of = as_of or datetime.now(timezone.utc)
    if as_of.utcoffset() is None:
        raise ValueError('as_of must have timezone')

    edition_years = _edition_years(dossier)
    results = []
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            raise ValueError(f'invalid evidence claim at index {index}')
        field, url, quote = (claim.get(k) for k in ('field', 'source_url', 'quote'))
        if not all(isinstance(v, str) and v.strip() for v in (field, url, quote)):
            raise ValueError(f'evidence claim {index} needs field, source_url and quote')
        row = {'field': field, 'source_url': url, 'quote': quote, 'status': None}
        if _field_value(dossier, field) is None:
            row['status'] = 'claim_field_missing_or_unknown'
        elif url not in captures:
            row['status'] = 'source_snapshot_missing'
        else:
            snapshot = captures[url]
            row['snapshot_sha256'] = snapshot.get('sha256')
            row['snapshot_final_url'] = snapshot.get('final_url')
            row['fetched_at_utc'] = snapshot.get('fetched_at_utc')
            row['redirect_chain'] = snapshot.get('redirect_chain', [])
            year_mismatch, year_details = _snapshot_year_mismatch(snapshot, edition_years)
            is_dynamic = bool(snapshot.get('js_rendered_suspected') or snapshot.get('unverified_dynamic_page'))
            row['same_host_path_redirect_year_mismatch'] = year_mismatch
            row['same_host_path_redirect_year_mismatch_details'] = year_details
            row['js_rendered_suspected'] = bool(snapshot.get('js_rendered_suspected'))
            row['unverified_dynamic_page'] = is_dynamic

            ext_status = snapshot.get('extraction_status', '')
            if year_mismatch and ext_status != 'fetch_failed':
                row['status'] = 'same_host_redirect_year_mismatch_blocked'
            elif ext_status == 'bot_blocked_anubis':
                row['status'] = 'source_bot_blocked'
            elif is_dynamic and ext_status != 'fetch_failed':
                row['status'] = 'unverified_dynamic_page'
            elif ext_status in ('fetch_failed', 'pdf_extractor_unavailable', 'pdf_extraction_failed',
                                'unsupported_content_type', 'no_extractable_text') or not isinstance(snapshot.get('text'), str):
                row['status'] = 'source_text_unavailable'
            else:
                try:
                    age_days = (as_of - _parse_time(snapshot.get('fetched_at_utc'))).total_seconds() / 86400
                except ValueError:
                    age_days = None
                row['snapshot_age_days'] = round(age_days, 1) if age_days is not None else None
                if age_days is None or age_days < 0 or age_days > max_age:
                    row['status'] = 'source_snapshot_stale_or_undated'
                elif not _contains_exact_quote(snapshot['text'], quote):
                    row['status'] = 'quote_not_found_in_snapshot'
                elif _is_different_host_redirect(snapshot):
                    row['status'] = 'quote_found_redirect_host_review_required'
                else:
                    row['status'] = 'quote_found'
        results.append(row)

    # Audit ALL referenced URLs (official_cfp_url, mandatory fees[*].source_url, evidence_claims[*].source_url)
    # to close the silent empty-value loophole when amount/milestones are None or evidence_claims omits a URL.
    referenced_urls: list[str] = []
    if isinstance(dossier.get('official_cfp_url'), str) and dossier['official_cfp_url'].strip():
        referenced_urls.append(dossier['official_cfp_url'])
    for fee in dossier.get('fees', []):
        if isinstance(fee, dict) and fee.get('mandatory') is True and isinstance(fee.get('source_url'), str) and fee['source_url'].strip():
            referenced_urls.append(fee['source_url'])
    for claim in claims:
        if isinstance(claim, dict) and isinstance(claim.get('source_url'), str) and claim['source_url'].strip():
            referenced_urls.append(claim['source_url'])
    referenced_urls = list(dict.fromkeys(referenced_urls))

    blocking_source_issues: list[dict] = []
    seen_issues: set[tuple[str, str]] = set()

    def _add_issue(src_url: str, issue_name: str, **extra) -> None:
        key = (src_url, issue_name)
        if key not in seen_issues:
            seen_issues.add(key)
            entry = {'source_url': src_url, 'issue': issue_name}
            entry.update(extra)
            blocking_source_issues.append(entry)

    for url in referenced_urls:
        snapshot = captures.get(url)
        if snapshot is None:
            _add_issue(url, 'source_snapshot_missing')
            continue
        ext_status = snapshot.get('extraction_status', '')
        year_mismatch, year_details = _snapshot_year_mismatch(snapshot, edition_years)
        if year_mismatch and ext_status != 'fetch_failed':
            _add_issue(url, 'same_host_path_redirect_year_mismatch', details=year_details)
        if ext_status == 'bot_blocked_anubis':
            _add_issue(url, 'source_bot_blocked', http_status=snapshot.get('http_status'))
        is_dynamic = bool(snapshot.get('js_rendered_suspected') or snapshot.get('unverified_dynamic_page'))
        if is_dynamic and ext_status not in ('fetch_failed', 'bot_blocked_anubis'):
            _add_issue(url, 'unverified_dynamic_page', signals=snapshot.get('js_rendered_signals', []))
        if _is_different_host_redirect(snapshot) and ext_status != 'fetch_failed':
            _add_issue(url, 'redirected_to_different_host', final_url=snapshot.get('final_url'))
        if (
            ext_status in ('fetch_failed', 'pdf_extractor_unavailable', 'pdf_extraction_failed', 'unsupported_content_type')
            or (ext_status == 'no_extractable_text' and not is_dynamic)
            or not isinstance(snapshot.get('text'), str)
        ):
            _add_issue(url, 'source_text_unavailable', extraction_status=ext_status, error=snapshot.get('error'))
        elif ext_status != 'bot_blocked_anubis':
            try:
                age_days = (as_of - _parse_time(snapshot.get('fetched_at_utc'))).total_seconds() / 86400
            except ValueError:
                age_days = None
            if age_days is None or age_days < 0 or age_days > max_age:
                _add_issue(
                    url,
                    'source_snapshot_stale_or_undated',
                    fetched_at_utc=snapshot.get('fetched_at_utc'),
                    snapshot_age_days=round(age_days, 1) if age_days is not None else None,
                )

    matched = {row['field'] for row in results if row['status'] == 'quote_found'}
    critical_missing = sorted(_critical_fields(dossier) - matched)

    if blocking_source_issues:
        source_text_status = 'verification_blocked'
    elif not critical_missing:
        source_text_status = 'all_supplied_critical_quotes_found'
    else:
        source_text_status = 'critical_quote_coverage_incomplete'

    verification_passed = (
        not critical_missing
        and not blocking_source_issues
        and all(row['status'] == 'quote_found' for row in results)
    )

    return {
        'venue': dossier.get('venue'),
        'checked_at_utc': as_of.isoformat(),
        'claims': results,
        'critical_fields_without_matched_quote': critical_missing,
        'blocking_source_issues': blocking_source_issues,
        'verification_passed': verification_passed,
        'source_text_status': source_text_status,
        'warning': (
            'A matched quote verifies text presence in a captured response only. Inspect the original '
            'official page/PDF, edition, track, context, date meaning, fee applicability, and changes '
            'after capture. This check cannot establish venue fit or affordability.'
        ),
    }


def _truncate_str(value, limit: int) -> str:
    s = str(value or '')
    return s if len(s) <= limit else s[: max(0, limit - 3)] + '...'


def _compact_check_summary(result: dict, report_path: str | None = None) -> dict:
    claims_list = result.get('claims', [])
    by_status: dict[str, int] = {}
    failed_claims = []
    for c in claims_list:
        st = c.get('status') or 'unknown'
        by_status[st] = by_status.get(st, 0) + 1
        if st != 'quote_found':
            failed_claims.append({
                'field': _truncate_str(c.get('field'), 80),
                'source_url': _truncate_str(c.get('source_url'), 160),
                'status': _truncate_str(st, 64),
                'quote': _truncate_str(c.get('quote'), 80),
            })

    raw_issues = result.get('blocking_source_issues', [])
    compact_issues = []
    for issue in raw_issues[:10]:
        if not isinstance(issue, dict):
            continue
        item = {
            'source_url': _truncate_str(issue.get('source_url'), 160),
            'issue': _truncate_str(issue.get('issue'), 80),
        }
        if issue.get('extraction_status'):
            item['extraction_status'] = _truncate_str(issue['extraction_status'], 64)
        if issue.get('final_url'):
            item['final_url'] = _truncate_str(issue['final_url'], 160)
        if issue.get('error'):
            item['error'] = _truncate_str(issue['error'], 120)
        if isinstance(issue.get('signals'), list) and issue['signals']:
            item['signals'] = [_truncate_str(sig, 64) for sig in issue['signals'][:4]]
        compact_issues.append(item)

    crit_missing = result.get('critical_fields_without_matched_quote', [])
    summary = {
        'venue': _truncate_str(result.get('venue'), 120) if result.get('venue') is not None else None,
        'checked_at_utc': result.get('checked_at_utc'),
        'verification_passed': result.get('verification_passed'),
        'source_text_status': result.get('source_text_status'),
        'critical_fields_without_matched_quote': crit_missing[:20],
        'blocking_source_issues': compact_issues,
        'blocking_source_issues_total': len(raw_issues),
        'claim_counts': {
            'total': len(claims_list),
            'quote_found': by_status.get('quote_found', 0),
            'failed': len(failed_claims),
            'by_status': by_status,
        },
        'failed_claims': failed_claims[:10],
        'failed_claims_total': len(failed_claims),
    }
    if len(crit_missing) > 20:
        summary['critical_fields_total'] = len(crit_missing)
    if len(failed_claims) > 10:
        summary['failed_claims_truncated'] = True
    if len(raw_issues) > 10:
        summary['blocking_source_issues_truncated'] = True
    if report_path:
        summary['report_path'] = report_path

    while len(json.dumps(summary, ensure_ascii=False).encode('utf-8')) > 3950 and summary['failed_claims']:
        summary['failed_claims'].pop()
        summary['failed_claims_truncated'] = True
    while len(json.dumps(summary, ensure_ascii=False).encode('utf-8')) > 3950 and summary['blocking_source_issues']:
        summary['blocking_source_issues'].pop()
        summary['blocking_source_issues_truncated'] = True
    while len(json.dumps(summary, ensure_ascii=False).encode('utf-8')) > 3950 and summary['critical_fields_without_matched_quote']:
        summary['critical_fields_without_matched_quote'].pop()
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dossier_json')
    parser.add_argument('source_capture_json')
    parser.add_argument('--out', metavar='REPORT_JSON', help='Write full JSON verification report to disk')
    parser.add_argument('--compact', action='store_true', help='Print bounded compact summary to stdout')
    args = parser.parse_args()
    try:
        dossier = json.loads(Path(args.dossier_json).read_text(encoding='utf-8'))
        bundle = json.loads(Path(args.source_capture_json).read_text(encoding='utf-8'))
        result = check(dossier, bundle)
        report_path_str = None
        if args.out:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
            report_path_str = str(out_path)
        elif args.compact:
            fd, tmp_name = tempfile.mkstemp(prefix='check_venue_sources_', suffix='.json')
            with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                fh.write(json.dumps(result, ensure_ascii=False))
            report_path_str = tmp_name
        stdout_payload = _compact_check_summary(result, report_path=report_path_str) if args.compact else result
        print(json.dumps(stdout_payload, ensure_ascii=False))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError, AttributeError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2
    return 0 if result['verification_passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
