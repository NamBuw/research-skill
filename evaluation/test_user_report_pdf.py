"""Tests for concise, plain-language, multilingual LaTeX-to-PDF user report generation."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "research-scientist" / "scripts" / "report_latex_pdf.py"
REFS_DIR = ROOT / "research-scientist" / "references"

spec = importlib.util.spec_from_file_location("report_latex_pdf", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _clean_en_payload() -> dict:
    return {
        "schema": "research_scientist_executive_report_v1",
        "report_type": "gap_audit",
        "lang": "en",
        "title": "Split-Leakage Audit on Retrieval Baseline",
        "verdict": {
            "status": "fail",
            "summary": "Accuracy drops from 84.1% to 61.3% after fixing duplicate IDs across splits [logs/run_02.json].",
            "evidence_refs": ["K1"],
        },
        "parsimony_check": {
            "simplest_alternative": "Deduplicating splits matches the custom regularizer without extra layers.",
            "problem_inflation_check": "Observed gain came from split overlap, not a model gap.",
            "verdict": "keep_simple",
        },
        "key_evidence": [
            {
                "id": "K1",
                "claim": "Clean split F1 score",
                "value": "61.3%",
                "status": "verified",
                "evidence": "Run log r-02",
                "source_refs": ["S1"],
                "locator": "logs/run_02.json#f1",
            },
            {
                "id": "K2",
                "claim": "Prior baseline comparison",
                "value": "61.0% F1",
                "status": "verified",
                "evidence": "Chen (2024)",
                "source_refs": ["S1"],
                "locator": "Table 2, p. 5",
                "source_url": "https://example.org/paper?id=1&v=2#sec",
            },
        ],
        "flaws_and_risks": [
            {
                "id": "R1",
                "severity": "critical",
                "summary": "142 duplicate IDs appear in both train and test splits.",
                "locator": "diagnostics/splits.json",
            }
        ],
        "next_steps": [
            {
                "step": 1,
                "action": "Re-run clean split across 3 random seeds.",
                "target": "logs/run_03.json",
            }
        ],
        "metadata": {
            "scope": "QA retrieval benchmark, 2024-2026",
            "search_date": "2026-11-21",
            "coverage_limits": "Bounded to arXiv and OpenAlex; S2 key absent.",
            "reading_basis": "full_text",
        },
        "sources": [
            {"id": "S1", "title": "Clean Split Audit Note", "locator": "logs/run_02.json", "url": "https://example.org/audit"}
        ],
    }


def _clean_vi_payload() -> dict:
    return {
        "schema": "research_scientist_executive_report_v1",
        "report_type": "gap_audit",
        "lang": "vi",
        "title": "Kiểm tra rò rỉ dữ liệu trên mô hình RAG",
        "verdict": {
            "status": "fail",
            "summary": "Độ chính xác giảm từ 84.1% xuống 61.3% sau khi xóa mẫu trùng lặp [logs/run_02.json].",
            "evidence_refs": ["K1"],
        },
        "simplest_alternative": "Chỉ cần lọc trùng lặp trước khi chia tập, không cần thêm mạng nơ-ron phụ.",
        "key_evidence": [
            {
                "id": "K1",
                "claim": "Chỉ số F1 trên tập sạch",
                "value": "61.3%",
                "status": "verified",
                "evidence": "Nhật ký chạy r-02",
                "source_refs": ["S1"],
                "locator": "logs/run_02.json#f1",
            },
            {
                "id": "K2",
                "claim": "Kiểm thử đầy đủ dấu tiếng Việt: ắ ằ ẳ ẵ ặ ề ệ ồ ỗ ử ự đ Đ",
                "value": "Đạt",
                "status": "verified",
                "evidence": "Bảng đối chiếu",
                "source_refs": ["S1"],
                "locator": "Bảng 1, trang 2",
                "source_url": "https://example.org/vi_test?a=1&b=2#muc",
            },
        ],
        "flaws_and_risks": [
            {
                "id": "R1",
                "severity": "critical",
                "summary": "Phát hiện 142 văn bản trùng lặp giữa tập huấn luyện và tập kiểm tra.",
                "locator": "diagnostics/splits.json",
            }
        ],
        "next_steps": [
            {
                "step": 1,
                "action": "Chạy lại mô hình gốc trên tập đã tách sạch với 3 seed.",
                "target": "logs/run_03.json",
            }
        ],
        "metadata": {
            "scope": "Tập kiểm thử RAG tiếng Việt, 2026",
            "search_date": "2026-11-21",
            "coverage_limits": "Giới hạn trong arXiv và OpenAlex.",
            "reading_basis": "full_text",
        },
        "sources": [
            {"id": "S1", "title": "Nguyễn Văn Ánh — Báo cáo kiểm thử", "locator": "logs/run_02.json", "url": "https://example.org/s1"}
        ],
    }


class UserReportPdfTests(unittest.TestCase):
    def test_import_clean_and_help_cli(self):
        self.assertTrue(callable(module.lint_report))
        self.assertTrue(callable(module.detect_language))
        self.assertTrue(callable(module.normalize_report_input))
        self.assertTrue(callable(module.generate_report))
        proc = run_cli("--help")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for flag in ("--input", "--out", "--tex-out", "--lang", "--input-text", "--engine", "--strict", "--json", "--compact"):
            self.assertIn(flag, proc.stdout)

    def test_language_detection_code_switching_and_overrides(self):
        mixed_vi_prompt = (
            "Hãy kiểm tra gap của paper RAG dùng LLM transformer, "
            "đánh giá baseline F1, ablation và data leakage trên benchmark"
        )
        res_vi = module.detect_language(text=mixed_vi_prompt, requested="auto")
        self.assertEqual(res_vi["lang"], "vi")
        self.assertEqual(res_vi["source"], "input_text")

        res_json_vi = module.detect_language(payload={"title": "Kiểm tra lỗi", "verdict": "Không đạt do rò rỉ dữ liệu"})
        self.assertEqual(res_json_vi["lang"], "vi")

        res_en = module.detect_language(text="Evaluate the baseline F1 score and split leakage in this paper.")
        self.assertEqual(res_en["lang"], "en")

        res_fr = module.detect_language(text="Résumé et évaluation des résultats avec les données.")
        self.assertEqual(res_fr["lang"], "fr")

        res_explicit = module.detect_language(text=mixed_vi_prompt, requested="fr")
        self.assertEqual(res_explicit["lang"], "fr")
        self.assertEqual(res_explicit["source"], "explicit")

    def test_concise_grounded_vi_and_en_pass_strict(self):
        for payload, expected_lang in ((_clean_en_payload(), "en"), (_clean_vi_payload(), "vi")):
            lint_res = module.lint_report(payload)
            self.assertTrue(lint_res["passed"], lint_res)
            self.assertEqual(lint_res["error_count"], 0, lint_res["findings"])
            self.assertEqual(lint_res["lang"], expected_lang)

    def test_strict_rejects_bloat_jargon_filler_sycophancy_and_ungrounded(self):
        long_sentence = " ".join(["word"] * 35) + "."
        bad_cases = [
            ("SENTENCE_TOO_LONG", {"title": "Audit", "verdict": long_sentence}),
            ("JARGON_AI_BUZZWORD", {"title": "Audit", "verdict": "This synergistic paradigm leverages an ontological tapestry."}),
            ("JARGON_VI_BUZZWORD", {"title": "Kiểm tra", "verdict": "Phương pháp mang tính đột phá trong hệ sinh thái đa chiều."}),
            ("FILLER_TRANSITION", {"title": "Audit", "verdict": "It is worth noting that the baseline fails [Table 1]."}),
            ("FILLER_TRANSITION", {"title": "Kiểm tra", "verdict": "Cần lưu ý rằng mô hình bị rò rỉ dữ liệu [Bảng 1]."}),
            ("NOMINALIZATION", {"title": "Audit", "verdict": "The utilization of a clean split fixes the error [Table 1]."}),
            ("NOMINALIZATION", {"title": "Kiểm tra", "verdict": "Việc tiến hành thực hiện tách tập dữ liệu giúp sửa lỗi [Bảng 1]."}),
            ("SYC_FLATTERY", {"title": "Audit", "verdict": "Great idea! You're completely right about this baseline."}),
            ("SYC_FLATTERY", {"title": "Kiểm tra", "verdict": "Ý tưởng xuất sắc và kết quả rất ấn tượng."}),
            ("SYC_PRAISE_SANDWICH", {"title": "Kiểm tra", "verdict": "Cách làm hay tuy nhiên dữ liệu bị lỗi rò rỉ nghiêm trọng."}),
            ("RPT_GRAND_BRANDING", {"title": "Audit", "verdict": "We evaluate HyperUnifiedCascade on QA [Table 1]."}),
            ("RPT_PLACEHOLDER", {"title": "Audit", "verdict": "TODO: finish verifying baseline [Table 1]."}),
            ("STRUCT_MISSING_VERDICT", {"title": "Audit", "key_evidence": [{"claim": "F1", "value": "0.8", "locator": "log"}]}),
            ("UNGROUNDED_NUMERIC_CLAIM", {"title": "Audit", "verdict": "Accuracy increased by 14.2% across tests."}),
            ("UNGROUNDED_CITATION", {"title": "Audit", "verdict": "Prior work (Smith et al., 2024) agrees.", "key_evidence": [{"claim": "Smith et al., 2024 baseline", "value": "ok", "evidence": ""}]}),
            ("MISSING_EVIDENCE_LOCATOR", {"title": "Audit", "verdict": "Baseline fails.", "key_evidence": [{"claim": "Clean split", "value": "low"}]}),
            ("JARGON_AI_BUZZWORD", {**_clean_en_payload(), "parsimony_check": "This holistic ecosystem leverages a paradigm shift."}),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            for idx, (expected_pid, bad_payload) in enumerate(bad_cases):
                res = module.lint_report(bad_payload)
                pids = {f["pattern_id"] for f in res["findings"]}
                self.assertFalse(res["passed"], f"Expected failure for {expected_pid}, got {res}")
                self.assertIn(expected_pid, pids, f"Missing {expected_pid} in {pids} for case {idx}")

                in_json = tmp / f"bad_{idx}.json"
                out_pdf = tmp / f"bad_{idx}.pdf"
                in_json.write_text(json.dumps(bad_payload, ensure_ascii=False), encoding="utf-8")
                proc = run_cli("--input", str(in_json), "--out", str(out_pdf), "--strict", "--json")
                self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
                receipt = json.loads(proc.stdout)
                self.assertEqual(receipt["status"], "lint_failed")
                self.assertFalse(out_pdf.exists(), f"Strict rejection must not emit {out_pdf}")

    def test_domain_term_exemptions_pass_strict(self):
        payload = {
            "title": "Domain Term Exemption Check",
            "verdict": {
                "status": "pass",
                "summary": (
                    "We compute leverage scores using robust optimization over the loss landscape "
                    "with an attention gate and an API key [logs/run.json]."
                ),
                "evidence_refs": ["K1"],
            },
            "key_evidence": [
                {
                    "id": "K1",
                    "claim": "Statistical leverage diagnostic",
                    "value": "0.12",
                    "status": "verified",
                    "locator": "logs/run.json",
                }
            ],
        }
        res = module.lint_report(payload)
        self.assertTrue(res["passed"], res["findings"])
        self.assertEqual(res["error_count"], 0)
        self.assertEqual(res["warn_count"], 0)

    def test_upstream_schema_normalization(self):
        gap_data = json.loads((REFS_DIR / "gap-record.schema-example.json").read_text(encoding="utf-8"))
        norm_gap = module.normalize_report_input(gap_data)
        self.assertEqual(norm_gap["report_type"], "gap_audit")
        self.assertEqual(norm_gap["verdict"]["status"], "supported")
        self.assertGreaterEqual(len(norm_gap["key_evidence"]), 1)

        venue_data = json.loads((REFS_DIR / "venue-novelty-profile.fixture.json").read_text(encoding="utf-8"))
        norm_venue = module.normalize_report_input(venue_data)
        self.assertEqual(norm_venue["report_type"], "novelty_scoring")
        self.assertIn("6/10", norm_venue["verdict"]["summary"])
        self.assertGreaterEqual(len(norm_venue["key_evidence"]), 2)

    def test_end_to_end_vietnamese_and_english_pdf_compilation_and_fitz(self):
        import fitz

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            # 1. Vietnamese report via mixed VI+EN --input-text and --strict
            vi_json = tmp / "vi.json"
            vi_pdf = tmp / "vi.pdf"
            vi_tex = tmp / "vi.tex"
            vi_payload = _clean_vi_payload()
            vi_payload["lang"] = "auto"
            vi_json.write_text(json.dumps(vi_payload, ensure_ascii=False), encoding="utf-8")

            proc_vi = run_cli(
                "--input", str(vi_json),
                "--out", str(vi_pdf),
                "--tex-out", str(vi_tex),
                "--input-text", "Hãy kiểm tra gap của paper RAG dùng LLM transformer và xuất báo cáo ngắn gọn",
                "--strict",
                "--json",
            )
            self.assertEqual(proc_vi.returncode, 0, proc_vi.stdout + proc_vi.stderr)
            rec_vi = json.loads(proc_vi.stdout)
            self.assertEqual(rec_vi["status"], "ok")
            self.assertEqual(rec_vi["lang"], "vi")
            self.assertTrue(rec_vi["diacritics_verified"])
            self.assertGreaterEqual(rec_vi["page_count"], 1)
            self.assertTrue(vi_pdf.is_file() and vi_pdf.stat().st_size > 1000)
            self.assertTrue(vi_tex.is_file())
            self.assertIn("Phương án đơn giản hơn", vi_tex.read_text(encoding="utf-8"))

            with fitz.open(str(vi_pdf)) as doc:
                extracted_vi = unicodedata.normalize("NFC", "\n".join(p.get_text("text") for p in doc))
            self.assertNotIn("\ufffd", extracted_vi)
            for ch in ("ắ", "ằ", "ẳ", "ẵ", "ặ", "ề", "ệ", "ồ", "ỗ", "ử", "ự", "đ", "Đ"):
                self.assertIn(ch, extracted_vi, f"Missing Vietnamese character {ch!r}")

            # 2. English report with mixed Vietnamese/European names + parsimony check
            en_json = tmp / "en.json"
            en_pdf = tmp / "en.pdf"
            en_tex = tmp / "en.tex"
            en_payload = _clean_en_payload()
            en_payload["sources"].append(
                {"id": "S2", "title": "Nguyễn Văn Ánh & Müller (2025)", "locator": "Section 2"}
            )
            en_json.write_text(json.dumps(en_payload, ensure_ascii=False), encoding="utf-8")

            proc_en = run_cli(
                "--input", str(en_json),
                "--out", str(en_pdf),
                "--tex-out", str(en_tex),
                "--strict",
                "--json",
            )
            self.assertEqual(proc_en.returncode, 0, proc_en.stdout + proc_en.stderr)
            rec_en = json.loads(proc_en.stdout)
            self.assertEqual(rec_en["status"], "ok")
            self.assertEqual(rec_en["lang"], "en")
            self.assertTrue(rec_en["diacritics_verified"])
            for key in ("pdf_path", "tex_path", "lang", "engine", "page_count", "lint_findings", "diacritics_verified"):
                self.assertIn(key, rec_en)

            with fitz.open(str(en_pdf)) as doc:
                extracted_en = unicodedata.normalize("NFC", "\n".join(p.get_text("text") for p in doc))
            self.assertNotIn("\ufffd", extracted_en)
            self.assertIn("SimplerAlternative", extracted_en.replace(" ", ""))
            self.assertIn("61.3%", extracted_en)

    def test_latex_escaping_injection_safety_and_unicode_math(self):
        import fitz

        payload = _clean_en_payload()
        payload["title"] = "Specials % _ $ & # ~ ^ < > | Check"
        payload["flaws_and_risks"] = [
            {
                "id": "R1",
                "severity": "high",
                "summary": r"Untrusted string \write18{echo pwned} with p ≤ 0.05, delta ≥ 2, gap ≈ 0, x ≠ y, diff −1 [Table 1].",
                "locator": "logs/escape_test.json",
            }
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            in_json = tmp / "esc.json"
            out_pdf = tmp / "esc.pdf"
            in_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            proc = run_cli("--input", str(in_json), "--out", str(out_pdf), "--strict", "--json")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            with fitz.open(str(out_pdf)) as doc:
                text = "\n".join(p.get_text("text") for p in doc)
            self.assertIn("write18", text)
            self.assertIn("echo pwned", text)

    def test_compact_cli_receipt_is_bounded(self):
        bad_many = {
            "title": "Audit",
            "verdict": "Great idea! This synergistic paradigm leverages ontological tapestry.",
            "key_evidence": [
                {"claim": "Item 1 with 10% gain", "value": "10%"},
                {"claim": "Item 2 with 20% gain", "value": "20%"},
                {"claim": "Item 3 with 30% gain", "value": "30%"},
                {"claim": "Item 4 with 40% gain", "value": "40%"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            in_json = tmp / "many.json"
            out_pdf = tmp / "many.pdf"
            in_json.write_text(json.dumps(bad_many), encoding="utf-8")
            proc = run_cli("--input", str(in_json), "--out", str(out_pdf), "--strict", "--json", "--compact")
            self.assertEqual(proc.returncode, 1, proc.stdout)
            rec = json.loads(proc.stdout)
            self.assertEqual(rec["status"], "lint_failed")
            self.assertLessEqual(len(rec["lint_findings"]), 5)
            self.assertTrue(rec.get("lint_findings_truncated"))
            self.assertGreater(rec.get("lint_findings_total", 0), 5)
            self.assertNotIn("verification", rec)
            self.assertNotIn("lang_detection", rec)

    def test_error_exit_code_2_on_missing_or_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            out_pdf = tmp / "out.pdf"

            proc_missing = run_cli("--input", str(tmp / "nope.json"), "--out", str(out_pdf))
            self.assertEqual(proc_missing.returncode, 2)

            bad_json = tmp / "bad.json"
            bad_json.write_text("{not valid json", encoding="utf-8")
            proc_bad = run_cli("--input", str(bad_json), "--out", str(out_pdf))
            self.assertEqual(proc_bad.returncode, 2)

    def test_grounding_bypass_closures_and_citation_validation(self):
        # 1. Unrelated grounded key_evidence must not ground verdict.summary or parsimony_check
        p_verdict = _clean_en_payload()
        p_verdict["verdict"] = {"status": "pass", "summary": "Model achieves 99.4% accuracy.", "evidence_refs": []}
        res_v = module.lint_report(p_verdict)
        self.assertFalse(res_v["passed"])
        self.assertIn("UNGROUNDED_NUMERIC_CLAIM", {f["pattern_id"] for f in res_v["findings"]})

        p_pars = _clean_en_payload()
        p_pars["parsimony_check"] = "Simple BM25 gets 94.5% F1."
        res_p = module.lint_report(p_pars)
        self.assertFalse(res_p["passed"])
        self.assertIn("UNGROUNDED_NUMERIC_CLAIM", {f["pattern_id"] for f in res_p["findings"]})

        # 2. Fake citations must be caught even when sources is non-empty
        p_cit = _clean_en_payload()
        p_cit["flaws_and_risks"] = [{"id": "R1", "severity": "high", "summary": "Contradicts FakeAuthor et al., 2026 [99]."}]
        res_c = module.lint_report(p_cit)
        self.assertFalse(res_c["passed"])
        self.assertIn("UNGROUNDED_CITATION", {f["pattern_id"] for f in res_c["findings"]})

        # 3. next_steps[*].action checked for ungrounded metrics (excluding step labels)
        p_step = _clean_en_payload()
        p_step["next_steps"] = [{"step": 1, "action": "Achieve 98.5% accuracy on held-out split.", "target": "run_04.json"}]
        res_s = module.lint_report(p_step)
        self.assertFalse(res_s["passed"])
        self.assertIn("UNGROUNDED_NUMERIC_CLAIM", {f["pattern_id"] for f in res_s["findings"]})

        # 4. Broadened metric patterns
        for claim in (
            "F1 improved by +4.2 points over baseline.",
            "Accuracy improves from 72.1 to 87.3 across seeds.",
            "MRR@10 is 0.42 on test.",
        ):
            r_m = module.lint_report({"title": "Audit", "verdict": claim})
            self.assertIn("UNGROUNDED_NUMERIC_CLAIM", {f["pattern_id"] for f in r_m["findings"]}, claim)

        # 5. Narrative Author et al. (2024) passes when matched in sources
        p_narr = _clean_en_payload()
        p_narr["sources"].append({"id": "S2", "title": "Nguyen et al. (2024) Retrieval Benchmark", "locator": "Section 3"})
        p_narr["verdict"] = {"status": "pass", "summary": "In Nguyen et al. (2024), F1 is 0.72.", "evidence_refs": ["S2"]}
        res_n = module.lint_report(p_narr)
        self.assertTrue(res_n["passed"], res_n["findings"])

    def test_upstream_schema_routing_and_normalization_fixes(self):
        # 1. check_engineering_diagnostics.py contract ("verdict" + "findings")
        diag = {
            "verdict": "ENGINEERING_BUG_DETECTED",
            "findings": [{"id": "LEAK1", "severity": "critical", "message": "Preprocessor fit before train/test split.", "locator": "train.py:42"}],
        }
        norm_diag = module.normalize_report_input(diag)
        self.assertEqual(norm_diag["report_type"], "integrity_audit")
        self.assertEqual(norm_diag["verdict"]["status"], "fail")
        self.assertEqual(len(norm_diag["flaws_and_risks"]), 1)

        # 2. gap_pipeline.py with "verdict" + "rejected_gaps"
        gp = {
            "verdict": "fail",
            "surviving_gaps": [],
            "rejected_gaps": [{"id": "G1", "drop_code": "DROP_ALREADY_SOLVED", "reason": "Solved by Smith (2024)."}],
        }
        norm_gp = module.normalize_report_input(gp)
        self.assertEqual(norm_gp["report_type"], "gap_audit")
        self.assertEqual(len(norm_gp["flaws_and_risks"]), 1)

        # 3. search_campaign fixture (gcn-precedent-campaign.json) + missed-seed failure
        camp = json.loads((ROOT / "evaluation" / "fixtures" / "gcn-precedent-campaign.json").read_text(encoding="utf-8"))
        norm_camp = module.normalize_report_input(camp)
        self.assertIn("2/2 positive-control seeds recalled", norm_camp["verdict"]["summary"])
        self.assertEqual(norm_camp["verdict"]["status"], "supported")
        self.assertTrue(module.lint_report(camp)["passed"], module.lint_report(camp)["findings"])

        camp_missed = json.loads(json.dumps(camp))
        camp_missed["known_seed_checks"][0]["status"] = "not_retrieved_in_campaign"
        norm_missed = module.normalize_report_input(camp_missed)
        self.assertEqual(norm_missed["verdict"]["status"], "fail")
        self.assertTrue(any(f["id"] == "R-SEED" for f in norm_missed["flaws_and_risks"]))

        # 4. scorecards dict evidence_locators + list closest_work formatting
        sc = json.loads((REFS_DIR / "scorecards.schema-example.json").read_text(encoding="utf-8"))
        norm_sc = module.normalize_report_input(sc)
        self.assertNotIn("{'", norm_sc["key_evidence"][0]["locator"])
        self.assertIn("importance:", norm_sc["key_evidence"][0]["locator"])
        self.assertIn("fictional_prior_paper_section_3", norm_sc["key_evidence"][0]["evidence"])

        # 5. experiment-manifest with passing and failed exit_code runs
        exp = json.loads((REFS_DIR / "experiment-manifest.schema-example.json").read_text(encoding="utf-8"))
        self.assertEqual(module.normalize_report_input(exp)["verdict"]["status"], "pass")
        exp_fail = json.loads(json.dumps(exp))
        exp_fail["runs"][1]["exit_code"] = 1
        norm_exp_fail = module.normalize_report_input(exp_fail)
        self.assertEqual(norm_exp_fail["verdict"]["status"], "fail")
        self.assertTrue(any(f["id"].startswith("R-RUN") for f in norm_exp_fail["flaws_and_risks"]))

        # 6. evidence-map, venue-dossier, manuscript-ledger normalize and pass strict lint
        for fname, rtype in (
            ("evidence-map.schema-example.json", "evidence_map"),
            ("venue-dossier.schema-example.json", "venue_dossier"),
            ("manuscript-ledger.schema-example.json", "manuscript_ledger"),
        ):
            raw_obj = json.loads((REFS_DIR / fname).read_text(encoding="utf-8"))
            norm_obj = module.normalize_report_input(raw_obj)
            self.assertEqual(norm_obj["report_type"], rtype)
            self.assertTrue(module.lint_report(raw_obj)["passed"], fname)

        # 7. humanizer_lint output containing sycophancy/jargon excerpts must not self-trigger --strict
        hl_out = {
            "source": "draft.md",
            "risk_count": 1,
            "warn_count": 0,
            "findings": [{"line": 4, "severity": "RISK", "pattern_id": "SYC01", "category": "sycophancy", "excerpt": "Great idea! This synergistic paradigm is groundbreaking."}],
            "sycophancy_hits": [{"line": 4, "pattern_id": "SYC01", "severity": "RISK", "excerpt": "Great idea!"}],
        }
        lint_hl = module.lint_report(hl_out)
        self.assertTrue(lint_hl["passed"], lint_hl["findings"])

    def test_linter_precision_coverage_and_url_splitting(self):
        # Neuro-symbolic and Hyper-parameter must not trigger RPT_GRAND_BRANDING
        ok_terms = _clean_en_payload()
        ok_terms["verdict"]["summary"] = "Neuro-symbolic baseline and hyper-parameter tuning fail on clean splits [logs/run_02.json]."
        self.assertTrue(module.lint_report(ok_terms)["passed"])

        # Unscanned fields & >12 truncation bypass closures
        p_lbl = _clean_en_payload()
        p_lbl["verdict"]["label"] = "GROUNDBREAKING SYNERGISTIC PARADIGM"
        self.assertFalse(module.lint_report(p_lbl)["passed"])

        p_val = _clean_en_payload()
        p_val["key_evidence"][0]["value"] = "Synergistic paradigm breakthrough"
        self.assertFalse(module.lint_report(p_val)["passed"])

        p_rat = _clean_en_payload()
        p_rat["parsimony_check"] = {"simplest_alternative": "Use BM25.", "rationale": "This synergistic paradigm leverages an ontological tapestry."}
        self.assertFalse(module.lint_report(p_rat)["passed"])

        p_13 = _clean_en_payload()
        base_ev = p_13["key_evidence"][0]
        p_13["key_evidence"] = [dict(base_ev, id=f"K{i}") for i in range(1, 13)] + [
            {"id": "K13", "claim": "Great idea! Synergistic paradigm 99.9%", "value": "99.9%"}
        ]
        res_13 = module.lint_report(p_13)
        self.assertFalse(res_13["passed"])
        self.assertTrue(any("key_evidence[13]" in f["field"] for f in res_13["findings"]))

        # EN & VI praise sandwiches
        self.assertIn("SYC_PRAISE_SANDWICH", {f["pattern_id"] for f in module.lint_report({"title": "Audit", "verdict": "Nice approach, although the split has severe leakage [logs/run.json]."})["findings"]})
        self.assertIn("SYC_PRAISE_SANDWICH", {f["pattern_id"] for f in module.lint_report({"title": "Kiểm tra", "verdict": "Ý tưởng rất hay, nhưng mô hình vẫn còn yếu [logs/run.json]."})["findings"]})

        # URL trailing period + p. abbreviation must not merge/break sentences falsely
        s1 = " ".join(["word"] * 14) + " https://example.org/run1."
        s2 = "See Table 2, p. 5 for the final score " + " ".join(["word"] * 8) + "."
        p_url = _clean_en_payload()
        p_url["verdict"]["summary"] = f"{s1} {s2}"
        res_url = module.lint_report(p_url)
        self.assertNotIn("SENTENCE_TOO_LONG", {f["pattern_id"] for f in res_url["findings"]}, res_url["findings"])

    def test_language_detection_regression_cases(self):
        # VI author in EN sources must not flip English report to vi
        en_with_vi_src = _clean_en_payload()
        en_with_vi_src["lang"] = "auto"
        en_with_vi_src["sources"] = [{"id": "S1", "title": "Nguyễn Văn Ánh & Müller (2025)", "locator": "Section 2"}]
        self.assertEqual(module.detect_language(payload=en_with_vi_src)["lang"], "en")

        self.assertEqual(
            module.detect_language(text="Check Nguyễn Văn Ánh (2025) paper on RAG baseline F1 and split leakage")["lang"],
            "en",
        )
        for vi_txt in (
            "Review paper giùm nhé",
            "Chính xác hay sai",
            "Check giúp anh nhé",
            "Hay xem lai ket qua baseline nay giup toi",
        ):
            self.assertEqual(module.detect_language(text=vi_txt)["lang"], "vi", vi_txt)

        for txt, expected in (
            ("Résumé et évaluation des résultats avec les données.", "fr"),
            ("Prüfung der Ergebnisse und Bericht mit den Daten.", "de"),
            ("Evaluación de los resultados con la evidencia sobre el informe.", "es"),
        ):
            d = module.detect_language(text=txt)
            self.assertEqual(d["lang"], expected)
            self.assertNotEqual(d["signals"], ["default_en"])

    def test_pdflatex_robustness_greek_mixed_names_brackets_urls_timeout_and_receipt(self):
        import fitz

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            # 1. Greek symbols + leading '[' + long URL + mixed hyphenated names + long VI snake_case + 67-char NFD
            nfd_unbroken = unicodedata.normalize("NFD", "aáàảãạăắằẳẵặâấầẩẫậeéèẻẽẹêếềểễệiíìỉĩịoóòỏõọôốồổỗộơớờởỡợuúùủũụưứừửữựyýỳỷỹỵđ")
            payload = _clean_vi_payload()
            payload["title"] = "Kiểm thử tên ghép: Müller-Nguyễn và François-Đặng (Δ)"
            payload["verdict"]["summary"] = "Hyperparameters α = 0.5, β = 0.9, γ = 0.1, δ = 0.2, Δ ≈ 0.2, latency 12 μs [Bảng 1]."
            payload["key_evidence"].extend([
                {
                    "id": "K3",
                    "claim": "[Phase 1] Baseline F1 với Đặng-Müller",
                    "value": "chưa_kiểm_chứng_được_kết_quả",
                    "status": "đã_kiểm_tra",
                    "locator": "https://example.org/very/long/unbroken/path/segment/alpha/beta/gamma/delta?a=1&b=2#frag_ment_12345",
                },
                {
                    "id": "K4",
                    "claim": nfd_unbroken,
                    "value": "OK",
                    "status": "verified",
                    "locator": "Bảng 2",
                },
            ])
            payload["next_steps"] = [{"step": 1, "action": "[unclosed bracket step.", "target": "run.json"}]

            in_json = tmp / "robust.json"
            out_pdf = tmp / "robust.pdf"
            out_tex = tmp / "robust.tex"
            in_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            proc = run_cli("--input", str(in_json), "--out", str(out_pdf), "--tex-out", str(out_tex), "--lang", "vi", "--strict", "--json")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            rec = json.loads(proc.stdout)
            self.assertEqual(rec["status"], "ok")
            self.assertTrue(rec["diacritics_verified"])

            with fitz.open(str(out_pdf)) as doc:
                extracted = unicodedata.normalize("NFC", "\n".join(p.get_text("text") for p in doc))
                self.assertIn("Müller-Nguyễn", extracted)
                self.assertIn("François-Đặng", extracted)
                self.assertIn("Đặng-Müller", extracted)
                for page in doc:
                    pw = page.rect.width
                    for blk in page.get_text("blocks"):
                        self.assertLessEqual(blk[2], pw - 10, f"Block overflowed A4 width: {blk}")

            # 2. Real pdflatex loop TimeoutExpired handled cleanly in compile_pdf + '!' TeX error extraction
            t_res = module.compile_pdf(
                r"\documentclass{article}\begin{document}\loop\iftrue\repeat\end{document}",
                tmp / "t.pdf",
                timeout=1,
            )
            self.assertFalse(t_res["compiled"])
            self.assertIn("timed out", t_res["error"])

            bad_tex_res = module.compile_pdf(r"\documentclass{article}\begin{document}\undefinedmacro\end{document}", tmp / "badtex.pdf")
            self.assertFalse(bad_tex_res["compiled"])
            self.assertIn("!", bad_tex_res["log_tail"])

            # 3. strict lint_failed must set receipt["tex_path"] = None and not write tex_out
            bad_json = tmp / "lint_fail.json"
            bad_pdf = tmp / "lint_fail.pdf"
            bad_tex = tmp / "lint_fail.tex"
            bad_json.write_text(json.dumps({"title": "Audit", "verdict": "Great idea!"}), encoding="utf-8")
            proc_lf = run_cli("--input", str(bad_json), "--out", str(bad_pdf), "--tex-out", str(bad_tex), "--strict", "--json")
            self.assertEqual(proc_lf.returncode, 1)
            rec_lf = json.loads(proc_lf.stdout)
            self.assertEqual(rec_lf["status"], "lint_failed")
            self.assertIsNone(rec_lf["tex_path"])
            self.assertFalse(bad_tex.exists())

    def test_e2e_vi_en_sycophancy_problem_inflation_and_compact_success_receipt(self):
        # 1. Standalone VI & EN cheerleading with intensifiers caught in both raw str and dict
        vi_cheer = "Tuyệt vời! Ý tưởng quá xuất sắc, đột phá toàn diện trên mọi khía cạnh."
        en_cheer = "Fantastic! This truly brilliant approach delivers outstanding performance."
        for txt in (vi_cheer, en_cheer):
            r_raw = module.lint_report(txt)
            self.assertFalse(r_raw["passed"], txt)
            self.assertTrue(any(f["pattern_id"].startswith("SYC_") for f in r_raw["findings"]), r_raw)
            r_dict = module.lint_report({"title": "Audit", "verdict": txt})
            self.assertFalse(r_dict["passed"], txt)
            self.assertTrue(any(f["pattern_id"].startswith("SYC_") for f in r_dict["findings"]), r_dict)

        # 2. Problem inflation PI01 caught in EN & VI, while grounded quantitative defects and 'catastrophic forgetting' pass
        for inflated in (
            "The field faces a fundamental crisis and catastrophic failure [Table 1].",
            "Phương pháp này dẫn đến khủng hoảng nền tảng và sụp đổ hoàn toàn [Bảng 1].",
        ):
            r_pi = module.lint_report({"title": "Audit", "verdict": inflated})
            self.assertFalse(r_pi["passed"], inflated)
            self.assertIn("PI01", {f["pattern_id"] for f in r_pi["findings"]})

        ok_grounded = _clean_en_payload()
        ok_grounded["verdict"]["summary"] = "Accuracy drops from 84% to 61% due to catastrophic forgetting [logs/run_02.json]."
        self.assertTrue(module.lint_report(ok_grounded)["passed"])

        # 3. F20 --compact emits bounded JSON receipt with pdf_path and tex_path on success
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            in_json = tmp / "ok.json"
            out_pdf = tmp / "ok.pdf"
            out_tex = tmp / "ok.tex"
            in_json.write_text(json.dumps(_clean_en_payload()), encoding="utf-8")
            proc = run_cli("--input", str(in_json), "--out", str(out_pdf), "--tex-out", str(out_tex), "--strict", "--json", "--compact")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            rec = json.loads(proc.stdout)
            self.assertEqual(rec["status"], "ok")
            self.assertEqual(rec["pdf_path"], str(out_pdf))
            self.assertEqual(rec["tex_path"], str(out_tex))
            self.assertLessEqual(len(rec["lint_findings"]), 5)
            self.assertNotIn(r"\documentclass", proc.stdout)

    def test_iteration3_grounding_citation_and_unscanned_field_closures(self):
        # 1. Non-[N] unverified citations caught even when locator and sources exist
        p_etal = _clean_en_payload()
        p_etal["flaws_and_risks"] = [{"id": "R1", "severity": "high", "summary": "Contradicts UnlistedAuthor et al., 2026.", "locator": "logs/run.json"}]
        self.assertIn("UNGROUNDED_CITATION", {f["pattern_id"] for f in module.lint_report(p_etal)["findings"]})

        p_arxiv = _clean_en_payload()
        p_arxiv["verdict"]["summary"] = "Per UnlistedAuthor et al. (2026) and arXiv:9999.99999, F1 is 99.4% [logs/run.json]."
        self.assertIn("UNGROUNDED_CITATION", {f["pattern_id"] for f in module.lint_report(p_arxiv)["findings"]})

        # 2. [99] caught even when sources is empty and verdict has evidence_refs
        p_num_empty = _clean_en_payload()
        p_num_empty["sources"] = []
        p_num_empty["verdict"]["summary"] = "Accuracy drops to 61.3% per [99]."
        self.assertIn("UNGROUNDED_CITATION", {f["pattern_id"] for f in module.lint_report(p_num_empty)["findings"]})

        # 3. Single-author UnlistedAuthor (2026), Accuracy (2024), dangling evidence_refs, and [unlisted_cue]
        for bad_payload, expected_pid in (
            ({"title": "Audit", "verdict": "In UnlistedAuthor (2026), accuracy is 99.4%."}, "UNGROUNDED_CITATION"),
            ({"title": "Audit", "verdict": "Accuracy (2024) is 99.4%."}, "UNGROUNDED_NUMERIC_CLAIM"),
            ({"title": "Audit", "verdict": "Accuracy is 99.4% [unlisted_cue]."}, "UNGROUNDED_NUMERIC_CLAIM"),
            ({**_clean_en_payload(), "verdict": {"status": "pass", "summary": "Accuracy is 99.4%.", "evidence_refs": ["NONEXISTENT_ID"]}}, "UNGROUNDED_NUMERIC_CLAIM"),
            ({"title": "Audit", "verdict": "ROUGE-L is 0.45."}, "UNGROUNDED_NUMERIC_CLAIM"),
            ({"title": "Kiểm tra", "verdict": "Độ chính xác tăng từ 72.1 lên 87.3."}, "UNGROUNDED_NUMERIC_CLAIM"),
            ({"title": "Audit", "verdict": "Li et al. (2024) reports 99.4% accuracy.", "sources": [{"id": "S1", "title": "Linear Models Survey (2024)", "locator": "Section 1"}]}, "UNGROUNDED_CITATION"),
        ):
            r = module.lint_report(bad_payload)
            self.assertFalse(r["passed"], bad_payload)
            self.assertIn(expected_pid, {f["pattern_id"] for f in r["findings"]}, bad_payload)

        # 4. Parenthetical (Smith, 2024) & Unicode Đặng et al. (2024) pass when matched in sources; year range passes
        for good_payload in (
            {"title": "Audit", "verdict": {"status": "pass", "summary": "In (Smith, 2024), accuracy is 99.4%.", "evidence_refs": ["S1"]}, "sources": [{"id": "S1", "title": "Smith (2024) Benchmark", "locator": "Table 1"}]},
            {"title": "Audit", "verdict": {"status": "pass", "summary": "In Đặng et al. (2024), F1 is 0.72.", "evidence_refs": ["S1"]}, "sources": [{"id": "S1", "title": "Đặng & Nguyễn (2024)", "locator": "Section 2"}]},
            {**_clean_en_payload(), "verdict": {"status": "pass", "summary": "Accuracy (2024) is 99.4% [logs/run.json].", "evidence_refs": ["K1"]}},
            {**_clean_vi_payload(), "verdict": {"status": "pass", "summary": "Dữ liệu từ 2020 đến 2024 được kiểm tra [Bảng 1].", "evidence_refs": ["K1"]}},
        ):
            r_ok = module.lint_report(good_payload)
            self.assertTrue(r_ok["passed"], f"{good_payload}: {r_ok['findings']}")

        # 5. next_steps[*].target and metadata.scope/coverage_limits scanned
        p_tgt = _clean_en_payload()
        p_tgt["next_steps"] = [{"step": 1, "action": "Re-run baseline.", "target": "Great idea! Synergistic paradigm TODO"}]
        self.assertFalse(module.lint_report(p_tgt)["passed"])

        p_tgt_num = _clean_en_payload()
        p_tgt_num["next_steps"] = [{"step": 1, "action": "Re-run baseline.", "target": "Achieve 99.4% F1"}]
        self.assertIn("UNGROUNDED_NUMERIC_CLAIM", {f["pattern_id"] for f in module.lint_report(p_tgt_num)["findings"]})

        p_meta = _clean_en_payload()
        p_meta["metadata"]["scope"] = "Great idea! TODO"
        self.assertFalse(module.lint_report(p_meta)["passed"])

    def test_iteration3_ml_term_fp_fixes_and_short_vi_lang_detection(self):
        # 1. Standard ML phrasing must pass strict without SYC_PRAISE_SANDWICH or RPT_GRAND_BRANDING FPs
        for ok_text in (
            "The paper uses a strong baseline, but split leakage invalidates the gain [logs/run.json].",
            "Clean baseline fails on test, though seed variance is small [logs/run.json].",
            "Strong baseline achieves 70% F1, yet fails on OOD [logs/run.json].",
            "Early-Fusion baseline fails on split check [logs/run.json].",
            "Split leakage invalidates the gain, though it is a nice approach [logs/run.json].",
        ):
            p = _clean_en_payload()
            p["verdict"]["summary"] = ok_text
            r = module.lint_report(p)
            self.assertTrue(r["passed"], f"{ok_text} -> {r['findings']}")

        p_vi = _clean_vi_payload()
        p_vi["verdict"]["summary"] = "Giả thiết hợp lý, nhưng thiếu kiểm tra trùng lặp [Bảng 1]."
        self.assertTrue(module.lint_report(p_vi)["passed"])

        # 2. Genuine EN/VI praise-before-critique sandwiches still rejected
        for sandwich_text in (
            "Solid work, however the baseline is leaky [logs/run.json].",
            "Phương pháp tốt, tuy nhiên dữ liệu bị trùng [Bảng 1].",
        ):
            r_sw = module.lint_report({"title": "Audit", "verdict": sandwich_text})
            self.assertFalse(r_sw["passed"], sandwich_text)
            self.assertIn("SYC_PRAISE_SANDWICH", {f["pattern_id"] for f in r_sw["findings"]}, sandwich_text)

        # 3. Short unaccented VI vs EN homographs & 4-diacritic VI author name inside EN body
        for vi_short in ("Check giup toi nhe", "Review paper giup minh", "Sua loi nay giup"):
            self.assertEqual(module.detect_language(text=vi_short)["lang"], "vi", vi_short)
        self.assertEqual(
            module.detect_language(text="So why is this so high? Let us check so far with hay and grass.")["lang"],
            "en",
        )
        self.assertEqual(
            module.detect_language(text="Evaluate the baseline F1 score and split leakage reported by Nguyễn Thị Hương (2025) on this benchmark.")["lang"],
            "en",
        )

    def test_iteration3_schemas_greek_utf8_url_t1_and_a4_bbox_all_fixtures(self):
        import fitz

        # 1. search_campaign schema key + top_results + compare_scorecards live CLI stdout (full & --compact)
        camp_schema = {
            "schema": "research_scientist_search_campaign_v1",
            "queries": ["graph neural network"],
            "combined_results": [{"title": "Graph Survey", "year": 2024, "arxiv_id": "2401.00001"}],
        }
        self.assertTrue(module.lint_report(camp_schema)["passed"])
        camp_compact = {
            "schema": "research_scientist_search_v2",
            "query": "gcn",
            "top_results": [{"title": "Graph Survey", "year": 2024, "doi": "10.1234/abc"}],
        }
        self.assertTrue(module.lint_report(camp_compact)["passed"])

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            for extra in ([], ["--compact"]):
                sc_proc = subprocess.run(
                    [sys.executable, str(ROOT / "research-scientist" / "scripts" / "compare_scorecards.py"), str(REFS_DIR / "scorecards.schema-example.json"), *extra],
                    capture_output=True, text=True, check=True,
                )
                sc_out = json.loads(sc_proc.stdout)
                sc_rec = module.generate_report(sc_out, tmp / f"sc_{len(extra)}.pdf", strict=True, compact=True)
                self.assertEqual(sc_rec["status"], "ok", sc_rec)

            # 2. Greek multi-char ToUnicode + UTF-8 URL without VI body + T1 îûÿÎÛŸ¿¡ + A4 overflow stress + venue-dossier
            greek_p = _clean_en_payload()
            greek_p["title"] = "αβγ divergence and λθω parameters"
            greek_p["verdict"]["summary"] = "Parameters αβγ, α12, αβ1, μσΔ, a≠b, a−b, and ∑xy stayed stable in Table 1 [K1]."
            rec_g = module.generate_report(greek_p, tmp / "greek.pdf", strict=True)
            self.assertEqual(rec_g["status"], "ok", rec_g)
            self.assertTrue(rec_g["diacritics_verified"])

            url_p = _clean_en_payload()
            url_p["key_evidence"][0]["source_url"] = "https://vi.wikipedia.org/wiki/Hà_Nội?q=đồ_thị#mục_1"
            rec_u = module.generate_report(url_p, tmp / "utf8url.pdf", strict=True)
            self.assertEqual(rec_u["status"], "ok", rec_u)
            with fitz.open(rec_u["pdf_path"]) as doc:
                uris = [lk["uri"] for pg in doc for lk in pg.get_links() if lk.get("uri")]
                self.assertTrue(any("%C3%A0" in u and "%E1%BB%99" in u for u in uris), uris)

            t1_p = _clean_vi_payload()
            t1_p["title"] = "Kiểm tra maître và coût với Lÿs (¿Cómo? ¡Sí!)"
            t1_p["verdict"]["summary"] = "Đối chiếu maître-Đặng và coût-Müller trong Bảng 1 [K1]."
            rec_t1 = module.generate_report(t1_p, tmp / "t1.pdf", strict=True)
            self.assertEqual(rec_t1["status"], "ok", rec_t1)
            with fitz.open(rec_t1["pdf_path"]) as doc:
                txt = "\n".join(pg.get_text("text") for pg in doc)
                for tok in ("maître", "coût", "Lÿs", "¿Cómo?", "¡Sí!", "maître-Đặng", "coût-Müller"):
                    self.assertIn(tok, txt)

            over_p = _clean_en_payload()
            over_p["title"] = "W" * 67
            over_p["verdict"]["summary"] = "See https://example.org/very/long/unbroken/path/segment/alpha/beta/gamma/delta/epsilon/zeta?a=1&b=2#frag_ment_12345 [K1]."
            over_p["key_evidence"].append({"id": "K3", "claim": "ABCDEFGHIJKLMNOPQRS", "value": "W" * 19, "status": "UNVERIFIED_12345678", "locator": "Table 1"})
            over_p["next_steps"] = [{"step": 1, "action": "Check https://example.org/very/long/unbroken/path/segment/alpha/beta/gamma/delta/epsilon/zeta?a=1&b=2#frag_ment_12345", "target": "https://example.org/very/long/unbroken/path/segment/alpha/beta/gamma"}]
            rec_o = module.generate_report(over_p, tmp / "over.pdf", strict=True)
            self.assertEqual(rec_o["status"], "ok", rec_o)

            dossier_data = json.loads((REFS_DIR / "venue-dossier.schema-example.json").read_text(encoding="utf-8"))
            rec_d = module.generate_report(dossier_data, tmp / "dossier.pdf", strict=True)
            self.assertEqual(rec_d["status"], "ok", rec_d)

            for check_pdf in (rec_o["pdf_path"], rec_d["pdf_path"]):
                with fitz.open(check_pdf) as doc:
                    for pg in doc:
                        pw = pg.rect.width
                        for blk in pg.get_text("blocks"):
                            self.assertLessEqual(blk[2], pw - 10, f"{check_pdf} overflow: {blk}")

    def test_iteration4_grounding_citations_multilingual_t5_and_full_greek(self):
        import fitz

        # 1. Unnumbered generic nouns fail UNGROUNDED_NUMERIC_CLAIM; numbered Table 1 passes
        for bad_cue in (
            "In this section, accuracy is 99.4%.",
            "The table shows F1 is 99.4%.",
            "The figure shows F1 is 99.4%.",
            "Bảng này cho thấy accuracy là 99.4%.",
            "Mục này cho thấy F1 đạt 99.4%.",
        ):
            r_cue = module.lint_report({"title": "Audit", "verdict": bad_cue})
            self.assertFalse(r_cue["passed"], bad_cue)
            self.assertIn("UNGROUNDED_NUMERIC_CLAIM", {f["pattern_id"] for f in r_cue["findings"]}, bad_cue)
        self.assertTrue(module.lint_report({"title": "Audit", "verdict": "Table 1 shows accuracy is 99.4%."})["passed"])

        # 2. metadata.scope and metadata.coverage_limits grounding checks
        for meta_update, expected_pid in (
            ({"scope": "Evaluated with accuracy 99.4%."}, "UNGROUNDED_NUMERIC_CLAIM"),
            ({"scope": "Follows UnlistedAuthor et al. (2026) and arXiv:9999.99999."}, "UNGROUNDED_CITATION"),
            ({"coverage_limits": "F1 drops from 90.0 to 40.0."}, "UNGROUNDED_NUMERIC_CLAIM"),
        ):
            p_m = _clean_en_payload()
            p_m["metadata"].update(meta_update)
            r_m = module.lint_report(p_m)
            self.assertFalse(r_m["passed"], meta_update)
            self.assertIn(expected_pid, {f["pattern_id"] for f in r_m["findings"]}, meta_update)

        # 3. Alphanumeric [S99] citations & parsimony_check.source_refs=["NONEXISTENT_ID"]
        p_s99 = _clean_en_payload()
        p_s99["verdict"]["summary"] = "Per [S99], accuracy is 99.4% [logs/run.json]."
        self.assertIn("UNGROUNDED_CITATION", {f["pattern_id"] for f in module.lint_report(p_s99)["findings"]})

        p_s99_fl = _clean_en_payload()
        p_s99_fl["flaws_and_risks"] = [{"id": "R1", "severity": "high", "summary": "Contradicts [S99] on split leakage.", "locator": "logs/run.json"}]
        self.assertIn("UNGROUNDED_CITATION", {f["pattern_id"] for f in module.lint_report(p_s99_fl)["findings"]})

        p_sk1 = _clean_en_payload()
        p_sk1["verdict"]["summary"] = "Per [S1] and [K1], accuracy is 61.3%."
        self.assertTrue(module.lint_report(p_sk1)["passed"])

        p_pars_bad = _clean_en_payload()
        p_pars_bad["parsimony_check"] = {"simplest_alternative": "Linear baseline hits 88.2% F1.", "source_refs": ["NONEXISTENT_ID"]}
        self.assertIn("UNGROUNDED_NUMERIC_CLAIM", {f["pattern_id"] for f in module.lint_report(p_pars_bad)["findings"]})

        p_pars_ok = _clean_en_payload()
        p_pars_ok["parsimony_check"] = {"simplest_alternative": "Linear baseline hits 61.3% F1.", "source_refs": ["S1"]}
        self.assertTrue(module.lint_report(p_pars_ok)["passed"])

        # 4. Multi-author all-surname matching, (Author YYYY) no-comma, and mAP@0.5 / Pass@1 / RMSE / MAE / Top-1
        p_co = _clean_en_payload()
        p_co["sources"] = [{"id": "S1", "title": "Doe et al. (2024) Split Audits", "locator": "logs/run_02.json"}]
        p_co["verdict"]["summary"] = "Doe & UnlistedAuthor (2024) report 99.4% F1 [logs/run.json]."
        self.assertIn("UNGROUNDED_CITATION", {f["pattern_id"] for f in module.lint_report(p_co)["findings"]})

        p_3au = _clean_en_payload()
        p_3au["sources"] = [{"id": "S1", "title": "Smith & Jones (2025) Audit", "locator": "Section 1"}]
        p_3au["verdict"]["summary"] = "Smith, Jones, and Lee (2025) report 99.4% F1 [logs/run.json]."
        self.assertIn("UNGROUNDED_CITATION", {f["pattern_id"] for f in module.lint_report(p_3au)["findings"]})
        p_3au["sources"] = [{"id": "S1", "title": "Smith, Jones, and Lee (2025) Audit", "locator": "Section 1"}]
        self.assertTrue(module.lint_report(p_3au)["passed"])

        p_nocomma = _clean_en_payload()
        p_nocomma["verdict"]["summary"] = "Per (UnlistedAuthor 2025), accuracy is 99.4% [logs/run.json]."
        self.assertIn("UNGROUNDED_CITATION", {f["pattern_id"] for f in module.lint_report(p_nocomma)["findings"]})

        p_nonauthor_paren = _clean_en_payload()
        p_nonauthor_paren["verdict"]["summary"] = "Accuracy in (Table 2024) is 61.3% [logs/run_02.json]."
        self.assertTrue(module.lint_report(p_nonauthor_paren)["passed"])

        for mclaim in ("mAP@0.5 is 0.72.", "Pass@1 is 65.2.", "RMSE is 0.12.", "MAE is 0.08.", "Top-1 is 78.4."):
            r_mc = module.lint_report({"title": "Audit", "verdict": mclaim})
            self.assertIn("UNGROUNDED_NUMERIC_CLAIM", {f["pattern_id"] for f in r_mc["findings"]}, mclaim)

        # 5 & 6. es/fr T1 compilation, VI chars in verdict.label/report_type/reading_basis, full Greek + falsification
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            for idx, (kwargs, label) in enumerate((
                ({"lang": "es"}, "es_explicit"),
                ({"lang": "auto", "input_text": "Evaluación de los resultados con la evidencia sobre el informe."}, "es_auto"),
                ({"lang": "auto", "input_text": "Résumé et évaluation des résultats avec les données."}, "fr_auto"),
            )):
                p = _clean_en_payload()
                p["lang"] = "auto"
                rec = module.generate_report(p, tmp / f"{label}_{idx}.pdf", strict=True, **kwargs)
                self.assertEqual(rec["status"], "ok", (label, rec))
                self.assertTrue(rec["diacritics_verified"], (label, rec))

            for idx, field_override in enumerate((
                {"verdict": {**_clean_en_payload()["verdict"], "label": "ĐẠT CHUẨN"}},
                {"report_type": "kiểm_tra"},
                {"metadata": {**_clean_en_payload()["metadata"], "reading_basis": "đọc_toàn_văn"}},
            )):
                p_vi_field = _clean_en_payload()
                p_vi_field.update(field_override)
                rec_vf = module.generate_report(p_vi_field, tmp / f"vi_field_{idx}.pdf", lang="en", strict=True)
                self.assertEqual(rec_vf["status"], "ok", (field_override, rec_vf))

            p_greek = _clean_en_payload()
            p_greek["title"] = "Greek αβγδεζηθικλμνξοπρστυφχψως ΓΔΘΛΞΠΣΦΨΩ ΑΒΕΖΗΙΚΜΝΟΡΤΥΧ"
            p_greek["verdict"]["summary"] = "Greek αβγδεζηθικλμνξοπρστυφχψως ΓΔΘΛΞΠΣΦΨΩ ΑΒΕΖΗΙΚΜΝΟΡΤΥΧ checked [K1]."
            rec_gr = module.generate_report(p_greek, tmp / "greek_full.pdf", lang="en", strict=True)
            self.assertEqual(rec_gr["status"], "ok", rec_gr)
            self.assertTrue(rec_gr["diacritics_verified"], rec_gr)
            with fitz.open(rec_gr["pdf_path"]) as doc:
                for pg in doc:
                    pw = pg.rect.width
                    for blk in pg.get_text("blocks"):
                        self.assertLessEqual(blk[2], pw - 10, f"Greek overflow: {blk}")

            p_plain = _clean_en_payload()
            p_plain["title"] = "Plain Check"
            p_plain["verdict"]["summary"] = "Hello world test only [K1]."
            rec_pl = module.generate_report(p_plain, tmp / "plain.pdf", lang="en", strict=True)
            self.assertEqual(rec_pl["status"], "ok", rec_pl)
            for missing_probe in ("αβγ divergence and λθω parameters", "ΑΒΕΖΗΙΚΜΝΟΡΤΥΧ", "Sum ς = 1"):
                self.assertFalse(module.verify_pdf_output(Path(rec_pl["pdf_path"]), [missing_probe], "en")["verified"], missing_probe)

    def test_iteration5_verifier_fixes(self):
        # 1. key_evidence[*].source_refs & flaws_and_risks[*].source_refs grounding bypass closure
        p_ev_bad = _clean_en_payload()
        p_ev_bad["sources"] = []
        p_ev_bad["key_evidence"] = [{"id": "K1", "claim": "F1 score", "value": "99.9%", "status": "verified", "source_refs": ["NONEXISTENT"]}]
        p_ev_bad["verdict"] = {"status": "fail", "summary": "Claimed gain fails [K1].", "evidence_refs": ["K1"], "parsimony_check": "Simple baseline hits 61.3% [K1]."}
        r_ev_bad = module.lint_report(p_ev_bad)
        self.assertFalse(r_ev_bad["passed"])
        ev_pids = {f["pattern_id"] for f in r_ev_bad["findings"]}
        self.assertIn("MISSING_EVIDENCE_LOCATOR", ev_pids)
        self.assertIn("UNGROUNDED_NUMERIC_CLAIM", ev_pids)

        p_fl_bad = _clean_en_payload()
        p_fl_bad["flaws_and_risks"] = [{"id": "R1", "severity": "high", "summary": "Accuracy dropped 15%.", "source_refs": ["NONEXISTENT"]}]
        r_fl_bad = module.lint_report(p_fl_bad)
        self.assertFalse(r_fl_bad["passed"])
        self.assertIn("UNGROUNDED_NUMERIC_CLAIM", {f["pattern_id"] for f in r_fl_bad["findings"]})

        p_partial = _clean_en_payload()
        p_partial["key_evidence"] = [{"id": "K1", "claim": "F1", "value": "61.3%", "source_refs": ["S1", "NONEXISTENT"]}]
        self.assertIn("MISSING_EVIDENCE_LOCATOR", {f["pattern_id"] for f in module.lint_report(p_partial)["findings"]})

        p_self = _clean_en_payload()
        p_self["key_evidence"] = [{"id": "K1", "claim": "F1", "value": "61.3%", "source_refs": ["K1"]}]
        self.assertIn("MISSING_EVIDENCE_LOCATOR", {f["pattern_id"] for f in module.lint_report(p_self)["findings"]})

        p_valid_ref = _clean_en_payload()
        p_valid_ref["key_evidence"] = [{"id": "K1", "claim": "F1", "value": "61.3%", "status": "verified", "source_refs": ["S1"]}]
        p_valid_ref["flaws_and_risks"] = [{"id": "R1", "severity": "high", "summary": "Accuracy dropped 15%.", "source_refs": ["K1"]}]
        self.assertTrue(module.lint_report(p_valid_ref)["passed"])

        # 2. _collect_report_text includes key_evidence[*].source_refs & flaws_and_risks[*].source_refs for T5 detection
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            p_t5_ref = _clean_en_payload()
            p_t5_ref["sources"] = [
                {"id": "tài_liệu_1", "title": "Audit log", "locator": "Section 1"},
                {"id": "Bảng_Nguyễn", "title": "Split table", "locator": "Section 2"},
            ]
            p_t5_ref["key_evidence"] = [{"id": "K1", "claim": "Split F1", "value": "61.3%", "status": "verified", "source_refs": ["tài_liệu_1"]}]
            p_t5_ref["flaws_and_risks"] = [{"id": "R1", "severity": "high", "summary": "Split overlap.", "source_refs": ["Bảng_Nguyễn"]}]
            collected = module._collect_report_text(module.normalize_report_input(p_t5_ref, lang="en"))
            self.assertIn("tài_liệu_1", collected)
            self.assertIn("Bảng_Nguyễn", collected)
            tex_t5 = tmp / "t5_ref.tex"
            rec_t5 = module.generate_report(p_t5_ref, tmp / "t5_ref.pdf", tex_out=tex_t5, lang="en", strict=True)
            self.assertEqual(rec_t5["status"], "ok", rec_t5)
            self.assertTrue(rec_t5["diacritics_verified"])
            self.assertIn("[T5,T1]", tex_t5.read_text(encoding="utf-8"))

            # 5a. verify_pdf_output short-Greek falsification
            p_plain = _clean_en_payload()
            p_plain["title"] = "Plain Check"
            p_plain["verdict"]["summary"] = "Hello world test only [K1]."
            rec_pl = module.generate_report(p_plain, tmp / "plain_i5.pdf", lang="en", strict=True)
            self.assertEqual(rec_pl["status"], "ok", rec_pl)
            for short_greek in ("φψω", "ιυς", "ΓΔΘ", "αβγδ", "Δ=1.0", "A=α"):
                self.assertFalse(
                    module.verify_pdf_output(Path(rec_pl["pdf_path"]), [short_greek], "en")["verified"],
                    short_greek,
                )

        # 3. _extract_inline_citations non-author leading token bypass closures
        for bad_cit in (
            "Winter & UnlistedAuthor (2024) report 99.4% F1 [logs/run.json].",
            "(Winter & UnlistedAuthor, 2024) report 99.4% F1 [logs/run.json].",
            "May et al. (2024) report 99.4% F1 [logs/run.json].",
            "Data et al. (2024) report 99.4% F1 [logs/run.json].",
            "Per (However, UnlistedAuthor 2025), F1 is 99.4% [logs/run.json].",
            "Per (Table, UnlistedAuthor 2025), F1 is 99.4% [logs/run.json].",
        ):
            p_bc = _clean_en_payload()
            p_bc["verdict"]["summary"] = bad_cit
            r_bc = module.lint_report(p_bc)
            self.assertFalse(r_bc["passed"], bad_cit)
            self.assertIn("UNGROUNDED_CITATION", {f["pattern_id"] for f in r_bc["findings"]}, bad_cit)

        for ok_non_au in (
            "Accuracy in (Table 2024) is 61.3% [logs/run_02.json].",
            "Results in (Section 2025) hold [logs/run_02.json].",
        ):
            p_ok = _clean_en_payload()
            p_ok["verdict"]["summary"] = ok_non_au
            self.assertTrue(module.lint_report(p_ok)["passed"], ok_non_au)

        p_may_ok = _clean_en_payload()
        p_may_ok["sources"].append({"id": "S2", "title": "May et al. (2024) Split Study", "locator": "Section 1"})
        p_may_ok["verdict"]["summary"] = "May et al. (2024) report 61.3% F1 [logs/run_02.json]."
        self.assertTrue(module.lint_report(p_may_ok)["passed"])

        # 4. parsimony_refs forwarded in all non-canonical normalizers
        gap_data = json.loads((REFS_DIR / "gap-record.schema-example.json").read_text(encoding="utf-8"))
        gap_ok = json.loads(json.dumps(gap_data))
        gap_ok["parsimony_check"] = {"simplest_alternative": "Linear probe hits 88.2% F1.", "source_refs": ["E1"]}
        self.assertTrue(module.lint_report(gap_ok)["passed"])
        gap_bad = json.loads(json.dumps(gap_data))
        gap_bad["parsimony_check"] = {"simplest_alternative": "Linear probe hits 88.2% F1.", "source_refs": ["NONEXISTENT_ID"]}
        self.assertIn("UNGROUNDED_NUMERIC_CLAIM", {f["pattern_id"] for f in module.lint_report(gap_bad)["findings"]})

        venue_data = json.loads((REFS_DIR / "venue-novelty-profile.fixture.json").read_text(encoding="utf-8"))
        ven_ok = json.loads(json.dumps(venue_data))
        ven_ok["parsimony_check"] = {"simplest_alternative": "Pruned LoRA hits 88.2% F1.", "source_refs": ["FICTIONAL-TARGET"]}
        self.assertTrue(module.lint_report(ven_ok)["passed"])
        ven_panel = json.loads(json.dumps(venue_data))
        ven_panel["parsimony_check"] = {"simplest_alternative": "Pruned LoRA hits 88.2% F1.", "source_refs": ["PANEL"]}
        self.assertTrue(module.lint_report(ven_panel)["passed"])
        ven_bad = json.loads(json.dumps(venue_data))
        ven_bad["parsimony_check"] = {"simplest_alternative": "Pruned LoRA hits 88.2% F1.", "source_refs": ["NONEXISTENT_ID"]}
        self.assertIn("UNGROUNDED_NUMERIC_CLAIM", {f["pattern_id"] for f in module.lint_report(ven_bad)["findings"]})

        # 5b. Broadened alphanumeric bracket citation matching
        for bad_br in ("[F99]", "[M1]", "[W99]", "[X99]", "[S1000]"):
            p_br = _clean_en_payload()
            p_br["verdict"]["summary"] = f"Per {bad_br}, accuracy is 61.3% [logs/run_02.json]."
            r_br = module.lint_report(p_br)
            self.assertFalse(r_br["passed"], bad_br)
            self.assertIn("UNGROUNDED_CITATION", {f["pattern_id"] for f in r_br["findings"]}, bad_br)

        for ok_tag in ("[PASS]", "[HIGH]", "[OK]", "[Table 1]", "[Fig 2]", "[Sec 1]", "[p 5]", "[S1]", "[K1]"):
            p_tag = _clean_en_payload()
            p_tag["verdict"]["summary"] = f"Status {ok_tag}: accuracy is 61.3% [logs/run_02.json]."
            self.assertTrue(module.lint_report(p_tag)["passed"], ok_tag)

        p_sc1 = _clean_en_payload()
        p_sc1["key_evidence"][0]["id"] = "SC1"
        p_sc1["verdict"]["evidence_refs"] = ["SC1"]
        p_sc1["verdict"]["summary"] = "Per [SC1], accuracy is 61.3%."
        self.assertTrue(module.lint_report(p_sc1)["passed"])


if __name__ == "__main__":
    unittest.main()
