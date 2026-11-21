"""Offline unit and CLI tests for the bundled ResearchRadar radar.py tool."""
from __future__ import annotations

import importlib.util
import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "research-scientist/modules/researchradar/problem-statement-finder/scripts/radar.py"
)


def load_radar():
    spec = importlib.util.spec_from_file_location("researchradar_radar", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["researchradar_radar"] = module
    spec.loader.exec_module(module)
    return module


def run_radar(radar_mod, argv: list[str]) -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    code = 0
    with redirect_stdout(out), redirect_stderr(err):
        try:
            radar_mod.main(argv)
        except SystemExit as exc:
            code = int(exc.code) if isinstance(exc.code, int) else 1
    return code, out.getvalue(), err.getvalue()


class BundledResearchRadarTests(unittest.TestCase):
    def test_quote_verification_requires_exact_words_and_case(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "reviews.json"
            source.write_text(
                json.dumps({"review": "The comparison omitted a matched baseline."}),
                encoding="utf-8",
            )
            yes = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "verify",
                    str(source),
                    "comparison omitted a matched baseline",
                ],
                capture_output=True,
                text=True,
            )
            no = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "verify",
                    str(source),
                    "Comparison omitted a matched baseline",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(yes.returncode, 0)
            self.assertTrue(json.loads(yes.stdout)["all_found"])
            self.assertEqual(no.returncode, 1)
            self.assertFalse(json.loads(no.stdout)["all_found"])

    def test_verify_nested_json_raw_text_and_whitespace(self):
        radar = load_radar()
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            nested = tmp / "nested.json"
            nested.write_text(
                json.dumps({"items": [{"text": "Line   one\n\tand   line two."}]}),
                encoding="utf-8",
            )
            rc_ok, out_ok, _ = run_radar(
                radar, ["verify", str(nested), "Line one and line two."]
            )
            self.assertEqual(rc_ok, 0)
            self.assertTrue(json.loads(out_ok)["all_found"])

            raw_txt = tmp / "raw.txt"
            raw_txt.write_text("{not valid json: Exact raw quote here.", encoding="utf-8")
            rc_partial, out_partial, _ = run_radar(
                radar, ["verify", str(raw_txt), "Exact raw quote here.", "Missing quote"]
            )
            self.assertEqual(rc_partial, 1)
            payload = json.loads(out_partial)
            self.assertFalse(payload["all_found"])
            self.assertTrue(payload["quotes"]["Exact raw quote here."])
            self.assertFalse(payload["quotes"]["Missing quote"])

    def test_fetch_and_stream_lines_edge_cases(self):
        radar = load_radar()

        class FakeResp:
            def __init__(self, status: int, data: bytes):
                self.status = status
                self._chunks = [data[i : i + 5] for i in range(0, len(data), 5)] + [b""]
                self._idx = 0

            def read(self, _n: int = -1):
                if len(self._chunks) == 2 and self._idx == 0 and _n == -1:
                    self._idx = 2
                    return self._chunks[0]
                if _n == -1:
                    return b"".join(self._chunks)
                val = self._chunks[self._idx]
                self._idx += 1
                return val

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with mock.patch.object(radar.time, "sleep") as sleep_mock:
            radar._last_request = radar.time.monotonic()
            with mock.patch.object(
                radar.urllib.request,
                "urlopen",
                return_value=FakeResp(200, b"hello \xc3\xa9"),
            ):
                status, body = radar.fetch("https://example.org/ok", pace=5.0)
            self.assertEqual(status, 200)
            self.assertEqual(body, "hello \u00e9")
            sleep_mock.assert_called()

            with mock.patch.object(
                radar.urllib.request,
                "urlopen",
                side_effect=urllib.error.HTTPError("https://example.org/429", 429, "Too Many", {}, None),
            ):
                self.assertEqual(radar.fetch("https://example.org/429", pace=0.0), (429, ""))

            err = io.StringIO()
            with redirect_stderr(err), mock.patch.object(
                radar.urllib.request,
                "urlopen",
                side_effect=urllib.error.URLError("offline"),
            ):
                self.assertEqual(radar.fetch("https://example.org/err", pace=0.0), (0, ""))
            self.assertIn("network failure", err.getvalue())

        seen_reqs = []

        def fake_stream_urlopen(req, timeout=120):
            seen_reqs.append(req)
            return FakeResp(200, b'partial_prefix\n{"a": 1}\n{"b": 2}\ntrailing_unterminated')

        with mock.patch.object(radar.urllib.request, "urlopen", side_effect=fake_stream_urlopen):
            lines_offset = list(radar.stream_lines("https://example.org/data.jsonl", start=100, max_bytes=50))
            self.assertEqual(seen_reqs[0].headers.get("Range"), "bytes=100-149")
            self.assertEqual(lines_offset, [b'{"a": 1}', b'{"b": 2}'])

            lines_zero = list(radar.stream_lines("https://example.org/data.jsonl", start=0))
            self.assertEqual(lines_zero, [b"partial_prefix", b'{"a": 1}', b'{"b": 2}'])

    def test_check_subcommand_and_index_states(self):
        radar = load_radar()

        def fake_fetch(url, **_kwargs):
            if "arxiv" in url:
                return (200, "")
            if "openalex" in url:
                return (429, "")
            if "neurips" in url:
                return (500, "")
            if "elifesciences" in url:
                return (0, "")
            return (200, "")

        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            with mock.patch.object(radar, "CACHE", cache_dir), mock.patch.object(
                radar, "fetch", side_effect=fake_fetch
            ):
                rc1, out1, _ = run_radar(radar, ["check"])
                self.assertEqual(rc1, 0)
                d1 = json.loads(out1)
                self.assertEqual(d1["arxiv"], "ok")
                self.assertEqual(d1["openalex"], "rate limited")
                self.assertEqual(d1["neurips_reviews"], "failed (HTTP 500)")
                self.assertEqual(d1["elife"], "failed (HTTP 0)")
                self.assertIn("not built", d1["iclr_index"])
                self.assertIn("challenge", d1["openreview_notes"])

                conn = radar.open_snor(cache_dir / "snor.sqlite3")
                conn.close()
                rc2, out2, _ = run_radar(radar, ["check"])
                self.assertEqual(rc2, 0)
                self.assertIn("not ready", json.loads(out2)["iclr_index"])

                conn = radar.open_snor(cache_dir / "snor.sqlite3")
                conn.execute("INSERT INTO papers (id, title) VALUES ('p1', 'Paper 1')")
                conn.execute("INSERT OR REPLACE INTO meta VALUES ('mode', 'sample')")
                conn.commit()
                conn.close()
                rc3, out3, _ = run_radar(radar, ["check"])
                self.assertEqual(rc3, 0)
                self.assertEqual(json.loads(out3)["iclr_index"], "built (sample): 1 papers")

    def test_papers_dedup_failures_and_hints(self):
        radar = load_radar()
        arxiv_xml = """<feed>
            <entry><id>http://arxiv.org/api/errors</id><title>Error</title></entry>
            <entry><id>http://arxiv.org/abs/2401.00001v2</id><title>Graph Oversmoothing Study</title>
                   <summary>We study oversmoothing.</summary><published>2024-01-01</published></entry>
        </feed>"""
        oa_json = json.dumps(
            {
                "results": [
                    {
                        "id": "https://openalex.org/W1",
                        "title": "Graph Oversmoothing Study!",
                        "publication_year": 2024,
                        "cited_by_count": 10,
                        "doi": "https://doi.org/10.1000/1",
                        "primary_location": {"source": {"display_name": "NeurIPS"}},
                        "abstract_inverted_index": {"study": [1], "We": [0]},
                    },
                    {
                        "id": "https://openalex.org/W2",
                        "title": "Distinct Graph Paper",
                        "publication_year": 2024,
                        "cited_by_count": 5,
                        "abstract_inverted_index": {"Distinct": [0], "work": [1]},
                    },
                ]
            }
        )
        seen_urls = []

        def fake_fetch(url, **_kwargs):
            seen_urls.append(url)
            if "export.arxiv.org" in url:
                return (200, arxiv_xml)
            if "api.openalex.org" in url:
                return (200, oa_json)
            return (0, "")

        with mock.patch.object(radar, "fetch", side_effect=fake_fetch):
            rc, out, _ = run_radar(
                radar, ["papers", "graph", "oversmoothing", "depth", "theory", "bounds", "--since", "2022", "--limit", "5"]
            )
            self.assertEqual(rc, 0)
            data = json.loads(out)
            self.assertEqual(data["status"], {"arxiv": "ok", "openalex": "ok"})
            self.assertEqual(data["count"], 2)
            self.assertEqual(data["papers"][0]["source"], "arxiv")
            self.assertEqual(data["papers"][0]["arxiv_id"], "2401.00001")
            self.assertFalse(data["papers"][0]["peer_reviewed"])
            self.assertEqual(data["papers"][1]["abstract"], "Distinct work")
            self.assertIn("2 to 4 words", data["hint"])
            self.assertTrue(any("submittedDate" in u for u in seen_urls))
            self.assertTrue(any("from_publication_date" in u for u in seen_urls))

        with mock.patch.object(radar, "fetch", side_effect=[(503, ""), (200, "not-json")]):
            rc_err, out_err, _ = run_radar(radar, ["papers", "rare"])
            self.assertEqual(rc_err, 0)
            d_err = json.loads(out_err)
            self.assertEqual(d_err["status"]["arxiv"], "failed (HTTP 503)")
            self.assertEqual(d_err["status"]["openalex"], "failed (unreadable response)")
            self.assertEqual(d_err["count"], 0)
            self.assertIn("No results for this wording", d_err["hint"])

    def test_citing_subcommand(self):
        radar = load_radar()
        seen = []

        def fake_ok(url, **_kwargs):
            seen.append(url)
            return (
                200,
                json.dumps(
                    {
                        "results": [
                            {
                                "id": "https://openalex.org/W999",
                                "title": "Citing Paper",
                                "publication_year": 2024,
                                "cited_by_count": 42,
                            }
                        ]
                    }
                ),
            )

        with mock.patch.object(radar, "fetch", side_effect=fake_ok):
            rc, out, _ = run_radar(radar, ["citing", "W123", "--since", "2023", "--limit", "5"])
            self.assertEqual(rc, 0)
            data = json.loads(out)
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["count"], 1)
            self.assertIn("cites%3AW123%2Cfrom_publication_date%3A2023-01-01", seen[0])

        with mock.patch.object(radar, "fetch", return_value=(500, "")):
            rc_fail, out_fail, _ = run_radar(radar, ["citing", "W123"])
            self.assertEqual(rc_fail, 0)
            self.assertEqual(json.loads(out_fail)["status"], "failed (HTTP 500)")

    def test_limits_subcommand(self):
        radar = load_radar()
        html_doc = """<html><body><article class="ltx_page_main">
            <script>var ignored = "future work";</script>
            <h2>1 Introduction</h2><p>Background text.</p>
            <h2>5 Limitations and Future Work</h2>
            <p>Our approach does not scale to graphs with over one million nodes in memory.
            Evaluation on non-English corpora remains open for future work.</p>
            <table><tr><td>remains open table cell ignored</td></tr></table>
        </article></body></html>"""

        seen = []

        def fake_ok(url, **_kwargs):
            seen.append(url)
            return (200, html_doc)

        with mock.patch.object(radar, "fetch", side_effect=fake_ok):
            rc, out, _ = run_radar(radar, ["limits", "https://arxiv.org/abs/2310.06825v3"])
            self.assertEqual(rc, 0)
            self.assertEqual(seen[0], "https://arxiv.org/html/2310.06825")
            data = json.loads(out)
            self.assertEqual(data["status"], "ok")
            self.assertEqual(len(data["sections"]), 1)
            self.assertTrue(any("does not scale" in s for s in data["admissions"]))

        with mock.patch.object(radar, "fetch", return_value=(404, "<html>not found</html>")):
            rc_404, out_404, _ = run_radar(radar, ["limits", "2310.06825"])
            self.assertEqual(rc_404, 0)
            d_404 = json.loads(out_404)
            self.assertIn("no HTML version", d_404["status"])
            self.assertEqual(d_404["sections"], [])

    def test_neurips_caching_matching_and_fallback(self):
        radar = load_radar()
        listing_2020 = (
            '<a href="/paper_files/paper/2020/hash/aaaaaaaaaaaaaaaa-Abstract.html">Topographic Mapping</a>'
            '<a href="/paper_files/paper/2020/hash/bbbbbbbbbbbbbbbb-Abstract.html">Sparse Graphs</a>'
        )
        listing_2019 = (
            '<a href="/paper_files/paper/2019/hash/cccccccccccccccc-Abstract.html">Graph Calibration</a>'
            '<a href="/paper_files/paper/2019/hash/dddddddddddddddd-Abstract.html">Graph Without Reviews</a>'
        )
        calls = []

        def fake_fetch(url, **_kwargs):
            calls.append(url)
            if url.endswith("/2020"):
                return (200, listing_2020)
            if url.endswith("/2019"):
                return (200, listing_2019)
            if url.endswith("bbbbbbbbbbbbbbbb-Reviews.html"):
                return (404, "")
            if url.endswith("bbbbbbbbbbbbbbbb-Review.html"):
                return (200, "Header\nReviewer 1\nNeeds stronger baseline.\n")
            if url.endswith("cccccccccccccccc-Reviews.html"):
                return (200, "Reviewer 1\n" + ("X" * 200))
            return (404, "")

        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            with mock.patch.object(radar, "CACHE", cache_dir), mock.patch.object(
                radar, "fetch", side_effect=fake_fetch
            ):
                rc, out, _ = run_radar(
                    radar, ["neurips", "graph", "--years", "2020,2019", "--limit", "5", "--max-chars", "40"]
                )
                self.assertEqual(rc, 0)
                data = json.loads(out)
                self.assertEqual(data["count"], 2)
                self.assertEqual(data["matched_without_reviews"], 1)
                titles = [p["title"] for p in data["papers"]]
                self.assertNotIn("Topographic Mapping", titles)
                self.assertEqual(titles, ["Sparse Graphs", "Graph Calibration"])
                self.assertLessEqual(len(data["papers"][1]["reviews"]), 40)
                self.assertTrue((cache_dir / "neurips-2020.html").is_file())

                calls.clear()
                rc2, _, _ = run_radar(radar, ["neurips", "graph", "--years", "2020,2019"])
                self.assertEqual(rc2, 0)
                self.assertFalse(any(u.endswith("/2020") or u.endswith("/2019") for u in calls))

    def test_neurips_listing_http_error_not_cached(self):
        radar = load_radar()

        def fake_fetch(url, **_kwargs):
            if url.endswith("/2021"):
                return (404, "not found")
            if url.endswith("/2022"):
                return (500, "internal error")
            return (500, "")

        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            with mock.patch.object(radar, "CACHE", cache_dir), mock.patch.object(
                radar, "fetch", side_effect=fake_fetch
            ):
                rc, out, err = run_radar(radar, ["neurips", "graph", "--years", "2021,2022"])
                self.assertEqual(rc, 0)
                data = json.loads(out)
                self.assertEqual(data["count"], 0)
                self.assertEqual(data["papers"], [])
                self.assertIn("NeurIPS 2021: listing unavailable (HTTP 404)", err)
                self.assertIn("NeurIPS 2022: listing unavailable (HTTP 500)", err)
                self.assertFalse((cache_dir / "neurips-2021.html").exists())
                self.assertFalse((cache_dir / "neurips-2022.html").exists())

    def test_elife_subcommand(self):
        radar = load_radar()

        def fake_fetch(url, **_kwargs):
            if "search?" in url:
                return (200, json.dumps({"items": [{"id": "101"}, {"id": "102"}]}))
            if "/articles/101" in url:
                return (200, json.dumps({"title": "No Letter", "published": "2024-01-01"}))
            if "/articles/102" in url:
                return (
                    200,
                    json.dumps(
                        {
                            "title": "<i>Memory</i> Dynamics",
                            "published": "2023-06-01",
                            "decisionLetter": {"content": [{"text": "Reviewer asked for <b>controls</b>."}]},
                            "authorResponse": [{"text": "We added controls."}],
                        }
                    ),
                )
            return (404, "")

        with mock.patch.object(radar, "fetch", side_effect=fake_fetch):
            rc, out, _ = run_radar(radar, ["elife", "memory", "--limit", "5"])
            self.assertEqual(rc, 0)
            data = json.loads(out)
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["count"], 1)
            self.assertEqual(data["papers"][0]["title"], "Memory Dynamics")
            self.assertEqual(data["papers"][0]["year"], 2023)
            self.assertIn("controls", data["papers"][0]["reviews"])
            self.assertIn("We added controls.", data["papers"][0]["author_response"])

        with mock.patch.object(radar, "fetch", return_value=(502, "")):
            rc_fail, out_fail, _ = run_radar(radar, ["elife", "memory"])
            self.assertEqual(rc_fail, 0)
            self.assertEqual(json.loads(out_fail)["status"], "failed (HTTP 502)")

    def test_iclr_build_and_iclr_query(self):
        radar = load_radar()
        norm_papers = [
            json.dumps(
                {
                    "id": "p_acc",
                    "title": "Graph Benchmark Calibration",
                    "abstract": "Calibration on graph models.",
                    "keywords": "graph calibration",
                    "accepted": 1,
                    "raw_decision": "Accept (Poster)",
                    "conference_name": "iclr",
                    "conference_year": 2024,
                    "review_score_avg": 7.5,
                }
            ).encode("utf-8"),
            json.dumps(
                {
                    "id": "p_with",
                    "title": "Withdrawn Graph Idea",
                    "abstract": "Graph idea.",
                    "keywords": "graph",
                    "accepted": 0,
                    "raw_decision": "Withdrawn by authors",
                    "conference_name": "iclr",
                    "conference_year": 2024,
                }
            ).encode("utf-8"),
        ]
        norm_comments = [
            json.dumps(
                {
                    "paper_id": "p_acc",
                    "is_review": True,
                    "numeric_rating": 8,
                    "signature": "Reviewer_XYZ_SECRET",
                    "content": {"summary": "Strong empirical graph evaluation across datasets.", "rating": "8"},
                }
            ).encode("utf-8"),
            json.dumps(
                {
                    "paper_id": "p_with",
                    "is_review": True,
                    "numeric_rating": 4,
                    "content": "{'weaknesses': 'Missing key baseline comparison on standard graphs.'}",
                }
            ).encode("utf-8"),
        ]
        failed_matches = [
            json.dumps(
                {
                    "id": "p_rej",
                    "title": "Rejected Graph Method",
                    "abstract": "Graph pruning method.",
                    "keywords": "graph pruning",
                    "accepted": 0,
                    "venueid": "Reject",
                    "conference": "iclr2025",
                    "raw": {
                        "details": {
                            "directReplies": [
                                {
                                    "invitations": ["ICLR.cc/2025/-/Official_Review"],
                                    "content": {
                                        "weaknesses": {"value": "Lacks matched compute baseline on graph benchmarks."},
                                        "rating": {"value": "3: reject"},
                                        "signature": "Reviewer_SECRET",
                                    },
                                },
                                {
                                    "invitations": ["ICLR.cc/2025/-/Meta_Review"],
                                    "content": {"comment": {"value": "Meta review text that is long enough."}},
                                },
                            ]
                        }
                    },
                }
            ).encode("utf-8")
        ]

        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            with mock.patch.object(radar, "CACHE", cache_dir):
                rc_noflag, _, err_noflag = run_radar(radar, ["iclr-build"])
                self.assertEqual(rc_noflag, 2)
                self.assertIn("--yes-download-2.2gb", err_noflag)

                rc_unbuilt, out_unbuilt, _ = run_radar(radar, ["iclr", "graph"])
                self.assertEqual(rc_unbuilt, 0)
                self.assertEqual(json.loads(out_unbuilt)["status"], "not built")

                stream_calls = []

                def fake_stream(url, start=0, max_bytes=None):
                    stream_calls.append((url, start, max_bytes))
                    if "normalized_papers" in url:
                        return iter(norm_papers)
                    if "normalized_comments" in url:
                        return iter(norm_comments)
                    return iter(failed_matches)

                with mock.patch.object(radar, "stream_lines", side_effect=fake_stream):
                    rc_sample, out_sample, _ = run_radar(radar, ["iclr-build", "--sample"])
                    self.assertEqual(rc_sample, 0)
                    d_sample = json.loads(out_sample)
                    self.assertEqual(d_sample["mode"], "sample")
                    self.assertEqual(d_sample["papers"], 3)
                    self.assertTrue(all(c[1] > 0 and c[2] == 30 * 1024 * 1024 for c in stream_calls))

                rc_q_sample, out_q_sample, _ = run_radar(
                    radar, ["iclr", "graph", "--outcome", "both", "--conference", "iclr", "--since", "2024", "--limit", "5"]
                )
                self.assertEqual(rc_q_sample, 0)
                dq_sample = json.loads(out_q_sample)
                self.assertIn("SAMPLE index", dq_sample["warning"])
                outcomes = {p["outcome"] for p in dq_sample["papers"]}
                self.assertEqual(outcomes, {"accepted", "rejected"})
                joined_reviews = "\n".join(p["reviews"] for p in dq_sample["papers"])
                self.assertNotIn("Reviewer_XYZ_SECRET", joined_reviews)
                self.assertNotIn("Meta review text", joined_reviews)

                stream_calls.clear()
                with mock.patch.object(radar, "stream_lines", side_effect=fake_stream):
                    rc_full, out_full, _ = run_radar(radar, ["iclr-build", "--yes-download-2.2gb"])
                    self.assertEqual(rc_full, 0)
                    self.assertEqual(json.loads(out_full)["mode"], "full")
                    self.assertTrue(all(c[1] == 0 and c[2] is None for c in stream_calls))

                rc_q_all, out_q_all, _ = run_radar(radar, ["iclr", "graph", "--outcome", "all"])
                self.assertEqual(rc_q_all, 0)
                dq_all = json.loads(out_q_all)
                self.assertIsNone(dq_all["warning"])
                self.assertEqual({p["outcome"] for p in dq_all["papers"]}, {"accepted", "rejected", "withdrawn"})

                with mock.patch.object(
                    radar, "stream_lines", side_effect=urllib.error.URLError("dropped")
                ):
                    rc_net_err, out_net_err, _ = run_radar(radar, ["iclr-build", "--sample"])
                    self.assertEqual(rc_net_err, 1)
                    self.assertIn("build failed", json.loads(out_net_err)["status"])

                conn = sqlite3.connect(cache_dir / "snor.sqlite3")
                conn.execute("DELETE FROM meta")
                conn.commit()
                conn.close()
                rc_not_ready, out_not_ready, _ = run_radar(radar, ["iclr", "graph"])
                self.assertEqual(rc_not_ready, 0)
                self.assertEqual(json.loads(out_not_ready)["status"], "not ready")


if __name__ == "__main__":
    unittest.main()
