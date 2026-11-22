"""Opaque-box E2E tests for M10C mock-review triage & monotonic calibration benchmark."""
from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path

import fitz

from helpers import EVAL_FIXTURES_DIR, REPO_ROOT, SCRIPTS_DIR, iso_utc, run_cli

MAX_COMPACT_BYTES = 4096
BENCHMARK_DIR = EVAL_FIXTURES_DIR / "calibration_benchmark"
SOURCES_DIR = BENCHMARK_DIR / "sources"
TRIAGE_SCRIPT = SCRIPTS_DIR / "triage_reviews.py"
SCORE_MATH_SCRIPT = SCRIPTS_DIR / "score_math.py"
COMPARE_SCORECARDS_SCRIPT = SCRIPTS_DIR / "compare_scorecards.py"
COMPARE_VENUE_NOVELTY_SCRIPT = SCRIPTS_DIR / "compare_venue_novelty.py"
CLAIM_AUDIT_SCRIPT = SCRIPTS_DIR / "claim_audit.py"
REPORT_PDF_SCRIPT = SCRIPTS_DIR / "report_latex_pdf.py"

FABRICATED_ODDS_RE = re.compile(
    r"\b\d+(?:\.\d+)?%\s*(?:acceptance|chance|odds|probability)",
    re.IGNORECASE,
)


def _refresh_portfolio_timestamps(portfolio: dict, now_iso: str) -> dict:
    doc = json.loads(json.dumps(portfolio))
    if isinstance(doc.get("target"), dict):
        doc["target"]["assessed_at_utc"] = now_iso
    for cand in doc.get("candidate_venues") or []:
        if isinstance(cand, dict):
            if isinstance(cand.get("venue"), dict):
                cand["venue"]["checked_at_utc"] = now_iso
            for item in cand.get("accepted_panel") or []:
                if isinstance(item, dict):
                    item["assessed_at_utc"] = now_iso
    return doc


def test_t1_m10c_cli_help_compact_and_5_tier_monotonic_calibration(tmp_path: Path) -> None:
    for help_args in (["--help"], ["mock-review", "--help"], ["post-reject", "--help"]):
        h = run_cli(TRIAGE_SCRIPT, help_args)
        assert h.returncode == 0, h.stderr

    manifest = json.loads((BENCHMARK_DIR / "benchmark_manifest.json").read_text(encoding="utf-8"))
    now_iso = iso_utc(0)

    by_tier = {}
    for entry in manifest["tiers"]:
        tid = entry["tier_id"]
        doc = json.loads((BENCHMARK_DIR / entry["file"]).read_text(encoding="utf-8"))

        # 1. score_math CLI
        sc_path = tmp_path / f"{tid}_scorecard.json"
        sc_path.write_text(json.dumps(doc["scorecard"]), encoding="utf-8")
        sc_res = run_cli(SCORE_MATH_SCRIPT, [str(sc_path)])
        assert sc_res.returncode == 0, sc_res.stderr
        assert sc_res.json_out["submission_readiness"]["band"] == entry["expected_band"]

        # 2. compare_scorecards CLI (--strict-related-panel --min-related 3 --sources-dir --compact)
        bundle_path = tmp_path / f"{tid}_bundle.json"
        bundle_path.write_text(json.dumps(doc["scorecards_bundle"]), encoding="utf-8")
        csc_out = tmp_path / f"{tid}_csc_out.json"
        csc_res = run_cli(
            COMPARE_SCORECARDS_SCRIPT,
            [
                str(bundle_path),
                "--target-id", entry["target_id"],
                "--strict-related-panel",
                "--min-related", "3",
                "--sources-dir", str(SOURCES_DIR),
                "--out", str(csc_out),
                "--compact",
            ],
        )
        assert csc_res.returncode == 0, (tid, csc_res.stderr, csc_res.stdout)
        assert len(csc_res.stdout.strip().encode("utf-8")) < MAX_COMPACT_BYTES
        csc_full = json.loads(csc_out.read_text(encoding="utf-8"))
        assert csc_full["locator_verification"]["failed"] == 0

        # 3. compare_venue_novelty CLI (--portfolio --require-panels --sources-dir --compact)
        vp_path = tmp_path / f"{tid}_portfolio.json"
        vp_path.write_text(json.dumps(_refresh_portfolio_timestamps(doc["venue_portfolio"], now_iso)), encoding="utf-8")
        vn_out = tmp_path / f"{tid}_vn_out.json"
        vn_res = run_cli(
            COMPARE_VENUE_NOVELTY_SCRIPT,
            [
                str(vp_path),
                "--portfolio",
                "--require-panels",
                "--sources-dir", str(SOURCES_DIR),
                "--out", str(vn_out),
                "--compact",
            ],
        )
        assert vn_res.returncode == 0, (tid, vn_res.stderr, vn_res.stdout)
        assert len(vn_res.stdout.strip().encode("utf-8")) < MAX_COMPACT_BYTES
        vn_full = json.loads(vn_out.read_text(encoding="utf-8"))
        assert vn_full["venue_portfolio_recommendations"]["portfolio_verdict"] == entry["expected_portfolio_verdict"]

        # 4. triage_reviews mock-review CLI fusing upstream outputs
        dossier_path = tmp_path / f"{tid}_dossier.json"
        dossier_path.write_text(json.dumps(doc), encoding="utf-8")
        mr_out = tmp_path / f"{tid}_mock_review.json"
        mr_res = run_cli(
            TRIAGE_SCRIPT,
            [
                "mock-review",
                "--input", str(dossier_path),
                "--scorecard", str(csc_out),
                "--venue-novelty", str(vn_out),
                "--subfield-preset", entry["subfield_preset"],
                "--venue-tier", "top_tier_flagship",
                "--out", str(mr_out),
                "--compact",
            ],
        )
        assert mr_res.returncode == 0, (tid, mr_res.stderr)
        assert len(mr_res.stdout.strip().encode("utf-8")) < MAX_COMPACT_BYTES
        mr_full = json.loads(mr_out.read_text(encoding="utf-8"))
        assert not FABRICATED_ODDS_RE.search(mr_out.read_text(encoding="utf-8"))

        by_tier[tid] = {
            "weighted": Decimal(sc_res.json_out["weighted_unrounded"]),
            "merit": mr_full["merit_vs_publishability"]["scientific_merit_score"],
            "floor": mr_full["worst_case_sensitivity"]["worst_case_reviewer_floor"],
            "mr": mr_full,
        }

    ladder = ["tier1_top_oral", "tier2_main_accept", "tier3_borderline_findings", "tier4_workshop", "tier5a_clear_reject"]
    for i in range(len(ladder) - 1):
        hi, lo = by_tier[ladder[i]], by_tier[ladder[i + 1]]
        assert hi["weighted"] > lo["weighted"]
        assert hi["merit"] > lo["merit"]
        assert hi["floor"] > lo["floor"]

    assert by_tier["tier5b_fatal_gate"]["weighted"] == Decimal("7.20")
    assert by_tier["tier5b_fatal_gate"]["mr"]["overall_verdict"] == "fatal_gate_triggered"


