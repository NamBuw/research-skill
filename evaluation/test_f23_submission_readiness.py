"""Unmocked unit & contract tests for F23 Submission Readiness & Venue Standing."""
from __future__ import annotations

import copy
import decimal
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / 'research-scientist' / 'scripts'
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


score_math = _load_module('score_math', SCRIPTS_DIR / 'score_math.py')
compare_scorecards = _load_module('compare_scorecards', SCRIPTS_DIR / 'compare_scorecards.py')
compare_venue_novelty = _load_module('compare_venue_novelty', SCRIPTS_DIR / 'compare_venue_novelty.py')
claim_audit = _load_module('claim_audit', SCRIPTS_DIR / 'claim_audit.py')
report_latex_pdf = _load_module('report_latex_pdf', SCRIPTS_DIR / 'report_latex_pdf.py')

FABRICATED_ODDS_RE = re.compile(
    r'\b\d+(?:\.\d+)?%\s*(?:acceptance|chance|odds|probability)',
    re.IGNORECASE,
)


def _weights(vals):
    return dict(zip(score_math.DIMENSIONS, vals))


def _ratings(vals):
    return dict(zip(score_math.DIMENSIONS, vals))


class TestScoreMathSubmissionReadiness(unittest.TestCase):
    def test_635_weighted_case_api_and_cli(self):
        payload = {
            'weights': _weights((15, 20, 20, 20, 15, 10)),
            'ratings': _ratings((7, 6, 7, 6, 6, 6)),
        }
        res = score_math.score(payload)
        self.assertEqual(res['weighted_unrounded'], '6.35')
        self.assertEqual(res['overall'], 6)
        self.assertEqual(res['status'], 'calculated')
        self.assertIn('warning', res)

        sr = res['submission_readiness']
        self.assertEqual(sr['band'], 'borderline_top_tier_competitive_findings_tier_a')
        self.assertEqual(sr['delta_to_competitive_top_tier'], -0.45)
        self.assertTrue(sr['ready_for_findings_or_tier_a'])
        self.assertFalse(sr['ready_for_top_tier_main_track'])
        self.assertFalse(sr['fatal_gate_triggered'])
        self.assertEqual(sr['fatal_dimensions'], [])
        self.assertEqual(sr['fatal_reasons'], [])
        self.assertEqual(
            set(sr['bottleneck_dimensions']),
            {'novelty', 'evidence', 'transparency', 'clarity'},
        )
        self.assertTrue(sr['guidance'])
        self.assertIsNone(FABRICATED_ODDS_RE.search(sr['guidance']))

        cli_stdin = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / 'score_math.py')],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(cli_stdin.returncode, 0, cli_stdin.stderr)
        self.assertEqual(json.loads(cli_stdin.stdout), res)

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'score.json'
            p.write_text(json.dumps(payload), encoding='utf-8')
            cli_file = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / 'score_math.py'), str(p)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(cli_file.returncode, 0, cli_file.stderr)
            self.assertEqual(json.loads(cli_file.stdout), res)

    def test_fatal_gate_overrides_high_weighted_mean(self):
        w = _weights((15, 20, 20, 20, 15, 10))
        cases = [
            ('soundness', _ratings((9, 8, 4, 8, 8, 8)), '7.35'),
            ('evidence', _ratings((9, 8, 8, 4, 8, 8)), '7.35'),
            ('novelty', _ratings((9, 2, 8, 8, 8, 8)), '6.95'),
            ('transparency', _ratings((9, 8, 8, 8, 3, 8)), '7.4'),
            ('importance', _ratings((2, 8, 8, 8, 8, 8)), '7.1'),
            ('clarity', _ratings((8, 8, 8, 8, 8, 2)), '7.4'),
        ]
        for dim, r, expected_raw in cases:
            res = score_math.score({'weights': w, 'ratings': r})
            self.assertEqual(res['weighted_unrounded'], expected_raw)
            sr = res['submission_readiness']
            self.assertEqual(sr['band'], 'not_ready_fatal_gate', dim)
            self.assertTrue(sr['fatal_gate_triggered'], dim)
            self.assertIn(dim, sr['fatal_dimensions'], dim)
            self.assertFalse(sr['ready_for_top_tier_main_track'], dim)
            self.assertFalse(sr['ready_for_findings_or_tier_a'], dim)

        for key in ('status', 'object_type'):
            idea_res = score_math.score({
                'weights': w,
                'ratings': _ratings((8, 8, 8, 8, 8, 8)),
                key: 'idea',
            })
            self.assertEqual(idea_res['weighted_unrounded'], '8')
            sr = idea_res['submission_readiness']
            self.assertEqual(sr['band'], 'not_ready_fatal_gate')
            self.assertTrue(sr['fatal_gate_triggered'])
            self.assertIn('unrun_idea_results', sr['fatal_reasons'])
            self.assertFalse(sr['ready_for_top_tier_main_track'])
            self.assertFalse(sr['ready_for_findings_or_tier_a'])

        missing_res = score_math.score({
            'weights': w,
            'ratings': _ratings((8, None, 8, 8, 8, 8)),
        })
        self.assertEqual(missing_res['status'], 'not_comparable')
        self.assertIsNone(missing_res['overall'])
        self.assertEqual(missing_res['submission_readiness']['band'], 'not_comparable_missing_dimension')
        self.assertFalse(missing_res['submission_readiness']['ready_for_top_tier_main_track'])
        self.assertFalse(missing_res['submission_readiness']['ready_for_findings_or_tier_a'])

        with self.assertRaises(ValueError):
            score_math.score({
                'weights': w,
                'ratings': _ratings((8, None, 8, 8, 8, 8)),
                'status': 123,
            })

    def test_all_five_calibrated_bands_and_exact_boundaries(self):
        cases = [
            ((1, 1, 50, 40, 7, 1), (4, 4, 5, 5, 5, 6), '4.99', 'not_ready_major_rework', False, False, -1.81),
            ((15, 20, 20, 20, 15, 10), (5, 5, 5, 5, 5, 5), '5', 'workshop_or_preliminary_only', False, False, -1.8),
            ((1, 1, 50, 40, 7, 1), (5, 5, 6, 6, 6, 7), '5.99', 'workshop_or_preliminary_only', False, False, -0.81),
            ((15, 20, 20, 20, 15, 10), (6, 6, 6, 6, 6, 6), '6', 'borderline_top_tier_competitive_findings_tier_a', False, True, -0.8),
            ((1, 1, 50, 27, 20, 1), (6, 6, 7, 7, 6, 8), '6.79', 'borderline_top_tier_competitive_findings_tier_a', False, True, -0.01),
            ((15, 20, 20, 20, 15, 10), (8, 7, 7, 7, 6, 5), '6.8', 'competitive_top_tier_main_track', True, True, 0.0),
            ((1, 1, 50, 27, 20, 1), (7, 7, 8, 8, 7, 9), '7.79', 'competitive_top_tier_main_track', True, True, 0.99),
            ((15, 20, 20, 20, 15, 10), (9, 8, 8, 8, 7, 6), '7.8', 'strong_top_tier_contender', True, True, 1.0),
        ]
        for w, r, exp_raw, exp_band, exp_top, exp_find, exp_delta in cases:
            res = score_math.score({'weights': _weights(w), 'ratings': _ratings(r)})
            self.assertEqual(res['weighted_unrounded'], exp_raw)
            sr = res['submission_readiness']
            self.assertEqual(sr['band'], exp_band, exp_raw)
            self.assertIs(sr['ready_for_top_tier_main_track'], exp_top, exp_raw)
            self.assertIs(sr['ready_for_findings_or_tier_a'], exp_find, exp_raw)
            self.assertEqual(sr['delta_to_competitive_top_tier'], exp_delta, exp_raw)
            self.assertIsNone(FABRICATED_ODDS_RE.search(sr['guidance']))

    def test_decimal_context_trap_isolation_with_readiness(self):
        payload = {
            'weights': _weights((15, 20, 20, 20, 15, 10)),
            'ratings': _ratings((7, 6, 7, 6, 6, 6)),
        }
        with decimal.localcontext() as ctx:
            ctx.prec = 1
            ctx.rounding = decimal.ROUND_DOWN
            ctx.traps[decimal.Inexact] = True
            ctx.traps[decimal.Rounded] = True
            ctx.traps[decimal.FloatOperation] = True
            res = score_math.score(payload)
        self.assertEqual(res['weighted_unrounded'], '6.35')
        self.assertEqual(res['submission_readiness']['delta_to_competitive_top_tier'], -0.45)

    def test_nan_and_bool_rejected(self):
        with self.assertRaises(ValueError):
            score_math.score({
                'weights': _weights((15, 20, 20, 20, 15, 10)),
                'ratings': _ratings((True, 6, 7, 6, 6, 6)),
            })
        cli = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / 'score_math.py')],
            input='{"weights":{"importance":15,"novelty":20,"soundness":20,"evidence":20,"transparency":15,"clarity":10},"ratings":{"importance":NaN,"novelty":6,"soundness":7,"evidence":6,"transparency":6,"clarity":6}}',
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(cli.returncode, 2)


