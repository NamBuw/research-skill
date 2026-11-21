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

def check(dossier, as_of=None):
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
            if not isinstance(fee.get('source_url'), str) or not fee['source_url'].startswith('https://') or fee_checked is None:
                unverified_fee_evidence.append(fee['name'])
            else:
                age = (as_of - fee_checked).total_seconds() / 86400
                fee_source_ages_days[fee['name']] = round(age, 1)
                if age < 0 or age > max_age:
                    stale_fee_evidence.append(fee['name'])
                elif amount is not None:
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
            schedule = {'status': 'start_already_passed_under_serial_assumption' if end < as_of.astimezone(user_zone) else 'start_not_yet_past_under_serial_assumption',
                        'buffer_days': plan['buffer_days'], 'tasks': latest,
                        'warning': 'Task durations and serial order are supplied assumptions; this does not establish scientific readiness or guarantee submission.'}
    return {'venue': dossier['venue'], 'edition': dossier['edition'], 'track': dossier['track'],
            'milestones_user_timezone': converted, 'mandatory_known_total': mandatory_total,
            'verified_known_lower_bound': verified_known_total,
            'currency': currency.upper(), 'missing_mandatory_costs': missing_mandatory,
            'unverified_fee_evidence': unverified_fee_evidence, 'stale_fee_evidence': stale_fee_evidence,
            'fee_source_ages_days': fee_source_ages_days, 'cfp_source_age_days': round(cfp_age_days, 1),
            'within_budget': feasible, 'warnings': warnings, 'backward_schedule': schedule,
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