def test_t2_m10c_mode1_mock_review_all_4_subfield_presets_and_strict_exit_1(tmp_path: Path) -> None:
    presets = ("nlp_llm", "cv_multimodal", "ml_theory", "ai_systems")
    files = {
        "nlp_llm": BENCHMARK_DIR / "triage" / "mode1_pre_submission_nlp_llm.json",
        "cv_multimodal": BENCHMARK_DIR / "triage" / "mode1_pre_submission_cv_multimodal.json",
        "ml_theory": BENCHMARK_DIR / "triage" / "mode1_pre_submission_ml_theory.json",
        "ai_systems": BENCHMARK_DIR / "triage" / "mode1_pre_submission_ai_systems.json",
    }

    for preset in presets:
        out_path = tmp_path / f"{preset}_review.json"
        res = run_cli(
            TRIAGE_SCRIPT,
            [
                "mock-review",
                "--input", str(files[preset]),
                "--subfield-preset", preset,
                "--out", str(out_path),
                "--compact",
            ],
        )
        assert res.returncode == 0, (preset, res.stderr)
        assert len(res.stdout.strip().encode("utf-8")) < MAX_COMPACT_BYTES
        assert res.json_out["compact"] is True
        full = json.loads(out_path.read_text(encoding="utf-8"))

        assert set(full["personas"].keys()) == {"method_theory", "experiments_baselines", "novelty_positioning"}
        assert set(full["subfield_preset_audit"]["presets"].keys()) == set(presets)
        assert full["subfield_preset_audit"]["active_preset"] == preset
        assert full["subfield_preset_audit"]["status"] == "FAIL"
        assert "merit_vs_publishability" in full
        assert "side_by_side_anchor_contrast" in full
        assert "worst_case_sensitivity" in full
        for sec in ("abstract", "introduction", "related_work", "method", "experiments", "limitations"):
            assert sec in full["section_diagnostics"]

        # Verify --strict exits 1 on fatal preset/rigor defects
        strict_res = run_cli(
            TRIAGE_SCRIPT,
            ["mock-review", "--input", str(files[preset]), "--subfield-preset", preset, "--strict", "--compact"],
        )
        assert strict_res.returncode == 1, (preset, strict_res.stdout, strict_res.stderr)


def test_t3_m10c_mode2_post_reject_h1_h17_venue_b_and_pdf_handoff(tmp_path: Path) -> None:
    reviews_path = BENCHMARK_DIR / "triage" / "mode2_post_reject_h1_h17_triage.json"
    venue_b_path = BENCHMARK_DIR / "triage" / "mode2_venue_b.json"
    out_path = tmp_path / "post_reject_plan.json"

    res = run_cli(
        TRIAGE_SCRIPT,
        [
            "post-reject",
            "--reviews", str(reviews_path),
            "--venue-a", "NeurIPS 2026",
            "--venue-b", str(venue_b_path),
            "--as-of", "2026-11-22T00:00:00Z",
            "--weeks", "3",
            "--subfield-preset", "nlp_llm",
            "--out", str(out_path),
            "--compact",
        ],
    )
    assert res.returncode == 0, res.stderr
    assert len(res.stdout.strip().encode("utf-8")) < MAX_COMPACT_BYTES
    full = json.loads(out_path.read_text(encoding="utf-8"))

    assert {h["heuristic_id"] for h in full["filtered_illegitimate_heuristics"]} == {"H5", "H7", "H12", "H13", "H16"}
    assert {d["code"] for d in full["substantive_defects"]} == {"M2", "R1", "R5", "G3"}
    assert full["venue_b_checks"]["status"] == "ready_for_resubmission"
    assert set(full["revision_plan"]["schedule"].keys()) == {"Week 1", "Week 2", "Week 3"}
    assert not FABRICATED_ODDS_RE.search(out_path.read_text(encoding="utf-8"))

    # Pipe concise triage verdict into report_latex_pdf.py --strict
    report_in = tmp_path / "triage_summary_for_pdf.json"
    report_payload = {
        "report_type": "venue_audit",
        "lang": "en",
        "title": "Post-Reject Review Triage and Venue B Revision Plan",
        "verdict": {
            "status": "provisional",
            "label": "Ready for 3-week Venue B resubmission",
            "summary": "Filtered 5 heuristics from NeurIPS 2026 reviews and scheduled 4 substantive defects across 3 weeks.",
            "evidence_refs": ["S1", "S2"],
        },
        "key_evidence": [
            {"id": "S1", "claim": "Filtered H5, H7, H12, H13, H16; retained M2, R1, R5, G3 defects.", "locator": "post_reject_plan.json"},
        ],
        "flaws_and_risks": [
            {"id": "F1", "severity": "major", "summary": "Missing 95% confidence intervals and G3 comparison against prior work.", "locator": "post_reject_plan.json#R3.3"},
        ],
        "next_steps": [
            {"step": 1, "action": "Add prior-work comparison in Week 1 and multi-seed CIs in Week 2.", "locator": "post_reject_plan.json#schedule"},
        ],
        "sources": [
            {"id": "S1", "title": "Venue A Reviews and Venue B Resubmission Checklist", "locator": "post_reject_plan.json"},
            {"id": "S2", "title": "Smith et al. (2025) G3 Precedent Reference", "locator": "post_reject_plan.json#R4.1"},
        ],
    }
    report_in.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")
    pdf_out = tmp_path / "triage_report.pdf"
    pdf_res = run_cli(
        REPORT_PDF_SCRIPT,
        ["--input", str(report_in), "--out", str(pdf_out), "--lang", "en", "--strict", "--json", "--compact"],
    )
    assert pdf_res.returncode == 0, (pdf_res.stderr, pdf_res.stdout)
    assert len(pdf_res.stdout.strip().encode("utf-8")) < MAX_COMPACT_BYTES
    assert pdf_out.is_file() and pdf_out.stat().st_size > 1000
    with fitz.open(str(pdf_out)) as doc:
        assert doc.page_count >= 1
        assert "NeurIPS" in doc[0].get_text() or "Venue B" in doc[0].get_text()


