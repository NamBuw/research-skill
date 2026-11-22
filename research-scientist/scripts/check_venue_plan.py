#!/usr/bin/env python3
# Incorporates verification conventions aligned with research-paper-lifecycle-skills
# (Apache-2.0, Copyright 2026 Shaishav Maisuria,
#  commit cf30d6452cc6fd0570dd760eb65696f4a3485398).
# Modified for research-scientist (M4_1): adds optional --sources / source_bundle
# enforcement blocking affordability and backward-schedule readiness when CFP or
# mandatory fee URLs have same-host stale-year redirects, JS-rendered shells,
# cross-host redirects, or Anubis bot blocks; adds F20 --compact and --out.
"""Check venue dossier arithmetic and time zones; source facts require review."""
import argparse
import json
import math
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

REQUIRED_MILESTONES = ('abstract_registration', 'full_paper')
REQUIRED_FEE_CATEGORIES = ('submission', 'publication', 'author_registration', 'overlength', 'tax')

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


def parse_deadline(value):
    if not isinstance(value, str):
        raise ValueError('deadline must be an ISO timestamp with offset or AoE')
    if value.endswith(' AoE'):
        date = datetime.fromisoformat(value[:-4])
        if date.tzinfo is not None:
            raise ValueError('AoE timestamp must not also have an offset')
        return date.replace(tzinfo=timezone(timedelta(hours=-12)))
    date = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if date.utcoffset() is None:
        raise ValueError('deadline lacks a timezone or AoE')
    return date


def parse_checked_at(value):
    if not isinstance(value, str):
        raise ValueError('checked_at must be a timezone-aware ISO timestamp')
    try:
        checked = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('checked_at must be a timezone-aware ISO timestamp') from exc
    if checked.utcoffset() is None:
        raise ValueError('checked_at must include a timezone')
    return checked


def _normalized_host_port(url):
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


def _extract_url_years(url):
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


def _edition_years(dossier):
    edition = dossier.get('edition')
    if not isinstance(edition, str):
        return []
    years = [int(m.group(1)) for m in re.finditer(r'(?<!\d)(20[0-3]\d)(?!\d)', edition)]
    masked = re.sub(r'(?<!\d)20[0-3]\d(?!\d)', ' ', edition)
    for m in re.finditer(r'(?<![a-z0-9])([a-z]{2,15})[-_\s]?([2-3]\d)(?!\d|[-/]\d{2})', masked, re.I):
        if m.group(1).lower() not in NON_YEAR_COMMON_WORDS:
            years.append(2000 + int(m.group(2)))
    return sorted(set(years))


def _edition_year(dossier):
    years = _edition_years(dossier)
    return years[0] if years else None


def _extract_text_years(text):
    if not isinstance(text, str) or not text:
        return []
    venue_years = []
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


def _is_different_host_redirect(snapshot):
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


