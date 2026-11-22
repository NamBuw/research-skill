"""Opaque-box E2E tests for Milestone M9A: Scoring Engine v2 (F26, F28, F30#5-8, F31#2)."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

from helpers import REFS_DIR, REPO_ROOT, SCRIPTS_DIR, run_cli

MAX_COMPACT_BYTES = 4096
FABRICATED_ODDS_RE = re.compile(
    r'\b\d+(?:\.\d+)?%\s*(?:acceptance|chance|odds|probability)',
    re.IGNORECASE,
)


def _paper_ratings(vals):
    dims = ('importance', 'novelty', 'soundness', 'evidence', 'transparency', 'clarity')
    return dict(zip(dims, vals))


def _idea_ratings(vals):
    dims = ('evidence_coverage', 'novelty', 'importance', 'answerability', 'feasibility', 'falsifiability')
    return dict(zip(dims, vals))


def test_t1_m9a_cli_contracts_and_compact_budget(tmp_path: Path) -> None:
    """T1-M9A: --help, --venue-type, --subfield-preset, --what-if, --mode idea, --revision-diff & <4096B compact."""
    for script in ('score_math.py', 'compare_scorecards.py', 'compare_venue_novelty.py'):
        h = run_cli(SCRIPTS_DIR / script, ['--help'])
        assert h.returncode == 0, h.stderr

    # 1. score_math.py CLI with --venue-type, --subfield-preset, --what-if
    sm_in = {
        'ratings': _paper_ratings((7, 6, 4, 7, 7, 7)),
        'subfield_checks': {'contamination_audit': True, 'eval_harness_parity': True},
    }
    r_sm = run_cli(
        SCRIPTS_DIR / 'score_math.py',
        ['--venue-type', 'journal_q1', '--subfield-preset', 'nlp_llm', '--what-if'],
        stdin_text=json.dumps(sm_in),
    )
    assert r_sm.returncode == 0, r_sm.stderr
    assert r_sm.json_out['venue_type_profile']['venue_type'] == 'journal_q1'
    assert r_sm.json_out['subfield_readiness']['preset'] == 'nlp_llm'
    assert 'contamination_check' in r_sm.json_out['subfield_readiness']['passed_checks']
    assert r_sm.json_out['what_if_roi']['single_axis_upgrades'][0]['dimension'] == 'soundness'
    assert r_sm.json_out['what_if_roi']['single_axis_upgrades'][0]['clears_fatal_gate'] is True
    assert FABRICATED_ODDS_RE.search(r_sm.stdout) is None

    # 2. compare_scorecards.py 30-profile stress + --what-if + --subfield-preset + huge --out path < 4096B
    src_dir = tmp_path / 'sources'
    src_dir.mkdir()
    (src_dir / 'shared.txt').write_text('Full experimental ablation and 5-seed CI results verified.\n', encoding='utf-8')
    profiles = []
    for i in range(30):
        pid = f'paper_{i:02d}'
        profiles.append({
            'id': pid,
            'reading_basis': 'full_text',
            'closest_work': ['paper_01' if i != 1 else 'paper_00'],
            'ratings': _paper_ratings((7, 7 if i % 2 else 6, 7, 7, 6, 7)),
            'evidence_locators': {
                d: ['shared.txt#L1 "Full experimental ablation and 5-seed CI results verified"']
                for d in ('importance', 'novelty', 'soundness', 'evidence', 'transparency', 'clarity')
            },
        })
    sc_path = tmp_path / 'sc30.json'
    sc_path.write_text(
        json.dumps({'weight_scenarios': [dict(zip(('importance', 'novelty', 'soundness', 'evidence', 'transparency', 'clarity'), (15, 20, 20, 20, 15, 10)))], 'profiles': profiles}),
        encoding='utf-8',
    )
    long_out = tmp_path / ('nested_' * 30) / 'full_report.json'
    r_cs = run_cli(
        SCRIPTS_DIR / 'compare_scorecards.py',
        [
            str(sc_path),
            '--sources-dir', str(src_dir),
            '--target-id', 'paper_00',
            '--venue-type', 'conference_top_tier',
            '--subfield-preset', 'nlp_llm',
            '--what-if',
            '--out', str(long_out),
            '--compact',
        ],
    )
    assert r_cs.returncode == 0, r_cs.stderr
    assert len(r_cs.stdout.encode('utf-8')) < MAX_COMPACT_BYTES
    assert r_cs.json_out['compact'] is True
    assert long_out.is_file()
    full_cs = json.loads(long_out.read_text(encoding='utf-8'))
    assert [list(row.keys()) for row in full_cs['rankings'][0]['ordered']] == [['id', 'weighted_unrounded']] * 30

    # 3. compare_venue_novelty.py with --venue-type + --subfield-preset + --what-if + --compact < 4096B
    prof = json.loads((REFS_DIR / 'venue-novelty-profile.fixture.json').read_text(encoding='utf-8'))
    prof['target_scorecard'] = {
        'weights': dict(zip(('importance', 'novelty', 'soundness', 'evidence', 'transparency', 'clarity'), (15, 20, 20, 20, 15, 10))),
        'ratings': _paper_ratings((7, 6, 7, 6, 6, 6)),
    }
    vn_path = tmp_path / 'vn.json'
    vn_out = tmp_path / 'vn_out.json'
    vn_path.write_text(json.dumps(prof), encoding='utf-8')
    r_vn = run_cli(
        SCRIPTS_DIR / 'compare_venue_novelty.py',
        [
            str(vn_path),
            '--venue-type', 'conference_top_tier',
            '--subfield-preset', 'cv_multimodal',
            '--what-if',
            '--out', str(vn_out),
            '--compact',
        ],
    )
    assert r_vn.returncode == 0, r_vn.stderr
    assert len(r_vn.stdout.encode('utf-8')) < MAX_COMPACT_BYTES
    assert r_vn.json_out['subfield_preset'] == 'cv_multimodal'
    assert r_vn.json_out['native_venue_scales']['neurips_1_to_6']['score'] == 4


def test_t2_m9a_boundaries_and_invalid_inputs(tmp_path: Path) -> None:
    """T2-M9A: NaN/Infinity exit 2, empty args exit 2, assassin fatal block, dataset T1-T2 gate."""
    # NaN in score_math.py -> exit 2
    r_nan = run_cli(SCRIPTS_DIR / 'score_math.py', [], stdin_text='{"weights":{"importance":15,"novelty":20,"soundness":20,"evidence":20,"transparency":15,"clarity":10},"ratings":{"importance":NaN,"novelty":7,"soundness":7,"evidence":7,"transparency":7,"clarity":7}}')
    assert r_nan.returncode == 2

    # Missing positional arg without --revision-diff -> exit 2
    r_noarg = run_cli(SCRIPTS_DIR / 'compare_scorecards.py', [])
    assert r_noarg.returncode == 2

    # Empty path -> exit 2
    r_empty = run_cli(SCRIPTS_DIR / 'compare_scorecards.py', [''])
    assert r_empty.returncode == 2

    # Unknown --venue-profile -> exit 2
    r_bad_vt = run_cli(SCRIPTS_DIR / 'score_math.py', ['--venue-profile', 'nonexistent_tier'], stdin_text='{}')
    assert r_bad_vt.returncode == 2

    # dataset_benchmark T1-T2 failure blocks readiness
    ds_payload = {
        'venue_type': 'dataset_benchmark',
        'ratings': _paper_ratings((8, 8, 8, 8, 8, 8)),
        'dataset_checks': {'data_quality_audit': True, 'annotation_protocol': True, 'ethics_and_license_t1_t2': False},
    }
    r_ds = run_cli(SCRIPTS_DIR / 'score_math.py', [], stdin_text=json.dumps(ds_payload))
    assert r_ds.returncode == 0
    assert r_ds.json_out['submission_readiness']['fatal_gate_triggered'] is True
    assert r_ds.json_out['submission_readiness']['ready_for_top_tier_main_track'] is False

    # Confident assassin reviewer blocks AC accept
    rev_payload = {
        'weights': dict(zip(('importance', 'novelty', 'soundness', 'evidence', 'transparency', 'clarity'), (15, 20, 20, 20, 15, 10))),
        'ratings': _paper_ratings((8, 8, 7, 8, 7, 8)),
        'reviewer_panel': [
            {'reviewer_id': 'R1', 'role': 'method_theory', 'confidence': 4, 'ratings': _paper_ratings((8, 8, 4, 8, 7, 8))},
            {'reviewer_id': 'R2', 'role': 'experiments_baselines', 'confidence': 5, 'ratings': _paper_ratings((8, 8, 8, 8, 7, 8))},
            {'reviewer_id': 'R3', 'role': 'novelty_positioning', 'confidence': 3, 'ratings': _paper_ratings((8, 8, 8, 8, 7, 8))},
        ],
    }
    r_ac = run_cli(SCRIPTS_DIR / 'score_math.py', [], stdin_text=json.dumps(rev_payload))
    assert r_ac.returncode == 0
    assert r_ac.json_out['reviewer_panel_analysis']['meta_review_verdict'] == 'reject_fatal_defect'
    assert r_ac.json_out['reviewer_panel_analysis']['assassin_reviewer_flag'] is True


def test_t3_m9a_gap_seed_bundle_to_idea_ranking_revision_portfolio_pdf(tmp_path: Path) -> None:
    """T3-M9A: gap_pipeline seed bundle -> idea Pareto ranking -> revision diff -> venue novelty -> VI PDF."""
    corpus = {
        'Paper2024A': {
            'id': 'Paper2024A', 'source': 'openalex', 'family': 'same_problem', 'year': 2024,
            'published_date': '2024-05-01', 'title': 'Prior Calibration 2024',
            'abstract': 'ID logit scaling.', 'text': 'ID calibration baseline.', 'retraction_status': 'clean',
        },
        'Paper2025B': {
            'id': 'Paper2025B', 'source': 'arxiv', 'family': 'cross_setting_analogy', 'year': 2025,
            'published_date': '2025-02-01', 'title': 'Prior Shift 2025',
            'abstract': 'OOD drift observed.', 'text': 'OOD shift degrades ECE.', 'retraction_status': 'clean',
        },
    }
    digests = {
        'Paper2024A': {'source_id': 'Paper2024A', 'access': 'full_text', 'digest': 'ID only'},
        'Paper2025B': {'source_id': 'Paper2025B', 'access': 'full_text', 'digest': 'No long-context OOD'},
    }
    gap_rec = {
        'scope': 'Long-context OOD calibration in RAG',
        'search_date': '2026-04-01',
        'coverage_limits': 'arXiv and OpenAlex 2020-2026',
        'next_check': 'Run 1-day OOD depth slice pilot',
        'queries': [
            {'id': 'Q1', 'source': 'arxiv', 'query': 'OOD calibration drift', 'family': 'closure', 'status': 'complete', 'retrieved': 10, 'inspected': 10},
            {'id': 'Q2', 'source': 'openalex', 'query': 'long context logit shift', 'family': 'alternate_vocabulary', 'status': 'complete', 'retrieved': 8, 'inspected': 8},
        ],
        'evidence': [
            {'id': 'E1', 'source_id': 'Paper2024A', 'study_id': 'Paper2024A', 'locator': 'Paper2024A.json page 1: "In-domain calibration baseline verified."', 'claim': 'In-domain calibration baseline verified.', 'access': 'full_text', 'role': 'result'},
            {'id': 'E2', 'source_id': 'Paper2025B', 'study_id': 'Paper2025B', 'locator': 'Paper2025B.json page 1: "OOD shift degrades ECE verified."', 'claim': 'OOD shift degrades ECE verified.', 'access': 'full_text', 'role': 'limitation'},
        ],
        'closest_works': [
            {'id': 'Paper2024A', 'source_id': 'Paper2024A', 'relation': 'partial_precedent', 'access': 'full_text', 'difference': 'Only tested in-domain.', 'evidence_ids': ['E1']},
            {'id': 'Paper2025B', 'source_id': 'Paper2025B', 'relation': 'partial_precedent', 'access': 'full_text', 'difference': 'No depth-normalization mechanism.', 'evidence_ids': ['E2']},
        ],
        'candidates': [{
            'id': 'G1',
            'disposition': 'supported_candidate',
            'type': 'measurement_gap',
            'rationale': 'Prior works do not separate depth-induced logit drift from ID calibration.',
            'engineering_status': 'implementation_checked',
            'claim': 'Long-context OOD calibration collapses without retrieval-depth normalization.',
            'cited_ids': ['Paper2024A', 'Paper2025B'],
            'support_ids': ['Paper2024A', 'Paper2025B'],
            'support_evidence_ids': ['E1'],
            'counter_evidence_ids': ['E2'],
            'closest_work_ids': ['Paper2024A', 'Paper2025B'],
            'kill_query_ids': ['Q1'],
            'cutoff_year': 2026,
            'sgha_critics_passed': True,
            'engineering_checked': True,
            'consequence': 'Prevents silent OOD miscalibration in deployment.',
            'answer_path': 'Compare depth-normalized vs standard temperature scaling across OOD context lengths.',
            'root_cause_barrier': 'measurement_gap',
            'why_now_enabler': '2025 long-context benchmarks enable controlled depth slicing.',
            'so_what_decision_impact': 'decision_changing',
            'durability_12_24m': 'durable_structural_limit',
            'pre_mortem': {
                'top_failure_modes': ['Spurious length cue', 'Untuned baseline', 'Eval contamination'],
                'killer_experiment': {'duration_days': 1, 'kill_threshold': 'ECE gain < 0.01'},
                'pivot_path': 'Pivot to OOD calibration failure taxonomy.',
            },
            'idea_portfolio': [
                {'id': 'I1', 'angle': 'minimal_fix', 'title': 'Depth-scaled temperature calibration', 'summary': 'Single scalar depth temperature.'},
                {'id': 'I2', 'angle': 'high_novelty_mechanism', 'title': 'Causal attention gate', 'summary': 'Head-level causal routing.'},
                {'id': 'I3', 'angle': 'benchmark_diagnostic_analysis', 'title': 'Long-context OOD stress benchmark', 'summary': 'Systematic depth shift suite.'},
                {'id': 'I4', 'angle': 'low_gpu_fallback', 'title': 'CPU post-hoc logit normalizer', 'summary': 'Zero-training post-hoc norm.'},
            ],
        }],
    }
    src_dir = tmp_path / 'sources'
    src_dir.mkdir()
    (src_dir / 'sources.txt').write_text(
        'ID calibration baseline verified.\nOOD shift degrades ECE verified.\nNew 5-seed ablation CI [1.1, 2.4] verified.\n',
        encoding='utf-8',
    )
    (src_dir / 'Paper2024A.json').write_text(json.dumps({
        'format': 'research_scientist_pdf_blocks_v1',
        'source_id': 'Paper2024A',
        'pages': [[{
            'type': 'paragraph',
            'page_idx': 0,
            'text': 'In-domain calibration baseline verified.',
            'content': {'paragraph_content': [{'content': 'In-domain calibration baseline verified.'}]},
        }]],
    }), encoding='utf-8')
    (src_dir / 'Paper2025B.json').write_text(json.dumps({
        'format': 'research_scientist_pdf_blocks_v1',
        'source_id': 'Paper2025B',
        'pages': [[{
            'type': 'paragraph',
            'page_idx': 0,
            'text': 'OOD shift degrades ECE verified.',
            'content': {'paragraph_content': [{'content': 'OOD shift degrades ECE verified.'}]},
        }]],
    }), encoding='utf-8')
    corpus_p = tmp_path / 'corpus.json'
    digests_p = tmp_path / 'digests.json'
    cands_p = tmp_path / 'cands.json'
    gap_p = tmp_path / 'gap_record.json'
    bundle_p = tmp_path / 'seed_bundle.json'
    gp_out_p = tmp_path / 'gp_out.json'
    corpus_p.write_text(json.dumps({'papers': list(corpus.values())}), encoding='utf-8')
    digests_p.write_text(json.dumps(digests), encoding='utf-8')
    cands_p.write_text(json.dumps(gap_rec['candidates']), encoding='utf-8')
    gap_p.write_text(json.dumps(gap_rec), encoding='utf-8')

    r_gp = run_cli(
        SCRIPTS_DIR / 'gap_pipeline.py',
        [
            '--topic', 'ood calibration',
            '--corpus', str(corpus_p),
            '--digests', str(digests_p),
            '--candidates', str(cands_p),
            '--subfield-preset', 'nlp_llm',
            '--require-idea-portfolio',
            '--require-pre-mortem',
            '--seed-bundle-out', str(bundle_p),
            '--out', str(gp_out_p),
        ],
    )
    assert r_gp.returncode == 0, r_gp.stdout + r_gp.stderr
    assert bundle_p.is_file()

    # Unrated seed bundle fails closed
    r_unrated = run_cli(SCRIPTS_DIR / 'compare_scorecards.py', [str(bundle_p), '--mode', 'idea'])
    assert r_unrated.returncode == 1
    assert r_unrated.json_out['status'] == 'not_comparable'

    # Populate idea ratings & locators and run full linked Pareto ranking
    rated_bundle = json.loads(bundle_p.read_text(encoding='utf-8'))
    idea_scores = {
        'I1': (7, 6, 7, 9, 9, 8),
        'I2': (7, 9, 9, 6, 5, 8),
        'I3': (8, 7, 7, 8, 8, 7),
        'I4': (6, 5, 6, 9, 10, 7),
    }
    for idea in rated_bundle['seeds'][0]['idea_portfolio']:
        iid = idea['id']
        idea['ratings'] = _idea_ratings(idea_scores[iid])
        idea['evidence_locators'] = {
            d: ['sources.txt#L1 "ID calibration baseline"']
            for d in ('evidence_coverage', 'novelty', 'importance', 'answerability', 'feasibility', 'falsifiability')
        }
        idea['pre_mortem'] = copy.deepcopy(gap_rec['candidates'][0]['pre_mortem'])
    rated_bundle['seeds'][0]['prior_art_boundary']['cited_ids'] = ['Paper2024A', 'Paper2025B']
    rated_bundle['seeds'][0]['prior_art_boundary']['support_ids'] = ['Paper2024A']
    rated_p = tmp_path / 'rated_bundle.json'
    idea_rep_p = tmp_path / 'idea_report.json'
    rated_p.write_text(json.dumps(rated_bundle), encoding='utf-8')

    r_idea = run_cli(
        SCRIPTS_DIR / 'compare_scorecards.py',
        [
            str(rated_p),
            '--mode', 'idea',
            '--goal', 'safe_fast_publish',
            '--gap-record', str(gap_p),
            '--idea-seed-bundle', str(rated_p),
            '--require-idea-portfolio',
            '--require-pre-mortem',
            '--sources-dir', str(src_dir),
            '--out', str(idea_rep_p),
            '--compact',
        ],
    )
    assert r_idea.returncode == 0, r_idea.stdout + r_idea.stderr
    assert len(r_idea.stdout.encode('utf-8')) < MAX_COMPACT_BYTES
    assert r_idea.json_out['pareto_frontier']['goal'] == 'safe_fast_publish'
    assert r_idea.json_out['submission_readiness']['I1']['ready_for_top_tier_main_track'] is False

    # Revision diff verified by new locator + SHA-256 receipt
    receipt_p = src_dir / 'exp_run.json'
    receipt_p.write_text('{"ece": 0.021}\n', encoding='utf-8')
    sha_hex = hashlib.sha256(receipt_p.read_bytes()).hexdigest()
    w = dict(zip(('importance', 'novelty', 'soundness', 'evidence', 'transparency', 'clarity'), (15, 20, 20, 20, 15, 10)))
    v1 = {
        'id': 'paper_v',
        'weights': w,
        'ratings': _paper_ratings((7, 6, 4, 6, 6, 6)),
        'evidence_locators': {d: ['sources.txt#L1 "ID calibration baseline"'] for d in w},
        'defects': ['missing_proof'],
    }
    v2 = copy.deepcopy(v1)
    v2['ratings'] = _paper_ratings((7, 6, 7, 8, 6, 6))
    v2['evidence_locators']['soundness'].append('sources.txt#L3 "New 5-seed ablation CI"')
    v2['run_receipts'] = [{'sha256': sha_hex, 'path': 'exp_run.json', 'dimensions': ['evidence']}]
    v2['defects'] = []
    v1_p = tmp_path / 'v1.json'
    v2_p = tmp_path / 'v2.json'
    diff_p = tmp_path / 'diff.json'
    v1_p.write_text(json.dumps(v1), encoding='utf-8')
    v2_p.write_text(json.dumps(v2), encoding='utf-8')
    r_diff = run_cli(
        SCRIPTS_DIR / 'compare_scorecards.py',
        ['--revision-diff', str(v1_p), str(v2_p), '--sources-dir', str(src_dir), '--out', str(diff_p), '--compact'],
    )
    assert r_diff.returncode == 0, r_diff.stderr
    assert len(r_diff.stdout.encode('utf-8')) < MAX_COMPACT_BYTES
    assert r_diff.json_out['suspected_grade_inflation'] is False
    assert r_diff.json_out['resolved_fatal_dimensions'] == ['soundness']

    # Compile Vietnamese LaTeX PDF from scoring report cleanly
    pdf_in = {
        'title': 'Báo cáo đánh giá điểm và ý tưởng',
        'verdict': 'Chưa sẵn sàng nộp hội nghị Q1; cần bổ sung chứng cứ và kiểm chứng.',
        'key_findings': [
            f"Ý tưởng ưu tiên theo mục tiêu nhanh: {r_idea.json_out['pareto_frontier']['goal_ranked_ids'][0]}.",
            f"Chênh lệch điểm sau chỉnh sửa: +{r_diff.json_out['weighted_delta']}.",
        ],
        'next_actions': ['Chạy thí nghiệm kiểm chứng trong 1-2 ngày và cập nhật bằng chứng.'],
    }
    pdf_in_p = tmp_path / 'report_in.json'
    pdf_out_p = tmp_path / 'report_vi.pdf'
    pdf_in_p.write_text(json.dumps(pdf_in, ensure_ascii=False), encoding='utf-8')
    r_pdf = run_cli(
        SCRIPTS_DIR / 'report_latex_pdf.py',
        ['--input', str(pdf_in_p), '--out', str(pdf_out_p), '--lang', 'vi', '--strict', '--json'],
        timeout=60,
    )
    assert r_pdf.returncode == 0, r_pdf.stderr + r_pdf.stdout
    assert pdf_out_p.is_file() and pdf_out_p.stat().st_size > 1000
    assert r_pdf.json_out['diacritics_verified'] is True


def test_t5_m9a_adversarial_inflation_halo_and_claim_audit(tmp_path: Path) -> None:
    """T5-M9A: Adversarial spoofed revision diff, halo warnings, zero % odds, and claim_audit = 0."""
    w = dict(zip(('importance', 'novelty', 'soundness', 'evidence', 'transparency', 'clarity'), (15, 20, 20, 20, 15, 10)))
    v1 = {
        'id': 'paper_adv',
        'weights': w,
        'ratings': _paper_ratings((7, 6, 5, 6, 6, 6)),
        'evidence_locators': {d: ['src.txt#L1 "Verified line"'] for d in w},
    }
    v2_spoof = copy.deepcopy(v1)
    v2_spoof['ratings'] = _paper_ratings((7, 8, 8, 8, 4, 8))
    v1_p = tmp_path / 'v1.json'
    v2_p = tmp_path / 'v2.json'
    v1_p.write_text(json.dumps(v1), encoding='utf-8')
    v2_p.write_text(json.dumps(v2_spoof), encoding='utf-8')
    r_spoof = run_cli(SCRIPTS_DIR / 'compare_scorecards.py', ['--revision-diff', str(v1_p), str(v2_p), '--compact'])
    assert r_spoof.returncode == 1
    assert r_spoof.json_out['suspected_grade_inflation'] is True
    assert r_spoof.json_out['status'] == 'grade_inflation_suspected'

    # Halo warnings surfaced on CLI
    halo_in = {
        'weights': w,
        'ratings': _paper_ratings((7, 9, 8, 9, 4, 8)),
        'closest_work': ['Prior1'],
        'reading_basis': 'abstract',
    }
    r_halo = run_cli(SCRIPTS_DIR / 'score_math.py', [], stdin_text=json.dumps(halo_in))
    assert r_halo.returncode == 0
    assert len(r_halo.json_out['sanity_warnings']) == 3
    assert FABRICATED_ODDS_RE.search(r_halo.stdout) is None

    # Suite-wide claim_audit = 0 findings and SKILL.md budgets <50L / <900tok
    r_ca = run_cli(
        SCRIPTS_DIR / 'claim_audit.py',
        ['--suite-root', str(REPO_ROOT), '--readme', str(REPO_ROOT / 'README.md'), '--json'],
    )
    assert r_ca.returncode == 0, r_ca.stdout + r_ca.stderr
    assert r_ca.json_out['finding_count'] == 0
    for sk in r_ca.json_out['skills_audited']:
        assert sk['footprint']['lines'] < 50
        assert sk['footprint']['est_tokens'] < 900


def test_t5_m9a_remediation_cli_regressions(tmp_path: Path) -> None:
    """T5-M9A regressions: portfolio gating, dataset T1-T2, reviewer_panel exit 2, receipt traversal, idea revision-diff."""
    prof = json.loads((REFS_DIR / 'venue-novelty-profile.fixture.json').read_text(encoding='utf-8'))
    w = dict(zip(('importance', 'novelty', 'soundness', 'evidence', 'transparency', 'clarity'), (15, 20, 20, 20, 15, 10)))

    # 1. Invalid reviewer_panel (< 3 reviewers) -> CLI exit 2
    bad_panel = copy.deepcopy(prof)
    bad_panel['target_scorecard'] = {'weights': w, 'ratings': _paper_ratings((8, 8, 7, 8, 7, 8))}
    bad_panel['reviewer_panel'] = [{'reviewer_id': 'R1', 'role': 'theory', 'confidence': 4, 'ratings': _paper_ratings((8, 8, 7, 8, 7, 8))}]
    bad_panel_p = tmp_path / 'bad_panel.json'
    bad_panel_p.write_text(json.dumps(bad_panel), encoding='utf-8')
    r_bad_panel = run_cli(SCRIPTS_DIR / 'compare_venue_novelty.py', [str(bad_panel_p)])
    assert r_bad_panel.returncode == 2

    # 2. Confident fatal reviewer blocks ready_to_submit & surfaces reviewer_panel_summary in --compact < 4096B
    fatal_panel = copy.deepcopy(prof)
    fatal_panel['target_scorecard'] = {'weights': w, 'ratings': _paper_ratings((8, 8, 7, 8, 7, 8))}
    fatal_panel['reviewer_panel'] = [
        {'reviewer_id': 'R1', 'role': 'theory', 'confidence': 5, 'ratings': _paper_ratings((8, 8, 3, 8, 7, 8))},
        {'reviewer_id': 'R2', 'role': 'exp', 'confidence': 4, 'ratings': _paper_ratings((8, 8, 8, 8, 7, 8))},
        {'reviewer_id': 'R3', 'role': 'nov', 'confidence': 3, 'ratings': _paper_ratings((8, 8, 8, 8, 7, 8))},
    ]
    fp_p = tmp_path / 'fatal_panel.json'
    fp_out = tmp_path / 'fatal_panel_out.json'
    fp_p.write_text(json.dumps(fatal_panel), encoding='utf-8')
    r_fp = run_cli(SCRIPTS_DIR / 'compare_venue_novelty.py', [str(fp_p), '--out', str(fp_out), '--compact'])
    assert r_fp.returncode == 0, r_fp.stderr
    assert len(r_fp.stdout.encode('utf-8')) < MAX_COMPACT_BYTES
    assert r_fp.json_out['submission_readiness']['ready_to_submit'] is False
    assert r_fp.json_out['submission_readiness']['verdict'] == 'not_ready_fatal_gate'
    assert r_fp.json_out['reviewer_panel_summary']['meta_review_verdict'] == 'reject_fatal_defect'

    # 3. Portfolio CLI: dataset_benchmark missing T1-T2 -> blocked_hold_for_rework & unlisted conference_top_tier -> rejected_below_venue_tier
    port = {
        'target': dict(prof['target'], score=5, low=4, high=6),
        'target_scorecard': {'weights': w, 'ratings': _paper_ratings((6, 5, 5, 6, 5, 6))},
        'candidate_venues': [
            {
                'venue_id': 'ds_missing',
                'role': 'primary',
                'venue_type': 'dataset_benchmark',
                'venue': dict(prof['venue'], name='NeurIPS', track='Datasets and Benchmarks'),
                'fit_axes': prof['fit_axes'],
                'hard_constraints': prof['hard_constraints'],
            },
            {
                'venue_id': 'unlisted_conf',
                'role': 'fallback',
                'venue_type': 'conference_top_tier',
                'venue': dict(prof['venue'], name='SomeUnlistedTopConf', track='Main'),
                'fit_axes': prof['fit_axes'],
                'hard_constraints': prof['hard_constraints'],
            },
            {
                'venue_id': 'icml_main',
                'role': 'fallback',
                'venue_type': 'conference_top_tier',
                'venue': dict(prof['venue'], name='ICML', track='Main'),
                'fit_axes': prof['fit_axes'],
                'hard_constraints': prof['hard_constraints'],
            },
        ],
    }
    port_p = tmp_path / 'port.json'
    port_out = tmp_path / 'port_out.json'
    port_p.write_text(json.dumps(port), encoding='utf-8')
    r_port = run_cli(SCRIPTS_DIR / 'compare_venue_novelty.py', [str(port_p), '--portfolio', '--out', str(port_out), '--compact'])
    assert r_port.returncode == 0, r_port.stderr
    assert len(r_port.stdout.encode('utf-8')) < MAX_COMPACT_BYTES
    rec = r_port.json_out['venue_portfolio_recommendations']
    assert 'ds_missing' in rec['blocked_hold_for_rework']
    assert 'ds_missing' not in rec['recommended_now']
    assert 'unlisted_conf' in rec['rejected_below_venue_tier']
    assert 'unlisted_conf' not in rec['stretch_high_risk']

    # 4. compare_scorecards --revision-diff CLI exit 1 on experiment_receipts traversal & exit 0 on idea+venue_type
    src = tmp_path / 'rev_src'
    src.mkdir()
    (src / 'n.txt').write_text('Old line.\nNew verified line.\n', encoding='utf-8')
    v1_idea = {
        'id': 'idea1', 'mode': 'idea', 'venue_type': 'conference_top_tier',
        'ratings': _idea_ratings((7, 7, 7, 6, 6, 6)),
        'evidence_locators': {d: ['n.txt#L1 "Old line"'] for d in ('evidence_coverage', 'novelty', 'importance', 'answerability', 'feasibility', 'falsifiability')},
    }
    v2_trav = copy.deepcopy(v1_idea)
    v2_trav['ratings']['feasibility'] = 8
    v2_trav['experiment_receipts'] = [{'sha256': 'a' * 64, 'path': '../../etc/passwd', 'dimensions': ['feasibility']}]
    v1_ip = tmp_path / 'v1_i.json'
    v2_tp = tmp_path / 'v2_t.json'
    v1_ip.write_text(json.dumps(v1_idea), encoding='utf-8')
    v2_tp.write_text(json.dumps(v2_trav), encoding='utf-8')
    r_trav = run_cli(SCRIPTS_DIR / 'compare_scorecards.py', ['--revision-diff', str(v1_ip), str(v2_tp)])
    assert r_trav.returncode == 1
    assert r_trav.json_out['status'] == 'grade_inflation_suspected'

    v2_ok = copy.deepcopy(v1_idea)
    v2_ok['ratings']['feasibility'] = 8
    v2_ok['evidence_locators']['feasibility'].append('n.txt#L2 "New verified line"')
    v2_okp = tmp_path / 'v2_ok.json'
    v2_okp.write_text(json.dumps(v2_ok), encoding='utf-8')
    r_idea_diff = run_cli(SCRIPTS_DIR / 'compare_scorecards.py', ['--revision-diff', str(v1_ip), str(v2_okp), '--sources-dir', str(src)])
    assert r_idea_diff.returncode == 0, r_idea_diff.stderr
    assert r_idea_diff.json_out['status'] == 'verified_revision'

    # 5. Unrated idea_portfolio seed bundle with ratings: null / omitted / id: None -> CLI exit 1 (not exit 2)
    unrated_bundle = {
        'schema': 'research_scientist_idea_seed_bundle_v1',
        'seeds': [{
            'gap_id': 'G1',
            'closest_work_ids': ['P1'],
            'idea_portfolio': [
                {'id': 'I1', 'angle': 'minimal_fix', 'ratings': None},
                {'id': None, 'idea_id': 'I2', 'angle': 'high_novelty_mechanism'},
            ],
        }],
    }
    ub_p = tmp_path / 'unrated_b.json'
    ub_p.write_text(json.dumps(unrated_bundle), encoding='utf-8')
    r_ub = run_cli(SCRIPTS_DIR / 'compare_scorecards.py', [str(ub_p), '--mode', 'idea'])
    assert r_ub.returncode == 1, r_ub.stderr
    assert r_ub.json_out['status'] == 'not_comparable'