class TestCompareScorecardsSubmissionReadiness(unittest.TestCase):
    def _write_sources(self, root: Path, pids: list[str]) -> dict:
        profiles = []
        for pid, r_vals, extra in [
            ('paper_635', (7, 6, 7, 6, 6, 6), {}),
            ('paper_fatal', (9, 8, 4, 8, 8, 8), {}),
            ('paper_top', (8, 7, 7, 7, 8, 7), {}),
        ]:
            if pid not in pids:
                continue
            src = root / f'{pid}.txt'
            src.write_text(f'Full evidence text for {pid} method evaluation.\n', encoding='utf-8')
            loc = f'{pid}.txt#L1 "method evaluation"'
            profiles.append({
                'id': pid,
                'reading_basis': 'full_text',
                'closest_work': ['PriorWork2024'],
                'ratings': _ratings(r_vals),
                'evidence_locators': {d: [loc] for d in score_math.DIMENSIONS},
                **extra,
            })
        return {
            'weight_scenarios': [_weights((15, 20, 20, 20, 15, 10))],
            'profiles': profiles,
        }

    def test_full_and_compact_surface_per_profile_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            src_dir = tmp_dir / 'sources'
            src_dir.mkdir()
            doc = self._write_sources(src_dir, ['paper_635', 'paper_fatal', 'paper_top'])
            sc_path = tmp_dir / 'scorecards.json'
            sc_path.write_text(json.dumps(doc), encoding='utf-8')
            out_path = tmp_dir / 'full_report.json'

            out = compare_scorecards.compare(doc, sources_dir=src_dir)
            self.assertEqual(out['status'], 'structurally_comparable')
            self.assertEqual(
                [list(row.keys()) for row in out['rankings'][0]['ordered']],
                [['id', 'weighted_unrounded']] * 3,
            )

            sr = out['submission_readiness']
            self.assertEqual(sr['paper_635']['band'], 'borderline_top_tier_competitive_findings_tier_a')
            self.assertEqual(sr['paper_635']['delta_to_competitive_top_tier'], -0.45)
            self.assertTrue(sr['paper_635']['structural_gate_passed'])
            self.assertEqual(sr['paper_fatal']['band'], 'not_ready_fatal_gate')
            self.assertFalse(sr['paper_fatal']['ready_for_top_tier_main_track'])
            self.assertFalse(sr['paper_fatal']['ready_for_findings_or_tier_a'])
            self.assertIn('soundness', sr['paper_fatal']['fatal_dimensions'])
            self.assertEqual(sr['paper_top']['band'], 'competitive_top_tier_main_track')
            self.assertTrue(sr['paper_top']['ready_for_top_tier_main_track'])

            cli = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / 'compare_scorecards.py'),
                    str(sc_path),
                    '--sources-dir',
                    str(src_dir),
                    '--out',
                    str(out_path),
                    '--compact',
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(cli.returncode, 0, cli.stderr)
            self.assertLess(len(cli.stdout.encode('utf-8')), 4096)
            compact = json.loads(cli.stdout)
            self.assertIn('submission_readiness', compact)
            self.assertEqual(compact['submission_readiness']['paper_635']['band'], 'borderline_top_tier_competitive_findings_tier_a')
            self.assertEqual(compact['submission_readiness']['paper_fatal']['band'], 'not_ready_fatal_gate')

    def test_structural_gate_and_idea_forwarding_and_schema_example_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            src_dir = tmp_dir / 'sources'
            src_dir.mkdir()
            doc = self._write_sources(src_dir, ['paper_635', 'paper_top'])
            doc['profiles'][0]['reading_basis'] = 'abstract'
            doc['profiles'][1]['status'] = 'idea'

            out = compare_scorecards.compare(doc)
            self.assertEqual(out['status'], 'not_comparable')
            sr = out['submission_readiness']
            self.assertEqual(sr['paper_635']['band'], 'not_comparable_structural_gate')
            self.assertFalse(sr['paper_635']['structural_gate_passed'])
            self.assertFalse(sr['paper_635']['ready_for_findings_or_tier_a'])
            self.assertEqual(sr['paper_top']['band'], 'not_ready_fatal_gate')
            self.assertIn('unrun_idea_results', sr['paper_top']['fatal_reasons'])

            example = json.loads((ROOT / 'research-scientist' / 'references' / 'scorecards.schema-example.json').read_text(encoding='utf-8'))
            ex_out = compare_scorecards.compare(example)
            self.assertFalse(ex_out['submission_readiness']['fictional_paper_A']['band_stable_across_scenarios'])
            pdf_out = tmp_dir / 'scorecard_summary.pdf'
            rep = report_latex_pdf.generate_report(ex_out, pdf_out, strict=True, compact=True)
            self.assertEqual(rep['status'], 'ok', rep)

    def test_wave1_compact_30_profiles_exact_pid_attribution_and_fatal_pdf_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            src_dir = tmp_dir / 'sources'
            src_dir.mkdir()
            w = _weights((15, 20, 20, 20, 15, 10))

            # 1. 30 profiles x 2 scenarios + --compact must stay < 4096 UTF-8 bytes
            profiles_30 = []
            for i in range(30):
                pid = f'benchmark_paper_profile_{i:02d}_long_identifier'
                (src_dir / f'{pid}.txt').write_text(f'Full evidence text for {pid}.\n', encoding='utf-8')
                profiles_30.append({
                    'id': pid,
                    'reading_basis': 'full_text',
                    'closest_work': ['PriorWork2024'],
                    'ratings': _ratings((7, 6, 7, 6, 6, 6)),
                    'evidence_locators': {d: [f'{pid}.txt#L1 "Full evidence text"'] for d in score_math.DIMENSIONS},
                })
            doc_30 = {
                'weight_scenarios': [w, _weights((25, 10, 20, 20, 15, 10))],
                'profiles': profiles_30,
            }
            p30 = tmp_dir / 'p30.json'
            p30.write_text(json.dumps(doc_30), encoding='utf-8')
            out30 = tmp_dir / 'p30_out.json'
            cli30 = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / 'compare_scorecards.py'), str(p30), '--sources-dir', str(src_dir), '--out', str(out30), '--compact'],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(cli30.returncode, 0, cli30.stderr)
            self.assertLess(len(cli30.stdout.encode('utf-8')), 4096)

            # 2. Profile IDs colliding with dimension/index/reason ('soundness', '0', 'quote_not_found')
            src_coll = tmp_dir / 'coll_sources'
            src_coll.mkdir()
            for pid in ('valid_bad_loc', 'soundness', '0', 'quote_not_found'):
                (src_coll / f'{pid}.txt').write_text(f'Verified text for {pid}.\n', encoding='utf-8')
            coll_profiles = []
            for pid in ('valid_bad_loc', 'soundness', '0', 'quote_not_found'):
                locs = {d: [f'{pid}.txt#L1 "Verified text"'] for d in score_math.DIMENSIONS}
                if pid == 'valid_bad_loc':
                    locs['soundness'] = ['valid_bad_loc.txt#L1 "Nonexistent quote"']
                    locs['clarity'] = ['valid_bad_loc.txt#L1 "Nonexistent quote"']
                coll_profiles.append({
                    'id': pid,
                    'reading_basis': 'full_text',
                    'closest_work': ['PriorWork2024'],
                    'ratings': _ratings((8, 8, 8, 8, 8, 8)),
                    'evidence_locators': locs,
                })
            coll_out = compare_scorecards.compare({'weight_scenarios': [w], 'profiles': coll_profiles}, sources_dir=src_coll)
            self.assertEqual(coll_out['status'], 'not_comparable')
            for clean_pid in ('soundness', '0', 'quote_not_found'):
                self.assertEqual(coll_out['submission_readiness'][clean_pid]['profile_issues'], [])
                self.assertTrue(coll_out['submission_readiness'][clean_pid]['structural_gate_passed'])
            self.assertGreater(len(coll_out['submission_readiness']['valid_bad_loc']['profile_issues']), 0)
            self.assertFalse(coll_out['submission_readiness']['valid_bad_loc']['structural_gate_passed'])

            # 3. report_latex_pdf.normalize_report_input never returns pass/supported on fatal gates
            fatal_doc = self._write_sources(src_dir, ['paper_635', 'paper_fatal'])
            fatal_sc_out = compare_scorecards.compare(fatal_doc, sources_dir=src_dir)
            norm_sc_fatal = report_latex_pdf.normalize_report_input(fatal_sc_out)
            self.assertNotIn(norm_sc_fatal['verdict']['status'], ('pass', 'supported'))
            rep_sc_fatal = report_latex_pdf.generate_report(fatal_sc_out, tmp_dir / 'sc_fatal.pdf', strict=True, compact=True)
            self.assertEqual(rep_sc_fatal['status'], 'ok', rep_sc_fatal)

    def test_wave2_10_profile_fatal_gate_at_index_8_blocks_strict_en_vi_pdfs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            src_dir = tmp_dir / 'sources10'
            src_dir.mkdir()
            w = _weights((15, 20, 20, 20, 15, 10))
            profs = []
            for idx in range(10):
                pid = 'p8_fatal' if idx == 8 else ('p9_ok' if idx == 9 else f'p{idx}')
                s_rating = 4 if idx == 8 else 7
                (src_dir / f'{pid}.txt').write_text(f'Verified evidence text for {pid}.\n', encoding='utf-8')
                profs.append({
                    'id': pid,
                    'reading_basis': 'full_text',
                    'closest_work': ['PriorWork2024'],
                    'ratings': _ratings((7, 7, s_rating, 7, 7, 7)),
                    'evidence_locators': {d: [f'{pid}.txt#L1 "Verified evidence text"'] for d in score_math.DIMENSIONS},
                })
            out = compare_scorecards.compare({'weight_scenarios': [w], 'profiles': profs}, sources_dir=src_dir)
            self.assertEqual(out['status'], 'structurally_comparable')
            self.assertEqual(out['submission_readiness']['p8_fatal']['band'], 'not_ready_fatal_gate')

            for lang in ('en', 'vi'):
                norm = report_latex_pdf.normalize_report_input(out, lang=lang, truncate=True)
                self.assertEqual(norm['verdict']['status'], 'blocked', lang)
                self.assertTrue(any('p8_fatal' in ev.get('claim', '') for ev in norm['key_evidence']), lang)
                self.assertTrue(any('p8_fatal' in fl.get('summary', '') for fl in norm['flaws_and_risks']), lang)

                pdf_path = tmp_dir / f'ten_profiles_{lang}.pdf'
                rep = report_latex_pdf.generate_report(out, pdf_path, lang=lang, strict=True, compact=True)
                self.assertEqual(rep['status'], 'ok', rep)
                self.assertEqual(rep['lint_summary']['error_count'], 0, rep)
                if lang == 'vi':
                    self.assertTrue(rep.get('diacritics_verified'), rep)

                try:
                    import fitz
                    doc = fitz.open(str(pdf_path))
                    pdf_text = '\n'.join(page.get_text() for page in doc)
                    doc.close()
                    compact_upper = ''.join(pdf_text.upper().split())
                    self.assertNotIn('SUPPORTED', compact_upper)
                    if lang == 'en':
                        self.assertIn('BLOCKED', compact_upper)
                    else:
                        self.assertIn('BỊCHẶN', compact_upper)
                except ImportError:
                    pass

    def test_wave3_3600b_out_path_compact_and_25_profile_strict_pdf_en_vi(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            src_dir = tmp_dir / 'sources25'
            src_dir.mkdir()
            w = _weights((15, 20, 20, 20, 15, 10))
            profs = []
            for idx in range(25):
                pid = 'p24_fatal' if idx == 24 else f'p{idx:02d}'
                if idx == 24:
                    r_vals = (9, 8, 4, 8, 8, 8)
                elif idx < 8:
                    r_vals = (7, 6, 7, 6, 6, 6)
                else:
                    r_vals = (8, 7, 7, 7, 7, 7)
                (src_dir / f'{pid}.txt').write_text(f'Verified evidence text for {pid}.\n', encoding='utf-8')
                profs.append({
                    'id': pid,
                    'reading_basis': 'full_text',
                    'closest_work': ['PriorWork2024'],
                    'ratings': _ratings(r_vals),
                    'evidence_locators': {d: [f'{pid}.txt#L1 "Verified evidence text"'] for d in score_math.DIMENSIONS},
                })
            for i in range(60):
                (src_dir / f'ignored_junk_{i:02d}.json').write_text('{}', encoding='utf-8')

            sc_path = tmp_dir / 'sc25.json'
            sc_path.write_text(json.dumps({'weight_scenarios': [w], 'profiles': profs}), encoding='utf-8')

            long_dir = tmp_dir
            for _ in range(18):
                long_dir = long_dir / ('d' * 190)
            long_dir.mkdir(parents=True)
            long_out = long_dir / 'sc25_out.json'
            self.assertGreater(len(str(long_out).encode('utf-8')), 3400)

            cli = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / 'compare_scorecards.py'),
                    str(sc_path),
                    '--sources-dir', str(src_dir),
                    '--out', str(long_out),
                    '--compact',
                ],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
            self.assertLess(len(cli.stdout.encode('utf-8')), 4096)
            compact_sc = json.loads(cli.stdout)
            self.assertEqual(compact_sc['locator_verification']['skipped_files_count'], 60)

            # Truncated --compact scorecard summary mentions omitted profiles and passes strict PDF
            norm_trunc = report_latex_pdf.normalize_report_input(compact_sc, lang='en', truncate=True)
            self.assertEqual(norm_trunc['verdict']['status'], 'caution')
            self.assertIn('omitted in compact input', norm_trunc['verdict']['summary'])
            self.assertTrue(report_latex_pdf.lint_report(compact_sc, lang='en')['passed'])

            # Full 25-profile JSON (with p24_fatal at index 24 and 8 borderline prefix) passes strict EN & VI PDFs
            for lang in ('en', 'vi'):
                pdf_path = tmp_dir / f'full25_{lang}.pdf'
                rep_cli = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPTS_DIR / 'report_latex_pdf.py'),
                        '--input', str(long_out),
                        '--out', str(pdf_path),
                        '--lang', lang,
                        '--strict',
                        '--json',
                        '--compact',
                    ],
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(rep_cli.returncode, 0, rep_cli.stdout + rep_cli.stderr)
                rec = json.loads(rep_cli.stdout)
                self.assertEqual(rec['status'], 'ok', rec)
                self.assertTrue(rec['diacritics_verified'], rec)
                try:
                    import fitz
                    with fitz.open(str(pdf_path)) as doc:
                        txt = '\n'.join(page.get_text() for page in doc)
                    self.assertIn('p24_fatal', txt, lang)
                    compact_upper = ''.join(txt.upper().split())
                    self.assertNotIn('SUPPORTED', compact_upper)
                    self.assertIn('BLOCKED' if lang == 'en' else 'BỊCHẶN', compact_upper)
                except ImportError:
                    pass


