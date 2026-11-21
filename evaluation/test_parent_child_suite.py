"""Unmocked tests for Milestone M7: Parent-Child Hub-and-Spoke Suite, Codex openai.yaml, sync_skills, claim_audit --suite-root, and F22 tools."""

from __future__ import annotations

import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import threading
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import fitz
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
PARENT_DIR = REPO_ROOT / "research-scientist"
SCRIPTS_DIR = PARENT_DIR / "scripts"

SUB_SKILLS = (
    "research-precedent-corpus",
    "research-gap-rq-audit",
    "research-experiment-coding",
    "research-novelty-venue",
    "research-paper-writing",
    "research-user-report",
)
ALL_SKILLS = ("research-scientist", *SUB_SKILLS)

CLAIM_AUDIT = SCRIPTS_DIR / "claim_audit.py"
SYNC_SKILLS = SCRIPTS_DIR / "sync_skills.py"
EXP_RIGOR = SCRIPTS_DIR / "check_experiment_rigor.py"
REBUTTAL = SCRIPTS_DIR / "check_rebuttal.py"
PREFLIGHT = SCRIPTS_DIR / "check_submission_preflight.py"
FIGURE_QA = SCRIPTS_DIR / "check_figure_qa.py"

MAX_COMPACT_BYTES = 4096


