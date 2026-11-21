#!/usr/bin/env python3
"""Cross-check an AI/CS gap, research question, and experiment plan.

This checks declared links and selected failure modes. It cannot validate the
science, reproduce code, establish prior-art recall, or approve a novelty claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from check_gap_record import check as check_gap
from check_gap_campaign import check as check_gap_campaign
from check_question_card import check as check_rq, normalize

HEX64 = re.compile(r'^[0-9a-fA-F]{64}$')
CLAIM_MODES = {'exploratory', 'confirmatory'}
CLAIM_TYPES = {'method', 'mechanism', 'boundary', 'measurement', 'dataset', 'systems'}
ENGINEERING_CHECKS = ('data_identity', 'split_integrity', 'preprocessing', 'metric_sanity',
                      'baseline_fidelity', 'reference_reproduction')
CHECK_STATES = {'passed', 'planned', 'failed', 'unknown', 'not_applicable'}
EXPERIMENT_ROLES = {'primary', 'ablation', 'negative_control', 'stress_test', 'replication'}
_BOILERPLATE_ALT = {'', 'na', 'n a', 'none', 'tbd', 'todo', 'unknown', 'not applicable'}
_DISMISSIVE_ALT_RE = re.compile(r'\b(?:obviously\s+fail|insufficient|clearly\s+inferior|cannot\s+work|inadequate)\b', re.I)
_STACKED_PHRASE_RE = re.compile(r'\b(?:stacking|\d+-stage|\d+-module|multi-?stage)\b', re.I)
_INFLATION_RE = re.compile(
    r'\b(?:fundamental\s+crisis|catastrophic\s+failure|plagued\s+by\s+severe\s+limitations|'
    r'paradigm\s+collapse|all\s+prior\s+work\s+fails?)\b',
    re.I,
)
_NOISE_HINT_RE = re.compile(r'\b(?:0?\.\d+%|noisy\s+fluctuation|seed\s+fluctuation|2\s+random\s+seeds|hyperparameter\s+mismatch)\b', re.I)


_VERSION_OR_COUNT_RE = re.compile(
    r'\b(?:phase|version|ver|stage|step|round|iter(?:ation)?|part|chapter|section|sec|fig(?:ure)?|table|eq(?:uation)?|v)\s*\.?\s*\d+(?:\.\d+)*\b'
    r'|\b\d+(?:\.\d+)?\s*(?:seeds?|runs?|epochs?|layers?|heads?|modules?|components?|parameters?|params?|folds?|trials?)\b',
    re.I,
)
_TRANSITION_RE = re.compile(
    r'(?<!\d)(\d+(?:\.\d+)?)\s*(?:%|pp)?\s*(?:->|→)\s*(\d+(?:\.\d+)?)\s*(?:%|pp)?\b'
    r'|\bfrom\s+(\d+(?:\.\d+)?)\s*(?:%|pp)?\s+to\s+(\d+(?:\.\d+)?)\s*(?:%|pp)?\b',
    re.I,
)
_PROPOSED_VS_SIMPLEST_RE = re.compile(
    r'\b(?:proposed|candidate|ours?)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:%|pp)?\s*'
    r'(?:vs\.?|compared\s+to|over)\s*(?:the\s+)?(?:simplest(?:\s+baseline)?|baseline)\s*[:=]?\s*(\d+(?:\.\d+)?)\b',
    re.I,
)
_SIGNED_DELTA_RE = re.compile(r'(?:^|[\s(,;:])([+-]\s*\d+(?:\.\d+)?)(?=\s*(?:%|pp|\b|[),;]|$))', re.I)
_UNSIGNED_PCT_RE = re.compile(r'(?:^|[\s(,;:])(\d+(?:\.\d+)?)\s*(?:%|pp\b)', re.I)
_GAIN_PHRASE_RE = re.compile(
    r'\b(?:gain|delta|improv\w*|increas\w*|decreas\w*|reduc\w*|drop\w*|outperform\w*|raises?|by)\s+'
    r'(?:of\s+|by\s+)?([+-]?\d+(?:\.\d+)?)\b',
    re.I,
)
_PRE_GAIN_NUM_RE = re.compile(
    r'(?:^|[\s(,;:])([+-]?\d+(?:\.\d+)?)\s*(?:%|pp)?\s+(?:[a-z0-9_-]+\s+)?(?:gain|delta|improvement)\b',
    re.I,
)
_LOWER_GAIN_HINT_RE = re.compile(r'\b(?:gain|improv\w*|reduc\w*|decreas\w*|drop\w*|lower|better)\b', re.I)


def _analyze_string_ablation(text, metric_direction='higher'):
    s = str(text or '').strip()
    if not s or normalize(s) in _BOILERPLATE_ALT:
        return False, False
    direction = str(metric_direction or 'higher').lower()
    positive = False
    cleaned = _VERSION_OR_COUNT_RE.sub(' ', s)

    def _mask_match(m):
        return ' ' * (m.end() - m.start())

    for pat, swap in ((_TRANSITION_RE, False), (_PROPOSED_VS_SIMPLEST_RE, True)):
        parts = []
        last = 0
        for m in pat.finditer(cleaned):
            nums = [g for g in m.groups() if g is not None]
            a, b = float(nums[0]), float(nums[1])
            if swap:
                a, b = b, a
            delta = (a - b) if direction == 'lower' else (b - a)
            if delta <= 0:
                return True, True
            positive = True
            parts.append(cleaned[last:m.start()] + _mask_match(m))
            last = m.end()
        parts.append(cleaned[last:])
        cleaned = ''.join(parts)

    signed_spans = []
    for m in _SIGNED_DELTA_RE.finditer(cleaned):
        signed_spans.append((m.start(), m.end()))
        val = float(re.sub(r'\s+', '', m.group(1)))
        after = cleaned[m.end():m.end() + 28]
        if val == 0.0:
            return True, True
        if direction == 'lower':
            if val < 0:
                if re.match(r'^\s*(?:%|pp)?\s*(?:gain|improvement)\b', after, re.I):
                    return True, True
                positive = True
            else:
                if positive or _LOWER_GAIN_HINT_RE.search(after):
                    positive = True
                else:
                    return True, True
        else:
            if val <= 0:
                return True, True
            positive = True

    for m in _UNSIGNED_PCT_RE.finditer(cleaned):
        if any(s_a <= m.start() < s_b for s_a, s_b in signed_spans):
            continue
        val = float(m.group(1))
        after = cleaned[m.end():m.end() + 28]
        if val <= 0:
            if re.match(r'^\s*(?:overhead|extra|cost|param|params|parameters)\b', after, re.I):
                continue
            return True, True
        positive = True

    for pat in (_GAIN_PHRASE_RE, _PRE_GAIN_NUM_RE):
        for m in pat.finditer(cleaned):
            if any(s_a <= m.start() < s_b for s_a, s_b in signed_spans):
                continue
            val = float(m.group(1))
            if val == 0.0 or (direction == 'higher' and val < 0):
                return True, True
            if val > 0:
                positive = True

    return positive, False


def _has_numeric_ablation(ablation):
    if not isinstance(ablation, dict):
        return False
    mg = ablation.get('marginal_gain')
    if isinstance(mg, (int, float)) and not isinstance(mg, bool):
        return True
    b_val, p_val = ablation.get('baseline_score'), ablation.get('proposed_score')
    return (
        isinstance(b_val, (int, float)) and not isinstance(b_val, bool)
        and isinstance(p_val, (int, float)) and not isinstance(p_val, bool)
    )


def _parse_leading_number(val):
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return float(val)
    if isinstance(val, str):
        m = re.match(r'^\s*([+-]?\d+(?:\.\d+)?)\b', val)
        if m:
            return float(m.group(1))
    return None


def _check_component_item(item, metric_direction):
    if isinstance(item, bool) or item is None:
        return False, False
    if isinstance(item, (int, float)):
        return True, item <= 0
    if isinstance(item, str):
        return _analyze_string_ablation(item, metric_direction)
    if not isinstance(item, dict):
        return False, False
    if item.get('retained') is False:
        return True, False
    raw_mg = item.get('marginal_gain')
    if isinstance(raw_mg, (int, float)) and not isinstance(raw_mg, bool):
        return True, float(raw_mg) <= 0
    if isinstance(raw_mg, str):
        return _analyze_string_ablation(raw_mg, metric_direction)
    b_val, p_val = item.get('baseline_score'), item.get('proposed_score')
    if (isinstance(b_val, (int, float)) and not isinstance(b_val, bool)
            and isinstance(p_val, (int, float)) and not isinstance(p_val, bool)):
        delta = (b_val - p_val) if metric_direction == 'lower' else (p_val - b_val)
        return True, delta <= 0
    return False, False


def _resolve_modules_alias(obj, primary, alias):
    val = obj.get(primary)
    if val is None or (isinstance(val, (list, dict)) and not val):
        alt = obj.get(alias)
        if alt is not None:
            return alt
    return val


def _component_name(comp):
    if isinstance(comp, str):
        return comp.strip().casefold()
    if isinstance(comp, dict):
        val = comp.get('component') or comp.get('name') or comp.get('module')
        if isinstance(val, str):
            return val.strip().casefold()
    return ''


def _check_parsimony(plan, candidate, roles, metric_direction, errors):
    text_blob = ' '.join(
        str(x or '') for x in (
            plan.get('contribution_delta'),
            plan.get('decision_if_resolved'),
            candidate.get('claim') if isinstance(candidate, dict) else '',
        )
    )
    if _INFLATION_RE.search(text_blob) and (
        _NOISE_HINT_RE.search(text_blob) or not re.search(r'\b(?:95%\s*ci|bootstrap|seeds?)\b', text_blob, re.I)
    ):
        errors.append('plan:parsimony_problem_inflation_detected')

    triggered = (
        'components' in plan
        or 'proposed_modules' in plan
        or 'parsimony_audit' in plan
        or 'simplest_alternative' in plan
        or (plan.get('claim_mode') == 'confirmatory' and plan.get('claim_type') == 'method')
        or bool(_STACKED_PHRASE_RE.search(str(plan.get('contribution_delta') or '')))
    )
    if not triggered:
        return
    audit = plan.get('parsimony_audit')
    alt = plan.get('simplest_alternative')
    if not isinstance(alt, str) or not alt.strip():
        alt = audit.get('simplest_alternative') if isinstance(audit, dict) else ''
    alt_str = alt.strip() if isinstance(alt, str) else ''
    alt_norm = normalize(alt_str) if alt_str else ''
    has_concrete_metric = bool(re.search(r'\d', alt_str))
    if (
        not alt_str
        or alt_norm in _BOILERPLATE_ALT
        or len(alt_str.split()) < 4
        or (_DISMISSIVE_ALT_RE.search(alt_str) and not has_concrete_metric)
    ):
        errors.append('plan:parsimony_missing_or_boilerplate_simplest_alternative')
    if not isinstance(audit, dict) or not audit:
        errors.append('plan:parsimony_audit_missing')
        return
    if audit.get('simpler_equal_or_better') is True or audit.get('complexity_justified') is False or audit.get('passed') is False:
        errors.append('plan:parsimony_simpler_baseline_equal_or_better')

    raw_components = _resolve_modules_alias(plan, 'components', 'proposed_modules')
    if isinstance(raw_components, dict):
        components = list(raw_components.keys())
    elif isinstance(raw_components, list):
        components = raw_components
    elif raw_components is not None:
        errors.append('plan:parsimony_invalid_components_format')
        components = [s.strip() for s in re.split(r'[,;+|/\n]+', raw_components) if s.strip()] if isinstance(raw_components, str) else []
    else:
        components = []

    has_ablation_key = 'ablation_over_simplest_baseline' in audit
    ablation = audit.get('ablation_over_simplest_baseline')
    if isinstance(ablation, dict):
        mg = ablation.get('marginal_gain')
        if isinstance(mg, (int, float)) and not isinstance(mg, bool):
            if mg <= 0:
                errors.append('plan:parsimony_nonpositive_marginal_gain')
        else:
            b_val, p_val = ablation.get('baseline_score'), ablation.get('proposed_score')
            if (isinstance(b_val, (int, float)) and not isinstance(b_val, bool)
                    and isinstance(p_val, (int, float)) and not isinstance(p_val, bool)):
                delta = (b_val - p_val) if metric_direction == 'lower' else (p_val - b_val)
                if delta <= 0:
                    errors.append('plan:parsimony_nonpositive_marginal_gain')
            else:
                errors.append('plan:parsimony_missing_ablation_over_simplest_baseline')
    elif has_ablation_key:
        if isinstance(ablation, str):
            has_ev, nonpos = _analyze_string_ablation(ablation, metric_direction)
            if nonpos:
                errors.append('plan:parsimony_nonpositive_marginal_gain')
            elif not has_ev:
                errors.append('plan:parsimony_missing_ablation_over_simplest_baseline')
        else:
            errors.append('plan:parsimony_missing_ablation_over_simplest_baseline')

    if len(components) >= 2:
        if 'ablation' not in roles:
            errors.append('plan:parsimony_missing_ablation_experiment')
        if not has_ablation_key and 'plan:parsimony_missing_ablation_over_simplest_baseline' not in errors:
            errors.append('plan:parsimony_missing_ablation_over_simplest_baseline')

    has_justs = 'component_justifications' in audit
    justs = audit.get('component_justifications')
    if len(components) >= 2 or has_justs:
        if not justs or not isinstance(justs, (list, dict)):
            errors.append('plan:parsimony_missing_component_justifications')
        else:
            if isinstance(justs, dict):
                named_items = [(k, v) for k, v in justs.items()]
            else:
                named_items = [
                    (item.get('component') or item.get('name') or item.get('module') if isinstance(item, dict) else '', item)
                    for item in justs
                ]
            if len(components) >= 2 and len(named_items) < len(components):
                errors.append('plan:parsimony_missing_component_justifications')
            comp_names = {_component_name(c) for c in components if _component_name(c)}
            retained_positive = 0
            retained_names = set()
            seen_comp_names = set()
            for cname, item in named_items:
                norm_cname = cname.strip().casefold() if isinstance(cname, str) else ''
                if norm_cname:
                    seen_comp_names.add(norm_cname)
                if isinstance(item, dict) and item.get('retained') is False:
                    if norm_cname in comp_names:
                        errors.append('plan:parsimony_unretained_component_still_in_plan')
                    continue
                has_num, nonpos = _check_component_item(item, metric_direction)
                if nonpos:
                    errors.append('plan:parsimony_component_nonpositive_gain')
                elif not has_num:
                    errors.append('plan:parsimony_missing_component_justifications')
                else:
                    retained_positive += 1
                    if norm_cname:
                        retained_names.add(norm_cname)
            if comp_names and not comp_names.issubset(retained_names):
                if not comp_names.issubset(seen_comp_names) and 'plan:parsimony_missing_component_justifications' not in errors:
                    errors.append('plan:parsimony_missing_component_justifications')
            if components and retained_positive == 0:
                errors.append('plan:parsimony_no_retained_positive_component')


def _filled(obj, key):
    return isinstance(obj, dict) and isinstance(obj.get(key), str) and bool(obj[key].strip())


def _list_of_strings(value):
    return isinstance(value, list) and all(isinstance(v, str) and bool(v.strip()) for v in value)


def _require_text(obj, fields, prefix, errors):
    for field in fields:
        if not _filled(obj, field):
            errors.append(f'{prefix}:missing_or_blank:{field}')


def check(gap_record, rq_card, plan, campaign=None, campaign_sha256=None):
    if not all(isinstance(item, dict) for item in (gap_record, rq_card, plan)):
        raise ValueError('gap record, RQ card, and experiment plan must be objects')
    errors, warnings = [], []
    gap_result = check_gap(gap_record)
    rq_result = check_rq(rq_card)
    errors.extend('gap_record:' + item for item in gap_result['errors'])
    errors.extend('rq_card:' + item for item in rq_result['errors'])
    warnings.extend('gap_record:' + item for item in gap_result['warnings'])
    warnings.extend('rq_card:' + item for item in rq_result['warnings'])
    campaign_report = None
    if campaign is not None:
        campaign_report = check_gap_campaign(gap_record, campaign, campaign_sha256)
        errors.extend('campaign:' + item for item in campaign_report['errors'] if item not in gap_result['errors'])
        warnings.extend('campaign:' + item for item in campaign_report['warnings'] if item not in gap_result['warnings'])
    elif plan.get('claim_mode') == 'confirmatory':
        errors.append('plan:confirmatory_claim_requires_campaign_manifest')
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
        elif item['status'] in ('planned', 'failed', 'unknown') or (
            plan.get('claim_mode') == 'confirmatory' and item['status'] == 'not_applicable'
        ):
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
        for name in unresolved_engineering:
            item = engineering.get(name)
            if isinstance(item, dict) and item.get('status') in ('planned', 'failed', 'unknown', 'not_applicable'):
                errors.append(f'engineering_checks:{name}:confirmatory_requires_passed_check')
        warnings.append('confirmatory_interpretation_blocked_until_engineering_checks_pass')
    _check_parsimony(plan, candidate, roles, benchmark.get('metric_direction', 'higher'), errors)
    unresolved_gate = bool(
        (candidate and candidate.get('trigger') == 'failed_implementation' and unresolved_engineering)
        or (plan.get('claim_mode') == 'confirmatory' and unresolved_engineering)
    )
    return {'status': 'invalid' if errors else 'structurally_reviewable',
            'errors': errors, 'warnings': warnings,
            'campaign_manifest_check': (None if campaign_report is None else {
                'valid_structure_and_manifest': campaign_report['valid_structure_and_manifest'],
                'campaign_sha256': campaign_report['campaign_sha256'],
                'verified_query_rows': campaign_report['verified_query_rows']}),
            'engineering_checks_pending_or_failed': unresolved_engineering,
            'gap_interpretation_gate': ('engineering_unresolved' if unresolved_gate
                                        else 'requires_source_and_experiment_review'),
            'disclaimer': ('A structural pass cannot establish a real gap, valid RQ, fair benchmark, working code, '
                           'novelty score or supported experimental result. Inspect sources, data, code and runs.')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gap_record_json')
    parser.add_argument('question_card_json')
    parser.add_argument('ai_cs_plan_json')
    parser.add_argument('--campaign', help='Optional search_campaign.py JSON to cross-check gap query rows')
    args = parser.parse_args()
    try:
        docs = [json.loads(Path(path).read_text(encoding='utf-8')) for path in
                (args.gap_record_json, args.question_card_json, args.ai_cs_plan_json)]
        campaign = None
        digest = None
        if args.campaign:
            raw = Path(args.campaign).read_bytes()
            campaign = json.loads(raw)
            digest = hashlib.sha256(raw).hexdigest()
        report = check(*docs, campaign=campaign, campaign_sha256=digest)
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report['status'] == 'structurally_reviewable' else 1
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