class TestCompareVenueNoveltySubmissionReadiness(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((ROOT / 'research-scientist' / 'references' / 'venue-novelty-profile.fixture.json').read_text(encoding='utf-8'))
        self.as_of = datetime(2026, 11, 21, 12, tzinfo=timezone.utc)

    def test_panel_standing_bands_and_interval_dominance(self):
        # Overlapping panel median (fixture: target [5,7], median 6)
        overlap_out = compare_venue_novelty.check(copy.deepcopy(self.fixture), self.as_of)
        sr_ov = overlap_out['submission_readiness']
        self.assertEqual(sr_ov['standing_vs_accepted_panel'], 'at_or_overlapping_panel_median')
        self.assertEqual(sr_ov['accepted_panel_median_score'], 6)
        self.assertEqual(sr_ov['verdict'], 'conditional_competitive_borderline_panel_overlap')
        self.assertTrue(sr_ov['ready_to_submit'])

        # Above panel median (target low > median)
        above = copy.deepcopy(self.fixture)
        above['target']['score'] = 9
        above['target']['low'] = 8
        above['target']['high'] = 10
        above['fit_axes'][2]['score'] = 2
        above_out = compare_venue_novelty.check(above, self.as_of)
        sr_ab = above_out['submission_readiness']
        self.assertEqual(sr_ab['standing_vs_accepted_panel'], 'above_panel_median')
        self.assertEqual(sr_ab['delta_vs_panel_median'], 3.0)
        self.assertTrue(sr_ab['interval_dominance']['target_interval_above_panel_median'])
        self.assertGreater(sr_ab['interval_dominance']['strictly_higher_than_count'], 0)
        self.assertEqual(sr_ab['verdict'], 'ready_strong_panel_standing_and_fit')
        self.assertTrue(sr_ab['ready_to_submit'])

        # Below panel median (target high < median)
        below = copy.deepcopy(self.fixture)
        below['target']['score'] = 3
        below['target']['low'] = 2
        below['target']['high'] = 4
        below_out = compare_venue_novelty.check(below, self.as_of)
        sr_bl = below_out['submission_readiness']
        self.assertEqual(sr_bl['standing_vs_accepted_panel'], 'below_panel_median')
        self.assertEqual(sr_bl['delta_vs_panel_median'], -3.0)
        self.assertTrue(sr_bl['interval_dominance']['target_interval_below_panel_median'])
        self.assertEqual(sr_bl['verdict'], 'below_panel_median_strengthen_or_retarget')
        self.assertFalse(sr_bl['ready_to_submit'])

    def test_fit_score_constraints_small_panel_and_empty_input(self):
        # Weak venue fit (<=5)
        weak_fit = copy.deepcopy(self.fixture)
        weak_fit['target']['score'] = 9
        weak_fit['target']['low'] = 8
        weak_fit['target']['high'] = 10
        weak_fit['fit_axes'][0]['score'] = 0
        weak_fit['fit_axes'][1]['score'] = 1
        weak_fit['fit_axes'][3]['score'] = 1
        wf_out = compare_venue_novelty.check(weak_fit, self.as_of)
        self.assertEqual(wf_out['fit_score_out_of_10'], 4)
        self.assertEqual(wf_out['submission_readiness']['verdict'], 'not_ready_weak_venue_fit')
        self.assertFalse(wf_out['submission_readiness']['ready_to_submit'])

        # Failed deadline & failed eligibility
        for idx, cname in [(0, 'deadline'), (2, 'eligibility')]:
            prof = copy.deepcopy(self.fixture)
            prof['hard_constraints'][idx]['status'] = 'failed'
            out = compare_venue_novelty.check(prof, self.as_of)
            self.assertIsNone(out['fit_score_out_of_10'])
            sr = out['submission_readiness']
            self.assertEqual(sr['verdict'], 'do_not_submit_constraint_failed')
            self.assertIn(cname, sr['failed_constraints'])
            self.assertFalse(sr['ready_to_submit'])

        # Unverified budget
        unv = copy.deepcopy(self.fixture)
        unv['hard_constraints'][1]['status'] = 'unverified'
        unv['hard_constraints'][1].pop('source_url')
        unv_out = compare_venue_novelty.check(unv, self.as_of)
        self.assertEqual(unv_out['submission_readiness']['verdict'], 'blocked_unverified_fit_or_constraints')
        self.assertIn('budget', unv_out['submission_readiness']['unverified_constraints'])
        self.assertFalse(unv_out['submission_readiness']['ready_to_submit'])

        # < 5 accepted panel papers
        small_panel = copy.deepcopy(self.fixture)
        small_panel['accepted_panel'] = small_panel['accepted_panel'][:4]
        sp_out = compare_venue_novelty.check(small_panel, self.as_of)
        self.assertIsNone(sp_out['novelty_comparison'])
        self.assertEqual(sp_out['submission_readiness']['standing_vs_accepted_panel'], 'unavailable')
        self.assertEqual(sp_out['submission_readiness']['verdict'], 'provisional_panel_withheld')
        self.assertFalse(sp_out['submission_readiness']['ready_to_submit'])

        # Empty {} input does not crash
        empty_out = compare_venue_novelty.check({}, self.as_of)
        self.assertEqual(empty_out['status'], 'invalid')
        self.assertEqual(empty_out['submission_readiness']['verdict'], 'not_ready_invalid_evidence')
        self.assertEqual(empty_out['submission_readiness']['standing_vs_accepted_panel'], 'unavailable')
        self.assertFalse(empty_out['submission_readiness']['ready_to_submit'])

    def test_compact_output_and_novelty_comparison_invariance(self):
        unknown_prof = copy.deepcopy(self.fixture)
        unknown_prof['venue']['checked_at_utc'] = datetime.now(timezone.utc).isoformat()
        neurips_prof = copy.deepcopy(unknown_prof)
        neurips_prof['venue']['name'] = 'NeurIPS'

        unknown_out = compare_venue_novelty.check(unknown_prof)
        neurips_out = compare_venue_novelty.check(neurips_prof)
        self.assertEqual(unknown_out['venue_quality_context']['quality_tier'], 'Unknown')
        self.assertEqual(neurips_out['venue_quality_context']['quality_tier'], 'S')
        self.assertEqual(unknown_out['fit_score_out_of_10'], neurips_out['fit_score_out_of_10'])
        self.assertEqual(unknown_out['novelty_comparison'], neurips_out['novelty_comparison'])
        self.assertEqual(unknown_out['submission_readiness'], neurips_out['submission_readiness'])

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            p_path = tmp_dir / 'profile.json'
            out_path = tmp_dir / 'venue_out.json'
            p_path.write_text(json.dumps(neurips_prof), encoding='utf-8')
            cli = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / 'compare_venue_novelty.py'),
                    str(p_path),
                    '--out',
                    str(out_path),
                    '--compact',
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(cli.returncode, 0, cli.stderr)
            self.assertLess(len(cli.stdout.encode('utf-8')), 4096)
            compact = json.loads(cli.stdout)
            self.assertEqual(
                compact['submission_readiness']['standing_vs_accepted_panel'],
                'at_or_overlapping_panel_median',
            )
            self.assertTrue(compact['submission_readiness']['hard_constraints_met'])

    def test_wave1_low_novelty_overlap_guidance_and_report_pdf_fatal_gate(self):
        # Target score=4 overlapping panel median=4 (or > panel median=3) must not say "sits below ... median"
        prof = copy.deepcopy(self.fixture)
        prof['target']['score'] = 4
        prof['target']['low'] = 3
        prof['target']['high'] = 5
        for item in prof['accepted_panel']:
            item['score'] = 4
            item['low'] = 3
            item['high'] = 5
        out = compare_venue_novelty.check(prof, self.as_of)
        sr = out['submission_readiness']
        self.assertEqual(sr['standing_vs_accepted_panel'], 'at_or_overlapping_panel_median')
        self.assertEqual(sr['delta_vs_panel_median'], 0.0)
        self.assertNotIn('sits below same-track accepted panel median', sr['guidance'])

        # report_latex_pdf must never classify fatal compare_venue_novelty output as pass/supported
        vn_fatal_prof = copy.deepcopy(self.fixture)
        vn_fatal_prof['venue']['checked_at_utc'] = datetime.now(timezone.utc).isoformat()
        vn_fatal_prof['target']['score'] = 2
        vn_fatal_prof['target']['low'] = 1
        vn_fatal_prof['target']['high'] = 3
        vn_fatal = compare_venue_novelty.check(vn_fatal_prof)
        self.assertEqual(vn_fatal['submission_readiness']['verdict'], 'not_ready_fatal_gate')
        norm = report_latex_pdf.normalize_report_input(vn_fatal)
        self.assertNotIn(norm['verdict']['status'], ('pass', 'supported'))
        with tempfile.TemporaryDirectory() as tmp:
            rep = report_latex_pdf.generate_report(vn_fatal, Path(tmp) / 'vn_fatal.pdf', strict=True, compact=True)
            self.assertEqual(rep['status'], 'ok', rep)


