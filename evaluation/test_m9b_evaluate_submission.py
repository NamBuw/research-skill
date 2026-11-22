"""Unit and integration tests for M9B evaluate_submission.py."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "research-scientist" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


evaluate_submission = _load_module("evaluate_submission", SCRIPTS_DIR / "evaluate_submission.py")
score_math = _load_module("score_math", SCRIPTS_DIR / "score_math.py")
claim_audit = _load_module("claim_audit", SCRIPTS_DIR / "claim_audit.py")

FABRICATED_ODDS_RE = re.compile(
    r"\b\d+(?:\.\d+)?%\s*(?:acceptance|chance|odds|probability)",
    re.IGNORECASE,
)


def _weights():
    return {"importance": 15, "novelty": 20, "soundness": 20, "evidence": 20, "transparency": 15, "clarity": 10}


def _ratings(vals):
    return dict(zip(score_math.DIMENSIONS, vals))


def _run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "evaluate_submission.py"), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


class TestM9BEvaluateSubmission(unittest.TestCase):
    def test_happy_path_ready_to_submit_and_native_scales(self):
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            sc = td / "scorecard.json"
            sc.write_text(json.dumps({"weights": _weights(), "ratings": _ratings((8, 7, 8, 7, 7, 8))}), encoding="utf-8")

            rigor = td / "repro.json"
            rigor.write_text(json.dumps({"schema": "experiment_rigor_repro_v1", "verdict": "PASS", "missing": [], "warnings": []}), encoding="utf-8")

            ledger = td / "ledger.json"
            ledger.write_text(json.dumps({"status": "structure_passed", "issues": [], "grandiose_findings": []}), encoding="utf-8")

            art = td / "art.json"
            art.write_text(json.dumps({"schema": "artifact_readiness_v1", "verdict": "PASS", "ready_to_submit": True, "recommended_transparency_cap": None, "blocking_reasons": []}), encoding="utf-8")

            vp = td / "venue_plan.json"
            vp.write_text(json.dumps({
                "venue": "NeurIPS",
                "edition": "2027",
                "cfp_verified": True,
                "within_budget": True,
                "missing_mandatory_costs": [],
                "unverified_fee_evidence": [],
                "stale_fee_evidence": [],
                "source_issues": [],
                "warnings": [],
                "backward_schedule": {"status": "start_not_yet_past_under_serial_assumption"},
            }), encoding="utf-8")

            vs = td / "venue_sources.json"
            vs.write_text(json.dumps({
                "venue": "NeurIPS",
                "verification_passed": True,
                "source_text_status": "all_supplied_critical_quotes_found",
                "blocking_source_issues": [],
                "critical_fields_without_matched_quote": [],
                "claims": [{"field": "deadline", "status": "quote_found"}],
            }), encoding="utf-8")

            out_path = td / "sub" / "report.json"
            res = _run_cli([
                "--scorecard", str(sc),
                "--rigor", str(rigor),
                "--ledger", str(ledger),
                "--artifact-readiness", str(art),
                "--venue-plan", str(vp),
                "--venue-sources", str(vs),
                "--target-venue", "NeurIPS",
                "--target-venue-tier", "top_tier_flagship",
                "--out", str(out_path),
            ])
            self.assertEqual(res.returncode, 0, res.stderr + res.stdout)
            data = json.loads(res.stdout)
            self.assertTrue(data["ready_to_submit"])
            self.assertEqual(data["verdict"], "READY_TO_SUBMIT")
            self.assertFalse(data["cross_tool_fatal_gate"])
            self.assertFalse(data["desk_reject_blocked"])
            self.assertFalse(data["no_viable_venue_in_portfolio"])
            self.assertEqual(data["overall"], 7)
            self.assertEqual(data["weighted_unrounded"], "7.45")
            self.assertTrue(out_path.is_file())
            self.assertIsNone(FABRICATED_ODDS_RE.search(res.stdout))

            ns = data["score_evaluation"]["native_scales"]
            self.assertIn("arr_1_5", ns)
            self.assertIn("neurips_1_6", ns)
            self.assertIn("iclr_1_10", ns)
            self.assertIn("journal_decision_band", ns)
            self.assertGreaterEqual(ns["arr_1_5"]["score"], 3.5)
            self.assertGreaterEqual(ns["neurips_1_6"]["score"], 4.5)
            self.assertGreaterEqual(ns["iclr_1_10"]["score"], 7.0)
            self.assertIsNotNone(data["score_evaluation"]["scientific_merit_score"])
            self.assertIsNotNone(data["score_evaluation"]["publishability_packaging_score"])
            self.assertTrue(data["score_evaluation"]["what_if_roi"])

    def test_rigor_contamination_engineering_and_manifest_trigger_fatal_caps(self):
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            sc = td / "scorecard.json"
            sc.write_text(json.dumps({"weights": _weights(), "ratings": _ratings((9, 8, 9, 9, 8, 8))}), encoding="utf-8")

            contam = td / "contam.json"
            contam.write_text(json.dumps({"schema": "experiment_rigor_contamination_v1", "verdict": "CONTAMINATION_DETECTED", "contaminated_eval_count": 3}), encoding="utf-8")

            repro = td / "repro.json"
            repro.write_text(json.dumps({"schema": "experiment_rigor_repro_v1", "verdict": "FAIL", "missing": ["SEED"], "warnings": []}), encoding="utf-8")

            eng = td / "eng.json"
            eng.write_text(json.dumps({
                "schema": "research_scientist_engineering_diagnostics_v1",
                "verdict": "ENGINEERING_BUG_DETECTED",
                "findings": [{"category": "preprocessing_before_split_leakage", "severity": "error"}],
            }), encoding="utf-8")

            exp = td / "exp_manifest.json"
            exp.write_text(json.dumps({
                "status": "invalid",
                "files_verified": False,
                "errors": ["run1: sha256 mismatch for result_artifact_path (cand.json)"],
            }), encoding="utf-8")

            rliable = td / "rliable.json"
            rliable.write_text(json.dumps({
                "schema": "experiment_rigor_rliable_v1",
                "verdict": "FAIL",
                "critical": True,
                "methods": {"cand": {"n_seeds": 2}},
                "warnings": ["underpowered_seeds:cand:n_seeds=2<3"],
            }), encoding="utf-8")

            res = _run_cli([
                "--scorecard", str(sc),
                "--rigor", str(contam),
                "--rigor", str(repro),
                "--rigor", str(rliable),
                "--engineering-diagnostics", str(eng),
                "--experiment-manifest", str(exp),
            ])
            self.assertEqual(res.returncode, 1, res.stderr + res.stdout)
            data = json.loads(res.stdout)
            self.assertFalse(data["ready_to_submit"])
            self.assertTrue(data["cross_tool_fatal_gate"])
            self.assertEqual(data["verdict"], "BLOCKED_CROSS_TOOL_FATAL_GATE")
            post_r = data["score_evaluation"]["ratings_post_cap"]
            self.assertLessEqual(post_r["evidence"], 4)
            self.assertLessEqual(post_r["soundness"], 4)
            self.assertEqual(data["band"], "not_ready_fatal_gate")
            self.assertEqual(data["recommended_matched_tier"], "none_hold_for_rework")
            self.assertLess(float(data["weighted_unrounded"]), 8.55)
            self.assertEqual(data["score_evaluation"]["ac_synthesis"]["decision"], "hold_reject_fatal_gate")

    def test_ledger_and_artifact_readiness_caps(self):
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            sc = td / "scorecard.json"
            sc.write_text(json.dumps({"weights": _weights(), "ratings": _ratings((8, 7, 8, 8, 8, 8))}), encoding="utf-8")

            ledger = td / "ledger.json"
            ledger.write_text(json.dumps({
                "status": "structural_issues",
                "issues": ["material_claim_without_verified_locator:C1", "grandiose_branding_detected:M1"],
                "grandiose_findings": [{"method_id": "M1", "token": "Unified Framework"}],
                "argument_audit": {
                    "enabled": True,
                    "recommended_transparency_cap": 3,
                    "recommended_evidence_cap": 4,
                },
            }), encoding="utf-8")

            art_warn = td / "art_warn.json"
            art_warn.write_text(json.dumps({
                "schema": "artifact_readiness_v1",
                "verdict": "WARN",
                "ready_to_submit": True,
                "recommended_transparency_cap": 5,
                "blocking_reasons": [],
                "warnings": ["reproducibility/unpinned-dependencies:requirements.txt"],
            }), encoding="utf-8")

            res = _run_cli(["--scorecard", str(sc), "--ledger", str(ledger), "--artifact-readiness", str(art_warn)])
            self.assertEqual(res.returncode, 1)
            data = json.loads(res.stdout)
            self.assertFalse(data["ready_to_submit"])
            self.assertTrue(data["cross_tool_fatal_gate"])
            # min(3 from ledger, 5 from WARN) == 3
            self.assertEqual(data["score_evaluation"]["ratings_post_cap"]["transparency"], 3)
            self.assertEqual(data["score_evaluation"]["ratings_post_cap"]["evidence"], 4)

            # Check WARN alone caps transparency <= 5 without forcing fatal gate
            ledger_ok = td / "ledger_ok.json"
            ledger_ok.write_text(json.dumps({"status": "structure_passed", "issues": [], "grandiose_findings": []}), encoding="utf-8")
            res_warn = _run_cli(["--scorecard", str(sc), "--ledger", str(ledger_ok), "--artifact-readiness", str(art_warn)])
            self.assertEqual(res_warn.returncode, 0, res_warn.stderr + res_warn.stdout)
            data_warn = json.loads(res_warn.stdout)
            self.assertTrue(data_warn["ready_to_submit"])
            self.assertEqual(data_warn["score_evaluation"]["ratings_post_cap"]["transparency"], 5)

    def test_desk_reject_rules_combine_preflight_artifact_novelty_and_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            sc = td / "scorecard.json"
            sc.write_text(json.dumps({"weights": _weights(), "ratings": _ratings((8, 7, 8, 7, 7, 8))}), encoding="utf-8")

            preflight = td / "preflight_anon.json"
            preflight.write_text(json.dumps({
                "schema": "submission_anonymization_v1",
                "verdict": "FAIL",
                "summary": {"ERROR": 1, "WARN": 0},
                "findings": [{"check": "anonymization/author-block", "severity": "ERROR"}],
            }), encoding="utf-8")

            art = td / "art_anon.json"
            art.write_text(json.dumps({
                "schema": "artifact_readiness_v1",
                "verdict": "FAIL",
                "ready_to_submit": False,
                "recommended_transparency_cap": 3,
                "blocking_reasons": ["anonymization/git-remote-leak:.git/config"],
                "summary": {"by_category": {"anonymization": {"status": "FAIL", "fail": 1, "warn": 0}}},
            }), encoding="utf-8")

            policy = td / "policy.json"
            policy.write_text(json.dumps({
                "page_count": 11,
                "page_limit": 9,
                "template": "iclr2025",
                "expected_template": "neurips_2026",
                "mandatory_checklist_missing": True,
                "already_submitted_elsewhere": True,
                "simultaneous_submission_allowed": False,
            }), encoding="utf-8")

            vn = td / "vn.json"
            vn.write_text(json.dumps({
                "mode": "portfolio",
                "venue_portfolio_recommendations": {
                    "recommended_now": [],
                    "timeline_conflicts": [{"primary_venue_id": "v1", "fallback_venue_id": "v2", "simultaneous_submission_allowed": False}],
                },
                "venue_evaluations": [
                    {"venue_id": "v1", "venue_name": "NeurIPS", "venue_tier": "top_tier_flagship", "classification": "conflicted_fallback"}
                ],
            }), encoding="utf-8")

            res = _run_cli([
                "--scorecard", str(sc),
                "--preflight", str(preflight),
                "--artifact-readiness", str(art),
                "--submission-policy", str(policy),
                "--venue-novelty", str(vn),
            ])
            self.assertEqual(res.returncode, 1)
            data = json.loads(res.stdout)
            self.assertTrue(data["desk_reject_blocked"])
            self.assertFalse(data["ready_to_submit"])
            reasons_blob = " | ".join(data["desk_reject_audit"]["reasons"])
            self.assertIn("page_limit_exceeded", reasons_blob)
            self.assertIn("template_mismatch", reasons_blob)
            self.assertIn("mandatory_checklist_missing", reasons_blob)
            self.assertIn("dual_submission_conflict", reasons_blob)
            self.assertIn("anonymization", reasons_blob)
            self.assertEqual(data["action_plan"][0]["priority"], "P0_BLOCKER")

    def test_venue_plan_and_sources_disqualification_and_portfolio_auto_retarget(self):
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            # Score is 6.65 -> competitive for q1_or_tier_a (6.35), viable for top_tier_flagship (min_viable 6.00)
            sc = td / "scorecard.json"
            sc.write_text(json.dumps({"weights": _weights(), "ratings": _ratings((7, 6, 7, 7, 6, 7))}), encoding="utf-8")

            vn = td / "vn_portfolio.json"
            vn.write_text(json.dumps({
                "mode": "portfolio",
                "venue_evaluations": [
                    {
                        "venue_id": "neurips_main",
                        "venue_name": "NeurIPS",
                        "edition": "2027",
                        "track": "Main",
                        "role": "primary",
                        "venue_tier": "top_tier_flagship",
                        "classification": "recommended_now",
                        "fit_score_out_of_10": 9,
                    },
                    {
                        "venue_id": "emnlp_findings",
                        "venue_name": "EMNLP Findings",
                        "edition": "2027",
                        "track": "Findings",
                        "role": "fallback",
                        "venue_tier": "q1_or_tier_a",
                        "classification": "viable_fallback",
                        "fit_score_out_of_10": 8,
                    },
                    {
                        "venue_id": "ws_eval",
                        "venue_name": "Eval Workshop",
                        "edition": "2027",
                        "track": "Workshop",
                        "role": "fallback",
                        "venue_tier": "workshop_or_preliminary",
                        "classification": "viable_fallback",
                        "fit_score_out_of_10": 7,
                    },
                ],
            }), encoding="utf-8")

            # NeurIPS fails check_venue_plan (even though check_venue_plan exits 0 on over_budget/passed deadline!)
            vp_neurips = td / "vp_neurips.json"
            vp_neurips.write_text(json.dumps({
                "venue": "NeurIPS",
                "edition": "2027",
                "cfp_verified": True,
                "within_budget": False,
                "source_issues": [],
                "warnings": ["full_paper_deadline_already_passed"],
                "backward_schedule": {"status": "start_already_passed_under_serial_assumption"},
            }), encoding="utf-8")

            vs_neurips = td / "vs_neurips.json"
            vs_neurips.write_text(json.dumps({
                "venue": "NeurIPS",
                "verification_passed": False,
                "source_text_status": "verification_blocked",
                "blocking_source_issues": [{"issue": "same_host_path_redirect_year_mismatch"}],
                "critical_fields_without_matched_quote": ["deadline"],
            }), encoding="utf-8")

            vp_emnlp = td / "vp_emnlp.json"
            vp_emnlp.write_text(json.dumps({
                "venue": "EMNLP Findings",
                "edition": "2027",
                "cfp_verified": True,
                "within_budget": True,
                "source_issues": [],
                "warnings": [],
                "backward_schedule": {"status": "start_not_yet_past_under_serial_assumption"},
            }), encoding="utf-8")

            res = _run_cli([
                "--scorecard", str(sc),
                "--venue-novelty", str(vn),
                "--venue-plan", str(vp_neurips),
                "--venue-sources", str(vs_neurips),
                "--venue-plan", str(vp_emnlp),
                "--target-venue", "NeurIPS",
            ])
            self.assertEqual(res.returncode, 0, res.stderr + res.stdout)
            data = json.loads(res.stdout)
            self.assertTrue(data["ready_to_submit"])
            self.assertEqual(data["verdict"], "RETARGETED_READY")
            self.assertEqual(data["selected_venue"]["venue_id"], "emnlp_findings")
            self.assertEqual(data["selected_venue"]["retargeted_from"], "neurips_main")
            self.assertFalse(data["no_viable_venue_in_portfolio"])

            # Now make all surviving venues fail -> no_viable_venue_in_portfolio = True
            vp_emnlp.write_text(json.dumps({
                "venue": "EMNLP Findings",
                "edition": "2027",
                "cfp_verified": False,
                "within_budget": True,
                "source_issues": [{"issue": "unverified_dynamic_page"}],
            }), encoding="utf-8")
            vp_ws = td / "vp_ws.json"
            vp_ws.write_text(json.dumps({
                "venue": "Eval Workshop",
                "edition": "2027",
                "cfp_verified": False,
                "source_issues": [],
                "backward_schedule": {"status": "deadline_unknown"},
            }), encoding="utf-8")
            res_none = _run_cli([
                "--scorecard", str(sc),
                "--venue-novelty", str(vn),
                "--venue-plan", str(vp_neurips),
                "--venue-plan", str(vp_emnlp),
                "--venue-plan", str(vp_ws),
                "--target-venue-tier", "top_tier_flagship",
            ])
            self.assertEqual(res_none.returncode, 1)
            data_none = json.loads(res_none.stdout)
            self.assertTrue(data_none["no_viable_venue_in_portfolio"])
            self.assertFalse(data_none["ready_to_submit"])
            self.assertIsNone(data_none["selected_venue"])
            self.assertEqual(data_none["recommended_matched_tier"], "q1_or_tier_a")

    def test_all_four_subfield_presets_and_optional_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            sc = td / "scorecard.json"
            # Include optional M9A v2 keys defensively
            sc.write_text(json.dumps({
                "weights": _weights(),
                "ratings": _ratings((8, 7, 8, 7, 7, 8)),
                "native_scales": {"arr_1_5": {"score": 3.85, "band": "Strong"}},
                "reviewer_synthesis": {"personas": [{"persona": "R1", "score": 7}]},
                "ac_synthesis": {"decision": "accept"},
                "sanity_warnings": ["custom_m9a_warning"],
            }), encoding="utf-8")

            prior_sc = td / "prior_sc.json"
            prior_sc.write_text(json.dumps({"weights": _weights(), "ratings": _ratings((6, 6, 6, 6, 6, 6))}), encoding="utf-8")

            gap = td / "gap.json"
            gap.write_text(json.dumps({"valid_structure": True, "errors": [], "warnings": [], "gap_tier_ceiling": "q1_top_tier_potential", "root_cause_barrier": "measurement_gap"}), encoding="utf-8")

            qcard = td / "qcard.json"
            qcard.write_text(json.dumps({"valid_structure": True, "errors": [], "warnings": []}), encoding="utf-8")

            seed_bundle = td / "seed_bundle.json"
            seed_bundle.write_text(json.dumps({
                "schema": "research_scientist_idea_seed_bundle_v1",
                "topic": "Long-context faithfulness",
                "subfield_preset": "nlp_llm",
                "trajectory_trees": {"G1": {"generations": [{"generation": 1, "year": 2024}], "open_root_limit": "context drift"}},
                "seeds": [{
                    "gap_id": "G1",
                    "gap_tier_ceiling": "q1_top_tier_potential",
                    "gap_below_target_venue_tier": False,
                    "prior_art_boundary": {"closest_work_ids": ["P1"], "cited_ids": ["P1", "P2"], "support_ids": ["P1"]},
                    "trajectory_tree": {"generations": [{"generation": 1, "year": 2024}], "open_root_limit": "context drift"},
                    "idea_portfolio": [{"id": "I1", "canonical_angle": "minimal_fix_f19"}],
                    "root_cause_barrier": "measurement_gap",
                    "why_now_enabler": "Long-context open baselines",
                    "evaluation_validity_gap": {"subtype": "construct_validity", "cues": ["length bias"]},
                    "isomorphic_transfer_leads": [{"status": "lead", "domain": "databases"}],
                    "so_what_decision_impact": "decision_changing",
                    "durability_12_24m": "durable_structural_limit",
                    "subfield_vetting": {"preset": "nlp_llm", "covered_checks": ["multi_prompt_variance"]},
                }],
            }), encoding="utf-8")

            proj = td / "proj.json"
            proj.write_text(json.dumps({"project_id": "PRJ-1", "status": "passed", "errors": [], "warnings": []}), encoding="utf-8")

            triage = td / "triage.json"
            triage.write_text(json.dumps({"verdict": "PASS_WITH_REVISIONS", "blocking": False, "major_defects": [{"summary": "Add compute table"}], "minor_defects": []}), encoding="utf-8")

            for preset in ("nlp_llm", "cv_multimodal", "ml_theory", "ai_systems", "speech_audio"):
                res = _run_cli([
                    "--scorecard", str(sc),
                    "--prior-scorecard", str(prior_sc),
                    "--gap-record", str(gap),
                    "--question-card", str(qcard),
                    "--idea-seed-bundle", str(seed_bundle),
                    "--project-state", str(proj),
                    "--triage-reviews", str(triage),
                    "--subfield-preset", preset,
                ])
                self.assertEqual(res.returncode, 0, preset + ": " + res.stderr + res.stdout)
                data = json.loads(res.stdout)
                self.assertEqual(data["subfield_preset"], preset)
                self.assertEqual(data["subfield_criteria"]["preset"], preset)
                self.assertEqual(data["upstream_downstream_linkage"]["idea_seed_bundle"]["seeds"][0]["support_ids"], ["P1"])
                self.assertEqual(data["upstream_downstream_linkage"]["idea_seed_bundle"]["seeds"][0]["trajectory_generations"], 1)
                self.assertIn("custom_m9a_warning", data["score_evaluation"]["sanity_warnings"])
                self.assertIsNotNone(data["score_evaluation"]["revision_diff"])
                self.assertGreater(data["score_evaluation"]["revision_diff"]["weighted_delta"], 0)

    def test_compact_budget_atomic_out_and_strict_exit_2_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            sc = td / "scorecard.json"
            sc.write_text(json.dumps({"weights": _weights(), "ratings": _ratings((8, 7, 8, 7, 7, 8))}), encoding="utf-8")

            # Huge >3400B --out path + many venues -> --compact must remain <4096 UTF-8 bytes
            deep_dir = td / ("a" * 180)
            for _ in range(18):
                deep_dir = deep_dir / ("b" * 180)
            long_out = deep_dir / "report.json"
            self.assertGreater(len(str(long_out).encode("utf-8")), 3400)

            vn = td / "vn_many.json"
            vn.write_text(json.dumps({
                "mode": "portfolio",
                "venue_evaluations": [
                    {
                        "venue_id": f"venue_{i}_" + ("x" * 60),
                        "venue_name": f"Long Venue Name {i} " + ("Y" * 80),
                        "venue_tier": "q1_or_tier_a",
                        "classification": "recommended_now",
                        "fit_score_out_of_10": 8,
                    }
                    for i in range(25)
                ],
            }), encoding="utf-8")

            res = _run_cli(["--scorecard", str(sc), "--venue-novelty", str(vn), "--out", str(long_out), "--compact"])
            self.assertEqual(res.returncode, 0, res.stderr + res.stdout)
            self.assertLess(len(res.stdout.encode("utf-8")), 4096)
            compact = json.loads(res.stdout)
            for req_key in (
                "compact", "schema", "ready_to_submit", "verdict", "cross_tool_fatal_gate",
                "desk_reject_blocked", "overall", "weighted_unrounded", "band",
                "selected_venue", "no_viable_venue_in_portfolio", "recommended_matched_tier", "artifact_path",
            ):
                self.assertIn(req_key, compact)
            self.assertTrue(compact["compact"])
            self.assertTrue(long_out.is_file())
            self.assertEqual([p for p in long_out.parent.iterdir() if p.name.startswith(".eval_sub_")], [])

            # Empty --out rejected BEFORE mkdir
            nonexist_parent = td / "should_not_exist_dir"
            res_empty_out = _run_cli(["--scorecard", str(sc), "--out", "   "])
            self.assertEqual(res_empty_out.returncode, 2)
            self.assertNotIn("Traceback", res_empty_out.stderr)
            self.assertIn("error", json.loads(res_empty_out.stderr))

            # Non-finite NaN / Inf / bool / malformed JSON -> exit 2, no mkdir, no Traceback
            for label, bad_text in [
                ("nan", '{"weights":{"importance":15,"novelty":20,"soundness":20,"evidence":20,"transparency":15,"clarity":10},"ratings":{"importance":7,"novelty":7,"soundness":7,"evidence":7,"transparency":7,"clarity":NaN}}'),
                ("inf", '{"weights":{"importance":15,"novelty":20,"soundness":20,"evidence":20,"transparency":15,"clarity":10},"ratings":{"importance":7,"novelty":7,"soundness":7,"evidence":7,"transparency":7,"clarity":Infinity}}'),
                ("bool", '{"weights":{"importance":15,"novelty":20,"soundness":20,"evidence":20,"transparency":15,"clarity":10},"ratings":{"importance":true,"novelty":7,"soundness":7,"evidence":7,"transparency":7,"clarity":7}}'),
                ("malformed", '{"weights": '),
            ]:
                bad_file = td / f"bad_{label}.json"
                bad_file.write_text(bad_text, encoding="utf-8")
                bad_out = nonexist_parent / f"{label}.json"
                r_bad = _run_cli(["--scorecard", str(bad_file), "--out", str(bad_out)])
                self.assertEqual(r_bad.returncode, 2, f"{label}: {r_bad.stderr}")
                self.assertNotIn("Traceback", r_bad.stderr)
                self.assertIn("error", json.loads(r_bad.stderr))
                self.assertFalse(nonexist_parent.exists())

    def test_claim_audit_and_all_seven_skill_md_footprints(self):
        skills = [
            "research-scientist",
            "research-precedent-corpus",
            "research-gap-rq-audit",
            "research-experiment-coding",
            "research-novelty-venue",
            "research-paper-writing",
            "research-user-report",
        ]
        for s in skills:
            raw = (ROOT / s / "SKILL.md").read_text(encoding="utf-8")
            fp = claim_audit._measure_skill_footprint(raw)
            self.assertLess(fp["lines"], 50, f"{s}: {fp}")
            self.assertLess(fp["est_tokens"], 900, f"{s}: {fp}")
            self.assertLess(fp["frontmatter_est_tokens"], 140, f"{s}: {fp}")

        audit_res = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS_DIR / "claim_audit.py"),
                "--suite-root", str(ROOT),
                "--readme", str(ROOT / "README.md"),
                "--json",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(audit_res.returncode, 0, audit_res.stderr + audit_res.stdout)
        parsed = json.loads(audit_res.stdout)
        self.assertEqual(parsed["finding_count"], 0, parsed["findings"])

    def test_raw_experiment_manifest_validated_without_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            sc = td / "sc.json"
            sc.write_text(json.dumps({"weights": _weights(), "ratings": _ratings((8, 7, 8, 7, 7, 8))}), encoding="utf-8")

            res_file = td / "cand.json"
            res_bytes = json.dumps({"accuracy": 0.91}).encode("utf-8")
            res_file.write_bytes(res_bytes)
            res_sha = hashlib.sha256(res_bytes).hexdigest()
            zero64 = "0" * 64

            raw_ok = td / "raw_exp_ok.json"
            raw_ok.write_text(json.dumps({
                "question_id": "Q1",
                "protocol_version": "v1",
                "protocol_frozen_at_utc": "2026-01-01T00:00:00Z",
                "runs": [{
                    "run_id": "R1",
                    "role": "baseline",
                    "protocol_version": "v1",
                    "code_commit": "abc123",
                    "data_version": "v1",
                    "split_manifest_sha256": zero64,
                    "metric_id": "accuracy",
                    "metric_script_sha256": zero64,
                    "command": "python3 run.py",
                    "started_at_utc": "2026-01-02T00:00:00Z",
                    "ended_at_utc": "2026-01-02T00:01:00Z",
                    "exit_code": 0,
                    "result_artifact_path": "cand.json",
                    "result_artifact_sha256": res_sha,
                    "result_value": 0.91,
                    "deviations": [],
                    "decision_timing": "prespecified",
                }],
            }), encoding="utf-8")

            r_ok = _run_cli(["--scorecard", str(sc), "--experiment-manifest", str(raw_ok)])
            self.assertEqual(r_ok.returncode, 0, r_ok.stderr + r_ok.stdout)
            self.assertNotIn("Traceback", r_ok.stderr)
            d_ok = json.loads(r_ok.stdout)
            self.assertTrue(d_ok["ready_to_submit"])
            self.assertTrue(d_ok["cross_tool_gating_audit"]["experiment_manifest"]["files_verified"])

            raw_bad = td / "raw_exp_bad.json"
            raw_bad.write_text(json.dumps({
                "question_id": "Q1",
                "protocol_version": "v1",
                "protocol_frozen_at_utc": "2026-01-01T00:00:00Z",
                "runs": [{
                    "run_id": "R1",
                    "role": "baseline",
                    "protocol_version": "v1",
                    "code_commit": "abc123",
                    "data_version": "v1",
                    "split_manifest_sha256": zero64,
                    "metric_id": "accuracy",
                    "metric_script_sha256": zero64,
                    "command": "python3 run.py",
                    "started_at_utc": "2026-01-02T00:00:00Z",
                    "ended_at_utc": "2026-01-02T00:01:00Z",
                    "exit_code": 0,
                    "result_artifact_sha256": zero64,
                    "result_value": 0.8,
                    "deviations": [],
                    "decision_timing": "prespecified",
                }],
            }), encoding="utf-8")

            r_bad = _run_cli(["--scorecard", str(sc), "--experiment-manifest", str(raw_bad)])
            self.assertEqual(r_bad.returncode, 1, r_bad.stderr + r_bad.stdout)
            self.assertNotIn("Traceback", r_bad.stderr)
            d_bad = json.loads(r_bad.stdout)
            self.assertFalse(d_bad["ready_to_submit"])
            self.assertTrue(d_bad["cross_tool_fatal_gate"])
            self.assertFalse(d_bad["cross_tool_gating_audit"]["experiment_manifest"]["files_verified"])

    def test_real_triage_reviews_mock_review_and_post_reject_integration(self):
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            sc_pass = td / "sc_pass.json"
            sc_pass.write_text(json.dumps({"weights": _weights(), "ratings": _ratings((8, 7, 8, 7, 7, 8))}), encoding="utf-8")

            # 1. Real triage_reviews.py mock-review fatal defect
            tri_sc = td / "tri_sc.json"
            tri_sc.write_text(json.dumps({"weights": _weights(), "ratings": _ratings((8, 7, 4, 4, 8, 8))}), encoding="utf-8")
            mr_out = td / "mr_out.json"
            subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "triage_reviews.py"), "mock-review", "--scorecard", str(tri_sc), "--out", str(mr_out)],
                cwd=str(ROOT), capture_output=True, text=True, check=False,
            )
            self.assertTrue(mr_out.is_file())
            r_mr = _run_cli(["--scorecard", str(sc_pass), "--triage-reviews", str(mr_out)])
            self.assertEqual(r_mr.returncode, 1, r_mr.stderr + r_mr.stdout)
            d_mr = json.loads(r_mr.stdout)
            self.assertFalse(d_mr["ready_to_submit"])
            tri_summary = d_mr["upstream_downstream_linkage"]["triage_reviews"]
            self.assertTrue(tri_summary["blocking"])
            self.assertGreaterEqual(tri_summary["fatal_count"], 1)
            self.assertEqual(tri_summary["verdict"], "fatal_gate_triggered")

            # 2. Real triage_reviews.py post-reject resubmission_blocked (even without fatal defects)
            revs = td / "revs.json"
            revs.write_text(json.dumps({"comments": [{"id": "R1.1", "reviewer": "R1", "text": "Need more ablations on dataset size."}]}), encoding="utf-8")
            vb = td / "vb.json"
            vb.write_text(json.dumps({"name": "EMNLP", "resubmission_allowed": False}), encoding="utf-8")
            pr_out = td / "pr_out.json"
            r_pr_cli = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "triage_reviews.py"), "post-reject", "--reviews", str(revs), "--venue-b", str(vb), "--out", str(pr_out)],
                cwd=str(ROOT), capture_output=True, text=True, check=False,
            )
            self.assertEqual(r_pr_cli.returncode, 0, r_pr_cli.stderr + r_pr_cli.stdout)
            self.assertTrue(pr_out.is_file())
            r_pr = _run_cli(["--scorecard", str(sc_pass), "--triage-reviews", str(pr_out)])
            self.assertEqual(r_pr.returncode, 1, r_pr.stderr + r_pr.stdout)
            d_pr = json.loads(r_pr.stdout)
            self.assertFalse(d_pr["ready_to_submit"])
            self.assertTrue(d_pr["upstream_downstream_linkage"]["triage_reviews"]["blocking"])
            self.assertEqual(d_pr["upstream_downstream_linkage"]["triage_reviews"]["venue_b_status"], "resubmission_blocked")

            # 3. Real mock-review with rejected_below_venue_tier also blocks
            tri_rej = td / "tri_rej.json"
            tri_rej.write_text(json.dumps({
                "overall_verdict": "rejected_below_venue_tier",
                "defect_ledger": [{"id": "D1", "severity": "major", "summary": "Weak novelty"}],
                "submission_readiness": {"fatal_gate_triggered": False},
            }), encoding="utf-8")
            r_rej = _run_cli(["--scorecard", str(sc_pass), "--triage-reviews", str(tri_rej)])
            self.assertEqual(r_rej.returncode, 1)
            self.assertFalse(json.loads(r_rej.stdout)["ready_to_submit"])

    def test_real_project_state_audit_key_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            sc = td / "sc.json"
            sc.write_text(json.dumps({"weights": _weights(), "ratings": _ratings((8, 7, 8, 7, 7, 8))}), encoding="utf-8")

            ps_file = td / "ps.json"
            subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "project_state.py"), "--state", str(ps_file), "--init", "--project-id", "P1", "--title", "Test Topic"],
                cwd=str(ROOT), capture_output=True, text=True, check=True,
            )
            # Inject an unlinked claim directly into state file and audit with --strict
            st = json.loads(ps_file.read_text(encoding="utf-8"))
            st["manuscript_claims"] = {"C1": {"id": "C1", "text": "Improves F1 by 5%", "material": True, "kind": "reported", "rq_id": None, "run_ids": []}}
            ps_file.write_text(json.dumps(st), encoding="utf-8")
            ps_audit = td / "ps_audit.json"
            subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "project_state.py"), "--state", str(ps_file), "--audit", "--strict", "--out", str(ps_audit)],
                cwd=str(ROOT), capture_output=True, text=True, check=False,
            )
            r = _run_cli(["--scorecard", str(sc), "--project-state", str(ps_audit)])
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            d = json.loads(r.stdout)
            ps_out = d["upstream_downstream_linkage"]["project_state"]
            self.assertEqual(ps_out["status"], "issues_detected")
            self.assertTrue(ps_out["errors"])
            self.assertIsNotNone(ps_out["lineage_coverage"])
            self.assertTrue(any(w.startswith("project_state_issues:") and not w.endswith(":0") for w in d["warnings"]))

    def test_finite_decimal_rejects_string_nan_inf_and_invalid_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            sc_ok = td / "sc_ok.json"
            sc_ok.write_text(json.dumps({"weights": _weights(), "ratings": _ratings((8, 7, 8, 7, 7, 8))}), encoding="utf-8")

            for bad_val in ("NaN", "Infinity", "-Infinity", "not_a_num", True):
                sc_bad = td / "sc_bad.json"
                sc_bad.write_text(json.dumps({
                    "status": "calculated",
                    "overall": 7,
                    "weighted_unrounded": bad_val,
                    "submission_readiness": {"band": "competitive_top_tier_main_track"},
                }), encoding="utf-8")
                r = _run_cli(["--scorecard", str(sc_bad)])
                self.assertEqual(r.returncode, 2, f"val={bad_val!r}: {r.stderr}")
                self.assertNotIn("Traceback", r.stderr)
                self.assertIn("error", json.loads(r.stderr))

                prior_bad = td / "prior_bad.json"
                prior_bad.write_text(json.dumps({
                    "status": "calculated",
                    "overall": 6,
                    "weighted_unrounded": bad_val,
                    "submission_readiness": {"band": "borderline_top_tier_competitive_findings_tier_a"},
                }), encoding="utf-8")
                rp = _run_cli(["--scorecard", str(sc_ok), "--prior-scorecard", str(prior_bad)])
                self.assertEqual(rp.returncode, 2, f"prior val={bad_val!r}: {rp.stderr}")
                self.assertNotIn("Traceback", rp.stderr)
                self.assertIn("error", json.loads(rp.stderr))
                self.assertEqual(rp.stdout.strip(), "")

    def test_match_venue_report_no_prefix_collision_acl_and_neurips(self):
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            sc = td / "sc.json"
            sc.write_text(json.dumps({"weights": _weights(), "ratings": _ratings((8, 7, 8, 7, 7, 8))}), encoding="utf-8")

            for main_id, main_name, sub_id, sub_name, sub_track, sub_tier in [
                ("acl_main", "ACL", "acl_findings", "ACL Findings", "Findings", "q1_or_tier_a"),
                ("neurips_main", "NeurIPS", "neurips_ws", "NeurIPS Workshop", "Workshop", "workshop_or_preliminary"),
            ]:
                vn = td / f"vn_{main_id}.json"
                vn.write_text(json.dumps({
                    "mode": "portfolio",
                    "venue_evaluations": [
                        {"venue_id": sub_id, "venue_name": sub_name, "edition": "2027", "track": sub_track, "role": "fallback", "venue_tier": sub_tier, "classification": "viable_fallback", "fit_score_out_of_10": 8},
                        {"venue_id": main_id, "venue_name": main_name, "edition": "2027", "track": "Main", "role": "primary", "venue_tier": "top_tier_flagship", "classification": "recommended_now", "fit_score_out_of_10": 9},
                    ],
                }), encoding="utf-8")
                vs = td / f"vs_{main_id}.json"
                vs.write_text(json.dumps({
                    "venue": main_name,
                    "verification_passed": False,
                    "source_text_status": "verification_blocked",
                    "blocking_source_issues": [{"issue": "same_host_path_redirect_year_mismatch"}],
                    "critical_fields_without_matched_quote": ["deadline"],
                }), encoding="utf-8")
                res = _run_cli(["--scorecard", str(sc), "--venue-novelty", str(vn), "--venue-sources", str(vs), "--target-venue", main_name])
                self.assertEqual(res.returncode, 0, res.stderr + res.stdout)
                d = json.loads(res.stdout)
                self.assertTrue(d["ready_to_submit"])
                self.assertEqual(d["verdict"], "RETARGETED_READY")
                self.assertEqual(d["selected_venue"]["venue_id"], sub_id)
                self.assertEqual(d["selected_venue"]["retargeted_from"], main_id)

    def test_real_score_math_and_compare_scorecards_m9a_v2_idea_bool_and_post_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            # 1. Real score_math.py output with reviewer_panel, section_diagnostics, evidence_anchors
            sm_in = td / "sm_in.json"
            sm_in.write_text(json.dumps({
                "weights": _weights(),
                "ratings": _ratings((8, 7, 8, 8, 7, 8)),
                "reviewer_confidence": 4,
                "reviewer_panel": [
                    {"reviewer_id": "R1", "confidence": 4, "ratings": _ratings((8, 7, 8, 8, 7, 8))},
                    {"reviewer_id": "R2", "confidence": 3, "ratings": _ratings((7, 7, 8, 7, 7, 8))},
                    {"reviewer_id": "R3", "confidence": 5, "ratings": _ratings((8, 8, 8, 8, 7, 8))},
                ],
                "section_diagnostics": {"method": 8, "experiments": 8, "limitations": 7},
            }), encoding="utf-8")
            sm_out = td / "sm_out.json"
            r_sm = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "score_math.py"), str(sm_in), "--what-if"],
                cwd=str(ROOT), capture_output=True, text=True, check=True,
            )
            sm_out.write_text(r_sm.stdout, encoding="utf-8")
            r_eval_sm = _run_cli(["--scorecard", str(sm_out)])
            self.assertEqual(r_eval_sm.returncode, 0, r_eval_sm.stderr + r_eval_sm.stdout)
            d_sm = json.loads(r_eval_sm.stdout)
            se = d_sm["score_evaluation"]
            self.assertEqual(se["native_scales"]["source"], "m9a_v2")
            self.assertIsNotNone(se["scientific_merit_score"])
            self.assertIsNotNone(se["publishability_packaging_score"])
            self.assertEqual(se["reviewer_synthesis"]["source"], "m9a_v2")
            self.assertEqual(se["ac_synthesis"]["source"], "m9a_v2")
            self.assertTrue(se["what_if_roi"])
            self.assertIsNotNone(se["worst_case_sensitivity"]["min_dimension"])
            self.assertIn("sections_scored", se["section_diagnostics"])

            # 2. Real compare_scorecards.py output (no raw ratings) + caps
            locs_t = {d: [f'target.txt#L1 "Evidence for {d}"'] for d in score_math.DIMENSIONS}
            locs_b = {d: [f'b1.txt#L1 "Evidence for {d}"'] for d in score_math.DIMENSIONS}
            cs_in = td / "cs_in.json"
            cs_in.write_text(json.dumps({
                "weight_scenarios": [_weights()],
                "profiles": [
                    {"id": "target", "reading_basis": "full_text", "closest_work": ["b1"], "evidence_locators": locs_t, "has_ci_or_error_bars": True, "ratings": _ratings((8, 8, 8, 8, 8, 8))},
                    {"id": "b1", "reading_basis": "full_text", "closest_work": ["target"], "evidence_locators": locs_b, "has_ci_or_error_bars": True, "ratings": _ratings((7, 7, 7, 7, 7, 7))},
                ],
            }), encoding="utf-8")
            cs_out = td / "cs_out.json"
            subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "compare_scorecards.py"), str(cs_in), "--target-id", "target", "--what-if", "--out", str(cs_out)],
                cwd=str(ROOT), capture_output=True, text=True, check=True,
            )
            # Clean compare_scorecards output preserves M9A v2 keys
            r_cs_ok = _run_cli(["--scorecard", str(cs_out), "--target-id", "target"])
            self.assertEqual(r_cs_ok.returncode, 0, r_cs_ok.stderr + r_cs_ok.stdout)
            d_cs_ok = json.loads(r_cs_ok.stdout)
            self.assertEqual(d_cs_ok["score_evaluation"]["native_scales"]["source"], "m9a_v2")
            self.assertIsNotNone(d_cs_ok["score_evaluation"]["scientific_merit_score"])
            self.assertTrue(d_cs_ok["score_evaluation"]["what_if_roi"])

            # Fatal cap on compare_scorecards output without raw ratings -> invalidates stale pre-cap overall
            contam = td / "contam.json"
            contam.write_text(json.dumps({"schema": "experiment_rigor_contamination_v1", "verdict": "CONTAMINATION_DETECTED"}), encoding="utf-8")
            r_cs_fat = _run_cli(["--scorecard", str(cs_out), "--rigor", str(contam)])
            self.assertEqual(r_cs_fat.returncode, 1)
            d_cs_fat = json.loads(r_cs_fat.stdout)
            self.assertFalse(d_cs_fat["ready_to_submit"])
            self.assertTrue(d_cs_fat["score_evaluation"]["post_cap_rescore_incomplete"])
            self.assertIsNone(d_cs_fat["overall"])
            self.assertIsNone(d_cs_fat["weighted_unrounded"])
            self.assertEqual(d_cs_fat["band"], "not_ready_fatal_gate")

            # Non-fatal WARN cap on compare_scorecards output without raw ratings -> blocks stale READY_TO_SUBMIT
            art_warn = td / "art_warn.json"
            art_warn.write_text(json.dumps({"schema": "artifact_readiness_v1", "verdict": "WARN", "ready_to_submit": True, "recommended_transparency_cap": 5, "blocking_reasons": []}), encoding="utf-8")
            r_cs_warn = _run_cli(["--scorecard", str(cs_out), "--artifact-readiness", str(art_warn)])
            self.assertEqual(r_cs_warn.returncode, 1, r_cs_warn.stderr + r_cs_warn.stdout)
            d_cs_warn = json.loads(r_cs_warn.stdout)
            self.assertFalse(d_cs_warn["ready_to_submit"])
            self.assertTrue(d_cs_warn["score_evaluation"]["post_cap_rescore_incomplete"])
            self.assertIsNone(d_cs_warn["overall"])
            self.assertIsNone(d_cs_warn["weighted_unrounded"])

            # 3. IDEA_DIMENSIONS mode="idea" accepted & blocks archival submission cleanly
            idea_in = td / "idea_in.json"
            idea_in.write_text(json.dumps({
                "mode": "idea",
                "weights": dict(score_math.DEFAULT_IDEA_WEIGHTS),
                "ratings": {"evidence_coverage": 8, "novelty": 8, "importance": 8, "answerability": 7, "feasibility": 3, "falsifiability": 8},
            }), encoding="utf-8")
            r_idea = _run_cli(["--scorecard", str(idea_in)])
            self.assertEqual(r_idea.returncode, 1, r_idea.stderr + r_idea.stdout)
            self.assertNotIn("Traceback", r_idea.stderr)
            d_idea = json.loads(r_idea.stdout)
            self.assertFalse(d_idea["ready_to_submit"])
            self.assertEqual(d_idea["score_evaluation"]["mode"], "idea")

            # 4. reviewer_panel bool confidence rejected with exit 2
            rp_bool = td / "rp_bool.json"
            rp_bool.write_text(json.dumps({
                "weights": _weights(),
                "ratings": _ratings((8, 7, 8, 7, 7, 8)),
                "reviewer_panel": [
                    {"reviewer_id": "R1", "confidence": True, "ratings": _ratings((8, 7, 8, 7, 7, 8))},
                    {"reviewer_id": "R2", "confidence": 4, "ratings": _ratings((8, 7, 8, 7, 7, 8))},
                    {"reviewer_id": "R3", "confidence": 4, "ratings": _ratings((8, 7, 8, 7, 7, 8))},
                ],
            }), encoding="utf-8")
            r_bool = _run_cli(["--scorecard", str(rp_bool)])
            self.assertEqual(r_bool.returncode, 2, r_bool.stderr + r_bool.stdout)
            self.assertNotIn("Traceback", r_bool.stderr)
            self.assertIn("error", json.loads(r_bool.stderr))

    def test_check_venue_plan_exit0_traps_and_type_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            sc = td / "sc.json"
            sc.write_text(json.dumps({"weights": _weights(), "ratings": _ratings((8, 7, 8, 7, 7, 8))}), encoding="utf-8")

            for label, vp_obj in [
                ("full_paper_unknown", {"venue": "ACL", "edition": "2027", "track": "Main", "cfp_verified": True, "within_budget": True, "source_issues": [], "warnings": ["full_paper_unknown"]}),
                ("presentation_mode_unverified", {"venue": "ACL", "edition": "2027", "track": "Main", "cfp_verified": True, "within_budget": None, "source_issues": [], "warnings": ["presentation_mode_unverified"]}),
            ]:
                vp = td / f"vp_{label}.json"
                vp.write_text(json.dumps(vp_obj), encoding="utf-8")
                r = _run_cli(["--scorecard", str(sc), "--target-venue", "ACL", "--venue-plan", str(vp)])
                self.assertEqual(r.returncode, 1, label + ": " + r.stderr + r.stdout)
                d = json.loads(r.stdout)
                self.assertFalse(d["ready_to_submit"])
                self.assertTrue(d["no_viable_venue_in_portfolio"])

            vp_bad_type = td / "vp_bad_type.json"
            vp_bad_type.write_text(json.dumps({"venue": "ACL", "cfp_verified": True, "within_budget": "false"}), encoding="utf-8")
            r_t = _run_cli(["--scorecard", str(sc), "--target-venue", "ACL", "--venue-plan", str(vp_bad_type)])
            self.assertEqual(r_t.returncode, 2)
            self.assertNotIn("Traceback", r_t.stderr)

    def test_compare_venue_novelty_invalid_portfolio_blocks_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            sc = td / "sc.json"
            sc.write_text(json.dumps({"weights": _weights(), "ratings": _ratings((8, 7, 8, 7, 7, 8))}), encoding="utf-8")

            vn = td / "vn_invalid.json"
            vn.write_text(json.dumps({
                "mode": "portfolio",
                "status": "invalid",
                "errors": ["candidate_venues:fewer_than_min_venues:1_lt_3"],
                "venue_portfolio_recommendations": {"portfolio_verdict": "invalid_portfolio_too_few_venues"},
                "venue_evaluations": [
                    {"venue_id": "neurips_main", "venue_name": "NeurIPS", "venue_tier": "top_tier_flagship", "classification": "recommended_now", "fit_score_out_of_10": 9}
                ],
            }), encoding="utf-8")
            r = _run_cli(["--scorecard", str(sc), "--venue-novelty", str(vn)])
            self.assertEqual(r.returncode, 1, r.stderr + r.stdout)
            d = json.loads(r.stdout)
            self.assertFalse(d["ready_to_submit"])
            self.assertTrue(d["no_viable_venue_in_portfolio"])
            self.assertIsNone(d["selected_venue"])

    def test_ergonomics_gap_pipeline_unwrap_compact_ledger_and_compact_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            sc = td / "sc.json"
            sc.write_text(json.dumps({"weights": _weights(), "ratings": _ratings((8, 7, 8, 7, 7, 8))}), encoding="utf-8")

            gp_out = td / "gp_out.json"
            gp_out.write_text(json.dumps({
                "schema": "research_scientist_gap_pipeline_v1",
                "topic": "Wrapped topic",
                "trajectory_trees": {"G1": {"generations": [{"generation": 1}]}},
                "idea_seed_bundle": {
                    "schema": "research_scientist_idea_seed_bundle_v1",
                    "topic": "Wrapped topic",
                    "subfield_preset": "nlp_llm",
                    "seeds": [{
                        "gap_id": "G1",
                        "gap_tier_ceiling": "q1_top_tier_potential",
                        "prior_art_boundary": {"closest_work_ids": ["P1"], "cited_ids": ["P1"], "support_ids": ["P1"]},
                        "subfield_vetting": {"preset": "nlp_llm", "covered_checks": ["contamination_check"]},
                    }],
                },
            }), encoding="utf-8")

            r_gp = _run_cli(["--scorecard", str(sc), "--idea-seed-bundle", str(gp_out)])
            self.assertEqual(r_gp.returncode, 0, r_gp.stderr + r_gp.stdout)
            d_gp = json.loads(r_gp.stdout)
            self.assertEqual(d_gp["subfield_preset"], "nlp_llm")
            isb = d_gp["upstream_downstream_linkage"]["idea_seed_bundle"]
            self.assertEqual(isb["seed_count"], 1)
            self.assertTrue(isb["has_root_trajectory_trees"])

            # Compact check_manuscript_ledger JSON with grandiose_finding_count (no list)
            compact_led = td / "compact_led.json"
            compact_led.write_text(json.dumps({
                "compact": True,
                "status": "structural_issues",
                "issues": [],
                "grandiose_finding_count": 2,
            }), encoding="utf-8")
            r_led = _run_cli(["--scorecard", str(sc), "--ledger", str(compact_led)])
            self.assertEqual(r_led.returncode, 1)
            d_led = json.loads(r_led.stdout)
            self.assertFalse(d_led["ready_to_submit"])
            self.assertEqual(d_led["cross_tool_gating_audit"]["manuscript_ledger"]["grandiose_finding_count"], 2)

            # _encoded_utf8_len matches default json.dumps(..., ensure_ascii=False)
            sample = {"a": "Tiếng Việt", "b": [1, 2, 3]}
            self.assertEqual(
                evaluate_submission._encoded_utf8_len(sample),
                len(json.dumps(sample, ensure_ascii=False).encode("utf-8")),
            )

    def test_venue_type_profile_fatal_gates_dataset_benchmark_journal_q1_and_survey(self):
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            for name, sc_obj in [
                ("db_ethics", {"venue_type": "dataset_benchmark", "ethics_license_verified": False, "ratings": _ratings((8, 8, 8, 8, 8, 8))}),
                ("db_t1t2", {"venue_type": "dataset_benchmark", "t1_t2_verified": False, "ratings": _ratings((8, 8, 8, 8, 8, 8))}),
                ("db_checks", {"venue_type": "dataset_benchmark", "dataset_checks": {"data_quality_audit": False, "ethics_and_license_t1_t2": True, "baseline_coverage": True, "contamination_and_leakage": True, "maintenance_plan": True}, "ratings": _ratings((8, 8, 8, 8, 8, 8))}),
                ("jq1", {"venue_type": "journal_q1", "venue_checks": {"comprehensive_ablations": False, "reproducibility_details": True}, "ratings": _ratings((8, 8, 8, 8, 8, 8))}),
                ("survey", {"venue_type": "survey_review", "venue_checks": {"systematic_coverage_protocol": False}, "ratings": _ratings((8, 8, 8, 8, 8, 8))}),
            ]:
                p = td / f"{name}.json"
                p.write_text(json.dumps(sc_obj), encoding="utf-8")
                r = _run_cli(["--scorecard", str(p)])
                self.assertEqual(r.returncode, 1, f"{name}: {r.stderr + r.stdout}")
                d = json.loads(r.stdout)
                self.assertFalse(d["ready_to_submit"], name)
                self.assertEqual(d["band"], "not_ready_fatal_gate", name)
                self.assertEqual(d["recommended_matched_tier"], "none_hold_for_rework", name)
                self.assertTrue(any("venue_checks_failed" in a["code"] for a in d["action_plan"]), name)

                r_v = _run_cli(["--scorecard", str(p), "--target-venue", "NeurIPS"])
                self.assertEqual(r_v.returncode, 1, name)
                dv = json.loads(r_v.stdout)
                self.assertFalse(dv["ready_to_submit"], name)
                self.assertIsNone(dv["selected_venue"], name)
                self.assertEqual(dv["recommended_matched_tier"], "none_hold_for_rework", name)

    def test_compact_wrappers_1hop_resolution_and_parity_fallbacks(self):
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            sc = td / "sc.json"
            sc.write_text(json.dumps({"weights": _weights(), "ratings": _ratings((8, 8, 8, 8, 8, 8))}), encoding="utf-8")

            # 1. check_venue_plan --compact schedule_status, cfp_verified=None, truncated source_issues
            for fname, vp_obj in [
                ("sched.json", {"venue": "NeurIPS", "edition": "2027", "track": "Main", "cfp_verified": True, "within_budget": True, "source_issues": [], "warnings": [], "schedule_status": "start_already_passed_under_serial_assumption"}),
                ("cfp_null.json", {"venue": "NeurIPS", "cfp_verified": None, "within_budget": True, "source_issues": [], "warnings": []}),
                ("si_trunc.json", {"venue": "NeurIPS", "cfp_verified": True, "within_budget": True, "source_issues": [], "source_issues_total": 2, "source_issues_truncated": True, "warnings": []}),
            ]:
                p = td / fname
                p.write_text(json.dumps(vp_obj), encoding="utf-8")
                r = _run_cli(["--scorecard", str(sc), "--venue-plan", str(p), "--target-venue", "NeurIPS"])
                self.assertEqual(r.returncode, 1, fname)
                d = json.loads(r.stdout)
                self.assertFalse(d["ready_to_submit"], fname)
                self.assertEqual(d["verdict"], "BLOCKED_NO_VIABLE_VENUE", fname)

            # 2. compare_venue_novelty --portfolio --compact venue_summaries + check_venue_sources --compact failed_claims
            vn_comp = td / "vn_comp.json"
            vn_comp.write_text(json.dumps({
                "compact": True, "mode": "portfolio", "status": "structurally_checked",
                "target_readiness": {"target_novelty_score": 6, "recommended_matched_tier": "q1_or_tier_a"},
                "venue_portfolio_recommendations": {"portfolio_verdict": "retargeted_to_matched_tier", "viable_fallback": ["acl_findings"], "recommended_now": ["acl_main"]},
                "venue_summaries": [
                    {"venue_id": "acl_main", "role": "primary", "venue_tier": "top_tier_flagship", "classification": "recommended_now", "fit_score_out_of_10": 9},
                    {"venue_id": "acl_findings", "role": "fallback", "venue_tier": "q1_or_tier_a", "classification": "viable_fallback", "fit_score_out_of_10": 8},
                ],
            }), encoding="utf-8")
            vs_comp = td / "vs_comp.json"
            vs_comp.write_text(json.dumps({
                "venue": "ACL", "verification_passed": False, "source_text_status": "verification_blocked",
                "failed_claims": [{"field": "workshop_fee", "status": "quote_not_found"}], "failed_claims_total": 1,
            }), encoding="utf-8")
            r_vn = _run_cli(["--scorecard", str(sc), "--venue-novelty", str(vn_comp), "--venue-sources", str(vs_comp), "--target-venue", "ACL"])
            self.assertEqual(r_vn.returncode, 0, r_vn.stderr + r_vn.stdout)
            d_vn = json.loads(r_vn.stdout)
            self.assertEqual(d_vn["verdict"], "RETARGETED_READY")
            self.assertEqual(d_vn["selected_venue"]["venue_id"], "acl_findings")
            self.assertEqual(d_vn["selected_venue"]["retargeted_from"], "acl_main")
            acl_main_ev = next(v for v in d_vn["venue_portfolio"]["evaluations"] if v["venue_id"] == "acl_main")
            self.assertIn("venue_sources_claim:workshop_fee:quote_not_found", acl_main_ev["disqualification_reasons"])

            # Portfolio trim_stage>=3 fallback reconstruction + conflicted_fallback desk_reject
            vn_trim = td / "vn_trim.json"
            vn_trim.write_text(json.dumps({
                "compact": True, "mode": "portfolio", "status": "structurally_checked",
                "venue_summaries": [], "venue_summaries_truncated": 2,
                "venue_portfolio_recommendations": {
                    "portfolio_verdict": "retargeted_to_matched_tier",
                    "conflicted_fallback": ["neurips_main"],
                    "recommended_now": ["icml_main"],
                    "recommended_matched_tier": {"matched_tier": "top_tier_flagship", "recommended_venues": ["icml_main"], "retargeted_from_rejected_venues": ["neurips_main"]},
                },
            }), encoding="utf-8")
            r_tr = _run_cli(["--scorecard", str(sc), "--venue-novelty", str(vn_trim), "--target-venue", "NeurIPS"])
            self.assertEqual(r_tr.returncode, 1)
            d_tr = json.loads(r_tr.stdout)
            self.assertTrue(d_tr["desk_reject_blocked"])
            self.assertEqual(d_tr["selected_venue"]["venue_id"], "icml_main")

            # _match_venue_report "<venue> <edition>" == ve_name & NaN target_vs_venue_overall_delta exit 2
            vn_ed = td / "vn_ed.json"
            vn_ed.write_text(json.dumps({
                "mode": "portfolio",
                "venue_evaluations": [
                    {"venue_id": "n27", "venue_name": "NeurIPS 2027", "edition": "2027", "track": "Main", "role": "primary", "venue_tier": "top_tier_flagship", "classification": "recommended_now"},
                ],
            }), encoding="utf-8")
            vp_ed = td / "vp_ed.json"
            vp_ed.write_text(json.dumps({"venue": "NeurIPS", "edition": "2027", "track": "Main", "cfp_verified": False, "within_budget": False, "source_issues": [{"issue": "stale"}]}), encoding="utf-8")
            r_ed = _run_cli(["--scorecard", str(sc), "--venue-novelty", str(vn_ed), "--venue-plan", str(vp_ed)])
            self.assertEqual(r_ed.returncode, 1)
            self.assertTrue(json.loads(r_ed.stdout)["no_viable_venue_in_portfolio"])

            vn_nan = td / "vn_nan.json"
            vn_nan.write_text(json.dumps({
                "mode": "portfolio",
                "venue_evaluations": [{"venue_id": "v1", "venue_name": "ACL", "venue_tier": "top_tier_flagship", "classification": "recommended_now", "venue_contribution_bar": {"target_vs_venue_overall_delta": "NaN"}}],
            }), encoding="utf-8")
            r_nan = _run_cli(["--venue-novelty", str(vn_nan)])
            self.assertEqual(r_nan.returncode, 2)

            # 3. 1-hop compact wrapper resolution & fallback counts (artifact_readiness, triage, ledger, eng, exp, project_state, gap_pipeline)
            art_full = td / "art_full.json"
            art_full.write_text(json.dumps({"schema": "artifact_readiness_v1", "verdict": "FAIL", "ready_to_submit": False, "recommended_transparency_cap": 3, "blocking_reasons": ["anonymization/author-leak"], "summary": {"by_category": {"anonymization": {"status": "FAIL"}}}}), encoding="utf-8")
            art_wrap = td / "art_wrap.json"
            art_wrap.write_text(json.dumps({"compact": True, "verdict": "FAIL", "ready_to_submit": False, "blocking_reasons": [], "warnings": [], "artifact_path": str(art_full)}), encoding="utf-8")
            r_art = _run_cli(["--scorecard", str(sc), "--artifact-readiness", str(art_wrap)])
            self.assertEqual(r_art.returncode, 1)
            d_art = json.loads(r_art.stdout)
            self.assertTrue(d_art["desk_reject_blocked"])
            self.assertEqual(d_art["verdict"], "BLOCKED_FATAL_GATE_AND_DESK_REJECT")

            tri_fb = td / "tri_fb.json"
            tri_fb.write_text(json.dumps({"compact": True, "schema": "triage_reviews_post_reject_v1", "mode": "post-reject", "status": "resubmission_blocked", "artifact_path": None}), encoding="utf-8")
            r_tri = _run_cli(["--scorecard", str(sc), "--triage-reviews", str(tri_fb)])
            self.assertEqual(r_tri.returncode, 1)
            self.assertEqual(json.loads(r_tri.stdout)["verdict"], "BLOCKED_INTEGRITY_OR_STRUCTURAL_GATE")

            led_tr = td / "led_tr.json"
            led_tr.write_text(json.dumps({"compact": True, "status": "structural_issues", "issues": [f"w{i}" for i in range(15)], "total_issues": 16, "issues_truncated": 1, "grandiose_finding_count": 0}), encoding="utf-8")
            r_led = _run_cli(["--scorecard", str(sc), "--ledger", str(led_tr)])
            self.assertEqual(r_led.returncode, 1)
            d_led = json.loads(r_led.stdout)
            self.assertEqual(d_led["cross_tool_gating_audit"]["manuscript_ledger"]["issue_count"], 16)
            self.assertIn("manuscript_ledger_issues_truncated_inspect_full_artifact", d_led["warnings"])

            ps_state = td / "ps_state.json"
            ps_state.write_text(json.dumps({"project_id": "P2", "status": "loaded", "state": {"subfield_preset": "ai_systems"}}), encoding="utf-8")
            r_ps = _run_cli(["--scorecard", str(sc), "--project-state", str(ps_state)])
            self.assertEqual(r_ps.returncode, 0)
            self.assertEqual(json.loads(r_ps.stdout)["subfield_preset"], "ai_systems")

    def test_score_math_and_compare_scorecards_v2_alignment_and_synthesis_invalidation(self):
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            # 1. Case 2 without weight_scenarios (mode=idea & venue_type) + evidence_anchors dict/list collision
            cs_idea = td / "cs_idea.json"
            cs_idea.write_text(json.dumps({
                "mode": "idea",
                "profiles": [
                    {"id": "i1", "reading_basis": "full_text", "closest_work": ["i2"], "ratings": {"evidence_coverage": 8, "novelty": 8, "importance": 8, "answerability": 8, "feasibility": 8, "falsifiability": 8}},
                    {"id": "i2", "reading_basis": "full_text", "closest_work": ["i1"], "ratings": {"evidence_coverage": 6, "novelty": 6, "importance": 6, "answerability": 6, "feasibility": 6, "falsifiability": 6}},
                ],
            }), encoding="utf-8")
            r_ci = _run_cli(["--scorecard", str(cs_idea), "--target-id", "i1"])
            self.assertEqual(r_ci.returncode, 1, r_ci.stderr + r_ci.stdout)
            d_ci = json.loads(r_ci.stdout)
            self.assertEqual(d_ci["score_evaluation"]["mode"], "idea")
            self.assertEqual(d_ci["score_evaluation"]["reviewer_synthesis"]["personas"][0]["focus"], ["novelty", "importance"])

            cs_ea = td / "cs_ea.json"
            cs_ea.write_text(json.dumps({
                "venue_type": "journal_q1",
                "subfield_checks": {"contamination_check": True},
                "evidence_anchors": [
                    {"id": "a1", "reading_basis": "full_text", "topic_relation": "same_topic", "benchmarks_count": 3, "sota_baselines_covered": 4, "ablation_depth": "full", "theoretical_rigor": "high", "effect_size_ci_stability": "95_ci", "code_artifact_openness": "public_repo"},
                    {"id": "a2", "reading_basis": "full_text", "topic_relation": "different_topic", "benchmarks_count": 4, "sota_baselines_covered": 5, "ablation_depth": "full", "theoretical_rigor": "high", "effect_size_ci_stability": "95_ci", "code_artifact_openness": "public_repo"},
                ],
                "profiles": [
                    {"id": "target", "reading_basis": "full_text", "closest_work": ["b1"], "ratings": _ratings((8, 8, 8, 8, 8, 8)), "evidence_anchors": {"benchmarks_count": 4, "sota_baselines_covered": 5}},
                    {"id": "b1", "reading_basis": "full_text", "closest_work": ["target"], "ratings": _ratings((7, 7, 7, 7, 7, 7))},
                ],
            }), encoding="utf-8")
            r_ea = _run_cli(["--scorecard", str(cs_ea), "--target-id", "target", "--subfield-preset", "nlp_llm"])
            self.assertEqual(r_ea.returncode, 0, r_ea.stderr + r_ea.stdout)
            d_ea = json.loads(r_ea.stdout)
            self.assertEqual(d_ea["score_evaluation"]["evidence_anchor_table"]["anchor_count"], 2)
            self.assertIn("subfield_readiness", d_ea["score_evaluation"]["post_cap"])
            self.assertIn("contamination_check", d_ea["subfield_criteria"]["covered_checks"])

            # 2. Invalid section_diagnostics raises exit 2
            sc_bsd = td / "sc_bsd.json"
            sc_bsd.write_text(json.dumps({"weights": _weights(), "ratings": _ratings((8, 8, 8, 8, 8, 8)), "section_diagnostics": {"bogus": 5}}), encoding="utf-8")
            self.assertEqual(_run_cli(["--scorecard", str(sc_bsd)]).returncode, 2)

            # 3. Stale pre-cap ac_synthesis / reviewer_synthesis invalidated when capped
            locs_t = {d: [f't.txt#L1 "ev {d}"'] for d in score_math.DIMENSIONS}
            locs_b = {d: [f'b.txt#L1 "ev {d}"'] for d in score_math.DIMENSIONS}
            cs_panel_in = td / "cs_panel_in.json"
            cs_panel_in.write_text(json.dumps({
                "weight_scenarios": [_weights()],
                "profiles": [
                    {
                        "id": "target", "reading_basis": "full_text", "closest_work": ["b1"], "evidence_locators": locs_t, "ratings": _ratings((8, 7, 8, 8, 8, 8)),
                        "reviewer_panel": [
                            {"reviewer_id": "R1", "confidence": 4, "ratings": _ratings((8, 7, 8, 8, 8, 8))},
                            {"reviewer_id": "R2", "confidence": 4, "ratings": _ratings((8, 7, 8, 8, 8, 8))},
                            {"reviewer_id": "R3", "confidence": 4, "ratings": _ratings((8, 7, 8, 8, 8, 8))},
                        ],
                    },
                    {"id": "b1", "reading_basis": "full_text", "closest_work": ["target"], "evidence_locators": locs_b, "ratings": _ratings((6, 6, 6, 6, 6, 6))},
                ],
            }), encoding="utf-8")
            cs_panel_out = td / "cs_panel_out.json"
            subprocess.run([sys.executable, str(SCRIPTS_DIR / "compare_scorecards.py"), str(cs_panel_in), "--target-id", "target", "--out", str(cs_panel_out)], cwd=str(ROOT), capture_output=True, text=True, check=True)
            art_w = td / "art_w.json"
            art_w.write_text(json.dumps({"schema": "artifact_readiness_v1", "verdict": "WARN", "ready_to_submit": True, "recommended_transparency_cap": 5, "blocking_reasons": []}), encoding="utf-8")
            r_cap = _run_cli(["--scorecard", str(cs_panel_out), "--target-id", "target", "--artifact-readiness", str(art_w)])
            self.assertEqual(r_cap.returncode, 1)
            d_cap = json.loads(r_cap.stdout)
            self.assertEqual(d_cap["score_evaluation"]["ac_synthesis"]["decision"], "incomplete_not_comparable")
            self.assertNotIn("meta_review_verdict", d_cap["score_evaluation"]["ac_synthesis"])
            self.assertEqual(d_cap["score_evaluation"]["reviewer_synthesis"]["source"], "calibrated_fallback")

    def test_r4_single_venue_placeholder_trim_stage3_conflicted_and_edge_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            sc = td / "sc.json"
            sc.write_text(json.dumps({"weights": _weights(), "ratings": _ratings((8, 8, 8, 8, 8, 8))}), encoding="utf-8")

            # 1. Single-venue compare_venue_novelty (omits "venue", non-CCF matched_name="") + failing venue_plan without --target-venue
            vn_single = td / "vn_single_non_ccf.json"
            vn_single.write_text(json.dumps({
                "compact": True,
                "status": "structurally_checked",
                "fit_score_out_of_10": 9,
                "novelty_comparison": {"target_novelty_score": 8, "accepted_panel_median_score": 7},
                "venue_contribution_bar": {"panel_median_overall": 7.0, "target_overall_score": 8.0, "target_vs_venue_overall_delta": 1.0},
                "venue_quality_context": {"quality_tier": "Unknown", "matched_name": "", "matched_source": ""},
                "submission_readiness": {"verdict": "ready", "ready_to_submit": True, "fit_score_out_of_10": 9},
            }), encoding="utf-8")
            vp_custom_bad = td / "vp_custom_bad.json"
            vp_custom_bad.write_text(json.dumps({
                "venue": "CustomML Conf",
                "edition": "2027",
                "track": "Main",
                "cfp_verified": False,
                "within_budget": False,
                "source_issues": [{"issue": "stale_redirect"}],
            }), encoding="utf-8")
            r_sv = _run_cli(["--scorecard", str(sc), "--venue-novelty", str(vn_single), "--venue-plan", str(vp_custom_bad)])
            self.assertEqual(r_sv.returncode, 1, r_sv.stderr + r_sv.stdout)
            d_sv = json.loads(r_sv.stdout)
            self.assertFalse(d_sv["ready_to_submit"])
            self.assertEqual(d_sv["verdict"], "BLOCKED_NO_VIABLE_VENUE")
            self.assertEqual(d_sv["venue_portfolio"]["evaluations"][0]["venue_name"], "CustomML Conf")

            # Direct _match_venue_report fallback for anonymous single-venue placeholder
            self.assertTrue(
                evaluate_submission._match_venue_report(
                    {"venue": "Another Conf"},
                    {"venue_id": "target_venue", "venue_name": "target_venue"},
                    1,
                )
            )

            # 2a. Portfolio trim_stage >= 3 (venue_summaries == [], retargeted_from_rejected_venues stripped) without --target-venue
            sc_665 = td / "sc_665.json"
            sc_665.write_text(json.dumps({"weights": _weights(), "ratings": _ratings((7, 6, 7, 7, 6, 7))}), encoding="utf-8")
            vn_trim3 = td / "vn_trim3.json"
            vn_trim3.write_text(json.dumps({
                "compact": True,
                "mode": "portfolio",
                "status": "structurally_checked",
                "venue_summaries": [],
                "venue_summaries_truncated": 12,
                "venue_portfolio_recommendations": {
                    "portfolio_verdict": "retargeted_to_matched_tier",
                    "recommended_now": [],
                    "viable_fallback": ["emnlp_findings_0_" + ("b" * 45)],
                    "rejected_below_venue_tier": ["neurips_main_" + ("a" * 48)],
                    "recommended_matched_tier": {"matched_tier": "q1_or_tier_a", "recommended_venues": ["emnlp_findings_0_" + ("b" * 45)]},
                },
            }), encoding="utf-8")
            r_t3 = _run_cli(["--scorecard", str(sc_665), "--venue-novelty", str(vn_trim3)])
            self.assertEqual(r_t3.returncode, 0, r_t3.stderr + r_t3.stdout)
            d_t3 = json.loads(r_t3.stdout)
            self.assertTrue(d_t3["ready_to_submit"])
            self.assertEqual(d_t3["verdict"], "RETARGETED_READY")
            self.assertTrue(d_t3["venue_portfolio"]["retargeted"])
            self.assertEqual(d_t3["selected_venue"]["retargeted_from"], "neurips_main_" + ("a" * 48))

            # 2b. Suffixed/year/"::" conflicted_fallback matching + ACL vs ACL Findings / NeurIPS vs NeurIPS Workshop non-collision
            vn_cf = td / "vn_cf.json"
            vn_cf.write_text(json.dumps({
                "compact": True,
                "mode": "portfolio",
                "status": "structurally_checked",
                "venue_summaries": [],
                "venue_summaries_truncated": 4,
                "venue_portfolio_recommendations": {
                    "portfolio_verdict": "retargeted_to_matched_tier",
                    "recommended_now": ["icml_main"],
                    "conflicted_fallback": ["neurips_main_2027", "acl_findings_2027", "NeurIPS::2027::Workshop"],
                },
            }), encoding="utf-8")
            r_cf_n = _run_cli(["--scorecard", str(sc), "--venue-novelty", str(vn_cf), "--target-venue", "NeurIPS"])
            self.assertEqual(r_cf_n.returncode, 1)
            d_cf_n = json.loads(r_cf_n.stdout)
            self.assertTrue(d_cf_n["desk_reject_blocked"])
            self.assertIn("venue_portfolio:selected_venue_conflicted_fallback", d_cf_n["desk_reject_audit"]["reasons"])

            r_cf_a = _run_cli(["--scorecard", str(sc), "--venue-novelty", str(vn_cf), "--target-venue", "ACL"])
            self.assertEqual(r_cf_a.returncode, 0, r_cf_a.stderr + r_cf_a.stdout)
            self.assertFalse(json.loads(r_cf_a.stdout)["desk_reject_blocked"])

            r_cf_nw = _run_cli(["--scorecard", str(sc), "--venue-novelty", str(vn_cf), "--target-venue", "NeurIPS Workshop"])
            self.assertEqual(r_cf_nw.returncode, 1)
            self.assertTrue(json.loads(r_cf_nw.stdout)["desk_reject_blocked"])

            # 3. check_submission_preflight --compact overflow (findings=[], out=None) + summary.WARN bool guard
            pre_over = td / "pre_over.json"
            pre_over.write_text(json.dumps({
                "compact": True,
                "schema": "submission_anonymization_v1",
                "summary": {"ERROR": 2, "WARN": True},
                "verdict": "FAIL",
                "findings": [],
                "out": None,
            }), encoding="utf-8")
            r_po = _run_cli(["--scorecard", str(sc), "--preflight", str(pre_over)])
            self.assertEqual(r_po.returncode, 1)
            d_po = json.loads(r_po.stdout)
            self.assertFalse(d_po["ready_to_submit"])
            self.assertTrue(d_po["desk_reject_blocked"])

            # 4. target_novelty_score bool when --scorecard omitted -> exit 2 without traceback
            vn_bool = td / "vn_bool.json"
            vn_bool.write_text(json.dumps({
                "status": "structurally_checked",
                "novelty_comparison": {"target_novelty_score": True, "accepted_panel_median_score": 6},
                "submission_readiness": {"verdict": "ready", "ready_to_submit": True, "venue_tier": "top_tier_flagship"},
            }), encoding="utf-8")
            r_vb = _run_cli(["--venue-novelty", str(vn_bool)])
            self.assertEqual(r_vb.returncode, 2)
            self.assertNotIn("Traceback", r_vb.stderr)

            # 5. Case 1 compare_scorecards summary with subfield_readiness (no profiles / no top-level subfield_checks)
            cs_sf = td / "cs_sf.json"
            cs_sf.write_text(json.dumps({
                "status": "structurally_comparable",
                "rankings": [{"scenario": "s0", "ordered": ["target"]}],
                "subfield_preset": "nlp_llm",
                "subfield_readiness": {
                    "preset": "nlp_llm",
                    "passed_checks": ["contamination_check", "multi_prompt_variance"],
                    "failed_checks": [],
                    "missing_checks": ["compute_matched_open_weight_baseline", "eval_harness_parity"],
                },
                "submission_readiness": {
                    "target": {"overall": 8, "weighted_unrounded": "8.00", "band": "competitive_top_tier_main_track", "structural_gate_passed": True},
                },
            }), encoding="utf-8")
            r_sf = _run_cli(["--scorecard", str(cs_sf), "--target-id", "target", "--subfield-preset", "nlp_llm"])
            self.assertEqual(r_sf.returncode, 0, r_sf.stderr + r_sf.stdout)
            d_sf = json.loads(r_sf.stdout)
            self.assertEqual(d_sf["subfield_criteria"]["covered_checks"], ["contamination_check", "multi_prompt_variance"])

    def test_r5_conflicted_double_colon_venue_type_min_dims_and_trim_stage3_top_venue(self):
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            sc = td / "sc.json"
            sc.write_text(json.dumps({"weights": _weights(), "ratings": _ratings((8, 8, 8, 8, 8, 8))}), encoding="utf-8")

            # 1. _target_matches_conflicted_id handles "::" IDs where venue.name includes track token (e.g. "ACL Findings::2027::Findings")
            self.assertTrue(evaluate_submission._target_matches_conflicted_id("acl findings", "ACL Findings::2027::Findings"))
            self.assertFalse(evaluate_submission._target_matches_conflicted_id("acl", "ACL Findings::2027::Findings"))

            vn_aclf = td / "vn_aclf.json"
            vn_aclf.write_text(json.dumps({
                "compact": True,
                "mode": "portfolio",
                "status": "structurally_checked",
                "venue_summaries": [],
                "venue_summaries_truncated": 3,
                "venue_portfolio_recommendations": {
                    "portfolio_verdict": "ready_with_primary_and_fallback",
                    "recommended_now": ["ACL::2027::Main", "EMNLP::2027::Main"],
                    "conflicted_fallback": ["ACL Findings::2027::Findings"],
                },
            }), encoding="utf-8")
            r_af = _run_cli(["--scorecard", str(sc), "--venue-novelty", str(vn_aclf), "--target-venue", "ACL Findings"])
            self.assertEqual(r_af.returncode, 1)
            d_af = json.loads(r_af.stdout)
            self.assertTrue(d_af["desk_reject_blocked"])
            self.assertIn("venue_portfolio:selected_venue_conflicted_fallback", d_af["desk_reject_audit"]["reasons"])

            r_a = _run_cli(["--scorecard", str(sc), "--venue-novelty", str(vn_aclf), "--target-venue", "ACL"])
            self.assertEqual(r_a.returncode, 0, r_a.stderr + r_a.stdout)
            self.assertFalse(json.loads(r_a.stdout)["desk_reject_blocked"])

            # 2a. venue_type min_dimensions post-cap: journal_q1 & dataset_benchmark transparency=5 < 6
            art_warn = td / "art_warn.json"
            art_warn.write_text(json.dumps({"verdict": "WARN", "ready_to_submit": True, "recommended_transparency_cap": 5}), encoding="utf-8")
            sc_jq1 = td / "sc_jq1.json"
            sc_jq1.write_text(json.dumps({
                "venue_type": "journal_q1",
                "venue_checks": {"comprehensive_ablations": True, "reproducibility_details": True},
                "ratings": _ratings((8, 7, 8, 8, 7, 8)),
            }), encoding="utf-8")
            vn_jq1 = td / "vn_jq1.json"
            vn_jq1.write_text(json.dumps({
                "status": "structurally_checked",
                "venue_type": "journal_q1",
                "venue": {"name": "TPAMI", "edition": "2027", "track": "Main"},
                "submission_readiness": {"verdict": "ready_strong_panel_standing_and_fit", "ready_to_submit": True, "venue_tier": "q1_or_tier_a"},
            }), encoding="utf-8")
            r_jq1 = _run_cli(["--scorecard", str(sc_jq1), "--venue-novelty", str(vn_jq1), "--artifact-readiness", str(art_warn)])
            self.assertEqual(r_jq1.returncode, 1)
            d_jq1 = json.loads(r_jq1.stdout)
            self.assertFalse(d_jq1["ready_to_submit"])
            self.assertEqual(d_jq1["verdict"], "BLOCKED_NO_VIABLE_VENUE")
            self.assertIn("post_cap_tier_fit:transparency_5_below_journal_q1_min_6", d_jq1["venue_portfolio"]["disqualified_venues"][0]["disqualification_reasons"])

            sc_db = td / "sc_db.json"
            sc_db.write_text(json.dumps({
                "venue_type": "dataset_benchmark",
                "venue_checks": {"data_quality_audit": True, "annotation_protocol": True, "ethics_and_license_t1_t2": True},
                "ratings": _ratings((8, 7, 8, 8, 7, 8)),
            }), encoding="utf-8")
            vn_db = td / "vn_db.json"
            vn_db.write_text(json.dumps({
                "status": "structurally_checked",
                "venue_type": "dataset_benchmark",
                "venue": {"name": "NeurIPS D&B", "edition": "2027", "track": "Main"},
                "submission_readiness": {"verdict": "ready_strong_panel_standing_and_fit", "ready_to_submit": True},
            }), encoding="utf-8")
            r_db = _run_cli(["--scorecard", str(sc_db), "--venue-novelty", str(vn_db), "--artifact-readiness", str(art_warn)])
            self.assertEqual(r_db.returncode, 1)
            d_db = json.loads(r_db.stdout)
            self.assertFalse(d_db["ready_to_submit"])
            self.assertIn("post_cap_tier_fit:transparency_5_below_dataset_benchmark_min_6", d_db["venue_portfolio"]["disqualified_venues"][0]["disqualification_reasons"])

            # 2b. Standalone journal_q1 cap=5 & --target-venue TPAMI / ACM CSUR
            r_st = _run_cli(["--scorecard", str(sc_jq1), "--artifact-readiness", str(art_warn)])
            self.assertEqual(r_st.returncode, 1)
            d_st = json.loads(r_st.stdout)
            self.assertFalse(d_st["ready_to_submit"])
            self.assertEqual(d_st["verdict"], "NOT_READY_BELOW_BAR")
            self.assertEqual(d_st["upgrade_gaps_to_target_tier"].get("transparency"), 1)
            self.assertTrue(any(a["code"] == "venue_tier_fit:transparency_5_below_journal_q1_min_6" for a in d_st["action_plan"]))
            self.assertTrue(any(a["code"] == "lift_transparency" for a in d_st["action_plan"]))

            sc_srv = td / "sc_srv.json"
            sc_srv.write_text(json.dumps({
                "venue_type": "survey_review",
                "venue_checks": {"systematic_coverage_protocol": True},
                "ratings": _ratings((8, 7, 8, 8, 7, 5)),
            }), encoding="utf-8")
            r_srv = _run_cli(["--scorecard", str(sc_srv), "--target-venue", "ACM CSUR"])
            self.assertEqual(r_srv.returncode, 1)
            d_srv = json.loads(r_srv.stdout)
            self.assertFalse(d_srv["ready_to_submit"])
            self.assertIn("post_cap_tier_fit:clarity_5_below_survey_review_min_6", d_srv["venue_portfolio"]["disqualified_venues"][0]["disqualification_reasons"])

            # 2c. Portfolio with journal_q1 + workshop fallback: workshop must NOT be blocked by transparency>=6
            vn_mix = td / "vn_mix.json"
            vn_mix.write_text(json.dumps({
                "mode": "portfolio",
                "venue_type": "journal_q1",
                "venue_evaluations": [
                    {"venue_id": "tpami", "venue_name": "TPAMI", "track": "Main", "role": "primary", "venue_tier": "q1_or_tier_a", "classification": "recommended_now", "fit_score_out_of_10": 9},
                    {"venue_id": "ws_fb", "venue_name": "Eval Workshop", "track": "Workshop", "role": "fallback", "venue_tier": "workshop_or_preliminary", "classification": "viable_fallback", "fit_score_out_of_10": 8},
                ],
            }), encoding="utf-8")
            r_mix = _run_cli(["--scorecard", str(sc_jq1), "--venue-novelty", str(vn_mix), "--artifact-readiness", str(art_warn), "--target-venue", "TPAMI"])
            self.assertEqual(r_mix.returncode, 0, r_mix.stderr + r_mix.stdout)
            d_mix = json.loads(r_mix.stdout)
            self.assertEqual(d_mix["verdict"], "RETARGETED_READY")
            self.assertEqual(d_mix["selected_venue"]["venue_id"], "ws_fb")
            self.assertEqual(d_mix["selected_venue"]["venue_tier"], "workshop_or_preliminary")

            # 3. trim_stage >= 3 with top_venue_id outside viable_fallback[:3] & no false q1_or_tier_a on workshop
            sc_665 = td / "sc_665.json"
            sc_665.write_text(json.dumps({"weights": _weights(), "ratings": _ratings((7, 6, 7, 7, 6, 7))}), encoding="utf-8")
            top_id = "emnlp_findings_0_" + ("a" * 40)
            ws1_id = "conf_ws_01_" + ("a" * 40)
            vn_t3_top = td / "vn_t3_top.json"
            vn_t3_top.write_text(json.dumps({
                "compact": True,
                "mode": "portfolio",
                "status": "structurally_checked",
                "venue_summaries": [],
                "venue_summaries_truncated": 31,
                "venue_portfolio_recommendations": {
                    "portfolio_verdict": "retargeted_to_matched_tier",
                    "recommended_now": [],
                    "viable_fallback": [ws1_id, "conf_ws_02_" + ("a" * 40), "conf_ws_03_" + ("a" * 40)],
                    "rejected_below_venue_tier": ["neurips_main_" + ("a" * 40)],
                    "recommended_matched_tier": {
                        "matched_tier": "q1_or_tier_a",
                        "top_venue_id": top_id,
                        "recommended_venues": [top_id, ws1_id],
                    },
                },
            }), encoding="utf-8")
            r_t3_top = _run_cli(["--scorecard", str(sc_665), "--venue-novelty", str(vn_t3_top)])
            self.assertEqual(r_t3_top.returncode, 0, r_t3_top.stderr + r_t3_top.stdout)
            d_t3_top = json.loads(r_t3_top.stdout)
            self.assertEqual(d_t3_top["verdict"], "RETARGETED_READY")
            self.assertEqual(d_t3_top["selected_venue"]["venue_id"], top_id)
            self.assertEqual(d_t3_top["selected_venue"]["venue_tier"], "q1_or_tier_a")
            self.assertEqual(d_t3_top["selected_venue"]["retargeted_from"], "neurips_main_" + ("a" * 40))
            ws1_entry = next(v for v in d_t3_top["venue_portfolio"]["surviving_venues"] if v["venue_id"] == ws1_id)
            self.assertIsNone(ws1_entry["venue_tier"])

    def test_r6_real_compare_venue_novelty_portfolio_ccf_a_flagship_q1_db_retargets_to_workshop(self):
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            now = datetime.now(timezone.utc)
            iso = lambda days: (now + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

            # 1. Real check_artifact_readiness.py WARN (recommended_transparency_cap == 5)
            warn_repo = td / "warn_repo"
            (warn_repo / "data").mkdir(parents=True, exist_ok=True)
            (warn_repo / "README.md").write_text("# Repo\n## Dataset\nUses data/splits.csv.\n## Reproduce\n`python3 train.py --seed 42`\n", encoding="utf-8")
            (warn_repo / "requirements.txt").write_text("numpy\n", encoding="utf-8")
            (warn_repo / "LICENSE").write_text("MIT License\n", encoding="utf-8")
            (warn_repo / "train.py").write_text("import random\nrandom.seed(42)\n", encoding="utf-8")
            art_warn = td / "art_warn.json"
            r_art = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "check_artifact_readiness.py"), "--repo-dir", str(warn_repo), "--anonymous", "--out", str(art_warn)],
                cwd=str(ROOT), capture_output=True, text=True, check=False,
            )
            self.assertEqual(r_art.returncode, 0, r_art.stderr + r_art.stdout)
            self.assertEqual(json.loads(art_warn.read_text(encoding="utf-8"))["recommended_transparency_cap"], 5)

            # 2. Local sources-dir for real compare_venue_novelty.py --portfolio
            src_dir = td / "sources"
            src_dir.mkdir()
            cfp_url = "https://example.org/r6-cfp"
            (src_dir / "venue-sources.json").write_text(json.dumps({
                "format": "research_scientist_venue_sources_v1",
                "sources": [{
                    "requested_url": cfp_url,
                    "final_url": cfp_url,
                    "extraction_status": "ok",
                    "same_host_path_redirect_year_mismatch": False,
                    "js_rendered_suspected": False,
                    "text": "TPAMI NeurIPS D&B Workshop 2027. Submission open. Fee USD 0.",
                }],
            }), encoding="utf-8")
            (src_dir / "target.txt").write_text("Full text target evidence.\n", encoding="utf-8")

            base_fix = json.loads((ROOT / "research-scientist" / "references" / "venue-novelty-profile.fixture.json").read_text(encoding="utf-8"))
            tgt = copy.deepcopy(base_fix["target"])
            tgt.update({
                "id": "target", "score": 8, "low": 7, "high": 9,
                "closest_work_id": "target", "closest_work_locator": 'target.txt#L1 "Full text target"',
                "assessed_at_utc": iso(0),
            })

            def _mk_panel(prefix: str, trk: str):
                rows = copy.deepcopy(base_fix["accepted_panel"])
                for i, row in enumerate(rows):
                    pid = f"{prefix}_{i}"
                    (src_dir / f"{pid}.txt").write_text("Accepted evidence.\n", encoding="utf-8")
                    row.update({
                        "id": pid, "track": trk, "score": 6, "low": 5, "high": 7,
                        "overall_score": 6.5, "topic_relation": "different_topic",
                        "closest_work_id": pid, "closest_work_locator": f'{pid}.txt#L1 "Accepted evidence"',
                        "assessed_at_utc": iso(0),
                    })
                return rows

            def _mk_cand(vid: str, name: str, trk: str, role: str, dl: int, nt: int):
                ps = copy.deepcopy(base_fix["panel_selection"])
                ps["track"] = trk
                return {
                    "venue_id": vid, "role": role,
                    "venue": {
                        "name": name, "edition": "2027", "track": trk,
                        "official_cfp_url": cfp_url, "checked_at_utc": iso(0),
                        "max_source_age_days": 14,
                        "submission_deadline_utc": iso(dl), "notification_date_utc": iso(nt),
                        "simultaneous_submission_allowed": False,
                    },
                    "panel_selection": ps, "accepted_panel": _mk_panel(vid, trk),
                    "fit_axes": [
                        {"name": ax, "score": 2, "source_url": cfp_url, "locator": '"Submission open."', "reason": "ok"}
                        for ax in ("scope_audience", "contribution_track", "evidence_maturity", "format_eligibility", "user_constraints")
                    ],
                    "hard_constraints": [
                        {"name": cn, "status": "met", "source_url": cfp_url, "reason": "ok"}
                        for cn in ("deadline", "budget", "eligibility")
                    ],
                }

            ratings = _ratings((8, 7, 8, 8, 7, 8))
            cases = [
                ("tpami", "journal_q1", "tpami_main", "TPAMI", "Main", "TPAMI", {"comprehensive_ablations": True, "reproducibility_details": True}, "post_cap_tier_fit:transparency_5_below_journal_q1_min_6"),
                ("ndb", "dataset_benchmark", "neurips_db", "NeurIPS", "Datasets and Benchmarks", "NeurIPS", {"data_quality_audit": True, "annotation_protocol": True, "ethics_and_license_t1_t2": True}, "post_cap_tier_fit:transparency_5_below_dataset_benchmark_min_6"),
            ]
            for tag, vtype, vid0, name0, trk0, tgt_arg, checks, exp_reason in cases:
                sc = td / f"sc_{tag}.json"
                sc.write_text(json.dumps({"venue_type": vtype, "venue_checks": checks, "ratings": ratings}), encoding="utf-8")
                port_in = td / f"port_{tag}.json"
                port_in.write_text(json.dumps({
                    "venue_type": vtype,
                    "venue_checks": checks,
                    "target": tgt,
                    "target_scorecard": {"venue_type": vtype, "venue_checks": checks, "ratings": ratings},
                    "candidate_venues": [
                        _mk_cand(vid0, name0, trk0, "primary", 30, 90),
                        _mk_cand("neurips_ws", "NeurIPS Workshop", "Workshop", "fallback", 120, 150),
                        _mk_cand("icml_ws", "ICML Workshop", "Workshop", "fallback", 180, 210),
                    ],
                }), encoding="utf-8")
                vn_full = td / f"vn_{tag}_full.json"
                r_vn = subprocess.run(
                    [sys.executable, str(SCRIPTS_DIR / "compare_venue_novelty.py"), str(port_in), "--portfolio", "--sources-dir", str(src_dir), "--out", str(vn_full), "--compact"],
                    cwd=str(ROOT), capture_output=True, text=True, check=False,
                )
                self.assertEqual(r_vn.returncode, 0, r_vn.stderr + r_vn.stdout)
                vn_comp_obj = json.loads(r_vn.stdout)
                vn_comp_obj.pop("artifact_path", None)
                vn_comp = td / f"vn_{tag}_comp.json"
                vn_comp.write_text(json.dumps(vn_comp_obj), encoding="utf-8")

                for vn_p in (vn_full, vn_comp):
                    r_ev = _run_cli(["--scorecard", str(sc), "--venue-novelty", str(vn_p), "--artifact-readiness", str(art_warn), "--target-venue", tgt_arg])
                    self.assertEqual(r_ev.returncode, 0, r_ev.stderr + r_ev.stdout)
                    d_ev = json.loads(r_ev.stdout)
                    self.assertTrue(d_ev["ready_to_submit"])
                    self.assertEqual(d_ev["verdict"], "RETARGETED_READY")
                    self.assertEqual(d_ev["selected_venue"]["venue_tier"], "workshop_or_preliminary")
                    self.assertEqual(d_ev["selected_venue"]["retargeted_from"], vid0)
                    disq = next(v for v in d_ev["venue_portfolio"]["disqualified_venues"] if v["venue_id"] == vid0)
                    self.assertIn(exp_reason, disq["disqualification_reasons"])
                    lift_codes = [a["code"] for a in d_ev["action_plan"] if str(a.get("code", "")).startswith("lift_")]
                    self.assertEqual(len(lift_codes), len(set(lift_codes)))

                    ev_out = td / f"ev_{tag}_{vn_p.stem}.json"
                    r_ev_c = _run_cli(["--scorecard", str(sc), "--venue-novelty", str(vn_p), "--artifact-readiness", str(art_warn), "--target-venue", tgt_arg, "--out", str(ev_out), "--compact"])
                    self.assertEqual(r_ev_c.returncode, 0, r_ev_c.stderr + r_ev_c.stdout)
                    self.assertLess(len(r_ev_c.stdout.encode("utf-8")), 4096)
                    dc = json.loads(r_ev_c.stdout)
                    self.assertTrue(dc["ready_to_submit"])
                    self.assertEqual(dc["verdict"], "RETARGETED_READY")
                    self.assertEqual(dc["selected_venue"]["venue_tier"], "workshop_or_preliminary")
                    self.assertEqual(dc["selected_venue"]["retargeted_from"], vid0)

            # 3. Tier boundaries: q2_q3_or_tier_b retargets cleanly; workshop_preliminary never weakens top_tier_flagship
            sc_q2 = td / "sc_q2.json"
            sc_q2.write_text(json.dumps({
                "venue_type": "journal_q1",
                "venue_checks": {"comprehensive_ablations": True, "reproducibility_details": True},
                "ratings": _ratings((8, 7, 8, 8, 5, 8)),
            }), encoding="utf-8")
            vn_q2 = td / "vn_q2.json"
            vn_q2.write_text(json.dumps({
                "mode": "portfolio",
                "venue_type": "journal_q1",
                "venue_evaluations": [
                    {"venue_id": "jmlr_main", "venue_name": "JMLR", "role": "primary", "venue_tier": "top_tier_flagship", "classification": "recommended_now", "fit_score_out_of_10": 9},
                    {"venue_id": "tier_b_j", "venue_name": "Tier-B Journal", "role": "fallback", "venue_tier": "q2_q3_or_tier_b", "classification": "viable_fallback", "fit_score_out_of_10": 8},
                ],
            }), encoding="utf-8")
            r_q2 = _run_cli(["--scorecard", str(sc_q2), "--venue-novelty", str(vn_q2), "--target-venue", "JMLR"])
            self.assertEqual(r_q2.returncode, 0, r_q2.stderr + r_q2.stdout)
            d_q2 = json.loads(r_q2.stdout)
            self.assertEqual(d_q2["verdict"], "RETARGETED_READY")
            self.assertEqual(d_q2["selected_venue"]["venue_id"], "tier_b_j")
            self.assertIn("post_cap_tier_fit:transparency_5_below_journal_q1_min_6", d_q2["venue_portfolio"]["disqualified_venues"][0]["disqualification_reasons"])

            sc_ws = td / "sc_ws.json"
            sc_ws.write_text(json.dumps({"venue_type": "workshop_preliminary", "ratings": _ratings((8, 7, 5, 5, 7, 8))}), encoding="utf-8")
            vn_ws = td / "vn_ws.json"
            vn_ws.write_text(json.dumps({
                "mode": "portfolio",
                "venue_type": "workshop_preliminary",
                "venue_evaluations": [
                    {"venue_id": "neurips_main", "venue_name": "NeurIPS", "role": "primary", "venue_tier": "top_tier_flagship", "classification": "recommended_now", "fit_score_out_of_10": 9},
                    {"venue_id": "ml_ws", "venue_name": "ML Workshop", "role": "fallback", "venue_tier": "workshop_or_preliminary", "classification": "viable_fallback", "fit_score_out_of_10": 8},
                ],
            }), encoding="utf-8")
            r_ws = _run_cli(["--scorecard", str(sc_ws), "--venue-novelty", str(vn_ws), "--target-venue", "NeurIPS"])
            self.assertEqual(r_ws.returncode, 0, r_ws.stderr + r_ws.stdout)
            d_ws = json.loads(r_ws.stdout)
            self.assertEqual(d_ws["verdict"], "RETARGETED_READY")
            self.assertEqual(d_ws["selected_venue"]["venue_id"], "ml_ws")
            ws_disq_r = d_ws["venue_portfolio"]["disqualified_venues"][0]["disqualification_reasons"]
            self.assertTrue(any("soundness_5_below_top_tier_flagship_min_6" in x for x in ws_disq_r), ws_disq_r)
            self.assertTrue(any("evidence_5_below_top_tier_flagship_min_6" in x for x in ws_disq_r), ws_disq_r)

    def test_r7_single_and_synthesized_venue_rank_aware_compatibility_cases_a_to_d(self):
        self.assertIsNone(evaluate_submission._compatible_venue_type("workshop_preliminary", "top_tier_flagship"))
        self.assertEqual(evaluate_submission._compatible_venue_type("workshop_preliminary", "workshop_or_preliminary"), "workshop_preliminary")
        self.assertEqual(evaluate_submission._compatible_venue_type("journal_q1", "top_tier_flagship"), "journal_q1")
        self.assertIsNone(evaluate_submission._compatible_venue_type("journal_q1", "workshop_or_preliminary"))
        self.assertIsNone(evaluate_submission._compatible_venue_type("journal_q1", "q2_q3_or_tier_b"))

        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            # Cases A & B: workshop_preliminary (soundness=5, evidence=5) targeting top_tier_flagship
            sc_ws = td / "sc_ws.json"
            sc_ws.write_text(json.dumps({
                "venue_type": "workshop_preliminary",
                "ratings": _ratings((8, 7, 5, 5, 7, 8)),
            }), encoding="utf-8")
            vn_single_top = td / "vn_single_top.json"
            vn_single_top.write_text(json.dumps({
                "status": "structurally_checked",
                "venue": {"name": "NeurIPS", "edition": "2027", "track": "Main"},
                "submission_readiness": {"verdict": "ready", "ready_to_submit": True, "venue_tier": "top_tier_flagship"},
            }), encoding="utf-8")

            for args in (
                ["--scorecard", str(sc_ws), "--target-venue", "NeurIPS", "--target-venue-tier", "top_tier_flagship"],
                ["--scorecard", str(sc_ws), "--venue-novelty", str(vn_single_top), "--target-venue", "NeurIPS"],
            ):
                r = _run_cli(args)
                self.assertEqual(r.returncode, 1, r.stderr + r.stdout)
                d = json.loads(r.stdout)
                self.assertFalse(d["ready_to_submit"])
                self.assertEqual(d["verdict"], "BLOCKED_NO_VIABLE_VENUE")
                disq_r = d["venue_portfolio"]["disqualified_venues"][0]["disqualification_reasons"]
                self.assertIn("post_cap_tier_fit:soundness_5_below_top_tier_flagship_min_6", disq_r)
                self.assertIn("post_cap_tier_fit:evidence_5_below_top_tier_flagship_min_6", disq_r)

            # Cases C & D: journal_q1 (transparency=5) targeting Eval Workshop (workshop_or_preliminary)
            sc_jq1 = td / "sc_jq1.json"
            sc_jq1.write_text(json.dumps({
                "venue_type": "journal_q1",
                "venue_checks": {"comprehensive_ablations": True, "reproducibility_details": True},
                "ratings": _ratings((8, 7, 8, 8, 5, 8)),
            }), encoding="utf-8")
            vn_single_ws = td / "vn_single_ws.json"
            vn_single_ws.write_text(json.dumps({
                "status": "structurally_checked",
                "venue": {"name": "Eval Workshop", "edition": "2027", "track": "Workshop"},
                "submission_readiness": {"verdict": "ready", "ready_to_submit": True, "venue_tier": "workshop_or_preliminary"},
            }), encoding="utf-8")

            for args in (
                ["--scorecard", str(sc_jq1), "--target-venue", "Eval Workshop"],
                ["--scorecard", str(sc_jq1), "--venue-novelty", str(vn_single_ws), "--target-venue", "Eval Workshop"],
            ):
                r = _run_cli(args)
                self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
                d = json.loads(r.stdout)
                self.assertTrue(d["ready_to_submit"])
                self.assertEqual(d["verdict"], "READY_TO_SUBMIT")
                self.assertEqual(d["selected_venue"]["venue_tier"], "workshop_or_preliminary")

            # Failed rigor contamination check must not be listed in subfield_criteria.covered_checks
            contam_bad = td / "contam_bad.json"
            contam_bad.write_text(json.dumps({"schema": "experiment_rigor_contamination_v1", "verdict": "CONTAMINATION_DETECTED"}), encoding="utf-8")
            r_cb = _run_cli(["--scorecard", str(sc_jq1), "--rigor", str(contam_bad), "--subfield-preset", "nlp_llm"])
            self.assertEqual(r_cb.returncode, 1)
            d_cb = json.loads(r_cb.stdout)
            self.assertNotIn("contamination_check", d_cb["subfield_criteria"]["covered_checks"])
            self.assertIn("contamination_check", d_cb["subfield_criteria"]["missing_checks"])

    def test_r7_trim_stage3_compact_without_out_no_disk_artifact_enforces_venue_type_and_floor(self):
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            now = datetime.now(timezone.utc)
            iso = lambda days: (now + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

            warn_repo = td / "warn_repo"
            (warn_repo / "data").mkdir(parents=True, exist_ok=True)
            (warn_repo / "README.md").write_text("# Repo\n## Dataset\nUses data/splits.csv.\n## Reproduce\n`python3 train.py --seed 42`\n", encoding="utf-8")
            (warn_repo / "requirements.txt").write_text("numpy\n", encoding="utf-8")
            (warn_repo / "LICENSE").write_text("MIT License\n", encoding="utf-8")
            (warn_repo / "train.py").write_text("import random\nrandom.seed(42)\n", encoding="utf-8")
            art_warn = td / "art_warn.json"
            r_art = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "check_artifact_readiness.py"), "--repo-dir", str(warn_repo), "--anonymous", "--out", str(art_warn)],
                cwd=str(ROOT), capture_output=True, text=True, check=False,
            )
            self.assertEqual(r_art.returncode, 0, r_art.stderr + r_art.stdout)
            self.assertEqual(json.loads(art_warn.read_text(encoding="utf-8"))["recommended_transparency_cap"], 5)

            src_dir = td / "sources"
            src_dir.mkdir()
            cfp_url = "https://example.org/r7-cfp"
            (src_dir / "venue-sources.json").write_text(json.dumps({
                "format": "research_scientist_venue_sources_v1",
                "sources": [{
                    "requested_url": cfp_url, "final_url": cfp_url, "extraction_status": "ok",
                    "same_host_path_redirect_year_mismatch": False, "js_rendered_suspected": False,
                    "text": "TPAMI AAAI NeurIPS ICML LREC Workshop 2027. Submission open. Fee USD 0.",
                }],
            }), encoding="utf-8")
            (src_dir / "target.txt").write_text("Full text target evidence.\n", encoding="utf-8")

            base_fix = json.loads((ROOT / "research-scientist" / "references" / "venue-novelty-profile.fixture.json").read_text(encoding="utf-8"))
            tgt = copy.deepcopy(base_fix["target"])
            tgt.update({
                "id": "target", "score": 8, "low": 7, "high": 9,
                "closest_work_id": "target", "closest_work_locator": 'target.txt#L1 "Full text target"',
                "assessed_at_utc": iso(0),
            })

            def _mk_panel(prefix: str, trk: str):
                rows = copy.deepcopy(base_fix["accepted_panel"])
                for i, row in enumerate(rows):
                    pid = f"{prefix}_{i}"
                    (src_dir / f"{pid}.txt").write_text("Accepted evidence.\n", encoding="utf-8")
                    row.update({
                        "id": pid, "track": trk, "score": 6, "low": 5, "high": 7,
                        "overall_score": 6.5, "topic_relation": "different_topic",
                        "closest_work_id": pid, "closest_work_locator": f'{pid}.txt#L1 "Accepted evidence"',
                        "assessed_at_utc": iso(0),
                    })
                return rows

            def _mk_cand(vid: str, name: str, trk: str, role: str, dl: int, nt: int):
                ps = copy.deepcopy(base_fix["panel_selection"])
                ps["track"] = trk
                return {
                    "venue_id": vid, "role": role,
                    "venue": {
                        "name": name, "edition": "2027", "track": trk,
                        "official_cfp_url": cfp_url, "checked_at_utc": iso(0),
                        "max_source_age_days": 14,
                        "submission_deadline_utc": iso(dl), "notification_date_utc": iso(nt),
                        "simultaneous_submission_allowed": False,
                    },
                    "panel_selection": ps, "accepted_panel": _mk_panel(vid, trk),
                    "fit_axes": [{"name": ax, "score": 2, "source_url": cfp_url, "locator": '"Submission open."', "reason": "ok"} for ax in ("scope_audience", "contribution_track", "evidence_maturity", "format_eligibility", "user_constraints")],
                    "hard_constraints": [{"name": cn, "status": "met", "source_url": cfp_url, "reason": "ok"} for cn in ("deadline", "budget", "eligibility")],
                }

            ratings_good = _ratings((8, 7, 8, 8, 7, 8))
            jq1_checks = {"comprehensive_ablations": True, "reproducibility_details": True}

            # Scenario A: TPAMI journal_q1 + 25 workshops, no weights, --compact WITHOUT --out
            cands_a = [_mk_cand("tpami_main_" + "p" * 120, "TPAMI", "Main", "primary", 30, 90)]
            for i in range(25):
                cands_a.append(_mk_cand(f"neurips_workshop_id_{i:02d}_" + "w" * 100, f"NeurIPS Workshop {i}", "Workshop", "fallback", 120 + i * 3, 150 + i * 3))
            port_a = td / "port_a.json"
            port_a.write_text(json.dumps({
                "venue_type": "journal_q1", "venue_checks": jq1_checks, "target": tgt,
                "target_scorecard": {"venue_type": "journal_q1", "venue_checks": jq1_checks, "ratings": ratings_good},
                "candidate_venues": cands_a,
            }), encoding="utf-8")
            r_vna = subprocess.run([sys.executable, str(SCRIPTS_DIR / "compare_venue_novelty.py"), str(port_a), "--portfolio", "--sources-dir", str(src_dir), "--compact"], cwd=str(ROOT), capture_output=True, text=True, check=False)
            self.assertEqual(r_vna.returncode, 0, r_vna.stderr + r_vna.stdout)
            vn_a_obj = json.loads(r_vna.stdout)
            self.assertEqual(vn_a_obj["venue_summaries"], [])
            self.assertIsNone(vn_a_obj.get("artifact_path"))
            vn_a = td / "vn_a.json"
            vn_a.write_text(r_vna.stdout, encoding="utf-8")
            sc_a = td / "sc_a.json"
            sc_a.write_text(json.dumps({"venue_type": "journal_q1", "venue_checks": jq1_checks, "ratings": ratings_good}), encoding="utf-8")
            r_eva = _run_cli(["--scorecard", str(sc_a), "--venue-novelty", str(vn_a), "--artifact-readiness", str(art_warn), "--target-venue", "TPAMI"])
            self.assertEqual(r_eva.returncode, 0, r_eva.stderr + r_eva.stdout)
            d_eva = json.loads(r_eva.stdout)
            self.assertEqual(d_eva["verdict"], "RETARGETED_READY")
            self.assertEqual(d_eva["selected_venue"]["venue_tier"], "workshop_or_preliminary")
            self.assertTrue(d_eva["selected_venue"]["retargeted_from"].startswith("tpami_main_"))
            disq_a = next(v for v in d_eva["venue_portfolio"]["disqualified_venues"] if v["venue_id"].startswith("tpami_main_"))
            self.assertIn("post_cap_tier_fit:transparency_5_below_journal_q1_min_6", disq_a["disqualification_reasons"])

            # Scenario B: AAAI + TPAMI + 25 workshops, WITH weights, --compact WITHOUT --out
            w_jq1 = {"importance": 15, "novelty": 15, "soundness": 25, "evidence": 25, "transparency": 10, "clarity": 10}
            cands_b = [
                _mk_cand("aaai_main_venue_top_00_" + "a" * 100, "AAAI", "Main", "primary", 30, 90),
                _mk_cand("tpami_main_venue_01_" + "p" * 100, "TPAMI", "Main", "primary", 60, 120),
            ]
            for i in range(25):
                cands_b.append(_mk_cand(f"neurips_workshop_id_{i:02d}_" + "w" * 100, f"NeurIPS Workshop {i}", "Workshop", "fallback", 150 + i * 3, 180 + i * 3))
            port_b = td / "port_b.json"
            port_b.write_text(json.dumps({
                "venue_type": "journal_q1", "venue_checks": jq1_checks, "target": tgt,
                "target_scorecard": {"venue_type": "journal_q1", "venue_checks": jq1_checks, "weights": w_jq1, "ratings": ratings_good},
                "candidate_venues": cands_b,
            }), encoding="utf-8")
            r_vnb = subprocess.run([sys.executable, str(SCRIPTS_DIR / "compare_venue_novelty.py"), str(port_b), "--portfolio", "--sources-dir", str(src_dir), "--compact"], cwd=str(ROOT), capture_output=True, text=True, check=False)
            self.assertEqual(r_vnb.returncode, 0, r_vnb.stderr + r_vnb.stdout)
            vn_b_obj = json.loads(r_vnb.stdout)
            self.assertEqual(vn_b_obj["venue_summaries"], [])
            self.assertIsNone(vn_b_obj.get("artifact_path"))
            vn_b = td / "vn_b.json"
            vn_b.write_text(r_vnb.stdout, encoding="utf-8")
            r_evb = _run_cli(["--scorecard", str(sc_a), "--venue-novelty", str(vn_b), "--artifact-readiness", str(art_warn), "--target-venue", "TPAMI"])
            self.assertEqual(r_evb.returncode, 0, r_evb.stderr + r_evb.stdout)
            d_evb = json.loads(r_evb.stdout)
            self.assertEqual(d_evb["verdict"], "RETARGETED_READY")
            self.assertEqual(d_evb["selected_venue"]["venue_tier"], "workshop_or_preliminary")
            self.assertTrue(d_evb["selected_venue"]["retargeted_from"].startswith("tpami_main_venue_01_"))
            disq_b_ids = {v["venue_id"] for v in d_evb["venue_portfolio"]["disqualified_venues"]}
            self.assertTrue(any(x.startswith("aaai_main_venue_top_00_") for x in disq_b_ids))
            self.assertTrue(any(x.startswith("tpami_main_venue_01_") for x in disq_b_ids))

            # Scenario E: dataset_benchmark (NeurIPS D&B + LREC + 45 conf_ws workshops, --compact WITHOUT --out)
            db_checks = {"data_quality_audit": True, "annotation_protocol": True, "ethics_and_license_t1_t2": True}
            cands_e = [
                _mk_cand("neurips_db_" + "d" * 100, "NeurIPS", "Datasets and Benchmarks", "primary", 30, 90),
                _mk_cand("lrec_main_" + "l" * 100, "LREC", "Main", "primary", 60, 120),
            ]
            for i in range(45):
                cands_e.append(_mk_cand(f"conf_ws_{i:02d}_" + "w" * 100, f"ConfWS {i}", "Workshop", "fallback", 150 + i * 2, 180 + i * 2))
            port_e = td / "port_e.json"
            port_e.write_text(json.dumps({
                "venue_type": "dataset_benchmark", "venue_checks": db_checks, "target": tgt,
                "target_scorecard": {"venue_type": "dataset_benchmark", "venue_checks": db_checks, "ratings": ratings_good},
                "candidate_venues": cands_e,
            }), encoding="utf-8")
            r_vne = subprocess.run([sys.executable, str(SCRIPTS_DIR / "compare_venue_novelty.py"), str(port_e), "--portfolio", "--sources-dir", str(src_dir), "--compact"], cwd=str(ROOT), capture_output=True, text=True, check=False)
            self.assertEqual(r_vne.returncode, 0, r_vne.stderr + r_vne.stdout)
            vn_e_obj = json.loads(r_vne.stdout)
            self.assertEqual(vn_e_obj["venue_summaries"], [])
            self.assertIsNone(vn_e_obj.get("artifact_path"))
            vn_e = td / "vn_e.json"
            vn_e.write_text(r_vne.stdout, encoding="utf-8")
            sc_e = td / "sc_e.json"
            sc_e.write_text(json.dumps({"venue_type": "dataset_benchmark", "venue_checks": db_checks, "ratings": ratings_good}), encoding="utf-8")
            r_eve = _run_cli(["--scorecard", str(sc_e), "--venue-novelty", str(vn_e), "--artifact-readiness", str(art_warn), "--target-venue", "NeurIPS", "--compact"])
            self.assertEqual(r_eve.returncode, 0, r_eve.stderr + r_eve.stdout)
            d_eve = json.loads(r_eve.stdout)
            self.assertEqual(d_eve["verdict"], "RETARGETED_READY")
            self.assertTrue(d_eve["selected_venue"]["venue_id"].startswith("conf_ws_"))
            self.assertIsNone(d_eve["selected_venue"]["venue_tier"])
            self.assertTrue(d_eve["selected_venue"]["retargeted_from"].startswith("neurips_db_"))

            # Scenario F: conference_top_tier (NeurIPS Main + ICML + 45 conf_ws, 6.10 -> 5.90 via cap=5, full == compact_disk == compact_nodisk)
            ratings_f = _ratings((6, 6, 6, 6, 7, 6))
            cands_f = [
                _mk_cand("neurips_main_" + "n" * 100, "NeurIPS", "Main", "primary", 30, 90),
                _mk_cand("icml_main_" + "i" * 100, "ICML", "Main", "primary", 60, 120),
            ]
            for i in range(45):
                cands_f.append(_mk_cand(f"conf_ws_{i:02d}_" + "w" * 100, f"ConfWS {i}", "Workshop", "fallback", 150 + i * 2, 180 + i * 2))
            port_f = td / "port_f.json"
            port_f.write_text(json.dumps({
                "venue_type": "conference_top_tier", "target": tgt,
                "target_scorecard": {"venue_type": "conference_top_tier", "ratings": ratings_f},
                "candidate_venues": cands_f,
            }), encoding="utf-8")
            vn_f_full = td / "vn_f_full.json"
            r_vnf = subprocess.run([sys.executable, str(SCRIPTS_DIR / "compare_venue_novelty.py"), str(port_f), "--portfolio", "--sources-dir", str(src_dir), "--out", str(vn_f_full), "--compact"], cwd=str(ROOT), capture_output=True, text=True, check=False)
            self.assertEqual(r_vnf.returncode, 0, r_vnf.stderr + r_vnf.stdout)
            vn_f_disk = td / "vn_f_disk.json"
            vn_f_disk.write_text(r_vnf.stdout, encoding="utf-8")
            vn_f_nodisk_obj = json.loads(r_vnf.stdout)
            self.assertEqual(vn_f_nodisk_obj["venue_summaries"], [])
            vn_f_nodisk_obj.pop("artifact_path", None)
            vn_f_nodisk = td / "vn_f_nodisk.json"
            vn_f_nodisk.write_text(json.dumps(vn_f_nodisk_obj), encoding="utf-8")
            sc_f = td / "sc_f.json"
            sc_f.write_text(json.dumps({"venue_type": "conference_top_tier", "ratings": ratings_f}), encoding="utf-8")

            for lbl, vnp in (("full", vn_f_full), ("compact_disk", vn_f_disk), ("compact_nodisk", vn_f_nodisk)):
                r_evf = _run_cli(["--scorecard", str(sc_f), "--venue-novelty", str(vnp), "--artifact-readiness", str(art_warn), "--target-venue", "NeurIPS", "--compact"])
                self.assertEqual(r_evf.returncode, 0, f"{lbl}: {r_evf.stderr + r_evf.stdout}")
                self.assertLess(len(r_evf.stdout.encode("utf-8")), 4096)
                d_evf = json.loads(r_evf.stdout)
                self.assertEqual(d_evf["verdict"], "RETARGETED_READY", lbl)
                self.assertEqual(d_evf["weighted_unrounded"], "5.9", lbl)
                self.assertTrue(d_evf["selected_venue"]["venue_id"].startswith("conf_ws_"), lbl)
                self.assertTrue(d_evf["selected_venue"]["retargeted_from"].startswith("neurips_main_"), lbl)

    def test_r8_venue_leads_fallback_and_unconditional_tier_preservation_4mode_parity(self):
        # Unit checks on _lookup_venue_leads_tier guardrails
        self.assertEqual(evaluate_submission._lookup_venue_leads_tier("NeurIPS"), "top_tier_flagship")
        self.assertEqual(evaluate_submission._lookup_venue_leads_tier("neurips_main_" + "n" * 60), "top_tier_flagship")
        self.assertEqual(evaluate_submission._lookup_venue_leads_tier("acl_main_" + "a" * 60), "top_tier_flagship")
        self.assertEqual(evaluate_submission._lookup_venue_leads_tier("emnlp_main_" + "e" * 60), "q1_or_tier_a")
        self.assertIsNone(evaluate_submission._lookup_venue_leads_tier("conf_ws_00_" + "w" * 60))
        self.assertIsNone(evaluate_submission._lookup_venue_leads_tier("neurips_workshop_00_" + "w" * 60))
        self.assertIsNone(evaluate_submission._lookup_venue_leads_tier("acl_findings_00_" + "f" * 60))
        self.assertIsNone(evaluate_submission._lookup_venue_leads_tier("CustomML Conf"))

        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            now = datetime.now(timezone.utc)
            iso = lambda days: (now + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

            # Synthesized-venue --target-venue NeurIPS without --target-venue-tier blocks workshop_preliminary
            sc_ws = td / "sc_ws.json"
            sc_ws.write_text(json.dumps({"venue_type": "workshop_preliminary", "ratings": _ratings((8, 7, 5, 5, 7, 8))}), encoding="utf-8")
            r_synth = _run_cli(["--scorecard", str(sc_ws), "--target-venue", "NeurIPS"])
            self.assertEqual(r_synth.returncode, 1, r_synth.stderr + r_synth.stdout)
            d_synth = json.loads(r_synth.stdout)
            self.assertEqual(d_synth["verdict"], "BLOCKED_NO_VIABLE_VENUE")
            self.assertEqual(d_synth["venue_portfolio"]["disqualified_venues"][0]["venue_tier"], "top_tier_flagship")

            src_dir = td / "sources"
            src_dir.mkdir()
            cfp_url = "https://example.org/r8-cfp"
            (src_dir / "venue-sources.json").write_text(json.dumps({
                "format": "research_scientist_venue_sources_v1",
                "sources": [{
                    "requested_url": cfp_url, "final_url": cfp_url, "extraction_status": "ok",
                    "same_host_path_redirect_year_mismatch": False, "js_rendered_suspected": False,
                    "text": "TPAMI AAAI Journal Q1 NeurIPS ACL Tier-B Conf Workshop 2027. Submission open. Fee USD 0.",
                }],
            }), encoding="utf-8")
            (src_dir / "target.txt").write_text("Full text target evidence.\n", encoding="utf-8")

            base_fix = json.loads((ROOT / "research-scientist" / "references" / "venue-novelty-profile.fixture.json").read_text(encoding="utf-8"))
            tgt = copy.deepcopy(base_fix["target"])
            tgt.update({
                "id": "target", "score": 8, "low": 7, "high": 9,
                "closest_work_id": "target", "closest_work_locator": 'target.txt#L1 "Full text target"',
                "assessed_at_utc": iso(0),
            })

            def _mk_panel(prefix: str, trk: str, ov: float = 6.5, sc_val: int = 6):
                rows = copy.deepcopy(base_fix["accepted_panel"])
                for i, row in enumerate(rows):
                    pid = f"{prefix}_{i}"
                    (src_dir / f"{pid}.txt").write_text("Accepted evidence.\n", encoding="utf-8")
                    row.update({
                        "id": pid, "track": trk, "score": sc_val, "low": max(1, sc_val - 1), "high": min(10, sc_val + 1),
                        "overall_score": ov, "topic_relation": "different_topic",
                        "closest_work_id": pid, "closest_work_locator": f'{pid}.txt#L1 "Accepted evidence"',
                        "assessed_at_utc": iso(0),
                    })
                return rows

            def _mk_cand(vid: str, name: str, trk: str, role: str, dl: int, nt: int, ov: float = 6.5, sc_val: int = 6):
                ps = copy.deepcopy(base_fix["panel_selection"])
                ps["track"] = trk
                return {
                    "venue_id": vid, "role": role,
                    "venue": {
                        "name": name, "edition": "2027", "track": trk,
                        "official_cfp_url": cfp_url, "checked_at_utc": iso(0), "max_source_age_days": 14,
                        "submission_deadline_utc": iso(dl), "notification_date_utc": iso(nt), "simultaneous_submission_allowed": False,
                    },
                    "panel_selection": ps, "accepted_panel": _mk_panel(vid, trk, ov=ov, sc_val=sc_val),
                    "fit_axes": [{"name": ax, "score": 2, "source_url": cfp_url, "locator": '"Submission open."', "reason": "ok"} for ax in ("scope_audience", "contribution_track", "evidence_maturity", "format_eligibility", "user_constraints")],
                    "hard_constraints": [{"name": cn, "status": "met", "source_url": cfp_url, "reason": "ok"} for cn in ("deadline", "budget", "eligibility")],
                }

            def _run_4mode(tag: str, port_obj: dict, sc_obj: dict, *, tgt_venue: str, extra_args: list[str] | tuple[str, ...] = ()):
                pf = td / f"{tag}_port.json"
                pf.write_text(json.dumps(port_obj), encoding="utf-8")
                vn_full = td / f"{tag}_vn_full.json"
                r1 = subprocess.run([sys.executable, str(SCRIPTS_DIR / "compare_venue_novelty.py"), str(pf), "--portfolio", "--sources-dir", str(src_dir), "--out", str(vn_full), "--compact"], cwd=str(ROOT), capture_output=True, text=True, check=False)
                self.assertEqual(r1.returncode, 0, tag + ": " + r1.stderr + r1.stdout)
                vn_disk = td / f"{tag}_vn_disk.json"
                vn_disk.write_text(r1.stdout, encoding="utf-8")
                r2 = subprocess.run([sys.executable, str(SCRIPTS_DIR / "compare_venue_novelty.py"), str(pf), "--portfolio", "--sources-dir", str(src_dir), "--compact"], cwd=str(ROOT), capture_output=True, text=True, check=False)
                self.assertEqual(r2.returncode, 0, tag + ": " + r2.stderr + r2.stdout)
                vn_noout = td / f"{tag}_vn_noout.json"
                vn_noout.write_text(r2.stdout, encoding="utf-8")
                nodisk_obj = json.loads(r1.stdout)
                self.assertEqual(nodisk_obj["venue_summaries"], [], tag)
                nodisk_obj.pop("artifact_path", None)
                vn_nodisk = td / f"{tag}_vn_nodisk.json"
                vn_nodisk.write_text(json.dumps(nodisk_obj), encoding="utf-8")

                scf = td / f"{tag}_sc.json"
                scf.write_text(json.dumps(sc_obj), encoding="utf-8")
                docs = {}
                sigs = {}
                for mode, vnp in (("full", vn_full), ("compact_disk", vn_disk), ("compact_noout", vn_noout), ("compact_nodisk", vn_nodisk)):
                    ev = _run_cli(["--scorecard", str(scf), "--venue-novelty", str(vnp), "--target-venue", tgt_venue, *extra_args])
                    d = json.loads(ev.stdout)
                    docs[mode] = d
                    sel = d.get("selected_venue") or {}
                    sigs[mode] = (ev.returncode, d["ready_to_submit"], d["verdict"], sel.get("venue_id"), sel.get("retargeted_from"))
                self.assertEqual(len(set(sigs.values())), 1, f"{tag} 4-mode mismatch: {sigs}")
                return sigs["full"], docs

            art5 = td / "art5.json"
            art5.write_text(json.dumps({"schema": "artifact_readiness_v1", "verdict": "WARN", "ready_to_submit": True, "recommended_transparency_cap": 5, "blocking_reasons": []}), encoding="utf-8")
            art4 = td / "art4.json"
            art4.write_text(json.dumps({"schema": "artifact_readiness_v1", "verdict": "WARN", "ready_to_submit": True, "recommended_transparency_cap": 4, "blocking_reasons": []}), encoding="utf-8")
            led5 = td / "led5.json"
            led5.write_text(json.dumps({"status": "structure_passed", "issues": [], "grandiose_findings": [], "argument_audit": {"enabled": True, "recommended_evidence_cap": 5}}), encoding="utf-8")
            jq1_chk = {"comprehensive_ablations": True, "reproducibility_details": True}
            w_std = _weights()
            r_good = _ratings((8, 7, 8, 8, 7, 8))

            # 1. tpami_q1_01_... (journal_q1, cap=5, --target-venue TPAMI) -> RETARGETED_READY to conf_ws_00_...
            c1 = [_mk_cand("tpami_q1_01_" + "p" * 100, "TPAMI", "Main", "primary", 30, 90)] + [_mk_cand(f"conf_ws_{i:02d}_" + "w" * 100, f"ConfWS {i}", "Workshop", "fallback", 120 + i * 2, 140 + i * 2, ov=5.5, sc_val=5) for i in range(25)]
            s1, d1 = _run_4mode("tpami_q1", {"venue_type": "journal_q1", "venue_checks": jq1_chk, "target": tgt, "target_scorecard": {"venue_type": "journal_q1", "venue_checks": jq1_chk, "weights": w_std, "ratings": r_good}, "candidate_venues": c1}, {"venue_type": "journal_q1", "venue_checks": jq1_chk, "weights": w_std, "ratings": r_good}, tgt_venue="TPAMI", extra_args=["--artifact-readiness", str(art5)])
            self.assertEqual((s1[0], s1[2]), (0, "RETARGETED_READY"))
            self.assertTrue(s1[3].startswith("conf_ws_00_") and s1[4].startswith("tpami_q1_01_"))
            self.assertIn("post_cap_tier_fit:transparency_5_below_journal_q1_min_6", d1["compact_nodisk"]["venue_portfolio"]["disqualified_venues"][0]["disqualification_reasons"])

            # 2. aaai_main_00_... + journal_q1_01_... (journal_q1, cap=5, --target-venue "Journal Q1")
            c2 = [_mk_cand("aaai_main_00_" + "a" * 100, "AAAI", "Main", "primary", 30, 90), _mk_cand("journal_q1_01_" + "j" * 100, "Journal Q1", "Main", "primary", 60, 120)] + [_mk_cand(f"conf_ws_{i:02d}_" + "w" * 100, f"ConfWS {i}", "Workshop", "fallback", 150 + i * 2, 170 + i * 2, ov=5.5, sc_val=5) for i in range(25)]
            s2, d2 = _run_4mode("journal_q1", {"venue_type": "journal_q1", "venue_checks": jq1_chk, "target": tgt, "target_scorecard": {"venue_type": "journal_q1", "venue_checks": jq1_chk, "weights": w_std, "ratings": r_good}, "candidate_venues": c2}, {"venue_type": "journal_q1", "venue_checks": jq1_chk, "weights": w_std, "ratings": r_good}, tgt_venue="Journal Q1", extra_args=["--artifact-readiness", str(art5)])
            self.assertEqual((s2[0], s2[2]), (0, "RETARGETED_READY"))
            self.assertTrue(s2[3].startswith("conf_ws_00_"))
            self.assertEqual(len(d2["compact_nodisk"]["venue_portfolio"]["disqualified_venues"]), 2)

            # 3. conf_q2_00_... (q2_q3_or_tier_b, post-cap weighted=5 < 5.50)
            w_t50 = {"importance": 10, "novelty": 10, "soundness": 10, "evidence": 10, "transparency": 50, "clarity": 10}
            c3 = [_mk_cand("neurips_main_00_" + "n" * 100, "NeurIPS", "Main", "primary", 30, 90), _mk_cand("conf_q2_00_" + "q" * 100, "Conf Q2", "Main", "fallback", 100, 120, ov=5.5, sc_val=5)] + [_mk_cand(f"conf_ws_{i:02d}_" + "w" * 100, f"ConfWS {i}", "Workshop", "fallback", 140 + i * 2, 160 + i * 2, ov=5.5, sc_val=5) for i in range(25)]
            s3, d3 = _run_4mode("conf_q2", {"target": tgt, "target_scorecard": {"weights": w_t50, "ratings": _ratings((6, 6, 6, 6, 6, 6))}, "candidate_venues": c3}, {"weights": w_t50, "ratings": _ratings((6, 6, 6, 6, 6, 6))}, tgt_venue="NeurIPS", extra_args=["--artifact-readiness", str(art4)])
            self.assertEqual((s3[0], s3[2]), (0, "RETARGETED_READY"))
            self.assertTrue(s3[3].startswith("conf_ws_00_") and s3[4].startswith("neurips_main_00_"))
            q2_disq = next(v for v in d3["compact_nodisk"]["venue_portfolio"]["disqualified_venues"] if v["venue_id"].startswith("conf_q2_00_"))
            self.assertIn("post_cap_tier_fit:weighted_5_below_q2_q3_or_tier_b_min_5.50", q2_disq["disqualification_reasons"])

            # 4a. acl_findings_00_... (viable_fallback, --ledger cap=5) -> BLOCKED_NO_VIABLE_VENUE
            c4a = [_mk_cand("neurips_main_" + "n" * 100, "NeurIPS", "Main", "primary", 30, 90)] + [_mk_cand(f"acl_findings_{i:02d}_" + "f" * 100, f"ACL {i}", "Findings", "fallback", 120 + i * 2, 140 + i * 2) for i in range(25)]
            s4a, d4a = _run_4mode("acl_findings_blk", {"target": tgt, "target_scorecard": {"weights": w_std, "ratings": r_good}, "candidate_venues": c4a}, {"weights": w_std, "ratings": r_good}, tgt_venue="NeurIPS", extra_args=["--ledger", str(led5)])
            self.assertEqual((s4a[0], s4a[2]), (1, "BLOCKED_NO_VIABLE_VENUE"))
            f0_disq = next(v for v in d4a["compact_nodisk"]["venue_portfolio"]["disqualified_venues"] if v["venue_id"].startswith("acl_findings_00_"))
            self.assertIn("post_cap_tier_fit:evidence_5_below_q1_or_tier_a_min_6", f0_disq["disqualification_reasons"])

            # 4b. acl_findings_2027_... (soundness=5 < 6) -> RETARGETED_READY to conf_ws_00_...
            c4b = [_mk_cand("neurips_main_2027_" + "n" * 100, "NeurIPS", "Main", "primary", 30, 90), _mk_cand("acl_findings_2027_" + "a" * 100, "ACL Findings", "Findings", "fallback", 100, 120)] + [_mk_cand(f"conf_ws_{i:02d}_" + "w" * 100, f"ConfWS {i}", "Workshop", "fallback", 140 + i * 2, 160 + i * 2, ov=5.5, sc_val=5) for i in range(45)]
            s4b, _ = _run_4mode("acl_findings_ret", {"target": tgt, "target_scorecard": {"weights": w_std, "ratings": _ratings((8, 7, 6, 8, 8, 8))}, "candidate_venues": c4b}, {"weights": w_std, "ratings": _ratings((8, 7, 5, 8, 8, 8))}, tgt_venue="ACL Findings")
            self.assertEqual((s4b[0], s4b[2]), (0, "RETARGETED_READY"))
            self.assertTrue(s4b[3].startswith("conf_ws_00_") and s4b[4].startswith("acl_findings_2027_"))

            # 5. tier_b_conf_2027_... (q2_q3_or_tier_b, weighted=5.20 < 5.50)
            c5 = [_mk_cand("tier_b_conf_2027_" + "b" * 100, "Tier-B Conf", "Main", "primary", 30, 90, ov=5.5, sc_val=5)] + [_mk_cand(f"conf_ws_{i:02d}_" + "w" * 100, f"ConfWS {i}", "Workshop", "fallback", 120 + i * 2, 140 + i * 2, ov=5.5, sc_val=5) for i in range(46)]
            s5, _ = _run_4mode("tier_b_ret", {"target": tgt, "target_scorecard": {"weights": w_std, "ratings": _ratings((6, 6, 5, 6, 5, 5))}, "candidate_venues": c5}, {"weights": w_std, "ratings": _ratings((5, 5, 5, 6, 5, 5))}, tgt_venue="Tier-B Conf")
            self.assertEqual((s5[0], s5[2]), (0, "RETARGETED_READY"))
            self.assertTrue(s5[3].startswith("conf_ws_00_") and s5[4].startswith("tier_b_conf_2027_"))

            # 6. neurips_main_... with workshop_preliminary, raw ratings=(8,7,5,5,7,8), matched_tier=None
            c6 = [_mk_cand("neurips_main_" + "n" * 100, "NeurIPS", "Main", "primary", 30, 90)] + [_mk_cand(f"conf_ws_{i:02d}_" + "w" * 100, f"ConfWS {i}", "Workshop", "fallback", 120 + i * 2, 140 + i * 2, ov=5.5, sc_val=5) for i in range(25)]
            s6, _ = _run_4mode("neurips_ws_prelim", {"venue_type": "workshop_preliminary", "target": tgt, "target_scorecard": {"venue_type": "workshop_preliminary", "ratings": _ratings((8, 7, 5, 5, 7, 8))}, "candidate_venues": c6}, {"venue_type": "workshop_preliminary", "ratings": _ratings((8, 7, 5, 5, 7, 8))}, tgt_venue="NeurIPS")
            self.assertEqual((s6[0], s6[2]), (0, "RETARGETED_READY"))
            self.assertTrue(s6[3].startswith("conf_ws_00_") and s6[4].startswith("neurips_main_"))

            # 7. Non-conflicted acl_main_... in viable_fallback (conference_top_tier, 6.10 -> 5.90 via cap=5)
            c7 = [_mk_cand("neurips_main_" + "n" * 100, "NeurIPS", "Main", "primary", 30, 90), _mk_cand("acl_main_" + "a" * 100, "ACL", "Main", "fallback", 100, 120)] + [_mk_cand(f"conf_ws_{i:02d}_" + "w" * 100, f"ConfWS {i}", "Workshop", "fallback", 140 + i * 2, 160 + i * 2, ov=5.5, sc_val=5) for i in range(45)]
            s7, d7 = _run_4mode("acl_main_fb", {"venue_type": "conference_top_tier", "target": tgt, "target_scorecard": {"venue_type": "conference_top_tier", "ratings": _ratings((6, 6, 6, 6, 7, 6))}, "candidate_venues": c7}, {"venue_type": "conference_top_tier", "ratings": _ratings((6, 6, 6, 6, 7, 6))}, tgt_venue="NeurIPS", extra_args=["--artifact-readiness", str(art5)])
            self.assertEqual((s7[0], s7[2]), (0, "RETARGETED_READY"))
            self.assertTrue(s7[3].startswith("conf_ws_00_") and s7[4].startswith("neurips_main_"))
            self.assertTrue(any(v["venue_id"].startswith("acl_main_") for v in d7["compact_nodisk"]["venue_portfolio"]["disqualified_venues"]))


if __name__ == "__main__":
    unittest.main()
