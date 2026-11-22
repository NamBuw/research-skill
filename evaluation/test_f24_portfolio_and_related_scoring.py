"""Unmocked unit & contract tests for F24 (closest-work + portfolio) and F25 (cross-topic bar + tier rejection)."""
from __future__ import annotations

import copy
import decimal
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / 'research-scientist' / 'scripts'
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
report_latex_pdf = _load_module('report_latex_pdf', SCRIPTS_DIR / 'report_latex_pdf.py')


def _weights(vals=(15, 20, 20, 20, 15, 10)):
    return dict(zip(score_math.DIMENSIONS, vals))


def _ratings(vals):
    return dict(zip(score_math.DIMENSIONS, vals))


def _make_profile(pid, r_vals, src_dir: Path, closest_work=None, **extra):
    (src_dir / f'{pid}.txt').write_text(f'Full evidence text for {pid} method evaluation.\n', encoding='utf-8')
    loc = f'{pid}.txt#L1 "method evaluation"'
    return {
        'id': pid,
        'reading_basis': 'full_text',
        'closest_work': closest_work if closest_work is not None else ['PriorAlpha'],
        'ratings': _ratings(r_vals),
        'evidence_locators': {d: [loc] for d in score_math.DIMENSIONS},
        **extra,
    }


def _make_venue_candidate(
    base_fixture: dict,
    venue_id: str,
    *,
    name: str,
    edition: str = '2027',
    track: str = 'Main Track',
    role: str = 'alternative',
    fit_scores=(2, 2, 2, 2, 2),
    deadline_status='met',
    budget_status='met',
    elig_status='met',
    checked_at='2026-11-21T10:00:00Z',
    include_panel=True,
    panel_scores=(4, 5, 6, 7, 8),
    panel_overalls=None,
    topic_relations=None,
    tier_expectation=None,
    submission_deadline_utc=None,
    notification_date_utc=None,
    simultaneous_submission_allowed=None,
):
    cand = {
        'venue_id': venue_id,
        'role': role,
        'venue': {
            'name': name,
            'edition': edition,
            'track': track,
            'official_cfp_url': f'https://example.org/{venue_id}/cfp',
            'checked_at_utc': checked_at,
            'max_source_age_days': 14,
        },
        'fit_axes': [],
        'hard_constraints': [],
    }
    if tier_expectation is not None:
        cand['tier_expectation'] = tier_expectation
    if submission_deadline_utc is not None:
        cand['venue']['submission_deadline_utc'] = submission_deadline_utc
    if notification_date_utc is not None:
        cand['venue']['notification_date_utc'] = notification_date_utc
    if simultaneous_submission_allowed is not None:
        cand['venue']['simultaneous_submission_allowed'] = simultaneous_submission_allowed

    for ax, sc in zip(compare_venue_novelty.AXES, fit_scores):
        cand['fit_axes'].append({
            'name': ax,
            'score': sc,
            'source_url': f'https://example.org/{venue_id}/cfp',
            'locator': f'{venue_id} CFP {ax} section',
            'reason': f'{ax} checked',
        })
    for cname, cst in zip(compare_venue_novelty.HARD_CONSTRAINTS, (deadline_status, budget_status, elig_status)):
        row = {'name': cname, 'status': cst, 'reason': f'{cname} {cst}'}
        if cst in ('met', 'failed'):
            row['source_url'] = f'https://example.org/{venue_id}/cfp'
        cand['hard_constraints'].append(row)

    if include_panel:
        cand['panel_selection'] = copy.deepcopy(base_fixture['panel_selection'])
        panel = copy.deepcopy(base_fixture['accepted_panel'])
        for i, item in enumerate(panel):
            item['id'] = f'{venue_id}-P{i+1}'
            item['track'] = track
            item['score'] = panel_scores[i]
            item['low'] = max(0, panel_scores[i] - 1)
            item['high'] = min(10, panel_scores[i] + 1)
            if panel_overalls is not None:
                item['overall_score'] = panel_overalls[i]
            if topic_relations is not None:
                item['topic_relation'] = topic_relations[i]
        cand['accepted_panel'] = panel
    return cand


