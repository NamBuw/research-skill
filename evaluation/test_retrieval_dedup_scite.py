"""Offline tests for M2 F5 (4-ID/arXiv/title dedup + campaign Kipf&Welling merge) and F6 (citation_graph, fulltext_mining, scite, retractions)."""
from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'research-scientist/scripts'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name.removesuffix('.py'), SCRIPTS / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


search_papers = _load('search_papers.py')
search_campaign = _load('search_campaign.py')
citation_trails = _load('citation_trails.py')
citation_graph = _load('citation_graph.py')
fulltext_mining = _load('fulltext_mining.py')
resolve_fulltext = _load('resolve_fulltext.py')
check_gap_campaign = _load('check_gap_campaign.py')


class F5DedupAndCampaignTests(unittest.TestCase):
    def test_4id_and_bare_arxiv_transitive_dedup_and_collision_guard(self):
        records = [
            {
                'source': 'openalex',
                'source_id': 'https://openalex.org/W2519887557',
                'title': 'Semi-Supervised Classification with Graph Convolutional Networks',
                'year': 2016,
                'doi': '10.48550/arxiv.1609.02907',
                'preprint_only': True,
            },
            {
                'source': 'arxiv',
                'source_id': 'arxiv:1609.02907v4',
                'title': 'Semi-Supervised Classification with Graph Convolutional Networks',
                'year': 2016,
                'doi': None,
                'preprint_only': True,
            },
            # Distinct published DOIs with identical title must NOT merge
            {
                'source': 'crossref',
                'source_id': '10.1000/pub1',
                'title': 'Identical Long Benchmark Title Across Two Different Studies',
                'year': 2022,
                'doi': '10.1000/pub1',
                'preprint_only': False,
            },
            {
                'source': 'crossref',
                'source_id': '10.1000/pub2',
                'title': 'Identical Long Benchmark Title Across Two Different Studies',
                'year': 2022,
                'doi': '10.1000/pub2',
                'preprint_only': False,
            },
            # Title-only record must be retained as unresolved-keep
            {
                'source': 'dblp',
                'source_id': '',
                'title': 'Title Only Unpublished Manuscript Lead',
                'year': 2023,
                'doi': None,
                'dblp_key': None,
                'preprint_only': False,
            },
        ]
        # Remove dblp_key/source_id hint for title-only case
        records[4]['source'] = 'unknown'
        merged, groups = search_papers.deduplicate_records(records)
        self.assertEqual(len(merged), 4)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['dedup_key'], 'arxiv:1609.02907')
        self.assertEqual(groups[0]['member_count'], 2)
        gcn = merged[0]
        self.assertEqual(gcn['sources_seen'], ['openalex', 'arxiv'])
        self.assertTrue(gcn['preprint_only'])
        self.assertEqual(gcn['resolution'], 'resolved')
        # Published DOIs remain distinct
        pub_keys = {m['dedup_key'] for m in merged}
        self.assertIn('doi:10.1000/pub1', pub_keys)
        self.assertIn('doi:10.1000/pub2', pub_keys)
        # Title-only retained as unresolved-keep
        self.assertEqual(merged[-1]['resolution'], 'unresolved-keep')

    def test_preprint_upgraded_to_published_when_published_twin_present(self):
        records = [
            {'source': 'huggingface', 'source_id': 'hf:2301.00001', 'title': 'Sparse Attention Study',
             'year': 2023, 'doi': '10.48550/arxiv.2301.00001', 'arxiv_id': '2301.00001', 'preprint_only': True},
            {'source': 'acl', 'source_id': 'acl:2023.acl-long.5', 'title': 'Sparse Attention Study',
             'year': 2023, 'doi': '10.18653/v1/2023.acl-long.5', 'acl_id': '2023.acl-long.5', 'preprint_only': False},
        ]
        merged, groups = search_papers.deduplicate_records(records)
        self.assertEqual(len(merged), 1)
        self.assertFalse(merged[0]['preprint_only'])
        self.assertEqual(merged[0]['dedup_key'], 'doi:10.18653/v1/2023.acl-long.5')

    def test_campaign_merges_kipf_and_welling_across_queries_and_passes_check_gap_campaign(self):
        plan = {
            'question': 'Does normalized adjacency GCN already exist?',
            'known_seeds': [
                {'doi': '10.48550/arxiv.1609.02907'},
                {'source': 'arxiv', 'source_id': '1609.02907'},
            ],
            'queries': [
                {'id': 'direct-1', 'family': 'direct_problem', 'query': 'graph convolutional networks', 'sources': ['openalex'], 'size': 5},
                {'id': 'closure-1', 'family': 'closure', 'query': 'semi-supervised graph', 'sources': ['arxiv'], 'size': 5,
                 'query_for': {'arxiv': 'ti:semi-supervised AND ti:graph'}},
            ],
        }

        def transport(source, params):
            if source == 'openalex':
                return {'meta': {'count': 1}, 'results': [{
                    'id': 'https://openalex.org/W2519887557',
                    'display_name': 'Semi-Supervised Classification with Graph Convolutional Networks',
                    'publication_year': 2016,
                    'doi': 'https://doi.org/10.48550/arxiv.1609.02907',
                }]}
            return {'total': 1, 'entries': [{
                'id': 'https://arxiv.org/abs/1609.02907v4',
                'title': 'Semi-Supervised Classification with Graph Convolutional Networks',
                'published': '2016-09-09',
            }]}

        out = search_campaign.run_campaign(
            plan,
            lambda q, s, sz, pg, **kw: search_papers.search(q, s, sz, pg, transport=transport, **kw),
        )
        self.assertEqual(out['format'], 'research_scientist_search_campaign_v1')
        self.assertEqual(out['schema'], 'research_scientist_search_campaign_v1')
        self.assertEqual(out['coverage']['distinct_source_record_count'], 2)
        self.assertEqual(out['coverage']['deduplicated_paper_count'], 1)
        self.assertEqual(len(out['combined_results']), 1)
        self.assertEqual(len(out['dedup_groups']), 1)
        self.assertEqual(out['dedup_groups'][0]['dedup_key'], 'arxiv:1609.02907')
        self.assertEqual(out['combined_results'][0]['discovered_by'], ['direct-1', 'closure-1'])
        self.assertEqual(out['known_seed_checks'][0]['status'], 'retrieved')
        self.assertEqual(set(out['known_seed_checks'][0]['retrieved_in_query_ids']), {'direct-1', 'closure-1'})

    def test_gcn_fixture_replay_collapses_kipf_welling_and_check_gap_campaign_compatible(self):
        fixture_campaign = json.loads((ROOT / 'evaluation/fixtures/gcn-precedent-campaign.json').read_text(encoding='utf-8'))
        fixture_record = json.loads((ROOT / 'evaluation/fixtures/gcn-direct-precedent-record.json').read_text(encoding='utf-8'))
        merged, groups = search_papers.deduplicate_records(fixture_campaign['source_records'])
        self.assertLess(len(merged), len(fixture_campaign['source_records']))
        gcn_groups = [g for g in groups if g['dedup_key'] == 'arxiv:1609.02907']
        self.assertEqual(len(gcn_groups), 1)
        self.assertEqual(gcn_groups[0]['member_count'], 2)
        chk = check_gap_campaign.check(fixture_record, fixture_campaign)
        self.assertTrue(chk['valid_structure_and_manifest'], chk['errors'])