def _snapshot_year_mismatch(snapshot, edition_year):
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
    if fin_url == req_url and not chain:
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
    drifted = []
    for u in chain_urls:
        u_hp = _normalized_host_port(u)
        if u_hp == req_hp or (not u_hp[0] and u.startswith('/')):
            uy = _extract_url_years(u)
            if expected_years and uy and not (set(uy) & expected_years):
                drifted.append({'url': u, 'years': uy})
    if expected_years and ((req_years and fin_years and set(fin_years) != set(req_years)) or drifted):
        return True, {
            'requested_url': req_url,
            'final_url': fin_url,
            'requested_years': req_years,
            'final_years': fin_years,
            'edition_years': ed_years,
            'drifted_hops': drifted,
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


def _validate_bundle_snapshots(sources):
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


def _inspect_snapshot_issues(snapshot, edition_year, as_of=None, max_age=None):
    """Return list of (issue_code, detail_dict) for a captured source snapshot."""
    issues = []
    ext_status = snapshot.get('extraction_status', '')
    year_mismatch, year_details = _snapshot_year_mismatch(snapshot, edition_year)
    if year_mismatch and ext_status != 'fetch_failed':
        issues.append(('redirect_year_mismatch', {'details': year_details}))
    if ext_status == 'bot_blocked_anubis':
        issues.append(('bot_blocked', {'http_status': snapshot.get('http_status')}))
    elif (snapshot.get('js_rendered_suspected') or snapshot.get('unverified_dynamic_page')) and ext_status != 'fetch_failed':
        issues.append(('unverified_dynamic_page', {'signals': snapshot.get('js_rendered_signals', [])}))
    if _is_different_host_redirect(snapshot) and ext_status != 'fetch_failed':
        issues.append(('redirected_to_different_host', {'final_url': snapshot.get('final_url')}))
    failed_statuses = ('fetch_failed', 'pdf_extractor_unavailable', 'pdf_extraction_failed',
                       'unsupported_content_type', 'no_extractable_text')
    if (
        ext_status in failed_statuses
        or (ext_status != 'bot_blocked_anubis' and not isinstance(snapshot.get('text'), str))
    ):
        issues.append(('fetch_failed', {'extraction_status': ext_status, 'error': snapshot.get('error')}))
    elif ext_status != 'bot_blocked_anubis' and as_of is not None and max_age is not None:
        try:
            age_days = (as_of - parse_checked_at(snapshot.get('fetched_at_utc'))).total_seconds() / 86400
        except ValueError:
            age_days = None
        if age_days is None or age_days < 0 or age_days > max_age:
            issues.append((
                'source_snapshot_stale_or_undated',
                {
                    'fetched_at_utc': snapshot.get('fetched_at_utc'),
                    'snapshot_age_days': round(age_days, 1) if age_days is not None else None,
                },
            ))
    return issues


def check(dossier, as_of=None, source_bundle=None):
    if not isinstance(dossier, dict):
        raise ValueError('dossier must be a JSON object')
    for key in ('venue', 'edition', 'track', 'official_cfp_url', 'checked_at', 'user_timezone', 'milestones', 'fees'):
        if key not in dossier:
            raise ValueError(f'missing {key}')
    for key in ('venue', 'edition', 'track', 'checked_at'):
        if not isinstance(dossier[key], str) or not dossier[key].strip():
            raise ValueError(f'blank {key}')
    checked = parse_checked_at(dossier['checked_at'])
    as_of = as_of or datetime.now(timezone.utc)
    if as_of.utcoffset() is None:
        raise ValueError('as_of must include a timezone')
    max_age = dossier.get('max_source_age_days', 30)
    if isinstance(max_age, bool) or not isinstance(max_age, int) or max_age < 0:
        raise ValueError('max_source_age_days must be a nonnegative integer')
    if not isinstance(dossier['official_cfp_url'], str) or not dossier['official_cfp_url'].startswith('https://'):
        raise ValueError('official_cfp_url must be HTTPS')
    try:
        user_zone = ZoneInfo(dossier['user_timezone'])
    except (ZoneInfoNotFoundError, KeyError, TypeError) as exc:
        raise ValueError('invalid user_timezone') from exc

    captures = None
    if source_bundle is not None:
        if (not isinstance(source_bundle, dict)
                or source_bundle.get('format') != 'research_scientist_venue_sources_v1'
                or not isinstance(source_bundle.get('sources'), list)):
            raise ValueError('invalid venue source bundle')
        _validate_bundle_snapshots(source_bundle['sources'])
        captures = {s.get('requested_url'): s for s in source_bundle['sources'] if isinstance(s, dict)}

    milestones = dossier['milestones']
    if not isinstance(milestones, dict):
        raise ValueError('milestones must be an object')
    converted, warnings, parsed = {}, [], {}
    cfp_age_days = (as_of - checked).total_seconds() / 86400
    if cfp_age_days < 0:
        warnings.append('cfp_checked_at_in_future')
    elif cfp_age_days > max_age:
        warnings.append('cfp_source_recheck_needed')
    for name, value in milestones.items():
        if value is None:
            converted[name] = None
            continue
        date = parse_deadline(value)
        parsed[name] = date
        converted[name] = date.astimezone(user_zone).isoformat()
    for name in REQUIRED_MILESTONES:
        if name not in milestones or milestones[name] is None:
            warnings.append(f'{name}_unknown')
    if all(name in parsed for name in REQUIRED_MILESTONES) and parsed['abstract_registration'] > parsed['full_paper']:
        warnings.append('abstract_deadline_after_full_paper; verify official CFP')
    for name in REQUIRED_MILESTONES:
        if name in parsed and parsed[name] < as_of:
            warnings.append(f'{name}_deadline_already_passed')

    edition_year = _edition_years(dossier)
    source_issues = []

    # Check official_cfp_url source flags (inline or via source_bundle)
    cfp_blocked = False
    if dossier.get('same_host_path_redirect_year_mismatch'):
        cfp_blocked = True
        warnings.append('cfp_source_redirect_year_mismatch')
        source_issues.append({'scope': 'official_cfp', 'source_url': dossier['official_cfp_url'],
                              'issue': 'same_host_path_redirect_year_mismatch'})
    if dossier.get('js_rendered_suspected') or dossier.get('unverified_dynamic_page'):
        cfp_blocked = True
        warnings.append('cfp_source_unverified_dynamic_page')
        source_issues.append({'scope': 'official_cfp', 'source_url': dossier['official_cfp_url'],
                              'issue': 'unverified_dynamic_page'})

    if captures is not None:
        cfp_snap = captures.get(dossier['official_cfp_url'])
        if cfp_snap is None:
            cfp_blocked = True
            warnings.append('cfp_source_snapshot_missing')
            source_issues.append({'scope': 'official_cfp', 'source_url': dossier['official_cfp_url'],
                                  'issue': 'source_snapshot_missing'})
        else:
            snap_issues = _inspect_snapshot_issues(cfp_snap, edition_year, as_of=as_of, max_age=max_age)
            for code, extra in snap_issues:
                cfp_blocked = True
                if code == 'redirect_year_mismatch':
                    warnings.append('cfp_source_redirect_year_mismatch')
                    issue_name = 'same_host_path_redirect_year_mismatch'
                elif code == 'unverified_dynamic_page':
                    warnings.append('cfp_source_unverified_dynamic_page')
                    issue_name = 'unverified_dynamic_page'
                elif code == 'redirected_to_different_host':
                    warnings.append('cfp_source_redirected_to_different_host')
                    issue_name = 'redirected_to_different_host'
                elif code == 'bot_blocked':
                    warnings.append('cfp_source_bot_blocked')
                    issue_name = 'source_bot_blocked'
                elif code == 'source_snapshot_stale_or_undated':
                    warnings.append('cfp_source_snapshot_stale_or_undated')
                    issue_name = 'source_snapshot_stale_or_undated'
                else:
                    warnings.append('cfp_source_fetch_failed')
                    issue_name = 'fetch_failed'
                entry = {'scope': 'official_cfp', 'source_url': dossier['official_cfp_url'], 'issue': issue_name}
                entry.update(extra)
                source_issues.append(entry)
        cfp_verified = not cfp_blocked
    else:
        cfp_verified = False

    fees = dossier['fees']
    if not isinstance(fees, list):
        raise ValueError('fees must be a list')
    currency = dossier.get('currency')
    if not isinstance(currency, str) or len(currency) != 3 or not currency.isalpha():
        raise ValueError('currency must be a three-letter code')
    mandatory_total = 0
    verified_known_total = 0
    missing_mandatory = []
    unverified_fee_evidence = []
    fee_source_ages_days = {}
    stale_fee_evidence = []
    seen_categories = set()
    for index, fee in enumerate(fees):
        if not isinstance(fee, dict) or not isinstance(fee.get('name'), str) or type(fee.get('mandatory')) is not bool:
            raise ValueError(f'invalid fee at index {index}')
        category = fee.get('category')
        if not isinstance(category, str) or not category or category in seen_categories:
            raise ValueError(f'missing or duplicate fee category at index {index}')
        seen_categories.add(category)
        amount = fee.get('amount')
        if amount is not None and (isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount < 0):
            raise ValueError(f'invalid fee amount at index {index}')
        if fee['mandatory']:
            if amount is None:
                missing_mandatory.append(fee['name'])
            else:
                mandatory_total += amount
            fee_checked_at = fee.get('checked_at')
            try:
                fee_checked = parse_checked_at(fee_checked_at)
            except ValueError:
                fee_checked = None

            fee_source_blocked = False
            fee_source_stale_snapshot = False
            if fee.get('same_host_path_redirect_year_mismatch'):
                fee_source_blocked = True
                warnings.append(f"fee_source_redirect_year_mismatch:{fee['name']}")
                source_issues.append({'scope': 'fee', 'fee_name': fee['name'], 'source_url': fee.get('source_url'),
                                      'issue': 'same_host_path_redirect_year_mismatch'})
            if fee.get('js_rendered_suspected') or fee.get('unverified_dynamic_page'):
                fee_source_blocked = True
                warnings.append(f"fee_source_unverified_dynamic_page:{fee['name']}")
                source_issues.append({'scope': 'fee', 'fee_name': fee['name'], 'source_url': fee.get('source_url'),
                                      'issue': 'unverified_dynamic_page'})
            if captures is not None and isinstance(fee.get('source_url'), str) and fee['source_url'].startswith('https://'):
                fee_snap = captures.get(fee['source_url'])
                if fee_snap is None:
                    fee_source_blocked = True
                    warnings.append(f"fee_source_snapshot_missing:{fee['name']}")
                    source_issues.append({'scope': 'fee', 'fee_name': fee['name'], 'source_url': fee['source_url'],
                                          'issue': 'source_snapshot_missing'})
                else:
                    for code, extra in _inspect_snapshot_issues(fee_snap, edition_year, as_of=as_of, max_age=max_age):
                        if code == 'source_snapshot_stale_or_undated':
                            fee_source_stale_snapshot = True
                            warnings.append(f"fee_source_snapshot_stale_or_undated:{fee['name']}")
                            issue_name = 'source_snapshot_stale_or_undated'
                        else:
                            fee_source_blocked = True
                            if code == 'redirect_year_mismatch':
                                warnings.append(f"fee_source_redirect_year_mismatch:{fee['name']}")
                                issue_name = 'same_host_path_redirect_year_mismatch'
                            elif code == 'unverified_dynamic_page':
                                warnings.append(f"fee_source_unverified_dynamic_page:{fee['name']}")
                                issue_name = 'unverified_dynamic_page'
                            elif code == 'redirected_to_different_host':
                                warnings.append(f"fee_source_redirected_to_different_host:{fee['name']}")
                                issue_name = 'redirected_to_different_host'
                            elif code == 'bot_blocked':
                                warnings.append(f"fee_source_bot_blocked:{fee['name']}")
                                issue_name = 'source_bot_blocked'
                            else:
                                warnings.append(f"fee_source_fetch_failed:{fee['name']}")
                                issue_name = 'fetch_failed'
                        entry = {'scope': 'fee', 'fee_name': fee['name'], 'source_url': fee['source_url'], 'issue': issue_name}
                        entry.update(extra)
                        source_issues.append(entry)

            if not isinstance(fee.get('source_url'), str) or not fee['source_url'].startswith('https://') or fee_checked is None:
                unverified_fee_evidence.append(fee['name'])
                if fee_source_stale_snapshot:
                    stale_fee_evidence.append(fee['name'])
            else:
                age = (as_of - fee_checked).total_seconds() / 86400
                fee_source_ages_days[fee['name']] = round(age, 1)
                if fee_source_blocked:
                    unverified_fee_evidence.append(fee['name'])
                if age < 0 or age > max_age or fee_source_stale_snapshot:
                    stale_fee_evidence.append(fee['name'])
                elif not fee_source_blocked and amount is not None:
                    verified_known_total += amount

    budget = dossier.get('budget')
    if budget is not None and (isinstance(budget, bool) or not isinstance(budget, (int, float)) or not math.isfinite(budget) or budget < 0):
        raise ValueError('invalid budget')
    missing_mandatory.extend(f'missing category: {category}' for category in REQUIRED_FEE_CATEGORIES if category not in seen_categories)
    if dossier.get('presentation_mode') == 'in_person':
        missing_mandatory.extend(f'missing category: {category}' for category in ('travel', 'visa', 'lodging', 'local_transport') if category not in seen_categories)
    elif dossier.get('presentation_mode') not in ('online', 'not_applicable'):
        warnings.append('presentation_mode_unverified')
    if dossier.get('budget_currency') != currency:
        warnings.append('budget_currency_unverified_or_mismatched')
    comparison_possible = budget is not None and 'budget_currency_unverified_or_mismatched' not in warnings and 'presentation_mode_unverified' not in warnings
    if comparison_possible and verified_known_total > budget:
        feasible = False
    elif missing_mandatory or unverified_fee_evidence or stale_fee_evidence or not comparison_possible:
        feasible = None
    else:
        feasible = True
    schedule = None
    plan = dossier.get('work_plan')
    if plan is not None:
        if not isinstance(plan, dict) or not isinstance(plan.get('tasks'), list) or not isinstance(plan.get('buffer_days'), int) or isinstance(plan['buffer_days'], bool) or plan['buffer_days'] < 0:
            raise ValueError('work_plan needs ordered tasks and nonnegative integer buffer_days')
        if 'full_paper' not in parsed:
            schedule = {'status': 'deadline_unknown', 'tasks': [], 'warning': 'A work plan cannot be dated without a verified full-paper deadline.'}
        else:
            end = parsed['full_paper'].astimezone(user_zone) - timedelta(days=plan['buffer_days'])
            latest = []
            for item in reversed(plan['tasks']):
                if not isinstance(item, dict) or not isinstance(item.get('name'), str) or not item['name'].strip() or not isinstance(item.get('days'), int) or isinstance(item['days'], bool) or item['days'] < 0:
                    raise ValueError('each work_plan task needs a name and nonnegative integer days')
                start = end - timedelta(days=item['days'])
                latest.append({'name': item['name'], 'days': item['days'], 'latest_start_local': start.isoformat(), 'latest_finish_local': end.isoformat()})
                end = start
            latest.reverse()
            schedule_status = 'start_already_passed_under_serial_assumption' if end < as_of.astimezone(user_zone) else 'start_not_yet_past_under_serial_assumption'
            if cfp_blocked:
                schedule_status = 'cfp_source_unverified_or_year_mismatch'
            schedule = {'status': schedule_status,
                        'buffer_days': plan['buffer_days'], 'tasks': latest,
                        'warning': 'Task durations and serial order are supplied assumptions; this does not establish scientific readiness or guarantee submission.'}
    return {'venue': dossier['venue'], 'edition': dossier['edition'], 'track': dossier['track'],
            'milestones_user_timezone': converted, 'mandatory_known_total': mandatory_total,
            'verified_known_lower_bound': verified_known_total,
            'currency': currency.upper(), 'missing_mandatory_costs': missing_mandatory,
            'unverified_fee_evidence': unverified_fee_evidence, 'stale_fee_evidence': stale_fee_evidence,
            'fee_source_ages_days': fee_source_ages_days, 'cfp_source_age_days': round(cfp_age_days, 1),
            'within_budget': feasible, 'warnings': warnings, 'backward_schedule': schedule,
            'cfp_verified': cfp_verified, 'source_issues': source_issues,
            'verification': 'Dates, CFP identity, fee categories, eligibility and source freshness are supplied claims, not verified by this script. Unknown costs prevent a positive affordability verdict.'}


def _truncate_str(value, limit):
    s = str(value or '')
    return s if len(s) <= limit else s[: max(0, limit - 3)] + '...'


def _compact_plan_summary(result, report_path=None):
    warnings_list = result.get('warnings', [])
    raw_issues = result.get('source_issues', [])
    compact_issues = []
    for issue in raw_issues[:10]:
        if not isinstance(issue, dict):
            continue
        item = {
            'scope': _truncate_str(issue.get('scope'), 32),
            'source_url': _truncate_str(issue.get('source_url'), 160),
            'issue': _truncate_str(issue.get('issue'), 80),
        }
        if issue.get('fee_name'):
            item['fee_name'] = _truncate_str(issue['fee_name'], 64)
        if issue.get('final_url'):
            item['final_url'] = _truncate_str(issue['final_url'], 160)
        if issue.get('extraction_status'):
            item['extraction_status'] = _truncate_str(issue['extraction_status'], 64)
        compact_issues.append(item)

    summary = {
        'venue': _truncate_str(result.get('venue'), 120) if result.get('venue') is not None else None,
        'edition': _truncate_str(result.get('edition'), 64) if result.get('edition') is not None else None,
        'track': _truncate_str(result.get('track'), 80) if result.get('track') is not None else None,
        'within_budget': result.get('within_budget'),
        'mandatory_known_total': result.get('mandatory_known_total'),
        'verified_known_lower_bound': result.get('verified_known_lower_bound'),
        'currency': result.get('currency'),
        'cfp_verified': result.get('cfp_verified'),
        'source_issues': compact_issues,
        'source_issues_total': len(raw_issues),
        'missing_mandatory_costs': result.get('missing_mandatory_costs', [])[:10],
        'unverified_fee_evidence': result.get('unverified_fee_evidence', [])[:10],
        'stale_fee_evidence': result.get('stale_fee_evidence', [])[:10],
        'schedule_status': (result.get('backward_schedule') or {}).get('status'),
        'warnings': [_truncate_str(w, 100) for w in warnings_list[:10]],
    }
    if len(warnings_list) > 10:
        summary['warnings_total'] = len(warnings_list)
    if len(raw_issues) > 10:
        summary['source_issues_truncated'] = True
    if report_path:
        summary['report_path'] = report_path
    while len(json.dumps(summary, ensure_ascii=False).encode('utf-8')) > 3950 and summary['source_issues']:
        summary['source_issues'].pop()
        summary['source_issues_truncated'] = True
    while len(json.dumps(summary, ensure_ascii=False).encode('utf-8')) > 3950 and summary['warnings']:
        summary['warnings'].pop()
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dossier_json')
    parser.add_argument('--sources', help='Optional capture_venue_sources.py JSON bundle to enforce redirect/JS verification')
    parser.add_argument('--out', metavar='REPORT_JSON', help='Write full JSON plan report to disk')
    parser.add_argument('--compact', action='store_true', help='Print bounded compact summary to stdout')
    args = parser.parse_args()
    try:
        dossier_obj = json.loads(Path(args.dossier_json).read_text(encoding='utf-8'))
        bundle_obj = json.loads(Path(args.sources).read_text(encoding='utf-8')) if args.sources else None
        result = check(dossier_obj, source_bundle=bundle_obj)
        report_path_str = None
        if args.out:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
            report_path_str = str(out_path)
        elif args.compact:
            fd, tmp_name = tempfile.mkstemp(prefix='check_venue_plan_', suffix='.json')
            with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                fh.write(json.dumps(result, ensure_ascii=False))
            report_path_str = tmp_name
        stdout_payload = _compact_plan_summary(result, report_path=report_path_str) if args.compact else result
        print(json.dumps(stdout_payload, ensure_ascii=False))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError, AttributeError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2
    return 1 if result['source_issues'] else 0


if __name__ == '__main__':
    sys.exit(main())
