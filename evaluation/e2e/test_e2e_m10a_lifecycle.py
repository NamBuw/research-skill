"""Opaque-box E2E tests for Milestone M10A (project_state, build_research_inputs, analyze_experiment_outcome)."""
from __future__ import annotations

import json
from pathlib import Path

from helpers import (
    MockScholarlyServer,
    PdfFactory,
    REPO_ROOT,
    SCRIPTS_DIR,
    WorkspaceFactory,
    run_cli,
    sha256_file,
)

MAX_COMPACT_BYTES = 4096


def _valid_question_card(qid: str = "RQ-E2E-1") -> dict:
    return {
        "id": qid,
        "question": "Does adaptive temperature scaling reduce OOD calibration error without harming ID accuracy?",
        "question_type": "mechanistic",
        "target_scope": "Vision-language classifiers under domain shift",
        "unit_of_observation": "image-text pair",
        "unit_of_analysis": "dataset split",
        "construct_or_estimand": "Expected Calibration Error (ECE)",
        "measurement": "15-bin ECE and top-1 accuracy",
        "closest_work": "Static Temperature Scaling (Guo et al., 2017)",
        "prior_art_boundary": "Prior work fits a single global scalar temperature on ID validation.",
        "rival_explanation": "Gain arises solely from conservative logit clipping rather than shift-aware scaling.",
        "expected_if_focal": "ECE improves on OOD domain shift while accuracy remains within 0.5%.",
        "expected_if_rival": "Constant logit clipping matches adaptive scaling on OOD shift.",
        "discriminating_test": "Compare adaptive scaling vs constant clipping across domain_shift and length slices.",
        "falsifying_result": "OOD ECE worsens relative to static baseline under matched tuning.",
        "indeterminate_result": "95% confidence interval crosses zero across seeds and slices.",
        "pilot": "2-day pilot on corruption and domain shift.",
        "engineering_diagnosis": "Verified identical backbone, preprocessing, and seed parity.",
        "prior_outcome_exposure": "none_uninspected",
    }


def test_t1_m10a_cli_contracts_compact_and_zero_fabrication(tmp_path: Path) -> None:
    """T1-M10A: --help, --compact <4096B, and zero-fabrication scaffolds from real PDF."""
    for name in ("project_state.py", "build_research_inputs.py", "analyze_experiment_outcome.py"):
        h = run_cli(SCRIPTS_DIR / name, ["--help"])
        assert h.returncode == 0, f"{name} --help failed: {h.stderr}"

    pdf_path = tmp_path / "draft_paper.pdf"
    PdfFactory.make_clean_paper_pdf(
        pdf_path,
        title="Adaptive Density Calibration for Vision-Language Models",
        quote_p1="We propose density-gated calibration for OOD shift robustness.",
    )
    out_dir = tmp_path / "inputs"
    build_out = tmp_path / "build_manifest.json"
    b_res = run_cli(
        SCRIPTS_DIR / "build_research_inputs.py",
        [
            "--pdf", str(pdf_path),
            "--target-venue", "NeurIPS 2027",
            "--subfield-preset", "cv_multimodal",
            "--offline",
            "--out-dir", str(out_dir),
            "--out", str(build_out),
            "--compact",
        ],
    )
    assert b_res.returncode == 0, b_res.stderr + b_res.stdout
    assert len(b_res.stdout.encode("utf-8")) < MAX_COMPACT_BYTES
    assert b_res.json_out["compact"] is True
    assert Path(b_res.json_out["artifact_path"]).is_file()

    corpus = json.loads((out_dir / "corpus.json").read_text(encoding="utf-8"))
    assert corpus["target_manuscript"]["reading_basis"] == "full_text"
    assert corpus["subfield_preset"] == "cv_multimodal"
    for p in corpus["papers"]:
        assert p["reading_basis"] == "metadata_only"
        assert p["ratings"] is None

    dossier = json.loads((out_dir / "dossier.json").read_text(encoding="utf-8"))
    assert dossier["verification_summary"]["cfp_status"] == "unverified"
    assert all(f["amount"] is None and f["verification_status"] == "unverified" for f in dossier["fees"])

    # Verify scaffolded gap_record passes check_gap_record cleanly
    g_chk = run_cli(SCRIPTS_DIR / "check_gap_record.py", [str(out_dir / "gap_record.json")])
    assert g_chk.returncode == 0, g_chk.stdout + g_chk.stderr
    assert g_chk.json_out["valid_structure"] is True

    # Verify scaffolded scorecards fails closed cleanly as not_comparable (exit 1, NOT exit 2 crash)
    sc_chk = run_cli(SCRIPTS_DIR / "compare_scorecards.py", [str(out_dir / "scorecards.json"), "--compact"])
    assert sc_chk.returncode == 1, sc_chk.stderr
    assert sc_chk.json_out["status"] == "not_comparable"

    # project_state init + advise compact
    state_path = tmp_path / "project_state.json"
    ps_res = run_cli(
        SCRIPTS_DIR / "project_state.py",
        [
            "--state", str(state_path),
            "--init",
            "--project-id", "proj-e2e-1",
            "--target-venue", "NeurIPS 2027",
            "--advise",
            "--compact",
        ],
    )
    assert ps_res.returncode == 0, ps_res.stderr
    assert len(ps_res.stdout.encode("utf-8")) < MAX_COMPACT_BYTES
    assert ps_res.json_out["current_stage"] == "intake"
    assert Path(ps_res.json_out["artifact_path"]).is_file()


