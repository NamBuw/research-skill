"""Offline tests for venue source capture and quote provenance."""
import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'research-scientist/scripts'

def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

capture = load('capture_venue_sources')
checker = load('check_venue_sources')


class VenueSourceTests(unittest.TestCase):
    def dossier(self):
        return {'venue': 'Example Conference', 'edition': '2027', 'track': 'Research',
                'official_cfp_url': 'https://conference.example/cfp',
                'milestones': {'full_paper': '2027-03-01T23:59:00 AoE'},
                'fees': [{'category': 'author_registration', 'amount': 500, 'mandatory': True,
                          'source_url': 'https://conference.example/fees'}],
                'evidence_claims': [
                    {'field': 'milestones.full_paper', 'source_url': 'https://conference.example/cfp',
                     'quote': 'Full papers: March 1, 2027, 23:59 AoE'},
                    {'field': 'fees.author_registration', 'source_url': 'https://conference.example/fees',
                     'quote': 'Author registration is USD 500'}]}

    def transport(self, url):
        if url.endswith('/cfp'):
            body = b'<html><script>fake deadline</script><body><p>Full papers: March 1, 2027, 23:59 AoE</p></body></html>'
        else:
            body = b'<html><p>Author registration is USD 500</p></html>'
        return {'final_url': url, 'content_type': 'text/html; charset=utf-8',
                'body': body, 'http_status': 200}

    def test_capture_and_exact_quote_with_missing_critical_fields(self):
        dossier = self.dossier()
        bundle = capture.capture_dossier(dossier, self.transport)
        self.assertEqual(len(bundle['sources']), 2)
        self.assertTrue(bundle['sources'][0]['sha256'])
        self.assertNotIn('fake deadline', bundle['sources'][0]['text'])
        out = checker.check(dossier, bundle)
        self.assertEqual([x['status'] for x in out['claims']], ['quote_found', 'quote_found'])
        self.assertEqual(out['critical_fields_without_matched_quote'], ['edition', 'track', 'venue'])

    def test_wrong_quote_and_stale_snapshot_are_not_verified(self):
        dossier = self.dossier()
        bundle = capture.capture_dossier(dossier, self.transport)
        dossier['evidence_claims'][1]['quote'] = 'Author registration is USD 50'
        out = checker.check(dossier, bundle)
        self.assertEqual(out['claims'][1]['status'], 'quote_not_found_in_snapshot')
        old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        bundle['sources'][0]['fetched_at_utc'] = old
        out = checker.check(dossier, bundle)
        self.assertEqual(out['claims'][0]['status'], 'source_snapshot_stale_or_undated')

    def test_failed_pdf_extraction_and_non_https_rejected(self):
        dossier = self.dossier()
        def fail(url):
            raise RuntimeError('http_404')
        bundle = capture.capture_dossier(dossier, fail)
        self.assertEqual(bundle['sources'][0]['extraction_status'], 'fetch_failed')
        self.assertEqual(checker.check(dossier, bundle)['claims'][0]['status'], 'source_text_unavailable')
        dossier['official_cfp_url'] = 'http://conference.example/cfp'
        with self.assertRaisesRegex(ValueError, 'HTTPS'):
            capture.urls_from_dossier(dossier)

    def test_pdf_text_extracts_when_dependency_available(self):
        try:
            import fitz
        except ImportError:
            self.skipTest('PyMuPDF not installed')
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((40, 40), 'Full paper deadline March 1, 2027')
        text, status = capture.extract_text(doc.tobytes(), 'application/pdf')
        self.assertEqual(status, 'pdf_text_extracted')
        self.assertIn('Full paper deadline', text)

    def test_cross_host_redirect_requires_review_even_with_matching_quote(self):
        dossier = self.dossier()
        def transport(url):
            response = self.transport(url)
            if url.endswith('/cfp'):
                response['final_url'] = 'https://unrelated.example/cfp'
            return response
        bundle = capture.capture_dossier(dossier, transport)
        out = checker.check(dossier, bundle)
        self.assertEqual(out['claims'][0]['status'], 'quote_found_redirect_host_review_required')
        self.assertIn('milestones.full_paper', out['critical_fields_without_matched_quote'])


if __name__ == '__main__':
    unittest.main()
