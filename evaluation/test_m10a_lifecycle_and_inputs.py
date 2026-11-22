import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "research-scientist" / "scripts"
FIXTURES_DIR = REPO_ROOT / "evaluation" / "e2e" / "fixtures"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import analyze_experiment_outcome
import build_research_inputs
import check_gap_record
import check_manuscript_ledger
import compare_scorecards
import gap_pipeline
import project_state
import score_math


def _valid_question_card(qid="RQ-1"):
    return {
        "id": qid,
        "question": "Does adaptive temperature scaling reduce OOD calibration error without hurting accuracy?",
        "question_type": "mechanistic",
        "target_scope": "Vision-language classifiers under domain shift",
        "unit_of_observation": "image-text pair",
        "unit_of_analysis": "dataset split",
        "construct_or_estimand": "Expected Calibration Error (ECE)",
        "measurement": "15-bin ECE and top-1 accuracy",
        "closest_work": "Static Temperature Scaling (Guo et al., 2017)",
        "prior_art_boundary": "Prior work uses a single scalar temperature fitted on ID validation.",
        "rival_explanation": "Gain comes only from post-hoc logit clipping rather than shift-aware scaling.",
        "expected_if_focal": "ECE improves on OOD domain shift while accuracy stays within 0.5%.",
        "expected_if_rival": "Constant logit clipping matches adaptive scaling on OOD shift.",
        "discriminating_test": "Compare adaptive scaling vs constant clipping on domain_shift and length slices.",
        "falsifying_result": "OOD ECE worsens relative to static baseline under matched tuning.",
        "indeterminate_result": "95% CI spans zero across seeds and slices.",
        "pilot": "2-day pilot on CIFAR-C corruption shift.",
        "engineering_diagnosis": "Verified identical backbone, preprocessing, and seed parity.",
        "prior_outcome_exposure": "none_uninspected",
    }


def _hex64(ch="a"):
    return ch * 64