def test_t2_m10a_harking_block_stitching_reject_and_nan_exit_2(tmp_path: Path) -> None:
    """T2-M10A: Block HARKing, vague stitching, aggregate-only metrics, and NaN/empty-arg exit 2."""
    qc_path = tmp_path / "qc.json"
    qc_path.write_text(json.dumps(_valid_question_card()), encoding="utf-8")

    # 1. Aggregate-only (< 2 error slices) -> exit 1
    agg_path = tmp_path / "agg_outcomes.json"
    agg_path.write_text(
        json.dumps({
            "claim_mode": "confirmatory",
            "claimed_outcome": "supports_focal",
            "primary_metric": {"name": "ece", "direction": "lower", "baseline": 0.09, "candidate": 0.05},
            "error_slices": [{"slice_type": "ood_shift", "slice_name": "domain", "baseline": 0.1, "candidate": 0.06, "n": 200}],
        }),
        encoding="utf-8",
    )
    r_agg = run_cli(
        SCRIPTS_DIR / "analyze_experiment_outcome.py",
        ["--question-card", str(qc_path), "--outcomes", str(agg_path)],
    )
    assert r_agg.returncode == 1
    assert "insufficient_error_slices:need_at_least_2" in r_agg.json_out["errors"]

    # 2. Post-hoc HARKing -> blocked_harking, exit 1
    hark_path = tmp_path / "hark_outcomes.json"
    hark_path.write_text(
        json.dumps({
            "claim_mode": "confirmatory",
            "claimed_outcome": "supports_focal",
            "post_hoc_hypothesis_changed": True,
            "primary_metric": {"name": "accuracy", "direction": "higher", "baseline": 0.72, "candidate": 0.69},
            "error_slices": [
                {"slice_type": "length", "slice_name": "short", "baseline": 0.75, "candidate": 0.77, "n": 200},
                {"slice_type": "ood_shift", "slice_name": "ood", "baseline": 0.69, "candidate": 0.61, "n": 300},
            ],
        }),
        encoding="utf-8",
    )
    r_hark = run_cli(
        SCRIPTS_DIR / "analyze_experiment_outcome.py",
        ["--question-card", str(qc_path), "--outcomes", str(hark_path), "--compact"],
    )
    assert r_hark.returncode == 1
    assert len(r_hark.stdout.encode("utf-8")) < MAX_COMPACT_BYTES
    assert r_hark.json_out["status"] == "blocked_harking"
    assert r_hark.json_out["harking_detected"] is True

    # 3. Vague module stitching rejected by project_state.py -> exit 1
    state_path = tmp_path / "state.json"
    assert run_cli(SCRIPTS_DIR / "project_state.py", ["--state", str(state_path), "--init"]).returncode == 0
    bad_idea = tmp_path / "stitched_idea.json"
    bad_idea.write_text(
        json.dumps({
            "title": "Combine Transformer and Diffusion with plug-and-play fusion",
            "mechanism_decomposition": {
                "bottleneck_target": "TBD",
                "why_sota_fails": "none",
                "proposed_mechanism": "Combine module A + module B",
                "components": ["Transformer", "Diffusion"],
                "simplest_alternative": "TBD",
            },
        }),
        encoding="utf-8",
    )
    r_stitch = run_cli(
        SCRIPTS_DIR / "project_state.py",
        ["--state", str(state_path), "--evaluate-ideation", str(bad_idea)],
    )
    assert r_stitch.returncode == 1
    assert r_stitch.json_out["ideation_evaluation"]["mechanism_decomposition"]["is_vague_stitching"] is True

    # 4. NaN JSON and empty/whitespace args -> exit 2 + JSON error on stderr, no Traceback
    nan_file = tmp_path / "nan_outcomes.json"
    nan_file.write_text(
        '{"primary_metric": {"name": "acc", "direction": "higher", "baseline": NaN, "candidate": 0.8}, "error_slices": []}',
        encoding="utf-8",
    )
    r_nan = run_cli(
        SCRIPTS_DIR / "analyze_experiment_outcome.py",
        ["--question-card", str(qc_path), "--outcomes", str(nan_file)],
    )
    assert r_nan.returncode == 2
    assert "Traceback" not in r_nan.stderr
    assert "error" in json.loads(r_nan.stderr)

    for script_name, bad_args in (
        ("project_state.py", ["--state", "   ", "--audit"]),
        ("build_research_inputs.py", ["--topic", "", "--offline"]),
        ("analyze_experiment_outcome.py", ["--question-card", str(qc_path), "--outcomes", str(agg_path), "--out", "  "]),
    ):
        res_empty = run_cli(SCRIPTS_DIR / script_name, bad_args)
        assert res_empty.returncode == 2, f"{script_name} expected exit 2, got {res_empty.returncode}"
        assert "Traceback" not in res_empty.stderr
        assert "error" in json.loads(res_empty.stderr)