class TestF24PartAClosestRelatedWorkScorecardGate(unittest.TestCase):
    def test_backward_compatibility_without_target_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            src_dir = Path(tmp)
            doc = {
                'weight_scenarios': [_weights()],
                'profiles': [
                    _make_profile('p1', (7, 6, 7, 6, 6, 6), src_dir, closest_work=['UnscoredPrior']),
                    _make_profile('p2', (8, 7, 7, 7, 7, 7), src_dir, closest_work=['p1']),
                ],
            }
            out = compare_scorecards.compare(doc, sources_dir=src_dir)
            self.assertEqual(out['status'], 'structurally_comparable')
            self.assertEqual(
                [list(r.keys()) for r in out['rankings'][0]['ordered']],
                [['id', 'weighted_unrounded'], ['id', 'weighted_unrounded']],
            )
            self.assertEqual(out['unscored_closest_work_ids']['p1'], ['UnscoredPrior'])
            self.assertEqual(out['unscored_closest_work_ids']['p2'], [])
            self.assertNotIn('related_work_comparison', out)

    def test_strict_related_panel_passes_with_three_verified_papers(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            src_dir = tmp_dir / 'sources'
            src_dir.mkdir()
            doc = {
                'weight_scenarios': [_weights()],
                'profiles': [
                    _make_profile(
                        'target',
                        (7, 7, 7, 6, 6, 6),
                        src_dir,
                        closest_work=['rw1', 'rw2', 'rw3'],
                        contribution_delta='Isolates attention routing invariance under clean split',
                        baseline_tradeoff_explanation='Uses 15% less compute than rw2 at equal accuracy',
                    ),
                    _make_profile('rw1', (6, 6, 7, 6, 6, 6), src_dir, closest_work=['rw2']),
                    _make_profile('rw2', (8, 7, 8, 7, 7, 7), src_dir, closest_work=['rw1']),
                    _make_profile('rw3', (6, 5, 6, 6, 6, 6), src_dir, closest_work=['rw1']),
                ],
            }
            sc_path = tmp_dir / 'sc.json'
            out_path = tmp_dir / 'sc_out.json'
            sc_path.write_text(json.dumps(doc), encoding='utf-8')

            cli = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / 'compare_scorecards.py'),
                    str(sc_path),
                    '--target-id', 'target',
                    '--strict-related-panel',
                    '--min-related', '3',
                    '--sources-dir', str(src_dir),
                    '--out', str(out_path),
                    '--compact',
                ],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(cli.returncode, 0, cli.stderr + cli.stdout)
            self.assertLess(len(cli.stdout.encode('utf-8')), 4096)
            compact = json.loads(cli.stdout)
            rwc = compact['related_work_comparison']
            self.assertEqual(rwc['target_id'], 'target')
            self.assertEqual(rwc['scored_related_ids'], ['rw1', 'rw2', 'rw3'])
            self.assertEqual(rwc['unscored_closest_work_ids'], [])
            self.assertEqual(rwc['best_related_overall'], 7.35)
            self.assertEqual(rwc['target_delta_vs_best_related_overall'], -0.8)
            self.assertEqual(rwc['max_related_by_dimension']['soundness'], 8)
            self.assertEqual(rwc['dimension_deltas_vs_max_related']['soundness'], -1)
            self.assertEqual(rwc['novelty_inflation_warnings'], [])

    def test_strict_related_panel_fails_closed_on_missing_and_self_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            src_dir = Path(tmp)
            # 1. Missing closest_work profile + < 3 related papers
            doc_missing = {
                'weight_scenarios': [_weights()],
                'profiles': [
                    _make_profile('target', (7, 6, 7, 6, 6, 6), src_dir, closest_work=['rw1', 'MissingPrior']),
                    _make_profile('rw1', (6, 6, 6, 6, 6, 6), src_dir, closest_work=['target']),
                    _make_profile('rw2', (6, 6, 6, 6, 6, 6), src_dir, closest_work=['target']),
                ],
            }
            out_m = compare_scorecards.compare(
                doc_missing, sources_dir=src_dir, target_id='target', strict_related_panel=True, min_related=3
            )
            self.assertEqual(out_m['status'], 'not_comparable')
            self.assertIn('unscored_closest_work:MissingPrior', out_m['issues'])
            self.assertIn('insufficient_scored_related_papers:2<3', out_m['issues'])

            # 2. Self-reference in closest_work
            doc_self = {
                'weight_scenarios': [_weights()],
                'profiles': [
                    _make_profile('target', (7, 6, 7, 6, 6, 6), src_dir, closest_work=['target', 'rw1']),
                    _make_profile('rw1', (6, 6, 6, 6, 6, 6), src_dir, closest_work=['rw2']),
                    _make_profile('rw2', (6, 6, 6, 6, 6, 6), src_dir, closest_work=['rw1']),
                    _make_profile('rw3', (6, 6, 6, 6, 6, 6), src_dir, closest_work=['rw1']),
                ],
            }
            out_s = compare_scorecards.compare(doc_self, sources_dir=src_dir, target_id='target', strict_related_panel=True)
            self.assertEqual(out_s['status'], 'not_comparable')
            self.assertIn('closest_work_self_reference:target', out_s['issues'])

            # 3. Missing target_id with strict_related_panel=True
            out_no_tgt = compare_scorecards.compare(doc_self, sources_dir=src_dir, strict_related_panel=True)
            self.assertEqual(out_no_tgt['status'], 'not_comparable')
            self.assertIn('target_id_required_for_strict_related_panel', out_no_tgt['issues'])

            # 4. Target ID not in profiles
            out_bad_tgt = compare_scorecards.compare(doc_self, sources_dir=src_dir, target_id='nonexistent')
            self.assertEqual(out_bad_tgt['status'], 'not_comparable')
            self.assertIn('target_profile_not_found:nonexistent', out_bad_tgt['issues'])

    def test_novelty_inflation_warnings_and_decimal_traps(self):
        with tempfile.TemporaryDirectory() as tmp:
            src_dir = Path(tmp)
            doc = {
                'weight_scenarios': [_weights()],
                'profiles': [
                    _make_profile('target', (7, 8, 5, 5, 6, 6), src_dir, closest_work=['rw1', 'rw2', 'rw3']),
                    _make_profile('rw1', (7, 6, 8, 8, 7, 7), src_dir, closest_work=['rw2']),
                    _make_profile('rw2', (6, 5, 7, 7, 6, 6), src_dir, closest_work=['rw1']),
                    _make_profile('rw3', (6, 5, 7, 7, 6, 6), src_dir, closest_work=['rw1']),
                ],
            }
            with decimal.localcontext() as ctx:
                ctx.prec = 1
                ctx.rounding = decimal.ROUND_DOWN
                ctx.traps[decimal.Inexact] = True
                ctx.traps[decimal.Rounded] = True
                ctx.traps[decimal.FloatOperation] = True
                out = compare_scorecards.compare(
                    doc, sources_dir=src_dir, target_id='target', strict_related_panel=True, min_related=3
                )
            self.assertEqual(out['status'], 'structurally_comparable')
            warns = out['related_work_comparison']['novelty_inflation_warnings']
            self.assertIn('novelty_inflation_risk:missing_contribution_delta', warns)
            self.assertIn('novelty_inflation_risk:soundness_or_evidence_trails_related_baseline', warns)


