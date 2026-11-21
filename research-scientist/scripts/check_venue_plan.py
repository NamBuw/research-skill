#!/usr/bin/env python3
"""Check venue dossier arithmetic and time zones; source facts require review."""
import argparse
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

REQUIRED_MILESTONES = ('abstract_registration', 'full_paper')
REQUIRED_FEE_CATEGORIES = ('submission', 'publication', 'author_registration', 'overlength', 'tax')

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

def check(dossier):
    if not isinstance(dossier, dict):
        raise ValueError('dossier must be a JSON object')
    for key in ('venue', 'edition', 'track', 'official_cfp_url', 'checked_at', 'user_timezone', 'milestones', 'fees'):
        if key not in dossier:
            raise ValueError(f'missing {key}')
    for key in ('venue', 'edition', 'track', 'checked_at'):
        if not isinstance(dossier[key], str) or not dossier[key].strip():
            raise ValueError(f'blank {key}')
    if not isinstance(dossier['official_cfp_url'], str) or not dossier['official_cfp_url'].startswith('https://'):
        raise ValueError('official_cfp_url must be HTTPS')
    try:
        user_zone = ZoneInfo(dossier['user_timezone'])
    except (ZoneInfoNotFoundError, KeyError, TypeError) as exc:
        raise ValueError('invalid user_timezone') from exc
    milestones = dossier['milestones']
    if not isinstance(milestones, dict):
        raise ValueError('milestones must be an object')
    converted, warnings, parsed = {}, [], {}
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
    fees = dossier['fees']
    if not isinstance(fees, list):
        raise ValueError('fees must be a list')
    currency = dossier.get('currency')
    if not isinstance(currency, str) or len(currency) != 3 or not currency.isalpha():
        raise ValueError('currency must be a three-letter code')
    mandatory_total = 0
    missing_mandatory = []
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
    feasible = None if missing_mandatory or budget is None or 'budget_currency_unverified_or_mismatched' in warnings or 'presentation_mode_unverified' in warnings else mandatory_total <= budget
    return {'venue': dossier['venue'], 'edition': dossier['edition'], 'track': dossier['track'],
            'milestones_user_timezone': converted, 'mandatory_known_total': mandatory_total,
            'currency': currency.upper(), 'missing_mandatory_costs': missing_mandatory,
            'within_budget': feasible, 'warnings': warnings,
            'verification': 'Dates, CFP identity, fee categories, eligibility and source freshness are supplied claims, not verified by this script. Unknown costs prevent a positive affordability verdict.'}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dossier_json')
    args = parser.parse_args()
    try:
        print(json.dumps(check(json.loads(Path(args.dossier_json).read_text(encoding='utf-8')))))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        sys.exit(2)
