"""Unit and adversarial tests for the F19 Parsimony & Anti-Problem-Inflation Gate."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'research-scientist/scripts'
F19_FIX = ROOT / 'evaluation/e2e/fixtures/f19'
sys.path.insert(0, str(SCRIPTS))

import check_ai_cs_research_plan as plan_chk
import gap_pipeline


class ParsimonyGateTests(unittest.TestCase):
    def _load(self, name: str):
        return json.loads((F19_FIX / name).read_text(encoding='utf-8'))

    def test_minimal_candidate_and_valid_parsimony_plan_pass(self):
        corpus, _ = gap_pipeline._load_corpus(F19_FIX / 'gap_corpus.json')
        digests = gap_pipeline._load_digests(F19_FIX / 'gap_digests.json')
        cands, _ = gap_pipeline._load_candidates(F19_FIX / 'gap_candidates_minimal_valid.json')
        gp = gap_pipeline.run_pipeline('degree shift', corpus, digests, cands)
        self.assertEqual(gp['exit_code'], 0)
        self.assertEqual(len(gp['surviving_gaps']), 1)

        rep = plan_chk.check(
            self._load('gap_parsimony.json'),
            self._load('rq_parsimony.json'),
            self._load('plan_parsimony_valid.json'),
            campaign=self._load('campaign_parsimony.json'),
        )
        self.assertEqual(rep['status'], 'structurally_reviewable', rep['errors'])

    def test_gap_pipeline_rejects_bloated_and_problem_inflated_candidates(self):
        corpus, _ = gap_pipeline._load_corpus(F19_FIX / 'gap_corpus.json')
        digests = gap_pipeline._load_digests(F19_FIX / 'gap_digests.json')
        cands, _ = gap_pipeline._load_candidates(F19_FIX / 'gap_candidates_bloated_and_inflated.json')
        gp = gap_pipeline.run_pipeline('degree shift', corpus, digests, cands)
        self.assertEqual(gp['exit_code'], 1)
        by_id = {r['id']: r['reason_code'] for r in gp['rejected_gaps']}
        self.assertEqual(by_id['C_BLOATED'], 'DROP_OVERCOMPLICATED')
        self.assertEqual(by_id['C_INFLATED'], 'DROP_PROBLEM_INFLATION')

    def test_plan_checker_rejects_boilerplate_and_nonpositive_ablation_gains(self):
        gap = self._load('gap_parsimony.json')
        rq = self._load('rq_parsimony.json')
        camp = self._load('campaign_parsimony.json')

        for bad_alt in ('', 'N/A', 'none', 'simpler methods obviously fail'):
            plan = copy.deepcopy(self._load('plan_parsimony_valid.json'))
            plan['simplest_alternative'] = bad_alt
            plan['parsimony_audit']['simplest_alternative'] = bad_alt
            rep = plan_chk.check(gap, rq, plan, campaign=camp)
            self.assertEqual(rep['status'], 'invalid', bad_alt)
            self.assertIn('plan:parsimony_missing_or_boilerplate_simplest_alternative', rep['errors'])

        zero_plan = self._load('plan_overengineered_zero_gain.json')
        rep_zero = plan_chk.check(gap, rq, zero_plan, campaign=camp)
        self.assertEqual(rep_zero['status'], 'invalid')
        self.assertIn('plan:parsimony_nonpositive_marginal_gain', rep_zero['errors'])
        self.assertIn('plan:parsimony_component_nonpositive_gain', rep_zero['errors'])

    def test_b7_gap_pipeline_rejects_negative_marginal_gain_ablation_dict(self):
        corpus, _ = gap_pipeline._load_corpus(F19_FIX / 'gap_corpus.json')
        digests = gap_pipeline._load_digests(F19_FIX / 'gap_digests.json')
        cand_neg = {
            'id': 'C_NEG_MG',
            'claim': 'Three-module extension improves degree-shift node classification.',
            'cited_ids': ['P1', 'P2'],
            'support_ids': ['P1', 'P2'],
            'cutoff_year': 2026,
            'sgha_critics_passed': True,
            'engineering_checked': True,
            'proposed_modules': ['M1', 'M2', 'M3'],
            'simplest_alternative': 'Tuned 2-layer GCN baseline scoring 0.718 macro-F1 across 5 seeds.',
            'ablation_evidence': {'marginal_gain': -0.05},
        }
        gp = gap_pipeline.run_pipeline('degree shift', corpus, digests, [cand_neg])
        self.assertEqual(gp['exit_code'], 1)
        self.assertEqual(gp['rejected_gaps'][0]['reason_code'], 'DROP_OVERCOMPLICATED')

        cand_nonnum = copy.deepcopy(cand_neg)
        cand_nonnum['ablation_evidence'] = {'note': 'planned later'}
        gp2 = gap_pipeline.run_pipeline('degree shift', corpus, digests, [cand_nonnum])
        self.assertEqual(gp2['exit_code'], 1)
        self.assertEqual(gp2['rejected_gaps'][0]['reason_code'], 'DROP_OVERCOMPLICATED')

    def test_b9_b10_b12_plan_checker_proposed_modules_dict_justifications_and_boundary_inflation(self):
        gap = self._load('gap_parsimony.json')
        rq = self._load('rq_parsimony.json')
        camp = self._load('campaign_parsimony.json')

        # B9: proposed_modules alias triggers multi-component parsimony checks
        plan_pm = copy.deepcopy(self._load('plan_parsimony_valid.json'))
        plan_pm.pop('components', None)
        plan_pm['proposed_modules'] = ['M1', 'M2', 'M3']
        plan_pm['experiments'] = [e for e in plan_pm['experiments'] if e['role'] != 'ablation']
        plan_pm['parsimony_audit'].pop('ablation_over_simplest_baseline', None)
        plan_pm['parsimony_audit'].pop('component_justifications', None)
        rep_pm = plan_chk.check(gap, rq, plan_pm, campaign=camp)
        self.assertEqual(rep_pm['status'], 'invalid')
        self.assertIn('plan:parsimony_missing_ablation_experiment', rep_pm['errors'])
        self.assertIn('plan:parsimony_missing_ablation_over_simplest_baseline', rep_pm['errors'])
        self.assertIn('plan:parsimony_missing_component_justifications', rep_pm['errors'])

        # B10: dict ablation without numbers + dict component_justifications with negative gain
        plan_dict = copy.deepcopy(self._load('plan_parsimony_valid.json'))
        plan_dict['components'] = ['M1', 'M2']
        plan_dict['parsimony_audit']['ablation_over_simplest_baseline'] = {'note': 'planned later'}
        plan_dict['parsimony_audit']['component_justifications'] = {
            'M1': {'marginal_gain': -0.05},
            'M2': {'marginal_gain': -0.02},
        }
        rep_dict = plan_chk.check(gap, rq, plan_dict, campaign=camp)
        self.assertEqual(rep_dict['status'], 'invalid')
        self.assertIn('plan:parsimony_missing_ablation_over_simplest_baseline', rep_dict['errors'])
        self.assertIn('plan:parsimony_component_nonpositive_gain', rep_dict['errors'])

        # B12: non-method boundary plan with dramatized problem inflation is still caught
        plan_bnd = copy.deepcopy(self._load('plan_parsimony_valid.json'))
        plan_bnd['claim_type'] = 'boundary'
        for k in ('components', 'parsimony_audit', 'simplest_alternative'):
            plan_bnd.pop(k, None)
        plan_bnd['contribution_delta'] = 'Exposes a catastrophic failure where all prior work fails completely.'
        rep_bnd = plan_chk.check(gap, rq, plan_bnd, campaign=camp)
        self.assertEqual(rep_bnd['status'], 'invalid')
        self.assertIn('plan:parsimony_problem_inflation_detected', rep_bnd['errors'])

    def test_n3_n5_plan_and_pipeline_parsimony_bypasses_closed(self):
        gap = self._load('gap_parsimony.json')
        rq = self._load('rq_parsimony.json')
        camp = self._load('campaign_parsimony.json')
        base = self._load('plan_parsimony_valid.json')

        # N3: string/partial justifications, bool ablation, dict proposed_modules, 1-comp negative
        p_str = copy.deepcopy(base)
        p_str['components'] = ['M1', 'M2', 'M3']
        p_str['parsimony_audit']['component_justifications'] = {'M1': 'helps', 'M2': 'ok', 'M3': 'good'}
        self.assertEqual(plan_chk.check(gap, rq, p_str, campaign=camp)['status'], 'invalid')

        p_part = copy.deepcopy(base)
        p_part['components'] = ['M1', 'M2', 'M3']
        p_part['parsimony_audit']['component_justifications'] = [{'component': 'M1', 'note': 'useful'}]
        self.assertEqual(plan_chk.check(gap, rq, p_part, campaign=camp)['status'], 'invalid')

        p_bool = copy.deepcopy(base)
        p_bool['parsimony_audit']['ablation_over_simplest_baseline'] = True
        self.assertEqual(plan_chk.check(gap, rq, p_bool, campaign=camp)['status'], 'invalid')

        p_dict_mod = copy.deepcopy(base)
        p_dict_mod.pop('components', None)
        p_dict_mod['proposed_modules'] = {'M1': 'a', 'M2': 'b', 'M3': 'c'}
        p_dict_mod['experiments'] = [e for e in p_dict_mod['experiments'] if e['role'] != 'ablation']
        p_dict_mod['parsimony_audit'].pop('ablation_over_simplest_baseline', None)
        p_dict_mod['parsimony_audit'].pop('component_justifications', None)
        self.assertEqual(plan_chk.check(gap, rq, p_dict_mod, campaign=camp)['status'], 'invalid')

        p_one_bad = copy.deepcopy(base)
        p_one_bad['parsimony_audit']['ablation_over_simplest_baseline'] = {'note': 'planned later'}
        p_one_bad['parsimony_audit']['component_justifications'] = {'M1': {'marginal_gain': -0.05}}
        r_one = plan_chk.check(gap, rq, p_one_bad, campaign=camp)
        self.assertEqual(r_one['status'], 'invalid')
        self.assertIn('plan:parsimony_missing_ablation_over_simplest_baseline', r_one['errors'])
        self.assertIn('plan:parsimony_component_nonpositive_gain', r_one['errors'])

        # N5: Phase 1 summary string, complexity_justified=False, dict proposed_modules
        corpus, _ = gap_pipeline._load_corpus(F19_FIX / 'gap_corpus.json')
        digests = gap_pipeline._load_digests(F19_FIX / 'gap_digests.json')
        for cand in (
            {'id': 'C5A', 'claim': 'Three-module stack', 'cited_ids': ['P1', 'P2'], 'support_ids': ['P1', 'P2'],
             'cutoff_year': 2026, 'sgha_critics_passed': True, 'engineering_checked': True,
             'proposed_modules': ['M1', 'M2', 'M3'],
             'simplest_alternative': 'Tuned 2-layer GCN baseline 0.718 macro-F1 across 5 seeds.',
             'ablation_evidence': {'summary': 'Phase 1 ablation planned'}},
            {'id': 'C5B', 'claim': 'Rejected audit flags', 'cited_ids': ['P1', 'P2'], 'support_ids': ['P1', 'P2'],
             'cutoff_year': 2026, 'sgha_critics_passed': True, 'engineering_checked': True,
             'parsimony_audit': {'complexity_justified': False, 'passed': False}},
            {'id': 'C5C', 'claim': 'Dict modules stack', 'cited_ids': ['P1', 'P2'], 'support_ids': ['P1', 'P2'],
             'cutoff_year': 2026, 'sgha_critics_passed': True, 'engineering_checked': True,
             'proposed_modules': {'M1': 'a', 'M2': 'b', 'M3': 'c'}},
        ):
            gp = gap_pipeline.run_pipeline('degree shift', corpus, digests, [cand])
            self.assertEqual(gp['exit_code'], 1, cand['id'])
            self.assertEqual(gp['rejected_gaps'][0]['reason_code'], 'DROP_OVERCOMPLICATED', cand['id'])

    def test_r3_1_r3_2_string_ablation_all_unretained_and_string_modules_rejected(self):
        gap = self._load('gap_parsimony.json')
        rq = self._load('rq_parsimony.json')
        camp = self._load('campaign_parsimony.json')
        base = self._load('plan_parsimony_valid.json')

        # R3_1: negative, zero-gain, and Phase 1.0 string ablations rejected on higher-is-better plan
        for bad_ab in (
            '-0.05 macro-F1 (proposed 0.700 vs simplest 0.750)',
            '0.00% gain over simplest baseline',
            'Phase 1.0 ablation planned',
        ):
            p = copy.deepcopy(base)
            p['parsimony_audit']['ablation_over_simplest_baseline'] = bad_ab
            rep = plan_chk.check(gap, rq, p, campaign=camp)
            self.assertEqual(rep['status'], 'invalid', bad_ab)

        # R3_1: lower-is-better allows valid negative ECE delta, rejects worsening positive transition
        p_low_ok = copy.deepcopy(base)
        p_low_ok['benchmark']['metric_direction'] = 'lower'
        p_low_ok['parsimony_audit']['ablation_over_simplest_baseline'] = '-0.05 ECE (0.12 -> 0.07)'
        p_low_ok['parsimony_audit']['component_justifications'][0]['marginal_gain'] = '-0.05 ECE (0.12 -> 0.07)'
        self.assertEqual(plan_chk.check(gap, rq, p_low_ok, campaign=camp)['status'], 'structurally_reviewable')

        p_low_bad = copy.deepcopy(p_low_ok)
        p_low_bad['parsimony_audit']['ablation_over_simplest_baseline'] = '+0.05 ECE (0.07 -> 0.12)'
        self.assertEqual(plan_chk.check(gap, rq, p_low_bad, campaign=camp)['status'], 'invalid')

        # R3_2: all-retained: False bypass and retained: False on still-present component rejected; pruned-out allowed
        p_unret = copy.deepcopy(base)
        p_unret['components'] = ['M1', 'M2', 'M3']
        p_unret['parsimony_audit']['component_justifications'] = [
            {'component': 'M1', 'retained': False},
            {'component': 'M2', 'retained': False},
            {'component': 'M3', 'retained': False},
        ]
        self.assertEqual(plan_chk.check(gap, rq, p_unret, campaign=camp)['status'], 'invalid')

        p_pruned_ok = copy.deepcopy(base)
        p_pruned_ok['parsimony_audit']['component_justifications'].append({'component': 'extra_adapter', 'retained': False})
        self.assertEqual(plan_chk.check(gap, rq, p_pruned_ok, campaign=camp)['status'], 'structurally_reviewable')

        # R3_2: string proposed_modules rejected in check_ai_cs_research_plan
        p_str_mod = copy.deepcopy(base)
        p_str_mod.pop('components', None)
        p_str_mod['proposed_modules'] = 'M1, M2, M3'
        rep_str = plan_chk.check(gap, rq, p_str_mod, campaign=camp)
        self.assertEqual(rep_str['status'], 'invalid')
        self.assertIn('plan:parsimony_invalid_components_format', rep_str['errors'])

        # R3_1 & R3_2 in gap_pipeline.py
        corpus, _ = gap_pipeline._load_corpus(F19_FIX / 'gap_corpus.json')
        digests = gap_pipeline._load_digests(F19_FIX / 'gap_digests.json')
        for cid, extra in (
            ('D1', {'proposed_modules': ['M1', 'M2', 'M3'], 'ablation_evidence': '-0.05 macro-F1 over simplest baseline'}),
            ('D2', {'proposed_modules': ['M1', 'M2', 'M3'], 'ablation_evidence': '0.00% gain over baseline'}),
            ('D3', {'proposed_modules': ['M1', 'M2', 'M3'], 'ablation_evidence': 'Phase 1.0 ablation planned'}),
            ('D4', {'proposed_modules': 'M1, M2, M3'}),
        ):
            cand = {
                'id': cid, 'claim': 'Calibration extension', 'cited_ids': ['P1', 'P2'], 'support_ids': ['P1', 'P2'],
                'cutoff_year': 2026, 'sgha_critics_passed': True, 'engineering_checked': True,
                'simplest_alternative': 'Tuned 2-layer GCN baseline 0.718 macro-F1 across 5 seeds.',
                **extra,
            }
            gp = gap_pipeline.run_pipeline('degree shift', corpus, digests, [cand])
            self.assertEqual(gp['exit_code'], 1, cid)
            self.assertEqual(gp['rejected_gaps'][0]['reason_code'], 'DROP_OVERCOMPLICATED', cid)

        cand_low_ok = {
            'id': 'D_LOW_OK', 'claim': 'Calibration extension', 'cited_ids': ['P1', 'P2'], 'support_ids': ['P1', 'P2'],
            'cutoff_year': 2026, 'sgha_critics_passed': True, 'engineering_checked': True,
            'metric_direction': 'lower',
            'proposed_modules': ['M1', 'M2', 'M3'],
            'simplest_alternative': 'Tuned 2-layer GCN baseline 0.12 ECE across 5 seeds.',
            'ablation_evidence': '-0.05 ECE (0.12 -> 0.07)',
        }
        gp_low = gap_pipeline.run_pipeline('degree shift', corpus, digests, [cand_low_ok])
        self.assertEqual(gp_low['exit_code'], 0, gp_low['rejected_gaps'])

    def test_r4_1_r4_2_r4_3_component_coverage_empty_alias_pct_boundary_and_simplest_baseline(self):
        gap = self._load('gap_parsimony.json')
        rq = self._load('rq_parsimony.json')
        camp = self._load('campaign_parsimony.json')
        base = self._load('plan_parsimony_valid.json')

        # R4_1a: unlisted retained:False padding and duplicate M1 padding rejected; valid covered + pruned-out passes
        p_pad = copy.deepcopy(base)
        p_pad['components'] = ['M1', 'M2', 'M3']
        p_pad['parsimony_audit']['component_justifications'] = [
            {'component': 'M1', 'marginal_gain': 0.05},
            {'component': 'M2', 'marginal_gain': 0.03},
            {'component': 'pruned_other', 'retained': False},
        ]
        rep_pad = plan_chk.check(gap, rq, p_pad, campaign=camp)
        self.assertEqual(rep_pad['status'], 'invalid')
        self.assertIn('plan:parsimony_missing_component_justifications', rep_pad['errors'])

        p_dup = copy.deepcopy(base)
        p_dup['components'] = ['M1', 'M2', 'M3']
        p_dup['parsimony_audit']['component_justifications'] = [{'component': 'M1', 'marginal_gain': 0.05}] * 3
        rep_dup = plan_chk.check(gap, rq, p_dup, campaign=camp)
        self.assertEqual(rep_dup['status'], 'invalid')
        self.assertIn('plan:parsimony_missing_component_justifications', rep_dup['errors'])

        p_dict_mis = copy.deepcopy(base)
        p_dict_mis['components'] = ['M1', 'M2']
        p_dict_mis['parsimony_audit']['component_justifications'] = {
            'M1': {'marginal_gain': 0.05},
            'other': {'marginal_gain': 0.03},
        }
        self.assertEqual(plan_chk.check(gap, rq, p_dict_mis, campaign=camp)['status'], 'invalid')

        p_all_cov = copy.deepcopy(base)
        p_all_cov['components'] = ['M1', 'M2']
        p_all_cov['parsimony_audit']['component_justifications'] = [
            {'component': 'M1', 'marginal_gain': 0.05},
            {'component': 'M2', 'marginal_gain': 0.03},
            {'component': 'pruned_other', 'retained': False},
        ]
        self.assertEqual(plan_chk.check(gap, rq, p_all_cov, campaign=camp)['status'], 'structurally_reviewable')

        # R4_1b: empty list/dict primary key falls back to alias; non-empty/string invalid format still rejected
        for empty_val in ([], {}):
            p_shadow = copy.deepcopy(base)
            p_shadow['components'] = empty_val
            p_shadow['proposed_modules'] = ['M1', 'M2', 'M3']
            p_shadow['experiments'] = [e for e in p_shadow['experiments'] if e['role'] != 'ablation']
            p_shadow['parsimony_audit'].pop('ablation_over_simplest_baseline', None)
            p_shadow['parsimony_audit'].pop('component_justifications', None)
            rep_sh = plan_chk.check(gap, rq, p_shadow, campaign=camp)
            self.assertEqual(rep_sh['status'], 'invalid')
            self.assertIn('plan:parsimony_missing_ablation_experiment', rep_sh['errors'])
            self.assertIn('plan:parsimony_missing_component_justifications', rep_sh['errors'])

        p_empty_str = copy.deepcopy(base)
        p_empty_str['components'] = ''
        p_empty_str['proposed_modules'] = ['M1', 'M2', 'M3']
        rep_es = plan_chk.check(gap, rq, p_empty_str, campaign=camp)
        self.assertEqual(rep_es['status'], 'invalid')
        self.assertIn('plan:parsimony_invalid_components_format', rep_es['errors'])

        # R4_2: %\b boundary fix for space-delimited percentage strings
        self.assertEqual(plan_chk._analyze_string_ablation('5.2% macro-F1 over simplest baseline', 'higher'), (True, False))
        self.assertEqual(plan_chk._analyze_string_ablation('0.00% macro-F1 over simplest baseline', 'higher'), (True, True))

        p_pct_ok = copy.deepcopy(base)
        p_pct_ok['parsimony_audit']['ablation_over_simplest_baseline'] = '5.2% macro-F1 over simplest baseline'
        p_pct_ok['parsimony_audit']['component_justifications'][0]['marginal_gain'] = '5.2% macro-F1 over simplest baseline'
        self.assertEqual(plan_chk.check(gap, rq, p_pct_ok, campaign=camp)['status'], 'structurally_reviewable')

        p_pct_zero = copy.deepcopy(base)
        p_pct_zero['parsimony_audit']['ablation_over_simplest_baseline'] = '0.00% macro-F1 over simplest baseline'
        rep_pz = plan_chk.check(gap, rq, p_pct_zero, campaign=camp)
        self.assertEqual(rep_pz['status'], 'invalid')
        self.assertIn('plan:parsimony_nonpositive_marginal_gain', rep_pz['errors'])

        # R4_3: two-word "simplest baseline" in _PROPOSED_VS_SIMPLEST_RE
        bad_vs = 'proposed 0.70 vs simplest baseline 0.75 (+0.05 latency overhead)'
        self.assertEqual(plan_chk._analyze_string_ablation(bad_vs, 'higher'), (True, True))
        self.assertEqual(plan_chk._analyze_string_ablation('proposed 0.07 vs simplest baseline 0.12 ECE', 'lower'), (True, False))

        p_vs_bad = copy.deepcopy(base)
        p_vs_bad['parsimony_audit']['ablation_over_simplest_baseline'] = bad_vs
        rep_vs = plan_chk.check(gap, rq, p_vs_bad, campaign=camp)
        self.assertEqual(rep_vs['status'], 'invalid')
        self.assertIn('plan:parsimony_nonpositive_marginal_gain', rep_vs['errors'])

        # R4_1b, R4_2, R4_3 in gap_pipeline.py
        corpus, _ = gap_pipeline._load_corpus(F19_FIX / 'gap_corpus.json')
        digests = gap_pipeline._load_digests(F19_FIX / 'gap_digests.json')
        for cid, extra in (
            ('GP_SHADOW_LIST', {'proposed_modules': [], 'components': ['M1', 'M2', 'M3']}),
            ('GP_SHADOW_DICT', {'proposed_modules': {}, 'components': ['M1', 'M2', 'M3']}),
            ('GP_SHADOW_STR', {'proposed_modules': '', 'components': ['M1', 'M2', 'M3']}),
            ('GP_PCT_ZERO', {
                'proposed_modules': ['M1', 'M2', 'M3'],
                'simplest_alternative': 'Tuned 2-layer GCN baseline 0.718 macro-F1 across 5 seeds.',
                'ablation_evidence': '0.00% macro-F1 over simplest baseline',
            }),
            ('GP_VS_BAD', {
                'proposed_modules': ['M1', 'M2', 'M3'],
                'simplest_alternative': 'Tuned 2-layer GCN baseline 0.750 macro-F1 across 5 seeds.',
                'ablation_evidence': bad_vs,
            }),
        ):
            cand = {
                'id': cid, 'claim': 'Calibration extension', 'cited_ids': ['P1', 'P2'], 'support_ids': ['P1', 'P2'],
                'cutoff_year': 2026, 'sgha_critics_passed': True, 'engineering_checked': True,
                **extra,
            }
            gp = gap_pipeline.run_pipeline('degree shift', corpus, digests, [cand])
            self.assertEqual(gp['exit_code'], 1, cid)
            self.assertEqual(gp['rejected_gaps'][0]['reason_code'], 'DROP_OVERCOMPLICATED', cid)

        cand_pct_ok = {
            'id': 'GP_PCT_OK', 'claim': 'Calibration extension', 'cited_ids': ['P1', 'P2'], 'support_ids': ['P1', 'P2'],
            'cutoff_year': 2026, 'sgha_critics_passed': True, 'engineering_checked': True,
            'proposed_modules': ['M1', 'M2', 'M3'],
            'simplest_alternative': 'Tuned 2-layer GCN baseline 0.718 macro-F1 across 5 seeds.',
            'ablation_evidence': '5.2% macro-F1 over simplest baseline',
        }
        gp_pct_ok = gap_pipeline.run_pipeline('degree shift', corpus, digests, [cand_pct_ok])
        self.assertEqual(gp_pct_ok['exit_code'], 0, gp_pct_ok['rejected_gaps'])


if __name__ == '__main__':
    unittest.main()

