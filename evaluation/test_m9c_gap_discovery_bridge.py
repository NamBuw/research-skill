"""Unit & structural tests for M9C: Gap Discovery, Triage, Deep Lenses & Idea Seed Bridge."""
from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'research-scientist' / 'scripts'
sys.path.insert(0, str(SCRIPTS))

import check_gap_record
import compare_scorecards
import gap_pipeline
import score_math
import storm_explorer


class StormExplorerM9CTests(unittest.TestCase):
    def test_f27_1_contradiction_coverage_hole_and_assumption_violation_mining(self):
        corpus = [
            {
                'source_id': 'P1',
                'title': 'RRF improves retrieval NDCG in-domain',
                'year': 2022,
                'family': 'same_problem',
                'methods': ['rrf'],
                'settings': ['beir'],
                'metrics': ['ndcg'],
                'regimes': ['in_domain'],
                'assumptions': ['i.i.d. query distribution'],
                'text': 'RRF improves retrieval ndcg in-domain. We assume i.i.d. data and pre-calibrated scores. Zero calibration or adversarial robustness data.',
            },
            {
                'source_id': 'P2',
                'title': 'RRF degrades retrieval NDCG under OOD shift',
                'year': 2024,
                'family': 'cross_setting_analogy',
                'methods': ['rrf'],
                'settings': ['beir'],
                'metrics': ['ndcg'],
                'regimes': ['ood_shift'],
                'text': 'RRF degrades retrieval ndcg under ood shift and fails with noisy inputs.',
            },
            {
                'source_id': 'P3',
                'title': 'RRF retrieval NDCG on MMLU in-domain',
                'year': 2023,
                'family': 'same_problem',
                'methods': ['rrf'],
                'settings': ['mmlu'],
                'metrics': ['ndcg'],
                'regimes': ['in_domain'],
                'text': 'RRF improves ndcg on mmlu in-domain.',
            },
        ]
        res = storm_explorer.explore(
            'RRF calibration under OOD shift',
            corpus,
            max_turns=8,
            target_regime='ood_shift',
        )
        state = res['storm_state']

        # Contradiction matrix: P1 (positive) vs P2 (negative) across regimes
        cm = state['contradiction_matrix']
        self.assertTrue(cm, 'Expected contradiction matrix row between P1 and P2')
        self.assertEqual(cm[0]['conflict_type'], 'cross_regime_conflict')
        self.assertEqual(cm[0]['status'], 'lead')

        # Coverage hole matrix: calibration / ood_shift must be genuine_coverage_hole
        ch = state['coverage_hole_matrix']
        self.assertGreaterEqual(ch['genuine_holes_count'], 1)
        hole_types = {c['hole_type'] for c in ch['uncovered_cells']}
        self.assertIn('genuine_coverage_hole', hole_types)
        # Ensure negated 'calibration' in P1 did NOT mark (rrf, beir, calibration, in_domain) as observed
        obs_tuples = {(c['method'], c['setting'], c['metric'], c['regime']) for c in ch['observed_cells']}
        self.assertNotIn(('rrf', 'beir', 'calibration', 'in_domain'), obs_tuples)

        # Assumption violation links i.i.d. assumption to ood_shift
        av = state['assumption_violations']
        self.assertTrue(av)
        self.assertEqual(av[0]['status'], 'lead')
        self.assertIn('ood_shift', av[0]['target_or_violating_regime'])

    def test_f30_1_chronological_trajectory_never_fabricates_missing_years(self):
        corpus = [
            {'source_id': 'G1', 'title': 'Sparse BM25', 'year': 2016, 'family': 'same_problem',
             'bottleneck': 'Vocabulary mismatch bottleneck on rare entities.', 'text': 'BM25 baseline.'},
            {'source_id': 'G2', 'title': 'Dense DPR', 'year': 2020, 'family': 'same_problem',
             'tradeoff': 'OOD domain shift degradation despite dense recall gains.', 'text': 'Dense retrieval.'},
            {'source_id': 'UNDATED', 'title': 'Undated Note', 'year': None, 'family': 'cross_setting_analogy',
             'text': 'Cross-setting analogy note.'},
        ]
        res = storm_explorer.explore('retrieval OOD shift', corpus, max_turns=4)
        traj = res['storm_state']['research_trajectory']
        self.assertEqual(len(traj['generations']), 2)
        self.assertEqual(traj['generations'][0]['generation'], 'Gen1')
        self.assertEqual(traj['generations'][1]['generation'], 'Gen2')
        self.assertEqual(traj['missing_year_source_ids'], ['UNDATED'])
        self.assertIn('Gen1 (2016)', traj['evolution_summary'])
        self.assertIn('Gen2 (2020)', traj['evolution_summary'])
        self.assertIn('open_root_limit', traj['evolution_summary'])
        self.assertTrue(all(x['status'] == 'lead' for x in traj['open_root_limits']))

        # All undated -> no fabricated years
        undated_res = storm_explorer.explore('topic', [{'source_id': 'U1', 'title': 'U', 'year': None, 'family': 'same_problem', 'text': 'topic'}])
        self.assertEqual(undated_res['research_trajectory']['generations'], [])
        self.assertIn('unavailable', undated_res['research_trajectory']['evolution_summary'].casefold())

    def test_f32_3_p4_isomorphic_transfer_leads_strictly_tagged_lead(self):
        corpus = [
            {'source_id': 'P1', 'title': 'Confidence Calibration', 'year': 2024, 'family': 'cross_setting_analogy',
             'text': 'Cross-setting analogy for calibration uncertainty under shift.'},
        ]
        res = storm_explorer.explore('OOD calibration drift & robustness', corpus, max_turns=8)
        leads = res['storm_state']['isomorphic_transfer_leads']
        self.assertGreaterEqual(len(leads), 1)
        disciplines = {l['discipline'] for l in leads}
        self.assertTrue(disciplines & {'Causal Inference', 'Information Theory', 'Control Theory', 'Optimization'})
        for lead in leads:
            self.assertEqual(lead['evidence_level'], 'lead')
            self.assertTrue(lead['requires_primary_verification'])
            self.assertEqual(lead['supporting_evidence'], [])
            self.assertTrue(lead['suggested_kill_queries'])

    def test_f30_2_failure_first_patterns_and_compact_50_papers(self):
        corpus = [
            {
                'source_id': f'P{i}',
                'title': f'Calibration study {i}',
                'year': 2020 + (i % 5),
                'family': 'cross_setting_analogy' if i % 2 == 0 else 'same_problem',
                'text': 'Calibration error and latency tail spike under OOD shift and quantized deployment.',
            }
            for i in range(55)
        ]
        failures = [
            {'id': 'F1', 'error_type': 'calibration_collapse', 'slice': 'ood_shift', 'baseline': 'TempScale', 'description': 'ECE jumps 3x on OOD shift'},
            {'id': 'F2', 'error_type': 'calibration_collapse', 'slice': 'ood_shift', 'baseline': 'Platt', 'description': 'ECE jumps on OOD shift'},
        ]
        res = storm_explorer.explore('OOD calibration & tail latency', corpus, max_turns=12, failure_cases=failures)
        fps = res['storm_state']['failure_first_patterns']
        self.assertEqual(len(fps), 1)
        self.assertEqual(fps[0]['recurrence_count'], 2)
        self.assertEqual(fps[0]['status'], 'lead')
        self.assertTrue(fps[0]['matched_prior_art_source_ids'])

        summary = storm_explorer.compact_summary(res, Path('/tmp/storm.json'))
        self.assertLess(len(json.dumps(summary, separators=(',', ':'), ensure_ascii=False).encode('utf-8')), 4096)

    def test_coerce_year_rejects_bool_and_nonfinite_json_rejected(self):
        with self.assertRaises(ValueError):
            storm_explorer._coerce_year(True)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'nan.json'
            p.write_text('[{"id": "P1", "year": NaN}]', encoding='utf-8')
            with self.assertRaises(ValueError):
                storm_explorer._load_corpus(p)

    def test_f27_1_target_regime_not_truncated_with_seven_corpus_regimes(self):
        corpus = [{
            'source_id': 'M1', 'title': 'RRF multi-regime benchmark', 'year': 2023, 'family': 'same_problem',
            'methods': ['rrf'], 'settings': ['beir'], 'metrics': ['ndcg'],
            'regimes': ['in_domain', 'zero_shot', 'noisy', 'quantized', 'long_context', 'low_resource', 'adversarial'],
            'text': 'Evaluates RRF across 7 regimes.',
        }]
        res = storm_explorer.explore('RRF under ood_shift', corpus, target_regime='ood_shift')
        ch = res['coverage_hole_matrix']
        self.assertEqual(ch['axes']['regimes'][0], 'ood_shift')
        ood_cells = [c for c in ch['uncovered_cells'] if c['regime'] == 'ood_shift']
        self.assertTrue(ood_cells, 'Expected target_regime=ood_shift to appear in uncovered_cells')
        self.assertEqual(ood_cells[0]['hole_type'], 'genuine_coverage_hole')


