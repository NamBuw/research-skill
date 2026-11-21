"""Offline checks for OA metadata and PDF delivery states."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'research-scientist/scripts/resolve_fulltext.py'
spec = importlib.util.spec_from_file_location('resolve_fulltext', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FullTextTests(unittest.TestCase):
    def work(self):
        return {'id': 'https://openalex.org/W2519887557',
                'doi': 'https://doi.org/10.48550/arxiv.1609.02907', 'title': 'Known GCN paper',
                'publication_year': 2017, 'open_access': {'oa_status': 'green'},
                'best_oa_location': {'is_oa': True, 'pdf_url': 'https://arxiv.org/pdf/1609.02907',
                                     'version': 'submittedVersion', 'license': None,
                                     'source': {'display_name': 'arXiv'}},
                'primary_location': {'is_oa': True, 'pdf_url': 'https://arxiv.org/pdf/1609.02907'},
                'locations': [{'is_oa': False, 'pdf_url': 'https://publisher.example/paywall.pdf'}]}

    def test_resolve_only_oa_pdf_and_deduplicate(self):
        r = module.resolve('10.48550/arxiv.1609.02907', lambda identifier: self.work())
        self.assertEqual(r['status'], 'oa_pdf_leads_found')
        self.assertEqual(len(r['oa_pdf_candidates']), 1)
        self.assertEqual(r['oa_pdf_candidates'][0]['version'], 'submittedVersion')
        self.assertEqual(r['oa_pdf_candidates'][0]['source_name'], 'arXiv')

    def test_no_oa_metadata_and_api_failure_are_distinct(self):
        work = self.work()
        work['best_oa_location'] = None
        work['primary_location'] = None
        work['locations'] = []
        r = module.resolve('W2519887557', lambda identifier: work)
        self.assertEqual(r['status'], 'no_oa_pdf_reported')
        def fail(identifier):
            raise RuntimeError('http_429')
        self.assertEqual(module.resolve('W2519887557', fail)['status'], 'http_429')

    def test_invalid_identifier_rejected_before_request(self):
        with self.assertRaises(ValueError):
            module.normalize_identifier('just a title')
        self.assertEqual(module.normalize_identifier('https://openalex.org/W123'), 'https://openalex.org/W123')
        self.assertEqual(module.normalize_identifier('DOI:10.1000/ABC'), 'https://doi.org/10.1000/abc')

    def test_wrong_work_identity_does_not_offer_pdf(self):
        work = self.work()
        work['doi'] = 'https://doi.org/10.1000/wrong'
        result = module.resolve('10.48550/arxiv.1609.02907', lambda identifier: work)
        self.assertEqual(result['status'], 'identity_mismatch_or_missing')
        self.assertEqual(result['oa_pdf_candidates'], [])
        work = self.work()
        work['id'] = 'https://openalex.org/W999'
        result = module.resolve('W2519887557', lambda identifier: work)
        self.assertEqual(result['status'], 'identity_mismatch_or_missing')
        self.assertEqual(result['oa_pdf_candidates'], [])

    def test_download_rejects_html_and_does_not_overwrite(self):
        candidate = {'pdf_url': 'https://arxiv.org/pdf/1609.02907', 'downloadable_https': True}
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'paper.pdf'
            with self.assertRaisesRegex(RuntimeError, 'not_pdf'):
                module.download_pdf(candidate, dest, lambda url: {'final_url': url, 'body': b'<html>login</html>',
                                                                    'content_type': 'text/html', 'http_status': 200})
            self.assertFalse(dest.exists())
            body = b'%PDF-1.4\nexample test body'
            result = module.download_pdf(candidate, dest,
                                         lambda url: {'final_url': url, 'body': body,
                                                      'content_type': 'application/pdf', 'http_status': 200})
            self.assertEqual(result['bytes'], len(body))
            with self.assertRaisesRegex(ValueError, 'already exists'):
                module.download_pdf(candidate, dest, lambda url: None)

    def test_second_oa_candidate_is_tried_after_first_fails(self):
        candidates = [{'pdf_url': 'https://repository.example/broken.pdf', 'downloadable_https': True},
                      {'pdf_url': 'https://arxiv.org/pdf/1609.02907', 'downloadable_https': True}]
        def downloader(candidate, destination):
            if 'broken' in candidate['pdf_url']:
                raise RuntimeError('http_404')
            return {'path': str(destination), 'sha256': 'example'}
        result = module.download_candidates(candidates, '/tmp/example.pdf', downloader)
        self.assertEqual(result['download']['status'], 'downloaded')
        self.assertEqual(result['download_attempts_failed'][0]['error'], 'http_404')


if __name__ == '__main__':
    unittest.main()
