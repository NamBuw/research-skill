"""Regression checks for local passage retrieval and provenance."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'research-scientist/scripts/local_evidence.py'
spec = importlib.util.spec_from_file_location('local_evidence', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class LocalEvidenceTests(unittest.TestCase):
    def test_text_passage_has_hash_and_exact_line_range(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'paper.txt'
            source.write_text('Title\n\nControl subjects improved.\nThe effect was uncertain.\n', encoding='utf-8')
            report = module.run([source], 'control subjects', 3)
            self.assertEqual(report['segments_indexed'], 2)
            hit = report['results'][0]
            self.assertEqual((hit['line_start'], hit['line_end']), (3, 4))
            self.assertEqual(len(hit['sha256']), 64)
            self.assertIn('Control subjects improved.', hit['excerpt'])

    def test_mineru_v2_page_and_visual_warning(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'paper.json'
            source.write_text(json.dumps([[{'type': 'title', 'content': {'title_content':
                                  [{'type': 'text', 'content': 'Trial'}]}}],
                                [{'type': 'table', 'bbox': [1, 2, 3, 4],
                                  'content': {'table_caption': [{'type': 'text', 'content': 'Mortality'}],
                                              'html': '<table><tr><td>5%</td></tr></table>'}},
                                 {'type': 'equation_interline', 'content': {'math_content': 'x=1'}}]]), encoding='utf-8')
            report = module.run([source], 'mortality', 2)
            hit = report['results'][0]
            self.assertEqual(hit['page_index_zero_based'], 1)
            self.assertEqual(hit['bbox_as_provided'], [1, 2, 3, 4])
            self.assertTrue(hit['visual_check_required'])
            self.assertIn('5%', hit['excerpt'])
            equation = module.run([source], 'x', 2)['results'][0]
            self.assertEqual(equation['page_index_zero_based'], 1)
            self.assertTrue(equation['visual_check_required'])

    def test_valid_no_match_is_not_a_claim_about_field(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'paper.md'
            source.write_text('A known method.', encoding='utf-8')
            report = module.run([source], 'unrelated', 5)
            self.assertEqual(report['matching_segments'], 0)
            self.assertEqual(report['source_files'], 1)
            self.assertIn('no full-text or field coverage', report['warning'])

    def test_unsupported_json_shape_fails_explicitly(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'wrong.json'
            source.write_text('{"papers": []}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Content List V2'):
                module.run([source], 'paper')

    def test_directory_skips_other_json_but_discloses_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'notes.txt').write_text('A measured outcome.', encoding='utf-8')
            (root / 'metadata.json').write_text('{"unrelated": true}', encoding='utf-8')
            report = module.run([root], 'measured')
            self.assertEqual(report['source_files'], 1)
            self.assertEqual(len(report['skipped_files']), 1)
            self.assertEqual(report['skipped_files'][0]['error'], 'ValueError')


if __name__ == '__main__':
    unittest.main()