class TestProjectState(unittest.TestCase):
    def test_full_lineage_chain_and_strict_audit(self):
        state = project_state.init_state(
            "proj-m10a",
            title="Adaptive OOD Calibration",
            subfield_preset="cv_multimodal",
            target_venue="NeurIPS 2027",
            author_profile={
                "strength_profile": "systems_engineering",
                "proprietary_assets": [],
                "gpu_budget_hours": 120.0,
                "timeline_weeks": 10,
            },
        )
        self.assertEqual(state["target_venue_tier"], "top_tier_flagship")

        # Register full_text digests
        res = project_state.ingest_artifact(
            state,
            "corpus_digests",
            {
                "digests": [
                    {
                        "source_id": "SRC-1",
                        "title": "On Calibration of Modern Neural Networks",
                        "access": "full_text",
                        "locator": "Section 3, p. 4",
                        "quote": "Temperature scaling uses a single scalar parameter on logits.",
                    },
                    {
                        "source_id": "SRC-2",
                        "title": "OOD Calibration Benchmark",
                        "access": "selected_full_text",
                        "locator": "Table 2, p. 6",
                        "digest": "Static temperature scaling degrades under covariate shift.",
                    },
                    {
                        "source_id": "SRC-3",
                        "title": "Shift-Aware Calibration",
                        "access": "full_text",
                        "locator": "Section 4.1, p. 5",
                        "quote": "Density-weighted calibration reduces shift error.",
                    },
                ]
            },
        )
        self.assertEqual(res["errors"], [])

        # Ingest F27/F32 idea_seed_bundle + trajectory_tree
        bundle = {
            "gap_id": "G1",
            "claim": "Static calibration fails under domain shift due to unmodeled feature density.",
            "support_source_ids": ["SRC-1", "SRC-2"],
            "closest_work_ids": ["SRC-1", "SRC-2", "SRC-3"],
            "prior_art_boundary": "Prior scalar scaling assumes ID/OOD logit calibration invariance.",
            "gap_tier_ceiling": "q1_top_tier_potential",
            "resource_feasibility": "feasible",
            "scoop_and_obsolescence_risk": "moderate",
            "root_cause_barrier": "measurement_gap",
            "why_now_enabler": "Open-weight vision-language feature embeddings enable fast density estimation.",
            "evaluation_validity_gap": {"is_eval_gap": False, "subtypes": []},
            "isomorphic_transfer_leads": [
                {"domain": "control_theory", "mechanism": "gain scheduling", "status": "lead"}
            ],
            "so_what_decision_impact": "decision_changing",
            "durability_12_24m": "durable_structural_limit",
            "trajectory_tree": [
                {
                    "generation": "Gen1",
                    "label": "Static temperature scaling",
                    "bottleneck": "Fails under covariate shift",
                    "tradeoff": "Simplicity vs OOD fragility",
                    "parent_generation": None,
                    "source_ids": ["SRC-1"],
                }
            ],
            "candidate_ideas": [
                {
                    "id": "IDEA-1",
                    "angle": "high_novelty_mechanism",
                    "contribution_type": "method",
                    "title": "Density-gated logit scaling",
                    "bottleneck_target": "Static scalar temperature ignores embedding density drop under OOD shift",
                    "why_sota_fails": "Single temperature parameter over-confidently amplifies OOD logits",
                    "proposed_mechanism": "Scale logits monotonically with normalized Mahalanobis feature density",
                    "components": ["density_gate"],
                    "simplest_alternative": "Single scalar temperature scaling fitted on validation logits",
                    "planned_contributions_count": 1,
                    "planned_datasets_count": 3,
                    "estimated_weeks": 6,
                    "required_gpu_hours": 40,
                    "required_strengths": ["systems_engineering"],
                }
            ],
        }
        b_res = project_state.ingest_artifact(state, "idea_seed_bundle", bundle)
        self.assertEqual(b_res["errors"], [])

        # Ingest Question Card
        qc = _valid_question_card("RQ-1")
        project_state.ingest_artifact(state, "question_card", qc, link_ids={"idea_id": "IDEA-1", "gap_id": "G1"})

        # Ingest Experiment Manifest
        manifest = {
            "question_id": "RQ-1",
            "protocol_version": "v1",
            "protocol_frozen_at_utc": "2026-11-20T00:00:00Z",
            "runs": [
                {
                    "run_id": "RUN-1",
                    "role": "candidate",
                    "protocol_version": "v1",
                    "code_commit": "abc1234",
                    "data_version": "v1",
                    "split_manifest_sha256": _hex64("1"),
                    "metric_id": "ece",
                    "metric_script_sha256": _hex64("2"),
                    "command": "python3 run.py",
                    "started_at_utc": "2026-11-21T00:00:00Z",
                    "ended_at_utc": "2026-11-21T01:00:00Z",
                    "exit_code": 0,
                    "result_artifact_sha256": _hex64("3"),
                    "result_value": 0.041,
                    "deviations": [],
                    "decision_timing": "prespecified",
                }
            ],
        }
        project_state.ingest_artifact(state, "experiment_manifest", manifest, link_ids={"rq_id": "RQ-1"})
        project_state.ingest_artifact(
            state,
            "experiment_outcome",
            {"status": "analyzed", "outcome_classification": "focal_supported"},
            link_ids={"rq_id": "RQ-1", "run_ids": ["RUN-1"]},
        )

        # Ingest Manuscript Ledger, Scorecard, Venue Verdict, Rebuttal
        project_state.ingest_artifact(
            state,
            "manuscript_ledger",
            {
                "passed": True,
                "sources": [{"id": "SRC-1", "type": "paper", "locator": "Section 3, p. 4", "verified": True}],
                "claims": [
                    {
                        "id": "C1",
                        "kind": "reported",
                        "material": True,
                        "rq_id": "RQ-1",
                        "target_ref": "Table 1",
                        "run_ids": ["RUN-1"],
                        "source_ids": ["SRC-1"],
                    }
                ],
            },
        )
        project_state.ingest_artifact(
            state,
            "scorecards",
            {
                "target_id": "target_paper",
                "status": "structurally_comparable",
                "profiles": [
                    {"id": "target_paper", "reading_basis": "full_text", "closest_work": ["SRC-1", "SRC-2", "SRC-3"]}
                ],
                "rankings": [{"ordered": [{"id": "target_paper", "weighted_unrounded": "7.10"}]}],
                "submission_readiness": {"target_paper": {"band": "competitive_top_tier_main_track", "fatal_gate_triggered": False}},
            },
            link_ids={"claim_id": "C1"},
        )
        project_state.ingest_artifact(
            state,
            "venue_novelty",
            {
                "venue": {"name": "NeurIPS 2027"},
                "submission_readiness": {
                    "venue_tier": "top_tier_flagship",
                    "verdict": "competitive_top_tier_main_track",
                    "ready_to_submit": True,
                    "recommended_matched_tier": "top_tier_flagship",
                },
            },
        )
        project_state.ingest_artifact(
            state,
            "rebuttal",
            {
                "points": [
                    {"point_id": "R1.1", "claim_ids": ["C1"], "run_ids": ["RUN-1"], "anchor": "Table 1, Section 4", "status": "addressed"}
                ]
            },
        )

        audit = project_state.audit_state(state, strict=True)
        self.assertEqual(audit["status"], "passed", msg=f"Unexpected audit errors: {audit['errors']}")
        self.assertEqual(audit["stage_summary"]["lineage_edges"], 7)

        adv = project_state.generate_next_step_prompt(state)
        self.assertEqual(adv["current_stage"], "ready_for_reporting")

    def test_provenance_blocks_silent_upgrade_and_downgrade(self):
        state = project_state.init_state("proj-prov")
        # 1. Valid full_text preserved over subsequent metadata_only downgrade
        project_state.register_corpus_digest(
            state,
            {
                "source_id": "P1",
                "access": "full_text",
                "locator": "Sec 2, p. 3",
                "quote": "Exact verified quote from paper P1.",
            },
        )
        _, warns = project_state.register_corpus_digest(
            state,
            {"source_id": "P1", "access": "metadata_only", "digest": "only title"},
        )
        self.assertEqual(state["corpus_digests"]["P1"]["access"], "full_text")
        self.assertTrue(any("provenance_downgrade_blocked" in w for w in warns))

        # 2. Silent full_text upgrade without locator/quote is blocked
        project_state.register_corpus_digest(
            state,
            {"source_id": "P2", "access": "abstract", "locator": "abstract", "digest": "Abstract snippet."},
        )
        _, up_warns = project_state.register_corpus_digest(
            state,
            {"source_id": "P2", "access": "full_text", "locator": "", "quote": ""},
        )
        self.assertTrue(any("silent_full_text_upgrade_blocked" in w for w in up_warns))
        self.assertEqual(state["corpus_digests"]["P2"]["access"], "abstract")
        strict_audit = project_state.audit_state(state, strict=True)
        self.assertEqual(strict_audit["status"], "issues_detected")

    def test_ideation_stitching_rejection_pivot_author_advantage_and_mpu(self):
        stitched = {
            "title": "HybridNet: Combine Transformer and GNN with plug-and-play fusion",
            "mechanism_decomposition": {
                "bottleneck_target": "TBD",
                "why_sota_fails": "none",
                "proposed_mechanism": "Combine module A + B",
                "components": ["Transformer", "GNN", "Adapter"],
                "simplest_alternative": "TBD",
            },
        }
        mech = project_state.assess_mechanism_decomposition(stitched)
        self.assertFalse(mech["passed"])
        self.assertTrue(mech["is_vague_stitching"])

        pivot = project_state.advise_contribution_pivot(
            {
                "contribution_type": "method",
                "lenses_f32": {"durability_12_24m": "high_scaling_erasure_risk", "evaluation_validity_gap": {"is_eval_gap": True}},
                "mechanism_decomposition": stitched["mechanism_decomposition"],
            },
            evidence_signals={"simplest_alternative_equal_or_better": True},
            author_profile={"strength_profile": "math_theory"},
        )
        self.assertTrue(pivot["pivot_needed"])
        self.assertIn(pivot["recommended_type"], ("benchmark_dataset", "diagnostic", "scaling_law", "theoretical_bound"))

        adv_bad = project_state.score_author_advantage(
            {"required_strengths": ["math_theory"], "required_gpu_hours": 500, "estimated_weeks": 12},
            {"strength_profile": "systems_engineering", "gpu_budget_hours": 64, "timeline_weeks": 6},
        )
        self.assertEqual(adv_bad["fit_classification"], "misaligned_or_infeasible")
        self.assertGreaterEqual(len(adv_bad["socratic_questions"]), 1)

        mpu_over = project_state.assess_mpu_scope(
            {"planned_contributions_count": 3, "mechanism_decomposition": {"components": ["a", "b", "c", "d"]}},
            target_venue="NeurIPS 2027",
        )
        self.assertEqual(mpu_over["mpu_verdict"], "over_scoped_for_mpu")

        mpu_under = project_state.assess_mpu_scope(
            {"planned_contributions_count": 1, "planned_datasets_count": 1, "gap_tier_ceiling": "workshop_incremental_only"},
            target_venue_tier="q1_or_tier_a",
        )
        self.assertEqual(mpu_under["mpu_verdict"], "under_scoped_for_target_tier")

    def test_advisor_stage_progression(self):
        s = project_state.init_state("proj-adv")
        self.assertEqual(project_state.generate_next_step_prompt(s)["current_stage"], "intake")
        s["target_venue_tier"] = "q1_or_tier_a"
        s["author_profile"] = {"strength_profile": "empirical_eval", "gpu_budget_hours": 80, "timeline_weeks": 8}
        self.assertEqual(project_state.generate_next_step_prompt(s)["current_stage"], "gap_discovery")

    def test_cli_nan_and_empty_args_exit_2_and_compact_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            bad_json = t / "bad.json"
            bad_json.write_text('{"strength_profile": "empirical_eval", "gpu_budget_hours": NaN}', encoding="utf-8")
            proc_nan = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "project_state.py"), "--init", "--author-profile", str(bad_json)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc_nan.returncode, 2)
            self.assertIn("error", json.loads(proc_nan.stderr))

            proc_empty = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "project_state.py"), "--state", "   ", "--audit"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc_empty.returncode, 2)

            state_path = t / "state.json"
            proc_ok = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "project_state.py"), "--state", str(state_path), "--init", "--advise", "--compact"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc_ok.returncode, 0, msg=proc_ok.stderr)
            self.assertLess(len(proc_ok.stdout.encode("utf-8")), 4096)
            out_obj = json.loads(proc_ok.stdout)
            self.assertTrue(out_obj["compact"])
            self.assertTrue(Path(out_obj["artifact_path"]).is_file())

    def test_bb1_bb6_provenance_stitching_blocking_gaps_lenses_and_cli_validation(self):
        # BB-1: corpus ingest must not synthesize locator='abstract' for full_text claim,
        # and register_corpus_digest must reject placeholder locator/quote.
        s = project_state.init_state("proj-bb1")
        c_ing = project_state.ingest_artifact(
            s,
            "corpus",
            {"papers": [{"id": "FAKE-FT-1", "title": "Some paper", "abstract": "Only an abstract.", "reading_basis": "full_text"}]},
        )
        self.assertTrue(any("silent_full_text_upgrade_blocked:FAKE-FT-1" in w for w in c_ing["warnings"]))
        self.assertEqual(s["corpus_digests"]["FAKE-FT-1"]["access"], "abstract")
        self.assertIsNone(s["corpus_digests"]["FAKE-FT-1"]["locator"])

        _, w2 = project_state.register_corpus_digest(
            s, {"source_id": "FAKE-FT-2", "access": "full_text", "locator": "TBD", "quote": "none"}
        )
        self.assertTrue(any("silent_full_text_upgrade_blocked:FAKE-FT-2" in w for w in w2))
        self.assertEqual(s["corpus_digests"]["FAKE-FT-2"]["access"], "metadata_only")
        self.assertEqual(project_state.audit_state(s, strict=True)["status"], "issues_detected")

        # BB-2: space-delimited '+' in "combine A + B + C" triggers stitching cue
        stitch_plus = project_state.assess_mechanism_decomposition({
            "title": "Combine A + B + C",
            "mechanism_decomposition": {
                "bottleneck_target": "TBD",
                "why_sota_fails": "none",
                "proposed_mechanism": "combine A + B + C",
                "components": [],
                "simplest_alternative": "TBD",
            },
        })
        self.assertTrue(stitch_plus["stitching_cue_detected"])
        self.assertTrue(stitch_plus["is_vague_stitching"])
        self.assertIn("vague_module_stitching_rejected", stitch_plus["issues"])

        stitch_non_placeholder = project_state.assess_mechanism_decomposition({
            "title": "Combine A + B + C",
            "mechanism_decomposition": {
                "bottleneck_target": "Calibration shifts under unseen domains",
                "why_sota_fails": "Static scalars ignore sample density",
                "proposed_mechanism": "combine A + B + C",
                "components": [],
                "simplest_alternative": "Single scalar temperature scaling baseline",
            },
        })
        self.assertTrue(stitch_non_placeholder["stitching_cue_detected"])
        self.assertIn("multi_component_proposal_requires_component_ablation", stitch_non_placeholder["warnings"])

        # BB-4: supported_candidate gap with empty support_source_ids and closest_work_ids fails audit
        s_gap = project_state.init_state("proj-bb4")
        project_state.ingest_artifact(
            s_gap,
            "gap_record",
            {
                "scope": "OOD calibration",
                "candidates": [
                    {
                        "id": "G-EMPTY",
                        "claim": "Unsupported gap claim",
                        "disposition": "supported_candidate",
                        "support_evidence_ids": [],
                        "closest_work_ids": [],
                    }
                ],
            },
        )
        gap_audit = project_state.audit_state(s_gap, strict=True)
        self.assertEqual(gap_audit["status"], "issues_detected")
        self.assertIn("gap_missing_supporting_sources:G-EMPTY", gap_audit["errors"])

        # BB-5: idea_seed_bundle merges lenses_f32 into existing gap without wiping existing keys
        s_lens = project_state.init_state("proj-bb5")
        project_state.ingest_artifact(
            s_lens,
            "gap_record",
            {
                "scope": "Calibration",
                "candidates": [
                    {
                        "id": "G1",
                        "claim": "Static scaling degrades under shift",
                        "disposition": "early_signal",
                        "root_cause_barrier": "theoretical_limit",
                        "why_now_enabler": "New bound discovered recently",
                        "durability_12_24m": "durable_structural_limit",
                    }
                ],
            },
        )
        project_state.ingest_artifact(
            s_lens,
            "idea_seed_bundle",
            {
                "gap_id": "G1",
                "so_what_decision_impact": "decision_changing",
                "candidate_ideas": [{"id": "I1", "title": "Idea 1"}],
            },
        )
        merged_lenses = s_lens["gaps"]["G1"]["lenses_f32"]
        self.assertEqual(merged_lenses["root_cause_barrier"], "theoretical_limit")
        self.assertEqual(merged_lenses["why_now_enabler"], "New bound discovered recently")
        self.assertEqual(merged_lenses["durability_12_24m"], "durable_structural_limit")
        self.assertEqual(merged_lenses["so_what_decision_impact"], "decision_changing")

        # BB-3: blocked_harking / gate_failed outcomes, failed ledger, fatal/not_comparable scorecards,
        # and rejected/unready venue verdicts MUST block strict audit and advisor progression
        s_gate = project_state.init_state(
            "proj-bb3",
            target_venue="NeurIPS 2027",
            author_profile={"strength_profile": "empirical_eval", "gpu_budget_hours": 100, "timeline_weeks": 8},
        )
        project_state.register_corpus_digest(
            s_gate, {"source_id": "SRC-1", "access": "full_text", "locator": "Sec 2, p. 3", "quote": "Verified source quote."}
        )
        project_state.ingest_artifact(
            s_gate,
            "idea_seed_bundle",
            {
                "gap_id": "G1",
                "claim": "Shift degrades calibration.",
                "support_source_ids": ["SRC-1"],
                "candidate_ideas": [{
                    "id": "IDEA-1",
                    "title": "Density gate",
                    "bottleneck_target": "Global scalar temperature ignores density",
                    "why_sota_fails": "Uniform scaling overconfident on OOD",
                    "proposed_mechanism": "Scale logits by normalized density",
                    "components": ["density_gate"],
                    "simplest_alternative": "Global scalar temperature scaling baseline",
                    "planned_contributions_count": 1,
                    "planned_datasets_count": 2,
                }],
            },
        )
        project_state.ingest_artifact(s_gate, "question_card", _valid_question_card("RQ-1"), link_ids={"idea_id": "IDEA-1", "gap_id": "G1"})
        project_state.ingest_artifact(
            s_gate,
            "experiment_manifest",
            {
                "question_id": "RQ-1",
                "protocol_version": "v1",
                "protocol_frozen_at_utc": "2026-11-20T00:00:00Z",
                "runs": [{
                    "run_id": "R1",
                    "role": "candidate",
                    "protocol_version": "v1",
                    "code_commit": "abc",
                    "data_version": "v1",
                    "split_manifest_sha256": _hex64("1"),
                    "metric_id": "ece",
                    "metric_script_sha256": _hex64("2"),
                    "command": "python3 run.py",
                    "started_at_utc": "2026-11-21T00:00:00Z",
                    "ended_at_utc": "2026-11-21T01:00:00Z",
                    "exit_code": 0,
                    "result_artifact_sha256": _hex64("3"),
                    "result_value": 0.05,
                    "deviations": [],
                    "decision_timing": "prespecified",
                }],
            },
            link_ids={"rq_id": "RQ-1"},
        )
        project_state.ingest_artifact(
            s_gate,
            "experiment_outcome",
            {"status": "blocked_harking", "outcome_classification": "rival_or_null_supported", "question_id": "RQ-1"},
            link_ids={"rq_id": "RQ-1", "run_ids": ["R1"]},
        )
        self.assertEqual(s_gate["experiments"]["R1"]["outcome_status"], "blocked_harking")
        self.assertEqual(project_state.audit_state(s_gate, strict=True)["status"], "issues_detected")
        self.assertEqual(project_state.generate_next_step_prompt(s_gate)["current_stage"], "experiment_and_outcome_audit")

        # Fix outcome -> test failed ledger & fatal/not_comparable scorecard
        project_state.ingest_artifact(
            s_gate,
            "experiment_outcome",
            {"status": "analyzed", "outcome_classification": "focal_supported", "question_id": "RQ-1"},
            link_ids={"rq_id": "RQ-1", "run_ids": ["R1"]},
        )
        project_state.ingest_artifact(
            s_gate,
            "manuscript_ledger",
            {
                "passed": False,
                "claims": [{"id": "C1", "kind": "reported", "rq_id": "RQ-1", "run_ids": ["R1"], "source_ids": ["SRC-1"]}],
            },
        )
        project_state.ingest_artifact(
            s_gate,
            "scorecards",
            {
                "target_id": "target",
                "status": "not_comparable",
                "submission_readiness": {"target": {"fatal_gate_triggered": True}},
            },
            link_ids={"claim_id": "C1"},
        )
        project_state.ingest_artifact(
            s_gate,
            "venue_novelty",
            {"submission_readiness": {"verdict": "rejected_below_venue_tier", "ready_to_submit": False}},
        )
        self.assertEqual(project_state.audit_state(s_gate, strict=True)["status"], "issues_detected")
        self.assertEqual(project_state.generate_next_step_prompt(s_gate)["current_stage"], "manuscript_and_scoring")

        # Fix ledger & scorecard -> rejected venue verdict must stay at venue_evaluation, never ready_for_reporting
        project_state.ingest_artifact(
            s_gate,
            "manuscript_ledger",
            {
                "passed": True,
                "claims": [{"id": "C1", "kind": "reported", "rq_id": "RQ-1", "run_ids": ["R1"], "source_ids": ["SRC-1"]}],
            },
        )
        s_gate["scorecards"] = {}
        project_state.ingest_artifact(
            s_gate,
            "scorecards",
            {
                "target_id": "target",
                "status": "structurally_comparable",
                "submission_readiness": {"target": {"fatal_gate_triggered": False}},
            },
            link_ids={"claim_id": "C1"},
        )
        self.assertEqual(project_state.audit_state(s_gate, strict=True)["status"], "issues_detected")
        self.assertEqual(project_state.generate_next_step_prompt(s_gate)["current_stage"], "venue_evaluation")

        # BB-6: --target-venue "" and --target-venue-tier bogus/"" exit 2 on init and update
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            st_file = t / "cli_state.json"
            self.assertEqual(
                subprocess.run(
                    [sys.executable, str(SCRIPTS_DIR / "project_state.py"), "--state", str(st_file), "--init", "--target-venue", ""],
                    capture_output=True, text=True, check=False,
                ).returncode,
                2,
            )
            self.assertEqual(
                subprocess.run(
                    [sys.executable, str(SCRIPTS_DIR / "project_state.py"), "--state", str(st_file), "--init", "--target-venue-tier", "bogus_tier"],
                    capture_output=True, text=True, check=False,
                ).returncode,
                2,
            )
            self.assertEqual(
                subprocess.run(
                    [sys.executable, str(SCRIPTS_DIR / "project_state.py"), "--state", str(st_file), "--init", "--target-venue", "NeurIPS 2027"],
                    capture_output=True, text=True, check=False,
                ).returncode,
                0,
            )
            for bad_flag in (["--target-venue", "   "], ["--target-venue-tier", ""], ["--target-venue-tier", "bogus_invalid_tier"]):
                proc = subprocess.run(
                    [sys.executable, str(SCRIPTS_DIR / "project_state.py"), "--state", str(st_file), *bad_flag],
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(proc.returncode, 2, msg=f"{bad_flag}: {proc.stdout} {proc.stderr}")

    def _make_passing_lifecycle_state(self, project_id="proj-bb-iter3"):
        s = project_state.init_state(
            project_id,
            target_venue="NeurIPS 2027",
            author_profile={"strength_profile": "empirical_eval", "gpu_budget_hours": 100, "timeline_weeks": 8},
        )
        project_state.register_corpus_digest(
            s, {"source_id": "SRC-1", "access": "full_text", "locator": "Sec 2, p. 3", "quote": "Verified source quote."}
        )
        project_state.ingest_artifact(
            s,
            "idea_seed_bundle",
            {
                "gap_id": "G1",
                "claim": "Static scaling degrades under domain shift.",
                "support_source_ids": ["SRC-1"],
                "candidate_ideas": [{
                    "id": "IDEA-1",
                    "title": "Density gate",
                    "bottleneck_target": "Global scalar temperature ignores density",
                    "why_sota_fails": "Uniform scaling overconfident on OOD",
                    "proposed_mechanism": "Scale logits by normalized density",
                    "components": ["density_gate"],
                    "simplest_alternative": "Global scalar temperature scaling baseline",
                    "planned_contributions_count": 1,
                    "planned_datasets_count": 2,
                }],
            },
        )
        project_state.ingest_artifact(s, "question_card", _valid_question_card("RQ-1"), link_ids={"idea_id": "IDEA-1", "gap_id": "G1"})
        project_state.ingest_artifact(
            s,
            "experiment_manifest",
            {
                "question_id": "RQ-1",
                "protocol_version": "v1",
                "protocol_frozen_at_utc": "2026-11-20T00:00:00Z",
                "runs": [{
                    "run_id": "R1",
                    "role": "candidate",
                    "protocol_version": "v1",
                    "code_commit": "abc",
                    "data_version": "v1",
                    "split_manifest_sha256": _hex64("1"),
                    "metric_id": "ece",
                    "metric_script_sha256": _hex64("2"),
                    "command": "python3 run.py",
                    "started_at_utc": "2026-11-21T00:00:00Z",
                    "ended_at_utc": "2026-11-21T01:00:00Z",
                    "exit_code": 0,
                    "result_artifact_sha256": _hex64("3"),
                    "result_value": 0.05,
                    "deviations": [],
                    "decision_timing": "prespecified",
                }],
            },
            link_ids={"rq_id": "RQ-1"},
        )
        project_state.ingest_artifact(
            s,
            "experiment_outcome",
            {"status": "analyzed", "outcome_classification": "focal_supported", "question_id": "RQ-1"},
            link_ids={"rq_id": "RQ-1", "run_ids": ["R1"]},
        )
        project_state.ingest_artifact(
            s,
            "manuscript_ledger",
            {
                "passed": True,
                "claims": [{"id": "C1", "kind": "reported", "rq_id": "RQ-1", "run_ids": ["R1"], "source_ids": ["SRC-1"]}],
            },
        )
        project_state.ingest_artifact(
            s,
            "scorecards",
            {
                "target_id": "target_paper",
                "status": "structurally_comparable",
                "submission_readiness": {"target_paper": {"band": "competitive_top_tier_main_track", "fatal_gate_triggered": False}},
            },
            link_ids={"claim_id": "C1"},
        )
        project_state.ingest_artifact(
            s,
            "venue_novelty",
            {
                "venue": {"name": "NeurIPS 2027"},
                "submission_readiness": {
                    "venue_tier": "top_tier_flagship",
                    "verdict": "competitive_top_tier_main_track",
                    "ready_to_submit": True,
                },
            },
        )
        return s

    def test_bb12_bb13_bb14_cross_tool_scorecards_ledger_and_advisor_strict(self):
        # BB-12: Real compare_scorecards output with baseline_1 passing and target_paper fatal_gate=True
        dims = score_math.DIMENSIONS
        locators_ok = {d: ["Section 1, p. 1"] for d in dims}
        weights_100 = {"importance": 20, "novelty": 20, "soundness": 20, "evidence": 20, "transparency": 10, "clarity": 10}
        sc_doc = {
            "weight_scenarios": [weights_100],
            "profiles": [
                {
                    "id": "baseline_1",
                    "reading_basis": "full_text",
                    "closest_work": ["target_paper"],
                    "ratings": {d: 7 for d in dims},
                    "evidence_locators": locators_ok,
                },
                {
                    "id": "target_paper",
                    "reading_basis": "full_text",
                    "closest_work": ["baseline_1"],
                    "ratings": {"importance": 7, "novelty": 2, "soundness": 7, "evidence": 7, "transparency": 7, "clarity": 7},
                    "evidence_locators": locators_ok,
                },
            ],
        }
        real_sc_targeted = compare_scorecards.compare(sc_doc, target_id="target_paper")
        self.assertEqual(real_sc_targeted["status"], "structurally_comparable")
        self.assertEqual(real_sc_targeted["related_work_comparison"]["target_id"], "target_paper")
        self.assertTrue(real_sc_targeted["submission_readiness"]["target_paper"]["fatal_gate_triggered"])

        s12 = self._make_passing_lifecycle_state("proj-bb12")
        s12["scorecards"] = {}
        project_state.ingest_artifact(s12, "scorecards", real_sc_targeted, link_ids={"claim_id": "C1"})
        sc_rec = s12["scorecards"]["SC-1"]
        self.assertEqual(sc_rec["target_id"], "target_paper")
        self.assertTrue(sc_rec["fatal_gate_triggered"])
        a12 = project_state.audit_state(s12, strict=True)
        self.assertEqual(a12["status"], "issues_detected")
        self.assertIn("scorecard_fatal_gate_triggered:SC-1", a12["errors"])
        self.assertEqual(project_state.generate_next_step_prompt(s12)["current_stage"], "manuscript_and_scoring")

        # BB-12 without --target-id: must inspect ALL profiles in submission_readiness, not just first key
        real_sc_untargeted = compare_scorecards.compare(sc_doc)
        self.assertNotIn("related_work_comparison", real_sc_untargeted)
        s12_untargeted = self._make_passing_lifecycle_state("proj-bb12-untargeted")
        s12_untargeted["scorecards"] = {}
        project_state.ingest_artifact(s12_untargeted, "scorecards", real_sc_untargeted, link_ids={"claim_id": "C1"})
        self.assertTrue(s12_untargeted["scorecards"]["SC-1"]["fatal_gate_triggered"])
        self.assertEqual(project_state.audit_state(s12_untargeted, strict=True)["status"], "issues_detected")
        self.assertEqual(project_state.generate_next_step_prompt(s12_untargeted)["current_stage"], "manuscript_and_scoring")

        # BB-13 Part A: Real check_manuscript_ledger.py failure output (status='structural_issues', issues=[...], no 'passed' key)
        bad_ledger = {
            "sources": [{"id": "SRC-1", "type": "paper", "locator": "Sec 2, p. 3", "verified": True, "verified_by": "author", "verified_at": "2026-11-21"}],
            "claims": [{"id": "C1", "kind": "reported", "material": True, "rq_id": "RQ-1", "run_ids": ["R1"], "source_ids": []}],
            "methods": [],
            "numeric_facts": [{"id": "NF-1", "occurrences": []}],
        }
        real_ledger_fail = check_manuscript_ledger.check(bad_ledger, manuscript_text="We achieve 99.9% accuracy on ImageNet.")
        self.assertEqual(real_ledger_fail["status"], "structural_issues")
        self.assertNotIn("passed", real_ledger_fail)
        self.assertTrue(real_ledger_fail["issues"])

        s13 = self._make_passing_lifecycle_state("proj-bb13")
        project_state.ingest_artifact(s13, "manuscript_ledger", real_ledger_fail)
        self.assertFalse(s13["manuscript_ledger_status"]["passed"])
        self.assertEqual(s13["manuscript_ledger_status"]["errors"], real_ledger_fail["issues"])
        a13 = project_state.audit_state(s13, strict=True)
        self.assertEqual(a13["status"], "issues_detected")
        self.assertIn("manuscript_ledger_failed", a13["errors"])
        self.assertEqual(project_state.generate_next_step_prompt(s13)["current_stage"], "manuscript_and_scoring")

        # BB-13 Part A with empty claims: failed ledger still fails audit_state
        s13_empty = project_state.init_state("proj-bb13-empty")
        project_state.ingest_artifact(s13_empty, "manuscript_ledger", real_ledger_fail)
        self.assertEqual(s13_empty["manuscript_claims"], {})
        a13_empty = project_state.audit_state(s13_empty, strict=True)
        self.assertEqual(a13_empty["status"], "issues_detected")
        self.assertIn("manuscript_ledger_failed", a13_empty["errors"])

        # BB-13 Part A passing check_manuscript_ledger output clears failure
        good_ledger = {
            "sources": [{"id": "SRC-1", "type": "paper", "locator": "Sec 2, p. 3", "verified": True, "verified_by": "author", "verified_at": "2026-11-21"}],
            "claims": [{"id": "C1", "kind": "reported", "material": True, "rq_id": "RQ-1", "run_ids": ["R1"], "source_ids": ["SRC-1"]}],
            "methods": [],
            "numeric_facts": [],
        }
        real_ledger_pass = check_manuscript_ledger.check(good_ledger, manuscript_text="Qualitative discussion without unverified figures.")
        self.assertEqual(real_ledger_pass["status"], "structure_passed")
        project_state.ingest_artifact(s13, "manuscript_ledger", real_ledger_pass)
        self.assertTrue(s13["manuscript_ledger_status"]["passed"])
        self.assertEqual(project_state.audit_state(s13, strict=True)["status"], "passed")

        # BB-13 Part B: manuscript_ledger sources must NEVER synthesize digest='source' to pass Guard 1
        s13_prov = project_state.init_state("proj-bb13-prov")
        ing_prov = project_state.ingest_artifact(
            s13_prov,
            "manuscript_ledger",
            {
                "passed": True,
                "sources": [{"id": "FAKE-ML-1", "verified": True, "locator": "Section 1"}],
                "claims": [],
            },
        )
        self.assertTrue(any("silent_full_text_upgrade_blocked:FAKE-ML-1" in w for w in ing_prov["warnings"]))
        self.assertEqual(s13_prov["corpus_digests"]["FAKE-ML-1"]["access"], "metadata_only")
        self.assertIsNone(s13_prov["corpus_digests"]["FAKE-ML-1"]["digest"])
        self.assertIn("silent_full_text_upgrade_blocked:FAKE-ML-1", project_state.audit_state(s13_prov, strict=True)["errors"])

        # BB-14: generate_next_step_prompt MUST surface silent_full_text_upgrade_blocked and NEVER return ready_for_reporting
        s14 = self._make_passing_lifecycle_state("proj-bb14")
        self.assertEqual(project_state.generate_next_step_prompt(s14)["current_stage"], "ready_for_reporting")
        _, w14 = project_state.register_corpus_digest(
            s14, {"source_id": "SRC-FAKE", "access": "full_text", "locator": "TBD", "quote": "none"}
        )
        self.assertTrue(any("silent_full_text_upgrade_blocked:SRC-FAKE" in w for w in w14))
        strict14 = project_state.audit_state(s14, strict=True)
        self.assertEqual(strict14["status"], "issues_detected")
        self.assertIn("silent_full_text_upgrade_blocked:SRC-FAKE", strict14["errors"])
        adv14 = project_state.generate_next_step_prompt(s14)
        self.assertEqual(adv14["current_stage"], "gap_discovery")
        self.assertIn("silent_full_text_upgrade_blocked:SRC-FAKE", adv14["blocking_issues"])

    def test_bb15_gap_pipeline_and_idea_seed_bundle_cross_module_integration(self):
        corpus = {
            "P1": {
                "id": "P1", "family": "same_problem", "year": 2021,
                "title": "Rank Fusion Baseline", "retraction_status": "clean",
                "limitations": ["Uncalibrated under domain shift"],
            },
            "P2": {
                "id": "P2", "family": "cross_setting_analogy", "year": 2024,
                "title": "Transportability Under Covariate Shift", "retraction_status": "clean",
                "limitations": ["No rank aggregation guarantees"],
            },
        }
        digests_no_loc = {
            "P1": {"access": "full_text", "digest": "RRF uses fixed reciprocal rank constant k=60."},
            "P2": {"access": "full_text", "digest": "Importance weighting fails on extreme shift."},
        }
        cand = {
            "id": "G1",
            "claim": "Calibrated rank fusion under OOD shift remains uncharacterized.",
            "cited_ids": ["P1", "P2"],
            "support_ids": ["P1", "P2"],
            "closest_work_ids": ["P1", "P2"],
            "sgha_critics_passed": True,
            "engineering_checked": True,
            "why_now_enabler": "Open-weight dense retrievers expose calibrated logit margins across shifts.",
            "root_cause_barrier": "measurement_gap",
            "evaluation_validity_gap": {"subtype": "shortcut_exploitation", "cues": ["lexical_overlap"]},
            "isomorphic_transfer_leads": [{"domain": "economics", "mechanism": "rank scoring", "status": "lead"}],
            "so_what_decision_impact": "decision_changing",
            "durability_12_24m": "durable_structural_limit",
            "idea_portfolio": [
                {"id": "I1", "angle": "minimal_fix_f19", "title": "Temp scaling on fused logits"},
                {"id": "I2", "angle": "high_novelty_mechanism_q1", "title": "Causal transportability rank calibration"},
                {"id": "I3", "angle": "benchmark_diagnostic_analysis", "title": "OOD BEIR calibration benchmark"},
            ],
            "pre_mortem": {
                "top_failure_modes": ["RRF beats learned fusion", "OOD variance dominates", "Short queries drift"],
                "killer_experiment": {"duration_days": 1.5, "kill_threshold": "OOD ECE delta <= 0.01"},
                "pivot_path": "Pivot to diagnostic benchmark analysis of rank fusion failure modes",
            },
        }
        gp_out = gap_pipeline.run_pipeline(
            "rank fusion", corpus, digests_no_loc, [cand],
            require_idea_portfolio=True, require_pre_mortem=True,
        )
        self.assertEqual(gp_out["exit_code"], 0)
        bundle = gp_out["idea_seed_bundle"]
        self.assertEqual(bundle["schema"], "research_scientist_idea_seed_bundle_v1")

        # 1. Fresh state without verified locators ingests G1/ideas/lenses/trajectory_tree AND fails closed in audit_state
        st_unverified = project_state.init_state(
            project_id="proj-bb15-fail", title="Rank Fusion", subfield_preset="nlp_llm", target_venue="NeurIPS 2027"
        )
        b_res = project_state.ingest_artifact(st_unverified, "idea_seed_bundle", bundle)
        self.assertEqual(b_res["errors"], [])
        self.assertIn("G1", st_unverified["gaps"])
        self.assertNotIn("G-BUNDLE-1", st_unverified["gaps"])
        self.assertEqual(set(st_unverified["ideas"].keys()), {"I1", "I2", "I3"})
        self.assertEqual(st_unverified["gaps"]["G1"]["support_source_ids"], ["P1", "P2"])
        self.assertEqual(st_unverified["gaps"]["G1"]["closest_work_ids"], ["P1", "P2"])
        self.assertEqual(st_unverified["gaps"]["G1"]["lenses_f32"]["root_cause_barrier"], "measurement_gap")
        self.assertEqual(st_unverified["gaps"]["G1"]["lenses_f32"]["evaluation_validity_gap"]["subtype"], "shortcut_exploitation")
        self.assertIsInstance(st_unverified["trajectory_tree"], dict)
        self.assertTrue(st_unverified["trajectory_tree"]["generations"])
        self.assertEqual(st_unverified["ideas"]["I2"]["killer_experiment"]["duration_days"], 1.5)
        self.assertTrue(any("unread_or_metadata_only_source:gap:G1:P1" in e for e in project_state.audit_state(st_unverified, strict=True)["errors"]))

        # Verify advise_contribution_pivot understands gap_pipeline's evaluation_validity_gap dict
        piv = project_state.advise_contribution_pivot(st_unverified["ideas"]["I1"])
        self.assertIn("benchmark_dataset", piv["candidate_pivots"])

        # 2. Pre-registered verified full_text digests + full gap_pipeline ingestion passes strict audit cleanly
        st_ok = project_state.init_state(
            project_id="proj-bb15-ok", title="Rank Fusion", subfield_preset="nlp_llm", target_venue="NeurIPS 2027"
        )
        project_state.register_corpus_digest(
            st_ok, {"source_id": "P1", "access": "full_text", "locator": "Section 2, p. 3", "quote": "RRF uses fixed constant k=60."}
        )
        project_state.register_corpus_digest(
            st_ok, {"source_id": "P2", "access": "full_text", "locator": "Section 4, p. 7", "quote": "Importance weighting fails under shift."}
        )
        gp_res = project_state.ingest_artifact(st_ok, "gap_pipeline", gp_out)
        self.assertEqual(gp_res["errors"], [])
        self.assertEqual(gp_res["warnings"], [])
        self.assertIn("G1", gp_res["ingested_ids"])
        self.assertEqual(set(st_ok["ideas"].keys()), {"I1", "I2", "I3"})
        self.assertIsInstance(st_ok["trajectory_tree"], dict)
        self.assertIn("G1", st_ok["trajectory_trees"])
        self.assertEqual(project_state.audit_state(st_ok, strict=True)["status"], "passed")

        # 3. Empty seeds list must NOT create phantom G-BUNDLE-1
        st_empty_seeds = project_state.init_state("proj-bb15-empty")
        empty_res = project_state.ingest_artifact(
            st_empty_seeds, "idea_seed_bundle", {"schema": "research_scientist_idea_seed_bundle_v1", "seeds": []}
        )
        self.assertEqual(empty_res["ingested_ids"], [])
        self.assertEqual(st_empty_seeds["gaps"], {})

    def test_bb16_recommended_rebuttal_command_valid_against_check_rebuttal_cli(self):
        # Pending rebuttal point and rebuttal blocking error must emit valid `check_rebuttal.py coverage ...` CLI
        for mode in ("pending", "missing_anchor"):
            st = self._make_passing_lifecycle_state(f"proj-bb16-{mode}")
            if mode == "pending":
                st["rebuttal_points"] = {"R1.1": {"point_id": "R1.1", "claim_ids": ["C1"], "run_ids": ["R1"], "anchor": "Table 1", "status": "pending"}}
            else:
                st["rebuttal_points"] = {"R1.1": {"point_id": "R1.1", "claim_ids": ["C1"], "run_ids": ["R1"], "anchor": "", "status": "addressed"}}
            adv = project_state.generate_next_step_prompt(st)
            self.assertEqual(adv["current_stage"], "rebuttal")
            self.assertTrue(adv["recommended_commands"])
            cmd = adv["recommended_commands"][0]
            tokens = shlex.split(cmd)
            self.assertEqual(Path(tokens[1]).name, "check_rebuttal.py")
            self.assertIn("coverage", tokens)
            self.assertNotIn("--manuscript", tokens)

            with tempfile.TemporaryDirectory() as tmp:
                t = Path(tmp)
                (t / "triage_points.md").write_text("- [R1.1] Address OOD calibration shift\n", encoding="utf-8")
                (t / "rebuttal.md").write_text("## R1.1\nAs shown in Table 1, ECE drops from 0.09 to 0.05.\n", encoding="utf-8")
                proc = subprocess.run(
                    [sys.executable, str(SCRIPTS_DIR / "check_rebuttal.py"), *tokens[2:]],
                    cwd=str(t), capture_output=True, text=True, check=False,
                )
                self.assertEqual(proc.returncode, 0, msg=f"Command failed ({cmd}): {proc.stdout}\n{proc.stderr}")


class TestBuildResearchInputs(unittest.TestCase):
    def test_offline_topic_and_mock_search_zero_fabrication(self):
        mock_search = json.loads((FIXTURES_DIR / "area1" / "gcn_search_mock_responses.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "out"
            res = build_research_inputs.build_inputs(
                topic="graph convolutional networks semi-supervised",
                target_venue="NeurIPS 2027",
                subfield_preset="ml_theory",
                offline=True,
                mock_search_data=mock_search,
                out_dir=out_dir,
            )
            self.assertGreaterEqual(res["paper_count"], 3)
            for p in res["corpus"]["papers"]:
                self.assertEqual(p["reading_basis"], "metadata_only")
                self.assertIsNone(p["ratings"])
                self.assertIsNone(p["full_text_excerpt"])
                self.assertIn(p["access"], ("abstract", "metadata"))

            gap_chk = check_gap_record.check(res["gap_record"])
            self.assertTrue(gap_chk["valid_structure"], msg=gap_chk["errors"])
            self.assertEqual(res["gap_record"]["candidates"][0]["disposition"], "insufficient_evidence")

            # compare_scorecards must NOT crash with ValueError; must return status=not_comparable
            sc_chk = compare_scorecards.compare(res["scorecards"])
            self.assertEqual(sc_chk["status"], "not_comparable")
            for prof in res["scorecards"]["profiles"]:
                self.assertEqual(set(prof["ratings"].keys()), set(score_math.DIMENSIONS))
                self.assertTrue(all(v is None for v in prof["ratings"].values()))
            for mp in res["scorecards"]["metadata_only_papers"]:
                self.assertIsNone(mp["ratings"])
                self.assertEqual(mp["reading_basis"], "metadata_only")

            self.assertEqual(res["dossier"]["verification_summary"]["cfp_status"], "unverified")
            self.assertTrue(all(f["amount"] is None and f["verification_status"] == "unverified" for f in res["dossier"]["fees"]))
            self.assertEqual(res["corpus"]["subfield_preset"], "ml_theory")

    def test_local_pdf_and_tex_modes_plus_traversal_block(self):
        pdf_fixture = FIXTURES_DIR / "area1" / "gcn_1609_02907v4_excerpt.pdf"
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            res_pdf = build_research_inputs.build_inputs(
                pdf_path=str(pdf_fixture),
                subfield_preset="nlp_llm",
                offline=True,
                out_dir=t / "pdf_out",
            )
            self.assertEqual(res_pdf["target_reading_basis"], "full_text")
            self.assertTrue(Path(res_pdf["corpus"]["target_manuscript"]["extracted_blocks_path"]).is_file())

            # Safe LaTeX with \input and .bib
            tex_dir = t / "tex_proj"
            tex_dir.mkdir()
            (tex_dir / "sec1.tex").write_text("We study calibration under distribution shift.", encoding="utf-8")
            (tex_dir / "refs.bib").write_text("@article{guo2017,\n  title={On Calibration of Modern Neural Networks},\n  year={2017}\n}\n", encoding="utf-8")
            main_tex = tex_dir / "main.tex"
            main_tex.write_text(
                "\\documentclass{article}\n\\title{Shift-Aware Calibration}\n\\begin{document}\n"
                "\\begin{abstract}We investigate calibration under covariate shift.\\end{abstract}\n"
                "\\input{sec1}\n\\end{document}\n",
                encoding="utf-8",
            )
            res_tex = build_research_inputs.build_inputs(
                input_path=str(main_tex),
                subfield_preset="ai_systems",
                offline=True,
                out_dir=t / "tex_out",
            )
            self.assertEqual(res_tex["target_reading_basis"], "full_text")
            self.assertEqual(res_tex["paper_count"], 1)
            self.assertEqual(res_tex["corpus"]["papers"][0]["reading_basis"], "metadata_only")

            # Traversal blocked
            (tex_dir / "evil.tex").write_text("\\documentclass{article}\\begin{document}\\input{../secret.tex}\\end{document}", encoding="utf-8")
            with self.assertRaises(ValueError):
                build_research_inputs.build_inputs(tex_path=str(tex_dir / "evil.tex"), offline=True, out_dir=t / "evil_out")

    def test_all_four_subfield_presets_and_invalid_cli_exit_2(self):
        for preset in ("nlp_llm", "cv_multimodal", "ml_theory", "ai_systems", "speech_audio"):
            with tempfile.TemporaryDirectory() as tmp:
                res = build_research_inputs.build_inputs(
                    topic=f"test topic for {preset}",
                    subfield_preset=preset,
                    offline=True,
                    out_dir=tmp,
                )
                self.assertEqual(res["subfield_preset"], preset)
                self.assertTrue(res["corpus"]["subfield_criteria"]["gap_vetting_checks"])

        proc_bad = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "build_research_inputs.py"), "--topic", "  ", "--offline"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(proc_bad.returncode, 2)

        proc_nan = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "build_research_inputs.py"), "--topic", "test", "--budget-usd", "NaN", "--offline"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(proc_nan.returncode, 2)

    def test_bb10_corpus_json_results_schema_and_bb11_blank_pdf_downgrade(self):
        # BB-10: --corpus-json accepts search_papers.py {"results": [...]} schema
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            corpus_file = t / "search_results.json"
            corpus_file.write_text(
                json.dumps({
                    "schema": "research_scientist_search_v2",
                    "results": [
                        {"id": "R1", "title": "Results Key Paper", "abstract": "Concrete abstract text."},
                        {"id": "R2", "title": "Second Results Paper", "abstract": "Second abstract."},
                    ],
                }),
                encoding="utf-8",
            )
            out_dir = t / "out_results"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "build_research_inputs.py"),
                    "--topic", "calibration",
                    "--corpus-json", str(corpus_file),
                    "--offline",
                    "--out-dir", str(out_dir),
                ],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            corpus_doc = json.loads((out_dir / "corpus.json").read_text(encoding="utf-8"))
            self.assertEqual(len(corpus_doc["papers"]), 2)
            self.assertEqual(corpus_doc["papers"][0]["id"], "R1")
            self.assertEqual(corpus_doc["papers"][0]["reading_basis"], "metadata_only")

            # BB-11: blank / 0-block PDF must downgrade cleanly to unavailable without E-TARGET full_text
            import fitz
            blank_pdf = t / "blank_scanned_name.pdf"
            doc = fitz.open()
            doc.new_page()
            doc.save(str(blank_pdf))
            doc.close()

            out_blank = t / "out_blank"
            res_blank = build_research_inputs.build_inputs(
                pdf_path=str(blank_pdf),
                offline=True,
                out_dir=out_blank,
            )
            self.assertEqual(res_blank["target_reading_basis"], "unavailable")
            self.assertIn("pdf_zero_extracted_blocks:downgraded_to_unavailable", res_blank["warnings"])
            tm = res_blank["corpus"]["target_manuscript"]
            self.assertEqual(tm["blocks_count"], 0)
            self.assertEqual(tm["reading_basis"], "unavailable")
            self.assertEqual(tm["access"], "unavailable")
            self.assertIsNone(tm["locator"])
            self.assertIsNone(tm["quote"])
            self.assertFalse(any(ev.get("id") == "E-TARGET" for ev in res_blank["gap_record"]["evidence"]))