def test_t5_m10c_adversarial_nan_bool_tamper_and_claim_audit(tmp_path: Path) -> None:
    # 1. NaN, Infinity, bool, out-of-range --weeks, empty CLI arg, missing file -> exit 2
    nan_p = tmp_path / "nan.json"
    nan_p.write_text('{"scorecard": {"weights": {"importance": 15, "novelty": 20, "soundness": 20, "evidence": 20, "transparency": 15, "clarity": 10}, "ratings": {"importance": NaN, "novelty": 7, "soundness": 7, "evidence": 7, "transparency": 7, "clarity": 7}}}', encoding="utf-8")
    inf_p = tmp_path / "inf.json"
    inf_p.write_text('{"scorecard": {"weights": {"importance": 15, "novelty": 20, "soundness": 20, "evidence": 20, "transparency": 15, "clarity": 10}, "ratings": {"importance": Infinity, "novelty": 7, "soundness": 7, "evidence": 7, "transparency": 7, "clarity": 7}}}', encoding="utf-8")
    bool_p = tmp_path / "bool.json"
    bool_p.write_text('{"scorecard": {"weights": {"importance": 15, "novelty": 20, "soundness": 20, "evidence": 20, "transparency": 15, "clarity": 10}, "ratings": {"importance": true, "novelty": 7, "soundness": 7, "evidence": 7, "transparency": 7, "clarity": 7}}}', encoding="utf-8")
    m2_reviews = BENCHMARK_DIR / "triage" / "mode2_post_reject_h1_h17_triage.json"
    m1_valid = BENCHMARK_DIR / "triage" / "mode1_pre_submission_nlp_llm.json"

    bad_cases = [
        ["mock-review", "--input", str(nan_p)],
        ["mock-review", "--input", str(inf_p)],
        ["mock-review", "--input", str(bool_p)],
        ["mock-review", "--input", ""],
        ["mock-review", "--input", str(tmp_path / "missing.json")],
        ["mock-review", "--input", str(m1_valid), "--out", ""],
        ["post-reject", "--reviews", str(m2_reviews), "--weeks", "1"],
        ["post-reject", "--reviews", str(m2_reviews), "--weeks", "5"],
    ]
    for args in bad_cases:
        r = run_cli(TRIAGE_SCRIPT, args)
        assert r.returncode == 2, (args, r.returncode, r.stderr)
        assert "Traceback" not in r.stderr
        assert "error" in json.loads(r.stderr)

    # 2. Tampered locator -> compare_scorecards & compare_venue_novelty fail closed (exit 1)
    tier2 = json.loads((BENCHMARK_DIR / "tiers" / "tier2_main_accept_cv_multimodal.json").read_text(encoding="utf-8"))
    bad_sc = tier2["scorecards_bundle"]
    bad_sc["profiles"][0]["evidence_locators"]["evidence"] = ['target_tier2_cv_accept.txt#L4 "tampered nonexistent quote"']
    bad_sc_p = tmp_path / "bad_sc.json"
    bad_sc_p.write_text(json.dumps(bad_sc), encoding="utf-8")
    r_csc = run_cli(
        COMPARE_SCORECARDS_SCRIPT,
        [str(bad_sc_p), "--target-id", tier2["target_id"], "--strict-related-panel", "--min-related", "3", "--sources-dir", str(SOURCES_DIR)],
    )
    assert r_csc.returncode == 1

    bad_vn = _refresh_portfolio_timestamps(tier2["venue_portfolio"], iso_utc(0))
    bad_vn["target"]["closest_work_locator"] = 'target_tier2_cv_accept.txt#L1 "tampered nonexistent quote"'
    bad_vn_p = tmp_path / "bad_vn.json"
    bad_vn_p.write_text(json.dumps(bad_vn), encoding="utf-8")
    r_vn = run_cli(
        COMPARE_VENUE_NOVELTY_SCRIPT,
        [str(bad_vn_p), "--portfolio", "--require-panels", "--sources-dir", str(SOURCES_DIR)],
    )
    assert r_vn.returncode == 1

    # 3. claim_audit.py --suite-root . -> 0 findings & all 7 SKILL.md < 50L / < 900 tokens
    ca_res = run_cli(CLAIM_AUDIT_SCRIPT, ["--suite-root", str(REPO_ROOT), "--readme", str(REPO_ROOT / "README.md"), "--json", "-"])
    assert ca_res.returncode == 0, ca_res.stderr
    assert ca_res.json_out["finding_count"] == 0, ca_res.json_out.get("findings")
    for skill in ca_res.json_out.get("skill_token_budgets", []):
        assert skill["lines"] < 50
        assert skill["est_tokens"] < 900


