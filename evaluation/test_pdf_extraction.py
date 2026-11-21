"""Local PDF extraction and passage-location integration, using a tiny fixture."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load(name):
    path = ROOT / 'research-scientist/scripts' / name
    spec = importlib.util.spec_from_file_location(name.removesuffix('.py'), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

extractor = load('extract_pdf_blocks.py')
local = load('local_evidence.py')

class PdfExtractionTests(unittest.TestCase):
    def test_page_and_pdf_hash_reach_passage_lead(self):
        try:
            import fitz
        except ImportError:
            self.skipTest('PyMuPDF not installed')
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / 'paper.pdf'
            with fitz.open() as document:
                page = document.new_page()
                page.insert_text((72, 72), 'Fictional calibration result with a matched baseline.')
                document.save(pdf)
            result = extractor.extract(pdf)
            self.assertEqual(result['status'], 'extracted_text_blocks')
            self.assertEqual(result['pages_extracted'], 1)
            self.assertEqual(len(result['source_pdf_sha256']), 64)
            export = Path(directory) / 'paper.json'
            export.write_text(json.dumps(result), encoding='utf-8')
            found = local.run([str(export)], 'calibration baseline')
            self.assertEqual(found['returned'], 1)
            lead = found['results'][0]
            self.assertEqual(lead['page_index_zero_based'], 0)
            self.assertEqual(lead['source_pdf_sha256_as_declared'], result['source_pdf_sha256'])
            self.assertTrue(lead['visual_check_required'])

    def test_page_limit_is_explicit(self):
        try:
            import fitz
        except ImportError:
            self.skipTest('PyMuPDF not installed')
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / 'paper.pdf'
            with fitz.open() as document:
                document.new_page()
                document.new_page()
                document.save(pdf)
            result = extractor.extract(pdf, max_pages=1)
            self.assertEqual(result['status'], 'bounded_partial')
            self.assertEqual(result['pages_extracted'], 1)
            self.assertEqual(result['total_pages'], 2)

if __name__ == '__main__':
    unittest.main()
