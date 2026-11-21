"""API-shape and failure-state regression checks; no network calls."""
import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'research-scientist/scripts/search_papers.py'
spec = importlib.util.spec_from_file_location('search_papers', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class SearchTests(unittest.TestCase):
    def test_failure_is_not_zero_results(self):
        def fail(source, params):
            raise RuntimeError('http_429')
        r = module.search('graph methods', ('s2',), 2, 1, fail)
        self.assertEqual(r['sources']['s2']['status'], 'http_429')
        self.assertEqual(r['records'], [])

    def test_valid_empty_response_is_distinct(self):
        r = module.search('graph methods', ('s2',), 2, 1, lambda source, params: {'total': 0, 'data': []})
        self.assertEqual(r['sources']['s2']['status'], 'valid_zero_results')

    def test_bounded_result_and_doi_group(self):
        def data(source, params):
            if source == 'openalex':
                return {'meta': {'count': 10}, 'results': [{'id': 'W1', 'display_name': 'Paper A', 'doi': 'https://doi.org/10.1/A'}]}
            return {'message': {'total-results': 10, 'items': [{'DOI': '10.1/a', 'title': ['Paper A']}]}}
        r = module.search('graph methods', ('openalex', 'crossref'), 2, 1, data)
        self.assertEqual(r['sources']['openalex']['status'], 'bounded_partial')
        self.assertEqual(r['doi_duplicate_groups']['10.1/a'], [0, 1])

    def test_europepmc_uses_returned_cursor(self):
        cursors = []
        def transport(source, params):
            cursors.append(params['cursorMark'])
            index = len(cursors)
            return {'hitCount': 10, 'nextCursorMark': f'cursor-{index}',
                    'resultList': {'result': [{'source': 'MED', 'id': str(index), 'title': f'Paper {index}'}]}}
        r = module.search('graph methods', ('europepmc',), 1, 2, transport)
        self.assertEqual(cursors, ['*', 'cursor-1'])
        self.assertEqual(len({item['source_id'] for item in r['records']}), 2)

    def test_repeated_page_is_flagged_not_counted_twice(self):
        def transport(source, params):
            return {'meta': {'count': 10}, 'results': [{'id': 'W1', 'display_name': 'Paper A'}]}
        r = module.search('graph methods', ('openalex',), 1, 2, transport)
        self.assertEqual(r['sources']['openalex']['status'], 'repeated_page')
        self.assertEqual(len(r['records']), 1)

    def test_malformed_success_is_not_evidence_of_zero(self):
        r = module.search('graph methods', ('s2',), 2, 1, lambda source, params: {'error': 'service unavailable'})
        self.assertEqual(r['sources']['s2']['status'], 'missing_result_list')

    def test_arxiv_query_and_version_identity(self):
        params = module.request_params('arxiv', 'graph neural network', 2, 2)
        self.assertEqual(params['start'], 2)
        self.assertEqual(params['search_query'], 'all:graph AND all:neural AND all:network')
        r = module.search('graph neural network', ('arxiv',), 1, 1,
                          lambda source, params: {'total': 2, 'entries': [
                              {'id': 'https://arxiv.org/abs/2401.00001v2', 'title': 'Example', 'published': '2024-01-01'}]})
        self.assertEqual(r['records'][0]['source_id'], 'arxiv:2401.00001v2')
        self.assertEqual(r['sources']['arxiv']['status'], 'bounded_partial')

    def test_pubmed_page_and_doi(self):
        params = module.request_params('pubmed', 'graph methods', 2, 3)
        self.assertEqual(params['retstart'], 4)
        r = module.search('graph methods', ('pubmed',), 1, 1,
                          lambda source, params: {'total': 1, 'records': [
                              {'id': '123', 'title': 'Example', 'year': '2025 Aug', 'doi': '10.1/ABC'}]})
        self.assertEqual(r['records'][0]['source_id'], 'pmid:123')
        self.assertEqual(r['records'][0]['doi'], '10.1/abc')
        self.assertEqual(r['records'][0]['year'], 2025)

    def test_missing_total_is_unchecked(self):
        r = module.search('graph methods', ('arxiv',), 1, 1,
                          lambda source, params: {'entries': []})
        self.assertEqual(r['sources']['arxiv']['status'], 'missing_or_invalid_total')

    def test_source_specific_arxiv_query_is_sent_verbatim_and_logged(self):
        seen = []
        def transport(source, params):
            seen.append(params['search_query'])
            return {'total': 0, 'entries': []}
        r = module.search('generic query', ('arxiv',), 1, 1, transport,
                          source_queries={'arxiv': 'ti:graph AND abs:network'})
        self.assertEqual(seen, ['ti:graph AND abs:network'])
        self.assertEqual(r['sources']['arxiv']['executed_query'], seen[0])

if __name__ == '__main__':
    unittest.main()
