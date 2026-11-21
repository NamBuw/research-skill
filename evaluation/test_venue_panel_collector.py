"""Offline tests for venue_panel_collector.py (PMLR, ACL Anthology, DBLP, challenges, and schema compatibility)."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / 'research-scientist/scripts'

collector_spec = importlib.util.spec_from_file_location('venue_panel_collector', SCRIPTS_DIR / 'venue_panel_collector.py')
collector_mod = importlib.util.module_from_spec(collector_spec)
sys.modules['venue_panel_collector'] = collector_mod
collector_spec.loader.exec_module(collector_mod)

novelty_spec = importlib.util.spec_from_file_location('compare_venue_novelty', SCRIPTS_DIR / 'compare_venue_novelty.py')
novelty_mod = importlib.util.module_from_spec(novelty_spec)
novelty_spec.loader.exec_module(novelty_mod)


PMLR_HTML = """<!DOCTYPE html>
<html><body><div class="wrapper">
<h2>Volume 235: International Conference on Machine Learning, 21-27 July 2024, Vienna, Austria</h2>
<div class="paper">
  <p class="title">Revisiting Character-level Adversarial Attacks for Language Models</p>
  <p class="details"><span class="authors">Elias Abad Rocamora,&nbsp;Yongtao Wu,&nbsp;Volkan Cevher</span>;
  <span class="info"><i>Proceedings of the 41st International Conference on Machine Learning</i>, PMLR 235:1-30</span></p>
  <p class="links">[<a href="https://proceedings.mlr.press/v235/abad-rocamora24a.html">abs</a>][<a href="https://raw.githubusercontent.com/mlresearch/v235/main/assets/abad-rocamora24a/abad-rocamora24a.pdf">Download PDF</a>][<a href="https://openreview.net/forum?id=AZWqXfM6z9">OpenReview</a>]</p>
</div>
<div class="paper">
  <p class="title">Second PMLR Paper Title</p>
  <p class="details"><span class="authors">Alice Smith,&nbsp;Bob Jones</span>;
  <span class="info"><i>Proceedings of the 41st International Conference on Machine Learning</i>, PMLR 235:31-45</span></p>
  <p class="links">[<a href="https://proceedings.mlr.press/v235/smith24a.html">abs</a>][<a href="https://proceedings.mlr.press/v235/smith24a/smith24a.pdf">Download PDF</a>]</p>
</div>
<div class="paper">
  <p class="title">Third PMLR Paper Title</p>
  <p class="details"><span class="authors">Carol Lee</span>; <span class="info">PMLR 235:46-60</span></p>
  <p class="links">[<a href="/v235/lee24a.html">abs</a>][<a href="/v235/lee24a/lee24a.pdf">PDF</a>]</p>
</div>
<div class="paper">
  <p class="title">Fourth PMLR Paper Title</p>
  <p class="details"><span class="authors">Dan Kim</span>; <span class="info">PMLR 235:61-75</span></p>
  <p class="links">[<a href="https://proceedings.mlr.press/v235/kim24a.html">abs</a>][<a href="https://raw.githubusercontent.com/mlresearch/v235/main/assets/kim24a/kim24a.pdf">Download PDF</a>]</p>
</div>
<div class="paper">
  <p class="title">Fifth PMLR Paper Title</p>
  <p class="details"><span class="authors">Eve Chen</span>; <span class="info">PMLR 235:76-90</span></p>
  <p class="links">[<a href="https://proceedings.mlr.press/v235/chen24a.html">abs</a>][<a href="https://raw.githubusercontent.com/mlresearch/v235/main/assets/chen24a/chen24a.pdf">Download PDF</a>]</p>
</div>
<div class="paper">
  <p class="title">Sixth PMLR Paper Title</p>
  <p class="details"><span class="authors">Frank Wu</span>; <span class="info">PMLR 235:91-110</span></p>
  <p class="links">[<a href="https://proceedings.mlr.press/v235/wu24a.html">abs</a>][<a href="https://proceedings.mlr.press/v235/wu24a/wu24a.pdf">Download PDF</a>]</p>
</div>
</div></body></html>
"""


ACL_EVENT_HTML = """<!DOCTYPE html>
<html><body><section id=main>
<h2 id=title>63rd Annual Meeting of the Association for Computational Linguistics</h2>
<div id=2025acl-long>
  <h4 class="d-sm-flex pb-2 border-bottom"><a class=align-middle href=/volumes/2025.acl-long/>Proceedings of the 63rd Annual Meeting (Volume 1: Long Papers)</a></h4>
  <div class="d-sm-flex align-items-stretch mb-3">
    <div class="d-block me-2 list-button-row"><span class="d-inline d-sm-block text-nowrap">
      <a href=https://aclanthology.org/2025.acl-long.0.pdf title="Open PDF">pdf</a>
      <a href=/2025.acl-long.0.bib title="Export to BibTeX">bib</a>
    </span></div>
    <span class=d-block><strong><a class=align-middle href=/2025.acl-long.0/>Proceedings of the 63rd Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers)</a></strong><br><a href=/people/ed1/>Editor One</a></span>
  </div>
  <div class="d-sm-flex align-items-stretch mb-3">
    <div class="d-block me-2 list-button-row"><span class="d-inline d-sm-block text-nowrap">
      <a href=https://aclanthology.org/2025.acl-long.1.pdf title="Open PDF">pdf</a>
      <a data-bs-target=#abstract-2025--acl-long--1 title="Show Abstract">abs</a>
    </span></div>
    <span class=d-block><strong><a class=align-middle href=/2025.acl-long.1/><span class=acl-fixed-case>E</span>com<span class=acl-fixed-case>S</span>cript<span class=acl-fixed-case>B</span>ench: Evaluating Scripted Tasks</a></strong><br><a href=/people/a1/>Alice One</a> | <a href=/people/a2/>Bob Two</a></span>
  </div>
  <div class="card collapse abstract-collapse" id=abstract-2025--acl-long--1><div class="card-body p-3 small">Abstract for EcomScriptBench.</div></div>
  <div class="d-sm-flex align-items-stretch mb-3">
    <div class="d-block me-2 list-button-row"><span class="d-inline d-sm-block text-nowrap">
      <a href=https://aclanthology.org/2025.acl-long.2.pdf>pdf</a><a data-bs-target=#abstract-2025--acl-long--2>abs</a>
    </span></div>
    <span class=d-block><strong><a href=/2025.acl-long.2/>Main Long Paper Two</a></strong><br><a href=/people/b1/>Author B</a></span>
  </div>
  <div class="d-sm-flex align-items-stretch mb-3">
    <div class="d-block me-2 list-button-row"><span class="d-inline d-sm-block text-nowrap">
      <a href=https://aclanthology.org/2025.acl-long.3.pdf>pdf</a><a data-bs-target=#abstract-2025--acl-long--3>abs</a>
    </span></div>
    <span class=d-block><strong><a href=/2025.acl-long.3/>Main Long Paper Three</a></strong><br><a href=/people/c1/>Author C</a></span>
  </div>
  <div class="d-sm-flex align-items-stretch mb-3">
    <div class="d-block me-2 list-button-row"><span class="d-inline d-sm-block text-nowrap">
      <a href=https://aclanthology.org/2025.acl-long.4.pdf>pdf</a><a data-bs-target=#abstract-2025--acl-long--4>abs</a>
    </span></div>
    <span class=d-block><strong><a href=/2025.acl-long.4/>Main Long Paper Four</a></strong><br><a href=/people/d1/>Author D</a></span>
  </div>
  <div class="d-sm-flex align-items-stretch mb-3">
    <div class="d-block me-2 list-button-row"><span class="d-inline d-sm-block text-nowrap">
      <a href=https://aclanthology.org/2025.acl-long.5.pdf>pdf</a><a data-bs-target=#abstract-2025--acl-long--5>abs</a>
    </span></div>
    <span class=d-block><strong><a href=/2025.acl-long.5/>Main Long Paper Five</a></strong><br><a href=/people/e1/>Author E</a></span>
  </div>
</div>
<div id=2025findings-acl>
  <h4 class="d-sm-flex pb-2 border-bottom"><a href=/volumes/2025.findings-acl/>Findings of the Association for Computational Linguistics: ACL 2025</a></h4>
  <div class="d-sm-flex align-items-stretch mb-3">
    <span class=d-block><strong><a href=/2025.findings-acl.0/>Findings of ACL 2025 Frontmatter</a></strong></span>
  </div>
  <div class="d-sm-flex align-items-stretch mb-3"><span class=d-block><strong><a href=/2025.findings-acl.1/>Findings Paper 1</a></strong><a data-bs-target=#abstract-f1>abs</a></span></div>
  <div class="d-sm-flex align-items-stretch mb-3"><span class=d-block><strong><a href=/2025.findings-acl.2/>Findings Paper 2</a></strong><a data-bs-target=#abstract-f2>abs</a></span></div>
  <div class="d-sm-flex align-items-stretch mb-3"><span class=d-block><strong><a href=/2025.findings-acl.3/>Findings Paper 3</a></strong><a data-bs-target=#abstract-f3>abs</a></span></div>
  <div class="d-sm-flex align-items-stretch mb-3"><span class=d-block><strong><a href=/2025.findings-acl.4/>Findings Paper 4</a></strong><a data-bs-target=#abstract-f4>abs</a></span></div>
  <div class="d-sm-flex align-items-stretch mb-3"><span class=d-block><strong><a href=/2025.findings-acl.5/>Findings Paper 5</a></strong><a data-bs-target=#abstract-f5>abs</a></span></div>