class GapPipelineM9CTests(unittest.TestCase):
    def _base(self):
        corpus = {
            'P1': {
                'id': 'P1', 'source': 'openalex', 'family': 'same_problem', 'year': 2021,
                'published_date': '2021-05-01', 'title': 'Dense Retrieval Latency',
                'abstract': 'Measures in-domain latency.', 'text': 'Assumes stationary queries.',
                'retraction_status': 'clean', 'methods': ['dense'], 'settings': ['beir'], 'metrics': ['latency'], 'regimes': ['in_domain'],
            },
            'P2': {
                'id': 'P2', 'source': 'arxiv', 'family': 'cross_setting_analogy', 'year': 2024,
                'published_date': '2024-03-01', 'title': 'Vision Calibration Shift',
                'abstract': 'Vision calibration under shift.', 'text': 'OOD shift degrades calibration.',
                'retraction_status': 'clean', 'methods': ['dense'], 'settings': ['beir'], 'metrics': ['calibration'], 'regimes': ['ood_shift'],
            },
        }
        digests = {
            'P1': {'source_id': 'P1', 'access': 'full_text', 'digest': 'Latency only in-domain.'},
            'P2': {'source_id': 'P2', 'access': 'full_text', 'digest': 'OOD shift miscalibration.'},
        }
        cand = {
            'id': 'G1',
            'claim': 'Calibrated rank fusion under OOD shift remains uncharacterized.',
            'cited_ids': ['P1', 'P2'],
            'support_ids': ['P1', 'P2'],
            'closest_work_ids': ['P1', 'P2'],
            'cutoff_year': 2026,
            'sgha_critics_passed': True,
            'engineering_checked': True,
            'consequence': 'Prevents silent retrieval failures in safety-critical RAG deployment.',
            'why_now_enabler': 'Recent open retrieval logs and calibrated token-level probes enable slice measurement.',
            'root_cause_barrier': 'measurement_gap',
            'so_what_decision_impact': 'decision_changing',
            'durability_12_24m': 'durable_structural_limit',
        }
        return corpus, digests, cand

    def test_f27_5_cross_vocab_drop_already_solved_via_aliases_campaign_and_citation_graph(self):
        corpus, digests, cand = self._base()
        cand_alias = copy.deepcopy(cand)
        cand_alias['claim'] = 'Adaptive multi-list score fusion under OOD shift remains unsolved.'
        cand_alias['mechanism_aliases'] = ['Reciprocal Rank Fusion', 'RRF']

        # Case A: Corpus paper uses alias vocabulary
        corpus_a = copy.deepcopy(corpus)
        corpus_a['K_ALIAS'] = {
            'id': 'K_ALIAS', 'source': 'acl', 'family': 'alternate_vocabulary', 'year': 2024,
            'published_date': '2024-07-01',
            'title': 'Dynamic Reciprocal Rank Fusion for Domain Shift',
            'abstract': 'Uses RRF with shift adaptation.', 'text': '', 'retraction_status': 'clean',
        }
        out_a = gap_pipeline.run_pipeline('fusion', corpus_a, digests, [cand_alias])
        self.assertEqual(out_a['exit_code'], 1)
        self.assertEqual(out_a['rejected_gaps'][0]['reason_code'], 'DROP_ALREADY_SOLVED')
        self.assertIn('K_ALIAS', out_a['rejected_gaps'][0]['evidence_ids'])

        # Case B: search_campaign.py with source_records fallback (like gcn-precedent-campaign.json)
        campaign = {
            'schema': 'research_scientist_search_campaign_v1',
            'query_runs': [{'id': 'Q_ALT', 'family': 'alternate_vocabulary', 'query': 'Reciprocal Rank Fusion OOD'}],
            'source_records': [{
                'source': 'openalex', 'source_id': 'W999', 'year': 2025,
                'title': 'Robust Reciprocal Rank Fusion Across Domains',
                'discovered_by': ['Q_ALT'],
            }],
        }
        out_b = gap_pipeline.run_pipeline('fusion', corpus, digests, [cand_alias], campaign=campaign)
        self.assertEqual(out_b['exit_code'], 1)
        self.assertEqual(out_b['rejected_gaps'][0]['reason_code'], 'DROP_ALREADY_SOLVED')

        # Case C: citation_graph.py neighbor clustered via co-citation with alias title
        cgraph = {
            'schema': 'research_scientist_citation_graph_v1',
            'seeds_resolved': [{'requested': 'P1', 'openalex_id': 'W1', 'title': 'Dense Retrieval Latency', 'year': 2021}],
            'clusters': [{'cluster_id': 'C1', 'size': 2, 'member_ids': ['W1', 'W_SOLVED']}],
            'results': [{
                'openalex_id': 'W_SOLVED', 'title': 'Reciprocal Rank Fusion Stability', 'year': 2025,
                'seed_overlap_count': 2, 'cluster_id': 'C1', 'edges': [{'seed_id': 'W1', 'relation': 'cite'}],
            }],
        }
        out_c = gap_pipeline.run_pipeline('fusion', corpus, digests, [cand_alias], citation_graph=cgraph)
        self.assertEqual(out_c['exit_code'], 1)
        self.assertEqual(out_c['rejected_gaps'][0]['reason_code'], 'DROP_ALREADY_SOLVED')

    def test_f30_4_code_prior_art_blocks_solved_repos(self):
        corpus, digests, cand = self._base()
        cand['code_prior_art'] = [{
            'id': 'CPA1', 'platform': 'github', 'repo_or_url': 'https://github.com/org/rrf-ood',
            'relation': 'direct_equivalent', 'status': 'solved',
        }]
        out = gap_pipeline.run_pipeline('fusion', corpus, digests, [cand])
        self.assertEqual(out['exit_code'], 1)
        self.assertEqual(out['rejected_gaps'][0]['reason_code'], 'DROP_ALREADY_SOLVED')

        # Require code prior art when unscreened
        _, _, cand_unscreened = self._base()
        cand_unscreened['code_prior_art_screened'] = False
        out_req = gap_pipeline.run_pipeline('fusion', corpus, digests, [cand_unscreened], require_code_prior_art=True)
        self.assertEqual(out_req['rejected_gaps'][0]['reason_code'], 'DROP_UNSCREENED_CODE_PRIOR_ART')

    def test_f27_2_tier_ceiling_and_below_target_warning_and_strict_drop(self):
        corpus, digests, cand = self._base()
        # High scaling erasure risk caps ceiling to workshop_incremental_only
        cand['durability_12_24m'] = 'high_scaling_erasure_risk'
        cand['gap_tier_ceiling'] = 'q1_top_tier_potential'  # optimistic override should be capped
        out = gap_pipeline.run_pipeline('fusion', corpus, digests, [cand], target_venue_tier='q1_or_tier_a')
        self.assertEqual(out['exit_code'], 0)
        surv = out['surviving_gaps'][0]
        self.assertEqual(surv['gap_tier_ceiling'], 'workshop_incremental_only')
        self.assertTrue(surv['gap_below_target_venue_tier'])
        self.assertIn('gap_below_target_venue_tier', out['triage_warnings'])

        # Strict triage rejects below-target gaps
        out_strict = gap_pipeline.run_pipeline('fusion', corpus, digests, [cand], target_venue_tier='q1_or_tier_a', strict_triage=True)
        self.assertEqual(out_strict['exit_code'], 1)
        self.assertEqual(out_strict['rejected_gaps'][0]['reason_code'], 'DROP_BELOW_TARGET_VENUE_TIER')

        # Low-impact dead end
        _, _, cand_dead = self._base()
        cand_dead['gap_tier_ceiling'] = 'low_impact_dead_end'
        out_dead = gap_pipeline.run_pipeline('fusion', corpus, digests, [cand_dead], strict_triage=True)
        self.assertEqual(out_dead['rejected_gaps'][0]['reason_code'], 'DROP_LOW_IMPACT_DEAD_END')

    def test_f27_3_scoop_risk_levels_and_zero_fabrication_unknown_disclosure(self):
        corpus, digests, cand = self._base()
        # Missing published_date -> MUST NOT fabricate counts!
        no_date_corpus = copy.deepcopy(corpus)
        for p in no_date_corpus.values():
            p['published_date'] = None
        out_unk = gap_pipeline.run_pipeline('fusion', no_date_corpus, digests, [cand], as_of_date='2026-01-01')
        sr_unk = out_unk['surviving_gaps'][0]['scoop_and_obsolescence_risk']
        self.assertIsNone(sr_unk['recent_preprints_3m'])
        self.assertIsNone(sr_unk['recent_preprints_12m'])
        self.assertFalse(sr_unk['recency_metadata_available'])
        self.assertIn('preprint_recency_metadata_unavailable', sr_unk['unknown_disclosures'])
        self.assertEqual(sr_unk['risk_level'], 'unknown')

        # High scoop risk with >=3 overlapping preprints in 3 months (related to rank fusion, not closing OOD claim)
        hot_corpus = copy.deepcopy(corpus)
        for i in range(3):
            hot_corpus[f'PRE{i}'] = {
                'id': f'PRE{i}', 'source': 'arxiv', 'family': 'same_problem', 'year': 2025,
                'published_date': f'2025-12-0{i + 1}',
                'title': f'Rank Fusion Hyperparameter Scaling {i}', 'abstract': 'Studies rank fusion latency scaling.',
                'text': '', 'retraction_status': 'clean',
            }
        out_hot = gap_pipeline.run_pipeline('fusion', hot_corpus, digests, [cand], as_of_date='2026-01-15')
        sr_hot = out_hot['surviving_gaps'][0]['scoop_and_obsolescence_risk']
        self.assertEqual(sr_hot['risk_level'], 'high_scoop_risk')
        self.assertGreaterEqual(sr_hot['recent_preprints_3m'], 3)

    def test_f27_4_resource_feasibility_and_bool_guard(self):
        corpus, digests, cand = self._base()
        cand['resource_requirements'] = {'gpu_count': 8, 'vram_gb': 80, 'api_budget_usd': 500, 'dataset_access': 'restricted', 'timeline_days': 90}
        avail = {'gpu_count': 1, 'vram_gb': 24, 'api_budget_usd': 50, 'dataset_access': 'public_only', 'timeline_days': 30}
        out = gap_pipeline.run_pipeline('fusion', corpus, digests, [cand], user_resources=avail)
        rf = out['surviving_gaps'][0]['resource_feasibility']
        self.assertEqual(rf['status'], 'infeasible_under_user_resources')
        self.assertTrue(rf['infeasible_under_user_resources'])
        self.assertGreaterEqual(len(rf['blocking_constraints']), 4)

        out_strict = gap_pipeline.run_pipeline('fusion', corpus, digests, [cand], user_resources=avail, strict_triage=True)
        self.assertEqual(out_strict['rejected_gaps'][0]['reason_code'], 'DROP_RESOURCE_INFEASIBLE')

        # Bool trap
        cand_bool = copy.deepcopy(cand)
        cand_bool['resource_requirements'] = {'gpu_count': True}
        with self.assertRaises(ValueError):
            gap_pipeline.run_pipeline('fusion', corpus, digests, [cand_bool], user_resources=avail)

    def test_f28_idea_portfolio_and_pre_mortem_and_seed_bundle_bridge(self):
        corpus, digests, cand = self._base()
        # Tunnel-vision single-idea portfolio rejected
        bad_cand = copy.deepcopy(cand)
        bad_cand['portfolio_mode'] = True
        bad_cand['idea_portfolio'] = [{'id': 'I1', 'angle': 'minimal_fix_f19', 'title': 'Single idea only'}]
        out_bad = gap_pipeline.run_pipeline('fusion', corpus, digests, [bad_cand], require_idea_portfolio=True)
        self.assertEqual(out_bad['rejected_gaps'][0]['reason_code'], 'DROP_TUNNEL_VISION_PORTFOLIO')

        # Bad pre-mortem rejected
        bad_pm = copy.deepcopy(cand)
        bad_pm['pre_mortem'] = {'top_failure_modes': ['Only one'], 'killer_experiment': {'duration_days': 5, 'kill_threshold': ''}, 'pivot_path': ''}
        out_pm = gap_pipeline.run_pipeline('fusion', corpus, digests, [bad_pm], require_pre_mortem=True)
        self.assertEqual(out_pm['rejected_gaps'][0]['reason_code'], 'DROP_INCOMPLETE_PRE_MORTEM')

        # Valid 4-angle portfolio + valid 2-day killer experiment + subfield preset
        good_cand = copy.deepcopy(cand)
        good_cand['idea_portfolio'] = [
            {'id': 'I1', 'angle': 'minimal_fix_f19', 'title': 'Post-hoc temperature scaling on fused logits'},
            {'id': 'I2', 'angle': 'high_novelty_mechanism_q1', 'title': 'Transportability-bounded rank calibration'},
            {'id': 'I3', 'angle': 'benchmark_diagnostic_analysis', 'title': 'BEIR OOD shift calibration failure slice suite'},
            {'id': 'I4', 'angle': 'low_gpu_fallback', 'title': 'CPU-only nonparametric quantile rank calibration'},
        ]
        good_cand['pre_mortem'] = {
            'top_failure_modes': [
                'Gain vanishes when base retrievers are well-tuned',
                'OOD slice variance exceeds calibration delta',
                'Rank ties break quantile estimation stability',
            ],
            'killer_experiment': {'duration_days': 2, 'design': 'Run 3-seed OOD BEIR subset check', 'kill_threshold': 'ECE reduction < 0.01 or NDCG drop > 0.5%'},
            'pivot_path': 'Pivot into a diagnostic benchmark & failure-slice analysis paper.',
        }
        good_cand['subfield_checks'] = {'contamination_check': True, 'multi_prompt_variance': True}
        out_ok = gap_pipeline.run_pipeline(
            'fusion', corpus, digests, [good_cand],
            target_venue_tier='q1_or_tier_a',
            subfield_preset='nlp_llm',
            author_profile={'strength_profile': 'empirical_eval'},
            require_idea_portfolio=True,
            require_pre_mortem=True,
        )
        self.assertEqual(out_ok['exit_code'], 0)
        bundle = out_ok['idea_seed_bundle']
        self.assertEqual(bundle['schema'], 'research_scientist_idea_seed_bundle_v1')
        seed = bundle['seeds'][0]
        self.assertEqual(seed['gap_id'], 'G1')
        self.assertEqual(seed['gap_tier_ceiling'], 'q1_top_tier_potential')
        self.assertEqual(seed['root_cause_barrier'], 'measurement_gap')
        self.assertEqual(seed['subfield_vetting']['preset'], 'nlp_llm')
        self.assertIn('compute_matched_open_weight_baseline', seed['subfield_vetting']['missing_checks'])
        self.assertEqual(len(seed['idea_portfolio']), 4)

        # Verify zero fabrication: ratings strictly null across the 6 idea dimensions,
        # and current score_math safely blocks unrun idea status
        expected_idea_dims = {'evidence_coverage', 'novelty', 'importance', 'answerability', 'feasibility', 'falsifiability'}
        for idea in seed['idea_portfolio']:
            self.assertEqual(idea['object_type'], 'idea')
            self.assertEqual(idea['status'], 'idea')
            self.assertEqual(set(idea['ratings'].keys()), expected_idea_dims)
            self.assertTrue(all(v is None for v in idea['ratings'].values()))
        sc_unrun = score_math.score({
            'status': seed['idea_portfolio'][0]['status'],
            'object_type': seed['idea_portfolio'][0]['object_type'],
            'weights': {'importance': 20, 'novelty': 20, 'soundness': 20, 'evidence': 20, 'transparency': 10, 'clarity': 10},
            'ratings': {'importance': 8, 'novelty': 8, 'soundness': 7, 'evidence': 7, 'transparency': 7, 'clarity': 8},
        })
        self.assertTrue(sc_unrun['submission_readiness']['fatal_gate_triggered'])
        self.assertIn('unrun_idea_results', sc_unrun['submission_readiness']['fatal_reasons'])

    def test_f30_2_failure_cases_gate3_and_f32_lenses(self):
        corpus, digests, cand = self._base()
        cand['trigger'] = 'failure_cases'
        cand['failure_case_ids'] = ['FC1']
        cand['engineering_checked'] = False
        failures = [{'id': 'FC1', 'error_type': 'nan_logits', 'slice': 'long_context', 'engineering_checked': False}]
        out_bug = gap_pipeline.run_pipeline('fusion', corpus, digests, [cand], failure_cases=failures)
        self.assertEqual(out_bug['rejected_gaps'][0]['reason_code'], 'DROP_ENGINEERING_BUG')

        # Unchecked why_now_enabler + evaluation_validity_gap lens
        _, _, cand_ev = self._base()
        cand_ev['why_now_enabler'] = 'TBD'
        cand_ev['type'] = 'evaluation_validity_gap'
        cand_ev['claim'] = 'Leaderboard metric saturation and shortcut exploitation mask OOD retrieval collapse.'
        out_ev = gap_pipeline.run_pipeline('fusion', corpus, digests, [cand_ev])
        surv = out_ev['surviving_gaps'][0]
        self.assertTrue(surv['missing_or_weak_why_now_enabler'])
        self.assertIn('missing_or_weak_why_now_enabler', out_ev['triage_warnings'])
        self.assertEqual(surv['evaluation_validity_gap']['subtype'], 'shortcut_exploitation')

    def test_f31_all_subfield_presets_and_allow_partial_backward_compat(self):
        corpus, digests, cand_ok = self._base()
        for preset in ('nlp_llm', 'cv_multimodal', 'ml_theory', 'ai_systems'):
            out = gap_pipeline.run_pipeline('fusion', corpus, digests, [cand_ok], subfield_preset=preset)
            self.assertEqual(out['exit_code'], 0)
            self.assertEqual(out['idea_seed_bundle']['seeds'][0]['subfield_vetting']['preset'], preset)

        # --allow-partial exits 0 when >=1 survives alongside rejected; default exits 1
        cand_bad = copy.deepcopy(cand_ok)
        cand_bad['id'] = 'G_BAD'
        cand_bad['engineering_checked'] = False
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            cp, dp, kp, sbp = t / 'c.json', t / 'd.json', t / 'k.json', t / 'bundle.json'
            cp.write_text(json.dumps(list(corpus.values())), encoding='utf-8')
            dp.write_text(json.dumps(digests), encoding='utf-8')
            kp.write_text(json.dumps([cand_ok, cand_bad]), encoding='utf-8')

            proc_default = subprocess.run(
                [sys.executable, str(SCRIPTS / 'gap_pipeline.py'), '--corpus', str(cp), '--digests', str(dp), '--candidates', str(kp)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc_default.returncode, 1)

            proc_partial = subprocess.run(
                [sys.executable, str(SCRIPTS / 'gap_pipeline.py'), '--corpus', str(cp), '--digests', str(dp), '--candidates', str(kp), '--allow-partial', '--seed-bundle-out', str(sbp), '--compact'],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc_partial.returncode, 0, proc_partial.stderr)
            self.assertLess(len(proc_partial.stdout.encode('utf-8')), 4096)
            self.assertTrue(sbp.is_file())
            self.assertEqual(json.loads(sbp.read_text(encoding='utf-8'))['schema'], 'research_scientist_idea_seed_bundle_v1')

    def test_gate4_cited_precedent_not_self_killed_via_campaign_or_citation_graph(self):
        corpus, digests, cand = self._base()
        corpus['P1']['doi'] = '10.1234/p1'
        corpus['P1']['openalex_id'] = 'W1'
        cand['claim'] = 'Dense retrieval latency under OOD shift lacks confidence calibration.'

        campaign = {
            'schema': 'research_scientist_search_campaign_v1',
            'query_runs': [{'id': 'Q1', 'family': 'direct_problem', 'query': 'dense retrieval latency OOD shift'}],
            'combined_results': [{
                'source': 'openalex', 'source_id': 'W1', 'doi': '10.1234/p1',
                'dedup_key': 'doi:10.1234/p1', 'year': 2021,
                'title': 'Dense Retrieval Latency',
                'abstract': 'Dense retrieval latency under OOD shift lacks confidence calibration.',
                'discovered_by': ['Q1'],
            }],
        }
        out_camp = gap_pipeline.run_pipeline('ood', corpus, digests, [cand], campaign=campaign)
        self.assertEqual(out_camp['exit_code'], 0)
        self.assertEqual(out_camp['rejected_gaps'], [])

        cgraph = {
            'schema': 'research_scientist_citation_graph_v1',
            'seeds_resolved': [{'requested': 'P1', 'openalex_id': 'W1', 'doi': '10.1234/p1'}],
            'clusters': [],
            'results': [{'openalex_id': 'W1', 'doi': '10.1234/p1', 'year': 2021, 'title': 'Dense Retrieval Latency'}],
        }
        out_cg = gap_pipeline.run_pipeline('ood', corpus, digests, [cand], citation_graph=cgraph)
        self.assertEqual(out_cg['exit_code'], 0)
        self.assertEqual(out_cg['rejected_gaps'], [])

    def test_gate4_arxiv_version_and_url_prefixed_id_normalization_and_negative_control(self):
        self.assertEqual(gap_pipeline._norm_arxiv('arXiv:2301.00001v2'), '2301.00001')
        self.assertEqual(gap_pipeline._norm_arxiv('https://arxiv.org/pdf/2301.00001v1.pdf'), '2301.00001')
        self.assertEqual(gap_pipeline._norm_arxiv('2301.00001v2'), '2301.00001')

        corpus, digests, cand = self._base()
        cand['claim'] = 'Dense retrieval latency under OOD shift remains uncharacterized.'

        # Repro A variants: arXiv version suffix & /pdf/*.pdf URL forms across corpus/campaign/citation_graph
        for corp_ax, camp_rec in (
            ('arXiv:2301.00001v2', {'dedup_key': 'arxiv:2301.00001', 'arxiv_id': '2301.00001'}),
            ('2301.00001', {'arxiv_id': 'arXiv:2301.00001v2'}),
            ('https://arxiv.org/abs/2301.00001v2', {'dedup_key': 'https://arxiv.org/pdf/2301.00001v1.pdf'}),
            ('https://arxiv.org/pdf/2301.00001v1.pdf', {'source_id': 'arXiv:2301.00001v3'}),
        ):
            c_ax = copy.deepcopy(corpus)
            c_ax['P1']['arxiv_id'] = corp_ax
            camp_ax = {
                'query_runs': [{'id': 'Q1', 'family': 'direct_problem', 'query': 'dense retrieval latency'}],
                'combined_results': [{
                    **camp_rec, 'year': 2023, 'title': 'Dense Retrieval Latency', 'discovered_by': ['Q1'],
                }],
            }
            out_ax = gap_pipeline.run_pipeline('t', c_ax, digests, [cand], campaign=camp_ax)
            self.assertEqual(out_ax['exit_code'], 0, f'Failed for {corp_ax} vs {camp_rec}: {out_ax}')
            self.assertEqual(out_ax['rejected_gaps'], [])

        # Repro B variants: URL-prefixed DOI in dedup_key / source_id / id (both directions)
        for corp_field, corp_val, camp_field, camp_val in (
            ('doi', '10.1000/p1', 'dedup_key', 'https://doi.org/10.1000/P1'),
            ('doi', '10.1000/p1', 'source_id', 'https://dx.doi.org/10.1000/P1'),
            ('doi', '10.1000/p1', 'id', 'doi:10.1000/P1'),
            ('dedup_key', 'https://doi.org/10.1000/P1', 'doi', '10.1000/p1'),
        ):
            c_doi = copy.deepcopy(corpus)
            c_doi['P1'][corp_field] = corp_val
            camp_doi = {
                'query_runs': [{'id': 'Q1', 'family': 'direct_problem', 'query': 'dense retrieval latency'}],
                'combined_results': [{
                    camp_field: camp_val, 'year': 2021, 'title': 'Dense Retrieval Latency', 'discovered_by': ['Q1'],
                }],
            }
            out_doi = gap_pipeline.run_pipeline('t', c_doi, digests, [cand], campaign=camp_doi)
            self.assertEqual(out_doi['exit_code'], 0, f'Failed for {corp_val} vs {camp_val}: {out_doi}')
            self.assertEqual(out_doi['rejected_gaps'], [])

        # Symmetric seeds_resolved check via URL-prefixed DOI & versioned arXiv
        c_cg = copy.deepcopy(corpus)
        c_cg['P1']['arxiv_id'] = 'arXiv:2301.00001v2'
        cg = {
            'schema': 'research_scientist_citation_graph_v1',
            'seeds_resolved': [{'requested': 'https://arxiv.org/pdf/2301.00001v1.pdf', 'openalex_id': 'W1'}],
            'clusters': [],
            'results': [{'openalex_id': 'W1', 'dedup_key': 'arxiv:2301.00001', 'year': 2023, 'title': 'Dense Retrieval Latency'}],
        }
        out_cg2 = gap_pipeline.run_pipeline('t', c_cg, digests, [cand], citation_graph=cg)
        self.assertEqual(out_cg2['exit_code'], 0)
        self.assertEqual(out_cg2['rejected_gaps'], [])

        # Negative control: genuinely distinct paper with different arXiv/DOI still triggers DROP_ALREADY_SOLVED
        c_neg = copy.deepcopy(corpus)
        c_neg['P1']['arxiv_id'] = 'arXiv:2301.00001v2'
        c_neg['P1']['doi'] = '10.1000/p1'
        camp_neg = {
            'query_runs': [{'id': 'Q1', 'family': 'direct_problem', 'query': 'dense retrieval latency'}],
            'combined_results': [{
                'dedup_key': 'https://doi.org/10.1000/p999',
                'arxiv_id': 'arXiv:2301.00002v2',
                'year': 2024,
                'title': 'Dense retrieval latency under OOD shift',
                'abstract': 'Dense retrieval latency under OOD shift is fully characterized here.',
                'discovered_by': ['Q1'],
            }],
        }
        out_neg = gap_pipeline.run_pipeline('t', c_neg, digests, [cand], campaign=camp_neg)
        self.assertEqual(out_neg['exit_code'], 1)
        self.assertEqual(out_neg['rejected_gaps'][0]['reason_code'], 'DROP_ALREADY_SOLVED')

    def test_f27_4_proprietary_data_unification_and_negative_or_empty_counterpart_validation(self):
        corpus, digests, cand = self._base()
        c_prop_bool = copy.deepcopy(cand)
        c_prop_bool['resource_requirements'] = {'gpu_count': 1, 'requires_proprietary_data': True}
        for avail in (
            {'gpu_count': 8, 'dataset_access': 'public_only'},
            {'gpu_count': 8},
            {'gpu_count': 8, 'has_proprietary_data': False, 'dataset_access': 'proprietary'},
        ):
            rf = gap_pipeline.run_pipeline('t', corpus, digests, [c_prop_bool], user_resources=avail)['surviving_gaps'][0]['resource_feasibility']
            self.assertTrue(rf['infeasible_under_user_resources'])
            self.assertEqual(rf['status'], 'infeasible_under_user_resources')

        c_prop_str = copy.deepcopy(cand)
        c_prop_str['resource_requirements'] = {'gpu_count': 1, 'dataset_access': 'proprietary'}
        rf_false = gap_pipeline.run_pipeline('t', corpus, digests, [c_prop_str], user_resources={'gpu_count': 8, 'has_proprietary_data': False})['surviving_gaps'][0]['resource_feasibility']
        self.assertTrue(rf_false['infeasible_under_user_resources'])
        rf_ok = gap_pipeline.run_pipeline('t', corpus, digests, [c_prop_str], user_resources={'gpu_count': 8, 'has_proprietary_data': True})['surviving_gaps'][0]['resource_feasibility']
        self.assertFalse(rf_ok['infeasible_under_user_resources'])

        # Negative values & bool with empty counterpart must raise ValueError
        c_neg = copy.deepcopy(cand)
        c_neg['resource_requirements'] = {'gpu_count': -2, 'timeline_days': -5}
        with self.assertRaises(ValueError):
            gap_pipeline.run_pipeline('t', corpus, digests, [c_neg], user_resources={'gpu_count': 1})
        c_bool_empty = copy.deepcopy(cand)
        c_bool_empty['resource_requirements'] = {'gpu_count': True}
        with self.assertRaises(ValueError):
            gap_pipeline.run_pipeline('t', corpus, digests, [c_bool_empty], user_resources={})

    def test_f27_3_mixed_dated_undated_corpus_disclosure_and_invalid_as_of_date(self):
        corpus, digests, cand = self._base()
        mixed = copy.deepcopy(corpus)
        mixed['OLD'] = {'id': 'OLD', 'family': 'same_problem', 'year': 2020, 'published_date': '2020-01-01', 'title': 'Unrelated Topic'}
        mixed['ND1'] = {'id': 'ND1', 'family': 'same_problem', 'year': 2025, 'published_date': None, 'title': 'Rank Fusion Hyperparameter Scaling'}
        sr = gap_pipeline.run_pipeline('t', mixed, digests, [cand], as_of_date='2026-01-15')['surviving_gaps'][0]['scoop_and_obsolescence_risk']
        self.assertIsNone(sr['recent_preprints_3m'])
        self.assertIsNone(sr['recent_preprints_12m'])
        self.assertIsNone(sr['recent_preprint_count'])
        self.assertFalse(sr['recency_metadata_available'])
        self.assertEqual(sr['risk_level'], 'unknown')
        self.assertIn('preprint_recency_metadata_partial_or_unavailable', sr['unknown_disclosures'])

        with self.assertRaises(ValueError):
            gap_pipeline.run_pipeline('t', corpus, digests, [cand], as_of_date='not-a-date')

    def test_trajectory_tree_temporal_cutoff_leak_and_string_year_normalization(self):
        corpus, digests, cand = self._base()
        corpus['P_POST'] = {
            'id': 'P_POST', 'source': 'arxiv', 'family': 'same_problem', 'year': 2027,
            'published_date': '2027-01-01', 'title': 'Future 2027 Paper',
            'tradeoff': '2027 secret tradeoff', 'text': 'Future 2027 method', 'retraction_status': 'clean',
        }
        storm = storm_explorer.explore('rank fusion', [
            {'source_id': 'P1', 'title': 'Dense Retrieval Latency', 'year': 2021, 'family': 'same_problem', 'bottleneck': 'Old limit', 'text': 'Old method'},
            {'source_id': 'P_POST', 'title': 'Future 2027 Paper', 'year': 2027, 'family': 'same_problem', 'tradeoff': '2027 secret tradeoff', 'text': 'Future 2027 method'},
        ])
        c_storm = copy.deepcopy(cand)
        c_storm['cutoff_year'] = 2025
        c_storm['cutoff_date'] = '2025-12-31'
        out_storm = gap_pipeline.run_pipeline('t', corpus, digests, [c_storm], storm_report=storm)
        tt_dump = json.dumps(out_storm['surviving_gaps'][0]['trajectory_tree'])
        self.assertNotIn('2027', tt_dump)
        self.assertNotIn('Gen2', tt_dump)
        self.assertEqual(out_storm['surviving_gaps'][0]['trajectory_tree']['edges'], [])

        # Candidate trajectory_tree with post-cutoff year and empty paper_ids -> DROP_TEMPORAL_LEAK
        c_leak = copy.deepcopy(cand)
        c_leak['cutoff_year'] = 2025
        c_leak['trajectory_tree'] = {
            'generations': [
                {'generation': 'Gen1', 'year': 2022, 'paper_ids': ['P1'], 'method_or_paradigm': 'A', 'bottleneck_or_tradeoff': 'X'},
                {'generation': 'Gen2', 'year': 2027, 'paper_ids': [], 'method_or_paradigm': 'B', 'bottleneck_or_tradeoff': 'Y'},
            ],
            'open_root_limit': 'Z',
        }
        out_leak = gap_pipeline.run_pipeline('t', corpus, digests, [c_leak])
        self.assertEqual(out_leak['rejected_gaps'][0]['reason_code'], 'DROP_TEMPORAL_LEAK')

        # String year coerced to int in exported idea_seed_bundle
        c_str_yr = copy.deepcopy(cand)
        c_str_yr['cutoff_year'] = 2025
        c_str_yr['trajectory_tree'] = {
            'generations': [{'generation': 'Gen1', 'year': '2022', 'method_or_paradigm': 'A', 'bottleneck_or_tradeoff': 'X'}],
            'open_root_limit': 'Z',
        }
        out_str = gap_pipeline.run_pipeline('t', corpus, digests, [c_str_yr])
        exp_tt = out_str['idea_seed_bundle']['seeds'][0]['trajectory_tree']
        self.assertIs(type(exp_tt['generations'][0]['year']), int)
        self.assertEqual(exp_tt['generations'][0]['year'], 2022)

    def test_f28_duplicate_ideas_null_failure_modes_and_nan_ratings(self):
        corpus, digests, cand = self._base()
        c_dup = copy.deepcopy(cand)
        c_dup['portfolio_mode'] = True
        c_dup['idea_portfolio'] = [
            {'id': 'I1', 'angle': 'minimal_fix_f19', 'title': 'Sparse calibration adapter for OOD retrieval'},
            {'id': 'I2', 'angle': 'high_novelty_mechanism_q1', 'title': 'Sparse calibration adapter for OOD retrieval'},
            {'id': 'I3', 'angle': 'low_gpu_fallback', 'title': 'Sparse calibration adapter for OOD retrieval'},
        ]
        out_dup = gap_pipeline.run_pipeline('t', corpus, digests, [c_dup], require_idea_portfolio=True, strict_triage=True)
        self.assertEqual(out_dup['rejected_gaps'][0]['reason_code'], 'DROP_TUNNEL_VISION_PORTFOLIO')

        c_null_fm = copy.deepcopy(cand)
        c_null_fm['pre_mortem'] = {
            'top_failure_modes': [None, None, None],
            'killer_experiment': {'duration_days': 2, 'kill_threshold': 'ECE < 0.01'},
            'pivot_path': 'Pivot to diagnostic.',
        }
        out_fm = gap_pipeline.run_pipeline('t', corpus, digests, [c_null_fm], require_pre_mortem=True)
        self.assertEqual(out_fm['rejected_gaps'][0]['reason_code'], 'DROP_INCOMPLETE_PRE_MORTEM')

        c_nan_r = copy.deepcopy(cand)
        c_nan_r['idea_portfolio'] = [
            {'id': 'I1', 'angle': 'minimal_fix_f19', 'title': 'Idea one', 'ratings': {'novelty': float('nan')}},
        ]
        with self.assertRaises(ValueError):
            gap_pipeline.run_pipeline('t', corpus, digests, [c_nan_r])

    def test_f30_2_dangling_or_unverified_failure_case_ids_and_f30_4_code_prior_art_ids(self):
        corpus, digests, cand = self._base()
        c_fc = copy.deepcopy(cand)
        c_fc['trigger'] = 'failure_cases'
        c_fc['failure_case_ids'] = ['FC1']
        # Unverified failure case entry -> DROP_ENGINEERING_BUG
        out_unv = gap_pipeline.run_pipeline('t', corpus, digests, [c_fc], failure_cases=[{'id': 'FC1', 'error_type': 'oom', 'slice': 'long_context'}])
        self.assertEqual(out_unv['rejected_gaps'][0]['reason_code'], 'DROP_ENGINEERING_BUG')
        # Missing failure_cases -> DROP_ENGINEERING_BUG
        out_miss = gap_pipeline.run_pipeline('t', corpus, digests, [c_fc], failure_cases=None)
        self.assertEqual(out_miss['rejected_gaps'][0]['reason_code'], 'DROP_ENGINEERING_BUG')
        # Verified failure case entry -> passes
        out_ok = gap_pipeline.run_pipeline('t', corpus, digests, [c_fc], failure_cases=[{'id': 'FC1', 'error_type': 'oom', 'slice': 'long_context', 'engineering_checked': True}])
        self.assertEqual(out_ok['exit_code'], 0)

        # code_prior_art_ids linking to global solved repo -> DROP_ALREADY_SOLVED
        c_cpa = copy.deepcopy(cand)
        c_cpa['code_prior_art_ids'] = ['CPA_SOLVED']
        out_cpa = gap_pipeline.run_pipeline('t', corpus, digests, [c_cpa], code_prior_art=[
            {'id': 'CPA_SOLVED', 'platform': 'github', 'repo_or_url': 'https://github.com/x/y', 'title': 'AlphaBetaRepo', 'relation': 'direct_equivalent', 'status': 'solved'},
        ])
        self.assertEqual(out_cpa['rejected_gaps'][0]['reason_code'], 'DROP_ALREADY_SOLVED')

        # partial_implementation sets overlap_found=True
        c_part = copy.deepcopy(cand)
        c_part['code_prior_art'] = [{'id': 'CPA_P', 'platform': 'github', 'repo_or_url': 'https://github.com/x/p', 'relation': 'partial_implementation', 'status': 'partial'}]
        out_part = gap_pipeline.run_pipeline('t', corpus, digests, [c_part])
        self.assertTrue(out_part['surviving_gaps'][0]['code_prior_art_summary']['overlap_found'])

    def test_gate4_bare_arxiv_doi_openalex_and_bare_versioned_arxiv_normalization_with_negative_controls(self):
        corpus, digests, cand = self._base()
        cand['claim'] = 'Dense retrieval latency under OOD shift remains uncharacterized.'

        # Bug 1: bare 10.48550/arXiv.* in dedup_key / source_id / id / cited_ids / seeds_resolved.requested
        for corp_field, corp_val, camp_rec in (
            ('dedup_key', '10.48550/arXiv.2301.00001v2', {'dedup_key': 'arxiv:2301.00001'}),
            ('arxiv_id', 'arxiv:2301.00001', {'dedup_key': '10.48550/arXiv.2301.00001v2'}),
            ('source_id', '10.48550/arXiv.2301.00001v2', {'arxiv_id': '2301.00001'}),
            ('id', '10.48550/arXiv.2301.00001v2', {'dedup_key': 'arxiv:2301.00001'}),
        ):
            c_b1 = copy.deepcopy(corpus)
            c_b1['P1'][corp_field] = corp_val
            camp_b1 = {
                'query_runs': [{'id': 'Q1', 'family': 'direct_problem', 'query': 'dense retrieval latency'}],
                'combined_results': [{**camp_rec, 'year': 2023, 'title': 'Dense Retrieval Latency', 'discovered_by': ['Q1']}],
            }
            out_b1 = gap_pipeline.run_pipeline('t', c_b1, digests, [cand], campaign=camp_b1)
            self.assertEqual(out_b1['exit_code'], 0, f'Bug1 failed for {corp_field}={corp_val}: {out_b1}')
            self.assertEqual(out_b1['rejected_gaps'], [])

        # Bug 1b: seeds_resolved.requested with bare 10.48550/arXiv.2301.00001v2
        c_b1_cg = copy.deepcopy(corpus)
        c_b1_cg['P1']['arxiv_id'] = 'arxiv:2301.00001'
        cg_b1 = {
            'schema': 'research_scientist_citation_graph_v1',
            'seeds_resolved': [{'requested': '10.48550/arXiv.2301.00001v2', 'openalex_id': 'W99'}],
            'clusters': [],
            'results': [{'openalex_id': 'W99', 'year': 2023, 'title': 'Dense Retrieval Latency'}],
        }
        out_b1_cg = gap_pipeline.run_pipeline('t', c_b1_cg, digests, [cand], citation_graph=cg_b1)
        self.assertEqual(out_b1_cg['exit_code'], 0, out_b1_cg)
        self.assertEqual(out_b1_cg['rejected_gaps'], [])

        # Bug 1c: direct cited_ids with bare 10.48550/arXiv.2301.00001v2
        cand_b1_cited = copy.deepcopy(cand)
        cand_b1_cited['cited_ids'] = ['10.48550/arXiv.2301.00001v2', 'P2']
        cand_b1_cited['support_ids'] = ['P1', 'P2']
        d_b1_cited = {**digests, '10.48550/arXiv.2301.00001v2': {'access': 'full_text', 'digest': 'x'}}
        out_b1_cited = gap_pipeline.run_pipeline('t', corpus, d_b1_cited, [cand_b1_cited], campaign={
            'query_runs': [{'id': 'Q1', 'family': 'direct_problem', 'query': 'dense retrieval latency'}],
            'combined_results': [{'dedup_key': 'arxiv:2301.00001', 'year': 2023, 'title': 'Dense Retrieval Latency', 'discovered_by': ['Q1']}],
        })
        self.assertEqual(out_b1_cited['exit_code'], 0, out_b1_cited)
        self.assertEqual(out_b1_cited['rejected_gaps'], [])

        # Bug 2: OpenAlex openalex:w* dedup_key and https://openalex.org/W* URLs
        c_oa = copy.deepcopy(corpus)
        c_oa['P1']['openalex_id'] = 'W12345'
        out_oa_camp = gap_pipeline.run_pipeline('t', c_oa, digests, [cand], campaign={
            'query_runs': [{'id': 'Q1', 'family': 'direct_problem', 'query': 'dense retrieval latency'}],
            'combined_results': [{'dedup_key': 'openalex:w12345', 'year': 2023, 'title': 'Dense Retrieval Latency', 'discovered_by': ['Q1']}],
        })
        self.assertEqual(out_oa_camp['exit_code'], 0, out_oa_camp)
        self.assertEqual(out_oa_camp['rejected_gaps'], [])

        out_oa_cg = gap_pipeline.run_pipeline('t', c_oa, digests, [cand], citation_graph={
            'schema': 'research_scientist_citation_graph_v1',
            'seeds_resolved': [{'requested': 'https://openalex.org/W12345', 'openalex_id': 'W12345'}],
            'clusters': [],
            'results': [{'openalex_id': 'https://openalex.org/W12345', 'year': 2023, 'title': 'Dense Retrieval Latency'}],
        })
        self.assertEqual(out_oa_cg['exit_code'], 0, out_oa_cg)
        self.assertEqual(out_oa_cg['rejected_gaps'], [])

        c_oa_url = copy.deepcopy(corpus)
        c_oa_url['P1']['openalex_id'] = 'https://openalex.org/W12345'
        out_oa_rev = gap_pipeline.run_pipeline('t', c_oa_url, digests, [cand], campaign={
            'query_runs': [{'id': 'Q1', 'family': 'direct_problem', 'query': 'dense retrieval latency'}],
            'combined_results': [{'openalex_id': 'W12345', 'year': 2023, 'title': 'Dense Retrieval Latency', 'discovered_by': ['Q1']}],
        })
        self.assertEqual(out_oa_rev['exit_code'], 0, out_oa_rev)
        self.assertEqual(out_oa_rev['rejected_gaps'], [])

        # Bug 3: bare versioned arXiv IDs (new & old-style) in dedup_key / cited_ids
        for bare_ax, canon_ax in (('2301.00001v2', 'arxiv:2301.00001'), ('hep-th/9901001v2', 'arxiv:hep-th/9901001')):
            c_b3 = copy.deepcopy(corpus)
            c_b3['P1']['dedup_key'] = bare_ax
            out_b3 = gap_pipeline.run_pipeline('t', c_b3, digests, [cand], campaign={
                'query_runs': [{'id': 'Q1', 'family': 'direct_problem', 'query': 'dense retrieval latency'}],
                'combined_results': [{'dedup_key': canon_ax, 'year': 2023, 'title': 'Dense Retrieval Latency', 'discovered_by': ['Q1']}],
            })
            self.assertEqual(out_b3['exit_code'], 0, f'Bug3 failed for {bare_ax}: {out_b3}')
            self.assertEqual(out_b3['rejected_gaps'], [])

            cand_b3 = copy.deepcopy(cand)
            cand_b3['cited_ids'] = [bare_ax, 'P2']
            cand_b3['support_ids'] = ['P1', 'P2']
            d_b3 = {**digests, bare_ax: {'access': 'full_text', 'digest': 'x'}}
            out_b3_cited = gap_pipeline.run_pipeline('t', corpus, d_b3, [cand_b3], campaign={
                'query_runs': [{'id': 'Q1', 'family': 'direct_problem', 'query': 'dense retrieval latency'}],
                'combined_results': [{'dedup_key': canon_ax, 'year': 2023, 'title': 'Dense Retrieval Latency', 'discovered_by': ['Q1']}],
            })
            self.assertEqual(out_b3_cited['exit_code'], 0, f'Bug3 cited_ids failed for {bare_ax}: {out_b3_cited}')
            self.assertEqual(out_b3_cited['rejected_gaps'], [])

        # Malformed / non-colliding boundary checks
        for bad_val in ('', None, 'v2', 'doi:', 'arxiv:', 'openalex:', 'https://openalex.org/'):
            variants = gap_pipeline._ref_variants(bad_val)
            self.assertNotIn('', variants)
            self.assertLessEqual(len(variants), 1)
        self.assertEqual(set(gap_pipeline._ref_variants('doi:')) & set(gap_pipeline._ref_variants('10.1000/p1')), set())
        self.assertEqual(set(gap_pipeline._ref_variants('arxiv:')) & set(gap_pipeline._ref_variants('2301.00001')), set())
        self.assertEqual(set(gap_pipeline._ref_variants('openalex:')) & set(gap_pipeline._ref_variants('W12345')), set())
        self.assertEqual(set(gap_pipeline._ref_variants('https://openalex.org/')) & set(gap_pipeline._ref_variants('W12345')), set())
        self.assertEqual(set(gap_pipeline._ref_variants('2301.00001')) & set(gap_pipeline._ref_variants('2301.000011')), set())

        # Negative controls: genuinely distinct papers still trigger DROP_ALREADY_SOLVED
        c_neg = copy.deepcopy(corpus)
        c_neg['P1']['openalex_id'] = 'W12345'
        c_neg['P1']['dedup_key'] = '10.48550/arXiv.2301.00001v2'
        for neg_rec in (
            {'openalex_id': 'W99999', 'dedup_key': 'openalex:w99999'},
            {'dedup_key': '10.48550/arXiv.2301.00002'},
            {'dedup_key': '2301.00002v2'},
        ):
            out_neg = gap_pipeline.run_pipeline('t', c_neg, digests, [cand], campaign={
                'query_runs': [{'id': 'Q1', 'family': 'direct_problem', 'query': 'dense retrieval latency'}],
                'combined_results': [{
                    **neg_rec, 'year': 2024, 'title': 'Dense retrieval latency under OOD shift',
                    'abstract': 'Dense retrieval latency under OOD shift is fully characterized here.',
                    'discovered_by': ['Q1'],
                }],
            })
            self.assertEqual(out_neg['exit_code'], 1, f'Negative control {neg_rec} failed to drop!')
            self.assertEqual(out_neg['rejected_gaps'][0]['reason_code'], 'DROP_ALREADY_SOLVED')

    def test_python_api_nonfinite_marginal_gain_and_survival_score_rejected(self):
        corpus, digests, cand = self._base()
        for bad_num in (float('nan'), float('inf'), float('-inf')):
            c_mg = copy.deepcopy(cand)
            c_mg['ablation_evidence'] = {'marginal_gain': bad_num}
            out_mg = gap_pipeline.run_pipeline('t', corpus, digests, [c_mg])
            self.assertEqual(out_mg['exit_code'], 1)
            self.assertEqual(out_mg['rejected_gaps'][0]['reason_code'], 'DROP_OVERCOMPLICATED')

            c_bp = copy.deepcopy(cand)
            c_bp['ablation_evidence'] = {'baseline_score': 0.5, 'proposed_score': bad_num}
            out_bp = gap_pipeline.run_pipeline('t', corpus, digests, [c_bp])
            self.assertEqual(out_bp['exit_code'], 1)
            self.assertEqual(out_bp['rejected_gaps'][0]['reason_code'], 'DROP_OVERCOMPLICATED')

            c_sc = copy.deepcopy(cand)
            c_sc['sgha_critics'] = {'survival_score': bad_num}
            out_sc = gap_pipeline.run_pipeline('t', corpus, digests, [c_sc])
            self.assertEqual(out_sc['exit_code'], 1)
            self.assertEqual(out_sc['rejected_gaps'][0]['reason_code'], 'DROP_SGHA_CRITIC_REJECT')

            c_cf = copy.deepcopy(cand)
            c_cf['sgha_critics'] = {'survival_score': 0.9, 'critic_confidence': bad_num}
            out_cf = gap_pipeline.run_pipeline('t', corpus, digests, [c_cf])
            self.assertEqual(out_cf['exit_code'], 1)
            self.assertEqual(out_cf['rejected_gaps'][0]['reason_code'], 'DROP_SGHA_CRITIC_REJECT')

    def test_bool_and_nonfinite_numeric_fields_rejected_python_api_and_cli(self):
        corpus, digests, cand = self._base()
        # Python API bool + non-finite checks across sgha_critics, ablation_evidence (<3 modules), and measured_delta
        py_cases = [
            ('sgha_survival_False', {'sgha_critics': {'survival_score': False}}, 'DROP_SGHA_CRITIC_REJECT'),
            ('sgha_survival_True', {'sgha_critics': {'survival_score': True}}, 'DROP_SGHA_CRITIC_REJECT'),
            ('sgha_conf_False', {'sgha_critics': {'survival_score': 0.9, 'critic_confidence': False}}, 'DROP_SGHA_CRITIC_REJECT'),
            ('sgha_conf_True', {'sgha_critics': {'survival_score': 0.9, 'critic_confidence': True}}, 'DROP_SGHA_CRITIC_REJECT'),
            ('ablation_mg_False', {'ablation_evidence': {'marginal_gain': False}}, 'DROP_OVERCOMPLICATED'),
            ('ablation_mg_True', {'ablation_evidence': {'marginal_gain': True}}, 'DROP_OVERCOMPLICATED'),
            ('ablation_bs_False_with_ps', {'ablation_evidence': {'baseline_score': False, 'proposed_score': 0.9}}, 'DROP_OVERCOMPLICATED'),
            ('ablation_bs_False_alone', {'ablation_evidence': {'baseline_score': False}}, 'DROP_OVERCOMPLICATED'),
            ('ablation_ps_True', {'ablation_evidence': {'baseline_score': 0.5, 'proposed_score': True}}, 'DROP_OVERCOMPLICATED'),
            ('measured_delta_nan', {'measured_delta': float('nan')}, 'DROP_PROBLEM_INFLATION'),
            ('measured_delta_inf', {'measured_delta': float('inf')}, 'DROP_PROBLEM_INFLATION'),
            ('measured_delta_ninf', {'measured_delta': float('-inf')}, 'DROP_PROBLEM_INFLATION'),
            ('measured_delta_True', {'measured_delta': True}, 'DROP_PROBLEM_INFLATION'),
            ('measured_delta_False', {'measured_delta': False}, 'DROP_PROBLEM_INFLATION'),
        ]
        for label, patch, expected_code in py_cases:
            c = copy.deepcopy(cand)
            c.update(patch)
            out = gap_pipeline.run_pipeline('t', corpus, digests, [c])
            self.assertEqual(out['exit_code'], 1, f'{label} unexpectedly passed: {out}')
            self.assertEqual(out['rejected_gaps'][0]['reason_code'], expected_code, f'{label}: {out}')

        # Direct _evaluate_candidate_triage defense-in-depth for measured_delta (both with and without so_what)
        structured = gap_pipeline._mine_structured_matrices(corpus)
        for bad_delta in (float('nan'), float('inf'), float('-inf'), True, False):
            for preset_so_what in (None, 'decision_changing'):
                c_tr = copy.deepcopy(cand)
                c_tr['measured_delta'] = bad_delta
                if preset_so_what is None:
                    c_tr.pop('so_what_decision_impact', None)
                else:
                    c_tr['so_what_decision_impact'] = preset_so_what
                _, _, triage_rej, _ = gap_pipeline._evaluate_candidate_triage(
                    c_tr, 'G1', ['P1', 'P2'], corpus, digests,
                    storm_report=None, structured_mining=structured, failure_patterns=[],
                    code_prior_art=None, target_venue_tier=None, user_resources=None,
                    author_profile=None, subfield_preset=None, as_of_date=None,
                    cutoff_date=None, cutoff_year=2026, strict_triage=False,
                    require_idea_portfolio=False, require_pre_mortem=False, require_code_prior_art=False,
                )
                self.assertIsNotNone(triage_rej, f'Direct triage bypassed for {bad_delta!r}')
                self.assertEqual(triage_rej[0], 'DROP_PROBLEM_INFLATION')

        # Positive control: valid finite numeric values continue to pass
        c_ok = copy.deepcopy(cand)
        c_ok['measured_delta'] = 0.05
        c_ok['ablation_evidence'] = {'marginal_gain': 0.05}
        c_ok['sgha_critics'] = {'survival_score': 0.9, 'critic_confidence': 0.85}
        out_ok = gap_pipeline.run_pipeline('t', corpus, digests, [c_ok])
        self.assertEqual(out_ok['exit_code'], 0, out_ok)
        self.assertEqual(out_ok['rejected_gaps'], [])

        # CLI JSON true/false tests
        cli_cases = [
            ('cli_sgha_survival_false', {'sgha_critics': {'survival_score': False}}, 'DROP_SGHA_CRITIC_REJECT'),
            ('cli_sgha_survival_true', {'sgha_critics': {'survival_score': True}}, 'DROP_SGHA_CRITIC_REJECT'),
            ('cli_sgha_conf_false', {'sgha_critics': {'survival_score': 0.9, 'critic_confidence': False}}, 'DROP_SGHA_CRITIC_REJECT'),
            ('cli_sgha_conf_true', {'sgha_critics': {'survival_score': 0.9, 'critic_confidence': True}}, 'DROP_SGHA_CRITIC_REJECT'),
            ('cli_ablation_mg_false', {'ablation_evidence': {'marginal_gain': False}}, 'DROP_OVERCOMPLICATED'),
            ('cli_ablation_mg_true', {'ablation_evidence': {'marginal_gain': True}}, 'DROP_OVERCOMPLICATED'),
            ('cli_ablation_bs_false', {'ablation_evidence': {'baseline_score': False, 'proposed_score': 0.9}}, 'DROP_OVERCOMPLICATED'),
            ('cli_measured_delta_true', {'measured_delta': True}, 'DROP_PROBLEM_INFLATION'),
            ('cli_measured_delta_false', {'measured_delta': False}, 'DROP_PROBLEM_INFLATION'),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            corpus_p = tmp_dir / 'corpus.json'
            digests_p = tmp_dir / 'digests.json'
            corpus_p.write_text(json.dumps(list(corpus.values())), encoding='utf-8')
            digests_p.write_text(json.dumps(digests), encoding='utf-8')
            for label, patch, expected_code in cli_cases:
                c_cli = copy.deepcopy(cand)
                c_cli.update(patch)
                cands_p = tmp_dir / f'{label}.json'
                cands_p.write_text(json.dumps([c_cli]), encoding='utf-8')
                proc = subprocess.run(
                    [
                        sys.executable, str(SCRIPTS / 'gap_pipeline.py'),
                        '--topic', 't',
                        '--corpus', str(corpus_p),
                        '--digests', str(digests_p),
                        '--candidates', str(cands_p),
                    ],
                    capture_output=True, text=True, check=False,
                )
                self.assertNotEqual(proc.returncode, 0, f'{label} CLI unexpectedly exited 0: {proc.stdout}')
                self.assertEqual(proc.returncode, 1, f'{label} CLI stderr={proc.stderr}')
                payload = json.loads(proc.stdout)
                self.assertEqual(payload['rejected_gaps'][0]['reason_code'], expected_code, f'{label}: {payload}')


class CheckGapRecordM9CTests(unittest.TestCase):
    def _base_record(self):
        return json.loads((ROOT / 'research-scientist' / 'references' / 'gap-record.schema-example.json').read_text(encoding='utf-8'))

    def test_legacy_record_remains_valid_and_code_prior_art_enforced(self):
        rec = self._base_record()
        self.assertTrue(check_gap_record.check(rec)['valid_structure'])

        rec['code_prior_art'] = [{
            'id': 'CPA1', 'platform': 'github', 'repo_or_url': 'https://github.com/org/repo',
            'relation': 'direct_equivalent', 'status': 'solved',
        }]
        rec['candidates'][0]['code_prior_art_ids'] = ['CPA1']
        res = check_gap_record.check(rec)
        self.assertFalse(res['valid_structure'])
        self.assertIn('candidates:G1:code_prior_art_direct_equivalent_closes_gap', res['errors'])

    def test_f28_f30_f32_presence_triggered_checks(self):
        rec = self._base_record()
        rec['failure_cases'] = [{'id': 'FC1', 'error_type': 'oom', 'slice': 'long_context', 'engineering_checked': False}]
        cand = rec['candidates'][0]
        cand['trigger'] = 'failure_cases'
        cand['failure_case_ids'] = ['FC1']
        cand['engineering_status'] = 'implementation_checked'
        cand['root_cause_barrier'] = 'compute_infra_barrier'
        cand['durability_12_24m'] = 'high_scaling_erasure_risk'
        cand['portfolio_mode'] = True
        cand['idea_portfolio'] = [{'id': 'I1', 'angle': 'minimal_fix_f19', 'summary': 'Only one'}]
        cand['pre_mortem'] = {
            'top_failure_modes': ['Only one mode'],
            'killer_experiment': {'duration_days': True, 'kill_threshold': ''},
            'pivot_path': '',
        }
        cand['trajectory_tree'] = {
            'generations': [
                {'generation': 'Gen1', 'year': 2024, 'method_or_paradigm': 'A', 'bottleneck_or_tradeoff': 'X'},
                {'generation': 'Gen2', 'year': 2020, 'method_or_paradigm': 'B', 'bottleneck_or_tradeoff': 'Y'},
            ],
            'open_root_limit': 'Z',
        }
        res = check_gap_record.check(rec)
        self.assertFalse(res['valid_structure'])
        self.assertIn('candidates:G1:engineering_failure_unresolved', res['errors'])
        self.assertIn('candidates:G1:tunnel_vision_idea_portfolio', res['errors'])
        self.assertIn('candidates:G1:pre_mortem_insufficient_failure_modes', res['errors'])
        self.assertIn('candidates:G1:pre_mortem_invalid_killer_experiment', res['errors'])
        self.assertIn('candidates:G1:pre_mortem_missing_pivot_path', res['errors'])
        self.assertIn('candidates:G1:trajectory_tree:generations[1]:non_monotonic_year', res['errors'])
        self.assertIn('candidates:G1:missing_or_weak_why_now_enabler', res['warnings'])
        self.assertIn('candidates:G1:high_scaling_erasure_risk', res['warnings'])

    def test_unhashable_enum_fields_duplicate_portfolio_and_unverified_failure_case_ids(self):
        # Unhashable non-string enum fields must emit structured errors without TypeError crash
        rec_unhash = self._base_record()
        c0 = rec_unhash['candidates'][0]
        c0['root_cause_barrier'] = ['measurement_gap']
        c0['gap_tier_ceiling'] = ['q1_top_tier_potential']
        c0['so_what_decision_impact'] = {'a': 1}
        c0['durability_12_24m'] = ['durable_structural_limit']
        c0['evaluation_validity_gap'] = ['shortcut_exploitation']
        res_unhash = check_gap_record.check(rec_unhash)
        self.assertFalse(res_unhash['valid_structure'])
        self.assertIn('candidates:G1:invalid_root_cause_barrier', res_unhash['errors'])
        self.assertIn('candidates:G1:invalid_gap_tier_ceiling', res_unhash['errors'])
        self.assertIn('candidates:G1:invalid_so_what_decision_impact', res_unhash['errors'])
        self.assertIn('candidates:G1:invalid_durability_12_24m', res_unhash['errors'])
        self.assertIn('candidates:G1:evaluation_validity_gap_must_be_object', res_unhash['errors'])

        # Duplicate ideas claiming 3 angles -> tunnel_vision_idea_portfolio
        rec_dup = self._base_record()
        rec_dup['candidates'][0]['portfolio_mode'] = True
        rec_dup['candidates'][0]['idea_portfolio'] = [
            {'id': 'I1', 'angle': 'minimal_fix_f19', 'title': 'Sparse calibration adapter for OOD retrieval'},
            {'id': 'I2', 'angle': 'high_novelty_mechanism_q1', 'title': 'Sparse calibration adapter for OOD retrieval'},
            {'id': 'I3', 'angle': 'low_gpu_fallback', 'title': 'Sparse calibration adapter for OOD retrieval'},
        ]
        res_dup = check_gap_record.check(rec_dup)
        self.assertFalse(res_dup['valid_structure'])
        self.assertIn('candidates:G1:tunnel_vision_idea_portfolio', res_dup['errors'])

        # Unverified failure case lacking engineering_checked / engineering_status -> engineering_failure_unresolved
        rec_fc = self._base_record()
        rec_fc['failure_cases'] = [{'id': 'FC1', 'error_type': 'oom', 'slice': 'long_context'}]
        rec_fc['candidates'][0]['trigger'] = 'failure_cases'
        rec_fc['candidates'][0]['failure_case_ids'] = ['FC1']
        rec_fc['candidates'][0]['engineering_status'] = 'implementation_checked'
        res_fc = check_gap_record.check(rec_fc)
        self.assertFalse(res_fc['valid_structure'])
        self.assertIn('candidates:G1:engineering_failure_unresolved', res_fc['errors'])


if __name__ == '__main__':
    unittest.main()
