"""Tests for compare_venue_novelty.py --sources-dir / venue_quality_context and venue_leads.py quality lookup."""
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / 'research-scientist/scripts'

novelty_spec = importlib.util.spec_from_file_location('compare_venue_novelty', SCRIPTS_DIR / 'compare_venue_novelty.py')
novelty_mod = importlib.util.module_from_spec(novelty_spec)
novelty_spec.loader.exec_module(novelty_mod)

leads_spec = importlib.util.spec_from_file_location('venue_leads', SCRIPTS_DIR / 'venue_leads.py')
leads_mod = importlib.util.module_from_spec(leads_spec)
leads_spec.loader.exec_module(leads_mod)

FIXTURE = ROOT / 'research-scientist/references/venue-novelty-profile.fixture.json'

try:
    import fitz
except ImportError:  # pragma: no cover
    fitz = None


def _build_local_fixture(tmp_path: Path, *, stale_redirect=False, js_rendered=False, unverified_dynamic=False):
    profile = json.loads(FIXTURE.read_text(encoding='utf-8'))
    src_dir = tmp_path / 'sources'
    src_dir.mkdir(parents=True, exist_ok=True)

    (src_dir / 'FICTIONAL-PRIOR-A.txt').write_text(
        'Section 3 Discriminating Test\n'
        'Prior work omits the graph shift intervention under boundary B.\n',
        encoding='utf-8',
    )
    profile['target']['closest_work_locator'] = (
        'FICTIONAL-PRIOR-A.txt:1-2: "Prior work omits the graph shift intervention"'
    )

    for idx, item in enumerate(profile['accepted_panel']):
        pid = item['closest_work_id']
        (src_dir / f'{pid}.txt').write_text(
            f'Section 2 Method\n'
            f'Panel reference {idx + 1} reports bounded delta.\n',
            encoding='utf-8',
        )
        item['closest_work_locator'] = f'{pid}.txt:2: "Panel reference {idx + 1} reports bounded delta."'

    bundle = {
        'format': 'research_scientist_venue_sources_v1',
        'sources': [
            {
                'requested_url': 'https://example.org/fictional-cfp',
                'final_url': 'https://example.org/fictional-cfp-2025' if stale_redirect else 'https://example.org/fictional-cfp',
                'extraction_status': 'ok',
                'same_host_path_redirect_year_mismatch': stale_redirect,
                'js_rendered_suspected': False,
                'text': 'Main scope covers graph learning. Contribution tracks include empirical mechanism studies.',
            },
            {
                'requested_url': 'https://example.org/fictional-p3',
                'final_url': 'https://example.org/fictional-p3',
                'extraction_status': 'ok',
                'text': 'Methods section specifies multi-seed ablations and comparator controls.',
            },
            {
                'requested_url': 'https://example.org/fictional-policy',
                'final_url': 'https://example.org/fictional-policy',
                'extraction_status': 'ok',
                'text': 'Submission rules require 8 pages plus references and double-blind PDF.',
            },
            {
                'requested_url': 'https://example.org/fictional-fees',
                'final_url': 'https://example.org/fictional-fees',
                'extraction_status': 'unverified_dynamic_page' if unverified_dynamic else 'ok',
                'js_rendered_suspected': js_rendered,
                'unverified_dynamic_page': unverified_dynamic,
                'text': '' if (js_rendered or unverified_dynamic) else 'Fee schedule: USD 750 early author registration.',
            },
        ],
    }
    (src_dir / 'venue-sources.json').write_text(json.dumps(bundle), encoding='utf-8')
    profile['fit_axes'][0]['locator'] = '"Main scope covers graph learning"'
    profile['fit_axes'][1]['locator'] = '"empirical mechanism studies"'
    profile['fit_axes'][2]['locator'] = '"multi-seed ablations"'
    profile['fit_axes'][3]['locator'] = '"8 pages plus references"'
    profile['fit_axes'][4]['locator'] = '"USD 750 early author registration"'
    return profile, src_dir