class TestF24PartBAndF25PortfolioAndCrossTopicTierGate(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((ROOT / 'research-scientist' / 'references' / 'venue-novelty-profile.fixture.json').read_text(encoding='utf-8'))
        self.as_of = datetime(2026, 11, 21, 12, tzinfo=timezone.utc)

    def test_score_math_tier_floors_decimal_trap_safe(self):
        with decimal.localcontext() as ctx:
            ctx.prec = 1
            ctx.rounding = decimal.ROUND_DOWN
            ctx.traps[decimal.Inexact] = True
            ctx.traps[decimal.Rounded] = True
            ctx.traps[decimal.FloatOperation] = True
            res = score_math.evaluate_venue_tier_fit(
                'q1_or_tier_a',
                weighted_unrounded='5.40',
                ratings=_ratings((6, 4, 6, 5, 6, 6)),
                target_novelty=4,
                panel_median_novelty=6,
                target_vs_venue_overall_delta=-1.2,
            )
        self.assertTrue(res['rejected_below_venue_tier'])
        self.assertEqual(res['recommended_matched_tier'], 'workshop_or_preliminary')
        self.assertIn('weighted_to_min_viable', res['upgrade_gaps_to_target_tier'])
        self.assertEqual(res['upgrade_gaps_to_target_tier']['novelty'], 1)
        self.assertEqual(res['upgrade_gaps_to_target_tier']['evidence'], 1)

    def test_cross_topic_venue_contribution_bar_and_no_fabrication(self):
        # Panel without overall_score/ratings -> panel_median_overall must remain None (never fabricated)
        base_out = compare_venue_novelty.check(copy.deepcopy(self.fixture), self.as_of)
        self.assertIsNone(base_out['venue_contribution_bar']['panel_median_overall'])

        # Cross-topic ("different_topic") panel at Q1 venue with 6.80 median overall vs workshop-scale 5.40 target
        prof = copy.deepcopy(self.fixture)
        prof['venue']['name'] = 'IEEE Transactions on Knowledge and Data Engineering'
        prof['venue']['track'] = 'Regular Papers'
        prof['tier_expectation'] = 'q1_or_tier_a'
        prof['target']['score'] = 5
        prof['target']['low'] = 4
        prof['target']['high'] = 6
        prof['target_scorecard'] = {
            'weights': _weights(),
            'ratings': _ratings((6, 5, 6, 5, 6, 6)),  # 5.60 < 6.00, delta = -1.20 vs 6.80
        }
        for idx, item in enumerate(prof['accepted_panel']):
            item['track'] = 'Regular Papers'
            item['topic_relation'] = 'different_topic'
            item['overall_score'] = [6.4, 6.6, 6.8, 7.1, 7.3][idx]
            item['score'] = [5, 6, 6, 7, 7][idx]
            item['low'] = item['score'] - 1
            item['high'] = item['score'] + 1

        out = compare_venue_novelty.check(prof, self.as_of)
        bar = out['venue_contribution_bar']
        self.assertEqual(bar['different_topic_count'], 5)
        self.assertEqual(bar['cross_topic_count'], 5)
        self.assertEqual(bar['panel_median_overall'], 6.8)
        self.assertEqual(bar['target_overall_score'], 5.6)
        self.assertEqual(bar['target_vs_venue_overall_delta'], -1.2)
        # Hard rejection (NEVER stretch_high_risk)
        sr = out['submission_readiness']
        self.assertEqual(sr['verdict'], 'rejected_below_venue_tier')
        self.assertFalse(sr['ready_to_submit'])
        self.assertEqual(sr['recommended_matched_tier'], 'q2_q3_or_tier_b')
        self.assertIn('overall_vs_venue_panel_median', sr['upgrade_gaps_to_target_tier'])

    def test_portfolio_635_classification_hold_and_timeline_conflict(self):
        target = copy.deepcopy(self.fixture['target'])
        target['score'] = 6
        target['low'] = 5
        target['high'] = 7
        cands = [
            _make_venue_candidate(
                self.fixture, 'neurips-main', name='NeurIPS', track='Main Track', role='primary',
                fit_scores=(2, 2, 2, 2, 1),  # fit 9/10, 6.35 < 6.80 competitive -> stretch_high_risk (meets 6.00 min viable)
                notification_date_utc='2027-09-25T23:59:00Z', simultaneous_submission_allowed=False,
            ),
            _make_venue_candidate(
                self.fixture, 'emnlp-findings', name='EMNLP', track='Findings', role='alternative',
                fit_scores=(2, 2, 2, 1, 1),  # fit 8/10, Findings q1_or_tier_a -> recommended_now
            ),
            _make_venue_candidate(
                self.fixture, 'coling-fallback', name='COLING', track='Main Track', role='fallback',
                fit_scores=(2, 2, 1, 1, 1),  # fit 7/10, CCF-B q1_or_tier_a matches 6.35 >= 6.00, clean post-notification deadline
                submission_deadline_utc='2027-10-15T23:59:00Z', simultaneous_submission_allowed=False,
            ),
            _make_venue_candidate(
                self.fixture, 'conflicted-fb', name='ICLR', track='Main Track', role='fallback',
                fit_scores=(2, 2, 2, 1, 1),
                submission_deadline_utc='2027-08-01T23:59:00Z', simultaneous_submission_allowed=False,
            ),
            _make_venue_candidate(
                self.fixture, 'expired-conf', name='IJCAI', track='Main Track', role='alternative',
                deadline_status='failed',
            ),
        ]
        port = {
            'target': target,
            'target_scorecard': {'weights': _weights(), 'ratings': _ratings((7, 6, 7, 6, 6, 6))},  # 6.35
            'candidate_venues': cands,
        }
        out = compare_venue_novelty.check(port, self.as_of, portfolio=True)
        self.assertEqual(out['status'], 'structurally_checked')
        rec = out['venue_portfolio_recommendations']
        self.assertEqual(rec['recommended_now'], ['emnlp-findings'])
        self.assertEqual(rec['stretch_high_risk'], ['neurips-main'])
        self.assertEqual(rec['viable_fallback'], ['coling-fallback'])
        self.assertEqual(rec['conflicted_fallback'], ['conflicted-fb'])
        self.assertEqual(rec['disqualified'], ['expired-conf'])
        self.assertEqual(len(rec['timeline_conflicts']), 1)

        # Hold for rework on fatal soundness=4
        hold_port = copy.deepcopy(port)
        hold_port['target_scorecard']['ratings'] = _ratings((9, 8, 4, 8, 8, 8))
        hold_out = compare_venue_novelty.check(hold_port, self.as_of, portfolio=True)
        hrec = hold_out['venue_portfolio_recommendations']
        self.assertEqual(hrec['portfolio_verdict'], 'hold_for_rework')
        self.assertTrue(hrec['hold_for_rework'])
        self.assertEqual(hrec['recommended_now'], [])
        self.assertEqual(hrec['stretch_high_risk'], [])
        self.assertEqual(hrec['viable_fallback'], [])

    def test_f25_workshop_paper_targeting_q1_rejected_and_retargeted(self):
        target = copy.deepcopy(self.fixture['target'])
        target['score'] = 4
        target['low'] = 3
        target['high'] = 5
        # Workshop-scale 5.40 (passes fatal thresholds, below Q1 >=6.00 & novelty=4<5 & evidence=5<6)
        cands = [
            _make_venue_candidate(
                self.fixture, 'q1-journal', name='TKDE', track='Regular Track', role='primary',
                tier_expectation='q1_or_tier_a',
                panel_scores=(5, 6, 6, 7, 7),
                panel_overalls=(6.5, 6.7, 6.9, 7.1, 7.2),
                topic_relations=('different_topic',) * 5,
            ),
            _make_venue_candidate(
                self.fixture, 'top-flagship', name='NeurIPS', track='Main Track', role='alternative',
                panel_scores=(5, 6, 6, 7, 7),
                panel_overalls=(6.6, 6.8, 7.0, 7.2, 7.4),
                topic_relations=('different_topic',) * 5,
            ),
            _make_venue_candidate(
                self.fixture, 'verified-workshop', name='NeurIPS Workshop on Trustworthy AI', track='Workshop', role='alternative',
                fit_scores=(2, 2, 2, 2, 2),
                panel_scores=(3, 4, 4, 5, 5),
                panel_overalls=(5.1, 5.3, 5.4, 5.6, 5.8),
                topic_relations=('adjacent_topic', 'different_topic', 'different_topic', 'same_topic', 'different_topic'),
            ),
        ]
        port = {
            'target': target,
            'target_scorecard': {'weights': _weights(), 'ratings': _ratings((6, 4, 6, 5, 6, 6))},  # 5.40
            'candidate_venues': cands,
        }
        out = compare_venue_novelty.check(port, self.as_of, portfolio=True)
        self.assertEqual(out['status'], 'structurally_checked')
        rec = out['venue_portfolio_recommendations']
        self.assertEqual(rec['stretch_high_risk'], [])  # NEVER stretch_high_risk!
        self.assertEqual(set(rec['rejected_below_venue_tier']), {'q1-journal', 'top-flagship'})
        self.assertEqual(rec['recommended_now'], ['verified-workshop'])
        self.assertEqual(rec['recommended_matched_tier']['top_venue_id'], 'verified-workshop')
        self.assertEqual(rec['portfolio_verdict'], 'retargeted_to_matched_tier')

        # Portfolio with ONLY Q1/Top-Tier venues -> no_viable_venue_in_portfolio
        only_high = copy.deepcopy(port)
        only_high['candidate_venues'][2] = _make_venue_candidate(
            self.fixture, 'icml-main', name='ICML', track='Main Track', role='alternative',
            panel_scores=(5, 6, 6, 7, 7),
        )
        no_viable = compare_venue_novelty.check(only_high, self.as_of, portfolio=True)
        self.assertEqual(no_viable['venue_portfolio_recommendations']['portfolio_verdict'], 'no_viable_venue_in_portfolio')
        self.assertEqual(no_viable['venue_portfolio_recommendations']['recommended_matched_tier']['recommended_venues'], [])
        self.assertIn('Workshop', no_viable['venue_portfolio_recommendations']['recommended_matched_tier']['action_if_empty'])

    def test_portfolio_validation_12_venue_compact_and_report_pdf_strict(self):
        # < 3 venues -> invalid exit 1
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            small_p = tmp_dir / 'small.json'
            small_p.write_text(json.dumps({
                'target': self.fixture['target'],
                'candidate_venues': [_make_venue_candidate(self.fixture, 'v1', name='ACL')],
            }), encoding='utf-8')
            r_small = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / 'compare_venue_novelty.py'), str(small_p), '--portfolio'],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(r_small.returncode, 1)

            # 12-venue portfolio --compact < 4096B
            cands_12 = [
                _make_venue_candidate(self.fixture, f'venue_{i:02d}_longname', name=f'Conf{i}', track='Main Track')
                for i in range(12)
            ]
            p12 = tmp_dir / 'p12.json'
            p12.write_text(json.dumps({
                'target': self.fixture['target'],
                'target_scorecard': {'weights': _weights(), 'ratings': _ratings((7, 6, 7, 6, 6, 6))},
                'candidate_venues': cands_12,
            }), encoding='utf-8')
            r12 = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / 'compare_venue_novelty.py'), str(p12), '--portfolio', '--compact'],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(r12.returncode, 0, r12.stderr)
            self.assertLess(len(r12.stdout.encode('utf-8')), 4096)

            # report_latex_pdf on hold_for_rework portfolio never reports pass/supported
            hold_out = compare_venue_novelty.check(
                {
                    'target': {**self.fixture['target'], 'score': 2, 'low': 1, 'high': 3},
                    'candidate_venues': cands_12[:3],
                },
                self.as_of,
                portfolio=True,
            )
            norm_hold = report_latex_pdf.normalize_report_input(hold_out)
            self.assertNotIn(norm_hold['verdict']['status'], ('pass', 'supported'))
            rep_hold = report_latex_pdf.generate_report(hold_out, tmp_dir / 'hold.pdf', strict=True, compact=True)
            self.assertEqual(rep_hold['status'], 'ok', rep_hold)

    def test_prompts_references_en_vi_strict_examples_and_claim_audit(self):
        for s in (
            'research-scientist', 'research-precedent-corpus', 'research-gap-rq-audit',
            'research-experiment-coding', 'research-novelty-venue', 'research-paper-writing',
            'research-user-report',
        ):
            fp = claim_audit._measure_skill_footprint((ROOT / s / 'SKILL.md').read_text(encoding='utf-8'))
            self.assertLess(fp['lines'], 50, s)
            self.assertLess(fp['est_tokens'], 900, s)
            self.assertLess(fp['frontmatter_est_tokens'], 140, s)

        for lang, title, summary in [
            (
                'en',
                'Portfolio & Related-Work Submission Readiness',
                'Target scores 6.35/10 (-0.45 vs 6.80; -0.65 vs best related work 7.00) [scorecards.json]. Recommended now: EMNLP Findings (fit 8/10); NeurIPS Main Track is stretch_high_risk [portfolio.json].',
            ),
            (
                'vi',
                'Đánh giá khả năng nộp bài và danh mục hội nghị',
                'Bài đạt 6.35/10 (kém bài liên quan mạnh nhất 0.65 điểm) [scorecards.json]. Nên nộp EMNLP Findings (fit 8/10); NeurIPS Main Track ở mức rủi ro cao [portfolio.json].',
            ),
            (
                'vi',
                'Bác bỏ mục tiêu Q1 và chuyển hướng hội thảo',
                'Bài đạt 5.40/10, chưa đạt ngưỡng tạp chí Q1 (tối thiểu 6.00/10) [portfolio.json]. Đề xuất chuyển hướng sang hội thảo kiểm chứng đạt 8/10 độ phù hợp [portfolio.json].',
            ),
        ]:
            doc = {
                'schema': 'research_scientist_executive_report_v1',
                'report_type': 'novelty_scoring',
                'lang': lang,
                'title': title,
                'verdict': {'status': 'caution', 'summary': summary, 'evidence_refs': ['SC1', 'PF1']},
                'key_evidence': [
                    {'id': 'SC1', 'claim': 'Scorecard', 'value': '6.35/10', 'status': 'verified', 'locator': 'scorecards.json'},
                    {'id': 'PF1', 'claim': 'Portfolio', 'value': 'verified', 'status': 'verified', 'locator': 'portfolio.json'},
                ],
                'flaws_and_risks': [{'id': 'R1', 'severity': 'medium', 'summary': 'Check gap [scorecards.json].', 'locator': 'scorecards.json'}],
                'next_steps': [{'step': 1, 'action': 'Submit to matched venue.', 'target': 'portfolio.json'}],
            }
            lint = report_latex_pdf.lint_report(doc, lang=lang)
            self.assertTrue(lint['passed'], f'{lang}: {lint}')
            self.assertEqual(lint['error_count'], 0, lint)
            self.assertEqual(lint['warn_count'], 0, lint)

        ca = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / 'claim_audit.py'), '--suite-root', str(ROOT), '--readme', str(ROOT / 'README.md'), '--json'],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(ca.returncode, 0, ca.stdout + ca.stderr)
        self.assertEqual(json.loads(ca.stdout)['finding_count'], 0)

    def test_wave2_portfolio_timeline_conflict_without_primary_stretch_before_recommended(self):
        target = copy.deepcopy(self.fixture['target'])
        target['score'] = 6
        target['low'] = 5
        target['high'] = 7
        cands = [
            # Stretch high-risk candidate at index 0 with NO notification_date_utc and NO role='primary'
            _make_venue_candidate(
                self.fixture, 'neurips-stretch', name='NeurIPS', track='Main Track', role='alternative',
                fit_scores=(2, 2, 2, 2, 2),
            ),
            # Recommended candidate at index 1 WITH notification_date_utc and simultaneous_submission_allowed=False
            _make_venue_candidate(
                self.fixture, 'emnlp-rec', name='EMNLP', track='Findings', role='alternative',
                fit_scores=(2, 2, 2, 2, 2),
                notification_date_utc='2027-09-25T23:59:00Z', simultaneous_submission_allowed=False,
            ),
            # Fallback whose deadline precedes emnlp-rec notification
            _make_venue_candidate(
                self.fixture, 'coling-fb', name='COLING', track='Main Track', role='fallback',
                fit_scores=(2, 2, 1, 1, 1),
                submission_deadline_utc='2027-08-01T23:59:00Z', simultaneous_submission_allowed=False,
            ),
        ]
        # Also verify venue_tier forwarding when tier_expectation is omitted on a candidate
        cands[2]['venue_tier'] = 'q1_or_tier_a'
        port = {
            'target': target,
            'target_scorecard': {'weights': _weights(), 'ratings': _ratings((7, 6, 7, 6, 6, 6))},
            'candidate_venues': cands,
        }
        out = compare_venue_novelty.check(port, self.as_of, portfolio=True)
        self.assertEqual(out['status'], 'structurally_checked')
        rec = out['venue_portfolio_recommendations']
        self.assertEqual(rec['recommended_now'], ['emnlp-rec'])
        self.assertEqual(rec['stretch_high_risk'], ['neurips-stretch'])
        self.assertEqual(rec['viable_fallback'], [])
        self.assertEqual(rec['conflicted_fallback'], ['coling-fb'])
        self.assertEqual(len(rec['timeline_conflicts']), 1)
        self.assertEqual(rec['timeline_conflicts'][0]['conflict_type'], 'double_submission_timeline_conflict')
        self.assertEqual(rec['timeline_conflicts'][0]['primary_venue_id'], 'emnlp-rec')
        self.assertEqual(rec['timeline_conflicts'][0]['fallback_venue_id'], 'coling-fb')
        coling_ev = next(ve for ve in out['venue_evaluations'] if ve['venue_id'] == 'coling-fb')
        self.assertEqual(coling_ev['submission_readiness'].get('venue_tier'), 'q1_or_tier_a')

    def test_wave2_single_venue_compact_under_4096_with_60_skipped_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            src_dir = tmp_dir / 'sources_skip'
            src_dir.mkdir()
            prof = copy.deepcopy(self.fixture)
            prof['venue']['checked_at_utc'] = datetime.now(timezone.utc).isoformat()
            (src_dir / 'FICTIONAL-PRIOR-A.txt').write_text(
                'Section 3\nPrior work omits the graph shift intervention under boundary B.\n',
                encoding='utf-8',
            )
            prof['target']['closest_work_locator'] = (
                'FICTIONAL-PRIOR-A.txt:2: "Prior work omits the graph shift intervention"'
            )
            for idx, item in enumerate(prof['accepted_panel']):
                pid = item['closest_work_id']
                (src_dir / f'{pid}.txt').write_text(
                    f'Section 2\nPanel reference {idx + 1} reports bounded delta.\n',
                    encoding='utf-8',
                )
                item['closest_work_locator'] = f'{pid}.txt:2: "Panel reference {idx + 1} reports bounded delta."'
            bundle = {
                'format': 'research_scientist_venue_sources_v1',
                'sources': [
                    {'requested_url': 'https://example.org/fictional-cfp', 'final_url': 'https://example.org/fictional-cfp', 'extraction_status': 'ok', 'text': 'Main scope covers graph learning. Contribution tracks include empirical mechanism studies.'},
                    {'requested_url': 'https://example.org/fictional-p3', 'final_url': 'https://example.org/fictional-p3', 'extraction_status': 'ok', 'text': 'Methods section specifies multi-seed ablations and comparator controls.'},
                    {'requested_url': 'https://example.org/fictional-policy', 'final_url': 'https://example.org/fictional-policy', 'extraction_status': 'ok', 'text': 'Submission rules require 8 pages plus references and double-blind PDF.'},
                    {'requested_url': 'https://example.org/fictional-fees', 'final_url': 'https://example.org/fictional-fees', 'extraction_status': 'ok', 'text': 'Fee schedule: USD 750 early author registration.'},
                ],
            }
            (src_dir / 'venue-sources.json').write_text(json.dumps(bundle), encoding='utf-8')
            prof['fit_axes'][0]['locator'] = '"Main scope covers graph learning"'
            prof['fit_axes'][1]['locator'] = '"empirical mechanism studies"'
            prof['fit_axes'][2]['locator'] = '"multi-seed ablations"'
            prof['fit_axes'][3]['locator'] = '"8 pages plus references"'
            prof['fit_axes'][4]['locator'] = '"USD 750 early author registration"'

            for i in range(60):
                (src_dir / f'ignored_junk_file_name_{i:02d}.json').write_text(json.dumps({'junk': i}), encoding='utf-8')

            p_path = tmp_dir / 'single.json'
            out_path = tmp_dir / 'single_out.json'
            p_path.write_text(json.dumps(prof), encoding='utf-8')
            cli = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / 'compare_venue_novelty.py'),
                    str(p_path),
                    '--sources-dir', str(src_dir),
                    '--out', str(out_path),
                    '--compact',
                ],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
            self.assertLess(len(cli.stdout.encode('utf-8')), 4096)
            compact = json.loads(cli.stdout)
            self.assertNotIn('skipped_files', compact['locator_verification'])
            self.assertEqual(compact['locator_verification']['skipped_files_count'], 60)
            full_out = json.loads(out_path.read_text(encoding='utf-8'))
            self.assertEqual(len(full_out['locator_verification']['skipped_files']), 60)

    def test_wave3_multiple_recommended_now_anchors_detects_fallback_conflict(self):
        target = copy.deepcopy(self.fixture['target'])
        target['score'] = 6
        target['low'] = 5
        target['high'] = 7
        for sim_fast in (False, True):
            cands = [
                _make_venue_candidate(
                    self.fixture, 'rec_fast', name='EMNLP', track='Findings', role='alternative',
                    fit_scores=(2, 2, 2, 2, 2),
                    notification_date_utc='2027-08-15T23:59:00Z',
                    simultaneous_submission_allowed=sim_fast,
                ),
                _make_venue_candidate(
                    self.fixture, 'rec_slow', name='ACL', track='Findings', role='alternative',
                    fit_scores=(2, 2, 2, 1, 1),
                    notification_date_utc='2027-10-15T23:59:00Z',
                    simultaneous_submission_allowed=False,
                ),
                _make_venue_candidate(
                    self.fixture, 'fb_mid', name='COLING', track='Main Track', role='fallback',
                    fit_scores=(2, 2, 1, 1, 1),
                    submission_deadline_utc='2027-09-15T23:59:00Z',
                    simultaneous_submission_allowed=False,
                ),
            ]
            cands[2]['venue_tier'] = 'q1_or_tier_a'
            port = {
                'target': target,
                'target_scorecard': {'weights': _weights(), 'ratings': _ratings((7, 6, 7, 6, 6, 6))},
                'candidate_venues': cands,
            }
            out = compare_venue_novelty.check(port, self.as_of, portfolio=True)
            self.assertEqual(out['status'], 'structurally_checked')
            rec = out['venue_portfolio_recommendations']
            self.assertEqual(rec['recommended_now'], ['rec_fast', 'rec_slow'])
            self.assertEqual(rec['viable_fallback'], [])
            self.assertEqual(rec['conflicted_fallback'], ['fb_mid'])
            self.assertTrue(
                any(
                    c['conflict_type'] == 'double_submission_timeline_conflict'
                    and c['primary_venue_id'] == 'rec_slow'
                    and c['fallback_venue_id'] == 'fb_mid'
                    for c in rec['timeline_conflicts']
                ),
                rec['timeline_conflicts'],
            )

    def test_wave3_compact_12_long_venue_ids_and_3600b_out_and_35_venue_strict_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            src_dir = tmp_dir / 'src_w3'
            src_dir.mkdir()
            (src_dir / 'FICTIONAL-PRIOR-A.txt').write_text(
                'Section 3\nPrior work omits the graph shift intervention under boundary B.\n',
                encoding='utf-8',
            )
            bundle = {
                'format': 'research_scientist_venue_sources_v1',
                'sources': [
                    {
                        'requested_url': f'https://example.org/venue_{i:02d}_' + 'x' * 151 + '/cfp',
                        'final_url': f'https://example.org/venue_{i:02d}_' + 'x' * 151 + '/cfp',
                        'extraction_status': 'ok',
                        'text': 'CFP verified details.',
                    }
                    for i in range(12)
                ] + [
                    {'requested_url': 'https://example.org/fictional-cfp', 'final_url': 'https://example.org/fictional-cfp', 'extraction_status': 'ok', 'text': 'Main scope covers graph learning. Contribution tracks include empirical mechanism studies.'},
                    {'requested_url': 'https://example.org/fictional-p3', 'final_url': 'https://example.org/fictional-p3', 'extraction_status': 'ok', 'text': 'Methods section specifies multi-seed ablations and comparator controls.'},
                    {'requested_url': 'https://example.org/fictional-policy', 'final_url': 'https://example.org/fictional-policy', 'extraction_status': 'ok', 'text': 'Submission rules require 8 pages plus references and double-blind PDF.'},
                    {'requested_url': 'https://example.org/fictional-fees', 'final_url': 'https://example.org/fictional-fees', 'extraction_status': 'ok', 'text': 'Fee schedule: USD 750 early author registration.'},
                ],
            }
            (src_dir / 'venue-sources.json').write_text(json.dumps(bundle), encoding='utf-8')
            for idx, item in enumerate(self.fixture['accepted_panel']):
                pid = item['closest_work_id']
                (src_dir / f'{pid}.txt').write_text(f'Section 2\nPanel reference {idx + 1} reports bounded delta.\n', encoding='utf-8')
            for i in range(60):
                (src_dir / f'junk_{i:02d}.json').write_text('{}', encoding='utf-8')

            # 1. Portfolio with 12 x 160-char venue_ids + 3600B --out path + 60 skipped files
            long_cands = [
                _make_venue_candidate(
                    self.fixture,
                    f'venue_{i:02d}_' + 'x' * 151,
                    name=f'Conf{i}',
                    track='Main Track',
                    checked_at=datetime.now(timezone.utc).isoformat(),
                )
                for i in range(12)
            ]
            for c in long_cands:
                for ax in c['fit_axes']:
                    ax['locator'] = '"CFP verified details."'
                for idx, item in enumerate(c['accepted_panel']):
                    pid = item['closest_work_id']
                    item['closest_work_locator'] = f'{pid}.txt:2: "Panel reference {idx + 1} reports bounded delta."'
            target = copy.deepcopy(self.fixture['target'])
            target['closest_work_locator'] = 'FICTIONAL-PRIOR-A.txt:2: "Prior work omits the graph shift intervention"'
            port_12 = {
                'target': target,
                'target_scorecard': {'weights': _weights(), 'ratings': _ratings((7, 6, 7, 6, 6, 6))},
                'candidate_venues': long_cands,
            }
            p12_path = tmp_dir / 'p12_long.json'
            p12_path.write_text(json.dumps(port_12), encoding='utf-8')

            # Reproducer 2A: short --out with 12 x 160-char venue_ids stays < 4096B
            short_port_out = tmp_dir / 'short_out.json'
            cli_2a = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / 'compare_venue_novelty.py'),
                    str(p12_path),
                    '--portfolio',
                    '--out', str(short_port_out),
                    '--compact',
                ],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(cli_2a.returncode, 0, cli_2a.stdout + cli_2a.stderr)
            self.assertLess(len(cli_2a.stdout.encode('utf-8')), 4096)

            long_dir = tmp_dir
            for _ in range(18):
                long_dir = long_dir / ('d' * 190)
            long_dir.mkdir(parents=True)
            long_port_out = long_dir / 'port_out.json'
            self.assertGreater(len(str(long_port_out).encode('utf-8')), 3400)

            cli_p = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / 'compare_venue_novelty.py'),
                    str(p12_path),
                    '--portfolio',
                    '--sources-dir', str(src_dir),
                    '--out', str(long_port_out),
                    '--compact',
                ],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(cli_p.returncode, 0, cli_p.stdout + cli_p.stderr)
            self.assertLess(len(cli_p.stdout.encode('utf-8')), 4096)
            compact_p = json.loads(cli_p.stdout)
            self.assertEqual(compact_p['locator_verification']['skipped_files_count'], 60)

            # 2. Single-venue CLI with 60 skipped files + 3600B --out path preserves skipped_files_count
            s_prof = copy.deepcopy(self.fixture)
            s_prof['venue']['checked_at_utc'] = datetime.now(timezone.utc).isoformat()
            s_prof['target']['closest_work_locator'] = target['closest_work_locator']
            for idx, item in enumerate(s_prof['accepted_panel']):
                pid = item['closest_work_id']
                item['closest_work_locator'] = f'{pid}.txt:2: "Panel reference {idx + 1} reports bounded delta."'
            s_prof['fit_axes'][0]['locator'] = '"Main scope covers graph learning"'
            s_prof['fit_axes'][1]['locator'] = '"empirical mechanism studies"'
            s_prof['fit_axes'][2]['locator'] = '"multi-seed ablations"'
            s_prof['fit_axes'][3]['locator'] = '"8 pages plus references"'
            s_prof['fit_axes'][4]['locator'] = '"USD 750 early author registration"'
            s_path = tmp_dir / 'single.json'
            s_path.write_text(json.dumps(s_prof), encoding='utf-8')
            long_s_out = long_dir / 'single_out.json'
            cli_s = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / 'compare_venue_novelty.py'),
                    str(s_path),
                    '--sources-dir', str(src_dir),
                    '--out', str(long_s_out),
                    '--compact',
                ],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(cli_s.returncode, 0, cli_s.stdout + cli_s.stderr)
            self.assertLess(len(cli_s.stdout.encode('utf-8')), 4096)
            compact_s = json.loads(cli_s.stdout)
            self.assertEqual(compact_s['locator_verification']['skipped_files_count'], 60)

            # 3. 35-venue --portfolio full JSON -> report_latex_pdf.py --strict in EN & VI
            port_35 = {
                'target': {**self.fixture['target'], 'score': 6, 'low': 5, 'high': 7},
                'target_scorecard': {'weights': _weights(), 'ratings': _ratings((7, 6, 7, 6, 6, 6))},
                'candidate_venues': [_make_venue_candidate(self.fixture, f'v_{i:02d}', name=f'Conf{i}') for i in range(35)],
            }
            full_35 = compare_venue_novelty.check(port_35, self.as_of, portfolio=True)
            full_35_path = tmp_dir / 'port35.json'
            full_35_path.write_text(json.dumps(full_35), encoding='utf-8')
            for lang in ('en', 'vi'):
                pdf_out = tmp_dir / f'port35_{lang}.pdf'
                rep_cli = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPTS_DIR / 'report_latex_pdf.py'),
                        '--input', str(full_35_path),
                        '--out', str(pdf_out),
                        '--lang', lang,
                        '--strict',
                        '--json',
                        '--compact',
                    ],
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(rep_cli.returncode, 0, rep_cli.stdout + rep_cli.stderr)
                rec = json.loads(rep_cli.stdout)
                self.assertEqual(rec['status'], 'ok', rec)
                self.assertTrue(rec['diacritics_verified'], rec)


if __name__ == '__main__':
    unittest.main()