</div>
<div id=w19-35>
  <h4 class="d-sm-flex pb-2 border-bottom"><a href=/volumes/W19-35/>Workshop on NLP</a></h4>
  <div class="d-sm-flex align-items-stretch mb-3"><span class=d-block><strong><a href=/P19-1000/>Proceedings of Legacy Frontmatter</a></strong></span></div>
  <div class="d-sm-flex align-items-stretch mb-3"><span class=d-block><strong><a href=/W19-3501/>Workshop Paper 1</a></strong><a href=#abstract-w1>abs</a></span></div>
</div>
</section></body></html>
"""


DBLP_HTML = """<!DOCTYPE html>
<html><body>
<h1>ICML 2024: Vienna, Austria</h1>
<header><h2>Main Track</h2></header>
<ul class="publ-list">
  <li class="entry editor" id="conf/icml/2024"><cite class="data"><span class="title">Proceedings of ICML 2024.</span></cite></li>
  <li class="entry inproceedings" id="conf/icml/Alpha24">
    <nav class="publ"><ul><li class="ee"><a href="http://dx.doi.org/10.1000/alpha">EE</a></li></ul></nav>
    <cite class="data"><span itemprop="author"><a href="#"><span itemprop="name">Alice A</span></a></span>,
      <span itemprop="author"><a href="#"><span itemprop="name">Bob B</span></a></span>:
      <span class="title" itemprop="name">Alpha Method for <i>Sparse</i> Graphs.</span>
      <span itemprop="pagination">10-20</span> <span itemprop="datePublished">2024</span>
    </cite>
  </li>
  <li class="entry inproceedings" id="conf/icml/Beta24">
    <cite class="data"><span itemprop="author"><span itemprop="name">Carol C</span></span>:
      <span class="title" itemprop="name">Beta Paper Two.</span><span itemprop="datePublished">2024</span>
    </cite>
  </li>
  <li class="entry inproceedings" id="conf/icml/Gamma24">
    <nav class="publ"><ul><li class="ee"><a href="https://proceedings.mlr.press/v235/gamma24.pdf">PDF</a></li></ul></nav>
    <cite class="data"><span itemprop="author"><span itemprop="name">Dan D</span></span>:
      <span class="title" itemprop="name">Gamma Paper Three.</span><span itemprop="datePublished">2024</span>
    </cite>
  </li>
  <li class="entry inproceedings" id="conf/icml/Delta24">
    <cite class="data"><span itemprop="author"><span itemprop="name">Eve E</span></span>:
      <span class="title" itemprop="name">Delta Paper Four.</span><span itemprop="datePublished">2024</span>
    </cite>
  </li>
  <li class="entry inproceedings" id="conf/icml/Eps24">
    <cite class="data"><span itemprop="author"><span itemprop="name">Frank F</span></span>:
      <span class="title" itemprop="name">Epsilon Paper Five.</span><span itemprop="datePublished">2024</span>
    </cite>
  </li>
</ul>
<header><h2>Workshop Track</h2></header>
<ul class="publ-list">
  <li class="entry inproceedings" id="conf/icml/Ws24">
    <cite class="data"><span itemprop="author"><span itemprop="name">Grace G</span></span>:
      <span class="title" itemprop="name">Workshop Only Paper.</span><span itemprop="datePublished">2024</span>
    </cite>
  </li>
</ul>
</body></html>
"""


DBLP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<dblp>
  <proceedings key="conf/icml/2024"><title>Proceedings of ICML 2024.</title><booktitle>ICML</booktitle><year>2024</year></proceedings>
  <inproceedings key="conf/icml/X1"><author orcid="0000-0001">Author One</author><title>Paper <i>One</i>.</title><pages>1-10</pages><year>2024</year><booktitle>ICML</booktitle><ee>http://dx.doi.org/10.5555/1</ee></inproceedings>
  <inproceedings key="conf/icml/X2"><author>Author Two</author><title>Paper Two.</title><year>2024</year><booktitle>ICML</booktitle><ee>https://proceedings.mlr.press/v235/x2.pdf</ee></inproceedings>
  <inproceedings key="conf/icml/X3"><author>Author Three</author><title>Paper Three.</title><year>2024</year><booktitle>ICML</booktitle></inproceedings>
  <article key="journals/jmlr/X4"><author>Author Four</author><title>Article Four.</title><year>2024</year><journal>JMLR</journal><ee>https://jmlr.org/papers/v25/x4.html</ee></article>
  <inproceedings key="conf/icml/X5"><author>Author Five</author><title>Paper Five.</title><year>2024</year><booktitle>ICML</booktitle></inproceedings>
</dblp>
"""


ANUBIS_202_HTML = """<!doctype html><html><head><title>Making sure you&#39;re not a bot!</title></head>
<body><script id="anubis_challenge" type="application/json">{"challenge":"abc"}</script>
<a href="/.within.website/x/cmd/anubis/api/pass-challenge">Anubis</a></body></html>
"""


