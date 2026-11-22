"""Unit & integration tests for Milestone M9A: Scoring Engine v2 (F26, F28, F30#5-8, F31#2)."""
from __future__ import annotations

import copy
import decimal
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / 'research-scientist' / 'scripts'
REFS_DIR = ROOT / 'research-scientist' / 'references'
NOVELTY_REFS_DIR = ROOT / 'research-novelty-venue' / 'references'
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


score_math = _load_module('score_math', SCRIPTS_DIR / 'score_math.py')
compare_scorecards = _load_module('compare_scorecards', SCRIPTS_DIR / 'compare_scorecards.py')
compare_venue_novelty = _load_module('compare_venue_novelty', SCRIPTS_DIR / 'compare_venue_novelty.py')
claim_audit = _load_module('claim_audit', SCRIPTS_DIR / 'claim_audit.py')
gap_pipeline = _load_module('gap_pipeline', SCRIPTS_DIR / 'gap_pipeline.py')

FABRICATED_ODDS_RE = re.compile(
    r'\b\d+(?:\.\d+)?%\s*(?:acceptance|chance|odds|probability)',
    re.IGNORECASE,
)


def _paper_weights(vals=(15, 20, 20, 20, 15, 10)):
    return dict(zip(score_math.DIMENSIONS, vals))


def _paper_ratings(vals):
    return dict(zip(score_math.DIMENSIONS, vals))


def _idea_ratings(vals):
    return dict(zip(score_math.IDEA_DIMENSIONS, vals))


def _make_panel_fixture():
    p = json.loads((REFS_DIR / 'venue-novelty-profile.fixture.json').read_text(encoding='utf-8'))
    return p


class TestM9AVenueProfilesAndNativeScales(unittest.TestCase):
    def test_all_five_venue_profiles_and_dataset_t1_t2_gate(self):
        expected = {
            'conference_top_tier',
            'journal_q1',
            'dataset_benchmark',
            'survey_review',
            'workshop_preliminary',
        }
        self.assertEqual(set(score_math.VENUE_TYPE_PROFILES.keys()), expected)
        for vtype, spec in score_math.VENUE_TYPE_PROFILES.items():
            self.assertEqual(sum(spec['weights'].values()), 100, vtype)
            res = score_math.score({
                'venue_type': vtype,
                'ratings': _paper_ratings((7, 7, 7, 7, 7, 7)),
            })
            self.assertEqual(res['status'], 'calculated')
            self.assertEqual(res['venue_type_profile']['venue_type'], vtype)

        # journal_q1 emphasizes soundness/evidence more than conference_top_tier novelty weight
        jq1 = score_math.VENUE_TYPE_PROFILES['journal_q1']['weights']
        ctt = score_math.VENUE_TYPE_PROFILES['conference_top_tier']['weights']
        self.assertGreater(jq1['soundness'] + jq1['evidence'], ctt['soundness'] + ctt['evidence'])
        self.assertGreater(ctt['novelty'], jq1['novelty'])

        # dataset_benchmark T1-T2 failure blocks readiness
        ds_fail = score_math.score({
            'venue_type': 'dataset_benchmark',
            'ratings': _paper_ratings((8, 8, 8, 8, 8, 8)),
            'ethics_license_verified': False,
        })
        self.assertTrue(ds_fail['submission_readiness']['fatal_gate_triggered'])
        self.assertFalse(ds_fail['submission_readiness']['ready_for_top_tier_main_track'])
        self.assertIn('ethics_and_license_t1_t2', ds_fail['venue_type_profile']['failed_checks'])

    def test_deterministic_native_scales_and_fatal_cap_zero_odds(self):
        cases = [
            ('4.20', False, 2.0, 2, 3, 'Reject'),
            ('5.50', False, 2.5, 3, 5, 'Major Revision'),
            ('6.35', False, 3.0, 4, 6, 'Minor Revision'),
            ('7.20', False, 3.5, 5, 7, 'Minor Revision'),
            ('8.10', False, 4.0, 6, 8, 'Accept'),
        ]
        for raw_s, fatal, exp_arr, exp_neu, exp_iclr, exp_j in cases:
            out = score_math.translate_to_native_scales(
                raw_s,
                fatal_gate_triggered=fatal,
                ratings=_paper_ratings((7, 7, 7, 7, 7, 7)),
            )
            self.assertEqual(out['arr_1_to_5']['score'], exp_arr, raw_s)
            self.assertEqual(out['neurips_1_to_6']['score'], exp_neu, raw_s)
            self.assertEqual(out['iclr_1_to_10']['score'], exp_iclr, raw_s)
            self.assertEqual(out['journal_decision'], exp_j, raw_s)
            self.assertIsNone(out['iclr_1_to_10']['confidence'])
            self.assertEqual(out['iclr_1_to_10']['confidence_source'], 'not_provided')
            self.assertIsNone(FABRICATED_ODDS_RE.search(json.dumps(out)))

        # Fatal gate caps high mean below accept bar
        capped = score_math.translate_to_native_scales(
            '7.60',
            fatal_gate_triggered=True,
            ratings=_paper_ratings((9, 8, 4, 8, 8, 8)),
            reviewer_confidence=4,
        )
        self.assertLessEqual(capped['arr_1_to_5']['score'], 2.5)
        self.assertLessEqual(capped['neurips_1_to_6']['score'], 3)
        self.assertLessEqual(capped['iclr_1_to_10']['score'], 3)
        self.assertEqual(capped['iclr_1_to_10']['confidence'], 4)
        self.assertEqual(capped['journal_decision'], 'Reject')

    def test_compare_venue_novelty_preserves_unknown_vs_neurips_invariance(self):
        base = _make_panel_fixture()
        as_of = datetime(2026, 4, 15, tzinfo=timezone.utc)
        unk = compare_venue_novelty.check(base, as_of=as_of, venue_type='conference_top_tier', subfield_preset='nlp_llm')
        neu_in = copy.deepcopy(base)
        neu_in['venue']['name'] = 'NeurIPS'
        neu = compare_venue_novelty.check(neu_in, as_of=as_of, venue_type='conference_top_tier', subfield_preset='nlp_llm')
        self.assertEqual(unk['novelty_comparison'], neu['novelty_comparison'])
        self.assertEqual(unk['fit_score_out_of_10'], neu['fit_score_out_of_10'])
        self.assertEqual(unk['venue_type'], 'conference_top_tier')
        self.assertEqual(unk['subfield_preset'], 'nlp_llm')


