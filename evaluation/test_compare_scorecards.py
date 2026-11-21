"""Ranking-sensitivity checks, --sources-dir locator verification, and score_math hardening tests."""
import decimal
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / 'research-scientist/scripts'
sys.path.insert(0, str(SCRIPT_DIR))
spec = importlib.util.spec_from_file_location('compare_scorecards', SCRIPT_DIR / 'compare_scorecards.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

score_spec = importlib.util.spec_from_file_location('score_math', SCRIPT_DIR / 'score_math.py')
score_math_mod = importlib.util.module_from_spec(score_spec)
score_spec.loader.exec_module(score_math_mod)

try:
    import fitz
except ImportError:  # pragma: no cover
    fitz = None


class CompareScorecardsTests(unittest.TestCase):
    def profile(self, name, importance, novelty):
        return {'id': name, 'reading_basis': 'full_text', 'closest_work': ['fictional work'],
                'ratings': {'importance': importance, 'novelty': novelty, 'soundness': 5, 'evidence': 5, 'transparency': 5, 'clarity': 5},
                'evidence_locators': {key: ['fictional section 1'] for key in module.DIMENSIONS}}

    def test_weight_change_reverses_top_paper(self):
        data = {'profiles': [self.profile('A', 9, 3), self.profile('B', 3, 9)],
                'weight_scenarios': [
                    {'importance': 45, 'novelty': 5, 'soundness': 15, 'evidence': 15, 'transparency': 10, 'clarity': 10},
                    {'importance': 5, 'novelty': 45, 'soundness': 15, 'evidence': 15, 'transparency': 10, 'clarity': 10}]}
        self.assertEqual(module.compare(data)['ranking_sensitivity'], 'top_changes_across_supplied_weights')

    def test_abstract_only_blocks_comparison(self):
        first = self.profile('A', 7, 7)
        first['reading_basis'] = 'abstract'
        data = {'profiles': [first, self.profile('B', 7, 7)],
                'weight_scenarios': [dict(zip(module.DIMENSIONS, (15, 20, 20, 20, 15, 10)))]}
        self.assertIn('full_text_not_confirmed:A', module.compare(data)['issues'])

    def test_missing_closest_work_blocks_novelty_rank(self):
        first = self.profile('A', 7, 7)
        first['closest_work'] = []
        data = {'profiles': [first, self.profile('B', 7, 7)],
                'weight_scenarios': [dict(zip(module.DIMENSIONS, (15, 20, 20, 20, 15, 10)))]}
        self.assertIn('closest_work_missing:A', module.compare(data)['issues'])

    def test_invalid_rating_is_not_hidden(self):
        first = self.profile('A', 7, 7)
        first['ratings']['clarity'] = 12
        data = {'profiles': [first, self.profile('B', 7, 7)],
                'weight_scenarios': [dict(zip(module.DIMENSIONS, (15, 20, 20, 20, 15, 10)))]}
        with self.assertRaises(ValueError):
            module.compare(data)

    def _valid_weights(self):
        return [dict(zip(module.DIMENSIONS, (15, 20, 20, 20, 15, 10)))]

    def test_sources_dir_valid_text_and_md_locators_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            src_dir = Path(tmp)
            (src_dir / 'paper_a.txt').write_text(
                'Title: Paper A\n'
                'Section 1 Introduction\n'
                'Control subjects improved by 14 percent.\n'
                'Prior baseline lacked calibration.\n'
                'Appendix A details hyperparameters.\n',
                encoding='utf-8',
            )
            (src_dir / 'paper_b.md').write_text(
                '# Paper B\n'
                '## Section 2 Methods\n'
                'We evaluate across five random seeds.\n'
                'Table 1 shows accuracy 91.2.\n',
                encoding='utf-8',
            )
            prof_a = self.profile('paper_a', 8, 7)
            prof_a['evidence_locators'] = {
                'importance': ['paper_a.txt:3-4: "Control subjects improved by 14 percent."'],
                'novelty': ['paper_a.txt#L4: "Prior baseline lacked calibration."'],
                'soundness': ['paper_a.txt lines 3-4: "Control subjects improved"'],
                'evidence': ['paper_a.txt: "Control subjects improved by 14 percent."'],
                'transparency': ['paper_a.txt#L5: "Appendix A details hyperparameters."'],
                'clarity': ['paper_a.txt: Section 1 Introduction'],
            }
            prof_b = self.profile('paper_b', 6, 8)
            prof_b['evidence_locators'] = {
                dim: ['paper_b.md:3-4: "We evaluate across five random seeds."']
                for dim in module.DIMENSIONS
            }
            out = module.compare({'profiles': [prof_a, prof_b], 'weight_scenarios': self._valid_weights()}, sources_dir=src_dir)
            self.assertEqual(out['status'], 'structurally_comparable')
            self.assertEqual(out['locator_verification']['checked'], 12)
            self.assertEqual(out['locator_verification']['verified'], 12)
            self.assertEqual(out['locator_verification']['failed'], 0)

    def test_sources_dir_mineru_v2_and_pdf_blocks_json_page_anchors(self):
        with tempfile.TemporaryDirectory() as tmp:
            src_dir = Path(tmp)
            blocks_v1 = {
                'format': 'research_scientist_pdf_blocks_v1',
                'source_pdf_sha256': 'abc123',
                'pages': [
                    [{'type': 'paragraph', 'page_idx': 0, 'content': {'paragraph_content': [{'content': 'Introductory text only.'}]}}],
                    [
                        {'type': 'table', 'page_idx': 1, 'content': {'table_caption': [{'content': 'Table 1 results'}], 'html': '<table><tr><td>Accuracy</td><td>94.5%</td></tr></table>'}},
                        {'type': 'equation_interline', 'page_idx': 1, 'content': {'math_content': 'L = alpha + beta'}},
                    ],
                ],
            }
            mineru_flat = [
                {'type': 'paragraph', 'page_idx': 0, 'content': {'paragraph_content': [{'content': 'Flat page one content.'}]}},
                {'type': 'paragraph', 'page_idx': 1, 'content': {'paragraph_content': [{'content': 'Flat page two ablation study.'}]}},
            ]
            (src_dir / 'paper_a.json').write_text(json.dumps(blocks_v1), encoding='utf-8')
            (src_dir / 'paper_b.json').write_text(json.dumps(mineru_flat), encoding='utf-8')

            prof_a = self.profile('paper_a', 8, 7)
            prof_a['evidence_locators'] = {dim: ['paper_a.json p.2: "94.5%"'] for dim in module.DIMENSIONS}
            prof_a['evidence_locators']['soundness'] = ['paper_a.json page_idx=1: "L = alpha + beta"']
            prof_b = self.profile('paper_b', 6, 8)
            prof_b['evidence_locators'] = {dim: ['paper_b.json p.2: "ablation study"'] for dim in module.DIMENSIONS}

            ok_out = module.compare({'profiles': [prof_a, prof_b], 'weight_scenarios': self._valid_weights()}, sources_dir=src_dir)
            self.assertEqual(ok_out['status'], 'structurally_comparable')

            # Claiming p.1 for page-2 text must fail.
            prof_a['evidence_locators']['evidence'] = ['paper_a.json p.1: "94.5%"']
            bad_out = module.compare({'profiles': [prof_a, prof_b], 'weight_scenarios': self._valid_weights()}, sources_dir=src_dir)
            self.assertEqual(bad_out['status'], 'not_comparable')
            self.assertIn('locator_unverified:paper_a:evidence:0:quote_not_found', bad_out['issues'])

    @unittest.skipIf(fitz is None, 'PyMuPDF (fitz) not installed')
    def test_sources_dir_real_pdf_fitz_and_wrong_page_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            src_dir = Path(tmp)
            pdf_a = src_dir / 'paper_a.pdf'
            doc = fitz.open()
            p1 = doc.new_page()
            p1.insert_text((72, 72), 'Page one introduction and problem framing.')
            p2 = doc.new_page()
            p2.insert_text((72, 72), 'Page two reports USD 500 fee and 92 percent recall.')
            doc.save(str(pdf_a))
            doc.close()

            (src_dir / 'paper_b.txt').write_text('Paper B baseline comparison on dataset X.\n', encoding='utf-8')
            prof_a = self.profile('paper_a', 8, 7)
            prof_a['evidence_locators'] = {dim: ['paper_a.pdf#page=2: "92 percent recall"'] for dim in module.DIMENSIONS}
            prof_b = self.profile('paper_b', 6, 8)
            prof_b['evidence_locators'] = {dim: ['paper_b.txt:1: "baseline comparison"'] for dim in module.DIMENSIONS}

            ok_out = module.compare({'profiles': [prof_a, prof_b], 'weight_scenarios': self._valid_weights()}, sources_dir=src_dir)
            self.assertEqual(ok_out['status'], 'structurally_comparable')

            # Word-boundary protection: "USD 50" must NOT match "USD 500"
            prof_a['evidence_locators']['evidence'] = ['paper_a.pdf#page=2: "USD 50"']
            wb_out = module.compare({'profiles': [prof_a, prof_b], 'weight_scenarios': self._valid_weights()}, sources_dir=src_dir)
            self.assertIn('locator_unverified:paper_a:evidence:0:quote_not_found', wb_out['issues'])

            # Wrong page (#page=1 for page-2 text) must fail
            prof_a['evidence_locators']['evidence'] = ['paper_a.pdf#page=1: "92 percent recall"']
            wp_out = module.compare({'profiles': [prof_a, prof_b], 'weight_scenarios': self._valid_weights()}, sources_dir=src_dir)
            self.assertIn('locator_unverified:paper_a:evidence:0:quote_not_found', wp_out['issues'])

            # Out-of-bounds page (#page=5) must fail
            prof_a['evidence_locators']['evidence'] = ['paper_a.pdf#page=5: "92 percent recall"']
            oob_out = module.compare({'profiles': [prof_a, prof_b], 'weight_scenarios': self._valid_weights()}, sources_dir=src_dir)
            self.assertIn('locator_unverified:paper_a:evidence:0:anchor_out_of_bounds', oob_out['issues'])

    def test_sources_dir_blocks_fabricated_quote_missing_file_and_bare_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            src_dir = Path(tmp)
            (src_dir / 'paper_a.txt').write_text('Real sentence on line one.\n', encoding='utf-8')
            (src_dir / 'paper_b.txt').write_text('Another real sentence on line one.\n', encoding='utf-8')

            prof_a = self.profile('paper_a', 8, 7)
            prof_a['evidence_locators'] = {
                'importance': ['paper_a.txt:1: "Fabricated quote not in text"'],
                'novelty': ['ghost.pdf p.1: "Real sentence"'],
                'soundness': ['paper_a.txt lines 1-1'],  # bare anchor without quote or section text
                'evidence': ['fictional section 1'],
                'transparency': ['paper_a.txt:1: "Real sentence on line one."'],
                'clarity': ['paper_a.txt:1: "Real sentence on line one."'],
            }
            prof_b = self.profile('paper_b', 6, 8)
            prof_b['evidence_locators'] = {dim: ['paper_b.txt:1: "Another real sentence"'] for dim in module.DIMENSIONS}

            out = module.compare({'profiles': [prof_a, prof_b], 'weight_scenarios': self._valid_weights()}, sources_dir=src_dir)
            self.assertEqual(out['status'], 'not_comparable')
            self.assertIn('locator_unverified:paper_a:importance:0:quote_not_found', out['issues'])
            self.assertIn('locator_unverified:paper_a:novelty:0:source_not_found', out['issues'])
            self.assertIn('locator_unverified:paper_a:soundness:0:missing_verifiable_text', out['issues'])
            self.assertIn('locator_unverified:paper_a:evidence:0:text_not_found', out['issues'])
            self.assertEqual(out['locator_verification']['failed'], 4)

    def test_sources_dir_blocks_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            src_dir = Path(tmp)
            (src_dir / 'paper_a.txt').write_text('Real sentence.\n', encoding='utf-8')
            prof_a = self.profile('paper_a', 8, 7)
            prof_a['evidence_locators'] = {dim: ['../../secret.txt: "key"'] for dim in module.DIMENSIONS}
            prof_a['evidence_locators']['clarity'] = ['/etc/passwd.txt: "root"']
            prof_b = self.profile('paper_b', 6, 8)
            prof_b['evidence_locators'] = {dim: ['paper_a.txt: "Real sentence."'] for dim in module.DIMENSIONS}
            out = module.compare({'profiles': [prof_a, prof_b], 'weight_scenarios': self._valid_weights()}, sources_dir=src_dir)
            self.assertIn('locator_unverified:paper_a:importance:0:unsafe_source_path', out['issues'])
            self.assertIn('locator_unverified:paper_a:clarity:0:unsafe_source_path', out['issues'])

    def test_cli_sources_dir_exit_codes_and_help(self):
        script = str(SCRIPT_DIR / 'compare_scorecards.py')
        help_res = subprocess.run([sys.executable, script, '--help'], capture_output=True, text=True)
        self.assertEqual(help_res.returncode, 0)
        self.assertIn('--sources-dir', help_res.stdout)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src_dir = tmp_path / 'sources'
            src_dir.mkdir()
            (src_dir / 'paper_a.txt').write_text('Real text A.\n', encoding='utf-8')
            (src_dir / 'paper_b.txt').write_text('Real text B.\n', encoding='utf-8')

            good_json = tmp_path / 'good.json'
            bad_json = tmp_path / 'bad.json'
            prof_a = self.profile('paper_a', 8, 7)
            prof_a['evidence_locators'] = {dim: ['paper_a.txt: "Real text A."'] for dim in module.DIMENSIONS}
            prof_b = self.profile('paper_b', 6, 8)
            prof_b['evidence_locators'] = {dim: ['paper_b.txt: "Real text B."'] for dim in module.DIMENSIONS}
            good_json.write_text(json.dumps({'profiles': [prof_a, prof_b], 'weight_scenarios': self._valid_weights()}), encoding='utf-8')

            bad_prof_a = self.profile('paper_a', 8, 7)
            bad_json.write_text(json.dumps({'profiles': [bad_prof_a, prof_b], 'weight_scenarios': self._valid_weights()}), encoding='utf-8')

            # Omitted --sources-dir keeps exit 0 even with fictional locators
            res_omit = subprocess.run([sys.executable, script, str(bad_json)], capture_output=True, text=True)
            self.assertEqual(res_omit.returncode, 0)

            res_pass = subprocess.run([sys.executable, script, str(good_json), '--sources-dir', str(src_dir)], capture_output=True, text=True)
            self.assertEqual(res_pass.returncode, 0)
            self.assertEqual(json.loads(res_pass.stdout)['status'], 'structurally_comparable')

            res_fail = subprocess.run([sys.executable, script, str(bad_json), '--sources-dir', str(src_dir)], capture_output=True, text=True)
            self.assertEqual(res_fail.returncode, 1)
            self.assertEqual(json.loads(res_fail.stdout)['status'], 'not_comparable')

            res_missing_dir = subprocess.run([sys.executable, script, str(good_json), '--sources-dir', str(tmp_path / 'nope')], capture_output=True, text=True)
            self.assertEqual(res_missing_dir.returncode, 2)

            empty_dir = tmp_path / 'empty'
            empty_dir.mkdir()
            res_empty_dir = subprocess.run([sys.executable, script, str(good_json), '--sources-dir', str(empty_dir)], capture_output=True, text=True)
            self.assertEqual(res_empty_dir.returncode, 2)

    def test_invalid_rating_not_masked_by_missing_locator(self):
        first = self.profile('A', 7, 7)
        first['reading_basis'] = 'abstract'
        first['evidence_locators']['clarity'] = []
        first['ratings']['clarity'] = 12
        data = {'profiles': [first, self.profile('B', 7, 7)], 'weight_scenarios': self._valid_weights()}
        with self.assertRaises(ValueError):
            module.compare(data)

    def test_score_math_hardening_edge_cases(self):
        weights = dict(zip(score_math_mod.DIMENSIONS, (15, 20, 20, 20, 15, 10)))
        ratings = dict.fromkeys(score_math_mod.DIMENSIONS, 7)

        # List inputs must raise ValueError, never AttributeError
        with self.assertRaises(ValueError):
            score_math_mod.score({'weights': list(score_math_mod.DIMENSIONS), 'ratings': ratings})
        with self.assertRaises(ValueError):
            score_math_mod.score({'weights': weights, 'ratings': list(score_math_mod.DIMENSIONS)})
        with self.assertRaises(ValueError):
            score_math_mod.score(['not', 'a', 'dict'])

        # bool and int subclass rejected
        class CustomInt(int):
            pass

        bad_w = dict(weights)
        bad_w['clarity'] = True
        with self.assertRaises(ValueError):
            score_math_mod.score({'weights': bad_w, 'ratings': ratings})

        sub_r = dict(ratings)
        sub_r['clarity'] = CustomInt(7)
        with self.assertRaises(ValueError):
            score_math_mod.score({'weights': weights, 'ratings': sub_r})

        # Zero-weight dimension with None rating -> not_comparable (never silently dropped)
        zero_w = dict(zip(score_math_mod.DIMENSIONS, (20, 20, 20, 20, 20, 0)))
        miss_r = dict(ratings)
        miss_r['clarity'] = None
        self.assertEqual(score_math_mod.score({'weights': zero_w, 'ratings': miss_r})['status'], 'not_comparable')

        # Caller decimal context precision=1 must NOT corrupt score_math rounding
        with decimal.localcontext() as ctx:
            ctx.prec = 1
            res = score_math_mod.score({'weights': weights, 'ratings': dict(zip(score_math_mod.DIMENSIONS, (9, 8, 7, 7, 7, 7)))})
            self.assertEqual(res['weighted_unrounded'], '7.5')
            self.assertEqual(res['overall'], 8)

        # CLI --help and NaN rejection
        script = str(SCRIPT_DIR / 'score_math.py')
        help_res = subprocess.run([sys.executable, script, '--help'], capture_output=True, text=True)
        self.assertEqual(help_res.returncode, 0)
        nan_payload = json.dumps({'weights': weights, 'ratings': ratings}).replace('7', 'NaN', 1)
        nan_res = subprocess.run([sys.executable, script], input=nan_payload, capture_output=True, text=True)
        self.assertEqual(nan_res.returncode, 2)
        self.assertIn('Non-finite', nan_res.stderr)

        # Caller decimal traps (Inexact, Rounded) must NOT crash score_math.score()
        with decimal.localcontext() as ctx:
            ctx.prec = 2
            ctx.traps[decimal.Inexact] = True
            ctx.traps[decimal.Rounded] = True
            res_traps = score_math_mod.score({'weights': weights, 'ratings': dict(zip(score_math_mod.DIMENSIONS, (9, 8, 7, 7, 7, 7)))})
            self.assertEqual(res_traps['weighted_unrounded'], '7.5')
            self.assertEqual(res_traps['overall'], 8)

    def test_sources_dir_quote_anchor_masking_and_filename_prefix_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            src_dir = Path(tmp)
            (src_dir / 'paper_a.txt').write_text(
                'Result is significant at p. 0.05 threshold.\n'
                'Section 3: Overview, Part A-B; Case|1\n',
                encoding='utf-8',
            )
            (src_dir / 'p1.json').write_text(
                json.dumps([{'type': 'paragraph', 'page_idx': 0, 'content': {'paragraph_content': [{'content': 'Page one real content.'}]}}]),
                encoding='utf-8',
            )
            (src_dir / 'p2.json').write_text(
                json.dumps([{'type': 'paragraph', 'page_idx': 0, 'content': {'paragraph_content': [{'content': 'Page one real content.'}]}}]),
                encoding='utf-8',
            )

            idx = module.index_sources_dir(src_dir)
            # p. 0.05 inside quotes must NOT trigger anchor_out_of_bounds
            self.assertEqual(
                module.verify_locator('paper_a.txt: "significant at p. 0.05 threshold"', idx),
                (True, 'verified'),
            )
            # Unquoted punctuation :;,|- must be preserved
            self.assertEqual(
                module.verify_locator('paper_a.txt:2: Section 3: Overview, Part A-B; Case|1', idx),
                (True, 'verified'),
            )
            # Filename p1.json must NOT override explicit p. 999 anchor
            ok_p999, reason_p999 = module.verify_locator('p1.json p. 999: "Page one real content."', idx)
            self.assertFalse(ok_p999)
            self.assertEqual(reason_p999, 'anchor_out_of_bounds')
            # Filename p2.json must NOT override explicit p. 1 anchor
            self.assertEqual(
                module.verify_locator('p2.json p. 1: "Page one real content."', idx),
                (True, 'verified'),
            )
            # dict locator with bool page/line_start must be rejected
            ok_bool, reason_bool = module.verify_locator({'source': 'p1.json', 'page': True, 'quote': 'Page one real content.'}, idx)
            self.assertFalse(ok_bool)
            self.assertEqual(reason_bool, 'invalid_page_type')

    @unittest.skipIf(fitz is None, 'PyMuPDF (fitz) not installed')
    def test_sources_dir_pdf_quote_anchor_spoof_and_extract_pdf_blocks_equation(self):
        with tempfile.TemporaryDirectory() as tmp:
            src_dir = Path(tmp)
            pdf_a = src_dir / 'paper_a.pdf'
            doc = fitz.open()
            doc.new_page().insert_text((72, 72), 'See page 1 for details.')
            doc.new_page().insert_text((72, 72), 'Page two reports P100 GPU results and 92 percent recall.')
            doc.save(str(pdf_a))
            doc.close()

            # extract_pdf_blocks.py type="equation" block compatibility
            eq_blocks = [
                {'type': 'paragraph', 'page_idx': 0, 'content': {'paragraph_content': [{'content': 'Intro'}]}},
                {'type': 'equation', 'page_idx': 1, 'content': {'math_content': 'L = alpha + beta - gamma (1)'}},
            ]
            (src_dir / 'paper_eq.json').write_text(json.dumps(eq_blocks), encoding='utf-8')

            idx = module.index_sources_dir(src_dir)
            # Wrong-page spoof ("page 1" inside quote while locator cites p.2) must FAIL
            ok_spoof, reason_spoof = module.verify_locator('paper_a.pdf p.2: "See page 1 for details."', idx)
            self.assertFalse(ok_spoof)
            self.assertEqual(reason_spoof, 'quote_not_found')

            # P100 inside quote without page anchor must PASS
            self.assertEqual(
                module.verify_locator('paper_a.pdf: "P100 GPU results"', idx),
                (True, 'verified'),
            )
            # Equation block on page 2 must PASS
            self.assertEqual(
                module.verify_locator('paper_eq.json p.2: "L = alpha + beta - gamma"', idx),
                (True, 'verified'),
            )

    def test_sources_dir_blocks_symlinks_absolute_paths_and_cross_paper_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            outside = tmp_path / 'outside'
            outside.mkdir()
            (outside / 'secret.txt').write_text('TOP_SECRET_OUTSIDE_CONTENT\n', encoding='utf-8')

            src_dir = tmp_path / 'sources'
            src_dir.mkdir()
            (src_dir / 'paper_a.txt').write_text('Real verified line one.\n', encoding='utf-8')
            (src_dir / 'paper_b.txt').write_text('Baseline comparison on dataset Y.\n', encoding='utf-8')
            (src_dir / 'symlink_leak.txt').symlink_to(outside / 'secret.txt')

            idx = module.index_sources_dir(src_dir)
            # Symlink escaping sources_dir must not be indexed
            ok_sym, reason_sym = module.verify_locator('symlink_leak.txt:1: "TOP_SECRET_OUTSIDE_CONTENT"', idx)
            self.assertFalse(ok_sym)
            self.assertEqual(reason_sym, 'source_not_found')

            # Absolute paths / src=/... bypasses must fail with unsafe_source_path
            for bad_loc in ('/etc/passwd: "Real verified line one."', 'src=/paper_a.txt: "Real verified line one."'):
                ok_abs, reason_abs = module.verify_locator(bad_loc, idx)
                self.assertFalse(ok_abs, msg=bad_loc)
                self.assertEqual(reason_abs, 'unsafe_source_path')

            # Silent cross-paper fallback for unmatched profile ID must fail with source_not_scoped
            prof_a = self.profile('model-A', 8, 7)
            prof_a['evidence_locators'] = {dim: ['"Baseline comparison on dataset Y."'] for dim in module.DIMENSIONS}
            prof_b = self.profile('paper_b', 6, 8)
            prof_b['evidence_locators'] = {dim: ['paper_b.txt: "Baseline comparison on dataset Y."'] for dim in module.DIMENSIONS}
            out = module.compare({'profiles': [prof_a, prof_b], 'weight_scenarios': self._valid_weights()}, sources_dir=src_dir)
            self.assertEqual(out['status'], 'not_comparable')
            self.assertIn('locator_unverified:model-A:importance:0:source_not_scoped', out['issues'])

    def test_cli_out_and_compact_summary(self):
        script = str(SCRIPT_DIR / 'compare_scorecards.py')
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src_dir = tmp_path / 'sources'
            src_dir.mkdir()
            (src_dir / 'paper_a.txt').write_text('Real text A.\n', encoding='utf-8')
            (src_dir / 'paper_b.txt').write_text('Real text B.\n', encoding='utf-8')

            prof_a = self.profile('paper_a', 8, 7)
            prof_a['evidence_locators'] = {dim: ['paper_a.txt: "Real text A."'] for dim in module.DIMENSIONS}
            prof_b = self.profile('paper_b', 6, 8)
            prof_b['evidence_locators'] = {dim: ['paper_b.txt: "Real text B."'] for dim in module.DIMENSIONS}
            sc_json = tmp_path / 'sc.json'
            sc_json.write_text(json.dumps({'profiles': [prof_a, prof_b], 'weight_scenarios': self._valid_weights()}), encoding='utf-8')
            out_file = tmp_path / 'full_report.json'

            res = subprocess.run(
                [sys.executable, script, str(sc_json), '--sources-dir', str(src_dir), '--out', str(out_file), '--compact'],
                capture_output=True, text=True,
            )
            self.assertEqual(res.returncode, 0, msg=res.stderr)
            compact = json.loads(res.stdout)
            self.assertTrue(compact['compact'])
            self.assertEqual(compact['status'], 'structurally_comparable')
            self.assertEqual(compact['issue_count'], 0)
            self.assertEqual(compact['artifact_path'], str(out_file))
            full = json.loads(out_file.read_text(encoding='utf-8'))
            self.assertEqual(full['status'], 'structurally_comparable')
            self.assertIn('warning', full)

    def test_verify_locator_allows_https_pdf_url_while_blocking_local_cheat_and_file_uri(self):
        with tempfile.TemporaryDirectory() as tmp:
            src_dir = Path(tmp)
            (src_dir / 'local_cheat.txt').write_text('Main scope covers graph learning.\n', encoding='utf-8')
            bundle = {
                'format': 'research_scientist_venue_sources_v1',
                'sources': [
                    {
                        'requested_url': 'https://icml.cc/cfp.pdf',
                        'final_url': 'https://icml.cc/cfp.pdf',
                        'extraction_status': 'ok',
                        'text': 'Main scope covers graph learning and reproducibility.',
                    }
                ],
            }
            (src_dir / 'venue-sources.json').write_text(json.dumps(bundle), encoding='utf-8')
            idx = module.index_sources_dir(src_dir)

            self.assertEqual(
                module.verify_locator(
                    'https://icml.cc/cfp.pdf: "Main scope covers graph learning"',
                    idx,
                    source_url='https://icml.cc/cfp.pdf',
                    require_url_snapshot=True,
                ),
                (True, 'verified'),
            )
            self.assertEqual(
                module.verify_locator(
                    'https://icml.cc/cfp.pdf local_cheat.txt: "Main scope covers graph learning"',
                    idx,
                    source_url='https://icml.cc/cfp.pdf',
                    require_url_snapshot=True,
                ),
                (False, 'source_snapshot_mismatch'),
            )
            self.assertEqual(
                module.verify_locator('file:///etc/passwd: "Main scope covers graph learning"', idx),
                (False, 'unsafe_source_path'),
            )
            self.assertEqual(
                module.verify_locator(
                    'https://icml.cc/cfp.pdf ../etc/passwd: "Main scope covers graph learning"',
                    idx,
                    source_url='https://icml.cc/cfp.pdf',
                    require_url_snapshot=True,
                ),
                (False, 'unsafe_source_path'),
            )

    def test_compare_isolates_caller_decimal_precision_rounding_and_traps(self):
        weights = {
            'importance': 24,
            'novelty': 24,
            'soundness': 24,
            'evidence': 24,
            'transparency': 2,
            'clarity': 2,
        }
        alpha = {
            'id': 'alpha',
            'reading_basis': 'full_text',
            'closest_work': ['fictional work'],
            'ratings': {'importance': 7, 'novelty': 7, 'soundness': 7, 'evidence': 7, 'transparency': 0, 'clarity': 0},
            'evidence_locators': {key: ['fictional section 1'] for key in module.DIMENSIONS},
        }
        beta = {
            'id': 'beta',
            'reading_basis': 'full_text',
            'closest_work': ['fictional work'],
            'ratings': {'importance': 7, 'novelty': 7, 'soundness': 7, 'evidence': 7, 'transparency': 1, 'clarity': 1},
            'evidence_locators': {key: ['fictional section 1'] for key in module.DIMENSIONS},
        }
        data = {'profiles': [alpha, beta], 'weight_scenarios': [weights]}

        for prec in (2, 1):
            with decimal.localcontext() as ctx:
                ctx.prec = prec
                ctx.rounding = decimal.ROUND_DOWN
                ctx.traps[decimal.Inexact] = True
                ctx.traps[decimal.Rounded] = True
                ctx.traps[decimal.FloatOperation] = True
                out = module.compare(data)
                self.assertEqual(out['status'], 'structurally_comparable')
                self.assertEqual(
                    out['rankings'][0]['ordered'],
                    [
                        {'id': 'beta', 'weighted_unrounded': '6.76'},
                        {'id': 'alpha', 'weighted_unrounded': '6.72'},
                    ],
                )

    @unittest.skipIf(fitz is None, 'PyMuPDF (fitz) not installed')
    def test_sources_dir_corrupt_pdf_recorded_in_skipped_files_and_valid_sources_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            src_dir = Path(tmp) / 'sources'
            src_dir.mkdir()
            (src_dir / 'corrupt.pdf').write_bytes(b'%PDF-1.4\nnot really a pdf at all\x00\xff')
            (src_dir / 'empty.pdf').write_bytes(b'')
            (src_dir / 'paper_a.txt').write_text('Real quote from paper A.\n', encoding='utf-8')

            pdf_b = src_dir / 'paper_b.pdf'
            doc = fitz.open()
            doc.new_page().insert_text((72, 72), 'Valid PDF text from paper B.')
            doc.save(str(pdf_b))
            doc.close()

            idx = module.index_sources_dir(src_dir)
            skipped_paths = {item['path'] for item in idx['skipped_files']}
            self.assertIn('corrupt.pdf', skipped_paths)
            self.assertIn('empty.pdf', skipped_paths)
            self.assertEqual(idx['sources_indexed'], 2)

            prof_a = self.profile('paper_a', 8, 7)
            prof_a['evidence_locators'] = {dim: ['paper_a.txt: "Real quote from paper A."'] for dim in module.DIMENSIONS}
            prof_b = self.profile('paper_b', 6, 8)
            prof_b['evidence_locators'] = {dim: ['paper_b.pdf#page=1: "Valid PDF text from paper B."'] for dim in module.DIMENSIONS}

            out = module.compare({'profiles': [prof_a, prof_b], 'weight_scenarios': self._valid_weights()}, sources_dir=src_dir)
            self.assertEqual(out['status'], 'structurally_comparable')
            self.assertEqual(out['locator_verification']['checked'], 12)
            self.assertEqual(out['locator_verification']['verified'], 12)
            self.assertEqual({item['path'] for item in out['locator_verification']['skipped_files']}, {'corrupt.pdf', 'empty.pdf'})

            only_corrupt = Path(tmp) / 'only_corrupt'
            only_corrupt.mkdir()
            (only_corrupt / 'corrupt.pdf').write_bytes(b'%PDF-1.4\nbroken')
            with self.assertRaises(ValueError):
                module.index_sources_dir(only_corrupt)

    def test_verify_locator_and_compare_block_null_byte_control_char_and_relative_file_uri(self):
        with tempfile.TemporaryDirectory() as tmp:
            src_dir = Path(tmp)
            (src_dir / 'paper_a.txt').write_text(
                'Real quote from paper A and quote mentioning file:example inside prose.\n',
                encoding='utf-8',
            )
            (src_dir / 'paper_b.txt').write_text('Real quote from paper B.\n', encoding='utf-8')
            idx = module.index_sources_dir(src_dir)

            blocked_locators = (
                'paper_a.txt\x00/etc/passwd: "Real quote from paper A"',
                'paper_a.txt\x00../outside/secret: "Real quote from paper A"',
                'paper_a\x00.txt: "Real quote from paper A"',
                'paper_a.txt\x07/etc/passwd: "Real quote from paper A"',
                'file:paper_a.txt: "Real quote from paper A"',
                'FILE:paper_a.txt: "Real quote from paper A"',
                'src=file:paper_a.txt: "Real quote from paper A"',
                {'source': 'file:paper_a.txt', 'quote': 'Real quote from paper A'},
                {'source': 'paper_a.txt\x00/etc/passwd', 'quote': 'Real quote from paper A'},
            )
            for bad_loc in blocked_locators:
                ok, reason = module.verify_locator(bad_loc, idx, default_source_ids=('paper_a',))
                self.assertFalse(ok, msg=repr(bad_loc))
                self.assertEqual(reason, 'unsafe_source_path', msg=repr(bad_loc))

            # Legitimate prose/locators (including words ending in "file:" or quoted "file:...") must still pass
            for good_loc in (
                'paper_a.txt: "Real quote from paper A"',
                'profile: "Real quote from paper A"',
                'paper_a.txt: "quote mentioning file:example inside prose"',
            ):
                self.assertEqual(
                    module.verify_locator(good_loc, idx, default_source_ids=('paper_a',)),
                    (True, 'verified'),
                    msg=good_loc,
                )

            prof_a = self.profile('paper_a', 8, 7)
            prof_a['evidence_locators'] = {dim: ['paper_a.txt: "Real quote from paper A"'] for dim in module.DIMENSIONS}
            prof_a['evidence_locators']['importance'] = ['paper_a.txt\x00/etc/passwd: "Real quote from paper A"']
            prof_a['evidence_locators']['novelty'] = ['file:paper_a.txt: "Real quote from paper A"']
            prof_b = self.profile('paper_b', 6, 8)
            prof_b['evidence_locators'] = {dim: ['paper_b.txt: "Real quote from paper B."'] for dim in module.DIMENSIONS}

            out = module.compare({'profiles': [prof_a, prof_b], 'weight_scenarios': self._valid_weights()}, sources_dir=src_dir)
            self.assertEqual(out['status'], 'not_comparable')
            self.assertIn('locator_unverified:paper_a:importance:0:unsafe_source_path', out['issues'])
            self.assertIn('locator_unverified:paper_a:novelty:0:unsafe_source_path', out['issues'])


if __name__ == '__main__':
    unittest.main()