def test_t3_m10a_end_to_end_lineage_with_mock_server(
    mock_server: MockScholarlyServer, tmp_path: Path
) -> None:
    """T3-M10A: MockScholarlyServer scholarly/CFP routes -> build -> state -> manifest+outcome -> advisor pivot."""
    mock_server.add_json(
        "/works",
        {
            "meta": {"count": 2, "page": 1, "per_page": 10},
            "results": [
                {
                    "id": "https://openalex.org/W1001",
                    "doi": "https://doi.org/10.1000/calib.1",
                    "title": "On Calibration of Modern Neural Networks",
                    "publication_year": 2017,
                    "authorships": [{"author": {"display_name": "Chuan Guo"}}],
                    "abstract_inverted_index": {"Temperature": [0], "scaling": [1], "calibrates": [2], "logits.": [3]},
                    "primary_location": {"source": {"id": "https://openalex.org/S1", "display_name": "ICML", "type": "conference"}},
                },
                {
                    "id": "https://openalex.org/W1002",
                    "doi": "https://doi.org/10.1000/calib.2",
                    "title": "Can You Trust Your Model Uncertainty Under Dataset Shift?",
                    "publication_year": 2019,
                    "authorships": [{"author": {"display_name": "Yaniv Ovadia"}}],
                    "abstract_inverted_index": {"Calibration": [0], "degrades": [1], "under": [2], "dataset": [3], "shift.": [4]},
                    "primary_location": {"source": {"id": "https://openalex.org/S2", "display_name": "NeurIPS", "type": "conference"}},
                },
            ],
        },
        host="api.openalex.org",
    )
    mock_server.add_json(
        "/graph/v1/paper/search",
        {"total": 1, "data": [{"paperId": "s2-1", "title": "Density-Based Calibration", "year": 2023, "abstract": "Density shift study.", "authors": [{"name": "A. Author"}], "externalIds": {"DOI": "10.1000/s2.1"}}]},
        host="api.semanticscholar.org",
    )
    mock_server.add_route(
        "/Conferences/2027/CallForPapers",
        (
            200,
            "text/html; charset=utf-8",
            "<html><head><title>ICML 2027 CFP</title></head><body><h1>ICML 2027</h1><p>Full paper deadline: January 22, 2027 AOE</p></body></html>",
        ),
        host="icml.cc",
    )

    pdf_path = tmp_path / "target_draft.pdf"
    PdfFactory.make_clean_paper_pdf(
        pdf_path,
        title="Adaptive Density Calibration Under Shift",
        quote_p1="We propose density-aware logit scaling for OOD calibration.",
    )
    inputs_dir = tmp_path / "inputs"
    b_res = run_cli(
        SCRIPTS_DIR / "build_research_inputs.py",
        [
            "--pdf", str(pdf_path),
            "--target-venue", "ICML 2027",
            "--venue-edition", "2027",
            "--cfp-url", "https://icml.cc/Conferences/2027/CallForPapers",
            "--subfield-preset", "nlp_llm",
            "--sources", "openalex,s2",
            "--out-dir", str(inputs_dir),
            "--compact",
        ],
        env=mock_server.env(),
    )
    assert b_res.returncode == 0, b_res.stderr + b_res.stdout
    assert b_res.json_out["paper_count"] >= 3
    assert (inputs_dir / "venue_sources.json").is_file()

    # Initialize project_state and ingest corpus + idea bundle + question card + manifest
    state_path = tmp_path / "project_state.json"
    ap_path = tmp_path / "author_profile.json"
    ap_path.write_text(json.dumps({"strength_profile": "empirical_eval", "gpu_budget_hours": 100, "timeline_weeks": 8}), encoding="utf-8")
    assert run_cli(
        SCRIPTS_DIR / "project_state.py",
        [
            "--state", str(state_path),
            "--init",
            "--project-id", "proj-e2e-flow",
            "--target-venue", "ICML 2027",
            "--subfield-preset", "nlp_llm",
            "--author-profile", str(ap_path),
        ],
    ).returncode == 0

    assert run_cli(
        SCRIPTS_DIR / "project_state.py",
        ["--state", str(state_path), "--ingest-kind", "corpus", "--ingest-file", str(inputs_dir / "corpus.json")],
    ).returncode == 0

    digests_path = tmp_path / "full_text_digests.json"
    digests_path.write_text(
        json.dumps({
            "digests": [
                {
                    "source_id": "SRC-1",
                    "title": "On Calibration of Modern Neural Networks",
                    "access": "full_text",
                    "locator": "Section 3, p. 4",
                    "quote": "Temperature scaling uses a single scalar parameter on logits.",
                }
            ]
        }),
        encoding="utf-8",
    )
    assert run_cli(
        SCRIPTS_DIR / "project_state.py",
        ["--state", str(state_path), "--ingest-kind", "corpus_digests", "--ingest-file", str(digests_path)],
    ).returncode == 0

    idea_bundle_path = tmp_path / "idea_bundle.json"
    idea_bundle_path.write_text(
        json.dumps({
            "gap_id": "G1",
            "claim": "Static temperature scaling fails on OOD shifts.",
            "support_source_ids": ["SRC-1"],
            "root_cause_barrier": "measurement_gap",
            "why_now_enabler": "Open-weight embeddings provide density estimates cheaply.",
            "so_what_decision_impact": "decision_changing",
            "durability_12_24m": "durable_structural_limit",
            "candidate_ideas": [
                {
                    "id": "IDEA-1",
                    "angle": "high_novelty_mechanism",
                    "contribution_type": "method",
                    "title": "Density-gated logit scaling",
                    "bottleneck_target": "Global scalar temperature ignores sample density under OOD shift",
                    "why_sota_fails": "Uniform scaling causes overconfident predictions on unseen domains",
                    "proposed_mechanism": "Scale logits by normalized Mahalanobis feature density",
                    "components": ["density_gate"],
                    "simplest_alternative": "Global scalar temperature scaling tuned on ID validation",
                    "planned_contributions_count": 1,
                    "planned_datasets_count": 3,
                }
            ],
        }),
        encoding="utf-8",
    )
    assert run_cli(
        SCRIPTS_DIR / "project_state.py",
        ["--state", str(state_path), "--ingest-kind", "idea_seed_bundle", "--ingest-file", str(idea_bundle_path), "--evaluate-ideation", "IDEA-1"],
    ).returncode == 0

    qc_path = tmp_path / "question_card.json"
    qc_path.write_text(json.dumps(_valid_question_card("RQ-E2E-1")), encoding="utf-8")
    assert run_cli(SCRIPTS_DIR / "check_question_card.py", [str(qc_path)]).returncode == 0
    assert run_cli(
        SCRIPTS_DIR / "project_state.py",
        ["--state", str(state_path), "--ingest-kind", "question_card", "--ingest-file", str(qc_path), "--link-idea", "IDEA-1"],
    ).returncode == 0

    man_path = WorkspaceFactory.make_verified_experiment_workspace(tmp_path / "exp_ws")
    assert run_cli(SCRIPTS_DIR / "check_experiment_manifest.py", [str(man_path), "--verify-files"]).returncode == 0
    assert run_cli(
        SCRIPTS_DIR / "project_state.py",
        ["--state", str(state_path), "--ingest-kind", "experiment_manifest", "--ingest-file", str(man_path), "--link-rq", "RQ-E2E-1"],
    ).returncode == 0

    # Outcome analysis with OOD regression -> pivot + failure_cases export
    outcomes_path = tmp_path / "outcomes.json"
    outcomes_path.write_text(
        json.dumps({
            "claim_mode": "exploratory",
            "claimed_outcome": "mixed",
            "primary_metric": {"name": "accuracy", "direction": "higher", "baseline": 0.72, "candidate": 0.70},
            "error_slices": [
                {"slice_type": "length", "slice_name": "short_prompt", "baseline": 0.80, "candidate": 0.82, "n": 300},
                {"slice_type": "ood_shift", "slice_name": "domain_shift", "baseline": 0.64, "candidate": 0.58, "n": 300, "notes": "Regresses on unseen domain"},
            ],
            "engineering_diagnostics_verdict": "PASS",
            "target_venue": "ICML 2027",
            "target_venue_tier": "top_tier_flagship",
            "proposed_paper_score": 5.6,
        }),
        encoding="utf-8",
    )
    out_analysis_path = tmp_path / "outcome_analysis.json"
    fc_path = tmp_path / "failure_cases.json"
    a_res = run_cli(
        SCRIPTS_DIR / "analyze_experiment_outcome.py",
        [
            "--question-card", str(qc_path),
            "--outcomes", str(outcomes_path),
            "--manifest", str(man_path),
            "--verify-files",
            "--export-failure-cases", str(fc_path),
            "--out", str(out_analysis_path),
            "--compact",
        ],
    )
    assert a_res.returncode == 0, a_res.stderr + a_res.stdout
    assert len(a_res.stdout.encode("utf-8")) < MAX_COMPACT_BYTES
    assert "narrow_claim_scope" in a_res.json_out["pivot_actions"]
    assert "downgrade_venue_tier" in a_res.json_out["pivot_actions"]
    assert fc_path.is_file()

    # Ingest outcome & failure_cases back into project_state and query advisor
    assert run_cli(
        SCRIPTS_DIR / "project_state.py",
        ["--state", str(state_path), "--ingest-kind", "experiment_outcome", "--ingest-file", str(out_analysis_path), "--link-rq", "RQ-E2E-1"],
    ).returncode == 0
    final_adv = run_cli(
        SCRIPTS_DIR / "project_state.py",
        ["--state", str(state_path), "--audit", "--strict", "--advise", "--compact"],
    )
    assert final_adv.returncode == 0, final_adv.stderr + final_adv.stdout
    assert final_adv.json_out["current_stage"] == "manuscript_and_scoring"