def test_t6_m10c_standalone_cross_tool_cli_gating_and_strict_validation(tmp_path: Path) -> None:
    now_iso = iso_utc(0)
    t5b = json.loads((BENCHMARK_DIR / "tiers" / "tier5_fatal_gate_cv_multimodal.json").read_text(encoding="utf-8"))
    t4 = json.loads((BENCHMARK_DIR / "tiers" / "tier4_workshop_ml_theory.json").read_text(encoding="utf-8"))
    m2_reviews = BENCHMARK_DIR / "triage" / "mode2_post_reject_h1_h17_triage.json"
    m2_venue_b = BENCHMARK_DIR / "triage" / "mode2_venue_b.json"

    # 1. Standalone compare_scorecards (full + --compact) CLI ingestion in Mode 1 & Mode 2
    t5b_bundle = tmp_path / "t5b_bundle.json"
    t5b_bundle.write_text(json.dumps(t5b["scorecards_bundle"]), encoding="utf-8")
    t5b_csc_full = tmp_path / "t5b_csc_full.json"
    assert run_cli(
        COMPARE_SCORECARDS_SCRIPT,
        [str(t5b_bundle), "--target-id", t5b["target_id"], "--strict-related-panel", "--min-related", "3", "--sources-dir", str(SOURCES_DIR), "--out", str(t5b_csc_full)],
    ).returncode == 0
    r_c5 = run_cli(
        COMPARE_SCORECARDS_SCRIPT,
        [str(t5b_bundle), "--target-id", t5b["target_id"], "--strict-related-panel", "--min-related", "3", "--sources-dir", str(SOURCES_DIR), "--compact"],
    )
    assert r_c5.returncode == 0
    t5b_csc_compact = tmp_path / "t5b_csc_compact.json"
    t5b_csc_compact.write_text(r_c5.stdout, encoding="utf-8")

    t5b_only_sc = tmp_path / "t5b_only_sc.json"
    t5b_only_sc.write_text(json.dumps({"target_id": t5b["target_id"], "scorecard": t5b["scorecard"]}), encoding="utf-8")

    for csc_p in (t5b_csc_full, t5b_csc_compact):
        mr_solo = run_cli(TRIAGE_SCRIPT, ["mock-review", "--scorecard", str(csc_p), "--venue-tier", "top_tier_flagship", "--strict"])
        assert mr_solo.returncode == 1, mr_solo.stdout
        assert mr_solo.json_out["overall_verdict"] == "fatal_gate_triggered"
        assert mr_solo.json_out["submission_readiness"]["fatal_gate_triggered"] is True

        mr_pair = run_cli(TRIAGE_SCRIPT, ["mock-review", "--input", str(t5b_only_sc), "--scorecard", str(csc_p), "--venue-tier", "top_tier_flagship", "--strict"])
        assert mr_pair.returncode == 1
        assert mr_pair.json_out["merit_vs_publishability"]["scientific_merit_score"] == 6.93
        assert mr_pair.json_out["worst_case_sensitivity"]["worst_case_reviewer_floor"] == 6.05

        m2_csc = run_cli(TRIAGE_SCRIPT, ["post-reject", "--reviews", str(m2_reviews), "--venue-b", str(m2_venue_b), "--scorecard", str(csc_p), "--as-of", "2026-11-22T00:00:00Z", "--strict"])
        assert m2_csc.returncode == 1
        assert m2_csc.json_out["venue_b_checks"]["status"] == "resubmission_blocked"

    # 2. Standalone compare_venue_novelty --portfolio (full + --compact) CLI ingestion
    t4_port = tmp_path / "t4_port.json"
    t4_port.write_text(json.dumps(_refresh_portfolio_timestamps(t4["venue_portfolio"], now_iso)), encoding="utf-8")
    t4_vn_full = tmp_path / "t4_vn_full.json"
    assert run_cli(
        COMPARE_VENUE_NOVELTY_SCRIPT,
        [str(t4_port), "--portfolio", "--require-panels", "--sources-dir", str(SOURCES_DIR), "--out", str(t4_vn_full)],
    ).returncode == 0
    r_vn4 = run_cli(
        COMPARE_VENUE_NOVELTY_SCRIPT,
        [str(t4_port), "--portfolio", "--require-panels", "--sources-dir", str(SOURCES_DIR), "--compact"],
    )
    assert r_vn4.returncode == 0
    t4_vn_compact = tmp_path / "t4_vn_compact.json"
    t4_vn_compact.write_text(r_vn4.stdout, encoding="utf-8")

    for vn_p in (t4_vn_full, t4_vn_compact):
        mr_vn = run_cli(TRIAGE_SCRIPT, ["mock-review", "--venue-novelty", str(vn_p), "--venue-tier", "top_tier_flagship", "--strict"])
        assert mr_vn.returncode == 1
        assert mr_vn.json_out["overall_verdict"] == "rejected_below_venue_tier"
        assert mr_vn.json_out["venue_tier_fit"]["rejected_below_venue_tier"] is True

    # 3. Real check_venue_plan.py output -> Mode 1 & Mode 2 blocking
    vp_script = SCRIPTS_DIR / "check_venue_plan.py"
    vp_dossier = tmp_path / "vp_dossier.json"
    vp_dossier.write_text(
        json.dumps({
            "venue": "ICLR",
            "edition": "2027",
            "track": "Main Track",
            "official_cfp_url": "https://iclr.cc/Conferences/2027",
            "checked_at": "2026-11-22T00:00:00Z",
            "user_timezone": "UTC",
            "milestones": {
                "abstract_registration": "2026-11-24T23:59:00Z",
                "full_paper": "2026-11-25T23:59:00Z",
            },
            "presentation_mode": "online",
            "budget": 500,
            "budget_currency": "USD",
            "currency": "USD",
            "fees": [
                {"name": "sub", "category": "submission", "mandatory": True, "amount": 0, "source_url": "https://iclr.cc/Conferences/2027", "checked_at": "2026-11-22T00:00:00Z"},
                {"name": "pub", "category": "publication", "mandatory": True, "amount": 0, "source_url": "https://iclr.cc/Conferences/2027", "checked_at": "2026-11-22T00:00:00Z"},
                {"name": "reg", "category": "author_registration", "mandatory": True, "amount": 800, "source_url": "https://iclr.cc/Conferences/2027", "checked_at": "2026-11-22T00:00:00Z"},
                {"name": "ovl", "category": "overlength", "mandatory": True, "amount": 0, "source_url": "https://iclr.cc/Conferences/2027", "checked_at": "2026-11-22T00:00:00Z"},
                {"name": "tax", "category": "tax", "mandatory": True, "amount": 0, "source_url": "https://iclr.cc/Conferences/2027", "checked_at": "2026-11-22T00:00:00Z"},
            ],
        }),
        encoding="utf-8",
    )
    vp_out = tmp_path / "vp_out.json"
    assert run_cli(vp_script, [str(vp_dossier), "--out", str(vp_out)]).returncode == 0
    r_vp1 = run_cli(TRIAGE_SCRIPT, ["mock-review", "--venue-plan", str(vp_out), "--strict"])
    assert r_vp1.returncode == 1
    assert r_vp1.json_out["overall_verdict"] == "fatal_gate_triggered"

    r_vp2 = run_cli(TRIAGE_SCRIPT, ["post-reject", "--reviews", str(m2_reviews), "--venue-b", "ICLR", "--venue-plan", str(vp_out), "--as-of", "2026-11-22T00:00:00Z", "--strict"])
    assert r_vp2.returncode == 1
    vb_chk = r_vp2.json_out["venue_b_checks"]
    assert vb_chk["status"] == "resubmission_blocked"
    assert vb_chk["days_remaining"] == 3
    assert "venue_plan:within_budget_false" in vb_chk["blocking_reasons"]
    assert "venue_plan:cfp_not_verified" in vb_chk["blocking_reasons"]

    # 4. Null rating dimension + cap=0 compact ledger + non-dict JSON root exit 2
    null_sc = tmp_path / "null_sc.json"
    null_sc.write_text(json.dumps({"scorecard": {"weights": t5b["scorecard"]["weights"], "ratings": {**t5b["scorecard"]["ratings"], "soundness": 8, "evidence": None}}}), encoding="utf-8")
    r_null = run_cli(TRIAGE_SCRIPT, ["mock-review", "--input", str(null_sc), "--venue-tier", "top_tier_flagship", "--strict"])
    assert r_null.json_out["overall_verdict"] == "major_revisions_required"

    led_c = tmp_path / "led_c.json"
    led_c.write_text(json.dumps({"compact": True, "status": "structural_issues", "total_issues": 2, "issues": []}), encoding="utf-8")
    rig_f = tmp_path / "rig_f.json"
    rig_f.write_text(json.dumps({"schema": "experiment_rigor_repro_v1", "verdict": "FAIL", "missing": ["seeds"]}), encoding="utf-8")
    base_d = tmp_path / "base.json"
    base_d.write_text(json.dumps({"target_id": "x"}), encoding="utf-8")
    r_led = run_cli(TRIAGE_SCRIPT, ["mock-review", "--input", str(base_d), "--ledger", str(led_c), "--rigor", str(rig_f)])
    assert r_led.returncode == 0
    assert {"check_manuscript_ledger", "check_experiment_rigor"}.issubset({d["source_tool"] for d in r_led.json_out["defect_ledger"]})

    bad_arr = tmp_path / "bad_arr.json"
    bad_arr.write_text("[]", encoding="utf-8")
    for flag in ("--scorecard", "--venue-novelty", "--ledger", "--venue-plan", "--sections"):
        assert run_cli(TRIAGE_SCRIPT, ["mock-review", "--input", str(base_d), flag, str(bad_arr)]).returncode == 2


