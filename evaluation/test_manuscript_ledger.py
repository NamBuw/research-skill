"""Structural and manuscript-grounded ledger checks with fictional fixtures."""
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'research-scientist/scripts/check_manuscript_ledger.py'
spec = importlib.util.spec_from_file_location('check_manuscript_ledger', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


class ManuscriptLedgerTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / 'research-scientist/references/manuscript-ledger.schema-example.json').read_text())

    def test_complete_fictional_structure(self):
        self.assertEqual(module.check(self.data)['status'], 'structure_passed')

    def test_claim_without_verified_locator_fails(self):
        self.data['sources'][0]['verified'] = False
        self.assertIn('material_claim_without_verified_locator:C1', module.check(self.data)['issues'])

    def test_recombination_novelty_requires_difference_evidence(self):
        method = self.data['methods'][0]
        method['novelty_claimed'] = True
        method['grand_name'] = True
        issues = module.check(self.data)['issues']
        self.assertIn('unsupported_method_novelty:M1', issues)
        self.assertIn('inflated_method_name:M1', issues)

    def test_grand_name_still_flagged_with_declared_difference(self):
        method = self.data['methods'][0]
        method['grand_name'] = True
        method['difference_evidence'] = 'Fictional result table 2'
        self.assertIn('inflated_method_name:M1', module.check(self.data)['issues'])

    def test_reused_method_cannot_be_claimed_as_new_method(self):
        method = self.data['methods'][0]
        method['origin'] = 'reused'
        method['novelty_claimed'] = True
        method['difference_evidence'] = 'Fictional result table 2'
        method['closest_work_source_ids'] = ['E2']
        method['human_adjudication'] = {'reviewer': 'fictional_author', 'date': '2026-11-21', 'rationale': 'fictional'}
        self.assertIn('reused_method_claimed_as_new:M1', module.check(self.data)['issues'])

    def test_numeric_mismatch_fails(self):
        self.data['numeric_facts'][0]['occurrences'][1]['value'] = 0.72
        self.assertIn('numeric_fact_mismatch:N1', module.check(self.data)['issues'])

    def test_unknown_source_and_duplicate_claim(self):
        other = copy.deepcopy(self.data['claims'][0])
        other['source_ids'] = ['E9']
        self.data['claims'].append(other)
        issues = module.check(self.data)['issues']
        self.assertIn('duplicate_claim:C1', issues)
        self.assertIn('unknown_source:C1:E9', issues)


class ManuscriptLedgerHardeningTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / 'research-scientist/references/manuscript-ledger.schema-example.json').read_text())

    def test_shnlc_grandiose_stitched_method_bypass_rejected(self):
        self.data['methods'][0]['origin'] = 'combined'
        self.data['methods'][0]['grand_name'] = False
        self.data['methods'][0]['novelty_claimed'] = False
        manuscript = (
            "# SHNLC: Synergistic Hyperbolic Neuro-Lexical Cascade — A Groundbreaking Unified Framework\n\n"
            "## Abstract\n"
            "We propose SHNLC, combining BM25, Contriever, RRF, and a Cross-Encoder, achieving a 14.2% SOTA gain "
            "with a benchmark score of 0.71. This is not merely retrieval, but cognitive synthesis.\n"
        )
        res = module.check(self.data, manuscript_text=manuscript)
        self.assertEqual(res['status'], 'structural_issues')
        self.assertIn('inflated_method_name:M1', res['issues'])
        self.assertIn('undeclared_manuscript_numeric_claim:14.2%', res['issues'])
        self.assertIn('unsupported_novelty_overclaim:manuscript', res['issues'])

    def test_newly_derived_without_derivation_evidence_blocked(self):
        self.data['methods'][0]['origin'] = 'newly_derived'
        self.data['methods'][0]['grand_name'] = False
        manuscript = (
            "# HyperFusion-Net: A Revolutionary Unified Paradigm\n\n"
            "We introduce HyperFusion-Net with score 0.71.\n"
        )
        res = module.check(self.data, manuscript_text=manuscript)
        self.assertIn('missing_derivation_evidence:M1', res['issues'])
        self.assertIn('inflated_method_name:M1', res['issues'])

    def test_undeclared_methods_with_grandiose_manuscript_rejected(self):
        self.data['methods'] = []
        manuscript = (
            "# OmniCascade: A Breakthrough Unified Architecture\n\n"
            "We present OmniCascade with score 0.71.\n"
        )
        res = module.check(self.data, manuscript_text=manuscript)
        self.assertIn('undeclared_method_branding:manuscript', res['issues'])

    def test_plain_honest_combined_method_with_latex_and_sources_dir_passes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sdir = Path(tmpdir)
            (sdir / 'run-001.json').write_text(json.dumps({'metric': 0.71}), encoding='utf-8')
            (sdir / 'cormack2009.json').write_text(
                json.dumps({
                    'format': 'research_scientist_pdf_blocks_v1',
                    'blocks': [
                        {'page': 3, 'text': 'Reciprocal rank fusion combines rankings from multiple retrieval models.'}
                    ],
                }),
                encoding='utf-8',
            )
            ledger = {
                'sources': [
                    {
                        'id': 'E1',
                        'type': 'run_log',
                        'locator': 'run-001.json#metric',
                        'verified': True,
                        'verified_by': 'author',
                        'verified_at': '2026-11-21',
                    },
                    {
                        'id': 'E2',
                        'type': 'paper',
                        'locator': 'cormack2009.json, page 3',
                        'quote': 'Reciprocal rank fusion combines rankings from multiple retrieval models.',
                        'verified': True,
                        'verified_by': 'author',
                        'verified_at': '2026-11-21',
                    },
                ],
                'claims': [
                    {'id': 'C1', 'kind': 'reported', 'material': True, 'source_ids': ['E1']}
                ],
                'methods': [
                    {
                        'id': 'M1',
                        'origin': 'combined',
                        'source_ids': ['E2'],
                        'exact_change': 'Sequentially applies BM25 then RRF (Cormack et al., 2009).',
                        'novelty_claimed': False,
                        'grand_name': False,
                    }
                ],
                'numeric_facts': [
                    {
                        'id': 'N1',
                        'occurrences': [
                            {'location': 'abstract', 'value': 0.71, 'unit': 'nDCG'},
                            {'location': 'results table', 'value': 0.71, 'unit': 'nDCG'},
                        ],
                    }
                ],
            }
            tex = (
                "\\title{Combining BM25 and Reciprocal Rank Fusion}\n"
                "% 99.9% ignored comment\n"
                "\\begin{abstract}\n"
                "We combine BM25 and RRF (Cormack et al., 2009) and observe \\textbf{0.71} nDCG.\n"
                "\\end{abstract}\n"
                "\\begin{table}\n"
                "Score & \\textbf{0.71} \\\\\n"
                "\\end{table}\n"
            )
            res = module.check(ledger, manuscript_text=tex, sources_dir=sdir)
            self.assertEqual(res['status'], 'structure_passed', res['issues'])
            self.assertEqual(res['issues'], [])

    def test_latex_numeric_mismatch_and_missing_fact_detected(self):
        tex = (
            "\\begin{abstract}\n"
            "Our baseline yields \\textbf{0.85} nDCG.\n"
            "\\end{abstract}\n"
        )
        res = module.check(self.data, manuscript_text=tex)
        self.assertIn('manuscript_numeric_fact_missing:N1:abstract', res['issues'])
        self.assertIn('undeclared_manuscript_numeric_claim:0.85', res['issues'])

    def test_sources_dir_quote_locator_page_and_traversal_checks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sdir = Path(tmpdir)
            (sdir / 'run-001.json').write_text(json.dumps({'metric': 0.71}), encoding='utf-8')
            (sdir / 'cormack2009.json').write_text(
                json.dumps({
                    'format': 'research_scientist_pdf_blocks_v1',
                    'blocks': [
                        {'page': 1, 'text': 'Introduction to information retrieval evaluation.'},
                        {'page': 3, 'text': 'Reciprocal rank fusion combines rankings cleanly.'},
                    ],
                }),
                encoding='utf-8',
            )
            # 1. Fabricated quote
            d1 = copy.deepcopy(self.data)
            d1['sources'][0]['locator'] = 'run-001.json#metric'
            d1['sources'][1]['locator'] = 'cormack2009.json, page 3'
            d1['sources'][1]['quote'] = 'Completely fabricated non-existent quote.'
            self.assertIn('source_quote_not_found:E2', module.check(d1, sources_dir=sdir)['issues'])

            # 2. Quote on page 3 but locator says page 1
            d2 = copy.deepcopy(d1)
            d2['sources'][1]['locator'] = 'cormack2009.json, page 1'
            d2['sources'][1]['quote'] = 'Reciprocal rank fusion combines rankings cleanly.'
            self.assertIn('source_quote_page_mismatch:E2', module.check(d2, sources_dir=sdir)['issues'])

            # 3. Missing file in locator
            d3 = copy.deepcopy(d1)
            d3['sources'][0]['locator'] = 'missing/run.json#metric'
            d3['sources'][1]['quote'] = 'Reciprocal rank fusion combines rankings cleanly.'
            self.assertIn('source_locator_file_missing:E1', module.check(d3, sources_dir=sdir)['issues'])

            # 4. Path traversal
            d4 = copy.deepcopy(d1)
            d4['sources'][0]['locator'] = '../secret.txt'
            d4['sources'][1]['quote'] = 'Reciprocal rank fusion combines rankings cleanly.'
            self.assertIn('invalid_source_path:E1', module.check(d4, sources_dir=sdir)['issues'])

    def test_cli_flags_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            td = Path(tmpdir)
            ledger_p = td / 'ledger.json'
            ledger_p.write_text(json.dumps(self.data), encoding='utf-8')
            shnlc_p = td / 'shnlc.md'
            shnlc_p.write_text(
                "# SHNLC: Synergistic Hyperbolic Neuro-Lexical Cascade — A Groundbreaking Unified Framework\n",
                encoding='utf-8',
            )
            src_dir = td / 'src'
            src_dir.mkdir()
            (src_dir / 'dummy.txt').write_text('hello', encoding='utf-8')

            p0 = run_cli(str(ledger_p))
            self.assertEqual(p0.returncode, 0, p0.stdout + p0.stderr)

            p1 = run_cli('--ledger', str(ledger_p), '--manuscript', str(shnlc_p), '--sources-dir', str(src_dir))
            self.assertEqual(p1.returncode, 1, p1.stdout + p1.stderr)
            self.assertEqual(json.loads(p1.stdout)['status'], 'structural_issues')

            p2 = run_cli('--ledger', str(td / 'missing.json'))
            self.assertEqual(p2.returncode, 2)

    def test_mineru_v2_sources_and_claim_markers_and_newly_derived_grand_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sdir = Path(tmpdir)
            (sdir / 'run-001.json').write_text(json.dumps({'nested': {'metric': 0.71}}), encoding='utf-8')
            (sdir / 'mineru.json').write_text(
                json.dumps([
                    [{'type': 'text', 'page_idx': 0, 'content': 'Introductory context on retrieval.'}],
                    [{'type': 'text', 'page_idx': 1, 'content': 'BM25 baseline attains 0.64 nDCG on BEIR.'}],
                ]),
                encoding='utf-8',
            )
            ledger = copy.deepcopy(self.data)
            ledger['sources'][0]['locator'] = 'run-001.json#nested.metric'
            ledger['sources'][1]['locator'] = 'mineru.json, page 2'
            ledger['sources'][1]['quote'] = 'BM25 baseline attains 0.64 nDCG on BEIR.'
            ledger['methods'][0]['origin'] = 'newly_derived'
            ledger['methods'][0]['derivation_evidence'] = 'Theorem 1 proves convergence.'
            ledger['claims'][0]['text'] = 'Baseline yields 0.71'
            manuscript = (
                "## Abstract\n"
                "Baseline yields 0.71 [claim:C1] [claim:C99].\n"
                "## Results\n"
                "Table reports 0.71.\n"
            )
            res = module.check(ledger, manuscript_text=manuscript, sources_dir=sdir)
            self.assertIn('unknown_manuscript_claim_marker:C99', res['issues'])
            self.assertNotIn('source_quote_not_found:E2', res['issues'])
            self.assertNotIn('source_locator_fragment_missing:E1', res['issues'])

            # Missing dotted fragment & newly_derived with grand_name=True lacking justification
            ledger['sources'][0]['locator'] = 'run-001.json#nested.missing_key'
            ledger['methods'][0]['grand_name'] = True
            res2 = module.check(ledger, sources_dir=sdir)
            self.assertIn('source_locator_fragment_missing:E1', res2['issues'])
            self.assertIn('unsupported_grand_method_name:M1', res2['issues'])

    def test_parsimony_multi_component_gate_positive_and_negative(self):
        # Negative 1: Multi-component combined method missing simplest_alternative & ablation_evidence + problem inflation
        bad_ledger = copy.deepcopy(self.data)
        bad_ledger['sources'].append({
            'id': 'E3',
            'type': 'fictional_prior_paper',
            'locator': 'fictional-paper-2, section 2',
            'verified': True,
            'verified_by': 'fictional_author',
            'verified_at': '2026-11-21',
        })
        bad_ledger['methods'][0]['origin'] = 'combined'
        bad_ledger['methods'][0]['source_ids'] = ['E2', 'E3']
        bad_ledger['methods'][0]['components'] = ['BM25', 'Dense', 'CrossEncoder']
        inflated_ms = (
            "## Abstract\n"
            "Existing single-stage retrievers face a catastrophic bottleneck; we combine three modules for 0.71 nDCG.\n"
            "## Results\n"
            "Table reports 0.71.\n"
        )
        res_bad = module.check(bad_ledger, manuscript_text=inflated_ms)
        self.assertIn('missing_simplest_alternative:M1', res_bad['issues'])
        self.assertIn('missing_component_ablation:M1', res_bad['issues'])
        self.assertIn('problem_inflation_detected:manuscript', res_bad['issues'])

        # Negative 2: Simpler alternative achieves equal or better quality -> overcomplicated_method
        bad_ledger['methods'][0]['parsimony_audit'] = {
            'simplest_alternative': 'Tuned BM25',
            'ablation_evidence': 'Tuned BM25 achieves 0.72 vs 0.71 for 3-stage pipeline.',
            'simpler_equal_or_better': True,
        }
        res_over = module.check(bad_ledger)
        self.assertIn('overcomplicated_method:M1', res_over['issues'])

        # Positive: Minimal justified multi-component ledger + plain prose passes cleanly
        good_ledger = copy.deepcopy(bad_ledger)
        good_ledger['methods'][0]['parsimony_audit'] = {
            'simplest_alternative': 'Tuned BM25 alone (0.64 nDCG)',
            'ablation_evidence': 'Adding CrossEncoder raises nDCG from 0.64 to 0.71 (+0.07) across 5 seeds; removing Dense drops 0.04.',
            'simpler_equal_or_better': False,
        }
        plain_ms = (
            "## Abstract\n"
            "Combining BM25 with CrossEncoder reranking yields 0.71 nDCG compared to 0.64 for BM25 alone.\n"
            "## Results\n"
            "Table reports 0.71 and 0.64.\n"
        )
        good_ledger['numeric_facts'].append({
            'id': 'N2',
            'occurrences': [{'location': 'abstract', 'value': 0.64, 'unit': 'nDCG'}],
        })
        res_good = module.check(good_ledger, manuscript_text=plain_ms)
        self.assertEqual(res_good['status'], 'structure_passed', res_good['issues'])

    def test_catastrophic_forgetting_exempt_extraneous_side_claims_and_compact_cli(self):
        # 1. Domain term "catastrophic forgetting" must NOT trigger problem_inflation_detected
        cl_ledger = copy.deepcopy(self.data)
        cl_ms = (
            "## Abstract\n"
            "Sequential fine-tuning suffers catastrophic forgetting on task 3 with 0.71 fictional score.\n"
            "## Results\n"
            "Table reports 0.71 fictional score.\n"
        )
        res_cl = module.check(cl_ledger, manuscript_text=cl_ms)
        self.assertNotIn('problem_inflation_detected:manuscript', res_cl['issues'])
        self.assertEqual(res_cl['status'], 'structure_passed', res_cl['issues'])

        # 2. Extraneous/unsupported side claims, missing RQ links, multi_component & padding checks
        bad = copy.deepcopy(self.data)
        bad['rqs'] = [{'id': 'RQ1', 'text': 'Does input transformation improve score?'}]
        bad['claims'][0]['rq_id'] = 'RQ1'
        bad['claims'].append({
            'id': 'C2',
            'kind': 'reported',
            'material': False,
            'source_ids': [],
            'text': 'Our method also lowers datacenter energy draw.',
            'scope_relevance': 'extraneous',
        })
        bad['claims'].append({
            'id': 'C3',
            'kind': 'inferred',
            'material': True,
            'source_ids': ['E1'],
            'rq_id': 'RQ99',
            'evidence_ids': ['E404'],
        })
        bad['methods'][0]['multi_component'] = True
        bad['methods'][0]['complexity_justified'] = False
        bad_ms = (
            "## Abstract\n"
            "In today's rapidly evolving world, this renders all prior work obsolete while yielding 0.71 fictional score. "
            "Our method also lowers datacenter energy draw.\n"
            "## Results\n"
            "Table reports 0.71 fictional score.\n"
        )
        res_bad = module.check(bad, manuscript_text=bad_ms)
        self.assertIn('extraneous_claim:C2', res_bad['issues'])
        self.assertIn('unsupported_side_claim:C2', res_bad['issues'])
        self.assertIn('unknown_claim_rq:C3:RQ99', res_bad['issues'])
        self.assertIn('unknown_evidence:C3:E404', res_bad['issues'])
        self.assertIn('missing_simplest_alternative:M1', res_bad['issues'])
        self.assertIn('missing_component_ablation:M1', res_bad['issues'])
        self.assertIn('overcomplicated_method:M1', res_bad['issues'])
        self.assertIn('problem_inflation_detected:manuscript', res_bad['issues'])
        self.assertIn('extraneous_padding_detected:manuscript', res_bad['issues'])

        # 3. Positive case with declared rqs, rq_id, evidence_ids + --compact CLI
        good = copy.deepcopy(self.data)
        good['rqs'] = ['RQ1']
        good['claims'][0]['rq_id'] = 'RQ1'
        good['claims'][0]['evidence_ids'] = ['E1', 'N1']
        self.assertEqual(module.check(good)['status'], 'structure_passed')

        with tempfile.TemporaryDirectory() as tmpdir:
            td = Path(tmpdir)
            bad_p = td / 'bad.json'
            good_p = td / 'good.json'
            bad_p.write_text(json.dumps(bad), encoding='utf-8')
            good_p.write_text(json.dumps(good), encoding='utf-8')
            cmp_bad = run_cli('--ledger', str(bad_p), '--compact')
            self.assertEqual(cmp_bad.returncode, 1)
            cmp_data = json.loads(cmp_bad.stdout)
            self.assertTrue(cmp_data['compact'])
            self.assertEqual(cmp_data['status'], 'structural_issues')
            self.assertGreaterEqual(cmp_data['total_issues'], 6)

            cmp_good = run_cli('--ledger', str(good_p), '--compact')
            self.assertEqual(cmp_good.returncode, 0, cmp_good.stdout)
            self.assertTrue(json.loads(cmp_good.stdout)['compact'])

    def test_cited_standard_baselines_not_flagged_and_mixed_coined_still_caught(self):
        ledger = copy.deepcopy(self.data)
        ledger['numeric_facts'] = [
            {'id': 'N1', 'occurrences': [{'location': 'results', 'value': '14.2%', 'unit': '%'}]}
        ]
        # Positive: cited & baseline-clause standard architectures must pass cleanly
        clean_ms = (
            "We compare against BERT (Devlin et al., 2019), ResNet (He et al., 2016), "
            "and GraphNet (Kipf & Welling, 2017).\n"
            "In our experiments, BERT and ResNet serve as standard baselines.\n"
            "We compare our approach against GraphNet~\\cite{kipf2017} and ResNet~\\cite{he2016}.\n"
            "Our pipeline achieves 14.2% recall gain.\n"
        )
        res_clean = module.check(ledger, manuscript_text=clean_ms)
        self.assertEqual(res_clean['status'], 'structure_passed', res_clean)

        # Negative: genuinely coined branding in same sentence as standard baseline must still flag coined only
        mixed_ms = "We propose HyperFusionNet and compare against ResNet~\\cite{he2016} with 14.2% recall gain.\n"
        res_mixed = module.check(ledger, manuscript_text=mixed_ms)
        self.assertIn('inflated_method_name:M1', res_mixed['issues'])
        self.assertIn('HyperFusionNet', [f['match'] for f in res_mixed['grandiose_findings']])
        self.assertNotIn('ResNet', [f['match'] for f in res_mixed['grandiose_findings']])

    def test_symlink_outside_root_and_short_locator_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            td = Path(tmpdir)
            outside = td / 'outside_secret.txt'
            outside.write_text('SECRET OUTSIDE QUOTE SHOULD NOT BE ACCESSIBLE\n', encoding='utf-8')
            sdir = td / 'sources'
            sdir.mkdir()
            (sdir / 'real.txt').write_text('alpha beta gamma delta\n', encoding='utf-8')
            (sdir / 'link_outside.txt').symlink_to(outside)

            # Symlink escape via quote/text locator omitting filename
            sym_ledger = {
                'sources': [{
                    'id': 'S1',
                    'type': 'paper',
                    'locator': 'SECRET OUTSIDE QUOTE',
                    'quote': 'SECRET OUTSIDE QUOTE SHOULD NOT BE ACCESSIBLE',
                    'verified': True,
                    'verified_by': 'author',
                    'verified_at': '2026-11-21',
                }],
                'claims': [{'id': 'C1', 'kind': 'reported', 'material': True, 'source_ids': ['S1']}],
                'methods': [],
                'numeric_facts': [],
            }
            res_sym = module.check(sym_ledger, sources_dir=sdir)
            self.assertEqual(res_sym['status'], 'structural_issues')
            self.assertIn('source_unverified_against_sources_dir:S1', res_sym['issues'])
            self.assertIn('source_quote_not_found:S1', res_sym['issues'])

            # Short-string locator (<8 chars) must not confirm arbitrary file
            short_ledger = copy.deepcopy(sym_ledger)
            short_ledger['sources'][0] = {
                'id': 'S1',
                'type': 'paper',
                'locator': 'a',
                'verified': True,
                'verified_by': 'author',
                'verified_at': '2026-11-21',
            }
            res_short = module.check(short_ledger, sources_dir=sdir)
            self.assertIn('source_unverified_against_sources_dir:S1', res_short['issues'])

    def test_latex_textsc_nested_title_intro_verbs_table_caption_and_body_decimals(self):
        # 1. Nested \title{} extraction
        secs = module._extract_sections(r"\title{\textbf{Retrieval Study}: \textsc{HyperPipe}}")
        self.assertEqual(secs['title'], 'Retrieval Study: HyperPipe')

        # 2. \textsc{OMNIGRAPH}:, \textsc{Atlas}:, and "We combine ... into OmniGraph"
        for bad_tex in (
            r"We evaluate \textsc{OMNIGRAPH}: A Modular Pipeline on standard benchmarks with 0.71 score.",
            r"We introduce \textsc{Atlas}: A Modular Retrieval Pipeline with 0.71 score.",
            r"We combine BM25 and Dense into OmniGraph and report 0.71 score.",
        ):
            ledger = copy.deepcopy(self.data)
            ledger['methods'][0]['origin'] = 'combined'
            res = module.check(ledger, manuscript_text=bad_tex)
            self.assertIn('inflated_method_name:M1', res['issues'], bad_tex)
            self.assertIn('grandiose_branding_detected:M1', res['issues'], bad_tex)

        # 3. Nested \begin{table}\begin{tabular}...\end{tabular}\caption{...}\end{table} preserves caption
        tbl_ledger = copy.deepcopy(self.data)
        tbl_ledger['numeric_facts'] = [
            {'id': 'F2', 'occurrences': [{'location': 'table 1', 'value': 0.85, 'unit': 'score'}]}
        ]
        tbl_tex = (
            "\\begin{table}\n"
            "\\begin{tabular}{cc}A & B \\\\ 1 & 2\\end{tabular}\n"
            "\\caption{Summary with score 0.85.}\n"
            "\\end{table}\n"
        )
        res_tbl = module.check(tbl_ledger, manuscript_text=tbl_tex)
        self.assertEqual(res_tbl['status'], 'structure_passed', res_tbl['issues'])

        # 4. Standalone body decimals ($0.88$) caught, duplicate 91.7 / 91.7% avoided, Section/Year excluded
        body_tex = (
            "In Section 2.1 and Eq. (3.4) from 2024, our pipeline achieves 0.71 score, "
            "obtains $0.88$ on MMLU, and reaches accuracy of 91.7%."
        )
        res_body = module.check(self.data, manuscript_text=body_tex)
        self.assertIn('undeclared_manuscript_numeric_claim:0.88', res_body['issues'])
        self.assertIn('undeclared_manuscript_numeric_claim:91.7%', res_body['issues'])
        self.assertNotIn('undeclared_manuscript_numeric_claim:91.7', res_body['issues'])
        self.assertNotIn('undeclared_manuscript_numeric_claim:2.1', res_body['issues'])
        self.assertNotIn('undeclared_manuscript_numeric_claim:3.4', res_body['issues'])

    def test_f19_parsimony_top_level_reused_partial_and_none_coercion(self):
        # 1. Top-level simpler_equal_or_better=True triggers overcomplicated_method
        d1 = copy.deepcopy(self.data)
        d1['methods'][0].update({
            'components': ['BM25', 'Dense', 'Reranker'],
            'simplest_alternative': 'BM25 alone',
            'ablation_evidence': 'Ablation table.',
            'simpler_equal_or_better': True,
        })
        self.assertIn('overcomplicated_method:M1', module.check(d1)['issues'])

        # 2. origin='reused' with components & parsimony_audit.simpler_equal_or_better=True still enforced
        d2 = copy.deepcopy(self.data)
        d2['methods'][0].update({
            'origin': 'reused',
            'components': ['BM25', 'Dense', 'Reranker'],
            'parsimony_audit': {'simpler_equal_or_better': True},
        })
        res2 = module.check(d2)['issues']
        self.assertIn('overcomplicated_method:M1', res2)
        self.assertIn('missing_simplest_alternative:M1', res2)
        self.assertIn('missing_component_ablation:M1', res2)

        # 3. Partial component_justifications (1 of 3 components) fails
        d3 = copy.deepcopy(self.data)
        d3['methods'][0].update({
            'components': ['BM25', 'Dense', 'Reranker'],
            'simplest_alternative': 'BM25 alone',
            'component_justifications': {'BM25': 'lexical recall'},
        })
        self.assertIn('missing_component_ablation:M1', module.check(d3)['issues'])

        # 4. None / empty container values in component_justifications must NOT pass via str(v) coercion
        for bad_val in (None, {}, []):
            d4 = copy.deepcopy(self.data)
            d4['methods'][0].update({
                'components': ['BM25', 'Dense'],
                'simplest_alternative': 'BM25 alone',
                'component_justifications': {'BM25': 'lexical recall', 'Dense': bad_val},
            })
            self.assertIn('missing_component_ablation:M1', module.check(d4)['issues'])

    def test_extract_pdf_blocks_real_pdf_json_mineru_nested_and_sibling_pdf_fallback(self):
        import fitz

        epb_spec = importlib.util.spec_from_file_location(
            'extract_pdf_blocks',
            ROOT / 'research-scientist/scripts/extract_pdf_blocks.py',
        )
        epb = importlib.util.module_from_spec(epb_spec)
        epb_spec.loader.exec_module(epb)

        with tempfile.TemporaryDirectory() as tmpdir:
            td = Path(tmpdir)
            outside = td / 'outside_secret.txt'
            outside.write_text('OUTSIDE SECRET SHOULD NEVER BE READ\n', encoding='utf-8')
            sdir = td / 'sources'
            sdir.mkdir()

            doc = fitz.open()
            p1 = doc.new_page()
            p1.insert_text((72, 72), 'Page one background context on retrieval evaluation.')
            p2 = doc.new_page()
            p2.insert_text((72, 72), 'Page two evidence: latency drops by 35 ms on CPU.')
            pdf_path = sdir / 'real_paper.pdf'
            doc.save(str(pdf_path))
            doc.close()

            extracted = epb.extract(pdf_path)
            self.assertEqual(extracted['format'], 'research_scientist_pdf_blocks_v1')
            (sdir / 'real_paper.json').write_text(json.dumps(extracted), encoding='utf-8')

            # Also test native MinerU V2 nested paragraph_content / title_content / table_caption without top-level text
            (sdir / 'mineru_v2_nested.json').write_text(
                json.dumps([[
                    {'type': 'title', 'content': {'title_content': [{'type': 'text', 'content': 'Section 1 Setup'}]}},
                    {'type': 'paragraph', 'content': {'paragraph_content': [{'type': 'text', 'content': 'dense index latency measured on CPU'}]}},
                ]]),
                encoding='utf-8',
            )

            # Positive 1: real_paper.json, page 2
            # Positive 2: real_paper.pdf, page 2 mapped cleanly to sibling real_paper.json
            for loc in ('real_paper.json, page 2', 'real_paper.pdf, page 2'):
                led = {
                    'sources': [{
                        'id': 'S1',
                        'type': 'paper',
                        'locator': loc,
                        'quote': 'latency drops by 35 ms on CPU',
                        'verified': True,
                        'verified_by': 'author',
                        'verified_at': '2026-11-21',
                    }],
                    'claims': [],
                    'methods': [],
                    'numeric_facts': [],
                }
                res = module.check(led, sources_dir=sdir)
                self.assertEqual(res['status'], 'structure_passed', (loc, res))
                self.assertTrue(res['source_locator_checks'][0]['file_confirmed'])
                self.assertTrue(res['source_locator_checks'][0]['quote_confirmed'])

            # Positive 3: MinerU V2 nested spans
            led_mineru = {
                'sources': [{
                    'id': 'S2',
                    'type': 'paper',
                    'locator': 'mineru_v2_nested.json, page 1',
                    'quote': 'dense index latency measured on CPU',
                    'verified': True,
                    'verified_by': 'author',
                    'verified_at': '2026-11-21',
                }],
                'claims': [],
                'methods': [],
                'numeric_facts': [],
            }
            res_mineru = module.check(led_mineru, sources_dir=sdir)
            self.assertEqual(res_mineru['status'], 'structure_passed', res_mineru)
            self.assertTrue(res_mineru['source_locator_checks'][0]['quote_confirmed'])

            # Negative 1: Wrong page for quote in real_paper.json
            led_mismatch = copy.deepcopy(led)
            led_mismatch['sources'][0]['locator'] = 'real_paper.json, page 1'
            res_mismatch = module.check(led_mismatch, sources_dir=sdir)
            self.assertIn('source_quote_page_mismatch:S1', res_mismatch['issues'])

            # Negative 2: Non-existent page 9
            led_missing_pg = copy.deepcopy(led)
            led_missing_pg['sources'][0]['locator'] = 'real_paper.pdf, page 9'
            res_missing_pg = module.check(led_missing_pg, sources_dir=sdir)
            self.assertIn('source_locator_page_missing:S1', res_missing_pg['issues'])

            # Negative 3: Symlinked .pdf escaping root must still be blocked even if sibling .json exists
            (sdir / 'escaped.json').write_text(
                json.dumps({'format': 'research_scientist_pdf_blocks_v1', 'pages': [[{'page_idx': 0, 'text': 'IN ROOT'}]]}),
                encoding='utf-8',
            )
            (sdir / 'escaped.pdf').symlink_to(outside)
            led_sym = {
                'sources': [{
                    'id': 'S3',
                    'type': 'paper',
                    'locator': 'escaped.pdf, page 1',
                    'quote': 'OUTSIDE SECRET SHOULD NEVER BE READ',
                    'verified': True,
                    'verified_by': 'author',
                    'verified_at': '2026-11-21',
                }],
                'claims': [],
                'methods': [],
                'numeric_facts': [],
            }
            self.assertIn('invalid_source_path:S3', module.check(led_sym, sources_dir=sdir)['issues'])

    def test_mixed_baseline_with_own_coined_brand_and_long_acronym_and_abstract_version_scrub(self):
        # Negative: mixed cited/standard baseline + coined own-brand in same sentence (>40 chars or "our approach/pipeline")
        mixed_cases = [
            "Compared against standard baselines, our pipeline HyperFusionNet achieves 0.71 score.",
            "We compare against ResNet~\\cite{he2016} using our pipeline HyperFusionNet with 0.71 score.",
            "Standard baselines are weak, so we propose a three-stage multi-hop retrieval pipeline HyperFusionNet with 0.71 score.",
            "Unlike prior baselines such as ResNet~\\cite{he2016}, we propose in Section 3 a lightweight pipeline called OmniGraph that achieves 0.71 score.",
            "Comparing against standard baselines like ResNet~\\cite{he2016}, our approach HyperFusionNet achieves 0.71 score.",
            "We introduce \\textsc{HYPERRETRIEVER}: A Modular Pipeline with 0.71 score.",
        ]
        for ms in mixed_cases:
            d = copy.deepcopy(self.data)
            d['methods'][0]['origin'] = 'combined'
            res = module.check(d, manuscript_text=ms)
            self.assertIn('inflated_method_name:M1', res['issues'], (ms, res))

        # Positive: legitimate cited standard baselines & PyTorch 2.1 in abstract pass cleanly
        clean_tex = (
            "\\begin{abstract}\n"
            "Using PyTorch 2.1, we compare our approach against GraphNet~\\cite{kipf2017} and ResNet~\\cite{he2016} "
            "and obtain 0.71 score.\n"
            "\\end{abstract}\n"
        )
        res_clean = module.check(copy.deepcopy(self.data), manuscript_text=clean_tex)
        self.assertEqual(res_clean['status'], 'structure_passed', res_clean)

    def test_iteration4_own_brand_passive_appositive_parenthetical_and_bare_our(self):
        negatives = [
            # 2c: passive own-work verb after brand
            (
                r"Compared against standard baselines like ResNet~\cite{he2016}, "
                r"HyperFusionNet is proposed as a lightweight pipeline achieving 14.2\% recall gain.",
                '14.2%',
                '%',
            ),
            # 2d: pre-brand appositive NP + post-brand passive
            (
                r"Compared against prior baselines such as ResNet~\cite{he2016}, a lightweight pipeline, "
                r"HyperFusionNet, is introduced in Section 3 with 14.2\% recall gain.",
                '14.2%',
                '%',
            ),
            # 2e: post-brand parenthetical own-work appositive
            (
                r"Compared against standard baselines, HyperFusionNet (our lightweight pipeline) "
                r"achieves 14.2\% recall gain.",
                '14.2%',
                '%',
            ),
            # 2f: ", and evaluate" + post-brand appositive
            (
                r"We compare against prior work such as GraphNet~\cite{kipf2017}, and evaluate "
                r"HyperFusionNet, our combined retriever, with 14.2\% recall gain.",
                '14.2%',
                '%',
            ),
            # Parenthetical contrastive baseline between verb and coined brand
            (
                "We combine BM25 and Dense, unlike standard baselines, into OmniGraph achieving 0.71 score.",
                0.71,
                'score',
            ),
            (
                "We propose, unlike existing baselines, HyperFusionNet achieving 0.71 score.",
                0.71,
                'score',
            ),
            # Bare "our <Brand>"
            (
                "Compared against standard baselines, our HyperFusionNet achieves 0.71 score.",
                0.71,
                'score',
            ),
            (
                "Our HyperFusionNet achieves 0.71 score.",
                0.71,
                'score',
            ),
        ]
        for ms, val, unit in negatives:
            d = copy.deepcopy(self.data)
            d['methods'][0]['origin'] = 'combined'
            d['numeric_facts'] = [{'id': 'N1', 'occurrences': [{'location': 'results', 'value': val, 'unit': unit}]}]
            res = module.check(d, manuscript_text=ms)
            self.assertIn('inflated_method_name:M1', res['issues'], (ms, res))
            self.assertIn('grandiose_branding_detected:M1', res['issues'], (ms, res))

    def test_iteration4_legitimate_baselines_and_selective_mixed_positive_controls(self):
        positives = [
            (
                r"We compare our approach against GraphNet~\cite{kipf2017} and ResNet~\cite{he2016} with 14.2% recall gain.",
                '14.2%',
                '%',
            ),
            (
                "We propose a simple linear probe with 0.71 score. Both OmniRetriever and HyperEmbedder serve as standard baselines.",
                0.71,
                'score',
            ),
            (
                "Compared against OmniRetriever and HyperEmbedder, our simple linear probe achieves 0.71 score.",
                0.71,
                'score',
            ),
            (
                "We compare our approach against OmniRetriever and HyperEmbedder with 0.71 score.",
                0.71,
                'score',
            ),
        ]
        for ms, val, unit in positives:
            d = copy.deepcopy(self.data)
            d['numeric_facts'] = [{'id': 'N1', 'occurrences': [{'location': 'results', 'value': val, 'unit': unit}]}]
            res = module.check(d, manuscript_text=ms)
            self.assertEqual(res['status'], 'structure_passed', (ms, res))
            self.assertEqual(res['grandiose_findings'], [], (ms, res))

        # Mixed selective flagging: flags HyperFusionNet ONLY, NOT OmniRetriever or HyperEmbedder
        mixed = "We compare our pipeline HyperFusionNet against OmniRetriever and HyperEmbedder with 0.71 score."
        d_mix = copy.deepcopy(self.data)
        d_mix['methods'][0]['origin'] = 'combined'
        res_mix = module.check(d_mix, manuscript_text=mixed)
        matches = [f['match'] for f in res_mix['grandiose_findings']]
        self.assertIn('HyperFusionNet', matches)
        self.assertNotIn('OmniRetriever', matches)
        self.assertNotIn('HyperEmbedder', matches)

    def test_iteration4_lowercase_colon_subtitle_refs_split_tex_fragment_hybrid_and_null_blocks(self):
        # 2h: lowercase colon subtitle negative
        d_2h = copy.deepcopy(self.data)
        d_2h['methods'][0]['origin'] = 'combined'
        d_2h['numeric_facts'] = [{'id': 'N1', 'occurrences': [{'location': 'results', 'value': '14.2%', 'unit': '%'}]}]
        res_2h = module.check(
            d_2h,
            manuscript_text=r"HYPERRETRIEVER: a modular retrieval pipeline. We propose this system with 14.2\% recall gain.",
        )
        self.assertIn('inflated_method_name:M1', res_2h['issues'])

        # Colon label positive controls
        for clean_colon in (
            "NOTE: a summary of the baseline pipeline with 0.71 score.",
            "BEIR: a retrieval benchmark yielding 0.71 score.",
        ):
            res_cc = module.check(copy.deepcopy(self.data), manuscript_text=clean_colon)
            self.assertEqual(res_cc['status'], 'structure_passed', (clean_colon, res_cc))
            self.assertEqual(res_cc['grandiose_findings'], [])

        # 9A: References split on raw text before normalization
        tex_refs = (
            "\\begin{abstract}\n"
            "Our method yields 0.71 score.\n"
            "\\end{abstract}\n"
            "\\section{References}\n"
            "[1] Smith et al. Achieving 95\\% accuracy in 2024.\n"
        )
        res_9a = module.check(copy.deepcopy(self.data), manuscript_text=tex_refs)
        self.assertEqual(res_9a['status'], 'structure_passed', res_9a)

        # 9B: Pure LaTeX text macros trigger TeX comment stripping
        tex_frag = "\\emph{We test} \\textsc{BERT}. % accuracy 99.9 and 0.99\nWe achieve 0.71 score.\n"
        res_9b = module.check(copy.deepcopy(self.data), manuscript_text=tex_frag)
        self.assertEqual(res_9b['status'], 'structure_passed', res_9b)

        # Hybrid \cite + unescaped 14.2% preserves 14.2%
        d_hyb = copy.deepcopy(self.data)
        d_hyb['methods'][0]['origin'] = 'combined'
        d_hyb['numeric_facts'] = [{'id': 'N1', 'occurrences': [{'location': 'results', 'value': '14.2%', 'unit': '%'}]}]
        res_hyb = module.check(
            d_hyb,
            manuscript_text="We propose HyperFusionNet and compare against ResNet~\\cite{he2016} with 14.2% recall gain.\n",
        )
        self.assertNotIn('manuscript_numeric_fact_missing:N1:results', res_hyb['issues'])
        self.assertIn('inflated_method_name:M1', res_hyb['issues'])

        # Null "blocks" in research_scientist_pdf_blocks_v1 JSON
        with tempfile.TemporaryDirectory() as tmpdir:
            sdir = Path(tmpdir)
            (sdir / 'null_blocks.json').write_text(
                json.dumps({
                    'format': 'research_scientist_pdf_blocks_v1',
                    'pages': [[{'page_idx': 0, 'text': 'Verified retrieval latency quote on page one.'}]],
                    'blocks': None,
                }),
                encoding='utf-8',
            )
            led_nb = {
                'sources': [{
                    'id': 'S1',
                    'type': 'paper',
                    'locator': 'null_blocks.json, page 1',
                    'quote': 'Verified retrieval latency quote on page one.',
                    'verified': True,
                    'verified_by': 'author',
                    'verified_at': '2026-11-21',
                }],
                'claims': [],
                'methods': [],
                'numeric_facts': [],
            }
            res_nb = module.check(led_nb, sources_dir=sdir)
            self.assertEqual(res_nb['status'], 'structure_passed', res_nb)
            self.assertTrue(res_nb['source_locator_checks'][0]['quote_confirmed'])

    def test_iteration5_modifier_nouns_paren_cite_long_compare_eval_title_and_tex_edges(self):
        # 1. Defect 2 + Auditor minor: selective own-brand flagging with domain modifiers/nouns & long compare...with
        selective_cases = [
            "We compare our retrieval pipeline HyperFusionNet against OmniRetriever and HyperEmbedder achieving 0.71 score.",
            "We compare our graph model HyperFusionNet against OmniRetriever and HyperEmbedder achieving 0.71 score.",
            "We compare our lightweight three-stage multi-hop retrieval pipeline, called HyperFusionNet, with OmniRetriever and HyperEmbedder achieving 0.71 score.",
            "We compare our lightweight three-stage multi-hop retrieval pipeline HyperFusionNet against OmniRetriever and HyperEmbedder achieving 0.71 score.",
        ]
        for ms in selective_cases:
            d = copy.deepcopy(self.data)
            d['methods'][0]['origin'] = 'combined'
            res = module.check(d, manuscript_text=ms)
            self.assertIn('inflated_method_name:M1', res['issues'], (ms, res))
            matches = {f['match'] for f in res['grandiose_findings']}
            self.assertEqual(matches, {'HyperFusionNet'}, (ms, matches, res))

        # 2. ADV_A1 (parenthetical year-cite contrast), ADV_A3/A3b, compact router, ADV_A4 (lowercase colon no article)
        flagged_cases = [
            ("We combine BM25 and Dense, unlike ResNet (2016), into OmniGraph achieving 0.71 score.", "OmniGraph"),
            ("The proposed HyperFusionNet achieves 0.71 score.", "HyperFusionNet"),
            ("Our paper proposes HyperFusionNet achieving 0.71 score.", "HyperFusionNet"),
            ("MetaFlow (our compact router) achieves 0.71 score.", "MetaFlow"),
            ("HYPERRETRIEVER: modular retrieval pipeline. We propose this system with 0.71 score.", "HYPERRETRIEVER: modular retrieval pipeline"),
            ("\\title{\\textbf{Retrieval Study}: \\textsc{HyperPipe}}\nWe achieve 0.71 score.", "HyperPipe"),
        ]
        for ms, expected_tok in flagged_cases:
            d = copy.deepcopy(self.data)
            d['methods'][0]['origin'] = 'combined'
            res = module.check(d, manuscript_text=ms)
            self.assertIn('inflated_method_name:M1', res['issues'], (ms, res))
            self.assertTrue(
                any(expected_tok in f['match'] for f in res['grandiose_findings']),
                (ms, expected_tok, res['grandiose_findings']),
            )

        # 3. ADV_A5 (.% TeX comment fragment) + clean negative controls (baseline modifiers, eval title, non-own verbs)
        clean_cases = [
            "We compare our baseline OmniRetriever against HyperEmbedder achieving 0.71 score.",
            "# Evaluating HyperEmbedder on Dense Retrieval\n\nCompared against HyperEmbedder, our simple linear probe achieves 0.71 score.",
            "# Evaluating HyperEmbedder on Dense Retrieval\n\nWe benchmark HyperEmbedder across 5 datasets achieving 0.71 score.",
            "Our 3-layer encoder outperforms HyperEmbedder achieving 0.71 score.",
            "The proposed method outperforms HyperEmbedder achieving 0.71 score.",
            "HYPERRETRIEVER: baseline retrieval pipeline yielding 0.71 score.",
            "NOTE: modular retrieval pipeline yielding 0.71 score.",
            "We follow Smith~\\cite{a}.% 99.9\nWe achieve 0.71 score.\n",
        ]
        for ms in clean_cases:
            res = module.check(copy.deepcopy(self.data), manuscript_text=ms)
            self.assertEqual(res['status'], 'structure_passed', (ms, res))
            self.assertEqual(res['grandiose_findings'], [], (ms, res))

    def test_iteration6_baseline_descriptive_nps_appositives_acronyms_passive_clauses_and_f19_placeholders(self):
        # 1. Clean baselines preceded by descriptive NPs or carrying non-own appositives + standard AI/CS colons
        clean_cases = [
            ("We compare our approach against a strong neural retriever HyperEmbedder achieving 0.71 score.", 0.71),
            ("We compare our approach against a strong neural model HyperEmbedder achieving 0.71 score.", 0.71),
            ("Compared to a recent dense retriever OmniRetriever, our simple linear probe achieves 0.71 score.", 0.71),
            ("OmniRetriever, a dense retrieval model, achieves 0.65 score on BEIR.", 0.65),
            ("HyperEmbedder (a two-tower graph encoder) achieves 0.65 score on BEIR.", 0.65),
            ("We compare against HyperEmbedder (a dense retriever) and OmniRetriever (a sparse model) achieving 0.71 score.", 0.71),
            ("HyperEmbedder, a dense retriever, serves as a standard baseline. Our linear probe achieves 0.71 score.", 0.71),
            ("COCO: Common Objects in Context evaluates object detection achieving 0.71 score.", 0.71),
            ("FEVER: Fact Extraction and Verification tests claim checking achieving 0.71 score.", 0.71),
            ("ADAMW: Decoupled Weight Decay Regularization trains the probe achieving 0.71 score.", 0.71),
            ("VIT: Vision Transformer Baseline achieves 0.71 score.", 0.71),
            ("UNSEENDS: Multi-Hop Claim Dataset tests retrieval achieving 0.71 score.", 0.71),
        ]
        for ms, val in clean_cases:
            d = copy.deepcopy(self.data)
            d['numeric_facts'][0]['occurrences'] = [{'location': 'results', 'value': val, 'unit': 'score'}]
            res = module.check(d, manuscript_text=ms)
            self.assertEqual(res['status'], 'structure_passed', (ms, res))
            self.assertEqual(res['grandiose_findings'], [], (ms, res))

        # 2. Coined own-brand evasions (expanded AI/CS head nouns, participial passive clauses, stack verb, coined colon headers/intros)
        bad_cases = [
            ("Our dense reranker HyperFusionNet achieves 0.71 score.", "HyperFusionNet"),
            ("We compare our dense reranker HyperFusionNet against OmniRetriever achieving 0.71 score.", "HyperFusionNet"),
            ("Our neural predictor HyperFusionNet achieves 0.71 score.", "HyperFusionNet"),
            ("Our lightweight adapter HyperFusionNet achieves 0.71 score.", "HyperFusionNet"),
            ("Our verification agent HyperFusionNet achieves 0.71 score.", "HyperFusionNet"),
            ("Our learned classifier HyperFusionNet achieves 0.71 score.", "HyperFusionNet"),
            ("HyperFusionNet, combining BM25 and DPR (2020), is introduced in Sec. 3 achieving 0.71 score.", "HyperFusionNet"),
            ("HyperFusionNet, combining BM25 and Dense, is proposed in Sec. 3 achieving 0.71 score.", "HyperFusionNet"),
            ("HyperFusionNet, built on RoBERTa, is introduced in Sec. 3 achieving 0.71 score.", "HyperFusionNet"),
            ("HyperFusionNet, a lightweight retriever, is proposed in Sec. 3 achieving 0.71 score.", "HyperFusionNet"),
            ("We propose HyperFusionNet, a lightweight retriever, achieving 0.71 score.", "HyperFusionNet"),
            ("We stack adapters, compared against DenseNet (2017), into VortexNet achieving 0.71 score.", "VortexNet"),
            ("We introduce APEX: Adaptive Policy Exploration achieving 0.71 score.", "APEX: Adaptive Policy Exploration"),
            ("# APEX: Adaptive Policy Exploration\n\nWe evaluate on BEIR achieving 0.71 score.", "APEX: Adaptive Policy Exploration"),
            ("NEUROCASCADE: a sparse routing architecture achieving 0.71 score.", "NEUROCASCADE: a sparse routing architecture"),
        ]
        for ms, expected_tok in bad_cases:
            d = copy.deepcopy(self.data)
            d['methods'][0]['origin'] = 'combined'
            res = module.check(d, manuscript_text=ms)
            self.assertIn('inflated_method_name:M1', res['issues'], (ms, res))
            matches = {f['match'] for f in res['grandiose_findings']}
            self.assertTrue(any(expected_tok in m for m in matches), (ms, expected_tok, matches))
            self.assertNotIn('OmniRetriever', matches, (ms, matches))

        # 3. F19 placeholder rejection & string boolean coercion
        for bad_alt in ('N/A', 'none', 'TBD', '-'):
            d_ph = copy.deepcopy(self.data)
            d_ph['methods'][0].update({
                'components': ['BM25', 'Dense'],
                'simplest_alternative': bad_alt,
                'ablation_evidence': 'N/A',
                'simpler_equal_or_better': 'true',
            })
            issues_ph = module.check(d_ph)['issues']
            self.assertIn('missing_simplest_alternative:M1', issues_ph, bad_alt)
            self.assertIn('missing_component_ablation:M1', issues_ph, bad_alt)
            self.assertIn('overcomplicated_method:M1', issues_ph, bad_alt)

    def test_iteration7_evasions_acronyms_numeric_compare_with_and_f19_placeholders(self):
        # 1. Negative controls: multi-comma passive clauses, participial active, parenthetical NP,
        # own-work prep/copular/verb/section framing
        evasion_cases = [
            ("HyperFusionNet, combining BM25, DPR, and ColBERT, is proposed in Sec. 3 achieving 0.71 score.", "HyperFusionNet"),
            ("HyperFusionNet, a lightweight, modular retriever, is proposed in Sec. 3 achieving 0.71 score.", "HyperFusionNet"),
            ("HyperFusionNet, which combines BM25, DPR, and ColBERT, is proposed in Sec. 3 achieving 0.71 score.", "HyperFusionNet"),
            ("HyperFusionNet, combining BM25 and Dense, achieves 0.71 score.", "HyperFusionNet"),
            ("Our hybrid pipeline (HyperFusionNet) achieves 0.71 score.", "HyperFusionNet"),
            ("The proposed pipeline (HyperFusionNet) achieves 0.71 score.", "HyperFusionNet"),
            ("This combined framework (HyperFusionNet) achieves 0.71 score.", "HyperFusionNet"),
            ("In our work, HyperFusionNet achieves 0.71 score.", "HyperFusionNet"),
            ("In our paper, HyperFusionNet achieves 0.71 score.", "HyperFusionNet"),
            ("Our newly proposed HyperFusionNet achieves 0.71 score.", "HyperFusionNet"),
            ("HyperFusionNet acts as our dense reranker achieving 0.71 score.", "HyperFusionNet"),
            ("We fuse BM25 and Dense into VortexNet achieving 0.71 score.", "VortexNet"),
            ("We unify BM25 and Dense into VortexNet achieving 0.71 score.", "VortexNet"),
            ("We chain BM25 and Dense into VortexNet achieving 0.71 score.", "VortexNet"),
            ("# Clean Paper Title\n\n## 3. APEX: Adaptive Precision Execution\n\nWe combine quantization and pruning achieving 0.71 score.", "APEX: Adaptive Precision Execution"),
            ("\\section*{3. APEX: Adaptive Precision Execution}\n\nWe combine quantization and pruning achieving 0.71 score.", "APEX: Adaptive Precision Execution"),
        ]
        for ms, expected_tok in evasion_cases:
            d = copy.deepcopy(self.data)
            d['methods'][0]['origin'] = 'combined'
            d['methods'][0]['exact_change'] = 'changed loss'
            res = module.check(d, manuscript_text=ms)
            self.assertEqual(res['status'], 'structural_issues', (ms, res))
            self.assertIn('inflated_method_name:M1', res['issues'], (ms, res))
            self.assertIn('grandiose_branding_detected:M1', res['issues'], (ms, res))
            matches = {f['match'] for f in res['grandiose_findings']}
            self.assertTrue(any(expected_tok in m for m in matches), (ms, expected_tok, matches))

        # 2. Positive controls (origin="reused"): standard AI/CS acronym definitions, headings,
        # numeric-cited compare...with & evaluate...with lists, and In our work baseline
        clean_cases = [
            "VLM: Vision Language Model achieves 0.71 score.",
            "SSM: State Space Model achieves 0.71 score.",
            "KAN: Kolmogorov-Arnold Network achieves 0.71 score.",
            "MOE: Mixture of Experts Architecture achieves 0.71 score.",
            "BGE: BAAI General Embedding Model achieves 0.71 score.",
            "UNSEENARCH: Sparse Mixture Model achieves 0.71 score.",
            "# Clean Paper Title\n\n## 3. COCO: Common Objects in Context\n\nWe achieve 0.71 score.",
            "# Clean Paper Title\n\n## 3. VLM: Vision Language Model\n\nWe achieve 0.71 score.",
            "We propose a linear probe and compare it with HyperEmbedder [1] and OmniRetriever achieving 0.71 score.",
            "We evaluate our linear probe with HyperEmbedder [1] and OmniRetriever achieving 0.71 score.",
            "In our work, HyperEmbedder (2020) serves as a baseline achieving 0.71 score.",
        ]
        for ms in clean_cases:
            d = copy.deepcopy(self.data)
            d['methods'][0]['origin'] = 'reused'
            d['methods'][0].pop('exact_change', None)
            res = module.check(d, manuscript_text=ms)
            self.assertEqual(res['status'], 'structure_passed', (ms, res))
            self.assertEqual(res['issues'], [], (ms, res))
            self.assertEqual(res['grandiose_findings'], [], (ms, res))

        # 3. Selective mixed case: flags HyperFusionNet ONLY, NOT OmniRetriever or HyperEmbedder
        d_mix = copy.deepcopy(self.data)
        d_mix['methods'][0]['origin'] = 'combined'
        mixed_ms = (
            "In our work, we propose our hybrid pipeline (HyperFusionNet) and compare it with "
            "HyperEmbedder [1] and OmniRetriever achieving 0.71 score."
        )
        res_mix = module.check(d_mix, manuscript_text=mixed_ms)
        self.assertIn('inflated_method_name:M1', res_mix['issues'])
        mix_matches = {f['match'] for f in res_mix['grandiose_findings']}
        self.assertEqual(mix_matches, {'HyperFusionNet'}, mix_matches)

        # 4. F19 dotted/qualified placeholder variants
        for bad_alt in ('N.A.', 't.b.d.', 'none yet'):
            d_ph = copy.deepcopy(self.data)
            d_ph['methods'][0].update({
                'components': ['BM25', 'Dense'],
                'simplest_alternative': bad_alt,
                'ablation_evidence': bad_alt,
            })
            issues_ph = module.check(d_ph)['issues']
            self.assertIn('missing_simplest_alternative:M1', issues_ph, bad_alt)
            self.assertIn('missing_component_ablation:M1', issues_ph, bad_alt)

    def test_iteration8_prior_work_acronyms_comparative_verbs_and_own_brand_evasions(self):
        # 1. Clean-baseline positive controls (origin="reused")
        clean_cases = [
            "Existing studies adopt the Group Relative Policy Optimization (GRPO) pipeline as a standard baseline achieving 0.71 score.",
            "Prior work introduces the Group Relative Policy Optimization (GRPO) framework for alignment achieving 0.71 score.",
            "Prior systems rely on the Model Context Protocol (MCP) architecture for tool calling achieving 0.71 score.",
            "Existing studies adopt the Spectral Sparse Attention (SSA) pipeline as a standard baseline achieving 0.71 score.",
            "We propose a linear probe that outperforms HyperEmbedder and OmniRetriever achieving 0.71 score.",
            "We propose a linear probe that surpasses HyperEmbedder and OmniRetriever achieving 0.71 score.",
            "We propose a linear probe that exceeds HyperEmbedder and OmniRetriever achieving 0.71 score.",
            "# Evaluating Open Alignment Methods\n\n## 3. GRPO: Group Relative Policy Optimization\n\nWe evaluate a linear probe achieving 0.71 score.",
            "# Evaluating Open Alignment Methods\n\n## 3. UNSEEN: Unseen Policy Optimization\n\nWe evaluate a linear probe achieving 0.71 score.",
            "# Linear Probing Study\n\n## 3. ColBERT: Late Interaction Retrieval\n\nWe evaluate a linear probe achieving 0.71 score.",
        ]
        for ms in clean_cases:
            d = copy.deepcopy(self.data)
            d['methods'][0]['origin'] = 'reused'
            d['methods'][0].pop('exact_change', None)
            res = module.check(d, manuscript_text=ms)
            self.assertEqual(res['status'], 'structure_passed', (ms, res))
            self.assertEqual(res['issues'], [], (ms, res))
            self.assertEqual(res['grandiose_findings'], [], (ms, res))

        # 2. Negative controls: active relative/paren/built-on clauses, namely/dubbed/denoted,
        # versioned parens, recently introduced/developed, title-cased & paren section headings
        evasion_cases = [
            ("HyperFusionNet, which combines BM25, DPR, and ColBERT, achieves 0.71 score.", "HyperFusionNet"),
            ("HyperFusionNet, which fuses BM25 and Dense, achieves 0.71 score.", "HyperFusionNet"),
            ("HyperFusionNet (combining BM25 and Dense) achieves 0.71 score.", "HyperFusionNet"),
            ("HyperFusionNet, built on BM25 and Dense, achieves 0.71 score.", "HyperFusionNet"),
            ("Our hybrid pipeline, namely HyperFusionNet, achieves 0.71 score.", "HyperFusionNet"),
            ("Our hybrid pipeline, dubbed HyperFusionNet, achieves 0.71 score.", "HyperFusionNet"),
            ("Our hybrid pipeline (HyperFusionNet v2) achieves 0.71 score.", "HyperFusionNet"),
            ("Our method is denoted HyperFusionNet and achieves 0.71 score.", "HyperFusionNet"),
            ("Our recently introduced ZetaFormer achieves 0.71 score.", "ZetaFormer"),
            ("Our recently developed ZetaFormer achieves 0.71 score.", "ZetaFormer"),
            ("# Clean Paper Title\n\n## 3. Vortex: Adaptive Retrieval Model\n\nWe combine BM25 and Dense achieving 0.71 score.", "Vortex: Adaptive Retrieval Model"),
            ("# Clean Paper Title\n\n## 3. Vortex: Adaptive Precision Execution\n\nWe combine quantization and pruning achieving 0.71 score.", "Vortex: Adaptive Precision Execution"),
            ("\\title{Clean Paper Title}\n\\section{Vortex: Adaptive Precision Execution}\n\nWe combine quantization and pruning achieving 0.71 score.", "Vortex: Adaptive Precision Execution"),
            ("# Clean Paper Title\n\n## 3. Adaptive Precision Execution (APEX)\n\nWe combine quantization and pruning achieving 0.71 score.", "Adaptive Precision Execution (APEX)"),
            ("We propose the Adaptive Precision Execution (APEX) framework achieving 0.71 score.", "Adaptive Precision Execution (APEX)"),
            ("# Clean Paper Title\n\n## 3. APEX: Adaptive Precision Execution\n\nWe combine quantization and pruning achieving 0.71 score.", "APEX: Adaptive Precision Execution"),
        ]
        for ms, expected_tok in evasion_cases:
            d = copy.deepcopy(self.data)
            d['methods'][0]['origin'] = 'combined'
            d['methods'][0]['exact_change'] = 'changed loss'
            res = module.check(d, manuscript_text=ms)
            self.assertEqual(res['status'], 'structural_issues', (ms, res))
            self.assertIn('inflated_method_name:M1', res['issues'], (ms, res))
            self.assertIn('grandiose_branding_detected:M1', res['issues'], (ms, res))
            matches = {f['match'] for f in res['grandiose_findings']}
            self.assertTrue(any(expected_tok in m for m in matches), (ms, expected_tok, matches))

        # 3. Selective mixed comparative verb: flags HyperFusionNet ONLY, NOT baselines
        d_mix = copy.deepcopy(self.data)
        d_mix['methods'][0]['origin'] = 'combined'
        d_mix['methods'][0]['exact_change'] = 'changed loss'
        mixed_ms = "We propose HyperFusionNet, which outperforms HyperEmbedder and OmniRetriever achieving 0.71 score."
        res_mix = module.check(d_mix, manuscript_text=mixed_ms)
        self.assertIn('inflated_method_name:M1', res_mix['issues'])
        self.assertEqual({f['match'] for f in res_mix['grandiose_findings']}, {'HyperFusionNet'})

    def test_iteration9_latex_section_labels_clean_baselines_coined_evasions_and_f19_nested(self):
        # 1. Positive controls (origin="reused"): We evaluate, better/higher than, to replace/improve upon/inspired by,
        # cited & comparative prior-work baselines, contrastive parentheticals
        clean_reused = [
            "We evaluate HyperEmbedder on BEIR achieving 0.71 score.",
            "We evaluate HyperEmbedder and OmniRetriever on BEIR achieving 0.71 score.",
            "We evaluate Spectral Sparse Attention (SSA) on LongBench achieving 0.71 score.",
            "We evaluate our linear probe on the Spectral Sparse Attention (SSA) framework achieving 0.71 score.",
            "We propose a linear probe that performs better than HyperEmbedder and OmniRetriever achieving 0.71 score.",
            "We propose a linear probe with higher recall than HyperEmbedder and OmniRetriever achieving 0.71 score.",
            "We propose a simple linear probe to replace the Spectral Sparse Attention (SSA) pipeline achieving 0.71 score.",
            "We propose a simple linear probe to improve upon the Spectral Sparse Attention (SSA) framework achieving 0.71 score.",
            "We design a linear probe inspired by the Spectral Sparse Attention (SSA) architecture achieving 0.71 score.",
            "OmniRetriever combines BM25 and Dense in prior work [ref] achieving 0.71 score.",
            "Unlike OmniRetriever, which combines BM25 and Dense, our linear probe achieves 0.71 score.",
            "Our hybrid pipeline (inspired by HyperEmbedder) achieves 0.71 score.",
            "Our hybrid pipeline (HyperEmbedder baseline) achieves 0.71 score.",
        ]
        for ms in clean_reused:
            d = copy.deepcopy(self.data)
            d['methods'][0]['origin'] = 'reused'
            d['methods'][0].pop('exact_change', None)
            res = module.check(d, manuscript_text=ms)
            self.assertEqual(res['status'], 'structure_passed', (ms, res))
            self.assertEqual(res['grandiose_findings'], [], (ms, res))

        # 2. Positive controls (origin="combined"): generic colon section labels & [ref]/against baseline sections
        clean_combined = [
            "# Improving Dense Retrieval\n\n## 3. Architecture: Transformer Encoder Overview\n\nWe describe the standard transformer backbone achieving 0.71 score.",
            "# Improving Dense Retrieval\n\n## 3. Pipeline: Tokenization and Indexing\n\nWe describe standard preprocessing achieving 0.71 score.",
            "# Improving Dense Retrieval\n\n## 3. Related: Neural Retrieval Models\n\nSeveral retrieval models have been studied achieving 0.71 score.",
            "# Improving Dense Retrieval\n\n## 3. Reproducibility: Seeds and Hardware\n\nWe fix random seeds achieving 0.71 score.",
            "# Improving Dense Retrieval\n\n## 3. UNSEEN: Unseen Policy Optimization\n\nUNSEEN computes group advantages across rollouts [ref] achieving 0.71 score.",
            "# Improving Dense Retrieval\n\n## 3. UNSEEN: Unseen Policy Optimization\n\nWe evaluate our probe against UNSEEN achieving 0.71 score.",
        ]
        for ms in clean_combined:
            d = copy.deepcopy(self.data)
            d['methods'][0]['origin'] = 'combined'
            d['methods'][0]['exact_change'] = 'changed loss'
            res = module.check(d, manuscript_text=ms)
            self.assertEqual(res['status'], 'structure_passed', (ms, res))
            self.assertEqual(res['grandiose_findings'], [], (ms, res))

        # 3. Negative controls: LaTeX \section{...}\label{...}, sentence-final join clauses,
        # copular/active subject join verbs, termed/referred to as/hereafter, (Brand for ...), acronym connectors
        evasion_cases = [
            ("\\title{Clean Paper Title}\n\\section{Vortex: Adaptive Precision Execution}\\label{sec:vortex}\n\nWe combine quantization and pruning achieving 0.71 score.", "Vortex: Adaptive Precision Execution", 0.71),
            ("\\title{Clean Paper Title}\n\\section{Adaptive Precision Execution (APEX)}\\label{sec:apex}\n\nWe combine quantization and pruning achieving 0.71 score.", "Adaptive Precision Execution (APEX)", 0.71),
            ("Evaluations test HyperFusionNet, which combines BM25 and Dense achieving 0.71 score.", "HyperFusionNet", 0.71),
            ("Experiments report results for HyperFusionNet, built on BM25 and Dense.", "HyperFusionNet", None),
            ("HyperFusionNet combines BM25 and Dense achieving 0.71 score.", "HyperFusionNet", 0.71),
            ("HyperFusionNet integrates BM25 and Dense to achieve 0.71 score.", "HyperFusionNet", 0.71),
            ("HyperFusionNet is a retriever that combines BM25 and Dense achieving 0.71 score.", "HyperFusionNet", 0.71),
            ("HyperFusionNet is a hybrid pipeline combining BM25 and Dense achieving 0.71 score.", "HyperFusionNet", 0.71),
            ("Versatile Retrieval Engine (VRE) combines BM25 and Dense in our pipeline, achieving 0.71 score.", "Versatile Retrieval Engine (VRE)", 0.71),
            ("Versatile Retrieval Engine (VRE) is a retriever that combines BM25 and Dense achieving 0.71 score.", "Versatile Retrieval Engine (VRE)", 0.71),
            ("We build a hybrid retriever (hereafter VRE) combining BM25 and Dense achieving 0.71 score.", "VRE", 0.71),
            ("Our hybrid pipeline, termed HyperFusionNet, achieves 0.71 score.", "HyperFusionNet", 0.71),
            ("Our hybrid pipeline, referred to as HyperFusionNet, achieves 0.71 score.", "HyperFusionNet", 0.71),
            ("Our method is termed HyperFusionNet and achieves 0.71 score.", "HyperFusionNet", 0.71),
            ("Our hybrid pipeline (HyperFusionNet for dense retrieval) achieves 0.71 score.", "HyperFusionNet", 0.71),
            ("We propose Adaptive Fusion for Retrieval (AFR) combining BM25 and Dense achieving 0.71 score.", "Adaptive Fusion for Retrieval (AFR)", 0.71),
            ("# Evaluating Retrieval Pipelines\n\n## 3. Vortex: Adaptive Retrieval Model\n\nVortex combines BM25 and Dense achieving 0.71 score.", "Vortex: Adaptive Retrieval Model", 0.71),
        ]
        for ms, expected_tok, num_val in evasion_cases:
            d = copy.deepcopy(self.data)
            d['methods'][0]['origin'] = 'combined'
            d['methods'][0]['exact_change'] = 'changed loss'
            if num_val is None:
                d['numeric_facts'] = []
            res = module.check(d, manuscript_text=ms)
            self.assertEqual(res['status'], 'structural_issues', (ms, res))
            self.assertIn('inflated_method_name:M1', res['issues'], (ms, res))
            matches = {f['match'] for f in res['grandiose_findings']}
            self.assertTrue(any(expected_tok in m for m in matches), (ms, expected_tok, matches))

        # 4. F19 nested parsimony_audit precedence, additional placeholders, and "no"/"0" false flags
        d_nested = copy.deepcopy(self.data)
        d_nested['methods'][0].update({
            'components': ['BM25', 'Dense'],
            'simplest_alternative': 'Linear probe',
            'ablation_evidence': 'BM25=0.68 vs 0.71',
            'parsimony_audit': {'simplest_alternative': 'N/A', 'ablation_evidence': 'N/A', 'passed': 'no'},
        })
        iss_nested = module.check(d_nested)['issues']
        self.assertIn('missing_simplest_alternative:M1', iss_nested)
        self.assertIn('missing_component_ablation:M1', iss_nested)
        self.assertIn('overcomplicated_method:M1', iss_nested)

        for bad_ph in ('TBA', 'pending', 'unknown', 'not applicable', '???'):
            d_ph = copy.deepcopy(self.data)
            d_ph['methods'][0].update({
                'components': ['BM25', 'Dense'],
                'simplest_alternative': bad_ph,
                'ablation_evidence': 'BM25=0.68',
            })
            self.assertIn('missing_simplest_alternative:M1', module.check(d_ph)['issues'], bad_ph)

    def test_iteration10_constituent_citations_tex_paragraphs_multiline_headings_and_redos(self):
        # 1. Negative controls: constituent-baseline citations (\cite, [1]/[2], mid-join, author-year),
        # LaTeX \paragraph/\subparagraph headings, multi-line headings, and 2-connector acronym
        negatives = [
            (r"HyperFusionNet combines BM25 \cite{robertson2009} and DPR \cite{karpukhin2020} achieving 0.71 score.", "HyperFusionNet"),
            ("HyperFusionNet is a hybrid retriever combining BM25 [1] and Dense [2] achieving 0.71 score.", "HyperFusionNet"),
            ("Evaluations test HyperFusionNet, which combines BM25 [1] and Dense [2] achieving 0.71 score.", "HyperFusionNet"),
            ("Evaluations test Versatile Retrieval Engine (VRE), which combines BM25 [1] and Dense [2] achieving 0.71 score.", "Versatile Retrieval Engine (VRE)"),
            ("Versatile Retrieval Engine (VRE) combines BM25 [1] and Dense [2] achieving 0.71 score.", "Versatile Retrieval Engine (VRE)"),
            ("HyperFusionNet combines BM25 [1] with a learned reranker achieving 0.71 score.", "HyperFusionNet"),
            ("HyperFusionNet combines BM25 (Robertson et al., 2009) and DPR (Karpukhin et al., 2020) achieving 0.71 score.", "HyperFusionNet"),
            ("HyperFusionNet, which combines BM25 and Dense, outperforms ResNet [1] achieving 0.71 score.", "HyperFusionNet"),
            ("\\title{Clean Paper Title}\n\\paragraph{Vortex: Adaptive Precision Execution}\\label{par:vortex}\n\nWe combine quantization and pruning achieving 0.71 score.", "Vortex: Adaptive Precision Execution"),
            ("\\title{Clean Paper Title}\n\\subparagraph{Vortex: Adaptive Precision Execution}\n\nWe combine quantization and pruning achieving 0.71 score.", "Vortex: Adaptive Precision Execution"),
            ("\\title{Clean Paper Title}\n\\paragraph*{Vortex: Adaptive Precision Execution} We combine quantization and pruning achieving 0.71 score.", "Vortex: Adaptive Precision Execution"),
            ("\\title{Clean Title}\n\\section{Adaptive Precision\nExecution (APEX)}\\label{sec:apex}\n\nWe combine quantization and pruning achieving 0.71 score.", "Adaptive Precision Execution (APEX)"),
            ("\\title{Clean Title}\n\\paragraph{Vortex: Adaptive\nPrecision Execution}\\label{par:vortex}\n\nWe combine quantization and pruning achieving 0.71 score.", "Vortex: Adaptive Precision Execution"),
            ("We propose Adaptive Fusion for the Retrieval (AFR) combining BM25 and Dense achieving 0.71 score.", "Adaptive Fusion for the Retrieval (AFR)"),
        ]
        for ms, expected_tok in negatives:
            d = copy.deepcopy(self.data)
            d['methods'][0]['origin'] = 'combined'
            d['methods'][0]['exact_change'] = 'changed loss'
            res = module.check(d, manuscript_text=ms)
            self.assertEqual(res['status'], 'structural_issues', (ms, res))
            self.assertIn('inflated_method_name:M1', res['issues'], (ms, res))
            matches = {f['match'] for f in res['grandiose_findings']}
            self.assertTrue(any(expected_tok in m for m in matches), (ms, expected_tok, matches))

        # 2. Positive controls (origin="reused"): single trailing citations, author-year citations,
        # left-clause prior-work citations, and indefinite termed/known as prior-work references
        clean_reused = [
            "HyperEmbedder combines dense and sparse embeddings [1] achieving 0.71 score.",
            "HyperEmbedder combines sparse and dense retrieval (Smith et al., 2024) achieving 0.71 score.",
            "HyperEmbedder is a retriever that combines sparse and dense signals (Smith et al., 2024) achieving 0.71 score.",
            "HyperEmbedder combines dense and sparse embeddings [1] and achieves 0.71 score.",
            "In [1], HyperEmbedder combines BM25 and Dense achieving 0.71 score.",
            "As shown in Smith et al. (2024), HyperEmbedder combines BM25 and Dense achieving 0.71 score.",
            "We compare against a neural retriever, termed UNSEEN, [ref] achieving 0.71 score.",
            "We evaluate a neural retriever, known as SpectralNet, from prior work [ref] achieving 0.71 score.",
            "We evaluate a neural retriever, termed UNSEEN, [ref] achieving 0.71 score.",
        ]
        for ms in clean_reused:
            d = copy.deepcopy(self.data)
            d['methods'][0]['origin'] = 'reused'
            d['methods'][0].pop('exact_change', None)
            res = module.check(d, manuscript_text=ms)
            self.assertEqual(res['status'], 'structure_passed', (ms, res))
            self.assertEqual(res['grandiose_findings'], [], (ms, res))

        # 3. Positive controls (origin="combined"): clean LaTeX multi-line \paragraph/\subparagraph headings
        clean_combined = [
            "\\title{Clean Paper Title}\n\\paragraph{Architecture: Transformer\nEncoder Overview}\n\nWe describe the standard transformer backbone achieving 0.71 score.",
            "\\title{Clean Paper Title}\n\\subparagraph{UNSEEN: Unseen\nPolicy Optimization}\n\nUNSEEN computes group advantages across rollouts [ref] achieving 0.71 score.",
        ]
        for ms in clean_combined:
            d = copy.deepcopy(self.data)
            d['methods'][0]['origin'] = 'combined'
            d['methods'][0]['exact_change'] = 'changed loss'
            res = module.check(d, manuscript_text=ms)
            self.assertEqual(res['status'], 'structure_passed', (ms, res))
            self.assertEqual(res['grandiose_findings'], [], (ms, res))

        # 4. Linear-time ReDoS check on adversarial regex inputs
        adversarial = [
            "A" * 2000,
            "Word " + "of the " * 300 + "End",
            "Word " + "for the Retrieval " * 120,
            "A B C D E F G H " * 200,
            "\\section{" + "Adaptive Precision " * 120,
        ]
        t0 = time.perf_counter()
        for adv in adversarial:
            list(module._PAREN_ACRONYM_RE.finditer(adv))
            module.check(copy.deepcopy(self.data), manuscript_text=adv)
        self.assertLess(time.perf_counter() - t0, 0.05)

    def test_iteration11_comparative_prior_framing_latex_short_titles_and_redos(self):
        # 1. Negative controls (Challenge 1): comparative/contrastive/replacement prior-work mentions
        # must NOT grant immunity in _SUBJECT_JOIN_AFTER_RE, bare indefinite termed/dubbed, or _PAREN_ACRONYM_RE
        negatives = [
            ("HyperFusionNet combines BM25 and DPR, outperforming prior methods achieving 0.71 score.", "HyperFusionNet"),
            ("HyperFusionNet combines BM25 and DPR to outperform existing baselines achieving 0.71 score.", "HyperFusionNet"),
            ("To replace prior baselines, HyperFusionNet combines BM25 and DPR achieving 0.71 score.", "HyperFusionNet"),
            ("Unlike standard baselines, HyperFusionNet combines BM25 and DPR achieving 0.71 score.", "HyperFusionNet"),
            ("Compared with prior work, HyperFusionNet combines BM25 and DPR achieving 0.71 score.", "HyperFusionNet"),
            ("To improve over prior work, HyperFusionNet combines BM25 and DPR achieving 0.71 score.", "HyperFusionNet"),
            ("In contrast to existing baselines, HyperFusionNet combines BM25 and DPR achieving 0.71 score.", "HyperFusionNet"),
            ("Instead of relying on standard baselines, HyperFusionNet combines BM25 and DPR achieving 0.71 score.", "HyperFusionNet"),
            ("While prior work uses single-stage scoring, HyperFusionNet combines BM25 and DPR achieving 0.71 score.", "HyperFusionNet"),
            ("HyperFusionNet combines BM25 and DPR to replace prior baselines achieving 0.71 score.", "HyperFusionNet"),
            ("HyperFusionNet combines BM25 and DPR, achieving better recall than prior methods achieving 0.71 score.", "HyperFusionNet"),
            ("Adaptive Fusion for the Retrieval (AFR) combines BM25 and DPR, outperforming prior methods achieving 0.71 score.", "Adaptive Fusion for the Retrieval (AFR)"),
            ("A hybrid retriever, termed APEX, outperforms existing baselines achieving 0.71 score.", "APEX"),
            ("A hybrid retriever, termed HyperFusionNet, outperforms prior methods achieving 0.71 score.", "HyperFusionNet"),
            ("A modular pipeline, dubbed NeuralFusion, surpasses prior methods achieving 0.71 score.", "NeuralFusion"),
            ("A hybrid retriever, termed APEX, combines BM25 and DPR, outperforming prior methods achieving 0.71 score.", "APEX"),
            ("To replace prior baselines, a hybrid retriever, termed APEX, achieves 0.71 score.", "APEX"),
            ("HyperFusion Engine (HFE) surpasses existing baselines achieving 0.71 score.", "HyperFusion Engine (HFE)"),
            ("HyperFusionNet combines BM25 and DPR (2020) achieving 0.71 score.", "HyperFusionNet"),
            # Challenge 2: LaTeX optional [Short] title arguments
            ("\\title{Clean Title}\n\\section[Vortex]{Vortex: Adaptive Precision Execution}\nWe combine quantization and pruning achieving 0.71 score.", "Vortex: Adaptive Precision Execution"),
            ("\\title{Clean Title}\n\\paragraph[Vortex]{Vortex: Adaptive Precision Execution} We combine quantization and pruning achieving 0.71 score.", "Vortex: Adaptive Precision Execution"),
            ("\\section[Vortex]{Vortex: Adaptive Precision Execution}\nThis section describes the architecture, which outperforms prior methods achieving 0.71 score.", "Vortex: Adaptive Precision Execution"),
            ("\\title[Clean Short]{Clean Title}\n\\subparagraph*[Vortex]{Vortex: Adaptive Precision Execution} We combine quantization and pruning achieving 0.71 score.", "Vortex: Adaptive Precision Execution"),
        ]
        for ms, expected_tok in negatives:
            d = copy.deepcopy(self.data)
            d['methods'][0]['origin'] = 'combined'
            d['methods'][0]['exact_change'] = 'changed loss'
            res = module.check(d, manuscript_text=ms)
            self.assertEqual(res['status'], 'structural_issues', (ms, res))
            self.assertIn('inflated_method_name:M1', res['issues'], (ms, res))
            self.assertIn('grandiose_branding_detected:M1', res['issues'], (ms, res))
            matches = {f['match'] for f in res['grandiose_findings']}
            self.assertTrue(any(expected_tok in m for m in matches), (ms, expected_tok, matches))

        # 2. Positive controls (origin="reused"): clean non-contrastive prior-work framing,
        # left-in citations, narrative author-year citations, and clean [Short] headings
        clean_reused = [
            "Prior work such as HyperEmbedder combines dense and sparse embeddings achieving 0.71 score.",
            "In prior work, HyperEmbedder combines dense and sparse embeddings achieving 0.71 score.",
            "A standard baseline, termed ColBERTv2 [1], achieves 0.71 score.",
            "In [1], a hybrid retriever, termed HyperEmbedder, combines dense and sparse embeddings achieving 0.71 score.",
            "HyperEmbedder combines dense and sparse embeddings as in Smith et al. (2024) achieving 0.71 score.",
            "In more than 10 prior studies, HyperEmbedder combines dense and sparse embeddings achieving 0.71 score.",
            "We evaluate a neural retriever, known as SpectralNet, from prior work [ref] achieving 0.71 score.",
            "\\title{Clean Title}\n\\section[ColBERTv2]{ColBERTv2: Late Interaction Baseline \\cite{khattab2020}}\nPrior work \\cite{khattab2020} evaluates ColBERTv2 achieving 0.71 score.",
            "\\title{Clean Title}\n\\paragraph[Arch]{Architecture: Transformer Encoder Overview} We describe standard layers achieving 0.71 score.",
        ]
        for ms in clean_reused:
            d = copy.deepcopy(self.data)
            d['methods'][0]['origin'] = 'reused'
            d['methods'][0].pop('exact_change', None)
            res = module.check(d, manuscript_text=ms)
            self.assertEqual(res['status'], 'structure_passed', (ms, res))
            self.assertEqual(res['grandiose_findings'], [], (ms, res))

        # 3. Linear-time ReDoS check across all compiled patterns in check_manuscript_ledger.py
        import re as _re
        patterns = [v for v in vars(module).values() if isinstance(v, _re.Pattern)]
        adv_inputs = [
            "A" * 2000,
            "Smith " * 300 + "et al. (2024)",
            "\\section[" + "Short " * 300 + "]{" + "Title " * 200 + "}",
            "\\section[" + "Unclosed " * 300,
            "better " + "and faster " * 200 + "than prior methods",
            "Unlike " + "very " * 400 + "prior work, " + "HyperFusionNet " * 5,
        ]
        for pat in patterns:
            t_pat = time.perf_counter()
            for adv in adv_inputs:
                list(pat.finditer(adv))
            self.assertLess(time.perf_counter() - t_pat, 0.02, pat.pattern)

    def test_iteration12_redos_enumerated_contrastive_interrupters_citations_tex_sources_and_cli_validation(self):
        import re as _re

        # 1. ReDoS < 0.02s across all compiled patterns and check() on whitespace / LaTeX stress inputs
        adv_stress = [
            " " * 5000,
            "\t" * 5000,
            "\n" * 5000 + "Hello.",
            "\\section" + " " * 10000 + "X",
            "\\section[" + "[a" * 2500,
            "\\section[" * 555,
            "HyperFusionNet combines " + " " * 5000 + "BM25 and DPR.",
            "," + " " * 5000 + "X",
            "A" * 2000,
            "Smith " * 300 + "et al. (2024)",
        ]
        for pat in [v for v in vars(module).values() if isinstance(v, _re.Pattern)]:
            t_pat = time.perf_counter()
            for adv in adv_stress:
                list(pat.finditer(adv))
            self.assertLess(time.perf_counter() - t_pat, 0.02, pat.pattern)
        for adv in adv_stress:
            t_chk = time.perf_counter()
            module.check(copy.deepcopy(self.data), manuscript_text=adv)
            self.assertLess(time.perf_counter() - t_chk, 0.02, repr(adv[:30]))

        # 2. Negative controls (Gate 11 R1/R2/Ch1: enumerated contrastive lists, interrupters,
        # comparative/causal cues, last-constituent citations, all-caps acronyms, LaTeX L1-L7)
        negatives = [
            ("Unlike BM25, DPR, and other prior methods, HyperFusionNet combines BM25 and DPR achieving 0.71 score.", "HyperFusionNet"),
            ("Compared with BM25, DPR, and existing baselines, HyperFusionNet combines BM25 and DPR achieving 0.71 score.", "HyperFusionNet"),
            ("In contrast to (1) BM25 and (2) prior methods, HyperFusionNet combines BM25 and DPR achieving 0.71 score.", "HyperFusionNet"),
            ("Instead of BM25 (a sparse retriever) or prior methods, HyperFusionNet combines BM25 and DPR achieving 0.71 score.", "HyperFusionNet"),
            ("HyperFusionNet combines BM25 and DPR (outperforming BM25, DPR, and prior methods) achieving 0.71 score.", "HyperFusionNet"),
            ("HyperFusionNet combines dense retrieval and BM25 [1] achieving 0.71 score.", "HyperFusionNet"),
            ("HyperFusionNet combines dense retrieval and BM25 from Robertson (2009) achieving 0.71 score.", "HyperFusionNet"),
            ("HyperFusionNet combines dense retrieval and BM25 (Robertson, 2009) achieving 0.71 score.", "HyperFusionNet"),
            ("To improve on prior work, HyperFusionNet combines BM25 and DPR achieving 0.71 score.", "HyperFusionNet"),
            ("A hybrid retriever, termed APEX, improves on prior methods achieving 0.71 score.", "APEX"),
            ("A hybrid retriever, termed APEX, overcomes prior methods achieving 0.71 score.", "APEX"),
            ("As an alternative to prior methods, HyperFusionNet combines BM25 and DPR achieving 0.71 score.", "HyperFusionNet"),
            ("A hybrid retriever, termed APEX, yields stronger zero-shot retrieval accuracy on benchmarks than prior methods achieving 0.71 score.", "APEX"),
            ("Unlike slow, multi-stage prior methods, HyperFusionNet combines BM25 and DPR achieving 0.71 score.", "HyperFusionNet"),
            ("To replace slow, brittle prior baselines, HyperFusionNet combines BM25 and DPR achieving 0.71 score.", "HyperFusionNet"),
            ("Compared with dense, resource-heavy prior models, a hybrid retriever, termed APEX, achieves 0.71 score.", "APEX"),
            ("While dense, expensive prior methods fail on rare tokens, HyperFusionNet combines BM25 and DPR achieving 0.71 score.", "HyperFusionNet"),
            ("While neural models struggle, multi-stage prior methods also fail, HyperFusionNet combines BM25 and DPR achieving 0.71 score.", "HyperFusionNet"),
            ("A hybrid retriever, termed APEX, achieves 0.71 score while dense, sparse standard baselines fail.", "APEX"),
            ("HyperFusionNet combines BM25 and DPR with substantial improvements over existing baselines achieving 0.71 score.", "HyperFusionNet"),
            ("To improve existing baselines, HyperFusionNet combines BM25 and DPR achieving 0.71 score.", "HyperFusionNet"),
            ("Improving prior methods, HyperFusionNet combines BM25 and DPR achieving 0.71 score.", "HyperFusionNet"),
            ("HyperFusionNet combines BM25 and DPR, which is superior to standard baselines achieving 0.71 score.", "HyperFusionNet"),
            ("Without relying on prior methods, HyperFusionNet combines BM25 and DPR achieving 0.71 score.", "HyperFusionNet"),
            ("In place of prior baselines, HyperFusionNet combines BM25 and DPR achieving 0.71 score.", "HyperFusionNet"),
            ("HyperFusionNet, which combines BM25 and DPR for gains over prior methods, achieves 0.71 score.", "HyperFusionNet"),
            ("To outperform, on all datasets, existing baselines, HyperFusionNet combines BM25 and DPR achieving 0.71 score.", "HyperFusionNet"),
            ("Unlike, say, prior methods, HyperFusionNet combines BM25 and DPR achieving 0.71 score.", "HyperFusionNet"),
            ("HyperFusionNet combines BM25 and DPR, achieving higher recall, across benchmarks, than prior methods achieving 0.71 score.", "HyperFusionNet"),
            ("HyperFusionNet combines BM25 and DPR, achieving better top-10 retrieval recall on BEIR than prior methods achieving 0.71 score.", "HyperFusionNet"),
            ("HyperFusionNet combines BM25 and DPR, achieving more consistent retrieval than prior methods achieving 0.71 score.", "HyperFusionNet"),
            ("HyperFusionNet combines BM25 and DPR, proving superior to prior methods achieving 0.71 score.", "HyperFusionNet"),
            ("HyperFusionNet combines BM25 and DPR, yielding substantial gains over prior methods achieving 0.71 score.", "HyperFusionNet"),
            ("Achieving a large improvement over prior methods, HyperFusionNet combines BM25 and DPR achieving 0.71 score.", "HyperFusionNet"),
            ("A hybrid retriever, termed APEX, is superior to existing baselines achieving 0.71 score.", "APEX"),
            ("A hybrid retriever, termed APEX, yields substantial gains over prior methods achieving 0.71 score.", "APEX"),
            ("Because prior methods fail on multi-hop queries, HyperFusionNet combines BM25 and DPR achieving 0.71 score.", "HyperFusionNet"),
            ("Since existing baselines struggle on long texts, HyperFusionNet combines BM25 and DPR achieving 0.71 score.", "HyperFusionNet"),
            ("Motivated by flaws in prior work, HyperFusionNet combines BM25 and DPR achieving 0.71 score.", "HyperFusionNet"),
            ("Departing from standard baselines, HyperFusionNet combines BM25 and DPR achieving 0.71 score.", "HyperFusionNet"),
            ("HyperFusionNet (Section 3) combines BM25 and DPR achieving 0.71 score.", "HyperFusionNet"),
            ("HyperFusionNet, in practice, combines BM25 and DPR achieving 0.71 score.", "HyperFusionNet"),
            ("HyperFusionNet (outperforming prior methods) combines BM25 and DPR achieving 0.71 score.", "HyperFusionNet"),
            ("Adaptive Fusion for the Retrieval (AFR) yields clear gains over prior methods achieving 0.71 score.", "Adaptive Fusion for the Retrieval (AFR)"),
            ("HyperFusionNet combines BM25 and DPR as in DPR (2020) achieving 0.71 score.", "HyperFusionNet"),
            ("\\title{Clean Title}\n\\section[Overview of \\cite[p.~1]{a}]{Vortex: Adaptive Precision Execution}\nWe combine quantization and pruning achieving 0.71 score.", "Vortex: Adaptive Precision Execution"),
            ("\\title{Clean Title}\n\\section[Vortex [v2]]{Vortex: Adaptive Precision Execution}\nWe combine quantization and pruning achieving 0.71 score.", "Vortex: Adaptive Precision Execution"),
            ("\\title{Clean Title}\n\\section[\n  Vortex Short\n]{Vortex: Adaptive Precision Execution}\nWe combine quantization and pruning achieving 0.71 score.", "Vortex: Adaptive Precision Execution"),
            ("\\title{Clean Title}\n\\section[Vortex]{{\\bf Vortex}: Adaptive Precision Execution}\nWe combine quantization and pruning achieving 0.71 score.", "Vortex: Adaptive Precision Execution"),
            ("\\title{Clean Title}\n\\section[Vortex]{Vortex: {\\bf Adaptive} Precision Execution}\nWe combine quantization and pruning achieving 0.71 score.", "Vortex: Adaptive Precision Execution"),
            ("\\title{Clean Title}\n\\section[Vortex]{Vortex: \\protect\\emph{Adaptive} Precision Execution}\nWe combine quantization and pruning achieving 0.71 score.", "Vortex: Adaptive Precision Execution"),
            ("\\title{Clean Title}\n\\section[Vortex]{\\texorpdfstring{Vortex: Adaptive Precision Execution}{Vortex}}\nWe combine quantization and pruning achieving 0.71 score.", "Vortex: Adaptive Precision Execution"),
        ]
        for ms, expected_tok in negatives:
            d = copy.deepcopy(self.data)
            d['methods'][0]['origin'] = 'combined'
            d['methods'][0]['exact_change'] = 'changed loss'
            res = module.check(d, manuscript_text=ms)
            self.assertEqual(res['status'], 'structural_issues', (ms, res))
            self.assertIn('inflated_method_name:M1', res['issues'], (ms, res))
            self.assertIn('grandiose_branding_detected:M1', res['issues'], (ms, res))
            matches = {f['match'] for f in res['grandiose_findings']}
            self.assertTrue(any(expected_tok in m for m in matches), (ms, expected_tok, matches))

        # 3. Clean-baseline positive controls (origin="reused")
        clean_reused = [
            "Unlike BERT, prior work such as HyperEmbedder combines dense and sparse embeddings achieving 0.71 score.",
            "Unlike single-stage baselines, prior work such as HyperEmbedder combines dense and sparse embeddings achieving 0.71 score.",
            "HyperEmbedder combines dense and sparse embeddings [1] achieving 0.71 score.",
            "HyperEmbedder combines dense and sparse embeddings without fine-tuning [1] achieving 0.71 score.",
            "Following [1], a hybrid retriever, termed HyperEmbedder, combines dense and sparse embeddings achieving 0.71 score.",
            "In prior work, HFE: HyperFusion Engine achieves 0.71 score.",
            "In more than 10 prior studies, HyperEmbedder combines dense and sparse embeddings achieving 0.71 score.",
            "Since prior work introduced HyperEmbedder, it combines dense and sparse embeddings achieving 0.71 score.",
            "HyperEmbedder (from [1]) combines dense and sparse embeddings achieving 0.71 score.",
        ]
        for ms in clean_reused:
            d = copy.deepcopy(self.data)
            d['methods'][0]['origin'] = 'reused'
            d['methods'][0].pop('exact_change', None)
            res = module.check(d, manuscript_text=ms)
            self.assertEqual(res['status'], 'structure_passed', (ms, res))
            self.assertEqual(res['grandiose_findings'], [], (ms, res))

        # 4. --sources-dir pp./pages/ranges + #fragment quote coupling + unit-partitioned numeric_facts (S1-S3, S5)
        with tempfile.TemporaryDirectory() as tmpdir:
            sdir = Path(tmpdir)
            (sdir / 'blocks.json').write_text(
                json.dumps({
                    'format': 'research_scientist_pdf_blocks_v1',
                    'pages': [
                        [{'page_idx': 0, 'text': 'Page one evidence.'}],
                        [{'page_idx': 1, 'text': 'Page two evidence.'}],
                    ],
                }),
                encoding='utf-8',
            )
            (sdir / 'nested.json').write_text(
                json.dumps({'metrics': {'acc': 0.65}, 'other': {'bogus': 'fabricated 0.99 claim'}}),
                encoding='utf-8',
            )
            for bad_loc in ('blocks.json, pp. 99', 'blocks.json, pages 99', 'blocks.json, pp. 12-99', 'blocks.json, pp. 2-1'):
                l_pg = {
                    'sources': [{'id': 'S1', 'type': 'paper', 'locator': bad_loc, 'verified': True, 'verified_by': 'a', 'verified_at': '2026-11-21'}],
                    'claims': [], 'methods': [], 'numeric_facts': [],
                }
                self.assertIn('source_locator_page_missing:S1', module.check(l_pg, sources_dir=sdir)['issues'], bad_loc)
            l_pg_ok = {
                'sources': [{'id': 'S1', 'type': 'paper', 'locator': 'blocks.json, pp. 1-2', 'quote': 'Page two evidence', 'verified': True, 'verified_by': 'a', 'verified_at': '2026-11-21'}],
                'claims': [], 'methods': [], 'numeric_facts': [],
            }
            self.assertEqual(module.check(l_pg_ok, sources_dir=sdir)['status'], 'structure_passed')

            l_frag_bad = {
                'sources': [{'id': 'S1', 'type': 'json', 'locator': 'nested.json#metrics.acc', 'quote': 'fabricated 0.99 claim', 'verified': True, 'verified_by': 'a', 'verified_at': '2026-11-21'}],
                'claims': [], 'methods': [], 'numeric_facts': [],
            }
            self.assertIn('source_quote_not_found:S1', module.check(l_frag_bad, sources_dir=sdir)['issues'])
            l_frag_ok = {
                'sources': [{'id': 'S1', 'type': 'json', 'locator': 'nested.json#metrics.acc', 'quote': '0.65', 'verified': True, 'verified_by': 'a', 'verified_at': '2026-11-21'}],
                'claims': [], 'methods': [], 'numeric_facts': [],
            }
            self.assertEqual(module.check(l_frag_ok, sources_dir=sdir)['status'], 'structure_passed')

        d_s5 = copy.deepcopy(self.data)
        d_s5['methods'][0]['origin'] = 'reused'
        d_s5['numeric_facts'] = [{'id': 'N1', 'occurrences': [{'location': 'body', 'value': 85, 'unit': 'epochs'}]}]
        r_s5 = module.check(d_s5, manuscript_text="We train for 85 epochs and achieve 85% accuracy.")
        self.assertIn('undeclared_manuscript_numeric_claim:85%', r_s5['issues'], r_s5)

        d_pct = copy.deepcopy(self.data)
        d_pct['methods'][0]['origin'] = 'reused'
        d_pct['numeric_facts'] = [{'id': 'N1', 'occurrences': [{'location': 'results', 'value': 81.5, 'unit': 'percent'}]}]
        r_pct = module.check(d_pct, manuscript_text="Reusing the baseline yielded 81.5 percent accuracy on Cora.")
        self.assertEqual(r_pct['status'], 'structure_passed', r_pct)

        # 5. Empty/whitespace CLI & Python API path validation (no CWD scan)
        with tempfile.TemporaryDirectory() as tmpdir:
            td = Path(tmpdir)
            (td / 'doc.txt').write_text('verified local doc quote\n', encoding='utf-8')
            (td / 'ms.md').write_text('Clean prose achieving 0.71 score.\n', encoding='utf-8')
            led_doc = copy.deepcopy(self.data)
            led_doc['sources'][0]['locator'] = 'doc.txt'
            led_p = td / 'ledger.json'
            led_p.write_text(json.dumps(led_doc), encoding='utf-8')

            for bad_args in (
                [''],
                ['   '],
                ['--ledger', ''],
                ['--ledger', '   '],
                ['--ledger', '', str(led_p)],
                ['--ledger', str(led_p), '--manuscript', ''],
                ['--ledger', str(led_p), '--manuscript', '   '],
                ['--ledger', str(led_p), '--sources-dir', ''],
                ['--ledger', str(led_p), '--sources-dir', '   '],
            ):
                proc = subprocess.run(
                    [sys.executable, str(SCRIPT), *bad_args],
                    cwd=str(td),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(proc.returncode, 2, (bad_args, proc.stdout, proc.stderr))
                self.assertIn('error', json.loads(proc.stderr), (bad_args, proc.stderr))

        for bad_kw in (
            {'sources_dir': ''},
            {'sources_dir': '   '},
            {'manuscript_path': ''},
            {'manuscript_path': '   '},
        ):
            with self.assertRaises(ValueError):
                module.check(copy.deepcopy(self.data), **bad_kw)

    def test_redos_unclosed_cite_and_tilde_runs_linear_time(self):
        import time

        for probe in (
            "\\cite[" * 5000 + "\nWe evaluate BM25 on BEIR.\n",
            "\\cite{" * 5000 + "\nWe evaluate BM25 on BEIR.\n",
            "~" * 5000 + "\nWe evaluate BM25 on BEIR.\n",
        ):
            t0 = time.perf_counter()
            norm = module._normalize_manuscript(probe)
            self.assertLess(time.perf_counter() - t0, 0.02, probe[:20])
            self.assertIn("We evaluate BM25 on BEIR.", norm)

        t_tilde = time.perf_counter()
        res_tilde = module.check(
            copy.deepcopy(self.data),
            manuscript_text="~" * 5000 + "\nWe achieve 0.71 score.\n",
        )
        self.assertLess(time.perf_counter() - t_tilde, 0.02)
        self.assertEqual(res_tilde['status'], 'structure_passed', res_tilde)

        t_cite = time.perf_counter()
        res_cite = module.check(
            copy.deepcopy(self.data),
            manuscript_text="\\cite[" * 5000 + "\nWe achieve 0.71 score.\n",
        )
        self.assertLess(time.perf_counter() - t_cite, 0.05)
        self.assertEqual(res_cite['status'], 'structure_passed', res_cite)

        # Functional equivalence: multi-arg ~\\cite normalized cleanly to [ref]
        norm_cite = module._normalize_manuscript(
            r"We compare against ResNet~\cite[see][p.~1]{he2016} achieving 0.71 score."
        )
        self.assertIn("[ref]", norm_cite)
        self.assertNotIn("he2016", norm_cite)


if __name__ == '__main__':
    unittest.main()