class TestAnalyzeExperimentOutcome(unittest.TestCase):
    def test_valid_analyzed_vs_aggregate_only_rejection(self):
        qc = _valid_question_card()
        agg_only = {
            "claim_mode": "confirmatory",
            "claimed_outcome": "supports_focal",
            "primary_metric": {"name": "ece", "direction": "lower", "baseline": 0.09, "candidate": 0.05},
            "error_slices": [{"slice_type": "ood_shift", "slice_name": "domain_shift", "baseline": 0.12, "candidate": 0.07, "n": 500}],
        }
        res_bad = analyze_experiment_outcome.analyze(qc, agg_only)
        self.assertEqual(res_bad["status"], "gate_failed")
        self.assertIn("insufficient_error_slices:need_at_least_2", res_bad["errors"])

        good_outcomes = {
            "claim_mode": "confirmatory",
            "claimed_outcome": "supports_focal",
            "claimed_hypothesis": "Adaptive temperature scaling improves ECE on OOD domain shift while keeping accuracy stable.",
            "post_hoc_hypothesis_changed": False,
            "primary_metric": {"name": "ece", "direction": "lower", "baseline": 0.09, "candidate": 0.05, "ci95": [0.02, 0.06]},
            "error_slices": [
                {"slice_type": "ood_shift", "slice_name": "domain_shift", "baseline": 0.12, "candidate": 0.07, "n": 500},
                {"slice_type": "length", "slice_name": "long_context", "baseline": 0.08, "candidate": 0.04, "n": 500},
            ],
            "ablation_results": [{"component": "density_gate", "marginal_gain": 0.03}],
            "engineering_diagnostics_verdict": "PASS",
        }
        res_ok = analyze_experiment_outcome.analyze(qc, good_outcomes)
        self.assertEqual(res_ok["status"], "analyzed")
        self.assertFalse(res_ok["harking_detected"])
        self.assertEqual(res_ok["outcome_classification"], "focal_supported")

    def test_harking_detection_blocks_rewrites_and_falsifier_reversals(self):
        qc = _valid_question_card()
        hark1 = {
            "claim_mode": "confirmatory",
            "claimed_outcome": "supports_focal",
            "post_hoc_hypothesis_changed": True,
            "primary_metric": {"name": "accuracy", "direction": "higher", "baseline": 0.72, "candidate": 0.70},
            "error_slices": [
                {"slice_type": "length", "slice_name": "short_context", "baseline": 0.80, "candidate": 0.82, "n": 200},
                {"slice_type": "ood_shift", "slice_name": "domain_shift", "baseline": 0.64, "candidate": 0.58, "n": 400},
            ],
        }
        r1 = analyze_experiment_outcome.analyze(qc, hark1)
        self.assertEqual(r1["status"], "blocked_harking")
        self.assertTrue(r1["harking_detected"])

        # Prior outcome exposure blocks confirmatory claim
        qc_exposed = _valid_question_card()
        qc_exposed["prior_outcome_exposure"] = "already_inspected_validation_set"
        r2 = analyze_experiment_outcome.analyze(qc_exposed, {
            "claim_mode": "confirmatory",
            "claimed_outcome": "indeterminate",
            "primary_metric": {"name": "accuracy", "direction": "higher", "baseline": 0.70, "candidate": 0.72},
            "error_slices": [
                {"slice_type": "length", "slice_name": "short", "baseline": 0.70, "candidate": 0.72, "n": 100},
                {"slice_type": "ood_shift", "slice_name": "ood", "baseline": 0.70, "candidate": 0.72, "n": 100},
            ],
        })
        self.assertEqual(r2["status"], "blocked_harking")

    def test_pivots_and_failure_cases_export_consumed_by_project_state(self):
        qc = _valid_question_card()
        mixed_out = {
            "claim_mode": "exploratory",
            "claimed_outcome": "mixed",
            "primary_metric": {"name": "accuracy", "direction": "higher", "baseline": 0.72, "candidate": 0.71},
            "error_slices": [
                {"slice_type": "length", "slice_name": "short_context", "baseline": 0.80, "candidate": 0.83, "n": 300},
                {"slice_type": "ood_shift", "slice_name": "domain_shift", "baseline": 0.64, "candidate": 0.57, "n": 300, "notes": "Degrades under domain shift"},
            ],
            "engineering_diagnostics_verdict": "PASS",
            "target_venue": "NeurIPS 2027",
            "target_venue_tier": "top_tier_flagship",
            "proposed_paper_score": 5.5,
        }
        res_mixed = analyze_experiment_outcome.analyze(qc, mixed_out)
        self.assertEqual(res_mixed["status"], "analyzed")
        actions = {p["action"] for p in res_mixed["pivot_recommendations"]}
        self.assertTrue({"add_targeted_ablation", "narrow_claim_scope", "downgrade_venue_tier"} <= actions)
        self.assertEqual(len(res_mixed["failure_cases"]), 1)
        self.assertEqual(res_mixed["failure_cases"][0]["failure_category"], "mechanistic_boundary")

        # Rival supported -> pivot_to_negative_or_diagnostic_paper
        rival_out = {
            "claim_mode": "confirmatory",
            "claimed_outcome": "rival_supported",
            "primary_metric": {"name": "accuracy", "direction": "higher", "baseline": 0.75, "candidate": 0.72},
            "error_slices": [
                {"slice_type": "length", "slice_name": "short", "baseline": 0.80, "candidate": 0.78, "n": 200},
                {"slice_type": "ood_shift", "slice_name": "ood", "baseline": 0.70, "candidate": 0.66, "n": 200},
            ],
            "engineering_diagnostics_verdict": "PASS",
        }
        res_rival = analyze_experiment_outcome.analyze(qc, rival_out)
        rival_actions = {p["action"] for p in res_rival["pivot_recommendations"]}
        self.assertIn("pivot_to_negative_or_diagnostic_paper", rival_actions)

        # Ingest failure_cases into project_state
        st = project_state.init_state("proj-fc")
        fc_ing = project_state.ingest_artifact(st, "failure_cases", res_mixed["failure_cases_payload"])
        self.assertEqual(len(fc_ing["ingested_ids"]), 1)
        self.assertEqual(st["failure_cases"][0]["failure_category"], "mechanistic_boundary")

    def test_verify_files_sha256_mismatch_blocks_outcome(self):
        qc = _valid_question_card("RQ-SHA")
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            res_file = t / "cand.json"
            res_file.write_text('{"accuracy": 0.8}', encoding="utf-8")
            man = {
                "question_id": "RQ-SHA",
                "protocol_version": "v1",
                "protocol_frozen_at_utc": "2026-01-01T00:00:00Z",
                "runs": [
                    {
                        "run_id": "cand-1",
                        "role": "candidate",
                        "protocol_version": "v1",
                        "code_commit": "abc",
                        "data_version": "v1",
                        "split_manifest_sha256": _hex64("1"),
                        "metric_id": "accuracy",
                        "metric_script_sha256": _hex64("2"),
                        "command": "python3 run.py",
                        "started_at_utc": "2026-01-02T00:00:00Z",
                        "ended_at_utc": "2026-01-02T01:00:00Z",
                        "exit_code": 0,
                        "result_artifact_path": "cand.json",
                        "result_artifact_sha256": _hex64("f"),
                        "result_value": 0.8,
                        "deviations": [],
                        "decision_timing": "prespecified",
                    }
                ],
            }
            outcomes = {
                "claim_mode": "confirmatory",
                "claimed_outcome": "supports_focal",
                "primary_metric": {"name": "accuracy", "direction": "higher", "baseline": 0.7, "candidate": 0.8},
                "error_slices": [
                    {"slice_type": "length", "slice_name": "short", "baseline": 0.7, "candidate": 0.8, "n": 100},
                    {"slice_type": "ood_shift", "slice_name": "ood", "baseline": 0.7, "candidate": 0.8, "n": 100},
                ],
            }
            res = analyze_experiment_outcome.analyze(qc, outcomes, manifest=man, manifest_dir=t, verify_files=True)
            self.assertEqual(res["status"], "blocked_harking")
            self.assertEqual(res["outcome_classification"], "engineering_artifact_unresolved")
            self.assertTrue(any("sha256 mismatch" in e for e in res["errors"]))

    def test_bb7_bb8_bb9_duplicate_slices_cherry_pick_and_prior_exposure(self):
        qc = _valid_question_card("RQ-BB")
        # BB-7: duplicate identical error slice must fail with gate_failed
        slice_a = {"slice_type": "ood_shift", "slice_name": "domain_shift", "baseline": 0.10, "candidate": 0.06, "n": 500}
        dup_res = analyze_experiment_outcome.analyze(
            qc,
            {
                "claim_mode": "confirmatory",
                "claimed_outcome": "supports_focal",
                "primary_metric": {"name": "ece", "direction": "lower", "baseline": 0.10, "candidate": 0.06, "ci95": [0.01, 0.07]},
                "error_slices": [slice_a, dict(slice_a)],
            },
        )
        self.assertEqual(dup_res["status"], "gate_failed")
        self.assertIn("duplicate_error_slices", dup_res["errors"])
        self.assertEqual(dup_res["slice_summary"]["total_valid_slices"], 1)

        # BB-8: cherry-picked slice HARKing even when primary_delta > 0 and winning == losing == 1
        cherry_res = analyze_experiment_outcome.analyze(
            qc,
            {
                "claim_mode": "confirmatory",
                "claimed_outcome": "supports_focal",
                "claimed_hypothesis": "Adaptive temperature scaling improves short_context calibration error",
                "primary_metric": {"name": "ece", "direction": "lower", "baseline": 0.10, "candidate": 0.09, "ci95": [0.001, 0.02]},
                "error_slices": [
                    {"slice_type": "length", "slice_name": "short_context", "baseline": 0.10, "candidate": 0.05, "n": 900},
                    {"slice_type": "ood_shift", "slice_name": "domain_shift", "baseline": 0.10, "candidate": 0.14, "n": 100},
                ],
            },
        )
        self.assertEqual(cherry_res["status"], "blocked_harking")
        self.assertTrue(cherry_res["harking_detected"])
        self.assertIn("cherry_picked_slice_harking:omits_regressing_slice", cherry_res["harking_violations"])

        # BB-9: canonical exposed values block confirmatory; safe values pass
        base_ok = {
            "claim_mode": "confirmatory",
            "claimed_outcome": "supports_focal",
            "claimed_hypothesis": "Adaptive temperature scaling improves OOD domain shift calibration error.",
            "primary_metric": {"name": "ece", "direction": "lower", "baseline": 0.10, "candidate": 0.06, "ci95": [0.02, 0.06]},
            "error_slices": [
                {"slice_type": "ood_shift", "slice_name": "domain_shift", "baseline": 0.10, "candidate": 0.06, "n": 300},
                {"slice_type": "length", "slice_name": "long_context", "baseline": 0.09, "candidate": 0.05, "n": 300},
            ],
        }
        for exposed in ("seen", "inspected", "outcomes seen", "yes", "already_seen", "already_inspected_validation_set", "inspected_validation_set", "tampered_with_outcomes", "peeked_at_test"):
            qc_exp = dict(qc)
            qc_exp["prior_outcome_exposure"] = exposed
            r_exp = analyze_experiment_outcome.analyze(qc_exp, base_ok)
            self.assertEqual(r_exp["status"], "blocked_harking", msg=f"failed to block {exposed!r}")
            self.assertTrue(r_exp["harking_detected"], msg=exposed)

        for safe_val in ("none", "unseen", "blinded", "no", "false", "not_inspected", "none_uninspected"):
            qc_safe = dict(qc)
            qc_safe["prior_outcome_exposure"] = safe_val
            r_safe = analyze_experiment_outcome.analyze(qc_safe, base_ok)
            self.assertEqual(r_safe["status"], "analyzed", msg=f"falsely blocked {safe_val!r}: {r_safe['errors']}")
            self.assertFalse(r_safe["harking_detected"], msg=safe_val)


if __name__ == "__main__":
    unittest.main()
