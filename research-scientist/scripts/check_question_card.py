#!/usr/bin/env python3
"""Check a structured research-question card for omitted decision-critical fields.

A passing report is structural, not scientific validation.
"""
import argparse
import json
import re
import sys
from pathlib import Path

REQUIRED = (
    'question', 'question_type', 'target_scope', 'unit_of_observation',
    'unit_of_analysis', 'construct_or_estimand', 'measurement',
    'closest_work', 'prior_art_boundary', 'rival_explanation',
    'expected_if_focal', 'expected_if_rival', 'discriminating_test',
    'falsifying_result', 'indeterminate_result', 'pilot',
    'engineering_diagnosis', 'prior_outcome_exposure',
)

PLACEHOLDER_VALUES = {
    'none', 'na', 'n a', 'unknown', 'tbd', 'todo', 'not applicable',
    'placeholder', 'none yet', 'to be determined', 'to be decided', 'fill later',
}
_PLACEHOLDER_PREFIX_RE = re.compile(
    r'^(?:tbd\b|todo\b|n\s*/?\s*a\b|placeholder\b|none\s+(?:yet|applicable|available|known|needed|found)\b|'
    r'not\s+applicable\b|to\s+be\s+(?:determined|decided)\b|unknown\s+yet\b|'
    r'no\s+rival(?:\s+(?:explanation|hypothesis|hypotheses|theory|theories|model|models))?\b|'
    r'(?:none|unknown)\s*[-:/(])',
    re.I,
)


def normalize(value):
    return re.sub(r'\W+', ' ', value.casefold()).strip()


def _is_placeholder(value):
    stripped = value.strip()
    return normalize(stripped) in PLACEHOLDER_VALUES or bool(_PLACEHOLDER_PREFIX_RE.match(stripped))


def check(card):
    if not isinstance(card, dict):
        raise ValueError('card must be a JSON object')
    errors, warnings = [], []
    for field in REQUIRED:
        if field not in card or not isinstance(card[field], str) or not card[field].strip():
            errors.append(f'missing_or_blank:{field}')
    if errors:
        return {'valid_structure': False, 'errors': errors, 'warnings': warnings}
    if _is_placeholder(card['rival_explanation']):
        errors.append('rival_explanation_placeholder')
    if normalize(card['expected_if_focal']) == normalize(card['expected_if_rival']):
        errors.append('focal_and_rival_expectations_identical')
    if normalize(card['falsifying_result']) == normalize(card['indeterminate_result']):
        errors.append('falsifier_and_indeterminate_result_identical')
    ident = card.get('identification_assumptions')
    if card['question_type'].strip().lower() == 'causal' and (not isinstance(ident, str) or not ident.strip()):
        errors.append('causal_question_missing_identification_assumptions')
    if normalize(card['closest_work']) in {'none', 'na', 'n a', 'unknown', 'not searched', 'tbd'}:
        warnings.append('closest_work_unchecked; do not score novelty')
    if normalize(card['engineering_diagnosis']) in {'none', 'na', 'n a', 'not checked', 'unknown', 'tbd'}:
        warnings.append('engineering_diagnosis_unchecked; verify before promoting a failure to a gap')
    return {'valid_structure': not errors, 'errors': errors, 'warnings': warnings,
            'scope': 'Checks field presence and a few logical collisions only; it does not verify sources, novelty, measurement validity, causal identification, feasibility, or ethics.'}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('card_json')
    args = parser.parse_args()
    try:
        card = json.loads(Path(args.card_json).read_text(encoding='utf-8'))
        report = check(card)
        print(json.dumps(report))
        sys.exit(0 if report['valid_structure'] else 1)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        sys.exit(2)