class TestM9AMultiReviewerAndACMetaReview(unittest.TestCase):
    def test_multi_reviewer_variance_champion_assassin_and_fatal_block(self):
        w = _paper_weights()
        panel = [
            {'reviewer_id': 'R1', 'role': 'method_theory', 'confidence': 5, 'ratings': _paper_ratings((8, 8, 3, 8, 7, 8))},
            {'reviewer_id': 'R2', 'role': 'experiments_baselines', 'confidence': 4, 'ratings': _paper_ratings((8, 8, 8, 8, 7, 8))},
            {'reviewer_id': 'R3', 'role': 'novelty_positioning', 'confidence': 3, 'ratings': _paper_ratings((8, 8, 8, 8, 7, 8))},
        ]
        res = score_math.score({
            'weights': w,
            'ratings': _paper_ratings((8, 8, 7, 8, 7, 8)),
            'reviewer_panel': panel,
        })
        rpa = res['reviewer_panel_analysis']
        self.assertEqual(rpa['reviewer_count'], 3)
        self.assertTrue(rpa['assassin_reviewer_flag'])
        self.assertIn('R1', rpa['assassin_reviewer_ids'])
        self.assertTrue(rpa['champion_flag'])
        self.assertIn('R2', rpa['champion_reviewer_ids'])
        self.assertTrue(rpa['fatal_defect_blocks_averaging'])
        # AC MUST NOT average away fatal soundness=3 from confident R1
        self.assertEqual(rpa['meta_review_verdict'], 'reject_fatal_defect')
        self.assertGreater(rpa['spread'], 0.9)
        self.assertIn(rpa['variance_risk'], ('moderate', 'high_disagreement'))

        # Clean consensus panel without fatal defect -> accept
        clean_panel = [
            {'reviewer_id': 'R1', 'role': 'method_theory', 'confidence': 4, 'ratings': _paper_ratings((8, 8, 8, 7, 7, 8))},
            {'reviewer_id': 'R2', 'role': 'experiments_baselines', 'confidence': 4, 'ratings': _paper_ratings((8, 7, 8, 8, 7, 7))},
            {'reviewer_id': 'R3', 'role': 'novelty_positioning', 'confidence': 3, 'ratings': _paper_ratings((7, 8, 7, 8, 7, 8))},
        ]
        clean_res = score_math.simulate_reviewer_panel(clean_panel, w)
        self.assertEqual(clean_res['meta_review_verdict'], 'accept')
        self.assertEqual(clean_res['variance_risk'], 'low')

        with self.assertRaises(ValueError):
            score_math.simulate_reviewer_panel(clean_panel[:2], w)
        with self.assertRaises(ValueError):
            score_math.simulate_reviewer_panel(
                [dict(clean_panel[0], confidence=True), clean_panel[1], clean_panel[2]], w
            )


class TestM9AIdeaModeParetoAndLinkage(unittest.TestCase):
    def test_idea_dimensions_viability_bands_and_legacy_compat(self):
        # Legacy F23/M9C compat: status/object_type='idea' with paper 6 dims
        for k in ('status', 'object_type'):
            legacy = score_math.score({
                k: 'idea',
                'weights': _paper_weights(),
                'ratings': _paper_ratings((8, 8, 8, 8, 8, 8)),
            })
            self.assertEqual(legacy['submission_readiness']['band'], 'not_ready_fatal_gate')
            self.assertIn('unrun_idea_results', legacy['submission_readiness']['fatal_reasons'])

        # Dedicated mode='idea' with 6 IDEA_DIMENSIONS
        bands = [
            ((8, 8, 8, 7, 7, 8), 'pursue_high_priority'),
            ((7, 6, 7, 6, 5, 6), 'refine_and_de_risk'),
            ((6, 6, 6, 5, 4, 5), 'pivot_or_narrow'),
            ((6, 6, 6, 5, 5, 3), 'kill_early'),
        ]
        for vals, exp_band in bands:
            out = score_math.score({'mode': 'idea', 'ratings': _idea_ratings(vals)})
            self.assertEqual(out['mode'], 'idea')
            self.assertEqual(out['idea_viability_band'], exp_band)
            self.assertTrue(out['archival_submission_blocked'])
            sr = out['submission_readiness']
            self.assertFalse(sr['ready_for_top_tier_main_track'])
            self.assertFalse(sr['ready_for_findings_or_tier_a'])
            self.assertTrue(sr['fatal_gate_triggered'])
            self.assertEqual(sr['idea_viability_band'], exp_band)

    def test_idea_seed_bundle_fail_closed_and_pareto_goals_linkage(self):
        # 1. Scaffold from gap_pipeline with null ratings MUST fail closed (not_comparable)
        corpus = {
            'P1': {
                'id': 'P1', 'source': 'openalex', 'family': 'same_problem', 'year': 2024,
                'published_date': '2024-05-01', 'title': 'Calibration Study A',
                'abstract': 'Temperature scaling improves ID calibration.',
                'text': 'In-domain calibration baseline.', 'retraction_status': 'clean',
            },
            'P2': {
                'id': 'P2', 'source': 'arxiv', 'family': 'cross_setting_analogy', 'year': 2025,
                'published_date': '2025-02-01', 'title': 'Calibration Study B',
                'abstract': 'Long context decoding exhibits calibration drift.',
                'text': 'Long-context OOD calibration drift observed.', 'retraction_status': 'clean',
            },
        }
        digests = {
            'P1': {'source_id': 'P1', 'access': 'full_text', 'digest': 'Only ID tested'},
            'P2': {'source_id': 'P2', 'access': 'full_text', 'digest': 'No OOD bound'},
        }
        cand = {
            'id': 'G1',
            'claim': 'Selective abstention reduces calibration drift on long-context OOD retrieval.',
            'cited_ids': ['P1', 'P2'],
            'support_ids': ['P1', 'P2'],
            'closest_work_ids': ['P1', 'P2'],
            'cutoff_year': 2026,
            'sgha_critics_passed': True,
            'engineering_checked': True,
            'consequence': 'Prevents silent OOD retrieval miscalibration.',
            'root_cause_barrier': 'measurement_gap',
            'why_now_enabler': 'Long-context open weights (2025) allow controlled layerwise probing.',
            'so_what_decision_impact': 'decision_changing',
            'durability_12_24m': 'durable_structural_limit',
            'pre_mortem': {
                'top_failure_modes': ['Spurious length bias', 'Baseline untuned', 'Metric saturation'],
                'killer_experiment': {'duration_days': 1.5, 'kill_threshold': 'ECE delta < 0.01'},
                'pivot_path': 'Pivot to diagnostic error taxonomy across retrieval depths.',
            },
            'idea_portfolio': [
                {'id': 'I1', 'angle': 'minimal_fix', 'title': 'Minimal logit scaling fix', 'summary': 'Single-parameter shift calibration.'},
                {'id': 'I2', 'angle': 'high_novelty_mechanism', 'title': 'Causal attention gate', 'summary': 'Interventional routing across heads.'},
                {'id': 'I3', 'angle': 'benchmark_diagnostic_analysis', 'title': 'Diagnostic stress suite', 'summary': 'Controlled OOD depth benchmark.'},
                {'id': 'I4', 'angle': 'low_gpu_fallback', 'title': 'CPU post-hoc calibrator', 'summary': 'Zero-training post-hoc estimator.'},
            ],
        }
        gp_out = gap_pipeline.run_pipeline(
            'calibration', corpus, digests, [cand],
            subfield_preset='nlp_llm', require_idea_portfolio=True, require_pre_mortem=True,
        )
        bundle = gp_out['idea_seed_bundle']
        scaffold_res = compare_scorecards.compare(bundle, mode='idea')
        self.assertEqual(scaffold_res['status'], 'not_comparable')
        self.assertTrue(any(iss.startswith('missing_rating:') for iss in scaffold_res['issues']))

        # 2. Rated ideas + gap_record + question_card + seed_bundle linkage + 3 Pareto goals
        rated_bundle = copy.deepcopy(bundle)
        rated_ratings = {
            'I1': (7, 6, 7, 9, 9, 8),
            'I2': (7, 9, 9, 6, 5, 8),
            'I3': (8, 7, 7, 8, 8, 7),
            'I4': (6, 5, 6, 9, 10, 7),
        }
        for idea in rated_bundle['seeds'][0]['idea_portfolio']:
            iid = idea['id']
            idea['ratings'] = _idea_ratings(rated_ratings[iid])
            idea['evidence_locators'] = {d: [f'notes_{iid}.txt#L1 "Verified evidence"'] for d in score_math.IDEA_DIMENSIONS}
            idea['pre_mortem'] = copy.deepcopy(cand['pre_mortem'])
        rated_bundle['seeds'][0]['prior_art_boundary']['cited_ids'] = ['P1', 'P2']
        rated_bundle['seeds'][0]['prior_art_boundary']['support_ids'] = ['P1']
        rated_bundle['seeds'][0]['idea_portfolio'][3]['required_gpu_hours'] = 4
        rated_bundle['seeds'][0]['idea_portfolio'][1]['required_gpu_hours'] = 240

        qc = {
            'id': 'RQ1', 'gap_id': 'G1', 'idea_id': 'I2',
            'question': 'Does causal head routing reduce OOD calibration error?',
            'question_type': 'causal',
            'identification_assumptions': 'No unobserved context-length confounders.',
            'target_scope': 'Long-context RAG',
            'unit_of_observation': 'Query-passage pair',
            'unit_of_analysis': 'Dataset split',
            'construct_or_estimand': 'ECE under shift',
            'measurement': '15-bin ECE',
            'closest_work': 'P1, P2',
            'prior_art_boundary': 'P1 only tested ID.',
            'rival_explanation': 'Simple temperature scaling explains the gain.',
            'expected_if_focal': 'Causal routing beats tuned temp scaling by >= 3% ECE.',
            'expected_if_rival': 'Tuned temp scaling matches routing within 0.5%.',
            'discriminating_test': 'Head intervention vs post-hoc temp sweep.',
            'falsifying_result': 'Difference < 0.5% under matched compute.',
            'indeterminate_result': 'High seed variance across runs.',
            'pilot': '1.5-day 500-example probe.',
            'engineering_diagnosis': 'Verified split hygiene and eval harness.',
            'prior_outcome_exposure': 'None prior to pre-registration.',
        }

        res_fast = compare_scorecards.compare(
            rated_bundle, mode='idea', goal='safe_fast_publish',
            question_card=qc, idea_seed_bundle=rated_bundle,
            require_idea_portfolio=True, require_pre_mortem=True,
        )
        self.assertEqual(res_fast['status'], 'structurally_comparable')
        self.assertEqual(res_fast['pareto_frontier']['goal'], 'safe_fast_publish')
        self.assertIn('I1', res_fast['pareto_frontier']['frontier_ids'])
        self.assertTrue(res_fast['linkage_summary']['question_card_valid'])
        self.assertTrue(res_fast['linkage_summary']['seed_bundle_linked'])
        self.assertEqual([list(x.keys()) for x in res_fast['rankings'][0]['ordered']], [['id', 'weighted_unrounded']] * 4)

        res_q1 = compare_scorecards.compare(rated_bundle, mode='idea', goal='high_risk_q1_top_tier')
        self.assertEqual(res_q1['pareto_frontier']['goal_ranked_ids'][0], 'I2')

        res_lowgpu = compare_scorecards.compare(rated_bundle, mode='idea', goal='low_compute_constrained')
        self.assertIn('I4', res_lowgpu['pareto_frontier']['frontier_ids'])

        # Tunnel-vision single-angle portfolio MUST fail when require_idea_portfolio=True
        bad_bundle = copy.deepcopy(rated_bundle)
        for idea in bad_bundle['seeds'][0]['idea_portfolio']:
            idea['angle'] = 'minimal_fix'
            idea['canonical_angle'] = 'minimal_fix'
        res_tunnel = compare_scorecards.compare(bad_bundle, mode='idea', require_idea_portfolio=True)
        self.assertEqual(res_tunnel['status'], 'not_comparable')
        self.assertTrue(any('tunnel_vision_idea_portfolio' in i for i in res_tunnel['issues']))


