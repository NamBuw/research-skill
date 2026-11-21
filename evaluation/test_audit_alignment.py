"""Behavioral checks for the read-only ID/split diagnostic."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'research-scientist/scripts/audit_alignment.py'
spec = importlib.util.spec_from_file_location('audit_alignment', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class AlignmentAuditTests(unittest.TestCase):
    def test_same_records_sorted_differently_warn_on_positional_join(self):
        report = module.audit(['patient-b', 'patient-a'], ['patient-a', 'patient-b'])
        self.assertEqual(report['positionwise_id_mismatches'], 2)
        self.assertEqual(report['feature_ids_without_labels'], 0)
        self.assertNotIn('patient-a', str(report))

    def test_repeated_id_and_overlap_are_flags_not_leakage_verdict(self):
        report = module.audit(['a', 'a'], ['a'], {'a': {'train', 'test'}}, {'a': {'train'}})
        self.assertEqual(report['feature_duplicate_id_rows'], 1)
        self.assertEqual(report['feature_ids_in_multiple_splits'], 1)
        self.assertNotIn('leakage_confirmed', report)

    def test_blank_identifier_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'sample.csv'
            path.write_text('sample_id,split\n,train\n')
            with self.assertRaises(ValueError):
                module.load(path, 'sample_id', 'split')

if __name__ == '__main__':
    unittest.main()
