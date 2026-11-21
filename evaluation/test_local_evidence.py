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

    def test_dual_cli_inputs_question_out_and_strict_gate(self):
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            doc1 = root / 'study_one.txt'
            doc1.write_text('Graph convolution uses normalized adjacency smoothing across node neighborhoods.', encoding='utf-8')
            out_file = root / 'evidence_out.json'
            proc = subprocess.run(
                [
                    sys.executable, str(SCRIPT),
                    '--question', 'normalized adjacency smoothing',
                    '--inputs', str(doc1),
                    '--min-studies', '2',
                    '--min-evidence', '1',
                    '--out', str(out_file),
                    '--strict-gate',
                ],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertTrue(out_file.is_file())
            payload = json.loads(out_file.read_text(encoding='utf-8'))
            self.assertEqual(payload['gate_status'], 'ABSTAIN')
            self.assertEqual(payload['distinct_studies'], 1)

    def test_mixed_question_with_positional_paths_and_conflict_rejection(self):
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            p1 = root / 'study_a.txt'
            p2 = root / 'study_b.txt'
            p1.write_text('Calibration error dropped significantly with temperature scaling.', encoding='utf-8')
            p2.write_text('Temperature scaling preserves accuracy while improving calibration.', encoding='utf-8')

            proc_two = subprocess.run(
                [sys.executable, str(SCRIPT), '--question', 'temperature scaling calibration', str(p1), str(p2)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc_two.returncode, 0, proc_two.stderr)
            out_two = json.loads(proc_two.stdout)
            self.assertEqual(out_two['source_files'], 2)
            self.assertEqual(out_two['distinct_studies'], 2)

            proc_one = subprocess.run(
                [sys.executable, str(SCRIPT), '--question', 'temperature scaling', str(p1)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc_one.returncode, 0, proc_one.stderr)
            self.assertEqual(json.loads(proc_one.stdout)['source_files'], 1)

            # Mixing --question, --inputs, and stray positional args must exit 2
            proc_conflict = subprocess.run(
                [sys.executable, str(SCRIPT), '--question', 'calibration', str(p1), '--inputs', str(p2)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc_conflict.returncode, 2)
            self.assertIn('error', json.loads(proc_conflict.stderr))

    def test_chunk_chars_and_overlap_validation(self):
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as folder:
            p1 = Path(folder) / 'doc.txt'
            p1.write_text('Graph neural network calibration study.', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'chunk_chars'):
                module.run([p1], 'calibration', chunk_chars=0)
            with self.assertRaisesRegex(ValueError, 'chunk_overlap'):
                module.run([p1], 'calibration', chunk_overlap=-1)

            proc = subprocess.run(
                [sys.executable, str(SCRIPT), 'calibration', str(p1), '--chunk-chars', '0'],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 2)
            self.assertIn('chunk_chars', json.loads(proc.stderr)['error'])

    def test_compact_flag_writes_artifact_and_caps_quote_preview(self):
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            p1 = root / 'study_1.txt'
            p2 = root / 'study_2.txt'
            long_body = 'Calibration accuracy metric ' + ('details ' * 60)
            p1.write_text(long_body, encoding='utf-8')
            p2.write_text('Independent calibration benchmark confirms lower ECE.', encoding='utf-8')
            out_file = root / 'evidence_full.json'

            proc = subprocess.run(
                [
                    sys.executable, str(SCRIPT),
                    '--question', 'calibration',
                    '--inputs', str(p1), str(p2),
                    '--out', str(out_file),
                    '--compact',
                ],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            summary = json.loads(proc.stdout)
            self.assertTrue(summary['compact'])
            self.assertEqual(summary['artifact_path'], str(out_file.resolve()))
            self.assertEqual(summary['gate_status'], 'ANSWERABLE')
            self.assertNotIn('context_packed', summary)
            self.assertTrue(summary['top_passages'])
            for tp in summary['top_passages']:
                self.assertLessEqual(len(tp['quote_preview']), 240)
            full_payload = json.loads(out_file.read_text(encoding='utf-8'))
            self.assertIn('context_packed', full_payload)
            self.assertTrue(any(len(p['quote']) > 240 for p in full_payload['ranked_passages']))

            # Auto-artifact path when --out omitted
            proc_auto = subprocess.run(
                [
                    sys.executable, str(SCRIPT),
                    '--question', 'calibration',
                    '--inputs', str(p1), str(p2),
                    '--compact',
                ],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc_auto.returncode, 0, proc_auto.stderr)
            auto_path = Path(json.loads(proc_auto.stdout)['artifact_path'])
            try:
                self.assertTrue(auto_path.is_file())
            finally:
                if auto_path.exists():
                    auto_path.unlink()


if __name__ == '__main__':
    unittest.main()
