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
        self.assertEqual(r['sources']['s2']['status'], 'rate_limited')
        self.assertEqual(r['sources']['s2']['status_category'], 'rate_limited')
        self.assertEqual(r['sources']['s2']['raw_status'], 'http_429')
        self.assertEqual(r['sources']['s2']['detail'], 'http_429')
        self.assertEqual(r['sources']['s2']['http_status'], 429)
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
        self.assertEqual(r['sources']['openalex']['status'], 'bounded_partial')
        self.assertEqual(r['sources']['openalex']['raw_status'], 'repeated_page')
        self.assertEqual(r['sources']['openalex']['detail'], 'repeated_page')
        self.assertEqual(len(r['records']), 1)

    def test_malformed_success_is_not_evidence_of_zero(self):
        r = module.search('graph methods', ('s2',), 2, 1, lambda source, params: {'error': 'service unavailable'})
        self.assertEqual(r['sources']['s2']['status'], 'source_failed')
        self.assertEqual(r['sources']['s2']['raw_status'], 'missing_result_list')
        self.assertEqual(r['sources']['s2']['detail'], 'missing_result_list')

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
        self.assertEqual(r['sources']['arxiv']['status'], 'source_failed')
        self.assertEqual(r['sources']['arxiv']['raw_status'], 'missing_or_invalid_total')
        self.assertEqual(r['sources']['arxiv']['detail'], 'missing_or_invalid_total')

    def test_source_specific_arxiv_query_is_sent_verbatim_and_logged(self):
        seen = []
        def transport(source, params):
            seen.append(params['search_query'])
            return {'total': 0, 'entries': []}
        r = module.search('generic query', ('arxiv',), 1, 1, transport,
                          source_queries={'arxiv': 'ti:graph AND abs:network'})
        self.assertEqual(seen, ['ti:graph AND abs:network'])
        self.assertEqual(r['sources']['arxiv']['executed_query'], seen[0])

    def test_known_seed_detects_restrictive_query_even_when_status_complete(self):
        def transport(source, params):
            if 'ti:' in params['search_query']:
                return {'total': 1, 'entries': [{'id': 'https://arxiv.org/abs/1609.02907v4',
                                                 'title': 'Semi-Supervised Classification with Graph Convolutional Networks'}]}
            return {'total': 0, 'entries': []}
        kwargs = {'known_source_ids': [('arxiv', 'arxiv:1609.02907')]}
        missed = module.search('semi supervised graph convolution normalized adjacency',
                               ('arxiv',), 10, 1, transport, **kwargs)
        self.assertEqual(missed['sources']['arxiv']['status'], 'valid_zero_results')
        self.assertEqual(missed['known_seed_checks'][0]['status'], 'not_retrieved_in_this_run')
        found = module.search('semi supervised graph convolution normalized adjacency',
                              ('arxiv',), 10, 1, transport,
                              source_queries={'arxiv': 'ti:semi-supervised AND ti:graph AND ti:convolutional'}, **kwargs)
        self.assertEqual(found['known_seed_checks'][0]['status'], 'retrieved')
        self.assertEqual(found['known_seed_checks'][0]['matched_source_ids'], ['arxiv:1609.02907v4'])

    def test_known_doi_matches_across_sources_and_failed_source_stays_unchecked(self):
        def transport(source, params):
            if source == 's2':
                raise RuntimeError('http_429')
            return {'meta': {'count': 1}, 'results': [{'id': 'https://openalex.org/W1',
                                                       'display_name': 'Known work',
                                                       'doi': 'https://doi.org/10.1000/ABC'}]}
        r = module.search('known work', ('s2', 'openalex'), 10, 1, transport,
                          known_dois=['https://doi.org/10.1000/abc'],
                          known_source_ids=[('s2', 'some-id'), ('openalex', 'W1')])
        self.assertEqual(r['known_seed_checks'][0]['status'], 'retrieved')
        self.assertEqual(r['known_seed_checks'][1]['source_status'], 'rate_limited')
        self.assertEqual(r['known_seed_checks'][1]['source_raw_status'], 'http_429')
        self.assertEqual(r['known_seed_checks'][1]['status'], 'not_retrieved_in_this_run')
        self.assertEqual(r['known_seed_checks'][2]['status'], 'retrieved')

    def test_v2_schema_openalex_inverted_index_and_require_abstract_default_false(self):
        seen_params = []

        def transport(source, params):
            seen_params.append(dict(params))
            return {
                'meta': {'count': 1},
                'results': [
                    {
                        'id': 'https://openalex.org/W2519887557',
                        'display_name': 'Semi-Supervised Classification with Graph Convolutional Networks',
                        'publication_year': 2016,
                        'doi': 'https://doi.org/10.48550/arxiv.1609.02907',
                        'is_retracted': False,
                        'abstract_inverted_index': {'Graph': [0], 'networks': [2], 'convolutional': [1]},
                    }
                ],
            }

        r_default = module.search('graph networks', ('openalex',), 10, 1, transport)
        self.assertEqual(r_default['schema'], 'research_scientist_search_v2')
        self.assertFalse(r_default['require_abstract'])
        self.assertNotIn('filter', seen_params[0])
        self.assertEqual(r_default['results'][0]['abstract'], 'Graph convolutional networks')
        self.assertEqual(r_default['results'][0]['arxiv_id'], '1609.02907')
        self.assertEqual(r_default['results'][0]['dedup_key'], 'arxiv:1609.02907')
        self.assertEqual(r_default['results'][0]['retraction_status'], 'clean')
        self.assertNotIn('similarity', r_default['results'][0])

        r_req = module.search('graph networks', ('openalex',), 10, 1, transport, require_abstract=True)
        self.assertTrue(r_req['require_abstract'])
        self.assertEqual(seen_params[1].get('filter'), 'has_abstract:true')

    def test_rate_limit_retry_after_recovery_and_exhaustion(self):
        import io
        from unittest.mock import patch
        from urllib.error import HTTPError

        class _FakeResp:
            def __init__(self, body: bytes, status=200, ct='application/json'):
                self._body = body
                self.status = status
                self.headers = {'Content-Type': ct}

            def read(self, n=-1):
                return self._body[:n] if n >= 0 else self._body

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        calls = {'n': 0}
        sleeps = []

        def fake_urlopen(req, timeout=20):
            calls['n'] += 1
            if calls['n'] == 1:
                raise HTTPError(req.full_url, 429, 'Too Many Requests', {'Retry-After': '2'}, io.BytesIO(b''))
            return _FakeResp(b'{"total": 1, "data": [{"paperId": "S1", "title": "Recovered Paper"}]}')

        with patch.object(module, 'urlopen', side_effect=fake_urlopen):
            data = module._read('https://api.example.test/search', {}, 10, max_retries=2, sleep_fn=sleeps.append)
        self.assertEqual(data['total'], 1)
        self.assertTrue(any(abs(s - 2.0) < 1e-6 for s in sleeps))

        # Exhaustion returns http_429 and status_category == rate_limited
        def always_429(req, timeout=20):
            raise HTTPError(req.full_url, 429, 'Too Many Requests', {'Retry-After': '1'}, io.BytesIO(b''))

        with patch.object(module, 'urlopen', side_effect=always_429):
            with self.assertRaisesRegex(RuntimeError, 'http_429'):
                module._read('https://api.example.test/search', {}, 10, max_retries=1, sleep_fn=lambda _: None)

        r = module.search('test query', ('s2',), 5, 1, lambda s, p: (_ for _ in ()).throw(RuntimeError('http_429')))
        self.assertEqual(r['sources']['s2']['status'], 'rate_limited')
        self.assertEqual(r['sources']['s2']['status_category'], 'rate_limited')
        self.assertEqual(r['sources']['s2']['raw_status'], 'http_429')
        self.assertEqual(r['sources']['s2']['detail'], 'http_429')
        self.assertEqual(r['sources']['s2']['http_status'], 429)

        # Multi-page partial failure with returned records -> bounded_partial; with 0 returned -> source_failed
        calls_partial = {'n': 0}

        def partial_500_with_hits(s, p):
            calls_partial['n'] += 1
            if calls_partial['n'] == 1:
                return {'total': 10, 'data': [{'paperId': 'S1', 'title': 'Page 1 Hit'}]}
            raise RuntimeError('http_500')

        r_partial = module.search('test query', ('s2',), 1, 2, partial_500_with_hits)
        self.assertEqual(r_partial['sources']['s2']['status'], 'bounded_partial')
        self.assertEqual(r_partial['sources']['s2']['raw_status'], 'partial_http_500')
        self.assertEqual(r_partial['sources']['s2']['http_status'], 500)

        calls_zero = {'n': 0}

        def partial_500_zero_hits(s, p):
            calls_zero['n'] += 1
            if calls_zero['n'] == 1:
                return {'total': 0, 'data': []}
            raise RuntimeError('http_500')

        r_zero_partial = module.search(
            'test query', ('s2',), 1, 1,
            partial_500_zero_hits,
            fanout_queries=['q1', 'q2'],
        )
        self.assertEqual(r_zero_partial['sources']['s2']['status'], 'source_failed')
        self.assertEqual(r_zero_partial['sources']['s2']['raw_status'], 'partial_http_500')
        self.assertEqual(r_zero_partial['sources']['s2']['http_status'], 500)

    def test_dblp_anubis_bot_blocked_and_json_parsing(self):
        self.assertTrue(module._is_bot_blocked(202, 'text/html; charset=utf-8', b'<title>Making sure you&#39;re not a bot!</title>'))
        r_blocked = module.search('graph networks', ('dblp',), 5, 1,
                                  lambda s, p: (_ for _ in ()).throw(RuntimeError('bot_blocked')))
        self.assertEqual(r_blocked['sources']['dblp']['status'], 'bot_blocked')
        self.assertEqual(r_blocked['sources']['dblp']['status_category'], 'bot_blocked')

        # Single-dict hit and multi-hit list parsing
        r_single = module.search('graph networks', ('dblp',), 5, 1, lambda s, p: {
            'result': {'hits': {'@total': '1', 'hit': {'info': {
                'key': 'journals/corr/abs-1609-02907',
                'title': {'#text': 'GCN Paper.'},
                'year': '2016',
                'authors': {'author': {'text': 'T. Kipf'}},
                'venue': 'CoRR',
            }}}}
        })
        self.assertEqual(len(r_single['records']), 1)
        self.assertEqual(r_single['records'][0]['title'], 'GCN Paper')
        self.assertTrue(r_single['records'][0]['preprint_only'])

    def test_huggingface_and_acl_adapters(self):
        hf_payload = [
            {
                'paper': {
                    'id': '2401.12345',
                    'title': 'HuggingFace Daily Paper',
                    'summary': 'Summary text here.',
                    'publishedAt': '2024-01-20T00:00:00Z',
                    'authors': [{'name': 'Alice'}],
                }
            }
        ]
        r_hf = module.search('daily paper', ('huggingface',), 5, 1, lambda s, p: hf_payload)
        self.assertEqual(r_hf['records'][0]['source_id'], 'hf:2401.12345')
        self.assertEqual(r_hf['records'][0]['arxiv_id'], '2401.12345')
        self.assertTrue(r_hf['records'][0]['preprint_only'])

        # ACL Crossref mode
        acl_cr = {'message': {'total-results': 1, 'items': [
            {'DOI': '10.18653/v1/2025.acl-long.1', 'title': ['ACL Paper'], 'published': {'date-parts': [[2025]]}}
        ]}}
        r_acl = module.search('acl paper', ('acl',), 5, 1, lambda s, p: acl_cr)
        self.assertEqual(r_acl['records'][0]['source_id'], 'acl:2025.acl-long.1')
        self.assertEqual(r_acl['records'][0]['pdf_url'], 'https://aclanthology.org/2025.acl-long.1.pdf')
        self.assertFalse(r_acl['records'][0]['preprint_only'])

        # ACL direct HTML parsing
        html_doc = (
            '<a href="/2025.acl-long.1/">EcomScriptBench Task</a>'
            '<div id="abstract-2025--acl-long--1">An inline ACL abstract.</div>'
        )
        parsed_html = module._parse_acl_html(html_doc, filter_query='ecomscriptbench')
        self.assertEqual(parsed_html['total'], 1)
        self.assertEqual(parsed_html['records'][0]['abstract'], 'An inline ACL abstract.')

    def test_vane_mode_routing_and_3_query_fanout_without_fake_similarity(self):
        seen_queries = []

        def transport(source, params):
            seen_queries.append(params['search'])
            return {'meta': {'count': 1}, 'results': [{'id': f'W{len(seen_queries)}', 'display_name': f'Paper {len(seen_queries)}'}]}

        r = module.search('semi-supervised graph neural-networks for node classification',
                          ('openalex',), 5, 1, transport, mode='quality')
        self.assertEqual(r['mode'], 'quality')
        self.assertEqual(len(r['executed_queries']), 3)
        self.assertEqual(len(seen_queries), 3)
        for item in r['results']:
            self.assertNotIn('similarity', item)
            self.assertEqual(item['ranking_basis'], 'provider_order')

    def test_fanout_quality_mode_preserves_bounded_partial_and_max_reported_total(self):
        # Case 1: Both variants return count=50, len=5 (size=5, pages=1)
        def transport_both_bounded(source, params):
            return {
                'meta': {'count': 50},
                'results': [
                    {'id': f'https://openalex.org/W{i}', 'display_name': f'Graph Paper {i}'}
                    for i in range(1, 6)
                ],
            }

        r1 = module.search('semi-supervised graph learning', ('openalex',), 5, 1,
                           transport=transport_both_bounded, mode='quality')
        self.assertEqual(r1['sources']['openalex']['status'], 'bounded_partial')
        self.assertEqual(r1['sources']['openalex']['status_category'], 'bounded_partial')
        self.assertEqual(r1['sources']['openalex']['reported_total'], 50)

        # Case 2: Variant 1 truncated (count=50, len=5), variant 2 returns 0 results (count=0, len=0)
        def transport_later_zero(source, params):
            if '-' in params['search']:
                return {
                    'meta': {'count': 50},
                    'results': [
                        {'id': f'https://openalex.org/W{i}', 'display_name': f'Graph Paper {i}'}
                        for i in range(1, 6)
                    ],
                }
            return {'meta': {'count': 0}, 'results': []}

        r2 = module.search('semi-supervised graph learning', ('openalex',), 5, 1,
                           transport=transport_later_zero, mode='quality')
        self.assertEqual(r2['sources']['openalex']['status'], 'bounded_partial')
        self.assertEqual(r2['sources']['openalex']['reported_total'], 50)

    def test_xml_entity_bomb_rejected_with_defusedxml(self):
        import io
        from unittest.mock import patch

        bomb = (
            b'<?xml version="1.0"?>'
            b'<!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;">]>'
            b'<feed><title>&lol2;</title></feed>'
        )

        class _FakeResp:
            status = 200
            headers = {'Content-Type': 'application/atom+xml'}

            def read(self, n=-1):
                return bomb

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch.object(module, 'urlopen', return_value=_FakeResp()):
            with self.assertRaisesRegex(RuntimeError, 'invalid_xml'):
                module._read('https://export.arxiv.org/api/query?search_query=all:test', {}, 10, xml=True, max_retries=0)

    def test_acl_direct_html_pages_gt_1_does_not_fail_with_repeated_page(self):
        calls = {'n': 0}

        def transport(source, params):
            calls['n'] += 1
            return {
                'records': [
                    {'id': f'2025.acl-long.{i}', 'title': f'ACL Paper {i}', 'year': 2025}
                    for i in range(1, 6)
                ],
                'total': 5,
                'html_kind': 'events',
            }

        r = module.search('event:acl-2025', ('acl',), 2, 2, transport=transport)
        self.assertEqual(calls['n'], 1)
        self.assertEqual(r['sources']['acl']['status'], 'complete')
        self.assertEqual(r['sources']['acl']['status_category'], 'complete')
        self.assertEqual(len(r['records']), 5)

    def test_dedup_normalizes_url_form_openalex_id_even_when_titles_differ(self):
        records = [
            {
                'source': 's2',
                'source_id': 's2_1',
                'title': 'Title A Unique One',
                'openalex_id': 'https://openalex.org/W777',
                'year': 2022,
            },
            {
                'source': 'openalex',
                'source_id': 'https://openalex.org/W777',
                'title': 'Title A Completely Different Variant',
                'year': 2022,
            },
        ]
        merged, groups = module.deduplicate_records(records)
        self.assertEqual(len(merged), 1)
        self.assertEqual(len(groups), 1)
        self.assertEqual(merged[0]['openalex_id'], 'W777')
        self.assertEqual(merged[0]['sources_seen'], ['s2', 'openalex'])

    def test_cli_compact_externalizes_full_payload_and_bounds_stdout(self):
        import json
        import subprocess
        import sys
        import tempfile

        long_abstract = 'word ' * 120
        oa_body = json.dumps({
            'meta': {'count': 1},
            'results': [{
                'id': 'https://openalex.org/W12345',
                'display_name': 'Compact Graph Paper',
                'publication_year': 2024,
                'doi': 'https://doi.org/10.1000/compact',
                'is_retracted': False,
                'abstract_inverted_index': {f'w{i}': [i] for i in range(80)},
            }],
        }).encode('utf-8')
        assert len(long_abstract) > 200

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / 'search_full.json'
            runner = (
                'import io, json, runpy, sys, urllib.request\n'
                'class _R:\n'
                '    status = 200\n'
                '    headers = {"Content-Type": "application/json"}\n'
                f'    def read(self, n=-1): return {oa_body!r}\n'
                '    def __enter__(self): return self\n'
                '    def __exit__(self, *a): return False\n'
                'urllib.request.urlopen = lambda req, timeout=20: _R()\n'
                f'sys.argv = [{str(SCRIPT)!r}, "graph", "--source", "openalex", "--out", {str(out_path)!r}, "--compact"]\n'
                f'runpy.run_path({str(SCRIPT)!r}, run_name="__main__")\n'
            )
            proc = subprocess.run([sys.executable, '-c', runner], capture_output=True, text=True, check=False)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            summary = json.loads(proc.stdout)
            self.assertTrue(summary['compact'])
            self.assertEqual(summary['schema'], 'research_scientist_search_v2')
            self.assertEqual(summary['artifact_path'], str(out_path.resolve()))
            self.assertEqual(summary['source_statuses'], {'openalex': 'complete'})
            self.assertEqual(summary['total_results'], 1)
            self.assertLessEqual(len(summary['top_results'][0]['abstract_preview']), 200)
            self.assertNotIn('records', summary)
            full_payload = json.loads(out_path.read_text(encoding='utf-8'))
            self.assertEqual(full_payload['schema'], 'research_scientist_search_v2')
            self.assertGreater(len(full_payload['results'][0]['abstract']), 200)

    def test_canonicalize_source_status_and_status_category_alignment(self):
        cases = [
            ('ok', 0, 'valid_zero_results'),
            ('ok', 5, 'complete'),
            ('OK', 2, 'complete'),
            ('cloudflare', 0, 'bot_blocked'),
            ('anubis', 0, 'bot_blocked'),
            ('bot_blocked_js', 0, 'bot_blocked'),
            ('bot_challenge_v2', 0, 'bot_blocked'),
            ('partial_bot_blocked', 2, 'bot_blocked'),
            ('partial_bot_blocked', 0, 'bot_blocked'),
            ('http_429', 0, 'rate_limited'),
            ('partial_http_429', 0, 'rate_limited'),
            ('partial_http_429', 3, 'rate_limited'),
            ('repeated_page', 2, 'bounded_partial'),
            ('missing_or_repeated_cursor', 2, 'bounded_partial'),
            ('truncated_api_cap', 2, 'bounded_partial'),
            ('partial_timeout', 3, 'bounded_partial'),
            ('partial_timeout', 0, 'source_failed'),
            ('partial_http_500', 2, 'bounded_partial'),
            ('partial_http_500', 0, 'source_failed'),
            ('http_403', 0, 'source_failed'),
            ('unimplemented', 0, 'source_failed'),
            ('error:connection_reset', 0, 'source_failed'),
        ]
        for raw, ret, expected in cases:
            self.assertEqual(module.canonicalize_source_status(raw, returned=ret), expected, (raw, ret))
            self.assertEqual(module.status_category(raw, returned=ret), expected, (raw, ret))
        self.assertEqual(module.status_category('ok'), 'complete')
        self.assertEqual(module.status_category('cloudflare'), 'bot_blocked')
        self.assertEqual(module.status_category('anubis'), 'bot_blocked')
        self.assertEqual(module.status_category('partial_timeout'), 'bounded_partial')
        self.assertEqual(module.status_category('partial_http_500'), 'bounded_partial')

    def test_read_detects_anubis_v1_and_cloudflare_js_challenge_as_bot_blocked(self):
        import io
        from unittest.mock import patch
        from urllib.error import HTTPError

        class _HtmlResp:
            def __init__(self, body: bytes, status=200, ct='text/html; charset=utf-8'):
                self._body = body
                self.status = status
                self.headers = {'Content-Type': ct}

            def read(self, n=-1):
                return self._body[:n] if n >= 0 else self._body

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        anubis_v1 = b'<html><script src="/.within.website/x/cmd/anubis/main.js"></script></html>'
        with patch.object(module, 'urlopen', return_value=_HtmlResp(anubis_v1)):
            with self.assertRaisesRegex(RuntimeError, '^bot_blocked$'):
                module._read('https://dblp.org/search/publ/api?q=graph', {}, 10, max_retries=0)

        anubis_chal = b'<html><body><div id="anubis_challenge">wait</div></body></html>'
        with patch.object(module, 'urlopen', return_value=_HtmlResp(anubis_chal)):
            with self.assertRaisesRegex(RuntimeError, '^bot_blocked$'):
                module._read('https://dblp.org/search/publ/api?q=graph', {}, 10, max_retries=0)

        cf_body = b'<html><head><title>Just a moment...</title></head><body><script>window._cf_chl_opt={};</script></body></html>'
        with patch.object(
            module,
            'urlopen',
            side_effect=HTTPError('https://api.example.test', 403, 'Forbidden', {'Content-Type': 'text/html'}, io.BytesIO(cf_body)),
        ):
            with self.assertRaisesRegex(RuntimeError, '^bot_blocked$'):
                module._read('https://api.example.test/search', {}, 10, max_retries=0)

        with patch.object(
            module,
            'urlopen',
            side_effect=HTTPError('https://api.example.test', 403, 'Forbidden', {'Content-Type': 'text/plain'}, io.BytesIO(b'Forbidden')),
        ):
            with self.assertRaisesRegex(RuntimeError, '^http_403$'):
                module._read('https://api.example.test/search', {}, 10, max_retries=0)

    def test_cli_out_oserror_exits_2_with_json_error_and_no_traceback(self):
        import json
        import subprocess
        import sys
        import tempfile

        oa_body = json.dumps({'meta': {'count': 0}, 'results': []}).encode('utf-8')
        with tempfile.TemporaryDirectory() as tmp:
            existing_dir = Path(tmp) / 'outdir'
            existing_dir.mkdir()
            art_dir = Path(tempfile.gettempdir()) / 'research_scientist_artifacts'
            before_artifacts = set(art_dir.glob('search_papers_*.json')) if art_dir.is_dir() else set()

            runner = (
                'import runpy, sys, urllib.request\n'
                'class _R:\n'
                '    status = 200\n'
                '    headers = {"Content-Type": "application/json"}\n'
                f'    def read(self, n=-1): return {oa_body!r}\n'
                '    def __enter__(self): return self\n'
                '    def __exit__(self, *a): return False\n'
                'urllib.request.urlopen = lambda req, timeout=20: _R()\n'
                f'sys.argv = [{str(SCRIPT)!r}, "graph", "--source", "openalex", "--out", {str(existing_dir)!r}, "--compact"]\n'
                f'runpy.run_path({str(SCRIPT)!r}, run_name="__main__")\n'
            )
            proc = subprocess.run([sys.executable, '-c', runner], capture_output=True, text=True, check=False)
            self.assertEqual(proc.returncode, 2)
            self.assertNotIn('Traceback', proc.stderr)
            err = json.loads(proc.stderr)
            self.assertIn('error', err)

            # Simulated OSError during write_text in --compact auto-artifact mode leaves no 0-byte orphan
            out_file = Path(tmp) / 'blocked.json'
            runner_perm = (
                'import pathlib, runpy, sys, urllib.request\n'
                'class _R:\n'
                '    status = 200\n'
                '    headers = {"Content-Type": "application/json"}\n'
                f'    def read(self, n=-1): return {oa_body!r}\n'
                '    def __enter__(self): return self\n'
                '    def __exit__(self, *a): return False\n'
                'urllib.request.urlopen = lambda req, timeout=20: _R()\n'
                'orig_write = pathlib.Path.write_text\n'
                'def _boom(self, *a, **kw):\n'
                '    if "research_scientist_artifacts" in str(self):\n'
                '        raise PermissionError("simulated write error")\n'
                '    return orig_write(self, *a, **kw)\n'
                'pathlib.Path.write_text = _boom\n'
                f'sys.argv = [{str(SCRIPT)!r}, "graph", "--source", "openalex", "--compact"]\n'
                f'runpy.run_path({str(SCRIPT)!r}, run_name="__main__")\n'
            )
            proc_perm = subprocess.run([sys.executable, '-c', runner_perm], capture_output=True, text=True, check=False)
            self.assertEqual(proc_perm.returncode, 2)
            self.assertNotIn('Traceback', proc_perm.stderr)
            self.assertIn('simulated write error', json.loads(proc_perm.stderr)['error'])
            self.assertFalse(out_file.exists())

            after_artifacts = set(art_dir.glob('search_papers_*.json')) if art_dir.is_dir() else set()
            self.assertEqual(after_artifacts - before_artifacts, set())


if __name__ == '__main__':
    unittest.main()
