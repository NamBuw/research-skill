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

if __name__ == '__main__':
    unittest.main()
