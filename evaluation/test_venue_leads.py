"""Bounded publication-source lead behavior, with mocked OpenAlex pages."""
import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'research-scientist/scripts/venue_leads.py'
spec = importlib.util.spec_from_file_location('venue_leads', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class VenueLeadTests(unittest.TestCase):
    def test_groups_source_and_preserves_work_ids(self):
        def transport(params):
            return {'meta': {'count': 2}, 'results': [
                {'id': 'W1', 'publication_year': 2024, 'primary_location': {'source': {'id': 'S1', 'display_name': 'Venue One', 'type': 'conference'}}},
                {'id': 'W2', 'publication_year': 2025, 'primary_location': {'source': {'id': 'S1', 'display_name': 'Venue One', 'type': 'conference'}}}]}
        r = module.collect('specific topic', page_size=2, transport=transport)
        self.assertEqual(r['status'], 'complete')
        self.assertEqual(r['source_leads'][0]['sample_count'], 2)
        self.assertEqual(r['source_leads'][0]['sample_year_range'], [2024, 2025])
        self.assertIn('Verify official current CFP', r['warning'])

    def test_repeated_page_is_not_counted_twice(self):
        def transport(params):
            return {'meta': {'count': 10}, 'results': [
                {'id': 'W1', 'primary_location': {'source': {'id': 'S1', 'display_name': 'One'}}}]}
        r = module.collect('topic', pages=2, page_size=1, transport=transport)
        self.assertEqual(r['status'], 'repeated_page')
        self.assertEqual(r['related_works_read_as_metadata'], 1)

    def test_failure_is_not_zero_results(self):
        def fail(params):
            raise RuntimeError('http_429')
        r = module.collect('topic', transport=fail)
        self.assertEqual(r['status'], 'http_429')

    def test_valid_zero_is_distinct(self):
        r = module.collect('topic', transport=lambda params: {'meta': {'count': 0}, 'results': []})
        self.assertEqual(r['status'], 'valid_zero_results')

if __name__ == '__main__':
    unittest.main()
