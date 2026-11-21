#!/usr/bin/env python3
"""Cross-check an AI/CS gap, research question, and experiment plan.

This checks declared links and selected failure modes. It cannot validate the
science, reproduce code, establish prior-art recall, or approve a novelty claim.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from check_gap_record import check as check_gap
from check_question_card import check as check_rq, normalize

HEX64 = re.compile(r'^[0-9a-fA-F]{64}$')
CLAIM_MODES = {'exploratory', 'confirmatory'}
CLAIM_TYPES = {'method', 'mechanism', 'boundary', 'measurement', 'dataset', 'systems'}
ENGINEERING_CHECKS = ('data_identity', 'split_integrity', 'preprocessing', 'metric_sanity',
                      'baseline_fidelity', 'reference_reproduction')
CHECK_STATES = {'passed', 'planned', 'failed', 'unknown', 'not_applicable'}
EXPERIMENT_ROLES = {'primary', 'ablation', 'negative_control', 'stress_test', 'replication'}


def _filled(obj, key):
    return isinstance(obj, dict) and isinstance(obj.get(key), str) and bool(obj[key].strip())


def _list_of_strings(value):
    return isinstance(value, list) and all(isinstance(v, str) and bool(v.strip()) for v in value)


def _require_text(obj, fields, prefix, errors):
    for field in fields:
        if not _filled(obj, field):
            errors.append(f'{prefix}:missing_or_blank:{field}')


def check(gap_record, rq_card, plan):
    if not all(isinstance(item, dict) for item in (gap_record, rq_card, plan)):
        raise ValueError('gap record, RQ card, and experiment plan must be objects')
    errors, warnings = [], []
    gap_result = check_gap(gap_record)
    rq_result = check_rq(rq_card)
    errors.extend('gap_record:' + item for item in gap_result['errors'])
    errors.extend('rq_card:' + item for item in rq_result['errors'])
    warnings.extend('gap_record:' + item for item in gap_result['warnings'])
    warnings.extend('rq_card:' + item for item in rq_result['warnings'])
    _require_text(plan, ('gap_candidate_id', 'question_id', 'claim_mode', 'claim_type',
                         'contribution_delta', 'decision_if_resolved'), 'plan', errors)
    if not _filled(rq_card, 'id'):
        errors.append('rq_card:missing_or_blank:id')
    elif plan.get('question_id') != rq_card['id']:
        errors.append('plan:question_id_mismatch')
    if not isinstance(plan.get('claim_mode'), str) or plan['claim_mode'] not in CLAIM_MODES:
        errors.append('plan:invalid_claim_mode')
    if not isinstance(plan.get('claim_type'), str) or plan['claim_type'] not in CLAIM_TYPES:
        errors.append('plan:invalid_claim_type')
    raw_candidates = gap_record.get('candidates')
    candidates = {c.get('id'): c for c in raw_candidates if isinstance(c, dict)} if isinstance(raw_candidates, list) else {}
    candidate = candidates.get(plan.get('gap_candidate_id'))
    if candidate is None:
        errors.append('plan:unknown_gap_candidate_id')
    elif plan.get('claim_mode') == 'confirmatory' and candidate.get('disposition') != 'supported_candidate':
        errors.append('plan:confirmatory_claim_requires_supported_gap_candidate')
    exposure = rq_card.get('prior_outcome_exposure')
    if plan.get('claim_mode') == 'confirmatory' and isinstance(exposure, str) and normalize(exposure) in {
            'seen', 'inspected', 'already inspected', 'outcomes seen', 'yes'}:
        errors.append('plan:seen_outcomes_cannot_be_called_prespecified_confirmation')
    close = plan.get('closest_work_ids')
    if not _list_of_strings(close):
        errors.append('plan:closest_work_ids_must_be_list')
        close = []
    if candidate:
        raw_close = candidate.get('closest_work_ids')
        candidate_close = set(raw_close) if _list_of_strings(raw_close) else set()
        if set(close) - candidate_close:
            errors.append('plan:closest_work_ids_not_linked_to_gap_candidate')
        if plan.get('claim_mode') == 'confirmatory' and not close:
            errors.append('plan:confirmatory_claim_needs_closest_work')
    unresolved = plan.get('unresolved_close_work_ids')
    if not _list_of_strings(unresolved):
        errors.append('plan:unresolved_close_work_ids_must_be_list')
        unresolved = []
    if plan.get('claim_mode') == 'confirmatory' and unresolved:
        errors.append('plan:unread_close_work_blocks_confirmatory_novelty')

    benchmark = plan.get('benchmark')
    if not isinstance(benchmark, dict):
        errors.append('benchmark:must_be_object')
        benchmark = {}
    _require_text(benchmark, ('task', 'dataset_version', 'metric_id', 'metric_direction',
                              'unit_of_analysis', 'contamination_check', 'test_set_access_policy',
                              'benchmark_limitations'), 'benchmark', errors)
    if not isinstance(benchmark.get('split_manifest_sha256'), str) or not HEX64.fullmatch(benchmark['split_manifest_sha256']):
        errors.append('benchmark:invalid_split_manifest_sha256')
    if benchmark.get('metric_direction') not in ('higher', 'lower'):
        errors.append('benchmark:metric_direction_must_be_higher_or_lower')

    engineering = plan.get('engineering_checks')
    if not isinstance(engineering, dict):
        errors.append('engineering_checks:must_be_object')
        engineering = {}
    unresolved_engineering = []
    for name in ENGINEERING_CHECKS:
        item = engineering.get(name)
        if (not isinstance(item, dict) or not isinstance(item.get('status'), str) or
                item['status'] not in CHECK_STATES or not _filled(item, 'evidence_or_action')):
            errors.append(f'engineering_checks:{name}:missing_status_or_evidence')
            unresolved_engineering.append(name)
        elif item['status'] in ('planned', 'failed', 'unknown'):
            unresolved_engineering.append(name)
    if candidate and candidate.get('trigger') == 'failed_implementation':
        if any(not isinstance(engineering.get(name), dict) or engineering[name].get('status') != 'passed'
               for name in ENGINEERING_CHECKS):
            warnings.append('failed_implementation_trigger:engineering_cause_not_ruled_out')
            if plan.get('claim_mode') == 'confirmatory':
                errors.append('plan:confirmatory_failure_claim_requires_passed_engineering_checks')

    fairness = plan.get('comparison_fairness')
    if not isinstance(fairness, dict):
        errors.append('comparison_fairness:must_be_object')
        fairness = {}
    _require_text(fairness, ('baseline_source', 'baseline_implementation', 'training_data_budget',
                             'compute_budget', 'tuning_budget', 'information_access'),
                  'comparison_fairness', errors)

    analysis = plan.get('analysis')
    if not isinstance(analysis, dict):
        errors.append('analysis:must_be_object')
        analysis = {}
    _require_text(analysis, ('effect_measure', 'decision_threshold', 'uncertainty_method',
                             'aggregation_unit', 'seed_policy', 'multiple_testing_policy',
                             'failed_run_policy', 'holdout_policy'), 'analysis', errors)
    if _filled(analysis, 'aggregation_unit') and _filled(benchmark, 'unit_of_analysis') and \
            normalize(analysis['aggregation_unit']) != normalize(benchmark['unit_of_analysis']):
        warnings.append('analysis:aggregation_unit_differs_from_benchmark; justify dependence model')

    experiments = plan.get('experiments')
    if not isinstance(experiments, list) or not experiments:
        errors.append('experiments:must_be_nonempty_list')
        experiments = []
    seen_ids, roles = set(), set()
    for index, experiment in enumerate(experiments):
        prefix = f'experiments:{index}'
        if not isinstance(experiment, dict):
            errors.append(f'{prefix}:must_be_object')
            continue
        _require_text(experiment, ('id', 'role', 'purpose', 'focal_condition', 'comparator_condition',
                                   'variable_changed', 'outcome', 'predicted_if_focal',
                                   'predicted_if_rival', 'falsifying_result', 'indeterminate_result',
                                   'analysis_action', 'tuning_data_role', 'evaluation_data_role'), prefix, errors)
        eid = experiment.get('id')
        if isinstance(eid, str):
            if eid in seen_ids:
                errors.append(f'{prefix}:duplicate_id')
            seen_ids.add(eid)
        role = experiment.get('role')
        if isinstance(role, str):
            roles.add(role)
        if not isinstance(role, str) or role not in EXPERIMENT_ROLES:
            errors.append(f'{prefix}:invalid_role')
        if _filled(experiment, 'predicted_if_focal') and _filled(experiment, 'predicted_if_rival') and \
                normalize(experiment['predicted_if_focal']) == normalize(experiment['predicted_if_rival']):
            errors.append(f'{prefix}:predictions_do_not_discriminate')
        if _filled(experiment, 'focal_condition') and _filled(experiment, 'comparator_condition') and \
                normalize(experiment['focal_condition']) == normalize(experiment['comparator_condition']):
            errors.append(f'{prefix}:focal_and_comparator_conditions_identical')
        if _filled(experiment, 'falsifying_result') and _filled(experiment, 'indeterminate_result') and \
                normalize(experiment['falsifying_result']) == normalize(experiment['indeterminate_result']):
            errors.append(f'{prefix}:falsifier_equals_indeterminate')
        if experiment.get('tuning_data_role') not in ('train', 'validation', 'none'):
            errors.append(f'{prefix}:invalid_tuning_data_role_or_test_set_used_for_tuning')
        if experiment.get('evaluation_data_role') not in ('test', 'external', 'simulator'):
            errors.append(f'{prefix}:invalid_evaluation_data_role')
        elif experiment.get('evaluation_data_role') != 'test':
            warnings.append(f'{prefix}:evaluation_not_on_declared_holdout_test_set; justify external or simulator route')
        controls = experiment.get('controls')
        if not _list_of_strings(controls) or not controls:
            errors.append(f'{prefix}:controls_must_be_nonempty_list')
    if 'primary' not in roles:
        errors.append('experiments:no_primary_discriminating_test')
    if plan.get('claim_type') == 'mechanism' and not roles.intersection({'ablation', 'negative_control'}):
        errors.append('experiments:mechanism_claim_needs_ablation_or_negative_control')
    if plan.get('claim_mode') == 'confirmatory' and unresolved_engineering:
        warnings.append('confirmatory_interpretation_blocked_until_engineering_checks_pass')
    return {'status': 'invalid' if errors else 'structurally_reviewable',
            'errors': errors, 'warnings': warnings,
            'engineering_checks_pending_or_failed': unresolved_engineering,
            'gap_interpretation_gate': ('engineering_unresolved' if candidate and
                                        candidate.get('trigger') == 'failed_implementation' and unresolved_engineering
                                        else 'requires_source_and_experiment_review'),
            'disclaimer': ('A structural pass cannot establish a real gap, valid RQ, fair benchmark, working code, '
                           'novelty score or supported experimental result. Inspect sources, data, code and runs.')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gap_record_json')
    parser.add_argument('question_card_json')
    parser.add_argument('ai_cs_plan_json')
    args = parser.parse_args()
    try:
        docs = [json.loads(Path(path).read_text(encoding='utf-8')) for path in
                (args.gap_record_json, args.question_card_json, args.ai_cs_plan_json)]
        print(json.dumps(check(*docs), ensure_ascii=False))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
