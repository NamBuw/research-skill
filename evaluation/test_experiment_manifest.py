"""Focused structural and comparability checks for experiment receipts."""
import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'research-scientist/scripts/check_experiment_manifest.py'
spec = importlib.util.spec_from_file_location('check_experiment_manifest', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

H = 'a' * 64

def fixture():
    base = {'run_id': 'b1', 'role': 'baseline', 'protocol_version': 'v1',
            'code_commit': 'abcd1234', 'data_version': 'd1',
            'split_manifest_sha256': H, 'metric_id': 'accuracy',
            'metric_script_sha256': H, 'command': 'python run.py',
            'started_at_utc': '2026-01-02T00:00:00Z',
            'ended_at_utc': '2026-01-02T01:00:00Z', 'exit_code': 0,
            'result_artifact_sha256': H, 'result_value': 0.5,
            'deviations': [], 'decision_timing': 'prespecified'}
    candidate = {**base, 'run_id': 'c1', 'role': 'candidate', 'result_value': 0.6}
    return {'question_id': 'RQ-1', 'protocol_version': 'v1',
            'protocol_frozen_at_utc': '2026-01-01T00:00:00Z',
            'runs': [base, candidate]}

class ExperimentManifestTests(unittest.TestCase):
    def test_matched_pair_is_structural_only(self):
        result = module.check(fixture())
        self.assertEqual(result['status'], 'structurally_checked')
        self.assertEqual(result['comparable_run_pairs'], [['b1', 'c1']])
        self.assertIn('does not read logs', result['disclaimer'])

    def test_split_mismatch_blocks_matched_pair(self):
        item = fixture()
        item['runs'][1]['split_manifest_sha256'] = 'b' * 64
        result = module.check(item)
        self.assertEqual(result['comparable_run_pairs'], [])
        self.assertEqual(result['comparison_status'], 'no_matched_successful_pair')
        self.assertTrue(any('mismatched' in x for x in result['warnings']))

    def test_failed_run_is_not_comparison(self):
        item = fixture()
        item['runs'][1]['exit_code'] = 1
        result = module.check(item)
        self.assertEqual(result['comparable_run_pairs'], [])
        self.assertEqual(result['comparison_status'], 'no_matched_successful_pair')

    def test_success_without_result_is_invalid(self):
        item = fixture()
        item['runs'][1]['result_value'] = None
        result = module.check(item)
        self.assertEqual(result['status'], 'invalid')

    def test_retrospective_protocol_is_invalid_as_prespecified(self):
        item = fixture()
        item['runs'][1]['started_at_utc'] = '2025-12-31T00:00:00Z'
        result = module.check(item)
        self.assertEqual(result['status'], 'invalid')
        self.assertTrue(any('later frozen protocol' in x for x in result['errors']))

    def test_verify_files_json_csv_sha256_and_tolerance(self):
        import csv
        import hashlib
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            split_p = t / 'splits.json'
            split_p.write_text('{"train":["S1"],"test":["S2"]}', encoding='utf-8')
            metric_p = t / 'metric.py'
            metric_p.write_text('def acc(): return 1', encoding='utf-8')
            base_csv = t / 'base.csv'
            with base_csv.open('w', newline='', encoding='utf-8') as fh:
                csv.writer(fh).writerows([['dataset', 'split', 'accuracy'], ['d1', 'test', '0.500']])
            cand_json = t / 'cand.json'
            cand_json.write_text(json.dumps({'accuracy': 0.6001}), encoding='utf-8')
            log_json = t / 'run.json'
            log_json.write_text(json.dumps({'run_id': 'c1', 'exit_code': 0, 'result_value': 0.6001}), encoding='utf-8')
            sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()

            man = fixture()
            man['runs'][0].update({
                'split_manifest_path': 'splits.json', 'split_manifest_sha256': sha(split_p),
                'metric_script_path': 'metric.py', 'metric_script_sha256': sha(metric_p),
                'result_artifact_path': 'base.csv', 'result_artifact_sha256': sha(base_csv),
                'result_value': 0.5,
            })
            man['runs'][1].update({
                'split_manifest_path': 'splits.json', 'split_manifest_sha256': sha(split_p),
                'metric_script_path': 'metric.py', 'metric_script_sha256': sha(metric_p),
                'result_artifact_path': 'cand.json', 'result_artifact_sha256': sha(cand_json),
                'run_log_path': 'run.json',
                'result_value': 0.6,
            })
            vf_ok = module.verify_files(man, base_dir=t, rel_tol=0.001, abs_tol=0.0005)
            self.assertTrue(vf_ok['files_verified'], vf_ok['file_errors'])

            man_bad = fixture()
            man_bad['runs'][1].update(man['runs'][1])
            man_bad['runs'][1]['result_value'] = 0.72
            vf_bad = module.verify_files(man_bad, base_dir=t)
            self.assertFalse(vf_bad['files_verified'])
            self.assertTrue(any('discrepancy' in e for e in vf_bad['file_errors']))

    def test_claims_comparison_and_audit_repo_completeness_and_compact(self):
        import json
        import subprocess
        import sys
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            man = fixture()
            claims = {'claims': [
                {'id': 'C1', 'metric': 'accuracy', 'value': 0.5},
                {'id': 'C2', 'metric': 'f1', 'value': 0.9},
            ]}
            comp = module.compare_claims(man, claims)
            self.assertEqual(comp['matched'], 1)
            self.assertEqual(comp['missing'], 1)

            repo = t / 'repo'
            repo.mkdir()
            (repo / 'README.md').write_text('contact: author@example.com\nhttps://github.com/user/proj\n', encoding='utf-8')
            rep = module.audit_repo_completeness(repo, blind='double')
            self.assertFalse(rep['complete'])
            self.assertIn('missing_dependencies_spec', rep['gaps'])
            self.assertTrue(any('email_detected' in x for x in rep['blind_leaks']))

            man_p = t / 'man.json'
            out_p = t / 'man_out.json'
            man_p.write_text(json.dumps(man), encoding='utf-8')
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), str(man_p), '--out', str(out_p), '--compact'],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertLess(len(proc.stdout.encode('utf-8')), 4096)
            self.assertTrue(json.loads(proc.stdout)['compact'])
            self.assertTrue(out_p.is_file())

    def test_c3_shared_multirow_csv_indexed_by_run_id(self):
        import csv
        import hashlib
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            shared_csv = t / 'shared_results.csv'
            with shared_csv.open('w', newline='', encoding='utf-8') as fh:
                csv.writer(fh).writerows([
                    ['run_id', 'macro_f1'],
                    ['b1', '0.45'],
                    ['c1', '0.61'],
                ])
            csv_sha = hashlib.sha256(shared_csv.read_bytes()).hexdigest()
            man = fixture()
            man['runs'][0].update({
                'metric_id': 'macro_f1',
                'result_artifact_path': 'shared_results.csv',
                'result_artifact_sha256': csv_sha,
                'result_value': 0.45,
            })
            man['runs'][1].update({
                'metric_id': 'macro_f1',
                'result_artifact_path': 'shared_results.csv',
                'result_artifact_sha256': csv_sha,
                'result_value': 0.61,
            })
            vf = module.verify_files(man, base_dir=t)
            self.assertTrue(vf['files_verified'], vf['file_errors'])
            claims = {'claims': [
                {'id': 'b1.macro_f1', 'metric': 'b1.macro_f1', 'value': 0.45},
                {'id': 'c1.macro_f1', 'metric': 'c1.macro_f1', 'value': 0.61},
            ]}
            comp = module.compare_claims(man, claims, base_dir=t)
            self.assertEqual(comp['matched'], 2, comp)
            self.assertEqual(comp['mismatched'], 0)

    def test_fresh_f4b_missing_run_id_in_explicit_run_id_csv_fails(self):
        import csv
        import hashlib
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            partial_csv = t / 'partial.csv'
            with partial_csv.open('w', newline='', encoding='utf-8') as fh:
                csv.writer(fh).writerows([['run_id', 'accuracy'], ['c1', '0.60']])
            csv_sha = hashlib.sha256(partial_csv.read_bytes()).hexdigest()
            man = fixture()
            man['runs'][0].update({
                'result_artifact_path': 'partial.csv',
                'result_artifact_sha256': csv_sha,
                'result_value': 0.60,
            })
            man['runs'][1].update({
                'result_artifact_path': 'partial.csv',
                'result_artifact_sha256': csv_sha,
                'result_value': 0.60,
            })
            vf = module.verify_files(man, base_dir=t)
            self.assertFalse(vf['files_verified'])
            self.assertTrue(any('b1: metric accuracy missing' in e for e in vf['file_errors']), vf['file_errors'])

    def test_r3_2_bug1_tall_csv_metric_integrity_and_case_insensitive_headers(self):
        import csv
        import hashlib
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            # Wrong metric (f1) must NOT certify metric_id='accuracy' via value/len(flat)==1 fallback
            for rows in (
                [['run_id', 'metric', 'value', 'epochs'], ['b1', 'f1', '0.50', '10'], ['c1', 'f1', '0.60', '10']],
                [['run_id', 'metric', 'value'], ['b1', 'f1', '0.50'], ['c1', 'f1', '0.60']],
            ):
                wrong_csv = t / 'wrong_metric.csv'
                with wrong_csv.open('w', newline='', encoding='utf-8') as fh:
                    csv.writer(fh).writerows(rows)
                sha = hashlib.sha256(wrong_csv.read_bytes()).hexdigest()
                man = fixture()
                for r in man['runs']:
                    r['result_artifact_path'] = 'wrong_metric.csv'
                    r['result_artifact_sha256'] = sha
                vf = module.verify_files(man, base_dir=t)
                self.assertFalse(vf['files_verified'], rows)
                self.assertTrue(any('metric accuracy missing' in e for e in vf['file_errors']), vf['file_errors'])

            # Capitalized tall CSV (Run_ID,Metric,Value,Epochs) must pass for matching metric
            cap_csv = t / 'cap_tall.csv'
            with cap_csv.open('w', newline='', encoding='utf-8') as fh:
                csv.writer(fh).writerows([
                    ['Run_ID', 'Metric', 'Value', 'Epochs'],
                    ['b1', 'accuracy', '0.50', '10'],
                    ['c1', 'accuracy', '0.60', '10'],
                ])
            cap_sha = hashlib.sha256(cap_csv.read_bytes()).hexdigest()
            man_ok = fixture()
            for r in man_ok['runs']:
                r['result_artifact_path'] = 'cap_tall.csv'
                r['result_artifact_sha256'] = cap_sha
            vf_ok = module.verify_files(man_ok, base_dir=t)
            self.assertTrue(vf_ok['files_verified'], vf_ok['file_errors'])

    def test_r3_2_bug2_compact_bounded_under_4096_bytes_on_long_errors(self):
        import json
        import subprocess
        import sys
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            man = fixture()
            man['runs'] = [
                {**man['runs'][0], 'run_id': f'run_{i}_' + 'R' * 900, 'result_artifact_path': 'missing_' + 'P' * 210 + '.json'}
                for i in range(6)
            ]
            mp = t / 'long_man.json'
            mp.write_text(json.dumps(man), encoding='utf-8')
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), str(mp), '--verify-files', '--compact'],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 2)
            self.assertLess(len(proc.stdout.encode('utf-8')), 4096)
            summary = json.loads(proc.stdout)
            self.assertTrue(summary['compact'])


if __name__ == '__main__':
    unittest.main()
