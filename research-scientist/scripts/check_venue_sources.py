#!/usr/bin/env python3
"""Match venue dossier quotes against captured official-source candidates.

Exact text matching is a provenance check, not a judgment that the URL is
official or that a date, fee, policy, or fit claim was interpreted correctly.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


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


def _field_value(dossier, field):
    if field in ('venue', 'edition', 'track', 'scope', 'eligibility', 'policy'):
        return dossier.get(field)
    if field.startswith('milestones.'):
        return (dossier.get('milestones') or {}).get(field.split('.', 1)[1])
    if field.startswith('fees.'):
        category = field.split('.', 1)[1]
        return next((fee.get('amount') for fee in dossier.get('fees', [])
                     if isinstance(fee, dict) and fee.get('category') == category), None)
    return None


def _critical_fields(dossier):
    required = {'venue', 'edition', 'track'}
    milestones = dossier.get('milestones') or {}
    for field in ('abstract_registration', 'full_paper'):
        if milestones.get(field) is not None:
            required.add('milestones.' + field)
    for fee in dossier.get('fees', []):
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
    claims = dossier.get('evidence_claims', [])
    if not isinstance(claims, list):
        raise ValueError('evidence_claims must be a list')
    captures = {s.get('requested_url'): s for s in bundle['sources'] if isinstance(s, dict)}
    max_age = dossier.get('max_source_age_days', 30)
    if isinstance(max_age, bool) or not isinstance(max_age, int) or max_age < 0:
        raise ValueError('max_source_age_days must be a nonnegative integer')
    as_of = as_of or datetime.now(timezone.utc)
    if as_of.utcoffset() is None:
        raise ValueError('as_of must have timezone')
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
            status = snapshot.get('extraction_status', '')
            if status in ('fetch_failed', 'pdf_extractor_unavailable', 'pdf_extraction_failed',
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
                elif snapshot.get('redirected_to_different_host'):
                    row['status'] = 'quote_found_redirect_host_review_required'
                else:
                    row['status'] = 'quote_found'
        results.append(row)
    matched = {row['field'] for row in results if row['status'] == 'quote_found'}
    critical_missing = sorted(_critical_fields(dossier) - matched)
    return {'venue': dossier.get('venue'), 'checked_at_utc': as_of.isoformat(),
            'claims': results, 'critical_fields_without_matched_quote': critical_missing,
            'source_text_status': 'all_supplied_critical_quotes_found' if not critical_missing else 'critical_quote_coverage_incomplete',
            'warning': ('A matched quote verifies text presence in a captured response only. Inspect the original '
                        'official page/PDF, edition, track, context, date meaning, fee applicability, and changes '
                        'after capture. This check cannot establish venue fit or affordability.')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dossier_json')
    parser.add_argument('source_capture_json')
    args = parser.parse_args()
    try:
        dossier = json.loads(Path(args.dossier_json).read_text(encoding='utf-8'))
        bundle = json.loads(Path(args.source_capture_json).read_text(encoding='utf-8'))
        print(json.dumps(check(dossier, bundle), ensure_ascii=False))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