class TestM9AWhatIfROIRevisionDiffAndHaloGuard(unittest.TestCase):
    def test_what_if_roi_clears_fatal_gate_and_venue_bars(self):
        w = _paper_weights()
        r = _paper_ratings((7, 6, 4, 7, 7, 7))
        roi = score_math.simulate_what_if_roi(w, r, venue_type='conference_top_tier')
        self.assertFalse(roi['single_axis_upgrades'][0]['clears_6_80'])
        self.assertTrue(roi['single_axis_upgrades'][0]['clears_fatal_gate'])
        self.assertEqual(roi['single_axis_upgrades'][0]['dimension'], 'soundness')
        self.assertTrue(roi['minimal_paths']['clear_fatal_gate']['reachable'])
        self.assertTrue(roi['minimal_paths']['reach_6_80']['reachable'])
        self.assertGreaterEqual(len(roi['minimal_paths']['reach_6_80']['steps']), 1)

    def test_revision_diff_anti_grade_inflation_with_locators_and_sha256(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'sources'
            src.mkdir()
            (src / 'paper.txt').write_text(
                'Baseline proof theorem verified. New 5-seed ablation CI [1.2, 2.8] reported.\n',
                encoding='utf-8',
            )
            receipt_file = src / 'run_ablation.json'
            receipt_file.write_text('{"acc": 88.4}\n', encoding='utf-8')
            sha_hex = hashlib.sha256(receipt_file.read_bytes()).hexdigest()

            w = _paper_weights()
            v1 = {
                'id': 'paper_target',
                'weights': w,
                'ratings': _paper_ratings((7, 6, 4, 6, 6, 6)),
                'evidence_locators': {d: ['paper.txt#L1 "Baseline proof theorem verified"'] for d in score_math.DIMENSIONS},
                'defects': ['soundness_lemma_gap', 'missing_5seed_ablation'],
            }
            # Spoofed v2: bumps soundness & evidence without any NEW locator or SHA-256 receipt
            v2_spoof = copy.deepcopy(v1)
            v2_spoof['ratings'] = _paper_ratings((7, 6, 7, 8, 6, 6))
            spoof_diff = compare_scorecards.revision_diff(v1, v2_spoof, sources_dir=src)
            self.assertTrue(spoof_diff['suspected_grade_inflation'])
            self.assertEqual(spoof_diff['status'], 'grade_inflation_suspected')
            self.assertEqual(set(spoof_diff['unsubstantiated_gain_dimensions']), {'soundness', 'evidence'})

            # Verified v2: soundness backed by NEW verified locator + evidence backed by NEW SHA-256 receipt
            v2_ok = copy.deepcopy(v1)
            v2_ok['ratings'] = _paper_ratings((7, 6, 7, 8, 6, 6))
            v2_ok['evidence_locators']['soundness'].append('paper.txt#L1 "New 5-seed ablation CI"')
            v2_ok['run_receipts'] = [{'sha256': sha_hex, 'path': 'run_ablation.json', 'dimensions': ['evidence']}]
            v2_ok['defects'] = ['minor_typo']
            ok_diff = compare_scorecards.revision_diff(v1, v2_ok, sources_dir=src)
            self.assertFalse(ok_diff['suspected_grade_inflation'])
            self.assertEqual(ok_diff['status'], 'verified_revision')
            self.assertEqual(ok_diff['resolved_fatal_dimensions'], ['soundness'])
            self.assertEqual(ok_diff['resolved_v1_defects'], ['missing_5seed_ablation', 'soundness_lemma_gap'])
            self.assertEqual(ok_diff['newly_introduced_defects'], ['minor_typo'])

            # Tampered SHA-256 receipt must fail verification
            v2_bad_sha = copy.deepcopy(v2_ok)
            v2_bad_sha['run_receipts'][0]['sha256'] = '0' * 64
            bad_sha_diff = compare_scorecards.revision_diff(v1, v2_bad_sha, sources_dir=src)
            self.assertTrue(bad_sha_diff['suspected_grade_inflation'])

    def test_halo_effect_sanity_warnings(self):
        w = _paper_weights()
        res = score_math.score({
            'weights': w,
            'ratings': _paper_ratings((7, 9, 8, 9, 4, 8)),
            'closest_work': ['Prior1'],
            'reading_basis': 'abstract',
        })
        sw = res['sanity_warnings']
        self.assertIn('halo_warning:high_soundness_low_transparency', sw)
        self.assertIn('halo_warning:high_evidence_without_ci_seed_or_ablation', sw)
        self.assertIn('halo_warning:high_novelty_with_thin_or_unread_closest_work', sw)


class TestM9ADeepScoringF30AndSubfieldPresetsF31(unittest.TestCase):
    def test_f30_anchor_table_merit_packaging_sections_and_deal_breakers(self):
        w = _paper_weights()
        target = {
            'id': 'target',
            'weights': w,
            'ratings': _paper_ratings((8, 7, 5, 7, 5, 7)),
            'evidence_profile': {
                'benchmarks_count': 2,
                'sota_baselines_covered': ['BaseA', 'BaseB'],
                'ablation_depth': 'single_axis',
                'theoretical_rigor': 'sketch',
                'effect_size_ci_stability': False,
                'code_artifact_openness': 'partial',
            },
            'evidence_anchors': [
                {
                    'id': 'Acc1', 'topic_relation': 'same_topic', 'reading_basis': 'full_text',
                    'benchmarks_count': 4, 'sota_baselines_covered': 5,
                    'ablation_depth': 'comprehensive', 'theoretical_rigor': 'proved_bounds',
                    'effect_size_ci_stability': True, 'code_artifact_openness': 'full_code_and_weights',
                },
                {
                    'id': 'Acc2', 'topic_relation': 'different_topic', 'reading_basis': 'full_text',
                    'benchmarks_count': 6,
                    # Intentionally omit sota_baselines_covered to verify zero fabrication ('unreported')
                    'ablation_depth': 'comprehensive', 'theoretical_rigor': 'none',
                    'effect_size_ci_stability': True, 'code_artifact_openness': 'full_code_and_weights',
                },
            ],
            'section_diagnostics': {
                'abstract': 8,
                'introduction': {'score': 7, 'issues': []},
                'related_work': {'score': 5, 'issues': ['Missing 2025 baseline']},
                'method': {'score': 4, 'issues': ['Unproven bound']},
                'experiments': 6,
                'limitations': 5,
            },
        }
        res = score_math.score(target)
        eat = res['evidence_anchor_table']
        self.assertEqual(eat['anchor_count'], 2)
        self.assertEqual(eat['same_topic_anchor_count'], 1)
        self.assertEqual(eat['cross_topic_anchor_count'], 1)
        self.assertEqual(eat['anchors'][1]['sota_baselines_covered'], 'unreported')
        self.assertEqual(eat['target_vs_anchors_summary']['target_benchmarks_delta'], -3.0)

        mvp = res['merit_vs_packaging']
        self.assertIn('scientific_merit_score', mvp)
        self.assertIn('publishability_packaging_score', mvp)

        # Strong merit + weak packaging diagnosis
        pack_bot = score_math.compute_merit_vs_packaging(w, _paper_ratings((8, 8, 7, 7, 5, 5)))
        self.assertEqual(pack_bot['diagnosis'], 'packaging_and_reproducibility_bottleneck')

        sd = res['section_diagnostics']
        self.assertEqual(sd['prioritized_edit_order'][0]['section'], 'method')
        self.assertIn('method', sd['weakest_sections'])

        dbs = res['deal_breaker_sensitivity']
        self.assertIn('soundness', dbs['deal_breaker_axes'])
        self.assertEqual(dbs['worst_case_reviewer_floor']['basis'], 'single_axis_minus1_floor')

    def test_f31_all_four_subfield_presets_and_alias_interop(self):
        expected = {'nlp_llm', 'cv_multimodal', 'ml_theory', 'ai_systems', 'speech_audio'}
        self.assertEqual(set(score_math.SUBFIELD_PRESETS.keys()), expected)

        # Alias mapping from build_research_inputs.py check names
        nlp_res = score_math.evaluate_subfield_readiness(
            'nlp_llm',
            {'contamination_audit': True, 'multi_prompt_template_variance': True, 'eval_harness_parity': True},
        )
        self.assertIn('contamination_check', nlp_res['passed_checks'])
        self.assertIn('multi_prompt_variance', nlp_res['passed_checks'])
        self.assertEqual(nlp_res['missing_checks'], ['compute_matched_open_weight_baseline'])

        sys_res = score_math.evaluate_subfield_readiness(
            'ai_systems',
            {'peak_vram_and_communication_overhead_matched_hardware': True},
        )
        self.assertIn('peak_vram_comm_overhead', sys_res['passed_checks'])
        self.assertIn('matched_hardware', sys_res['passed_checks'])

        sp_res = score_math.evaluate_subfield_readiness(
            'speech_audio',
            {
                'speaker_and_session_disjoint_split': True,
                'audio_text_normalization_and_metric_parity': True,
                'lm_vocoder_embedding_backend_parity': False,
            },
        )
        self.assertIn('speaker_session_disjoint_split', sp_res['passed_checks'])
        self.assertIn('audio_metric_and_normalization_parity', sp_res['passed_checks'])
        self.assertIn('decoding_vocoder_embedding_parity', sp_res['failed_checks'])
        self.assertEqual(sp_res['missing_checks'], ['speech_slice_significance_and_consent'])

    def test_decimal_trap_isolation_across_all_m9a_helpers(self):
        w = _paper_weights()
        r = _paper_ratings((7, 6, 7, 6, 6, 6))
        with decimal.localcontext() as ctx:
            ctx.prec = 1
            ctx.rounding = decimal.ROUND_DOWN
            ctx.traps[decimal.Inexact] = True
            ctx.traps[decimal.Rounded] = True
            ctx.traps[decimal.FloatOperation] = True
            res = score_math.score({
                'weights': w,
                'ratings': r,
                'venue_type': 'journal_q1',
                'subfield_preset': 'ml_theory',
                'reviewer_panel': [
                    {'reviewer_id': 'R1', 'role': 'theory', 'confidence': 4, 'ratings': _paper_ratings((7, 7, 7, 6, 6, 6))},
                    {'reviewer_id': 'R2', 'role': 'exp', 'confidence': 3, 'ratings': _paper_ratings((7, 6, 7, 6, 6, 7))},
                    {'reviewer_id': 'R3', 'role': 'nov', 'confidence': 5, 'ratings': _paper_ratings((6, 6, 7, 6, 6, 6))},
                ],
            })
            self.assertEqual(res['weighted_unrounded'], '6.35')
            self.assertEqual(res['native_venue_scales']['neurips_1_to_6']['score'], 4)
            self.assertEqual(res['merit_vs_packaging']['scientific_merit_score'], 6.47)


class TestM9AReferencesAndAudit(unittest.TestCase):
    def test_references_and_claim_audit_clean(self):
        scoring_ref = (REFS_DIR / 'scoring-and-venue-fit.md').read_text(encoding='utf-8')
        novelty_ref = (NOVELTY_REFS_DIR / 'novelty-venue-rebuttal-protocol.md').read_text(encoding='utf-8')
        self.assertIn('Scoring Engine v2', scoring_ref)
        self.assertIn('### 3.5 Scoring Engine v2', novelty_ref)
        self.assertNotIn('(../research-scientist/', novelty_ref)

        audit = claim_audit.audit_suite(ROOT, readme=ROOT / 'README.md')
        self.assertEqual(audit['status'], 'passed', audit['findings'])
        self.assertEqual(audit['finding_count'], 0, audit['findings'])
        for sk in audit['skills_audited']:
            self.assertLess(sk['footprint']['lines'], 50)
            self.assertLess(sk['footprint']['est_tokens'], 900)


class TestM9ARemediationRegressions(unittest.TestCase):
    def test_bug01_portfolio_unlisted_venue_falls_back_to_venue_type_tier(self):
        base = _make_panel_fixture()
        as_of = datetime(2026, 11, 21, 12, 0, 0, tzinfo=timezone.utc)
        weak_r = _paper_ratings((6, 5, 5, 6, 5, 6))  # 5.50 < 6.00
        port = {
            'target': dict(base['target'], score=5, low=4, high=6),
            'target_scorecard': {'weights': _paper_weights(), 'ratings': weak_r},
            'candidate_venues': [
                {
                    'venue_id': 'unlisted_top',
                    'role': 'primary',
                    'venue_type': 'conference_top_tier',
                    'venue': dict(base['venue'], name='SomeUnlistedTopConf', track='Main'),
                    'fit_axes': base['fit_axes'],
                    'hard_constraints': base['hard_constraints'],
                },
                {
                    'venue_id': 'neurips_main',
                    'role': 'fallback',
                    'venue_type': 'conference_top_tier',
                    'venue': dict(base['venue'], name='NeurIPS', track='Main'),
                    'fit_axes': base['fit_axes'],
                    'hard_constraints': base['hard_constraints'],
                },
                {
                    'venue_id': 'icml_main',
                    'role': 'fallback',
                    'venue_type': 'conference_top_tier',
                    'venue': dict(base['venue'], name='ICML', track='Main'),
                    'fit_axes': base['fit_axes'],
                    'hard_constraints': base['hard_constraints'],
                },
            ],
        }
        res = compare_venue_novelty.check(port, as_of=as_of, portfolio=True)
        ve = next(v for v in res['venue_evaluations'] if v['venue_id'] == 'unlisted_top')
        self.assertEqual(ve['venue_tier'], 'top_tier_flagship')
        self.assertEqual(ve['classification'], 'rejected_below_venue_tier')
        self.assertEqual(ve['submission_readiness']['verdict'], 'rejected_below_venue_tier')
        self.assertEqual(res['venue_portfolio_recommendations']['stretch_high_risk'], [])
        self.assertEqual(
            res['venue_portfolio_recommendations']['portfolio_verdict'],
            'no_viable_venue_in_portfolio',
        )

    def test_bug02_portfolio_dataset_benchmark_t1_t2_gate_blocks_recommended_now(self):
        base = _make_panel_fixture()
        as_of = datetime(2026, 11, 21, 12, 0, 0, tzinfo=timezone.utc)
        strong_r = _paper_ratings((8, 8, 8, 8, 8, 8))
        port = {
            'target': dict(base['target'], score=8, low=7, high=9),
            'target_scorecard': {'weights': _paper_weights(), 'ratings': strong_r},
            'candidate_venues': [
                {
                    'venue_id': 'neurips_db_fail',
                    'role': 'primary',
                    'venue_type': 'dataset_benchmark',
                    'ethics_license_verified': False,
                    'venue': dict(base['venue'], name='NeurIPS', track='Datasets and Benchmarks'),
                    'fit_axes': base['fit_axes'],
                    'hard_constraints': base['hard_constraints'],
                },
                {
                    'venue_id': 'neurips_db_missing',
                    'role': 'fallback',
                    'venue_type': 'dataset_benchmark',
                    'venue': dict(base['venue'], name='ICLR', track='Datasets'),
                    'fit_axes': base['fit_axes'],
                    'hard_constraints': base['hard_constraints'],
                },
                {
                    'venue_id': 'icml_ok',
                    'role': 'fallback',
                    'venue_type': 'conference_top_tier',
                    'venue': dict(base['venue'], name='ICML', track='Main'),
                    'fit_axes': base['fit_axes'],
                    'hard_constraints': base['hard_constraints'],
                },
            ],
        }
        res = compare_venue_novelty.check(port, as_of=as_of, portfolio=True)
        rec = res['venue_portfolio_recommendations']
        for vid in ('neurips_db_fail', 'neurips_db_missing'):
            ve = next(v for v in res['venue_evaluations'] if v['venue_id'] == vid)
            self.assertEqual(ve['submission_readiness']['verdict'], 'not_ready_fatal_gate')
            self.assertFalse(ve['submission_readiness']['ready_to_submit'])
            self.assertEqual(ve['classification'], 'hold_for_rework')
            self.assertNotIn(vid, rec['recommended_now'])
            self.assertIn(vid, rec['blocked_hold_for_rework'])
        self.assertIn('icml_ok', rec['viable_fallback'] + rec['recommended_now'])

        # All venues blocked by per-candidate fatal gates -> portfolio_verdict == 'hold_for_rework'
        port_all_hold = copy.deepcopy(port)
        port_all_hold['candidate_venues'][2]['venue_type'] = 'dataset_benchmark'
        res_all_hold = compare_venue_novelty.check(port_all_hold, as_of=as_of, portfolio=True)
        self.assertEqual(
            res_all_hold['venue_portfolio_recommendations']['portfolio_verdict'],
            'hold_for_rework',
        )
        self.assertTrue(res_all_hold['venue_portfolio_recommendations']['hold_for_rework'])

    def test_bug03_venue_type_min_dimensions_honored_everywhere(self):
        checks_ok = {
            'data_quality_audit': True,
            'annotation_protocol': True,
            'ethics_and_license_t1_t2': True,
        }
        # dataset_benchmark requires transparency >= 6
        ds_low_tr = score_math.score({
            'venue_type': 'dataset_benchmark',
            'ratings': _paper_ratings((7, 7, 7, 7, 5, 7)),
            'dataset_checks': checks_ok,
        })
        self.assertTrue(ds_low_tr['venue_tier_fit']['rejected_below_venue_tier'])
        self.assertTrue(any('transparency' in s for s in ds_low_tr['venue_tier_fit']['rejection_reasons']))
        tr_up = next(
            m for m in ds_low_tr['what_if_roi']['single_axis_upgrades']
            if m['dimension'] == 'transparency' and m['step'] == 1
        )
        self.assertTrue(tr_up['clears_tier_rejection'])
        self.assertEqual(
            ds_low_tr['what_if_roi']['minimal_paths']['clear_venue_tier_rejection']['steps'][0]['dimension'],
            'transparency',
        )

        # dataset_benchmark min_any_dimension=5 rejects novelty=4 with dataset_benchmark label, allows novelty=5
        ds_nov4 = score_math.score({
            'venue_type': 'dataset_benchmark',
            'ratings': _paper_ratings((7, 4, 7, 7, 7, 7)),
            'dataset_checks': checks_ok,
        })
        self.assertTrue(ds_nov4['venue_tier_fit']['rejected_below_venue_tier'])
        self.assertIn('novelty_4_below_dataset_benchmark_dim_floor_5', ds_nov4['venue_tier_fit']['rejection_reasons'])
        ds_nov5 = score_math.score({
            'venue_type': 'dataset_benchmark',
            'ratings': _paper_ratings((7, 5, 7, 7, 7, 7)),
            'dataset_checks': checks_ok,
        })
        self.assertFalse(ds_nov5['venue_tier_fit']['rejected_below_venue_tier'])

        # survey_review requires clarity >= 6
        sv_low_cl = score_math.score({
            'venue_type': 'survey_review',
            'ratings': _paper_ratings((7, 7, 7, 7, 7, 5)),
            'venue_checks': {'systematic_coverage_protocol': True},
        })
        self.assertTrue(sv_low_cl['venue_tier_fit']['rejected_below_venue_tier'])
        self.assertTrue(any('clarity' in s for s in sv_low_cl['venue_tier_fit']['rejection_reasons']))

        # compute_deal_breaker_sensitivity honors venue_type transparency>=6
        dbs = score_math.compute_deal_breaker_sensitivity(
            score_math.VENUE_TYPE_PROFILES['dataset_benchmark']['weights'],
            _paper_ratings((8, 8, 8, 8, 6, 8)),
            venue_type='dataset_benchmark',
        )
        self.assertTrue(dbs['per_dimension']['transparency']['drop_minus_1']['triggers_tier_rejection'])
        self.assertIn('transparency', dbs['deal_breaker_axes'])

        # compare_venue_novelty single-venue honors dataset_benchmark transparency>=6
        base = _make_panel_fixture()
        base['venue']['name'] = 'NeurIPS'
        base['venue']['track'] = 'Datasets and Benchmarks'
        base['accepted_panel'] = [dict(p, track='Datasets and Benchmarks') for p in base['accepted_panel']]
        base['dataset_checks'] = checks_ok
        base['target_scorecard'] = {
            'weights': score_math.VENUE_TYPE_PROFILES['dataset_benchmark']['weights'],
            'ratings': _paper_ratings((7, 7, 7, 7, 5, 7)),
        }
        vn_res = compare_venue_novelty.check(
            base, as_of=datetime(2026, 11, 21, 12, 0, 0, tzinfo=timezone.utc), venue_type='dataset_benchmark'
        )
        self.assertEqual(vn_res['submission_readiness']['verdict'], 'rejected_below_venue_tier')
        self.assertFalse(vn_res['submission_readiness']['ready_to_submit'])

    def test_bug04_dataset_benchmark_missing_t1_t2_fails_closed_and_what_if_blocked(self):
        ds_missing = score_math.score({
            'venue_type': 'dataset_benchmark',
            'ratings': _paper_ratings((8, 8, 8, 8, 8, 8)),
        })
        self.assertTrue(ds_missing['venue_type_profile']['checks_gate_failed'])
        self.assertTrue(ds_missing['submission_readiness']['fatal_gate_triggered'])
        self.assertEqual(ds_missing['submission_readiness']['band'], 'not_ready_fatal_gate')
        self.assertFalse(ds_missing['submission_readiness']['ready_for_top_tier_main_track'])
        self.assertFalse(ds_missing['submission_readiness']['ready_for_findings_or_tier_a'])
        self.assertTrue(
            any(r.startswith('venue_checks_unverified:') for r in ds_missing['submission_readiness']['fatal_reasons'])
        )

        ds_fail = score_math.score({
            'venue_type': 'dataset_benchmark',
            'ratings': _paper_ratings((8, 8, 8, 8, 8, 8)),
            'ethics_license_verified': False,
        })
        self.assertFalse(ds_fail['what_if_roi']['minimal_paths']['clear_fatal_gate']['reachable'])
        self.assertTrue(ds_fail['what_if_roi']['blocked_by_non_rating_fatal_gate'])

        # Positive control: all 3 dataset_checks True -> ready
        ds_ok = score_math.score({
            'venue_type': 'dataset_benchmark',
            'ratings': _paper_ratings((8, 8, 8, 8, 8, 8)),
            'dataset_checks': {
                'data_quality_audit': True,
                'annotation_protocol': True,
                'ethics_and_license_t1_t2': True,
            },
        })
        self.assertFalse(ds_ok['venue_type_profile']['checks_gate_failed'])
        self.assertTrue(ds_ok['submission_readiness']['ready_for_top_tier_main_track'])

        base = _make_panel_fixture()
        base['target_scorecard'] = {
            'weights': score_math.VENUE_TYPE_PROFILES['dataset_benchmark']['weights'],
            'ratings': _paper_ratings((8, 8, 8, 8, 8, 8)),
        }
        vn_missing = compare_venue_novelty.check(
            base, as_of=datetime(2026, 11, 21, 12, 0, 0, tzinfo=timezone.utc), venue_type='dataset_benchmark'
        )
        self.assertFalse(vn_missing['submission_readiness']['ready_to_submit'])
        self.assertEqual(vn_missing['submission_readiness']['verdict'], 'not_ready_fatal_gate')

    def test_bug05_reviewer_confidence_and_venue_novelty_reviewer_panel_validation(self):
        w = _paper_weights()
        doc = {
            'weight_scenarios': [w],
            'profiles': [
                {
                    'id': 'p1',
                    'reading_basis': 'full_text',
                    'closest_work': ['p2'],
                    'ratings': _paper_ratings((7, 7, 7, 7, 7, 7)),
                    'reviewer_confidence': 4,
                    'evidence_locators': {d: ['f.txt#L1 "ok"'] for d in score_math.DIMENSIONS},
                },
                {
                    'id': 'p2',
                    'reading_basis': 'full_text',
                    'closest_work': ['p1'],
                    'ratings': _paper_ratings((7, 6, 7, 7, 7, 7)),
                    'confidence': 3,
                    'evidence_locators': {d: ['f.txt#L1 "ok"'] for d in score_math.DIMENSIONS},
                },
            ],
        }
        cs_out = compare_scorecards.compare(doc)
        self.assertEqual(cs_out['native_venue_scales']['p1']['iclr_1_to_10']['confidence'], 4)
        self.assertEqual(cs_out['native_venue_scales']['p2']['iclr_1_to_10']['confidence'], 3)

        base = _make_panel_fixture()
        as_of = datetime(2026, 11, 21, 12, 0, 0, tzinfo=timezone.utc)
        base['target_scorecard'] = {'weights': w, 'ratings': _paper_ratings((8, 8, 7, 8, 7, 8))}
        base['reviewer_panel'] = [
            {'reviewer_id': 'R1', 'role': 'method_theory', 'confidence': 5, 'ratings': _paper_ratings((8, 8, 3, 8, 7, 8))},
            {'reviewer_id': 'R2', 'role': 'experiments_baselines', 'confidence': 4, 'ratings': _paper_ratings((8, 8, 8, 8, 7, 8))},
            {'reviewer_id': 'R3', 'role': 'novelty_positioning', 'confidence': 3, 'ratings': _paper_ratings((8, 8, 8, 8, 7, 8))},
        ]
        vn_fatal = compare_venue_novelty.check(base, as_of=as_of)
        self.assertFalse(vn_fatal['submission_readiness']['ready_to_submit'])
        self.assertEqual(vn_fatal['submission_readiness']['verdict'], 'not_ready_fatal_gate')
        self.assertEqual(vn_fatal['reviewer_panel_analysis']['meta_review_verdict'], 'reject_fatal_defect')
        self.assertEqual(vn_fatal['deal_breaker_sensitivity']['worst_case_reviewer_floor']['basis'], 'reviewer_panel_min')

        # Invalid reviewer_panel raises ValueError & CLI exit 2
        bad_panel = copy.deepcopy(base)
        bad_panel['reviewer_panel'] = [base['reviewer_panel'][0]]
        with self.assertRaises(ValueError):
            compare_venue_novelty.check(bad_panel, as_of=as_of)

        bool_conf = copy.deepcopy(base)
        bool_conf['reviewer_panel'][0]['confidence'] = True
        with self.assertRaises(ValueError):
            compare_venue_novelty.check(bool_conf, as_of=as_of)

        with tempfile.TemporaryDirectory() as tmp:
            bad_p = Path(tmp) / 'bad_panel.json'
            bad_p.write_text(json.dumps(bad_panel), encoding='utf-8')
            proc = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / 'compare_venue_novelty.py'), str(bad_p)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 2)

    def test_bug06_revision_diff_all_receipt_aliases_traversal_symlink_and_sha256(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            src = tmp_p / 'sources'
            src.mkdir()
            outside = tmp_p / 'outside_secret.txt'
            outside.write_text('secret', encoding='utf-8')
            (src / 'paper.txt').write_text('Verified baseline claim.\n', encoding='utf-8')
            run_ok = src / 'run.json'
            run_ok.write_text('{"ok": true}\n', encoding='utf-8')
            sha_ok = hashlib.sha256(run_ok.read_bytes()).hexdigest()
            sym = src / 'sym_escape.json'
            sym.symlink_to(outside)

            w = _paper_weights()
            v1 = {
                'id': 'p_rev',
                'weights': w,
                'ratings': _paper_ratings((7, 6, 5, 6, 6, 6)),
                'evidence_locators': {d: ['paper.txt#L1 "Verified baseline claim"'] for d in score_math.DIMENSIONS},
            }

            bad_cases = [
                {'experiment_receipts': [{'sha256': '0' * 64, 'path': 'run.json', 'dimensions': ['evidence']}]},
                {'receipts': {'sha256': sha_ok, 'path': 'sym_escape.json', 'dimensions': ['evidence']}},
                {'run_receipts': {'sha256': '0' * 64, 'path': 'run.json', 'dimensions': ['evidence']}},
                {'revision_evidence': {'evidence': [{'sha256': sha_ok, 'path': '../outside_secret.txt'}]}},
            ]
            for extra in bad_cases:
                v2_bad = copy.deepcopy(v1)
                v2_bad['ratings']['evidence'] = 8
                v2_bad.update(extra)
                res = compare_scorecards.revision_diff(v1, v2_bad, sources_dir=src)
                self.assertEqual(res['status'], 'grade_inflation_suspected', extra)
                self.assertTrue(res['suspected_grade_inflation'], extra)
                self.assertTrue(res.get('receipt_verification_errors'), extra)

            # Even without sources_dir, path traversal in experiment_receipts fails closed (exit 1)
            v2_trav = copy.deepcopy(v1)
            v2_trav['ratings']['evidence'] = 8
            v2_trav['experiment_receipts'] = [{'sha256': sha_ok, 'path': '../../etc/passwd', 'dimensions': ['evidence']}]
            res_nosrc = compare_scorecards.revision_diff(v1, v2_trav)
            self.assertEqual(res_nosrc['status'], 'grade_inflation_suspected')

            v1_p = tmp_p / 'v1.json'
            v2_p = tmp_p / 'v2.json'
            v1_p.write_text(json.dumps(v1), encoding='utf-8')
            v2_p.write_text(json.dumps(v2_trav), encoding='utf-8')
            proc = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / 'compare_scorecards.py'), '--revision-diff', str(v1_p), str(v2_p)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 1)

            # Positive control: valid experiment_receipts SHA-256 passes
            v2_good = copy.deepcopy(v1)
            v2_good['ratings']['evidence'] = 8
            v2_good['experiment_receipts'] = [{'sha256': sha_ok, 'path': 'run.json', 'dimensions': ['evidence']}]
            res_ok = compare_scorecards.revision_diff(v1, v2_good, sources_dir=src)
            self.assertEqual(res_ok['status'], 'verified_revision')
            self.assertFalse(res_ok['suspected_grade_inflation'])

    def test_bug07_unrated_idea_portfolio_seed_bundle_fails_closed(self):
        bundle = {
            'schema': 'research_scientist_idea_seed_bundle_v1',
            'seeds': [
                {
                    'gap_id': 'G1',
                    'closest_work_ids': ['P1'],
                    'idea_portfolio': [
                        {'id': 'I1', 'angle': 'minimal_fix', 'ratings': None},
                        {'id': 'I2', 'angle': 'high_novelty_mechanism'},
                        {'id': None, 'idea_id': 'I3', 'angle': 'low_gpu_fallback', 'evidence_locators': None},
                    ],
                },
            ],
        }
        res = compare_scorecards.compare(bundle, mode='idea')
        self.assertEqual(res['status'], 'not_comparable')
        self.assertTrue(any(i.startswith('missing_rating:') for i in res['issues']))
        self.assertIn('I3', res['submission_readiness'])

    def test_bug08_idea_mode_revision_diff_with_venue_type_uses_idea_weights(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'sources'
            src.mkdir()
            (src / 'notes.txt').write_text('Initial idea note.\nNew pilot F1=0.81 verified.\n', encoding='utf-8')
            v1_idea = {
                'id': 'idea_1',
                'mode': 'idea',
                'venue_type': 'conference_top_tier',
                'ratings': _idea_ratings((7, 7, 7, 6, 6, 6)),
                'evidence_locators': {d: ['notes.txt#L1 "Initial idea note"'] for d in score_math.IDEA_DIMENSIONS},
            }
            v2_ok = copy.deepcopy(v1_idea)
            v2_ok['ratings']['feasibility'] = 8
            v2_ok['evidence_locators']['feasibility'].append('notes.txt#L2 "New pilot F1=0.81 verified"')
            res_ok = compare_scorecards.revision_diff(v1_idea, v2_ok, sources_dir=src)
            self.assertEqual(res_ok['status'], 'verified_revision')

            v2_spoof = copy.deepcopy(v1_idea)
            v2_spoof['ratings']['feasibility'] = 8
            res_spoof = compare_scorecards.revision_diff(v1_idea, v2_spoof, sources_dir=src)
            self.assertEqual(res_spoof['status'], 'grade_inflation_suspected')

    def test_bug09_multi_seed_idea_portfolio_validated_per_gap(self):
        corpus = {
            'P1': {
                'id': 'P1', 'source': 'openalex', 'family': 'same_problem', 'year': 2024,
                'published_date': '2024-05-01', 'title': 'Study A',
                'abstract': 'Method A tested.', 'text': 'Method A baseline.', 'retraction_status': 'clean',
            },
            'P2': {
                'id': 'P2', 'source': 'arxiv', 'family': 'cross_setting_analogy', 'year': 2025,
                'published_date': '2025-02-01', 'title': 'Study B',
                'abstract': 'Method B tested.', 'text': 'Method B baseline.', 'retraction_status': 'clean',
            },
        }
        digests = {
            'P1': {'source_id': 'P1', 'access': 'selected_full_text', 'digest': 'Baseline A'},
            'P2': {'source_id': 'P2', 'access': 'full_text', 'digest': 'Baseline B'},
        }
        pm = {
            'top_failure_modes': ['Spurious cue', 'Weak baseline', 'Metric artifact'],
            'killer_experiment': {'duration_days': 1.5, 'kill_threshold': 'Delta < 0.01'},
            'pivot_path': 'Pivot to diagnostic error slice.',
        }
        cands = [
            {
                'id': 'G1', 'claim': 'Gap 1 claim on calibration shift.',
                'cited_ids': ['P1', 'P2'], 'support_ids': ['P1', 'P2'], 'closest_work_ids': ['P1', 'P2'],
                'cutoff_year': 2026, 'sgha_critics_passed': True, 'engineering_checked': True,
                'consequence': 'Improves calibration.', 'pre_mortem': copy.deepcopy(pm),
                'idea_portfolio': [
                    {'id': 'G1_I1', 'angle': 'minimal_fix', 'title': 'Alpha scalar temp', 'summary': 'Single scalar.'},
                    {'id': 'G1_I2', 'angle': 'high_novelty_mechanism', 'title': 'Beta head gate', 'summary': 'Causal head routing.'},
                    {'id': 'G1_I3', 'angle': 'low_gpu_fallback', 'title': 'Gamma cpu norm', 'summary': 'Zero train norm.'},
                ],
            },
            {
                'id': 'G2', 'claim': 'Gap 2 claim on retrieval latency.',
                'cited_ids': ['P1', 'P2'], 'support_ids': ['P1', 'P2'], 'closest_work_ids': ['P1', 'P2'],
                'cutoff_year': 2026, 'sgha_critics_passed': True, 'engineering_checked': True,
                'consequence': 'Cuts tail latency.', 'pre_mortem': copy.deepcopy(pm),
                'idea_portfolio': [
                    {'id': 'G2_I1', 'angle': 'minimal_fix', 'title': 'Delta index prune', 'summary': 'Prune top-k.'},
                    {'id': 'G2_I2', 'angle': 'high_novelty_mechanism', 'title': 'Epsilon sparse route', 'summary': 'Learned sparse router.'},
                    {'id': 'G2_I3', 'angle': 'benchmark_diagnostic_analysis', 'title': 'Zeta latency bench', 'summary': 'Latency suite.'},
                ],
            },
        ]
        gp_out = gap_pipeline.run_pipeline(
            'calibration', corpus, digests, cands,
            subfield_preset='nlp_llm', require_idea_portfolio=True, require_pre_mortem=True,
        )
        bundle = gp_out['idea_seed_bundle']
        for seed in bundle['seeds']:
            for idea in seed['idea_portfolio']:
                idea['ratings'] = _idea_ratings((7, 7, 7, 7, 8, 7))
                idea['evidence_locators'] = {d: ['n.txt#L1 "ok"'] for d in score_math.IDEA_DIMENSIONS}
                idea['pre_mortem'] = copy.deepcopy(pm)
            seed['prior_art_boundary']['cited_ids'] = ['P1', 'P2']
            seed['prior_art_boundary']['support_ids'] = ['P1']

        res_ok = compare_scorecards.compare(bundle, mode='idea', idea_seed_bundle=bundle, require_idea_portfolio=True)
        self.assertEqual(res_ok['status'], 'structurally_comparable')
        self.assertEqual(res_ok['linkage_summary']['portfolio_distinct_ideas'], 6)

        bad_bundle = copy.deepcopy(bundle)
        for idea in bad_bundle['seeds'][1]['idea_portfolio']:
            idea['angle'] = 'minimal_fix'
            idea['canonical_angle'] = 'minimal_fix'
        res_bad = compare_scorecards.compare(bad_bundle, mode='idea', idea_seed_bundle=bad_bundle, require_idea_portfolio=True)
        self.assertEqual(res_bad['status'], 'not_comparable')
        self.assertTrue(any('tunnel_vision_idea_portfolio:G2' in i for i in res_bad['issues']))

    def test_bug10_low_compute_pareto_omitted_gpu_hours_never_dominates_reported(self):
        base_r = _idea_ratings((7, 6, 7, 8, 9, 7))
        locs = {d: ['n.txt#L1 "ok"'] for d in score_math.IDEA_DIMENSIONS}
        doc1 = {
            'mode': 'idea',
            'goal': 'low_compute_constrained',
            'profiles': [
                {
                    'id': 'I_honest_10h', 'object_type': 'idea', 'reading_basis': 'full_text',
                    'closest_work': ['P1'], 'angle': 'low_gpu_fallback', 'required_gpu_hours': 10,
                    'ratings': dict(base_r), 'evidence_locators': copy.deepcopy(locs),
                },
                {
                    'id': 'I_omitted_gpu', 'object_type': 'idea', 'reading_basis': 'full_text',
                    'closest_work': ['P1'], 'angle': 'minimal_fix',
                    'ratings': dict(base_r), 'evidence_locators': copy.deepcopy(locs),
                },
            ],
        }
        res1 = compare_scorecards.compare(doc1, mode='idea', goal='low_compute_constrained')
        pf1 = res1['pareto_frontier']
        self.assertIn('I_honest_10h', pf1['frontier_ids'])
        self.assertEqual(pf1['dominance_map']['I_honest_10h'], [])
        self.assertNotIn('I_omitted_gpu', pf1['dominance_map']['I_honest_10h'])
        self.assertEqual(pf1['goal_ranked_ids'][0], 'I_honest_10h')

        doc2 = {
            'mode': 'idea',
            'goal': 'low_compute_constrained',
            'profiles': [
                {
                    'id': 'I_zero_gpu', 'object_type': 'idea', 'reading_basis': 'full_text',
                    'closest_work': ['P1'], 'angle': 'minimal_fix', 'required_gpu_hours': 0,
                    'ratings': dict(base_r), 'evidence_locators': copy.deepcopy(locs),
                },
                {
                    'id': 'I_omitted_lowgpu_tag', 'object_type': 'idea', 'reading_basis': 'full_text',
                    'closest_work': ['P1'], 'angle': 'low_gpu_fallback',
                    'ratings': dict(base_r), 'evidence_locators': copy.deepcopy(locs),
                },
            ],
        }
        res2 = compare_scorecards.compare(doc2, mode='idea', goal='low_compute_constrained')
        pf2 = res2['pareto_frontier']
        self.assertEqual(pf2['frontier_ids'], ['I_zero_gpu'])
        self.assertNotIn('I_omitted_lowgpu_tag', pf2['dominance_map']['I_zero_gpu'])

    def test_safe_nits_sota_neg_halo_negation_subfield_fail_and_pipeline_wrapper(self):
        with self.assertRaises(ValueError):
            score_math.build_evidence_anchor_table(
                {'id': 't', 'sota_baselines_covered': -1},
                [{'id': 'a1', 'reading_basis': 'full_text', 'sota_baselines_covered': 3}],
            )

        halo = score_math.score({
            'weights': _paper_weights(),
            'ratings': _paper_ratings((7, 7, 7, 9, 7, 7)),
            'evidence_notes': 'Single seed only; no ablation or CI reported.',
        })
        self.assertIn('halo_warning:high_evidence_without_ci_seed_or_ablation', halo['sanity_warnings'])

        sf_res = score_math.evaluate_subfield_readiness(
            'nlp_llm',
            {'contamination_audit': True, 'contamination_check': 'fail'},
        )
        self.assertIn('contamination_check', sf_res['failed_checks'])

        # gap_pipeline wrapper dict accepted directly by compare_scorecards.compare
        wrapper = {
            'schema': 'research_scientist_gap_pipeline_v1',
            'idea_seed_bundle': {
                'schema': 'research_scientist_idea_seed_bundle_v1',
                'seeds': [{
                    'gap_id': 'G1',
                    'closest_work_ids': ['P1'],
                    'idea_portfolio': [
                        {'id': 'I1', 'angle': 'minimal_fix', 'ratings': None},
                        {'id': 'I2', 'angle': 'high_novelty_mechanism', 'ratings': None},
                    ],
                }],
            },
        }
        res_wrap = compare_scorecards.compare(wrapper, mode='idea')
        self.assertEqual(res_wrap['status'], 'not_comparable')
        self.assertTrue(any(i.startswith('missing_rating:') for i in res_wrap['issues']))


if __name__ == '__main__':
    unittest.main()