def test_t7_m10c_round2_cross_tool_tier_precedence_and_adversarial_cli(tmp_path: Path) -> None:
    w = {"importance": 15, "novelty": 20, "soundness": 20, "evidence": 20, "transparency": 15, "clarity": 10}
    t3 = json.loads((BENCHMARK_DIR / "tiers" / "tier3_borderline_ai_systems.json").read_text(encoding="utf-8"))
    t4 = json.loads((BENCHMARK_DIR / "tiers" / "tier4_workshop_ml_theory.json").read_text(encoding="utf-8"))
    t5b = json.loads((BENCHMARK_DIR / "tiers" / "tier5_fatal_gate_cv_multimodal.json").read_text(encoding="utf-8"))
    m2_reviews = BENCHMARK_DIR / "triage" / "mode2_post_reject_h1_h17_triage.json"

    # 1. score_math (6.85 soundness=5) and compare_scorecards full+compact (6.05 evidence=5) must reject top_tier_flagship --strict (exit 1)
    s5_in = tmp_path / "s5_in.json"
    s5_in.write_text(json.dumps({"weights": w, "ratings": {"importance": 8, "novelty": 7, "soundness": 5, "evidence": 8, "transparency": 7, "clarity": 6}}), encoding="utf-8")
    sm_s5 = run_cli(SCORE_MATH_SCRIPT, [str(s5_in)])
    assert sm_s5.returncode == 0
    sm_s5_p = tmp_path / "sm_s5.json"
    sm_s5_p.write_text(sm_s5.stdout, encoding="utf-8")

    r_s5_m1 = run_cli(TRIAGE_SCRIPT, ["mock-review", "--scorecard", str(sm_s5_p), "--venue-tier", "top_tier_flagship", "--strict"])
    assert r_s5_m1.returncode == 1
    assert r_s5_m1.json_out["overall_verdict"] == "rejected_below_venue_tier"
    assert r_s5_m1.json_out["venue_tier_fit"]["recommended_matched_tier"] == "q2_q3_or_tier_b"

    r_s5_m2 = run_cli(TRIAGE_SCRIPT, ["post-reject", "--reviews", str(m2_reviews), "--venue-b", "ICLR", "--scorecard", str(sm_s5_p), "--as-of", "2026-11-22T00:00:00Z", "--strict"])
    assert r_s5_m2.returncode == 1
    assert r_s5_m2.json_out["venue_b_checks"]["status"] == "resubmission_blocked"

    p2 = {"id": "p2", "reading_basis": "full_text", "closest_work": ["p1"], "evidence_locators": {"soundness": ["x"]}, "ratings": {"importance": 7, "novelty": 7, "soundness": 7, "evidence": 7, "transparency": 7, "clarity": 7}}
    e5_bun = tmp_path / "e5_bun.json"
    e5_bun.write_text(json.dumps({"weight_scenarios": [w], "profiles": [{"id": "p1", "reading_basis": "full_text", "ratings": {"importance": 7, "novelty": 6, "soundness": 6, "evidence": 5, "transparency": 6, "clarity": 7}}, p2]}), encoding="utf-8")
    e5_full_p = tmp_path / "e5_full.json"
    e5_comp_p = tmp_path / "e5_comp.json"
    assert run_cli(COMPARE_SCORECARDS_SCRIPT, [str(e5_bun), "--target-id", "p1", "--out", str(e5_full_p)]).returncode == 1
    e5_comp_r = run_cli(COMPARE_SCORECARDS_SCRIPT, [str(e5_bun), "--target-id", "p1", "--compact"])
    e5_comp_p.write_text(e5_comp_r.stdout, encoding="utf-8")
    for p in (e5_full_p, e5_comp_p):
        r_e5 = run_cli(TRIAGE_SCRIPT, ["mock-review", "--scorecard", str(p), "--venue-tier", "top_tier_flagship", "--strict"])
        assert r_e5.returncode == 1
        assert r_e5.json_out["overall_verdict"] == "rejected_below_venue_tier"

    # Tier 3 (6.35, all >= 6) via compare_scorecards must stay non-rejected
    t3_bun_p = tmp_path / "t3_bun.json"
    t3_bun_p.write_text(json.dumps(t3["scorecards_bundle"]), encoding="utf-8")
    t3_csc_p = tmp_path / "t3_csc.json"
    assert run_cli(COMPARE_SCORECARDS_SCRIPT, [str(t3_bun_p), "--target-id", t3["target_id"], "--strict-related-panel", "--min-related", "3", "--sources-dir", str(SOURCES_DIR), "--out", str(t3_csc_p)]).returncode == 0
    r_t3 = run_cli(TRIAGE_SCRIPT, ["mock-review", "--scorecard", str(t3_csc_p), "--venue-tier", "top_tier_flagship", "--strict"])
    assert r_t3.returncode == 0
    assert r_t3.json_out["venue_tier_fit"]["rejected_below_venue_tier"] is False
    assert r_t3.json_out["venue_tier_fit"]["recommended_matched_tier"] == "q1_or_tier_a"

    # 2. Explicit --scorecard overrides stale --input embedded scorecard
    t5b_bun_p = tmp_path / "t5b_bun.json"
    t5b_bun_p.write_text(json.dumps(t5b["scorecards_bundle"]), encoding="utf-8")
    t5b_csc_p = tmp_path / "t5b_csc.json"
    assert run_cli(COMPARE_SCORECARDS_SCRIPT, [str(t5b_bun_p), "--target-id", t5b["target_id"], "--strict-related-panel", "--min-related", "3", "--sources-dir", str(SOURCES_DIR), "--out", str(t5b_csc_p)]).returncode == 0
    stale_in = tmp_path / "stale_in.json"
    stale_in.write_text(json.dumps({"target_id": t5b["target_id"], "scorecard": {"weights": w, "ratings": {"importance": 8, "novelty": 8, "soundness": 7, "evidence": 8, "transparency": 8, "clarity": 8}}}), encoding="utf-8")
    r_prec = run_cli(TRIAGE_SCRIPT, ["mock-review", "--input", str(stale_in), "--scorecard", str(t5b_csc_p), "--venue-tier", "top_tier_flagship", "--strict"])
    assert r_prec.returncode == 1
    assert r_prec.json_out["overall_verdict"] == "fatal_gate_triggered"
    assert r_prec.json_out["venue_tier_fit"]["rejected_below_venue_tier"] is True
    assert r_prec.json_out["venue_tier_fit"]["recommended_matched_tier"] == "none_hold_for_rework"

    # 3. Mode 2 --venue-plan fallback without --venue-b
    plain_revs = tmp_path / "plain_revs.json"
    plain_revs.write_text(json.dumps(json.loads(m2_reviews.read_text(encoding="utf-8"))["comments"]), encoding="utf-8")
    vp_ok = tmp_path / "vp_ok.json"
    vp_ok.write_text(json.dumps({"venue": "ICLR", "track": "Main Track", "within_budget": True, "cfp_verified": True, "milestones_user_timezone": {"full_paper": "2026-12-20T23:59:00+00:00"}}), encoding="utf-8")
    t4_sc = tmp_path / "t4_sc.json"
    t4_sc.write_text(json.dumps(t4["scorecard"]), encoding="utf-8")
    r_vp_fb = run_cli(TRIAGE_SCRIPT, ["post-reject", "--reviews", str(plain_revs), "--venue-plan", str(vp_ok), "--scorecard", str(t4_sc), "--as-of", "2026-11-22T00:00:00Z", "--strict"])
    assert r_vp_fb.returncode == 1
    assert r_vp_fb.json_out["venue_b_checks"]["venue_b_name"] == "ICLR"
    assert r_vp_fb.json_out["venue_b_checks"]["venue_b_tier"] == "top_tier_flagship"
    assert r_vp_fb.json_out["venue_b_checks"]["status"] == "resubmission_blocked"

    # 4. --compact < 4096B on 4040-char ASCII & multi-byte Unicode --out + adversarial exit-2 checks
    base_p = tmp_path / "base.json"
    base_p.write_text(json.dumps({"target_id": "x"}), encoding="utf-8")
    long_ascii = tmp_path.joinpath(*(["a" * 190] * 21), "r.json")
    r_la = run_cli(TRIAGE_SCRIPT, ["mock-review", "--input", str(base_p), "--out", str(long_ascii), "--compact"])
    assert r_la.returncode == 0
    assert len(r_la.stdout.strip().encode("utf-8")) < MAX_COMPACT_BYTES
    assert long_ascii.is_file()

    bad_precomp = tmp_path / "bad_precomp.json"
    bad_precomp.write_text(json.dumps({"submission_readiness": {"band": "clear_accept_main_track"}, "weighted_unrounded": "NaN"}), encoding="utf-8")
    r_bp = run_cli(TRIAGE_SCRIPT, ["mock-review", "--scorecard", str(bad_precomp)])
    assert r_bp.returncode == 2 and "Traceback" not in r_bp.stderr

    bad_nested = tmp_path / "bad_nested.json"
    bad_nested.write_text(json.dumps({"venue_novelty": {"venue": {"name": "ICLR"}, "venue_quality_context": [1, 2]}}), encoding="utf-8")
    r_bn = run_cli(TRIAGE_SCRIPT, ["mock-review", "--input", str(bad_nested)])
    assert r_bn.returncode == 2 and "Traceback" not in r_bn.stderr

    bad_anc = tmp_path / "bad_anc.json"
    bad_anc.write_text(json.dumps([{"anchor_id": "a1", "overall_score": 7.5, "ratings": {"novelty": True}}]), encoding="utf-8")
    r_ba = run_cli(TRIAGE_SCRIPT, ["mock-review", "--input", str(base_p), "--anchors", str(bad_anc)])
    assert r_ba.returncode == 2 and "Traceback" not in r_ba.stderr


