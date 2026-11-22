"""Opaque-box E2E tests for Milestone M8A: hardened F22 & sync_skills workflows.

Covers:
- Tier 1 (`test_t1_*`): `sync_skills.py --check --out` & overlap protection; `check_rebuttal.py` per-point & receipt workflows.
- Tier 2 (`test_t2_*`): `check_submission_preflight.py` `--prune-unused` + `--verify-online` via `MockScholarlyServer` (`RS_MOCK_BLOCK_UNMOCKED=1`); `check_experiment_rigor.py` `.ipynb`/ancestor `build/`/`rliable`/`contamination`.
- Tier 3 (`test_t3_*`): `check_figure_qa.py` end-to-end mixed figure/script directory QA + `--out` JSON receipt.
"""
from __future__ import annotations

import json
import os
import struct
import zlib
from pathlib import Path

from helpers import MockScholarlyServer, REPO_ROOT, SCRIPTS_DIR, run_cli

SYNC_SKILLS = SCRIPTS_DIR / "sync_skills.py"
EXP_RIGOR = SCRIPTS_DIR / "check_experiment_rigor.py"
REBUTTAL = SCRIPTS_DIR / "check_rebuttal.py"
PREFLIGHT = SCRIPTS_DIR / "check_submission_preflight.py"
FIGURE_QA = SCRIPTS_DIR / "check_figure_qa.py"


def _chunk(ctype: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(ctype + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", crc)


def _make_png(path: Path, width: int, height: int, dpi: int) -> None:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ppm = int(round(dpi / 0.0254))
    phys = struct.pack(">IIB", ppm, ppm, 1)
    idat = zlib.compress(b"\x00" + b"\x00\x00\x00" * width)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"pHYs", phys) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b""))


def test_t1_sync_skills_check_out_and_overlap_guard(tmp_path: Path) -> None:
    # 1. Self-destruct attempt against REPO_ROOT fails with exit 2 without touching REPO_ROOT
    bad = run_cli(SYNC_SKILLS, ["--suite-root", str(REPO_ROOT), "--target-dir", str(REPO_ROOT / "research-scientist")])
    assert bad.returncode == 2
    assert (REPO_ROOT / "research-scientist" / "SKILL.md").is_file()

    # 2. Sync to fresh target with --out receipt + --compact, then verify --check passes even with __pycache__
    target = tmp_path / "cli_skills"
    receipt = tmp_path / "sync_receipt.json"
    res_sync = run_cli(SYNC_SKILLS, ["--suite-root", str(REPO_ROOT), "--target-dir", str(target), "--out", str(receipt), "--compact"])
    assert res_sync.returncode == 0, res_sync.stderr
    assert receipt.is_file()
    assert json.loads(receipt.read_text(encoding="utf-8"))["status"] == "synced"

    pyc_dir = target / "research-scientist" / "scripts" / "__pycache__"
    pyc_dir.mkdir(parents=True, exist_ok=True)
    (pyc_dir / "claim_audit.cpython-313.pyc").write_bytes(b"\x00\x01")
    res_chk = run_cli(SYNC_SKILLS, ["--suite-root", str(REPO_ROOT), "--target-dir", str(target), "--check", "--compact"])
    assert res_chk.returncode == 0, res_chk.stdout
    assert res_chk.json_out["status"] == "in_sync"

    # 3. Drift in installed skill triggers exit 1 under --check
    (target / "research-paper-writing" / "SKILL.md").write_text("drifted\n", encoding="utf-8")
    res_drift = run_cli(SYNC_SKILLS, ["--suite-root", str(REPO_ROOT), "--target-dir", str(target), "--check", "--json"])
    assert res_drift.returncode == 1
    assert res_drift.json_out["status"] == "out_of_sync"


