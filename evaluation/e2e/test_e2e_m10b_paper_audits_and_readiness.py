"""Opaque-box subprocess E2E tests for Milestone M10B (F29#4 + F29#5)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "research-scientist" / "scripts"
LEDGER_SCRIPT = SCRIPTS_DIR / "check_manuscript_ledger.py"
READINESS_SCRIPT = SCRIPTS_DIR / "check_artifact_readiness.py"
EXAMPLE_LEDGER = REPO_ROOT / "research-scientist" / "references" / "manuscript-ledger.schema-example.json"


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True, check=False)


def _setup_clean_repo(repo: Path) -> Path:
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "LICENSE").write_text(
        "MIT License\n\nCopyright (c) 2026 Anonymous Authors\n"
        "Permission is hereby granted, free of charge, to any person obtaining a copy...\n",
        encoding="utf-8",
    )
    (repo / "requirements.txt").write_text("torch==2.3.1\n", encoding="utf-8")
    (repo / "run.py").write_text(
        "import os\nimport torch\n\n"
        "def run():\n    torch.manual_seed(42)\n    return os.environ.get('HF_TOKEN', '')\n\n"
        "if __name__ == '__main__':\n    run()\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text(
        "# Anonymous Artifact\n\nRepo: https://anonymous.4open.science/r/m10b-demo\n\n"
        "## Reproduce\n```bash\npython3 run.py\n```\n",
        encoding="utf-8",
    )
    (repo / "data").mkdir(exist_ok=True)
    (repo / "data" / "eval.csv").write_text("id,email\n1,user@example.org\n", encoding="utf-8")
    mpath = repo / "manifest.json"
    mpath.write_text(
        json.dumps(
            {
                "code_license": "MIT",
                "intended_release": "public",
                "datasets": [{"name": "Bench", "license": "CC-BY-4.0"}],
                "pretrained_models": [{"name": "BaseEnc", "license": "Apache-2.0"}],
                "authors": ["Alice SecretAuthor"],
            }
        ),
        encoding="utf-8",
    )
    return mpath


def test_e2e_m10b_clean_paper_and_anonymous_release_pipeline() -> None:
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        ledger = json.loads(EXAMPLE_LEDGER.read_text(encoding="utf-8"))
        ledger["methods"][0]["origin"] = "reused"
        ledger["methods"][0].pop("exact_change", None)
        ledger["numeric_facts"] = [{"id": "N1", "occurrences": [{"location": "Table 1", "value": 0.88, "unit": "acc"}]}]
        ledger["evaluated_scope"] = {
            "datasets": ["MMLU", "GSM8K"],
            "regimes": ["in-distribution"],
            "conditions": ["English-only"],
            "scales": ["7B"],
            "limitations": ["Evaluated only on 7B English benchmarks."],
        }
        ledger["contributions"] = [
            {"id": "C1", "text": "Sparse pruning baseline evaluation.", "evidence_ids": ["E1"], "anchors": ["Table 1"], "manuscript_bullet": 1}
        ]
        led_p = work / "ledger.json"
        led_p.write_text(json.dumps(ledger), encoding="utf-8")

        sc_p = work / "scorecards.json"
        sc_p.write_text(
            json.dumps(
                {
                    "target_id": "OurPaper",
                    "profiles": [
                        {"id": "OurPaper", "reading_basis": "full_text", "closest_work": ["BM25"]},
                        {"id": "BM25", "reading_basis": "full_text", "citation_key": "robertson2009"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        tex_p = work / "paper.tex"
        tex_p.write_text(
            "\\title{Clean Study}\n"
            "\\begin{abstract}We evaluate across all baselines on 2 benchmarks.\\end{abstract}\n"
            "\\section{Introduction}\nOur main contributions are:\n"
            "\\begin{itemize}\\item Sparse pruning baseline evaluation (Table 1).\\end{itemize}\n"
            "\\section{Related Work}\n"
            "Unlike BM25~\\cite{robertson2009}, which relies on lexical overlap, our pipeline uses dense scoring.\n"
            "\\begin{table}\\caption{Table 1 accuracy 0.88.}\\end{table}\n"
            "\\section{Limitations}\nRestricted to English 7B experiments.\n",
            encoding="utf-8",
        )

        led_out = work / "out" / "ledger_audit.json"
        p_led = _run(
            [
                sys.executable, str(LEDGER_SCRIPT),
                "--ledger", str(led_p),
                "--manuscript", str(tex_p),
                "--audit-arguments",
                "--scorecards", str(sc_p),
                "--target-id", "OurPaper",
                "--out", str(led_out),
                "--compact",
            ],
            work,
        )
        assert p_led.returncode == 0, f"{p_led.stdout}\n{p_led.stderr}"
        assert len(p_led.stdout.encode("utf-8")) < 4096
        led_compact = json.loads(p_led.stdout)
        assert led_compact["status"] == "structure_passed"
        assert led_compact["argument_audit"]["claim_scope_alignment"]["status"] == "PASS"
        assert led_compact["argument_audit"]["contribution_evidence_map"]["status"] == "PASS"
        assert led_compact["argument_audit"]["related_work_differentiation"]["status"] == "PASS"
        assert led_out.is_file()

        repo_dir = work / "repo"
        manifest_p = _setup_clean_repo(repo_dir)
        art_out = work / "out" / "readiness.json"
        p_art = _run(
            [
                sys.executable, str(READINESS_SCRIPT),
                "--repo-dir", str(repo_dir),
                "--manifest", str(manifest_p),
                "--anonymous",
                "--out", str(art_out),
                "--compact",
            ],
            work,
        )
        assert p_art.returncode == 0, f"{p_art.stdout}\n{p_art.stderr}"
        assert len(p_art.stdout.encode("utf-8")) < 4096
        art_compact = json.loads(p_art.stdout)
        assert art_compact["status"] == "PASS"
        assert art_compact["verdict"] == "PASS"
        assert art_compact["ready_to_submit"] is True
        assert art_compact["recommended_transparency_cap"] is None
        assert art_out.is_file()


def test_e2e_m10b_argument_audit_failures_and_compact_budget() -> None:
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        ledger = json.loads(EXAMPLE_LEDGER.read_text(encoding="utf-8"))
        ledger["methods"][0]["origin"] = "reused"
        ledger["methods"][0].pop("exact_change", None)
        ledger["evaluated_scope"] = {"datasets": ["MMLU"], "conditions": ["English-only"]}
        ledger["contributions"] = [
            {"id": "C_BAD", "text": "Phantom claim", "anchors": ["Table 9"]},
        ]
        led_p = work / "ledger.json"
        led_p.write_text(json.dumps(ledger), encoding="utf-8")

        cmp_p = work / "compare_out.json"
        cmp_p.write_text(
            json.dumps(
                {
                    "status": "structurally_comparable",
                    "related_work_comparison": {
                        "target_id": "Ours",
                        "scored_related_ids": ["CompX", "CompY"],
                        "unscored_closest_work_ids": [],
                    },
                }
            ),
            encoding="utf-8",
        )
        ms_p = work / "draft.md"
        ms_p.write_text(
            "# Inflated Paper\n\n"
            "## Abstract\nOur method works across all tasks and languages on 4 benchmarks.\n\n"
            "## Contributions\n- Completely ungrounded contribution bullet.\n\n"
            "## Related Work\nCompX introduces sparse indexing. CompY studies dense retrieval.\n",
            encoding="utf-8",
        )
        proc = _run(
            [
                sys.executable, str(LEDGER_SCRIPT),
                "--ledger", str(led_p),
                "--manuscript", str(ms_p),
                "--audit-arguments",
                "--scorecards", str(cmp_p),
                "--compact",
            ],
            work,
        )
        assert proc.returncode == 1, f"{proc.stdout}\n{proc.stderr}"
        assert len(proc.stdout.encode("utf-8")) < 4096
        data = json.loads(proc.stdout)
        assert data["status"] == "structural_issues"
        assert data["argument_audit"]["recommended_transparency_cap"] == 3
        issues = set(data["issues"])
        assert "claim_scope_overclaim:abstract" in issues
        assert "claim_scope_dataset_count_mismatch:abstract" in issues
        assert "contribution_anchor_missing_in_manuscript:C_BAD:table_9" in issues
        assert "unmapped_manuscript_contribution:bullet_1" in issues
        assert "uncited_closest_work:CompX" in issues
        assert "generic_related_work_summary:manuscript" in issues


def test_e2e_m10b_artifact_readiness_blockers_and_redaction() -> None:
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        repo = work / "bad_repo"
        manifest_p = _setup_clean_repo(repo)
        manifest = json.loads(manifest_p.read_text(encoding="utf-8"))
        manifest["dependencies"] = [{"name": "copyleft-pkg", "license": "GPL-3.0"}]
        manifest_p.write_text(json.dumps(manifest), encoding="utf-8")

        fake_tok = "ghp_" + "9876543210abcdefghijkl"
        raw_ssn = "321-54-8765"
        (repo / "run.py").write_text(
            f"# torch.manual_seed(42)\n"
            f"DATA = '/home/alice/data'\n"
            f"TOK = '{fake_tok}'\n"
            f"URL = 'https://github.com/alice/secret-repo'\n",
            encoding="utf-8",
        )
        (repo / "data" / "users.csv").write_text(f"ssn,email\n{raw_ssn},alice@corp.com\n", encoding="utf-8")

        out_p = work / "readiness_full.json"
        proc = _run(
            [
                sys.executable, str(READINESS_SCRIPT),
                "--repo-dir", str(repo),
                "--manifest", str(manifest_p),
                "--anonymous",
                "--out", str(out_p),
                "--compact",
            ],
            work,
        )
        assert proc.returncode == 1, f"{proc.stdout}\n{proc.stderr}"
        assert len(proc.stdout.encode("utf-8")) < 4096
        compact = json.loads(proc.stdout)
        assert compact["verdict"] == "FAIL"
        assert compact["ready_to_submit"] is False
        assert compact["recommended_transparency_cap"] == 3
        full_txt = out_p.read_text(encoding="utf-8")
        assert fake_tok not in full_txt and fake_tok not in proc.stdout
        assert raw_ssn not in full_txt and raw_ssn not in proc.stdout


def test_e2e_m10b_adversarial_cli_nan_empty_symlink_redos() -> None:
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        # 1. Empty --out rejected BEFORE creating dir
        bad_out = work / "never_created" / "report.json"
        p_empty = _run([sys.executable, str(READINESS_SCRIPT), "--out", "   ", "--repo-dir", str(work)], work)
        assert p_empty.returncode == 2
        assert "Traceback" not in p_empty.stderr
        assert "error" in json.loads(p_empty.stderr)
        assert not bad_out.parent.exists()

        # 2. NaN rejected in manifest and ledger with exit 2
        nan_json = work / "nan.json"
        nan_json.write_text('{"code_license": "MIT", "val": NaN}', encoding="utf-8")
        p_nan = _run([sys.executable, str(READINESS_SCRIPT), "--manifest", str(nan_json)], work)
        assert p_nan.returncode == 2
        assert "Traceback" not in p_nan.stderr
        assert "error" in json.loads(p_nan.stderr)

        p_led_empty = _run([sys.executable, str(LEDGER_SCRIPT), "--ledger", str(EXAMPLE_LEDGER), "--out", "  "], work)
        assert p_led_empty.returncode == 2
        assert "error" in json.loads(p_led_empty.stderr)

        # 3. Pathological 50KB LaTeX ReDoS check on check_manuscript_ledger.py
        big_tex = work / "big.tex"
        big_tex.write_text("\\section[" * 5000 + "\n\\section{Limitations}\nBounded.\n", encoding="utf-8")
        t0 = time.perf_counter()
        p_redos = _run(
            [sys.executable, str(LEDGER_SCRIPT), "--ledger", str(EXAMPLE_LEDGER), "--manuscript", str(big_tex), "--audit-arguments"],
            work,
        )
        assert time.perf_counter() - t0 < 2.0
        assert p_redos.returncode in (0, 1)


def test_e2e_m10b_regression_fixes_ledger_and_readiness() -> None:
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        ledger = json.loads(EXAMPLE_LEDGER.read_text(encoding="utf-8"))
        ledger["methods"][0]["origin"] = "reused"
        ledger["methods"][0].pop("exact_change", None)
        ledger["evaluated_scope"] = {
            "datasets": ["MMLU"],
            "regimes": ["in-distribution"],
            "conditions": ["English-only"],
            "limitations": ["English 7B only."],
        }
        ledger["contributions"] = [
            {"id": "C1", "text": "Phantom claim", "anchors": ["Table 99"], "manuscript_bullet": 1}
        ]
        led_p = work / "led.json"
        led_p.write_text(json.dumps(ledger), encoding="utf-8")

        ms_p = work / "paper.md"
        ms_p.write_text(
            "# Paper\n\n## Abstract\nWhile leaving scaling to future work, our method achieves universal generalization across all tasks on 5 benchmarks.\n\n"
            "## Contributions\n- Phantom claim (Table 99).\n\n"
            "## Method\nSimple pruning.\n\n## Limitations\nEnglish only.\n",
            encoding="utf-8",
        )
        p_led = _run(
            [sys.executable, str(LEDGER_SCRIPT), "--ledger", str(led_p), "--manuscript", str(ms_p), "--audit-arguments", "--compact"],
            work,
        )
        assert p_led.returncode == 1, f"{p_led.stdout}\n{p_led.stderr}"
        led_json = json.loads(p_led.stdout)
        issues = set(led_json["issues"])
        assert "contribution_anchor_missing_in_manuscript:C1:table_99" in issues
        assert "claim_scope_overclaim:abstract" in issues

        # BSD-3 with All rights reserved + 100KB hyphenated file passes < 2.0s via subprocess
        repo_bsd = work / "repo_bsd"
        _setup_clean_repo(repo_bsd)
        (repo_bsd / "LICENSE").write_text(
            "BSD 3-Clause License\n\nCopyright (c) 2026, Research Org\nAll rights reserved.\n\n"
            "Redistribution and use in source and binary forms, with or without modification, are permitted.\n",
            encoding="utf-8",
        )
        (repo_bsd / "hyphen.txt").write_text(("1-2-3-" * 17066) + "\n", encoding="utf-8")
        t0 = time.perf_counter()
        p_bsd = _run([sys.executable, str(READINESS_SCRIPT), "--repo-dir", str(repo_bsd), "--compact"], work)
        assert time.perf_counter() - t0 < 2.0
        assert p_bsd.returncode == 0, f"{p_bsd.stdout}\n{p_bsd.stderr}"
        assert json.loads(p_bsd.stdout)["verdict"] == "PASS"

        # CC-BY-NC-4.0 repo with intended_release=commercial fails via subprocess
        (repo_bsd / "hyphen.txt").unlink()
        (repo_bsd / "LICENSE").write_text("Creative Commons Attribution-NonCommercial 4.0 (CC-BY-NC-4.0)\n", encoding="utf-8")
        comm_manifest = work / "comm_manifest.json"
        comm_manifest.write_text(json.dumps({"intended_release": "commercial"}), encoding="utf-8")
        p_nc = _run(
            [sys.executable, str(READINESS_SCRIPT), "--repo-dir", str(repo_bsd), "--manifest", str(comm_manifest), "--compact"],
            work,
        )
        assert p_nc.returncode == 1, f"{p_nc.stdout}\n{p_nc.stderr}"
        nc_json = json.loads(p_nc.stdout)
        assert nc_json["verdict"] == "FAIL"
        assert "license/non-commercial-conflict:LICENSE" in nc_json["blocking_reasons"]