def test_t4_m10a_iter2_gate_and_provenance_regressions(tmp_path: Path) -> None:
    """T4-M10A: E2E CLI regressions for BB-1..BB-11 (corpus results/blank-PDF, stitching, slices/HARKing, advisor blocking)."""
    # BB-10: build_research_inputs accepts search_papers.py {"results": [...]} schema
    results_json = tmp_path / "search_results.json"
    results_json.write_text(
        json.dumps({
            "schema": "research_scientist_search_v2",
            "results": [{"id": "R1", "title": "Search Result One", "abstract": "Concrete abstract."}],
        }),
        encoding="utf-8",
    )
    out_res_dir = tmp_path / "out_results"
    r_res = run_cli(
        SCRIPTS_DIR / "build_research_inputs.py",
        ["--topic", "calibration", "--corpus-json", str(results_json), "--offline", "--out-dir", str(out_res_dir), "--compact"],
    )
    assert r_res.returncode == 0, r_res.stderr
    assert r_res.json_out["paper_count"] == 1
    assert json.loads((out_res_dir / "corpus.json").read_text(encoding="utf-8"))["papers"][0]["reading_basis"] == "metadata_only"

    # BB-11: blank 0-block PDF downgrades to unavailable and omits E-TARGET full_text evidence
    import fitz
    blank_pdf = tmp_path / "blank_scanned_doc.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(blank_pdf))
    doc.close()
    out_blank_dir = tmp_path / "out_blank"
    r_blank = run_cli(
        SCRIPTS_DIR / "build_research_inputs.py",
        ["--pdf", str(blank_pdf), "--offline", "--out-dir", str(out_blank_dir), "--compact"],
    )
    assert r_blank.returncode == 0, r_blank.stderr
    assert r_blank.json_out["target_reading_basis"] == "unavailable"
    assert "pdf_zero_extracted_blocks:downgraded_to_unavailable" in r_blank.json_out["warnings"]
    gap_doc = json.loads((out_blank_dir / "gap_record.json").read_text(encoding="utf-8"))
    assert not any(ev.get("id") == "E-TARGET" for ev in gap_doc["evidence"])

    # BB-6: empty --target-venue and bogus --target-venue-tier exit 2 on init and update
    st_path = tmp_path / "state_bb.json"
    assert run_cli(SCRIPTS_DIR / "project_state.py", ["--state", str(st_path), "--init", "--target-venue", ""]).returncode == 2
    assert run_cli(SCRIPTS_DIR / "project_state.py", ["--state", str(st_path), "--init", "--target-venue", "NeurIPS 2027"]).returncode == 0
    assert run_cli(SCRIPTS_DIR / "project_state.py", ["--state", str(st_path), "--target-venue-tier", "bogus_invalid_tier"]).returncode == 2

    # BB-7, BB-8, BB-9: CLI analyze_experiment_outcome regressions
    qc_path = tmp_path / "qc_bb.json"
    qc_obj = _valid_question_card("RQ-BB")
    qc_path.write_text(json.dumps(qc_obj), encoding="utf-8")

    # BB-7: duplicate slices exit 1 gate_failed
    dup_path = tmp_path / "dup.json"
    dup_path.write_text(json.dumps({
        "claim_mode": "confirmatory",
        "claimed_outcome": "supports_focal",
        "primary_metric": {"name": "ece", "direction": "lower", "baseline": 0.1, "candidate": 0.06},
        "error_slices": [
            {"slice_type": "ood_shift", "slice_name": "domain_shift", "baseline": 0.1, "candidate": 0.06, "n": 500},
            {"slice_type": "ood_shift", "slice_name": "domain_shift", "baseline": 0.1, "candidate": 0.06, "n": 500},
        ],
    }), encoding="utf-8")
    r_dup = run_cli(SCRIPTS_DIR / "analyze_experiment_outcome.py", ["--question-card", str(qc_path), "--outcomes", str(dup_path)])
    assert r_dup.returncode == 1
    assert r_dup.json_out["status"] == "gate_failed"
    assert "duplicate_error_slices" in r_dup.json_out["errors"]

    # BB-8: cherry-picked slice HARKing even when primary_delta > 0
    cherry_path = tmp_path / "cherry.json"
    cherry_path.write_text(json.dumps({
        "claim_mode": "confirmatory",
        "claimed_outcome": "supports_focal",
        "claimed_hypothesis": "Adaptive temperature scaling improves short_context calibration error",
        "primary_metric": {"name": "ece", "direction": "lower", "baseline": 0.10, "candidate": 0.09, "ci95": [0.001, 0.02]},
        "error_slices": [
            {"slice_type": "length", "slice_name": "short_context", "baseline": 0.10, "candidate": 0.05, "n": 900},
            {"slice_type": "ood_shift", "slice_name": "domain_shift", "baseline": 0.10, "candidate": 0.14, "n": 100},
        ],
    }), encoding="utf-8")
    r_cherry = run_cli(SCRIPTS_DIR / "analyze_experiment_outcome.py", ["--question-card", str(qc_path), "--outcomes", str(cherry_path)])
    assert r_cherry.returncode == 1
    assert r_cherry.json_out["status"] == "blocked_harking"

    # BB-9: canonical exposed prior_outcome_exposure blocks confirmatory
    qc_seen_path = tmp_path / "qc_seen.json"
    qc_seen = dict(qc_obj)
    qc_seen["prior_outcome_exposure"] = "outcomes seen"
    qc_seen_path.write_text(json.dumps(qc_seen), encoding="utf-8")
    ok_path = tmp_path / "ok.json"
    ok_path.write_text(json.dumps({
        "claim_mode": "confirmatory",
        "claimed_outcome": "supports_focal",
        "claimed_hypothesis": "Adaptive temperature scaling improves OOD domain shift calibration error.",
        "primary_metric": {"name": "ece", "direction": "lower", "baseline": 0.10, "candidate": 0.06, "ci95": [0.02, 0.06]},
        "error_slices": [
            {"slice_type": "ood_shift", "slice_name": "domain_shift", "baseline": 0.10, "candidate": 0.06, "n": 300},
            {"slice_type": "length", "slice_name": "long_context", "baseline": 0.09, "candidate": 0.05, "n": 300},
        ],
    }), encoding="utf-8")
    r_seen = run_cli(SCRIPTS_DIR / "analyze_experiment_outcome.py", ["--question-card", str(qc_seen_path), "--outcomes", str(ok_path)])
    assert r_seen.returncode == 1
    assert r_seen.json_out["status"] == "blocked_harking"


