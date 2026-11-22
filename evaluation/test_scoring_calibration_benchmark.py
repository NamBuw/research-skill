"""Unmocked calibration benchmark & review triage unit/contract tests (M10C)."""
from __future__ import annotations

import copy
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "research-scientist" / "scripts"
BENCHMARK_DIR = ROOT / "evaluation" / "fixtures" / "calibration_benchmark"
SOURCES_DIR = BENCHMARK_DIR / "sources"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


score_math = _load_module("score_math", SCRIPTS_DIR / "score_math.py")
compare_scorecards = _load_module("compare_scorecards", SCRIPTS_DIR / "compare_scorecards.py")
compare_venue_novelty = _load_module("compare_venue_novelty", SCRIPTS_DIR / "compare_venue_novelty.py")
triage_reviews = _load_module("triage_reviews", SCRIPTS_DIR / "triage_reviews.py")
claim_audit = _load_module("claim_audit", SCRIPTS_DIR / "claim_audit.py")

AS_OF = datetime(2026, 11, 22, 0, 0, 0, tzinfo=timezone.utc)
FABRICATED_ODDS_RE = re.compile(
    r"\b\d+(?:\.\d+)?%\s*(?:acceptance|chance|odds|probability)",
    re.IGNORECASE,
)


class TestCalibrationBenchmarkScoringLadder(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = json.loads((BENCHMARK_DIR / "benchmark_manifest.json").read_text(encoding="utf-8"))

    def test_benchmark_manifest_and_all_sources_verify_with_zero_errors(self) -> None:
        self.assertEqual(
            set(self.manifest["subfields"]),
            {"nlp_llm", "cv_multimodal", "ml_theory", "ai_systems"},
        )
        covered_subfields = {entry["subfield_preset"] for entry in self.manifest["tiers"]}
        self.assertEqual(covered_subfields, {"nlp_llm", "cv_multimodal", "ml_theory", "ai_systems"})
        self.assertEqual(len(self.manifest["tiers"]), 6)

        for entry in self.manifest["tiers"]:
            doc = json.loads((BENCHMARK_DIR / entry["file"]).read_text(encoding="utf-8"))
            csc = compare_scorecards.compare(
                doc["scorecards_bundle"],
                sources_dir=SOURCES_DIR,
                target_id=entry["target_id"],
                strict_related_panel=True,
                min_related=3,
            )
            self.assertEqual(csc["status"], "structurally_comparable", (entry["tier_id"], csc.get("issues")))
            self.assertEqual(csc["locator_verification"]["failed"], 0, entry["tier_id"])

            vn = compare_venue_novelty.check(
                doc["venue_portfolio"],
                as_of=AS_OF,
                sources_dir=SOURCES_DIR,
                portfolio=True,
                require_panels=True,
            )
            self.assertEqual(vn["status"], "structurally_checked", (entry["tier_id"], vn.get("errors")))
            self.assertEqual(vn["errors"], [], entry["tier_id"])

    def test_strict_monotonic_tier_ordering_and_readiness_bands(self) -> None:
        tier_docs = {
            entry["tier_id"]: json.loads((BENCHMARK_DIR / entry["file"]).read_text(encoding="utf-8"))
            for entry in self.manifest["tiers"]
        }
        ordered_ids = [
            "tier1_top_oral",
            "tier2_main_accept",
            "tier3_borderline_findings",
            "tier4_workshop",
            "tier5a_clear_reject",
        ]
        weighted_scores = []
        merit_scores = []
        floor_scores = []

        for tid in ordered_ids:
            doc = tier_docs[tid]
            sc = score_math.score(doc["scorecard"])
            sr = sc["submission_readiness"]
            self.assertEqual(sr["band"], doc["meta"]["expected_band"], tid)
            self.assertEqual(Decimal(sc["weighted_unrounded"]), Decimal(doc["meta"]["expected_weighted_unrounded"]), tid)
            self.assertIsNone(FABRICATED_ODDS_RE.search(sr["guidance"]), tid)
            weighted_scores.append(Decimal(sc["weighted_unrounded"]))

            mr = triage_reviews.run_mock_review(doc, subfield_preset=doc["subfield_preset"])
            merit_scores.append(mr["merit_vs_publishability"]["scientific_merit_score"])
            floor_scores.append(mr["worst_case_sensitivity"]["worst_case_reviewer_floor"])

        for i in range(len(weighted_scores) - 1):
            self.assertGreater(weighted_scores[i], weighted_scores[i + 1], ordered_ids[i])
            self.assertGreater(merit_scores[i], merit_scores[i + 1], ordered_ids[i])
            self.assertGreater(floor_scores[i], floor_scores[i + 1], ordered_ids[i])

        # Fatal gate trap (weighted 7.20 with soundness=4) overrides high mean
        fatal_doc = tier_docs["tier5b_fatal_gate"]
        fatal_sc = score_math.score(fatal_doc["scorecard"])
        self.assertEqual(Decimal(fatal_sc["weighted_unrounded"]), Decimal("7.20"))
        self.assertEqual(fatal_sc["submission_readiness"]["band"], "not_ready_fatal_gate")
        self.assertTrue(fatal_sc["submission_readiness"]["fatal_gate_triggered"])
        self.assertFalse(fatal_sc["submission_readiness"]["ready_for_top_tier_main_track"])
        self.assertFalse(fatal_sc["submission_readiness"]["ready_for_findings_or_tier_a"])

    def test_tier_mismatch_rejection_and_matched_retargeting(self) -> None:
        tier_docs = {
            entry["tier_id"]: json.loads((BENCHMARK_DIR / entry["file"]).read_text(encoding="utf-8"))
            for entry in self.manifest["tiers"]
        }

        # Tier 3 (6.35): stretch_high_risk at flagship, recommended_now at findings
        t3_vn = compare_venue_novelty.check(
            tier_docs["tier3_borderline_findings"]["venue_portfolio"],
            as_of=AS_OF,
            sources_dir=SOURCES_DIR,
            portfolio=True,
            require_panels=True,
        )
        t3_by_id = {v["venue_id"]: v["classification"] for v in t3_vn["venue_evaluations"]}
        self.assertEqual(t3_by_id["flagship_conf"], "stretch_high_risk")
        self.assertEqual(t3_by_id["findings_tier_a"], "recommended_now")

        # Tier 4 (5.40): hard rejected at flagship & q1_or_tier_a (NEVER stretch_high_risk)
        t4_vn = compare_venue_novelty.check(
            tier_docs["tier4_workshop"]["venue_portfolio"],
            as_of=AS_OF,
            sources_dir=SOURCES_DIR,
            portfolio=True,
            require_panels=True,
        )
        t4_by_id = {v["venue_id"]: v["classification"] for v in t4_vn["venue_evaluations"]}
        self.assertEqual(t4_by_id["flagship_conf"], "rejected_below_venue_tier")
        self.assertEqual(t4_by_id["findings_tier_a"], "rejected_below_venue_tier")
        self.assertEqual(t4_by_id["workshop_track"], "viable_fallback")
        self.assertEqual(t4_vn["venue_portfolio_recommendations"]["portfolio_verdict"], "retargeted_to_matched_tier")
        self.assertEqual(
            t4_vn["venue_portfolio_recommendations"]["recommended_matched_tier"]["matched_tier"],
            "workshop_or_preliminary",
        )

        # Tier 5a (4.50): no viable venue
        t5a_vn = compare_venue_novelty.check(
            tier_docs["tier5a_clear_reject"]["venue_portfolio"],
            as_of=AS_OF,
            sources_dir=SOURCES_DIR,
            portfolio=True,
            require_panels=True,
        )
        self.assertEqual(t5a_vn["venue_portfolio_recommendations"]["portfolio_verdict"], "no_viable_venue_in_portfolio")

        # Tier 5b (7.20 fatal): hold_for_rework
        t5b_vn = compare_venue_novelty.check(
            tier_docs["tier5b_fatal_gate"]["venue_portfolio"],
            as_of=AS_OF,
            sources_dir=SOURCES_DIR,
            portfolio=True,
            require_panels=True,
        )
        self.assertEqual(t5b_vn["venue_portfolio_recommendations"]["portfolio_verdict"], "hold_for_rework")

    def test_tampered_locator_fails_closed(self) -> None:
        doc = json.loads((BENCHMARK_DIR / "tiers" / "tier2_main_accept_cv_multimodal.json").read_text(encoding="utf-8"))
        bad_sc = copy.deepcopy(doc["scorecards_bundle"])
        bad_sc["profiles"][0]["evidence_locators"]["soundness"] = ['target_tier2_cv_accept.txt#L3 "completely fabricated quote"']
        csc = compare_scorecards.compare(
            bad_sc,
            sources_dir=SOURCES_DIR,
            target_id=doc["target_id"],
            strict_related_panel=True,
            min_related=3,
        )
        self.assertEqual(csc["status"], "not_comparable")

        bad_vn = copy.deepcopy(doc["venue_portfolio"])
        bad_vn["target"]["closest_work_locator"] = 'target_tier2_cv_accept.txt#L1 "nonexistent fabricated phrase"'
        vn = compare_venue_novelty.check(
            bad_vn,
            as_of=AS_OF,
            sources_dir=SOURCES_DIR,
            portfolio=True,
            require_panels=True,
        )
        self.assertEqual(vn["status"], "invalid")


class TestTriageReviewsUnitAndSubfields(unittest.TestCase):
    def test_mode1_mock_review_3_personas_f30_hooks_and_compact_upstream(self) -> None:
        doc = json.loads((BENCHMARK_DIR / "triage" / "mode1_pre_submission_nlp_llm.json").read_text(encoding="utf-8"))
        # Also verify compact upstream ingestion works cleanly
        compact_ledger = {
            "compact": True,
            "status": "structural_issues",
            "issues": ["inflated_method_name:UltraSolver"],
            "grandiose_finding_count": 1,
            "argument_audit": {
                "enabled": True,
                "claim_scope_alignment": {"status": "FAIL", "finding_count": 1},
                "contribution_evidence_map": {"status": "PASS", "mapped_count": 2, "orphan_count": 0},
                "related_work_differentiation": {"status": "FAIL", "expected_count": 3, "missing_count": 1, "lacks_differentiation_count": 0},
                "recommended_transparency_cap": 3,
                "recommended_evidence_cap": 4,
            },
        }
        compact_ar = {
            "compact": True,
            "schema": "artifact_readiness_v1",
            "verdict": "FAIL",
            "ready_to_submit": False,
            "recommended_transparency_cap": 3,
            "blocking_reasons": ["secrets_detected"],
            "warnings": [],
        }
        res = triage_reviews.run_mock_review(
            doc,
            ledger_obj=compact_ledger,
            artifact_obj=compact_ar,
            venue_tier="top_tier_flagship",
            scale="iclr_1_10",
            subfield_preset="nlp_llm",
        )
        self.assertEqual(set(res["personas"].keys()), {"method_theory", "experiments_baselines", "novelty_positioning"})
        self.assertGreater(res["defect_counts"]["fatal"], 0)
        self.assertEqual(res["overall_verdict"], "fatal_gate_triggered")

        # F30#5 anchor contrast
        ac = res["side_by_side_anchor_contrast"]
        self.assertEqual(ac["anchor_count"], 2)
        self.assertEqual(ac["same_topic_count"], 1)
        self.assertEqual(ac["cross_topic_count"], 1)
        self.assertEqual(ac["target_profile"]["benchmarks_count"], "unverified")  # never fabricated

        # F30#6 merit vs publishability split
        mvp = res["merit_vs_publishability"]
        self.assertEqual(mvp["recommended_transparency_cap"], 3)
        self.assertEqual(mvp["recommended_evidence_cap"], 4)
        self.assertLess(mvp["publishability_packaging_score"], mvp["scientific_merit_score"])
        self.assertIn(mvp["bottleneck_diagnosis"], ("both_bottlenecked", "packaging_and_venue_bottleneck"))

        # F30#7 exact 6 sections
        sec_diag = res["section_diagnostics"]
        for sec in ("abstract", "introduction", "related_work", "method", "experiments", "limitations"):
            self.assertIn(sec, sec_diag)
        self.assertEqual(sec_diag["related_work"]["status"], "fatal")
        self.assertEqual(sec_diag["experiments"]["status"], "fatal")
        self.assertEqual(len(sec_diag["priority_edit_order"]), 6)

        # F30#8 worst-case floor & deal-breakers
        tier2 = json.loads((BENCHMARK_DIR / "tiers" / "tier2_main_accept_cv_multimodal.json").read_text(encoding="utf-8"))
        t2_res = triage_reviews.run_mock_review(tier2, venue_tier="top_tier_flagship", subfield_preset="cv_multimodal")
        wcs = t2_res["worst_case_sensitivity"]
        self.assertIsNotNone(wcs["worst_case_reviewer_floor"])
        self.assertIn(wcs["worst_case_persona"], ("method_theory", "experiments_baselines", "novelty_positioning"))
        # For tier3 (7,6,7,6,6,6), -1 on evidence (6->5) breaks top_tier_flagship floor (evidence>=6)
        tier3 = json.loads((BENCHMARK_DIR / "tiers" / "tier3_borderline_ai_systems.json").read_text(encoding="utf-8"))
        t3_res = triage_reviews.run_mock_review(tier3, venue_tier="top_tier_flagship", subfield_preset="ai_systems")
        self.assertIn("evidence", t3_res["worst_case_sensitivity"]["deal_breaker_dimensions"])
        # When novelty is at floor 5, -1 on novelty (5->4) also triggers tier rejection deal-breaker
        nov_floor_doc = copy.deepcopy(tier3)
        nov_floor_doc["scorecard"]["ratings"]["novelty"] = 5
        nov_res = triage_reviews.run_mock_review(nov_floor_doc, venue_tier="top_tier_flagship", subfield_preset="ai_systems")
        self.assertIn("novelty", nov_res["worst_case_sensitivity"]["deal_breaker_dimensions"])

        # Non-rescuable check on soundness=4 fatal gate
        tier5b = json.loads((BENCHMARK_DIR / "tiers" / "tier5_fatal_gate_cv_multimodal.json").read_text(encoding="utf-8"))
        t5b_res = triage_reviews.run_mock_review(tier5b, venue_tier="top_tier_flagship", subfield_preset="cv_multimodal")
        self.assertIn("clarity", t5b_res["worst_case_sensitivity"]["non_rescuable_dimensions"])

        # Zero fabricated % acceptance odds
        self.assertIsNone(FABRICATED_ODDS_RE.search(json.dumps(res)))

    def test_all_four_subfield_presets_and_cross_check_alignment(self) -> None:
        expected_keys = {
            "nlp_llm": {"contamination_check", "multi_prompt_variance", "compute_matched_open_weight_baseline", "eval_harness_parity"},
            "cv_multimodal": {"backbone_resolution_augmentation_parity", "flops_fps_memory_tradeoff", "qualitative_failure_analysis"},
            "ml_theory": {"assumption_tightness_realism", "lower_vs_upper_bound_gap", "empirical_sanity_validation"},
            "ai_systems": {"end_to_end_vs_microbenchmark", "tail_latency_p99", "peak_vram_comm_overhead", "matched_hardware"},
            "speech_audio": {"speaker_session_disjoint_split", "audio_metric_and_normalization_parity", "decoding_vocoder_embedding_parity", "speech_slice_significance_and_consent"},
        }
        fixture_map = {
            "nlp_llm": "mode1_pre_submission_nlp_llm.json",
            "cv_multimodal": "mode1_pre_submission_cv_multimodal.json",
            "ml_theory": "mode1_pre_submission_ml_theory.json",
            "ai_systems": "mode1_pre_submission_ai_systems.json",
            "speech_audio": "mode1_pre_submission_speech_audio.json",
        }
        for preset, fname in fixture_map.items():
            doc = json.loads((BENCHMARK_DIR / "triage" / fname).read_text(encoding="utf-8"))
            res = triage_reviews.run_mock_review(doc, subfield_preset=preset)
            spa = res["subfield_preset_audit"]
            self.assertEqual(spa["active_preset"], preset)
            self.assertEqual(set(spa["presets"].keys()), {"nlp_llm", "cv_multimodal", "ml_theory", "ai_systems", "speech_audio"})
            self.assertEqual(set(spa["required_checks"]), expected_keys[preset])
            self.assertEqual(spa["status"], "FAIL", preset)
            self.assertTrue(spa["failed_checks"], preset)

    def test_mode2_h1_h17_firewall_context_caveats_and_2_4_week_plan(self) -> None:
        m2_doc = json.loads((BENCHMARK_DIR / "triage" / "mode2_post_reject_h1_h17_triage.json").read_text(encoding="utf-8"))
        res = triage_reviews.run_post_reject_triage(
            m2_doc["comments"],
            venue_a=m2_doc["venue_a"],
            venue_b_obj=m2_doc["venue_b"],
            scorecard_obj=m2_doc["scorecard"],
            as_of_str="2026-11-22T00:00:00Z",
            weeks=3,
        )
        filtered_ids = {h["heuristic_id"] for h in res["filtered_illegitimate_heuristics"]}
        self.assertEqual(filtered_ids, {"H5", "H7", "H12", "H13", "H16"})
        sub_codes = {d["code"] for d in res["substantive_defects"]}
        self.assertEqual(sub_codes, {"M2", "R1", "R5", "G3"})
        self.assertEqual(res["venue_b_checks"]["status"], "ready_for_resubmission")
        self.assertEqual(set(res["revision_plan"]["schedule"].keys()), {"Week 1", "Week 2", "Week 3"})
        scheduled_ids = {
            item["id"]
            for items in res["revision_plan"]["schedule"].values()
            for item in items
        }
        self.assertEqual(scheduled_ids, {"R3.1", "R3.2", "R3.3", "R4.1"})
        self.assertIsNone(FABRICATED_ODDS_RE.search(json.dumps(res)))

        # Context caveat tests: H3 with citation is NOT filtered; H5 with author_claimed_sota IS substantive;
        # H12 >=3 months before Venue B deadline IS promoted to G3; H14 targeting proprietary API IS substantive
        caveat_comments = [
            {"id": "C1", "text": "The results are not novel.", "heuristic_tag": "H3"},
            {"id": "C2", "text": "The results are not novel given Smith et al. (2024).", "heuristic_tag": "H3", "cited_precedent": "Smith et al. 2024"},
            {"id": "C3", "text": "Does not beat SOTA.", "heuristic_tag": "H5", "author_claimed_sota": True},
            {"id": "C4", "text": "Missing reference published 4 months ago.", "heuristic_tag": "H12", "reference_published_at": "2026-06-01T00:00:00Z", "reference_is_preprint_only": False},
            {"id": "C5", "text": "Should compare to GPT-4 closed API.", "heuristic_tag": "H14", "claim_targets_proprietary_api": True},
        ]
        cav_res = triage_reviews.run_post_reject_triage(
            caveat_comments,
            venue_b_obj=m2_doc["venue_b"],
            as_of_str="2026-11-22T00:00:00Z",
            weeks=2,
        )
        self.assertEqual([h["id"] for h in cav_res["filtered_illegitimate_heuristics"]], ["C1"])
        self.assertEqual({d["id"] for d in cav_res["substantive_defects"]}, {"C2", "C3", "C4", "C5"})

        # Venue B deadline passed -> resubmission_blocked
        past_vb = dict(m2_doc["venue_b"], submission_deadline_utc="2026-10-01T00:00:00Z")
        blocked_res = triage_reviews.run_post_reject_triage(
            m2_doc["comments"],
            venue_b_obj=past_vb,
            as_of_str="2026-11-22T00:00:00Z",
            weeks=2,
        )
        self.assertEqual(blocked_res["venue_b_checks"]["status"], "resubmission_blocked")

    def test_invalid_inputs_exit_2_and_compact_under_4096_bytes(self) -> None:
        script = SCRIPTS_DIR / "triage_reviews.py"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            nan_file = tmp_dir / "nan.json"
            nan_file.write_text('{"scorecard": {"weights": {"importance": 15, "novelty": 20, "soundness": 20, "evidence": 20, "transparency": 15, "clarity": 10}, "ratings": {"importance": NaN, "novelty": 7, "soundness": 7, "evidence": 7, "transparency": 7, "clarity": 7}}}', encoding="utf-8")
            r_nan = subprocess.run([sys.executable, str(script), "mock-review", "--input", str(nan_file)], capture_output=True, text=True, check=False)
            self.assertEqual(r_nan.returncode, 2)
            self.assertIn("error", json.loads(r_nan.stderr))

            bool_file = tmp_dir / "bool.json"
            bool_file.write_text('{"scorecard": {"weights": {"importance": 15, "novelty": 20, "soundness": 20, "evidence": 20, "transparency": 15, "clarity": 10}, "ratings": {"importance": true, "novelty": 7, "soundness": 7, "evidence": 7, "transparency": 7, "clarity": 7}}}', encoding="utf-8")
            r_bool = subprocess.run([sys.executable, str(script), "mock-review", "--input", str(bool_file)], capture_output=True, text=True, check=False)
            self.assertEqual(r_bool.returncode, 2)

            m2_file = BENCHMARK_DIR / "triage" / "mode2_post_reject_h1_h17_triage.json"
            r_weeks = subprocess.run([sys.executable, str(script), "post-reject", "--reviews", str(m2_file), "--weeks", "5"], capture_output=True, text=True, check=False)
            self.assertEqual(r_weeks.returncode, 2)

            r_empty = subprocess.run([sys.executable, str(script), "mock-review", "--input", ""], capture_output=True, text=True, check=False)
            self.assertEqual(r_empty.returncode, 2)

            out_json = tmp_dir / "compact_out.json"
            m1_file = BENCHMARK_DIR / "triage" / "mode1_pre_submission_nlp_llm.json"
            r_compact = subprocess.run(
                [sys.executable, str(script), "mock-review", "--input", str(m1_file), "--subfield-preset", "nlp_llm", "--out", str(out_json), "--compact"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(r_compact.returncode, 0, r_compact.stderr)
            self.assertLess(len(r_compact.stdout.strip().encode("utf-8")), 4096)
            self.assertTrue(json.loads(r_compact.stdout)["compact"])
            self.assertTrue(out_json.is_file())

    def test_standalone_compare_scorecards_and_portfolio_novelty_gating(self) -> None:
        t5b = json.loads((BENCHMARK_DIR / "tiers" / "tier5_fatal_gate_cv_multimodal.json").read_text(encoding="utf-8"))
        t4 = json.loads((BENCHMARK_DIR / "tiers" / "tier4_workshop_ml_theory.json").read_text(encoding="utf-8"))

        csc_t5b_full = compare_scorecards.compare(
            t5b["scorecards_bundle"], sources_dir=SOURCES_DIR, target_id=t5b["target_id"], strict_related_panel=True, min_related=3
        )
        csc_t5b_compact = compare_scorecards._compact_output(csc_t5b_full)
        csc_t4_full = compare_scorecards.compare(
            t4["scorecards_bundle"], sources_dir=SOURCES_DIR, target_id=t4["target_id"], strict_related_panel=True, min_related=3
        )
        csc_t4_compact = compare_scorecards._compact_output(csc_t4_full)

        # Standalone compare_scorecards (full & compact) enforces fatal gate and tier floors
        for csc_obj, is_full in ((csc_t5b_full, True), (csc_t5b_compact, False)):
            res = triage_reviews.run_mock_review({}, scorecard_obj=csc_obj, venue_tier="top_tier_flagship")
            self.assertEqual(res["overall_verdict"], "fatal_gate_triggered")
            self.assertTrue(res["submission_readiness"]["fatal_gate_triggered"])
            self.assertTrue(triage_reviews._should_strict_fail(res))
            if is_full:
                self.assertEqual(res["merit_vs_publishability"]["scientific_merit_score"], 6.93)

            # Preserves bundle["scorecard"] ratings/weights when paired with --input
            paired = triage_reviews.run_mock_review(
                {"target_id": t5b["target_id"], "scorecard": t5b["scorecard"]},
                scorecard_obj=csc_obj,
                venue_tier="top_tier_flagship",
            )
            self.assertEqual(paired["overall_verdict"], "fatal_gate_triggered")
            self.assertEqual(paired["merit_vs_publishability"]["scientific_merit_score"], 6.93)
            self.assertEqual(paired["worst_case_sensitivity"]["worst_case_reviewer_floor"], 6.05)

        for csc_obj in (csc_t4_full, csc_t4_compact):
            res_t4 = triage_reviews.run_mock_review({}, scorecard_obj=csc_obj, venue_tier="top_tier_flagship")
            self.assertEqual(res_t4["overall_verdict"], "rejected_below_venue_tier")
            self.assertTrue(res_t4["venue_tier_fit"]["rejected_below_venue_tier"])
            self.assertTrue(triage_reviews._should_strict_fail(res_t4))

        # Standalone score_math output propagates merit_vs_packaging & deal_breaker_sensitivity
        sm_t5b = score_math.score(t5b["scorecard"])
        res_sm = triage_reviews.run_mock_review({}, scorecard_obj=sm_t5b, venue_tier="top_tier_flagship")
        self.assertEqual(res_sm["overall_verdict"], "fatal_gate_triggered")
        self.assertEqual(res_sm["merit_vs_publishability"]["scientific_merit_score"], 6.93)
        self.assertEqual(res_sm["worst_case_sensitivity"]["worst_case_reviewer_floor"], 7.0)

        # Standalone compare_venue_novelty --portfolio (full & compact)
        vn_t4_full = compare_venue_novelty.check(
            t4["venue_portfolio"], as_of=AS_OF, sources_dir=SOURCES_DIR, portfolio=True, require_panels=True
        )
        vn_t4_compact = compare_venue_novelty._compact_output(vn_t4_full)
        for vn_obj in (vn_t4_full, vn_t4_compact):
            res_vn = triage_reviews.run_mock_review({}, venue_novelty_obj=vn_obj, venue_tier="top_tier_flagship")
            self.assertEqual(res_vn["overall_verdict"], "rejected_below_venue_tier")
            self.assertTrue(res_vn["venue_tier_fit"]["rejected_below_venue_tier"])
            self.assertTrue(triage_reviews._should_strict_fail(res_vn))

        # Mode 2 with standalone compare_scorecards (Tier 5b fatal gate & Tier 4 below Venue B tier)
        m2_doc = json.loads((BENCHMARK_DIR / "triage" / "mode2_post_reject_h1_h17_triage.json").read_text(encoding="utf-8"))
        for csc_obj in (csc_t5b_full, csc_t5b_compact, csc_t4_full, csc_t4_compact):
            m2_res = triage_reviews.run_post_reject_triage(
                m2_doc["comments"],
                venue_b_obj=m2_doc["venue_b"],
                scorecard_obj=csc_obj,
                as_of_str="2026-11-22T00:00:00Z",
            )
            self.assertEqual(m2_res["venue_b_checks"]["status"], "resubmission_blocked")
            self.assertTrue(triage_reviews._should_strict_fail(m2_res))

    def test_venue_plan_schema_missing_dim_and_ledger_cap0_truncation(self) -> None:
        # 1. check_venue_plan schema: milestones_user_timezone, within_budget=False, cfp_verified=False, source_issues
        vp_flags = {
            "venue": "ICLR",
            "edition": "2027",
            "track": "Main Track",
            "within_budget": False,
            "cfp_verified": False,
            "source_issues": [{"scope": "official_cfp", "issue": "redirect_year_mismatch"}],
            "warnings": [],
            "milestones_user_timezone": {"full_paper": "2026-12-20T23:59:00Z"},
        }
        mr_vp = triage_reviews.run_mock_review({}, venue_plan_obj=vp_flags)
        self.assertEqual(mr_vp["overall_verdict"], "fatal_gate_triggered")
        self.assertTrue(triage_reviews._should_strict_fail(mr_vp))

        m2_doc = json.loads((BENCHMARK_DIR / "triage" / "mode2_post_reject_h1_h17_triage.json").read_text(encoding="utf-8"))
        m2_vp = triage_reviews.run_post_reject_triage(
            m2_doc["comments"],
            venue_b_obj="ICLR",
            venue_plan_obj=vp_flags,
            as_of_str="2026-11-22T00:00:00Z",
        )
        self.assertEqual(m2_vp["venue_b_checks"]["status"], "resubmission_blocked")
        self.assertEqual(m2_vp["venue_b_checks"]["submission_deadline_utc"], "2026-12-20T23:59:00+00:00")
        self.assertIsNotNone(m2_vp["venue_b_checks"]["h12_three_month_cutoff_utc"])
        self.assertIn("venue_plan:within_budget_false", m2_vp["venue_b_checks"]["blocking_reasons"])
        self.assertIn("venue_plan:cfp_not_verified", m2_vp["venue_b_checks"]["blocking_reasons"])
        self.assertIn("venue_plan:source_issues_detected", m2_vp["venue_b_checks"]["blocking_reasons"])

        vp_close = {
            "venue": "ICLR",
            "edition": "2027",
            "track": "Main Track",
            "within_budget": True,
            "cfp_verified": True,
            "source_issues": [],
            "warnings": [],
            "milestones_user_timezone": {"full_paper": "2026-11-25T23:59:00Z"},
        }
        m2_close = triage_reviews.run_post_reject_triage(
            m2_doc["comments"],
            venue_b_obj="ICLR",
            venue_plan_obj=vp_close,
            as_of_str="2026-11-22T00:00:00Z",
        )
        self.assertEqual(m2_close["venue_b_checks"]["days_remaining"], 3)
        self.assertEqual(m2_close["venue_b_checks"]["venue_b_tier"], "top_tier_flagship")
        self.assertEqual(m2_close["venue_b_checks"]["status"], "resubmission_blocked")

        # 2. Incomplete scorecard with null dimension -> never ready_for_submission_check
        null_bundle = {
            "scorecard": {
                "weights": {"importance": 15, "novelty": 20, "soundness": 20, "evidence": 20, "transparency": 15, "clarity": 10},
                "ratings": {"importance": 8, "novelty": 8, "soundness": 8, "evidence": None, "transparency": 8, "clarity": 8},
            }
        }
        null_res = triage_reviews.run_mock_review(null_bundle, venue_tier="top_tier_flagship")
        self.assertEqual(null_res["submission_readiness"]["band"], "not_comparable_missing_dimension")
        self.assertEqual(null_res["overall_verdict"], "major_revisions_required")
        self.assertNotEqual(null_res["overall_verdict"], "ready_for_submission_check")

        # 3. check_manuscript_ledger --compact cap=0 truncation still emits defect when prior defects exist
        led_cap0 = {"compact": True, "status": "structural_issues", "total_issues": 2, "issues": []}
        rig_fail = {"schema": "experiment_rigor_repro_v1", "verdict": "FAIL", "missing": ["seeds"]}
        led_res = triage_reviews.run_mock_review({"target_id": "x"}, ledger_obj=led_cap0, rigor_objs=[rig_fail])
        tools = {d["source_tool"] for d in led_res["defect_ledger"]}
        self.assertIn("check_experiment_rigor", tools)
        self.assertIn("check_manuscript_ledger", tools)

    def test_strict_validation_rejects_bad_types_and_non_dict_roots(self) -> None:
        script = SCRIPTS_DIR / "triage_reviews.py"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            base_p = tmp_dir / "base.json"
            base_p.write_text('{"target_id": "x"}', encoding="utf-8")

            for bad_effort in (True, False, "NaN", "Infinity", -5, 0, 15, 2.5):
                rev_p = tmp_dir / "bad_rev.json"
                rev_p.write_text(json.dumps([{"id": "C1", "text": "Untuned baseline comparison.", "effort_days": bad_effort}]), encoding="utf-8")
                r = subprocess.run([sys.executable, str(script), "post-reject", "--reviews", str(rev_p)], capture_output=True, text=True, check=False)
                self.assertEqual(r.returncode, 2, (bad_effort, r.stderr))

            for bad_sec in (True, False, "NaN", "Infinity", -1, 11):
                sec_p = tmp_dir / "bad_sec.json"
                sec_p.write_text(json.dumps({"target_id": "x", "sections": {"abstract": bad_sec}}), encoding="utf-8")
                r = subprocess.run([sys.executable, str(script), "mock-review", "--input", str(sec_p)], capture_output=True, text=True, check=False)
                self.assertEqual(r.returncode, 2, (bad_sec, r.stderr))

            for bad_anc in (True, False, "NaN", "Infinity"):
                anc_p = tmp_dir / "bad_anc.json"
                anc_p.write_text(json.dumps({"target_id": "x", "anchors": [{"anchor_id": "a1", "overall_score": bad_anc}]}), encoding="utf-8")
                r = subprocess.run([sys.executable, str(script), "mock-review", "--input", str(anc_p)], capture_output=True, text=True, check=False)
                self.assertEqual(r.returncode, 2, (bad_anc, r.stderr))

            rr_p = tmp_dir / "bad_rr.json"
            rr_p.write_text(json.dumps({"target_id": "x", "reviewer_ratings": [True, 123]}), encoding="utf-8")
            self.assertEqual(
                subprocess.run([sys.executable, str(script), "mock-review", "--input", str(rr_p)], capture_output=True, text=True, check=False).returncode,
                2,
            )

            for idx, bad_root in enumerate(([], [1], "hello", 123, True, None)):
                rp = tmp_dir / f"root_{idx}.json"
                rp.write_text(json.dumps(bad_root), encoding="utf-8")
                for flag in (
                    "--scorecard", "--venue-novelty", "--rigor", "--ledger", "--preflight",
                    "--artifact-readiness", "--venue-sources", "--venue-plan", "--engineering-diagnostics", "--sections",
                ):
                    r = subprocess.run(
                        [sys.executable, str(script), "mock-review", "--input", str(base_p), flag, str(rp)],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(r.returncode, 2, (flag, bad_root, r.stderr))
                if not isinstance(bad_root, list):
                    ra = subprocess.run(
                        [sys.executable, str(script), "mock-review", "--input", str(base_p), "--anchors", str(rp)],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(ra.returncode, 2, ("--anchors", bad_root, ra.stderr))

            # Valid JSON list --reviews succeeds while scalar JSON root fails exit 2
            list_rev_p = tmp_dir / "list_rev.json"
            list_rev_p.write_text(json.dumps([{"id": "C1", "text": "Untuned baseline comparison.", "effort_days": 3}]), encoding="utf-8")
            r_ok = subprocess.run([sys.executable, str(script), "post-reject", "--reviews", str(list_rev_p)], capture_output=True, text=True, check=False)
            self.assertEqual(r_ok.returncode, 0, r_ok.stderr)
            scalar_rev_p = tmp_dir / "scalar_rev.json"
            scalar_rev_p.write_text(json.dumps(True), encoding="utf-8")
            r_bad_rev = subprocess.run([sys.executable, str(script), "post-reject", "--reviews", str(scalar_rev_p)], capture_output=True, text=True, check=False)
            self.assertEqual(r_bad_rev.returncode, 2)

    def test_round2_remediations_tier_reconciliation_precedence_and_validation(self) -> None:
        script = SCRIPTS_DIR / "triage_reviews.py"
        w = {"importance": 15, "novelty": 20, "soundness": 20, "evidence": 20, "transparency": 15, "clarity": 10}
        t3 = json.loads((BENCHMARK_DIR / "tiers" / "tier3_borderline_ai_systems.json").read_text(encoding="utf-8"))
        t4 = json.loads((BENCHMARK_DIR / "tiers" / "tier4_workshop_ml_theory.json").read_text(encoding="utf-8"))
        t5b = json.loads((BENCHMARK_DIR / "tiers" / "tier5_fatal_gate_cv_multimodal.json").read_text(encoding="utf-8"))

        # 1. Reconcile tier_fit / venue_b_tier_fit when ratings is None (6.85 soundness=5, 6.05 evidence=5, tier5b fatal, Tier 3 safe)
        sm_s5 = score_math.score({"weights": w, "ratings": {"importance": 8, "novelty": 7, "soundness": 5, "evidence": 8, "transparency": 7, "clarity": 6}})
        mr_s5 = triage_reviews.run_mock_review({}, scorecard_obj=sm_s5, venue_tier="top_tier_flagship")
        self.assertEqual(mr_s5["overall_verdict"], "rejected_below_venue_tier")
        self.assertTrue(mr_s5["venue_tier_fit"]["rejected_below_venue_tier"])
        self.assertEqual(mr_s5["venue_tier_fit"]["recommended_matched_tier"], "q2_q3_or_tier_b")
        self.assertTrue(triage_reviews._should_strict_fail(mr_s5))

        m2_doc = json.loads((BENCHMARK_DIR / "triage" / "mode2_post_reject_h1_h17_triage.json").read_text(encoding="utf-8"))
        m2_s5 = triage_reviews.run_post_reject_triage(m2_doc["comments"], venue_b_obj="ICLR", scorecard_obj=sm_s5, as_of_str="2026-11-22T00:00:00Z")
        self.assertEqual(m2_s5["venue_b_checks"]["status"], "resubmission_blocked")
        self.assertTrue(m2_s5["venue_b_checks"]["venue_b_tier_fit"]["rejected_below_venue_tier"])
        self.assertEqual(m2_s5["venue_b_checks"]["venue_b_tier_fit"]["recommended_matched_tier"], "q2_q3_or_tier_b")

        p2 = {"id": "p2", "reading_basis": "full_text", "closest_work": ["p1"], "evidence_locators": {"soundness": ["x"]}, "ratings": {"importance": 7, "novelty": 7, "soundness": 7, "evidence": 7, "transparency": 7, "clarity": 7}}
        e5_bundle = {"weight_scenarios": [w], "profiles": [{"id": "p1", "reading_basis": "full_text", "ratings": {"importance": 7, "novelty": 6, "soundness": 6, "evidence": 5, "transparency": 6, "clarity": 7}}, p2]}
        csc_e5_full = compare_scorecards.compare(e5_bundle, target_id="p1")
        csc_e5_compact = compare_scorecards._compact_output(csc_e5_full)
        for csc_obj in (csc_e5_full, csc_e5_compact):
            mr_e5 = triage_reviews.run_mock_review({}, scorecard_obj=csc_obj, venue_tier="top_tier_flagship")
            self.assertEqual(mr_e5["overall_verdict"], "rejected_below_venue_tier")
            self.assertTrue(mr_e5["venue_tier_fit"]["rejected_below_venue_tier"])
            self.assertEqual(mr_e5["venue_tier_fit"]["recommended_matched_tier"], "q2_q3_or_tier_b")

        # Tier 3 (6.35, all >= 6) must NOT be rejected below top_tier_flagship
        t3_csc_full = compare_scorecards.compare(t3["scorecards_bundle"], sources_dir=SOURCES_DIR, target_id=t3["target_id"], strict_related_panel=True, min_related=3)
        t3_csc_compact = compare_scorecards._compact_output(t3_csc_full)
        for sc_obj in (score_math.score(t3["scorecard"]), t3_csc_full, t3_csc_compact):
            mr_t3 = triage_reviews.run_mock_review({}, scorecard_obj=sc_obj, venue_tier="top_tier_flagship")
            self.assertFalse(mr_t3["venue_tier_fit"]["rejected_below_venue_tier"])
            self.assertEqual(mr_t3["venue_tier_fit"]["recommended_matched_tier"], "q1_or_tier_a")

        # Tier 5b fatal gate via compare_scorecards must set tier_fit rejected & none_hold_for_rework
        t5b_csc_full = compare_scorecards.compare(t5b["scorecards_bundle"], sources_dir=SOURCES_DIR, target_id=t5b["target_id"], strict_related_panel=True, min_related=3)
        for sc_obj in (t5b_csc_full, compare_scorecards._compact_output(t5b_csc_full)):
            mr_t5b = triage_reviews.run_mock_review({}, scorecard_obj=sc_obj, venue_tier="top_tier_flagship")
            self.assertEqual(mr_t5b["overall_verdict"], "fatal_gate_triggered")
            self.assertTrue(mr_t5b["venue_tier_fit"]["rejected_below_venue_tier"])
            self.assertEqual(mr_t5b["venue_tier_fit"]["recommended_matched_tier"], "none_hold_for_rework")

        # 2. Explicit --scorecard takes precedence over stale --input embedded scorecard
        stale_bundle = {"target_id": t5b["target_id"], "scorecard": {"weights": w, "ratings": {"importance": 8, "novelty": 8, "soundness": 7, "evidence": 8, "transparency": 8, "clarity": 8}}}
        mr_prec = triage_reviews.run_mock_review(stale_bundle, scorecard_obj=t5b_csc_full, venue_tier="top_tier_flagship")
        self.assertEqual(mr_prec["overall_verdict"], "fatal_gate_triggered")
        self.assertTrue(mr_prec["submission_readiness"]["fatal_gate_triggered"])

        # 3. Mode 2 --venue-plan fallback for venue_b_name / track when --venue-b omitted
        m2_vp_fb = triage_reviews.run_post_reject_triage(
            m2_doc["comments"],
            venue_b_obj=None,
            venue_plan_obj={"venue": "ICLR", "track": "Main Track", "within_budget": True, "cfp_verified": True, "milestones_user_timezone": {"full_paper": "2026-12-20T23:59:00+00:00"}},
            scorecard_obj=t4["scorecard"],
            as_of_str="2026-11-22T00:00:00Z",
        )
        self.assertEqual(m2_vp_fb["venue_b_checks"]["venue_b_name"], "ICLR")
        self.assertEqual(m2_vp_fb["venue_b_checks"]["venue_b_tier"], "top_tier_flagship")
        self.assertEqual(m2_vp_fb["venue_b_checks"]["status"], "resubmission_blocked")

        # 4-8. Precomputed Decimal validation, nested dict validation, anchor ratings/novelty validation, effort_days on H1, contamination pass/fail, and --compact long/Unicode --out
        with self.assertRaises(ValueError):
            triage_reviews.run_mock_review({}, scorecard_obj={"submission_readiness": {"band": "clear_accept_main_track"}, "weighted_unrounded": "NaN"})
        with self.assertRaises(ValueError):
            triage_reviews.run_mock_review({}, scorecard_obj={"submission_readiness": {"band": "clear_accept_main_track"}, "weighted_unrounded": "7.50", "merit_vs_packaging": {"scientific_merit_score": True, "publishability_packaging_score": 7.0}})
        with self.assertRaises(ValueError):
            triage_reviews.run_mock_review({}, scorecard_obj={"submission_readiness": {"band": "clear_accept_main_track"}, "weighted_unrounded": "7.50", "deal_breaker_sensitivity": {"worst_case_reviewer_floor": {"worst_case_score": "NaN"}}})
        with self.assertRaises(ValueError):
            triage_reviews.run_mock_review({"venue_novelty": {"venue": {"name": "ICLR"}, "venue_quality_context": [1, 2]}})
        with self.assertRaises(ValueError):
            triage_reviews.run_mock_review({"ledger": {"argument_audit": {"claim_scope_alignment": [1, 2]}}})
        with self.assertRaises(ValueError):
            triage_reviews.run_mock_review({"target_id": "x"}, anchors_obj=[{"anchor_id": "a1", "overall_score": 7.5, "ratings": {"novelty": True}}])
        with self.assertRaises(ValueError):
            triage_reviews.run_mock_review({"target_id": "x"}, anchors_obj=[{"anchor_id": "a1", "overall_score": 7.5, "novelty_score": True}])
        with self.assertRaises(ValueError):
            triage_reviews.run_post_reject_triage([{"id": "C1", "text": "This is not surprising.", "effort_days": True}])

        rig_res = triage_reviews.run_mock_review(
            {"target_id": "x"},
            rigor_objs=[
                {"schema": "experiment_rigor_contamination_v1", "verdict": "CONTAMINATION_DETECTED"},
                {"schema": "experiment_rigor_contamination_v1", "verdict": "CLEAN"},
            ],
            subfield_preset="nlp_llm",
        )
        self.assertIn("contamination_check", rig_res["subfield_preset_audit"]["failed_checks"])

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            base_p = tmp_dir / "base.json"
            base_p.write_text('{"target_id": "x"}', encoding="utf-8")
            long_uni = tmp_dir.joinpath(*(["á" * 100] * 8), "r.json")
            r_u = subprocess.run([sys.executable, str(script), "mock-review", "--input", str(base_p), "--out", str(long_uni), "--compact"], capture_output=True, text=True, check=False)
            self.assertEqual(r_u.returncode, 0, r_u.stderr)
            self.assertLess(len(r_u.stdout.strip().encode("utf-8")), 4096)
            self.assertTrue(long_uni.is_file())

    def test_round3_remediations_compact_boundary_thresholds_and_input_consistency(self) -> None:
        script = SCRIPTS_DIR / "triage_reviews.py"
        csc_script = SCRIPTS_DIR / "compare_scorecards.py"
        w = {"importance": 15, "novelty": 20, "soundness": 20, "evidence": 20, "transparency": 15, "clarity": 10}
        m2_file = BENCHMARK_DIR / "triage" / "mode2_post_reject_h1_h17_triage.json"
        locs = {dim: [f"paper.txt#L1 \"evidence for {dim}\""] for dim in score_math.DIMENSIONS}

        def _make_bundle(p1_ratings: dict[str, int]) -> dict:
            other_ids = ["p2", "p3", "p4"]
            profiles = [
                {
                    "id": "p1",
                    "reading_basis": "full_text",
                    "closest_work": other_ids,
                    "evidence_locators": locs,
                    "ratings": p1_ratings,
                }
            ]
            for oid in other_ids:
                profiles.append({
                    "id": oid,
                    "reading_basis": "full_text",
                    "closest_work": ["p1"],
                    "evidence_locators": locs,
                    "ratings": {"importance": 7, "novelty": 7, "soundness": 7, "evidence": 7, "transparency": 7, "clarity": 7},
                })
            return {"weight_scenarios": [w], "profiles": profiles}

        # 1. A_675_ev5 (6.75, evidence=5) on compare_scorecards --compact without --target-id
        a675_bun = _make_bundle({"importance": 8, "novelty": 7, "soundness": 7, "evidence": 5, "transparency": 7, "clarity": 7})
        a675_comp = compare_scorecards._compact_output(compare_scorecards.compare(a675_bun))
        self.assertIsNone(a675_comp["related_work_comparison"])
        self.assertNotIn("recommended_matched_tier", a675_comp["submission_readiness"]["p1"])

        mr_a675 = triage_reviews.run_mock_review({}, scorecard_obj=a675_comp, venue_tier="top_tier_flagship")
        self.assertEqual(mr_a675["overall_verdict"], "rejected_below_venue_tier")
        self.assertTrue(mr_a675["venue_tier_fit"]["rejected_below_venue_tier"])
        self.assertEqual(mr_a675["venue_tier_fit"]["recommended_matched_tier"], "q2_q3_or_tier_b")
        self.assertTrue(triage_reviews._should_strict_fail(mr_a675))

        m2_doc = json.loads(m2_file.read_text(encoding="utf-8"))
        m2_a675 = triage_reviews.run_post_reject_triage(
            m2_doc["comments"], venue_b_obj="ICLR", scorecard_obj=a675_comp, as_of_str="2026-11-22T00:00:00Z"
        )
        self.assertEqual(m2_a675["venue_b_checks"]["status"], "resubmission_blocked")
        self.assertTrue(m2_a675["venue_b_checks"]["venue_b_tier_fit"]["rejected_below_venue_tier"])
        self.assertEqual(m2_a675["venue_b_checks"]["venue_b_tier_fit"]["recommended_matched_tier"], "q2_q3_or_tier_b")

        # Also verify soundness=5 at 6.75 via compare_scorecards --compact
        s675_bun = _make_bundle({"importance": 8, "novelty": 7, "soundness": 5, "evidence": 7, "transparency": 7, "clarity": 7})
        s675_comp = compare_scorecards._compact_output(compare_scorecards.compare(s675_bun))
        mr_s675 = triage_reviews.run_mock_review({}, scorecard_obj=s675_comp, venue_tier="top_tier_flagship")
        self.assertTrue(mr_s675["venue_tier_fit"]["rejected_below_venue_tier"])
        self.assertEqual(mr_s675["venue_tier_fit"]["recommended_matched_tier"], "q2_q3_or_tier_b")

        # 2. nov5_660 (6.60, novelty=5, soundness>=6, evidence>=6) must NOT be falsely rejected
        nov5_bun = _make_bundle({"importance": 7, "novelty": 5, "soundness": 7, "evidence": 7, "transparency": 7, "clarity": 7})
        nov5_comp = compare_scorecards._compact_output(compare_scorecards.compare(nov5_bun))
        mr_nov5 = triage_reviews.run_mock_review({}, scorecard_obj=nov5_comp, venue_tier="top_tier_flagship")
        self.assertEqual(mr_nov5["overall_verdict"], "ready_for_submission_check")
        self.assertFalse(mr_nov5["venue_tier_fit"]["rejected_below_venue_tier"])
        self.assertEqual(mr_nov5["venue_tier_fit"]["recommended_matched_tier"], "q1_or_tier_a")
        self.assertFalse(triage_reviews._should_strict_fail(mr_nov5))

        m2_nov5 = triage_reviews.run_post_reject_triage(
            m2_doc["comments"], venue_b_obj="ICLR", scorecard_obj=nov5_comp, as_of_str="2026-11-22T00:00:00Z"
        )
        self.assertEqual(m2_nov5["venue_b_checks"]["status"], "ready_for_resubmission")
        self.assertFalse(m2_nov5["venue_b_checks"]["venue_b_tier_fit"]["rejected_below_venue_tier"])
        self.assertEqual(m2_nov5["venue_b_checks"]["venue_b_tier_fit"]["recommended_matched_tier"], "q1_or_tier_a")

        # 3. Same weighted_unrounded (6.85) in --input (all dims>=6) must NOT override --scorecard (soundness=5)
        s5_685_bun = _make_bundle({"importance": 8, "novelty": 7, "soundness": 5, "evidence": 8, "transparency": 7, "clarity": 6})
        s5_685_comp = compare_scorecards._compact_output(compare_scorecards.compare(s5_685_bun))
        stale_same_w = {
            "target_id": "p1",
            "scorecard": {"weights": w, "ratings": {"importance": 7, "novelty": 7, "soundness": 7, "evidence": 7, "transparency": 6, "clarity": 7}},
        }
        mr_same_w = triage_reviews.run_mock_review(stale_same_w, scorecard_obj=s5_685_comp, venue_tier="top_tier_flagship")
        self.assertEqual(mr_same_w["overall_verdict"], "rejected_below_venue_tier")
        self.assertTrue(mr_same_w["venue_tier_fit"]["rejected_below_venue_tier"])
        self.assertEqual(mr_same_w["venue_tier_fit"]["recommended_matched_tier"], "q2_q3_or_tier_b")
        self.assertTrue(triage_reviews._should_strict_fail(mr_same_w))

        # CLI subprocess checks for all three cases
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            for name, bun, expected_rc in (("a675", a675_bun, 1), ("nov5", nov5_bun, 0)):
                bp = tmp_dir / f"{name}_bun.json"
                bp.write_text(json.dumps(bun), encoding="utf-8")
                rc_csc = subprocess.run([sys.executable, str(csc_script), str(bp), "--compact"], capture_output=True, text=True, check=False)
                self.assertEqual(rc_csc.returncode, 0, rc_csc.stderr)
                cp = tmp_dir / f"{name}_comp.json"
                cp.write_text(rc_csc.stdout, encoding="utf-8")
                r_m1 = subprocess.run([sys.executable, str(script), "mock-review", "--scorecard", str(cp), "--venue-tier", "top_tier_flagship", "--strict"], capture_output=True, text=True, check=False)
                self.assertEqual(r_m1.returncode, expected_rc, r_m1.stdout)
                r_m2 = subprocess.run([sys.executable, str(script), "post-reject", "--reviews", str(m2_file), "--venue-b", "ICLR", "--scorecard", str(cp), "--as-of", "2026-11-22T00:00:00Z", "--strict"], capture_output=True, text=True, check=False)
                self.assertEqual(r_m2.returncode, expected_rc, r_m2.stdout)

            s5_bp = tmp_dir / "s5_bun.json"
            s5_bp.write_text(json.dumps(s5_685_bun), encoding="utf-8")
            rc_s5_csc = subprocess.run([sys.executable, str(csc_script), str(s5_bp), "--compact"], capture_output=True, text=True, check=False)
            self.assertEqual(rc_s5_csc.returncode, 0, rc_s5_csc.stderr)
            s5_cp = tmp_dir / "s5_comp.json"
            s5_cp.write_text(rc_s5_csc.stdout, encoding="utf-8")
            same_w_p = tmp_dir / "same_w.json"
            same_w_p.write_text(json.dumps(stale_same_w), encoding="utf-8")
            r_sw = subprocess.run([sys.executable, str(script), "mock-review", "--input", str(same_w_p), "--scorecard", str(s5_cp), "--venue-tier", "top_tier_flagship", "--strict"], capture_output=True, text=True, check=False)
            self.assertEqual(r_sw.returncode, 1, r_sw.stdout)

    def test_round4_submission_readiness_type_validation_and_reproducers(self) -> None:
        script = SCRIPTS_DIR / "triage_reviews.py"
        m2_file = BENCHMARK_DIR / "triage" / "mode2_post_reject_h1_h17_triage.json"

        exact_reproducer = {
            "weighted_unrounded": "6.75",
            "overall": 7,
            "submission_readiness": {
                "band": 123,
                "recommended_matched_tier": {"bad": 1},
                "bottleneck_dimensions": ["evidence"],
                "fatal_gate_triggered": False,
            },
        }
        bad_scorecards = [
            ("exact_repro", exact_reproducer),
            ("band_int", {"weighted_unrounded": "6.75", "overall": 7, "submission_readiness": {"band": 123}}),
            ("band_bool", {"weighted_unrounded": "6.75", "overall": 7, "submission_readiness": {"band": True}}),
            ("band_list", {"weighted_unrounded": "6.75", "overall": 7, "submission_readiness": {"band": ["x"]}}),
            ("rec_tier_dict", {"weighted_unrounded": "6.75", "overall": 7, "submission_readiness": {"band": "borderline_top_tier_competitive_findings_tier_a", "recommended_matched_tier": {"bad": 1}}}),
            ("rec_tier_int", {"weighted_unrounded": "6.75", "overall": 7, "submission_readiness": {"band": "borderline_top_tier_competitive_findings_tier_a", "recommended_matched_tier": 123}}),
            ("rec_tier_bool", {"weighted_unrounded": "6.75", "overall": 7, "submission_readiness": {"band": "borderline_top_tier_competitive_findings_tier_a", "recommended_matched_tier": True}}),
            ("rec_tier_list", {"weighted_unrounded": "6.75", "overall": 7, "submission_readiness": {"band": "borderline_top_tier_competitive_findings_tier_a", "recommended_matched_tier": ["q1_or_tier_a"]}}),
            ("rec_tier_dict_no_band", {"weighted_unrounded": "6.75", "overall": 7, "submission_readiness": {"recommended_matched_tier": {"bad": 1}, "bottleneck_dimensions": ["evidence"], "fatal_gate_triggered": False}}),
            ("fatal_dims_str", {"weighted_unrounded": "6.75", "overall": 7, "submission_readiness": {"band": "not_ready_fatal_gate", "fatal_gate_triggered": True, "fatal_dimensions": "soundness"}}),
            ("fatal_dims_dict_elem", {"weighted_unrounded": "6.75", "overall": 7, "submission_readiness": {"band": "not_ready_fatal_gate", "fatal_gate_triggered": True, "fatal_dimensions": [{}]}}),
            ("bdims_dict_elem", {"weighted_unrounded": "6.75", "overall": 7, "submission_readiness": {"band": "borderline_top_tier_competitive_findings_tier_a", "bottleneck_dimensions": [{}]}}),
            ("csc_band_int", {"status": "structurally_comparable", "submission_readiness": {"p1": {"band": 123, "weighted_unrounded": "6.75", "recommended_matched_tier": {"bad": 1}}}}),
            ("csc_fatal_dims_str", {"status": "structurally_comparable", "submission_readiness": {"p1": {"band": "not_ready_fatal_gate", "fatal_gate_triggered": True, "fatal_dimensions": "soundness"}}}),
        ]

        # Direct Python API checks (ValueError, never TypeError or silent pass)
        for label, sc_obj in bad_scorecards:
            with self.assertRaises(ValueError, msg=label):
                triage_reviews.run_mock_review({}, scorecard_obj=sc_obj, venue_tier="top_tier_flagship")
            with self.assertRaises(ValueError, msg=label):
                triage_reviews.run_mock_review({"scorecard": sc_obj}, venue_tier="top_tier_flagship")
            with self.assertRaises(ValueError, msg=label):
                triage_reviews.run_post_reject_triage(
                    [{"id": "C1", "text": "Missing ablation."}],
                    venue_b_obj="ICLR",
                    scorecard_obj=sc_obj,
                    as_of_str="2026-11-22T00:00:00Z",
                )

        with self.assertRaises(ValueError):
            triage_reviews._reconcile_tier_fit_with_readiness(
                {"venue_tier": "top_tier_flagship", "rejected_below_venue_tier": False, "rejection_reasons": [], "recommended_matched_tier": None},
                {"band": 123, "recommended_matched_tier": {"bad": 1}},
                "top_tier_flagship",
            )
        with self.assertRaises(ValueError):
            triage_reviews.run_mock_review(
                {},
                venue_novelty_obj={"mode": "portfolio", "target_readiness": {"band": 123, "recommended_matched_tier": {"bad": 1}}},
                venue_tier="top_tier_flagship",
            )

        # CLI Mode 1 & Mode 2 checks -> exit 2 with clean JSON {"error": ...} and zero Traceback
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            for label, sc_obj in bad_scorecards:
                sp = tmp_dir / f"{label}.json"
                sp.write_text(json.dumps(sc_obj), encoding="utf-8")

                r_m1 = subprocess.run(
                    [sys.executable, str(script), "mock-review", "--scorecard", str(sp), "--venue-tier", "top_tier_flagship", "--strict"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(r_m1.returncode, 2, (label, r_m1.stdout, r_m1.stderr))
                self.assertNotIn("Traceback", r_m1.stderr, label)
                self.assertIn("error", json.loads(r_m1.stderr), label)

                r_m2 = subprocess.run(
                    [sys.executable, str(script), "post-reject", "--reviews", str(m2_file), "--venue-b", "ICLR", "--scorecard", str(sp), "--as-of", "2026-11-22T00:00:00Z", "--strict"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(r_m2.returncode, 2, (label, r_m2.stdout, r_m2.stderr))
                self.assertNotIn("Traceback", r_m2.stderr, label)
                self.assertIn("error", json.loads(r_m2.stderr), label)

    def test_claim_audit_suite_zero_findings(self) -> None:
        audit = claim_audit.audit_suite(ROOT, readme=ROOT / "README.md")
        self.assertEqual(audit["finding_count"], 0, audit.get("findings"))
        self.assertEqual(audit["status"], "passed")


if __name__ == "__main__":
    unittest.main()
