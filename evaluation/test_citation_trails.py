"""Bounded citation graph behavior without network calls."""
import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'research-scientist/scripts/citation_trails.py'
spec = importlib.util.spec_from_file_location('citation_trails', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class CitationTrailTests(unittest.TestCase):
    def test_partial_citation_list_is_explicit(self):
        def transport(url, params=None):
            if params is None:
                return {'display_name': 'Seed', 'referenced_works': ['https://openalex.org/W2']}
            return {'meta': {'count': 10}, 'results': [{'id': 'https://openalex.org/W3', 'display_name': 'Citing paper'}]}
        r = module.expand('W1', pages=1, page_size=1, transport=transport)
        self.assertEqual(r['backward_status'], 'retrieved_ids_not_full_reference_list')
        self.assertEqual(r['forward_status'], 'bounded_partial')

    def test_repeated_forward_page_is_not_counted_twice(self):
        def transport(url, params=None):
            if params is None:
                return {'referenced_works': []}
            return {'meta': {'count': 10}, 'results': [{'id': 'https://openalex.org/W3'}]}
        r = module.expand('W1', pages=2, page_size=1, transport=transport)
        self.assertEqual(r['forward_status'], 'repeated_page')
        self.assertEqual(len(r['forward_records']), 1)

    def test_failed_seed_does_not_hide_forward_results(self):
        def transport(url, params=None):
            if params is None:
                raise RuntimeError('http_429')
            return {'meta': {'count': 0}, 'results': []}
        r = module.expand('W1', transport=transport)
        self.assertEqual(r['backward_status'], 'http_429')
        self.assertEqual(r['forward_status'], 'valid_zero_results')

    def test_missing_total_is_not_a_complete_citation_search(self):
        def transport(url, params=None):
            if params is None:
                return {'referenced_works': []}
            return {'meta': {}, 'results': [{'id': 'https://openalex.org/W3'}]}
        r = module.expand('W1', transport=transport)
        self.assertEqual(r['forward_status'], 'missing_or_invalid_total')
        self.assertEqual(r['forward_records'], [])

    def test_id_validation(self):
        with self.assertRaises(ValueError):
            module.expand('../users')

if __name__ == '__main__':
    unittest.main()