class CompareVenueNoveltySourcesTests(unittest.TestCase):
    def setUp(self):
        self.as_of = datetime(2026, 11, 21, 12, tzinfo=timezone.utc)

    def test_sources_dir_valid_panel_and_venue_bundle_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile, src_dir = _build_local_fixture(Path(tmp))
            out = novelty_mod.check(profile, as_of=self.as_of, sources_dir=src_dir)
            self.assertEqual(out['status'], 'structurally_checked')
            self.assertEqual(out['errors'], [])
            self.assertEqual(out['fit_score_out_of_10'], 8)
            self.assertIsNotNone(out['novelty_comparison'])
            self.assertEqual(out['locator_verification']['checked'], 11)
            self.assertEqual(out['locator_verification']['verified'], 11)
            self.assertEqual(out['locator_verification']['failed'], 0)

    @unittest.skipIf(fitz is None, 'PyMuPDF (fitz) not installed')
    def test_sources_dir_corrupt_pdf_skipped_while_valid_sources_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile, src_dir = _build_local_fixture(Path(tmp))
            (src_dir / 'corrupt.pdf').write_bytes(b'%PDF-1.4\nnot really a pdf at all\x00\xff')
            out = novelty_mod.check(profile, as_of=self.as_of, sources_dir=src_dir)
            self.assertEqual(out['status'], 'structurally_checked')
            self.assertEqual(out['errors'], [])
            self.assertEqual(out['fit_score_out_of_10'], 8)
            skipped_paths = [item['path'] for item in out['locator_verification']['skipped_files']]
            self.assertIn('corrupt.pdf', skipped_paths)

    @unittest.skipIf(fitz is None, 'PyMuPDF (fitz) not installed')
    def test_sources_dir_with_real_pdf_closest_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            profile, src_dir = _build_local_fixture(tmp_path)
            pdf_path = src_dir / 'FICTIONAL-PRIOR-A.pdf'
            doc = fitz.open()
            doc.new_page().insert_text((72, 72), 'Section 1 Overview only.')
            doc.new_page().insert_text((72, 72), 'Section 3 proves graph shift failure case.')
            doc.save(str(pdf_path))
            doc.close()

            profile['target']['closest_work_locator'] = (
                'FICTIONAL-PRIOR-A.pdf#page=2: "proves graph shift failure case"'
            )
            out = novelty_mod.check(profile, as_of=self.as_of, sources_dir=src_dir)
            self.assertEqual(out['status'], 'structurally_checked')

            profile['target']['closest_work_locator'] = (
                'FICTIONAL-PRIOR-A.pdf#page=1: "proves graph shift failure case"'
            )
            bad = novelty_mod.check(profile, as_of=self.as_of, sources_dir=src_dir)
            self.assertEqual(bad['status'], 'invalid')
            self.assertIn('target:closest_work_locator_unverified:quote_not_found', bad['errors'])
            self.assertIsNone(bad['novelty_comparison'])

    def test_sources_dir_fabricated_target_closest_work_locator_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile, src_dir = _build_local_fixture(Path(tmp))
            profile['target']['closest_work_locator'] = 'FICTIONAL-PRIOR-A.txt:1: "Nonexistent claim"'
            out = novelty_mod.check(profile, as_of=self.as_of, sources_dir=src_dir)
            self.assertEqual(out['status'], 'invalid')
            self.assertIn('target:closest_work_locator_unverified:quote_not_found', out['errors'])
            self.assertIsNone(out['novelty_comparison'])

    def test_sources_dir_fabricated_panel_closest_work_locator_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile, src_dir = _build_local_fixture(Path(tmp))
            profile['accepted_panel'][2]['closest_work_locator'] = 'missing_paper.pdf p.3: "anything"'
            out = novelty_mod.check(profile, as_of=self.as_of, sources_dir=src_dir)
            self.assertEqual(out['status'], 'invalid')
            self.assertIn('accepted_panel:2:closest_work_locator_unverified:source_not_found', out['errors'])
            self.assertIsNone(out['novelty_comparison'])

    def test_sources_dir_fabricated_fit_axis_locator_withholds_fit_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile, src_dir = _build_local_fixture(Path(tmp))
            profile['fit_axes'][0]['locator'] = '"Fabricated CFP scope sentence"'
            out = novelty_mod.check(profile, as_of=self.as_of, sources_dir=src_dir)
            self.assertEqual(out['status'], 'invalid')
            self.assertIn('fit_axes:0:locator_unverified:quote_not_found', out['errors'])
            self.assertIsNone(out['fit_score_out_of_10'])

    def test_sources_dir_rejects_stale_redirect_or_js_venue_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile_stale, src_stale = _build_local_fixture(Path(tmp) / 'stale', stale_redirect=True)
            out_stale = novelty_mod.check(profile_stale, as_of=self.as_of, sources_dir=src_stale)
            self.assertEqual(out_stale['status'], 'invalid')
            self.assertIn('fit_axes:0:locator_unverified:unverified_or_stale_venue_snapshot', out_stale['errors'])
            self.assertIsNone(out_stale['fit_score_out_of_10'])

            profile_js, src_js = _build_local_fixture(Path(tmp) / 'js', js_rendered=True)
            out_js = novelty_mod.check(profile_js, as_of=self.as_of, sources_dir=src_js)
            self.assertEqual(out_js['status'], 'invalid')
            self.assertIn('fit_axes:4:locator_unverified:unverified_or_stale_venue_snapshot', out_js['errors'])
            self.assertIsNone(out_js['fit_score_out_of_10'])

            profile_dyn, src_dyn = _build_local_fixture(Path(tmp) / 'dyn', unverified_dynamic=True)
            out_dyn = novelty_mod.check(profile_dyn, as_of=self.as_of, sources_dir=src_dyn)
            self.assertEqual(out_dyn['status'], 'invalid')
            self.assertIn('fit_axes:4:locator_unverified:unverified_or_stale_venue_snapshot', out_dyn['errors'])

    def test_sources_dir_blocks_uncaptured_fit_axis_url_when_bundle_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile, src_dir = _build_local_fixture(Path(tmp))
            profile['fit_axes'][0]['source_url'] = 'https://example.org/uncaptured-cfp'
            out = novelty_mod.check(profile, as_of=self.as_of, sources_dir=src_dir)
            self.assertEqual(out['status'], 'invalid')
            self.assertIn('fit_axes:0:locator_unverified:source_snapshot_missing', out['errors'])
            self.assertIsNone(out['fit_score_out_of_10'])

    def test_omitted_sources_dir_preserves_fixture_behavior(self):
        profile = json.loads(FIXTURE.read_text(encoding='utf-8'))
        out = novelty_mod.check(profile, as_of=self.as_of)
        self.assertEqual(out['status'], 'structurally_checked')
        self.assertNotIn('locator_verification', out)
        self.assertEqual(out['fit_score_out_of_10'], 8)

    def test_cli_sources_dir_exit_codes_and_help(self):
        script = str(SCRIPTS_DIR / 'compare_venue_novelty.py')
        help_res = subprocess.run([sys.executable, script, '--help'], capture_output=True, text=True)
        self.assertEqual(help_res.returncode, 0)
        self.assertIn('--sources-dir', help_res.stdout)
        self.assertIn('--quality-refs-dir', help_res.stdout)

        # Fixture without --sources-dir keeps exit 0
        omit_res = subprocess.run([sys.executable, script, str(FIXTURE)], capture_output=True, text=True)
        self.assertEqual(omit_res.returncode, 0)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            profile, src_dir = _build_local_fixture(tmp_path)
            profile['venue']['checked_at_utc'] = datetime.now(timezone.utc).isoformat()
            for item in [profile['target']] + profile['accepted_panel']:
                item['assessed_at_utc'] = datetime.now(timezone.utc).isoformat()
            good_file = tmp_path / 'good.json'
            good_file.write_text(json.dumps(profile), encoding='utf-8')

            ok_res = subprocess.run(
                [sys.executable, script, str(good_file), '--sources-dir', str(src_dir)],
                capture_output=True, text=True,
            )
            self.assertEqual(ok_res.returncode, 0)
            self.assertEqual(json.loads(ok_res.stdout)['status'], 'structurally_checked')

            bad_profile = copy.deepcopy(profile)
            bad_profile['target']['closest_work_locator'] = 'FICTIONAL-PRIOR-A.txt:1: "Fabricated"'
            bad_file = tmp_path / 'bad.json'
            bad_file.write_text(json.dumps(bad_profile), encoding='utf-8')
            fail_res = subprocess.run(
                [sys.executable, script, str(bad_file), '--sources-dir', str(src_dir)],
                capture_output=True, text=True,
            )
            self.assertEqual(fail_res.returncode, 1)
            self.assertEqual(json.loads(fail_res.stdout)['status'], 'invalid')

            missing_dir = subprocess.run(
                [sys.executable, script, str(good_file), '--sources-dir', str(tmp_path / 'nope')],
                capture_output=True, text=True,
            )
            self.assertEqual(missing_dir.returncode, 2)

            bad_refs = subprocess.run(
                [sys.executable, script, str(good_file), '--quality-refs-dir', str(tmp_path / 'no_refs')],
                capture_output=True, text=True,
            )
            self.assertEqual(bad_refs.returncode, 2)

    def test_venue_quality_context_advisory_only_never_changes_scores(self):
        base = json.loads(FIXTURE.read_text(encoding='utf-8'))
        unknown_out = novelty_mod.check(base, as_of=self.as_of)

        neurips_profile = copy.deepcopy(base)
        neurips_profile['venue']['name'] = 'NeurIPS'
        neurips_out = novelty_mod.check(neurips_profile, as_of=self.as_of)

        self.assertEqual(unknown_out['venue_quality_context']['quality_tier'], 'Unknown')
        self.assertEqual(neurips_out['venue_quality_context']['quality_tier'], 'S')
        self.assertTrue(neurips_out['venue_quality_context']['advisory_only'])
        self.assertEqual(unknown_out['fit_score_out_of_10'], neurips_out['fit_score_out_of_10'])
        self.assertEqual(unknown_out['novelty_comparison'], neurips_out['novelty_comparison'])

    def test_sources_dir_blocks_missing_bundle_local_cheat_anubis_hard_constraints_and_masked_residual(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # 1. Missing venue-sources.json must fail fit_axes & hard_constraints with source_snapshot_missing
            prof_no_bundle, src_no_bundle = _build_local_fixture(tmp_path / 'no_bundle')
            (src_no_bundle / 'venue-sources.json').unlink()
            (src_no_bundle / 'random_paper.txt').write_text(
                'Main scope covers graph learning. empirical mechanism studies. multi-seed ablations. '
                '8 pages plus references. USD 750 early author registration.\n',
                encoding='utf-8',
            )
            prof_no_bundle['fit_axes'][0]['locator'] = 'random_paper.txt: "Main scope covers graph learning"'
            out_no_bundle = novelty_mod.check(prof_no_bundle, as_of=self.as_of, sources_dir=src_no_bundle)
            self.assertEqual(out_no_bundle['status'], 'invalid')
            self.assertIn('fit_axes:0:locator_unverified:source_snapshot_missing', out_no_bundle['errors'])
            self.assertIn('hard_constraints:0:source_snapshot_missing', out_no_bundle['errors'])
            self.assertIsNone(out_no_bundle['fit_score_out_of_10'])

            # 2. Explicit local_cheat.txt / venue-sources.json cannot bypass uncaptured fit_axes source_url
            prof_cheat, src_cheat = _build_local_fixture(tmp_path / 'cheat')
            (src_cheat / 'local_cheat.txt').write_text('Fake CFP scope from local file.\n', encoding='utf-8')
            prof_cheat['fit_axes'][0]['source_url'] = 'https://evil-uncaptured.org/cfp'
            prof_cheat['fit_axes'][0]['locator'] = 'local_cheat.txt: "Fake CFP scope from local file."'
            out_cheat = novelty_mod.check(prof_cheat, as_of=self.as_of, sources_dir=src_cheat)
            self.assertEqual(out_cheat['status'], 'invalid')
            self.assertIn('fit_axes:0:locator_unverified:source_snapshot_missing', out_cheat['errors'])

            # 3. bot_blocked_anubis snapshot with text must be blocked (even if cited via venue-sources.json)
            prof_anubis, src_anubis = _build_local_fixture(tmp_path / 'anubis')
            bundle_path = src_anubis / 'venue-sources.json'
            bundle = json.loads(bundle_path.read_text(encoding='utf-8'))
            bundle['sources'][0]['extraction_status'] = 'bot_blocked_anubis'
            bundle['sources'][0]['text'] = 'Anubis challenge leaked text Main scope covers graph learning.'
            bundle_path.write_text(json.dumps(bundle), encoding='utf-8')
            prof_anubis['fit_axes'][0]['locator'] = 'venue-sources.json: "Main scope covers graph learning"'
            out_anubis = novelty_mod.check(prof_anubis, as_of=self.as_of, sources_dir=src_anubis)
            self.assertEqual(out_anubis['status'], 'invalid')
            self.assertIn('fit_axes:0:locator_unverified:unverified_or_stale_venue_snapshot', out_anubis['errors'])
            self.assertIn('hard_constraints:0:unverified_or_stale_venue_snapshot', out_anubis['errors'])

            # 4. hard_constraints[*].source_url must also match a verified snapshot when status is met/failed
            prof_hc, src_hc = _build_local_fixture(tmp_path / 'hc')
            prof_hc['hard_constraints'][1]['source_url'] = 'https://evil-uncaptured.org/fees'
            out_hc = novelty_mod.check(prof_hc, as_of=self.as_of, sources_dir=src_hc)
            self.assertEqual(out_hc['status'], 'invalid')
            self.assertIn('hard_constraints:1:source_snapshot_missing', out_hc['errors'])

            # 5. closest_work_quote cannot mask fabricated unquoted text in closest_work_locator
            # (even when the line anchor matches closest_work_quote on line 2!)
            prof_mask, src_mask = _build_local_fixture(tmp_path / 'mask')
            prof_mask['accepted_panel'][0]['closest_work_locator'] = 'FICTIONAL-A1.txt:2: FABRICATED UNQUOTED CLAIM'
            prof_mask['accepted_panel'][0]['closest_work_quote'] = 'Panel reference 1 reports bounded delta.'
            out_mask = novelty_mod.check(prof_mask, as_of=self.as_of, sources_dir=src_mask)
            self.assertEqual(out_mask['status'], 'invalid')
            self.assertIn('accepted_panel:0:closest_work_locator_unverified:text_not_found', out_mask['errors'])

    def test_cli_compare_venue_novelty_out_and_compact(self):
        script = str(SCRIPTS_DIR / 'compare_venue_novelty.py')
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            profile = json.loads(FIXTURE.read_text(encoding='utf-8'))
            profile['venue']['checked_at_utc'] = datetime.now(timezone.utc).isoformat()
            for item in [profile['target']] + profile['accepted_panel']:
                item['assessed_at_utc'] = datetime.now(timezone.utc).isoformat()
            prof_file = tmp_path / 'profile.json'
            prof_file.write_text(json.dumps(profile), encoding='utf-8')
            out_file = tmp_path / 'novelty_out.json'

            res = subprocess.run(
                [sys.executable, script, str(prof_file), '--out', str(out_file), '--compact'],
                capture_output=True, text=True,
            )
            self.assertEqual(res.returncode, 0, msg=res.stderr)
            compact = json.loads(res.stdout)
            self.assertTrue(compact['compact'])
            self.assertEqual(compact['status'], 'structurally_checked')
            self.assertEqual(compact['fit_score_out_of_10'], 8)
            self.assertEqual(compact['novelty_comparison']['accepted_panel_median_score'], 6)
            self.assertEqual(compact['artifact_path'], str(out_file))
            full = json.loads(out_file.read_text(encoding='utf-8'))
            self.assertEqual(full['status'], 'structurally_checked')
            self.assertIn('disclaimer', full)

    @unittest.skipIf(fitz is None, 'PyMuPDF (fitz) not installed')
    def test_sources_dir_rejects_html_and_svg_disguised_as_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            profile, src_dir = _build_local_fixture(tmp_path / 'mixed')
            (src_dir / 'anubis_challenge.pdf').write_bytes(
                b'<html><body>Anubis Proof of Work Challenge</body></html>'
            )
            (src_dir / 'fake_svg.pdf').write_bytes(
                b'<svg xmlns="http://www.w3.org/2000/svg"><text x="10" y="20">Fake SVG</text></svg>'
            )

            out = novelty_mod.check(profile, as_of=self.as_of, sources_dir=src_dir)
            self.assertEqual(out['status'], 'structurally_checked')
            skipped_paths = {item['path'] for item in out['locator_verification']['skipped_files']}
            self.assertIn('anubis_challenge.pdf', skipped_paths)
            self.assertIn('fake_svg.pdf', skipped_paths)

            only_fake = tmp_path / 'only_fake'
            only_fake.mkdir()
            (only_fake / 'anubis_challenge.pdf').write_bytes(
                b'<html><body>Anubis Proof of Work Challenge</body></html>'
            )
            (only_fake / 'fake_svg.pdf').write_bytes(
                b'<svg xmlns="http://www.w3.org/2000/svg"><text x="10" y="20">Fake SVG</text></svg>'
            )
            with self.assertRaises(ValueError):
                novelty_mod.check(profile, as_of=self.as_of, sources_dir=only_fake)

            prof_file = tmp_path / 'profile.json'
            prof_file.write_text(json.dumps(profile), encoding='utf-8')
            script = str(SCRIPTS_DIR / 'compare_venue_novelty.py')
            res_cli = subprocess.run(
                [sys.executable, script, str(prof_file), '--sources-dir', str(only_fake)],
                capture_output=True, text=True,
            )
            self.assertEqual(res_cli.returncode, 2)
            self.assertIn('error', json.loads(res_cli.stderr))

    def test_https_rejects_whitespace_and_control_characters(self):
        self.assertTrue(novelty_mod._https('https://example.org/cfp?id=1&x=2#page=1'))
        bad_urls = (
            'https://example.org/cfp\x00',
            'https://example.org/cfp\x07',
            'https://example.org/cfp\n',
            'https://example.org/cfp\r',
            'https://example.org/cfp\t',
            'https://example.org/cfp\x7f',
            'https://example.org/cfp\u0085',
            'https://example.org/cfp\u00a0',
            'https://example.org/cfp\u200b',
            'https://example.org/cfp\u202e',
            'https://example.org/cfp\ufeff',
            'https://@example.org/cfp',
            'https://user@example.org/cfp',
            'https://example.org/cfp with spaces',
            ' https://example.org/cfp',
        )
        for bad_url in bad_urls:
            self.assertFalse(novelty_mod._https(bad_url), msg=repr(bad_url))
            profile = json.loads(FIXTURE.read_text(encoding='utf-8'))
            profile['venue']['official_cfp_url'] = bad_url
            out = novelty_mod.check(profile, as_of=self.as_of)
            self.assertEqual(out['status'], 'invalid', msg=repr(bad_url))
            self.assertIn('venue:official_cfp_url_must_be_https', out['errors'], msg=repr(bad_url))

    def test_sources_dir_blocks_r10_traversal_symbol_and_url_swallowing_bypasses(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile, src_dir = _build_local_fixture(Path(tmp))
            profile['target']['closest_work_locator'] = '!file:FICTIONAL-PRIOR-A.txt: "Prior work omits the graph shift intervention"'
            profile['accepted_panel'][0]['closest_work_locator'] = 'sub/.. "Panel reference 1 reports bounded delta."'
            profile['fit_axes'][0]['locator'] = 'https://example.org/fictional-cfp(file:foo.txt: "Main scope covers graph learning"'
            out = novelty_mod.check(profile, as_of=self.as_of, sources_dir=src_dir)
            self.assertEqual(out['status'], 'invalid')
            self.assertIn('target:closest_work_locator_unverified:unsafe_source_path', out['errors'])
            self.assertIn('accepted_panel:0:closest_work_locator_unverified:unsafe_source_path', out['errors'])
            self.assertIn('fit_axes:0:locator_unverified:unsafe_source_path', out['errors'])
            self.assertIsNone(out['fit_score_out_of_10'])
            self.assertIsNone(out['novelty_comparison'])

    def test_https_port_validation_and_r11_url_snapshot_bypass_blocks(self):
        # Finding 3: _https() port validation
        for good_url in (
            'https://example.org:8443/cfp',
            'https://example.org:443/cfp',
            'https://[::1]:8443/cfp',
            'https://example.org:/cfp',
        ):
            self.assertTrue(novelty_mod._https(good_url), msg=repr(good_url))

        for bad_port_url in (
            'https://example.org:abc/cfp',
            'https://example.org:99999/cfp',
            'https://example.org:-1/cfp',
            'https://example.org:65536/cfp',
            'https://example.org:80:80/cfp',
            'https://[::1]:abc/cfp',
        ):
            self.assertFalse(novelty_mod._https(bad_port_url), msg=repr(bad_port_url))
            profile = json.loads(FIXTURE.read_text(encoding='utf-8'))
            profile['venue']['official_cfp_url'] = bad_port_url
            out = novelty_mod.check(profile, as_of=self.as_of)
            self.assertEqual(out['status'], 'invalid', msg=repr(bad_port_url))
            self.assertIn('venue:official_cfp_url_must_be_https', out['errors'], msg=repr(bad_port_url))

        # Finding 1 & 2 end-to-end inside compare_venue_novelty.check(sources_dir=...)
        with tempfile.TemporaryDirectory() as tmp:
            profile, src_dir = _build_local_fixture(Path(tmp))
            profile['target']['closest_work_locator'] = (
                'https://example.org/a\u202e../etc/passwd: "Prior work omits the graph shift intervention"'
            )
            profile['accepted_panel'][0]['closest_work_locator'] = (
                'https:///etc/passwd: "Panel reference 1 reports bounded delta."'
            )
            profile['fit_axes'][0]['locator'] = (
                'https://example.org/fictional-cfp\u200bfile:FICTIONAL-PRIOR-A.txt: "Main scope covers graph learning"'
            )
            profile['fit_axes'][1]['locator'] = (
                'https://example.org/fictional-p3\u2014/etc/passwd: "empirical mechanism studies"'
            )
            profile['fit_axes'][2]['locator'] = (
                'https://../etc/passwd: "multi-seed ablations"'
            )
            profile['fit_axes'][3]['locator'] = (
                'https://file:FICTIONAL-PRIOR-A.txt: "8 pages plus references"'
            )
            profile['fit_axes'][4]['locator'] = (
                'https://example.org/a//etc/passwd: "USD 750 early author registration"'
            )
            out = novelty_mod.check(profile, as_of=self.as_of, sources_dir=src_dir)
            self.assertEqual(out['status'], 'invalid')
            self.assertIn('target:closest_work_locator_unverified:unsafe_source_path', out['errors'])
            self.assertIn('accepted_panel:0:closest_work_locator_unverified:unsafe_source_path', out['errors'])
            for i in range(5):
                self.assertIn(f'fit_axes:{i}:locator_unverified:unsafe_source_path', out['errors'])
            self.assertIsNone(out['fit_score_out_of_10'])
            self.assertIsNone(out['novelty_comparison'])

    def test_r12_https_authority_hostnames_port_zero_and_quote_desync_blocks(self):
        # Finding 2: _https() must preserve valid authorities while rejecting malformed hostnames & port 0
        valid_https = (
            'https://example.org/cfp',
            'https://example.org:8443/cfp',
            'https://example.org:/cfp',
            'https://[::1]:8443/cfp',
            'https://[::1]/cfp',
            'https://localhost/cfp',
            'https://127.0.0.1/cfp',
            'https://127.0.0.1:8443/cfp',
            'https://münchen.de/cfp',
        )
        for url in valid_https:
            self.assertTrue(novelty_mod._https(url), msg=repr(url))

        bad_https = (
            'https://../',
            'https://..',
            'https://../cfp',
            'https://./cfp',
            'https://~/cfp',
            'https://.example.org/cfp',
            'https://example.org./cfp',
            'https://a..b.org/cfp',
            'https://-bad.org/cfp',
            'https://bad-.org/cfp',
            'https://127.1/cfp',
            'https://2130706433/cfp',
            'https://[example.org]/cfp',
            'https://[127.0.0.1]/cfp',
            'https://example.org:0/cfp',
            'https://example.org:000/cfp',
            'https://[::1]:0/cfp',
        )
        for url in bad_https:
            self.assertFalse(novelty_mod._https(url), msg=repr(url))

        # End-to-end check() rejects malformed hostnames & port 0 on official_cfp_url and official_acceptance_url
        for bad_url in ('https://../cfp', 'https://./cfp', 'https://~/cfp', 'https://example.org:0/cfp', 'https://[::1]:0/cfp'):
            profile = json.loads(FIXTURE.read_text(encoding='utf-8'))
            profile['venue']['official_cfp_url'] = bad_url
            profile['accepted_panel'][0]['official_acceptance_url'] = bad_url
            out = novelty_mod.check(profile, as_of=self.as_of)
            self.assertEqual(out['status'], 'invalid', msg=repr(bad_url))
            self.assertIn('venue:official_cfp_url_must_be_https', out['errors'], msg=repr(bad_url))
            self.assertIn('accepted_panel:0:official_acceptance_url_must_be_https', out['errors'], msg=repr(bad_url))

        # Finding 1: compare_venue_novelty.check() rejects single-quote/double-quote desync payloads in locators
        with tempfile.TemporaryDirectory() as tmp:
            profile, src_dir = _build_local_fixture(Path(tmp))
            (src_dir / 'FICTIONAL-PRIOR-A.txt').write_text(
                'We evaluate "zero-shot" transfer. Prior work omits the graph shift intervention under boundary B.\n',
                encoding='utf-8',
            )
            bundle_path = src_dir / 'venue-sources.json'
            bundle = json.loads(bundle_path.read_text(encoding='utf-8'))
            bundle['sources'][0]['text'] = (
                'We evaluate "zero-shot" transfer. ' + bundle['sources'][0]['text']
            )
            bundle_path.write_text(json.dumps(bundle), encoding='utf-8')

            # Benign mixed-quote locator passes cleanly
            profile_ok = copy.deepcopy(profile)
            profile_ok['target']['closest_work_locator'] = (
                'FICTIONAL-PRIOR-A.txt: \'We evaluate "zero-shot" transfer.\' "Prior work omits the graph shift intervention"'
            )
            profile_ok['fit_axes'][0]['locator'] = (
                '\'We evaluate "zero-shot" transfer.\' "Main scope covers graph learning"'
            )
            ok_out = novelty_mod.check(profile_ok, as_of=self.as_of, sources_dir=src_dir)
            self.assertEqual(ok_out['status'], 'structurally_checked', msg=ok_out['errors'])
            self.assertEqual(ok_out['fit_score_out_of_10'], 8)

            # Desync injection across target, accepted_panel, and fit_axes fails closed
            profile_bad = copy.deepcopy(profile)
            profile_bad['target']['closest_work_locator'] = (
                'FICTIONAL-PRIOR-A.txt: \'evaluate "zero-shot\' file:FICTIONAL-PRIOR-A.txt " transfer." "Prior work omits the graph shift intervention"'
            )
            profile_bad['accepted_panel'][0]['closest_work_locator'] = (
                'FICTIONAL-PRIOR-B.txt: \'evaluate "zero-shot\' /etc/passwd " transfer." "Panel reference 1 reports bounded delta."'
            )
            profile_bad['fit_axes'][0]['locator'] = (
                '\'evaluate "zero-shot\' ../etc/passwd " transfer." "Main scope covers graph learning"'
            )
            bad_out = novelty_mod.check(profile_bad, as_of=self.as_of, sources_dir=src_dir)
            self.assertEqual(bad_out['status'], 'invalid')
            self.assertIn('target:closest_work_locator_unverified:unsafe_source_path', bad_out['errors'])
            self.assertIn('accepted_panel:0:closest_work_locator_unverified:unsafe_source_path', bad_out['errors'])
            self.assertIn('fit_axes:0:locator_unverified:unsafe_source_path', bad_out['errors'])
            self.assertIsNone(bad_out['fit_score_out_of_10'])
            self.assertIsNone(bad_out['novelty_comparison'])


class VenueLeadsQualityLookupTests(unittest.TestCase):
    def test_venue_leads_quality_normalization_and_builtin_ccf_tiers(self):
        # Verify fixed backslash regex typo: backslashes no longer treated weirdly, punctuation collapsed
        self.assertEqual(leads_mod.normalize_venue_name('IEEE/CVF Conference & Pattern-Recognition (CVPR)'),
                         'ieee cvf conference and pattern recognition cvpr')
        self.assertEqual(leads_mod.compact_venue_name('IEEE/CVF-CVPR!'), 'ieeecvfcvpr')

        refs = leads_mod.load_venue_quality_refs()
        for acronym in ('NeurIPS', 'NIPS', 'ICLR', 'ICML', 'ACL', 'AAAI'):
            res = leads_mod.lookup_venue_quality(acronym, refs)
            self.assertEqual(res['quality_tier'], 'S', msg=f'{acronym} failed: {res}')
            self.assertEqual(res['matched_source'], 'builtin_ccf')

        ijcai = leads_mod.lookup_venue_quality('IJCAI', refs)
        self.assertEqual(ijcai['quality_tier'], 'A', msg=f'IJCAI failed: {ijcai}')
        self.assertEqual(ijcai['evidence'], ['CCF B'])
        self.assertEqual(ijcai['matched_source'], 'builtin_ccf')

        # Secondary probes: proceedings prefix stripping & parenthetical acronym
        adv = leads_mod.lookup_venue_quality('Advances in Neural Information Processing Systems 2024', refs)
        self.assertEqual(adv['quality_tier'], 'S')
        self.assertEqual(adv['match_type'], 'proceedings_stripped')

        paren = leads_mod.lookup_venue_quality('Forty-First International Conference on Something (ICML)', refs)
        self.assertEqual(paren['quality_tier'], 'S')
        self.assertEqual(paren['match_type'], 'parenthetical_acronym')

        emnlp = leads_mod.lookup_venue_quality('EMNLP', refs)
        self.assertEqual(emnlp['quality_tier'], 'A')

        # Preprints must stay Unknown / preprint_excluded
        for pre in ('arXiv (Cornell University)', 'bioRxiv (Cold Spring Harbor Laboratory)', 'medRxiv', 'SSRN Electronic Journal'):
            res = leads_mod.lookup_venue_quality(pre, refs)
            self.assertEqual(res['quality_tier'], 'Unknown', msg=f'{pre}: {res}')
            self.assertEqual(res['match_type'], 'preprint_excluded')
            self.assertEqual(res['recommendation'], 'Insufficient Venue Evidence')

    def test_venue_leads_collect_includes_venue_quality_and_coverage(self):
        def transport(params):
            return {
                'meta': {'count': 3},
                'results': [
                    {'id': 'W1', 'publication_year': 2024, 'primary_location': {'source': {'id': 'S1', 'display_name': 'Advances in Neural Information Processing Systems', 'type': 'conference'}}},
                    {'id': 'W2', 'publication_year': 2025, 'primary_location': {'source': {'id': 'S2', 'display_name': 'arXiv (Cornell University)', 'type': 'repository'}}},
                    {'id': 'W3', 'publication_year': 2025, 'primary_location': {'source': {'id': 'S3', 'display_name': 'Obscure Workshop X', 'type': 'conference'}}},
                ],
            }

        out = leads_mod.collect('graph shift', pages=1, page_size=10, transport=transport)
        self.assertEqual(out['venue_quality_coverage']['matched'], 1)
        self.assertEqual(out['venue_quality_coverage']['unmatched'], 2)
        self.assertEqual(out['venue_quality_coverage']['refs_mode'], 'builtin_ccf_only')
        by_name = {row['name']: row for row in out['source_leads']}
        self.assertEqual(by_name['Advances in Neural Information Processing Systems']['venue_quality']['quality_tier'], 'S')
        self.assertEqual(by_name['arXiv (Cornell University)']['venue_quality']['match_type'], 'preprint_excluded')
        self.assertEqual(by_name['Obscure Workshop X']['venue_quality']['quality_tier'], 'Unknown')

    def test_venue_leads_external_quality_refs_dir_and_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            refs_dir = Path(tmp)
            (refs_dir / 'ccf_conferences.json').write_text(json.dumps({
                '会议全称 AAAI Conference on Artificial': 'A',
                'Custom Conf B': 'B',
            }), encoding='utf-8')
            (refs_dir / 'journal_scores.json').write_text(json.dumps({
                'nature machine intelligence': {'name': 'Nature Machine Intelligence', 'quartile': 'Q1', 'if': 23.9, 'csa_zone': 1},
            }), encoding='utf-8')
            (refs_dir / 'eiiRankingName.json').write_text(json.dumps({'SOME EI JOURNAL': 'EI'}), encoding='utf-8')
            (refs_dir / 'chinese_journal_tags.json').write_text(json.dumps({'中文核心期刊': ['北大核心']}), encoding='utf-8')

            refs = leads_mod.load_venue_quality_refs(refs_dir)
            self.assertEqual(refs['refs_mode'], 'builtin_ccf_plus_external')
            nmi = leads_mod.lookup_venue_quality('Nature Machine Intelligence', refs)
            self.assertEqual(nmi['quality_tier'], 'S')
            self.assertIn('JCR Q1', nmi['evidence'])
            self.assertIn('CAS Zone 1', nmi['evidence'])

            ei = leads_mod.lookup_venue_quality('Some EI Journal', refs)
            self.assertEqual(ei['quality_tier'], 'B')
            self.assertIn('EI', ei['evidence'])

            zh = leads_mod.lookup_venue_quality('中文核心期刊', refs)
            self.assertEqual(zh['quality_tier'], 'B')
            self.assertIn('北大核心', zh['evidence'])

            # Built-in NeurIPS still works even when external ccf_conferences.json omits it
            neurips = leads_mod.lookup_venue_quality('NeurIPS', refs)
            self.assertEqual(neurips['quality_tier'], 'S')

        script = str(SCRIPTS_DIR / 'venue_leads.py')
        help_res = subprocess.run([sys.executable, script, '--help'], capture_output=True, text=True)
        self.assertEqual(help_res.returncode, 0)
        self.assertIn('--quality-refs-dir', help_res.stdout)
        self.assertIn('--compact', help_res.stdout)
        self.assertIn('--out', help_res.stdout)

    def test_venue_leads_parenthetical_year_ai_cs_venues_preprints_and_compact(self):
        refs = leads_mod.load_venue_quality_refs()
        for venue_str in (
            'Advances in Neural Information Processing Systems 36 (NeurIPS 2023)',
            'International Conference on Learning Representations (ICLR 2025)',
            'Proceedings of the 38th AAAI Conference on Artificial Intelligence (AAAI 2024)',
        ):
            res = leads_mod.lookup_venue_quality(venue_str, refs)
            self.assertEqual(res['quality_tier'], 'S', msg=f'{venue_str}: {res}')

        ijcai_24 = leads_mod.lookup_venue_quality(
            'Proceedings of the Thirty-Third International Joint Conference on Artificial Intelligence (IJCAI-24)',
            refs,
        )
        self.assertEqual(ijcai_24['quality_tier'], 'A', msg=f'IJCAI-24: {ijcai_24}')
        self.assertEqual(ijcai_24['evidence'], ['CCF B'])

        # Findings and Workshops must NOT be falsely inflated to S-tier
        for non_main in (
            'Findings of the Association for Computational Linguistics: ACL 2024',
            'ICLR Workshop on Tiny Papers (ICLR 2025)',
        ):
            res = leads_mod.lookup_venue_quality(non_main, refs)
            self.assertEqual(res['quality_tier'], 'Unknown', msg=f'{non_main}: {res}')

        # CoRR and preprint variants must resolve to Unknown / preprint_excluded
        for pre in ('CoRR', 'bioRxiv preprint', 'SSRN Working Paper'):
            res = leads_mod.lookup_venue_quality(pre, refs)
            self.assertEqual(res['quality_tier'], 'Unknown', msg=f'{pre}: {res}')
            self.assertEqual(res['match_type'], 'preprint_excluded', msg=f'{pre}: {res}')

        # External CCF table with non-A/B/C rank must NOT emit confidence='high'
        with tempfile.TemporaryDirectory() as tmp:
            refs_dir = Path(tmp)
            (refs_dir / 'ccf_conferences.json').write_text(json.dumps({'Odd Conf': 'D'}), encoding='utf-8')
            ext_refs = leads_mod.load_venue_quality_refs(refs_dir)
            odd = leads_mod.lookup_venue_quality('Odd Conf', ext_refs)
            self.assertEqual(odd['quality_tier'], 'Unknown')
            self.assertEqual(odd['confidence'], 'low')

        # Compact output helper strips bulky related_work_ids and caps top_leads
        sample = leads_mod.collect(
            'vision transformers',
            pages=1,
            page_size=5,
            transport=lambda p: {
                'meta': {'count': 1},
                'results': [{
                    'id': 'W1',
                    'publication_year': 2024,
                    'primary_location': {'source': {'id': 'S1', 'display_name': 'CVPR', 'type': 'conference'}},
                }],
            },
        )
        compact = leads_mod._compact_output(sample, '/tmp/leads.json')
        self.assertTrue(compact['compact'])
        self.assertEqual(compact['lead_count'], 1)
        self.assertEqual(compact['top_leads'][0]['quality_tier'], 'S')
        self.assertNotIn('related_work_ids', compact['top_leads'][0])
        self.assertEqual(compact['artifact_path'], '/tmp/leads.json')

        # main() --out + --compact writes full JSON to --out and bounded summary to stdout
        import io
        from contextlib import redirect_stdout

        class _FakeResp:
            def __init__(self, payload: bytes):
                self._buf = io.BytesIO(payload)
            def __enter__(self):
                return self
            def __exit__(self, *exc):
                return False
            def read(self, *args):
                return self._buf.read(*args)

        fake_body = json.dumps({
            'meta': {'count': 1},
            'results': [{
                'id': 'W1',
                'publication_year': 2024,
                'primary_location': {'source': {'id': 'S1', 'display_name': 'CVPR', 'type': 'conference'}},
            }],
        }).encode('utf-8')
        orig_urlopen = leads_mod.urlopen
        leads_mod.urlopen = lambda req, timeout=20: _FakeResp(fake_body)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out_file = Path(tmp) / 'leads.json'
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = leads_mod.main(['vision transformers', '--out', str(out_file), '--compact'])
                self.assertEqual(rc, 0)
                cli_compact = json.loads(buf.getvalue())
                self.assertTrue(cli_compact['compact'])
                self.assertEqual(cli_compact['artifact_path'], str(out_file))
                self.assertEqual(cli_compact['lead_count'], 1)
                self.assertNotIn('related_work_ids', cli_compact['top_leads'][0])
                full = json.loads(out_file.read_text(encoding='utf-8'))
                self.assertEqual(full['source_leads'][0]['related_work_ids'], ['W1'])
        finally:
            leads_mod.urlopen = orig_urlopen

    def test_ccf_7th_ed_accuracy_disambiguation_secondary_tracks_and_https_pdf_locator(self):
        refs = leads_mod.load_venue_quality_refs()

        # 1. Non-CCF venues must NOT get fabricated CCF tiers
        for non_ccf in (
            'EACL',
            'European Chapter of the Association for Computational Linguistics',
            'Conference of the European Chapter of the Association for Computational Linguistics',
            'WACV',
            'AACL',
            'IMWUT',
            'TMLR',
        ):
            res = leads_mod.lookup_venue_quality(non_ccf, refs)
            self.assertEqual(res['quality_tier'], 'Unknown', msg=f'{non_ccf}: {res}')
            self.assertEqual(res['evidence'], [], msg=f'{non_ccf}: {res}')

        # 2. Reconciled CCF 7th Edition (March 2026) ranks
        expected_ranks = {
            'ICLR': ('S', ['CCF A']),
            'IJCAI': ('A', ['CCF B']),
            'AISTATS': ('B', ['CCF C']),
            'MSR': ('B', ['CCF C']),
            'ICWS': ('A', ['CCF B']),
            'DASFAA': ('A', ['CCF B']),
            'PODS': ('A', ['CCF B']),
            'NDSS': ('S', ['CCF A']),
            'ISSTA': ('S', ['CCF A']),
            'ICDE': ('S', ['CCF A']),
            'SODA': ('S', ['CCF A']),
            'FM': ('S', ['CCF A']),
            'EuroSys': ('S', ['CCF A']),
            'USENIX ATC': ('S', ['CCF A']),
            'ACM SIGOPS ATC': ('S', ['CCF A']),
            'FAST': ('S', ['CCF A']),
            'UIST': ('S', ['CCF A']),
            'ASE': ('S', ['CCF A']),
            'CSCW': ('S', ['CCF A']),
            'WWW': ('S', ['CCF A']),
            'World Wide Web': ('A', ['CCF B']),
            'World Wide Web (WWW)': ('A', ['CCF B']),
            'Automated Software Engineering': ('A', ['CCF B']),
            'Computer Supported Cooperative Work': ('A', ['CCF B']),
            'Fast Software Encryption': ('A', ['CCF B']),
        }
        for venue_name, (exp_tier, exp_ev) in expected_ranks.items():
            res = leads_mod.lookup_venue_quality(venue_name, refs)
            self.assertEqual((res['quality_tier'], res['evidence']), (exp_tier, exp_ev), msg=f'{venue_name}: {res}')

        # 3. Parenthetical secondary-track venues must NOT promote to main conference tiers
        #    under either built-in refs or external --quality-refs-dir
        secondary_titles = (
            'Findings of the Association for Computational Linguistics (ACL 2024)',
            'Workshop on Trustworthy AI (NeurIPS)',
            'NeurIPS Workshop on Safety (NeurIPS)',
            'Workshop on Trustworthy AI (ICML)',
            'Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR) Workshops',
            'System Demonstrations (EMNLP 2024)',
            'Tutorial on Foundation Models (ICLR 2025)',
            'Companion Proceedings of the ACM Web Conference (WWW 2024)',
            'AAAI Doctoral Consortium (AAAI 2024)',
            'NeurIPS (Workshop)',
            'Co-located Workshops (CVPR)',
            'Extended Abstracts of CHI',
            'Posters (ICML)',
        )
        with tempfile.TemporaryDirectory() as tmp:
            ext_dir = Path(tmp)
            (ext_dir / 'ccf_conferences.json').write_text(json.dumps({
                'ACL': 'A',
                'NeurIPS': 'A',
                'ICML': 'A',
                'CVPR': 'A',
                'EMNLP': 'B',
                'ICLR': 'A',
                'WWW': 'A',
                'AAAI': 'A',
                'CHI': 'A',
            }), encoding='utf-8')
            ext_refs = leads_mod.load_venue_quality_refs(ext_dir)
            for label, ref_set in (('builtin', refs), ('external', ext_refs)):
                for title in secondary_titles:
                    res = leads_mod.lookup_venue_quality(title, ref_set)
                    self.assertEqual(res['quality_tier'], 'Unknown', msg=f'[{label}] {title}: {res}')

        # 4. R2-4h: HTTPS .pdf URL repeated inside fit_axes[0].locator verifies cleanly
        with tempfile.TemporaryDirectory() as tmp:
            profile, src_dir = _build_local_fixture(Path(tmp))
            bundle_path = src_dir / 'venue-sources.json'
            bundle = json.loads(bundle_path.read_text(encoding='utf-8'))
            bundle['sources'].append({
                'requested_url': 'https://example.org/fictional-cfp.pdf',
                'final_url': 'https://example.org/fictional-cfp.pdf',
                'extraction_status': 'ok',
                'same_host_path_redirect_year_mismatch': False,
                'js_rendered_suspected': False,
                'text': 'Main scope covers graph learning.',
            })
            bundle_path.write_text(json.dumps(bundle), encoding='utf-8')
            profile['fit_axes'][0]['source_url'] = 'https://example.org/fictional-cfp.pdf'
            profile['fit_axes'][0]['locator'] = (
                'https://example.org/fictional-cfp.pdf: "Main scope covers graph learning"'
            )
            out = novelty_mod.check(profile, as_of=datetime(2026, 11, 21, 12, tzinfo=timezone.utc), sources_dir=src_dir)
            self.assertEqual(out['status'], 'structurally_checked', msg=out['errors'])
            self.assertEqual(out['fit_score_out_of_10'], 8)

    def test_ccf_7th_ed_precedence_over_external_refs_and_extended_secondary_tracks(self):
        # 1. Curated CCF-7 builtin_ccf must take precedence over stale/conflicting external ccf_conferences.json
        ccf7_expected = {
            'ICLR': ('S', ['CCF A']),
            'IJCAI': ('A', ['CCF B']),
            'AISTATS': ('B', ['CCF C']),
            'MSR': ('B', ['CCF C']),
            'ICWS': ('A', ['CCF B']),
            'DASFAA': ('A', ['CCF B']),
            'PODS': ('A', ['CCF B']),
            'NDSS': ('S', ['CCF A']),
            'ISSTA': ('S', ['CCF A']),
            'ICDE': ('S', ['CCF A']),
            'SODA': ('S', ['CCF A']),
            'FM': ('S', ['CCF A']),
            'EuroSys': ('S', ['CCF A']),
            'USENIX ATC': ('S', ['CCF A']),
            'ACM SIGOPS ATC': ('S', ['CCF A']),
            'FAST': ('S', ['CCF A']),
            'UIST': ('S', ['CCF A']),
            'ASE': ('S', ['CCF A']),
            'CSCW': ('S', ['CCF A']),
            'WWW': ('S', ['CCF A']),
            'FSE': ('S', ['CCF A']),
            'World Wide Web': ('A', ['CCF B']),
            'World Wide Web (WWW)': ('A', ['CCF B']),
            'Automated Software Engineering': ('A', ['CCF B']),
            'Automated Software Engineering (ASE)': ('A', ['CCF B']),
            'Computer Supported Cooperative Work': ('A', ['CCF B']),
            'Computer Supported Cooperative Work (CSCW)': ('A', ['CCF B']),
            'Fast Software Encryption': ('A', ['CCF B']),
            'Fast Software Encryption (FSE)': ('A', ['CCF B']),
        }

        with tempfile.TemporaryDirectory() as tmp:
            ext_dir = Path(tmp)
            # Synthetic external ccf_conferences.json containing stale 6th-ed / journal collisions
            (ext_dir / 'ccf_conferences.json').write_text(json.dumps({
                'ASE': 'B',
                'CSCW': 'B',
                'WWW': 'B',
                'FSE': 'B',
                'IJCAI': 'A',
                'ICLR': 'B',
                'AISTATS': 'B',
                'MSR': 'B',
                'PODS': 'A',
                'Custom External Conf': 'B',
                'ACL': 'A',
                'NeurIPS': 'A',
                'ICML': 'A',
                'KDD': 'A',
                'ICSE': 'A',
            }), encoding='utf-8')
            synth_refs = leads_mod.load_venue_quality_refs(ext_dir)

            for venue_name, (exp_tier, exp_ev) in ccf7_expected.items():
                res = leads_mod.lookup_venue_quality(venue_name, synth_refs)
                self.assertEqual((res['quality_tier'], res['evidence']), (exp_tier, exp_ev), msg=f'[synth] {venue_name}: {res}')
                self.assertEqual(res['matched_source'], 'builtin_ccf', msg=f'[synth] {venue_name}: {res}')

            # External-only entries not in builtin_ccf still resolve cleanly
            custom_res = leads_mod.lookup_venue_quality('Custom External Conf', synth_refs)
            self.assertEqual((custom_res['quality_tier'], custom_res['evidence']), ('A', ['CCF B']))
            self.assertEqual(custom_res['matched_source'], 'ccf_conferences')

            # 2. Extended secondary tracks must return Unknown under both builtin and external refs
            builtin_refs = leads_mod.load_venue_quality_refs()
            extended_secondary = (
                'NeurIPS Dataset and Benchmark Track (NeurIPS 2024)',
                'Datasets and Benchmarks Track (NeurIPS 2024)',
                'ACL SRW (ACL 2024)',
                'Industry Track (KDD 2024)',
                'Doctoral Symposium (ICSE 2024)',
                'Position Paper Track (ICML 2024)',
                'Pre-conference Symposium (ICML 2024)',
            )
            # 3. Legitimate main conferences with 'Symposium' in their official name must NOT be blocked
            main_symposiums = (
                'IEEE Symposium on Security and Privacy (S&P)',
                'ACM Symposium on User Interface Software and Technology (UIST)',
                'ACM Symposium on Theory of Computing (STOC)',
                'ACM-SIAM Symposium on Discrete Algorithms (SODA)',
                'ACM SIGOPS Symposium on Operating Systems Principles (SOSP)',
                'USENIX Symposium on Networked Systems Design and Implementation (NSDI)',
                'Symposium on Foundations of Computer Science (FOCS)',
                'ACM SIGSOFT International Symposium on Software Testing and Analysis (ISSTA)',
            )

            ref_sets = [('builtin', builtin_refs), ('synthetic_ext', synth_refs)]
            pqf_dir = Path('/tmp/research-repos/paper-quality-filter/references')
            if pqf_dir.is_dir():
                pqf_refs = leads_mod.load_venue_quality_refs(pqf_dir)
                ref_sets.append(('external_pqf', pqf_refs))
                for venue_name, (exp_tier, exp_ev) in ccf7_expected.items():
                    res = leads_mod.lookup_venue_quality(venue_name, pqf_refs)
                    self.assertEqual(res['quality_tier'], exp_tier, msg=f'[pqf] {venue_name}: {res}')
                    self.assertIn(exp_ev[0], res['evidence'], msg=f'[pqf] {venue_name}: {res}')
                    self.assertEqual(res['matched_source'], 'builtin_ccf', msg=f'[pqf] {venue_name}: {res}')
                for non_ccf in ('EACL', 'WACV', 'AACL', 'IMWUT', 'TMLR'):
                    res = leads_mod.lookup_venue_quality(non_ccf, pqf_refs)
                    self.assertEqual((res['quality_tier'], res['evidence']), ('Unknown', []), msg=f'[pqf] {non_ccf}: {res}')

            for label, rset in ref_sets:
                for title in extended_secondary:
                    res = leads_mod.lookup_venue_quality(title, rset)
                    self.assertEqual(res['quality_tier'], 'Unknown', msg=f'[{label}] {title}: {res}')
                for main_symp in main_symposiums:
                    res = leads_mod.lookup_venue_quality(main_symp, rset)
                    self.assertEqual((res['quality_tier'], res['evidence']), ('S', ['CCF A']), msg=f'[{label}] {main_symp}: {res}')


if __name__ == '__main__':
    unittest.main()