def test_t8_m10c_round3_compact_boundary_and_same_weighted_precedence(tmp_path: Path) -> None:
    w = {"importance": 15, "novelty": 20, "soundness": 20, "evidence": 20, "transparency": 15, "clarity": 10}
    m2_reviews = BENCHMARK_DIR / "triage" / "mode2_post_reject_h1_h17_triage.json"
    locs = {dim: [f"paper.txt#L1 \"evidence for {dim}\""] for dim in ("importance", "novelty", "soundness", "evidence", "transparency", "clarity")}

    def _write_compact(name: str, p1_ratings: dict[str, int]) -> Path:
        others = ["p2", "p3", "p4"]
        profiles = [{"id": "p1", "reading_basis": "full_text", "closest_work": others, "evidence_locators": locs, "ratings": p1_ratings}]
        for oid in others:
            profiles.append({
                "id": oid,
                "reading_basis": "full_text",
                "closest_work": ["p1"],
                "evidence_locators": locs,
                "ratings": {"importance": 7, "novelty": 7, "soundness": 7, "evidence": 7, "transparency": 7, "clarity": 7},
            })
        bun_p = tmp_path / f"{name}_bun.json"
        bun_p.write_text(json.dumps({"weight_scenarios": [w], "profiles": profiles}), encoding="utf-8")
        res = run_cli(COMPARE_SCORECARDS_SCRIPT, [str(bun_p), "--compact"])
        assert res.returncode == 0, res.stderr
        comp_p = tmp_path / f"{name}_comp.json"
        comp_p.write_text(res.stdout, encoding="utf-8")
        return comp_p

    # 1. A_675_ev5 (6.75, evidence=5) via compare_scorecards --compact without --target-id
    a675_comp = _write_compact("a675", {"importance": 8, "novelty": 7, "soundness": 7, "evidence": 5, "transparency": 7, "clarity": 7})
    r_a1 = run_cli(TRIAGE_SCRIPT, ["mock-review", "--scorecard", str(a675_comp), "--venue-tier", "top_tier_flagship", "--strict"])
    assert r_a1.returncode == 1, r_a1.stdout
    assert r_a1.json_out["overall_verdict"] == "rejected_below_venue_tier"
    assert r_a1.json_out["venue_tier_fit"]["rejected_below_venue_tier"] is True
    assert r_a1.json_out["venue_tier_fit"]["recommended_matched_tier"] == "q2_q3_or_tier_b"

    r_a2 = run_cli(TRIAGE_SCRIPT, ["post-reject", "--reviews", str(m2_reviews), "--venue-b", "ICLR", "--scorecard", str(a675_comp), "--as-of", "2026-11-22T00:00:00Z", "--strict"])
    assert r_a2.returncode == 1, r_a2.stdout
    assert r_a2.json_out["venue_b_checks"]["status"] == "resubmission_blocked"
    assert r_a2.json_out["venue_b_checks"]["venue_b_tier_fit"]["rejected_below_venue_tier"] is True
    assert r_a2.json_out["venue_b_checks"]["venue_b_tier_fit"]["recommended_matched_tier"] == "q2_q3_or_tier_b"

    # 2. nov5_660 (6.60, novelty=5, soundness>=6, evidence>=6) -> valid q1_or_tier_a, NOT rejected
    nov5_comp = _write_compact("nov5", {"importance": 7, "novelty": 5, "soundness": 7, "evidence": 7, "transparency": 7, "clarity": 7})
    r_n1 = run_cli(TRIAGE_SCRIPT, ["mock-review", "--scorecard", str(nov5_comp), "--venue-tier", "top_tier_flagship", "--strict"])
    assert r_n1.returncode == 0, r_n1.stdout
    assert r_n1.json_out["overall_verdict"] == "ready_for_submission_check"
    assert r_n1.json_out["venue_tier_fit"]["rejected_below_venue_tier"] is False
    assert r_n1.json_out["venue_tier_fit"]["recommended_matched_tier"] == "q1_or_tier_a"

    r_n2 = run_cli(TRIAGE_SCRIPT, ["post-reject", "--reviews", str(m2_reviews), "--venue-b", "ICLR", "--scorecard", str(nov5_comp), "--as-of", "2026-11-22T00:00:00Z", "--strict"])
    assert r_n2.returncode == 0, r_n2.stdout
    assert r_n2.json_out["venue_b_checks"]["status"] == "ready_for_resubmission"
    assert r_n2.json_out["venue_b_checks"]["venue_b_tier_fit"]["rejected_below_venue_tier"] is False
    assert r_n2.json_out["venue_b_checks"]["venue_b_tier_fit"]["recommended_matched_tier"] == "q1_or_tier_a"

    # 3. Same weighted_unrounded=6.85 in --input (all dims >= 6) + --scorecard compare_scorecards --compact (soundness=5)
    s5_comp = _write_compact("s5_685", {"importance": 8, "novelty": 7, "soundness": 5, "evidence": 8, "transparency": 7, "clarity": 6})
    same_w_in = tmp_path / "same_w.json"
    same_w_in.write_text(json.dumps({
        "target_id": "p1",
        "scorecard": {"weights": w, "ratings": {"importance": 7, "novelty": 7, "soundness": 7, "evidence": 7, "transparency": 6, "clarity": 7}},
    }), encoding="utf-8")
    r_sw = run_cli(TRIAGE_SCRIPT, ["mock-review", "--input", str(same_w_in), "--scorecard", str(s5_comp), "--venue-tier", "top_tier_flagship", "--strict"])
    assert r_sw.returncode == 1, r_sw.stdout
    assert r_sw.json_out["overall_verdict"] == "rejected_below_venue_tier"
    assert r_sw.json_out["venue_tier_fit"]["rejected_below_venue_tier"] is True
    assert r_sw.json_out["venue_tier_fit"]["recommended_matched_tier"] == "q2_q3_or_tier_b"