def test_t5_m10a_claim_audit_and_skill_budgets() -> None:
    """T5-M10A: claim_audit --suite-root . passes with 0 findings and all 7 SKILL.md stay <50L/<900tok."""
    res = run_cli(SCRIPTS_DIR / "claim_audit.py", ["--suite-root", str(REPO_ROOT), "--json", "--compact"])
    assert res.returncode == 0, res.stderr + res.stdout
    assert res.json_out["status"] == "passed"
    assert res.json_out["finding_count"] == 0
    for sk in res.json_out["skills_audited"]:
        fp = sk["footprint"]
        assert fp["lines"] < 50, f"{sk['name']} SKILL.md exceeded 50 lines: {fp['lines']}"
        assert fp["est_tokens"] < 900, f"{sk['name']} SKILL.md exceeded 900 tokens: {fp['est_tokens']}"
        assert fp["frontmatter_est_tokens"] < 140, f"{sk['name']} frontmatter exceeded 140 tokens"


def test_t6_m10a_iter3_cross_tool_scorecards_ledger_and_advisor_regressions(tmp_path: Path) -> None:
    """T6-M10A: Opaque-box E2E regressions for BB-12, BB-13, BB-14 via real compare_scorecards.py & check_manuscript_ledger.py."""
    state_path = tmp_path / "project_state.json"
    ap_path = tmp_path / "author_profile.json"
    ap_path.write_text(json.dumps({"strength_profile": "empirical_eval", "gpu_budget_hours": 100, "timeline_weeks": 8}), encoding="utf-8")
    assert run_cli(
        SCRIPTS_DIR / "project_state.py",
        ["--state", str(state_path), "--init", "--project-id", "proj-e2e-iter3", "--target-venue", "NeurIPS 2027", "--author-profile", str(ap_path)],
    ).returncode == 0

    digests_path = tmp_path / "digests.json"
    digests_path.write_text(
        json.dumps({"digests": [{"source_id": "SRC-1", "access": "full_text", "locator": "Sec 2, p. 3", "quote": "Verified quote."}]}),
        encoding="utf-8",
    )
    assert run_cli(SCRIPTS_DIR / "project_state.py", ["--state", str(state_path), "--ingest-kind", "corpus_digests", "--ingest-file", str(digests_path)]).returncode == 0

    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(
        json.dumps({
            "gap_id": "G1",
            "claim": "Static scaling degrades under domain shift.",
            "support_source_ids": ["SRC-1"],
            "candidate_ideas": [{
                "id": "IDEA-1",
                "title": "Density gate",
                "bottleneck_target": "Global scalar temperature ignores sample density",
                "why_sota_fails": "Uniform scaling overconfident on OOD",
                "proposed_mechanism": "Scale logits by normalized density",
                "components": ["density_gate"],
                "simplest_alternative": "Global scalar temperature scaling baseline",
                "planned_contributions_count": 1,
                "planned_datasets_count": 2,
            }],
        }),
        encoding="utf-8",
    )
    assert run_cli(SCRIPTS_DIR / "project_state.py", ["--state", str(state_path), "--ingest-kind", "idea_seed_bundle", "--ingest-file", str(bundle_path)]).returncode == 0

    qc_path = tmp_path / "qc.json"
    qc_path.write_text(json.dumps(_valid_question_card("RQ-1")), encoding="utf-8")
    assert run_cli(SCRIPTS_DIR / "project_state.py", ["--state", str(state_path), "--ingest-kind", "question_card", "--ingest-file", str(qc_path), "--link-idea", "IDEA-1"]).returncode == 0

    man_path = WorkspaceFactory.make_verified_experiment_workspace(tmp_path / "exp_ws")
    assert run_cli(SCRIPTS_DIR / "project_state.py", ["--state", str(state_path), "--ingest-kind", "experiment_manifest", "--ingest-file", str(man_path), "--link-rq", "RQ-1"]).returncode == 0
    out_ok = tmp_path / "out_ok.json"
    out_ok.write_text(json.dumps({"status": "analyzed", "outcome_classification": "focal_supported", "question_id": "RQ-1"}), encoding="utf-8")
    assert run_cli(SCRIPTS_DIR / "project_state.py", ["--state", str(state_path), "--ingest-kind", "experiment_outcome", "--ingest-file", str(out_ok), "--link-rq", "RQ-1"]).returncode == 0

    # Real compare_scorecards.py --target-id target_paper where baseline_1 passes (7s) and target_paper triggers fatal gate (novelty=2)
    dims = ("importance", "novelty", "soundness", "evidence", "transparency", "clarity")
    locators = {d: ["Section 1, p. 1"] for d in dims}
    weights_100 = {"importance": 20, "novelty": 20, "soundness": 20, "evidence": 20, "transparency": 10, "clarity": 10}
    sc_input = tmp_path / "scorecards_input.json"
    sc_input.write_text(
        json.dumps({
            "weight_scenarios": [weights_100],
            "profiles": [
                {"id": "baseline_1", "reading_basis": "full_text", "closest_work": ["target_paper"], "ratings": {d: 7 for d in dims}, "evidence_locators": locators},
                {"id": "target_paper", "reading_basis": "full_text", "closest_work": ["baseline_1"], "ratings": {"importance": 7, "novelty": 2, "soundness": 7, "evidence": 7, "transparency": 7, "clarity": 7}, "evidence_locators": locators},
            ],
        }),
        encoding="utf-8",
    )
    sc_out = tmp_path / "scorecards_out.json"
    sc_cli = run_cli(SCRIPTS_DIR / "compare_scorecards.py", [str(sc_input), "--target-id", "target_paper", "--out", str(sc_out)])
    assert sc_cli.returncode == 0, sc_cli.stderr
    assert sc_cli.json_out["related_work_comparison"]["target_id"] == "target_paper"

    # Passing ledger + passing venue_novelty so ONLY target_paper's fatal gate should block readiness (BB-12)
    good_ledger = tmp_path / "good_ledger.json"
    good_ledger.write_text(
        json.dumps({
            "passed": True,
            "claims": [{"id": "C1", "kind": "reported", "material": True, "rq_id": "RQ-1", "run_ids": ["cand-1"], "source_ids": ["SRC-1"]}],
        }),
        encoding="utf-8",
    )
    assert run_cli(SCRIPTS_DIR / "project_state.py", ["--state", str(state_path), "--ingest-kind", "manuscript_ledger", "--ingest-file", str(good_ledger)]).returncode == 0
    assert run_cli(SCRIPTS_DIR / "project_state.py", ["--state", str(state_path), "--ingest-kind", "scorecards", "--ingest-file", str(sc_out), "--link-claim", "C1"]).returncode == 0

    vv_path = tmp_path / "venue.json"
    vv_path.write_text(json.dumps({"venue": {"name": "NeurIPS 2027"}, "submission_readiness": {"venue_tier": "top_tier_flagship", "verdict": "competitive_top_tier_main_track", "ready_to_submit": True}}), encoding="utf-8")
    assert run_cli(SCRIPTS_DIR / "project_state.py", ["--state", str(state_path), "--ingest-kind", "venue_novelty", "--ingest-file", str(vv_path)]).returncode == 0

    adv_bb12 = run_cli(SCRIPTS_DIR / "project_state.py", ["--state", str(state_path), "--audit", "--strict", "--advise"])
    assert adv_bb12.returncode == 1
    assert adv_bb12.json_out["audit"]["status"] == "issues_detected"
    assert "scorecard_fatal_gate_triggered:SC-1" in adv_bb12.json_out["audit"]["errors"]
    assert adv_bb12.json_out["current_stage"] == "manuscript_and_scoring"

    # Replace scorecard with passing target_paper (novelty=7) -> now verify BB-13 Part A with real check_manuscript_ledger.py failure
    sc_input_pass = tmp_path / "scorecards_pass.json"
    sc_input_pass.write_text(
        json.dumps({
            "weight_scenarios": [weights_100],
            "profiles": [
                {"id": "baseline_1", "reading_basis": "full_text", "closest_work": ["target_paper"], "ratings": {d: 7 for d in dims}, "evidence_locators": locators},
                {"id": "target_paper", "reading_basis": "full_text", "closest_work": ["baseline_1"], "ratings": {d: 7 for d in dims}, "evidence_locators": locators},
            ],
        }),
        encoding="utf-8",
    )
    sc_out_pass = tmp_path / "scorecards_pass_out.json"
    assert run_cli(SCRIPTS_DIR / "compare_scorecards.py", [str(sc_input_pass), "--target-id", "target_paper", "--out", str(sc_out_pass)]).returncode == 0
    assert run_cli(SCRIPTS_DIR / "project_state.py", ["--state", str(state_path), "--ingest-kind", "scorecards", "--ingest-file", str(sc_out_pass), "--link-scorecard", "SC-1", "--link-claim", "C1"]).returncode == 0

    bad_ledger_path = tmp_path / "bad_ledger.json"
    bad_ledger_path.write_text(
        json.dumps({
            "sources": [{"id": "SRC-1", "type": "paper", "locator": "Sec 2, p. 3", "verified": True, "verified_by": "author", "verified_at": "2026-11-21"}],
            "claims": [{"id": "C1", "kind": "reported", "material": True, "rq_id": "RQ-1", "run_ids": ["cand-1"], "source_ids": []}],
            "methods": [],
            "numeric_facts": [{"id": "NF-1", "occurrences": []}],
        }),
        encoding="utf-8",
    )
    paper_md = tmp_path / "paper.md"
    paper_md.write_text("We achieve 99.9% accuracy on ImageNet.\n", encoding="utf-8")
    ledger_audit_path = tmp_path / "ledger_audit.json"
    cml_res = run_cli(
        SCRIPTS_DIR / "check_manuscript_ledger.py",
        ["--ledger", str(bad_ledger_path), "--manuscript", str(paper_md), "--out", str(ledger_audit_path)],
    )
    assert cml_res.returncode == 1
    assert cml_res.json_out["status"] == "structural_issues"

    assert run_cli(SCRIPTS_DIR / "project_state.py", ["--state", str(state_path), "--ingest-kind", "manuscript_ledger", "--ingest-file", str(ledger_audit_path)]).returncode == 0
    adv_bb13 = run_cli(SCRIPTS_DIR / "project_state.py", ["--state", str(state_path), "--audit", "--strict", "--advise"])
    assert adv_bb13.returncode == 1
    assert adv_bb13.json_out["audit"]["status"] == "issues_detected"
    assert "manuscript_ledger_failed" in adv_bb13.json_out["audit"]["errors"]
    assert adv_bb13.json_out["current_stage"] == "manuscript_and_scoring"

    # Fix manuscript_ledger to passing -> verify BB-13 Part B + BB-14 (sources verified=True without quote/digest blocks full_text & blocks ready_for_reporting)
    fake_ml_ledger = tmp_path / "fake_ml_ledger.json"
    fake_ml_ledger.write_text(
        json.dumps({
            "status": "structure_passed",
            "issues": [],
            "sources": [{"id": "FAKE-ML-1", "verified": True, "locator": "Section 1"}],
        }),
        encoding="utf-8",
    )
    ing_ml = run_cli(SCRIPTS_DIR / "project_state.py", ["--state", str(state_path), "--ingest-kind", "manuscript_ledger", "--ingest-file", str(fake_ml_ledger)])
    assert ing_ml.returncode == 0
    assert any("silent_full_text_upgrade_blocked:FAKE-ML-1" in w for w in ing_ml.json_out["ingest"]["warnings"])
    state_obj = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_obj["corpus_digests"]["FAKE-ML-1"]["access"] == "metadata_only"
    assert state_obj["corpus_digests"]["FAKE-ML-1"]["digest"] is None

    adv_bb14 = run_cli(SCRIPTS_DIR / "project_state.py", ["--state", str(state_path), "--audit", "--strict", "--advise"])
    assert adv_bb14.returncode == 1
    assert adv_bb14.json_out["audit"]["status"] == "issues_detected"
    assert "silent_full_text_upgrade_blocked:FAKE-ML-1" in adv_bb14.json_out["audit"]["errors"]
    assert adv_bb14.json_out["current_stage"] == "gap_discovery"
    assert "silent_full_text_upgrade_blocked:FAKE-ML-1" in adv_bb14.json_out["blocking_issues"]