def _run(
    script: Path,
    args: list[str],
    cwd: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=str(cwd or REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _make_png(path: Path, width: int, height: int, dpi: int) -> None:
    def _chunk(ctype: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(ctype + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ppm = int(round(dpi / 0.0254))
    phys = struct.pack(">IIB", ppm, ppm, 1)
    idat = zlib.compress(b"\x00" + b"\x00\x00\x00" * width)
    raw = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"pHYs", phys) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")
    path.write_bytes(raw)


def _make_pdf_pages(path: Path, pages: list[str]) -> None:
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(50, 50, 540, 750), text, fontsize=11)
    doc.save(str(path))
    doc.close()


# ---------------------------------------------------------------------------
# 1. Parent + 6 Sub-Skills Structure, Token Budgets, openai.yaml & claim_audit
# ---------------------------------------------------------------------------


def test_all_7_skills_structure_budgets_openai_yaml_and_no_duplication() -> None:
    parent_skill = (PARENT_DIR / "SKILL.md").read_text(encoding="utf-8")
    for sname in ALL_SKILLS:
        sdir = REPO_ROOT / sname
        assert sdir.is_dir(), f"Missing skill directory: {sdir}"
        skill_md = sdir / "SKILL.md"
        assert skill_md.is_file(), f"Missing SKILL.md in {sname}"
        raw = skill_md.read_text(encoding="utf-8")
        lines = raw.splitlines()
        assert len(lines) <= 95, f"{sname}/SKILL.md exceeds 95 lines ({len(lines)})"

        yaml_path = sdir / "agents" / "openai.yaml"
        assert yaml_path.is_file(), f"Missing Codex metadata: {yaml_path}"
        parsed = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        assert isinstance(parsed, dict) and isinstance(parsed.get("interface"), dict)
        iface = parsed["interface"]
        assert isinstance(iface.get("display_name"), str) and iface["display_name"].strip()
        assert isinstance(iface.get("short_description"), str) and iface["short_description"].strip()
        assert isinstance(iface.get("default_prompt"), str) and f"${sname}" in iface["default_prompt"]

        if sname != "research-scientist":
            assert f"../{sname}/SKILL.md" in parent_skill, f"Parent SKILL.md missing route to {sname}"
            assert not (sdir / "scripts").exists(), f"Sub-skill {sname} must NOT duplicate scripts/"
            assert not (sdir / "modules").exists(), f"Sub-skill {sname} must NOT duplicate modules/"
            assert "../research-scientist/scripts/" in raw, f"{sname}/SKILL.md must reference shared parent scripts"

    res = _run(CLAIM_AUDIT, ["--suite-root", str(REPO_ROOT), "--json"])
    assert res.returncode == 0, f"stdout={res.stdout}\nstderr={res.stderr}"
    report = json.loads(res.stdout)
    assert report["status"] == "passed"
    assert report["finding_count"] == 0
    assert len(report["skills_audited"]) == 7
    for entry in report["skills_audited"]:
        fp = entry["footprint"]
        assert fp["est_tokens"] <= 1100
        assert fp["frontmatter_est_tokens"] <= 140

    cmp_res = _run(CLAIM_AUDIT, ["--suite-root", str(REPO_ROOT), "--json", "--compact"])
    assert cmp_res.returncode == 0
    assert len(cmp_res.stdout.encode("utf-8")) < MAX_COMPACT_BYTES
    assert json.loads(cmp_res.stdout)["compact"] is True


def test_claim_audit_suite_root_catches_duplication_missing_yaml_secrets_and_broken_refs(tmp_path: Path) -> None:
    suite_copy = tmp_path / "suite"
    for sname in ALL_SKILLS:
        shutil.copytree(REPO_ROOT / sname, suite_copy / sname, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    assert _run(CLAIM_AUDIT, ["--suite-root", str(suite_copy), "--json"]).returncode == 0

    # Empty suite-root exits 2
    assert _run(CLAIM_AUDIT, ["--suite-root", ""]).returncode == 2
    assert _run(CLAIM_AUDIT, ["--suite-root", str(tmp_path / "missing")]).returncode == 2

    # 1. Duplicated scripts/ dir in sub-skill
    (suite_copy / "research-paper-writing" / "scripts").mkdir()
    r_dup = json.loads(_run(CLAIM_AUDIT, ["--suite-root", str(suite_copy), "--json"]).stdout)
    assert any(f["kind"] == "duplicated-dir" for f in r_dup["findings"])
    (suite_copy / "research-paper-writing" / "scripts").rmdir()

    # 2. Missing openai.yaml
    (suite_copy / "research-user-report" / "agents" / "openai.yaml").unlink()
    r_yaml = json.loads(_run(CLAIM_AUDIT, ["--suite-root", str(suite_copy), "--json"]).stdout)
    assert any(f["kind"] == "missing-openai-yaml" for f in r_yaml["findings"])
    shutil.copy2(REPO_ROOT / "research-user-report" / "agents" / "openai.yaml", suite_copy / "research-user-report" / "agents" / "openai.yaml")

    # 3. Broken shared script & bogus flag
    sp = suite_copy / "research-novelty-venue" / "SKILL.md"
    orig_sp = sp.read_text(encoding="utf-8")
    sp.write_text(orig_sp + "\nRun `../research-scientist/scripts/check_rebuttal.py --bogus-flag`.\n", encoding="utf-8")
    r_flag = json.loads(_run(CLAIM_AUDIT, ["--suite-root", str(suite_copy), "--json"]).stdout)
    assert any(f["kind"] == "missing-flag" and f["token"] == "--bogus-flag" for f in r_flag["findings"])
    sp.write_text(orig_sp, encoding="utf-8")

    # 4. Hardcoded secret leak
    rp = suite_copy / "research-precedent-corpus" / "references" / "corpus-retrieval-protocol.md"
    rp.write_text(rp.read_text(encoding="utf-8") + "\nS2_API_KEY='ABCDEFGHIJKLMNOP123456'\n", encoding="utf-8")
    r_sec = json.loads(_run(CLAIM_AUDIT, ["--suite-root", str(suite_copy), "--json"]).stdout)
    assert any(f["kind"] == "secret-leak" for f in r_sec["findings"])


# ---------------------------------------------------------------------------
# 2. Installed-Layout Simulation via sync_skills.py
# ---------------------------------------------------------------------------


def test_sync_skills_dry_run_and_installed_layout_resolution(tmp_path: Path) -> None:
    dry_target = tmp_path / "dry_skills"
    dry_res = _run(SYNC_SKILLS, ["--suite-root", str(REPO_ROOT), "--target-dir", str(dry_target), "--dry-run", "--json", "--compact"])
    assert dry_res.returncode == 0, dry_res.stderr
    assert len(dry_res.stdout.encode("utf-8")) < MAX_COMPACT_BYTES
    dry_data = json.loads(dry_res.stdout)
    assert dry_data["status"] == "dry_run"
    assert not dry_target.exists()

    installed_root = tmp_path / "installed_cli_skills"
    sync_res = _run(SYNC_SKILLS, ["--suite-root", str(REPO_ROOT), "--target-dir", str(installed_root), "--json", "--compact"])
    assert sync_res.returncode == 0, sync_res.stderr
    assert len(sync_res.stdout.encode("utf-8")) < MAX_COMPACT_BYTES
    sync_data = json.loads(sync_res.stdout)
    assert sync_data["status"] == "synced"
    assert sync_data["targets"][0]["count"] == 7
    assert sync_data["targets"][0]["resolved"] is True

    # Verify every installed sub-skill resolves parent scripts cleanly and passes claim_audit
    for sub in SUB_SKILLS:
        probe = (installed_root / sub / ".." / "research-scientist" / "scripts" / "check_experiment_rigor.py").resolve()
        assert probe.is_file(), f"Installed sub-skill {sub} failed to resolve parent script"

    audit_installed = _run(CLAIM_AUDIT, ["--suite-root", str(installed_root), "--json"])
    assert audit_installed.returncode == 0, audit_installed.stdout
    assert json.loads(audit_installed.stdout)["finding_count"] == 0

    assert _run(SYNC_SKILLS, ["--target-dir", ""]).returncode == 2
    assert _run(SYNC_SKILLS, ["--suite-root", str(tmp_path / "nope")]).returncode == 2


# ---------------------------------------------------------------------------
# 3. F22 Tool 1: check_experiment_rigor.py (repro, rliable, contamination)
# ---------------------------------------------------------------------------


def test_check_experiment_rigor_repro_rliable_and_contamination(tmp_path: Path) -> None:
    # A. repro: positive vs negative vs exit 2
    good_repo = tmp_path / "good_repo"
    (good_repo / "data").mkdir(parents=True)
    (good_repo / "tests").mkdir()
    (good_repo / "tests" / "test_smoke.py").write_text("def test_ok(): assert True\n", encoding="utf-8")
    (good_repo / "README.md").write_text("# Good Repo\nDownload dataset from Zenodo.\n```bash\npython3 train.py --seed 42\n```\n", encoding="utf-8")
    (good_repo / "requirements.txt").write_text("torch==2.5.1\nnumpy==2.1.0\n", encoding="utf-8")
    (good_repo / "train.py").write_text("import torch\ntorch.manual_seed(42)\nif __name__ == '__main__':\n    print('ok')\n", encoding="utf-8")

    r_ok = _run(EXP_RIGOR, ["repro", str(good_repo), "--strict", "--compact"])
    assert r_ok.returncode == 0, r_ok.stdout + r_ok.stderr
    assert len(r_ok.stdout.encode("utf-8")) < MAX_COMPACT_BYTES
    assert json.loads(r_ok.stdout)["verdict"] == "PASS"

    bad_repo = tmp_path / "bad_repo"
    bad_repo.mkdir()
    (bad_repo / "helper.py").write_text("x = 1\n", encoding="utf-8")
    r_bad = _run(EXP_RIGOR, ["repro", str(bad_repo), "--json"])
    assert r_bad.returncode == 1
    assert set(json.loads(r_bad.stdout)["missing"]) >= {"README", "ENV", "SEED"}

    assert _run(EXP_RIGOR, ["repro", ""]).returncode == 2
    assert _run(EXP_RIGOR, ["repro", str(tmp_path / "missing")]).returncode == 2

    # B. rliable: positive IQM/CI/P(X>Y) vs negative underpowered/NaN
    scores_file = tmp_path / "scores.json"
    scores_file.write_text(
        json.dumps({
            "baseline": "ItemKNN",
            "methods": {
                "ItemKNN": [[0.30, 0.40], [0.31, 0.41], [0.29, 0.39], [0.30, 0.40], [0.32, 0.42]],
                "SimpleLin": [[0.36, 0.46], [0.37, 0.47], [0.35, 0.45], [0.38, 0.48], [0.36, 0.46]],
            },
        }),
        encoding="utf-8",
    )
    rl_ok = _run(EXP_RIGOR, ["rliable", str(scores_file), "--reps", "200", "--strict", "--compact"])
    assert rl_ok.returncode == 0, rl_ok.stdout + rl_ok.stderr
    assert len(rl_ok.stdout.encode("utf-8")) < MAX_COMPACT_BYTES
    rl_data = json.loads(rl_ok.stdout)
    assert rl_data["methods"]["SimpleLin"]["iqm"] > rl_data["methods"]["ItemKNN"]["iqm"]
    assert rl_data["methods"]["SimpleLin"]["prob_improvement_vs_baseline"] == 1.0
    ci = rl_data["methods"]["SimpleLin"]["iqm_ci95"]
    assert ci[0] <= rl_data["methods"]["SimpleLin"]["iqm"] <= ci[1]

    under_file = tmp_path / "under.json"
    under_file.write_text(json.dumps({"methods": {"OnlyOneSeed": [[0.5, 0.6]]}}), encoding="utf-8")
    assert _run(EXP_RIGOR, ["rliable", str(under_file), "--strict", "--json"]).returncode == 1

    nan_file = tmp_path / "nan.json"
    nan_file.write_text('{"methods": {"M": [NaN, 0.5]}}', encoding="utf-8")
    assert _run(EXP_RIGOR, ["rliable", str(nan_file)]).returncode == 2

    # C. contamination: positive clean vs negative 8-gram leak
    train_f = tmp_path / "train.jsonl"
    eval_clean = tmp_path / "eval_clean.jsonl"
    eval_dirty = tmp_path / "eval_dirty.jsonl"
    train_f.write_text(
        json.dumps({"text": "Graph convolutional networks propagate node features across normalized adjacency matrices efficiently."}) + "\n",
        encoding="utf-8",
    )
    eval_clean.write_text(
        json.dumps({"text": "Transformer attention heads weight pairwise token similarity scores across sequence positions."}) + "\n",
        encoding="utf-8",
    )
    eval_dirty.write_text(
        json.dumps({"text": "We note that graph convolutional networks propagate node features across normalized adjacency matrices in tests."}) + "\n",
        encoding="utf-8",
    )
    c_ok = _run(EXP_RIGOR, ["contamination", "--train", str(train_f), "--eval", str(eval_clean), "--compact"])
    assert c_ok.returncode == 0
    assert len(c_ok.stdout.encode("utf-8")) < MAX_COMPACT_BYTES
    assert json.loads(c_ok.stdout)["verdict"] == "PASS"

    c_bad = _run(EXP_RIGOR, ["contamination", "--train", str(train_f), "--eval", str(eval_dirty), "--json"])
    assert c_bad.returncode == 1
    assert json.loads(c_bad.stdout)["verdict"] == "CONTAMINATION_DETECTED"
    assert _run(EXP_RIGOR, ["contamination", "--train", "", "--eval", str(eval_clean)]).returncode == 2


# ---------------------------------------------------------------------------
# 4. F22 Tool 2: check_rebuttal.py (budget & coverage)
# ---------------------------------------------------------------------------


def test_check_rebuttal_budget_and_coverage(tmp_path: Path) -> None:
    reb_ok = tmp_path / "rebuttal_ok.md"
    reb_ok.write_text(
        "## R1\nAddressing R1.1 and R1.2: see Table 2 and Sec. 4 for the 5-seed ablation.\n\n"
        "## AC\nAddressing AC.1: we clarified the limitation in Appendix A.\n",
        encoding="utf-8",
    )
    b_ok = _run(REBUTTAL, ["budget", str(reb_ok), "--sections", "--limit", "500", "--compact"])
    assert b_ok.returncode == 0
    assert len(b_ok.stdout.encode("utf-8")) < MAX_COMPACT_BYTES

    b_over = _run(REBUTTAL, ["budget", str(reb_ok), "--sections", "--limit", "40", "--json"])
    assert b_over.returncode == 1
    assert json.loads(b_over.stdout)["verdict"] == "OVER_BUDGET"

    pdf_1p = tmp_path / "reb_1p.pdf"
    pdf_2p = tmp_path / "reb_2p.pdf"
    _make_pdf_pages(pdf_1p, ["One page CVPR rebuttal with Table 1."])
    _make_pdf_pages(pdf_2p, ["Page 1 rebuttal.", "Page 2 overflow."])
    assert _run(REBUTTAL, ["budget", str(pdf_1p), "--max-pages", "1", "--compact"]).returncode == 0
    assert _run(REBUTTAL, ["budget", str(pdf_2p), "--max-pages", "1", "--json"]).returncode == 1
    assert _run(REBUTTAL, ["budget", ""]).returncode == 2

    pts = tmp_path / "points.md"
    pts.write_text("- R1.1: Baseline fairness\n- R1.2: Seed variance\n- AC.1: Scope\n", encoding="utf-8")
    cov_ok = _run(REBUTTAL, ["coverage", str(pts), str(reb_ok), "--strict", "--compact"])
    assert cov_ok.returncode == 0
    assert len(cov_ok.stdout.encode("utf-8")) < MAX_COMPACT_BYTES
    assert json.loads(cov_ok.stdout)["verdict"] == "PASS"

    reb_bad = tmp_path / "reb_bad.md"
    reb_bad.write_text("## R1\nFor R1.1 and R1.2, we ran new experiments and they confirm huge gains.\n", encoding="utf-8")
    cov_bad = _run(REBUTTAL, ["coverage", str(pts), str(reb_bad), "--strict", "--json"])
    assert cov_bad.returncode == 1
    cov_data = json.loads(cov_bad.stdout)
    assert "AC.1" in cov_data["missing_points"]
    assert cov_data["unanchored_sections"]
    assert cov_data["unverified_experiment_claims"]

    # Flat/headerless rebuttal (no '##' headings) must NOT skip (preamble) audit
    pts_single = tmp_path / "pts_single.md"
    pts_single.write_text("- R1.1: Run ablation\n", encoding="utf-8")
    reb_flat = tmp_path / "reb_flat.md"
    reb_flat.write_text("For R1.1 we ran new experiments and got +10% accuracy.\n", encoding="utf-8")
    cov_flat = _run(REBUTTAL, ["coverage", str(pts_single), str(reb_flat), "--strict", "--json"])
    assert cov_flat.returncode == 1, cov_flat.stdout + cov_flat.stderr
    flat_data = json.loads(cov_flat.stdout)
    assert any("(preamble)" in s for s in flat_data["unanchored_sections"])
    assert any("(preamble)" in s for s in flat_data["unverified_experiment_claims"])

    # Preamble before first '##' that contains point IDs/claims is audited; benign intro preamble is skipped
    reb_preamble_claim = tmp_path / "reb_preamble_claim.md"
    reb_preamble_claim.write_text(
        "# Rebuttal\nFor R1.1 we ran new experiments and got +10% accuracy.\n\n"
        "## R1.2 & AC.1\nAddressing R1.2 and AC.1: see Table 1 and Appendix A.\n",
        encoding="utf-8",
    )
    cov_pre_claim = _run(REBUTTAL, ["coverage", str(pts), str(reb_preamble_claim), "--strict", "--json"])
    assert cov_pre_claim.returncode == 1
    pre_claim_data = json.loads(cov_pre_claim.stdout)
    assert any("(preamble)" in s for s in pre_claim_data["unanchored_sections"])
    assert any("(preamble)" in s for s in pre_claim_data["unverified_experiment_claims"])

    reb_benign_intro = tmp_path / "reb_benign_intro.md"
    reb_benign_intro.write_text(
        "# Author Response\nWe thank all reviewers for their constructive feedback.\n\n"
        "## Responses\nAddressing R1.1, R1.2, and AC.1: see Table 2 and Sec. 4.\n",
        encoding="utf-8",
    )
    cov_intro = _run(REBUTTAL, ["coverage", str(pts), str(reb_benign_intro), "--strict", "--json"])
    assert cov_intro.returncode == 0, cov_intro.stdout
    assert json.loads(cov_intro.stdout)["verdict"] == "PASS"


# ---------------------------------------------------------------------------
# 5. F22 Tool 3: check_submission_preflight.py (anonymize, arxiv-clean, bibtex)
# ---------------------------------------------------------------------------


def test_check_submission_preflight_anonymize_arxiv_and_bibtex(tmp_path: Path) -> None:
    # A. anonymize: clean vs leaky vs camera-ready leftover
    clean_tex = tmp_path / "clean.tex"
    clean_tex.write_text(
        "\\documentclass{article}\n\\author{Anonymous Authors}\n\\begin{document}\n"
        "Code at https://anonymous.4open.science/r/abc123.\n\\end{document}\n",
        encoding="utf-8",
    )
    an_ok = _run(PREFLIGHT, ["anonymize", str(clean_tex), "--strict", "--compact"])
    assert an_ok.returncode == 0, an_ok.stdout
    assert len(an_ok.stdout.encode("utf-8")) < MAX_COMPACT_BYTES

    leaky_tex = tmp_path / "leaky.tex"
    leaky_tex.write_text(
        "\\documentclass{article}\n\\author{Jane Doe}\n\\begin{document}\n"
        "Repo: https://github.com/janedoe/proj and /home/janedoe/data.\n"
        "\\section*{Acknowledgments}\nFunded by NSF 1234567.\n\\end{document}\n",
        encoding="utf-8",
    )
    an_bad = _run(PREFLIGHT, ["anonymize", str(leaky_tex), "--json"])
    assert an_bad.returncode == 1
    checks = {f["check"] for f in json.loads(an_bad.stdout)["findings"]}
    assert {"anonymization/author-block", "anonymization/identifying-link", "anonymization/home-path", "anonymization/acknowledgments"}.issubset(checks)

    cr_bad = _run(PREFLIGHT, ["anonymize", str(clean_tex), "--mode", "camera-ready", "--json"])
    assert cr_bad.returncode == 1
    assert _run(PREFLIGHT, ["anonymize", ""]).returncode == 2

    # B. arxiv-clean: dirty comments + unused figure + strip_comments_out
    tex_dir = tmp_path / "arxiv_src"
    tex_dir.mkdir()
    (tex_dir / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "Gain is 12\\% over baseline. % TODO: remove alice@uni.edu before upload\n"
        "\\includegraphics{used.png}\n\\end{document}\n",
        encoding="utf-8",
    )
    _make_png(tex_dir / "used.png", 800, 600, 300)
    _make_png(tex_dir / "unused.png", 800, 600, 300)
    stripped_dir = tmp_path / "arxiv_clean_out"
    ax_res = _run(PREFLIGHT, ["arxiv-clean", str(tex_dir), "--strip-comments-out", str(stripped_dir), "--strict", "--compact"])
    assert ax_res.returncode == 1
    assert len(ax_res.stdout.encode("utf-8")) < MAX_COMPACT_BYTES
    cleaned_tex = (stripped_dir / "main.tex").read_text(encoding="utf-8")
    assert "alice@uni.edu" not in cleaned_tex
    assert "12\\%" in cleaned_tex

    # C. bibtex: rebiber protect_title_caps + undefined \cite{} + duplicate key
    bib_bad = tmp_path / "refs.bib"
    bib_bad.write_text(
        "@inproceedings{devlin2019,\n  title = {Pre-training of BERT for 3D NLP},\n  author = {Devlin, Jacob},\n  booktitle = {NAACL},\n  year = {2019}\n}\n",
        encoding="utf-8",
    )
    tex_cite = tmp_path / "paper_cite.tex"
    tex_cite.write_text("\\cite{devlin2019,missing2025}\n", encoding="utf-8")
    bib_fixed = tmp_path / "refs_fixed.bib"
    bb_res = _run(PREFLIGHT, ["bibtex", str(bib_bad), "--tex", str(tex_cite), "--protect-caps", "--fix-out", str(bib_fixed), "--compact"])
    assert bb_res.returncode == 1
    assert len(bb_res.stdout.encode("utf-8")) < MAX_COMPACT_BYTES
    bb_data = json.loads(bb_res.stdout)
    assert any(f["check"] == "bibtex/undefined-cite" and f["key"] == "missing2025" for f in bb_data["findings"])
    fixed_text = bib_fixed.read_text(encoding="utf-8")
    assert "{BERT}" in fixed_text and "{3D}" in fixed_text and "{{BERT}}" not in fixed_text
    assert _run(PREFLIGHT, ["bibtex", ""]).returncode == 2


def test_check_submission_preflight_verify_online_local_http_server(tmp_path: Path) -> None:
    seen_headers: list[str] = []

    class _CrossrefHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            seen_headers.append(self.headers.get("User-Agent", ""))
            if self.path == "/works/10.5555/3295222.3295720":
                payload = {"message": {"title": ["Attention Is All You Need"], "issued": {"date-parts": [[2017]]}}}
            elif self.path == "/works/10.5555/mismatch":
                payload = {"message": {"title": ["Completely Different Study"], "issued": {"date-parts": [[2021]]}}}
            else:
                self.send_response(404)
                self.end_headers()
                return
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _CrossrefHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        bib_ok = tmp_path / "online_ok.bib"
        bib_ok.write_text(
            "@inproceedings{vaswani2017,\n"
            "  title = {Attention Is All You Need},\n"
            "  author = {Vaswani, Ashish},\n"
            "  booktitle = {NeurIPS},\n"
            "  year = {2017},\n"
            "  doi = {10.5555/3295222.3295720}\n"
            "}\n",
            encoding="utf-8",
        )
        res_ok = _run(
            PREFLIGHT,
            ["bibtex", str(bib_ok), "--verify-online", "--strict", "--json"],
            extra_env={"CROSSREF_API_BASE": f"http://127.0.0.1:{port}"},
        )
        assert res_ok.returncode == 0, f"stdout={res_ok.stdout}\nstderr={res_ok.stderr}"
        assert "AttributeError" not in res_ok.stderr
        assert json.loads(res_ok.stdout)["verdict"] == "PASS"
        assert "research-scientist-preflight/1.0" in seen_headers

        bib_bad = tmp_path / "online_mismatch.bib"
        bib_bad.write_text(
            "@inproceedings{vaswani2017,\n"
            "  title = {Attention Is All You Need},\n"
            "  author = {Vaswani, Ashish},\n"
            "  booktitle = {NeurIPS},\n"
            "  year = {2017},\n"
            "  doi = {10.5555/mismatch}\n"
            "}\n",
            encoding="utf-8",
        )
        res_bad = _run(
            PREFLIGHT,
            ["bibtex", str(bib_bad), "--verify-online", "--json"],
            extra_env={"CROSSREF_API_BASE": f"http://127.0.0.1:{port}"},
        )
        assert res_bad.returncode == 1
        bad_msgs = [f["message"] for f in json.loads(res_bad.stdout)["findings"] if f["check"] == "bibtex/online-mismatch"]
        assert any("DOI title mismatch" in m for m in bad_msgs)
        assert any("DOI year mismatch" in m for m in bad_msgs)
    finally:
        server.shutdown()
        server.server_close()

    # Closed localhost port must report URLError cleanly as online-mismatch, never AttributeError
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        closed_port = sock.getsockname()[1]
    res_closed = _run(
        PREFLIGHT,
        ["bibtex", str(bib_ok), "--verify-online", "--json"],
        extra_env={"CROSSREF_API_BASE": f"http://127.0.0.1:{closed_port}"},
    )
    assert res_closed.returncode == 1
    assert "AttributeError" not in res_closed.stderr
    closed_findings = json.loads(res_closed.stdout)["findings"]
    assert any(f["check"] == "bibtex/online-mismatch" and "Online DOI check error" in f["message"] for f in closed_findings)


# ---------------------------------------------------------------------------
# 6. F22 Tool 4: check_figure_qa.py (palette & figure QA)
# ---------------------------------------------------------------------------


def test_check_figure_qa_palette_and_assets(tmp_path: Path) -> None:
    pal_list = _run(FIGURE_QA, ["palette", "--list-palettes", "--compact"])
    assert pal_list.returncode == 0
    assert "okabe_ito" in json.loads(pal_list.stdout)["palettes"]

    pal_ok = _run(
        FIGURE_QA,
        ["palette", "--color", "#000000", "--color", "#993300", "--color", "#228833", "--color", "#949494", "--fail-on", "any", "--compact"],
    )
    assert pal_ok.returncode == 0, pal_ok.stdout
    assert len(pal_ok.stdout.encode("utf-8")) < MAX_COMPACT_BYTES
    assert json.loads(pal_ok.stdout)["background_review_count"] == 0

    pal_bad = _run(FIGURE_QA, ["palette", "--color", "#EEEEEE", "--color", "#FFFFFF", "--fail-on", "background", "--json"])
    assert pal_bad.returncode == 1
    assert json.loads(pal_bad.stdout)["background_review_count"] == 2
    assert _run(FIGURE_QA, ["palette", "--color", "not_hex"]).returncode == 2

    fig_dir = tmp_path / "figs"
    fig_dir.mkdir()
    _make_png(fig_dir / "good.png", 1200, 800, 300)
    (fig_dir / "good_plot.py").write_text(
        "import matplotlib.pyplot as plt\nplt.rcParams['pdf.fonttype'] = 42\nplt.savefig('good.pdf')\n",
        encoding="utf-8",
    )
    fg_ok = _run(FIGURE_QA, ["figure", str(fig_dir), "--strict", "--compact"])
    assert fg_ok.returncode == 0, fg_ok.stdout
    assert len(fg_ok.stdout.encode("utf-8")) < MAX_COMPACT_BYTES

    bad_dir = tmp_path / "bad_figs"
    bad_dir.mkdir()
    (bad_dir / "chart.jpg").write_bytes(b"\xff\xd8\xff\xe0dummy")
    (bad_dir / "bad_type3.pdf").write_bytes(b"%PDF-1.4\n/Subtype /Type3\n/MediaBox [0 0 100 100]\n%%EOF\n")
    (bad_dir / "bad_plot.py").write_text("plt.imshow(x, cmap='jet')\nplt.savefig('out.jpg')\n", encoding="utf-8")
    fg_bad = _run(FIGURE_QA, ["figure", str(bad_dir), "--json"])
    assert fg_bad.returncode == 1
    bad_checks = {f["check"] for f in json.loads(fg_bad.stdout)["findings"]}
    assert {"figure/jpeg-prohibited", "figure/type3-font", "figure/rainbow-colormap", "figure/jpeg-export"}.issubset(bad_checks)
    assert _run(FIGURE_QA, ["figure", ""]).returncode == 2


def test_all_new_m7_scripts_help_clean() -> None:
    for script, subcmds in (
        (SYNC_SKILLS, ()),
        (EXP_RIGOR, ("repro", "rliable", "contamination")),
        (REBUTTAL, ("budget", "coverage")),
        (PREFLIGHT, ("anonymize", "arxiv-clean", "bibtex")),
        (FIGURE_QA, ("palette", "figure")),
    ):
        top = _run(script, ["--help"])
        assert top.returncode == 0, f"{script.name} --help failed: {top.stderr}"
        for sub in subcmds:
            sub_res = _run(script, [sub, "--help"])
            assert sub_res.returncode == 0, f"{script.name} {sub} --help failed: {sub_res.stderr}"
