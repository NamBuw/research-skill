"""Opaque-box CLI E2E tests for M9C Gap Discovery, Triage & Idea Seed Bridge."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'research-scientist' / 'scripts'
STORM_SCRIPT = SCRIPTS / 'storm_explorer.py'
PIPELINE_SCRIPT = SCRIPTS / 'gap_pipeline.py'
RECORD_SCRIPT = SCRIPTS / 'check_gap_record.py'
CLAIM_AUDIT_SCRIPT = SCRIPTS / 'claim_audit.py'


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, check=False)


def test_e2e_storm_to_gap_pipeline_to_check_gap_record_chain(tmp_path: Path):
    corpus_p = tmp_path / 'corpus.json'
    digests_p = tmp_path / 'digests.json'
    cands_p = tmp_path / 'candidates.json'
    storm_out = tmp_path / 'storm.json'
    gap_out = tmp_path / 'gap_out.json'
    bundle_out = tmp_path / 'idea_seed_bundle.json'
    record_p = tmp_path / 'gap_record.json'
    ev_dir = tmp_path / 'evidence'
    ev_dir.mkdir()

    corpus_p.write_text(json.dumps({
        'cutoff_date': '2026-01-01',
        'papers': [
            {
                'id': 'P1', 'source': 'openalex', 'family': 'same_problem', 'year': 2021, 'published_date': '2021-06-01',
                'title': 'BM25 and RRF In-Domain Latency',
                'abstract': 'RRF improves retrieval ndcg in-domain. Assumes i.i.d. query distribution. Zero calibration data.',
                'methods': ['rrf'], 'settings': ['beir'], 'metrics': ['ndcg'], 'regimes': ['in_domain'],
                'bottleneck': 'No confidence calibration under query shift.',
                'retraction_status': 'clean',
            },
            {
                'id': 'P2', 'source': 'arxiv', 'family': 'cross_setting_analogy', 'year': 2024, 'published_date': '2024-04-15',
                'title': 'Confidence Calibration Under OOD Shift',
                'abstract': 'RRF degrades calibration under OOD shift and cross-setting analogy.',
                'methods': ['rrf'], 'settings': ['beir'], 'metrics': ['calibration'], 'regimes': ['ood_shift'],
                'tradeoff': 'Extra calibration overhead under deployment constraints.',
                'retraction_status': 'clean',
            },
        ],
    }), encoding='utf-8')
    digests_p.write_text(json.dumps({
        'P1': {'access': 'full_text', 'digest': 'RRF improves in-domain NDCG without calibration.'},
        'P2': {'access': 'full_text', 'digest': 'OOD shift degrades RRF calibration.'},
    }), encoding='utf-8')
    cands_p.write_text(json.dumps({
        'target_venue_tier': 'q1_or_tier_a',
        'candidates': [
            {
                'id': 'G1',
                'claim': 'Calibrated rank fusion under OOD shift remains uncharacterized.',
                'cited_ids': ['P1', 'P2'],
                'support_ids': ['P1', 'P2'],
                'closest_work_ids': ['P1', 'P2'],
                'cutoff_year': 2026,
                'sgha_critics_passed': True,
                'engineering_checked': True,
                'consequence': 'Prevents silent retrieval failures in safety-critical RAG.',
                'why_now_enabler': 'New open OOD retrieval logs and lightweight logit probes enable slice calibration.',
                'root_cause_barrier': 'measurement_gap',
                'so_what_decision_impact': 'decision_changing',
                'durability_12_24m': 'durable_structural_limit',
                'code_prior_art_screened': True,
                'code_prior_art': [{'id': 'CPA1', 'platform': 'github', 'repo_or_url': 'https://github.com/org/none', 'relation': 'none_found', 'status': 'no_match'}],
                'idea_portfolio': [
                    {'id': 'I1', 'angle': 'minimal_fix_f19', 'title': 'Temp scaling over fused ranks'},
                    {'id': 'I2', 'angle': 'high_novelty_mechanism_q1', 'title': 'Causal transportability rank calibration'},
                    {'id': 'I3', 'angle': 'benchmark_diagnostic_analysis', 'title': 'OOD BEIR calibration failure benchmark'},
                    {'id': 'I4', 'angle': 'low_gpu_fallback', 'title': 'CPU quantile rank calibration'},
                ],
                'pre_mortem': {
                    'top_failure_modes': ['No gain over tuned temp scaling', 'High slice variance', 'Rank ties instability'],
                    'killer_experiment': {'duration_days': 2, 'design': '3-seed BEIR OOD pilot', 'kill_threshold': 'ECE delta < 0.01'},
                    'pivot_path': 'Pivot to diagnostic benchmark analysis paper.',
                },
            },
            {
                'id': 'G_DROP',
                'claim': 'Unchecked engineering bug claim',
                'cited_ids': ['P1', 'P2'],
                'support_ids': ['P1', 'P2'],
                'engineering_checked': False,
            },
        ],
    }), encoding='utf-8')

    # Step 1: storm_explorer --compact
    p_storm = _run([
        sys.executable, str(STORM_SCRIPT),
        '--topic', 'RRF calibration & OOD shift',
        '--corpus', str(corpus_p),
        '--target-regime', 'ood_shift',
        '--out', str(storm_out),
        '--compact',
    ])
    assert p_storm.returncode == 0, p_storm.stderr
    assert len(p_storm.stdout.encode('utf-8')) < 4096
    storm_sum = json.loads(p_storm.stdout)
    assert storm_sum['contradictions_count'] >= 1
    assert storm_sum['genuine_coverage_holes_count'] >= 1
    assert storm_sum['isomorphic_transfer_leads_count'] >= 1

    # Step 2: gap_pipeline --allow-partial --compact --seed-bundle-out
    p_pipe = _run([
        sys.executable, str(PIPELINE_SCRIPT),
        '--topic', 'RRF calibration & OOD shift',
        '--corpus', str(corpus_p),
        '--digests', str(digests_p),
        '--candidates', str(cands_p),
        '--storm', str(storm_out),
        '--subfield-preset', 'nlp_llm',
        '--require-idea-portfolio',
        '--require-pre-mortem',
        '--require-code-prior-art',
        '--allow-partial',
        '--seed-bundle-out', str(bundle_out),
        '--out', str(gap_out),
        '--compact',
    ])
    assert p_pipe.returncode == 0, p_pipe.stderr
    assert len(p_pipe.stdout.encode('utf-8')) < 4096
    pipe_report = json.loads(gap_out.read_text(encoding='utf-8'))
    assert len(pipe_report['surviving_gaps']) == 1
    assert pipe_report['rejected_gaps'][0]['reason_code'] == 'DROP_ENGINEERING_BUG'
    bundle = json.loads(bundle_out.read_text(encoding='utf-8'))
    assert bundle['schema'] == 'research_scientist_idea_seed_bundle_v1'
    assert bundle['seeds'][0]['gap_tier_ceiling'] == 'q1_top_tier_potential'
    assert all(v is None for idea in bundle['seeds'][0]['idea_portfolio'] for v in idea['ratings'].values())

    # Step 3: check_gap_record --evidence-dir
    (ev_dir / 'PaperOne2021.json').write_text(json.dumps({
        'source_id': 'PaperOne2021',
        'pages': [[{'page_idx': 0, 'text': 'RRF improves in-domain NDCG without calibration.'}]],
    }), encoding='utf-8')
    (ev_dir / 'PaperTwo2024.json').write_text(json.dumps({
        'source_id': 'PaperTwo2024',
        'pages': [[{'page_idx': 0, 'text': 'OOD shift degrades RRF calibration.'}]],
    }), encoding='utf-8')
    seed = bundle['seeds'][0]
    rec = {
        'scope': 'OOD rank fusion calibration',
        'search_date': '2026-01-01',
        'coverage_limits': 'Two primary benchmarks inspected.',
        'next_check': 'Run 2-day killer experiment.',
        'queries': [
            {'id': 'Q1', 'source': 'openalex', 'query': 'RRF OOD calibration', 'family': 'direct_problem', 'status': 'complete', 'retrieved': 2, 'inspected': 2},
            {'id': 'Q2', 'source': 'arxiv', 'query': 'rank aggregation calibration', 'family': 'alternate_vocabulary', 'status': 'complete', 'retrieved': 1, 'inspected': 1},
        ],
        'evidence': [
            {'id': 'E1', 'source_id': 'PaperOne2021', 'study_id': 'S1', 'locator': 'PaperOne2021.json page 1', 'claim': 'RRF improves in-domain NDCG without calibration.', 'access': 'full_text', 'role': 'result'},
            {'id': 'E2', 'source_id': 'PaperTwo2024', 'study_id': 'S2', 'locator': 'PaperTwo2024.json page 1', 'claim': 'OOD shift degrades RRF calibration.', 'access': 'full_text', 'role': 'result'},
        ],
        'closest_works': [
            {'id': 'W1', 'source_id': 'PaperOne2021', 'relation': 'partial_precedent', 'access': 'full_text', 'difference': 'In-domain only.', 'evidence_ids': ['E1']},
            {'id': 'W2', 'source_id': 'PaperTwo2024', 'relation': 'adjacent_precedent', 'access': 'full_text', 'difference': 'Vision shift only.', 'evidence_ids': ['E2']},
        ],
        'code_prior_art': [{'id': 'CPA1', 'platform': 'github', 'repo_or_url': 'https://github.com/org/none', 'relation': 'none_found', 'status': 'no_match'}],
        'candidates': [{
            'id': 'G1',
            'disposition': 'supported_candidate',
            'claim': seed['claim'],
            'type': 'method_boundary',
            'rationale': 'Observed gap across P1 and P2.',
            'engineering_status': 'implementation_checked',
            'support_evidence_ids': ['E1', 'E2'],
            'counter_evidence_ids': [],
            'closest_work_ids': ['W1', 'W2'],
            'kill_query_ids': ['Q2'],
            'consequence': 'Prevents silent retrieval failures.',
            'answer_path': 'Calibrate ranks on OOD slices.',
            'code_prior_art_screened': True,
            'code_prior_art_ids': ['CPA1'],
            'root_cause_barrier': seed['root_cause_barrier'],
            'why_now_enabler': seed['why_now_enabler'],
            'so_what_decision_impact': seed['so_what_decision_impact'],
            'durability_12_24m': seed['durability_12_24m'],
            'gap_tier_ceiling': seed['gap_tier_ceiling'],
            'portfolio_mode': True,
            'idea_portfolio': seed['idea_portfolio'],
            'pre_mortem': seed['pre_mortem'],
            'trajectory_tree': seed['trajectory_tree'],
        }],
    }
    record_p.write_text(json.dumps(rec), encoding='utf-8')
    p_rec = _run([sys.executable, str(RECORD_SCRIPT), str(record_p), '--evidence-dir', str(ev_dir)])
    assert p_rec.returncode == 0, p_rec.stdout + p_rec.stderr
    assert json.loads(p_rec.stdout)['valid_structure'] is True


def test_e2e_adversarial_kills_triage_warnings_and_zero_fabrication(tmp_path: Path):
    corpus_p = tmp_path / 'corpus.json'
    digests_p = tmp_path / 'digests.json'
    cands_p = tmp_path / 'candidates.json'
    camp_p = tmp_path / 'campaign.json'
    cpa_p = tmp_path / 'code_prior_art.json'

    corpus_p.write_text(json.dumps([
        {'id': 'P1', 'source': 'openalex', 'family': 'same_problem', 'year': 2022, 'title': 'P1 Study'},
        {'id': 'P2', 'source': 'arxiv', 'family': 'cross_setting_analogy', 'year': 2023, 'title': 'P2 Study'},
    ]), encoding='utf-8')
    digests_p.write_text(json.dumps({
        'P1': {'access': 'full_text', 'digest': 'P1 full text.'},
        'P2': {'access': 'full_text', 'digest': 'P2 full text.'},
    }), encoding='utf-8')
    camp_p.write_text(json.dumps({
        'schema': 'research_scientist_search_campaign_v1',
        'query_runs': [{'id': 'Q1', 'family': 'alternate_vocabulary', 'query': 'post-hoc logit calibration OOD'}],
        'source_records': [{'source': 's2', 'source_id': 'S2_HIT', 'year': 2024, 'title': 'Post-Hoc Logit Calibration Under OOD Shift', 'discovered_by': ['Q1']}],
    }), encoding='utf-8')
    cpa_p.write_text(json.dumps({
        'code_prior_art': [{'id': 'GH1', 'platform': 'huggingface', 'repo_or_url': 'https://huggingface.co/org/kv-compress', 'title': 'KV Cache Compression Wrapper', 'status': 'implemented'}],
    }), encoding='utf-8')

    cands_p.write_text(json.dumps([
        {
            'id': 'C_CAMPAIGN_KILL',
            'claim': 'Temperature scaling under OOD shift remains open.',
            'mechanism_aliases': ['post-hoc logit calibration'],
            'cited_ids': ['P1', 'P2'], 'support_ids': ['P1', 'P2'], 'engineering_checked': True,
        },
        {
            'id': 'C_CODE_KILL',
            'claim': 'KV cache compression wrapper for quantized models remains open.',
            'cited_ids': ['P1', 'P2'], 'support_ids': ['P1', 'P2'], 'engineering_checked': True,
        },
        {
            'id': 'C_WARN_ONLY',
            'claim': 'Thin prompt-wrapper trick for small context patch improves accuracy.',
            'cited_ids': ['P1', 'P2'], 'support_ids': ['P1', 'P2'], 'engineering_checked': True,
            'resource_requirements': {'gpu_count': 4, 'vram_gb': 80},
        },
    ]), encoding='utf-8')

    p_adv = _run([
        sys.executable, str(PIPELINE_SCRIPT),
        '--corpus', str(corpus_p),
        '--digests', str(digests_p),
        '--candidates', str(cands_p),
        '--campaign', str(camp_p),
        '--code-prior-art', str(cpa_p),
        '--target-venue-tier', 'q1',
        '--user-resources', '{"gpu_count":1,"vram_gb":24}',
        '--allow-partial',
    ])
    assert p_adv.returncode == 0, p_adv.stderr
    out = json.loads(p_adv.stdout)
    rej = {r['id']: r['reason_code'] for r in out['rejected_gaps']}
    assert rej['C_CAMPAIGN_KILL'] == 'DROP_ALREADY_SOLVED'
    assert rej['C_CODE_KILL'] == 'DROP_ALREADY_SOLVED'
    surv = out['surviving_gaps'][0]
    assert surv['id'] == 'C_WARN_ONLY'
    assert surv['gap_below_target_venue_tier'] is True
    assert surv['resource_feasibility']['infeasible_under_user_resources'] is True
    assert surv['missing_or_weak_why_now_enabler'] is True
    assert surv['scoop_and_obsolescence_risk']['recent_preprints_12m'] is None
    assert 'preprint_recency_metadata_unavailable' in surv['scoop_and_obsolescence_risk']['unknown_disclosures']

    # Strict triage rejects C_WARN_ONLY -> exit 1
    p_strict = _run([
        sys.executable, str(PIPELINE_SCRIPT),
        '--corpus', str(corpus_p),
        '--digests', str(digests_p),
        '--candidates', str(cands_p),
        '--campaign', str(camp_p),
        '--code-prior-art', str(cpa_p),
        '--target-venue-tier', 'q1',
        '--user-resources', '{"gpu_count":1,"vram_gb":24}',
        '--strict-triage',
    ])
    assert p_strict.returncode == 1

    # Invalid NaN JSON exits 2
    nan_p = tmp_path / 'nan.json'
    nan_p.write_text('{"scope": "s", "search_date": "2026", "coverage_limits": "c", "next_check": "n", "x": NaN}', encoding='utf-8')
    p_nan = _run([sys.executable, str(RECORD_SCRIPT), str(nan_p)])
    assert p_nan.returncode == 2


def test_e2e_failure_first_and_claim_audit_and_skill_footprints(tmp_path: Path):
    corpus_p = tmp_path / 'corpus.json'
    fc_p = tmp_path / 'failure_cases.json'
    corpus_p.write_text(json.dumps([
        {'id': 'P1', 'title': 'Quantization Latency', 'year': 2024, 'family': 'cross_setting_analogy', 'text': 'Quantized inference causes tail latency spikes.'},
    ]), encoding='utf-8')
    fc_p.write_text(json.dumps([
        {'id': 'FC1', 'error_type': 'tail_latency_spike', 'slice': 'quantized', 'baseline': 'INT4-Llama', 'description': 'p99 latency spikes 4x'},
    ]), encoding='utf-8')
    p_fc = _run([
        sys.executable, str(STORM_SCRIPT),
        '--topic', 'quantized inference',
        '--corpus', str(corpus_p),
        '--failure-cases', str(fc_p),
        '--compact',
    ])
    assert p_fc.returncode == 0, p_fc.stderr
    assert json.loads(p_fc.stdout)['failure_first_patterns_count'] == 1

    p_audit = _run([sys.executable, str(CLAIM_AUDIT_SCRIPT), '--suite-root', str(ROOT), '--json'])
    assert p_audit.returncode == 0, p_audit.stdout + p_audit.stderr
    audit_data = json.loads(p_audit.stdout)
    assert audit_data['finding_count'] == 0
    for sk in audit_data['skills_audited']:
        assert sk['footprint']['lines'] < 50
        assert sk['footprint']['est_tokens'] < 900


def test_e2e_cli_regression_guards(tmp_path: Path):
    corpus_p = tmp_path / 'corpus.json'
    digests_p = tmp_path / 'digests.json'
    cands_p = tmp_path / 'candidates.json'
    rec_p = tmp_path / 'bad_rec.json'

    corpus_p.write_text(json.dumps([
        {'id': 'P1', 'source': 'openalex', 'family': 'same_problem', 'year': 2022, 'title': 'A'},
        {'id': 'P2', 'source': 'arxiv', 'family': 'cross_setting_analogy', 'year': 2023, 'title': 'B'},
    ]), encoding='utf-8')
    digests_p.write_text(json.dumps({
        'P1': {'access': 'full_text', 'digest': 'A'},
        'P2': {'access': 'full_text', 'digest': 'B'},
    }), encoding='utf-8')
    cands_p.write_text(json.dumps([
        {'id': 'G1', 'claim': 'Novel OOD gap.', 'cited_ids': ['P1', 'P2'], 'support_ids': ['P1', 'P2'], 'engineering_checked': True},
    ]), encoding='utf-8')

    # Negative user resources exits 2 cleanly even with --allow-partial
    p_neg = _run([
        sys.executable, str(PIPELINE_SCRIPT),
        '--corpus', str(corpus_p), '--digests', str(digests_p), '--candidates', str(cands_p),
        '--user-resources', '{"gpu_count": -1, "vram_gb": -24}', '--allow-partial',
    ])
    assert p_neg.returncode == 2
    assert 'error' in json.loads(p_neg.stderr)

    # Invalid --as-of-date exits 2 cleanly
    p_date = _run([
        sys.executable, str(PIPELINE_SCRIPT),
        '--corpus', str(corpus_p), '--digests', str(digests_p), '--candidates', str(cands_p),
        '--as-of-date', 'not-a-date',
    ])
    assert p_date.returncode == 2
    assert 'error' in json.loads(p_date.stderr)

    # check_gap_record exits 1 with structured JSON (no traceback) on unhashable enum lists
    base_rec = json.loads((ROOT / 'research-scientist' / 'references' / 'gap-record.schema-example.json').read_text(encoding='utf-8'))
    base_rec['candidates'][0]['root_cause_barrier'] = ['measurement_gap']
    rec_p.write_text(json.dumps(base_rec), encoding='utf-8')
    p_rec = _run([sys.executable, str(RECORD_SCRIPT), str(rec_p)])
    assert p_rec.returncode == 1
    assert 'Traceback' not in p_rec.stderr
    assert 'candidates:G1:invalid_root_cause_barrier' in json.loads(p_rec.stdout)['errors']
