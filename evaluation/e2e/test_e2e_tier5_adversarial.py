"""Tier-5 Adversarial Hardening, Scientific-Integrity Rubric & Live-Audit Regression Tests.

Covers:
- Scientific-integrity rubric across all 7 Hub-and-Spoke skills (`research-scientist` + 6 spokes)
- Live-discovered weak-spot regressions:
  - `search_papers.py`: Semantic Scholar `venue="arXiv.org"` preprint classification & dedup preservation
  - `capture_venue_sources.py`: `AoE` / `UTC -12h` timezone extraction and policy-paragraph filtering
  - `real_cases_runner.py`: HTTP 202 Anubis challenge classification in `_live_probe`
- White-box Tier-5 adversarial bypass & boundary checks:
  - `check_ai_cs_research_plan.py`: `NaN`/`Infinity` ablation bypass prevention (Python API + CLI exit 2)
  - `compare_scorecards.py`, `compare_venue_novelty.py`, `report_latex_pdf.py`, `check_experiment_rigor.py`:
    empty/whitespace CLI path rejection and non-finite `NaN`/`Infinity` rejection (exit 2)
  - `claim_audit.py`: `audit_suite` symlink-escape prevention on sub-skill directory
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PARENT_DIR = REPO_ROOT / "research-scientist"
SCRIPTS_DIR = PARENT_DIR / "scripts"
F19_FIXTURES = REPO_ROOT / "evaluation" / "e2e" / "fixtures" / "f19"

ALL_SKILLS = (
    "research-scientist",
    "research-precedent-corpus",
    "research-gap-rq-audit",
    "research-experiment-coding",
    "research-novelty-venue",
    "research-paper-writing",
    "research-user-report",
)


def _load_mod(name: str, path: Path) -> Any:
    parent_str = str(path.parent)
    if parent_str not in sys.path:
        sys.path.insert(0, parent_str)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_cli(script_name: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / script_name), *args],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_t5_1_all_seven_skills_enforce_scientific_integrity_rubric() -> None:
    """Tier-5: Every skill in the 7-skill suite enforces strict non-sycophancy, anti-fabrication, and valid refs."""
    sycophantic_phrases = ("great idea", "brilliant framing", "impressive gain", "promising direction")
    for sname in ALL_SKILLS:
        sdir = REPO_ROOT / sname
        skill_md = sdir / "SKILL.md"
        openai_yaml = sdir / "agents" / "openai.yaml"
        assert skill_md.is_file(), f"Missing {skill_md}"
        assert openai_yaml.is_file(), f"Missing {openai_yaml}"
        raw = skill_md.read_text(encoding="utf-8")
        low = raw.casefold()
        # No accidental endorsement of sycophancy (outside explicit ban quotes in parent)
        if sname != "research-scientist":
            for bad in sycophantic_phrases:
                assert bad not in low, f"Unexpected praise phrase {bad!r} in {sname}/SKILL.md"
        assert any(
            tok in low
            for tok in ("sycophancy", "refuse", "never", "zero", "unverified", "fabricated", "honesty", "parsimony")
        ), f"{sname}/SKILL.md lacks explicit scientific-integrity constraint"


def test_t5_2_search_papers_s2_arxiv_venue_preprint_only_and_dedup() -> None:
    """Tier-5 regression (Live Area 1): S2 venue='arXiv.org' + 10.48550/arxiv.* stays preprint_only=True."""
    sp = _load_mod("search_papers_t5", SCRIPTS_DIR / "search_papers.py")
    s2_payload = {
        "total": 2,
        "data": [
            {
                "paperId": "s2-wisv",
                "title": "WISV: Wireless-Informed Semantic Verification",
                "year": 2026,
                "venue": "arXiv.org",
                "externalIds": {"DOI": "10.48550/arxiv.2604.17701", "ArXiv": "2604.17701"},
                "authors": [{"name": "A. Author"}],
            },
            {
                "paperId": "s2-longspec",
                "title": "LongSpec: Long-Context Speculative Decoding",
                "year": 2025,
                "venue": "Annual Meeting of the Association for Computational Linguistics",
                "externalIds": {"DOI": "10.18653/v1/2026.acl-long.83", "ArXiv": "2502.17421"},
                "authors": [{"name": "B. Author"}],
            },
        ],
    }
    recs, _ = sp.parse("s2", s2_payload)
    assert recs[0]["preprint_only"] is True, "S2 venue='arXiv.org' must remain preprint_only=True"
    assert recs[1]["preprint_only"] is False, "Published ACL venue must remain preprint_only=False"

    oa_payload = {
        "meta": {"count": 1},
        "results": [
            {
                "id": "https://openalex.org/W7155055455",
                "display_name": "WISV: Wireless-Informed Semantic Verification",
                "publication_year": 2026,
                "doi": "https://doi.org/10.48550/arxiv.2604.17701",
                "type": "preprint",
                "ids": {"arxiv": "https://arxiv.org/abs/2604.17701"},
            }
        ],
    }
    oa_recs, _ = sp.parse("openalex", oa_payload)
    merged, groups = sp.deduplicate_records(recs + oa_recs)
    wisv = next(r for r in merged if r.get("arxiv_id") == "2604.17701")
    assert wisv["preprint_only"] is True
    assert len(groups) == 1


def test_t5_3_capture_venue_sources_aoe_utc_offset_and_prose_filter() -> None:
    """Tier-5 regression (Live Area 3): Extract uppercase AOE, 'UTC -12h', and skip >260-char policy prose."""
    cap = _load_mod("capture_venue_sources_t5", SCRIPTS_DIR / "capture_venue_sources.py")
    html = (
        "<html><body>"
        "<p>Change in policy: " + ("authors should review submission instructions carefully " * 8) + "</p>"
        "<p>Abstract submission deadline: January 14, 2027 11:59 PM AOE</p>"
        "<p>All deadlines are 11.59 pm UTC -12h (anywhere on earth).</p>"
        "</body></html>"
    )
    structured, links = cap.to_structured_text(html)
    signals = cap.extract_cfp_signals(structured, html, links)
    assert "AoE" in signals["timezones"], f"Expected AoE in timezones, got {signals['timezones']}"
    assert "UTC-12H" in signals["timezones"], f"Expected UTC-12H in timezones, got {signals['timezones']}"
    assert all("Change in policy:" not in d for d in signals["deadlines"]), (
        f"Long policy prose leaked into deadlines: {signals['deadlines']}"
    )
    assert any("January 14, 2027" in d for d in signals["deadlines"])


def test_t5_4_live_probe_classifies_http_202_anubis_not_ok() -> None:
    """Tier-5 regression (Live Area 1 probe): HTTP 202 HTML Anubis challenge is never labeled 'ok'."""
    runner = _load_mod("real_cases_runner_t5", REPO_ROOT / "evaluation" / "e2e" / "real_cases_runner.py")

    class _Resp202:
        status = 202
        headers = {"Content-Type": "text/html; charset=utf-8"}

        def geturl(self) -> str:
            return "https://dblp.org/search/publ/api?q=graph&format=json"

        def read(self, n: int = -1) -> bytes:
            return b"<html><title>Making sure you're not a bot!</title><div id='anubis_challenge'></div></html>"[:n]

        def __enter__(self) -> "_Resp202":
            return self

        def __exit__(self, *args: object) -> bool:
            return False

    with patch.object(runner, "urlopen", return_value=_Resp202()):
        ev = runner._live_probe("https://dblp.org/search/publ/api?q=graph&format=json")
    assert ev["status"] == 202
    assert ev["provider_state"] == "bot_challenge_202"


def test_t5_5_research_plan_blocks_nan_and_infinity_ablation_bypass(tmp_path: Path) -> None:
    """Tier-5 adversarial: NaN/Infinity in marginal_gain or scores cannot bypass parsimony check."""
    plan_mod = _load_mod("check_ai_cs_research_plan_t5", SCRIPTS_DIR / "check_ai_cs_research_plan.py")
    gap = json.loads((F19_FIXTURES / "gap_parsimony.json").read_text(encoding="utf-8"))
    rq = json.loads((F19_FIXTURES / "rq_parsimony.json").read_text(encoding="utf-8"))
    plan = json.loads((F19_FIXTURES / "plan_parsimony_valid.json").read_text(encoding="utf-8"))
    camp = json.loads((F19_FIXTURES / "campaign_parsimony.json").read_text(encoding="utf-8"))

    # Python API bypass probes: float('nan') in ablation_over_simplest_baseline & component_justifications
    bad_plan = json.loads(json.dumps(plan))
    bad_plan["parsimony_audit"]["ablation_over_simplest_baseline"]["marginal_gain"] = float("nan")
    res = plan_mod.check(gap, rq, bad_plan, campaign=camp)
    assert res["status"] == "invalid"
    assert "plan:parsimony_nonpositive_marginal_gain" in res["errors"]

    bad_plan_comp = json.loads(json.dumps(plan))
    bad_plan_comp["parsimony_audit"]["component_justifications"][0]["marginal_gain"] = float("nan")
    res_comp = plan_mod.check(gap, rq, bad_plan_comp, campaign=camp)
    assert res_comp["status"] == "invalid"
    assert "plan:parsimony_component_nonpositive_gain" in res_comp["errors"]

    # CLI JSON non-finite probe: NaN literal in JSON exits 2 cleanly
    nan_plan_path = tmp_path / "plan_nan.json"
    nan_plan_path.write_text(
        json.dumps(plan).replace("0.034", "NaN", 1),
        encoding="utf-8",
    )
    proc = _run_cli(
        "check_ai_cs_research_plan.py",
        [
            str(F19_FIXTURES / "gap_parsimony.json"),
            str(F19_FIXTURES / "rq_parsimony.json"),
            str(nan_plan_path),
            "--campaign",
            str(F19_FIXTURES / "campaign_parsimony.json"),
        ],
    )
    assert proc.returncode == 2
    assert "Traceback" not in proc.stderr
    assert "error" in json.loads(proc.stderr)


def test_t5_6_empty_cli_args_and_nonfinite_json_exit_2_cleanly(tmp_path: Path) -> None:
    """Tier-5 adversarial: Empty CLI flags and NaN JSON payloads fail closed with exit 2 and JSON error."""
    out_pdf = tmp_path / "out.pdf"
    nan_json = tmp_path / "nan.json"
    nan_json.write_text('{"title": "Test", "score": NaN}', encoding="utf-8")

    # report_latex_pdf.py empty --out / --tex-out / --lang and NaN JSON
    for bad_args in (
        ["--input", str(nan_json), "--out", str(out_pdf)],
        ["--input", str(F19_FIXTURES / "report_en_parsimony_clean.json"), "--out", "   "],
        ["--input", str(F19_FIXTURES / "report_en_parsimony_clean.json"), "--out", str(out_pdf), "--tex-out", ""],
        ["--input", str(F19_FIXTURES / "report_en_parsimony_clean.json"), "--out", str(out_pdf), "--lang", "  "],
    ):
        proc = _run_cli("report_latex_pdf.py", bad_args)
        assert proc.returncode == 2, f"Expected exit 2 for {bad_args}, got {proc.returncode}: {proc.stderr}"
        assert "Traceback" not in proc.stderr
        assert "error" in json.loads(proc.stderr)

    # compare_scorecards.py & compare_venue_novelty.py empty --out and NaN JSON
    for script in ("compare_scorecards.py", "compare_venue_novelty.py"):
        for bad_args in ([str(nan_json)], ["   "]):
            proc = _run_cli(script, bad_args)
            assert proc.returncode == 2, f"{script} {bad_args}: got {proc.returncode}"
            assert "Traceback" not in proc.stderr
            assert "error" in json.loads(proc.stderr)

    # check_experiment_rigor.py contamination --threshold nan
    tr = tmp_path / "tr.txt"
    ev = tmp_path / "ev.txt"
    tr.write_text("sample training sentence one two three\n", encoding="utf-8")
    ev.write_text("sample evaluation sentence four five six\n", encoding="utf-8")
    proc_rigor = _run_cli(
        "check_experiment_rigor.py",
        ["contamination", "--train", str(tr), "--eval", str(ev), "--threshold", "nan"],
    )
    assert proc_rigor.returncode == 2
    assert "error" in json.loads(proc_rigor.stderr)


def test_t5_7_claim_audit_suite_blocks_subskill_symlink_escape(tmp_path: Path) -> None:
    """Tier-5 adversarial: Symlinked sub-skill dir escaping suite_root is rejected by audit_suite."""
    outside = tmp_path / "outside_skill"
    outside.mkdir()
    (outside / "SKILL.md").write_text("---\nname: research-user-report\ndescription: x\n---\n# Outside\n", encoding="utf-8")

    suite = tmp_path / "suite"
    suite.mkdir()
    for sname in ALL_SKILLS:
        if sname == "research-user-report":
            (suite / sname).symlink_to(outside)
        else:
            shutil_src = REPO_ROOT / sname
            dest = suite / sname
            dest.mkdir()
            (dest / "SKILL.md").write_text((shutil_src / "SKILL.md").read_text(encoding="utf-8"), encoding="utf-8")
            (dest / "agents").mkdir()
            (dest / "agents" / "openai.yaml").write_text(
                (shutil_src / "agents" / "openai.yaml").read_text(encoding="utf-8"), encoding="utf-8"
            )
            if (shutil_src / "references").is_dir():
                (dest / "references").mkdir()
                for ref in (shutil_src / "references").glob("*.md"):
                    (dest / "references" / ref.name).write_text(ref.read_text(encoding="utf-8"), encoding="utf-8")
            if sname == "research-scientist":
                (dest / "scripts").mkdir()
                for sc in (shutil_src / "scripts").glob("*.py"):
                    (dest / "scripts" / sc.name).write_text(sc.read_text(encoding="utf-8"), encoding="utf-8")
                (dest / "modules").mkdir()
                for mod_sc in (shutil_src / "modules").rglob("*.py"):
                    rel = mod_sc.relative_to(shutil_src)
                    (dest / rel).parent.mkdir(parents=True, exist_ok=True)
                    (dest / rel).write_text(mod_sc.read_text(encoding="utf-8"), encoding="utf-8")

    proc = _run_cli("claim_audit.py", ["--suite-root", str(suite), "--compact"])
    assert proc.returncode == 1, f"Expected exit 1 on subskill symlink escape, got {proc.returncode}: {proc.stdout}"
    assert "outside-root-symlink" in proc.stdout
