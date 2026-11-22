"""Opaque-box E2E tests for Feature F23: Submission Readiness & Venue Standing."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import fitz

from helpers import (
    MockScholarlyServer,
    REFS_DIR,
    REPO_ROOT,
    SCRIPTS_DIR,
    T123_FIXTURES_DIR,
    iso_utc,
    run_cli,
)

MAX_COMPACT_BYTES = 4096


def test_t1_f23_score_math_and_compare_scorecards_readiness(tmp_path: Path) -> None:
    """T1-F23: score_math.py (6.35 & soundness=4 fatal override) + compare_scorecards.py --compact."""
    weights = {
        'importance': 15,
        'novelty': 20,
        'soundness': 20,
        'evidence': 20,
        'transparency': 15,
        'clarity': 10,
    }
    p635 = {
        'weights': weights,
        'ratings': {
            'importance': 7,
            'novelty': 6,
            'soundness': 7,
            'evidence': 6,
            'transparency': 6,
            'clarity': 6,
        },
    }
    r1 = run_cli(SCRIPTS_DIR / 'score_math.py', [], stdin_text=json.dumps(p635))
    assert r1.returncode == 0, r1.stderr
    assert r1.json_out['weighted_unrounded'] == '6.35'
    sr1 = r1.json_out['submission_readiness']
    assert sr1['band'] == 'borderline_top_tier_competitive_findings_tier_a'
    assert sr1['delta_to_competitive_top_tier'] == -0.45
    assert sr1['ready_for_findings_or_tier_a'] is True
    assert sr1['ready_for_top_tier_main_track'] is False

    pfatal = {
        'weights': weights,
        'ratings': {
            'importance': 9,
            'novelty': 8,
            'soundness': 4,
            'evidence': 8,
            'transparency': 8,
            'clarity': 8,
        },
    }
    r2 = run_cli(SCRIPTS_DIR / 'score_math.py', [], stdin_text=json.dumps(pfatal))
    assert r2.returncode == 0, r2.stderr
    assert r2.json_out['weighted_unrounded'] == '7.35'
    sr2 = r2.json_out['submission_readiness']
    assert sr2['band'] == 'not_ready_fatal_gate'
    assert sr2['fatal_gate_triggered'] is True
    assert 'soundness' in sr2['fatal_dimensions']
    assert sr2['ready_for_top_tier_main_track'] is False
    assert sr2['ready_for_findings_or_tier_a'] is False

    src_dir = tmp_path / 'sources'
    src_dir.mkdir()
    for pid in ('paper_635', 'paper_fatal'):
        (src_dir / f'{pid}.txt').write_text(f'Verified text for {pid} benchmark.\n', encoding='utf-8')
    sc_doc = {
        'weight_scenarios': [weights],
        'profiles': [
            {
                'id': 'paper_635',
                'reading_basis': 'full_text',
                'closest_work': ['Prior2024'],
                'ratings': p635['ratings'],
                'evidence_locators': {k: ['paper_635.txt#L1 "Verified text"'] for k in weights},
            },
            {
                'id': 'paper_fatal',
                'reading_basis': 'full_text',
                'closest_work': ['Prior2024'],
                'ratings': pfatal['ratings'],
                'evidence_locators': {k: ['paper_fatal.txt#L1 "Verified text"'] for k in weights},
            },
        ],
    }
    sc_path = tmp_path / 'scorecards.json'
    out_path = tmp_path / 'sc_full.json'
    sc_path.write_text(json.dumps(sc_doc), encoding='utf-8')
    comp_res = run_cli(
        SCRIPTS_DIR / 'compare_scorecards.py',
        [str(sc_path), '--sources-dir', str(src_dir), '--out', str(out_path), '--compact'],
    )
    assert comp_res.returncode == 0, comp_res.stderr
    assert len(comp_res.stdout.encode('utf-8')) < MAX_COMPACT_BYTES
    assert comp_res.json_out['submission_readiness']['paper_635']['band'] == 'borderline_top_tier_competitive_findings_tier_a'
    assert comp_res.json_out['submission_readiness']['paper_fatal']['band'] == 'not_ready_fatal_gate'
    full_sc = json.loads(out_path.read_text(encoding='utf-8'))
    assert [list(x.keys()) for x in full_sc['rankings'][0]['ordered']] == [['id', 'weighted_unrounded']] * 2


def test_t2_f23_boundaries_venue_blockers_and_tier_invariance(tmp_path: Path) -> None:
    """T2-F23: Exact /10 band boundaries, idea stage, venue blockers, and Unknown vs NeurIPS invariance."""
    boundary_cases = [
        ((1, 1, 50, 40, 7, 1), (4, 4, 5, 5, 5, 6), 'not_ready_major_rework'),
        ((15, 20, 20, 20, 15, 10), (5, 5, 5, 5, 5, 5), 'workshop_or_preliminary_only'),
        ((1, 1, 50, 40, 7, 1), (5, 5, 6, 6, 6, 7), 'workshop_or_preliminary_only'),
        ((15, 20, 20, 20, 15, 10), (6, 6, 6, 6, 6, 6), 'borderline_top_tier_competitive_findings_tier_a'),
        ((1, 1, 50, 27, 20, 1), (6, 6, 7, 7, 6, 8), 'borderline_top_tier_competitive_findings_tier_a'),
        ((15, 20, 20, 20, 15, 10), (8, 7, 7, 7, 6, 5), 'competitive_top_tier_main_track'),
        ((1, 1, 50, 27, 20, 1), (7, 7, 8, 8, 7, 9), 'competitive_top_tier_main_track'),
        ((15, 20, 20, 20, 15, 10), (9, 8, 8, 8, 7, 6), 'strong_top_tier_contender'),
    ]
    dims = ('importance', 'novelty', 'soundness', 'evidence', 'transparency', 'clarity')
    for w, r, expected_band in boundary_cases:
        res = run_cli(
            SCRIPTS_DIR / 'score_math.py',
            [],
            stdin_text=json.dumps({'weights': dict(zip(dims, w)), 'ratings': dict(zip(dims, r))}),
        )
        assert res.returncode == 0
        assert res.json_out['submission_readiness']['band'] == expected_band

    idea_res = run_cli(
        SCRIPTS_DIR / 'score_math.py',
        [],
        stdin_text=json.dumps({
            'status': 'idea',
            'weights': dict(zip(dims, (15, 20, 20, 20, 15, 10))),
            'ratings': dict(zip(dims, (8, 8, 8, 8, 8, 8))),
        }),
    )
    assert idea_res.returncode == 0
    assert idea_res.json_out['submission_readiness']['band'] == 'not_ready_fatal_gate'
    assert idea_res.json_out['submission_readiness']['ready_for_top_tier_main_track'] is False

    base_prof = json.loads((REFS_DIR / 'venue-novelty-profile.fixture.json').read_text(encoding='utf-8'))
    base_prof['venue']['checked_at_utc'] = iso_utc(0)

    # Hard constraint failed -> do_not_submit_constraint_failed
    deadline_fail = copy.deepcopy(base_prof)
    deadline_fail['hard_constraints'][0]['status'] = 'failed'
    df_path = tmp_path / 'deadline_fail.json'
    df_path.write_text(json.dumps(deadline_fail), encoding='utf-8')
    df_res = run_cli(SCRIPTS_DIR / 'compare_venue_novelty.py', [str(df_path), '--compact'])
    assert df_res.returncode == 0
    assert df_res.json_out['submission_readiness']['verdict'] == 'do_not_submit_constraint_failed'
    assert df_res.json_out['submission_readiness']['ready_to_submit'] is False

    # Unknown vs NeurIPS invariance on novelty_comparison + fit_score_out_of_10 + submission_readiness
    unk_path = tmp_path / 'unknown.json'
    neu_prof = copy.deepcopy(base_prof)
    neu_prof['venue']['name'] = 'NeurIPS'
    neu_path = tmp_path / 'neurips.json'
    unk_path.write_text(json.dumps(base_prof), encoding='utf-8')
    neu_path.write_text(json.dumps(neu_prof), encoding='utf-8')
    r_unk = run_cli(SCRIPTS_DIR / 'compare_venue_novelty.py', [str(unk_path)])
    r_neu = run_cli(SCRIPTS_DIR / 'compare_venue_novelty.py', [str(neu_path)])
    assert r_unk.returncode == 0 and r_neu.returncode == 0
    assert r_unk.json_out['venue_quality_context']['quality_tier'] == 'Unknown'
    assert r_neu.json_out['venue_quality_context']['quality_tier'] == 'S'
    assert r_unk.json_out['novelty_comparison'] == r_neu.json_out['novelty_comparison']
    assert r_unk.json_out['fit_score_out_of_10'] == r_neu.json_out['fit_score_out_of_10']
    assert r_unk.json_out['submission_readiness'] == r_neu.json_out['submission_readiness']


def test_t3_f23_panel_scorecards_venue_novelty_to_multilingual_pdf(
    mock_server: MockScholarlyServer, tmp_path: Path
) -> None:
    """T3-F23: Offline panel collection -> compare_scorecards -> compare_venue_novelty -> EN & VI --strict PDFs."""
    payloads = json.loads((T123_FIXTURES_DIR / 'mock_scholarly_payloads.json').read_text(encoding='utf-8'))
    mock_server.add_route('/v235/', (200, 'text/html', payloads['pmlr_v235_html']), host='proceedings.mlr.press')
    mock_server.add_route('/v235', (200, 'text/html', payloads['pmlr_v235_html']), host='proceedings.mlr.press')

    panel_path = tmp_path / 'panel.json'
    p_res = run_cli(
        SCRIPTS_DIR / 'venue_panel_collector.py',
        ['--source', 'pmlr', '--venue-id', 'v235', '--limit', '5', '--out', str(panel_path), '--compact'],
        env=mock_server.env(),
    )
    assert p_res.returncode == 0, p_res.stderr
    assert len(p_res.stdout.encode('utf-8')) < MAX_COMPACT_BYTES
    collected = json.loads(panel_path.read_text(encoding='utf-8'))['accepted_panel']

    # Run compare_scorecards with local sources
    src_dir = tmp_path / 'sources'
    src_dir.mkdir()
    for pid in ('target_635', 'baseline_strong'):
        (src_dir / f'{pid}.txt').write_text(f'Verified full text for {pid} benchmark.\n', encoding='utf-8')
    weights = {'importance': 15, 'novelty': 20, 'soundness': 20, 'evidence': 20, 'transparency': 15, 'clarity': 10}
    sc_doc = {
        'weight_scenarios': [weights],
        'profiles': [
            {
                'id': 'target_635',
                'reading_basis': 'full_text',
                'closest_work': ['Prior2024'],
                'ratings': {'importance': 7, 'novelty': 6, 'soundness': 7, 'evidence': 6, 'transparency': 6, 'clarity': 6},
                'evidence_locators': {k: ['target_635.txt#L1 "Verified full text"'] for k in weights},
            },
            {
                'id': 'baseline_strong',
                'reading_basis': 'full_text',
                'closest_work': ['Prior2024'],
                'ratings': {'importance': 8, 'novelty': 7, 'soundness': 7, 'evidence': 7, 'transparency': 7, 'clarity': 7},
                'evidence_locators': {k: ['baseline_strong.txt#L1 "Verified full text"'] for k in weights},
            },
        ],
    }
    sc_in = tmp_path / 'scorecards.json'
    sc_out = tmp_path / 'sc_out.json'
    sc_in.write_text(json.dumps(sc_doc), encoding='utf-8')
    sc_res = run_cli(
        SCRIPTS_DIR / 'compare_scorecards.py',
        [str(sc_in), '--sources-dir', str(src_dir), '--out', str(sc_out), '--compact'],
    )
    assert sc_res.returncode == 0, sc_res.stderr
    assert len(sc_res.stdout.encode('utf-8')) < MAX_COMPACT_BYTES
    sc_sr = sc_res.json_out['submission_readiness']['target_635']
    assert sc_sr['band'] == 'borderline_top_tier_competitive_findings_tier_a'

    # Run compare_venue_novelty using collected panel URLs
    prof = json.loads((REFS_DIR / 'venue-novelty-profile.fixture.json').read_text(encoding='utf-8'))
    prof['venue']['checked_at_utc'] = iso_utc(0)
    for idx, row in enumerate(prof['accepted_panel']):
        if idx < len(collected):
            row['official_acceptance_url'] = collected[idx]['official_acceptance_url']
    vn_in = tmp_path / 'vn_prof.json'
    vn_out = tmp_path / 'vn_out.json'
    vn_in.write_text(json.dumps(prof), encoding='utf-8')
    vn_res = run_cli(
        SCRIPTS_DIR / 'compare_venue_novelty.py',
        [str(vn_in), '--out', str(vn_out), '--compact'],
    )
    assert vn_res.returncode == 0, vn_res.stderr
    assert len(vn_res.stdout.encode('utf-8')) < MAX_COMPACT_BYTES
    vn_sr = vn_res.json_out['submission_readiness']

    # Export EN and VI strict PDFs reflecting readiness guidance
    for lang, title, summary, action in [
        (
            'en',
            'Submission Readiness Assessment',
            f"Weighted score 6.35/10 sits below top-tier accepted median (~6.8-7.6) [sc_out.json]. Standing is {vn_sr['standing_vs_accepted_panel']}; competitive for Findings or Tier-A now.",
            'Strengthen soundness and evidence before NeurIPS submission.',
        ),
        (
            'vi',
            'Báo cáo khả năng nộp bài và vị thế hội nghị',
            'Điểm 6.35/10 vượt mức trung bình toàn bộ bài nộp (~4.8-5.5) nhưng thấp hơn mức bài được nhận top-tier (~6.8-7.6) [sc_out.json]. Phù hợp nộp Findings hoặc hội nghị Tier-A hiện tại.',
            'Bổ sung thí nghiệm đối chứng trước khi nộp hội nghị top-tier.',
        ),
    ]:
        rep_in = tmp_path / f'report_{lang}.json'
        pdf_out = tmp_path / f'report_{lang}.pdf'
        rep_doc = {
            'schema': 'research_scientist_executive_report_v1',
            'report_type': 'novelty_scoring',
            'lang': lang,
            'title': title,
            'verdict': {'status': 'provisional', 'summary': summary, 'evidence_refs': ['SC1', 'VN1']},
            'key_evidence': [
                {'id': 'SC1', 'claim': 'Weighted scorecard', 'value': '6.35/10', 'status': 'verified', 'locator': 'sc_out.json'},
                {'id': 'VN1', 'claim': 'Venue standing', 'value': f"{vn_sr['standing_vs_accepted_panel']} (fit {vn_sr['fit_score_out_of_10']}/10)", 'status': 'verified', 'locator': 'vn_out.json'},
            ],
            'flaws_and_risks': [
                {'id': 'R1', 'severity': 'medium', 'summary': 'Gap of -0.45 to 6.80 main-track threshold [sc_out.json].', 'locator': 'sc_out.json'},
            ],
            'next_steps': [{'step': 1, 'action': action, 'target': 'sc_out.json'}],
        }
        rep_in.write_text(json.dumps(rep_doc, ensure_ascii=False), encoding='utf-8')
        rep_res = run_cli(
            SCRIPTS_DIR / 'report_latex_pdf.py',
            ['--input', str(rep_in), '--out', str(pdf_out), '--lang', lang, '--strict', '--json', '--compact'],
        )
        assert rep_res.returncode == 0, f'{lang}: {rep_res.stdout}\n{rep_res.stderr}'
        assert len(rep_res.stdout.encode('utf-8')) < MAX_COMPACT_BYTES
        assert rep_res.json_out['status'] == 'ok'
        assert rep_res.json_out['diacritics_verified'] is True
        with fitz.open(pdf_out) as doc:
            text = '\n'.join(page.get_text() for page in doc)
        assert '6.35/10' in text
        if lang == 'vi':
            assert 'Khả năng' in text or 'Phù hợp nộp Findings' in text


def test_t5_f23_adversarial_fatal_gates_nan_and_prompt_budgets(tmp_path: Path) -> None:
    """T5-F23: Adversarial fatal gates never mark ready; NaN exits 2; NeurIPS never boosts weak score; SKILL.md <50L/<900tok & claim_audit=0."""
    dims = ('importance', 'novelty', 'soundness', 'evidence', 'transparency', 'clarity')
    weights = dict(zip(dims, (15, 20, 20, 20, 15, 10)))

    # High weighted mean (>=7.15) with fatal defect must block both main track & Findings/Tier-A
    for ratings, extra in [
        ((10, 10, 4, 10, 10, 10), {}),
        ((10, 10, 10, 4, 10, 10), {}),
        ((10, 2, 10, 10, 10, 10), {}),
        ((10, 10, 10, 10, 3, 10), {}),
        ((9, 9, 9, 9, 9, 9), {'status': 'idea'}),
    ]:
        res = run_cli(
            SCRIPTS_DIR / 'score_math.py',
            [],
            stdin_text=json.dumps({'weights': weights, 'ratings': dict(zip(dims, ratings)), **extra}),
        )
        assert res.returncode == 0
        sr = res.json_out['submission_readiness']
        assert sr['band'] == 'not_ready_fatal_gate'
        assert sr['fatal_gate_triggered'] is True
        assert sr['ready_for_top_tier_main_track'] is False
        assert sr['ready_for_findings_or_tier_a'] is False

    # NaN rejected with exit 2 across all 3 scripts
    nan_sc = tmp_path / 'nan_sc.json'
    nan_sc.write_text('{"weight_scenarios":[],"profiles":[{"id":"a","ratings":{"importance":NaN}}]}', encoding='utf-8')
    assert run_cli(SCRIPTS_DIR / 'compare_scorecards.py', [str(nan_sc)]).returncode == 2
    nan_vn = tmp_path / 'nan_vn.json'
    nan_vn.write_text('{"target":{"score":NaN}}', encoding='utf-8')
    assert run_cli(SCRIPTS_DIR / 'compare_venue_novelty.py', [str(nan_vn)]).returncode == 2

    # Weak score at S-tier NeurIPS must not inflate readiness or alter novelty_comparison
    prof = json.loads((REFS_DIR / 'venue-novelty-profile.fixture.json').read_text(encoding='utf-8'))
    prof['venue']['checked_at_utc'] = iso_utc(0)
    prof['venue']['name'] = 'NeurIPS'
    prof['target']['score'] = 3
    prof['target']['low'] = 2
    prof['target']['high'] = 4
    weak_path = tmp_path / 'weak_neurips.json'
    weak_path.write_text(json.dumps(prof), encoding='utf-8')
    w_res = run_cli(SCRIPTS_DIR / 'compare_venue_novelty.py', [str(weak_path)])
    assert w_res.returncode == 0
    assert w_res.json_out['venue_quality_context']['quality_tier'] == 'S'
    assert w_res.json_out['submission_readiness']['standing_vs_accepted_panel'] == 'below_panel_median'
    assert w_res.json_out['submission_readiness']['ready_to_submit'] is False

    # Piping fatal-gate compare_venue_novelty output directly to report_latex_pdf.py --strict must never emit PASS/SUPPORTED
    fatal_vn_pdf = tmp_path / 'fatal_vn_direct.pdf'
    weak_vn_out = tmp_path / 'weak_vn_out.json'
    weak_vn_out.write_text(w_res.stdout, encoding='utf-8')
    fatal_vn_rep = run_cli(
        SCRIPTS_DIR / 'report_latex_pdf.py',
        ['--input', str(weak_vn_out), '--out', str(fatal_vn_pdf), '--strict', '--json', '--compact'],
    )
    assert fatal_vn_rep.returncode == 0, fatal_vn_rep.stdout + fatal_vn_rep.stderr
    with fitz.open(fatal_vn_pdf) as doc:
        vn_pdf_txt = '\n'.join(p.get_text() for p in doc)
    assert 'BLOCKED' in vn_pdf_txt or 'NOT SUPPORTED' in vn_pdf_txt
    assert 'Audit defect count' not in vn_pdf_txt

    # All 7 SKILL.md <50L/<900tok & claim_audit 0 findings
    audit = run_cli(
        SCRIPTS_DIR / 'claim_audit.py',
        ['--suite-root', str(REPO_ROOT), '--readme', str(REPO_ROOT / 'README.md'), '--json'],
    )
    assert audit.returncode == 0, audit.stdout + audit.stderr
    data = json.loads(audit.stdout)
    assert data['finding_count'] == 0
    footprints = {item['name']: item['footprint'] for item in data['skills_audited']}
    for s in (
        'research-scientist',
        'research-precedent-corpus',
        'research-gap-rq-audit',
        'research-experiment-coding',
        'research-novelty-venue',
        'research-paper-writing',
        'research-user-report',
    ):
        fp = footprints[s]
        assert fp['lines'] < 50, fp
        assert fp['est_tokens'] < 900, fp
        assert fp['frontmatter_est_tokens'] < 140, fp