class F6CitationGraphTests(unittest.TestCase):
    def test_multi_seed_refs_cites_crossref_fallback_and_scipip_clustering(self):
        def oa_transport(url, params=None):
            if url.endswith('/W1'):
                return {'id': 'https://openalex.org/W1', 'title': 'Seed One', 'doi': '10.1/s1',
                        'publication_year': 2020, 'referenced_works': ['https://openalex.org/W10', 'https://openalex.org/W11']}
            if url.endswith('/W2'):
                # Empty referenced_works triggers Crossref fallback
                return {'id': 'https://openalex.org/W2', 'title': 'Seed Two', 'doi': '10.1/s2',
                        'publication_year': 2021, 'referenced_works': []}
            if params and str(params.get('filter', '')).startswith('doi:'):
                return {'results': [
                    {'id': 'https://openalex.org/W10', 'doi': '10.1/shared'},
                    {'id': 'https://openalex.org/W12', 'doi': '10.1/other'},
                ]}
            if params and str(params.get('filter', '')).startswith('cites:'):
                sid = params['filter'].split(':', 1)[1]
                if sid == 'W1':
                    return {'meta': {'count': 1}, 'results': [
                        {'id': 'https://openalex.org/W20', 'title': 'Graph Attention Extension', 'publication_year': 2022, 'cited_by_count': 50}
                    ]}
                return {'meta': {'count': 1}, 'results': [
                    {'id': 'https://openalex.org/W20', 'title': 'Graph Attention Extension', 'publication_year': 2022, 'cited_by_count': 50}
                ]}
            if params and str(params.get('filter', '')).startswith('ids.openalex:'):
                return {'results': [
                    {'id': 'https://openalex.org/W10', 'title': 'Graph Convolution Core', 'publication_year': 2017, 'cited_by_count': 900},
                    {'id': 'https://openalex.org/W11', 'title': 'Graph Convolution Variant', 'publication_year': 2018, 'cited_by_count': 10},
                    {'id': 'https://openalex.org/W12', 'title': 'Unrelated Domain Survey', 'publication_year': 2019, 'cited_by_count': 20},
                ]}
            raise RuntimeError('http_404')

        def cr_transport(url, params=None):
            return {'message': {'reference': [{'DOI': '10.1/shared'}, {'DOI': '10.1/other'}]}}

        res = citation_graph.build_citation_graph(
            ['W1', 'W2'], direction='both', top=10, min_overlap=1,
            similarity_threshold=0.2, cluster_diverse=True,
            oa_transport=oa_transport, cr_transport=cr_transport,
        )
        self.assertEqual(res['schema'], 'research_scientist_citation_graph_v1')
        self.assertEqual(res['status'], 'COMPLETE')
        self.assertEqual(res['providers']['crossref_fallback'], 'used')
        # W10 and W20 have seed_overlap_count == 2; W10 has higher global_citations (900 vs 50)
        overlaps = {r['openalex_id']: r['seed_overlap_count'] for r in res['results']}
        self.assertEqual(overlaps['W10'], 2)
        self.assertEqual(overlaps['W20'], 2)
        self.assertEqual(overlaps['W11'], 1)
        self.assertGreaterEqual(len(res['clusters']), 1)

    def test_partial_status_on_unresolved_seed_or_capped_cites(self):
        def oa_transport(url, params=None):
            if url.endswith('/W1'):
                return {'id': 'https://openalex.org/W1', 'title': 'Seed One', 'referenced_works': []}
            if url.endswith('/W999'):
                raise RuntimeError('http_404')
            if params and str(params.get('filter', '')).startswith('cites:'):
                return {'meta': {'count': 200}, 'results': [
                    {'id': 'https://openalex.org/W5', 'title': 'Citing Paper', 'cited_by_count': 5}
                ]}
            return {'results': []}

        res = citation_graph.build_citation_graph(['W1', 'W999'], direction='cites', oa_transport=oa_transport)
        self.assertEqual(res['status'], 'PARTIAL')
        self.assertEqual(len(res['seeds_unresolved']), 1)
        self.assertTrue(any('cites_capped' in r for r in res['partial_reasons']))

    def test_scipip_union_find_and_can_merge(self):
        uf = citation_graph.UnionFind(3)
        sim = [
            [1.0, 0.8, 0.1],
            [0.8, 1.0, 0.9],
            [0.1, 0.9, 1.0],
        ]
        self.assertTrue(citation_graph.can_merge(uf, sim, 0, 1, 0.5))
        uf.union(0, 1)
        # Complete-linkage forbids merging {0,1} with {2} because sim[0][2]=0.1 < 0.5
        self.assertFalse(citation_graph.can_merge(uf, sim, 1, 2, 0.5))

    def test_cli_seeds_file_and_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            seeds_file = Path(tmp) / 'seeds.json'
            out_file = Path(tmp) / 'graph.json'
            seeds_file.write_text('[]', encoding='utf-8')
            proc = subprocess.run(
                [sys.executable, str(SCRIPTS / 'citation_graph.py'), '--seeds', str(seeds_file), '--out', str(out_file)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 2)


class F6CitationTrailsAndResolveTests(unittest.TestCase):
    def test_citation_trails_429_backoff_recovery_and_exhaustion(self):
        class _FakeResp:
            def __init__(self, body: bytes):
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        calls = {'n': 0}
        sleeps = []

        def fake_urlopen(req, timeout=20):
            calls['n'] += 1
            if calls['n'] == 1:
                raise HTTPError(req.full_url, 429, 'Too Many Requests', {'Retry-After': '1'}, io.BytesIO(b''))
            return _FakeResp(b'{"id": "https://openalex.org/W1", "referenced_works": []}')

        with patch.object(citation_trails, 'urlopen', side_effect=fake_urlopen):
            data = citation_trails.polite_get('https://api.openalex.org/works/W1', max_retries=2, sleep_fn=sleeps.append)
        self.assertEqual(data['id'], 'https://openalex.org/W1')
        self.assertTrue(any(abs(s - 1.0) < 1e-6 for s in sleeps))

        def always_429(req, timeout=20):
            raise HTTPError(req.full_url, 429, 'Too Many Requests', {'Retry-After': '1'}, io.BytesIO(b''))

        with patch.object(citation_trails, 'urlopen', side_effect=always_429):
            with self.assertRaisesRegex(RuntimeError, 'http_429'):
                citation_trails.polite_get('https://api.openalex.org/works/W1', max_retries=1, sleep_fn=lambda _: None)

    def test_resolve_fulltext_extracts_pmcid_jats_url_and_is_retracted(self):
        work = {
            'id': 'https://openalex.org/W2976826629',
            'doi': 'https://doi.org/10.1177/1758835919874651',
            'title': 'Sample Work',
            'publication_year': 2019,
            'is_retracted': True,
            'ids': {'pmcid': 'https://pmc.ncbi.nlm.nih.gov/articles/PMC13771371/'},
            'open_access': {'oa_status': 'gold'},
            'best_oa_location': None,
            'primary_location': None,
            'locations': [],
        }
        res = resolve_fulltext.resolve('10.1177/1758835919874651', lambda _: work)
        self.assertEqual(res['work']['pmcid'], 'PMC13771371')
        self.assertTrue(res['work']['is_retracted'])
        self.assertEqual(res['jats_xml_url'], 'https://www.ebi.ac.uk/europepmc/webservices/rest/PMC13771371/fullTextXML')


class F6FulltextMiningTests(unittest.TestCase):
    def test_jats_xml_extraction_nested_discussion_limitations_and_entity_bomb_rejection(self):
        jats = """<!DOCTYPE article PUBLIC "-//NLM//DTD JATS//EN" "JATS.dtd">
        <article><body>
          <sec sec-type="methods"><title>Methods</title><p>Method details ignored.</p></sec>
          <sec sec-type="discussion"><title>Discussion</title>
            <p>Our main discussion finding shows improved calibration.</p>
            <sec sec-type="limitations"><title>Limitations</title>
              <p>A key limitation is that this method does not scale beyond 10k nodes.</p>
            </sec>
            <sec><title>Future Work</title>
              <p>Future work will address sparse graphs.</p>
            </sec>
          </sec>
        </body><back><ref-list><ref><mixed-citation>Ref 1</mixed-citation></ref></ref-list></back></article>"""
        parsed = fulltext_mining.extract_jats_sections(jats)
        self.assertEqual(parsed['status'], 'ok')
        self.assertTrue(parsed['sections']['Discussion'])
        self.assertTrue(parsed['sections']['Limitations'])
        self.assertTrue(parsed['sections']['Future Work'])
        self.assertNotIn('Method details ignored', ' '.join(parsed['sections']['Discussion']))
        self.assertNotIn('does not scale beyond 10k nodes', ' '.join(parsed['sections']['Discussion']))
        self.assertTrue(parsed['admission_sentences'])

        # Hostile XML entity expansion must fail safely
        bomb = """<?xml version="1.0"?>
        <!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;">]>
        <article><body><sec><title>Discussion</title><p>&lol2;</p></sec></body></article>"""
        bad = fulltext_mining.extract_jats_sections(bomb)
        self.assertEqual(bad['status'], 'xml_parse_error')

    def test_pdf_slice_fallback_extracts_discussion_and_limitations_before_references(self):
        try:
            import fitz
        except ImportError:
            self.skipTest('PyMuPDF not installed')
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / 'paper.pdf'
            with fitz.open() as doc:
                page = doc.new_page()
                page.insert_text(
                    (72, 72),
                    '1. Introduction\nBackground text.\n\n'
                    '4. Discussion\nWe observed consistent calibration improvements across benchmarks.\n\n'
                    '4.1 Limitations\nOur approach cannot handle dynamic graphs and remains open for future work.\n\n'
                    'References\n[1] Doe et al. 2020.',
                )
                doc.save(pdf_path)
            res = fulltext_mining.extract_pdf_sections(pdf_path)
            self.assertEqual(res['status'], 'ok')
            self.assertIn('consistent calibration', ' '.join(res['sections']['Discussion']))
            self.assertIn('cannot handle dynamic graphs', ' '.join(res['sections']['Limitations']))
            self.assertNotIn('Doe et al.', ' '.join(res['sections']['Limitations']))

    def test_scite_tallies_states(self):
        ok = fulltext_mining.fetch_scite_tallies(
            '10.1038/s41586-021-03819-2',
            transport=lambda url, headers=None: {'supporting': 10, 'mentioning': 50, 'contradicting': 2, 'total': 62, 'citingPublications': 60},
        )
        self.assertEqual(ok['status'], 'ok')
        self.assertEqual(ok['supporting'], 10)
        self.assertEqual(ok['contradicting'], 2)

        nf = fulltext_mining.fetch_scite_tallies('10.1/missing', transport=lambda u, headers=None: (_ for _ in ()).throw(RuntimeError('not_found')))
        self.assertEqual(nf['status'], 'not_found')
        self.assertIsNone(nf['supporting'])

        rl = fulltext_mining.fetch_scite_tallies('10.1/rl', transport=lambda u, headers=None: (_ for _ in ()).throw(RuntimeError('rate_limited')))
        self.assertEqual(rl['status'], 'rate_limited')
        self.assertIsNone(rl['total'])

        no_doi = fulltext_mining.fetch_scite_tallies(None)
        self.assertEqual(no_doi['status'], 'no_doi')

    def test_retraction_strict_invariant_errors_never_return_clean(self):
        # Crossref updated-by retraction
        r1 = fulltext_mining.check_retraction(
            '10.1/ret',
            cr_transport=lambda u: {'message': {'updated-by': [{'type': 'retraction', 'DOI': '10.1/notice'}]}},
            oa_transport=lambda u: {'id': 'https://openalex.org/W1', 'is_retracted': False},
        )
        self.assertEqual(r1['status'], 'retracted')

        # OpenAlex is_retracted True when Crossref 404s
        r2 = fulltext_mining.check_retraction(
            '10.48550/arxiv.1234.5678',
            cr_transport=lambda u: (_ for _ in ()).throw(RuntimeError('not_found')),
            oa_transport=lambda u: {'id': 'https://openalex.org/W2', 'is_retracted': True},
        )
        self.assertEqual(r2['status'], 'retracted')

        # Retraction Watch CSV
        with tempfile.TemporaryDirectory() as tmp:
            csv_p = Path(tmp) / 'rw.csv'
            csv_p.write_text('OriginalPaperDOI,RetractionDOI,RetractionNature\n10.1/csvret,10.1/not,Retraction\n', encoding='utf-8')
            csv_set = fulltext_mining.load_retraction_csv(csv_p)
        r3 = fulltext_mining.check_retraction('10.1/csvret', retraction_csv_set=csv_set)
        self.assertEqual(r3['status'], 'retracted')

        # Clean only on explicit valid 200
        r_clean = fulltext_mining.check_retraction(
            '10.1/clean',
            cr_transport=lambda u: {'message': {'DOI': '10.1/clean', 'type': 'journal-article'}},
            oa_transport=lambda u: {'id': 'https://openalex.org/W3', 'is_retracted': False},
        )
        self.assertEqual(r_clean['status'], 'clean')

        # Strict invariant: ANY error, 429, 500, invalid_json, or missing DOI -> unchecked (NEVER clean)
        for err in ('rate_limited', 'http_500', 'network_failure', 'invalid_json'):
            r_err = fulltext_mining.check_retraction(
                '10.1/err',
                cr_transport=lambda u, e=err: (_ for _ in ()).throw(RuntimeError(e)),
                oa_transport=lambda u: {'id': 'https://openalex.org/W3', 'is_retracted': False},
            )
            self.assertEqual(r_err['status'], 'unchecked', f'Error {err} must yield unchecked')
        self.assertEqual(fulltext_mining.check_retraction('')['status'], 'unchecked')
        self.assertEqual(fulltext_mining.check_retraction(None)['status'], 'unchecked')

    def test_check_retraction_requires_bool_is_retracted_when_crossref_404s(self):
        # Missing is_retracted when Crossref 404s MUST yield 'unchecked', never 'clean'
        res_missing = fulltext_mining.check_retraction(
            '10.1/test',
            cr_transport=lambda u: (_ for _ in ()).throw(RuntimeError('not_found')),
            oa_transport=lambda u: {'id': 'https://openalex.org/W1'},
        )
        self.assertEqual(res_missing['status'], 'unchecked')

        # Explicit is_retracted: False when Crossref 404s yields 'clean'
        res_false = fulltext_mining.check_retraction(
            '10.1/test',
            cr_transport=lambda u: (_ for _ in ()).throw(RuntimeError('not_found')),
            oa_transport=lambda u: {'id': 'https://openalex.org/W1', 'is_retracted': False},
        )
        self.assertEqual(res_false['status'], 'clean')

    def test_citation_graph_crossref_fallback_partial_is_not_overwritten_by_later_seed(self):
        def oa_transport(url, params=None):
            if url.endswith('/W1'):
                return {'id': 'https://openalex.org/W1', 'title': 'Seed 1', 'doi': '10.1/s1', 'referenced_works': []}
            if url.endswith('/W2'):
                return {'id': 'https://openalex.org/W2', 'title': 'Seed 2', 'doi': '10.1/s2', 'referenced_works': []}
            if params and str(params.get('filter', '')).startswith('doi:'):
                return {'results': [{'id': 'https://openalex.org/W10', 'doi': '10.1/r2'}]}
            if params and str(params.get('filter', '')).startswith('ids.openalex:'):
                return {'results': [{'id': 'https://openalex.org/W10', 'title': 'Ref 2', 'publication_year': 2020, 'cited_by_count': 5}]}
            raise RuntimeError('http_404')

        def cr_transport(url, params=None):
            if '10.1%2Fs1' in url or '10.1/s1' in url:
                raise RuntimeError('http_500')
            return {'message': {'reference': [{'DOI': '10.1/r2'}]}}

        res = citation_graph.build_citation_graph(
            ['W1', 'W2'], direction='refs', oa_transport=oa_transport, cr_transport=cr_transport
        )
        self.assertEqual(res['status'], 'PARTIAL')
        self.assertEqual(res['providers']['crossref_fallback'], 'partial')

    def test_f20_compact_cli_for_campaign_citation_graph_and_fulltext_mining(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            # 1. fulltext_mining.py --pdfs <pdf> --compact (real subprocess, no network)
            try:
                import fitz
            except ImportError:
                self.skipTest('PyMuPDF not installed')
            pdf_path = root / 'paper.pdf'
            with fitz.open() as doc:
                page = doc.new_page()
                page.insert_text(
                    (72, 72),
                    '1. Introduction\nBackground text.\n\n'
                    '4. Discussion\n' + ('Calibration finding details. ' * 25) + '\n\n'
                    '4.1 Limitations\nA key limitation is that this method cannot handle dynamic graphs.\n\n'
                    'References\n[1] Doe 2020.',
                )
                doc.save(pdf_path)

            ft_out = root / 'mining_full.json'
            proc_ft = subprocess.run(
                [sys.executable, str(SCRIPTS / 'fulltext_mining.py'), '--pdfs', str(pdf_path), '--out', str(ft_out), '--compact'],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc_ft.returncode, 0, proc_ft.stderr)
            ft_summary = json.loads(proc_ft.stdout)
            self.assertTrue(ft_summary['compact'])
            self.assertEqual(ft_summary['artifact_path'], str(ft_out.resolve()))
            self.assertNotIn('sections', ft_summary['items'][0])
            self.assertIn('section_char_counts', ft_summary['items'][0])
            self.assertGreater(ft_summary['items'][0]['section_char_counts']['Discussion'], 100)
            self.assertGreaterEqual(ft_summary['items'][0]['admission_sentence_count'], 1)
            ft_full = json.loads(ft_out.read_text(encoding='utf-8'))
            self.assertIn('sections', ft_full['items'][0])

            # 2. search_campaign.py --compact (subprocess with local HTTP mock)
            plan_path = root / 'plan.json'
            camp_out = root / 'campaign_full.json'
            plan_path.write_text(json.dumps({
                'question': 'Graph learning?',
                'queries': [{'id': 'q1', 'family': 'direct', 'query': 'graph', 'sources': ['openalex'], 'size': 2}],
                'known_seeds': [{'doi': '10.1000/camp'}],
            }), encoding='utf-8')
            oa_resp = json.dumps({
                'meta': {'count': 1},
                'results': [{
                    'id': 'https://openalex.org/W555',
                    'display_name': 'Campaign Paper',
                    'publication_year': 2023,
                    'doi': 'https://doi.org/10.1000/camp',
                    'abstract_inverted_index': {f'tok{i}': [i] for i in range(60)},
                }],
            }).encode('utf-8')
            camp_runner = (
                'import runpy, sys, urllib.request\n'
                'class _R:\n'
                '    status = 200\n'
                '    headers = {"Content-Type": "application/json"}\n'
                f'    def read(self, n=-1): return {oa_resp!r}\n'
                '    def __enter__(self): return self\n'
                '    def __exit__(self, *a): return False\n'
                'urllib.request.urlopen = lambda req, timeout=20: _R()\n'
                f'sys.argv = [{str(SCRIPTS / "search_campaign.py")!r}, {str(plan_path)!r}, "--out", {str(camp_out)!r}, "--compact"]\n'
                f'runpy.run_path({str(SCRIPTS / "search_campaign.py")!r}, run_name="__main__")\n'
            )
            proc_camp = subprocess.run([sys.executable, '-c', camp_runner], capture_output=True, text=True, check=False)
            self.assertEqual(proc_camp.returncode, 0, proc_camp.stderr)
            camp_summary = json.loads(proc_camp.stdout)
            self.assertTrue(camp_summary['compact'])
            self.assertEqual(camp_summary['schema'], 'research_scientist_search_campaign_v1')
            self.assertEqual(camp_summary['artifact_path'], str(camp_out.resolve()))
            self.assertEqual(camp_summary['queries_count'], 1)
            self.assertEqual(camp_summary['combined_results_count'], 1)
            self.assertLessEqual(len(camp_summary['top_results'][0]['abstract_preview']), 200)
            self.assertNotIn('source_records', camp_summary)
            self.assertTrue(camp_out.is_file())

            # 3. citation_graph.py --compact (subprocess with local HTTP mock)
            cg_out = root / 'graph_full.json'
            cg_seed = json.dumps({
                'id': 'https://openalex.org/W1',
                'title': 'Seed Paper',
                'doi': '10.1/s1',
                'publication_year': 2020,
                'referenced_works': ['https://openalex.org/W10'],
            }).encode('utf-8')
            cg_batch = json.dumps({
                'results': [{
                    'id': 'https://openalex.org/W10',
                    'title': 'Neighbor Paper',
                    'publication_year': 2019,
                    'cited_by_count': 42,
                }]
            }).encode('utf-8')
            cg_runner = (
                'import io, runpy, sys, urllib.request\n'
                'class _R:\n'
                '    def __init__(self, b): self.b = b\n'
                '    def read(self, n=-1): return self.b\n'
                '    def __enter__(self): return self\n'
                '    def __exit__(self, *a): return False\n'
                'def fake_open(req, timeout=20):\n'
                '    u = req.full_url\n'
                f'    if "/works/W1" in u: return _R({cg_seed!r})\n'
                f'    return _R({cg_batch!r})\n'
                'urllib.request.urlopen = fake_open\n'
                f'sys.argv = [{str(SCRIPTS / "citation_graph.py")!r}, "--seed", "W1", "--direction", "refs", "--out", {str(cg_out)!r}, "--compact"]\n'
                f'runpy.run_path({str(SCRIPTS / "citation_graph.py")!r}, run_name="__main__")\n'
            )
            proc_cg = subprocess.run([sys.executable, '-c', cg_runner], capture_output=True, text=True, check=False)
            self.assertEqual(proc_cg.returncode, 0, proc_cg.stderr)
            cg_summary = json.loads(proc_cg.stdout)
            self.assertTrue(cg_summary['compact'])
            self.assertEqual(cg_summary['schema'], 'research_scientist_citation_graph_v1')
            self.assertEqual(cg_summary['artifact_path'], str(cg_out.resolve()))
            self.assertEqual(cg_summary['status'], 'COMPLETE')
            self.assertEqual(cg_summary['neighbors_total'], 1)
            self.assertEqual(cg_summary['top_neighbors'][0]['openalex_id'], 'W10')
            self.assertNotIn('results', cg_summary)
            self.assertTrue(cg_out.is_file())


if __name__ == '__main__':
    unittest.main()