def test_t1_rebuttal_per_point_masking_and_receipt_flow(tmp_path: Path) -> None:
    pts = tmp_path / "points.md"
    pts.write_text("- R1.1: Baseline comparison\n- R1.2: New ablation\n- Q1: Hyperparameters\n", encoding="utf-8")

    # Section-masked draft must fail under --strict
    masked = tmp_path / "masked.md"
    masked.write_text(
        "## Reviewer 1\n"
        "> **R1.2**: Can you run new experiments? See Table 9.\n"
        "- **R1.1**: See Table 1.\n"
        "- **R1.2**: We ran new experiments and saw strong gains.\n"
        "- **Q1**: Set lr=1e-4.\n",
        encoding="utf-8",
    )
    r_fail = run_cli(REBUTTAL, ["coverage", str(pts), str(masked), "--strict", "--json"])
    assert r_fail.returncode == 1
    assert any("R1.2" in s for s in r_fail.json_out["unverified_experiment_claims"])
    assert any("Q1" in s for s in r_fail.json_out["unanchored_sections"])

    # Anchored + run_id receipt draft passes
    clean = tmp_path / "clean.md"
    clean.write_text(
        "## Reviewer 1\n"
        "> Reviewer comment: \"We ran new experiments in Table 9?\"\n"
        "- **R1.1**: See Table 1.\n"
        "- **R1.2**: We ran new experiments (run_id=exp_r1_2, results/abl.json).\n"
        "- **Q1**: See Appendix A (lr=1e-4).\n",
        encoding="utf-8",
    )
    r_ok = run_cli(REBUTTAL, ["coverage", str(pts), str(clean), "--strict", "--compact"])
    assert r_ok.returncode == 0, r_ok.stdout
    assert r_ok.json_out["verdict"] == "PASS"