def test_t7_m10a_iter4_gap_pipeline_seed_bundle_and_rebuttal_cli(tmp_path: Path) -> None:
    """T7-M10A: Opaque-box CLI E2E for BB-15 (gap_pipeline --seed-bundle-out -> project_state) & BB-16 (check_rebuttal.py)."""
    import shlex
    import subprocess
    import sys

    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(
        json.dumps({
            "papers": [
                {"id": "P1", "family": "same_problem", "year": 2021, "title": "Static Rank Fusion", "retraction_status": "clean", "limitations": ["Uncalibrated under domain shift"]},
                {"id": "P2", "family": "cross_setting_analogy", "year": 2024, "title": "Transportability Under Shift", "retraction_status": "clean", "limitations": ["No rank aggregation guarantees"]},
            ]
        }),
        encoding="utf-8",
    )
    digests_cli_path = tmp_path / "digests_cli.json"
    digests_cli_path.write_text(
        json.dumps({
            "P1": {"access": "full_text", "digest": "RRF uses fixed constant k=60."},
            "P2": {"access": "full_text", "digest": "Importance weighting degrades on OOD shift."},
        }),
        encoding="utf-8",
    )
    cands_path = tmp_path / "candidates.json"
    cands_path.write_text(
        json.dumps({
            "candidates": [
                {
                    "id": "G1",
                    "claim": "Calibrated rank fusion under OOD shift remains uncharacterized.",
                    "cited_ids": ["P1", "P2"],
                    "support_ids": ["P1", "P2"],
                    "closest_work_ids": ["P1", "P2"],
                    "sgha_critics_passed": True,
                    "engineering_checked": True,
                    "why_now_enabler": "Open-weight dense retrievers expose calibrated logit margins across shifts.",
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
            ]
        }),
        encoding="utf-8",
    )

    seed_bundle_path = tmp_path / "seed_bundle.json"
    gp_out_path = tmp_path / "gp_out.json"
    gp_cli = run_cli(
        SCRIPTS_DIR / "gap_pipeline.py",
        [
            "--topic", "rank fusion",
            "--corpus", str(corpus_path),
            "--digests", str(digests_cli_path),
            "--candidates", str(cands_path),
            "--require-idea-portfolio",
            "--require-pre-mortem",
            "--seed-bundle-out", str(seed_bundle_path),
            "--out", str(gp_out_path),
            "--compact",
        ],
    )
    assert gp_cli.returncode == 0, gp_cli.stderr + gp_cli.stdout
    assert seed_bundle_path.is_file()

    # 1. Fresh state without verified locators ingests G1/ideas/trajectory_tree and fails closed on --audit --strict
    st_unverified = tmp_path / "state_unverified.json"
    assert run_cli(
        SCRIPTS_DIR / "project_state.py",
        ["--state", str(st_unverified), "--init", "--project-id", "e2e-bb15-fail", "--target-venue", "NeurIPS 2027"],
    ).returncode == 0
    ing_bundle = run_cli(
        SCRIPTS_DIR / "project_state.py",
        ["--state", str(st_unverified), "--ingest-kind", "idea_seed_bundle", "--ingest-file", str(seed_bundle_path)],
    )
    assert ing_bundle.returncode == 0, ing_bundle.stderr
    st_u_obj = json.loads(st_unverified.read_text(encoding="utf-8"))
    assert "G1" in st_u_obj["gaps"]
    assert "G-BUNDLE-1" not in st_u_obj["gaps"]
    assert set(st_u_obj["ideas"].keys()) == {"I1", "I2", "I3"}
    assert isinstance(st_u_obj["trajectory_tree"], dict)
    assert st_u_obj["trajectory_tree"]["generations"]
    aud_fail = run_cli(SCRIPTS_DIR / "project_state.py", ["--state", str(st_unverified), "--audit", "--strict"])
    assert aud_fail.returncode == 1
    assert any("unread_or_metadata_only_source:gap:G1:" in e for e in aud_fail.json_out["audit"]["errors"])

    # 2. Pre-registered verified corpus_digests + gap_pipeline ingestion passes strict audit cleanly
    st_ok = tmp_path / "state_ok.json"
    ap_path = tmp_path / "ap.json"
    ap_path.write_text(json.dumps({"strength_profile": "empirical_eval", "gpu_budget_hours": 100, "timeline_weeks": 8}), encoding="utf-8")
    assert run_cli(
        SCRIPTS_DIR / "project_state.py",
        ["--state", str(st_ok), "--init", "--project-id", "e2e-bb15-ok", "--target-venue", "NeurIPS 2027", "--author-profile", str(ap_path)],
    ).returncode == 0
    verified_digests = tmp_path / "verified_digests.json"
    verified_digests.write_text(
        json.dumps({
            "digests": [
                {"source_id": "P1", "access": "full_text", "locator": "Sec 2, p. 3", "quote": "RRF uses fixed constant k=60."},
                {"source_id": "P2", "access": "full_text", "locator": "Sec 4, p. 7", "quote": "Importance weighting degrades on OOD shift."},
            ]
        }),
        encoding="utf-8",
    )
    assert run_cli(
        SCRIPTS_DIR / "project_state.py",
        ["--state", str(st_ok), "--ingest-kind", "corpus_digests", "--ingest-file", str(verified_digests)],
    ).returncode == 0
    ing_gp = run_cli(
        SCRIPTS_DIR / "project_state.py",
        ["--state", str(st_ok), "--ingest-kind", "gap_pipeline", "--ingest-file", str(gp_out_path)],
    )
    assert ing_gp.returncode == 0, ing_gp.stderr
    assert ing_gp.json_out["ingest"]["warnings"] == []
    aud_ok = run_cli(SCRIPTS_DIR / "project_state.py", ["--state", str(st_ok), "--audit", "--strict"])
    assert aud_ok.returncode == 0, aud_ok.stdout

    # 3. BB-16: Verify advisor's recommended check_rebuttal.py command executes cleanly (no argparse exit 2)
    reb_state_path = tmp_path / "state_reb.json"
    reb_state = json.loads(st_ok.read_text(encoding="utf-8"))
    for iid in list(reb_state["ideas"].keys()):
        reb_state["ideas"][iid]["mechanism_decomposition"] = {
            "bottleneck_target": "Static fusion ignores OOD logit variance",
            "why_sota_fails": "Uniform rank weighting amplifies noisy retrievers",
            "proposed_mechanism": "Calibrate per-retriever rank weights via transportability",
            "components": ["rank_calibrator"],
            "simplest_alternative": "Global scalar temperature scaling on fused scores",
        }
    reb_state["rqs"] = {"RQ-1": {"id": "RQ-1", "idea_id": "I1", "gap_id": "G1", "valid_structure": True}}
    reb_state["experiments"] = {
        "RUN-1": {
            "run_id": "RUN-1", "rq_id": "RQ-1",
            "result_artifact_sha256": "a" * 64, "split_manifest_sha256": "b" * 64, "metric_script_sha256": "c" * 64,
            "engineering_verdict": "PASS", "outcome_status": "analyzed",
        }
    }
    reb_state["manuscript_claims"] = {
        "C1": {"id": "C1", "rq_id": "RQ-1", "kind": "reported", "material": True, "run_ids": ["RUN-1"], "source_ids": ["P1"], "ledger_verified": True, "ledger_passed": True}
    }
    reb_state["scorecards"] = {"SC-1": {"id": "SC-1", "fatal_gate_triggered": False, "status": "structurally_comparable"}}
    reb_state["venue_verdicts"] = {"VV-1": {"id": "VV-1", "ready_to_submit": True, "venue_verdict": "competitive_top_tier_main_track"}}
    reb_state["rebuttal_points"] = {"R1.1": {"point_id": "R1.1", "claim_ids": ["C1"], "run_ids": ["RUN-1"], "anchor": "Table 1", "status": "pending"}}
    reb_state_path.write_text(json.dumps(reb_state, indent=2), encoding="utf-8")

    adv_reb = run_cli(SCRIPTS_DIR / "project_state.py", ["--state", str(reb_state_path), "--advise", "--compact"])
    assert adv_reb.returncode == 0, adv_reb.stderr
    assert adv_reb.json_out["current_stage"] == "rebuttal"
    rec_cmd = adv_reb.json_out["recommended_commands"][0]
    tokens = shlex.split(rec_cmd)
    assert Path(tokens[1]).name == "check_rebuttal.py"
    assert "coverage" in tokens and "--manuscript" not in tokens

    reb_dir = tmp_path / "reb_ws"
    reb_dir.mkdir()
    (reb_dir / "triage_points.md").write_text("- [R1.1] Address OOD rank calibration\n", encoding="utf-8")
    (reb_dir / "rebuttal.md").write_text("## R1.1\nSee Table 1 in Section 4 for OOD ECE results.\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "check_rebuttal.py"), *tokens[2:]],
        cwd=str(reb_dir), capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, f"{rec_cmd} failed: {proc.stdout}\n{proc.stderr}"
    assert json.loads(proc.stdout)["verdict"] == "PASS"
