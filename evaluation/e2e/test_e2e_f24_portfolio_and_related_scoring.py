"""Opaque-box E2E tests for F24 (closest-work + portfolio) and F25 (cross-topic bar + tier rejection)."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import fitz

from helpers import (
    MockScholarlyServer,
    PdfFactory,
    REFS_DIR,
    REPO_ROOT,
    SCRIPTS_DIR,
    T123_FIXTURES_DIR,
    iso_utc,
    run_cli,
)

MAX_COMPACT_BYTES = 4096


def _weights():
    return {'importance': 15, 'novelty': 20, 'soundness': 20, 'evidence': 20, 'transparency': 15, 'clarity': 10}


def _ratings(vals):
    return dict(zip(_weights().keys(), vals))


def test_t1_f24_closest_related_work_and_portfolio_cli_contracts(tmp_path: Path) -> None:
    """T1-F24: Real PDFs -> compare_scorecards --target-id --strict-related-panel & compare_venue_novelty --portfolio."""
    src_dir = tmp_path / 'sources'
    src_dir.mkdir()
    profiles = []
    specs = [
        ('target_635', (7, 6, 7, 6, 6, 6), ['rw1', 'rw2', 'rw3'], {'contribution_delta': 'Bounded split ablation'}),
        ('rw1', (7, 6, 7, 7, 6, 6), ['rw2'], {}),
        ('rw2', (8, 7, 7, 7, 7, 7), ['rw1'], {}),
        ('rw3', (6, 5, 6, 6, 6, 6), ['rw1'], {}),
    ]
    for pid, r_vals, cw, extra in specs:
        pdf_path = src_dir / f'{pid}.pdf'
        PdfFactory.make_clean_paper_pdf(
            pdf_path,
            title=f'Paper {pid}',
            quote_p1=f'Verified evaluation evidence for {pid} on clean splits.',
        )
        loc = f'{pid}.pdf#page=1 "Verified evaluation evidence"'
        profiles.append({
            'id': pid,
            'reading_basis': 'full_text',
            'closest_work': cw,
            'ratings': _ratings(r_vals),
            'evidence_locators': {d: [loc] for d in _weights()},
            **extra,
        })

    sc_in = tmp_path / 'sc.json'
    sc_out = tmp_path / 'sc_out.json'
    sc_in.write_text(json.dumps({'weight_scenarios': [_weights()], 'profiles': profiles}), encoding='utf-8')

    ok_res = run_cli(
        SCRIPTS_DIR / 'compare_scorecards.py',
        [str(sc_in), '--target-id', 'target_635', '--strict-related-panel', '--min-related', '3', '--sources-dir', str(src_dir), '--out', str(sc_out), '--compact'],
    )
    assert ok_res.returncode == 0, ok_res.stderr + ok_res.stdout
    assert len(ok_res.stdout.encode('utf-8')) < MAX_COMPACT_BYTES
    assert ok_res.json_out['related_work_comparison']['best_related_overall'] == 7.15
    assert ok_res.json_out['related_work_comparison']['target_delta_vs_best_related_overall'] == -0.8

    # Remove 1 closest_work profile -> fail closed exit 1
    sc_bad = tmp_path / 'sc_bad.json'
    sc_bad.write_text(json.dumps({'weight_scenarios': [_weights()], 'profiles': profiles[:3]}), encoding='utf-8')
    bad_res = run_cli(
        SCRIPTS_DIR / 'compare_scorecards.py',
        [str(sc_bad), '--target-id', 'target_635', '--strict-related-panel', '--min-related', '3', '--sources-dir', str(src_dir)],
    )
    assert bad_res.returncode == 1
    assert 'unscored_closest_work:rw3' in bad_res.json_out['issues']

    # Invalid CLI flags -> exit 2
    assert run_cli(SCRIPTS_DIR / 'compare_scorecards.py', [str(sc_in), '--min-related', '0']).returncode == 2
    assert run_cli(SCRIPTS_DIR / 'compare_venue_novelty.py', [str(sc_in), '--portfolio']).returncode == 2


def test_t3_f25_cross_topic_capture_panel_tier_rejection_to_en_vi_pdfs(
    mock_server: MockScholarlyServer, tmp_path: Path
) -> None:
    """T3-F25: Offline CFP capture (clean + stale redirect + JS shell) + PMLR panel + workshop-vs-Q1 rejection & retarget + strict EN/VI PDFs."""
    # Serve offline CFP pages (valid Q1, valid Workshop, stale redirect /2027/->/2025/, JS SPA shell)
    mock_server.add_route('/q1/cfp', (200, 'text/html', '<html><body><h1>TKDE Q1 CFP</h1><p>Scope covers machine learning systems. Deadline open. Author fee USD 0.</p></body></html>'), host='cfp.example.org')
    mock_server.add_route('/ws/cfp', (200, 'text/html', '<html><body><h1>NeurIPS Workshop CFP</h1><p>Preliminary workshop on ML evaluation. Deadline open. Fee USD 250.</p></body></html>'), host='cfp.example.org')
    mock_server.add_route('/stale/2027/cfp', (302, 'https://cfp.example.org/stale/2025/cfp', ''), host='cfp.example.org')
    mock_server.add_route('/stale/2025/cfp', (200, 'text/html', '<html><body><h1>2025 Archive</h1><p>Old 2025 CFP scope.</p></body></html>'), host='cfp.example.org')
    mock_server.add_route('/js-spa/cfp', (200, 'text/html', '<html><body><div id="root"></div><noscript>Enable JavaScript</noscript></body></html>'), host='cfp.example.org')

    payloads = json.loads((T123_FIXTURES_DIR / 'mock_scholarly_payloads.json').read_text(encoding='utf-8'))
    mock_server.add_route('/v235/', (200, 'text/html', payloads['pmlr_v235_html']), host='proceedings.mlr.press')
    mock_server.add_route('/v235', (200, 'text/html', payloads['pmlr_v235_html']), host='proceedings.mlr.press')

    dossier = {
        'venue': 'Portfolio Capture',
        'edition': '2027',
        'official_cfp_url': 'https://cfp.example.org/q1/cfp',
        'checked_at': iso_utc(0),
        'evidence_claims': [
            {'field': 'q1', 'source_url': 'https://cfp.example.org/q1/cfp', 'quote': 'Scope covers machine learning systems.'},
            {'field': 'ws', 'source_url': 'https://cfp.example.org/ws/cfp', 'quote': 'Preliminary workshop on ML evaluation.'},
            {'field': 'stale', 'source_url': 'https://cfp.example.org/stale/2027/cfp', 'quote': 'Old 2025 CFP scope.'},
            {'field': 'js', 'source_url': 'https://cfp.example.org/js-spa/cfp', 'quote': 'Enable JavaScript'},
        ],
    }
    src_dir = tmp_path / 'sources'
    src_dir.mkdir()
    dos_path = tmp_path / 'dossier.json'
    dos_path.write_text(json.dumps(dossier), encoding='utf-8')
    bundle_path = src_dir / 'venue-sources.json'
    cap_res = run_cli(
        SCRIPTS_DIR / 'capture_venue_sources.py',
        [str(dos_path), '--out', str(bundle_path), '--compact'],
        env=mock_server.env(),
    )
    assert cap_res.returncode == 0, cap_res.stderr

    panel_path = tmp_path / 'panel.json'
    p_res = run_cli(
        SCRIPTS_DIR / 'venue_panel_collector.py',
        ['--source', 'pmlr', '--venue-id', 'v235', '--limit', '5', '--out', str(panel_path), '--compact'],
        env=mock_server.env(),
    )
    assert p_res.returncode == 0, p_res.stderr
    collected = json.loads(panel_path.read_text(encoding='utf-8'))['accepted_panel']

    # Create local evidence files for target + panel papers
    base_fix = json.loads((REFS_DIR / 'venue-novelty-profile.fixture.json').read_text(encoding='utf-8'))
    (src_dir / 'ws_target.txt').write_text('Preliminary small-scale ablation on two toy datasets.\n', encoding='utf-8')
    target = copy.deepcopy(base_fix['target'])
    target.update({
        'id': 'ws_target',
        'score': 4, 'low': 3, 'high': 5,
        'closest_work_id': 'ws_target',
        'closest_work_locator': 'ws_target.txt#L1 "Preliminary small-scale ablation"',
        'assessed_at_utc': iso_utc(0),
    })

    def _build_panel(track_name, scores, overalls, rels):
        rows = copy.deepcopy(base_fix['accepted_panel'])
        for i, row in enumerate(rows):
            pid = f'{track_name.replace(" ", "_")}_P{i+1}'
            (src_dir / f'{pid}.txt').write_text(f'Accepted full text evidence for {pid}.\n', encoding='utf-8')
            row['id'] = pid
            row['track'] = track_name
            row['score'] = scores[i]
            row['low'] = scores[i] - 1
            row['high'] = scores[i] + 1
            row['overall_score'] = overalls[i]
            row['topic_relation'] = rels[i]
            row['closest_work_id'] = pid
            row['closest_work_locator'] = f'{pid}.txt#L1 "Accepted full text evidence"'
            row['assessed_at_utc'] = iso_utc(0)
            if i < len(collected):
                row['official_acceptance_url'] = collected[i]['official_acceptance_url']
        return rows

    def _cand(vid, name, track, url, quote, panel_args, tier_exp=None, role='alternative'):
        c = {
            'venue_id': vid,
            'role': role,
            'venue': {
                'name': name, 'edition': '2027', 'track': track,
                'official_cfp_url': url, 'checked_at_utc': iso_utc(0), 'max_source_age_days': 14,
            },
            'panel_selection': copy.deepcopy(base_fix['panel_selection']),
            'accepted_panel': _build_panel(track, *panel_args),
            'fit_axes': [
                {'name': ax, 'score': 2, 'source_url': url, 'locator': f'"{quote}"', 'reason': f'{ax} verified'}
                for ax in ('scope_audience', 'contribution_track', 'evidence_maturity', 'format_eligibility', 'user_constraints')
            ],
            'hard_constraints': [
                {'name': cn, 'status': 'met', 'source_url': url, 'reason': f'{cn} open'}
                for cn in ('deadline', 'budget', 'eligibility')
            ],
        }
        if tier_exp:
            c['tier_expectation'] = tier_exp
        return c

    portfolio = {
        'target': target,
        'target_scorecard': {
            'weights': _weights(),
            'ratings': _ratings((6, 4, 6, 5, 6, 6)),  # 5.40 workshop-scale
        },
        'candidate_venues': [
            _cand('q1-tkde', 'TKDE', 'Regular Track', 'https://cfp.example.org/q1/cfp', 'Scope covers machine learning systems.',
                  ((6, 6, 7, 7, 8), (6.6, 6.8, 7.0, 7.2, 7.4), ('different_topic',) * 5), tier_exp='q1_or_tier_a', role='primary'),
            _cand('ws-neurips', 'NeurIPS Workshop on Trustworthy AI', 'Workshop', 'https://cfp.example.org/ws/cfp', 'Preliminary workshop on ML evaluation.',
                  ((3, 4, 4, 5, 5), (5.1, 5.3, 5.4, 5.6, 5.8), ('different_topic', 'different_topic', 'adjacent_topic', 'same_topic', 'different_topic'))),
            _cand('stale-conf', 'StaleConf', 'Main Track', 'https://cfp.example.org/stale/2027/cfp', 'Old 2025 CFP scope.',
                  ((5, 5, 6, 6, 7), (6.0, 6.1, 6.2, 6.3, 6.4), ('same_topic',) * 5)),
            _cand('js-conf', 'JsConf', 'Main Track', 'https://cfp.example.org/js-spa/cfp', 'Enable JavaScript',
                  ((5, 5, 6, 6, 7), (6.0, 6.1, 6.2, 6.3, 6.4), ('same_topic',) * 5)),
        ],
    }
    p_in = tmp_path / 'portfolio.json'
    p_out = tmp_path / 'portfolio_out.json'
    p_in.write_text(json.dumps(portfolio), encoding='utf-8')
    res = run_cli(
        SCRIPTS_DIR / 'compare_venue_novelty.py',
        [str(p_in), '--portfolio', '--require-panels', '--sources-dir', str(src_dir), '--out', str(p_out), '--compact'],
    )
    assert res.returncode == 0, res.stderr + res.stdout
    assert len(res.stdout.encode('utf-8')) < MAX_COMPACT_BYTES
    rec = res.json_out['venue_portfolio_recommendations']
    assert rec['portfolio_verdict'] == 'retargeted_to_matched_tier'
    assert rec['rejected_below_venue_tier'] == ['q1-tkde']
    assert rec['stretch_high_risk'] == []
    assert rec['recommended_now'] == ['ws-neurips']
    assert set(rec['withheld_unverified']) == {'stale-conf', 'js-conf'}
    assert rec['recommended_matched_tier']['top_venue_id'] == 'ws-neurips'

    # Direct raw portfolio JSON -> report_latex_pdf.py --strict
    direct_pdf = tmp_path / 'direct_port.pdf'
    d_rep = run_cli(
        SCRIPTS_DIR / 'report_latex_pdf.py',
        ['--input', str(p_out), '--out', str(direct_pdf), '--strict', '--json', '--compact'],
    )
    assert d_rep.returncode == 0, d_rep.stdout + d_rep.stderr
    assert d_rep.json_out['status'] == 'ok'

    # Canonical VI strict PDF summarizing cross-topic Q1 rejection & workshop retargeting
    vi_in = tmp_path / 'vi_retarget.json'
    vi_pdf = tmp_path / 'vi_retarget.pdf'
    vi_doc = {
        'schema': 'research_scientist_executive_report_v1',
        'report_type': 'novelty_scoring',
        'lang': 'vi',
        'title': 'Kiểm tra bậc tạp chí Q1 và chuyển hướng hội thảo',
        'verdict': {
            'status': 'caution',
            'summary': 'Bài đạt 5.40/10, kém mức trung vị 7.00/10 của hội đồng khác chủ đề [p_out.json]. Bác bỏ mục tiêu Q1 và chuyển sang hội thảo kiểm chứng.',
            'evidence_refs': ['K1', 'K2'],
        },
        'key_evidence': [
            {'id': 'K1', 'claim': 'Điểm bài báo', 'value': '5.40/10', 'status': 'verified', 'locator': 'p_out.json'},
            {'id': 'K2', 'claim': 'Mức đóng góp Q1 khác chủ đề', 'value': '7.00/10', 'status': 'verified', 'locator': 'p_out.json'},
        ],
        'flaws_and_risks': [
            {'id': 'R1', 'severity': 'high', 'summary': 'Thiếu 1 điểm novelty và 1 điểm evidence cho Q1 [p_out.json].', 'locator': 'p_out.json'},
        ],
        'next_steps': [
            {'step': 1, 'action': 'Nộp hội thảo NeurIPS Workshop hoặc bổ sung thực nghiệm trước khi nộp Q1.', 'target': 'ws-neurips'},
        ],
    }
    vi_in.write_text(json.dumps(vi_doc, ensure_ascii=False), encoding='utf-8')
    vi_rep = run_cli(
        SCRIPTS_DIR / 'report_latex_pdf.py',
        ['--input', str(vi_in), '--out', str(vi_pdf), '--lang', 'vi', '--strict', '--json', '--compact'],
    )
    assert vi_rep.returncode == 0, vi_rep.stdout + vi_rep.stderr
    assert vi_rep.json_out['diacritics_verified'] is True
    with fitz.open(vi_pdf) as pdf_doc:
        vi_txt = '\n'.join(p.get_text() for p in pdf_doc)
    assert '5.40/10' in vi_txt
    assert 'Bác bỏ' in vi_txt and 'tiêu Q1' in vi_txt


def test_t5_f24_f25_adversarial_inflation_duplicates_and_claim_audit(tmp_path: Path) -> None:
    """T5-F24/F25: Novelty inflation warning, duplicate venue rejection, NaN exit 2, SKILL.md <50L/<900tok, claim_audit=0."""
    # Duplicate venue_id in portfolio -> exit 1
    base_fix = json.loads((REFS_DIR / 'venue-novelty-profile.fixture.json').read_text(encoding='utf-8'))
    base_fix['venue']['checked_at_utc'] = iso_utc(0)
    base_fix['target']['assessed_at_utc'] = iso_utc(0)
    cand = {
        'venue_id': 'dup-venue',
        'venue': base_fix['venue'],
        'fit_axes': base_fix['fit_axes'],
        'hard_constraints': base_fix['hard_constraints'],
    }
    dup_path = tmp_path / 'dup_port.json'
    dup_path.write_text(json.dumps({
        'target': base_fix['target'],
        'candidate_venues': [cand, copy.deepcopy(cand), {**copy.deepcopy(cand), 'venue_id': 'v3', 'venue': {**base_fix['venue'], 'name': 'Other'}}],
    }), encoding='utf-8')
    dup_res = run_cli(SCRIPTS_DIR / 'compare_venue_novelty.py', [str(dup_path), '--portfolio'])
    assert dup_res.returncode == 1
    assert any('duplicate_venue' in e for e in dup_res.json_out['errors'])

    # NaN in --target-overall -> exit 2
    assert run_cli(SCRIPTS_DIR / 'compare_venue_novelty.py', [str(dup_path), '--target-overall', 'NaN']).returncode == 2

    # Suite claim_audit & all 7 SKILL.md footprints
    ca = run_cli(
        SCRIPTS_DIR / 'claim_audit.py',
        ['--suite-root', str(REPO_ROOT), '--readme', str(REPO_ROOT / 'README.md'), '--json'],
    )
    assert ca.returncode == 0, ca.stdout + ca.stderr
    data = json.loads(ca.stdout)
    assert data['finding_count'] == 0
    for item in data['skills_audited']:
        fp = item['footprint']
        assert fp['lines'] < 50, item
        assert fp['est_tokens'] < 900, item
        assert fp['frontmatter_est_tokens'] < 140, item
