"""Opaque-box E2E tests for Feature F18: Concise Plain-Language Multilingual
LaTeX-to-PDF User Report (`research-scientist/scripts/report_latex_pdf.py`).

Covers:
- Tier 1 (`T1-H1`..`T1-H6`, 6 tests): Core CLI, EN/VI auto-detection, explicit
  `--lang vi --tex-out`, plain-language executive structure, rejection of
  bloated/jargon prose, and rejection of sycophancy/ungrounded claims.
- Tier 2 (`T2-H1`..`T2-H6`, 6 tests): Full Vietnamese diacritics stress test,
  LaTeX special character escaping, mixed-language technical IDs, bilingual
  bloated/jargon rejection, missing/malformed input handling, and bilingual
  sycophancy/fabricated metric rejection.
- Tier 3 (`T3-11`, `T3-12`, 2 tests): Cross-feature chains from gap/engineering
  diagnostics and venue/manuscript novelty evaluations to compiled reports.

Self-contained by design (no imports from `helpers.py` or `real_cases_runner.py`).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any

import fitz

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "research-scientist" / "scripts" / "report_latex_pdf.py"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "f18"

SYCOPHANCY_BANNED_PHRASES = (
    "brilliant idea",
    "groundbreaking",
    "paradigm shift",
    "revolutionary",
    "great job",
    "spot-on",
    "i hope this helps",
    "virtually guaranteed acceptance",
    "chúc mừng thành công",
)

ENGLISH_BOILERPLATE_HEADINGS = (
    "executive summary",
    "flaws and risks",
    "next steps",
    "key evidence",
)


def _run_report_cli(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    assert SCRIPT_PATH.is_file(), (
        f"Feature F18 script not implemented yet at {SCRIPT_PATH} "
        "(expected by PROJECT.md Interface Contracts #5)"
    )
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    cmd = [sys.executable, str(SCRIPT_PATH), *[str(a) for a in args]]
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _parse_json_receipt(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    for stream in (proc.stdout, proc.stderr):
        text = (stream or "").strip()
        if not text:
            continue
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except ValueError:
            pass
    raise AssertionError(
        f"Expected JSON dict receipt in CLI output.\n"
        f"returncode={proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )


def _extract_pdf_text_nfc(pdf_path: Path) -> tuple[int, str]:
    assert pdf_path.is_file(), f"Expected PDF file at {pdf_path}"
    assert pdf_path.stat().st_size > 256, f"PDF file is suspiciously small/empty: {pdf_path}"
    with fitz.open(str(pdf_path)) as doc:
        page_count = len(doc)
        assert page_count >= 1, f"Compiled PDF has 0 pages: {pdf_path}"
        pages_text = [page.get_text("text") for page in doc]
    combined = "\n".join(pages_text)
    normalized = unicodedata.normalize("NFC", combined)
    collapsed = re.sub(r"\s+", " ", normalized).strip()
    assert collapsed, f"Compiled PDF yielded empty extracted text: {pdf_path}"
    return page_count, collapsed


def _assert_no_broken_unicode(text: str) -> None:
    assert "\ufffd" not in text, "Extracted PDF text contains Unicode replacement char U+FFFD"
    assert "???" not in text, "Extracted PDF text contains '???' substitution placeholder"


def _pdf_contains(pdf_text: str, token: str) -> bool:
    """Match token in extracted PDF text, tolerating pdflatex T5 glyph-kerning space drops."""
    if token in pdf_text:
        return True
    return re.sub(r"\s+", "", token) in re.sub(r"\s+", "", pdf_text)


# ---------------------------------------------------------------------------
# Tier 1: Core Category-Partition E2E Tests (T1-H1 .. T1-H6)
# ---------------------------------------------------------------------------


def test_t1_h1_help_and_english_report_pdf_receipt(tmp_path: Path) -> None:
    """T1-H1: --help and valid English structured report produce valid PDF + JSON receipt."""
    help_proc = _run_report_cli(["--help"])
    assert help_proc.returncode == 0, help_proc.stdout + help_proc.stderr
    help_text = (help_proc.stdout + help_proc.stderr).lower()
    for flag in ("--input", "--out", "--tex-out", "--lang", "--input-text", "--strict", "--json"):
        assert flag in help_text, f"--help output missing documented flag {flag}"

    fixture_json = FIXTURES_DIR / "en_clean_report.json"
    prompt_text = (FIXTURES_DIR / "en_prompt.txt").read_text(encoding="utf-8").strip()
    out_pdf = tmp_path / "report_en.pdf"
    out_tex = tmp_path / "report_en.tex"

    proc = _run_report_cli(
        [
            "--input", str(fixture_json),
            "--out", str(out_pdf),
            "--tex-out", str(out_tex),
            "--lang", "auto",
            "--input-text", prompt_text,
            "--strict",
            "--json",
        ]
    )
    assert proc.returncode == 0, f"Unexpected failure:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    receipt = _parse_json_receipt(proc)

    for key in ("pdf_path", "tex_path", "lang", "engine", "page_count", "lint_findings", "diacritics_verified"):
        assert key in receipt, f"JSON receipt missing required key {key!r}: {receipt}"

    assert receipt["lang"] == "en"
    assert isinstance(receipt["engine"], str) and receipt["engine"].strip()
    assert any(eng in receipt["engine"].lower() for eng in ("xelatex", "lualatex", "pdflatex"))
    assert isinstance(receipt["page_count"], int) and receipt["page_count"] >= 1
    assert receipt["lint_findings"] == []
    assert isinstance(receipt["diacritics_verified"], bool)
    assert Path(receipt["pdf_path"]).resolve() == out_pdf.resolve()
    assert Path(receipt["tex_path"]).resolve() == out_tex.resolve()
    assert out_tex.is_file() and out_tex.stat().st_size > 100

    page_count, pdf_text = _extract_pdf_text_nfc(out_pdf)
    assert page_count == receipt["page_count"]
    _assert_no_broken_unicode(pdf_text)
    for token in ("REJECT GAP", "0.311", "0.314", "124", "arXiv:1907.06902"):
        assert token in pdf_text, f"Expected token {token!r} missing from extracted PDF text"


def test_t1_h2_vietnamese_auto_detect_localization_and_diacritics(tmp_path: Path) -> None:
    """T1-H2: Vietnamese input auto-detects lang=='vi', localizes headings, preserves diacritics."""
    fixture_json = FIXTURES_DIR / "vi_clean_report.json"
    prompt_text = (FIXTURES_DIR / "vi_prompt.txt").read_text(encoding="utf-8").strip()
    out_pdf = tmp_path / "report_vi.pdf"

    proc = _run_report_cli(
        [
            "--input", str(fixture_json),
            "--out", str(out_pdf),
            "--lang", "auto",
            "--input-text", prompt_text,
            "--strict",
            "--json",
        ]
    )
    assert proc.returncode == 0, f"Unexpected failure:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    receipt = _parse_json_receipt(proc)

    assert receipt["lang"] == "vi"
    assert receipt["diacritics_verified"] is True
    assert receipt["lint_findings"] == []
    assert isinstance(receipt["page_count"], int) and receipt["page_count"] >= 1

    _, pdf_text = _extract_pdf_text_nfc(out_pdf)
    _assert_no_broken_unicode(pdf_text)
    lowered = pdf_text.lower()
    for unlocalized in ENGLISH_BOILERPLATE_HEADINGS:
        assert unlocalized not in lowered, (
            f"Vietnamese report left English boilerplate heading {unlocalized!r} unlocalized"
        )
    for expected_vi in (
        "LOẠI BỎ LỖ HỔNG",
        "tiền xử lý",
        "trùng lặp",
        "hạt giống",
        "0.308",
        "0.315",
        "38.5%",
    ):
        assert _pdf_contains(pdf_text, expected_vi), (
            f"Vietnamese phrase/value {expected_vi!r} missing or corrupted in PDF"
        )


def test_t1_h3_explicit_lang_vi_tex_out_compilable_and_preserves_numbers(tmp_path: Path) -> None:
    """T1-H3: Explicit --lang vi --tex-out produces compilable .tex + PDF preserving exact evidence."""
    fixture_json = FIXTURES_DIR / "vi_clean_report.json"
    out_pdf = tmp_path / "explicit_vi.pdf"
    out_tex = tmp_path / "explicit_vi.tex"

    proc = _run_report_cli(
        [
            "--input", str(fixture_json),
            "--out", str(out_pdf),
            "--tex-out", str(out_tex),
            "--lang", "vi",
            "--strict",
            "--json",
        ]
    )
    assert proc.returncode == 0, f"Unexpected failure:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    receipt = _parse_json_receipt(proc)
    assert receipt["lang"] == "vi"
    assert receipt["diacritics_verified"] is True
    assert out_tex.is_file()

    tex_src = unicodedata.normalize("NFC", out_tex.read_text(encoding="utf-8"))
    tex_unbroken = tex_src.replace(r"\allowbreak{}", "")
    assert "\\documentclass" in tex_src and "\\end{document}" in tex_src
    for token in ("0.308", "0.412", "0.315", "38.5", "arXiv:1907.06902"):
        assert token in tex_unbroken, f"Expected evidence token {token!r} missing from generated .tex"

    engine_bin = shutil.which(receipt["engine"]) or shutil.which("lualatex") or shutil.which("pdflatex")
    assert engine_bin is not None, f"LaTeX engine {receipt['engine']!r} not found in PATH"
    recompile_dir = tmp_path / "recompile"
    recompile_dir.mkdir()
    recompile_tex = recompile_dir / "check.tex"
    recompile_tex.write_text(out_tex.read_text(encoding="utf-8"), encoding="utf-8")
    tex_proc = subprocess.run(
        [engine_bin, "-interaction=nonstopmode", "-halt-on-error", recompile_tex.name],
        cwd=str(recompile_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    assert tex_proc.returncode == 0, (
        f"Generated .tex failed independent {engine_bin} compilation:\n"
        f"{tex_proc.stdout}\n{tex_proc.stderr}"
    )
    assert (recompile_dir / "check.pdf").is_file()

    _, pdf_text = _extract_pdf_text_nfc(out_pdf)
    _assert_no_broken_unicode(pdf_text)
    for token in ("0.308", "0.412", "0.315", "38.5%", "1,250"):
        assert token in pdf_text, f"Expected number {token!r} missing from compiled PDF"


def test_t1_h4_crisp_plain_language_executive_structure_passes_strict(tmp_path: Path) -> None:
    """T1-H4: Crisp plain-language executive structure (verdict first) passes --strict."""
    fixture_json = FIXTURES_DIR / "en_clean_report.json"
    out_pdf = tmp_path / "exec_en.pdf"
    out_tex = tmp_path / "exec_en.tex"

    proc = _run_report_cli(
        [
            "--input", str(fixture_json),
            "--out", str(out_pdf),
            "--tex-out", str(out_tex),
            "--lang", "en",
            "--strict",
            "--json",
        ]
    )
    assert proc.returncode == 0, f"Clean plain-language report rejected by --strict: {proc.stdout}\n{proc.stderr}"
    receipt = _parse_json_receipt(proc)
    assert receipt["lint_findings"] == []

    _, pdf_text = _extract_pdf_text_nfc(out_pdf)
    verdict_idx = pdf_text.find("REJECT GAP")
    next_steps_idx = pdf_text.find("Move feature scaling")
    assert verdict_idx != -1, "Direct verdict missing from executive report PDF"
    assert next_steps_idx != -1, "Next steps missing from executive report PDF"
    assert verdict_idx < next_steps_idx, "Executive report must present direct verdict before next steps"


def test_t1_h5_rejects_bloated_prose_filler_jargon_strict(tmp_path: Path) -> None:
    """T1-H5: Rejects bloated prose, filler, obscure jargon, and convoluted phrasing under --strict."""
    fixture_json = FIXTURES_DIR / "neg_bloated_jargon_en.json"
    out_pdf = tmp_path / "bloated_en.pdf"

    proc = _run_report_cli(
        [
            "--input", str(fixture_json),
            "--out", str(out_pdf),
            "--lang", "en",
            "--strict",
            "--json",
        ]
    )
    assert proc.returncode == 1, (
        f"Expected exit 1 on bloated/jargon prose under --strict, got {proc.returncode}: {proc.stdout}"
    )
    receipt = _parse_json_receipt(proc)
    findings = receipt.get("lint_findings")
    assert isinstance(findings, list) and len(findings) >= 1
    categories = {f.get("category") for f in findings}
    pattern_ids = {str(f.get("pattern_id", "")) for f in findings}
    assert "MISSING_EVIDENCE_LOCATOR" not in pattern_ids, (
        f"Negative style control masked by MISSING_EVIDENCE_LOCATOR: {findings}"
    )
    assert "plain_language" in categories, f"Expected plain_language finding, got: {findings}"
    assert "conciseness" in categories, f"Expected conciseness finding, got: {findings}"
    assert any(
        pid.startswith(("JARGON", "FILLER", "SENTENCE")) for pid in pattern_ids
    ), f"Expected jargon/filler/bloat pattern_id, got: {findings}"
    assert not out_pdf.exists(), "Failed --strict gate must not emit a compiled PDF"


def test_t1_h6_rejects_sycophancy_and_ungrounded_claims_strict(tmp_path: Path) -> None:
    """T1-H6: Rejects sycophancy/flattery and ungrounded/fabricated claims under --strict."""
    fixture_json = FIXTURES_DIR / "neg_sycophancy_ungrounded.json"
    out_pdf = tmp_path / "sycophancy_en.pdf"

    proc = _run_report_cli(
        [
            "--input", str(fixture_json),
            "--out", str(out_pdf),
            "--lang", "en",
            "--strict",
            "--json",
        ]
    )
    assert proc.returncode == 1, (
        f"Expected exit 1 on sycophancy/ungrounded claims under --strict, got {proc.returncode}: {proc.stdout}"
    )
    receipt = _parse_json_receipt(proc)
    findings = receipt.get("lint_findings")
    assert isinstance(findings, list) and len(findings) >= 1
    pattern_ids = {str(f.get("pattern_id", "")) for f in findings}
    assert "MISSING_EVIDENCE_LOCATOR" not in pattern_ids, (
        f"Negative sycophancy control masked by MISSING_EVIDENCE_LOCATOR: {findings}"
    )
    assert any(
        f.get("category") == "sycophancy" or str(f.get("pattern_id", "")).startswith("SYC_")
        for f in findings
    ), f"Expected sycophancy / SYC_* finding, got: {findings}"
    assert any(
        f.get("category") == "integrity" and f.get("pattern_id") == "UNGROUNDED_NUMERIC_CLAIM"
        for f in findings
    ), f"Expected integrity/UNGROUNDED_NUMERIC_CLAIM finding, got: {findings}"
    assert not out_pdf.exists(), "Failed --strict gate must not emit a compiled PDF"


# ---------------------------------------------------------------------------
# Tier 2: Corner Cases & Adversarial Negative Controls (T2-H1 .. T2-H6)
# ---------------------------------------------------------------------------


def test_t2_h1_full_vietnamese_diacritics_stress_test_intact_in_fitz(tmp_path: Path) -> None:
    """T2-H1: Full Vietnamese diacritics (đ/Đ, ă/â/ê/ô/ơ/ư, all 6 tones) verified intact in fitz."""
    fixture_json = FIXTURES_DIR / "vi_diacritics_stress.json"
    out_pdf = tmp_path / "vi_stress.pdf"
    out_tex = tmp_path / "vi_stress.tex"

    proc = _run_report_cli(
        [
            "--input", str(fixture_json),
            "--out", str(out_pdf),
            "--tex-out", str(out_tex),
            "--lang", "vi",
            "--strict",
            "--json",
        ]
    )
    assert proc.returncode == 0, f"Unexpected failure:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    receipt = _parse_json_receipt(proc)
    assert receipt["lang"] == "vi"
    assert receipt["diacritics_verified"] is True

    _, pdf_text = _extract_pdf_text_nfc(out_pdf)
    _assert_no_broken_unicode(pdf_text)

    required_tokens = (
        "Đánh giá độc lập",
        "băng", "bằng", "bắng", "bẳng", "bẵng", "bặng",
        "Ăn năn", "Ấm áp", "Ếch ộp", "Ổn định", "Ờ hờ", "Ứng xử",
        "Đổi mới", "Đi đầu", "Đại học", "Đường dẫn",
        "Mẫu thử", "Lỗi kỹ thuật", "Rủi ro rò rỉ", "Mở rộng vừa đủ",
        "0.842", "2.4%", "640",
    )
    for token in required_tokens:
        assert _pdf_contains(pdf_text, token), (
            f"Vietnamese diacritic stress token {token!r} missing/corrupted in PDF"
        )


def test_t2_h2_latex_special_chars_escape_cleanly_without_truncation(tmp_path: Path) -> None:
    """T2-H2: LaTeX special chars (%, &, _, $, #, {, }) inside findings/URLs compile cleanly."""
    fixture_json = FIXTURES_DIR / "latex_special_chars.json"
    out_pdf = tmp_path / "special_chars.pdf"
    out_tex = tmp_path / "special_chars.tex"

    proc = _run_report_cli(
        [
            "--input", str(fixture_json),
            "--out", str(out_pdf),
            "--tex-out", str(out_tex),
            "--lang", "en",
            "--strict",
            "--json",
        ]
    )
    assert proc.returncode == 0, f"LaTeX special char escaping failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    receipt = _parse_json_receipt(proc)
    assert receipt["page_count"] >= 1

    _, pdf_text = _extract_pdf_text_nfc(out_pdf)
    _assert_no_broken_unicode(pdf_text)
    for token in (
        "+3.4%",
        "Kapoor & Narayanan",
        "split_leakage_rate",
        "test_auc_roc",
        "$750",
        "#42",
        "seed=42",
        "lr=1e-3",
        "example.org",
        "main_track",
    ):
        assert _pdf_contains(pdf_text, token), (
            f"Special-character token {token!r} missing or truncated in compiled PDF"
        )


def test_t2_h3_mixed_language_vi_prompt_with_english_tech_ids(tmp_path: Path) -> None:
    """T2-H3: Mixed VI prompt + EN tech IDs adapts to lang=='vi' while keeping tech IDs verbatim."""
    fixture_json = FIXTURES_DIR / "mixed_vi_en_tech.json"
    prompt_text = (FIXTURES_DIR / "mixed_vi_prompt.txt").read_text(encoding="utf-8").strip()
    out_pdf = tmp_path / "mixed_vi.pdf"

    proc = _run_report_cli(
        [
            "--input", str(fixture_json),
            "--out", str(out_pdf),
            "--lang", "auto",
            "--input-text", prompt_text,
            "--strict",
            "--json",
        ]
    )
    assert proc.returncode == 0, f"Unexpected failure:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    receipt = _parse_json_receipt(proc)
    assert receipt["lang"] == "vi"
    assert receipt["diacritics_verified"] is True

    _, pdf_text = _extract_pdf_text_nfc(out_pdf)
    _assert_no_broken_unicode(pdf_text)
    for token in ("KHÔNG ĐẠT", "tinh chỉnh", "tiền lệ", "NDCG@10", "ItemKNN", "arXiv:1609.02907", "0.314", "0.298"):
        assert token in pdf_text, f"Mixed-language token {token!r} missing or altered in PDF"


def test_t2_h4_bilingual_obscure_jargon_and_bloated_sentences_rejected_strict(tmp_path: Path) -> None:
    """T2-H4: Obscure academic jargon + multi-clause bloated prose (EN + VI) rejected by --strict."""
    fixture_json = FIXTURES_DIR / "neg_bloated_jargon_bilingual.json"
    out_pdf = tmp_path / "bloated_bilingual.pdf"

    proc = _run_report_cli(
        [
            "--input", str(fixture_json),
            "--out", str(out_pdf),
            "--lang", "auto",
            "--strict",
            "--json",
        ]
    )
    assert proc.returncode == 1, (
        f"Expected exit 1 on bilingual jargon/bloated prose under --strict, got {proc.returncode}: {proc.stdout}"
    )
    receipt = _parse_json_receipt(proc)
    findings = receipt.get("lint_findings")
    assert isinstance(findings, list) and len(findings) >= 1
    categories = {f.get("category") for f in findings}
    pattern_ids = {str(f.get("pattern_id", "")) for f in findings}
    assert "MISSING_EVIDENCE_LOCATOR" not in pattern_ids, (
        f"Negative bilingual style control masked by MISSING_EVIDENCE_LOCATOR: {findings}"
    )
    assert "plain_language" in categories, f"Expected plain_language finding, got: {findings}"
    assert "conciseness" in categories, f"Expected conciseness finding, got: {findings}"
    assert not out_pdf.exists(), "Failed --strict gate must not emit a compiled PDF"


def test_t2_h5_missing_or_malformed_input_exits_nonzero_without_half_written_pdf(tmp_path: Path) -> None:
    """T2-H5: Missing/malformed/invalid --input JSON exits non-zero (1 or 2) without half-written PDF."""
    missing_pdf = tmp_path / "missing.pdf"
    proc_missing = _run_report_cli(
        ["--input", str(tmp_path / "does_not_exist.json"), "--out", str(missing_pdf), "--json"]
    )
    assert proc_missing.returncode in (1, 2)
    assert not missing_pdf.exists(), "Missing input must not leave a PDF artifact"
    missing_receipt = _parse_json_receipt(proc_missing)
    err_missing = missing_receipt.get("error")
    assert isinstance(err_missing, str) and err_missing.strip(), (
        f"Missing input must emit non-empty JSON 'error': {missing_receipt!r}"
    )
    assert "not found" in err_missing.lower(), f"Unexpected missing-file error: {err_missing!r}"

    bad_json = tmp_path / "malformed.json"
    bad_json.write_text('{"verdict": [unterminated', encoding="utf-8")
    malformed_pdf = tmp_path / "malformed.pdf"
    proc_malformed = _run_report_cli(
        ["--input", str(bad_json), "--out", str(malformed_pdf), "--json"]
    )
    assert proc_malformed.returncode in (1, 2)
    assert not malformed_pdf.exists(), "Malformed JSON must not leave a half-written PDF"
    malformed_receipt = _parse_json_receipt(proc_malformed)
    err_malformed = malformed_receipt.get("error")
    assert isinstance(err_malformed, str) and err_malformed.strip(), (
        f"Malformed JSON must emit non-empty JSON 'error': {malformed_receipt!r}"
    )
    assert any(tok in err_malformed.lower() for tok in ("expecting", "line", "json", "decode")), (
        f"Unexpected malformed-JSON diagnostic: {err_malformed!r}"
    )

    empty_json = tmp_path / "empty.json"
    empty_json.write_text("{}", encoding="utf-8")
    empty_pdf = tmp_path / "empty.pdf"
    proc_empty = _run_report_cli(
        ["--input", str(empty_json), "--out", str(empty_pdf), "--json"]
    )
    assert proc_empty.returncode in (1, 2)
    assert not empty_pdf.exists(), "Empty JSON object must not emit a PDF"
    empty_receipt = _parse_json_receipt(proc_empty)
    err_empty = empty_receipt.get("error")
    assert isinstance(err_empty, str) and err_empty.strip(), (
        f"Empty JSON object must emit non-empty JSON 'error': {empty_receipt!r}"
    )
    assert any(tok in err_empty.lower() for tok in ("non-empty", "empty")), (
        f"Unexpected empty-JSON diagnostic: {err_empty!r}"
    )


def test_t2_h6_bilingual_sycophancy_and_fabricated_metric_rejected_strict(tmp_path: Path) -> None:
    """T2-H6: Sycophancy + fabricated/unverified metric in VI/EN rejected by --strict."""
    fixture_json = FIXTURES_DIR / "neg_sycophancy_fabricated_bilingual.json"
    out_pdf = tmp_path / "sycophancy_bilingual.pdf"

    proc = _run_report_cli(
        [
            "--input", str(fixture_json),
            "--out", str(out_pdf),
            "--lang", "auto",
            "--strict",
            "--json",
        ]
    )
    assert proc.returncode == 1, (
        f"Expected exit 1 on bilingual sycophancy/fabricated metric under --strict, got {proc.returncode}: {proc.stdout}"
    )
    receipt = _parse_json_receipt(proc)
    findings = receipt.get("lint_findings")
    assert isinstance(findings, list) and len(findings) >= 1
    pattern_ids = {str(f.get("pattern_id", "")) for f in findings}
    assert "MISSING_EVIDENCE_LOCATOR" not in pattern_ids, (
        f"Negative bilingual sycophancy control masked by MISSING_EVIDENCE_LOCATOR: {findings}"
    )
    assert any(
        f.get("category") == "sycophancy" or str(f.get("pattern_id", "")).startswith("SYC_")
        for f in findings
    ), f"Expected sycophancy / SYC_* finding on Vietnamese flattery, got: {findings}"
    assert any(
        f.get("category") == "integrity" and f.get("pattern_id") == "UNGROUNDED_NUMERIC_CLAIM"
        for f in findings
    ), f"Expected integrity/UNGROUNDED_NUMERIC_CLAIM finding, got: {findings}"
    assert not out_pdf.exists(), "Failed --strict gate must not emit a compiled PDF"


# ---------------------------------------------------------------------------
# Tier 3: Cross-Feature Chains (T3-11, T3-12)
# ---------------------------------------------------------------------------


def test_t3_11_chain_gap_engineering_verdict_to_vietnamese_pdf(tmp_path: Path) -> None:
    """T3-11: Gap/engineering verdict JSON -> report_latex_pdf.py --lang auto --strict --json (VI)."""
    fixture_json = FIXTURES_DIR / "t3_11_gap_engineering_vi.json"
    prompt_text = (FIXTURES_DIR / "t3_11_vi_prompt.txt").read_text(encoding="utf-8").strip()
    out_pdf = tmp_path / "t3_11_vi.pdf"

    proc = _run_report_cli(
        [
            "--input", str(fixture_json),
            "--out", str(out_pdf),
            "--lang", "auto",
            "--input-text", prompt_text,
            "--strict",
            "--json",
        ]
    )
    assert proc.returncode == 0, f"T3-11 failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    receipt = _parse_json_receipt(proc)
    assert receipt["lang"] == "vi"
    assert receipt["diacritics_verified"] is True
    assert receipt["lint_findings"] == []

    _, pdf_text = _extract_pdf_text_nfc(out_pdf)
    _assert_no_broken_unicode(pdf_text)
    for token in ("0.612", "0.796", "0.184", "84", "arXiv:1907.06902", "lỗi kỹ thuật", "rò rỉ", "tập sạch"):
        assert _pdf_contains(pdf_text, token), (
            f"T3-11 token {token!r} missing or corrupted in compiled Vietnamese PDF"
        )
    assert (
        "ENGINEERING_BUG_DETECTED" in pdf_text or "DROP_ENGINEERING_BUG" in pdf_text
    ), "T3-11 engineering/gap verdict code missing from compiled PDF"


def test_t3_12_chain_venue_manuscript_findings_to_english_tex_and_pdf(tmp_path: Path) -> None:
    """T3-12: Venue/manuscript findings JSON -> report_latex_pdf.py --lang en --tex-out --strict --json."""
    fixture_json = FIXTURES_DIR / "t3_12_venue_manuscript_en.json"
    out_pdf = tmp_path / "t3_12_en.pdf"
    out_tex = tmp_path / "t3_12_en.tex"

    proc = _run_report_cli(
        [
            "--input", str(fixture_json),
            "--out", str(out_pdf),
            "--tex-out", str(out_tex),
            "--lang", "en",
            "--strict",
            "--json",
        ]
    )
    assert proc.returncode == 0, f"T3-12 failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    receipt = _parse_json_receipt(proc)
    assert receipt["lang"] == "en"
    assert receipt["lint_findings"] == []
    assert out_tex.is_file()

    tex_src = unicodedata.normalize("NFC", out_tex.read_text(encoding="utf-8"))
    tex_unbroken = tex_src.replace(r"\allowbreak{}", "")
    _, pdf_text = _extract_pdf_text_nfc(out_pdf)
    _assert_no_broken_unicode(pdf_text)

    for token in ("ICML", "2027", "6/10", "7.5/10", "5", "arXiv:1907.06902"):
        assert token in tex_unbroken, f"T3-12 token {token!r} missing from generated .tex"
        assert token in pdf_text, f"T3-12 token {token!r} missing from compiled PDF"

    combined_lower = (tex_src + "\n" + pdf_text).lower()
    for banned in SYCOPHANCY_BANNED_PHRASES:
        assert banned not in combined_lower, f"Sycophancy phrase {banned!r} leaked into T3-12 output"