def test_t9_m10c_round4_readiness_type_validation_reproducers(tmp_path: Path) -> None:
    m2_reviews = BENCHMARK_DIR / "triage" / "mode2_post_reject_h1_h17_triage.json"
    cases = [
        (
            "exact_repro",
            {
                "weighted_unrounded": "6.75",
                "overall": 7,
                "submission_readiness": {
                    "band": 123,
                    "recommended_matched_tier": {"bad": 1},
                    "bottleneck_dimensions": ["evidence"],
                    "fatal_gate_triggered": False,
                },
            },
        ),
        ("band_bool", {"weighted_unrounded": "6.75", "overall": 7, "submission_readiness": {"band": True}}),
        ("band_list", {"weighted_unrounded": "6.75", "overall": 7, "submission_readiness": {"band": ["x"]}}),
        (
            "rec_tier_dict",
            {
                "weighted_unrounded": "6.75",
                "overall": 7,
                "submission_readiness": {
                    "band": "borderline_top_tier_competitive_findings_tier_a",
                    "recommended_matched_tier": {"bad": 1},
                },
            },
        ),
        (
            "rec_tier_no_band",
            {
                "weighted_unrounded": "6.75",
                "overall": 7,
                "submission_readiness": {
                    "recommended_matched_tier": 123,
                    "bottleneck_dimensions": ["evidence"],
                    "fatal_gate_triggered": False,
                },
            },
        ),
        (
            "fatal_dims_str",
            {
                "weighted_unrounded": "6.75",
                "overall": 7,
                "submission_readiness": {
                    "band": "not_ready_fatal_gate",
                    "fatal_gate_triggered": True,
                    "fatal_dimensions": "soundness",
                },
            },
        ),
        (
            "bdims_dict_elem",
            {
                "weighted_unrounded": "6.75",
                "overall": 7,
                "submission_readiness": {
                    "band": "borderline_top_tier_competitive_findings_tier_a",
                    "bottleneck_dimensions": [{}],
                },
            },
        ),
        (
            "csc_band_int",
            {
                "status": "structurally_comparable",
                "submission_readiness": {
                    "p1": {"band": 123, "weighted_unrounded": "6.75", "recommended_matched_tier": {"bad": 1}}
                },
            },
        ),
    ]

    for label, payload in cases:
        sp = tmp_path / f"{label}.json"
        sp.write_text(json.dumps(payload), encoding="utf-8")

        r1 = run_cli(
            TRIAGE_SCRIPT,
            ["mock-review", "--scorecard", str(sp), "--venue-tier", "top_tier_flagship", "--strict"],
        )
        assert r1.returncode == 2, (label, r1.returncode, r1.stdout, r1.stderr)
        assert "Traceback" not in r1.stderr
        assert "error" in json.loads(r1.stderr)

        r2 = run_cli(
            TRIAGE_SCRIPT,
            [
                "post-reject",
                "--reviews", str(m2_reviews),
                "--venue-b", "ICLR",
                "--scorecard", str(sp),
                "--as-of", "2026-11-22T00:00:00Z",
                "--strict",
            ],
        )
        assert r2.returncode == 2, (label, r2.returncode, r2.stdout, r2.stderr)
        assert "Traceback" not in r2.stderr
        assert "error" in json.loads(r2.stderr)

    # --input embedded scorecard & --venue-novelty target_readiness must also reject exit 2
    bad_in = tmp_path / "bad_in.json"
    bad_in.write_text(json.dumps({"scorecard": cases[0][1]}), encoding="utf-8")
    r_in = run_cli(TRIAGE_SCRIPT, ["mock-review", "--input", str(bad_in), "--venue-tier", "top_tier_flagship", "--strict"])
    assert r_in.returncode == 2 and "Traceback" not in r_in.stderr and "error" in json.loads(r_in.stderr)

    bad_vn = tmp_path / "bad_vn.json"
    bad_vn.write_text(json.dumps({"mode": "portfolio", "target_readiness": {"band": 123, "recommended_matched_tier": {"bad": 1}}}), encoding="utf-8")
    r_vn = run_cli(TRIAGE_SCRIPT, ["mock-review", "--venue-novelty", str(bad_vn), "--venue-tier", "top_tier_flagship", "--strict"])
    assert r_vn.returncode == 2 and "Traceback" not in r_vn.stderr and "error" in json.loads(r_vn.stderr)

