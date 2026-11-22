"""Unit and contract tests for Milestone M10B (F29#4 Deep Paper Audits + F29#5 Artifact Readiness)."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "research-scientist" / "scripts"
LEDGER_SCRIPT = SCRIPTS_DIR / "check_manuscript_ledger.py"
READINESS_SCRIPT = SCRIPTS_DIR / "check_artifact_readiness.py"
CLAIM_AUDIT_SCRIPT = SCRIPTS_DIR / "claim_audit.py"
EXAMPLE_LEDGER = REPO_ROOT / "research-scientist" / "references" / "manuscript-ledger.schema-example.json"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ledger_mod = _load_module("check_manuscript_ledger_m10b", LEDGER_SCRIPT)
readiness_mod = _load_module("check_artifact_readiness_m10b", READINESS_SCRIPT)


def _base_ledger() -> dict:
    return json.loads(EXAMPLE_LEDGER.read_text(encoding="utf-8"))


def _make_clean_repo(root: Path, *, anonymous: bool = False) -> dict:
    (root / "LICENSE").write_text(
        "MIT License\n\nCopyright (c) 2026 "
        + ("Anonymous Authors" if anonymous else "Research Team")
        + "\nPermission is hereby granted, free of charge, to any person obtaining a copy...\n",
        encoding="utf-8",
    )
    (root / "requirements.txt").write_text("torch==2.3.1\nnumpy==1.26.4\n", encoding="utf-8")
    (root / "train.py").write_text(
        "import os\nimport random\nimport torch\n\n"
        "def main():\n"
        "    random.seed(42)\n"
        "    torch.manual_seed(42)\n"
        "    api_key = os.environ.get('OPENAI_API_KEY', '')\n"
        "    return len(api_key)\n\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="utf-8",
    )
    url = "https://anonymous.4open.science/r/clean-repo-1234" if anonymous else "https://github.com/org/clean-repo"
    (root / "README.md").write_text(
        f"# Artifact\n\nCode URL: {url}\n\n## Reproduce\n```bash\npython3 train.py\n```\n",
        encoding="utf-8",
    )
    (root / "data").mkdir(exist_ok=True)
    (root / "data" / "sample.csv").write_text("id,contact\n1,demo@example.org\n", encoding="utf-8")
    return {
        "code_license": "MIT",
        "intended_release": "public",
        "datasets": [{"name": "BenchA", "license": "CC-BY-4.0", "redistribution_allowed": True}],
        "pretrained_models": [{"name": "EncoderB", "license": "Apache-2.0"}],
    }


class TestM10BManuscriptArgumentAudits(unittest.TestCase):
    def test_legacy_example_ledger_remains_100_percent_backward_compatible(self) -> None:
        led = _base_ledger()
        res = ledger_mod.check(led)
        self.assertEqual(res["status"], "structure_passed")
        self.assertEqual(res["issues"], [])
        self.assertFalse(res["argument_audits_enabled"])
        self.assertEqual(res["claim_scope_audit"]["status"], "NOT_RUN")
        self.assertEqual(res["contribution_evidence_map"]["status"], "NOT_RUN")
        self.assertEqual(res["related_work_differentiation"]["status"], "NOT_RUN")
        self.assertIsNone(res["argument_audit"]["recommended_transparency_cap"])

    def test_claim_scope_alignment_positive_non_fp_and_negative(self) -> None:
        led = _base_ledger()
        led["methods"][0]["origin"] = "reused"
        led["methods"][0].pop("exact_change", None)
        led["evaluated_scope"] = {
            "datasets": ["MMLU", "GSM8K"],
            "regimes": ["in-distribution"],
            "conditions": ["English-only"],
            "scales": ["7B"],
            "modalities": ["text"],
            "excluded_claims": ["multimodal reasoning"],
            "limitations": ["Evaluated only on English 7B models."],
        }
        good_ms = (
            "# Calibrated Study\n\n"
            "## Abstract\n"
            "We evaluate across all 5 random seeds and all baselines on 2 benchmarks (MMLU and GSM8K). "
            "Our method does not generalize to out-of-distribution settings.\n\n"
            "## Introduction\n"
            "In English-only 7B experiments, accuracy reaches 0.85 score.\n\n"
            "## Limitations\n"
            "Results are restricted to text-only benchmarks and do not cover multimodal reasoning.\n"
        )
        led_clean = copy.deepcopy(led)
        led_clean["numeric_facts"] = [{"id": "N1", "occurrences": [{"location": "body", "value": 0.85, "unit": "score"}]}]
        res_ok = ledger_mod.check(led_clean, manuscript_text=good_ms)
        self.assertEqual(res_ok["claim_scope_audit"]["status"], "PASS", res_ok)
        self.assertEqual(res_ok["status"], "structure_passed", res_ok)

        bad_ms = (
            "# Overclaimed Study\n\n"
            "## Abstract\n"
            "Our approach solves reasoning across all tasks and languages and achieves strong "
            "out-of-distribution generalization across 5 benchmarks, including multimodal reasoning.\n"
        )
        res_bad = ledger_mod.check(copy.deepcopy(led_clean), manuscript_text=bad_ms)
        self.assertEqual(res_bad["claim_scope_audit"]["status"], "FAIL")
        self.assertIn("claim_scope_overclaim:abstract", res_bad["issues"])
        self.assertIn("claim_scope_dataset_count_mismatch:abstract", res_bad["issues"])

        # Missing limitations in both manuscript and evaluated_scope
        led_no_lim = copy.deepcopy(led_clean)
        led_no_lim["evaluated_scope"] = {"datasets": ["MMLU"]}
        res_nolim = ledger_mod.check(led_no_lim, manuscript_text="# Study\n\n## Abstract\nWe test on MMLU.\n")
        self.assertIn("missing_scope_limitations:manuscript", res_nolim["issues"])

    def test_contribution_evidence_map_positive_and_failures(self) -> None:
        led = _base_ledger()
        led["methods"][0]["origin"] = "reused"
        led["methods"][0].pop("exact_change", None)
        led["contributions"] = [
            {
                "id": "CONTRIB_1",
                "text": "Sparse pruning schedule reducing FLOPs.",
                "evidence_ids": ["E1"],
                "anchors": ["Table 1"],
                "receipt_ids": ["run_01"],
                "manuscript_bullet": 1,
            },
            {
                "id": "CONTRIB_2",
                "text": "Theoretical convergence bound.",
                "anchors": ["Theorem 1"],
                "manuscript_bullet": 2,
            },
        ]
        ms_ok = (
            "# Paper\n\n## Introduction\nOur main contributions are:\n"
            "- Sparse pruning schedule reducing FLOPs (Table 1).\n"
            "- Theoretical convergence bound (Theorem 1).\n\n"
            "## Method\nTheorem 1 establishes convergence.\n\n"
            "| Method | Acc |\n|---|---|\n| Baseline | 0.85 |\n\n"
            "Table 1 shows accuracy.\n\n"
            "## Limitations\nLimited to 7B scale.\n"
        )
        led["numeric_facts"] = [{"id": "N1", "occurrences": [{"location": "Table 1", "value": 0.85, "unit": "acc"}]}]
        res_ok = ledger_mod.check(copy.deepcopy(led), manuscript_text=ms_ok, check_scope=False, check_related_work=False)
        self.assertEqual(res_ok["contribution_evidence_map"]["status"], "PASS", res_ok)
        self.assertEqual(res_ok["contribution_evidence_map"]["mapped_count"], 2)

        # Negative: orphan, unknown evidence, unverified source, phantom Table 9, unmapped bullet 3
        led_bad = copy.deepcopy(led)
        led_bad["sources"].append({"id": "S_UNVER", "type": "paper", "locator": "p.2", "verified": False})
        led_bad["contributions"] = [
            {"id": "C_ORPHAN", "text": "Magic module"},
            {"id": "C_UNK", "text": "Unknown link", "evidence_ids": ["S_MISSING"]},
            {"id": "C_UNVER", "text": "Unverified link", "source_ids": ["S_UNVER"]},
            {"id": "C_PHANTOM", "text": "Phantom anchor", "anchors": ["Table 9"]},
        ]
        ms_bad = (
            "# Paper\n\n## Contributions\n"
            "- Unanchored broad claim with zero evidence.\n"
        )
        res_bad = ledger_mod.check(led_bad, manuscript_text=ms_bad, check_scope=False, check_related_work=False)
        self.assertEqual(res_bad["contribution_evidence_map"]["status"], "FAIL")
        self.assertIn("orphan_contribution_without_evidence:C_ORPHAN", res_bad["issues"])
        self.assertIn("unknown_contribution_evidence:C_UNK:S_MISSING", res_bad["issues"])
        self.assertIn("contribution_evidence_unverified:C_UNVER:S_UNVER", res_bad["issues"])
        self.assertIn("contribution_anchor_missing_in_manuscript:C_PHANTOM:table_9", res_bad["issues"])
        self.assertIn("unmapped_manuscript_contribution:bullet_1", res_bad["issues"])

    def test_related_work_differentiation_raw_scorecards_and_compare_output_latex(self) -> None:
        led = _base_ledger()
        led["methods"][0]["origin"] = "reused"
        led["methods"][0].pop("exact_change", None)
        scorecards_raw = {
            "target_id": "OurPaper",
            "profiles": [
                {"id": "OurPaper", "reading_basis": "full_text", "closest_work": ["BM25Plus", "ColBERTv2"]},
                {"id": "BM25Plus", "reading_basis": "full_text", "citation_key": "bm25plus2023", "aliases": ["BM25+"]},
                {"id": "ColBERTv2", "reading_basis": "full_text", "citation_key": "santhanam2022"},
            ],
        }
        tex_ok = (
            "\\title{Clean Retrieval}\n"
            "\\begin{abstract}We evaluate retrieval.\\end{abstract}\n"
            "\\section{Related Work}\n"
            "Unlike BM25+~\\cite{bm25plus2023}, which relies purely on lexical matching, our retriever models dense interactions. "
            "In contrast to ColBERTv2~\\cite{santhanam2022}, we avoid multi-vector index overhead.\n"
            "\\section{Limitations}\nTested only on English corpora.\n"
        )
        res_ok = ledger_mod.check(
            copy.deepcopy(led),
            manuscript_text=tex_ok,
            manuscript_path="paper.tex",
            scorecards=scorecards_raw,
            check_scope=False,
            check_contributions=False,
        )
        self.assertEqual(res_ok["related_work_differentiation"]["status"], "PASS", res_ok)
        self.assertEqual(set(res_ok["related_work_differentiation"]["cited_and_contrasted"]), {"BM25Plus", "ColBERTv2"})

        # Also test compare_scorecards.py output format with generic summary failure & missing competitor
        compare_out = {
            "status": "not_comparable",
            "related_work_comparison": {
                "target_id": "OurPaper",
                "scored_related_ids": ["CompA", "CompB"],
                "unscored_closest_work_ids": ["CompMissing"],
            },
        }
        ms_generic = (
            "# Paper\n\n## Related Work\n"
            "CompA proposes sparse routing. CompB studies dense adapters.\n"
        )
        res_bad = ledger_mod.check(
            copy.deepcopy(led),
            manuscript_text=ms_generic,
            scorecards=compare_out,
            check_scope=False,
            check_contributions=False,
        )
        self.assertEqual(res_bad["related_work_differentiation"]["status"], "FAIL")
        self.assertIn("related_work_panel_incomplete:CompMissing", res_bad["issues"])
        self.assertIn("missing_closest_work_in_manuscript:CompMissing", res_bad["issues"])
        self.assertIn("uncited_closest_work:CompA", res_bad["issues"])
        self.assertIn("related_work_lacks_differentiation:CompA", res_bad["issues"])
        self.assertIn("generic_related_work_summary:manuscript", res_bad["issues"])
        self.assertEqual(res_bad["argument_audit"]["recommended_transparency_cap"], 3)

    def test_redos_linear_time_with_argument_audits_enabled(self) -> None:
        led = _base_ledger()
        led["evaluated_scope"] = {"datasets": ["MMLU"], "limitations": ["English only"]}
        led["contributions"] = [{"id": "C1", "evidence_ids": ["S1"], "anchors": ["Table 1"]}]
        led["closest_work"] = ["BM25"]
        adv = ("\\section[" * 1000) + (" " * 20000) + "\nTable 1 compares BM25 [1] unlike prior work.\n"
        patterns = [v for v in vars(ledger_mod).values() if isinstance(v, re.Pattern)]
        for pat in patterns:
            t0 = time.perf_counter()
            list(pat.finditer(adv))
            self.assertLess(time.perf_counter() - t0, 0.02, pat.pattern)
        t1 = time.perf_counter()
        ledger_mod.check(led, manuscript_text=adv, audit_arguments=True)
        self.assertLess(time.perf_counter() - t1, 0.5)

    def test_phantom_anchor_self_reference_blocked(self) -> None:
        led = _base_ledger()
        led["methods"][0]["origin"] = "reused"
        led["methods"][0].pop("exact_change", None)

        # 1. Markdown phantom Table 99 inside Contributions bullet must FAIL
        led_md = copy.deepcopy(led)
        led_md["contributions"] = [
            {"id": "C1", "text": "Novel pruning reduces latency.", "anchors": ["Table 99"], "manuscript_bullet": 1}
        ]
        ms_md = (
            "# Paper\n\n## Contributions\n- Novel pruning reduces latency (Table 99).\n\n"
            "## Method\nWe prune weights.\n\n## Limitations\nLimited to 7B.\n"
        )
        r_md = ledger_mod.check(led_md, manuscript_text=ms_md, check_scope=False, check_related_work=False)
        self.assertEqual(r_md["contribution_evidence_map"]["status"], "FAIL", r_md)
        self.assertIn("contribution_anchor_missing_in_manuscript:C1:table_99", r_md["issues"])

        # 2. LaTeX phantom \ref{tab:phantom} without \label{tab:phantom} must FAIL
        led_tex = copy.deepcopy(led)
        led_tex["contributions"] = [
            {"id": "C1", "text": "Novel pruning reduces latency.", "anchors": ["\\ref{tab:phantom}"], "manuscript_bullet": 1}
        ]
        ms_tex = (
            "\\title{Paper}\n\\section{Contributions}\n"
            "\\begin{itemize}\\item Novel pruning reduces latency (\\ref{tab:phantom}).\\end{itemize}\n"
            "\\section{Method}\nWe prune weights.\n\\section{Limitations}\nLimited to 7B.\n"
        )
        r_tex = ledger_mod.check(led_tex, manuscript_text=ms_tex, manuscript_path="paper.tex", check_scope=False, check_related_work=False)
        self.assertEqual(r_tex["contribution_evidence_map"]["status"], "FAIL", r_tex)
        self.assertTrue(any(i.startswith("contribution_anchor_missing_in_manuscript:C1:") for i in r_tex["issues"]), r_tex["issues"])

        # Valid LaTeX \ref{tab:real} with \label{tab:real} outside Contributions must PASS
        led_tex_ok = copy.deepcopy(led)
        led_tex_ok["contributions"] = [
            {"id": "C1", "text": "Novel pruning reduces latency.", "anchors": ["\\ref{tab:real}"], "manuscript_bullet": 1}
        ]
        ms_tex_ok = (
            "\\title{Paper}\n\\section{Contributions}\n"
            "\\begin{itemize}\\item Novel pruning reduces latency (\\ref{tab:real}).\\end{itemize}\n"
            "\\section{Experiments}\n\\begin{table}\\caption{Results}\\label{tab:real}\\end{table}\n"
            "\\section{Limitations}\nLimited to 7B.\n"
        )
        r_tex_ok = ledger_mod.check(led_tex_ok, manuscript_text=ms_tex_ok, manuscript_path="paper.tex", check_scope=False, check_related_work=False)
        self.assertEqual(r_tex_ok["contribution_evidence_map"]["status"], "PASS", r_tex_ok)

        # 3. Empty contributions=[] with inline phantom (Table 99) bullet must FAIL
        led_empty = copy.deepcopy(led)
        led_empty["contributions"] = []
        ms_inline = "# Paper\n\n## Contributions\n- We achieve huge gains (Table 99).\n\n## Limitations\nNone.\n"
        r_inline = ledger_mod.check(led_empty, manuscript_text=ms_inline, check_scope=False, check_related_work=False)
        self.assertEqual(r_inline["contribution_evidence_map"]["status"], "FAIL", r_inline)
        self.assertIn("contribution_anchor_missing_in_manuscript:bullet_1:table_99", r_inline["issues"])

    def test_multi_list_introduction_non_fp(self) -> None:
        led = _base_ledger()
        led["methods"][0]["origin"] = "reused"
        led["methods"][0].pop("exact_change", None)
        led["numeric_facts"] = [{"id": "N1", "occurrences": [{"location": "Table 1", "value": 0.85, "unit": "acc"}]}]
        led["contributions"] = [
            {"id": "C1", "text": "Sparse pruning schedule.", "anchors": ["Table 1"], "manuscript_bullet": 1}
        ]
        tex_intro = (
            "\\section{Introduction}\nOur contributions are:\n"
            "\\begin{itemize}\\item Sparse pruning schedule (Table 1).\\end{itemize}\n"
            "We evaluate on the following datasets:\n"
            "\\begin{itemize}\\item MMLU benchmark.\\item GSM8K benchmark.\\end{itemize}\n"
            "\\section{Experiments}\nTable 1 reports accuracy 0.85.\n\\section{Limitations}\nEnglish only.\n"
        )
        r_tex = ledger_mod.check(copy.deepcopy(led), manuscript_text=tex_intro, manuscript_path="p.tex", check_scope=False, check_related_work=False)
        self.assertEqual(r_tex["contribution_evidence_map"]["status"], "PASS", r_tex)
        self.assertEqual(r_tex["issues"], [])

        md_intro = (
            "## Introduction\nOur contributions are:\n- Sparse pruning schedule (Table 1).\n\n"
            "Next we describe our datasets:\n- Dataset A\n- Dataset B\n\n"
            "## Experiments\nTable 1 reports accuracy 0.85.\n\n## Limitations\nEnglish only.\n"
        )
        r_md = ledger_mod.check(copy.deepcopy(led), manuscript_text=md_intro, check_scope=False, check_related_work=False)
        self.assertEqual(r_md["contribution_evidence_map"]["status"], "PASS", r_md)
        self.assertEqual(r_md["issues"], [])

    def test_mixed_caveat_and_overclaim_clause_awareness(self) -> None:
        led = _base_ledger()
        led["methods"][0]["origin"] = "reused"
        led["methods"][0].pop("exact_change", None)
        led["evaluated_scope"] = {
            "datasets": ["MMLU", "GSM8K"],
            "regimes": ["in-distribution"],
            "conditions": ["English-only"],
            "scales": ["7B"],
            "modalities": ["text"],
            "excluded_claims": ["multimodal reasoning"],
            "limitations": ["Evaluated only on English 7B text models."],
        }
        for mixed in (
            "While leaving scaling to future work, our method achieves universal generalization across all tasks and languages on 10 benchmarks, with out-of-distribution generalization and multimodal reasoning.",
            "Although limited to English 7B text, our method solves reasoning across all tasks and languages and achieves out-of-distribution generalization across 8 benchmarks.",
            "Our method achieves universal generalization across all tasks, while scaling to 70B is left to future work.",
        ):
            r = ledger_mod.check(
                copy.deepcopy(led),
                manuscript_text=f"\\begin{{abstract}}{mixed}\\end{{abstract}}",
                manuscript_path="p.tex",
                check_contributions=False,
                check_related_work=False,
            )
            self.assertEqual(r["claim_scope_audit"]["status"], "FAIL", (mixed, r))
            self.assertIn("claim_scope_overclaim:abstract", r["issues"])

        # Legitimate negated disclaimers still PASS
        r_ok = ledger_mod.check(
            copy.deepcopy(led),
            manuscript_text="\\begin{abstract}Our method does not generalize to out-of-distribution settings and we do not claim universal generalization.\\end{abstract}",
            manuscript_path="p.tex",
            check_contributions=False,
            check_related_work=False,
        )
        self.assertEqual(r_ok["claim_scope_audit"]["status"], "PASS", r_ok)


class TestM10BArtifactReadiness(unittest.TestCase):
    def test_clean_repo_and_anonymous_passes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = _make_clean_repo(root, anonymous=True)
            res = readiness_mod.check_readiness(root, manifest, anonymous=True)
            self.assertEqual(res["schema"], "artifact_readiness_v1")
            self.assertEqual(res["status"], "PASS", res)
            self.assertEqual(res["verdict"], "PASS")
            self.assertTrue(res["ready_to_submit"])
            self.assertTrue(res["ready_for_release"])
            self.assertIsNone(res["recommended_transparency_cap"])
            self.assertEqual(res["blocking_reasons"], [])

    def test_license_conflicts_and_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = _make_clean_repo(root)
            manifest["dependencies"] = [{"name": "gpl-lib", "license": "GPL-3.0"}]
            manifest["datasets"].append({"name": "NCData", "license": "CC-BY-NC-4.0"})
            manifest["pretrained_models"].append({"name": "RailModel", "license": "OpenRAIL-M"})
            res = readiness_mod.check_readiness(root, manifest)
            self.assertEqual(res["verdict"], "FAIL")
            self.assertFalse(res["ready_to_submit"])
            self.assertEqual(res["recommended_transparency_cap"], 3)
            checks = {f["check"] for f in res["findings"]}
            self.assertIn("license/copyleft-incompatibility", checks)
            self.assertIn("license/non-commercial-conflict", checks)
            self.assertIn("license/rail-use-restriction-notice", checks)

    def test_pii_redaction_and_non_fp_exemptions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = _make_clean_repo(root)
            raw_ssn = "123-45-6789"
            raw_email = "patient.zero@hospital.org"
            (root / "data" / "patients.csv").write_text(
                f"ssn,email,phone\n{raw_ssn},{raw_email},(415) 555-2671\n",
                encoding="utf-8",
            )
            res = readiness_mod.check_readiness(root, manifest)
            self.assertEqual(res["verdict"], "FAIL")
            serialized = json.dumps(res)
            self.assertNotIn(raw_ssn, serialized)
            self.assertNotIn(raw_email, serialized)
            checks = {f["check"] for f in res["findings"]}
            self.assertIn("pii/sensitive-data-field", checks)
            self.assertIn("pii/ssn-detected", checks)
            self.assertIn("pii/email-in-data", checks)
            self.assertIn("pii/phone-detected", checks)

    def test_reproducibility_comment_and_docstring_seed_spoof_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = _make_clean_repo(root)
            (root / "train.py").write_text(
                '"""torch.manual_seed(42)"""\n# random.seed(0)\n'
                "def run():\n    return 1\n"
                "if __name__ == '__main__':\n    run()\n",
                encoding="utf-8",
            )
            (root / "requirements.txt").write_text("torch\nnumpy\n", encoding="utf-8")
            res = readiness_mod.check_readiness(root, manifest)
            self.assertEqual(res["verdict"], "FAIL")
            checks = {f["check"] for f in res["findings"]}
            self.assertIn("reproducibility/missing-seed", checks)
            self.assertIn("reproducibility/unpinned-dependencies", checks)

    def test_secrets_local_paths_and_anonymization_leaks(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = _make_clean_repo(root, anonymous=False)
            manifest["authors"] = ["Alice Researcher"]
            manifest["affiliations"] = ["Example University"]
            fake_ghp = "ghp_" + "A1B2C3D4E5F6G7H8I9J0K1"
            (root / "config.py").write_text(
                f"CKPT = '/home/alice/checkpoints/model.pt'\n"
                f"SAFE_DEMO = '/home/user/demo'\n"
                f"TOKEN = '{fake_ghp}'\n"
                f"# Author: Alice Researcher, https://github.com/alice/proj\n",
                encoding="utf-8",
            )
            (root / ".git").mkdir()
            (root / ".git" / "config").write_text(
                "[remote \"origin\"]\n\turl = https://github.com/alice/proj.git\n",
                encoding="utf-8",
            )
            res = readiness_mod.check_readiness(root, manifest, anonymous=True)
            self.assertEqual(res["verdict"], "FAIL")
            serialized = json.dumps(res)
            self.assertNotIn(fake_ghp, serialized)
            checks = {f["check"] for f in res["findings"]}
            self.assertIn("local_paths/hardcoded-user-path", checks)
            self.assertIn("secrets/api-key-detected", checks)
            self.assertIn("anonymization/git-dir-present", checks)
            self.assertIn("anonymization/git-remote-leak", checks)
            self.assertIn("anonymization/identifying-url", checks)
            self.assertIn("anonymization/author-name-leak", checks)
            self.assertNotIn("/home/user/demo", serialized)

    def test_security_symlink_escape_bool_traversal_and_redos(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            outside = base / "outside.txt"
            outside_secret = "sk-proj-" + "X9Y8Z7W6V5U4T3S2R1Q0P9"
            outside.write_text(f"KEY='{outside_secret}'\n", encoding="utf-8")
            repo = base / "repo"
            repo.mkdir()
            manifest = _make_clean_repo(repo)
            (repo / "escape.txt").symlink_to(outside)

            res = readiness_mod.check_readiness(repo, manifest)
            self.assertEqual(res["verdict"], "FAIL")
            self.assertNotIn(outside_secret, json.dumps(res))
            self.assertIn("security/unsafe-symlink", {f["check"] for f in res["findings"]})

            with self.assertRaises(ValueError):
                readiness_mod.check_readiness(repo, manifest, max_files=True)  # type: ignore[arg-type]

            bad_manifest = copy.deepcopy(manifest)
            bad_manifest["datasets"][0]["path"] = "../../etc/passwd"
            with self.assertRaises(ValueError):
                readiness_mod.check_readiness(repo, bad_manifest)

            # ReDoS 50KB scan
            (repo / "big.txt").write_text("1" * 50000 + "\n", encoding="utf-8")
            t0 = time.perf_counter()
            readiness_mod.check_readiness(repo, manifest)
            self.assertLess(time.perf_counter() - t0, 0.5)

    def test_bsd_all_rights_reserved_passes_and_proprietary_still_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = _make_clean_repo(root)
            manifest.pop("code_license", None)
            (root / "LICENSE").write_text(
                "BSD 3-Clause License\n\nCopyright (c) 2026, Research Org\nAll rights reserved.\n\n"
                "Redistribution and use in source and binary forms, with or without modification, are permitted.\n",
                encoding="utf-8",
            )
            res = readiness_mod.check_readiness(root, manifest)
            self.assertEqual(res["verdict"], "PASS", res)
            self.assertTrue(res["ready_to_submit"])
            self.assertEqual(res["checks"]["license"]["repo_license"], "bsd")

            # True proprietary without OSI grant still fails
            (root / "LICENSE").write_text("Copyright (c) 2026 Corp. All rights reserved.\n", encoding="utf-8")
            res_prop = readiness_mod.check_readiness(root, manifest)
            self.assertEqual(res_prop["verdict"], "FAIL", res_prop)
            self.assertIn("license/proprietary-not-releasable", {f["check"] for f in res_prop["findings"]})

    def test_email_regex_100kb_hyphenated_linear_time(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = _make_clean_repo(root)
            (root / "hyphen_no_at.txt").write_text(("1-2-3-" * 17066) + "\n", encoding="utf-8")
            (root / "hyphen_with_at.txt").write_text(("1-2-3-" * 17066) + "@\n", encoding="utf-8")
            t0 = time.perf_counter()
            res = readiness_mod.check_readiness(root, manifest)
            elapsed = time.perf_counter() - t0
            self.assertLess(elapsed, 0.5, f"Readiness scan took {elapsed:.3f}s")
            self.assertEqual(res["verdict"], "PASS", res)

    def test_cc_by_nc_repo_license_commercial_release_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _make_clean_repo(root)
            (root / "LICENSE").write_text(
                "Creative Commons Attribution-NonCommercial 4.0 (CC-BY-NC-4.0)\n",
                encoding="utf-8",
            )
            res = readiness_mod.check_readiness(root, {"intended_release": "commercial"})
            self.assertEqual(res["verdict"], "FAIL", res)
            self.assertFalse(res["ready_to_submit"])
            self.assertEqual(res["recommended_transparency_cap"], 3)
            self.assertIn("license/non-commercial-conflict", {f["check"] for f in res["findings"]})


class TestM10BReferencesAndClaimAudit(unittest.TestCase):
    def test_m10b_references_and_scripts_have_zero_claim_audit_findings(self) -> None:
        claim_audit_mod = _load_module("claim_audit_m10b", CLAIM_AUDIT_SCRIPT)
        payload = claim_audit_mod.audit_suite(
            REPO_ROOT,
            readme=REPO_ROOT / "README.md",
        )
        m10b_owned_prefixes = (
            "research-paper-writing/",
            "research-experiment-coding/",
            "research-scientist/scripts/check_manuscript_ledger.py",
            "research-scientist/scripts/check_artifact_readiness.py",
        )
        m10b_findings = [
            f
            for f in payload.get("findings", [])
            if str(f.get("file", "")).startswith(m10b_owned_prefixes)
            or "check_manuscript_ledger.py" in str(f.get("detail", ""))
            or "check_artifact_readiness.py" in str(f.get("detail", ""))
        ]
        self.assertEqual(m10b_findings, [], f"M10B claim_audit findings: {m10b_findings}")

        pw_txt = (REPO_ROOT / "research-paper-writing" / "references" / "paper-writing-preflight-guide.md").read_text(
            encoding="utf-8"
        )
        for flag in ("--audit-arguments", "--check-scope", "--check-contributions", "--check-related-work", "--scorecards", "--target-id", "--out"):
            self.assertIn(flag, pw_txt)
        ec_txt = (REPO_ROOT / "research-experiment-coding" / "references" / "experiment-coding-debugging.md").read_text(
            encoding="utf-8"
        )
        for token in ("check_artifact_readiness.py", "--repo-dir", "--manifest", "--anonymous", "--strict", "--max-files", "PASS", "WARN", "FAIL"):
            self.assertIn(token, ec_txt)


if __name__ == "__main__":
    unittest.main()
