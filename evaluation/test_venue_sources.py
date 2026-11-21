"""Offline tests for venue source capture, redirect/JS verification, and plan gating."""
import gzip
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from email.message import Message
from pathlib import Path
from urllib.request import BaseHandler, build_opener
from urllib.response import addinfourl

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'research-scientist/scripts'


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


capture = load('capture_venue_sources')
checker = load('check_venue_sources')
planner = load('check_venue_plan')


def _make_fake_https_opener(routes):
    """Build an offline opener_factory serving scripted HTTP responses/redirects."""

    class FakeHTTPSHandler(BaseHandler):
        handler_order = 100

        def https_open(self, req):
            url = req.full_url
            entry = routes[url]
            if callable(entry):
                entry = entry(req)
            status = entry.get('status', 200)
            headers = Message()
            for k, v in (entry.get('headers') or {}).items():
                headers[k] = v
            body = entry.get('body', b'')
            resp = addinfourl(io.BytesIO(body), headers, url, status)
            resp.msg = entry.get('msg', 'OK')
            if status >= 400 or status in (301, 302, 303, 307, 308):
                return self.parent.error('https', req, resp, status, resp.msg, headers)
            return resp

    return lambda redirect_handler: build_opener(redirect_handler, FakeHTTPSHandler())


class VenueSourceTests(unittest.TestCase):
    def dossier(self):
        return {
            'venue': 'Example Conference',
            'edition': '2027',
            'track': 'Research',
            'official_cfp_url': 'https://conference.example/cfp',
            'milestones': {'full_paper': '2027-03-01T23:59:00 AoE'},
            'fees': [{
                'category': 'author_registration',
                'amount': 500,
                'mandatory': True,
                'source_url': 'https://conference.example/fees',
            }],
            'evidence_claims': [
                {
                    'field': 'milestones.full_paper',
                    'source_url': 'https://conference.example/cfp',
                    'quote': 'Full papers: March 1, 2027, 23:59 AoE',
                },
                {
                    'field': 'fees.author_registration',
                    'source_url': 'https://conference.example/fees',
                    'quote': 'Author registration is USD 500',
                },
            ],
        }

    def transport(self, url):
        if url.endswith('/cfp'):
            body = b'<html><script>fake deadline</script><body><p>Full papers: March 1, 2027, 23:59 AoE</p></body></html>'
        else:
            body = b'<html><p>Author registration is USD 500</p></html>'
        return {
            'final_url': url,
            'content_type': 'text/html; charset=utf-8',
            'body': body,
            'http_status': 200,
        }

    # --- Existing 5 baseline tests (preserved verbatim) ---

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

    # --- New F13 tests: Multi-hop redirect chains & security ---

    def test_multihop_redirect_chain_301_302_307_308_and_bounce(self):
        routes = {
            'https://conf.example/start': {
                'status': 301,
                'headers': {'Location': 'https://conf.example/mid1'},
            },
            'https://conf.example/mid1': {
                'status': 302,
                'headers': {'Location': '/mid2'},
            },
            'https://conf.example/mid2': {
                'status': 307,
                'headers': {'Location': 'https://conf.example/mid3'},
            },
            'https://conf.example/mid3': {
                'status': 308,
                'headers': {'Location': 'https://conf.example/final'},
            },
            'https://conf.example/final': {
                'status': 200,
                'headers': {'Content-Type': 'text/html; charset=utf-8'},
                'body': b'<html><body><p>Full papers: March 1, 2027</p></body></html>',
            },
            'https://a.org/2027': {
                'status': 302,
                'headers': {'Location': 'https://b.org/stale'},
            },
            'https://b.org/stale': {
                'status': 302,
                'headers': {'Location': 'https://a.org/2027'},
            },
            'https://a.org/2027_final': {},
        }
        # Test 4-hop chain (301 -> 302 -> 307 -> 308 -> 200)
        opener_factory = _make_fake_https_opener(routes)
        snap = capture.capture_url(
            'https://conf.example/start',
            transport=lambda u: capture.fetch(u, opener_factory=opener_factory),
        )
        self.assertEqual(snap['final_url'], 'https://conf.example/final')
        self.assertEqual([h['status'] for h in snap['redirect_chain']], [301, 302, 307, 308])
        self.assertFalse(snap['redirected_to_different_host'])

        # Test cross-host bounce A -> B -> A
        bounce_routes = {
            'https://a.org/2027': {
                'status': 302,
                'headers': {'Location': 'https://b.org/stale'},
            },
            'https://b.org/stale': {
                'status': 302,
                'headers': {'Location': 'https://a.org/2027/done'},
            },
            'https://a.org/2027/done': {
                'status': 200,
                'headers': {'Content-Type': 'text/html'},
                'body': b'<html><p>Conference 2027</p></html>',
            },
        }
        bounce_factory = _make_fake_https_opener(bounce_routes)
        bounce_snap = capture.capture_url(
            'https://a.org/2027',
            transport=lambda u: capture.fetch(u, opener_factory=bounce_factory),
        )
        self.assertTrue(bounce_snap['redirected_to_different_host'])
        self.assertEqual(len(bounce_snap['redirect_chain']), 2)

    def test_intermediate_non_https_hop_rejected(self):
        routes = {
            'https://conf.example/cfp': {
                'status': 302,
                'headers': {'Location': 'http://conf.example/insecure'},
            },
        }
        opener_factory = _make_fake_https_opener(routes)
        with self.assertRaisesRegex(RuntimeError, 'redirected_to_non_https_url'):
            capture.fetch('https://conf.example/cfp', opener_factory=opener_factory)
        snap = capture.capture_url(
            'https://conf.example/cfp',
            transport=lambda u: capture.fetch(u, opener_factory=opener_factory),
        )
        self.assertEqual(snap['extraction_status'], 'fetch_failed')
        self.assertEqual(snap['error'], 'redirected_to_non_https_url')

    def test_mock_transport_redirect_chain_synthesis(self):
        snap_same = capture.capture_url('https://conference.example/cfp', transport=self.transport)
        self.assertEqual(snap_same['redirect_chain'], [])
        snap_diff = capture.capture_url(
            'https://conference.example/2027/cfp',
            transport=lambda u: {
                'final_url': 'https://conference.example/2025/cfp',
                'content_type': 'text/html',
                'body': b'<html><p>CFP 2025</p></html>',
                'http_status': 200,
            },
        )
        self.assertEqual(len(snap_diff['redirect_chain']), 1)
        self.assertEqual(snap_diff['redirect_chain'][0]['to_url'], 'https://conference.example/2025/cfp')

    # --- Same-host stale-year redirect positives & false-positive prevention ---

    def test_same_host_stale_year_redirect_positives(self):
        positive_cases = [
            ('https://aaai.org/conference/aaai/aaai-27/registration/', 'https://aaai.org/conference/aaai/aaai-25/registration/', None, b'<html></html>'),
            ('https://conf.example/2027/cfp', 'https://conf.example/2025/cfp', None, b'<html></html>'),
            ('https://icml.cc/icml2026/cfp', 'https://icml.cc/icml2024/cfp', None, b'<html></html>'),
            ('https://kdd.org/kdd2027/dates', 'https://kdd.org/kdd2026/dates', None, b'<html></html>'),
            ('https://conf.example/cfp?year=2027', 'https://conf.example/cfp?year=2025', None, b'<html></html>'),
            (
                'https://conf.example/2027/cfp',
                'https://conf.example/cfp',
                [
                    {'from_url': 'https://conf.example/2027/cfp', 'status': 301, 'to_url': 'https://conf.example/2025/cfp'},
                    {'from_url': 'https://conf.example/2025/cfp', 'status': 302, 'to_url': 'https://conf.example/cfp'},
                ],
                b'<html></html>',
            ),
            (
                'https://conf.example/2027/cfp',
                'https://conf.example/cfp',
                None,
                b'<html><head><title>AAAI-25 Registration</title></head><body><p>Welcome</p></body></html>',
            ),
        ]
        for req_url, fin_url, chain, body in positive_cases:
            with self.subTest(req=req_url, fin=fin_url):
                mismatch, details = capture.detect_same_host_path_redirect_year_mismatch(
                    req_url, fin_url, chain, body.decode('utf-8')
                )
                self.assertTrue(mismatch, f'Expected mismatch for {req_url} -> {fin_url}')
                self.assertIsInstance(details, dict)

    def test_same_host_year_drift_false_positive_prevention(self):
        negative_cases = [
            ('https://aaai.org/conference/aaai/aaai-27/', 'https://aaai.org/conference/aaai/aaai-2027/'),
            ('https://conf.example:2025/cfp', 'https://conf.example:2025/registration'),
            ('https://conf.example/paper/2025', 'https://conf.example/paper/2026'),
            ('https://conf.example/cfp?paper_id=2025', 'https://conf.example/cfp?paper_id=2026'),
            ('https://conf.example/papers/20251234', 'https://conf.example/papers/20259999'),
            ('https://conf.example/02-15/cfp', 'https://conf.example/02-16/cfp'),
            ('https://conf.example/2026-02-15/cfp', 'https://conf.example/2026-02-16/cfp'),
            ('https://conf.example/feb-25/cfp', 'https://conf.example/feb-26/cfp'),
            ('https://conf.example/track-25/cfp', 'https://conf.example/track-26/cfp'),
            ('https://proceedings.mlr.press/v235', 'https://proceedings.mlr.press/v235/'),
        ]
        for req_url, fin_url in negative_cases:
            with self.subTest(req=req_url, fin=fin_url):
                mismatch, _ = capture.detect_same_host_path_redirect_year_mismatch(req_url, fin_url, None)
                self.assertFalse(mismatch, f'Unexpected mismatch for {req_url} -> {fin_url}')

    # --- JS-rendered detection positives & false-positive prevention ---

    def test_js_rendered_dynamic_detection_positives(self):
        nav_padding = ' '.join(['NeurIPS 2026 Navigation Policy Cancellation $100 USD fee applies.'] * 80)
        neurips_pricing_html = (
            '<html><head><title>2026 Pricing</title></head><body>'
            f'<nav>{nav_padding}</nav>'
            '<form id="registration-form"><i class="fa fa-spinner fa-spin d-none" id="pricingSpinner"></i>'
            '<div class="card-body mb-3" id="earlyregistration">   </div>'
            '<div class="card-body mb-3" id="lateregistration">   </div></form>'
            '<script>function getpricing(){ $.ajax({type:"POST", success: function(data){ '
            '$("#earlyregistration").html(data["early_invoice_html"]); '
            '$("#lateregistration").html(data["late_invoice_html"]); }}); }</script>'
            '</body></html>'
        ).encode('utf-8')

        spa_root_html = (
            b'<html><head><title>NeurIPS 2027 Registration</title></head>'
            b'<body><div id="root"></div><script src="/static/js/main.chunk.js"></script></body></html>'
        )
        spa_app_html = (
            b'<html><body><div id="app"></div><script src="/assets/bundle.js"></script></body></html>'
        )
        reactroot_html = (
            b'<html><body><div data-reactroot=""></div><script src="/app.js"></script></body></html>'
        )
        next_empty_html = (
            b'<html><body><div id="__next"></div><script id="__NEXT_DATA__" type="application/json">{}</script></body></html>'
        )
        noscript_html = (
            b'<html><body><noscript>Please enable JavaScript to view registration pricing.</noscript>'
            b'<div id="app-root"></div></body></html>'
        )
        calculator_html = (
            b'<html><body><p>Select your category to calculate your registration fee using our pricing calculator.</p>'
            b'<script src="/calc.js"></script></body></html>'
        )
        empty_table_html = (
            b'<html><body><h2>Fees</h2><table><tbody></tbody></table>'
            b'<script>loadFees();</script></body></html>'
        )
        cf_challenge_html = (
            b'<html><head><title>Just a moment...</title></head>'
            b'<body><p>Just a moment... Checking your browser before accessing conference.example.</p></body></html>'
        )

        for name, body in (
            ('neurips_ajax_pricing', neurips_pricing_html),
            ('spa_root', spa_root_html),
            ('spa_app', spa_app_html),
            ('reactroot', reactroot_html),
            ('next_empty', next_empty_html),
            ('noscript', noscript_html),
            ('calculator', calculator_html),
            ('empty_table', empty_table_html),
            ('cf_challenge', cf_challenge_html),
        ):
            with self.subTest(case=name):
                snap = capture.capture_url(
                    'https://conference.example/pricing',
                    transport=lambda u, b=body: {
                        'final_url': u,
                        'content_type': 'text/html; charset=utf-8',
                        'body': b,
                        'http_status': 200,
                    },
                )
                self.assertTrue(snap['js_rendered_suspected'], f'{name} should trigger js_rendered_suspected')
                self.assertTrue(snap['unverified_dynamic_page'])
                self.assertTrue(snap['js_rendered_signals'])

    def test_anubis_202_capture_and_js_detection(self):
        anubis_html = (
            b'<html><head><title>Making sure you&#39;re not a bot!</title></head>'
            b'<body><script id="anubis_challenge" type="application/json">{"rules":{}}</script>'
            b'<meta http-equiv="refresh" content="2; url=/.within.website/x/cmd/anubis/api/pass-challenge">'
            b'<p>Making sure you\'re not a bot!</p></body></html>'
        )
        snap = capture.capture_url(
            'https://dblp.org/search/venue/api?q=icml&format=json',
            transport=lambda u: {
                'final_url': u,
                'content_type': 'text/html; charset=utf-8',
                'body': anubis_html,
                'http_status': 202,
            },
        )
        self.assertEqual(snap['extraction_status'], 'bot_blocked_anubis')
        self.assertEqual(snap['http_status'], 202)
        self.assertEqual(snap['text'], '')
        js_flag, signals = capture.detect_js_rendered(anubis_html.decode('utf-8'), "Making sure you're not a bot!", 'html_text_extracted')
        self.assertTrue(js_flag)
        self.assertTrue(any('anubis' in s for s in signals))

    def test_js_detection_false_positive_prevention(self):
        jmlr_plain = b'<html><body><p>There are no publication fees associated with this journal.</p></body></html>'
        jmlr_analytics = (
            b'<html><body><p>There are no publication fees associated with this journal.</p>'
            b'<script>var _paq = [];</script></body></html>'
        )
        ssr_body = ' '.join(['Full papers due March 1, 2027 AoE. Author registration USD 500.'] * 15)
        ssr_next_html = (
            f'<html><body><div id="__next"><main>{ssr_body}</main></div>'
            f'<script id="__NEXT_DATA__" type="application/json">{{"page":"cfp"}}</script>'
            f'<script src="/_next/static/chunks/main.js"></script></body></html>'
        ).encode('utf-8')

        for name, body in (('jmlr_plain', jmlr_plain), ('jmlr_analytics', jmlr_analytics), ('ssr_next', ssr_next_html)):
            with self.subTest(case=name):
                snap = capture.capture_url(
                    'https://journal.example/author-info',
                    transport=lambda u, b=body: {
                        'final_url': u,
                        'content_type': 'text/html; charset=utf-8',
                        'body': b,
                        'http_status': 200,
                    },
                )
                self.assertFalse(snap['js_rendered_suspected'], f'{name} false positive: {snap["js_rendered_signals"]}')
                self.assertFalse(snap['unverified_dynamic_page'])

    # --- check_venue_sources.py blocking & CLI exit codes ---

    def test_check_venue_sources_blocks_stale_redirect_js_and_silent_nulls(self):
        # 1. Stale-year redirect WITH matching generic quote -> still blocked!
        dossier = self.dossier()
        dossier['official_cfp_url'] = 'https://aaai.org/conference/aaai/aaai-27/cfp'
        dossier['evidence_claims'][0]['source_url'] = dossier['official_cfp_url']
        bundle = capture.capture_dossier(
            dossier,
            transport=lambda u: {
                'final_url': 'https://aaai.org/conference/aaai/aaai-25/cfp' if 'aaai-27' in u else u,
                'content_type': 'text/html',
                'body': b'<html><p>Full papers: March 1, 2027, 23:59 AoE</p></html>' if 'aaai-27' in u else b'<html><p>Author registration is USD 500</p></html>',
                'http_status': 200,
            },
        )
        out = checker.check(dossier, bundle)
        self.assertEqual(out['claims'][0]['status'], 'same_host_redirect_year_mismatch_blocked')
        self.assertFalse(out['verification_passed'])
        self.assertEqual(out['source_text_status'], 'verification_blocked')
        self.assertTrue(out['blocking_source_issues'])

        # 2. Undated redirect to 2025 when edition is 2027 -> blocked!
        dossier_undated = self.dossier()
        bundle_undated = capture.capture_dossier(
            dossier_undated,
            transport=lambda u: {
                'final_url': 'https://conference.example/2025/cfp' if u.endswith('/cfp') else u,
                'content_type': 'text/html',
                'body': b'<html><p>Full papers: March 1, 2027, 23:59 AoE</p></html>' if u.endswith('/cfp') else b'<html><p>Author registration is USD 500</p></html>',
                'http_status': 200,
            },
        )
        out_undated = checker.check(dossier_undated, bundle_undated)
        self.assertEqual(out_undated['claims'][0]['status'], 'same_host_redirect_year_mismatch_blocked')
        self.assertFalse(out_undated['verification_passed'])

        # 3. JS-rendered pricing page WITH matching nav/cancellation quote -> blocked!
        dossier_js = self.dossier()
        dossier_js['evidence_claims'][1]['quote'] = '$100 USD'
        js_pricing = (
            b'<html><body><p>Cancellation fee is $100 USD.</p>'
            b'<div id="earlyregistration"></div><i id="pricingSpinner"></i>'
            b'<script>function getpricing(){$.ajax({url:"/api"});}</script></body></html>'
        )
        bundle_js = capture.capture_dossier(
            dossier_js,
            transport=lambda u: {
                'final_url': u,
                'content_type': 'text/html',
                'body': js_pricing if u.endswith('/fees') else b'<html><p>Full papers: March 1, 2027, 23:59 AoE</p></html>',
                'http_status': 200,
            },
        )
        out_js = checker.check(dossier_js, bundle_js)
        self.assertEqual(out_js['claims'][1]['status'], 'unverified_dynamic_page')
        self.assertFalse(out_js['verification_passed'])
        self.assertEqual(out_js['source_text_status'], 'verification_blocked')

        # 4. Silent empty-value loophole: amount=None and full_paper=None with omitted evidence_claims
        dossier_silent = {
            'venue': 'Example Conference',
            'edition': '2027',
            'track': 'Research',
            'official_cfp_url': 'https://conference.example/cfp',
            'milestones': {'full_paper': None},
            'fees': [{
                'category': 'author_registration',
                'amount': None,
                'mandatory': True,
                'source_url': 'https://conference.example/fees',
            }],
            'evidence_claims': [],
        }
        bundle_silent = capture.capture_dossier(
            dossier_silent,
            transport=lambda u: {
                'final_url': u,
                'content_type': 'text/html',
                'body': js_pricing if u.endswith('/fees') else b'<html><body><div id="root"></div><script src="/app.js"></script></body></html>',
                'http_status': 200,
            },
        )
        out_silent = checker.check(dossier_silent, bundle_silent)
        self.assertFalse(out_silent['verification_passed'])
        self.assertEqual(out_silent['source_text_status'], 'verification_blocked')
        self.assertEqual(len(out_silent['blocking_source_issues']), 2)

        # 5. Anubis 202 claim status -> source_bot_blocked
        dossier_anubis = self.dossier()
        bundle_anubis = capture.capture_dossier(
            dossier_anubis,
            transport=lambda u: {
                'final_url': u,
                'content_type': 'text/html',
                'body': b'<html><script id="anubis_challenge"></script></html>',
                'http_status': 202,
            },
        )
        out_anubis = checker.check(dossier_anubis, bundle_anubis)
        self.assertEqual(out_anubis['claims'][0]['status'], 'source_bot_blocked')
        self.assertEqual(out_anubis['source_text_status'], 'verification_blocked')

    # --- check_venue_plan.py source_bundle & --sources gating ---

    def test_check_venue_plan_blocks_unverified_and_stale_sources(self):
        base = json.loads((ROOT / 'research-scientist/references/venue-dossier.schema-example.json').read_text())
        now_iso = datetime.now(timezone.utc).isoformat()
        base['checked_at'] = now_iso
        for item in base['fees']:
            if item['mandatory']:
                item['amount'] = 50
                item['checked_at'] = now_iso

        # Clean source bundle allows within_budget=True and cfp_verified=True
        clean_bundle = capture.capture_dossier(
            base,
            transport=lambda u: {
                'final_url': u,
                'content_type': 'text/html',
                'body': b'<html><p>Static official venue info 2027 fee USD 50</p></html>',
                'http_status': 200,
            },
        )
        now = datetime.now(timezone.utc) + timedelta(seconds=5)
        clean_res = planner.check(base, as_of=now, source_bundle=clean_bundle)
        self.assertTrue(clean_res['within_budget'])
        self.assertTrue(clean_res['cfp_verified'])
        self.assertEqual(clean_res['source_issues'], [])

        # JS-rendered fee source blocks within_budget=True even with amount=0
        base_zero = json.loads(json.dumps(base))
        for item in base_zero['fees']:
            item['amount'] = 0
        js_bundle = json.loads(json.dumps(clean_bundle))
        fee_url = base_zero['fees'][0]['source_url']
        for src in js_bundle['sources']:
            if src['requested_url'] == fee_url:
                src['js_rendered_suspected'] = True
                src['unverified_dynamic_page'] = True
                src['js_rendered_signals'] = ['empty_pricing_container:earlyregistration']
        js_res = planner.check(base_zero, as_of=now, source_bundle=js_bundle)
        self.assertIsNone(js_res['within_budget'])
        self.assertEqual(js_res['verified_known_lower_bound'], 0)
        self.assertIn(base_zero['fees'][0]['name'], js_res['unverified_fee_evidence'])
        self.assertTrue(any('fee_source_unverified_dynamic_page' in w for w in js_res['warnings']))
        self.assertTrue(js_res['source_issues'])

        # Year-mismatched CFP source blocks backward_schedule and cfp_verified
        cfp_mismatch_bundle = json.loads(json.dumps(clean_bundle))
        for src in cfp_mismatch_bundle['sources']:
            if src['requested_url'] == base_zero['official_cfp_url']:
                src['same_host_path_redirect_year_mismatch'] = True
                src['final_url'] = 'https://example.org/2025/cfp'
        cfp_res = planner.check(base_zero, as_of=now, source_bundle=cfp_mismatch_bundle)
        self.assertFalse(cfp_res['cfp_verified'])
        self.assertIn('cfp_source_redirect_year_mismatch', cfp_res['warnings'])
        self.assertEqual(cfp_res['backward_schedule']['status'], 'cfp_source_unverified_or_year_mismatch')

    # --- CLI exit codes ---

    def test_cli_exit_codes_across_all_three_scripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            # Full-pass dossier + clean bundle -> check_venue_sources exit 0, check_venue_plan exit 0
            full_dossier = json.loads((ROOT / 'research-scientist/references/venue-dossier.schema-example.json').read_text())
            now_iso = datetime.now(timezone.utc).isoformat()
            full_dossier['checked_at'] = now_iso
            for item in full_dossier['fees']:
                item['amount'] = 50
                if item.get('mandatory'):
                    item['checked_at'] = now_iso
            full_dossier['evidence_claims'] = [
                {'field': 'venue', 'source_url': full_dossier['official_cfp_url'], 'quote': full_dossier['venue']},
                {'field': 'edition', 'source_url': full_dossier['official_cfp_url'], 'quote': full_dossier['edition']},
                {'field': 'track', 'source_url': full_dossier['official_cfp_url'], 'quote': full_dossier['track']},
                {'field': 'milestones.abstract_registration', 'source_url': full_dossier['official_cfp_url'], 'quote': 'Abstracts Jan 29'},
                {'field': 'milestones.full_paper', 'source_url': full_dossier['official_cfp_url'], 'quote': 'Full papers Feb 5'},
            ] + [
                {'field': f"fees.{item['category']}", 'source_url': item['source_url'], 'quote': 'Fee USD 50'}
                for item in full_dossier['fees'] if item['mandatory']
            ]
            clean_bundle = capture.capture_dossier(
                full_dossier,
                transport=lambda u: {
                    'final_url': u,
                    'content_type': 'text/html',
                    'body': (
                        f"<html><p>{full_dossier['venue']} {full_dossier['edition']} {full_dossier['track']} "
                        f"Abstracts Jan 29 Full papers Feb 5 Fee USD 50</p></html>"
                    ).encode('utf-8'),
                    'http_status': 200,
                },
            )
            dossier_path = tmp_dir / 'dossier.json'
            bundle_path = tmp_dir / 'bundle.json'
            blocked_bundle_path = tmp_dir / 'blocked_bundle.json'
            bad_json_path = tmp_dir / 'bad.json'

            dossier_path.write_text(json.dumps(full_dossier), encoding='utf-8')
            bundle_path.write_text(json.dumps(clean_bundle), encoding='utf-8')
            blocked = json.loads(json.dumps(clean_bundle))
            blocked['sources'][0]['same_host_path_redirect_year_mismatch'] = True
            blocked_bundle_path.write_text(json.dumps(blocked), encoding='utf-8')
            bad_json_path.write_text('{not valid json', encoding='utf-8')

            p_ok = subprocess.run(
                [sys.executable, str(SCRIPTS / 'check_venue_sources.py'), str(dossier_path), str(bundle_path)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(p_ok.returncode, 0, p_ok.stdout + p_ok.stderr)
            self.assertTrue(json.loads(p_ok.stdout)['verification_passed'])

            p_block = subprocess.run(
                [sys.executable, str(SCRIPTS / 'check_venue_sources.py'), str(dossier_path), str(blocked_bundle_path)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(p_block.returncode, 1)
            self.assertFalse(json.loads(p_block.stdout)['verification_passed'])

            p_bad = subprocess.run(
                [sys.executable, str(SCRIPTS / 'check_venue_sources.py'), str(bad_json_path), str(bundle_path)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(p_bad.returncode, 2)

            plan_ok = subprocess.run(
                [sys.executable, str(SCRIPTS / 'check_venue_plan.py'), str(dossier_path), '--sources', str(bundle_path)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(plan_ok.returncode, 0, plan_ok.stdout + plan_ok.stderr)

            plan_block = subprocess.run(
                [sys.executable, str(SCRIPTS / 'check_venue_plan.py'), str(dossier_path), '--sources', str(blocked_bundle_path)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(plan_block.returncode, 1)
            self.assertTrue(json.loads(plan_block.stdout)['source_issues'])

            plan_bad = subprocess.run(
                [sys.executable, str(SCRIPTS / 'check_venue_plan.py'), str(bad_json_path)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(plan_bad.returncode, 2)

            cap_bad = subprocess.run(
                [sys.executable, str(SCRIPTS / 'capture_venue_sources.py'), str(bad_json_path)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(cap_bad.returncode, 2)

    # --- Upstream fetch_cfp.py & dblp_venue_lookup.py integration ---

    def test_gzip_decompression_and_429_retry_in_fetch(self):
        html = b'<html><body><p>ICML 2027 Call For Papers</p></body></html>'
        gz_body = gzip.compress(html)
        calls = {'count': 0}

        def route(req):
            calls['count'] += 1
            if calls['count'] == 1:
                return {'status': 429, 'headers': {'Retry-After': '0'}, 'body': b'rate limited'}
            return {
                'status': 200,
                'headers': {'Content-Type': 'text/html; charset=utf-8', 'Content-Encoding': 'gzip'},
                'body': gz_body,
            }

        opener_factory = _make_fake_https_opener({'https://conf.example/cfp': route})
        res = capture.fetch('https://conf.example/cfp', opener_factory=opener_factory, max_retries=2)
        self.assertEqual(calls['count'], 2)
        self.assertEqual(res['body'], html)

        bad_gz_factory = _make_fake_https_opener({
            'https://conf.example/badgz': {
                'status': 200,
                'headers': {'Content-Type': 'text/html', 'Content-Encoding': 'gzip'},
                'body': b'not-valid-gzip',
            },
        })
        with self.assertRaisesRegex(RuntimeError, 'gzip_decompression_failed'):
            capture.fetch('https://conf.example/badgz', opener_factory=bad_gz_factory)

    def test_cfp_text_extractor_and_signals(self):
        html = (
            '<html><head><title>Ignored Head</title></head><body>'
            '<h1>ICML 2027 Call For Papers</h1>'
            '<ul><li>Full paper deadline: January 28, 2027 AoE</li>'
            '<li>8 pages main paper; unlimited references and appendices</li></ul>'
            '<p>Submit via <a href="https://openreview.net/group?id=ICML.cc/2027/Conference">OpenReview</a></p>'
            '</body></html>'
        )
        structured, links = capture.to_structured_text(html)
        self.assertIn('# ICML 2027 Call For Papers', structured)
        self.assertIn('[https://openreview.net/group?id=ICML.cc/2027/Conference]', structured)
        signals = capture.extract_cfp_signals(structured, html, links)
        self.assertEqual(signals['verification_status'], 'candidate_extracted_unverified')
        self.assertIn('AoE', signals['timezones'])
        self.assertIn('openreview', signals['submission_systems'])
        self.assertTrue(signals['deadlines'])
        self.assertTrue(signals['page_limits'])

    def test_dblp_lookup_handles_ok_anubis_202_429_and_unreachable_without_exit(self):
        venue_ok = capture.lookup_dblp_venue(
            'ICML',
            transport=lambda u: {
                'http_status': 200,
                'body': json.dumps({
                    'result': {'hits': {'hit': [{'info': {
                        'venue': 'International Conference on Machine Learning',
                        'acronym': 'ICML',
                        'type': 'Conference and Workshop Papers',
                        'url': 'https://dblp.org/db/conf/icml/',
                    }}]}}
                }).encode('utf-8'),
            },
        )
        self.assertEqual(venue_ok['status'], 'ok')
        self.assertEqual(venue_ok['results'][0]['dblp_key'], 'conf/icml')

        toc_ok = capture.lookup_dblp_toc_count(
            'conf/icml',
            2025,
            transport=lambda u: {
                'http_status': 200,
                'body': json.dumps({'result': {'hits': {'@total': '2468'}}}).encode('utf-8'),
            },
        )
        self.assertEqual(toc_ok['status'], 'ok')
        self.assertEqual(toc_ok['paper_count'], 2468)

        anubis = capture.lookup_dblp_venue(
            'ICML',
            transport=lambda u: {
                'http_status': 202,
                'body': b'<html><title>Making sure you&#39;re not a bot!</title><script id="anubis_challenge"></script></html>',
            },
        )
        self.assertEqual(anubis['status'], 'bot_blocked')
        self.assertEqual(anubis['http_status'], 202)
        self.assertEqual(anubis['results'], [])

        rate_lim = capture.lookup_dblp_toc_count(
            'conf/icml',
            2025,
            transport=lambda u: {'http_status': 429, 'body': b'Too Many Requests'},
        )
        self.assertEqual(rate_lim['status'], 'rate_limited')
        self.assertIsNone(rate_lim['paper_count'])

        def boom(u):
            raise OSError('connection refused')

        unreachable = capture.lookup_dblp_venue('ICML', transport=boom)
        self.assertEqual(unreachable['status'], 'unreachable')
        self.assertEqual(unreachable['results'], [])

    # --- Iteration 2 remediation tests: SSR Next.js, parity, edition-year, schema, JS tables, CFP, DBLP, F20 ---

    def test_ssr_nextjs_react_vue_false_positive_prevention(self):
        # Bug 1A: concise (<200 chars) SSR Next.js page with static fee table + prose
        concise_ssr = (
            '<html><body><div id="__next"><main><h1>NeurIPS 2027 Registration Fees</h1>'
            '<table><thead><tr><th>Category</th><th>Fee</th></tr></thead>'
            '<tbody><tr><td>Author</td><td>$650 USD</td></tr><tr><td>Student</td><td>$350 USD</td></tr></tbody></table>'
            '<p>Full author registration due May 1, 2027 AoE.</p></main></div>'
            '<script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{}}}</script>'
            '<script src="/_next/static/chunks/main.js"></script></body></html>'
        )
        # Bug 1B: SSR Next.js/Vue page with boilerplate <noscript> (both concise with table and >=400 chars)
        ssr_concise_noscript = (
            concise_ssr.replace('</body>', '<noscript>You need to enable JavaScript to run this app.</noscript></body>')
        )
        long_prose = ' '.join(['ICLR 2027 Main Track full paper submission deadline October 1, 2026 AoE. Author registration $500 USD.'] * 6)
        ssr_long_noscript = (
            f'<html><body><div id="app"><main>{long_prose}</main></div>'
            f'<noscript>Please enable JavaScript to run this app.</noscript>'
            f'<script src="/assets/bundle.js"></script></body></html>'
        )
        for name, html in (
            ('concise_ssr_next', concise_ssr),
            ('ssr_concise_noscript', ssr_concise_noscript),
            ('ssr_long_noscript', ssr_long_noscript),
        ):
            with self.subTest(case=name):
                snap = capture.capture_url(
                    'https://neurips.cc/Conferences/2027/Pricing',
                    transport=lambda u, h=html: {
                        'final_url': u,
                        'content_type': 'text/html; charset=utf-8',
                        'body': h.encode('utf-8'),
                        'http_status': 200,
                    },
                )
                self.assertFalse(snap['js_rendered_suspected'], f'{name} FP: {snap["js_rendered_signals"]}')
                self.assertFalse(snap['unverified_dynamic_page'])

        # Control: empty SPA mount with <noscript> MUST still trigger
        empty_next_noscript = (
            '<html><body><div id="__next"></div>'
            '<noscript>You need to enable JavaScript to run this app.</noscript>'
            '<script src="/_next/static/chunks/main.js"></script></body></html>'
        )
        ctrl = capture.capture_url(
            'https://neurips.cc/Conferences/2027/Pricing',
            transport=lambda u: {
                'final_url': u,
                'content_type': 'text/html',
                'body': empty_next_noscript.encode('utf-8'),
                'http_status': 200,
            },
        )
        self.assertTrue(ctrl['js_rendered_suspected'])
        self.assertIn('noscript_requires_js', ctrl['js_rendered_signals'])

    def test_check_venue_sources_parity_on_missing_failed_hijacked_stale_urls(self):
        base_dossier = {
            'venue': 'AAAI',
            'edition': 'AAAI 2027',
            'track': 'Main',
            'official_cfp_url': 'https://aaai.org/aaai-27/cfp',
            'checked_at': '2026-11-21T00:00:00Z',
            'user_timezone': 'UTC',
            'currency': 'USD',
            'budget': 2000,
            'budget_currency': 'USD',
            'presentation_mode': 'online',
            'milestones': {'abstract_registration': None, 'full_paper': None},
            'fees': [
                {'name': 'submission', 'category': 'submission', 'mandatory': True, 'amount': 0,
                 'source_url': 'https://clean.org/info', 'checked_at': '2026-11-21T00:00:00Z'},
                {'name': 'publication', 'category': 'publication', 'mandatory': True, 'amount': 0,
                 'source_url': 'https://clean.org/info', 'checked_at': '2026-11-21T00:00:00Z'},
                {'name': 'author_registration', 'category': 'author_registration', 'mandatory': True, 'amount': None,
                 'source_url': 'https://neurips.cc/Pricing-broken', 'checked_at': '2026-11-21T00:00:00Z'},
                {'name': 'overlength', 'category': 'overlength', 'mandatory': False, 'amount': 0},
                {'name': 'tax', 'category': 'tax', 'mandatory': False, 'amount': 0},
            ],
            'evidence_claims': [
                {'field': 'venue', 'source_url': 'https://clean.org/info', 'quote': 'AAAI'},
                {'field': 'edition', 'source_url': 'https://clean.org/info', 'quote': '2027'},
                {'field': 'track', 'source_url': 'https://clean.org/info', 'quote': 'Main'},
                {'field': 'fees.submission', 'source_url': 'https://clean.org/info', 'quote': 'free'},
                {'field': 'fees.publication', 'source_url': 'https://clean.org/info', 'quote': 'free'},
            ],
        }
        now = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)

        def make_snap(url, **kw):
            snap = {
                'requested_url': url,
                'final_url': kw.get('final_url', url),
                'fetched_at_utc': now.isoformat(),
                'http_status': 200,
                'content_type': 'text/html',
                'sha256': 'abc123',
                'bytes': 64,
                'redirect_chain': [],
                'redirected_to_different_host': False,
                'same_host_path_redirect_year_mismatch': False,
                'same_host_path_redirect_year_mismatch_details': None,
                'requested_url_years': [],
                'final_url_years': [],
                'js_rendered_suspected': False,
                'unverified_dynamic_page': False,
                'js_rendered_signals': [],
                'extraction_status': 'html_text_extracted',
                'text': 'AAAI 2027 Main track free',
            }
            snap.update(kw)
            return snap

        # 1. Parity: fetch_failed official_cfp_url + cross-host hijacked mandatory fee
        bundle_fail_hijack = {
            'format': 'research_scientist_venue_sources_v1',
            'sources': [
                make_snap('https://clean.org/info'),
                make_snap('https://aaai.org/aaai-27/cfp', extraction_status='fetch_failed', text='', error='http_500'),
                make_snap('https://neurips.cc/Pricing-broken', final_url='https://evil.org/phish', redirected_to_different_host=True),
            ],
        }
        res_src = checker.check(base_dossier, bundle_fail_hijack, as_of=now)
        res_plan = planner.check(base_dossier, as_of=now, source_bundle=bundle_fail_hijack)
        self.assertFalse(res_src['verification_passed'])
        self.assertEqual(res_src['source_text_status'], 'verification_blocked')
        src_issues = {item['issue'] for item in res_src['blocking_source_issues']}
        self.assertIn('source_text_unavailable', src_issues)
        self.assertIn('redirected_to_different_host', src_issues)
        self.assertTrue(res_plan['source_issues'])

        # 2. Missing snapshots for official_cfp_url and mandatory fee URL
        bundle_missing = {
            'format': 'research_scientist_venue_sources_v1',
            'sources': [make_snap('https://clean.org/info')],
        }
        res_missing = checker.check(base_dossier, bundle_missing, as_of=now)
        self.assertFalse(res_missing['verification_passed'])
        self.assertEqual(res_missing['source_text_status'], 'verification_blocked')
        self.assertEqual(
            [i['issue'] for i in res_missing['blocking_source_issues']],
            ['source_snapshot_missing', 'source_snapshot_missing'],
        )

        # 3. Stale (>30 days) official_cfp_url and mandatory fee URL omitted from evidence_claims
        old_iso = (now - timedelta(days=60)).isoformat()
        bundle_stale = {
            'format': 'research_scientist_venue_sources_v1',
            'sources': [
                make_snap('https://clean.org/info'),
                make_snap('https://aaai.org/aaai-27/cfp', fetched_at_utc=old_iso),
                make_snap('https://neurips.cc/Pricing-broken', fetched_at_utc=old_iso),
            ],
        }
        res_stale = checker.check(base_dossier, bundle_stale, as_of=now)
        self.assertFalse(res_stale['verification_passed'])
        self.assertEqual(res_stale['source_text_status'], 'verification_blocked')
        self.assertEqual(
            [i['issue'] for i in res_stale['blocking_source_issues']],
            ['source_snapshot_stale_or_undated', 'source_snapshot_stale_or_undated'],
        )

    def test_edition_2digit_non_redirected_stale_url_and_title_space_year(self):
        # Title/H1 space-separated venue year vs common English words
        self.assertEqual(
            capture._extract_title_h1_years('<title>AAAI 25 Registration</title>'),
            [2025],
        )
        self.assertEqual(
            capture._extract_title_h1_years('<title>Top 25 NLP Papers on February 25</title>'),
            [],
        )
        mismatch, _ = capture.detect_same_host_path_redirect_year_mismatch(
            'https://aaai.org/aaai-27/',
            'https://aaai.org/registration/',
            None,
            '<html><head><title>AAAI 25 Registration</title></head></html>',
        )
        self.assertTrue(mismatch)

        now = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
        # 2-digit edition "AAAI-27" with undated->dated redirect to 2025
        dossier_2d = self.dossier()
        dossier_2d['venue'] = 'AAAI'
        dossier_2d['edition'] = 'AAAI-27'
        dossier_2d['official_cfp_url'] = 'https://aaai.org/cfp'
        dossier_2d['evidence_claims'] = [
            {'field': 'venue', 'source_url': 'https://aaai.org/cfp', 'quote': 'AAAI'},
            {'field': 'edition', 'source_url': 'https://aaai.org/cfp', 'quote': 'AAAI'},
            {'field': 'track', 'source_url': 'https://aaai.org/cfp', 'quote': 'Research'},
            {'field': 'milestones.full_paper', 'source_url': 'https://aaai.org/cfp', 'quote': 'March 1, 2027'},
            {'field': 'fees.author_registration', 'source_url': 'https://conference.example/fees', 'quote': 'USD 500'},
        ]
        bundle_2d = {
            'format': 'research_scientist_venue_sources_v1',
            'sources': [
                {
                    'requested_url': 'https://aaai.org/cfp',
                    'final_url': 'https://aaai.org/2025/cfp',
                    'fetched_at_utc': now.isoformat(),
                    'extraction_status': 'html_text_extracted',
                    'text': 'AAAI Research March 1, 2027',
                },
                {
                    'requested_url': 'https://conference.example/fees',
                    'final_url': 'https://conference.example/fees',
                    'fetched_at_utc': now.isoformat(),
                    'extraction_status': 'html_text_extracted',
                    'text': 'Author registration USD 500',
                },
            ],
        }
        out_2d = checker.check(dossier_2d, bundle_2d, as_of=now)
        self.assertEqual(out_2d['claims'][0]['status'], 'same_host_redirect_year_mismatch_blocked')
        self.assertFalse(out_2d['verification_passed'])

        # Non-redirected stale URL: requested_url == final_url == https://aaai.org/2025/cfp
        dossier_nonred = json.loads(json.dumps(dossier_2d))
        dossier_nonred['edition'] = 'AAAI 2027'
        dossier_nonred['official_cfp_url'] = 'https://aaai.org/2025/cfp'
        for c in dossier_nonred['evidence_claims']:
            if c['source_url'] == 'https://aaai.org/cfp':
                c['source_url'] = 'https://aaai.org/2025/cfp'
        bundle_nonred = json.loads(json.dumps(bundle_2d))
        bundle_nonred['sources'][0]['requested_url'] = 'https://aaai.org/2025/cfp'
        bundle_nonred['sources'][0]['final_url'] = 'https://aaai.org/2025/cfp'
        out_nonred = checker.check(dossier_nonred, bundle_nonred, as_of=now)
        self.assertEqual(out_nonred['claims'][0]['status'], 'same_host_redirect_year_mismatch_blocked')
        self.assertFalse(out_nonred['verification_passed'])

        # Hand-crafted undated redirect (/aaai-27/ -> /registration/) with text='AAAI-25 Registration'
        dossier_hc = json.loads(json.dumps(dossier_2d))
        dossier_hc['official_cfp_url'] = 'https://aaai.org/aaai-27/'
        for c in dossier_hc['evidence_claims']:
            if c['source_url'] == 'https://aaai.org/cfp':
                c['source_url'] = 'https://aaai.org/aaai-27/'
        bundle_hc = json.loads(json.dumps(bundle_2d))
        bundle_hc['sources'][0]['requested_url'] = 'https://aaai.org/aaai-27/'
        bundle_hc['sources'][0]['final_url'] = 'https://aaai.org/registration/'
        bundle_hc['sources'][0]['text'] = 'AAAI-25 Registration AAAI Research March 1, 2027'
        out_hc = checker.check(dossier_hc, bundle_hc, as_of=now)
        self.assertEqual(out_hc['claims'][0]['status'], 'same_host_redirect_year_mismatch_blocked')
        self.assertFalse(out_hc['verification_passed'])

        # Also verify check_venue_plan catches non-redirected stale URL & hand-crafted undated redirect
        dossier_plan = json.loads((ROOT / 'research-scientist/references/venue-dossier.schema-example.json').read_text())
        dossier_plan['edition'] = 'AAAI-27'
        dossier_plan['official_cfp_url'] = 'https://aaai.org/2025/cfp'
        bundle_plan = {
            'format': 'research_scientist_venue_sources_v1',
            'sources': [
                {
                    'requested_url': 'https://aaai.org/2025/cfp',
                    'final_url': 'https://aaai.org/2025/cfp',
                    'fetched_at_utc': now.isoformat(),
                    'extraction_status': 'html_text_extracted',
                    'text': 'AAAI 2025 CFP',
                },
                {
                    'requested_url': 'https://example.org/fictional-fees',
                    'final_url': 'https://example.org/fictional-fees',
                    'fetched_at_utc': now.isoformat(),
                    'extraction_status': 'html_text_extracted',
                    'text': 'Fees',
                },
            ],
        }
        plan_res = planner.check(dossier_plan, as_of=now, source_bundle=bundle_plan)
        self.assertFalse(plan_res['cfp_verified'])
        self.assertTrue(any(i['issue'] == 'same_host_path_redirect_year_mismatch' for i in plan_res['source_issues']))

    def test_cli_exit_code_2_on_invalid_bundle_schema_field_types(self):
        dossier = json.loads((ROOT / 'research-scientist/references/venue-dossier.schema-example.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            dp = tmp_dir / 'dossier.json'
            dp.write_text(json.dumps(dossier), encoding='utf-8')
            for label, bad_field in (('redirect_chain_int', {'redirect_chain': 123}), ('final_url_int', {'final_url': 123})):
                bp = tmp_dir / f'{label}.json'
                bad_bundle = {
                    'format': 'research_scientist_venue_sources_v1',
                    'sources': [{
                        'requested_url': dossier['official_cfp_url'],
                        'final_url': dossier['official_cfp_url'],
                        'fetched_at_utc': '2026-11-21T00:00:00Z',
                        'extraction_status': 'html_text_extracted',
                        'text': 'Fictional Conference Z',
                        **bad_field,
                    }],
                }
                bp.write_text(json.dumps(bad_bundle), encoding='utf-8')
                for script, cli_args in (
                    ('check_venue_sources.py', [str(dp), str(bp)]),
                    ('check_venue_plan.py', [str(dp), '--sources', str(bp)]),
                ):
                    with self.subTest(case=label, script=script):
                        proc = subprocess.run(
                            [sys.executable, str(SCRIPTS / script), *cli_args],
                            capture_output=True, text=True, check=False,
                        )
                        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
                        err_obj = json.loads(proc.stderr)
                        self.assertIn('error', err_obj)

    def test_thead_empty_tbody_loading_container_and_calculator_detection(self):
        nav_padding = ' '.join(['ICML 2027 Navigation Menu Policies Code of Conduct Travel Grants.'] * 18)
        thead_empty_tbody = (
            f'<html><body><nav>{nav_padding}</nav>'
            '<table class="table"><thead><tr><th>Category</th><th>Early Bird</th><th>Regular</th><th>Late</th></tr></thead>'
            '<tbody id="fees-body"></tbody></table>'
            '<script>fetch("/api/v1/fees").then(r => r.json());</script></body></html>'
        )
        verbose_loading_div = (
            f'<html><body><nav>{nav_padding}</nav>'
            '<div id="earlyregistration"><span>Loading early registration rates from server...</span></div>'
            '<script>fetch("/api/pricing");</script></body></html>'
        )
        calc_variant = (
            '<html><body><p>Select your registration tier to view exact fees.</p>'
            '<script src="/calc.js"></script></body></html>'
        )
        for name, html, expected_sig in (
            ('thead_empty_tbody', thead_empty_tbody, 'empty_table_with_scripts'),
            ('verbose_loading_div', verbose_loading_div, 'empty_pricing_container:earlyregistration'),
            ('calc_variant', calc_variant, 'dynamic_calculator_placeholder'),
        ):
            with self.subTest(case=name):
                snap = capture.capture_url(
                    'https://icml.cc/Conferences/2027/Pricing',
                    transport=lambda u, h=html: {
                        'final_url': u,
                        'content_type': 'text/html',
                        'body': h.encode('utf-8'),
                        'http_status': 200,
                    },
                )
                self.assertTrue(snap['js_rendered_suspected'])
                self.assertIn(expected_sig, snap['js_rendered_signals'])

    def test_cfp_text_extractor_strikethrough_tables_urls_and_headings(self):
        html = (
            '<html><body>'
            '<h3>Submission Portals</h3>'
            '<p>Submit to https://easychair.org/my/conference?conf=icml2027 or '
            '<a href="https://openreview.net/venue?id=NeurIPS.cc/2027/Conference">OpenReview</a> or '
            'https://acl2027.org/hotcrp</p>'
            '<table>'
            '<tr><th>Milestone</th><th>Date</th></tr>'
            '<tr><td>Full Paper</td><td><s>January 15, 2027 AoE</s> January 22, 2027 (Extended) AoE</td></tr>'
            '<tr><td>Cancelled</td><td><del>Abstract deadline: January 1, 2027 AoE</del></td></tr>'
            '</table>'
            '<ul><li><strike>Old deadline: December 20, 2026 AoE</strike></li></ul>'
            '</body></html>'
        )
        structured, links = capture.to_structured_text(html)
        self.assertIn('~~January 15, 2027 AoE~~', structured)
        self.assertIn('~~Abstract deadline: January 1, 2027 AoE~~', structured)
        self.assertIn('~~Old deadline: December 20, 2026 AoE~~', structured)
        self.assertIn('| Milestone | Date |', structured)
        self.assertNotIn('| | Milestone', structured)

        signals = capture.extract_cfp_signals(structured, html, links)
        self.assertIn('easychair', signals['submission_systems'])
        self.assertIn('openreview', signals['submission_systems'])
        self.assertIn('hotcrp', signals['submission_systems'])
        deadlines_joined = '\n'.join(signals['deadlines'])
        self.assertIn('January 22, 2027', deadlines_joined)
        self.assertNotIn('January 15, 2027', deadlines_joined)
        self.assertNotIn('January 1, 2027', deadlines_joined)
        self.assertNotIn('December 20, 2026', deadlines_joined)
        self.assertNotIn('Submission Portals', deadlines_joined)

    def test_dblp_gzip_202_malformed_json_403_anubis_and_clean_help(self):
        # 1. Gzip-compressed HTTPError(202) Anubis challenge in _dblp_fetch_json via urllib
        anubis_gz = gzip.compress(
            b'<html><title>Making sure you&#39;re not a bot!</title>'
            b'<script id="anubis_challenge"></script></html>'
        )
        routes = {
            'https://dblp.org/search/venue/api?q=AAAI&format=json&h=10': {
                'status': 202,
                'headers': {'Content-Type': 'text/html', 'Content-Encoding': 'gzip'},
                'body': anubis_gz,
            },
        }
        # Test _dblp_fetch_json directly with FakeHTTPSHandler wrapped into urllib
        # by temporarily using _make_fake_https_opener via monkeypatch-style build_opener
        orig_build_opener = capture.build_opener
        try:
            fake_factory = _make_fake_https_opener(routes)
            capture.build_opener = lambda handler: fake_factory(handler)
            res = capture.lookup_dblp_venue('AAAI')
            self.assertEqual(res['status'], 'bot_blocked')
            self.assertEqual(res['http_status'], 202)
            self.assertEqual(res['reason'], 'anubis_challenge')
        finally:
            capture.build_opener = orig_build_opener

        # 2. Malformed DBLP 200 JSON responses return source_failed cleanly
        for bad_payload in (b'{"result": null}', b'[]', b'{"result": {"hits": "bad"}}'):
            bad_res = capture.lookup_dblp_venue(
                'NeurIPS',
                transport=lambda u, p=bad_payload: {'http_status': 200, 'body': p},
            )
            self.assertEqual(bad_res['status'], 'source_failed')
            self.assertEqual(bad_res['results'], [])

        bad_toc = capture.lookup_dblp_toc_count(
            'conf/neurips',
            2025,
            transport=lambda u: {'http_status': 200, 'body': b'{"result": {"hits": {"@total": "nan"}}}'},
        )
        self.assertEqual(bad_toc['status'], 'source_failed')
        self.assertIsNone(bad_toc['paper_count'])

        # 3. 403 / 503 Anubis in capture_url classified as bot_blocked_anubis
        for code in (403, 503):
            snap = capture.capture_url(
                'https://dblp.org/db/conf/iclr/',
                transport=lambda u, c=code: {
                    'final_url': u,
                    'content_type': 'text/html',
                    'body': b'<html><script id="anubis_challenge"></script></html>',
                    'http_status': c,
                },
            )
            self.assertEqual(snap['extraction_status'], 'bot_blocked_anubis')
            self.assertEqual(snap['http_status'], code)

        # 4. --help renders cleanly without raw # comment lines
        for script in ('capture_venue_sources.py', 'check_venue_sources.py', 'check_venue_plan.py'):
            help_res = subprocess.run(
                [sys.executable, str(SCRIPTS / script), '--help'],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(help_res.returncode, 0, help_res.stderr)
            self.assertFalse(
                any(line.lstrip().startswith('#') for line in help_res.stdout.splitlines()),
                f'{script} --help contained raw # comment lines:\n{help_res.stdout}',
            )

    def test_f20_compact_out_and_artifacts_dir_across_all_three_scripts(self):
        import os

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            artifacts_dir = tmp_dir / 'artifacts'
            dossier = json.loads((ROOT / 'research-scientist/references/venue-dossier.schema-example.json').read_text())
            now_iso = datetime.now(timezone.utc).isoformat()
            dossier['venue'] = 'ICML'
            dossier['edition'] = '2027'
            dossier['track'] = 'Main Track'
            dossier['checked_at'] = now_iso
            for fee in dossier['fees']:
                fee['amount'] = 400 if fee['category'] == 'author_registration' else 0
                if fee['mandatory']:
                    fee['checked_at'] = now_iso
            dossier['evidence_claims'] = [
                {'field': 'venue', 'source_url': dossier['official_cfp_url'], 'quote': 'ICML'},
                {'field': 'edition', 'source_url': dossier['official_cfp_url'], 'quote': '2027'},
                {'field': 'track', 'source_url': dossier['official_cfp_url'], 'quote': 'Main Track'},
                {'field': 'milestones.abstract_registration', 'source_url': dossier['official_cfp_url'], 'quote': 'Abstracts Jan 28'},
                {'field': 'milestones.full_paper', 'source_url': dossier['official_cfp_url'], 'quote': 'Full papers Feb 4'},
            ] + [
                {'field': f"fees.{fee['category']}", 'source_url': fee['source_url'], 'quote': 'Author registration USD 400'}
                for fee in dossier['fees'] if fee['mandatory']
            ]

            long_body = ('ICML 2027 Main Track Abstracts Jan 28 Full papers Feb 4 Author registration USD 400. ' + ('Details ' * 60)).encode('utf-8')
            # CLI subprocess test for capture_venue_sources.py --out --artifacts-dir --compact and --dblp-lookup --compact
            site_dir = tmp_dir / 'site'
            site_dir.mkdir()
            (site_dir / 'sitecustomize.py').write_text(
                "import io, json\n"
                "from email.message import Message\n"
                "from urllib.request import BaseHandler\n"
                "from urllib.response import addinfourl\n"
                "import urllib.request as ur\n"
                f"HTML_BODY = {repr(b'<html><body><p>' + long_body + b'</p></body></html>')}\n"
                "DBLP_VENUE = json.dumps({'result': {'hits': {'hit': [{'info': {'venue': 'ICML', 'acronym': 'ICML', 'type': 'Conference', 'url': 'https://dblp.org/db/conf/icml/'}}]}}}).encode()\n"
                "DBLP_TOC = json.dumps({'result': {'hits': {'@total': '1800'}}}).encode()\n"
                "class MockHTTPS(BaseHandler):\n"
                "    handler_order = 1\n"
                "    def https_open(self, req):\n"
                "        u = req.full_url\n"
                "        h = Message()\n"
                "        if 'dblp.org/search/venue/api' in u:\n"
                "            h['Content-Type'] = 'application/json'\n"
                "            r = addinfourl(io.BytesIO(DBLP_VENUE), h, u, 200)\n"
                "            r.msg = 'OK'\n"
                "            return r\n"
                "        if 'dblp.org/search/publ/api' in u:\n"
                "            h['Content-Type'] = 'application/json'\n"
                "            r = addinfourl(io.BytesIO(DBLP_TOC), h, u, 200)\n"
                "            r.msg = 'OK'\n"
                "            return r\n"
                "        h['Content-Type'] = 'text/html; charset=utf-8'\n"
                "        r = addinfourl(io.BytesIO(HTML_BODY), h, u, 200)\n"
                "        r.msg = 'OK'\n"
                "        return r\n"
                "_orig_build = ur.build_opener\n"
                "ur.build_opener = lambda *handlers: _orig_build(MockHTTPS(), *handlers)\n",
                encoding='utf-8',
            )
            env = dict(os.environ)
            env['PYTHONPATH'] = str(site_dir) + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')

            dp = tmp_dir / 'dossier.json'
            dp.write_text(json.dumps(dossier), encoding='utf-8')
            cli_bundle_path = tmp_dir / 'cli_out' / 'bundle.json'
            cli_art_dir = tmp_dir / 'cli_artifacts'
            cap_cli = subprocess.run(
                [sys.executable, str(SCRIPTS / 'capture_venue_sources.py'), str(dp),
                 '--out', str(cli_bundle_path), '--artifacts-dir', str(cli_art_dir), '--compact'],
                capture_output=True, text=True, env=env, check=False,
            )
            self.assertEqual(cap_cli.returncode, 0, cap_cli.stderr)
            self.assertTrue(cli_bundle_path.is_file())
            cli_compact = json.loads(cap_cli.stdout)
            self.assertEqual(cli_compact['format'], 'research_scientist_venue_sources_v1')
            self.assertEqual(cli_compact['bundle_path'], str(cli_bundle_path))
            self.assertEqual(cli_compact['artifacts_dir'], str(cli_art_dir))
            self.assertEqual(cli_compact['source_count'], 2)
            self.assertEqual(cli_compact['blocked_count'], 0)
            for csrc in cli_compact['sources']:
                self.assertNotIn('text', csrc)
                self.assertNotIn('text_preview', csrc)
                self.assertNotIn('structured_text', csrc)
                self.assertIn('text_chars', csrc)
                self.assertGreater(csrc['text_chars'], 0)
                self.assertTrue(Path(csrc['artifact_path']).is_file())
                self.assertTrue(Path(csrc['text_path']).is_file())

            # Auto-persist bundle_path when --compact is passed without --out and leak zero body prose
            cap_no_out = subprocess.run(
                [sys.executable, str(SCRIPTS / 'capture_venue_sources.py'), str(dp), '--compact'],
                capture_output=True, text=True, env=env, check=False,
            )
            self.assertEqual(cap_no_out.returncode, 0, cap_no_out.stderr)
            self.assertNotIn('Details Details', cap_no_out.stdout)
            no_out_compact = json.loads(cap_no_out.stdout)
            auto_bundle_path = Path(no_out_compact['bundle_path'])
            try:
                self.assertTrue(auto_bundle_path.is_file())
                auto_bundle = json.loads(auto_bundle_path.read_text(encoding='utf-8'))
                self.assertIn('Details Details', auto_bundle['sources'][0]['text'])
            finally:
                auto_bundle_path.unlink(missing_ok=True)
            for csrc in no_out_compact['sources']:
                self.assertNotIn('text', csrc)
                self.assertNotIn('text_preview', csrc)
                self.assertNotIn('structured_text', csrc)
                self.assertIn('text_chars', csrc)

            dblp_cli = subprocess.run(
                [sys.executable, str(SCRIPTS / 'capture_venue_sources.py'),
                 '--dblp-lookup', 'ICML', '--dblp-year', '2025', '--compact'],
                capture_output=True, text=True, env=env, check=False,
            )
            self.assertEqual(dblp_cli.returncode, 0, dblp_cli.stderr)
            dblp_compact = json.loads(dblp_cli.stdout)
            dblp_auto_path = Path(dblp_compact['bundle_path'])
            try:
                self.assertTrue(dblp_auto_path.is_file())
                self.assertEqual(dblp_compact['status'], 'ok')
                self.assertEqual(dblp_compact['result_count'], 1)
                self.assertEqual(dblp_compact['toc_count']['paper_count'], 1800)
            finally:
                dblp_auto_path.unlink(missing_ok=True)

            bundle = capture.capture_dossier(
                dossier,
                transport=lambda u: {
                    'final_url': u,
                    'content_type': 'text/html; charset=utf-8',
                    'body': b'<html><body><p>' + long_body + b'</p></body></html>',
                    'http_status': 200,
                },
                artifacts_dir=artifacts_dir,
            )
            self.assertEqual(len(bundle['sources']), 2)
            for src in bundle['sources']:
                self.assertTrue(Path(src['artifact_path']).is_file())
                self.assertTrue(Path(src['text_path']).is_file())
                self.assertIn('ICML 2027', Path(src['text_path']).read_text(encoding='utf-8'))

            bundle_path = tmp_dir / 'bundle.json'
            bundle_path.write_text(json.dumps(bundle), encoding='utf-8')
            compact_cap = capture._compact_capture_summary(
                bundle,
                bundle_path=str(bundle_path),
                artifacts_dir=str(artifacts_dir),
                has_dossier=True,
            )
            self.assertEqual(compact_cap['format'], 'research_scientist_venue_sources_v1')
            self.assertEqual(compact_cap['bundle_path'], str(bundle_path))
            self.assertEqual(compact_cap['artifacts_dir'], str(artifacts_dir))
            self.assertEqual(compact_cap['source_count'], 2)
            self.assertEqual(compact_cap['blocked_count'], 0)
            for csrc in compact_cap['sources']:
                self.assertNotIn('text', csrc)
                self.assertNotIn('text_preview', csrc)
                self.assertNotIn('structured_text', csrc)
                self.assertIn('text_chars', csrc)
                self.assertGreater(csrc['text_chars'], 0)
                self.assertTrue(csrc['artifact_path'])
                self.assertTrue(csrc['text_path'])

            # Compact DBLP summary helper
            compact_dblp = capture._compact_capture_summary(
                {'status': 'ok', 'query': 'ICLR', 'http_status': 200, 'results': [{'acronym': 'ICLR'}] * 8},
                bundle_path=str(tmp_dir / 'dblp.json'),
                has_dossier=False,
            )
            self.assertEqual(compact_dblp['result_count'], 8)
            self.assertEqual(len(compact_dblp['results']), 5)
            self.assertEqual(compact_dblp['bundle_path'], str(tmp_dir / 'dblp.json'))

            # CLI test for check_venue_sources.py --out --compact (pass and fail)
            chk_out = tmp_dir / 'reports' / 'chk_report.json'
            chk_proc = subprocess.run(
                [sys.executable, str(SCRIPTS / 'check_venue_sources.py'), str(dp), str(bundle_path),
                 '--out', str(chk_out), '--compact'],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(chk_proc.returncode, 0, chk_proc.stderr)
            self.assertTrue(chk_out.is_file())
            full_chk = json.loads(chk_out.read_text(encoding='utf-8'))
            self.assertIn('claims', full_chk)
            compact_chk = json.loads(chk_proc.stdout)
            self.assertTrue(compact_chk['verification_passed'])
            self.assertEqual(compact_chk['report_path'], str(chk_out))
            self.assertEqual(compact_chk['claim_counts']['failed'], 0)
            self.assertEqual(compact_chk['failed_claims'], [])
            self.assertNotIn('claims', compact_chk)

            # Failing check_venue_sources --compact preserves exit code 1 and populates failed_claims
            bad_bundle = json.loads(json.dumps(bundle))
            bad_bundle['sources'][0]['js_rendered_suspected'] = True
            bad_bundle['sources'][0]['unverified_dynamic_page'] = True
            bad_bundle_path = tmp_dir / 'bad_bundle.json'
            bad_bundle_path.write_text(json.dumps(bad_bundle), encoding='utf-8')
            chk_fail = subprocess.run(
                [sys.executable, str(SCRIPTS / 'check_venue_sources.py'), str(dp), str(bad_bundle_path), '--compact'],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(chk_fail.returncode, 1)
            compact_fail = json.loads(chk_fail.stdout)
            self.assertFalse(compact_fail['verification_passed'])
            self.assertTrue(compact_fail['failed_claims'])
            self.assertTrue(compact_fail['blocking_source_issues'])
            chk_auto_report = Path(compact_fail['report_path'])
            try:
                self.assertTrue(chk_auto_report.is_file())
            finally:
                chk_auto_report.unlink(missing_ok=True)

            # CLI test for check_venue_plan.py --out --compact (pass and blocked exit 1)
            plan_out = tmp_dir / 'reports' / 'plan_report.json'
            plan_proc = subprocess.run(
                [sys.executable, str(SCRIPTS / 'check_venue_plan.py'), str(dp), '--sources', str(bundle_path),
                 '--out', str(plan_out), '--compact'],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(plan_proc.returncode, 0, plan_proc.stderr)
            self.assertTrue(plan_out.is_file())
            compact_plan = json.loads(plan_proc.stdout)
            self.assertEqual(compact_plan['report_path'], str(plan_out))
            self.assertTrue(compact_plan['within_budget'])
            self.assertTrue(compact_plan['cfp_verified'])
            self.assertEqual(compact_plan['schedule_status'], 'start_not_yet_past_under_serial_assumption')
            self.assertNotIn('backward_schedule', compact_plan)

            plan_fail = subprocess.run(
                [sys.executable, str(SCRIPTS / 'check_venue_plan.py'), str(dp), '--sources', str(bad_bundle_path), '--compact'],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(plan_fail.returncode, 1)
            compact_plan_fail = json.loads(plan_fail.stdout)
            self.assertTrue(compact_plan_fail['source_issues'])
            plan_auto_report = Path(compact_plan_fail['report_path'])
            try:
                self.assertTrue(plan_auto_report.is_file())
            finally:
                plan_auto_report.unlink(missing_ok=True)

    def test_r3_stale_snapshot_parity_bypasses_and_schema_guards(self):
        now = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
        now_iso = now.isoformat()
        stale_iso = '2020-01-01T00:00:00+00:00'

        base_dossier = {
            'venue': 'AAAI',
            'edition': 'AAAI 2027',
            'track': 'Main',
            'official_cfp_url': 'https://aaai.org/aaai-27/cfp',
            'checked_at': now_iso,
            'user_timezone': 'UTC',
            'currency': 'USD',
            'budget': 2000,
            'budget_currency': 'USD',
            'presentation_mode': 'online',
            'milestones': {
                'abstract_registration': '2027-08-01T23:59:00 AoE',
                'full_paper': '2027-08-08T23:59:00 AoE',
            },
            'work_plan': {'buffer_days': 2, 'tasks': [{'name': 'Draft', 'days': 10}]},
            'fees': [
                {'name': 'submission', 'category': 'submission', 'mandatory': True, 'amount': 0,
                 'source_url': 'https://aaai.org/aaai-27/cfp', 'checked_at': now_iso},
                {'name': 'publication', 'category': 'publication', 'mandatory': True, 'amount': 0,
                 'source_url': 'https://aaai.org/aaai-27/cfp', 'checked_at': now_iso},
                {'name': 'author_registration', 'category': 'author_registration', 'mandatory': True, 'amount': 500,
                 'source_url': 'https://aaai.org/aaai-27/reg', 'checked_at': now_iso},
                {'name': 'overlength', 'category': 'overlength', 'mandatory': False, 'amount': 0},
                {'name': 'tax', 'category': 'tax', 'mandatory': False, 'amount': 0},
            ],
            'evidence_claims': [
                {'field': 'venue', 'source_url': 'https://aaai.org/aaai-27/cfp', 'quote': 'AAAI'},
                {'field': 'edition', 'source_url': 'https://aaai.org/aaai-27/cfp', 'quote': '2027'},
                {'field': 'track', 'source_url': 'https://aaai.org/aaai-27/cfp', 'quote': 'Main'},
                {'field': 'milestones.abstract_registration', 'source_url': 'https://aaai.org/aaai-27/cfp', 'quote': 'Aug 1'},
                {'field': 'milestones.full_paper', 'source_url': 'https://aaai.org/aaai-27/cfp', 'quote': 'Aug 8'},
                {'field': 'fees.submission', 'source_url': 'https://aaai.org/aaai-27/cfp', 'quote': '$0'},
                {'field': 'fees.publication', 'source_url': 'https://aaai.org/aaai-27/cfp', 'quote': '$0'},
                {'field': 'fees.author_registration', 'source_url': 'https://aaai.org/aaai-27/reg', 'quote': '$500'},
            ],
        }

        def snap(u, **kw):
            s = {
                'requested_url': u,
                'final_url': kw.get('final_url', u),
                'fetched_at_utc': now_iso,
                'http_status': 200,
                'content_type': 'text/html',
                'sha256': 'abc',
                'bytes': 100,
                'redirect_chain': [],
                'redirected_to_different_host': False,
                'same_host_path_redirect_year_mismatch': False,
                'same_host_path_redirect_year_mismatch_details': None,
                'requested_url_years': [2027],
                'final_url_years': [2027],
                'js_rendered_suspected': False,
                'unverified_dynamic_page': False,
                'js_rendered_signals': [],
                'extraction_status': 'html_text_extracted',
                'text': 'AAAI 2027 Main Aug 1 Aug 8 $0 $500',
            }
            s.update(kw)
            return s

        # 1. Stale snapshot parity in check_venue_plan.py --sources (CFP + mandatory fee)
        stale_bundle = {
            'format': 'research_scientist_venue_sources_v1',
            'sources': [
                snap('https://aaai.org/aaai-27/cfp', fetched_at_utc=stale_iso),
                snap('https://aaai.org/aaai-27/reg', fetched_at_utc=stale_iso),
            ],
        }
        src_stale = checker.check(base_dossier, stale_bundle, as_of=now)
        plan_stale = planner.check(base_dossier, as_of=now, source_bundle=stale_bundle)
        self.assertFalse(src_stale['verification_passed'])
        self.assertFalse(plan_stale['cfp_verified'])
        self.assertIsNone(plan_stale['within_budget'])
        self.assertEqual(plan_stale['verified_known_lower_bound'], 0)
        self.assertEqual(plan_stale['backward_schedule']['status'], 'cfp_source_unverified_or_year_mismatch')
        self.assertEqual(set(plan_stale['stale_fee_evidence']), {'submission', 'publication', 'author_registration'})
        self.assertTrue(all(i['issue'] == 'source_snapshot_stale_or_undated' for i in plan_stale['source_issues']))
        with tempfile.TemporaryDirectory() as tmp:
            dp = Path(tmp) / 'd.json'
            bp = Path(tmp) / 'b.json'
            dp.write_text(json.dumps(base_dossier), encoding='utf-8')
            bp.write_text(json.dumps(stale_bundle), encoding='utf-8')
            p_cli = subprocess.run(
                [sys.executable, str(SCRIPTS / 'check_venue_plan.py'), str(dp), '--sources', str(bp)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(p_cli.returncode, 1)

        # 2. Bypass C1: undated->undated redirect (/cfp -> /registration/) with edition='AAAI 2027' and text='AAAI-25 Registration'
        d_undated = json.loads(json.dumps(base_dossier))
        d_undated['official_cfp_url'] = 'https://aaai.org/cfp'
        for f in d_undated['fees']:
            if f.get('source_url') == 'https://aaai.org/aaai-27/cfp':
                f['source_url'] = 'https://aaai.org/cfp'
        for c in d_undated['evidence_claims']:
            if c.get('source_url') == 'https://aaai.org/aaai-27/cfp':
                c['source_url'] = 'https://aaai.org/cfp'
        b_undated = {
            'format': 'research_scientist_venue_sources_v1',
            'sources': [
                snap('https://aaai.org/cfp', final_url='https://aaai.org/registration/',
                     requested_url_years=[], final_url_years=[], text='AAAI-25 Registration Main Aug 1 Aug 8 $0'),
                snap('https://aaai.org/aaai-27/reg'),
            ],
        }
        self.assertFalse(checker.check(d_undated, b_undated, as_of=now)['verification_passed'])
        self.assertFalse(planner.check(d_undated, as_of=now, source_bundle=b_undated)['cfp_verified'])

        # 3. Bypass C2: hand-crafted explicit empty 'final_url_years': [] on /2027/cfp -> /2025/cfp
        d_empty_fy = json.loads(json.dumps(base_dossier))
        d_empty_fy['official_cfp_url'] = 'https://aaai.org/2027/cfp'
        for f in d_empty_fy['fees']:
            if f.get('source_url') == 'https://aaai.org/aaai-27/cfp':
                f['source_url'] = 'https://aaai.org/2027/cfp'
        for c in d_empty_fy['evidence_claims']:
            if c.get('source_url') == 'https://aaai.org/aaai-27/cfp':
                c['source_url'] = 'https://aaai.org/2027/cfp'
        b_empty_fy = {
            'format': 'research_scientist_venue_sources_v1',
            'sources': [
                snap('https://aaai.org/2027/cfp', final_url='https://aaai.org/2025/cfp',
                     requested_url_years=[2027], final_url_years=[]),
                snap('https://aaai.org/aaai-27/reg'),
            ],
        }
        self.assertFalse(checker.check(d_empty_fy, b_empty_fy, as_of=now)['verification_passed'])
        self.assertFalse(planner.check(d_empty_fy, as_of=now, source_bundle=b_empty_fy)['cfp_verified'])

        # 4. Bypass C3: omitted redirected_to_different_host with cross-host final_url
        b_diff_host = {
            'format': 'research_scientist_venue_sources_v1',
            'sources': [
                {k: v for k, v in snap('https://aaai.org/aaai-27/cfp', final_url='https://evil.org/aaai-27/cfp').items()
                 if k != 'redirected_to_different_host'},
                snap('https://aaai.org/aaai-27/reg'),
            ],
        }
        res_dh_src = checker.check(base_dossier, b_diff_host, as_of=now)
        res_dh_plan = planner.check(base_dossier, as_of=now, source_bundle=b_diff_host)
        self.assertFalse(res_dh_src['verification_passed'])
        self.assertTrue(any(i['issue'] == 'redirected_to_different_host' for i in res_dh_src['blocking_source_issues']))
        self.assertFalse(res_dh_plan['cfp_verified'])
        self.assertTrue(any(i['issue'] == 'redirected_to_different_host' for i in res_dh_plan['source_issues']))

        # 5. NON_YEAR_COMMON_WORDS ignores 'edition' and 'volume', and fees='bad' raises ValueError / exit 2
        self.assertEqual(checker._extract_text_years('Edition 25 Volume 26'), [])
        self.assertEqual(planner._extract_text_years('Edition 25 Volume 26'), [])
        self.assertEqual(capture._extract_title_h1_years('<title>Edition 25 Volume 26</title>'), [])

        d_bad_fees = json.loads(json.dumps(base_dossier))
        d_bad_fees['fees'] = 'bad'
        b_clean = {
            'format': 'research_scientist_venue_sources_v1',
            'sources': [snap('https://aaai.org/aaai-27/cfp'), snap('https://aaai.org/aaai-27/reg')],
        }
        with self.assertRaises(ValueError):
            checker.check(d_bad_fees, b_clean, as_of=now)
        with tempfile.TemporaryDirectory() as tmp:
            dp = Path(tmp) / 'bad_fees.json'
            bp = Path(tmp) / 'b.json'
            dp.write_text(json.dumps(d_bad_fees), encoding='utf-8')
            bp.write_text(json.dumps(b_clean), encoding='utf-8')
            bad_proc = subprocess.run(
                [sys.executable, str(SCRIPTS / 'check_venue_sources.py'), str(dp), str(bp)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(bad_proc.returncode, 2)
            self.assertIn('error', json.loads(bad_proc.stderr))

    def test_r4_ssr_concise_external_table_compact_scale_and_parity(self):
        # 1. Concise (<100 chars) SSR Next.js, React, and Vue static pricing with <noscript> must NOT trigger JS FP
        for mount in ('<div id="__next">', '<div id="root" data-reactroot="">', '<div id="app" data-v-app="">'):
            ssr_html = (
                f'<html><body>{mount}<h1>ICML 2027 Registration</h1>'
                '<table><thead><tr><th>Tier</th><th>Fee</th></tr></thead>'
                '<tbody><tr><td>Author</td><td>$500 USD</td></tr></tbody></table>'
                '<p>Author registration deadline May 1, 2027 AoE.</p></div>'
                '<noscript>Enable JavaScript for interactive dashboard.</noscript>'
                '<script src="/_next/static/chunks/main.js"></script></body></html>'
            )
            with self.subTest(mount=mount):
                s = capture.capture_url(
                    'https://neurips.cc/2027/Pricing',
                    transport=lambda u, h=ssr_html: {
                        'final_url': u, 'content_type': 'text/html', 'body': h.encode('utf-8'), 'http_status': 200,
                    },
                )
                self.assertFalse(s['js_rendered_suspected'], f'SSR FP: {s["js_rendered_signals"]}')
                self.assertFalse(s['unverified_dynamic_page'])

        # Control: truly empty SPA mount with <noscript> MUST still trigger
        empty_mount = (
            '<html><body><div id="__next"></div>'
            '<noscript>Enable JavaScript for interactive dashboard.</noscript>'
            '<script src="/_next/static/chunks/main.js"></script></body></html>'
        )
        s_empty = capture.capture_url(
            'https://neurips.cc/2027/Pricing',
            transport=lambda u: {
                'final_url': u, 'content_type': 'text/html', 'body': empty_mount.encode('utf-8'), 'http_status': 200,
            },
        )
        self.assertTrue(s_empty['js_rendered_suspected'])

        # 2. thead + empty tbody with >=500 chars nav prose & external <script src=...> MUST trigger
        nav = ' '.join(['Conference Policy Guidelines Code of Conduct Travel Grants Submission Info.'] * 15)
        ext_html = (
            f'<html><body><nav>{nav}</nav>'
            '<table><thead><tr><th>Tier</th><th>Fee</th></tr></thead><tbody></tbody></table>'
            '<script src="/assets/fees-loader.js"></script></body></html>'
        )
        s_ext = capture.capture_url(
            'https://icml.cc/2027/Pricing',
            transport=lambda u: {
                'final_url': u, 'content_type': 'text/html', 'body': ext_html.encode('utf-8'), 'http_status': 200,
            },
        )
        self.assertTrue(s_ext['js_rendered_suspected'])
        self.assertIn('empty_table_with_scripts', s_ext['js_rendered_signals'])

        # 3. _compact_capture_summary handles non-dict submission_systems & 5KB strings & 20 sources < 4096B
        crafted = {
            'format': 'research_scientist_venue_sources_v1',
            'captured_at_utc': datetime.now(timezone.utc).isoformat(),
            'sources': [
                {
                    'requested_url': f'https://conf.example/page/{i}?token=' + ('x' * 500),
                    'final_url': f'https://conf.example/final/{i}',
                    'fetched_at_utc': datetime.now(timezone.utc).isoformat(),
                    'http_status': 200,
                    'extraction_status': 'html_text_extracted',
                    'sha256': 'a' * 64,
                    'bytes': 1234,
                    'text': 'Body text',
                    'error': 'E' * 5000,
                    'cfp_signals': {
                        'deadlines': 'bad-non-list',
                        'timezones': ['AoE', 'Z' * 5000],
                        'submission_systems': ['openreview'],
                    },
                }
                for i in range(20)
            ],
        }
        compact_cap = capture._compact_capture_summary(crafted, bundle_path='/tmp/b.json')
        encoded_cap = json.dumps(compact_cap, ensure_ascii=False).encode('utf-8')
        self.assertLess(len(encoded_cap), 4096)
        self.assertEqual(compact_cap['source_count'], 20)
        self.assertTrue(compact_cap.get('sources_truncated'))
        self.assertEqual(compact_cap['sources'][0]['cfp_signals_summary']['submission_systems'], ['openreview'])

        # 4. _compact_check_summary with 30 failed claims (>120-char quotes) stays < 4096B
        many_failed = {
            'venue': 'ICML',
            'checked_at_utc': datetime.now(timezone.utc).isoformat(),
            'verification_passed': False,
            'source_text_status': 'verification_blocked',
            'critical_fields_without_matched_quote': ['venue', 'edition'],
            'blocking_source_issues': [
                {'source_url': f'https://conf.example/s{i}', 'issue': 'unverified_dynamic_page', 'signals': ['empty_table_with_scripts']}
                for i in range(15)
            ],
            'claims': [
                {
                    'field': f'milestones.item_{i}',
                    'source_url': f'https://conf.example/cfp_{i}',
                    'status': 'quote_not_found_in_snapshot',
                    'quote': 'Q' * 200,
                }
                for i in range(30)
            ],
        }
        compact_chk = checker._compact_check_summary(many_failed, report_path='/tmp/r.json')
        encoded_chk = json.dumps(compact_chk, ensure_ascii=False).encode('utf-8')
        self.assertLess(len(encoded_chk), 4096)
        self.assertEqual(compact_chk['failed_claims_total'], 30)
        self.assertLessEqual(len(compact_chk['failed_claims']), 10)
        self.assertEqual(compact_chk['blocking_source_issues_total'], 15)
        self.assertLessEqual(len(compact_chk['blocking_source_issues']), 10)

        # 5. Parity: undated -> /2025/cfp -> undated hop, 'location'-only hop, text=None, and non-int DBLP year
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        hop_snap = {
            'requested_url': 'https://aaai.org/cfp',
            'final_url': 'https://aaai.org/registration/',
            'fetched_at_utc': now_iso,
            'extraction_status': 'html_text_extracted',
            'redirect_chain': [
                {'from_url': 'https://aaai.org/cfp', 'status': 302, 'to_url': 'https://aaai.org/2025/cfp'},
                {'from_url': 'https://aaai.org/2025/cfp', 'status': 302, 'to_url': 'https://aaai.org/registration/'},
            ],
            'text': 'AAAI Main Aug 1 Aug 8',
        }
        self.assertTrue(checker._snapshot_year_mismatch(hop_snap, [2027])[0])
        self.assertTrue(planner._snapshot_year_mismatch(hop_snap, [2027])[0])

        loc_snap = {
            'requested_url': 'https://aaai.org/aaai-27/cfp',
            'final_url': 'https://aaai.org/aaai-27/cfp',
            'redirect_chain': [{'from_url': 'https://aaai.org/aaai-27/cfp', 'status': 302, 'location': 'https://evil.org/bounce'}],
        }
        self.assertTrue(checker._is_different_host_redirect(loc_snap))
        self.assertTrue(planner._is_different_host_redirect(loc_snap))

        base_dossier = json.loads((ROOT / 'research-scientist/references/venue-dossier.schema-example.json').read_text())
        base_dossier['checked_at'] = now_iso
        for f in base_dossier['fees']:
            if f.get('mandatory'):
                f['checked_at'] = now_iso
        none_text_bundle = {
            'format': 'research_scientist_venue_sources_v1',
            'sources': [
                {
                    'requested_url': base_dossier['official_cfp_url'],
                    'final_url': base_dossier['official_cfp_url'],
                    'fetched_at_utc': now_iso,
                    'extraction_status': 'html_text_extracted',
                    'text': None,
                },
                {
                    'requested_url': base_dossier['fees'][0]['source_url'],
                    'final_url': base_dossier['fees'][0]['source_url'],
                    'fetched_at_utc': now_iso,
                    'extraction_status': 'html_text_extracted',
                    'text': 'Fee 0',
                },
            ],
        }
        self.assertFalse(checker.check(base_dossier, none_text_bundle, as_of=now)['verification_passed'])
        plan_none = planner.check(base_dossier, as_of=now, source_bundle=none_text_bundle)
        self.assertFalse(plan_none['cfp_verified'])
        self.assertTrue(any(i['issue'] == 'fetch_failed' for i in plan_none['source_issues']))

        bad_year_toc = capture.lookup_dblp_toc_count('conf/aaai', 'not_an_int')
        self.assertEqual(bad_year_toc['status'], 'source_failed')
        self.assertIsNone(bad_year_toc['paper_count'])
        self.assertEqual(bad_year_toc['error'], 'invalid_year')


if __name__ == '__main__':
    unittest.main()
