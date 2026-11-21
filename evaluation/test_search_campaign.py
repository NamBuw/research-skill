"""Offline campaign checks: retrieval bookkeeping, not literature recall."""
import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'research-scientist/scripts'
sys.path.insert(0, str(SCRIPTS))
import search_papers

spec = importlib.util.spec_from_file_location('search_campaign', SCRIPTS / 'search_campaign.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CampaignTests(unittest.TestCase):
    def test_positive_control_fails_strict_query_then_recovers(self):
        plan = {'question': 'Is the named GCN combination new?',
                'known_seeds': [{'source': 'arxiv', 'source_id': '1609.02907'}],
                'queries': [
                    {'id': 'strict', 'family': 'direct', 'query': 'semi supervised graph convolution normalized adjacency',
                     'sources': ['arxiv'], 'size': 10},
                    {'id': 'reformulated', 'family': 'mechanism', 'query': 'graph convolution',
                     'sources': ['arxiv'], 'size': 10, 'query_for': {'arxiv': 'ti:semi-supervised AND ti:graph'}}]}

        def transport(source, params):
            if params['search_query'].startswith('ti:'):
                return {'total': 1, 'entries': [{'id': 'https://arxiv.org/abs/1609.02907v4',
                                                 'title': 'Known paper'}]}
            return {'total': 1, 'entries': [{'id': 'https://arxiv.org/abs/2501.00001v1',
                                             'title': 'Other paper'}]}

        def fake_search(query, sources, size, pages, **kwargs):
            return search_papers.search(query, sources, size, pages, transport=transport, **kwargs)

        out = module.run_campaign(plan, fake_search)
        self.assertEqual(out['query_runs'][0]['sources']['arxiv']['status'], 'complete')
        self.assertEqual(out['query_runs'][0]['known_seed_checks'][0]['status'], 'not_retrieved_in_this_run')
        self.assertEqual(out['known_seed_checks'][0]['status'], 'retrieved')
        self.assertEqual(out['known_seed_checks'][0]['retrieved_in_query_ids'], ['reformulated'])
        self.assertEqual(out['coverage']['distinct_source_record_count'], 2)

    def test_repeated_records_keep_query_provenance_without_study_claim(self):
        plan = {'question': 'Find prior methods', 'known_seeds': [{'doi': '10.1/ABC'}],
                'queries': [{'id': 'q1', 'family': 'direct', 'query': 'method', 'sources': ['openalex', 'crossref']},
                            {'id': 'q2', 'family': 'closure', 'query': 'previous method', 'sources': ['openalex']} ]}

        def transport(source, params):
            if source == 'openalex':
                return {'meta': {'count': 1}, 'results': [{'id': 'https://openalex.org/W1',
                                                          'display_name': 'Paper A', 'doi': 'https://doi.org/10.1/abc'}]}
            return {'message': {'total-results': 1, 'items': [{'DOI': '10.1/ABC', 'title': ['Paper A']}]}}

        def fake_search(query, sources, size, pages, **kwargs):
            return search_papers.search(query, sources, size, pages, transport=transport, **kwargs)

        out = module.run_campaign(plan, fake_search)
        self.assertEqual(out['coverage']['raw_record_count'], 3)
        self.assertEqual(out['coverage']['distinct_source_record_count'], 2)
        self.assertEqual(out['source_records'][0]['discovered_by'], ['q1', 'q2'])
        self.assertEqual(len(out['doi_candidate_groups']['10.1/abc']), 2)
        self.assertEqual(out['known_seed_checks'][0]['status'], 'retrieved')

    def test_failed_and_unqueried_source_seeds_are_not_absence(self):
        plan = {'question': 'Find a known paper',
                'known_seeds': [{'source': 's2', 'source_id': 'abc'},
                                {'source': 'pubmed', 'source_id': 'pmid:1'}],
                'queries': [{'id': 'q1', 'family': 'direct', 'query': 'known paper', 'sources': ['s2']}]}

        def fake_search(query, sources, size, pages, **kwargs):
            return search_papers.search(query, sources, size, pages,
                                        transport=lambda source, params: (_ for _ in ()).throw(RuntimeError('http_429')),
                                        **kwargs)

        out = module.run_campaign(plan, fake_search)
        self.assertEqual([x['status'] for x in out['known_seed_checks']], ['source_unavailable', 'source_not_queried'])
        self.assertEqual(out['coverage']['failed_or_partial_source_runs'][0]['status'], 'rate_limited')
        self.assertEqual(out['query_runs'][0]['sources']['s2']['raw_status'], 'http_429')
        self.assertEqual(out['query_runs'][0]['sources']['s2']['http_status'], 429)

    def test_validation_rejects_duplicate_query_id(self):
        plan = {'question': 'Q', 'queries': [{'id': 'same', 'family': 'direct', 'query': 'A'},
                                            {'id': 'same', 'family': 'closure', 'query': 'B'}]}
        with self.assertRaisesRegex(ValueError, 'duplicate query id'):
            module.validate_plan(plan)

    def test_bounded_source_is_visible_in_coverage(self):
        plan = {'question': 'Q', 'queries': [{'id': 'q1', 'family': 'direct', 'query': 'A',
                                             'sources': ['openalex'], 'size': 1}]}

        def fake_search(query, sources, size, pages, **kwargs):
            return search_papers.search(query, sources, size, pages,
                                        transport=lambda source, params: {'meta': {'count': 100},
                                                                           'results': [{'id': 'W1', 'display_name': 'A'}]},
                                        **kwargs)

        out = module.run_campaign(plan, fake_search)
        self.assertEqual(out['coverage']['failed_or_partial_source_runs'],
                         [{'query_id': 'q1', 'source': 'openalex', 'status': 'bounded_partial'}])

    def test_bot_blocked_and_partial_failures_categorized_consistently(self):
        plan = {
            'question': 'Check coverage buckets',
            'queries': [
                {'id': 'q1', 'family': 'direct', 'query': 'graph learning', 'sources': ['dblp', 's2', 'openalex'], 'pages': 2, 'size': 1},
            ],
        }
        calls = {'oa': 0}

        def transport(source, params):
            if source == 'dblp':
                raise RuntimeError('bot_blocked')
            if source == 's2':
                raise RuntimeError('http_429')
            calls['oa'] += 1
            if calls['oa'] == 1:
                return {'meta': {'count': 10}, 'results': [{'id': 'W1', 'display_name': 'Hit 1'}]}
            raise RuntimeError('timeout')

        def fake_search(query, sources, size, pages, **kwargs):
            return search_papers.search(query, sources, size, pages, transport=transport, **kwargs)

        out = module.run_campaign(plan, fake_search)
        self.assertEqual(out['coverage']['bot_blocked_source_runs'],
                         [{'query_id': 'q1', 'source': 'dblp', 'status': 'bot_blocked'}])
        self.assertEqual(out['coverage']['rate_limited_source_runs'],
                         [{'query_id': 'q1', 'source': 's2', 'status': 'rate_limited'}])
        self.assertEqual(out['coverage']['failed_or_partial_source_runs'], [
            {'query_id': 'q1', 'source': 'dblp', 'status': 'bot_blocked'},
            {'query_id': 'q1', 'source': 's2', 'status': 'rate_limited'},
            {'query_id': 'q1', 'source': 'openalex', 'status': 'bounded_partial'},
        ])


if __name__ == '__main__':
    unittest.main()
