"""Opaque-box E2E tests for Feature F19: "Ít nhất mà tốt nhất" — Mandatory
Parsimony / Anti-Overcomplication & Anti-Problem-Inflation Gate.

Covers:
- Tier 1 (`T1-I1`..`T1-I5`, 5 tests): Core SKILL.md parsimony interrogation gate,
  confirmatory plan acceptance with `parsimony_audit`/`simplest_alternative`,
  blocking over-engineered multi-component plans missing parsimony/ablation,
  `gap_pipeline.py` rejection of bloated/problem-inflated candidates, and
  `report_latex_pdf.py --strict --json` preservation of concise parsimony summaries.
- Tier 2 (`T2-I1`..`T2-I5`, 5 tests): Empty/boilerplate `simplest_alternative`
  rejection, 3+ stacked modules with omitted baseline or <=0 marginal gain,
  problem-inflation/dramatization trap across `gap_pipeline.py`, `humanizer_lint.py`,
  and `report_latex_pdf.py`, `check_manuscript_ledger.py` on `origin: "combined"`
  missing parsimony/ablation, and bilingual VI+EN parsimony checks in
  `report_latex_pdf.py --strict`.
- Tier 3 (`T3-13`, `T3-14`, 2 tests): End-to-end parsimony chains linking
  `gap_pipeline.py` -> `check_ai_cs_research_plan.py` -> `report_latex_pdf.py`
  and `check_manuscript_ledger.py` + `humanizer_lint.py` + `check_ai_cs_research_plan.py`.

Self-contained by design (no imports from `helpers.py` or `real_cases_runner.py`).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any

import fitz

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = REPO_ROOT / "research-scientist"
SCRIPTS_DIR = SKILL_DIR / "scripts"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "f19"

PLAN_CHECKER = SCRIPTS_DIR / "check_ai_cs_research_plan.py"
GAP_PIPELINE = SCRIPTS_DIR / "gap_pipeline.py"
REPORT_PDF = SCRIPTS_DIR / "report_latex_pdf.py"
LEDGER_CHECKER = SCRIPTS_DIR / "check_manuscript_ledger.py"
HUMANIZER_LINT = SCRIPTS_DIR / "humanizer_lint.py"


def _run_script(
    script_path: Path,
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    assert script_path.is_file(), f"Required script not implemented yet at {script_path}"
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    cmd = [sys.executable, str(script_path), *[str(a) for a in args]]
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _parse_json(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
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
        f"Expected JSON dict output.\nreturncode={proc.returncode}\n"
        f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )


def _extract_pdf_text_nfc(pdf_path: Path) -> tuple[int, str]:
    assert pdf_path.is_file(), f"Expected PDF file at {pdf_path}"
    assert pdf_path.stat().st_size > 256, f"PDF file is suspiciously small/empty: {pdf_path}"
    with fitz.open(str(pdf_path)) as doc:
        page_count = len(doc)
        assert page_count >= 1, f"Compiled PDF has 0 pages: {pdf_path}"
        pages_text = [page.get_text("text") for page in doc]
    normalized = unicodedata.normalize("NFC", "\n".join(pages_text))
    collapsed = re.sub(r"\s+", " ", normalized).strip()
    assert collapsed, f"Compiled PDF yielded empty extracted text: {pdf_path}"
    assert "\ufffd" not in collapsed, "Extracted PDF text contains U+FFFD replacement char"
    assert "???" not in collapsed, "Extracted PDF text contains '???' substitution placeholder"
    return page_count, collapsed


def _load_fixture_json(name: str) -> Any:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Tier 1: Core Category-Partition E2E Tests (T1-I1 .. T1-I5)
# ---------------------------------------------------------------------------


def test_t1_i1_skill_md_mandatory_parsimony_interrogation_gate() -> None:
    """T1-I1: SKILL.md requires Mandatory Parsimony / Anti-Problem-Inflation Self-Interrogation Gate."""
    skill_text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8").casefold()
    assert "parsimony" in skill_text or "least is best" in skill_text, (
        "SKILL.md missing Mandatory Parsimony / 'least is best' gate"
    )
    assert any(
        tok in skill_text
        for tok in ("problem inflation", "exaggerat", "dramatiz", "overcomplicat")
    ), "SKILL.md missing anti-problem-inflation / anti-overcomplication check"
    assert any(
        tok in skill_text
        for tok in ("simpler approach", "simpler alternative", "simpler baseline", "simplest")
    ), "SKILL.md missing mandatory simpler-alternative check"
    assert any(
        tok in skill_text
        for tok in ("refuse", "hard refusal")
    ), "SKILL.md missing hard refusal rule when simpler baseline achieves equal/better quality"

    # F21 Hub-and-Spoke resilience: ablation/component details may live in root SKILL.md,
    # linked references/*.md, or sibling sub-skill SKILL.md files (e.g. research-gap-rq-audit).
    extended_texts = [skill_text]
    for ref_name in set(re.findall(r"references/([a-z0-9_.-]+\.md)", skill_text)):
        ref_path = SKILL_DIR / "references" / ref_name
        if ref_path.is_file():
            extended_texts.append(ref_path.read_text(encoding="utf-8").casefold())
    for sib_dir in sorted(REPO_ROOT.glob("research-*")):
        sib_skill = sib_dir / "SKILL.md"
        if sib_dir != SKILL_DIR and sib_skill.is_file():
            extended_texts.append(sib_skill.read_text(encoding="utf-8").casefold())
    combined_text = "\n".join(extended_texts)

    assert "ablat" in combined_text and any(
        tok in combined_text for tok in ("component", "module")
    ), "Parsimony gate missing per-component ablation / complexity justification across SKILL.md & sub-skills"


def test_t1_i2_research_plan_passes_with_parsimony_audit_and_ablation() -> None:
    """T1-I2: check_ai_cs_research_plan.py passes confirmatory plan with concrete parsimony_audit & ablation."""
    proc = _run_script(
        PLAN_CHECKER,
        [
            str(FIXTURES_DIR / "gap_parsimony.json"),
            str(FIXTURES_DIR / "rq_parsimony.json"),
            str(FIXTURES_DIR / "plan_parsimony_valid.json"),
            "--campaign",
            str(FIXTURES_DIR / "campaign_parsimony.json"),
        ],
    )
    assert proc.returncode == 0, f"stderr={proc.stderr}\nstdout={proc.stdout}"
    data = _parse_json(proc)
    assert data["status"] == "structurally_reviewable"
    assert data["errors"] == []


def test_t1_i3_research_plan_blocks_overengineered_plan_missing_parsimony() -> None:
    """T1-I3: check_ai_cs_research_plan.py blocks (exit 1) 4-module plan missing simplest_alternative/ablation."""
    proc = _run_script(
        PLAN_CHECKER,
        [
            str(FIXTURES_DIR / "gap_parsimony.json"),
            str(FIXTURES_DIR / "rq_parsimony.json"),
            str(FIXTURES_DIR / "plan_overengineered_missing_parsimony.json"),
            "--campaign",
            str(FIXTURES_DIR / "campaign_parsimony.json"),
        ],
    )
    assert proc.returncode == 1, (
        f"Expected exit 1 for over-engineered plan missing simplest_alternative/ablation, "
        f"got {proc.returncode}: stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    data = _parse_json(proc)
    assert data["status"] == "invalid"
    assert data["errors"], "Expected non-empty errors explaining missing parsimony/ablation"
    blob = json.dumps(data["errors"]).casefold()
    assert any(
        tok in blob for tok in ("parsimony", "simplest", "ablation", "component", "over")
    ), f"Expected parsimony/ablation error, got: {data['errors']}"


def test_t1_i4_gap_pipeline_rejects_overcomplicated_and_inflated_candidates(tmp_path: Path) -> None:
    """T1-I4: gap_pipeline.py rejects 4-module bloated candidate and problem-inflated minor-variance candidate."""
    out_path = tmp_path / "gap_out.json"
    proc = _run_script(
        GAP_PIPELINE,
        [
            "--topic", "citation graph degree shift",
            "--corpus", str(FIXTURES_DIR / "gap_corpus.json"),
            "--digests", str(FIXTURES_DIR / "gap_digests.json"),
            "--candidates", str(FIXTURES_DIR / "gap_candidates_bloated_and_inflated.json"),
            "--out", str(out_path),
        ],
    )
    assert proc.returncode != 0, (
        f"Expected non-zero exit for bloated/problem-inflated candidates, got 0: "
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    assert out_path.is_file(), f"Expected gap_pipeline output JSON at {out_path}"
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["surviving_gaps"] == []
    rejected = data["rejected_gaps"]
    assert len(rejected) == 2
    by_id = {(r.get("id") or r.get("candidate_id")): r for r in rejected}
    assert {"C_BLOATED", "C_INFLATED"}.issubset(by_id)
    bloated_codes = " ".join(
        str(by_id["C_BLOATED"].get(k) or "") for k in ("drop_code", "code", "reason_code", "reasons")
    )
    inflated_codes = " ".join(
        str(by_id["C_INFLATED"].get(k) or "") for k in ("drop_code", "code", "reason_code", "reasons")
    )
    assert any(
        tok in bloated_codes for tok in ("DROP_OVERCOMPLICATED", "DROP_PARSIMONY")
    ), f"Expected DROP_OVERCOMPLICATED/DROP_PARSIMONY code for C_BLOATED, got: {by_id['C_BLOATED']}"
    assert any(
        tok in inflated_codes for tok in ("DROP_PROBLEM_INFLATION", "DROP_OVERCOMPLICATED")
    ), f"Expected DROP_PROBLEM_INFLATION code for C_INFLATED, got: {by_id['C_INFLATED']}"


def test_t1_i5_report_latex_pdf_preserves_concise_parsimony_summary(tmp_path: Path) -> None:
    """T1-I5: report_latex_pdf.py --strict --json accepts concise parsimony summary and keeps it in PDF."""
    out_pdf = tmp_path / "parsimony_en.pdf"
    out_tex = tmp_path / "parsimony_en.tex"
    proc = _run_script(
        REPORT_PDF,
        [
            "--input", str(FIXTURES_DIR / "report_en_parsimony_clean.json"),
            "--out", str(out_pdf),
            "--tex-out", str(out_tex),
            "--lang", "en",
            "--strict",
            "--json",
        ],
    )
    assert proc.returncode == 0, f"stderr={proc.stderr}\nstdout={proc.stdout}"
    receipt = _parse_json(proc)
    assert receipt["lang"] == "en"
    assert receipt["lint_findings"] == []
    assert receipt["page_count"] >= 1

    _, pdf_text = _extract_pdf_text_nfc(out_pdf)
    for token in ("KEEP SIMPLE BASELINE", "1-layer linear head", "0.741", "0.744", "+0.003"):
        assert token in pdf_text, f"Expected parsimony token {token!r} missing from PDF"


# ---------------------------------------------------------------------------
# Tier 2: Adversarial Corner Cases (T2-I1 .. T2-I5)
# ---------------------------------------------------------------------------


def test_t2_i1_boilerplate_simplest_alternative_rejected(tmp_path: Path) -> None:
    """T2-I1: Empty or hand-wavy boilerplate simplest_alternative is rejected (exit 1)."""
    base_plan = _load_fixture_json("plan_parsimony_valid.json")
    boilerplate_values = [
        "",
        "   ",
        "N/A",
        "none",
        "simpler methods obviously fail",
        "standard baselines are insufficient",
    ]
    for idx, bad_alt in enumerate(boilerplate_values):
        mutated = json.loads(json.dumps(base_plan))
        mutated["simplest_alternative"] = bad_alt
        mutated["parsimony_audit"]["simplest_alternative"] = bad_alt
        plan_path = tmp_path / f"plan_bad_alt_{idx}.json"
        plan_path.write_text(json.dumps(mutated), encoding="utf-8")

        proc = _run_script(
            PLAN_CHECKER,
            [
                str(FIXTURES_DIR / "gap_parsimony.json"),
                str(FIXTURES_DIR / "rq_parsimony.json"),
                str(plan_path),
                "--campaign",
                str(FIXTURES_DIR / "campaign_parsimony.json"),
            ],
        )
        assert proc.returncode == 1, (
            f"Boilerplate simplest_alternative {bad_alt!r} should fail (exit 1), "
            f"got {proc.returncode}: {proc.stdout}"
        )
        data = _parse_json(proc)
        assert data["status"] == "invalid"
        assert data["errors"]


def test_t2_i2_multicomponent_omitted_baseline_or_nonpositive_gain_blocked(tmp_path: Path) -> None:
    """T2-I2: 3+ stacked modules with omitted single-module ablation OR <=0 marginal gain exits 1."""
    # Sub-case A: 3+ modules where ablation omits single-module baseline comparison
    plan_no_single = _load_fixture_json("plan_parsimony_valid.json")
    plan_no_single["components"] = ["GraphEncoder", "HyperbolicAdapter", "DualContrastiveLoss"]
    plan_no_single["parsimony_audit"]["component_justifications"] = []
    plan_no_single["parsimony_audit"].pop("ablation_over_simplest_baseline", None)
    plan_no_single["experiments"] = [
        e for e in plan_no_single["experiments"] if e["role"] != "ablation"
    ]
    p_no_single = tmp_path / "plan_no_single_ablation.json"
    p_no_single.write_text(json.dumps(plan_no_single), encoding="utf-8")

    proc_a = _run_script(
        PLAN_CHECKER,
        [
            str(FIXTURES_DIR / "gap_parsimony.json"),
            str(FIXTURES_DIR / "rq_parsimony.json"),
            str(p_no_single),
            "--campaign",
            str(FIXTURES_DIR / "campaign_parsimony.json"),
        ],
    )
    assert proc_a.returncode == 1, (
        f"Expected exit 1 when 3+ module plan omits single-module ablation, got {proc_a.returncode}: {proc_a.stdout}"
    )
    assert _parse_json(proc_a)["status"] == "invalid"

    # Sub-case B: 3+ modules where ablation shows <= 0 marginal gain over simpler baseline
    proc_b = _run_script(
        PLAN_CHECKER,
        [
            str(FIXTURES_DIR / "gap_parsimony.json"),
            str(FIXTURES_DIR / "rq_parsimony.json"),
            str(FIXTURES_DIR / "plan_overengineered_zero_gain.json"),
            "--campaign",
            str(FIXTURES_DIR / "campaign_parsimony.json"),
        ],
    )
    assert proc_b.returncode == 1, (
        f"Expected exit 1 when 3+ module plan shows <=0 marginal gain, got {proc_b.returncode}: {proc_b.stdout}"
    )
    data_b = _parse_json(proc_b)
    assert data_b["status"] == "invalid"
    assert data_b["errors"]


def test_t2_i3_problem_inflation_dramatization_trap_flagged_everywhere(tmp_path: Path) -> None:
    """T2-I3: 'fundamental crisis' / 'catastrophic failure of all prior work' for 0.2% noise flagged by all 3 gates."""
    # 1. gap_pipeline.py rejects problem-inflated candidate
    gap_out = tmp_path / "gap_inflation.json"
    gp = _run_script(
        GAP_PIPELINE,
        [
            "--topic", "citation graph variance",
            "--corpus", str(FIXTURES_DIR / "gap_corpus.json"),
            "--digests", str(FIXTURES_DIR / "gap_digests.json"),
            "--candidates", str(FIXTURES_DIR / "gap_candidates_problem_inflation.json"),
            "--out", str(gap_out),
        ],
    )
    assert gp.returncode != 0, f"gap_pipeline must reject problem-inflated candidate: {gp.stdout}"
    gp_data = json.loads(gap_out.read_text(encoding="utf-8"))
    assert gp_data["surviving_gaps"] == []
    assert len(gp_data["rejected_gaps"]) == 1
    rej0 = gp_data["rejected_gaps"][0]
    rej_codes = " ".join(str(rej0.get(k) or "") for k in ("drop_code", "code", "reason_code", "reasons"))
    assert "DROP_PROBLEM_INFLATION" in rej_codes, (
        f"Expected DROP_PROBLEM_INFLATION code for C_INFLATION_TRAP, got: {rej0}"
    )

    # 2. humanizer_lint.py --strict flags problem-inflation prose
    draft_md = tmp_path / "inflated_draft.md"
    draft_md.write_text(
        "# Motivation\n\n"
        "A 0.2% accuracy fluctuation exposes a fundamental crisis and catastrophic failure of all prior work.\n"
        "Existing baselines are plagued by severe limitations under standard hyperparameter settings.\n",
        encoding="utf-8",
    )
    hl = _run_script(HUMANIZER_LINT, [str(draft_md), "--strict", "--json"])
    assert hl.returncode == 1, f"humanizer_lint --strict must reject problem inflation: {hl.stdout}"
    hl_data = _parse_json(hl)
    assert hl_data["risk_count"] + hl_data["warn_count"] >= 1
    assert any(
        f.get("category") == "problem_inflation" or f.get("pattern_id") == "PI01"
        for f in hl_data["findings"]
    ), f"Expected PI01/problem_inflation finding, got: {hl_data['findings']}"

    # 3. report_latex_pdf.py --strict rejects problem-inflation report without emitting PDF
    bad_pdf = tmp_path / "inflated_report.pdf"
    rp = _run_script(
        REPORT_PDF,
        [
            "--input", str(FIXTURES_DIR / "report_en_problem_inflation.json"),
            "--out", str(bad_pdf),
            "--lang", "en",
            "--strict",
            "--json",
        ],
    )
    assert rp.returncode == 1, f"report_latex_pdf --strict must reject problem inflation: {rp.stdout}"
    rp_data = _parse_json(rp)
    findings = rp_data.get("lint_findings") or []
    assert findings
    pattern_ids = {str(f.get("pattern_id", "")) for f in findings}
    assert "MISSING_EVIDENCE_LOCATOR" not in pattern_ids, (
        f"Problem-inflation negative control masked by MISSING_EVIDENCE_LOCATOR: {findings}"
    )
    assert "UNGROUNDED_NUMERIC_CLAIM" not in pattern_ids, (
        f"Problem-inflation negative control masked by UNGROUNDED_NUMERIC_CLAIM: {findings}"
    )
    assert any(
        f.get("category") == "problem_inflation" or f.get("pattern_id") == "PI01"
        for f in findings
    ), f"Expected PI01/problem_inflation finding in report_latex_pdf output, got: {findings}"
    assert not bad_pdf.exists()


def test_t2_i4_manuscript_ledger_combined_without_parsimony_rejected(tmp_path: Path) -> None:
    """T2-I4: check_manuscript_ledger.py rejects origin='combined' stacked method lacking parsimony/ablation."""
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    (sources_dir / "source_evidence.txt").write_text(
        (FIXTURES_DIR / "source_evidence.txt").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    manuscript = tmp_path / "ms.md"
    manuscript.write_text(
        "# Results\n\nThe combined four-stage pipeline reached 0.752 macro-F1.\n",
        encoding="utf-8",
    )

    # Sub-case A: origin='combined' with 4 stacked components and missing simplest_alternative / ablation
    proc_missing = _run_script(
        LEDGER_CHECKER,
        [
            "--ledger", str(FIXTURES_DIR / "ledger_combined_no_parsimony.json"),
            "--manuscript", str(manuscript),
            "--sources-dir", str(sources_dir),
        ],
    )
    assert proc_missing.returncode == 1, (
        f"Expected exit 1 on combined method missing parsimony/ablation, got {proc_missing.returncode}: {proc_missing.stdout}"
    )
    data_a = _parse_json(proc_missing)
    assert data_a["status"] == "structural_issues"
    issues_blob = " ".join(data_a["issues"])
    assert "missing_simplest_alternative" in issues_blob
    assert "missing_component_ablation" in issues_blob

    # Sub-case B: parsimony_audit declares simpler_equal_or_better=True -> overcomplicated_method
    ledger_over = _load_fixture_json("ledger_stitched_clean.json")
    ledger_over["methods"][0]["parsimony_audit"]["simpler_equal_or_better"] = True
    ledger_over_path = tmp_path / "ledger_over.json"
    ledger_over_path.write_text(json.dumps(ledger_over), encoding="utf-8")

    proc_over = _run_script(
        LEDGER_CHECKER,
        [
            "--ledger", str(ledger_over_path),
            "--manuscript", str(FIXTURES_DIR / "manuscript_stitched_clean.md"),
            "--sources-dir", str(sources_dir),
        ],
    )
    assert proc_over.returncode == 1
    data_b = _parse_json(proc_over)
    assert any("overcomplicated_method" in iss for iss in data_b["issues"])


def test_t2_i5_bilingual_parsimony_report_strict_reject_vs_pass(tmp_path: Path) -> None:
    """T2-I5: report_latex_pdf.py --strict rejects bilingual over-explanation (exit 1) and passes crisp VI verdict (exit 0)."""
    # Negative: convoluted bilingual multi-layer over-explanation
    bad_pdf = tmp_path / "bilingual_over.pdf"
    neg_proc = _run_script(
        REPORT_PDF,
        [
            "--input", str(FIXTURES_DIR / "report_bilingual_overexplanation.json"),
            "--out", str(bad_pdf),
            "--lang", "auto",
            "--strict",
            "--json",
        ],
    )
    assert neg_proc.returncode == 1, (
        f"Expected exit 1 for convoluted bilingual over-explanation, got {neg_proc.returncode}: {neg_proc.stdout}"
    )
    neg_receipt = _parse_json(neg_proc)
    neg_findings = neg_receipt.get("lint_findings") or []
    assert neg_findings
    neg_cats = {f.get("category") for f in neg_findings}
    neg_pids = {str(f.get("pattern_id", "")) for f in neg_findings}
    assert "MISSING_EVIDENCE_LOCATOR" not in neg_pids, (
        f"Bilingual over-explanation control masked by MISSING_EVIDENCE_LOCATOR: {neg_findings}"
    )
    assert "plain_language" in neg_cats or "conciseness" in neg_cats, (
        f"Expected plain_language/conciseness findings, got: {neg_findings}"
    )
    assert not bad_pdf.exists()

    # Positive: crisp parsimonious Vietnamese verdict
    ok_pdf = tmp_path / "vi_parsimony_clean.pdf"
    ok_tex = tmp_path / "vi_parsimony_clean.tex"
    vi_prompt = (FIXTURES_DIR / "vi_parsimony_prompt.txt").read_text(encoding="utf-8").strip()
    pos_proc = _run_script(
        REPORT_PDF,
        [
            "--input", str(FIXTURES_DIR / "report_vi_parsimony_clean.json"),
            "--out", str(ok_pdf),
            "--tex-out", str(ok_tex),
            "--lang", "auto",
            "--input-text", vi_prompt,
            "--strict",
            "--json",
        ],
    )
    assert pos_proc.returncode == 0, f"stderr={pos_proc.stderr}\nstdout={pos_proc.stdout}"
    pos_receipt = _parse_json(pos_proc)
    assert pos_receipt["lang"] == "vi"
    assert pos_receipt["diacritics_verified"] is True
    assert pos_receipt["lint_findings"] == []

    _, pdf_text = _extract_pdf_text_nfc(ok_pdf)
    pdf_compact = re.sub(r"\s+", "", pdf_text)
    for token in ("GIỮ BASELINE ĐƠN GIẢN", "0.742", "0.740", "1 tầng", "5 hạt giống"):
        assert token in pdf_text or re.sub(r"\s+", "", token) in pdf_compact, (
            f"Vietnamese parsimony token {token!r} missing/corrupted in PDF"
        )


# ---------------------------------------------------------------------------
# Tier 3: Cross-Feature End-to-End Chains (T3-13, T3-14)
# ---------------------------------------------------------------------------


def test_t3_13_chain_gap_pipeline_research_plan_and_pdf_parsimony(tmp_path: Path) -> None:
    """T3-13: gap_pipeline -> check_ai_cs_research_plan -> report_latex_pdf parsimony chain (blocked bloated vs passed minimal)."""
    # Part 1: Bloated 4-module proposal blocked by gap_pipeline & plan checker, then summarized cleanly in PDF
    bloated_gap_out = tmp_path / "bloated_gap_out.json"
    gp_bad = _run_script(
        GAP_PIPELINE,
        [
            "--topic", "citation graph degree shift",
            "--corpus", str(FIXTURES_DIR / "gap_corpus.json"),
            "--digests", str(FIXTURES_DIR / "gap_digests.json"),
            "--candidates", str(FIXTURES_DIR / "gap_candidates_bloated_and_inflated.json"),
            "--out", str(bloated_gap_out),
        ],
    )
    assert gp_bad.returncode != 0
    assert json.loads(bloated_gap_out.read_text(encoding="utf-8"))["surviving_gaps"] == []

    plan_bad = _run_script(
        PLAN_CHECKER,
        [
            str(FIXTURES_DIR / "gap_parsimony.json"),
            str(FIXTURES_DIR / "rq_parsimony.json"),
            str(FIXTURES_DIR / "plan_overengineered_missing_parsimony.json"),
            "--campaign",
            str(FIXTURES_DIR / "campaign_parsimony.json"),
        ],
    )
    assert plan_bad.returncode == 1
    assert _parse_json(plan_bad)["status"] == "invalid"

    blocked_pdf = tmp_path / "t3_13_blocked.pdf"
    rep_blocked = _run_script(
        REPORT_PDF,
        [
            "--input", str(FIXTURES_DIR / "report_t3_13_blocked_bloated.json"),
            "--out", str(blocked_pdf),
            "--lang", "en",
            "--strict",
            "--json",
        ],
    )
    assert rep_blocked.returncode == 0, f"stderr={rep_blocked.stderr}\nstdout={rep_blocked.stdout}"
    _, blocked_text = _extract_pdf_text_nfc(blocked_pdf)
    for token in ("REJECT PROPOSAL", "0.741", "0.740"):
        assert token in blocked_text

    # Part 2: Minimal justified 1-component proposal passes all 3 gates
    clean_gap_out = tmp_path / "clean_gap_out.json"
    gp_ok = _run_script(
        GAP_PIPELINE,
        [
            "--topic", "citation graph degree shift",
            "--corpus", str(FIXTURES_DIR / "gap_corpus.json"),
            "--digests", str(FIXTURES_DIR / "gap_digests.json"),
            "--candidates", str(FIXTURES_DIR / "gap_candidates_minimal_valid.json"),
            "--out", str(clean_gap_out),
        ],
    )
    assert gp_ok.returncode == 0, f"stderr={gp_ok.stderr}\nstdout={gp_ok.stdout}"
    gp_ok_data = json.loads(clean_gap_out.read_text(encoding="utf-8"))
    assert len(gp_ok_data["surviving_gaps"]) == 1
    assert gp_ok_data["rejected_gaps"] == []

    plan_ok = _run_script(
        PLAN_CHECKER,
        [
            str(FIXTURES_DIR / "gap_parsimony.json"),
            str(FIXTURES_DIR / "rq_parsimony.json"),
            str(FIXTURES_DIR / "plan_parsimony_valid.json"),
            "--campaign",
            str(FIXTURES_DIR / "campaign_parsimony.json"),
        ],
    )
    assert plan_ok.returncode == 0, f"stderr={plan_ok.stderr}\nstdout={plan_ok.stdout}"
    assert _parse_json(plan_ok)["status"] == "structurally_reviewable"

    minimal_pdf = tmp_path / "t3_13_minimal.pdf"
    rep_ok = _run_script(
        REPORT_PDF,
        [
            "--input", str(FIXTURES_DIR / "report_t3_13_passed_minimal.json"),
            "--out", str(minimal_pdf),
            "--lang", "en",
            "--strict",
            "--json",
        ],
    )
    assert rep_ok.returncode == 0, f"stderr={rep_ok.stderr}\nstdout={rep_ok.stdout}"
    _, minimal_text = _extract_pdf_text_nfc(minimal_pdf)
    for token in ("PASS PARSIMONY GATE", "0.718", "0.752", "+0.034"):
        assert token in minimal_text


def test_t3_14_chain_parsimony_plus_antifabrication_stitched_pipeline(tmp_path: Path) -> None:
    """T3-14: Parsimony + Anti-Fabrication across check_manuscript_ledger + humanizer_lint + check_ai_cs_research_plan."""
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    (sources_dir / "source_evidence.txt").write_text(
        (FIXTURES_DIR / "source_evidence.txt").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    # Negative stitched 4-module pipeline: fails ledger, humanizer_lint --strict, and plan checker
    bad_ledger = _run_script(
        LEDGER_CHECKER,
        [
            "--ledger", str(FIXTURES_DIR / "ledger_stitched_bad.json"),
            "--manuscript", str(FIXTURES_DIR / "manuscript_stitched_bad.md"),
            "--sources-dir", str(sources_dir),
        ],
    )
    assert bad_ledger.returncode == 1
    bad_ledger_data = _parse_json(bad_ledger)
    bad_issues = " ".join(bad_ledger_data["issues"])
    assert "inflated_method_name" in bad_issues or "grandiose_branding_detected" in bad_issues
    assert "problem_inflation_detected" in bad_issues
    assert "missing_simplest_alternative" in bad_issues
    assert "missing_component_ablation" in bad_issues

    bad_humanizer = _run_script(
        HUMANIZER_LINT,
        [str(FIXTURES_DIR / "manuscript_stitched_bad.md"), "--strict", "--json"],
    )
    assert bad_humanizer.returncode == 1
    bad_hum_data = _parse_json(bad_humanizer)
    assert bad_hum_data["risk_count"] + bad_hum_data["warn_count"] >= 1
    assert any(
        f.get("category") == "problem_inflation" or f.get("pattern_id") == "PI01"
        for f in bad_hum_data.get("findings", [])
    ), f"Expected PI01/problem_inflation finding in humanizer_lint output, got: {bad_hum_data.get('findings')}"

    bad_plan = _run_script(
        PLAN_CHECKER,
        [
            str(FIXTURES_DIR / "gap_parsimony.json"),
            str(FIXTURES_DIR / "rq_parsimony.json"),
            str(FIXTURES_DIR / "plan_overengineered_missing_parsimony.json"),
            "--campaign",
            str(FIXTURES_DIR / "campaign_parsimony.json"),
        ],
    )
    assert bad_plan.returncode == 1
    assert _parse_json(bad_plan)["status"] == "invalid"

    # Positive minimal honest combined pipeline: passes ledger, humanizer_lint --strict, and plan checker
    ok_ledger = _run_script(
        LEDGER_CHECKER,
        [
            "--ledger", str(FIXTURES_DIR / "ledger_stitched_clean.json"),
            "--manuscript", str(FIXTURES_DIR / "manuscript_stitched_clean.md"),
            "--sources-dir", str(sources_dir),
        ],
    )
    assert ok_ledger.returncode == 0, f"stdout={ok_ledger.stdout}\nstderr={ok_ledger.stderr}"
    assert _parse_json(ok_ledger)["status"] == "structure_passed"

    ok_humanizer = _run_script(
        HUMANIZER_LINT,
        [str(FIXTURES_DIR / "manuscript_stitched_clean.md"), "--strict", "--json"],
    )
    assert ok_humanizer.returncode == 0, f"stdout={ok_humanizer.stdout}\nstderr={ok_humanizer.stderr}"
    ok_hum_data = _parse_json(ok_humanizer)
    assert ok_hum_data["risk_count"] == 0
    assert ok_hum_data["warn_count"] == 0

    ok_plan = _run_script(
        PLAN_CHECKER,
        [
            str(FIXTURES_DIR / "gap_parsimony.json"),
            str(FIXTURES_DIR / "rq_parsimony.json"),
            str(FIXTURES_DIR / "plan_parsimony_valid.json"),
            "--campaign",
            str(FIXTURES_DIR / "campaign_parsimony.json"),
        ],
    )
    assert ok_plan.returncode == 0, f"stdout={ok_plan.stdout}\nstderr={ok_plan.stderr}"
    assert _parse_json(ok_plan)["status"] == "structurally_reviewable"
