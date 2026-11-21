"""Comprehensive offline tests for F7/F8: PaperQA2 chunking, Shannon entropy, GPT Researcher stemmed BM25, MMR, ABSTAIN gate, and clean-room Khoj HTTP client."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'research-scientist/scripts'


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name.removesuffix('.py'), SCRIPTS / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


extractor = _load('extract_pdf_blocks.py')
local = _load('local_evidence.py')


class PaperQA2AndCorpusQATests(unittest.TestCase):
    def test_shannon_entropy_drops_gibberish_but_preserves_short_headings_and_equations(self):
        self.assertTrue(local.maybe_is_text('Title'))
        self.assertTrue(local.maybe_is_text('x=1'))
        self.assertFalse(local.maybe_is_text('AAAAAAAAAAAAAAAAAAAAAAAAAA'))
        self.assertFalse(local.maybe_is_text('ab' * 20))

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'doc.txt'
            p.write_text(
                'Title\n\n'
                'AAAAAAAAAAAAAAAAAAAAAAAAAAAA\n\n'
                'Valid experimental paragraph about graph neural networks.',
                encoding='utf-8',
            )
            report = local.run([p], 'graph neural networks', min_studies=1, min_evidence=1)
            self.assertEqual(report['dropped_low_entropy_chunks'], 1)
            self.assertEqual(report['returned'], 1)

    def test_overlapping_page_aware_chunking_and_stemmed_bm25(self):
        with tempfile.TemporaryDirectory() as tmp:
            v2_path = Path(tmp) / 'multi_page.json'
            long_p1 = ' '.join(['battery'] * 40) + ' degradation observed on page one.'
            long_p2 = ' '.join(['thermal'] * 40) + ' runaway mitigation on page two.'
            pages = [
                [{'type': 'paragraph', 'content': {'paragraph_content': [{'content': long_p1}]}}],
                [{'type': 'paragraph', 'content': {'paragraph_content': [{'content': long_p2}]}}],
            ]
            v2_path.write_text(json.dumps(pages), encoding='utf-8')
            report = local.run(
                [v2_path], 'batteries', limit=5,
                chunk_chars=250, chunk_overlap=50, min_studies=1, min_evidence=1,
            )
            self.assertGreaterEqual(report['segments_indexed'], 2)
            self.assertGreaterEqual(report['returned'], 1)
            hit = report['results'][0]
            self.assertIn('page_span', hit)
            self.assertIn('battery', local.tokens('batteries'))
            self.assertEqual(local._stem('batteries'), local._stem('battery'))

    def test_mmr_diversity_vs_bm25_fallback_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p1 = root / 'study_a.txt'
            p2 = root / 'study_b.txt'
            p1.write_text(
                'Graph classification with graph classification convolution accuracy reaches 94 percent on Cora.\n\n'
                'Graph classification with graph classification convolution accuracy reaches 94 percent on Cora benchmark.',
                encoding='utf-8',
            )
            p2.write_text(
                'Spectral wavelet methods for graph classification improve robustness under adversarial node perturbations across multiple biological and citation benchmarks.',
                encoding='utf-8',
            )
            r_mmr = local.run([p1, p2], 'graph classification', limit=2, mmr_lambda=0.3, min_studies=1, min_evidence=1)
            self.assertEqual(r_mmr['reranker_mode'], 'bm25_mmr')
            self.assertEqual(r_mmr['distinct_studies'], 2)

            r_fb = local.run([p1, p2], 'graph classification', limit=2, mmr_lambda=1.0, min_studies=1, min_evidence=1)
            self.assertEqual(r_fb['reranker_mode'], 'bm25_fallback')
            self.assertEqual(r_fb['distinct_studies'], 1)

    def test_abstain_vs_answerable_gate_and_citation_context_packing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            s1 = root / 'paper_one.txt'
            s2 = root / 'paper_two.txt'
            s1.write_text(
                'First calibration experiment improved ECE by 3 percent.\n\n'
                'Second calibration ablation confirmed lower Brier score.',
                encoding='utf-8',
            )
            s2.write_text('Independent calibration validation on medical imaging datasets.', encoding='utf-8')

            abstain_res = local.run([s1], 'calibration', limit=5, min_studies=2, min_evidence=2)
            self.assertEqual(abstain_res['gate_status'], 'ABSTAIN')
            self.assertEqual(abstain_res['distinct_studies'], 1)
            self.assertIn('distinct_studies', abstain_res['abstain_reason'])

            answerable_res = local.run([s1, s2], 'calibration', limit=5, min_studies=2, min_evidence=2)
            self.assertEqual(answerable_res['gate_status'], 'ANSWERABLE')
            self.assertEqual(answerable_res['distinct_studies'], 2)
            self.assertIn('[', answerable_res['context_packed'])
            self.assertTrue(answerable_res['ranked_passages'])

    def test_khoj_url_clean_room_http_client_and_error_handling(self):
        captured_paths = []

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                captured_paths.append(self.path)
                body = json.dumps([
                    {
                        'entry': 'Khoj semantic hit about normalized graph Laplacian.',
                        'score': 0.91,
                        'cross_score': 0.88,
                        'corpus_id': 'khoj-doc-1',
                        'additional': {'file': 'notes.md'},
                    }
                ]).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                return

        server = HTTPServer(('127.0.0.1', 0), _Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                local_file = Path(tmp) / 'local.txt'
                local_file.write_text('Normalized graph Laplacian eigenvalues bound diffusion.', encoding='utf-8')
                res = local.run(
                    [local_file], 'graph Laplacian',
                    min_studies=2, min_evidence=2,
                    khoj_url=f'http://127.0.0.1:{port}',
                )
                self.assertEqual(res['khoj_status'], 'ok')
                self.assertEqual(len(res['khoj_results']), 1)
                self.assertEqual(res['distinct_studies'], 2)
                self.assertEqual(res['gate_status'], 'ANSWERABLE')
                self.assertTrue(any('/api/search?q=' in p for p in captured_paths))
        finally:
            server.shutdown()
            server.server_close()

        # Unreachable URL reports graceful unavailable status without crashing
        k_res, k_status = local.query_khoj('http://127.0.0.1:1', 'test query')
        self.assertEqual(k_res, [])
        self.assertEqual(k_status, 'unavailable')

    def test_khoj_malformed_http_line_degrades_gracefully_without_crash(self):
        import socket

        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(('127.0.0.1', 0))
        srv.listen(2)
        port = srv.getsockname()[1]

        def _serve_garbage():
            try:
                conn, _ = srv.accept()
                with conn:
                    conn.recv(4096)
                    conn.sendall(b'GARBAGE_NOT_HTTP\r\n\r\n')
            except OSError:
                pass

        t = threading.Thread(target=_serve_garbage, daemon=True)
        t.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                local_file = Path(tmp) / 'local.txt'
                local_file.write_text('Normalized graph Laplacian eigenvalues bound diffusion.', encoding='utf-8')
                res = local.run(
                    [local_file], 'graph Laplacian',
                    min_studies=1, min_evidence=1,
                    khoj_url=f'http://127.0.0.1:{port}',
                )
                self.assertEqual(res['khoj_status'], 'unavailable')
                self.assertEqual(res['returned'], 1)
                self.assertEqual(res['gate_status'], 'ANSWERABLE')
        finally:
            srv.close()
            t.join(timeout=2)

    def test_mmr_lambda_05_promotes_diverse_study_b_with_slightly_lower_bm25(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sa = root / 'study_a.txt'
            sb = root / 'study_b.txt'
            sa.write_text(
                'Graph neural network calibration accuracy reaches high precision on citation benchmarks.\n\n'
                'Graph neural network calibration accuracy reaches high precision on citation benchmarks today.',
                encoding='utf-8',
            )
            sb.write_text(
                'Graph neural network calibration reliability improves under distribution shift across unseen protein graphs and molecular tasks.',
                encoding='utf-8',
            )
            res = local.run([sa, sb], 'graph neural network calibration', limit=2, mmr_lambda=0.5, min_studies=2, min_evidence=2)
            self.assertEqual(res['reranker_mode'], 'bm25_mmr')
            self.assertEqual(res['distinct_studies'], 2)
            self.assertEqual(res['gate_status'], 'ANSWERABLE')


if __name__ == '__main__':
    unittest.main()
