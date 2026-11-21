#!/usr/bin/env python3
"""Check scorecard completeness and ranking sensitivity under declared weights."""
import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

from score_math import DIMENSIONS, score


def compare(document):
    if not isinstance(document, dict) or not isinstance(document.get('profiles'), list) or len(document['profiles']) < 2:
        raise ValueError('at least two profiles are required')
    scenarios = document.get('weight_scenarios')
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError('weight_scenarios must be a nonempty list')
    issues = []
    profiles = document['profiles']
    ids = set()
    for item in profiles:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id'].strip():
            raise ValueError('each profile needs a nonblank id')
        pid = item['id']
        if pid in ids:
            issues.append(f'duplicate_profile:{pid}')
        ids.add(pid)
        if item.get('reading_basis') != 'full_text':
            issues.append(f'full_text_not_confirmed:{pid}')
        if not isinstance(item.get('closest_work'), list) or not item['closest_work']:
            issues.append(f'closest_work_missing:{pid}')
        elif any(not isinstance(x, str) or not x.strip() for x in item['closest_work']):
            issues.append(f'invalid_closest_work:{pid}')
        locators = item.get('evidence_locators')
        if not isinstance(locators, dict) or set(locators) != set(DIMENSIONS):
            issues.append(f'evidence_locators_incomplete:{pid}')
        else:
            for dimension in DIMENSIONS:
                value = locators[dimension]
                if not isinstance(value, list) or not value or any(not isinstance(x, str) or not x.strip() for x in value):
                    issues.append(f'missing_locator:{pid}:{dimension}')
    if issues:
        return {'status': 'not_comparable', 'issues': sorted(set(issues)), 'rankings': [],
                'warning': 'This structural checker cannot validate the locators, closest-work equivalence, or ratings.'}
    rankings = []
    for index, weights in enumerate(scenarios):
        results = []
        for item in profiles:
            calculated = score({'weights': weights, 'ratings': item['ratings']})
            if calculated['status'] != 'calculated':
                issues.append(f'missing_rating:{item["id"]}')
            else:
                results.append((item['id'], calculated['weighted_unrounded']))
        if issues:
            continue
        ordered = sorted(results, key=lambda x: (-Decimal(x[1]), x[0]))
        rankings.append({'scenario': index + 1,
                         'ordered': [{'id': pid, 'weighted_unrounded': raw} for pid, raw in ordered],
                         'top_tied': len(ordered) > 1 and ordered[0][1] == ordered[1][1]})
    if issues:
        return {'status': 'not_comparable', 'issues': sorted(set(issues)), 'rankings': [],
                'warning': 'Missing ratings cannot be silently reweighted.'}
    leaders = {tuple(row['id'] for row in ranking['ordered'] if row['weighted_unrounded'] == ranking['ordered'][0]['weighted_unrounded']) for ranking in rankings}
    return {'status': 'structurally_comparable', 'rankings': rankings,
            'ranking_sensitivity': 'stable_top_within_supplied_weights' if len(leaders) == 1 else 'top_changes_across_supplied_weights',
            'warning': 'No source text or rating is verified. Stability applies only to the supplied weight scenarios, not all defensible weights or reviewer judgments.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scorecards_json')
    args = parser.parse_args()
    try:
        print(json.dumps(compare(json.loads(Path(args.scorecards_json).read_text(encoding='utf-8')))))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        sys.exit(2)