class VenuePanelCollectorTests(unittest.TestCase):
    def test_pmlr_parses_v235_github_pdfs_and_v202_mlr_pdfs(self):
        transport = lambda url, timeout=20: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': PMLR_HTML.encode('utf-8')}
        out5 = collector_mod.collect_panel('pmlr', 'v235', limit=5, transport=transport)
        self.assertEqual(out5['schema'], 'research_scientist_venue_panel_v1')
        self.assertEqual(out5['paper_count'], 5)
        self.assertEqual(out5['screened_count'], 6)
        self.assertEqual(out5['year'], 2024)
        p0 = out5['papers'][0]
        self.assertEqual(p0['id'], 'pmlr:v235/abad-rocamora24a')
        self.assertEqual(p0['authors'], ['Elias Abad Rocamora', 'Yongtao Wu', 'Volkan Cevher'])
        self.assertEqual(p0['pages'], '1-30')
        self.assertEqual(p0['pdf_url'], 'https://raw.githubusercontent.com/mlresearch/v235/main/assets/abad-rocamora24a/abad-rocamora24a.pdf')
        self.assertEqual(p0['openreview_url'], 'https://openreview.net/forum?id=AZWqXfM6z9')
        self.assertEqual(p0['reading_basis'], 'metadata_only')
        p1 = out5['papers'][1]
        self.assertEqual(p1['pdf_url'], 'https://proceedings.mlr.press/v235/smith24a/smith24a.pdf')

        out6 = collector_mod.collect_panel('pmlr', 'v235', limit=6, transport=transport)
        self.assertEqual(out6['paper_count'], 6)

    def test_acl_event_unquoted_attrs_fixed_case_frontmatter_abstract_and_tracks(self):
        transport = lambda url, timeout=20: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': ACL_EVENT_HTML.encode('utf-8')}
        main_out = collector_mod.collect_panel('acl', 'acl-2025', limit=5, transport=transport)
        self.assertEqual(main_out['track'], 'Main')
        self.assertEqual(main_out['paper_count'], 5)
        self.assertEqual(main_out['provenance']['frontmatter_skipped'], 3)  # .0 long, .0 findings, P19-1000
        first = main_out['papers'][0]
        self.assertEqual(first['title'], 'EcomScriptBench: Evaluating Scripted Tasks')
        self.assertEqual(first['official_acceptance_url'], 'https://aclanthology.org/2025.acl-long.1/')
        self.assertEqual(first['abstract'], 'Abstract for EcomScriptBench.')
        self.assertEqual(first['authors'], ['Alice One', 'Bob Two'])
        self.assertTrue(all(item['track'] == main_out['venue']['track'] == 'Main' for item in main_out['accepted_panel']))

        findings_out = collector_mod.collect_panel('acl', 'acl-2025', limit=5, track='Findings', transport=transport)
        self.assertEqual(findings_out['track'], 'Findings')
        self.assertEqual(findings_out['paper_count'], 5)
        self.assertTrue(all(item['id'].startswith('acl:2025.findings-acl.') for item in findings_out['accepted_panel']))
        self.assertTrue(all(item['track'] == findings_out['venue']['track'] == 'Findings' for item in findings_out['accepted_panel']))

        # Workshop track only has 1 paper -> insufficient_panel_papers
        with self.assertRaises(collector_mod.PanelCollectionError) as ctx:
            collector_mod.collect_panel('acl', 'acl-2025', limit=5, track='Workshop', transport=transport)
        self.assertEqual(ctx.exception.error_code, 'insufficient_panel_papers')
        self.assertEqual(ctx.exception.details['found_count'], 1)

    def test_acl_single_volume_url_layout(self):
        vol_html = """<section id="main"><h2 id="title">Proceedings of ACL 2025 Long</h2>
        <div class="d-sm-flex"><span class="d-block"><strong><a href="/2025.acl-long.1/">Paper 1</a></strong></span></div>
        <div class="d-sm-flex"><span class="d-block"><strong><a href="/2025.acl-long.2/">Paper 2</a></strong></span></div>
        <div class="d-sm-flex"><span class="d-block"><strong><a href="/2025.acl-long.3/">Paper 3</a></strong></span></div>
        <div class="d-sm-flex"><span class="d-block"><strong><a href="/2025.acl-long.4/">Paper 4</a></strong></span></div>
        <div class="d-sm-flex"><span class="d-block"><strong><a href="/2025.acl-long.5/">Paper 5</a></strong></span></div>
        </section>"""
        transport = lambda url, timeout=20: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': vol_html.encode('utf-8')}
        out = collector_mod.collect_panel('acl', '2025.acl-long', limit=5, transport=transport)
        self.assertEqual(out['source_url'], 'https://aclanthology.org/volumes/2025.acl-long/')
        self.assertEqual(out['paper_count'], 5)

    def test_dblp_html_toc_and_section_track_filtering(self):
        transport = lambda url, timeout=20: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': DBLP_HTML.encode('utf-8')}
        out = collector_mod.collect_panel('dblp', 'conf/icml/icml2024', limit=5, track='Main Track', transport=transport)
        self.assertEqual(out['provenance']['frontmatter_skipped'], 1)  # entry editor
        self.assertEqual(out['paper_count'], 5)
        self.assertEqual(out['papers'][0]['title'], 'Alpha Method for Sparse Graphs')
        self.assertEqual(out['papers'][0]['authors'], ['Alice A', 'Bob B'])
        self.assertEqual(out['papers'][0]['official_acceptance_url'], 'https://doi.org/10.1000/alpha')
        self.assertEqual(out['papers'][0]['doi'], '10.1000/alpha')
        self.assertEqual(out['papers'][1]['official_acceptance_url'], 'https://dblp.org/rec/conf/icml/Beta24.html')
        self.assertEqual(out['papers'][2]['pdf_url'], 'https://proceedings.mlr.press/v235/gamma24.pdf')

    def test_dblp_xml_toc_parsing(self):
        transport = lambda url, timeout=20: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': DBLP_XML.encode('utf-8')}
        out = collector_mod.collect_panel('dblp', 'conf/icml/icml2024.xml', limit=5, transport=transport)
        self.assertEqual(out['source_url'], 'https://dblp.org/db/conf/icml/icml2024.xml')
        self.assertEqual(out['provenance']['frontmatter_skipped'], 1)  # <proceedings>
        self.assertEqual(out['paper_count'], 5)
        self.assertEqual(out['papers'][0]['title'], 'Paper One')
        self.assertEqual(out['papers'][0]['authors'], ['Author One'])
        self.assertEqual(out['papers'][0]['official_acceptance_url'], 'https://doi.org/10.5555/1')
        self.assertEqual(out['papers'][2]['official_acceptance_url'], 'https://dblp.org/rec/conf/icml/X3.html')

    def test_bot_challenges_anubis_202_and_cloudflare_403(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / 'should_not_exist.json'
            anubis_t = lambda url, timeout=20: {
                'status_code': 202,
                'headers': {'refresh': '2; url=/.within.website/'},
                'final_url': url,
                'body': ANUBIS_202_HTML.encode('utf-8'),
            }
            with self.assertRaises(collector_mod.PanelCollectionError) as ctx:
                collector_mod.collect_panel('dblp', 'conf/icml/icml2024', transport=anubis_t)
            self.assertEqual(ctx.exception.error_code, 'bot_challenge_anubis')
            self.assertEqual(ctx.exception.exit_code, 1)

            cf_t = lambda url, timeout=20: {
                'status_code': 403,
                'headers': {'cf-ray': '12345'},
                'final_url': url,
                'body': b'<html><title>Just a moment...</title>Enable JavaScript and cookies</html>',
            }
            with self.assertRaises(collector_mod.PanelCollectionError) as cf_ctx:
                collector_mod.collect_panel('pmlr', 'v235', transport=cf_t)
            self.assertEqual(cf_ctx.exception.error_code, 'bot_challenge_cloudflare')
            self.assertFalse(out_path.exists())

    def test_http_errors_network_failures_and_shells(self):
        for status, expected in ((429, 'rate_limited_429'), (404, 'http_404'), (503, 'http_5xx')):
            t = lambda url, timeout=20, s=status: {'status_code': s, 'headers': {}, 'final_url': url, 'body': b'error'}
            with self.assertRaises(collector_mod.PanelCollectionError) as ctx:
                collector_mod.collect_panel('pmlr', 'v235', transport=t)
            self.assertEqual(ctx.exception.error_code, expected)

        # Redirect to non-HTTPS
        http_redir = lambda url, timeout=20: {'status_code': 200, 'headers': {}, 'final_url': 'http://insecure.example/', 'body': PMLR_HTML.encode('utf-8')}
        with self.assertRaises(collector_mod.PanelCollectionError) as redir_ctx:
            collector_mod.collect_panel('pmlr', 'v235', transport=http_redir)
        self.assertEqual(redir_ctx.exception.error_code, 'redirected_to_non_https_url')

        # JS-rendered SPA shell
        spa_t = lambda url, timeout=20: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': b'<html><body><div id="root"></div><noscript>Please enable JavaScript</noscript></body></html>'}
        with self.assertRaises(collector_mod.PanelCollectionError) as spa_ctx:
            collector_mod.collect_panel('pmlr', 'v235', transport=spa_t)
        self.assertEqual(spa_ctx.exception.error_code, 'js_rendered_shell')

        # Empty / binary / malformed XML
        empty_t = lambda url, timeout=20: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': b'   '}
        with self.assertRaises(collector_mod.PanelCollectionError) as empty_ctx:
            collector_mod.collect_panel('pmlr', 'v235', transport=empty_t)
        self.assertEqual(empty_ctx.exception.error_code, 'empty_or_malformed_html')

        bad_xml_t = lambda url, timeout=20: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': b'<?xml version="1.0"?><dblp><unclosed>'}
        with self.assertRaises(collector_mod.PanelCollectionError) as xml_ctx:
            collector_mod.collect_panel('dblp', 'conf/icml/icml2024.xml', transport=bad_xml_t)
        self.assertEqual(xml_ctx.exception.error_code, 'malformed_xml')

        # Network URLError via fetch_url mock
        def raise_urlerror(*args, **kwargs):
            raise URLError('dns failed')

        orig_urlopen = collector_mod.urlopen
        collector_mod.urlopen = raise_urlerror
        try:
            with self.assertRaises(collector_mod.PanelCollectionError) as net_ctx:
                collector_mod.fetch_url('https://proceedings.mlr.press/v235/')
            self.assertEqual(net_ctx.exception.error_code, 'network_failure')
        finally:
            collector_mod.urlopen = orig_urlopen

    def test_cli_validation_minimum_limit_and_offline_html(self):
        script = str(SCRIPTS_DIR / 'venue_panel_collector.py')
        help_res = subprocess.run([sys.executable, script, '--help'], capture_output=True, text=True)
        self.assertEqual(help_res.returncode, 0)
        self.assertIn('--offline-html', help_res.stdout)

        # --limit < 5 -> exit 2
        res_limit = subprocess.run([sys.executable, script, '--source', 'pmlr', '--venue-id', 'v235', '--limit', '3'], capture_output=True, text=True)
        self.assertEqual(res_limit.returncode, 2)

        # Traversal venue-id -> exit 2
        res_trav = subprocess.run([sys.executable, script, '--source', 'pmlr', '--venue-id', '../etc'], capture_output=True, text=True)
        self.assertEqual(res_trav.returncode, 2)

        # Missing --offline-html -> exit 2
        res_miss = subprocess.run([sys.executable, script, '--source', 'pmlr', '--venue-id', 'v235', '--offline-html', '/nonexistent/file.html'], capture_output=True, text=True)
        self.assertEqual(res_miss.returncode, 2)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            html_file = tmp_path / 'pmlr_v235.html'
            html_file.write_text(PMLR_HTML, encoding='utf-8')
            out_file = tmp_path / 'panel.json'
            res_ok = subprocess.run(
                [sys.executable, script, '--source', 'pmlr', '--venue-id', 'v235', '--limit', '5', '--offline-html', str(html_file), '--out', str(out_file)],
                capture_output=True, text=True,
            )
            self.assertEqual(res_ok.returncode, 0, msg=res_ok.stderr)
            self.assertTrue(out_file.is_file())
            loaded = json.loads(out_file.read_text(encoding='utf-8'))
            self.assertEqual(loaded['paper_count'], 5)
            self.assertEqual(loaded['provenance']['fetch_status'], 'offline_fixture')

            # Anubis offline HTML must exit 1 and NOT write --out
            anubis_file = tmp_path / 'anubis.html'
            anubis_file.write_text(ANUBIS_202_HTML, encoding='utf-8')
            bad_out = tmp_path / 'should_not_write.json'
            res_anubis = subprocess.run(
                [sys.executable, script, '--source', 'dblp', '--venue-id', 'conf/icml/icml2024', '--offline-html', str(anubis_file), '--out', str(bad_out)],
                capture_output=True, text=True,
            )
            self.assertEqual(res_anubis.returncode, 1)
            self.assertEqual(json.loads(res_anubis.stderr)['error_code'], 'bot_challenge_anubis')
            self.assertFalse(bad_out.exists())

    def test_compare_venue_novelty_compatibility_and_anti_fabrication(self):
        transport = lambda url, timeout=20: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': PMLR_HTML.encode('utf-8')}
        collected = collector_mod.collect_panel('pmlr', 'v235', limit=5, transport=transport)

        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        collected['venue']['official_cfp_url'] = 'https://icml.cc/Conferences/2024/CallForPapers'
        collected['venue']['checked_at_utc'] = now_iso
        collected['target'] = {
            'id': 'TARGET-1',
            'claim': 'Target paper empirical claim',
            'contribution_type': 'empirical study',
            'reading_basis': 'full_text',
            'score': 7, 'low': 6, 'high': 8,
            'closest_work_id': 'PRIOR-1',
            'closest_work_locator': 'Section 3, p. 4',
            'contribution_delta': 'New controlled benchmark',
            'search_manifest': 'target-search.json',
            'score_reason': 'Substantial delta',
            'assessment_boundary': 'Prior work before 2026',
            'assessed_at_utc': now_iso,
        }
        collected['fit_axes'] = [
            {'name': ax, 'score': 2, 'source_url': 'https://icml.cc/cfp', 'locator': 'CFP section', 'reason': 'Fits'}
            for ax in novelty_mod.AXES
        ]
        collected['hard_constraints'] = [
            {'name': hc, 'status': 'met', 'source_url': 'https://icml.cc/cfp', 'reason': 'Met'}
            for hc in novelty_mod.HARD_CONSTRAINTS
        ]

        # Raw un-read collected panel MUST fail compare_venue_novelty ONLY on unread/unscored fields!
        raw_check = novelty_mod.check(collected, as_of=now)
        self.assertEqual(raw_check['status'], 'invalid')
        self.assertIsNone(raw_check['novelty_comparison'])
        self.assertTrue(raw_check['errors'])
        for err in raw_check['errors']:
            self.assertNotIn('official_acceptance_url', err)
            self.assertNotIn('track_mismatch', err)
            self.assertNotIn('invalid_year', err)
            self.assertNotIn('duplicate_id', err)
            self.assertNotIn('screened_count', err)

        # Populating reviewer full-text judgments makes it pass cleanly
        for idx, item in enumerate(collected['accepted_panel']):
            item['reading_basis'] = 'full_text'
            item['claim'] = f'Panel claim {idx + 1}'
            item['contribution_type'] = 'empirical study'
            item['score'] = 5 + (idx % 3)
            item['low'] = item['score'] - 1
            item['high'] = item['score'] + 1
            item['closest_work_id'] = f'PRIOR-P-{idx}'
            item['closest_work_locator'] = 'Section 2'
            item['contribution_delta'] = 'Bounded delta'
            item['score_reason'] = 'Evaluated from full text'
            item['assessment_boundary'] = 'Prior work before 2024'
            item['assessed_at_utc'] = now_iso

        full_check = novelty_mod.check(collected, as_of=now)
        self.assertEqual(full_check['status'], 'structurally_checked', msg=full_check['errors'])
        self.assertEqual(full_check['errors'], [])
        self.assertEqual(full_check['novelty_comparison']['accepted_panel_size'], 5)

    def test_round2_pmlr_preface_supp_pdf_track_conflict_acl_1000_dblp_omitted_track_and_compact(self):
        # 1. PMLR Preface skipped, Supplementary PDF before Download PDF still picks main PDF,
        #    and --track Workshop on Main ICML volume raises insufficient_panel_papers.
        pmlr_edge_html = """<!DOCTYPE html><html><body><div class="wrapper">
        <h2>Volume 246: Conference on Algorithmic Decision Theory 2024</h2>
        <div class="paper">
          <p class="title">Preface</p>
          <p class="details"><span class="authors">Editor One</span>; <span class="info">PMLR 246:1-2</span></p>
          <p class="links">[<a href="/v246/preface24a.html">abs</a>][<a href="/v246/preface24a.pdf">Download PDF</a>]</p>
        </div>
        <div class="paper">
          <p class="title">Paper One</p>
          <p class="details"><span class="authors">A1</span>; <span class="info">PMLR 246:3-15</span></p>
          <p class="links">[<a href="/v246/one24a.html">abs</a>][<a href="/v246/one24a-supp.pdf">Supplementary PDF</a>][<a href="/v246/one24a.pdf">Download PDF</a>]</p>
        </div>
        <div class="paper"><p class="title">Paper Two</p><p class="details"><span class="info">PMLR 246:16-25</span></p><p class="links">[<a href="/v246/two24a.html">abs</a>][<a href="/v246/two24a.pdf">Download PDF</a>]</p></div>
        <div class="paper"><p class="title">Paper Three</p><p class="details"><span class="info">PMLR 246:26-35</span></p><p class="links">[<a href="/v246/three24a.html">abs</a>][<a href="/v246/three24a.pdf">Download PDF</a>]</p></div>
        <div class="paper"><p class="title">Paper Four</p><p class="details"><span class="info">PMLR 246:36-45</span></p><p class="links">[<a href="/v246/four24a.html">abs</a>][<a href="/v246/four24a.pdf">Download PDF</a>]</p></div>
        <div class="paper"><p class="title">Paper Five</p><p class="details"><span class="info">PMLR 246:46-55</span></p><p class="links">[<a href="/v246/five24a.html">abs</a>][<a href="/v246/five24a.pdf">Download PDF</a>]</p></div>
        </div></body></html>"""
        pmlr_t = lambda url, timeout=20: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': pmlr_edge_html.encode('utf-8')}
        out_pmlr = collector_mod.collect_panel('pmlr', 'v246', limit=5, transport=pmlr_t)
        self.assertEqual(out_pmlr['provenance']['frontmatter_skipped'], 1)
        self.assertEqual(out_pmlr['papers'][0]['title'], 'Paper One')
        self.assertEqual(out_pmlr['papers'][0]['pdf_url'], 'https://proceedings.mlr.press/v246/one24a.pdf')

        with self.assertRaises(collector_mod.PanelCollectionError) as ws_ctx:
            collector_mod.collect_panel('pmlr', 'v246', limit=5, track='Workshop', transport=pmlr_t)
        self.assertEqual(ws_ctx.exception.error_code, 'insufficient_panel_papers')
        self.assertEqual(ws_ctx.exception.details['found_count'], 0)

        # 2. ACL 1000th paper (2025.acl-long.1000) NOT dropped + nested <h4> inside child <div>
        acl_1000_html = """<!DOCTYPE html><html><body><section id=main><h2 id=title>ACL 2025</h2>
        <div id=2025acl-long>
          <div class="vol-hdr"><h4>Proceedings of ACL 2025 (Volume 1: Long Papers)</h4></div>
          <div class="d-sm-flex"><a href="/2025.acl-long.0.pdf">pdf</a><strong><a href="/2025.acl-long.0/">Proceedings of ACL 2025</a></strong></div>
          <div class="d-sm-flex"><a data-bs-target="#abstract-1000">abs</a><strong><a href="/2025.acl-long.1000/">Paper 1000</a></strong></div>
          <div class="d-sm-flex"><a data-bs-target="#abstract-1001">abs</a><strong><a href="/2025.acl-long.1001/">Paper 1001</a></strong></div>
          <div class="d-sm-flex"><a data-bs-target="#abstract-1002">abs</a><strong><a href="/2025.acl-long.1002/">Paper 1002</a></strong></div>
          <div class="d-sm-flex"><a data-bs-target="#abstract-1003">abs</a><strong><a href="/2025.acl-long.1003/">Paper 1003</a></strong></div>
          <div class="d-sm-flex"><a data-bs-target="#abstract-1004">abs</a><strong><a href="/2025.acl-long.1004/">Paper 1004</a></strong></div>
        </div></section></body></html>"""
        acl_t = lambda url, timeout=20: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': acl_1000_html.encode('utf-8')}
        out_acl = collector_mod.collect_panel('acl', 'acl-2025', limit=5, transport=acl_t)
        self.assertEqual(out_acl['provenance']['frontmatter_skipped'], 1)
        self.assertEqual(out_acl['papers'][0]['id'], 'acl:2025.acl-long.1000')
        self.assertGreaterEqual(collector_mod.MAX_BYTES, 32_000_000)

        # 3. DBLP omitted --track excludes Workshop Track when Main Track exists
        dblp_t = lambda url, timeout=20: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': DBLP_HTML.encode('utf-8')}
        out_dblp = collector_mod.collect_panel('dblp', 'conf/icml/icml2024', limit=5, transport=dblp_t)
        self.assertEqual(out_dblp['track'], 'Main')
        self.assertEqual(out_dblp['provenance']['track_filtered_out'], 1)
        self.assertNotIn('Workshop Only Paper', [p['title'] for p in out_dblp['papers']])

        # 4. CLI --compact + --out emits bounded summary on stdout and full JSON to --out
        script = str(SCRIPTS_DIR / 'venue_panel_collector.py')
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            html_file = tmp_path / 'pmlr.html'
            html_file.write_text(PMLR_HTML, encoding='utf-8')
            out_file = tmp_path / 'full_panel.json'
            res = subprocess.run(
                [sys.executable, script, '--source', 'pmlr', '--venue-id', 'v235', '--limit', '5', '--offline-html', str(html_file), '--out', str(out_file), '--compact'],
                capture_output=True, text=True,
            )
            self.assertEqual(res.returncode, 0, msg=res.stderr)
            compact = json.loads(res.stdout)
            self.assertTrue(compact['compact'])
            self.assertEqual(compact['paper_count'], 5)
            self.assertLessEqual(len(compact['sample_papers']), 5)
            self.assertEqual(compact['artifact_path'], str(out_file))
            full = json.loads(out_file.read_text(encoding='utf-8'))
            self.assertEqual(len(full['accepted_panel']), 5)

    def test_dblp_xml_multi_booktitle_secondary_track_exclusion_and_workshop_only(self):
        mixed_xml = """<?xml version="1.0" encoding="UTF-8"?>
<dblp>
  <proceedings key="conf/icml/2024"><title>Proceedings of ICML 2024.</title><booktitle>ICML</booktitle><year>2024</year></proceedings>
  <inproceedings key="conf/icml/Ws1"><author>W Author</author><title>Workshop Paper 1.</title><year>2024</year><booktitle>ICML Workshop on Agents</booktitle></inproceedings>
  <inproceedings key="conf/icml/Ws2"><author>W Author 2</author><title>Workshop Paper 2.</title><year>2024</year><booktitle>ICML Workshop on Agents</booktitle></inproceedings>
  <inproceedings key="conf/icml/Ws3"><author>W Author 3</author><title>Workshop Paper 3.</title><year>2024</year><booktitle>ICML Workshop on Agents</booktitle></inproceedings>
  <inproceedings key="conf/icml/Ws4"><author>W Author 4</author><title>Workshop Paper 4.</title><year>2024</year><booktitle>ICML Workshop on Agents</booktitle></inproceedings>
  <inproceedings key="conf/icml/Ws5"><author>W Author 5</author><title>Workshop Paper 5.</title><year>2024</year><booktitle>ICML Workshop on Agents</booktitle></inproceedings>
  <inproceedings key="conf/icml/M1"><author>M1</author><title>Main Paper 1.</title><year>2024</year><booktitle>ICML</booktitle></inproceedings>
  <inproceedings key="conf/icml/M2"><author>M2</author><title>Main Paper 2.</title><year>2024</year><booktitle>ICML</booktitle></inproceedings>
  <inproceedings key="conf/icml/M3"><author>M3</author><title>Main Paper 3.</title><year>2024</year><booktitle>ICML</booktitle></inproceedings>
  <inproceedings key="conf/icml/M4"><author>M4</author><title>Main Paper 4.</title><year>2024</year><booktitle>ICML</booktitle></inproceedings>
  <inproceedings key="conf/icml/M5"><author>M5</author><title>Main Paper 5.</title><year>2024</year><booktitle>ICML</booktitle></inproceedings>
</dblp>
"""
        mixed_t = lambda url, timeout=20: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': mixed_xml.encode('utf-8')}

        # Omitted --track must exclude Workshop entries and keep Main
        main_out = collector_mod.collect_panel('dblp', 'conf/icml/icml2024.xml', limit=5, transport=mixed_t)
        self.assertEqual(main_out['track'], 'Main')
        self.assertEqual(main_out['provenance']['track_filtered_out'], 5)
        self.assertEqual([p['title'] for p in main_out['papers']], [f'Main Paper {i}' for i in range(1, 6)])

        # Explicit --track Workshop returns only workshop entries
        ws_out = collector_mod.collect_panel('dblp', 'conf/icml/icml2024.xml', limit=5, track='Workshop', transport=mixed_t)
        self.assertEqual(ws_out['track'], 'Workshop')
        self.assertEqual([p['title'] for p in ws_out['papers']], [f'Workshop Paper {i}' for i in range(1, 6)])

        # Workshop-only DBLP XML sets canonical track to Workshop (never Main)
        ws_only_xml = """<?xml version="1.0" encoding="UTF-8"?>
<dblp>
  <inproceedings key="conf/icml/Ws1"><author>W1</author><title>WS Only 1.</title><year>2024</year><booktitle>ICML Workshop on Agents</booktitle></inproceedings>
  <inproceedings key="conf/icml/Ws2"><author>W2</author><title>WS Only 2.</title><year>2024</year><booktitle>ICML Workshop on Agents</booktitle></inproceedings>
  <inproceedings key="conf/icml/Ws3"><author>W3</author><title>WS Only 3.</title><year>2024</year><booktitle>ICML Workshop on Agents</booktitle></inproceedings>
  <inproceedings key="conf/icml/Ws4"><author>W4</author><title>WS Only 4.</title><year>2024</year><booktitle>ICML Workshop on Agents</booktitle></inproceedings>
  <inproceedings key="conf/icml/Ws5"><author>W5</author><title>WS Only 5.</title><year>2024</year><booktitle>ICML Workshop on Agents</booktitle></inproceedings>
</dblp>
"""
        ws_only_t = lambda url, timeout=20: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': ws_only_xml.encode('utf-8')}
        ws_only_out = collector_mod.collect_panel('dblp', 'conf/icml/icmlw2024.xml', limit=5, transport=ws_only_t)
        self.assertEqual(ws_only_out['track'], 'Workshop')
        self.assertEqual(ws_only_out['paper_count'], 5)

    def test_dblp_xml_no_proceedings_workshop_first_and_secondary_labels(self):
        # Multi-booktitle DBLP XML without <proceedings> where Workshop precedes Main
        ws_first_no_proc_xml = """<?xml version="1.0" encoding="UTF-8"?>
<dblp>
  <inproceedings key="conf/icml/Ws1"><author>W1</author><title>Workshop Paper 1.</title><year>2024</year><booktitle>ICML Workshop on Agents</booktitle></inproceedings>
  <inproceedings key="conf/icml/Ws2"><author>W2</author><title>Workshop Paper 2.</title><year>2024</year><booktitle>ICML Workshop on Agents</booktitle></inproceedings>
  <inproceedings key="conf/icml/Ws3"><author>W3</author><title>Workshop Paper 3.</title><year>2024</year><booktitle>ICML Workshop on Agents</booktitle></inproceedings>
  <inproceedings key="conf/icml/Ws4"><author>W4</author><title>Workshop Paper 4.</title><year>2024</year><booktitle>ICML Workshop on Agents</booktitle></inproceedings>
  <inproceedings key="conf/icml/Ws5"><author>W5</author><title>Workshop Paper 5.</title><year>2024</year><booktitle>ICML Workshop on Agents</booktitle></inproceedings>
  <inproceedings key="conf/icml/M1"><author>M1</author><title>Main Paper 1.</title><year>2024</year><booktitle>ICML</booktitle></inproceedings>
  <inproceedings key="conf/icml/M2"><author>M2</author><title>Main Paper 2.</title><year>2024</year><booktitle>ICML</booktitle></inproceedings>
  <inproceedings key="conf/icml/M3"><author>M3</author><title>Main Paper 3.</title><year>2024</year><booktitle>ICML</booktitle></inproceedings>
  <inproceedings key="conf/icml/M4"><author>M4</author><title>Main Paper 4.</title><year>2024</year><booktitle>ICML</booktitle></inproceedings>
  <inproceedings key="conf/icml/M5"><author>M5</author><title>Main Paper 5.</title><year>2024</year><booktitle>ICML</booktitle></inproceedings>
</dblp>
"""
        t_ws_first = lambda url, timeout=20: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': ws_first_no_proc_xml.encode('utf-8')}
        main_out = collector_mod.collect_panel('dblp', 'conf/icml/icml2024.xml', limit=5, transport=t_ws_first)
        self.assertEqual(main_out['track'], 'Main')
        self.assertEqual(main_out['venue_name'], 'ICML')
        self.assertEqual(main_out['venue']['name'], 'ICML')
        self.assertTrue(all(p['venue'] == 'ICML' and p['track'] == 'Main' for p in main_out['papers']))
        self.assertEqual([p['title'] for p in main_out['papers']], [f'Main Paper {i}' for i in range(1, 6)])

        ws_out = collector_mod.collect_panel('dblp', 'conf/icml/icml2024.xml', limit=5, track='Workshop', transport=t_ws_first)
        self.assertEqual(ws_out['track'], 'Workshop')
        self.assertEqual(ws_out['venue_name'], 'ICML Workshop on Agents')
        self.assertTrue(all(p['venue'] == 'ICML Workshop on Agents' for p in ws_out['papers']))

        # Canonical secondary-track labels in secondary-only DBLP XML volumes
        for booktitle, expected_track in (
            ('ACL Companion', 'Companion'),
            ('AAAI Doctoral Consortium', 'Doctoral Consortium'),
            ('ACL Findings', 'Findings'),
            ('ICML Tutorials', 'Tutorials'),
            ('ACL Demo', 'Demo'),
            ('ACL Demonstrations', 'Demo'),
            ('ICML Workshop', 'Workshop'),
        ):
            sec_xml = (
                '<?xml version="1.0" encoding="UTF-8"?><dblp>'
                + ''.join(
                    f'<inproceedings key="conf/x/P{i}"><author>A{i}</author><title>Paper {i}.</title><year>2024</year><booktitle>{booktitle}</booktitle></inproceedings>'
                    for i in range(1, 6)
                )
                + '</dblp>'
            )
            t_sec = lambda url, timeout=20, body=sec_xml: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': body.encode('utf-8')}
            sec_out = collector_mod.collect_panel('dblp', 'conf/x/sec2024.xml', limit=5, transport=t_sec)
            self.assertEqual(sec_out['track'], expected_track, msg=f'{booktitle}: {sec_out}')
            self.assertEqual(sec_out['venue_name'], booktitle)
            self.assertTrue(all(p['track'] == expected_track and p['venue'] == booktitle for p in sec_out['papers']))

    def test_dblp_multi_proceedings_venue_name_and_track_main(self):
        # Bug 1 & Bug 3: Workshop <proceedings> before Main <proceedings>, standard <booktitle>ICML</booktitle>
        multi_proc_xml = """<?xml version="1.0" encoding="UTF-8"?>
<dblp>
  <proceedings key="conf/icml/2024w"><title>Proceedings of ICML 2024 Workshop.</title><booktitle>ICML Workshop</booktitle><year>2024</year></proceedings>
  <proceedings key="conf/icml/2024"><title>Proceedings of ICML 2024.</title><booktitle>ICML</booktitle><year>2024</year></proceedings>
  <inproceedings key="conf/icml/W1"><author>W1</author><title>Workshop 1.</title><year>2024</year><booktitle>ICML Workshop</booktitle></inproceedings>
  <inproceedings key="conf/icml/M1"><author>M1</author><title>Main 1.</title><year>2024</year><booktitle>ICML</booktitle></inproceedings>
  <inproceedings key="conf/icml/M2"><author>M2</author><title>Main 2.</title><year>2024</year><booktitle>ICML</booktitle></inproceedings>
  <inproceedings key="conf/icml/M3"><author>M3</author><title>Main 3.</title><year>2024</year><booktitle>ICML</booktitle></inproceedings>
  <inproceedings key="conf/icml/M4"><author>M4</author><title>Main 4.</title><year>2024</year><booktitle>ICML</booktitle></inproceedings>
  <inproceedings key="conf/icml/M5"><author>M5</author><title>Main 5.</title><year>2024</year><booktitle>ICML</booktitle></inproceedings>
</dblp>
"""
        t_multi = lambda url, timeout=20: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': multi_proc_xml.encode('utf-8')}
        for trk in (None, 'Main', 'main'):
            out = collector_mod.collect_panel('dblp', 'conf/icml/icml2024.xml', limit=5, track=trk, transport=t_multi)
            self.assertEqual(out['track'], 'Main')
            self.assertEqual(out['venue_name'], 'ICML')
            self.assertEqual(out['venue']['name'], 'ICML')
            self.assertTrue(all(p['venue'] == 'ICML' and p['track'] == 'Main' for p in out['papers']))
            self.assertEqual([p['title'] for p in out['papers']], [f'Main {i}' for i in range(1, 6)])

        # Even if only Workshop <proceedings> exists before Main papers, Main papers must NOT get Workshop venue_name
        ws_proc_only_xml = multi_proc_xml.replace(
            '  <proceedings key="conf/icml/2024"><title>Proceedings of ICML 2024.</title><booktitle>ICML</booktitle><year>2024</year></proceedings>\n',
            '',
        )
        t_ws_proc = lambda url, timeout=20: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': ws_proc_only_xml.encode('utf-8')}
        out_no_main_proc = collector_mod.collect_panel('dblp', 'conf/icml/icml2024.xml', limit=5, track='Main', transport=t_ws_proc)
        self.assertEqual(out_no_main_proc['venue_name'], 'ICML')
        self.assertTrue(all(p['venue'] == 'ICML' for p in out_no_main_proc['papers']))

        # Bug 3 on DBLP HTML without literal word "Main" in <h2>
        std_html = """<!DOCTYPE html><html><body>
        <h1>ICML 2024</h1>
        <header><h2>Session 1: Optimization</h2></header>
        <ul class="publ-list">
          <li class="entry inproceedings" id="conf/icml/M1"><cite class="data"><span class="title">Main H1.</span><span itemprop="datePublished">2024</span></cite></li>
          <li class="entry inproceedings" id="conf/icml/M2"><cite class="data"><span class="title">Main H2.</span><span itemprop="datePublished">2024</span></cite></li>
          <li class="entry inproceedings" id="conf/icml/M3"><cite class="data"><span class="title">Main H3.</span><span itemprop="datePublished">2024</span></cite></li>
          <li class="entry inproceedings" id="conf/icml/M4"><cite class="data"><span class="title">Main H4.</span><span itemprop="datePublished">2024</span></cite></li>
          <li class="entry inproceedings" id="conf/icml/M5"><cite class="data"><span class="title">Main H5.</span><span itemprop="datePublished">2024</span></cite></li>
        </ul>
        <header><h2>Workshop Track</h2></header>
        <ul class="publ-list">
          <li class="entry inproceedings" id="conf/icml/W1"><cite class="data"><span class="title">WS H1.</span><span itemprop="datePublished">2024</span></cite></li>
        </ul></body></html>"""
        t_html = lambda url, timeout=20: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': std_html.encode('utf-8')}
        html_main = collector_mod.collect_panel('dblp', 'conf/icml/icml2024', limit=5, track='Main', transport=t_html)
        self.assertEqual(html_main['track'], 'Main')
        self.assertEqual(html_main['provenance']['track_filtered_out'], 1)
        self.assertEqual([p['title'] for p in html_main['papers']], [f'Main H{i}' for i in range(1, 6)])

        # --track Main on Workshop-only XML must raise insufficient_panel_papers (0 found)
        ws_only_xml = (
            '<?xml version="1.0" encoding="UTF-8"?><dblp>'
            + ''.join(
                f'<inproceedings key="conf/icml/W{i}"><author>W{i}</author><title>WS {i}.</title><year>2024</year><booktitle>ICML Workshop</booktitle></inproceedings>'
                for i in range(1, 6)
            )
            + '</dblp>'
        )
        t_ws_only = lambda url, timeout=20: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': ws_only_xml.encode('utf-8')}
        with self.assertRaises(collector_mod.PanelCollectionError) as ctx_ws:
            collector_mod.collect_panel('dblp', 'conf/icml/icml2024.xml', limit=5, track='Main', transport=t_ws_only)
        self.assertEqual(ctx_ws.exception.error_code, 'insufficient_panel_papers')
        self.assertEqual(ctx_ws.exception.details['found_count'], 0)

    def test_dblp_secondary_only_no_mixing_and_canonical_html_labels(self):
        # Bug 2: ACL Findings + ACL Demo must NEVER mix into one panel or mislabel Findings as Demo
        mixed_sec_xml = (
            '<?xml version="1.0" encoding="UTF-8"?><dblp>'
            + ''.join(
                f'<inproceedings key="conf/acl/F{i}"><author>F{i}</author><title>Findings {i}.</title><year>2024</year><booktitle>ACL Findings</booktitle></inproceedings>'
                for i in range(1, 6)
            )
            + ''.join(
                f'<inproceedings key="conf/acl/D{i}"><author>D{i}</author><title>Demo {i}.</title><year>2024</year><booktitle>ACL Demo</booktitle></inproceedings>'
                for i in range(1, 6)
            )
            + '</dblp>'
        )
        t_mixed_sec = lambda url, timeout=20: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': mixed_sec_xml.encode('utf-8')}
        out_sec = collector_mod.collect_panel('dblp', 'conf/acl/acl2024.xml', limit=5, transport=t_mixed_sec)
        self.assertEqual(out_sec['track'], 'Findings')
        self.assertEqual(out_sec['provenance']['track_filtered_out'], 5)
        self.assertEqual({p['section'] for p in out_sec['papers']}, {'ACL Findings'})

        # 3 Findings + 3 Demo must NOT combine to 6 papers to satisfy limit=5
        small_mixed_sec_xml = (
            '<?xml version="1.0" encoding="UTF-8"?><dblp>'
            + ''.join(
                f'<inproceedings key="conf/acl/F{i}"><author>F{i}</author><title>Findings {i}.</title><year>2024</year><booktitle>ACL Findings</booktitle></inproceedings>'
                for i in range(1, 4)
            )
            + ''.join(
                f'<inproceedings key="conf/acl/D{i}"><author>D{i}</author><title>Demo {i}.</title><year>2024</year><booktitle>ACL Demo</booktitle></inproceedings>'
                for i in range(1, 4)
            )
            + '</dblp>'
        )
        t_small_sec = lambda url, timeout=20: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': small_mixed_sec_xml.encode('utf-8')}
        with self.assertRaises(collector_mod.PanelCollectionError) as ctx_small:
            collector_mod.collect_panel('dblp', 'conf/acl/acl2024.xml', limit=5, transport=t_small_sec)
        self.assertEqual(ctx_small.exception.error_code, 'insufficient_panel_papers')
        self.assertEqual(ctx_small.exception.details['found_count'], 3)

        # DBLP HTML single secondary section & multi-secondary sections get canonical track labels (never raw <h2> or 'Workshop')
        single_sec_html = """<!DOCTYPE html><html><body>
        <h1>Findings of ACL 2024</h1>
        <header><h2>Findings of the Association for Computational Linguistics: ACL 2024</h2></header>
        <ul class="publ-list">""" + ''.join(
            f'<li class="entry inproceedings" id="conf/acl/F{i}"><cite class="data"><span class="title">F {i}.</span><span itemprop="datePublished">2024</span></cite></li>'
            for i in range(1, 6)
        ) + '</ul></body></html>'
        t_single_html = lambda url, timeout=20: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': single_sec_html.encode('utf-8')}
        out_single_html = collector_mod.collect_panel('dblp', 'conf/acl/findings2024', limit=5, transport=t_single_html)
        self.assertEqual(out_single_html['track'], 'Findings')

        multi_sec_html = """<!DOCTYPE html><html><body>
        <h1>ACL 2024 Companion</h1>
        <header><h2>ACL 2024 Findings</h2></header><ul class="publ-list">""" + ''.join(
            f'<li class="entry inproceedings" id="conf/acl/F{i}"><cite class="data"><span class="title">F {i}.</span><span itemprop="datePublished">2024</span></cite></li>'
            for i in range(1, 6)
        ) + '</ul><header><h2>ACL 2024 Demonstrations</h2></header><ul class="publ-list">' + ''.join(
            f'<li class="entry inproceedings" id="conf/acl/D{i}"><cite class="data"><span class="title">D {i}.</span><span itemprop="datePublished">2024</span></cite></li>'
            for i in range(1, 6)
        ) + '</ul></body></html>'
        t_multi_html = lambda url, timeout=20: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': multi_sec_html.encode('utf-8')}
        out_multi_html = collector_mod.collect_panel('dblp', 'conf/acl/acl2024comp', limit=5, transport=t_multi_html)
        self.assertEqual(out_multi_html['track'], 'Findings')
        self.assertEqual(out_multi_html['provenance']['track_filtered_out'], 5)
        self.assertEqual({p['section'] for p in out_multi_html['papers']}, {'ACL 2024 Findings'})

    def test_dblp_extended_secondary_track_parity_excludes_industry_and_benchmarks_from_main(self):
        # Bug 4: KDD Industry Track, Datasets and Benchmarks, SRW, etc. must NOT leak into Main
        for sec_label, expected_track in (
            ('KDD Industry Track', 'Industry'),
            ('NeurIPS Datasets and Benchmarks', 'Datasets and Benchmarks'),
            ('ACL SRW', 'SRW'),
            ('ICSE Doctoral Symposium', 'Doctoral Symposium'),
            ('CHI Extended Abstracts', 'Extended Abstracts'),
            ('ICML Posters', 'Posters'),
            ('ICML Position Papers', 'Position Papers'),
            ('WWW Adjunct', 'Adjunct'),
        ):
            mixed_xml = (
                '<?xml version="1.0" encoding="UTF-8"?><dblp>'
                + ''.join(
                    f'<inproceedings key="conf/x/S{i}"><author>S{i}</author><title>Sec {i}.</title><year>2024</year><booktitle>{sec_label}</booktitle></inproceedings>'
                    for i in range(1, 6)
                )
                + ''.join(
                    f'<inproceedings key="conf/x/M{i}"><author>M{i}</author><title>Main {i}.</title><year>2024</year><booktitle>KDD</booktitle></inproceedings>'
                    for i in range(1, 6)
                )
                + '</dblp>'
            )
            t_mix = lambda url, timeout=20, body=mixed_xml: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': body.encode('utf-8')}
            main_out = collector_mod.collect_panel('dblp', 'conf/x/2024.xml', limit=5, transport=t_mix)
            self.assertEqual(main_out['track'], 'Main', msg=sec_label)
            self.assertEqual(main_out['provenance']['track_filtered_out'], 5, msg=sec_label)
            self.assertEqual({p['section'] for p in main_out['papers']}, {'KDD'}, msg=sec_label)

            # Secondary-only XML with extended secondary label does not claim Main
            sec_only_xml = (
                '<?xml version="1.0" encoding="UTF-8"?><dblp>'
                + ''.join(
                    f'<inproceedings key="conf/x/S{i}"><author>S{i}</author><title>Sec {i}.</title><year>2024</year><booktitle>{sec_label}</booktitle></inproceedings>'
                    for i in range(1, 6)
                )
                + '</dblp>'
            )
            t_only = lambda url, timeout=20, body=sec_only_xml: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': body.encode('utf-8')}
            sec_out = collector_mod.collect_panel('dblp', 'conf/x/sec2024.xml', limit=5, transport=t_only)
            self.assertEqual(sec_out['track'], expected_track, msg=sec_label)

    def test_dblp_ampersand_datasets_benchmarks_demos_alias_and_colocated_isolation(self):
        # 1. DBLP XML & DBLP HTML with "NeurIPS Datasets & Benchmarks" (&amp;) must NEVER leak into Main
        db_xml = (
            '<?xml version="1.0" encoding="UTF-8"?><dblp>'
            '<proceedings key="conf/nips/2024db"><title>NeurIPS Datasets &amp; Benchmarks 2024.</title><booktitle>NeurIPS Datasets &amp; Benchmarks</booktitle><year>2024</year></proceedings>'
            '<proceedings key="conf/nips/2024"><title>Advances in Neural Information Processing Systems 37.</title><booktitle>NeurIPS</booktitle><year>2024</year></proceedings>'
            + ''.join(
                f'<inproceedings key="conf/nips/DB{i}"><author>D{i}</author><title>DB Paper {i}.</title><year>2024</year><booktitle>NeurIPS Datasets &amp; Benchmarks</booktitle></inproceedings>'
                for i in range(1, 6)
            )
            + ''.join(
                f'<inproceedings key="conf/nips/M{i}"><author>M{i}</author><title>Main Paper {i}.</title><year>2024</year><booktitle>NeurIPS</booktitle></inproceedings>'
                for i in range(1, 6)
            )
            + '</dblp>'
        )
        t_db_xml = lambda url, timeout=20: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': db_xml.encode('utf-8')}
        for trk in (None, 'Main', 'main'):
            out_main = collector_mod.collect_panel('dblp', 'conf/nips/neurips2024.xml', limit=5, track=trk, transport=t_db_xml)
            self.assertEqual(out_main['track'], 'Main')
            self.assertEqual(out_main['provenance']['track_filtered_out'], 5)
            self.assertEqual([p['title'] for p in out_main['papers']], [f'Main Paper {i}' for i in range(1, 6)])

        for db_trk in ('Datasets and Benchmarks', 'Datasets & Benchmarks'):
            out_db_sel = collector_mod.collect_panel('dblp', 'conf/nips/neurips2024.xml', limit=5, track=db_trk, transport=t_db_xml)
            self.assertEqual([p['title'] for p in out_db_sel['papers']], [f'DB Paper {i}' for i in range(1, 6)])
            self.assertEqual({p['section'] for p in out_db_sel['papers']}, {'NeurIPS Datasets & Benchmarks'})

        db_only_xml = (
            '<?xml version="1.0" encoding="UTF-8"?><dblp>'
            + ''.join(
                f'<inproceedings key="conf/nips/DB{i}"><author>D{i}</author><title>DB Paper {i}.</title><year>2024</year><booktitle>NeurIPS Datasets &amp; Benchmarks</booktitle></inproceedings>'
                for i in range(1, 6)
            )
            + '</dblp>'
        )
        t_db_only_xml = lambda url, timeout=20: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': db_only_xml.encode('utf-8')}
        out_db_iso = collector_mod.collect_panel('dblp', 'conf/nips/db2024.xml', limit=5, transport=t_db_only_xml)
        self.assertEqual(out_db_iso['track'], 'Datasets and Benchmarks')

        db_html = (
            '<!DOCTYPE html><html><body><h1>NeurIPS 2024</h1>'
            '<header><h2>NeurIPS Datasets &amp; Benchmarks</h2></header><ul class="publ-list">'
            + ''.join(
                f'<li class="entry inproceedings" id="conf/nips/DB{i}"><cite class="data"><span class="title">DB H{i}.</span><span itemprop="datePublished">2024</span></cite></li>'
                for i in range(1, 6)
            )
            + '</ul><header><h2>Session 1: Core</h2></header><ul class="publ-list">'
            + ''.join(
                f'<li class="entry inproceedings" id="conf/nips/M{i}"><cite class="data"><span class="title">Core H{i}.</span><span itemprop="datePublished">2024</span></cite></li>'
                for i in range(1, 6)
            )
            + '</ul></body></html>'
        )
        t_db_html = lambda url, timeout=20: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': db_html.encode('utf-8')}
        for trk in (None, 'Main'):
            out_html_main = collector_mod.collect_panel('dblp', 'conf/nips/neurips2024', limit=5, track=trk, transport=t_db_html)
            self.assertEqual(out_html_main['track'], 'Main')
            self.assertEqual(out_html_main['provenance']['track_filtered_out'], 5)
            self.assertEqual([p['title'] for p in out_html_main['papers']], [f'Core H{i}' for i in range(1, 6)])

        db_only_html = (
            '<!DOCTYPE html><html><body><h1>NeurIPS 2024 Datasets &amp; Benchmarks</h1>'
            '<header><h2>NeurIPS Datasets &amp; Benchmarks</h2></header><ul class="publ-list">'
            + ''.join(
                f'<li class="entry inproceedings" id="conf/nips/DB{i}"><cite class="data"><span class="title">DB H{i}.</span><span itemprop="datePublished">2024</span></cite></li>'
                for i in range(1, 6)
            )
            + '</ul></body></html>'
        )
        t_db_only_html = lambda url, timeout=20: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': db_only_html.encode('utf-8')}
        out_html_db_iso = collector_mod.collect_panel('dblp', 'conf/nips/db2024', limit=5, transport=t_db_only_html)
        self.assertEqual(out_html_db_iso['track'], 'Datasets and Benchmarks')

        # 2. --track Demos resolves Demo in both DBLP XML (ACL (Demo)) and DBLP HTML (System Demonstrations)
        demo_xml = (
            '<?xml version="1.0" encoding="UTF-8"?><dblp>'
            + ''.join(
                f'<inproceedings key="conf/acl/D{i}"><author>D{i}</author><title>Demo {i}.</title><year>2024</year><booktitle>ACL (Demo)</booktitle></inproceedings>'
                for i in range(1, 6)
            )
            + '</dblp>'
        )
        t_demo_xml = lambda url, timeout=20: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': demo_xml.encode('utf-8')}
        out_demos_xml = collector_mod.collect_panel('dblp', 'conf/acl/demo2024.xml', limit=5, track='Demos', transport=t_demo_xml)
        self.assertEqual(out_demos_xml['paper_count'], 5)
        self.assertEqual([p['title'] for p in out_demos_xml['papers']], [f'Demo {i}' for i in range(1, 6)])

        demo_html = (
            '<!DOCTYPE html><html><body><h1>ACL 2024 Companion</h1>'
            '<header><h2>System Demonstrations</h2></header><ul class="publ-list">'
            + ''.join(
                f'<li class="entry inproceedings" id="conf/acl/D{i}"><cite class="data"><span class="title">Demo H{i}.</span><span itemprop="datePublished">2024</span></cite></li>'
                for i in range(1, 6)
            )
            + '</ul></body></html>'
        )
        t_demo_html = lambda url, timeout=20: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': demo_html.encode('utf-8')}
        out_demos_html = collector_mod.collect_panel('dblp', 'conf/acl/demo2024', limit=5, track='Demos', transport=t_demo_html)
        self.assertEqual(out_demos_html['paper_count'], 5)
        self.assertEqual([p['title'] for p in out_demos_html['papers']], [f'Demo H{i}' for i in range(1, 6)])

        # 3. Co-located and Pre-conference Symposium get dedicated labels and never merge with Workshop
        for sec_label, expected_track in (
            ('AAAI Co-located Events', 'Co-located'),
            ('AAAI Co-located Workshops', 'Co-located'),
            ('SIGMOD Pre-conference Symposium', 'Pre-conference Symposium'),
        ):
            small_mix_xml = (
                '<?xml version="1.0" encoding="UTF-8"?><dblp>'
                + ''.join(
                    f'<inproceedings key="conf/x/W{i}"><author>W{i}</author><title>WS {i}.</title><year>2024</year><booktitle>ICML Workshop</booktitle></inproceedings>'
                    for i in range(1, 4)
                )
                + ''.join(
                    f'<inproceedings key="conf/x/C{i}"><author>C{i}</author><title>Other {i}.</title><year>2024</year><booktitle>{sec_label}</booktitle></inproceedings>'
                    for i in range(1, 4)
                )
                + '</dblp>'
            )
            t_small_mix = lambda url, timeout=20, body=small_mix_xml: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': body.encode('utf-8')}
            with self.assertRaises(collector_mod.PanelCollectionError) as ctx_no_merge:
                collector_mod.collect_panel('dblp', 'conf/x/mix2024.xml', limit=5, transport=t_small_mix)
            self.assertEqual(ctx_no_merge.exception.error_code, 'insufficient_panel_papers', msg=sec_label)
            self.assertEqual(ctx_no_merge.exception.details['found_count'], 3, msg=sec_label)

            iso_xml = (
                '<?xml version="1.0" encoding="UTF-8"?><dblp>'
                + ''.join(
                    f'<inproceedings key="conf/x/C{i}"><author>C{i}</author><title>Other {i}.</title><year>2024</year><booktitle>{sec_label}</booktitle></inproceedings>'
                    for i in range(1, 6)
                )
                + '</dblp>'
            )
            t_iso = lambda url, timeout=20, body=iso_xml: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': body.encode('utf-8')}
            out_iso = collector_mod.collect_panel('dblp', 'conf/x/iso2024.xml', limit=5, transport=t_iso)
            self.assertEqual(out_iso['track'], expected_track, msg=sec_label)

        # 4. --year filtering happens before _select_dblp_default_track on multi-year secondary TOC
        multi_yr_xml = (
            '<?xml version="1.0" encoding="UTF-8"?><dblp>'
            + ''.join(
                f'<inproceedings key="conf/x/W{i}"><author>W{i}</author><title>WS23 {i}.</title><year>2023</year><booktitle>ICML Workshop</booktitle></inproceedings>'
                for i in range(1, 7)
            )
            + ''.join(
                f'<inproceedings key="conf/x/F{i}"><author>F{i}</author><title>Find24 {i}.</title><year>2024</year><booktitle>ACL Findings</booktitle></inproceedings>'
                for i in range(1, 6)
            )
            + '</dblp>'
        )
        t_multi_yr = lambda url, timeout=20: {'status_code': 200, 'headers': {}, 'final_url': url, 'body': multi_yr_xml.encode('utf-8')}
        out_yr24 = collector_mod.collect_panel('dblp', 'conf/x/multi.xml', limit=5, year=2024, transport=t_multi_yr)
        self.assertEqual(out_yr24['track'], 'Findings')
        self.assertEqual(out_yr24['year'], 2024)
        self.assertEqual([p['title'] for p in out_yr24['papers']], [f'Find24 {i}' for i in range(1, 6)])


if __name__ == '__main__':
    unittest.main()
