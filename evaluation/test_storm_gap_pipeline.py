"""Unit and adversarial tests for storm_explorer.py and gap_pipeline.py (F9, F10, F20)."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'research-scientist/scripts'
sys.path.insert(0, str(SCRIPTS))

import storm_explorer
import gap_pipeline


class StormExplorerTests(unittest.TestCase):
    def test_perspectives_dedup_information_table_and_uncovered_branches(self):
        corpus = [
            {'source_id': 'P1', 'url': 'u1', 'title': 'Latency Benchmark', 'year': 2024, 'family': 'same_problem',
             'text': 'Latency measured in-domain only; zero calibration or adversarial robustness data.', 'snippet': 'Latency only.'},
            {'source_id': 'P1', 'url': 'u1', 'title': 'Latency Benchmark', 'year': 2024, 'family': 'same_problem',
             'text': 'Latency measured in-domain only; zero calibration or adversarial robustness data.', 'snippet': 'Latency only.'},
        ]
        res = storm_explorer.explore('OOD calibration & adversarial robustness', corpus, max_turns=8)
        state = res['storm_state']
        self.assertGreaterEqual(len(state['perspectives']), 2)
        self.assertGreaterEqual(len(state['qa_turns']), 1)
        self.assertEqual(len(state['information_table']), len({r['source_id'] for r in state['information_table']}))
        branches = {b['branch'] for b in state['uncovered_branches']}
        self.assertTrue(any('calibration' in b or 'robustness' in b for b in branches), branches)

    def test_compact_cli_bounded_stdout_and_disk_artifact(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            corpus_p = tmp_path / 'corpus.json'
            out_p = tmp_path / 'storm_out.json'
            corpus_p.write_text(json.dumps([
                {'id': 'P1', 'title': 'RRF latency', 'text': 'RRF latency study.', 'family': 'same_problem'},
                {'id': 'P2', 'title': 'Calibration shift', 'text': 'OOD calibration shift.', 'family': 'cross_setting_analogy'},
            ]), encoding='utf-8')
            proc = subprocess.run(
                [sys.executable, str(SCRIPTS / 'storm_explorer.py'),
                 '--topic', 'RRF OOD calibration', '--corpus', str(corpus_p), '--out', str(out_p), '--compact'],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertLess(len(proc.stdout.encode('utf-8')), 4096)
            summary = json.loads(proc.stdout)
            self.assertTrue(summary['compact'])
            self.assertEqual(Path(summary['artifact_path']), out_p)
            self.assertTrue(out_p.is_file())

    def test_b13_four_facet_p4_turns_non_zero_regex_and_huge_topic_compact(self):
        import tempfile
        corpus = [
            {'source_id': 'P1', 'url': 'u1', 'title': 'Calibration & Analogy Study', 'year': 2024,
             'family': 'cross_setting_analogy',
             'text': 'Produces non-zero calibration error under OOD shift and cross-setting analogy.',
             'snippet': 'Non-zero calibration error.'},
        ]
        res = storm_explorer.explore('alpha & beta & gamma & calibration', corpus, max_turns=12)
        p4_turns = [t for t in res['qa_turns'] if t['perspective_id'] == 'P4']
        self.assertGreaterEqual(len(p4_turns), 1)
        p4_outline = next(o for o in res['outline'] if o['perspective_id'] == 'P4')
        self.assertEqual(p4_outline['coverage'], 'covered')
        uncovered_names = {b['branch'] for b in res['uncovered_branches']}
        self.assertNotIn('calibration', uncovered_names)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            corpus_p = tmp_path / 'corpus.json'
            corpus_p.write_text(json.dumps(corpus), encoding='utf-8')
            huge_topic = 'calibration ' * 450
            proc = subprocess.run(
                [sys.executable, str(SCRIPTS / 'storm_explorer.py'),
                 '--topic', huge_topic, '--corpus', str(corpus_p), '--compact'],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertLess(len(proc.stdout.encode('utf-8')), 4096)

    def test_n8_four_facets_all_receive_turns_at_default_max_turns(self):
        corpus = [
            {'source_id': 'P1', 'url': 'u1', 'title': 'Alpha Beta Gamma Delta Study', 'year': 2024,
             'family': 'cross_setting_analogy', 'text': 'alpha beta gamma delta calibration shift', 'snippet': 's'},
        ]
        res = storm_explorer.explore('alpha & beta & gamma & delta', corpus, max_turns=12)
        for facet in ('alpha', 'beta', 'gamma', 'delta'):
            self.assertGreaterEqual(len([t for t in res['qa_turns'] if t['facet'] == facet]), 1, facet)


class GapPipelineTests(unittest.TestCase):
    def _base_corpus_and_digests(self):
        corpus = {
            'P1': {'id': 'P1', 'source': 'openalex', 'family': 'same_problem', 'year': 2023,
                   'published_date': '2023-05-01', 'title': 'Dense Retrieval Latency',
                   'abstract': 'Latency only.', 'text': '', 'retraction_status': 'clean'},
            'P2': {'id': 'P2', 'source': 'arxiv', 'family': 'cross_setting_analogy', 'year': 2024,
                   'published_date': '2024-03-01', 'title': 'Vision Calibration Shift',
                   'abstract': 'Vision calibration.', 'text': '', 'retraction_status': 'clean'},
        }
        digests = {
            'P1': {'source_id': 'P1', 'access': 'full_text', 'digest': 'Latency only.'},
            'P2': {'source_id': 'P2', 'access': 'full_text', 'digest': 'Vision calibration.'},
        }
        return corpus, digests

    def test_positive_bounded_dual_regime_gap_passes(self):
        corpus, digests = self._base_corpus_and_digests()
        cands = [{
            'id': 'G1', 'claim': 'Rank fusion variance under OOD shift remains uncharacterized.',
            'cited_ids': ['P1', 'P2'], 'support_ids': ['P1', 'P2'],
            'cutoff_year': 2026, 'sgha_critics_passed': True, 'engineering_checked': True,
        }]
        out = gap_pipeline.run_pipeline('OOD fusion', corpus, digests, cands)
        self.assertEqual(out['exit_code'], 0)
        self.assertEqual(len(out['surviving_gaps']), 1)
        self.assertEqual(out['rejected_gaps'], [])

    def test_all_rejection_gates_fire_with_exact_codes(self):
        corpus, digests = self._base_corpus_and_digests()
        corpus['KILL1'] = {
            'id': 'KILL1', 'source': 'acl', 'family': 'kill_search', 'year': 2024,
            'published_date': '2024-06-01',
            'title': 'Dynamic Temperature Scaling for OOD Reciprocal Rank Fusion',
            'abstract': None, 'text': '', 'retraction_status': 'clean',
        }
        corpus['FUTURE'] = {
            'id': 'FUTURE', 'source': 'arxiv', 'family': 'same_problem', 'year': 2027,
            'published_date': '2027-01-15', 'title': 'Future Study', 'abstract': '...', 'text': '', 'retraction_status': 'clean',
        }
        corpus['RET'] = {
            'id': 'RET', 'source': 'crossref', 'family': 'same_problem', 'year': 2022,
            'published_date': '2022-01-01', 'title': 'Retracted Study', 'abstract': '...', 'text': '', 'retraction_status': 'retracted',
        }
        digests['FUTURE'] = {'source_id': 'FUTURE', 'access': 'full_text', 'digest': 'Future.'}
        digests['RET'] = {'source_id': 'RET', 'access': 'full_text', 'digest': 'Retracted.'}

        cases = [
            ('C_TEMP', {'id': 'C_TEMP', 'claim': 'Uses future work', 'cited_ids': ['P1', 'FUTURE'], 'support_ids': ['P1', 'FUTURE'], 'cutoff_date': '2025-12-31'}, 'DROP_TEMPORAL_LEAK'),
            ('C_UNREAD', {'id': 'C_UNREAD', 'claim': 'Missing digest', 'cited_ids': ['P1', 'UNKNOWN'], 'support_ids': ['P1', 'UNKNOWN']}, 'DROP_UNREAD_CITATION'),
            ('C_RET', {'id': 'C_RET', 'claim': 'Retracted support', 'cited_ids': ['P1', 'RET'], 'support_ids': ['P1', 'RET']}, 'DROP_RETRACTED_SUPPORT'),
            ('C_ENG', {'id': 'C_ENG', 'claim': 'Buggy setup', 'cited_ids': ['P1', 'P2'], 'support_ids': ['P1', 'P2'], 'engineering_checked': False}, 'DROP_ENGINEERING_BUG'),
            ('C_SOLVED', {'id': 'C_SOLVED', 'claim': 'Dynamic temperature scaling for OOD reciprocal rank fusion', 'cited_ids': ['P1', 'P2'], 'support_ids': ['P1', 'P2'], 'cutoff_year': 2025, 'engineering_checked': True}, 'DROP_ALREADY_SOLVED'),
            ('C_COV', {'id': 'C_COV', 'claim': 'Uncovered branch claim', 'cited_ids': ['P1', 'P2'], 'support_ids': ['P1', 'P2'], 'engineering_checked': True, 'uncovered_branches': [{'branch': 'calibration'}]}, 'DROP_INSUFFICIENT_COVERAGE'),
            ('C_FRAG', {'id': 'C_FRAG', 'claim': 'Unique unexplored claim on single paper', 'cited_ids': ['P1'], 'support_ids': ['P1'], 'engineering_checked': True}, 'DROP_SINGLE_PAPER_FRAGILE'),
            ('C_SGHA', {'id': 'C_SGHA', 'claim': 'Artificial scope claim', 'cited_ids': ['P1', 'P2'], 'support_ids': ['P1', 'P2'], 'engineering_checked': True, 'sgha_critics_passed': False}, 'DROP_ARTIFICIAL_SCOPE'),
        ]
        for _, cand, expected_code in cases:
            out = gap_pipeline.run_pipeline('OOD fusion', corpus, digests, [cand])
            self.assertEqual(out['exit_code'], 1, cand['id'])
            self.assertEqual(out['rejected_gaps'][0]['reason_code'], expected_code, cand['id'])

    def test_hindsight_kill_beats_fragile_and_feedback_memory_dedup(self):
        import tempfile
        corpus, digests = self._base_corpus_and_digests()
        corpus['P1']['year'] = 2017
        corpus['P1']['published_date'] = '2017-04-03'
        corpus['D19'] = {
            'id': 'D19', 'source': 'acm', 'family': 'kill_search', 'year': 2019,
            'published_date': '2019-07-16',
            'title': 'Tuned ItemKNN Baselines Outperform Neural Collaborative Filtering',
            'abstract': None, 'text': 'Systematic tuning closes neural gap.', 'retraction_status': 'clean',
        }
        cand_hindsight = {
            'id': 'C_HINDSIGHT',
            'claim': 'Systematic tuning of ItemKNN baselines vs neural collaborative filtering remains open',
            'cited_ids': ['P1'], 'support_ids': ['P1'],
            'cutoff_date': '2018-12-31', 'hindsight_eval_date': '2026-01-01',
            'engineering_checked': True,
        }
        with tempfile.TemporaryDirectory() as tmp:
            fb_path = Path(tmp) / 'feedback.json'
            out1 = gap_pipeline.run_pipeline('recsys', corpus, digests, [cand_hindsight], feedback_store=fb_path)
            self.assertEqual(out1['rejected_gaps'][0]['reason_code'], 'DROP_ALREADY_SOLVED')
            self.assertTrue(fb_path.is_file())
            # Repeat near-identical phrasing against clean corpus should be suppressed via feedback memory
            cand_dup = {
                'id': 'C_DUP',
                'claim': 'Systematic tuning of ItemKNN baselines vs neural collaborative filtering remains open!',
                'cited_ids': ['P1', 'P2'], 'support_ids': ['P1', 'P2'],
                'engineering_checked': True,
            }
            out2 = gap_pipeline.run_pipeline('recsys', {k: v for k, v in corpus.items() if k != 'D19'}, digests, [cand_dup], feedback_store=fb_path)
            self.assertEqual(out2['rejected_gaps'][0]['reason_code'], 'DROP_DUPLICATE')

    def test_b6_b8_b14b_digest_access_string_year_and_feedback_claim(self):
        import tempfile
        corpus, digests = self._base_corpus_and_digests()
        digests['P1']['access'] = 'abstract'
        cand = {
            'claim': 'Calibration under OOD shift remains uncharacterized.',
            'cited_ids': ['P1', 'P2'], 'support_ids': ['P1', 'P2'],
            'cutoff_year': 2026, 'sgha_critics_passed': True, 'engineering_checked': True,
        }
        with tempfile.TemporaryDirectory() as tmp:
            fb_path = Path(tmp) / 'fb.json'
            out_unread = gap_pipeline.run_pipeline('ood', corpus, digests, [cand], feedback_store=fb_path)
            self.assertEqual(out_unread['rejected_gaps'][0]['reason_code'], 'DROP_UNREAD_CITATION')
            fb = json.loads(fb_path.read_text(encoding='utf-8'))
            self.assertEqual(fb['rejected_claims'][0]['claim'], cand['claim'])

            digests['P1']['access'] = 'full_text'
            corpus_p = Path(tmp) / 'c.json'
            digests_p = Path(tmp) / 'd.json'
            cands_p = Path(tmp) / 'k.json'
            corpus_p.write_text(json.dumps([
                {'id': 'P1', 'source': 'openalex', 'family': 'same_problem', 'year': '2026', 'title': 'P1'},
                {'id': 'P2', 'source': 'arxiv', 'family': 'cross_setting_analogy', 'year': 2023, 'title': 'P2'},
            ]), encoding='utf-8')
            digests_p.write_text(json.dumps(digests), encoding='utf-8')
            cands_p.write_text(json.dumps([{
                'id': 'C_STR', 'claim': 'String year leak test', 'cited_ids': ['P1', 'P2'],
                'support_ids': ['P1', 'P2'], 'cutoff_year': '2024', 'engineering_checked': True,
            }]), encoding='utf-8')
            proc_leak = subprocess.run(
                [sys.executable, str(SCRIPTS / 'gap_pipeline.py'),
                 '--corpus', str(corpus_p), '--digests', str(digests_p), '--candidates', str(cands_p)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc_leak.returncode, 1)
            self.assertEqual(json.loads(proc_leak.stdout)['rejected_gaps'][0]['reason_code'], 'DROP_TEMPORAL_LEAK')

            cands_p.write_text(json.dumps([{
                'id': 'C_BADYR', 'claim': 'Bad year', 'cited_ids': ['P1', 'P2'],
                'support_ids': ['P1', 'P2'], 'cutoff_year': 'not_a_year', 'engineering_checked': True,
            }]), encoding='utf-8')
            proc_bad = subprocess.run(
                [sys.executable, str(SCRIPTS / 'gap_pipeline.py'),
                 '--corpus', str(corpus_p), '--digests', str(digests_p), '--candidates', str(cands_p)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc_bad.returncode, 2)
            self.assertIn('error', json.loads(proc_bad.stderr))

    def test_n4_n6_int_cutoff_date_json_error_and_long_id_compact_bounded(self):
        import tempfile
        _, digests = self._base_corpus_and_digests()
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            corpus_p, digests_p, cands_p = t / 'c.json', t / 'd.json', t / 'k.json'
            corpus_p.write_text(json.dumps([
                {'id': 'P1', 'source': 'openalex', 'family': 'same_problem', 'year': 2023, 'published_date': '2023-01-01', 'title': 'P1'},
                {'id': 'P2', 'source': 'arxiv', 'family': 'cross_setting_analogy', 'year': 2023, 'published_date': '2023-01-01', 'title': 'P2'},
            ]), encoding='utf-8')
            digests_p.write_text(json.dumps(digests), encoding='utf-8')
            cands_p.write_text(json.dumps([
                {'id': 'C1', 'claim': 'Test claim', 'cited_ids': ['P1', 'P2'], 'support_ids': ['P1', 'P2'],
                 'cutoff_date': 2024, 'engineering_checked': True}
            ]), encoding='utf-8')
            proc4 = subprocess.run(
                [sys.executable, str(SCRIPTS / 'gap_pipeline.py'),
                 '--corpus', str(corpus_p), '--digests', str(digests_p), '--candidates', str(cands_p)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc4.returncode, 2)
            self.assertIn('error', json.loads(proc4.stderr))

            cands_p.write_text(json.dumps([
                {'id': f'LONG_{i}_' + 'X' * 500, 'claim': f'Unread {i}', 'cited_ids': ['MISSING'], 'support_ids': ['MISSING']}
                for i in range(15)
            ]), encoding='utf-8')
            proc6 = subprocess.run(
                [sys.executable, str(SCRIPTS / 'gap_pipeline.py'),
                 '--corpus', str(corpus_p), '--digests', str(digests_p), '--candidates', str(cands_p), '--compact'],
                capture_output=True, text=True, check=False,
            )
            self.assertLess(len(proc6.stdout.encode('utf-8')), 4096)

    def test_r4_parsimony_empty_alias_pct_and_simplest_baseline_regression(self):
        corpus, digests = self._base_corpus_and_digests()
        for cid, extra in (
            ('R4_EMPTY_ALIAS', {'proposed_modules': [], 'components': ['M1', 'M2', 'M3']}),
            ('R4_PCT_ZERO', {
                'proposed_modules': ['M1', 'M2', 'M3'],
                'simplest_alternative': 'Tuned 2-layer GCN baseline 0.718 macro-F1 across 5 seeds.',
                'ablation_evidence': '0.00% macro-F1 over simplest baseline',
            }),
            ('R4_VS_TWO_WORD', {
                'proposed_modules': ['M1', 'M2', 'M3'],
                'simplest_alternative': 'Tuned 2-layer GCN baseline 0.750 macro-F1 across 5 seeds.',
                'ablation_evidence': 'proposed 0.70 vs simplest baseline 0.75 (+0.05 latency overhead)',
            }),
        ):
            cand = {
                'id': cid, 'claim': 'Rank fusion under shift', 'cited_ids': ['P1', 'P2'], 'support_ids': ['P1', 'P2'],
                'cutoff_year': 2026, 'sgha_critics_passed': True, 'engineering_checked': True, **extra,
            }
            out = gap_pipeline.run_pipeline('OOD fusion', corpus, digests, [cand])
            self.assertEqual(out['exit_code'], 1, cid)
            self.assertEqual(out['rejected_gaps'][0]['reason_code'], 'DROP_OVERCOMPLICATED', cid)

        ok_cand = {
            'id': 'R4_PCT_OK', 'claim': 'Rank fusion under shift', 'cited_ids': ['P1', 'P2'], 'support_ids': ['P1', 'P2'],
            'cutoff_year': 2026, 'sgha_critics_passed': True, 'engineering_checked': True,
            'proposed_modules': ['M1', 'M2', 'M3'],
            'simplest_alternative': 'Tuned 2-layer GCN baseline 0.718 macro-F1 across 5 seeds.',
            'ablation_evidence': '5.2% macro-F1 over simplest baseline',
        }
        ok_out = gap_pipeline.run_pipeline('OOD fusion', corpus, digests, [ok_cand])
        self.assertEqual(ok_out['exit_code'], 0, ok_out['rejected_gaps'])


if __name__ == '__main__':
    unittest.main()