class TestF23PromptReferenceAndLatexContracts(unittest.TestCase):
    def test_all_seven_skill_md_footprints_and_sycophancy_guard(self):
        skills = [
            'research-scientist',
            'research-precedent-corpus',
            'research-gap-rq-audit',
            'research-experiment-coding',
            'research-novelty-venue',
            'research-paper-writing',
            'research-user-report',
        ]
        for s in skills:
            raw = (ROOT / s / 'SKILL.md').read_text(encoding='utf-8')
            fp = claim_audit._measure_skill_footprint(raw)
            self.assertLess(fp['lines'], 50, f'{s}: {fp}')
            self.assertLess(fp['est_tokens'], 900, f'{s}: {fp}')
            self.assertLess(fp['frontmatter_est_tokens'], 140, f'{s}: {fp}')

        novelty_skill = (ROOT / 'research-novelty-venue' / 'SKILL.md').read_text(encoding='utf-8')
        self.assertIn('Submission Readiness', novelty_skill)
        self.assertIn('never', novelty_skill.lower())

        parent_skill = (ROOT / 'research-scientist' / 'SKILL.md').read_text(encoding='utf-8')
        self.assertIn('submission_readiness', parent_skill)

        report_skill = (ROOT / 'research-user-report' / 'SKILL.md').read_text(encoding='utf-8')
        self.assertIn('Submission Readiness / Khả năng nộp bài', report_skill)

    def test_reference_calibration_and_strict_en_vi_examples(self):
        parent_ref = (ROOT / 'research-scientist' / 'references' / 'scoring-and-venue-fit.md').read_text(encoding='utf-8')
        novelty_ref = (ROOT / 'research-novelty-venue' / 'references' / 'novelty-venue-rebuttal-protocol.md').read_text(encoding='utf-8')
        report_ref = (ROOT / 'research-user-report' / 'references' / 'user-report-pdf-guide.md').read_text(encoding='utf-8')

        for tok in (
            'Mandatory Submission Readiness & Venue Standing Calibration',
            'not_ready_fatal_gate',
            'not_ready_major_rework',
            'workshop_or_preliminary_only',
            'borderline_top_tier_competitive_findings_tier_a',
            'competitive_top_tier_main_track',
            'strong_top_tier_contender',
            'soundness <= 4',
            'evidence <= 4',
            'novelty <= 2',
            'transparency <= 3',
            '6.80',
        ):
            self.assertIn(tok, parent_ref)
            self.assertIn(tok, novelty_ref)

        self.assertIn('Khả năng nộp bài', report_ref)
        self.assertNotIn('(../research-scientist/', novelty_ref)
        self.assertNotIn('(../research-scientist/', report_ref)

        # Verify EN/VI examples in user-report-pdf-guide.md pass report_latex_pdf.lint_report strict=True
        for lang, title, summary in [
            (
                'en',
                'Scorecard Submission Readiness Assessment',
                'Weighted score 6.35/10 passes fatal gates but sits below top-tier main-track accepted median (~6.8-7.6) [scorecards.json]. Competitive now for Findings or Tier-A venues; strengthen soundness before NeurIPS.',
            ),
            (
                'vi',
                'Đánh giá khả năng nộp bài theo bảng điểm',
                'Điểm 6.35/10 vượt mức trung bình toàn bộ bài nộp (~4.8-5.5) nhưng thấp hơn mức bài được nhận top-tier (~6.8-7.6) [scorecards.json]. Phù hợp nộp Findings hoặc hội nghị Tier-A hiện tại.',
            ),
            (
                'vi',
                'Cảnh báo lỗi chí mạng khi chấm điểm bài báo',
                'Chưa đủ điều kiện nộp dù điểm trung bình đạt 6.6/10 do vướng lỗi chí mạng ở độ chặt phương pháp (4/10) [scorecards.json]. Cần sửa thiết kế thí nghiệm trước khi nộp.',
            ),
        ]:
            doc = {
                'schema': 'research_scientist_executive_report_v1',
                'report_type': 'novelty_scoring',
                'lang': lang,
                'title': title,
                'verdict': {'status': 'provisional', 'summary': summary, 'evidence_refs': ['SC1']},
                'key_evidence': [
                    {
                        'id': 'SC1',
                        'claim': 'Weighted scorecard summary',
                        'value': '6.35/10',
                        'status': 'verified',
                        'locator': 'scorecards.json',
                    }
                ],
                'flaws_and_risks': [
                    {
                        'id': 'R1',
                        'severity': 'medium',
                        'summary': 'Soundness needs stronger ablation evidence [scorecards.json].',
                        'locator': 'scorecards.json',
                    }
                ],
                'next_steps': [
                    {
                        'step': 1,
                        'action': 'Run 5-seed baseline ablation before submission.',
                        'target': 'scorecards.json',
                    }
                ],
            }
            lint = report_latex_pdf.lint_report(doc, lang=lang)
            self.assertTrue(lint['passed'], f'{lang} failed lint: {lint}')
            self.assertEqual(lint['error_count'], 0, lint)
            self.assertEqual(lint['warn_count'], 0, lint)

    def test_claim_audit_clean_across_suite(self):
        cli = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS_DIR / 'claim_audit.py'),
                '--suite-root',
                str(ROOT),
                '--readme',
                str(ROOT / 'README.md'),
                '--json',
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
        data = json.loads(cli.stdout)
        self.assertEqual(data['finding_count'], 0, data)


if __name__ == '__main__':
    unittest.main()