def test_t2_preflight_arxiv_prune_and_verify_online_mock_server(tmp_path: Path, mock_server: MockScholarlyServer) -> None:
    # A. arXiv clean with --strip-comments-out + --prune-unused + verbatim preservation
    src = tmp_path / "arxiv_src"
    (src / "figs").mkdir(parents=True)
    (src / "drafts").mkdir()
    _make_png(src / "figs" / "arch.png", 900, 600, 300)
    _make_png(src / "drafts" / "arch.png", 900, 600, 300)
    (src / "unused_note.tex").write_text("Old note.\n", encoding="utf-8")
    (src / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\graphicspath{{figs/}}\n"
        "\\begin{document}\n"
        "Accuracy is 92\\% via \\verb|100% deterministic| mode. % TODO: drop bob@uni.edu\n"
        "\\begin{verbatim}\n"
        "% keep verbatim comment\n"
        "\\end{verbatim}\n"
        "\\includegraphics{arch}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "arxiv_out"
    ax = run_cli(PREFLIGHT, ["arxiv-clean", str(src), "--strip-comments-out", str(out_dir), "--prune-unused", "--json"])
    assert ax.returncode == 0, ax.stdout
    assert ax.json_out["verdict"] == "PASS_WITH_WARNINGS"
    assert (out_dir / "figs" / "arch.png").is_file()
    assert not (out_dir / "drafts" / "arch.png").exists()
    assert not (out_dir / "unused_note.tex").exists()
    cleaned = (out_dir / "main.tex").read_text(encoding="utf-8")
    assert "\\verb|100% deterministic|" in cleaned
    assert "% keep verbatim comment" in cleaned
    assert "bob@uni.edu" not in cleaned

    # B. BibTeX --verify-online via MockScholarlyServer (Crossref -> arXiv + OpenAlex fallback)
    mock_server.add_route(
        "/works/",
        (404, "application/json", json.dumps({"status": "failed"})),
        host="api.crossref.org",
    )
    mock_server.add_route(
        "/api/query",
        (
            200,
            "application/atom+xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<feed xmlns="http://www.w3.org/2005/Atom">'
            '<entry><title>Unified Graph Scaling Laws</title><published>2025-01-10T00:00:00Z</published></entry>'
            '</feed>',
        ),
        host="export.arxiv.org",
    )
    mock_server.add_json(
        "/works",
        {"results": [{"title": "Robust Vision Transformers", "publication_year": 2024}]},
        host="api.openalex.org",
    )

    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{graph2025,\n"
        "  title = {Unified Graph Scaling Laws},\n"
        "  author = {Smith, Alice},\n"
        "  journal = {arXiv preprint},\n"
        "  eprint = {2501.00123},\n"
        "  year = {2025}\n"
        "}\n"
        "@inproceedings{vit2024,\n"
        "  title = {Robust Vision Transformers},\n"
        "  author = {Tan, Wei},\n"
        "  booktitle = {NeurIPS},\n"
        "  doi = {10.5555/oa-only},\n"
        "  year = {2024}\n"
        "}\n",
        encoding="utf-8",
    )
    bb = run_cli(
        PREFLIGHT,
        ["bibtex", str(bib), "--verify-online", "--json"],
        env=mock_server.env(),
    )
    assert bb.returncode == 0, bb.stdout + bb.stderr
    assert not [f for f in bb.json_out["findings"] if f["check"] == "bibtex/online-mismatch"]


def test_t2_rigor_build_ancestor_ipynb_and_contamination(tmp_path: Path) -> None:
    proj = tmp_path / "build" / "ml_repo"
    (proj / "data").mkdir(parents=True)
    (proj / "tests").mkdir()
    (proj / "tests" / "test_unit.py").write_text("def test_pass(): assert True\n", encoding="utf-8")
    (proj / "README.md").write_text("Download dataset from HF Hub.\n```bash\npython train.py\n```\n", encoding="utf-8")
    (proj / "requirements.txt").write_text("torch==2.5.1\n", encoding="utf-8")
    (proj / "train.py").write_text("import torch\ntorch.manual_seed(42)\nif __name__ == '__main__':\n    pass\n", encoding="utf-8")
    (proj / "nb.ipynb").write_text(json.dumps({"cells": [{"cell_type": "markdown", "source": ["set_seed(0)"]}]}), encoding="utf-8")

    r_ok = run_cli(EXP_RIGOR, ["repro", str(proj), "--strict", "--compact"])
    assert r_ok.returncode == 0, r_ok.stdout
    assert r_ok.json_out["verdict"] == "PASS"

    tr = tmp_path / "train.jsonl"
    ev = tmp_path / "eval.jsonl"
    tr.write_text(json.dumps({"id": "train_99", "text": "exact duplicate prompt"}) + "\n", encoding="utf-8")
    ev.write_text(json.dumps({"id": "eval_01", "text": "exact duplicate prompt"}) + "\n", encoding="utf-8")
    c_bad = run_cli(EXP_RIGOR, ["contamination", "--train", str(tr), "--eval", str(ev), "--json"])
    assert c_bad.returncode == 1
    assert c_bad.json_out["exact_match_count"] == 1


def test_t3_figure_qa_mixed_directory_and_out_receipt(tmp_path: Path) -> None:
    figs = tmp_path / "figs"
    (figs / ".venv").mkdir(parents=True)
    (figs / ".venv" / "ignored.py").write_text("plt.imshow(x, cmap='jet')\n", encoding="utf-8")
    _make_png(figs / "clean.png", 1200, 800, 300)
    (figs / "plot.py").write_text(
        "# avoid cmap='jet' and plt.savefig('bad.jpg')\n"
        "import matplotlib.pyplot as plt\n"
        "plt.rcParams['pdf.fonttype'] = 42\n"
        "plt.imshow([[1, 2]], cmap='viridis')\n"
        "plt.savefig('clean.pdf')\n",
        encoding="utf-8",
    )
    receipt = tmp_path / "fig_receipt.json"
    res = run_cli(FIGURE_QA, ["figure", str(figs), "--strict", "--out", str(receipt), "--compact"])
    assert res.returncode == 0, res.stdout
    assert receipt.is_file()
    full = json.loads(receipt.read_text(encoding="utf-8"))
    assert full["checked_count"] == 2
    assert full["verdict"] == "PASS"
