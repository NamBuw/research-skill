"""Regression checks for gap-record structure, not scientific gap truth."""
import copy
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('check_gap_record', ROOT / 'research-scientist/scripts/check_gap_record.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class GapRecordTests(unittest.TestCase):
    def setUp(self):
        self.record = json.loads((ROOT / 'research-scientist/references/gap-record.schema-example.json').read_text())

    def test_fixture_passes_with_warning_about_empty_counterevidence(self):
        report = module.check(self.record)
        self.assertTrue(report['valid_structure'])
        self.assertTrue(report['warnings'])

    def test_abstract_only_support_blocks_positive_gap(self):
        self.record['evidence'][0]['access'] = 'abstract'
        report = module.check(self.record)
        self.assertIn('candidates:G1:support_not_checked_in_full_text', report['errors'])

    def test_unread_closest_work_blocks_positive_gap(self):
        self.record['closest_works'][0]['access'] = 'abstract'
        report = module.check(self.record)
        self.assertIn('candidates:G1:closest_work_unread', report['errors'])

    def test_closest_work_flag_does_not_override_abstract_locator(self):
        self.record['evidence'][0]['access'] = 'abstract'
        report = module.check(self.record)
        self.assertIn('candidates:G1:closest_work_unread', report['errors'])

    def test_direct_precedent_conflicts_with_positive_gap(self):
        self.record['closest_works'][0]['relation'] = 'direct_precedent'
        report = module.check(self.record)
        self.assertIn('candidates:G1:direct_precedent_conflicts_with_positive_gap', report['errors'])

    def test_failed_kill_search_is_not_completed(self):
        self.record['queries'][1]['status'] = 'rate_limited'
        report = module.check(self.record)
        self.assertIn('candidates:G1:no_completed_kill_search', report['errors'])

    def test_future_work_quote_alone_does_not_promote_gap(self):
        self.record['evidence'][0]['role'] = 'author_future_work'
        report = module.check(self.record)
        self.assertIn('candidates:G1:author_future_work_alone_cannot_establish_gap', report['errors'])

    def test_unrelated_query_cannot_count_as_kill_search(self):
        self.record['queries'][1]['family'] = 'direct_problem'
        report = module.check(self.record)
        self.assertIn('candidates:G1:no_completed_kill_search', report['errors'])

    def test_uninspected_kill_search_hits_block_positive_gap(self):
        self.record['queries'][1]['inspected'] = 0
        report = module.check(self.record)
        self.assertIn('candidates:G1:kill_search_retrieved_records_unscreened', report['errors'])

    def test_closest_work_needs_source_locator(self):
        self.record['closest_works'][0]['evidence_ids'] = []
        report = module.check(self.record)
        self.assertIn('candidates:G1:closest_work_has_no_locator_evidence', report['errors'])

    def test_closest_work_evidence_must_identify_same_source(self):
        self.record['closest_works'][0]['source_id'] = 'DifferentStudy'
        report = module.check(self.record)
        self.assertIn('closest_works:W1:evidence_source_mismatch:E1', report['errors'])

    def test_single_index_needs_explicit_exception(self):
        self.record['queries'][1]['source'] = self.record['queries'][0]['source']
        report = module.check(self.record)
        self.assertIn('candidates:G1:single_source_or_query_family_without_exception', report['errors'])
        self.record['candidates'][0]['coverage_exception'] = 'Only one historical archive covers this bounded collection'
        second = module.check(self.record)
        self.assertTrue(second['valid_structure'])
        self.assertIn('candidates:G1:coverage_exception_requires_scientific_review', second['warnings'])

    def test_invalid_query_count_reports_error_instead_of_crashing(self):
        self.record['queries'][1]['retrieved'] = 'many'
        report = module.check(self.record)
        self.assertIn('queries:Q2:invalid_retrieved_count', report['errors'])

    def test_local_failure_needs_engineering_diagnosis(self):
        candidate = self.record['candidates'][0]
        candidate['trigger'] = 'failed_implementation'
        candidate['engineering_status'] = 'not_checked'
        report = module.check(self.record)
        self.assertIn('candidates:G1:engineering_failure_unresolved', report['errors'])

    def test_broken_evidence_link_is_rejected(self):
        self.record['candidates'][0]['support_evidence_ids'] = ['missing']
        report = module.check(self.record)
        self.assertIn('candidates:G1:support_evidence_ids:unknown_id:missing', report['errors'])

    def test_early_signal_does_not_require_positive_gap_gate(self):
        self.record['candidates'][0]['disposition'] = 'early_signal'
        self.record['evidence'][0]['access'] = 'abstract'
        self.record['queries'][1]['status'] = 'failed'
        self.assertTrue(module.check(self.record)['valid_structure'])


if __name__ == '__main__':
    unittest.main()
