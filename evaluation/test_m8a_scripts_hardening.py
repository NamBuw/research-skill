"""Comprehensive unmocked unit tests for Milestone M8A: radar.py + 5 hardened M7 scripts."""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import sqlite3
import struct
import subprocess
import sys
import threading
import time
import warnings
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "research-scientist" / "scripts"
RADAR_PY = REPO_ROOT / "research-scientist" / "modules" / "researchradar" / "problem-statement-finder" / "scripts" / "radar.py"

SYNC_SKILLS = SCRIPTS_DIR / "sync_skills.py"
EXP_RIGOR = SCRIPTS_DIR / "check_experiment_rigor.py"
REBUTTAL = SCRIPTS_DIR / "check_rebuttal.py"
PREFLIGHT = SCRIPTS_DIR / "check_submission_preflight.py"
FIGURE_QA = SCRIPTS_DIR / "check_figure_qa.py"

ALL_SKILLS = (
    "research-scientist",
    "research-precedent-corpus",
    "research-gap-rq-audit",
    "research-experiment-coding",
    "research-novelty-venue",
    "research-paper-writing",
    "research-user-report",
)
MAX_COMPACT_BYTES = 3800


def _load_mod(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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


def _chunk(ctype: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(ctype + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", crc)


def _make_png(path: Path, width: int, height: int, dpi_x: int, dpi_y: int | None = None) -> None:
    if dpi_y is None:
        dpi_y = dpi_x
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ppmx = int(round(dpi_x / 0.0254))
    ppmy = int(round(dpi_y / 0.0254))
    phys = struct.pack(">IIB", ppmx, ppmy, 1)
    idat = zlib.compress(b"\x00" + b"\x00\x00\x00" * width)
    raw = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"pHYs", phys) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")
    path.write_bytes(raw)


# ---------------------------------------------------------------------------
# Target 1: radar.py open_snor ResourceWarning guard & humanizer_lint perf
# ---------------------------------------------------------------------------


def test_radar_open_snor_closes_connection_on_executescript_error(tmp_path: Path) -> None:
    radar = _load_mod("radar_m8a", RADAR_PY)
    bad_db = tmp_path / "corrupt.sqlite"
    bad_db.write_bytes(b"this is definitely not a sqlite database header!!")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("error", ResourceWarning)
        with pytest.raises(sqlite3.DatabaseError):
            radar.open_snor(bad_db)
        import gc
        gc.collect()
    assert not [w for w in caught if issubclass(w.category, ResourceWarning)]


def test_humanizer_lint_unclosed_section_redos_stays_fast() -> None:
    hl = _load_mod("hl_m8a", SCRIPTS_DIR / "humanizer_lint.py")
    payload = "\\section[" * 5000 + "\nWe evaluate BM25 on BEIR.\n"
    hl.mask_prose(payload, ".tex")
    t0 = time.perf_counter()
    hl.mask_prose(payload, ".tex")
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.02


# ---------------------------------------------------------------------------
# Script A: sync_skills.py
# ---------------------------------------------------------------------------


def _make_mini_suite(suite_dir: Path) -> None:
    for name in ALL_SKILLS:
        sdir = suite_dir / name
        (sdir / "agents").mkdir(parents=True, exist_ok=True)
        (sdir / "SKILL.md").write_text(f"---\nname: {name}\ndescription: test\n---\n# {name}\n", encoding="utf-8")
        (sdir / "agents" / "openai.yaml").write_text("interface:\n  display_name: x\n  short_description: x\n  default_prompt: x\n", encoding="utf-8")
    scripts_dir = suite_dir / "research-scientist" / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / "claim_audit.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")


def test_sync_skills_overlap_self_destruct_and_symlinks(tmp_path: Path) -> None:
    suite = tmp_path / "suite"
    _make_mini_suite(suite)
    marker = suite / "research-scientist" / "SKILL.md"
    orig = marker.read_text(encoding="utf-8")

    # 1. tdir == suite_root
    r1 = _run(SYNC_SKILLS, ["--suite-root", str(suite), "--target-dir", str(suite)])
    assert r1.returncode == 2
    assert marker.read_text(encoding="utf-8") == orig

    # 2. tdir inside suite_root
    r2 = _run(SYNC_SKILLS, ["--suite-root", str(suite), "--target-dir", str(suite / "research-scientist")])
    assert r2.returncode == 2
    assert marker.read_text(encoding="utf-8") == orig

    # 3. suite_root inside tdir
    r3 = _run(SYNC_SKILLS, ["--suite-root", str(suite), "--target-dir", str(tmp_path)])
    assert r3.returncode == 2
    assert marker.read_text(encoding="utf-8") == orig

    # 4. Symlink alias to suite_root
    link_target = tmp_path / "suite_link"
    link_target.symlink_to(suite)
    r4 = _run(SYNC_SKILLS, ["--suite-root", str(suite), "--target-dir", str(link_target)])
    assert r4.returncode == 2
    assert marker.read_text(encoding="utf-8") == orig

    # 5. Pre-existing dest symlinked to source skill
    t_sym = tmp_path / "t_sym"
    t_sym.mkdir()
    (t_sym / "research-scientist").symlink_to(suite / "research-scientist")
    r5 = _run(SYNC_SKILLS, ["--suite-root", str(suite), "--target-dir", str(t_sym)])
    assert r5.returncode == 2
    assert marker.read_text(encoding="utf-8") == orig

    # 6. Hardlink inode overlap
    t_hard = tmp_path / "t_hard"
    (t_hard / "research-scientist").mkdir(parents=True)
    os.link(marker, t_hard / "research-scientist" / "SKILL.md")
    r6 = _run(SYNC_SKILLS, ["--suite-root", str(suite), "--target-dir", str(t_hard)])
    assert r6.returncode == 2
    assert marker.read_text(encoding="utf-8") == orig

    # 7. Multi-target [valid_new_dir, suite_root] must fail BEFORE creating valid_new_dir
    valid_new = tmp_path / "never_created"
    r7 = _run(SYNC_SKILLS, ["--suite-root", str(suite), "--target-dir", str(valid_new), "--target-dir", str(suite)])
    assert r7.returncode == 2
    assert not valid_new.exists()

    # 8. Escaping symlink inside source skill rejected before touching target
    good_target = tmp_path / "good_target"
    assert _run(SYNC_SKILLS, ["--suite-root", str(suite), "--target-dir", str(good_target)]).returncode == 0
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    (suite / "research-scientist" / "leak.txt").symlink_to(outside)
    r8 = _run(SYNC_SKILLS, ["--suite-root", str(suite), "--target-dir", str(good_target)])
    assert r8.returncode == 2
    assert not (good_target / "research-scientist" / "leak.txt").exists()


def test_sync_skills_check_mode_out_dedup_and_errors(tmp_path: Path) -> None:
    suite = tmp_path / "suite"
    _make_mini_suite(suite)
    target = tmp_path / "installed"
    missing_target = tmp_path / "not_created_by_check"

    # --check on non-existent target exits 1 without creating directory
    c_miss = _run(SYNC_SKILLS, ["--suite-root", str(suite), "--target-dir", str(missing_target), "--check", "--compact"])
    assert c_miss.returncode == 1
    assert not missing_target.exists()
    assert json.loads(c_miss.stdout)["status"] == "out_of_sync"

    # Sync with duplicate target paths + --out receipt + --compact
    out_file = tmp_path / "sync_receipt.json"
    s_res = _run(
        SYNC_SKILLS,
        ["--suite-root", str(suite), "--target-dir", str(target), "--target-dir", str(target / "."), "--out", str(out_file), "--compact"],
    )
    assert s_res.returncode == 0
    cmp_data = json.loads(s_res.stdout)
    assert len(cmp_data["targets"]) == 1
    assert cmp_data["out"] == str(out_file)
    assert out_file.is_file()
    assert json.loads(out_file.read_text(encoding="utf-8"))["status"] == "synced"

    # Add __pycache__/*.pyc -> --check STILL exits 0
    cache_dir = target / "research-scientist" / "scripts" / "__pycache__"
    cache_dir.mkdir(parents=True)
    (cache_dir / "claim_audit.cpython-313.pyc").write_bytes(b"\x00\x01")
    c_ok = _run(SYNC_SKILLS, ["--suite-root", str(suite), "--target-dir", str(target), "--check", "--compact"])
    assert c_ok.returncode == 0
    assert json.loads(c_ok.stdout)["status"] == "in_sync"

    # Modify file -> --check exits 1 with modified_file
    (target / "research-scientist" / "SKILL.md").write_text("tampered\n", encoding="utf-8")
    c_mod = _run(SYNC_SKILLS, ["--suite-root", str(suite), "--target-dir", str(target), "--check", "--json"])
    assert c_mod.returncode == 1
    diffs = json.loads(c_mod.stdout)["targets"][0]["diffs"]
    assert any(d["kind"] == "modified_file" for d in diffs)

    # Extra stale file and missing file
    (target / "research-scientist" / "SKILL.md").write_text((suite / "research-scientist" / "SKILL.md").read_text(encoding="utf-8"), encoding="utf-8")
    (target / "research-scientist" / "stale.md").write_text("stale", encoding="utf-8")
    (target / "research-user-report" / "SKILL.md").unlink()
    c_drift = _run(SYNC_SKILLS, ["--suite-root", str(suite), "--target-dir", str(target), "--check", "--json"])
    assert c_drift.returncode == 1
    kinds = {d["kind"] for d in json.loads(c_drift.stdout)["targets"][0]["diffs"]}
    assert {"extra_file", "missing_file"}.issubset(kinds)

    # Empty --out / --json and directory write error -> exit 2
    assert _run(SYNC_SKILLS, ["--suite-root", str(suite), "--target-dir", str(target), "--out", ""]).returncode == 2
    assert _run(SYNC_SKILLS, ["--suite-root", str(suite), "--target-dir", str(target), "--json", ""]).returncode == 2
    dir_as_json = tmp_path / "dir_as_json"
    dir_as_json.mkdir()
    err_write = _run(SYNC_SKILLS, ["--suite-root", str(suite), "--target-dir", str(target), "--dry-run", "--json", str(dir_as_json)])
    assert err_write.returncode == 2
    assert "Traceback" not in err_write.stderr


# ---------------------------------------------------------------------------
# Script C: check_rebuttal.py
# ---------------------------------------------------------------------------


def test_check_rebuttal_per_point_quotes_receipts_and_pdf_hardening(tmp_path: Path) -> None:
    pts = tmp_path / "points.md"
    pts.write_text("- R1.1: Baseline\n- R1.2: Ablation\n- R1.3: Runtime\n", encoding="utf-8")

    # 1. Section-level masking must fail: R1.1 anchored, R1.2 unverified claim, R1.3 unanchored
    reb_mask = tmp_path / "reb_mask.md"
    reb_mask.write_text(
        "## Response to R1\n"
        "- **R1.1**: See Table 1.\n"
        "- **R1.2**: We ran new experiments and confirmed large gains.\n"
        "- **R1.3**: Our runtime is fast.\n",
        encoding="utf-8",
    )
    res_mask = _run(REBUTTAL, ["coverage", str(pts), str(reb_mask), "--strict", "--json"])
    assert res_mask.returncode == 1
    data_mask = json.loads(res_mask.stdout)
    assert any("R1.2" in s for s in data_mask["unanchored_sections"])
    assert any("R1.2" in s for s in data_mask["unverified_experiment_claims"])
    assert any("R1.3" in s for s in data_mask["unanchored_sections"])

    # 2. Same-point multi-sentence masking must fail
    pts1 = tmp_path / "pts1.md"
    pts1.write_text("- R1.1: Clarification and ablation\n", encoding="utf-8")
    reb_sent = tmp_path / "reb_sent.md"
    reb_sent.write_text(
        "## R1\n- **R1.1**: We clarified notation in Sec. 2. We ran new experiments and got gains.\n",
        encoding="utf-8",
    )
    res_sent = _run(REBUTTAL, ["coverage", str(pts1), str(reb_sent), "--strict", "--json"])
    assert res_sent.returncode == 1
    assert json.loads(res_sent.stdout)["unverified_experiment_claims"]

    # 3. Receipt-anchored experiment claim passes
    reb_rcpt = tmp_path / "reb_rcpt.md"
    reb_rcpt.write_text(
        "## R1\n- **R1.1**: We ran new experiments (run_id=abl_03, results/abl.json: 84.2% vs 79.0%).\n",
        encoding="utf-8",
    )
    res_rcpt = _run(REBUTTAL, ["coverage", str(pts1), str(reb_rcpt), "--strict", "--json"])
    assert res_rcpt.returncode == 0, res_rcpt.stdout
    assert json.loads(res_rcpt.stdout)["verdict"] == "PASS"

    # 4. Expanded point IDs ([R1-1], MR.1, Q1:, W1:) + W1 distance prose non-interference
    pts_exp = tmp_path / "pts_exp.md"
    pts_exp.write_text("- [R1-1]: Clarity\n- MR.1: Scope\n- Q1: Hyperparams\n- W1: Speed\n", encoding="utf-8")
    reb_exp = tmp_path / "reb_exp.md"
    reb_exp.write_text(
        "## Responses\n"
        "- **[R1-1]**: See Sec. 3.\n"
        "- **MR.1**: See Appendix B.\n"
        "- **Q1**: See Table 2.\n"
        "- **W1**: See Fig. 1; note W1 distance is not an ID.\n",
        encoding="utf-8",
    )
    res_exp = _run(REBUTTAL, ["coverage", str(pts_exp), str(reb_exp), "--strict", "--json"])
    assert res_exp.returncode == 0, res_exp.stdout
    assert json.loads(res_exp.stdout)["orphan_ids"] == []

    # 5. Reviewer quote isolation + array index x[0] not an anchor + negation guard
    reb_quote = tmp_path / "reb_quote.md"
    reb_quote.write_text(
        "## R1\n"
        "> **R1.1**: See Table 1 in the paper?\n"
        "We set x[0] = 1 and did not run new experiments.\n",
        encoding="utf-8",
    )
    res_quote = _run(REBUTTAL, ["coverage", str(pts1), str(reb_quote), "--strict", "--json"])
    assert res_quote.returncode == 1
    q_data = json.loads(res_quote.stdout)
    assert q_data["unanchored_sections"]
    assert not q_data["unverified_experiment_claims"]

    reb_rev_claim = tmp_path / "reb_rev_claim.md"
    reb_rev_claim.write_text(
        "## R1\n"
        "> Reviewer comment: \"We ran new experiments in Table 1?\"\n"
        "For R1.1, we did not run new experiments; we clarified Appendix A.\n",
        encoding="utf-8",
    )
    res_rev_claim = _run(REBUTTAL, ["coverage", str(pts1), str(reb_rev_claim), "--strict", "--json"])
    assert res_rev_claim.returncode == 0, res_rev_claim.stdout

    # 6. ReDoS, corrupt PDF, binary budget, and CLI --out/--json/--compact
    reb_mod = _load_mod("check_rebuttal_m8a", REBUTTAL)
    t0 = time.perf_counter()
    with pytest.raises(ValueError):
        reb_mod.count_pdf_pages(b"/Count 1 " * 20000)
    assert time.perf_counter() - t0 < 0.5

    corrupt_pdf = tmp_path / "corrupt.pdf"
    corrupt_pdf.write_bytes(b"%PDF-1.4\n/Type /Page\ngarbage\n")
    assert _run(REBUTTAL, ["budget", str(corrupt_pdf)]).returncode == 2

    png_file = tmp_path / "img.png"
    _make_png(png_file, 800, 600, 300)
    assert _run(REBUTTAL, ["budget", str(png_file)]).returncode == 2

    json_out = tmp_path / "cov_out.json"
    c_both = _run(REBUTTAL, ["coverage", str(pts1), str(reb_rcpt), "--compact", "--json", str(json_out)])
    assert c_both.returncode == 0
    assert json_out.is_file()
    assert len(c_both.stdout.encode("utf-8")) < MAX_COMPACT_BYTES
    assert _run(REBUTTAL, ["budget", str(reb_rcpt), "--out", ""]).returncode == 2
    assert _run(REBUTTAL, ["budget", str(reb_rcpt), "--json", ""]).returncode == 2


# ---------------------------------------------------------------------------
# Script E: check_submission_preflight.py
# ---------------------------------------------------------------------------


def test_check_submission_preflight_caps_bibtex_and_online_fallback(tmp_path: Path) -> None:
    sp = _load_mod("preflight_m8a", PREFLIGHT)

    # 1. protect_title_caps outer-brace & compound tokens
    assert sp.protect_title_caps("{BERT} pretraining for 3d {CT}") == "{BERT} pretraining for {3d} {CT}"
    assert sp.protect_title_caps("{BERT}/3d") == "{BERT}/{3d}"
    assert sp.protect_title_caps("{Full Title Protected}") == "{Full Title Protected}"
    assert sp.protect_title_caps("arXiv Preprint") == "{arXiv} Preprint"
    with pytest.raises(ValueError):
        sp.protect_title_caps(True)  # type: ignore[arg-type]

    # 2. parse_bibtex backslash escapes, @comment, @string, case-insensitive dupes, malformed
    bib_text = (
        '@string{neurips = "NeurIPS"}\n'
        '@comment{ignored note, @article{ghost, title={Phantom}}}\n'
        '@inproceedings{Vaswani2017,\n'
        '  title = "On \\{BERT\\} \\"Quotes\\" foo\\\\",\n'
        '  author = {M{\\"u}ller, Hans},\n'
        '  booktitle = neurips,\n'
        '  abstract = {$\\{x$},\n'
        '  year = {2025}\n'
        '}\n'
        '@article{vaswani2017,\n'
        '  title = {Duplicate},\n'
        '  author = {true},\n'
        '  journal = {JMLR},\n'
        '  year = {2025}\n'
        '}\n'
    )
    entries = sp.parse_bibtex(bib_text)
    assert len(entries) == 2
    assert entries[0]["fields"]["booktitle"] == "NeurIPS"
    assert "ghost" not in {e["key"] for e in entries}

    bib_file = tmp_path / "hard.bib"
    bib_file.write_text(bib_text + "\n@article{unclosed,\n  title = {Broken\n", encoding="utf-8")
    b_res = _run(PREFLIGHT, ["bibtex", str(bib_file), "--json"])
    assert b_res.returncode == 1
    b_checks = {f["check"] for f in json.loads(b_res.stdout)["findings"]}
    assert {"bibtex/duplicate-key", "bibtex/placeholder-field", "bibtex/malformed-entry"}.issubset(b_checks)

    # 3. --verify-online fallback: Crossref 404 -> arXiv Atom -> OpenAlex
    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            if self.path.startswith("/api/query"):
                xml = (
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<feed xmlns="http://www.w3.org/2005/Atom">'
                    '<entry><title>Sparse Attention Pretraining</title><published>2024-03-01T00:00:00Z</published></entry>'
                    '</feed>'
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/atom+xml")
                self.send_header("Content-Length", str(len(xml)))
                self.end_headers()
                self.wfile.write(xml)
                return
            if self.path.startswith("/works/https://doi.org/10.5555/not-in-crossref"):
                payload = json.dumps({"title": "OpenAlex Verified Paper", "publication_year": 2023}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if self.path.startswith("/works?search="):
                payload = json.dumps({"results": [{"title": "OpenAlex Title Search Paper", "publication_year": 2022}]}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            self.send_response(404)
            self.end_headers()

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        bib_on = tmp_path / "online.bib"
        bib_on.write_text(
            "@article{ax2024,\n"
            "  title = {Sparse Attention Pretraining},\n"
            "  author = {Doe, Alex},\n"
            "  journal = {arXiv preprint},\n"
            "  eprint = {2403.01234},\n"
            "  year = {2024}\n"
            "}\n"
            "@inproceedings{oa2023,\n"
            "  title = {OpenAlex Verified Paper},\n"
            "  author = {Lee, Bo},\n"
            "  booktitle = {ICLR},\n"
            "  doi = {10.5555/not-in-crossref},\n"
            "  year = {2023}\n"
            "}\n"
            "@inproceedings{oa_nodoi,\n"
            "  title = {OpenAlex Title Search Paper},\n"
            "  author = {Kim, Min},\n"
            "  booktitle = {ICML},\n"
            "  year = {2022}\n"
            "}\n",
            encoding="utf-8",
        )
        base = f"http://127.0.0.1:{port}"
        res_on = _run(
            PREFLIGHT,
            ["bibtex", str(bib_on), "--verify-online", "--json"],
            extra_env={"CROSSREF_API_BASE": base, "ARXIV_API_BASE": base, "OPENALEX_API_BASE": base},
        )
        assert res_on.returncode == 0, res_on.stdout + res_on.stderr
        assert not [f for f in json.loads(res_on.stdout)["findings"] if f["check"] == "bibtex/online-mismatch"]
    finally:
        srv.shutdown()
        srv.server_close()


def test_check_submission_preflight_arxiv_anonymize_and_uncovered_bugs(tmp_path: Path) -> None:
    sp = _load_mod("preflight_m8a_b", PREFLIGHT)

    # 1. ReDoS fixes (< 0.05s on 20000 spaces)
    for rx, prefix in (
        (sp._ML_STY_RE, "\\usepackage"),
        (sp._DOCCLASS_RE, "\\documentclass"),
        (sp._GRAPHIC_RE, "\\includegraphics"),
    ):
        t0 = time.perf_counter()
        rx.search(prefix + " " * 20000 + "!")
        assert time.perf_counter() - t0 < 0.05

    # 2. arxiv-clean: \verb/verbatim preservation, symlink block, \graphicspath, --prune-unused, NaN, overlap
    tex_dir = tmp_path / "tex_dir"
    (tex_dir / "figs").mkdir(parents=True)
    (tex_dir / "drafts").mkdir()
    (tex_dir / "secs").mkdir()
    _make_png(tex_dir / "figs" / "fig.png", 800, 600, 300)
    _make_png(tex_dir / "drafts" / "fig.png", 800, 600, 300)
    (tex_dir / "secs" / "v1.2_ablation.tex").write_text("Ablation text.\n", encoding="utf-8")
    (tex_dir / "unused_draft.tex").write_text("Unused draft.\n", encoding="utf-8")
    outside = tmp_path / "outside.tex"
    outside.write_text("secret outside\n", encoding="utf-8")
    (tex_dir / "leak.tex").symlink_to(outside)

    (tex_dir / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\graphicspath{{figs/}}\n"
        "\\begin{document}\n"
        "Text \\verb|100% pure| ok % drop secret\n"
        "\\begin{verbatim}\n"
        "% keep inside verbatim\n"
        "10 % 3\n"
        "\\end{verbatim}\n"
        "\\input{secs/v1.2_ablation}\n"
        "\\includegraphics{fig}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )

    assert _run(PREFLIGHT, ["arxiv-clean", str(tex_dir), "--prune-unused"]).returncode == 2
    assert _run(PREFLIGHT, ["arxiv-clean", str(tex_dir), "--max-image-mb", "nan"]).returncode == 2
    assert _run(PREFLIGHT, ["arxiv-clean", str(tex_dir), "--strip-comments-out", str(tex_dir / "sub")]).returncode == 2

    strip_out = tmp_path / "stripped"
    # Upfront --out "" must fail BEFORE creating strip_out
    assert _run(PREFLIGHT, ["arxiv-clean", str(tex_dir), "--strip-comments-out", str(strip_out), "--out", ""]).returncode == 2
    assert not strip_out.exists()

    ax_res = _run(PREFLIGHT, ["arxiv-clean", str(tex_dir), "--strip-comments-out", str(strip_out), "--prune-unused", "--json"])
    assert ax_res.returncode == 1
    ax_data = json.loads(ax_res.stdout)
    checks = {(f["check"], f["file"]) for f in ax_data["findings"]}
    assert ("arxiv/unsafe-symlink", "leak.tex") in checks
    assert ("arxiv/unused-figure", "drafts/fig.png") in checks
    assert ("arxiv/unused-tex", "unused_draft.tex") in checks
    assert not (strip_out / "leak.tex").exists()
    assert not (strip_out / "drafts" / "fig.png").exists()
    assert not (strip_out / "unused_draft.tex").exists()
    assert (strip_out / "figs" / "fig.png").is_file()
    cleaned = (strip_out / "main.tex").read_text(encoding="utf-8")
    assert "\\verb|100% pure|" in cleaned
    assert "% keep inside verbatim" in cleaned
    assert "10 % 3" in cleaned
    assert "drop secret" not in cleaned

    # 3. anonymize: URL host parsing, finditer comments, [preprint]/\iclrfinalcopy, \input traversal, UTF-16BE PDF /Author
    an_dir = tmp_path / "anon_dir"
    an_dir.mkdir()
    outside_inc = tmp_path / "outside_inc.tex"
    outside_inc.write_text("should not be read\n", encoding="utf-8")
    (an_dir / "paper.tex").write_text(
        "\\documentclass{article}\n"
        "\\usepackage[preprint]{neurips_2025}\n"
        "\\iclrfinalcopy\n"
        "\\begin{document}\n"
        "Matrix host https://matrix.com/paper and spoof https://anonymous.4open.science.evil.com/r/1.\n"
        "\\input{../outside_inc.tex}\n"
        "% anon@example.com real@university.edu\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    pdf_utf16 = tmp_path / "meta.pdf"
    author_hex = (b"\xfe\xff" + "Jane Doe".encode("utf-16-be")).hex().upper().encode("ascii")
    pdf_utf16.write_bytes(b"%PDF-1.4\n1 0 obj\n<< /Author <" + author_hex + b"> >>\nendobj\n%%EOF\n")

    an_res = _run(PREFLIGHT, ["anonymize", str(an_dir / "paper.tex"), "--pdf", str(pdf_utf16), "--json"])
    assert an_res.returncode == 1
    an_findings = json.loads(an_res.stdout)["findings"]
    assert not any("matrix.com" in f["message"] for f in an_findings)
    assert not any(f["check"] == "anonymization/link-ok" for f in an_findings)
    assert any(f["check"] == "anonymization/class-option" and "preprint" in f["message"] for f in an_findings)
    assert any(f["check"] == "anonymization/class-option" and "iclrfinalcopy" in f["message"] for f in an_findings)
    assert any(f["check"] == "anonymization/unsafe-input" for f in an_findings)
    assert any(f["check"] == "anonymization/comment-leak" and "real@university.edu" in f["message"] for f in an_findings)
    assert any(f["check"] == "anonymization/pdf-author" and "Jane Doe" in f["message"] for f in an_findings)


# ---------------------------------------------------------------------------
# Script D: check_experiment_rigor.py
# ---------------------------------------------------------------------------


def test_check_experiment_rigor_hardening(tmp_path: Path) -> None:
    # 1. Comment/docstring stripping & .ipynb code-only parsing
    fake_repo = tmp_path / "fake_repo"
    (fake_repo / "data").mkdir(parents=True)
    (fake_repo / "README.md").write_text("Download dataset from Zenodo.\n```bash\npython train.py\n```\n", encoding="utf-8")
    (fake_repo / "requirements.txt").write_text("# torch==2.5.1\ntorch\n", encoding="utf-8")
    (fake_repo / "helper.py").write_text(
        '"""set_seed(0)"""\n# torch.manual_seed(42)\n# if __name__ == "__main__":\nx = 1\n',
        encoding="utf-8",
    )
    (fake_repo / "launch.sh").write_text("# PYTHONHASHSEED=0\necho hi\n", encoding="utf-8")
    (fake_repo / "nb.ipynb").write_text(
        json.dumps({
            "cells": [
                {"cell_type": "markdown", "source": ["torch.manual_seed(42)"]},
                {"cell_type": "code", "source": ["%matplotlib inline\n", "print(1)\n"], "outputs": [{"text": ["set_seed(0)"]}]},
            ]
        }),
        encoding="utf-8",
    )
    r_fake = _run(EXP_RIGOR, ["repro", str(fake_repo), "--json"])
    assert r_fake.returncode == 1
    d_fake = json.loads(r_fake.stdout)
    assert "SEED" in d_fake["missing"]
    assert d_fake["deps_pinned"] is False
    assert any(e["name"] == "ENTRYPOINT" and e["status"] == "MISSING" for e in d_fake["essentials"])

    # 2. Ancestor build/ dir works, .venv & escaping symlinks skipped, top-level README preferred
    build_parent = tmp_path / "build" / "real_proj"
    (build_parent / "subpkg").mkdir(parents=True)
    (build_parent / ".venv").mkdir()
    (build_parent / "data").mkdir()
    (build_parent / "tests").mkdir()
    (build_parent / "tests" / "test_ok.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    (build_parent / "subpkg" / "readme.md").write_text("Empty subreadme", encoding="utf-8")
    (build_parent / "README.md").write_text("Download dataset.\n```bash\npython train.py\n```\n", encoding="utf-8")
    (build_parent / "requirements.txt").write_text("torch==2.5.1\n", encoding="utf-8")
    (build_parent / "train.py").write_text('import os\nos.environ["PYTHONHASHSEED"] = "42"\nif __name__ == "__main__":\n    pass\n', encoding="utf-8")
    (build_parent / ".venv" / "bad.py").write_text("torch.manual_seed(0)\n", encoding="utf-8")
    outside_py = tmp_path / "outside.py"
    outside_py.write_text("torch.manual_seed(0)\n", encoding="utf-8")
    (build_parent / "escape.py").symlink_to(outside_py)

    r_build = _run(EXP_RIGOR, ["repro", str(build_parent), "--strict", "--json"])
    assert r_build.returncode == 0, r_build.stdout + r_build.stderr
    assert json.loads(r_build.stdout)["scanned_files"] == 2  # train.py + tests/test_ok.py

    # 3. RESULTS_CMD_RE & _has_results_cmd ReDoS
    rigor_mod = _load_mod("rigor_m8a", EXP_RIGOR)
    t0 = time.perf_counter()
    assert not rigor_mod._has_results_cmd("```" + "python " * 10000)
    assert not rigor_mod.RESULTS_CMD_RE.search("```" + "python " * 10000)
    assert time.perf_counter() - t0 < 0.05
    assert rigor_mod._has_results_cmd("```bash\npython train.py\n```")

    # 4. rliable bool/null/mixed/task-mismatch/baseline validation
    for bad_obj in (
        {"methods": {"M": [True, False, True]}},
        {"methods": {"M": [None, 0.5]}},
        {"methods": {"M": [0.5, [0.6]]}},
        {"baseline": "B", "methods": {"B": [[0.1, 0.2, 0.3], [0.2, 0.3, 0.4]], "M": [[0.9], [0.8]]}},
        {"baseline": ["bad"], "methods": {"M": [0.5, 0.6]}},
    ):
        bf = tmp_path / "bad_scores.json"
        bf.write_text(json.dumps(bad_obj), encoding="utf-8")
        res_b = _run(EXP_RIGOR, ["rliable", str(bf)])
        assert res_b.returncode == 2
        assert "Traceback" not in res_b.stderr

    ok_scores = tmp_path / "ok_scores.json"
    ok_scores.write_text(json.dumps({"methods": {"M": [0.5, 0.5, 0.5]}}), encoding="utf-8")
    assert _run(EXP_RIGOR, ["rliable", str(ok_scores), "--baseline", ""]).returncode == 2

    # 5. contamination: SKIP_DIRS + binary skip + single binary reject + jsonl id masking fix + json dict container
    tr_dir = tmp_path / "train_dir"
    (tr_dir / ".git" / "objects").mkdir(parents=True)
    (tr_dir / ".git" / "objects" / "pack.idx").write_bytes(b"\xff\x00\xfe\x01binary")
    (tr_dir / "img.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00")
    (tr_dir / "data.jsonl").write_text(json.dumps({"id": "tr_1", "text": "short exact test sentence"}) + "\n", encoding="utf-8")
    ev_dir = tmp_path / "eval_dir"
    ev_dir.mkdir()
    (ev_dir / "eval.json").write_text(json.dumps({"data": [{"id": "ev_1", "text": "short exact test sentence"}]}), encoding="utf-8")

    c_hit = _run(EXP_RIGOR, ["contamination", "--train", str(tr_dir), "--eval", str(ev_dir), "--json"])
    assert c_hit.returncode == 1
    assert json.loads(c_hit.stdout)["exact_match_count"] == 1
    assert _run(EXP_RIGOR, ["contamination", "--train", str(tr_dir / "img.png"), "--eval", str(ev_dir)]).returncode == 2
    assert _run(EXP_RIGOR, ["repro", str(build_parent), "--out", ""]).returncode == 2
    assert _run(EXP_RIGOR, ["repro", str(build_parent), "--json", ""]).returncode == 2


# ---------------------------------------------------------------------------
# Script B: check_figure_qa.py
# ---------------------------------------------------------------------------


def test_check_figure_qa_hardening(tmp_path: Path) -> None:
    # 1. Corrupt PNG checks (huge length, missing IEND, bad CRC, width=0, partial trailing header, ppuy DPI)
    bad_len_png = tmp_path / "bad_len.png"
    bad_len_png.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I4s", 999999, b"IHDR") + b"\x00" * 17)
    r1 = _run(FIGURE_QA, ["figure", str(bad_len_png), "--json"])
    assert r1.returncode == 1
    assert json.loads(r1.stdout)["findings"][0]["check"] == "figure/corrupt-png"

    no_iend_png = tmp_path / "no_iend.png"
    ihdr = struct.pack(">IIBBBBB", 800, 600, 8, 2, 0, 0, 0)
    no_iend_png.write_bytes(b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(b"\x00" * 10)))
    assert json.loads(_run(FIGURE_QA, ["figure", str(no_iend_png), "--json"]).stdout)["findings"][0]["check"] == "figure/corrupt-png"

    bad_crc_png = tmp_path / "bad_crc.png"
    bad_crc_png.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I4s", 13, b"IHDR") + ihdr + b"\x00\x00\x00\x00" + _chunk(b"IEND", b""))
    assert json.loads(_run(FIGURE_QA, ["figure", str(bad_crc_png), "--json"]).stdout)["findings"][0]["check"] == "figure/corrupt-png"

    asym_dpi_png = tmp_path / "asym_dpi.png"
    _make_png(asym_dpi_png, 1200, 800, dpi_x=300, dpi_y=72)
    r_dpi = _run(FIGURE_QA, ["figure", str(asym_dpi_png), "--strict", "--json"])
    assert r_dpi.returncode == 1
    assert any(f["check"] == "figure/low-dpi" for f in json.loads(r_dpi.stdout)["findings"])

    # 2. Compressed FlateDecode PDF Type3 & ObjStm MediaBox
    comp_type3 = zlib.compress(b"/Type /Font /Subtype /Type3\n/MediaBox [0 0 100 100]\n")
    comp_pdf = tmp_path / "comp_type3.pdf"
    comp_pdf.write_bytes(b"%PDF-1.5\n1 0 obj\n<< /Type /ObjStm /Filter /FlateDecode >>\nstream\n" + comp_type3 + b"\nendstream\nendobj\n%%EOF\n")
    r_pdf = _run(FIGURE_QA, ["figure", str(comp_pdf), "--json"])
    assert r_pdf.returncode == 1
    pdf_checks = {f["check"] for f in json.loads(r_pdf.stdout)["findings"]}
    assert "figure/type3-font" in pdf_checks
    assert "figure/missing-bbox" not in pdf_checks

    # 3. Plot script comment/docstring stripping + AST checks
    clean_dir = tmp_path / "clean_scripts"
    (clean_dir / ".venv").mkdir(parents=True)
    (clean_dir / ".venv" / "bad_ignored.py").write_text("plt.imshow(x, cmap='jet')\n", encoding="utf-8")
    (clean_dir / "good_plot.py").write_text(
        '"""Never use cmap=\'jet\' or savefig(\'bad.jpg\') or set_ylim(5, 10)"""\n'
        "# avoid cmap='jet' and plt.savefig('bad.jpg')\n"
        "import matplotlib.pyplot as plt\n"
        "plt.rcParams['pdf.fonttype'] = 42\n"
        "plt.imshow([[1, 2]], cmap='viridis')\n"
        "plt.savefig('good.pdf')\n",
        encoding="utf-8",
    )
    r_clean = _run(FIGURE_QA, ["figure", str(clean_dir), "--strict", "--json"])
    assert r_clean.returncode == 0, r_clean.stdout
    assert json.loads(r_clean.stdout)["checked_count"] == 1

    tricky_bad = tmp_path / "tricky_bad.py"
    tricky_bad.write_text(
        "import os\n"
        "import matplotlib.pyplot as plt\n"
        "# plt.rcParams['pdf.fonttype'] = 42\n"
        "plt.rcParams['pdf.fonttype'] = 3\n"
        "plt.bar([1, 2], [3, 4])\n"
        "plt.set_ylim(0.5, 1.0)\n"
        "plt.savefig(os.path.join('out', 'fig.jpg'))\n"
        "plt.savefig('fig2', format='jpeg')\n"
        "plt.savefig('fig3.pdf')\n",
        encoding="utf-8",
    )
    r_tricky = _run(FIGURE_QA, ["figure", str(tricky_bad), "--strict", "--json"])
    assert r_tricky.returncode == 1
    tricky_checks = {f["check"] for f in json.loads(r_tricky.stdout)["findings"]}
    assert {
        "figure/jpeg-export",
        "figure/missing-truetype-rcparam",
        "figure/truncated-bar-axis",
    }.issubset(tricky_checks)

    # 4. Hex validation, SVG/EPS, and --out "" / --json ""
    for bad_hex in ("+12345", "-12345", "##123456"):
        assert _run(FIGURE_QA, ["palette", "--color", bad_hex]).returncode == 2
    assert _run(FIGURE_QA, ["figure", str(clean_dir), "--out", ""]).returncode == 2
    assert _run(FIGURE_QA, ["figure", str(clean_dir), "--json", ""]).returncode == 2

    bad_svg = tmp_path / "bad.svg"
    bad_svg.write_text('<svg><image href="data:image/jpeg;base64,/9j/4AAQ"/></svg>', encoding="utf-8")
    r_svg = _run(FIGURE_QA, ["figure", str(bad_svg), "--json"])
    assert r_svg.returncode == 1
    assert any(f["check"] == "figure/jpeg-prohibited" for f in json.loads(r_svg.stdout)["findings"])

    empty_eps = tmp_path / "empty.eps"
    empty_eps.write_text("", encoding="utf-8")
    assert _run(FIGURE_QA, ["figure", str(empty_eps)]).returncode == 1


# ---------------------------------------------------------------------------
# Iteration 2 Regression Tests (S1-S2, F1-F5, R1-R5, P1-P5, G1-G3)
# ---------------------------------------------------------------------------


def test_sync_skills_r2_internal_symlinks_cycles_emptydirs_and_premutation(tmp_path: Path) -> None:
    # S1: Internal relative symlinks across subdirs pass --check cleanly after sync
    suite = tmp_path / "suite_sym"
    _make_mini_suite(suite)
    rs = suite / "research-scientist"
    (rs / "references").mkdir()
    (rs / "references" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (rs / "references" / "to_script.py").symlink_to("../scripts/claim_audit.py")
    (rs / "ref_alias").symlink_to("references")

    t_s1 = tmp_path / "t_s1"
    assert _run(SYNC_SKILLS, ["--suite-root", str(suite), "--target-dir", str(t_s1)]).returncode == 0
    chk = _run(SYNC_SKILLS, ["--suite-root", str(suite), "--target-dir", str(t_s1), "--check", "--json"])
    assert chk.returncode == 0, chk.stdout
    assert json.loads(chk.stdout)["status"] == "in_sync"

    # Extra non-ignored empty dir in destination is flagged by --check
    extra_empty = t_s1 / "research-scientist" / "stale_empty_dir"
    extra_empty.mkdir()
    chk_empty = _run(SYNC_SKILLS, ["--suite-root", str(suite), "--target-dir", str(t_s1), "--check", "--json"])
    assert chk_empty.returncode == 1
    assert any(d["kind"] == "extra_dir" and "stale_empty_dir" in d["path"] for d in json.loads(chk_empty.stdout)["targets"][0]["diffs"])
    extra_empty.rmdir()

    # Destination symlink pointing into another skill in suite_root rejected upfront
    (t_s1 / "research-scientist" / "cross_link").symlink_to(suite / "research-paper-writing" / "SKILL.md")
    assert _run(SYNC_SKILLS, ["--suite-root", str(suite), "--target-dir", str(t_s1)]).returncode == 2
    (t_s1 / "research-scientist" / "cross_link").unlink()

    # S2: Unwritable / directory --out / --json fails BEFORE creating/mutating targets
    ro_out_dir = tmp_path / "ro_out_dir"
    ro_out_dir.mkdir()
    t_uncreated = tmp_path / "t_uncreated"
    existing_dir_out = tmp_path / "existing_dir_out"
    existing_dir_out.mkdir()
    assert _run(SYNC_SKILLS, ["--suite-root", str(suite), "--target-dir", str(t_uncreated), "--out", str(existing_dir_out)]).returncode == 2
    assert not t_uncreated.exists()

    if os.geteuid() != 0:
        ro_out_dir.chmod(0o555)
        try:
            r_ro = _run(SYNC_SKILLS, ["--suite-root", str(suite), "--target-dir", str(t_uncreated), "--out", str(ro_out_dir / "r.json")])
            assert r_ro.returncode == 2
            assert not t_uncreated.exists()

            r_roj = _run(SYNC_SKILLS, ["--suite-root", str(suite), "--target-dir", str(t_uncreated), "--json", str(ro_out_dir / "r2.json")])
            assert r_roj.returncode == 2
            assert not t_uncreated.exists()

            # Multi-target [good_dir, readonly_dir] must fail BEFORE mutating good_dir
            good_dir = tmp_path / "good_untouched"
            good_dir.mkdir()
            sentinel = good_dir / "sentinel.txt"
            sentinel.write_text("keep\n", encoding="utf-8")
            ro_target = tmp_path / "ro_target"
            ro_target.mkdir()
            ro_target.chmod(0o555)
            try:
                r_mt = _run(SYNC_SKILLS, ["--suite-root", str(suite), "--target-dir", str(good_dir), "--target-dir", str(ro_target)])
                assert r_mt.returncode == 2
                assert [p.name for p in good_dir.iterdir()] == ["sentinel.txt"]
            finally:
                ro_target.chmod(0o755)
        finally:
            ro_out_dir.chmod(0o755)

    # Cyclic internal symlink raises ValueError (exit 2), NOT RecursionError
    suite_cyc = tmp_path / "suite_cyc"
    _make_mini_suite(suite_cyc)
    (suite_cyc / "research-scientist" / "sub").mkdir()
    (suite_cyc / "research-scientist" / "sub" / "loop").symlink_to("..")
    r_cyc = _run(SYNC_SKILLS, ["--suite-root", str(suite_cyc), "--target-dir", str(tmp_path / "t_cyc")])
    assert r_cyc.returncode == 2
    assert "Traceback" not in r_cyc.stderr


def test_check_figure_qa_r2_regressions(tmp_path: Path) -> None:
    # F1: Trailing bytes after IEND -> ERROR: figure/corrupt-png
    trail_png = tmp_path / "trailing.png"
    _make_png(trail_png, 800, 600, 300)
    trail_png.write_bytes(trail_png.read_bytes() + b"TRAILING_GARBAGE")
    r_f1 = _run(FIGURE_QA, ["figure", str(trail_png), "--json"])
    assert r_f1.returncode == 1
    assert any(f["check"] == "figure/corrupt-png" for f in json.loads(r_f1.stdout)["findings"])

    # F2: /MediaBox inside content stream does NOT mask missing page bbox
    content_stream = zlib.compress(b"BT /F1 12 Tf (/MediaBox) Tj ET\n")
    no_bbox_pdf = tmp_path / "content_mediabox.pdf"
    no_bbox_pdf.write_bytes(b"%PDF-1.5\n1 0 obj\n<< /Filter /FlateDecode >>\nstream\n" + content_stream + b"\nendstream\nendobj\n%%EOF\n")
    r_f2 = _run(FIGURE_QA, ["figure", str(no_bbox_pdf), "--strict", "--json"])
    assert r_f2.returncode == 1
    assert any(f["check"] == "figure/missing-bbox" for f in json.loads(r_f2.stdout)["findings"])

    # F3: Non-docstring string constants and U+2028 line separator must NOT false-positive
    safe_strings_py = tmp_path / "safe_strings.py"
    safe_strings_py.write_text(
        'import matplotlib.pyplot as plt\n'
        'HELP = """\nNever pass cmap=\'jet\' or savefig("x.jpg")\n"""\n'
        'x = 1\n'
        '"cmap=\'jet\'"\n'
        "s = 'a\u2028b'\n"
        "# cmap='jet'\n"
        "plt.rcParams['pdf.fonttype'] = 42\n"
        "plt.plot([1, 2])\n"
        "plt.savefig('ok.pdf')\n",
        encoding="utf-8",
    )
    r_f3 = _run(FIGURE_QA, ["figure", str(safe_strings_py), "--strict", "--json"])
    assert r_f3.returncode == 0, r_f3.stdout

    # F4: ps.fonttype=42 bypass, plt.rc('pdf', fonttype=3), colormaps['JET'], set_ylim variants
    ps_only = tmp_path / "ps_only.py"
    ps_only.write_text("import matplotlib.pyplot as plt\nplt.rcParams['ps.fonttype'] = 42\nplt.savefig('a.pdf')\n", encoding="utf-8")
    r_ps = _run(FIGURE_QA, ["figure", str(ps_only), "--strict", "--json"])
    assert r_ps.returncode == 1
    assert any(f["check"] == "figure/missing-truetype-rcparam" for f in json.loads(r_ps.stdout)["findings"])

    rc_type3 = tmp_path / "rc_type3.py"
    rc_type3.write_text("import matplotlib.pyplot as plt\nplt.rc('pdf', fonttype=3)\nplt.savefig('a.pdf')\n", encoding="utf-8")
    r_rc3 = _run(FIGURE_QA, ["figure", str(rc_type3), "--strict", "--json"])
    assert r_rc3.returncode == 1
    assert any(f["check"] == "figure/missing-truetype-rcparam" for f in json.loads(r_rc3.stdout)["findings"])

    cmap_upper = tmp_path / "cmap_upper.py"
    cmap_upper.write_text("import matplotlib as mpl\nc = mpl.colormaps['JET']\n", encoding="utf-8")
    r_cm = _run(FIGURE_QA, ["figure", str(cmap_upper), "--json"])
    assert r_cm.returncode == 1
    assert any(f["check"] == "figure/rainbow-colormap" for f in json.loads(r_cm.stdout)["findings"])

    for idx, ylim_call in enumerate(["ax.set_ylim(top=1.0, bottom=0.5)", "ax.set_ylim((0.5, 1.0))"]):
        bar_py = tmp_path / f"bar_{idx}.py"
        bar_py.write_text(f"ax.bar([1, 2], [3, 4])\n{ylim_call}\n", encoding="utf-8")
        r_bar = _run(FIGURE_QA, ["figure", str(bar_py), "--strict", "--json"])
        assert r_bar.returncode == 1
        assert any(f["check"] == "figure/truncated-bar-axis" for f in json.loads(r_bar.stdout)["findings"])

    # F5: Commented <svg> does not satisfy root <svg> check
    comment_svg = tmp_path / "comment_only.svg"
    comment_svg.write_text("<!-- <svg> --><root/>", encoding="utf-8")
    r_f5 = _run(FIGURE_QA, ["figure", str(comment_svg), "--json"])
    assert r_f5.returncode == 1
    assert any(f["check"] == "figure/corrupt-svg" for f in json.loads(r_f5.stdout)["findings"])


def test_check_rebuttal_r2_regressions(tmp_path: Path) -> None:
    pts = tmp_path / "pts.md"
    pts.write_text("- R1.1: Interval\n- R1.2: Extra\n", encoding="utf-8")

    # R1: Unclosed/mismatched [0, 1) and :( do NOT swallow subsequent unanchored experiment claims
    for bad_txt in (
        "## R1\n- R1.1: For values in [0, 1) we show results in Table 1. We ran new experiments and improved by 5%.\n- R1.2: See Table 2.\n",
        "## R1\n- R1.1: Sorry :( for the typo in Table 1. We ran new experiments confirming +5%.\n- R1.2: See Table 2.\n",
    ):
        reb = tmp_path / "reb_r1.md"
        reb.write_text(bad_txt, encoding="utf-8")
        r1 = _run(REBUTTAL, ["coverage", str(pts), str(reb), "--strict", "--json"])
        assert r1.returncode == 1
        assert json.loads(r1.stdout)["unverified_experiment_claims"]

    # R2: Distinct single-newline lines split; wrapped '(see Table 1)' stays attached
    reb_r2_bad = tmp_path / "reb_r2_bad.md"
    reb_r2_bad.write_text(
        "## R1\n- R1.1: See Table 1\n  We ran new experiments confirming improvements\n- R1.2: See Table 2.\n",
        encoding="utf-8",
    )
    r2_bad = _run(REBUTTAL, ["coverage", str(pts), str(reb_r2_bad), "--strict", "--json"])
    assert r2_bad.returncode == 1
    assert any("R1.1" in s for s in json.loads(r2_bad.stdout)["unverified_experiment_claims"])

    reb_r2_ok = tmp_path / "reb_r2_ok.md"
    reb_r2_ok.write_text(
        "## R1\n- R1.1: We ran new experiments\n(see Table 1).\n- R1.2: Addressing R1.2: see Table A1 and Fig. S1.\n",
        encoding="utf-8",
    )
    r2_ok = _run(REBUTTAL, ["coverage", str(pts), str(reb_r2_ok), "--strict", "--json"])
    assert r2_ok.returncode == 0, r2_ok.stdout

    # R3: arr[i][0] and f()[0] must NOT match as citation anchors
    pts1 = tmp_path / "pts1.md"
    pts1.write_text("## Q1: Indexing\n", encoding="utf-8")
    reb_r3 = tmp_path / "reb_r3.md"
    reb_r3.write_text("## Responses\n- **Q1**: We initialize arr[i][0] = 1 and call f()[0] for +5%.\n", encoding="utf-8")
    r3 = _run(REBUTTAL, ["coverage", str(pts1), str(reb_r3), "--strict", "--json"])
    assert r3.returncode == 1
    assert json.loads(r3.stdout)["unanchored_sections"]

    # R4: Multi-line Reviewer comment: "..." does not leak Table 1
    reb_r4 = tmp_path / "reb_r4.md"
    reb_r4.write_text(
        'Q1:\nReviewer comment: "This paper lacks clarity.\nPlease check Table 1."\nWe clarify the notation.\n',
        encoding="utf-8",
    )
    r4 = _run(REBUTTAL, ["coverage", str(pts1), str(reb_r4), "--strict", "--json"])
    assert r4.returncode == 1
    assert json.loads(r4.stdout)["unanchored_sections"]

    # R5: Empty point stub is NOT credited in covered_points
    reb_r5 = tmp_path / "reb_r5.md"
    reb_r5.write_text("R1.1:\nR1.2: See Table 1.\n", encoding="utf-8")
    r5 = _run(REBUTTAL, ["coverage", str(pts), str(reb_r5), "--json"])
    assert r5.returncode == 1
    d5 = json.loads(r5.stdout)
    assert "R1.1" in d5["missing_points"]
    assert "R1.1" not in d5["covered_points"]


def test_check_submission_preflight_r2_regressions(tmp_path: Path) -> None:
    sp = _load_mod("preflight_m8a_r2", PREFLIGHT)

    # P1: _titles_match rejects different domain after 25-char prefix & fails closed on empty remote title
    assert not sp._titles_match("A Survey of Deep Learning for Vision", "A Survey of Deep Learning for Healthcare")
    assert not sp._titles_match("Any Title", "")

    class _BadTitleHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            if self.path.startswith("/api/query"):
                xml = (
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<feed xmlns="http://www.w3.org/2005/Atom">'
                    '<entry><published>2023-01-01T00:00:00Z</published></entry>'
                    '</feed>'
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/atom+xml")
                self.send_header("Content-Length", str(len(xml)))
                self.end_headers()
                self.wfile.write(xml)
                return
            if self.path.startswith("/works?search="):
                payload = json.dumps({"results": [{"title": "A Survey of Deep Learning for Healthcare", "publication_year": 2024}]}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            self.send_response(404)
            self.end_headers()

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _BadTitleHandler)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        bib_bad = tmp_path / "bad_online.bib"
        bib_bad.write_text(
            "@article{ax_empty,\n  title={Completely Invented Title},\n  author={Doe, J.},\n  journal={arXiv},\n  eprint={2301.00001},\n  year={2023}\n}\n"
            "@inproceedings{oa_mismatch,\n  title={A Survey of Deep Learning for Vision},\n  author={Lee, K.},\n  booktitle={CVPR},\n  year={2024}\n}\n",
            encoding="utf-8",
        )
        base = f"http://127.0.0.1:{port}"
        r_p1 = _run(PREFLIGHT, ["bibtex", str(bib_bad), "--verify-online", "--json"], extra_env={"ARXIV_API_BASE": base, "OPENALEX_API_BASE": base})
        assert r_p1.returncode == 1
        mismatches = [f for f in json.loads(r_p1.stdout)["findings"] if f["check"] == "bibtex/online-mismatch"]
        assert len(mismatches) == 2
    finally:
        srv.shutdown()
        srv.server_close()

    # P2: No double-bracing on {LLM}s, {BERT}'s, {3D}-CNN, or \t whitespace
    assert sp.protect_title_caps("Using (BERT) and {LLM}s in 2024") == "Using ({BERT}) and {LLM}s in 2024"
    assert "{{" not in sp.protect_title_caps("On {BERT}'s Attention and GPT-4's Reasoning")
    assert sp.protect_title_caps("{3D}-CNN") == "{3D}-{CNN}"
    assert sp.protect_title_caps("BERT\tNLP") == "{BERT}\t{NLP}"

    # P3 & P4: Unmatched braces in quoted fields, parens in @article(...), brace-only empty fields
    p3_bib = (
        '@article{bq1, title = "Unmatched } brace in quote", author = {A}, journal = {J}, year = {2024}}\n'
        '@article{qu1, title = "Broken {brace in BERT quote", author = {B}, journal = {J}, year = {2024}}\n'
        '@article(p1, title = {Foo (bar) and baz ) qux}, author = {C}, journal = {J}, year = {2024})\n'
    )
    ents_p3 = sp.parse_bibtex(p3_bib)
    assert [e["key"] for e in ents_p3] == ["bq1", "qu1", "p1"]

    empty_brace_bib = tmp_path / "empty_brace.bib"
    empty_brace_bib.write_text("@article{eb1, title={{}}, author={{ }}, journal={{}}, year={2024}}\n", encoding="utf-8")
    r_p4 = _run(PREFLIGHT, ["bibtex", str(empty_brace_bib), "--json"])
    assert r_p4.returncode == 1
    p4_checks = [f["check"] for f in json.loads(r_p4.stdout)["findings"]]
    assert p4_checks.count("bibtex/missing-field") == 2
    assert "bibtex/missing-venue" in p4_checks

    # P5: \end{verbatim} % leak, bibtex --tex unsafe-input, prune-unused clears stale dir, acmart \banonymous\b
    tex_d = tmp_path / "ax_p5"
    tex_d.mkdir()
    outside_p5 = tmp_path / "secret_p5.tex"
    outside_p5.write_text("\\author{Real}\n", encoding="utf-8")
    (tex_d / "main.tex").write_text(
        "\\documentclass[nonanonymous]{acmart}\n"
        "\\begin{document}\n"
        "\\begin{verbatim}\n"
        "100% safe\n"
        "\\end{verbatim} % leak_secret@mit.edu\n"
        "\\input{../secret_p5.tex}\n"
        "\\cite{bq1}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    stale_out = tmp_path / "stale_out"
    stale_out.mkdir()
    (stale_out / "old_secret.txt").write_text("stale\n", encoding="utf-8")

    r_ax5 = _run(PREFLIGHT, ["arxiv-clean", str(tex_d), "--strip-comments-out", str(stale_out), "--prune-unused", "--strict", "--json"])
    assert r_ax5.returncode == 1
    assert any(f["check"] == "arxiv/comment-leak" and "leak_secret@mit.edu" in f["message"] for f in json.loads(r_ax5.stdout)["findings"])
    assert not (stale_out / "old_secret.txt").exists()
    assert "leak_secret@mit.edu" not in (stale_out / "main.tex").read_text(encoding="utf-8")

    r_an5 = _run(PREFLIGHT, ["anonymize", str(tex_d / "main.tex"), "--json"])
    assert r_an5.returncode == 1
    an5_findings = json.loads(r_an5.stdout)["findings"]
    assert any(f["check"] == "anonymization/comment-leak" and "leak_secret@mit.edu" in f["message"] for f in an5_findings)
    assert any(f["check"] == "anonymization/class-option" and "acmart" in f["message"] for f in an5_findings)

    ok_bib = tmp_path / "ok_p5.bib"
    ok_bib.write_text('@article{bq1, title={Valid}, author={Doe, A.}, journal={ICML}, year={2024}}\n', encoding="utf-8")
    r_bb5 = _run(PREFLIGHT, ["bibtex", str(ok_bib), "--tex", str(tex_d / "main.tex"), "--json"])
    assert r_bb5.returncode == 1
    assert any(f["check"] == "bibtex/unsafe-input" for f in json.loads(r_bb5.stdout)["findings"])


def test_check_experiment_rigor_r2_regressions(tmp_path: Path) -> None:
    # G1: Escaped \' inside single quotes in broken .py and .R (while preserving bash non-escaping '')
    repo_g1 = tmp_path / "repo_g1"
    repo_g1.mkdir()
    (repo_g1 / "README.md").write_text("Download dataset.\n```bash\npython run.R\n```\n", encoding="utf-8")
    (repo_g1 / "requirements.txt").write_text("torch==2.5.1\n", encoding="utf-8")
    (repo_g1 / "data").mkdir()
    (repo_g1 / "bad_helper.py").write_text("0x\nmsg = 'it\\'s' # torch.manual_seed(0)\n", encoding="utf-8")
    (repo_g1 / "run.R").write_text("msg <- 'it\\'s' # set_seed(0)\n", encoding="utf-8")
    (repo_g1 / "run.sh").write_text("echo 'hello\\' # torch.manual_seed(0)\n", encoding="utf-8")

    r_g1 = _run(EXP_RIGOR, ["repro", str(repo_g1), "--json"])
    assert r_g1.returncode == 1
    assert "SEED" in json.loads(r_g1.stdout)["missing"]

    # G2: .ipynb %magic in indented block must NOT trigger IndentationError & bypass docstring stripping
    repo_g2 = tmp_path / "repo_g2"
    repo_g2.mkdir()
    (repo_g2 / "README.md").write_text("Download dataset.\n```bash\njupyter nbconvert\n```\n", encoding="utf-8")
    (repo_g2 / "requirements.txt").write_text("torch==2.5.1\n", encoding="utf-8")
    (repo_g2 / "data").mkdir()
    (repo_g2 / "nb.ipynb").write_text(
        json.dumps({
            "cells": [{
                "cell_type": "code",
                "source": ['if True:\n', '    %time x = 1\n', '"""\n', 'torch.manual_seed(0)\n', '"""\n', 'y = 2\n'],
            }]
        }),
        encoding="utf-8",
    )
    r_g2 = _run(EXP_RIGOR, ["repro", str(repo_g2), "--json"])
    assert r_g2.returncode == 1
    assert "SEED" in json.loads(r_g2.stdout)["missing"]

    # G3: Falsy 0 / False field values must still be extracted for contamination detection
    tr0 = tmp_path / "tr0.jsonl"
    ev0 = tmp_path / "ev0.jsonl"
    tr0.write_text(json.dumps({"id": "train_1", "answer": 0}) + "\n", encoding="utf-8")
    ev0.write_text(json.dumps({"id": "eval_1", "answer": 0}) + "\n", encoding="utf-8")
    r_g3 = _run(EXP_RIGOR, ["contamination", "--train", str(tr0), "--eval", str(ev0), "--json"])
    assert r_g3.returncode == 1
    assert json.loads(r_g3.stdout)["exact_match_count"] == 1


# ---------------------------------------------------------------------------
# Iteration 3 Regression Tests
# ---------------------------------------------------------------------------


def test_r3_submission_preflight_regressions(tmp_path: Path) -> None:
    sp = _load_mod("preflight_m8a_r3", PREFLIGHT)

    # 1. _protect_token / _split_brace_segments: no RecursionError on braced hyphens/slashes/unclosed braces
    assert sp.protect_title_caps("{GPT-4}s") == "{GPT-4}s"
    assert sp.protect_title_caps("{ResNet-50}'s") == "{ResNet-50}'s"
    assert sp.protect_title_caps("{Pre-Trained}-CNN") == "{Pre-Trained}-{CNN}"
    assert sp.protect_title_caps("{BERT/GPT}s") == "{BERT/GPT}s"
    assert sp.protect_title_caps("{A--B}s") == "{A--B}s"
    assert sp.protect_title_caps("non-{BERT-Large}") == "non-{BERT-Large}"
    assert sp.protect_title_caps("Broken {BERT") == "Broken {BERT"
    assert sp.protect_title_caps("Broken/{BERT") == "Broken/{BERT"

    bib_crash = tmp_path / "r3_crash.bib"
    bib_crash.write_text(
        '@article{g1, title={{GPT-4}s in Action}, author={Doe, A.}, journal={ICLR}, year={2024}}\n'
        '@article{qu1, title = "Broken {brace in BERT quote", author = {Smith, J.}, journal = {ICML}, year = {2024}}\n'
        '@article{eq3, title = "A {nested "quote", test} end", author = {Lee, K.}, journal = {NeurIPS}, year = {2024}}\n',
        encoding="utf-8",
    )
    r_bib = _run(PREFLIGHT, ["bibtex", str(bib_crash), "--json", "-"])
    assert r_bib.returncode == 0, r_bib.stdout + r_bib.stderr
    assert json.loads(r_bib.stdout)["entry_count"] == 3
    parsed_eq = sp.parse_bibtex(bib_crash.read_text(encoding="utf-8"))
    assert [e["key"] for e in parsed_eq] == ["g1", "qu1", "eq3"]
    assert parsed_eq[2]["fields"]["title"] == 'A {nested "quote", test} end'

    # 2. acmart anonymous=false / anonymous = false must warn; anonymous=true passes
    for tex_name, opts, expect_warn in (
        ("acm_false.tex", "sigconf,anonymous=false", True),
        ("acm_false_sp.tex", "sigconf, anonymous = false", True),
        ("acm_true.tex", "sigconf,anonymous=true", False),
    ):
        tf = tmp_path / tex_name
        tf.write_text(f"\\documentclass[{opts}]{{acmart}}\n\\begin{{document}}\nHi.\n\\end{{document}}\n", encoding="utf-8")
        r_acm = _run(PREFLIGHT, ["anonymize", str(tf), "--strict", "--json", "-"])
        if expect_warn:
            assert r_acm.returncode == 1
            assert any(f["check"] == "anonymization/class-option" for f in json.loads(r_acm.stdout)["findings"])
        else:
            assert r_acm.returncode == 0, r_acm.stdout

    # 3. _titles_match: reject loose prefix without subtitle boundary or high overlap
    assert not sp._titles_match("A Survey of Deep Learning", "A Survey of Deep Learning for Healthcare")
    assert sp._titles_match(
        "Deep Learning for Natural Language Processing",
        "Deep Learning for Natural Language Processing: A Unified Approach",
    )
    assert sp._titles_match(
        "A Survey of Deep Learning for Vision",
        "A Survey of Deep Learning for Vision Systems",
    )


def test_r3_sync_skills_s3_output_overlap_guard(tmp_path: Path) -> None:
    suite = tmp_path / "suite_s3"
    _make_mini_suite(suite)
    skill_md = suite / "research-scientist" / "SKILL.md"
    orig_md = skill_md.read_text(encoding="utf-8")
    t_new = tmp_path / "t_new"

    for bad_flag, bad_out in (
        ("--out", suite / "research-scientist" / "SKILL.md"),
        ("--out", suite / "report.json"),
        ("--json", suite / "research-scientist" / "out.json"),
        ("--out", t_new / "research-scientist" / "report.json"),
        ("--json", t_new / "research-paper-writing"),
    ):
        r_bad = _run(
            SYNC_SKILLS,
            ["--suite-root", str(suite), "--target-dir", str(t_new), bad_flag, str(bad_out)],
        )
        assert r_bad.returncode == 2, f"Expected exit 2 for {bad_flag}={bad_out}, got {r_bad.returncode}"
        assert skill_md.read_text(encoding="utf-8") == orig_md
        assert not t_new.exists()

    # Sibling file directly in target_dir (outside any skill subdir) is allowed
    ok_out = t_new / "sync_receipt.json"
    r_ok = _run(SYNC_SKILLS, ["--suite-root", str(suite), "--target-dir", str(t_new), "--out", str(ok_out), "--compact"])
    assert r_ok.returncode == 0, r_ok.stdout + r_ok.stderr
    assert ok_out.is_file()
    assert _run(SYNC_SKILLS, ["--suite-root", str(suite), "--target-dir", str(t_new), "--check"]).returncode == 0


def test_r3_figure_qa_f2_f6_f7_and_expanduser(tmp_path: Path) -> None:
    # F2-R2: /ObjStm with (myobj) passes; non-ObjStm with /Title (/Type /ObjStm) or comment fails missing-bbox
    stm_bbox = zlib.compress(b"1 0 obj << /MediaBox [0 0 100 100] >> endobj\n")
    valid_objstm_pdf = tmp_path / "valid_objstm.pdf"
    valid_objstm_pdf.write_bytes(
        b"%PDF-1.5\n1 0 obj\n<< /Type /ObjStm /Producer (myobj) /Filter /FlateDecode >>\nstream\n"
        + stm_bbox
        + b"\nendstream\nendobj\n%%EOF\n"
    )
    r_ok_pdf = _run(FIGURE_QA, ["figure", str(valid_objstm_pdf), "--strict", "--json"])
    assert r_ok_pdf.returncode == 0, r_ok_pdf.stdout

    for name, hdr in (
        ("spoof_title.pdf", b"<< /Title (/Type /ObjStm) /Filter /FlateDecode >>"),
        ("spoof_comment.pdf", b"% /Type /ObjStm\n<< /Filter /FlateDecode >>"),
    ):
        bad_pdf = tmp_path / name
        bad_pdf.write_bytes(
            b"%PDF-1.5\n1 0 obj\n" + hdr + b"\nstream\n" + stm_bbox + b"\nendstream\nendobj\n%%EOF\n"
        )
        r_bad_pdf = _run(FIGURE_QA, ["figure", str(bad_pdf), "--strict", "--json"])
        assert r_bad_pdf.returncode == 1
        assert any(f["check"] == "figure/missing-bbox" for f in json.loads(r_bad_pdf.stdout)["findings"])

    # F6: barh X-axis truncation via set_xlim / xlim / set(xlim=...)
    for idx, call in enumerate(
        (
            "ax.set_xlim(0.5, 1.0)",
            "ax.set_xlim(left=0.5)",
            "plt.xlim(xmin=0.5)",
            "ax.set(xlim=(0.5, 1.0))",
        )
    ):
        bh = tmp_path / f"barh_{idx}.py"
        bh.write_text(f"ax.barh(['a', 'b'], [3, 4])\n{call}\n", encoding="utf-8")
        r_bh = _run(FIGURE_QA, ["figure", str(bh), "--strict", "--json"])
        assert r_bh.returncode == 1
        assert any(f["check"] == "figure/truncated-bar-axis" for f in json.loads(r_bh.stdout)["findings"])

    # F7: rcParams.update(list of pairs), rcParams |= {...}, savefig format='png', Path.with_suffix('.png'), UTF-8 docstring
    for idx, code in enumerate(
        (
            "import matplotlib.pyplot as plt\nplt.rcParams.update([('pdf.fonttype', 42)])\nplt.savefig('a.pdf')\n",
            "import matplotlib.pyplot as plt\nplt.rcParams |= {'pdf.fonttype': 42}\nplt.savefig('a.pdf')\n",
            "import matplotlib.pyplot as plt\nplt.savefig('a.pdf', format='png')\n",
            "from pathlib import Path\nimport matplotlib.pyplot as plt\nplt.savefig(Path('a.pdf').with_suffix('.png'))\n",
            "import matplotlib.pyplot as plt\ns = 'café'\n\"\"\"cmap='jet'\"\"\"\nplt.plot([1, 2])\n",
        )
    ):
        ok_py = tmp_path / f"ok_f7_{idx}.py"
        ok_py.write_text(code, encoding="utf-8")
        r_f7 = _run(FIGURE_QA, ["figure", str(ok_py), "--strict", "--json"])
        assert r_f7.returncode == 0, f"Case {idx} failed: {r_f7.stdout}"

    # --out ~/fig_out.json expands HOME
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    r_home = _run(
        FIGURE_QA,
        ["figure", str(tmp_path / "ok_f7_0.py"), "--out", "~/fig_out.json", "--compact"],
        extra_env={"HOME": str(fake_home)},
    )
    assert r_home.returncode == 0, r_home.stderr
    assert (fake_home / "fig_out.json").is_file()


def test_r3_experiment_rigor_utf8_col_offset(tmp_path: Path) -> None:
    repo = tmp_path / "repo_utf8"
    (repo / "data").mkdir(parents=True)
    (repo / "README.md").write_text("Download dataset.\n```bash\npython train.py\n```\n", encoding="utf-8")
    (repo / "requirements.txt").write_text("torch==2.5.1\n", encoding="utf-8")
    (repo / "train.py").write_text('x = "café"; """torch.manual_seed(0)"""\n', encoding="utf-8")

    r_utf8 = _run(EXP_RIGOR, ["repro", str(repo), "--json", "-"])
    assert r_utf8.returncode == 1
    assert "SEED" in json.loads(r_utf8.stdout)["missing"]


def test_r3_check_rebuttal_bold_colon_multiline_quote_and_h2_q1(tmp_path: Path) -> None:
    # 1. Empty bold-colon stubs (**R1.1:**, - **R1.1:**, ### **R1.1:**) must NOT count as covered
    pts = tmp_path / "pts.md"
    pts.write_text("R1.1: First.\nR1.2: Second.\n", encoding="utf-8")
    for idx, stub in enumerate(("**R1.1:**", "- **R1.1:**", "### **R1.1:**", "__R1.1:__")):
        resp = tmp_path / f"resp_stub_{idx}.md"
        resp.write_text(f"{stub}\n**R1.2:** See Table 1.\n", encoding="utf-8")
        r_stub = _run(REBUTTAL, ["coverage", str(pts), str(resp), "--json", "-"])
        assert r_stub.returncode == 1
        d_stub = json.loads(r_stub.stdout)
        assert "R1.1" in d_stub["missing_points"]
        assert "R1.1" not in d_stub["covered_points"]
        assert "R1.2" in d_stub["covered_points"]

    # 2. Multi-line Reviewer comment: "..." containing R1.2: must NOT split sub-blocks or credit R1.2 / Table 1
    resp_mq = tmp_path / "resp_mq.md"
    resp_mq.write_text(
        'R1.1:\nReviewer comment: "Unclear.\nR1.2: Also check Table 1."\nWe clarified in Sec. 2.\n',
        encoding="utf-8",
    )
    r_mq = _run(REBUTTAL, ["coverage", str(pts), str(resp_mq), "--strict", "--json", "-"])
    assert r_mq.returncode == 1
    d_mq = json.loads(r_mq.stdout)
    assert d_mq["covered_points"] == ["R1.1"]
    assert d_mq["missing_points"] == ["R1.2"]
    assert d_mq["unanchored_sections"] == []

    # 3. ## Q1: H2 sections in responses.md credit Q1/Q2 when substantive, reject when empty/quote-only
    pts_q = tmp_path / "pts_q.md"
    pts_q.write_text("## Q1: Why?\n## Q2: How?\n", encoding="utf-8")
    resp_q_ok = tmp_path / "resp_q_ok.md"
    resp_q_ok.write_text("## Q1:\nExplained in Table 1.\n\n## Q2:\nExplained in Fig. 1.\n", encoding="utf-8")
    r_q_ok = _run(REBUTTAL, ["coverage", str(pts_q), str(resp_q_ok), "--strict", "--json", "-"])
    assert r_q_ok.returncode == 0, r_q_ok.stdout
    assert json.loads(r_q_ok.stdout)["covered_points"] == ["Q1", "Q2"]

    resp_q_empty = tmp_path / "resp_q_empty.md"
    resp_q_empty.write_text("## Q1:\n> Reviewer comment: \"Why?\"\n\n## Q2:\nExplained in Fig. 1.\n", encoding="utf-8")
    r_q_empty = _run(REBUTTAL, ["coverage", str(pts_q), str(resp_q_empty), "--json", "-"])
    assert r_q_empty.returncode == 1
    assert json.loads(r_q_empty.stdout)["missing_points"] == ["Q1"]


# ---------------------------------------------------------------------------
# Iteration 4 Regression Tests
# ---------------------------------------------------------------------------


def _make_minimal_repro_repo(repo: Path, train_bytes: bytes) -> None:
    (repo / "data").mkdir(parents=True, exist_ok=True)
    (repo / "README.md").write_text("Download dataset.\n```bash\npython train.py\n```\n", encoding="utf-8")
    (repo / "requirements.txt").write_text("torch==2.5.1\n", encoding="utf-8")
    (repo / "train.py").write_bytes(train_bytes)


def test_r4_experiment_rigor_bom_and_constant_fstring_docstrings(tmp_path: Path) -> None:
    # 1. UTF-8 BOM must not trigger SyntaxError and disable docstring stripping
    bom_cases = (
        ("bom_mid", b"\xef\xbb\xbf" + b'x = 1\n"""torch.manual_seed(0)"""\n'),
        ("bom_head", b"\xef\xbb\xbf" + b'"""torch.manual_seed(0)"""\nprint(1)\n'),
        ("bom_utf8", b"\xef\xbb\xbf" + 'x = "café"; """torch.manual_seed(0)"""\nprint(1)\n'.encode("utf-8")),
    )
    for name, payload in bom_cases:
        repo = tmp_path / name
        _make_minimal_repro_repo(repo, payload)
        r = _run(EXP_RIGOR, ["repro", str(repo), "--json", "-"])
        assert r.returncode == 1, f"{name}: {r.stdout}"
        assert "SEED" in json.loads(r.stdout)["missing"], f"{name}: {r.stdout}"

    # 2. Constant-only f"""...""" docstrings must also be stripped
    fstr_cases = (
        ("fstr_single", b'f"""torch.manual_seed(0)"""\nprint(1)\n'),
        ("fstr_utf8_multi", 'x = "café"; f"""\ntorch.manual_seed(0)\n"""\nprint(1)\n'.encode("utf-8")),
        ("fstr_bom", b"\xef\xbb\xbf" + b'f"""torch.manual_seed(0)"""\nprint(1)\n'),
    )
    for name, payload in fstr_cases:
        repo = tmp_path / name
        _make_minimal_repro_repo(repo, payload)
        r = _run(EXP_RIGOR, ["repro", str(repo), "--json", "-"])
        assert r.returncode == 1, f"{name}: {r.stdout}"
        assert "SEED" in json.loads(r.stdout)["missing"], f"{name}: {r.stdout}"

    # 3. Real seeding inside a UTF-8 BOM file still passes
    repo_ok = tmp_path / "bom_real_seed"
    _make_minimal_repro_repo(
        repo_ok,
        b"\xef\xbb\xbf" + b'import torch\nif __name__ == "__main__":\n    torch.manual_seed(0)\n',
    )
    r_ok = _run(EXP_RIGOR, ["repro", str(repo_ok), "--strict", "--json", "-"])
    assert r_ok.returncode == 0, r_ok.stdout
    assert json.loads(r_ok.stdout)["missing"] == []


def test_r4_check_rebuttal_title_mask_nested_wrappers_and_unclosed_quote(tmp_path: Path) -> None:
    pts = tmp_path / "pts.md"
    pts.write_text("R1.1: First.\nR1.2: Second.\n", encoding="utf-8")

    # 1. H2 section title must NOT mask empty or omitted sub-points when explicit point sub-blocks exist
    resp_mask1 = tmp_path / "resp_mask1.md"
    resp_mask1.write_text("## Addressing R1.1 and R1.2\nR1.1:\nR1.2: See Table 1.\n", encoding="utf-8")
    r_m1 = _run(REBUTTAL, ["coverage", str(pts), str(resp_mask1), "--strict", "--json", "-"])
    assert r_m1.returncode == 1
    d_m1 = json.loads(r_m1.stdout)
    assert d_m1["verdict"] == "FAIL"
    assert d_m1["covered_points"] == ["R1.2"]
    assert d_m1["missing_points"] == ["R1.1"]

    resp_mask2 = tmp_path / "resp_mask2.md"
    resp_mask2.write_text("## Addressing R1.1 and R1.2\nR1.1: See Table 1.\n", encoding="utf-8")
    r_m2 = _run(REBUTTAL, ["coverage", str(pts), str(resp_mask2), "--strict", "--json", "-"])
    assert r_m2.returncode == 1
    d_m2 = json.loads(r_m2.stdout)
    assert d_m2["covered_points"] == ["R1.1"]
    assert d_m2["missing_points"] == ["R1.2"]

    # 2. Nested/triple markdown empty stubs must NOT count as covered
    for idx, stub in enumerate(
        (
            "**[R1.1]:**",
            "[**R1.1**]:",
            "***R1.1:***",
            "___R1.1:___",
            "**[R1.1]**:",
            "- **[R1.1]:**",
            "### **[R1.1]:**",
        )
    ):
        resp_s = tmp_path / f"resp_nested_stub_{idx}.md"
        resp_s.write_text(f"{stub}\n**[R1.2]:** See Table 1.\n", encoding="utf-8")
        r_s = _run(REBUTTAL, ["coverage", str(pts), str(resp_s), "--strict", "--json", "-"])
        assert r_s.returncode == 1, f"Stub {stub!r} failed: {r_s.stdout}"
        d_s = json.loads(r_s.stdout)
        assert d_s["verdict"] == "FAIL", f"Stub {stub!r}: {d_s}"
        assert d_s["missing_points"] == ["R1.1"], f"Stub {stub!r}: {d_s}"
        assert d_s["covered_points"] == ["R1.2"], f"Stub {stub!r}: {d_s}"

    resp_nested_ok = tmp_path / "resp_nested_ok.md"
    resp_nested_ok.write_text("**[R1.1]:** See Table 1.\n***R1.2:*** See Fig. 1.\n", encoding="utf-8")
    r_nok = _run(REBUTTAL, ["coverage", str(pts), str(resp_nested_ok), "--strict", "--json", "-"])
    assert r_nok.returncode == 0, r_nok.stdout
    assert json.loads(r_nok.stdout)["covered_points"] == ["R1.1", "R1.2"]

    # 3. Unclosed Reviewer comment quote in R1.1 must not swallow later R1.2's Reviewer comment block
    resp_uq_split = tmp_path / "resp_unclosed_quote_split.md"
    resp_uq_split.write_text(
        'R1.1:\nReviewer comment: "Why is this needed?\n\n'
        'R1.2:\nReviewer comment: "What about memory?"\nWe report memory in Table 1.\n',
        encoding="utf-8",
    )
    r_uq_split = _run(REBUTTAL, ["coverage", str(pts), str(resp_uq_split), "--json", "-"])
    assert r_uq_split.returncode == 1
    d_uq_split = json.loads(r_uq_split.stdout)
    assert d_uq_split["covered_points"] == ["R1.2"]
    assert d_uq_split["missing_points"] == ["R1.1"]

    resp_uq_both = tmp_path / "resp_unclosed_quote_both.md"
    resp_uq_both.write_text(
        'R1.1: We explain in Sec. 2.\nReviewer comment: "Why is this needed?\n\n'
        'R1.2:\nReviewer comment: "What about memory?"\nWe report memory in Table 1.\n',
        encoding="utf-8",
    )
    r_uq_both = _run(REBUTTAL, ["coverage", str(pts), str(resp_uq_both), "--strict", "--json", "-"])
    assert r_uq_both.returncode == 0, r_uq_both.stdout
    assert json.loads(r_uq_both.stdout)["covered_points"] == ["R1.1", "R1.2"]


def test_r4_submission_preflight_multiline_includegraphics_and_fix_out_unbalanced_brace(tmp_path: Path) -> None:
    # 1. Multi-line \includegraphics and \input must be recognized and NOT flagged/pruned
    tex_dir = tmp_path / "arxiv_multiline"
    tex_dir.mkdir()
    (tex_dir / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\includegraphics[\n"
        "  width=0.5\\linewidth % half width\n"
        "]{fig1.png}\n"
        "\\input{\n"
        "  sec1.tex\n"
        "}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    (tex_dir / "sec1.tex").write_text("\\includegraphics\n{fig2.png}\n", encoding="utf-8")
    (tex_dir / "fig1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (tex_dir / "fig2.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    out_clean = tmp_path / "arxiv_clean_out"
    r_clean = _run(
        PREFLIGHT,
        ["arxiv-clean", str(tex_dir), "--strip-comments-out", str(out_clean), "--prune-unused", "--strict", "--json", "-"],
    )
    assert r_clean.returncode == 0, r_clean.stdout + r_clean.stderr
    d_clean = json.loads(r_clean.stdout)
    assert d_clean["verdict"] == "PASS"
    assert d_clean["findings"] == []
    assert d_clean["pruned_files"] == []
    assert (out_clean / "fig1.png").is_file()
    assert (out_clean / "fig2.png").is_file()
    assert (out_clean / "sec1.tex").is_file()

    # Add an actually unused image; only unused.png is flagged/pruned
    (tex_dir / "unused.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    r_prune = _run(
        PREFLIGHT,
        ["arxiv-clean", str(tex_dir), "--strip-comments-out", str(out_clean), "--prune-unused", "--json", "-"],
    )
    assert r_prune.returncode == 0, r_prune.stdout
    d_prune = json.loads(r_prune.stdout)
    assert d_prune["pruned_files"] == ["unused.png"]
    assert [f["file"] for f in d_prune["findings"] if f["check"] == "arxiv/unused-figure"] == ["unused.png"]
    assert (out_clean / "fig1.png").is_file()
    assert (out_clean / "fig2.png").is_file()
    assert not (out_clean / "unused.png").exists()

    # 2. --fix-out on accepted quoted unbalanced-brace BibTeX entries must re-parse cleanly
    bib_in = tmp_path / "unbalanced.bib"
    bib_in.write_text(
        '@article{qu1, title = "Broken {brace in BERT quote", author = {Smith, J.}, journal = {ICML}, year = {2024}}\n'
        '@article{qu2, title = "Broken {brace with \\"quote\\", BERT", author = {Lee, K.}, journal = {ICLR}, year = {2024}}\n'
        '@article{qu3, title = "Broken } brace in BERT", author = {Doe, A.}, journal = {NeurIPS}, year = {2024}}\n',
        encoding="utf-8",
    )
    bib_fixed = tmp_path / "fixed.bib"
    r_fix = _run(PREFLIGHT, ["bibtex", str(bib_in), "--protect-caps", "--fix-out", str(bib_fixed), "--json", "-"])
    assert r_fix.returncode == 0, r_fix.stdout + r_fix.stderr
    assert bib_fixed.is_file()

    r_re = _run(PREFLIGHT, ["bibtex", str(bib_fixed), "--strict", "--json", "-"])
    assert r_re.returncode == 0, r_re.stdout + r_re.stderr
    d_re = json.loads(r_re.stdout)
    assert d_re["entry_count"] == 3
    assert d_re["verdict"] == "PASS"
    assert d_re["findings"] == []


# ---------------------------------------------------------------------------
# Iteration 5 Regression Tests
# ---------------------------------------------------------------------------


def test_r5_check_rebuttal_redos_bom_and_pdf_stream(tmp_path: Path) -> None:
    # 1. ReDoS guard: 50KB leading whitespace must run in < 0.05s in-process and fast via CLI
    reb_mod = _load_mod("check_rebuttal_r5", REBUTTAL)
    adv_50k = " " * 50000 + "x"
    adv_multi = (" " * 5000 + "Q1\n") * 20

    for label, fn in (
        ("SHORT_50k", lambda: reb_mod.SHORT_POINT_DEF_RE.findall(adv_50k)),
        ("SUB_50k", lambda: reb_mod._SUBPOINT_LINE_RE.match(adv_50k)),
        ("LEAD_50k", lambda: reb_mod._LEADING_POINT_HEADER_RE.sub("", adv_50k, count=1)),
        ("SHORT_multi", lambda: reb_mod.SHORT_POINT_DEF_RE.findall(adv_multi)),
        ("SUB_multi", lambda: reb_mod._SUBPOINT_LINE_RE.match(adv_multi)),
    ):
        t0 = time.perf_counter()
        fn()
        dt = time.perf_counter() - t0
        assert dt < 0.05, f"{label} took {dt:.4f}s (>= 0.05s)"

    pts = tmp_path / "pts.md"
    pts.write_text("R1.1: First point.\n", encoding="utf-8")
    resp_ws = tmp_path / "resp_ws.md"
    resp_ws.write_text("R1.1: See Table 1.\n" + (" " * 12000 + "x\n") * 3, encoding="utf-8")

    t0_inproc = time.perf_counter()
    cov = reb_mod.check_coverage(pts, [resp_ws])
    assert time.perf_counter() - t0_inproc < 0.05
    assert cov["verdict"] == "PASS"

    t0_cli = time.perf_counter()
    r_cli = _run(REBUTTAL, ["coverage", str(pts), str(resp_ws), "--json", "-"])
    cli_dt = time.perf_counter() - t0_cli
    assert r_cli.returncode == 0, r_cli.stdout + r_cli.stderr
    assert cli_dt < 1.0, f"CLI coverage took {cli_dt:.4f}s"

    # 2. UTF-8 BOM in pts.md / resp.md must parse Q1 cleanly
    pts_bom = tmp_path / "pts_bom.md"
    pts_bom.write_bytes(b"\xef\xbb\xbfQ1: First question.\n")
    resp_bom = tmp_path / "resp_bom.md"
    resp_bom.write_bytes(b"\xef\xbb\xbfQ1: Answered in Table 1.\n")
    r_bom = _run(REBUTTAL, ["coverage", str(pts_bom), str(resp_bom), "--strict", "--json", "-"])
    assert r_bom.returncode == 0, r_bom.stdout + r_bom.stderr
    assert json.loads(r_bom.stdout)["covered_points"] == ["Q1"]

    # 3. PDF count_pdf_pages: metadata strings ending in stream\n must not hide FlateDecode /Type /Page
    compressed_page = zlib.compress(b"/Type /Page\n")
    pdf_bytes = (
        b"%PDF-1.5\n"
        b"1 0 obj << /Title (Downstream\nAnalysis) /Subject (Down stream\nNote) >> endobj\n"
        b"2 0 obj << /Filter /FlateDecode >>\nstream\n"
        + compressed_page
        + b"\nendstream\nendobj\n%%EOF\n"
    )
    pages, method = reb_mod.count_pdf_pages(pdf_bytes)
    assert pages == 1
    assert method == "FlateDecode object streams"


def test_r5_check_figure_qa_pdf_stream_bom_and_const_fstr(tmp_path: Path) -> None:
    # 1. PDF /Title (Downstream\nAnalysis) and fake " stream\n" must not swallow FlateDecode /Subtype /Type3 or /ObjStm
    compressed_type3 = zlib.compress(b"/Type /Font /Subtype /Type3\n")
    compressed_objstm = zlib.compress(b"/MediaBox [0 0 100 100]\n")
    pdf_path = tmp_path / "title_stream_type3.pdf"
    pdf_path.write_bytes(
        b"%PDF-1.5\n"
        b"1 0 obj << /Title (Downstream\nAnalysis) /Subject (Down stream\nNote) >> endobj\n"
        b"2 0 obj << /Filter /FlateDecode >>\nstream\n"
        + compressed_type3
        + b"\nendstream\nendobj\n"
        b"3 0 obj << /Type /ObjStm /Filter /FlateDecode >>\nstream\n"
        + compressed_objstm
        + b"\nendstream\nendobj\n%%EOF\n"
    )
    r_pdf = _run(FIGURE_QA, ["figure", str(pdf_path), "--json", "-"])
    assert r_pdf.returncode == 1, r_pdf.stdout + r_pdf.stderr
    d_pdf = json.loads(r_pdf.stdout)
    assert [f["check"] for f in d_pdf["findings"]] == ["figure/type3-font"]

    # 2. UTF-8 BOM in .py plot script: must catch real errors (no silent FN) and ignore docstrings (no FP)
    bom_bad = tmp_path / "bom_bad.py"
    bom_bad.write_bytes(
        b"\xef\xbb\xbf"
        b"from pathlib import Path\n"
        b"import matplotlib.pyplot as plt\n"
        b"plt.bar(['a', 'b'], [1, 2])\n"
        b"plt.gca().set(ylim=(0.5, 2.5))\n"
        b"plt.savefig(Path('out').with_suffix('.jpg'))\n"
    )
    r_bad = _run(FIGURE_QA, ["figure", str(bom_bad), "--strict", "--json", "-"])
    assert r_bad.returncode == 1, r_bad.stdout + r_bad.stderr
    bad_checks = {f["check"] for f in json.loads(r_bad.stdout)["findings"]}
    assert "figure/jpeg-export" in bad_checks
    assert "figure/truncated-bar-axis" in bad_checks

    bom_doc_ok = tmp_path / "bom_doc_ok.py"
    bom_doc_ok.write_bytes(
        b"\xef\xbb\xbf"
        b'"""Never use cmap=\'jet\'"""\n'
        b"import matplotlib.pyplot as plt\n"
        b"plt.plot([1, 2])\n"
    )
    r_doc_ok = _run(FIGURE_QA, ["figure", str(bom_doc_ok), "--strict", "--json", "-"])
    assert r_doc_ok.returncode == 0, r_doc_ok.stdout + r_doc_ok.stderr
    assert json.loads(r_doc_ok.stdout)["verdict"] == "PASS"

    bom_rc_ok = tmp_path / "bom_rc_ok.py"
    bom_rc_ok.write_bytes(
        b"\xef\xbb\xbf"
        b"from pathlib import Path\n"
        b"import matplotlib.pyplot as plt\n"
        b"plt.rcParams.update([('pdf.fonttype', 42)])\n"
        b"plt.savefig(Path('a.pdf').with_suffix('.png'))\n"
    )
    r_rc_ok = _run(FIGURE_QA, ["figure", str(bom_rc_ok), "--strict", "--json", "-"])
    assert r_rc_ok.returncode == 0, r_rc_ok.stdout + r_rc_ok.stderr
    assert json.loads(r_rc_ok.stdout)["verdict"] == "PASS"

    # 3. Constant-only f"""...""" docstrings must be stripped by _strip_python_comments_and_docstrings
    fig_mod = _load_mod("check_figure_qa_r5", FIGURE_QA)
    cleaned, tree = fig_mod._strip_python_comments_and_docstrings('\ufefff"""cmap=\'jet\'"""\nprint(1)\n')
    assert tree is not None
    assert "jet" not in cleaned


def test_r5_submission_preflight_trailing_backslash_and_multiline_input(tmp_path: Path) -> None:
    # 1. --fix-out round-trip on trailing lone backslash fields (both braced and bare-normalized)
    bib_in = tmp_path / "trailing_bs.bib"
    bib_in.write_text(
        "@article{bs1, title = {Hello \\ }, author = {Smith, J.}, journal = {ICML}, year = {2024}}\n"
        "@article{bs2, title = {BERT paper}, author = {Lee, K.}, journal = {ICLR}, note = foo\\\n, year = {2024}}\n"
        "@article{bs3, title = {Even \\\\}, author = {Doe, A.}, journal = {NeurIPS}, year = {2024}}\n",
        encoding="utf-8",
    )
    bib_fixed = tmp_path / "trailing_bs_fixed.bib"
    r_fix = _run(PREFLIGHT, ["bibtex", str(bib_in), "--protect-caps", "--fix-out", str(bib_fixed), "--json", "-"])
    assert r_fix.returncode == 0, r_fix.stdout + r_fix.stderr

    r_re = _run(PREFLIGHT, ["bibtex", str(bib_fixed), "--strict", "--json", "-"])
    assert r_re.returncode == 0, r_re.stdout + r_re.stderr
    d_re = json.loads(r_re.stdout)
    assert d_re["entry_count"] == 3
    assert d_re["verdict"] == "PASS"

    # 2. Multi-line \input{\n  sec1.tex\n} must be traversed by anonymize and bibtex --tex
    tex_dir = tmp_path / "tex_ml"
    tex_dir.mkdir()
    main_tex = tex_dir / "main.tex"
    main_tex.write_text(
        "\\documentclass{article}\n\\begin{document}\n\\input{\n  sec1.tex\n}\n\\end{document}\n",
        encoding="utf-8",
    )
    (tex_dir / "sec1.tex").write_text(
        "Contact alice@stanford.edu and see \\cite{missing_key}.\n",
        encoding="utf-8",
    )
    r_anon = _run(PREFLIGHT, ["anonymize", str(main_tex), "--json", "-"])
    assert r_anon.returncode == 1, r_anon.stdout + r_anon.stderr
    d_anon = json.loads(r_anon.stdout)
    assert d_anon["verdict"] == "FAIL"
    assert any(f["check"] == "anonymization/email" for f in d_anon["findings"])

    refs_bib = tex_dir / "refs.bib"
    refs_bib.write_text(
        "@article{k1, title = {BERT Paper}, author = {Smith, J.}, journal = {ICML}, year = {2024}}\n",
        encoding="utf-8",
    )
    r_bib_tex = _run(PREFLIGHT, ["bibtex", str(refs_bib), "--tex", str(main_tex), "--json", "-"])
    assert r_bib_tex.returncode == 1, r_bib_tex.stdout + r_bib_tex.stderr
    d_bt = json.loads(r_bib_tex.stdout)
    assert any(f["check"] == "bibtex/undefined-cite" and f["key"] == "missing_key" for f in d_bt["findings"])


def test_r5_experiment_rigor_ipynb_bom_magic_and_contamination_bom(tmp_path: Path) -> None:
    # 1. .ipynb cell-level \ufeff before %/! magic must not bypass magic replacement or docstring stripping
    repo = tmp_path / "nb_repo"
    (repo / "data").mkdir(parents=True)
    (repo / "README.md").write_text("Run notebook.\n```bash\npython main.py\n```\n", encoding="utf-8")
    (repo / "requirements.txt").write_text("torch==2.5.1\n", encoding="utf-8")
    (repo / "main.py").write_text("print('ok')\n", encoding="utf-8")
    nb = {
        "cells": [
            {
                "cell_type": "code",
                "execution_count": 1,
                "metadata": {},
                "outputs": [],
                "source": ["\ufeff%matplotlib inline\n", "f'''torch.manual_seed(0)'''\n", "print(1)\n"],
            }
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    (repo / "nb.ipynb").write_text(json.dumps(nb), encoding="utf-8")
    r_repro = _run(EXP_RIGOR, ["repro", str(repo), "--json", "-"])
    assert r_repro.returncode == 1, r_repro.stdout + r_repro.stderr
    d_repro = json.loads(r_repro.stdout)
    assert d_repro["verdict"] == "FAIL"
    assert "SEED" in d_repro["missing"]

    # 2. UTF-8 BOM in .jsonl/.json contamination corpus must decode cleanly (no rc=2)
    train_jsonl = tmp_path / "train_bom.jsonl"
    train_jsonl.write_bytes(
        b"\xef\xbb\xbf"
        + json.dumps({"text": "unrelated training sample alpha beta gamma delta epsilon zeta eta theta"}).encode("utf-8")
        + b"\n"
    )
    eval_json = tmp_path / "eval_bom.json"
    eval_json.write_bytes(
        b"\xef\xbb\xbf"
        + json.dumps([{"text": "completely distinct evaluation prompt iota kappa lambda mu nu xi omicron"}]).encode("utf-8")
    )
    r_cont = _run(EXP_RIGOR, ["contamination", "--train", str(train_jsonl), "--eval", str(eval_json), "--json", "-"])
    assert r_cont.returncode == 0, r_cont.stdout + r_cont.stderr
    assert json.loads(r_cont.stdout)["verdict"] == "PASS"


# ---------------------------------------------------------------------------
# Iteration 6 Regression Tests
# ---------------------------------------------------------------------------


def test_r6_pdf_stream_retry_linear_time(tmp_path: Path) -> None:
    fig_mod = _load_mod("check_figure_qa_r6", FIGURE_QA)
    reb_mod = _load_mod("check_rebuttal_r6", REBUTTAL)

    for prefix in (b" stream\n", b" stream\n\x78\x9c"):
        for n in (10000, 40000):
            payload = prefix * n + b"endstream"

            t0 = time.perf_counter()
            assert fig_mod._inflate_pdf_streams_meta(payload) == []
            dt_fig = time.perf_counter() - t0
            assert dt_fig < 0.2, f"check_figure_qa._inflate_pdf_streams_meta({prefix!r}, N={n}) took {dt_fig:.4f}s (>= 0.2s)"

            t0 = time.perf_counter()
            with pytest.raises(ValueError, match="Could not determine a positive PDF page count"):
                reb_mod.count_pdf_pages(payload)
            dt_reb = time.perf_counter() - t0
            assert dt_reb < 0.2, f"check_rebuttal.count_pdf_pages({prefix!r}, N={n}) took {dt_reb:.4f}s (>= 0.2s)"

    # Verify CLI figure check on a 200KB PDF with repeated " stream\n" stays fast and passes
    pdf_200kb = tmp_path / "adv_200kb.pdf"
    pdf_200kb.write_bytes(b"%PDF-1.5\n" + b" stream\n" * 25000 + b"endstream\n/MediaBox [0 0 10 10]\n%%EOF\n")
    t0_cli = time.perf_counter()
    r_cli = _run(FIGURE_QA, ["figure", str(pdf_200kb), "--json", "-"])
    dt_cli = time.perf_counter() - t0_cli
    assert r_cli.returncode == 0, r_cli.stdout + r_cli.stderr
    assert dt_cli < 1.0, f"check_figure_qa CLI on 200KB PDF took {dt_cli:.4f}s"

    # Verify /Type /ObjStm preceded by false " stream\n" retries still resolves accurately
    compressed_objstm = zlib.compress(b"/MediaBox [0 0 100 100]\n")
    pdf_objstm = tmp_path / "objstm_after_retries.pdf"
    pdf_objstm.write_bytes(
        b"%PDF-1.5\n"
        b"1 0 obj << /Title (Downstream\nAnalysis) >> endobj\n"
        b"2 0 obj << /Type /ObjStm /Subject (Down stream\nNote) /Filter /FlateDecode >>\nstream\n"
        + compressed_objstm
        + b"\nendstream\nendobj\n%%EOF\n"
    )
    r_obj = _run(FIGURE_QA, ["figure", str(pdf_objstm), "--json", "-"])
    assert r_obj.returncode == 0, r_obj.stdout + r_obj.stderr
    assert json.loads(r_obj.stdout)["findings"] == []


# ---------------------------------------------------------------------------
# Iteration 7 Regression Tests
# ---------------------------------------------------------------------------


def test_r7_pdf_stream_adv_probes_and_downstream_recovery(tmp_path: Path) -> None:
    fig_mod = _load_mod("check_figure_qa_r7", FIGURE_QA)
    reb_mod = _load_mod("check_rebuttal_r7", REBUTTAL)

    # 1. adv_stored67: valid 64B zlib+stored prefix failing at byte 67 (N=40000 -> ~3.2MB, < 0.5s)
    adv_stored67_unit = b" stream\n\x78\x9c\x00\x3c\x00\xc3\xff" + b"A" * 60 + b"\x00\x00\x00\x00\x01"
    adv_stored67 = adv_stored67_unit * 40000 + b"endstream"

    t0 = time.perf_counter()
    assert fig_mod._inflate_pdf_streams_meta(adv_stored67) == []
    dt_fig_67 = time.perf_counter() - t0
    assert dt_fig_67 < 0.5, f"check_figure_qa adv_stored67 N=40000 took {dt_fig_67:.4f}s (>= 0.5s)"

    t0 = time.perf_counter()
    with pytest.raises(ValueError, match="Could not determine a positive PDF page count"):
        reb_mod.count_pdf_pages(adv_stored67)
    dt_reb_67 = time.perf_counter() - t0
    assert dt_reb_67 < 0.5, f"check_rebuttal adv_stored67 N=40000 took {dt_reb_67:.4f}s (>= 0.5s)"

    # 2. Probe A: 65B empty sync-flush blocks exceeding 64B initial probe (N=20000 -> ~1.5MB, < 0.2s)
    probe_a_unit = b" stream\n\x78\x9c" + (b"\x00\x00\x00\xff\xff" * 13)
    probe_a = probe_a_unit * 20000 + b"endstream"

    t0 = time.perf_counter()
    assert fig_mod._inflate_pdf_streams_meta(probe_a) == []
    dt_fig_a = time.perf_counter() - t0
    assert dt_fig_a < 0.2, f"check_figure_qa Probe A N=20000 took {dt_fig_a:.4f}s (>= 0.2s)"

    t0 = time.perf_counter()
    with pytest.raises(ValueError, match="Could not determine a positive PDF page count"):
        reb_mod.count_pdf_pages(probe_a)
    dt_reb_a = time.perf_counter() - t0
    assert dt_reb_a < 0.2, f"check_rebuttal Probe A N=20000 took {dt_reb_a:.4f}s (>= 0.2s)"

    # 3. Probe B: chained 10B stored blocks wrapping " stream\n\x78\x9c" (N=4000 -> ~60KB, < 0.05s)
    probe_b_unit = b" stream\n\x78\x9c\x00\x0a\x00\xf5\xff"
    probe_b = probe_b_unit * 4000 + b"0123456789\xff\xffendstream"

    t0 = time.perf_counter()
    assert fig_mod._inflate_pdf_streams_meta(probe_b) == []
    dt_fig_b = time.perf_counter() - t0
    assert dt_fig_b < 0.05, f"check_figure_qa Probe B N=4000 took {dt_fig_b:.4f}s (>= 0.05s)"

    t0 = time.perf_counter()
    with pytest.raises(ValueError, match="Could not determine a positive PDF page count"):
        reb_mod.count_pdf_pages(probe_b)
    dt_reb_b = time.perf_counter() - t0
    assert dt_reb_b < 0.05, f"check_rebuttal Probe B N=4000 took {dt_reb_b:.4f}s (>= 0.05s)"

    # 4. u65k: 65535B stored blocks wrapping " stream\n\x78\x9c" (N=40000 -> ~600KB, < 0.1s)
    u65k_unit = b" stream\n\x78\x9c\x00\xff\xff\x00\x00"
    u65k = u65k_unit * 40000 + b"endstream"

    t0 = time.perf_counter()
    assert fig_mod._inflate_pdf_streams_meta(u65k) == []
    dt_fig_u = time.perf_counter() - t0
    assert dt_fig_u < 0.1, f"check_figure_qa u65k N=40000 took {dt_fig_u:.4f}s (>= 0.1s)"

    t0 = time.perf_counter()
    with pytest.raises(ValueError, match="Could not determine a positive PDF page count"):
        reb_mod.count_pdf_pages(u65k)
    dt_reb_u = time.perf_counter() - t0
    assert dt_reb_u < 0.1, f"check_rebuttal u65k N=40000 took {dt_reb_u:.4f}s (>= 0.1s)"

    # 5. Downstream valid FlateDecode stream recovery AFTER adversarial Probe B + adv_stored67 blocks
    comp_type3 = zlib.compress(b"/Type /Font /Subtype /Type3\n")
    comp_objstm = zlib.compress(b"/MediaBox [0 0 100 100]\n")
    fig_recovery_pdf = tmp_path / "downstream_recovery_fig.pdf"
    fig_recovery_pdf.write_bytes(
        b"%PDF-1.5\n"
        b"1 0 obj << /Length 100 >>\nstream\n"
        + probe_b_unit * 500
        + b"0123456789\xff\xff\nendstream\nendobj\n"
        b"2 0 obj << /Length 100 >>\nstream\n"
        + adv_stored67_unit * 500
        + b"\nendstream\nendobj\n"
        b"3 0 obj << /Filter /FlateDecode >>\nstream\n"
        + comp_type3
        + b"\nendstream\nendobj\n"
        b"4 0 obj << /Type /ObjStm /Filter /FlateDecode >>\nstream\n"
        + comp_objstm
        + b"\nendstream\nendobj\n%%EOF\n"
    )
    r_fig_rec = _run(FIGURE_QA, ["figure", str(fig_recovery_pdf), "--json", "-"])
    assert r_fig_rec.returncode == 1, r_fig_rec.stdout + r_fig_rec.stderr
    fig_checks = [f["check"] for f in json.loads(r_fig_rec.stdout)["findings"]]
    assert fig_checks == ["figure/type3-font"], f"Expected only Type3 finding (ObjStm MediaBox recovered), got {fig_checks}"

    # Also verify _TAIL_STREAM_RE fallback recovers an unclosed-prior-obj downstream >>\nstream\n in same endstream span
    tail_fallback_fig = tmp_path / "tail_fallback_fig.pdf"
    tail_fallback_fig.write_bytes(
        b"%PDF-1.5\n"
        b"1 0 obj << /Length 100 >>\nstream\n"
        + probe_b_unit * 500
        + b"0123456789\xff\xff\n"
        b"2 0 obj << /Type /ObjStm /Filter /FlateDecode >>\nstream\n"
        + zlib.compress(b"/Type /Font /Subtype /Type3 /MediaBox [0 0 50 50]\n")
        + b"\nendstream\nendobj\n%%EOF\n"
    )
    r_tail_fig = _run(FIGURE_QA, ["figure", str(tail_fallback_fig), "--json", "-"])
    assert r_tail_fig.returncode == 1, r_tail_fig.stdout + r_tail_fig.stderr
    assert [f["check"] for f in json.loads(r_tail_fig.stdout)["findings"]] == ["figure/type3-font"]

    comp_page = zlib.compress(b"/Type /Page\n")
    reb_recovery_bytes = (
        b"%PDF-1.5\n"
        b"1 0 obj << /Length 100 >>\nstream\n"
        + probe_b_unit * 500
        + b"0123456789\xff\xff\nendstream\nendobj\n"
        b"2 0 obj << /Length 100 >>\nstream\n"
        + adv_stored67_unit * 500
        + b"\nendstream\nendobj\n"
        b"3 0 obj << /Filter /FlateDecode >>\nstream\n"
        + comp_page
        + b"\nendstream\nendobj\n%%EOF\n"
    )
    pages, method = reb_mod.count_pdf_pages(reb_recovery_bytes)
    assert pages == 1
    assert method == "FlateDecode object streams"

    reb_tail_bytes = (
        b"%PDF-1.5\n"
        b"1 0 obj << /Length 100 >>\nstream\n"
        + probe_b_unit * 500
        + b"0123456789\xff\xff\n"
        b"2 0 obj << /Filter /FlateDecode >>\nstream\n"
        + comp_page
        + b"\nendstream\nendobj\n%%EOF\n"
    )
    pages_tail, method_tail = reb_mod.count_pdf_pages(reb_tail_bytes)
    assert pages_tail == 1
    assert method_tail == "FlateDecode object streams"


def test_r7_figure_qa_svg_and_plot_script_linear_time(tmp_path: Path) -> None:
    fig_mod = _load_mod("check_figure_qa_svg_py_r7", FIGURE_QA)

    # 1. Adversarial unclosed HTML comments in SVG (< 0.1s)
    adv_svg = tmp_path / "adv_comments.svg"
    adv_svg.write_text("<!--" * 20000 + '<svg viewBox="0 0 10 10"></svg>', encoding="utf-8")
    t0 = time.perf_counter()
    svg_findings = fig_mod._inspect_svg(adv_svg)
    dt_svg = time.perf_counter() - t0
    assert dt_svg < 0.1, f"_inspect_svg unclosed comments took {dt_svg:.4f}s (>= 0.1s)"
    assert svg_findings == []

    # 2. Adversarial SyntaxError savefig( repeats in plot script (< 0.1s)
    adv_py = tmp_path / "adv_savefig.py"
    adv_py.write_text("savefig(" * 20000 + "\n", encoding="utf-8")
    t0 = time.perf_counter()
    py_findings = fig_mod._inspect_plot_script(adv_py)
    dt_py = time.perf_counter() - t0
    assert dt_py < 0.1, f"_inspect_plot_script savefig( took {dt_py:.4f}s (>= 0.1s)"
    assert py_findings == []

    # 3. Verify SyntaxError fallback still detects nested Path("a.jpg") and rc('pdf', fonttype=3)
    syntax_err_py = tmp_path / "syntax_err_fig.py"
    syntax_err_py.write_text(
        "from pathlib import Path\n"
        "plt.rc('pdf', fonttype=3)\n"
        "plt.savefig(Path('out.jpg'))\n"
        "plt.savefig('out.pdf')\n"
        "if broken syntax (:\n",
        encoding="utf-8",
    )
    err_checks = {f["check"] for f in fig_mod._inspect_plot_script(syntax_err_py)}
    assert {"figure/jpeg-export", "figure/missing-truetype-rcparam"} <= err_checks


def test_r7_rebuttal_text_and_coverage_linear_time() -> None:
    reb_mod = _load_mod("check_rebuttal_text_r7", REBUTTAL)

    # 1. _scan_reviewer_quote_lines with N=8000 R1.1 lines inside quote (< 0.1s)
    quote_text = 'Reviewer comment: "Start\n' + ("R1.1: item\n" * 8000) + '"\nR1.1: Author reply.\n'
    t0 = time.perf_counter()
    stripped, in_quote = reb_mod._scan_reviewer_quote_lines(quote_text)
    dt_quote = time.perf_counter() - t0
    assert dt_quote < 0.1, f"_scan_reviewer_quote_lines N=8000 took {dt_quote:.4f}s (>= 0.1s)"
    assert sum(in_quote) == 8002
    assert "R1.1: Author reply." in stripped

    # 2. _split_clauses on hanging wrapped lines (N=16000) and dot runs (N=30000) (< 0.1s each)
    t0 = time.perf_counter()
    clauses_wrap = reb_mod._split_clauses("word and\n" * 16000)
    dt_wrap = time.perf_counter() - t0
    assert dt_wrap < 0.1, f"_split_clauses wrapped N=16000 took {dt_wrap:.4f}s (>= 0.1s)"
    assert len(clauses_wrap) == 1

    t0 = time.perf_counter()
    clauses_dots = reb_mod._split_clauses("." * 30000 + "x")
    dt_dots = time.perf_counter() - t0
    assert dt_dots < 0.1, f"_split_clauses dots N=30000 took {dt_dots:.4f}s (>= 0.1s)"
    assert len(clauses_dots) == 1

    # 3. _extract_point_ids / _extract_title_point_ids with 1000 short IDs (< 0.1s)
    short_ids = [f"Q{i}" for i in range(1, 1001)]
    sample_body = "Addressing Q1, Q500, and Q1000: see Table 1."
    t0 = time.perf_counter()
    extracted = reb_mod._extract_point_ids(sample_body, short_ids)
    extracted_title = reb_mod._extract_title_point_ids("Response to Q1, Q500 & Q1000", short_ids)
    dt_ids = time.perf_counter() - t0
    assert dt_ids < 0.1, f"point ID extraction with 1000 short IDs took {dt_ids:.4f}s (>= 0.1s)"
    assert extracted == ["Q1", "Q500", "Q1000"]
    assert extracted_title == ["Q1", "Q500", "Q1000"]
    # Custom non-[QWCM]\d+ fallback remains intact
    assert reb_mod._extract_point_ids("Addressing P7", ["P7"]) == ["P7"]


def test_r7_preflight_tex_bibtex_acks_and_etal(tmp_path: Path) -> None:
    sp_mod = _load_mod("check_submission_preflight_r7", PREFLIGHT)

    # 1. _find_tex_cmd unclosed \author{ * 8000 (< 0.1s) + nested brace accuracy
    t0 = time.perf_counter()
    res_unclosed = sp_mod._find_tex_cmd("\\author{" * 8000 + "John", "author")
    dt_tex = time.perf_counter() - t0
    assert dt_tex < 0.1, f"_find_tex_cmd N=8000 took {dt_tex:.4f}s (>= 0.1s)"
    assert res_unclosed == []
    nested_cmds = sp_mod._find_tex_cmd(r"\author{Alice \thanks{MIT}} \author{Bob}", "author")
    assert [arg for _, arg in nested_cmds] == [r"Alice \thanks{MIT}", "Bob"]

    # 2. _parse_bibtex_with_errors with 8000 quoted-brace `", "` tokens (< 0.1s)
    bib_adv = '@article{k1, title = "{a' + '", "' * 8000 + '}b", author={A}, journal={J}, year={2024}}'
    t0 = time.perf_counter()
    entries, errors = sp_mod._parse_bibtex_with_errors(bib_adv)
    dt_bib = time.perf_counter() - t0
    assert dt_bib < 0.1, f"_parse_bibtex_with_errors N=8000 took {dt_bib:.4f}s (>= 0.1s)"
    assert errors == []
    assert len(entries) == 1 and entries[0]["key"] == "k1"

    # 3. Unclosed \begin{acks} * 16000 in scan_anonymization (< 0.1s)
    tex_adv = tmp_path / "adv_acks.tex"
    tex_adv.write_text("\\begin{acks}" * 16000 + "\n\\section{Intro}\nHello.\n", encoding="utf-8")
    t0 = time.perf_counter()
    scan_adv = sp_mod.scan_anonymization(tex_adv)
    dt_acks = time.perf_counter() - t0
    assert dt_acks < 0.1, f"scan_anonymization unclosed acks N=16000 took {dt_acks:.4f}s (>= 0.1s)"
    assert not any(f["check"] == "anonymization/acknowledgments" for f in scan_adv["findings"])

    tex_closed = tmp_path / "closed_acks.tex"
    tex_closed.write_text("\\begin{acks}Supported by NSF.\\end{acks}\n", encoding="utf-8")
    scan_closed = sp_mod.scan_anonymization(tex_closed)
    assert any(f["check"] == "anonymization/acknowledgments" for f in scan_closed["findings"])

    # 4. Dead et\s+al\.? branch fix: author={et al.} must trigger bibtex/placeholder-field
    bib_etal = tmp_path / "etal.bib"
    bib_etal.write_text(
        "@article{k1,\n  title={Good Paper},\n  author={et al.},\n  journal={ICML},\n  year={2024}\n}\n",
        encoding="utf-8",
    )
    r_bib = _run(PREFLIGHT, ["bibtex", str(bib_etal), "--json", "-"])
    assert r_bib.returncode == 1, r_bib.stdout + r_bib.stderr
    bib_checks = [f["check"] for f in json.loads(r_bib.stdout)["findings"]]
    assert "bibtex/placeholder-field" in bib_checks


# ---------------------------------------------------------------------------
# Iteration 8 Regression Tests
# ---------------------------------------------------------------------------


def test_r8_figure_qa_fonttype_redos_and_multi_tail_recovery(tmp_path: Path) -> None:
    fig_mod = _load_mod("check_figure_qa_r8", FIGURE_QA)
    reb_mod = _load_mod("check_rebuttal_r8", REBUTTAL)

    # 1. O(N^2) ReDoS fix for both pdf.fonttype SyntaxError fallback regexes (< 0.1s)
    ws42_py = tmp_path / "fonttype42_ws_50k.py"
    ws42_py.write_text("'pdf.fonttype'" + " " * 50000 + "x\nif broken (:\n", encoding="utf-8")
    t0 = time.perf_counter()
    res42 = fig_mod._inspect_plot_script(ws42_py)
    dt42 = time.perf_counter() - t0
    assert dt42 < 0.1, f"fonttype42 50k whitespace took {dt42:.4f}s (>= 0.1s)"
    assert res42 == []

    ws3_py = tmp_path / "fonttype3_ws_50k.py"
    ws3_py.write_text("pdf.fonttype" + " " * 50000 + "x\nif broken (:\n", encoding="utf-8")
    t0 = time.perf_counter()
    res3 = fig_mod._inspect_plot_script(ws3_py)
    dt3 = time.perf_counter() - t0
    assert dt3 < 0.1, f"fonttype3 50k whitespace took {dt3:.4f}s (>= 0.1s)"
    assert res3 == []

    # Verify SyntaxError fallback still detects rcParams['pdf.fonttype'] = 42 vs 3
    ok42_py = tmp_path / "syntax_err_42.py"
    ok42_py.write_text("plt.rcParams['pdf.fonttype'] = 42\nplt.savefig('a.pdf')\nif broken (:\n", encoding="utf-8")
    assert fig_mod._inspect_plot_script(ok42_py) == []

    bad3_py = tmp_path / "syntax_err_3.py"
    bad3_py.write_text("plt.rcParams['pdf.fonttype'] = 3\nplt.savefig('a.pdf')\nif broken (:\n", encoding="utf-8")
    assert [f["check"] for f in fig_mod._inspect_plot_script(bad3_py)] == ["figure/missing-truetype-rcparam"]

    # 2. Multi-stream _TAIL_STREAM_RE recovery in check_figure_qa.py
    probe_b = b" stream\n\x78\x9c\x00\x0a\x00\xf5\xff" * 500 + b"0123456789\xff\xff\n"

    two_tail_objstm = tmp_path / "two_tail_objstm.pdf"
    two_tail_objstm.write_bytes(
        b"%PDF-1.5\n1 0 obj << /Length 10 >>\nstream\n" + probe_b
        + b"2 0 obj << /Filter /FlateDecode >>\nstream\n" + zlib.compress(b"/Subtype /Type3\n") + b"\n"
        + b"3 0 obj << /Type /ObjStm /Filter /FlateDecode >>\nstream\n" + zlib.compress(b"/MediaBox [0 0 10 10]\n")
        + b"\nendstream\nendobj\n%%EOF\n"
    )
    r_objstm = _run(FIGURE_QA, ["figure", str(two_tail_objstm), "--json", "-"])
    assert r_objstm.returncode == 1, r_objstm.stdout + r_objstm.stderr
    assert [f["check"] for f in json.loads(r_objstm.stdout)["findings"]] == ["figure/type3-font"]

    two_tail_uncomp = tmp_path / "two_tail_uncompressed.pdf"
    two_tail_uncomp.write_bytes(
        b"%PDF-1.5\n1 0 obj << /Length 10 >>\nstream\n" + probe_b
        + b"2 0 obj << /Type /ObjStm /Filter /FlateDecode >>\nstream\n"
        + zlib.compress(b"/Subtype /Type3 /MediaBox [0 0 10 10]\n") + b"\n"
        + b"3 0 obj << /Length 20 >>\nstream\nBT /F1 12 Tf ET"
        + b"\nendstream\nendobj\n%%EOF\n"
    )
    r_uncomp = _run(FIGURE_QA, ["figure", str(two_tail_uncomp), "--json", "-"])
    assert r_uncomp.returncode == 1, r_uncomp.stdout + r_uncomp.stderr
    assert [f["check"] for f in json.loads(r_uncomp.stdout)["findings"]] == ["figure/type3-font"]

    # Adversarial repeated >>\nstream\n inside same endstream stays O(N) (< 0.2s) and still recovers tail streams
    adv_tail_pdf = tmp_path / "adv_tail_4k.pdf"
    adv_tail_pdf.write_bytes(
        b"%PDF-1.5\n1 0 obj << /Length 10 >>\nstream\n"
        + (b">>\nstream\n\x78\x9c\x00\x0a\x00\xf5\xff" * 4000) + b"0123456789\xff\xff\n"
        + b"2 0 obj << /Filter /FlateDecode >>\nstream\n" + zlib.compress(b"/Subtype /Type3\n") + b"\n"
        + b"3 0 obj << /Type /ObjStm /Filter /FlateDecode >>\nstream\n" + zlib.compress(b"/MediaBox [0 0 10 10]\n")
        + b"\nendstream\nendobj\n%%EOF\n"
    )
    t0 = time.perf_counter()
    adv_tail_findings = fig_mod._inspect_pdf_figure(adv_tail_pdf)
    dt_tail = time.perf_counter() - t0
    assert dt_tail < 0.2, f"adv_tail_4k took {dt_tail:.4f}s (>= 0.2s)"
    assert [f["check"] for f in adv_tail_findings] == ["figure/type3-font"]

    # 3. Parity in check_rebuttal.count_pdf_pages multi-tail recovery
    reb_two_tail = (
        b"%PDF-1.5\n1 0 obj << /Length 10 >>\nstream\n" + probe_b
        + b"2 0 obj << /Filter /FlateDecode >>\nstream\n" + zlib.compress(b"/Type /Page\n") + b"\n"
        + b"3 0 obj << /Length 20 >>\nstream\nBT /F1 12 Tf ET\n"
        + b"4 0 obj << /Filter /FlateDecode >>\nstream\n" + zlib.compress(b"/Type /Page\n")
        + b"\nendstream\nendobj\n%%EOF\n"
    )
    t0 = time.perf_counter()
    pages, method = reb_mod.count_pdf_pages(reb_two_tail)
    dt_reb = time.perf_counter() - t0
    assert dt_reb < 0.1, f"reb_two_tail took {dt_reb:.4f}s (>= 0.1s)"
    assert pages == 2
    assert method == "FlateDecode object streams"


def test_r8_preflight_negative_bibtex_lookahead_linear_and_equivalent() -> None:
    import random

    sp_mod = _load_mod("check_submission_preflight_r8", PREFLIGHT)

    # 1. Both adversarial negative-quote BibTeX patterns run in O(N) (< 0.2s)
    bib_unclosed_4k = '@article{k1, title = "{a' + '", "{a' * 4000
    t0 = time.perf_counter()
    entries_u, errors_u = sp_mod._parse_bibtex_with_errors(bib_unclosed_4k)
    dt_u = time.perf_counter() - t0
    assert dt_u < 0.2, f"bib_unclosed_4k took {dt_u:.4f}s (>= 0.2s)"
    assert entries_u == [] and len(errors_u) == 1

    for n_rep in (4000, 8000):
        bib_mf = '@article{k1, title = "{a' + '", a="{a' * n_rep + '"}'
        t0 = time.perf_counter()
        entries_m, errors_m = sp_mod._parse_bibtex_with_errors(bib_mf)
        dt_m = time.perf_counter() - t0
        assert dt_m < 0.2, f"bib_multifield_{n_rep} took {dt_m:.4f}s (>= 0.2s)"
        assert errors_m == [] and len(entries_m) == 1 and entries_m[0]["fields"]["a"] == "{a"

    bib_5k = ('@article{k1, title="{a", a="{a"}\n') * 5000
    t0 = time.perf_counter()
    entries_5k, errors_5k = sp_mod._parse_bibtex_with_errors(bib_5k)
    dt_5k = time.perf_counter() - t0
    assert dt_5k < 0.2, f"bib_5k_entries took {dt_5k:.4f}s (>= 0.2s)"
    assert errors_5k == [] and len(entries_5k) == 5000

    # 2. Differential equivalence vs uncached _has_balanced_closing_quote
    def _uncached_parse(text: str) -> tuple[list[dict[str, object]], list[str]]:
        orig = sp_mod._query_balanced_closing_quote

        def _direct(buf, start, limit, init_depth, terminators, *, stop_at_entry=False, oracle_state=None):
            return sp_mod._has_balanced_closing_quote(
                buf, start, limit, init_depth, terminators, stop_at_entry=stop_at_entry
            )

        sp_mod._query_balanced_closing_quote = _direct
        try:
            return sp_mod._parse_bibtex_with_errors(text)
        finally:
            sp_mod._query_balanced_closing_quote = orig

    tricky_cases = [
        '@article{k1, title = "{a", a = "{a", b = "ok}"}',
        '@article{k1, title = "{a", a = "{a}", b = "ok"}',
        '@article{k1, title = "{a", a = "x}", b = "y"}',
        '@article{k1, title = "{foo \\"bar\\", baz}", author = "Alice"}',
        '@article{k1, title = "{a", a = "{a"} @article{k2, title = "{b}", author = "Bob"}',
        '@article(k1, title = "{a", a = "{a") @article(k2, title = "{b", a = "ok}")',
        '@article{k1, author = foo\\, title = "{a", b = "{a", c = "ok}"}',
        '@article{k1, year = 2024\\\n, title = "{a", b = "{a"}',
        '@article{k1, title = "{{a", a = "}, b = \\"{a", c = "ok}"}',
    ]
    for tc in tricky_cases:
        assert sp_mod._parse_bibtex_with_errors(tc) == _uncached_parse(tc)

    rng = random.Random(42)
    tokens = ['"', "{", "}", "a", ", ", "=", "@article{k, ", "@book(m, ", '\\"', "\\{", "\\}", "\\\\", "(", ")", "\n", "#"]
    for _ in range(250):
        sample = '@article{k1, title = "' + "".join(rng.choice(tokens) for _ in range(rng.randint(5, 50)))
        assert sp_mod._parse_bibtex_with_errors(sample) == _uncached_parse(sample)


# ---------------------------------------------------------------------------
# Iteration 9 Regression Tests
# ---------------------------------------------------------------------------


def test_r9_unclosed_endstream_below_budget_multi_stream_recovery(tmp_path: Path) -> None:
    fig_mod = _load_mod("check_figure_qa_r9", FIGURE_QA)
    reb_mod = _load_mod("check_rebuttal_r9", REBUTTAL)

    zp1 = zlib.compress(b"/Type /Page /Parent 1 0 R\n")
    zp2 = zlib.compress(b"/Type /Page /Parent 2 0 R\n")

    # 1. check_rebuttal: 1 corrupt stream (< budget) + 2 valid FlateDecode /Type /Page streams
    one_corrupt_two_pages = (
        b"%PDF-1.4\n1 0 obj << /Length 10 >>\nstream\nBADHDR\n"
        b"2 0 obj << /Filter /FlateDecode >>\nstream\n" + zp1 + b"\n"
        b"3 0 obj << /Filter /FlateDecode >>\nstream\n" + zp2 + b"\nendstream\nendobj\n%%EOF\n"
    )
    pages_1, method_1 = reb_mod.count_pdf_pages(one_corrupt_two_pages)
    assert pages_1 == 2, f"Expected 2 pages, got {pages_1}"
    assert method_1 == "FlateDecode object streams"

    # 2. check_rebuttal: 1k BADHDR (< 4096 budget) + 2 valid >>\nstream\n /Type /Page streams
    reb_1k_bad_two_tail = (
        b"%PDF-1.5\n1 0 obj << /Length 10 >>\nstream\n" + (b"BADHDR" * 1000) + b"\n"
        b"2 0 obj << /Filter /FlateDecode >>\n>>\nstream\n" + zp1 + b"\n"
        b"3 0 obj << /Filter /FlateDecode >>\n>>\nstream\n" + zp2 + b"\nendstream\nendobj\n%%EOF\n"
    )
    pages_2, method_2 = reb_mod.count_pdf_pages(reb_1k_bad_two_tail)
    assert pages_2 == 2, f"Expected 2 pages, got {pages_2}"
    assert method_2 == "FlateDecode object streams"

    # 3. check_rebuttal: valid FlateDecode stream missing endstream followed by second valid stream
    two_valid_unclosed = (
        b"%PDF-1.4\n1 0 obj << /Filter /FlateDecode >>\nstream\n" + zp1 + b"\n"
        b"2 0 obj << /Filter /FlateDecode >>\nstream\n" + zp2 + b"\nendstream\nendobj\n%%EOF\n"
    )
    pages_3, method_3 = reb_mod.count_pdf_pages(two_valid_unclosed)
    assert pages_3 == 2, f"Expected 2 pages, got {pages_3}"
    assert method_3 == "FlateDecode object streams"

    # 4. check_figure_qa: 1 corrupt stream (< budget) + /Type /ObjStm (/MediaBox) + /Subtype /Type3
    one_corrupt_two_streams = tmp_path / "one_corrupt_two_streams.pdf"
    one_corrupt_two_streams.write_bytes(
        b"%PDF-1.5\n1 0 obj << /Length 10 >>\nstream\nBADHDR\n"
        b"2 0 obj << /Type /ObjStm /Filter /FlateDecode >>\nstream\n"
        + zlib.compress(b"/MediaBox [0 0 100 100]\n")
        + b"\n3 0 obj << /Filter /FlateDecode >>\nstream\n"
        + zlib.compress(b"/Type /Font /Subtype /Type3\n")
        + b"\nendstream\nendobj\n%%EOF\n"
    )
    fig_findings = fig_mod._inspect_pdf_figure(one_corrupt_two_streams)
    assert [f["check"] for f in fig_findings] == ["figure/type3-font"]
    r_fig = _run(FIGURE_QA, ["figure", str(one_corrupt_two_streams), "--json", "-"])
    assert r_fig.returncode == 1, r_fig.stdout + r_fig.stderr
    assert [f["check"] for f in json.loads(r_fig.stdout)["findings"]] == ["figure/type3-font"]

    # Lookback isolation: ObjStm on stream 2 must NOT bleed into stream 3 when stream 3 lacks /Type /ObjStm
    lookback_iso = tmp_path / "lookback_isolation.pdf"
    lookback_iso.write_bytes(
        b"%PDF-1.5\n1 0 obj << /Length 10 >>\nstream\nBADHDR\n"
        b"2 0 obj << /Type /ObjStm /Filter /FlateDecode >>\nstream\n"
        + zlib.compress(b"/Contents 9 0 R\n")
        + b"\n<< /Filter /FlateDecode >>\nstream\n"
        + zlib.compress(b"/MediaBox [0 0 100 100]\n")
        + b"\nendstream\nendobj\n%%EOF\n"
    )
    assert [f["check"] for f in fig_mod._inspect_pdf_figure(lookback_iso)] == ["figure/missing-bbox"]

    # False stream\n in /ObjStm dict string before valid stream + second valid Type3 stream
    dict_str_multi = tmp_path / "dict_str_multi.pdf"
    dict_str_multi.write_bytes(
        b"%PDF-1.5\n"
        b"1 0 obj << /Type /ObjStm /Subject (Down stream\nNote) /Filter /FlateDecode >>\nstream\n"
        + zlib.compress(b"/MediaBox [0 0 100 100]\n")
        + b"\n2 0 obj << /Filter /FlateDecode >>\nstream\n"
        + zlib.compress(b"/Subtype /Type3\n")
        + b"\nendstream\nendobj\n%%EOF\n"
    )
    assert [f["check"] for f in fig_mod._inspect_pdf_figure(dict_str_multi)] == ["figure/type3-font"]

    # 5. Adversarial O(N) scaling inside one unclosed span: alternating corrupt + tiny valid FlateDecode
    tiny_valid = zlib.compress(b"x")
    alt_bad_valid = (
        b"%PDF-1.5\n1 0 obj << /Length 10 >>\nstream\n"
        + (b"stream\n" + b"BADHDR" * 200 + b"\nstream\n" + tiny_valid + b"\n") * 2000
        + b"endstream\n%%EOF\n"
    )
    t0 = time.perf_counter()
    fig_meta_alt = fig_mod._inflate_pdf_streams_meta(alt_bad_valid)
    dt_fig_alt = time.perf_counter() - t0
    assert dt_fig_alt < 0.2, f"check_figure_qa alt_bad_valid took {dt_fig_alt:.4f}s (>= 0.2s)"
    assert len(fig_meta_alt) == 2000

    t0 = time.perf_counter()
    with pytest.raises(ValueError, match="Could not determine a positive PDF page count"):
        reb_mod.count_pdf_pages(alt_bad_valid)
    dt_reb_alt = time.perf_counter() - t0
    assert dt_reb_alt < 0.2, f"check_rebuttal alt_bad_valid took {dt_reb_alt:.4f}s (>= 0.2s)"

    # Probe B interleaved with tiny valid streams must still trigger monotonic budget -> _TAIL_STREAM_RE in O(N)
    probe_b_unit = b" stream\n\x78\x9c\x00\x0a\x00\xf5\xff"
    alt_probeb_valid = (
        b"%PDF-1.5\n1 0 obj << /Filter /FlateDecode >>\nstream\n" + zp1 + b"\n"
        + (probe_b_unit + b" stream\n" + tiny_valid) * 2000
        + b"0123456789\xff\xff\n2 0 obj << /Filter /FlateDecode >>\nstream\n" + zp2
        + b"\nendstream\nendobj\n%%EOF\n"
    )
    t0 = time.perf_counter()
    pages_pb, _ = reb_mod.count_pdf_pages(alt_probeb_valid)
    dt_pb_alt = time.perf_counter() - t0
    assert dt_pb_alt < 0.2, f"check_rebuttal alt_probeb_valid took {dt_pb_alt:.4f}s (>= 0.2s)"
    assert pages_pb == 2

    t0 = time.perf_counter()
    fig_meta_pb = fig_mod._inflate_pdf_streams_meta(alt_probeb_valid)
    dt_fig_pb = time.perf_counter() - t0
    assert dt_fig_pb < 0.2, f"check_figure_qa alt_probeb_valid took {dt_fig_pb:.4f}s (>= 0.2s)"
    assert any(zp2_tok in buf for _, buf in fig_meta_pb for zp2_tok in (b"/Parent 2 0 R",))


# ---------------------------------------------------------------------------
# Iteration 10 Regression Tests
# ---------------------------------------------------------------------------


def test_r10_tail_stream_lookback_dict_isolation_and_bleed(tmp_path: Path) -> None:
    fig_mod = _load_mod("check_figure_qa_r10", FIGURE_QA)
    z_mb = zlib.compress(b"/MediaBox [0 0 100 100]\n")
    z_other = zlib.compress(b"/Contents 1 0 R\n")
    z_empty = zlib.compress(b"")
    z_type3 = zlib.compress(b"/Type /Font /Subtype /Type3\n")
    probe_b_unit = b" stream\n\x78\x9c\x00\x0a\x00\xf5\xff" + b"0123456789\xff\xff"

    # 1. tail_dict_bug: false >>\nstream\n inside /ObjStm dict string must NOT advance last_stream_end
    tail_dict_pdf = tmp_path / "tail_dict_bug.pdf"
    tail_dict_pdf.write_bytes(
        b"%PDF-1.5\n1 0 obj << /Length 10 >>\nstream\n"
        + (probe_b_unit * 400)
        + b"\n2 0 obj << /Type /ObjStm /Subject (Down >>\nstream\nNote) /Filter /FlateDecode >>\nstream\n"
        + z_mb
        + b"\nendstream\nendobj\n%%EOF\n"
    )
    meta_dict = fig_mod._inflate_pdf_streams_meta(tail_dict_pdf.read_bytes())
    assert meta_dict == [(True, b"/MediaBox [0 0 100 100]\n")]
    assert fig_mod._inspect_pdf_figure(tail_dict_pdf) == []
    r_strict = _run(FIGURE_QA, ["figure", str(tail_dict_pdf), "--strict", "--compact"])
    assert r_strict.returncode == 0, r_strict.stdout + r_strict.stderr

    # False >>\nstream\n in PDF comment or 0-byte >>\nstream\n>>\nstream\n in dict string
    tail_comment_pdf = tmp_path / "tail_dict_comment.pdf"
    tail_comment_pdf.write_bytes(
        b"%PDF-1.5\n1 0 obj << /Length 10 >>\nstream\n"
        + (probe_b_unit * 400)
        + b"\n2 0 obj << /Type /ObjStm % >>\nstream\nignored comment\n/Filter /FlateDecode >>\nstream\n"
        + z_mb
        + b"\nendstream\nendobj\n%%EOF\n"
    )
    assert fig_mod._inspect_pdf_figure(tail_comment_pdf) == []

    tail_zero_gap_pdf = tmp_path / "tail_dict_zero_gap.pdf"
    tail_zero_gap_pdf.write_bytes(
        b"%PDF-1.5\n1 0 obj << /Length 10 >>\nstream\n"
        + (probe_b_unit * 400)
        + b"\n2 0 obj << /Type /ObjStm /Subject (>>\nstream\n>>\nstream\n) /Filter /FlateDecode >>\nstream\n"
        + z_mb
        + b"\nendstream\nendobj\n%%EOF\n"
    )
    assert fig_mod._inspect_pdf_figure(tail_zero_gap_pdf) == []

    # 2. tail_bleed: valid stream 1 /Type /ObjStm must STILL NOT bleed into stream 2 non-ObjStm /MediaBox
    tail_bleed_pdf = tmp_path / "tail_bleed.pdf"
    tail_bleed_pdf.write_bytes(
        b"%PDF-1.5\n1 0 obj << /Length 10 >>\nstream\n"
        + (probe_b_unit * 400)
        + b"\n2 0 obj << /Type /ObjStm /Filter /FlateDecode >>\nstream\n"
        + z_other
        + b"\n<< /Filter /FlateDecode >>\nstream\n"
        + z_mb
        + b"\nendstream\nendobj\n%%EOF\n"
    )
    meta_bleed = fig_mod._inflate_pdf_streams_meta(tail_bleed_pdf.read_bytes())
    assert meta_bleed == [(True, b"/Contents 1 0 R\n"), (False, b"/MediaBox [0 0 100 100]\n")]
    assert [f["check"] for f in fig_mod._inspect_pdf_figure(tail_bleed_pdf)] == ["figure/missing-bbox"]

    # Empty valid zlib stream in stream 1 /ObjStm must also isolate stream 2
    tail_bleed_empty_pdf = tmp_path / "tail_bleed_empty.pdf"
    tail_bleed_empty_pdf.write_bytes(
        b"%PDF-1.5\n1 0 obj << /Length 10 >>\nstream\n"
        + (probe_b_unit * 400)
        + b"\n2 0 obj << /Type /ObjStm /Filter /FlateDecode >>\nstream\n"
        + z_empty
        + b"\n<< /Filter /FlateDecode >>\nstream\n"
        + z_mb
        + b"\nendstream\nendobj\n%%EOF\n"
    )
    assert [f["check"] for f in fig_mod._inspect_pdf_figure(tail_bleed_empty_pdf)] == ["figure/missing-bbox"]

    # 3. corrupt_then_valid_then_budget_exceeded_then_tail
    mixed_tail_pdf = tmp_path / "corrupt_valid_budget_tail.pdf"
    mixed_tail_pdf.write_bytes(
        b"%PDF-1.5\n1 0 obj << /Length 10 >>\nstream\nBADHDR\n"
        + b"2 0 obj << /Type /ObjStm /Filter /FlateDecode >>\nstream\n"
        + z_mb
        + b"\n3 0 obj << /Length 10 >>\nstream\n"
        + (probe_b_unit * 400)
        + b"\nstream\nignored\n"
        + b"4 0 obj << /Filter /FlateDecode >>\nstream\n"
        + z_type3
        + b"\nendstream\nendobj\n%%EOF\n"
    )
    meta_mixed = fig_mod._inflate_pdf_streams_meta(mixed_tail_pdf.read_bytes())
    assert len(meta_mixed) == 2
    assert [f["check"] for f in fig_mod._inspect_pdf_figure(mixed_tail_pdf)] == ["figure/type3-font"]
