"""Dedicated tests for research-scientist/scripts/extract_pdf_blocks.py (F7)."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'research-scientist/scripts/extract_pdf_blocks.py'
spec = importlib.util.spec_from_file_location('extract_pdf_blocks', SCRIPT)
extractor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extractor)


class ExtractPdfBlocksCliAndFeatureTests(unittest.TestCase):
    def test_cli_out_and_v2_only_and_overwrite_flags(self):
        try:
            import fitz
        except ImportError:
            self.skipTest('PyMuPDF not installed')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / 'sample.pdf'
            out_json = root / 'blocks.json'
            v2_json = root / 'v2.json'
            with fitz.open() as doc:
                page = doc.new_page()
                page.insert_text((72, 72), 'Experimental evaluation shows 94.2% calibration accuracy.')
                document = doc
                document.save(pdf)

            # --out works cleanly
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), str(pdf), '--out', str(out_json)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(out_json.read_text(encoding='utf-8'))
            self.assertEqual(payload['format'], 'research_scientist_pdf_blocks_v1')
            self.assertTrue(payload['pages'][0][0]['visual_check_required'])
            self.assertIn('text', payload['pages'][0][0])

            # Default refuses overwrite; --overwrite succeeds
            proc_refuse = subprocess.run(
                [sys.executable, str(SCRIPT), str(pdf), '--out', str(out_json)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc_refuse.returncode, 2)

            proc_ow = subprocess.run(
                [sys.executable, str(SCRIPT), str(pdf), '--out', str(out_json), '--overwrite'],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc_ow.returncode, 0)

            # --v2-only writes bare list[list[dict]] MinerU Content List V2 shape
            proc_v2 = subprocess.run(
                [sys.executable, str(SCRIPT), str(pdf), '--out', str(v2_json), '--v2-only'],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc_v2.returncode, 0, proc_v2.stderr)
            v2_data = json.loads(v2_json.read_text(encoding='utf-8'))
            self.assertIsInstance(v2_data, list)
            self.assertIsInstance(v2_data[0], list)
            self.assertEqual(v2_data[0][0]['type'], 'paragraph')

    def test_tables_figure_caption_and_equation_extraction(self):
        try:
            import fitz
        except ImportError:
            self.skipTest('PyMuPDF not installed')
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / 'layout.pdf'
            with fitz.open() as doc:
                page = doc.new_page()
                # Drawn 2x2 table grid at (50, 80, 250, 140)
                page.insert_text((50, 68), 'Table 1: Benchmark comparison across models.')
                for y in (80, 110, 140):
                    page.draw_line((50, y), (250, y))
                for x in (50, 150, 250):
                    page.draw_line((x, 80), (x, 140))
                page.insert_text((60, 100), 'Method')
                page.insert_text((160, 100), 'Score')
                page.insert_text((60, 130), 'Ours')
                page.insert_text((160, 130), '94.2%')

                # Drawn figure box distinct from table
                page.draw_rect(fitz.Rect(50, 180, 250, 260))
                page.insert_text((50, 280), 'Figure 1: Calibration reliability curve.')

                # Display equation
                page.insert_text((50, 320), 'L = ∑ α_i x_i ≈ 0 (1)')
                doc.save(pdf)

            res = extractor.extract(pdf, tables=True)
            items = res['pages'][0]
            types = [it['type'] for it in items]
            self.assertIn('table', types)
            self.assertIn('image', types)
            self.assertIn('equation', types)

            tbl = next(it for it in items if it['type'] == 'table')
            self.assertIn('<table>', tbl['content']['html'])
            self.assertIn('94.2%', tbl['text'])
            self.assertTrue(tbl['visual_check_required'])
            # Fragmented cell text should not duplicate as separate paragraph items
            para_texts = ' '.join(it['text'] for it in items if it['type'] == 'paragraph')
            self.assertNotIn('94.2%', para_texts)

            fig = next(it for it in items if it['type'] == 'image')
            self.assertIn('Figure 1', fig['text'])
            self.assertTrue(fig['visual_check_required'])

    def test_ocr_scanned_pdf_and_use_mineru_wrapper(self):
        try:
            import fitz
            from PIL import Image, ImageDraw
        except ImportError:
            self.skipTest('PyMuPDF or Pillow not installed')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Create image-only scanned PDF with 0 embedded text
            img = Image.new('RGB', (800, 200), 'white')
            draw = ImageDraw.Draw(img)
            draw.text((20, 60), 'Experimental accuracy was 94.2 percent on CIFAR-10.', fill='black')
            img_path = root / 'scan.png'
            img.save(img_path)

            pdf = root / 'scanned.pdf'
            with fitz.open() as doc:
                page = doc.new_page(width=600, height=200)
                page.insert_image(fitz.Rect(20, 20, 580, 170), filename=str(img_path))
                doc.save(pdf)

            res = extractor.extract(pdf, ocr=True)
            self.assertEqual(res['ocr_pages_one_based'], [1])
            ocr_items = [it for it in res['pages'][0] if it.get('ocr_used')]
            self.assertTrue(ocr_items)
            self.assertTrue(all(it['visual_check_required'] for it in ocr_items))

            # --use-mineru missing binary exits 2 with mineru_cli_not_found
            out_m = root / 'mineru_out.json'
            env_no_mineru = dict(os.environ, PATH='/usr/bin:/bin')
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), str(pdf), '--out', str(out_m), '--use-mineru'],
                capture_output=True, text=True, env=env_no_mineru, check=False,
            )
            self.assertEqual(proc.returncode, 2)
            err_json = json.loads(proc.stderr)
            self.assertEqual(err_json['status'], 'mineru_cli_not_found')

            # Dummy mineru script on PATH succeeds via external subprocess
            bin_dir = root / 'bin'
            bin_dir.mkdir()
            dummy = bin_dir / 'mineru'
            dummy.write_text(
                '#!/usr/bin/env python3\n'
                'import json, sys\n'
                'from pathlib import Path\n'
                'out_dir = Path(sys.argv[sys.argv.index("-o") + 1])\n'
                '(out_dir / "doc_content_list_v2.json").write_text(json.dumps([[{"type":"paragraph","text":"MinerU parsed"}]]))\n',
                encoding='utf-8',
            )
            dummy.chmod(0o755)
            env_with_mineru = dict(os.environ, PATH=f"{bin_dir}:{os.environ.get('PATH', '')}")
            proc_ok = subprocess.run(
                [sys.executable, str(SCRIPT), str(pdf), '--out', str(out_m), '--use-mineru'],
                capture_output=True, text=True, env=env_with_mineru, check=False,
            )
            self.assertEqual(proc_ok.returncode, 0, proc_ok.stderr)
            parsed_m = json.loads(out_m.read_text(encoding='utf-8'))
            self.assertEqual(parsed_m['status'], 'extracted_mineru_cli')

    def test_tables_ocr_on_native_table_page_does_not_trigger_spurious_ocr(self):
        try:
            import fitz
        except ImportError:
            self.skipTest('PyMuPDF not installed')
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / 'table_only.pdf'
            with fitz.open() as doc:
                page = doc.new_page()
                for y in (80, 110, 140):
                    page.draw_line((50, y), (350, y))
                for x in (50, 200, 350):
                    page.draw_line((x, 80), (x, 140))
                page.insert_text((60, 100), 'Model Name')
                page.insert_text((210, 100), 'Accuracy Score')
                page.insert_text((60, 130), 'Baseline Alpha')
                page.insert_text((210, 130), '88.5 percent')
                doc.save(pdf)

            res = extractor.extract(pdf, tables=True, ocr=True)
            self.assertEqual(res['tables_extracted'], 1)
            self.assertEqual(res['ocr_pages_one_based'], [])
            self.assertEqual(res['pages_with_little_text_one_based'], [])
            ocr_items = [it for it in res['pages'][0] if it.get('ocr_used')]
            self.assertEqual(ocr_items, [])

    def test_tables_on_empty_corrupt_truncated_encrypted_pdfs_exits_2_no_traceback(self):
        try:
            import fitz
        except ImportError:
            self.skipTest('PyMuPDF not installed')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            empty_pdf = root / 'empty.pdf'
            empty_pdf.write_bytes(b'')
            corrupt_pdf = root / 'corrupt.pdf'
            corrupt_pdf.write_bytes(b'NOT A PDF FILE AT ALL')

            valid_pdf = root / 'valid.pdf'
            with fitz.open() as doc:
                page = doc.new_page()
                page.insert_text((72, 72), 'Hello valid PDF content.')
                doc.save(valid_pdf)
            raw_valid = valid_pdf.read_bytes()
            truncated_pdf = root / 'truncated.pdf'
            truncated_pdf.write_bytes(raw_valid[:max(20, len(raw_valid) // 2)])

            encrypted_pdf = root / 'encrypted.pdf'
            with fitz.open() as doc:
                page = doc.new_page()
                page.insert_text((72, 72), 'Secret text')
                doc.save(encrypted_pdf, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw='secret', owner_pw='owner')

            for idx, bad_pdf in enumerate((empty_pdf, corrupt_pdf, truncated_pdf, encrypted_pdf)):
                out_json = root / f'out_{idx}.json'
                proc = subprocess.run(
                    [sys.executable, str(SCRIPT), str(bad_pdf), '--out', str(out_json), '--tables', '--ocr'],
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(proc.returncode, 2, f'{bad_pdf.name}: stderr={proc.stderr}')
                self.assertNotIn('Traceback', proc.stderr)
                err_payload = json.loads(proc.stderr)
                self.assertIn('error', err_payload)
                self.assertFalse(out_json.exists())

    def test_external_mineru_flat_list_preserves_multipage_page_idx(self):
        try:
            import fitz
        except ImportError:
            self.skipTest('PyMuPDF not installed')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / 'dummy.pdf'
            with fitz.open() as doc:
                doc.new_page().insert_text((72, 72), 'Page 0')
                doc.new_page().insert_text((72, 72), 'Page 1')
                doc.new_page().insert_text((72, 72), 'Page 2')
                doc.save(pdf)

            bin_dir = root / 'bin'
            bin_dir.mkdir()
            dummy = bin_dir / 'mineru'
            flat_items = [
                {'type': 'paragraph', 'page_idx': 0, 'text': 'Page zero block'},
                {'type': 'paragraph', 'page_idx': 2, 'text': 'Page two block'},
            ]
            dummy.write_text(
                '#!/usr/bin/env python3\n'
                'import json, sys\n'
                'from pathlib import Path\n'
                'out_dir = Path(sys.argv[sys.argv.index("-o") + 1])\n'
                f'(out_dir / "doc_content_list.json").write_text({json.dumps(json.dumps(flat_items))})\n',
                encoding='utf-8',
            )
            dummy.chmod(0o755)
            out_m = root / 'mineru_flat.json'
            env_with_mineru = dict(os.environ, PATH=f"{bin_dir}:{os.environ.get('PATH', '')}")
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), str(pdf), '--out', str(out_m), '--use-mineru'],
                capture_output=True, text=True, env=env_with_mineru, check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            parsed = json.loads(out_m.read_text(encoding='utf-8'))
            self.assertEqual(len(parsed['pages']), 3)
            self.assertEqual(parsed['pages'][0][0]['text'], 'Page zero block')
            self.assertEqual(parsed['pages'][1], [])
            self.assertEqual(parsed['pages'][2][0]['text'], 'Page two block')

    def test_compact_flag_writes_artifact_and_emits_bounded_summary(self):
        try:
            import fitz
        except ImportError:
            self.skipTest('PyMuPDF not installed')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / 'compact.pdf'
            out_json = root / 'full_blocks.json'
            with fitz.open() as doc:
                page = doc.new_page()
                page.insert_text((72, 72), 'Experimental calibration evaluation with 95.1% accuracy.')
                doc.save(pdf)

            proc = subprocess.run(
                [sys.executable, str(SCRIPT), str(pdf), '--out', str(out_json), '--compact'],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            summary = json.loads(proc.stdout)
            self.assertTrue(summary['compact'])
            self.assertEqual(summary['artifact_path'], str(out_json.resolve()))
            self.assertEqual(summary['pages_extracted'], 1)
            self.assertEqual(summary['total_pages'], 1)
            self.assertIn('source_pdf_sha256', summary)
            self.assertNotIn('pages', summary)
            full_payload = json.loads(out_json.read_text(encoding='utf-8'))
            self.assertEqual(full_payload['format'], 'research_scientist_pdf_blocks_v1')
            self.assertEqual(len(full_payload['pages']), 1)

            # Auto-artifact path when --out is omitted with --compact
            proc_auto = subprocess.run(
                [sys.executable, str(SCRIPT), str(pdf), '--compact'],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc_auto.returncode, 0, proc_auto.stderr)
            summary_auto = json.loads(proc_auto.stdout)
            auto_path = Path(summary_auto['artifact_path'])
            try:
                self.assertTrue(auto_path.is_file())
                self.assertEqual(json.loads(auto_path.read_text(encoding='utf-8'))['format'], 'research_scientist_pdf_blocks_v1')
            finally:
                if auto_path.exists():
                    auto_path.unlink()

    def test_symlink_pdf_rejected_and_failed_compact_leaves_no_orphan_artifact(self):
        try:
            import fitz
        except ImportError:
            self.skipTest('PyMuPDF not installed')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_pdf = root / 'real.pdf'
            with fitz.open() as doc:
                doc.new_page().insert_text((72, 72), 'Valid paper content.')
                doc.save(real_pdf)

            sym_pdf = root / 'symlink.pdf'
            os.symlink(real_pdf, sym_pdf)

            # Direct extract() rejects symlink before resolving
            with self.assertRaisesRegex(ValueError, 'symlink'):
                extractor.extract(sym_pdf)

            # CLI rejects symlink with rc=2, JSON error on stderr, no traceback, and no orphan --compact artifact
            art_dir = Path(tempfile.gettempdir()) / 'research_scientist_artifacts'
            before_artifacts = set(art_dir.glob('extract_pdf_blocks_*.json')) if art_dir.is_dir() else set()

            proc_sym = subprocess.run(
                [sys.executable, str(SCRIPT), str(sym_pdf), '--compact'],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc_sym.returncode, 2)
            self.assertNotIn('Traceback', proc_sym.stderr)
            err_sym = json.loads(proc_sym.stderr)
            self.assertIn('symlink', err_sym['error'].lower())

            corrupt_pdf = root / 'corrupt.pdf'
            corrupt_pdf.write_bytes(b'NOT A PDF')
            proc_bad = subprocess.run(
                [sys.executable, str(SCRIPT), str(corrupt_pdf), '--compact'],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc_bad.returncode, 2)
            self.assertNotIn('Traceback', proc_bad.stderr)
            err_bad = json.loads(proc_bad.stderr)
            self.assertIn('error', err_bad)

            after_artifacts = set(art_dir.glob('extract_pdf_blocks_*.json')) if art_dir.is_dir() else set()
            self.assertEqual(after_artifacts - before_artifacts, set())

    def test_output_symlink_rejected_even_with_overwrite(self):
        try:
            import fitz
        except ImportError:
            self.skipTest('PyMuPDF not installed')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / 'sample.pdf'
            with fitz.open() as doc:
                doc.new_page().insert_text((72, 72), 'Valid paper content.')
                doc.save(pdf)

            target_json = root / 'target.json'
            target_json.write_text('{"sentinel": true}', encoding='utf-8')
            sym_out = root / 'out_link.json'
            os.symlink(target_json, sym_out)

            for extra in ([], ['--overwrite']):
                proc = subprocess.run(
                    [sys.executable, str(SCRIPT), str(pdf), '--out', str(sym_out), *extra],
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(proc.returncode, 2)
                self.assertNotIn('Traceback', proc.stderr)
                err = json.loads(proc.stderr)
                self.assertIn('symlink', err['error'].lower())
                self.assertEqual(target_json.read_text(encoding='utf-8'), '{"sentinel": true}')

            dangling_out = root / 'dangling_link.json'
            dangling_target = root / 'does_not_exist.json'
            os.symlink(dangling_target, dangling_out)
            proc_dangling = subprocess.run(
                [sys.executable, str(SCRIPT), str(pdf), '--out', str(dangling_out), '--overwrite'],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc_dangling.returncode, 2)
            self.assertIn('symlink', json.loads(proc_dangling.stderr)['error'].lower())
            self.assertFalse(dangling_target.exists())

    def test_external_mineru_tallies_tables_figures_and_equations_from_pages(self):
        try:
            import fitz
        except ImportError:
            self.skipTest('PyMuPDF not installed')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / 'mineru_counts.pdf'
            with fitz.open() as doc:
                doc.new_page().insert_text((72, 72), 'Page 0')
                doc.save(pdf)

            bin_dir = root / 'bin'
            bin_dir.mkdir()
            dummy = bin_dir / 'mineru'
            pages_payload = [[
                {'type': 'paragraph', 'text': 'Intro'},
                {'type': 'table', 'text': 'T1'},
                {'type': 'table', 'text': 'T2'},
                {'type': 'image', 'text': 'F1'},
                {'type': 'chart', 'text': 'F2'},
                {'type': 'image', 'text': 'F3'},
                {'type': 'equation', 'text': 'E1'},
                {'type': 'equation_interline', 'text': 'E2'},
            ]]
            dummy.write_text(
                '#!/usr/bin/env python3\n'
                'import json, sys\n'
                'from pathlib import Path\n'
                'out_dir = Path(sys.argv[sys.argv.index("-o") + 1])\n'
                f'(out_dir / "doc_content_list_v2.json").write_text({json.dumps(json.dumps(pages_payload))})\n',
                encoding='utf-8',
            )
            dummy.chmod(0o755)
            out_m = root / 'mineru_tallied.json'
            env_with_mineru = dict(os.environ, PATH=f"{bin_dir}:{os.environ.get('PATH', '')}")
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), str(pdf), '--out', str(out_m), '--use-mineru', '--compact'],
                capture_output=True, text=True, env=env_with_mineru, check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            summary = json.loads(proc.stdout)
            self.assertEqual(summary['tables_extracted'], 2)
            self.assertEqual(summary['figures_detected'], 3)
            self.assertEqual(summary['equations_detected'], 2)
            full_payload = json.loads(out_m.read_text(encoding='utf-8'))
            self.assertEqual(full_payload['tables_extracted'], 2)
            self.assertEqual(full_payload['figures_detected'], 3)
            self.assertEqual(full_payload['equations_detected'], 2)


if __name__ == '__main__':
    unittest.main()
