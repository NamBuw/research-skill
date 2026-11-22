#!/usr/bin/env python3
"""Connected cross-tool submission evaluation, gating, desk-reject, and portfolio auto-retargeting pipeline."""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import tempfile
from decimal import BasicContext, Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from score_math import (  # noqa: E402
    DEFAULT_IDEA_WEIGHTS,
    DIAGNOSTIC_SECTIONS,
    DIMENSIONS,
    FATAL_THRESHOLDS,
    IDEA_DIMENSIONS,
    IDEA_FATAL_THRESHOLDS,
    IDEA_MERIT_DIMENSIONS,
    IDEA_PACKAGING_DIMENSIONS,
    TOP_TIER_COMPETITIVE_THRESHOLD,
    VENUE_TIER_FLOORS,
    VENUE_TIER_ORDER,
    VENUE_TYPE_PROFILES,
    evaluate_venue_tier_fit,
    resolve_venue_tier,
    resolve_venue_type,
    score as score_math_score,
)
from venue_leads import load_venue_quality_refs, lookup_venue_quality  # noqa: E402

SCHEMA_VERSION = "research_scientist_submission_evaluation_v1"
MAX_COMPACT_BYTES = 3950
DEFAULT_WEIGHTS = {
    "importance": 15,
    "novelty": 20,
    "soundness": 20,
    "evidence": 20,
    "transparency": 15,
    "clarity": 10,
}

SUBFIELD_PRESETS: dict[str, dict[str, Any]] = {
    "nlp_llm": {
        "label": "NLP / LLMs",
        "required_checks": [
            "contamination_check",
            "multi_prompt_variance",
            "compute_matched_open_weight_baseline",
            "eval_harness_parity",
        ],
        "critical_rigor_focus": [
            "nlp_benchmark_contamination",
            "nlp_eval_on_train_split",
            "nlp_prompt_template_sensitivity_missing",
            "hpo_budget_asymmetry",
        ],
    },
    "cv_multimodal": {
        "label": "Computer Vision / Multimodal",
        "required_checks": [
            "backbone_resolution_augmentation_parity",
            "flops_fps_memory_tradeoff",
            "qualitative_failure_analysis",
        ],
        "critical_rigor_focus": [
            "budget_or_config_mismatch",
            "hpo_budget_asymmetry",
            "missing_baseline",
        ],
    },
    "ml_theory": {
        "label": "ML Theory / Optimization",
        "required_checks": [
            "assumption_tightness_realism",
            "lower_vs_upper_bound_gap",
            "empirical_sanity_validation",
        ],
        "critical_rigor_focus": [
            "missing_sanity_control",
            "failed_sanity_control",
        ],
    },
    "ai_systems": {
        "label": "AI Systems / Efficiency",
        "required_checks": [
            "end_to_end_vs_microbenchmark",
            "tail_latency_p99",
            "peak_vram_comm_overhead",
            "matched_hardware",
        ],
        "critical_rigor_focus": [
            "budget_or_config_mismatch",
            "missing_baseline",
            "excluded_failed_runs",
        ],
    },
    "speech_audio": {
        "label": "Speech & Audio (STT/ASR, TTS, Speech-to-Vector)",
        "required_checks": [
            "speaker_session_disjoint_split",
            "audio_metric_and_normalization_parity",
            "decoding_vocoder_embedding_parity",
            "speech_slice_significance_and_consent",
        ],
        "critical_rigor_focus": [
            "group_leakage_across_splits",
            "split_overlap_leakage",
            "budget_or_config_mismatch",
            "metric_direction_mismatch",
            "hpo_budget_asymmetry",
        ],
    },
}

CRITICAL_ENGINEERING_CATEGORIES = {
    "missing_baseline",
    "missing_sanity_control",
    "failed_sanity_control",
    "preprocessing_before_split_leakage",
    "split_overlap_leakage",
    "test_set_tuning_leakage",
    "nlp_benchmark_contamination",
    "nlp_eval_on_train_split",
    "seed_count_mismatch",
    "single_seed_cherry_picking",
    "group_leakage_across_splits",
    "duplicate_sample_ids",
    "metric_direction_mismatch",
    "metric_averaging_mismatch",
    "excluded_failed_runs",
    "pytorch_train_mode_in_eval",
    "pytorch_missing_eval_or_no_grad",
    "hpo_budget_asymmetry",
    "budget_or_config_mismatch",
    "python_syntax_error",
}

LEDGER_EVIDENCE_ISSUE_PREFIXES = (
    "material_claim_without_source",
    "material_claim_without_verified_locator",
    "material_claim_marked_unknown",
    "unknown_source",
    "unknown_evidence",
    "source_unverified_against_sources_dir",
    "source_locator_file_missing",
    "source_quote_not_found",
    "source_quote_page_mismatch",
    "manuscript_numeric_fact_missing",
    "undeclared_manuscript_numeric_claim",
    "manuscript_claim_not_found",
    "orphan_contribution_without_evidence",
    "unknown_contribution_evidence",
    "contribution_evidence_unverified",
    "contribution_anchor_missing_in_manuscript",
    "unmapped_manuscript_contribution",
    "missing_contributions_map",
    "claim_scope_overclaim",
    "claim_scope_dataset_count_mismatch",
    "missing_scope_limitations",
    "missing_closest_work_in_manuscript",
    "uncited_closest_work",
    "related_work_lacks_differentiation",
    "related_work_panel_incomplete",
)

LEDGER_GRANDIOSE_PREFIXES = (
    "grandiose_branding_detected",
    "inflated_method_name",
    "reused_method_claimed_as_new",
    "unsupported_method_novelty",
    "unsupported_newly_derived_method",
    "unsupported_novelty_overclaim",
    "problem_inflation_detected",
    "overcomplicated_method",
    "missing_simplest_alternative",
    "missing_component_ablation",
)

PLAN_BAD_BACKWARD_STATUSES = {
    "start_already_passed_under_serial_assumption",
    "cfp_source_unverified_or_year_mismatch",
    "deadline_unknown",
}

PLAN_DISQUALIFYING_WARNING_PREFIXES = (
    "cfp_source_",
    "fee_source_",
    "abstract_registration_deadline_already_passed",
    "full_paper_deadline_already_passed",
    "abstract_deadline_after_full_paper",
    "cfp_checked_at_in_future",
    "cfp_source_recheck_needed",
    "budget_currency_unverified_or_mismatched",
    "full_paper_unknown",
    "presentation_mode_unverified",
)

DISQUALIFIED_NOVELTY_CLASSIFICATIONS = {
    "disqualified",
    "withheld_unverified",
    "hold_for_rework",
    "rejected_below_venue_tier",
    "conflicted_fallback",
}

DISQUALIFYING_SINGLE_VERDICTS = {
    "not_ready_invalid_evidence",
    "not_ready_fatal_gate",
    "do_not_submit_constraint_failed",
    "blocked_unverified_fit_or_constraints",
    "rejected_below_venue_tier",
    "provisional_panel_withheld",
    "not_ready_weak_venue_fit",
    "below_panel_median_strengthen_or_retarget",
}

CLASSIFICATION_PRIORITY = {
    "recommended_now": 0,
    "viable_fallback": 1,
    "stretch_high_risk": 2,
    "hold_for_rework": 3,
    "rejected_below_venue_tier": 4,
    "conflicted_fallback": 5,
    "withheld_unverified": 6,
    "disqualified": 7,
}

M9A_OPTIONAL_KEYS = (
    "native_scales",
    "native_scale",
    "native_venue_scales",
    "venue_profile",
    "venue_type",
    "venue_type_profile",
    "reviewer_synthesis",
    "reviewer_panel_analysis",
    "reviewer_panel_summary",
    "ac_synthesis",
    "what_if_roi",
    "scientific_merit_score",
    "publishability_packaging_score",
    "merit_vs_packaging",
    "section_diagnostics",
    "worst_case_sensitivity",
    "deal_breaker_sensitivity",
    "sanity_warnings",
    "sanity_warnings_list",
    "subfield_preset",
    "subfield_readiness",
    "evidence_anchor_table",
    "pareto_frontier",
    "linkage_summary",
    "idea_viability_band",
    "idea_readiness",
)


def _reject_nonfinite(token: str) -> None:
    raise ValueError(f"Non-finite JSON constant not allowed: {token}")


def _validate_finite_tree(obj: Any, path: str = "$") -> None:
    if isinstance(obj, float):
        if not math.isfinite(obj):
            raise ValueError(f"Non-finite float at {path}")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _validate_finite_tree(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            _validate_finite_tree(item, f"{path}[{idx}]")


def _require_nonempty_path(val: Any, flag_name: str) -> Path:
    if not isinstance(val, str) or not val.strip():
        raise ValueError(f"Empty or invalid path for {flag_name}")
    return Path(val.strip())


def _require_nonempty_str(val: Any, flag_name: str) -> str:
    if not isinstance(val, str) or not val.strip():
        raise ValueError(f"Empty or invalid value for {flag_name}")
    return val.strip()


def _load_json_file(
    path: Path,
    label: str,
    *,
    expect_dict: bool = True,
    resolve_compact_artifact: bool = False,
) -> Any:
    if not path.exists() or not path.is_file():
        raise ValueError(f"{label} file not found: {path}")
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw, parse_constant=_reject_nonfinite)
    _validate_finite_tree(data, label)
    if expect_dict and not isinstance(data, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    if (
        resolve_compact_artifact
        and isinstance(data, dict)
        and (data.get("compact") is True or "report_path" in data)
    ):
        for ref_key in ("artifact_path", "report_path", "out"):
            raw_ref = data.get(ref_key)
            if not isinstance(raw_ref, str):
                continue
            ref_s = raw_ref.strip()
            if not ref_s or ref_s.startswith("..."):
                continue
            cand = Path(ref_s)
            if not cand.is_absolute() and (path.parent / cand).is_file():
                cand = path.parent / cand
            try:
                if cand.exists() and cand.is_file() and cand.resolve() != path.resolve():
                    full_raw = cand.read_text(encoding="utf-8")
                    full_data = json.loads(full_raw, parse_constant=_reject_nonfinite)
                    _validate_finite_tree(full_data, f"{label}.{ref_key}")
                    if isinstance(full_data, dict):
                        return full_data
            except OSError:
                continue
    return data


def _resolve_manifest_ref(raw_val: str, flag_name: str, manifest_dir: Path | None) -> Path:
    candidate = _require_nonempty_path(raw_val, flag_name)
    if not candidate.is_absolute() and manifest_dir is not None:
        rel = manifest_dir / candidate
        if rel.exists():
            return rel
    return candidate


def _check_int_no_bool(val: Any, field_name: str, *, lo: int = 0, hi: int = 10, allow_none: bool = False) -> int | None:
    if val is None and allow_none:
        return None
    if isinstance(val, bool) or type(val) is not int or val < lo or val > hi:
        raise ValueError(f"{field_name} must be an integer in {lo}..{hi}")
    return val


def _check_num_no_bool(val: Any, field_name: str, *, lo: float | None = None, hi: float | None = None) -> float:
    if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(float(val)):
        raise ValueError(f"{field_name} must be a finite number (not bool)")
    num = float(val)
    if lo is not None and num < lo:
        raise ValueError(f"{field_name} must be >= {lo}")
    if hi is not None and num > hi:
        raise ValueError(f"{field_name} must be <= {hi}")
    return num


def _parse_finite_decimal(val: Any, label: str) -> Decimal:
    if isinstance(val, bool):
        raise ValueError(f"{label} must be a finite numeric value (not bool)")
    if isinstance(val, Decimal):
        if not val.is_finite():
            raise ValueError(f"{label} must be finite, got {val!r}")
        return val
    if isinstance(val, int):
        return Decimal(val)
    if isinstance(val, float):
        if not math.isfinite(val):
            raise ValueError(f"{label} must be finite, got {val!r}")
        return Decimal(str(val))
    if isinstance(val, str):
        s = val.strip()
        if not s:
            raise ValueError(f"{label} must not be blank")
        try:
            d = Decimal(s)
        except InvalidOperation as exc:
            raise ValueError(f"{label} is not a valid finite decimal: {val!r}") from exc
        if not d.is_finite():
            raise ValueError(f"{label} must be finite, got {val!r}")
        return d
    raise ValueError(f"{label} must be a finite numeric value, got {type(val).__name__}")


def _is_idea_doc(doc: dict[str, Any], weights: Any = None, ratings: Any = None) -> bool:
    explicit_mode = str(doc.get("mode") or "").strip().lower() if isinstance(doc.get("mode"), str) else ""
    if explicit_mode == "idea":
        return True
    if any(isinstance(doc.get(k), str) and doc[k].strip().lower() == "idea" for k in ("status", "object_type")):
        return True
    if explicit_mode in ("", "auto"):
        if isinstance(ratings, dict) and set(ratings) == set(IDEA_DIMENSIONS):
            return True
        if isinstance(weights, dict) and set(weights) == set(IDEA_DIMENSIONS):
            return True
    return False


def _validate_weights_and_ratings(
    weights: Any,
    ratings: Any,
    context: str,
    *,
    active_dims: tuple[str, ...] = DIMENSIONS,
) -> tuple[dict[str, int], dict[str, int | None]]:
    if not isinstance(weights, dict) or set(weights) != set(active_dims):
        raise ValueError(f"{context}.weights must contain exact six dimensions")
    if not isinstance(ratings, dict) or set(ratings) != set(active_dims):
        raise ValueError(f"{context}.ratings must contain exact six dimensions")
    clean_w: dict[str, int] = {}
    for k in active_dims:
        v = _check_int_no_bool(weights[k], f"{context}.weights.{k}", lo=0, hi=100)
        assert v is not None
        clean_w[k] = v
    if sum(clean_w.values()) != 100:
        raise ValueError(f"{context}.weights must sum to 100")
    clean_r: dict[str, int | None] = {}
    for k in active_dims:
        clean_r[k] = _check_int_no_bool(ratings[k], f"{context}.ratings.{k}", lo=0, hi=10, allow_none=True)
    return clean_w, clean_r


def _validate_reviewer_panel(
    reviewer_panel: Any,
    active_dims: tuple[str, ...],
    context: str,
) -> list[dict[str, Any]] | None:
    if reviewer_panel is None:
        return None
    if not isinstance(reviewer_panel, list):
        raise ValueError(f"{context}.reviewer_panel must be a list")
    for idx, rev in enumerate(reviewer_panel):
        if not isinstance(rev, dict):
            raise ValueError(f"{context}.reviewer_panel[{idx}] must be a JSON object")
        _check_int_no_bool(rev.get("confidence"), f"{context}.reviewer_panel[{idx}].confidence", lo=1, hi=5)
        r_ratings = rev.get("ratings")
        if not isinstance(r_ratings, dict) or set(r_ratings) != set(active_dims):
            raise ValueError(f"{context}.reviewer_panel[{idx}].ratings must contain exact six dimensions")
        for dim_k in active_dims:
            _check_int_no_bool(r_ratings.get(dim_k), f"{context}.reviewer_panel[{idx}].ratings.{dim_k}", lo=0, hi=10)
    if len(reviewer_panel) < 3:
        raise ValueError(f"{context}.reviewer_panel must contain at least 3 reviewers")
    return reviewer_panel


def _build_score_math_extra(
    src_doc: dict[str, Any],
    parent_doc: dict[str, Any] | None = None,
    *,
    cli_subfield_preset: str | None = None,
) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    is_compare_output = (
        isinstance(parent_doc, dict)
        and isinstance(parent_doc.get("submission_readiness"), dict)
        and "rankings" in parent_doc
    )
    merged: dict[str, Any] = {}
    if isinstance(parent_doc, dict):
        merged.update(parent_doc)
    merged.update(src_doc)
    for k in (
        "venue_type",
        "venue_profile",
        "venue_tier",
        "venue_checks",
        "dataset_checks",
        "ethics_license_verified",
        "t1_t2_verified",
        "subfield_preset",
        "subfield_checks",
        "closest_work",
        "reading_basis",
        "evidence_rigor",
        "has_ci_or_error_bars",
        "has_ablation",
        "seed_count",
        "ablation_results",
        "evidence_locators",
        "evidence_notes",
        "notes",
        "ablation_summary",
        "statistical_summary",
        "gap_tier_ceiling",
        "resource_feasibility",
        "id",
        "evidence_profile",
        "benchmarks_count",
        "sota_baselines_covered",
        "ablation_depth",
        "theoretical_rigor",
        "effect_size_ci_stability",
        "code_artifact_openness",
    ):
        if merged.get(k) is not None:
            extra[k] = merged[k]
    meta_src = src_doc if is_compare_output else merged
    for meta_k in ("status", "object_type", "mode"):
        if meta_src.get(meta_k) is not None:
            extra[meta_k] = meta_src[meta_k]
    if cli_subfield_preset is not None and "subfield_preset" not in extra:
        extra["subfield_preset"] = cli_subfield_preset
    conf = merged.get("reviewer_confidence") if merged.get("reviewer_confidence") is not None else merged.get("confidence")
    if conf is not None:
        _check_int_no_bool(conf, "scorecard.confidence", lo=1, hi=5)
        extra["reviewer_confidence"] = conf
    if is_compare_output:
        sec_diag = src_doc.get("section_diagnostics")
        if sec_diag is not None:
            extra["section_diagnostics"] = sec_diag
    elif "section_diagnostics" in merged and merged["section_diagnostics"] is not None:
        extra["section_diagnostics"] = merged["section_diagnostics"]
    src_ea = src_doc.get("evidence_anchors")
    par_ea = parent_doc.get("evidence_anchors") if isinstance(parent_doc, dict) else None
    if isinstance(src_ea, dict) and isinstance(par_ea, list):
        extra["evidence_anchors"] = par_ea
        base_prof = dict(extra.get("evidence_profile")) if isinstance(extra.get("evidence_profile"), dict) else {}
        base_prof.update(src_ea)
        extra["evidence_profile"] = base_prof
    else:
        ev_anchors = merged.get("evidence_anchors")
        if isinstance(ev_anchors, list):
            extra["evidence_anchors"] = ev_anchors
    if merged.get("reviewer_panel") is not None:
        extra["reviewer_panel"] = merged["reviewer_panel"]
    return extra


def _piecewise_scale(val: float, anchors: list[tuple[float, float]]) -> float:
    if val <= anchors[0][0]:
        return anchors[0][1]
    if val >= anchors[-1][0]:
        return anchors[-1][1]
    for (x0, y0), (x1, y1) in zip(anchors, anchors[1:]):
        if x0 <= val <= x1:
            t = (val - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return anchors[-1][1]


def _compute_native_scales(
    weighted_dec: Decimal | None,
    *,
    fatal_gate_triggered: bool,
    desk_reject_blocked: bool,
    existing_native: Any = None,
) -> dict[str, Any]:
    if weighted_dec is None:
        return {
            "arr_1_5": None,
            "neurips_1_6": None,
            "iclr_1_10": None,
            "journal_decision_band": "Hold / Incomplete Scoring",
            "fatal_gate_override": fatal_gate_triggered or desk_reject_blocked,
            "note": "No acceptance percentage odds emitted; native scale requires complete dimension scores.",
        }
    w_float = float(weighted_dec)
    arr_val = round(_piecewise_scale(w_float, [(0.0, 1.0), (5.0, 2.5), (6.0, 3.0), (6.8, 3.5), (7.8, 4.0), (10.0, 5.0)]), 2)
    neurips_val = round(_piecewise_scale(w_float, [(0.0, 1.0), (5.0, 3.0), (6.0, 4.0), (7.8, 5.0), (10.0, 6.0)]), 2)
    iclr_val = round(max(1.0, min(10.0, w_float)), 2)

    if fatal_gate_triggered or desk_reject_blocked:
        arr_label = "Hold / Reject (gate blocked)"
        neurips_label = "Reject / Hold (gate blocked)"
        iclr_label = "Reject / Hold (gate blocked)"
        journal_band = "Reject / Hold Pending Gate Resolution"
    else:
        arr_label = (
            "Strong (>=3.5)" if arr_val >= 3.5 else ("Borderline (~3.0-3.49)" if arr_val >= 3.0 else "Below Bar (<3.0)")
        )
        neurips_label = (
            "Accept / Strong (>=5.0)"
            if neurips_val >= 5.0
            else ("Borderline Accept (~4.0-4.99)" if neurips_val >= 4.0 else "Borderline Reject / Reject (<4.0)")
        )
        iclr_label = (
            "Strong Accept (>=8.0)"
            if iclr_val >= 8.0
            else ("Accept / Weak Accept (6.0-7.99)" if iclr_val >= 6.0 else "Reject / Below Threshold (<6.0)")
        )
        if w_float >= 7.8:
            journal_band = "Accept / Minor Revision"
        elif w_float >= 6.8:
            journal_band = "Minor Revision"
        elif w_float >= 6.0:
            journal_band = "Major Revision"
        elif w_float >= 5.0:
            journal_band = "Reject / Major Revision"
        else:
            journal_band = "Reject"

    out = {
        "arr_1_5": {"score": arr_val, "band": arr_label},
        "neurips_1_6": {"score": neurips_val, "band": neurips_label},
        "iclr_1_10": {"score": iclr_val, "band": iclr_label},
        "journal_decision_band": journal_band,
        "fatal_gate_override": fatal_gate_triggered or desk_reject_blocked,
        "source": "m9a_v2" if isinstance(existing_native, dict) and not (fatal_gate_triggered or desk_reject_blocked) else "calibrated_fallback",
    }
    if isinstance(existing_native, dict):
        out["upstream_native_scales"] = existing_native
    return out


def _compute_merit_vs_packaging(
    weights: dict[str, int],
    ratings: dict[str, int | None],
    *,
    active_dims: tuple[str, ...] = DIMENSIONS,
) -> tuple[float | None, float | None]:
    if active_dims == IDEA_DIMENSIONS:
        merit_dims: tuple[str, ...] = IDEA_MERIT_DIMENSIONS
        pack_dims: tuple[str, ...] = IDEA_PACKAGING_DIMENSIONS
    else:
        merit_dims = ("importance", "novelty", "soundness", "evidence")
        pack_dims = ("transparency", "clarity")
    merit_vals = [(weights[d], ratings[d]) for d in merit_dims if d in weights and ratings.get(d) is not None]
    pack_vals = [(weights[d], ratings[d]) for d in pack_dims if d in weights and ratings.get(d) is not None]
    merit_score = None
    pack_score = None
    if len(merit_vals) == len(merit_dims):
        w_sum = sum(w for w, _ in merit_vals)
        if w_sum > 0:
            merit_score = round(sum(w * r for w, r in merit_vals) / w_sum, 2)
        else:
            merit_score = round(sum(r for _, r in merit_vals) / len(merit_vals), 2)
    if len(pack_vals) == len(pack_dims):
        w_sum = sum(w for w, _ in pack_vals)
        if w_sum > 0:
            pack_score = round(sum(w * r for w, r in pack_vals) / w_sum, 2)
        else:
            pack_score = round(sum(r for _, r in pack_vals) / len(pack_vals), 2)
    return merit_score, pack_score


def _compute_sanity_warnings(
    ratings: dict[str, int | None],
    existing: Any = None,
    *,
    existing_list: Any = None,
) -> list[str]:
    warnings: list[str] = []
    if isinstance(existing, list):
        for item in existing:
            s = str(item)
            if s not in warnings:
                warnings.append(s)
    elif isinstance(existing_list, list):
        for item in existing_list:
            s = str(item)
            if s not in warnings:
                warnings.append(s)
    imp = ratings.get("importance")
    nov = ratings.get("novelty")
    snd = ratings.get("soundness")
    evd = ratings.get("evidence")
    trn = ratings.get("transparency")
    clr = ratings.get("clarity")
    if imp is not None and snd is not None and imp >= 8 and snd <= 5:
        warnings.append("halo_effect_risk:high_importance_with_weak_soundness")
    if nov is not None and evd is not None and nov >= 8 and evd <= 5:
        warnings.append("halo_effect_risk:high_novelty_with_weak_evidence")
    if clr is not None and trn is not None and clr >= 8 and trn <= 4:
        warnings.append("halo_effect_risk:high_clarity_with_low_transparency")
    return sorted(set(warnings))


def _compute_what_if_roi(
    weights: dict[str, int],
    ratings: dict[str, int | None],
    weighted_dec: Decimal | None,
    existing: Any = None,
    *,
    active_dims: tuple[str, ...] = DIMENSIONS,
    fatal_thresholds: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    thresholds = fatal_thresholds or (IDEA_FATAL_THRESHOLDS if active_dims == IDEA_DIMENSIONS else FATAL_THRESHOLDS)
    if isinstance(existing, list) and existing:
        # Preserve upstream M9A ROI entries while ensuring finite/valid structure
        cleaned = [dict(x) for x in existing if isinstance(x, dict)]
        if cleaned:
            return cleaned
    if isinstance(existing, dict) and isinstance(existing.get("single_axis_upgrades"), list) and existing["single_axis_upgrades"]:
        converted: list[dict[str, Any]] = []
        for item in existing["single_axis_upgrades"]:
            if not isinstance(item, dict):
                continue
            dim = item.get("dimension")
            if not dim:
                continue
            converted.append({
                "dimension": dim,
                "current_rating": item.get("from_rating", item.get("current_rating")),
                "proposed_rating": item.get("new_rating", item.get("proposed_rating")),
                "delta_dimension": item.get("step", item.get("delta_dimension")),
                "weight": weights.get(dim),
                "weighted_lift": item.get("weighted_gain", item.get("weighted_lift")),
                "projected_weighted": item.get("new_weighted_unrounded", item.get("projected_weighted")),
                "resolves_fatal_threshold": bool(item.get("clears_fatal_gate", item.get("resolves_fatal_threshold"))),
                "roi_per_point": item.get("roi_leverage_per_point", item.get("roi_per_point")),
                "gate_clearing_priority": item.get("gate_clearing_priority"),
            })
        if converted:
            return converted
    if weighted_dec is None or any(ratings.get(d) is None for d in active_dims):
        return []
    roi: list[dict[str, Any]] = []
    for d in active_dims:
        cur = ratings[d]
        assert cur is not None
        if cur >= 10:
            continue
        f_th = thresholds[d]
        target_step = min(10, max(cur + 1, f_th + 1 if cur <= f_th else cur + 1))
        delta_dim = target_step - cur
        lift = round(float(Decimal(weights[d] * delta_dim) / Decimal(100)), 4)
        new_weighted = round(float(weighted_dec) + lift, 4)
        fixes_fatal = cur <= f_th
        roi.append({
            "dimension": d,
            "current_rating": cur,
            "proposed_rating": target_step,
            "delta_dimension": delta_dim,
            "weight": weights[d],
            "weighted_lift": lift,
            "projected_weighted": new_weighted,
            "resolves_fatal_threshold": fixes_fatal,
            "roi_per_point": round(weights[d] / 100.0, 4),
        })
    roi.sort(key=lambda x: (not x["resolves_fatal_threshold"], -x["weighted_lift"], -x["roi_per_point"], x["dimension"]))
    return roi


def _compute_syntheses(
    ratings: dict[str, int | None],
    weighted_dec: Decimal | None,
    *,
    fatal_gate_triggered: bool,
    cross_tool_fatal_gate: bool,
    desk_reject_blocked: bool,
    upstream_rev: Any = None,
    upstream_ac: Any = None,
    active_dims: tuple[str, ...] = DIMENSIONS,
) -> tuple[dict[str, Any], dict[str, Any]]:
    rev_synth: dict[str, Any]
    if isinstance(upstream_rev, dict):
        rev_synth = dict(upstream_rev)
        rev_synth.setdefault("source", "m9a_v2")
    elif active_dims == IDEA_DIMENSIONS:
        nov_imp = [ratings[k] for k in ("novelty", "importance") if ratings.get(k) is not None]
        ev_fal = [ratings[k] for k in ("evidence_coverage", "falsifiability") if ratings.get(k) is not None]
        ans_fea = [ratings[k] for k in ("answerability", "feasibility") if ratings.get(k) is not None]
        rev_synth = {
            "source": "calibrated_fallback",
            "personas": [
                {
                    "persona": "Novelty/Importance",
                    "focus": ["novelty", "importance"],
                    "mean_score": round(sum(nov_imp) / len(nov_imp), 2) if nov_imp else None,
                },
                {
                    "persona": "Evidence/Falsifiability",
                    "focus": ["evidence_coverage", "falsifiability"],
                    "mean_score": round(sum(ev_fal) / len(ev_fal), 2) if ev_fal else None,
                },
                {
                    "persona": "Answerability/Feasibility",
                    "focus": ["answerability", "feasibility"],
                    "mean_score": round(sum(ans_fea) / len(ans_fea), 2) if ans_fea else None,
                },
            ],
        }
    else:
        method_vals = [ratings[k] for k in ("soundness", "novelty") if ratings.get(k) is not None]
        exp_vals = [ratings[k] for k in ("evidence", "transparency") if ratings.get(k) is not None]
        clar_vals = [ratings[k] for k in ("importance", "clarity") if ratings.get(k) is not None]
        rev_synth = {
            "source": "calibrated_fallback",
            "personas": [
                {
                    "persona": "Method/Theory",
                    "focus": ["soundness", "novelty"],
                    "mean_score": round(sum(method_vals) / len(method_vals), 2) if method_vals else None,
                },
                {
                    "persona": "Experiments/Reproducibility",
                    "focus": ["evidence", "transparency"],
                    "mean_score": round(sum(exp_vals) / len(exp_vals), 2) if exp_vals else None,
                },
                {
                    "persona": "Clarity/Impact",
                    "focus": ["importance", "clarity"],
                    "mean_score": round(sum(clar_vals) / len(clar_vals), 2) if clar_vals else None,
                },
            ],
        }

    ac_synth: dict[str, Any]
    if isinstance(upstream_ac, dict):
        ac_synth = dict(upstream_ac)
        ac_synth.setdefault("source", "m9a_v2")
    else:
        ac_synth = {"source": "calibrated_fallback"}

    if desk_reject_blocked:
        ac_synth["decision"] = "desk_reject_blocked"
        ac_synth["fatal_gate_override"] = True
        ac_synth["summary"] = "Blocked at pre-submission desk-reject gate; resolve mandatory venue/anonymization defects."
    elif fatal_gate_triggered or cross_tool_fatal_gate:
        ac_synth["decision"] = "hold_reject_fatal_gate"
        ac_synth["fatal_gate_override"] = True
        ac_synth["summary"] = "Held/rejected by AC due to fatal threshold or cross-tool scientific-rigor/integrity gate."
    elif weighted_dec is None:
        ac_synth["decision"] = "incomplete_not_comparable"
        ac_synth["fatal_gate_override"] = False
        ac_synth["summary"] = "Cannot issue AC recommendation with missing rating dimensions."
    elif weighted_dec >= Decimal("6.80"):
        ac_synth["decision"] = "competitive_accept_candidate"
        ac_synth["fatal_gate_override"] = False
        ac_synth["summary"] = "Post-cap profile meets top-tier competitive threshold pending venue CFP verification."
    elif weighted_dec >= Decimal("6.00"):
        ac_synth["decision"] = "borderline_retarget_tier_a_or_findings"
        ac_synth["fatal_gate_override"] = False
        ac_synth["summary"] = "Borderline for main track; stronger match for Tier-A / Findings / Q1 journal or strengthen bottlenecks."
    elif weighted_dec >= Decimal("5.00"):
        ac_synth["decision"] = "workshop_or_major_rework"
        ac_synth["fatal_gate_override"] = False
        ac_synth["summary"] = "Below archival main-track bar; target workshop track or perform substantial rework."
    else:
        ac_synth["decision"] = "reject_major_rework"
        ac_synth["fatal_gate_override"] = False
        ac_synth["summary"] = "Not ready for submission (< 5.00 weighted score)."
    return rev_synth, ac_synth


def _compute_section_diagnostics(ratings: dict[str, int | None], existing: Any = None) -> dict[str, Any]:
    if isinstance(existing, dict) and existing:
        out = dict(existing)
        out.setdefault("source", "m9a_v2")
        return out
    return {
        "source": "calibrated_fallback",
        "method_and_theory": ratings.get("soundness"),
        "novelty_and_positioning": ratings.get("novelty"),
        "experiments_and_evidence": ratings.get("evidence"),
        "reproducibility_and_transparency": ratings.get("transparency"),
        "presentation_and_clarity": ratings.get("clarity"),
        "problem_importance": ratings.get("importance"),
    }


def _compute_worst_case_sensitivity(
    weights: dict[str, int],
    ratings: dict[str, int | None],
    weighted_dec: Decimal | None,
    existing: Any = None,
    *,
    active_dims: tuple[str, ...] = DIMENSIONS,
    fatal_thresholds: dict[str, int] | None = None,
) -> dict[str, Any]:
    thresholds = fatal_thresholds or (IDEA_FATAL_THRESHOLDS if active_dims == IDEA_DIMENSIONS else FATAL_THRESHOLDS)
    if isinstance(existing, dict) and existing:
        out = dict(existing)
        out.setdefault("source", "m9a_v2")
        per_dim = out.get("per_dimension")
        if out.get("min_dimension") is None and isinstance(per_dim, dict) and per_dim:
            candidates = [
                (d, info.get("current_rating"), (info.get("drop_minus_1") or {}).get("new_weighted"), (info.get("drop_minus_1") or {}).get("triggers_fatal_gate"))
                for d, info in per_dim.items()
                if isinstance(info, dict) and type(info.get("current_rating")) is int
            ]
            if candidates:
                min_d, min_r, drop_w, trig_f = min(
                    candidates,
                    key=lambda x: (x[1], -(weights.get(x[0], 0)), active_dims.index(x[0]) if x[0] in active_dims else 99),
                )
                out["min_dimension"] = min_d
                out["min_rating"] = min_r
                out["drop_one_weighted"] = drop_w
                out["triggers_fatal_on_drop_one"] = bool(trig_f)
        return out
    non_null = [(d, ratings[d], weights[d]) for d in active_dims if d in weights and ratings.get(d) is not None]
    if not non_null or weighted_dec is None:
        return {"source": "calibrated_fallback", "min_dimension": None, "min_rating": None, "drop_one_weighted": None}
    min_dim, min_r, min_w = min(non_null, key=lambda x: (x[1], -x[2], active_dims.index(x[0])))
    drop_one = round(float(weighted_dec) - (min_w / 100.0), 4)
    return {
        "source": "calibrated_fallback",
        "min_dimension": min_dim,
        "min_rating": min_r,
        "drop_one_weighted": drop_one,
        "triggers_fatal_on_drop_one": (min_r - 1) <= thresholds[min_dim],
    }


def _unwrap_per_target(val: Any, eff_tid: str | None, *, direct_keys: tuple[str, ...] = ()) -> Any:
    if not isinstance(val, dict) or not eff_tid:
        return val
    if any(k in val for k in direct_keys):
        return val
    if eff_tid in val:
        return val[eff_tid]
    return val


def _extract_m9a_fields(src: dict[str, Any] | None, *, target_id: str | None = None) -> dict[str, Any]:
    if not isinstance(src, dict):
        return {}
    out: dict[str, Any] = {}
    per_target_specs: dict[str, tuple[str, ...]] = {
        "native_venue_scales": ("arr_1_to_5", "neurips_1_to_6", "iclr_1_to_10", "journal_decision"),
        "merit_vs_packaging": ("scientific_merit_score", "publishability_packaging_score"),
        "reviewer_panel_analysis": ("per_reviewer_summary", "meta_review_verdict", "reviewer_count"),
        "reviewer_panel_summary": ("meta_review_verdict", "confidence_weighted_mean", "variance_risk"),
        "deal_breaker_sensitivity": ("worst_case_reviewer_floor", "per_dimension", "deal_breaker_axes"),
        "what_if_roi": ("single_axis_upgrades", "minimal_paths"),
        "section_diagnostics": ("sections_scored", "section_mean", "prioritized_edit_order"),
    }
    for k in M9A_OPTIONAL_KEYS:
        val = src.get(k)
        if val is None:
            continue
        if k in per_target_specs:
            val = _unwrap_per_target(val, target_id, direct_keys=per_target_specs[k])
        elif k == "sanity_warnings" and isinstance(val, dict) and target_id:
            val = val.get(target_id, [])
        out[k] = val
    return out


def _parse_scorecard_input(
    sc_doc: dict[str, Any] | None,
    target_id: str | None,
    *,
    subfield_preset: str | None = None,
) -> dict[str, Any]:
    if sc_doc is None:
        return {
            "present": False,
            "target_id": target_id,
            "weights": None,
            "ratings": None,
            "active_dims": DIMENSIONS,
            "is_idea": False,
            "pre_cap_result": None,
            "structural_gate_passed": True,
            "issues": [],
            "novelty_inflation_warnings": [],
            "related_work_comparison": None,
            "m9a_fields": {},
            "score_math_extra": {},
        }

    # Case 1: compare_scorecards.py output (has submission_readiness dict of profiles & rankings)
    if isinstance(sc_doc.get("submission_readiness"), dict) and "status" in sc_doc and "rankings" in sc_doc:
        sr_map = sc_doc["submission_readiness"]
        if not sr_map:
            raise ValueError("Scorecard comparison report has empty submission_readiness")
        eff_tid = target_id
        if not eff_tid and isinstance(sc_doc.get("related_work_comparison"), dict):
            eff_tid = sc_doc["related_work_comparison"].get("target_id")
        if not eff_tid:
            eff_tid = "target" if "target" in sr_map else next(iter(sr_map))
        if eff_tid not in sr_map:
            raise ValueError(f"target_id {eff_tid!r} not found in scorecard submission_readiness")
        target_sr = sr_map[eff_tid]
        if not isinstance(target_sr, dict):
            raise ValueError(f"Invalid submission_readiness entry for {eff_tid!r}")

        m9a_fields = _extract_m9a_fields(sc_doc, target_id=eff_tid)
        m9a_fields.update(_extract_m9a_fields(target_sr, target_id=eff_tid))

        # Resolve ratings from target_sr, or fallback to sc_doc["profiles"] if attached
        prof_match = None
        if isinstance(sc_doc.get("profiles"), list):
            prof_match = next(
                (p for p in sc_doc["profiles"] if isinstance(p, dict) and p.get("id") == eff_tid),
                None,
            )

        weights = sc_doc.get("weights") or target_sr.get("weights") or (prof_match.get("weights") if isinstance(prof_match, dict) else None)
        ratings = target_sr.get("ratings") or (prof_match.get("ratings") if isinstance(prof_match, dict) else None)
        is_idea = (
            _is_idea_doc(sc_doc, weights, ratings)
            or _is_idea_doc(target_sr, weights, ratings)
            or ("unrun_idea_results" in (target_sr.get("fatal_reasons") or []))
            or ("idea_viability_band" in target_sr)
        )
        active_dims = IDEA_DIMENSIONS if (
            (isinstance(ratings, dict) and set(ratings) == set(IDEA_DIMENSIONS))
            or (isinstance(weights, dict) and set(weights) == set(IDEA_DIMENSIONS))
            or (is_idea and ratings is None and weights is None)
        ) else DIMENSIONS

        extra = _build_score_math_extra(
            prof_match if isinstance(prof_match, dict) else target_sr,
            sc_doc,
            cli_subfield_preset=subfield_preset,
        )

        if isinstance(ratings, dict) and (isinstance(weights, dict) or is_idea):
            eff_weights = weights if isinstance(weights, dict) else dict(DEFAULT_IDEA_WEIGHTS)
            clean_w, clean_r = _validate_weights_and_ratings(eff_weights, ratings, f"scorecard[{eff_tid}]", active_dims=active_dims)
            if extra.get("reviewer_panel") is not None:
                _validate_reviewer_panel(extra["reviewer_panel"], active_dims, f"scorecard[{eff_tid}]")
            pre_cap = score_math_score({
                "weights": clean_w,
                "ratings": clean_r,
                **extra,
                **({"mode": "idea"} if is_idea else {}),
            })
            m9a_fields.update({k: v for k, v in _extract_m9a_fields(pre_cap).items() if k not in m9a_fields})
        else:
            if extra.get("reviewer_panel") is not None:
                _validate_reviewer_panel(extra["reviewer_panel"], active_dims, f"scorecard[{eff_tid}]")
            clean_w = dict(DEFAULT_IDEA_WEIGHTS if is_idea else DEFAULT_WEIGHTS)
            clean_r = None
            raw_wu = target_sr.get("weighted_unrounded")
            if raw_wu is not None:
                _parse_finite_decimal(raw_wu, f"scorecard[{eff_tid}].weighted_unrounded")
            raw_ov = target_sr.get("overall")
            if raw_ov is not None:
                _check_int_no_bool(raw_ov, f"scorecard[{eff_tid}].overall", lo=0, hi=10)
            pre_cap = {
                "overall": raw_ov,
                "weighted_unrounded": raw_wu,
                "status": "calculated" if raw_ov is not None else "not_comparable",
                "submission_readiness": {
                    k: target_sr.get(k)
                    for k in (
                        "band",
                        "ready_for_top_tier_main_track",
                        "ready_for_findings_or_tier_a",
                        "fatal_gate_triggered",
                        "fatal_dimensions",
                        "fatal_reasons",
                        "bottleneck_dimensions",
                        "delta_to_competitive_top_tier",
                        "recommended_matched_tier",
                        "guidance",
                        "idea_viability_band",
                    )
                    if k in target_sr
                },
            }
            if is_idea:
                pre_cap["mode"] = "idea"
                pre_cap["archival_submission_blocked"] = True

        issues = list(sc_doc.get("issues") or [])
        raw_issue_cnt = sc_doc.get("issue_count")
        if type(raw_issue_cnt) is int and raw_issue_cnt > len(issues):
            if not issues:
                issues = [f"scorecard_issues_truncated({raw_issue_cnt})"]
            else:
                issues.append(f"scorecard_issues_truncated({raw_issue_cnt - len(issues)}_more)")
        prof_issues = list(target_sr.get("profile_issues") or [])
        all_issues = sorted(set(str(x) for x in (issues + prof_issues)))
        rw_comp = sc_doc.get("related_work_comparison") if isinstance(sc_doc.get("related_work_comparison"), dict) else None
        nov_warns = list((rw_comp or {}).get("novelty_inflation_warnings") or [])
        structural_ok = (sc_doc.get("status") == "structurally_comparable") and bool(target_sr.get("structural_gate_passed", True)) and not all_issues
        return {
            "present": True,
            "target_id": eff_tid,
            "weights": clean_w,
            "ratings": clean_r,
            "active_dims": active_dims,
            "is_idea": is_idea,
            "pre_cap_result": pre_cap,
            "structural_gate_passed": structural_ok,
            "issues": all_issues,
            "novelty_inflation_warnings": nov_warns,
            "related_work_comparison": rw_comp,
            "m9a_fields": m9a_fields,
            "score_math_extra": extra,
        }

    m9a_fields = _extract_m9a_fields(sc_doc, target_id=target_id)

    # Case 2: compare_scorecards.py input document (profiles + optional weight_scenarios)
    if isinstance(sc_doc.get("profiles"), list):
        profiles = sc_doc["profiles"]
        if not profiles:
            raise ValueError("Scorecard document requires non-empty profiles")
        eff_tid = target_id or sc_doc.get("target_id") or (profiles[0].get("id") if isinstance(profiles[0], dict) else None)
        chosen = next((p for p in profiles if isinstance(p, dict) and p.get("id") == eff_tid), None)
        if chosen is None:
            raise ValueError(f"target_id {eff_tid!r} not found in scorecard profiles")
        m9a_fields.update(_extract_m9a_fields(chosen))

        raw_scenarios = sc_doc.get("weight_scenarios")
        has_idea_dim_profiles = any(
            isinstance(p, dict) and isinstance(p.get("ratings"), dict) and set(p["ratings"]) == set(IDEA_DIMENSIONS)
            for p in profiles
        )
        vtype_raw = chosen.get("venue_type") or chosen.get("venue_profile") or sc_doc.get("venue_type") or sc_doc.get("venue_profile")
        if raw_scenarios is None:
            is_idea_pre = (
                _is_idea_doc(sc_doc, None, chosen.get("ratings"))
                or _is_idea_doc(chosen, None, chosen.get("ratings"))
            )
            dims_pre = IDEA_DIMENSIONS if (is_idea_pre and (
                not isinstance(chosen.get("ratings"), dict) or set(chosen["ratings"]) != set(DIMENSIONS)
            )) or has_idea_dim_profiles else DIMENSIONS
            if dims_pre == IDEA_DIMENSIONS:
                scenarios = [dict(DEFAULT_IDEA_WEIGHTS)]
            elif isinstance(vtype_raw, str) and vtype_raw.strip().lower() in VENUE_TYPE_PROFILES:
                scenarios = [dict(VENUE_TYPE_PROFILES[vtype_raw.strip().lower()]["weights"])]
            else:
                raise ValueError("Scorecard document requires non-empty weight_scenarios")
        else:
            if not isinstance(raw_scenarios, list) or not raw_scenarios:
                raise ValueError("Scorecard document requires non-empty profiles and weight_scenarios")
            scenarios = raw_scenarios

        is_idea = _is_idea_doc(sc_doc, scenarios[0], chosen.get("ratings")) or _is_idea_doc(chosen, scenarios[0], chosen.get("ratings"))
        active_dims = IDEA_DIMENSIONS if is_idea and (
            not isinstance(chosen.get("ratings"), dict) or set(chosen["ratings"]) != set(DIMENSIONS)
        ) else DIMENSIONS
        clean_w, clean_r = _validate_weights_and_ratings(scenarios[0], chosen.get("ratings"), f"scorecard[{eff_tid}]", active_dims=active_dims)
        extra = _build_score_math_extra(chosen, sc_doc, cli_subfield_preset=subfield_preset)
        if extra.get("reviewer_panel") is not None:
            _validate_reviewer_panel(extra["reviewer_panel"], active_dims, f"scorecard[{eff_tid}]")
        pre_cap = score_math_score({
            "weights": clean_w,
            "ratings": clean_r,
            **extra,
            **({"mode": "idea"} if is_idea else {}),
        })
        m9a_fields.update({k: v for k, v in _extract_m9a_fields(pre_cap).items() if k not in m9a_fields})
        return {
            "present": True,
            "target_id": eff_tid,
            "weights": clean_w,
            "ratings": clean_r,
            "active_dims": active_dims,
            "is_idea": is_idea,
            "pre_cap_result": pre_cap,
            "structural_gate_passed": True,
            "issues": [],
            "novelty_inflation_warnings": [],
            "related_work_comparison": None,
            "m9a_fields": m9a_fields,
            "score_math_extra": extra,
        }

    # Case 3: score_math.py input document (weights + ratings, or idea ratings with default weights)
    if "ratings" in sc_doc and ("weights" in sc_doc or _is_idea_doc(sc_doc, None, sc_doc.get("ratings")) or sc_doc.get("venue_type") or sc_doc.get("venue_profile")):
        raw_ratings = sc_doc.get("ratings")
        raw_weights = sc_doc.get("weights")
        is_idea = _is_idea_doc(sc_doc, raw_weights, raw_ratings)
        active_dims = IDEA_DIMENSIONS if is_idea and (
            not isinstance(raw_ratings, dict) or set(raw_ratings) != set(DIMENSIONS)
        ) else DIMENSIONS
        if raw_weights is None:
            vtype = sc_doc.get("venue_type") or sc_doc.get("venue_profile")
            if active_dims == IDEA_DIMENSIONS:
                raw_weights = dict(DEFAULT_IDEA_WEIGHTS)
            elif isinstance(vtype, str) and vtype.strip().lower() in VENUE_TYPE_PROFILES:
                raw_weights = dict(VENUE_TYPE_PROFILES[vtype.strip().lower()]["weights"])
            else:
                raise ValueError("scorecard.weights is required")
        clean_w, clean_r = _validate_weights_and_ratings(raw_weights, raw_ratings, "scorecard", active_dims=active_dims)
        extra = _build_score_math_extra(sc_doc, cli_subfield_preset=subfield_preset)
        if extra.get("reviewer_panel") is not None:
            _validate_reviewer_panel(extra["reviewer_panel"], active_dims, "scorecard")
        pre_cap = score_math_score({
            "weights": clean_w,
            "ratings": clean_r,
            **extra,
            **({"mode": "idea"} if is_idea else {}),
        })
        m9a_fields.update({k: v for k, v in _extract_m9a_fields(pre_cap).items() if k not in m9a_fields})
        return {
            "present": True,
            "target_id": target_id or sc_doc.get("id") or "target",
            "weights": clean_w,
            "ratings": clean_r,
            "active_dims": active_dims,
            "is_idea": is_idea,
            "pre_cap_result": pre_cap,
            "structural_gate_passed": True,
            "issues": [],
            "novelty_inflation_warnings": [],
            "related_work_comparison": None,
            "m9a_fields": m9a_fields,
            "score_math_extra": extra,
        }

    # Case 4: score_math.py output document (overall + submission_readiness, no raw ratings)
    if "submission_readiness" in sc_doc and "status" in sc_doc and isinstance(sc_doc["submission_readiness"], dict):
        sr = sc_doc["submission_readiness"]
        raw_wu = sc_doc.get("weighted_unrounded")
        if raw_wu is not None:
            _parse_finite_decimal(raw_wu, "scorecard.weighted_unrounded")
        raw_ov = sc_doc.get("overall")
        if raw_ov is not None:
            _check_int_no_bool(raw_ov, "scorecard.overall", lo=0, hi=10)
        is_idea = (
            _is_idea_doc(sc_doc)
            or ("unrun_idea_results" in (sr.get("fatal_reasons") or []))
            or (sc_doc.get("archival_submission_blocked") is True)
            or ("idea_viability_band" in sc_doc)
        )
        return {
            "present": True,
            "target_id": target_id or "target",
            "weights": dict(DEFAULT_IDEA_WEIGHTS if is_idea else DEFAULT_WEIGHTS),
            "ratings": None,
            "active_dims": IDEA_DIMENSIONS if is_idea else DIMENSIONS,
            "is_idea": is_idea,
            "pre_cap_result": sc_doc,
            "structural_gate_passed": sc_doc.get("status") == "calculated",
            "issues": [] if sc_doc.get("status") == "calculated" else [str(sc_doc.get("reason") or "not_comparable")],
            "novelty_inflation_warnings": [],
            "related_work_comparison": None,
            "m9a_fields": m9a_fields,
            "score_math_extra": {},
        }

    raise ValueError("Unrecognized scorecard JSON schema")


def _apply_cap(caps: dict[str, int], dim: str, cap_val: int, reason: str, cap_reasons: list[str]) -> None:
    if dim not in caps or cap_val < caps[dim]:
        caps[dim] = cap_val
    if reason not in cap_reasons:
        cap_reasons.append(reason)


def _evaluate_rigor_and_engineering(
    rigor_docs: list[tuple[Path, dict[str, Any]]],
    eng_doc: dict[str, Any] | None,
    exp_manifest_doc: dict[str, Any] | None,
    exp_manifest_path: Path | None,
) -> dict[str, Any]:
    caps: dict[str, int] = {}
    cap_reasons: list[str] = []
    fatal = False
    critical_failures: list[str] = []
    warnings: list[str] = []
    rigor_summaries: list[dict[str, Any]] = []
    covered_checks: set[str] = set()
    failed_checks: set[str] = set()

    for path, doc in rigor_docs:
        schema = str(doc.get("schema") or "")
        verdict = str(doc.get("verdict") or "")
        if "contamination" in schema or "contaminated_eval_count" in doc or "exact_match_count" in doc:
            is_bad = verdict == "CONTAMINATION_DETECTED" or verdict == "FAIL"
            if is_bad:
                fatal = True
                failed_checks.add("contamination_check")
                msg = f"rigor_contamination:{verdict or 'CONTAMINATION_DETECTED'}"
                critical_failures.append(msg)
                _apply_cap(caps, "evidence", 4, msg, cap_reasons)
                _apply_cap(caps, "soundness", 4, msg, cap_reasons)
            else:
                covered_checks.add("contamination_check")
            rigor_summaries.append({"kind": "contamination", "file": str(path), "verdict": verdict, "critical": is_bad})
        elif "repro" in schema or ("essentials" in doc and "missing" in doc):
            missing = [str(m) for m in (doc.get("missing") or [])]
            doc_warns = [str(w) for w in (doc.get("warnings") or [])]
            is_bad = verdict == "FAIL" or bool(missing) or ("SEED" in missing)
            if is_bad:
                fatal = True
                msg = f"rigor_repro_fail:missing={','.join(missing) or 'essentials'}"
                critical_failures.append(msg)
                _apply_cap(caps, "evidence", 4, msg, cap_reasons)
                _apply_cap(caps, "soundness", 4, msg, cap_reasons)
            elif doc_warns or verdict == "PASS_WITH_WARNINGS":
                warnings.extend(f"rigor_repro_warn:{w}" for w in (doc_warns or [verdict]))
            rigor_summaries.append({"kind": "repro", "file": str(path), "verdict": verdict, "missing": missing, "critical": is_bad})
        elif "rliable" in schema or ("methods" in doc and isinstance(doc.get("methods"), dict)):
            doc_warns = [str(w) for w in (doc.get("warnings") or [])]
            flagged_critical = (
                verdict in ("FAIL", "CRITICAL")
                or doc.get("critical") is True
                or str(doc.get("severity") or "").lower() == "critical"
                or (doc.get("strict") is True and bool(doc_warns))
            )
            if flagged_critical:
                fatal = True
                msg = f"rigor_rliable_critical:{','.join(doc_warns[:3]) or verdict}"
                critical_failures.append(msg)
                _apply_cap(caps, "evidence", 4, msg, cap_reasons)
            elif doc_warns:
                warnings.extend(f"rigor_rliable_warn:{w}" for w in doc_warns)
            rigor_summaries.append({"kind": "rliable", "file": str(path), "verdict": verdict, "warnings": doc_warns, "critical": flagged_critical})
        else:
            if verdict in ("FAIL", "CONTAMINATION_DETECTED", "CRITICAL", "ENGINEERING_BUG_DETECTED"):
                fatal = True
                msg = f"rigor_unknown_fail:{verdict}"
                critical_failures.append(msg)
                _apply_cap(caps, "evidence", 4, msg, cap_reasons)
            rigor_summaries.append({"kind": "generic", "file": str(path), "verdict": verdict, "critical": verdict in ("FAIL", "CONTAMINATION_DETECTED", "CRITICAL")})

    eng_summary: dict[str, Any] | None = None
    if eng_doc is not None:
        eng_verdict = str(eng_doc.get("verdict") or "")
        findings = [f for f in (eng_doc.get("findings") or []) if isinstance(f, dict)]
        crit_findings = [
            f for f in findings
            if str(f.get("severity") or "").lower() == "error"
            or str(f.get("category") or "") in CRITICAL_ENGINEERING_CATEGORIES
        ]
        is_eng_bad = eng_verdict == "ENGINEERING_BUG_DETECTED" or bool(crit_findings)
        if is_eng_bad:
            fatal = True
            cats = sorted({str(f.get("category") or "engineering_bug") for f in crit_findings}) or [eng_verdict]
            msg = f"engineering_diagnostics:{','.join(cats[:4])}"
            critical_failures.append(msg)
            _apply_cap(caps, "soundness", 4, msg, cap_reasons)
            _apply_cap(caps, "evidence", 4, msg, cap_reasons)
        speech_cfg_tokens = (
            "sample_rate",
            "vocoder",
            "lm_decoding",
            "decoding_strategy",
            "embedding_backend",
            "score_normalization",
        )
        for f in findings:
            cat = str(f.get("category") or "")
            loc = str(f.get("location") or "").casefold()
            det = str(f.get("detail") or "").casefold()
            if cat == "nlp_prompt_template_sensitivity_missing":
                warnings.append("missing_prompt_template_sensitivity")
            if cat in ("group_leakage_across_splits", "split_overlap_leakage"):
                failed_checks.add("speaker_session_disjoint_split")
            elif cat == "budget_or_config_mismatch" and any(tok in loc or tok in det for tok in speech_cfg_tokens):
                failed_checks.add("decoding_vocoder_embedding_parity")
        raw_fc = eng_doc.get("finding_count")
        eff_finding_count = max(len(findings), raw_fc) if type(raw_fc) is int and raw_fc >= 0 else len(findings)
        eng_summary = {
            "verdict": eng_verdict,
            "triage_classification": eng_doc.get("triage_classification"),
            "finding_count": eff_finding_count,
            "critical_categories": sorted({str(f.get("category") or "") for f in crit_findings if f.get("category")}),
        }

    exp_summary: dict[str, Any] | None = None
    if exp_manifest_doc is not None:
        # Support both check_experiment_manifest output AND raw manifest JSON
        doc_to_eval = exp_manifest_doc
        if "runs" in exp_manifest_doc and "status" not in exp_manifest_doc and "errors" not in exp_manifest_doc:
            import check_experiment_manifest  # noqa: E402

            base_dir = exp_manifest_path.parent if exp_manifest_path is not None else None
            checked = check_experiment_manifest.check(exp_manifest_doc)
            vf = check_experiment_manifest.verify_files(exp_manifest_doc, base_dir=base_dir)
            checked["files_verified"] = vf["files_verified"]
            checked["file_checks"] = vf["file_checks"]
            checked["errors"] = list(checked.get("errors") or []) + list(vf.get("file_errors") or [])
            checked["warnings"] = list(checked.get("warnings") or []) + list(vf.get("file_warnings") or [])
            checked["status"] = "invalid" if checked["errors"] else "structurally_checked"
            doc_to_eval = checked

        m_status = str(doc_to_eval.get("status") or "")
        files_ok = doc_to_eval.get("files_verified")
        m_errors = [str(e) for e in (doc_to_eval.get("errors") or [])]
        m_warns = [str(w) for w in (doc_to_eval.get("warnings") or [])]
        claims_cmp = doc_to_eval.get("claim_comparisons") if isinstance(doc_to_eval.get("claim_comparisons"), dict) else None
        claim_bad = bool(claims_cmp and ((claims_cmp.get("mismatched") or 0) > 0 or (claims_cmp.get("missing") or 0) > 0))
        receipt_err = any(
            tok in err.lower()
            for err in m_errors
            for tok in ("sha256 mismatch", "missing file on disk", "invalid ", "value discrepancy", "missing run log", "empty run log", "missing result_artifact")
        )
        raw_ec = doc_to_eval.get("error_count")
        eff_err_count = max(len(m_errors), raw_ec) if type(raw_ec) is int and raw_ec >= 0 else len(m_errors)
        is_exp_bad = m_status == "invalid" or files_ok is False or receipt_err or claim_bad or bool(m_errors) or eff_err_count > 0
        if is_exp_bad:
            fatal = True
            msg = f"experiment_manifest:{m_errors[0] if m_errors else ('files_unverified' if files_ok is False else m_status)}"
            critical_failures.append(msg)
            _apply_cap(caps, "evidence", 4, msg, cap_reasons)
            _apply_cap(caps, "soundness", 4, msg, cap_reasons)
        warnings.extend(f"experiment_manifest_warn:{w}" for w in m_warns)
        exp_summary = {
            "status": m_status,
            "files_verified": files_ok,
            "error_count": eff_err_count,
            "errors": m_errors[:10],
            "comparison_status": doc_to_eval.get("comparison_status"),
        }

    return {
        "fatal": fatal,
        "caps": caps,
        "cap_reasons": cap_reasons,
        "critical_failures": critical_failures,
        "warnings": warnings,
        "rigor_summaries": rigor_summaries,
        "engineering_diagnostics": eng_summary,
        "experiment_manifest": exp_summary,
        "covered_checks": sorted(covered_checks - failed_checks),
        "failed_checks": sorted(failed_checks),
    }


def _evaluate_ledger_and_readiness(
    ledger_doc: dict[str, Any] | None,
    readiness_doc: dict[str, Any] | None,
) -> dict[str, Any]:
    caps: dict[str, int] = {}
    cap_reasons: list[str] = []
    block_ready = False
    fatal = False
    blocking_reasons: list[str] = []
    warnings: list[str] = []
    anon_desk_reject_reasons: list[str] = []

    ledger_summary: dict[str, Any] | None = None
    if ledger_doc is not None:
        l_status = str(ledger_doc.get("status") or "")
        issues = [str(i) for i in (ledger_doc.get("issues") or [])]
        grandiose = list(ledger_doc.get("grandiose_findings") or [])
        raw_gf_count = ledger_doc.get("grandiose_finding_count")
        if raw_gf_count is not None and (isinstance(raw_gf_count, bool) or type(raw_gf_count) is not int or raw_gf_count < 0):
            raise ValueError("ledger.grandiose_finding_count must be a non-negative integer")
        grandiose_count = len(grandiose) if grandiose else int(raw_gf_count or 0)
        arg_audit = ledger_doc.get("argument_audit") if isinstance(ledger_doc.get("argument_audit"), dict) else {}

        rec_t = arg_audit.get("recommended_transparency_cap")
        if rec_t is not None:
            rec_t_int = _check_int_no_bool(rec_t, "ledger.argument_audit.recommended_transparency_cap", lo=0, hi=10)
            assert rec_t_int is not None
            _apply_cap(caps, "transparency", rec_t_int, f"ledger_argument_audit_transparency_cap:{rec_t_int}", cap_reasons)

        rec_e = arg_audit.get("recommended_evidence_cap")
        if rec_e is not None:
            rec_e_int = _check_int_no_bool(rec_e, "ledger.argument_audit.recommended_evidence_cap", lo=0, hi=10)
            assert rec_e_int is not None
            _apply_cap(caps, "evidence", rec_e_int, f"ledger_argument_audit_evidence_cap:{rec_e_int}", cap_reasons)

        raw_total_issues = ledger_doc.get("total_issues")
        eff_total_issues = max(len(issues), raw_total_issues) if type(raw_total_issues) is int and raw_total_issues >= 0 else len(issues)
        raw_trunc = ledger_doc.get("issues_truncated")
        trunc_cnt = raw_trunc if type(raw_trunc) is int and raw_trunc > 0 else max(0, eff_total_issues - len(issues))

        has_evidence_issue = any(i.startswith(LEDGER_EVIDENCE_ISSUE_PREFIXES) for i in issues)
        has_grandiose_issue = grandiose_count > 0 or any(i.startswith(LEDGER_GRANDIOSE_PREFIXES) for i in issues)
        has_structural_issue = l_status == "structural_issues" or bool(issues) or eff_total_issues > 0 or grandiose_count > 0

        if has_grandiose_issue or has_structural_issue:
            block_ready = True
            _apply_cap(caps, "transparency", 3, "manuscript_ledger_structural_or_grandiose_issue", cap_reasons)
            blocking_reasons.append(
                f"manuscript_ledger:{l_status or 'issues'}({eff_total_issues} issues, {grandiose_count} grandiose)"
            )
        if has_evidence_issue:
            block_ready = True
            _apply_cap(caps, "evidence", 4, "manuscript_ledger_unverified_claims_or_receipts", cap_reasons)
        if trunc_cnt > 0 and not has_evidence_issue:
            warnings.append("manuscript_ledger_issues_truncated_inspect_full_artifact")

        for dim_k, cap_v in caps.items():
            if cap_v <= FATAL_THRESHOLDS[dim_k]:
                fatal = True

        ledger_summary = {
            "status": l_status,
            "issue_count": eff_total_issues,
            "issues": issues[:20],
            "grandiose_finding_count": grandiose_count,
            "argument_audit": arg_audit or None,
        }

    readiness_summary: dict[str, Any] | None = None
    if readiness_doc is not None:
        r_verdict = str(readiness_doc.get("verdict") or readiness_doc.get("status") or "")
        r_ready = readiness_doc.get("ready_to_submit")
        if r_ready is not None and type(r_ready) is not bool:
            raise ValueError("artifact_readiness.ready_to_submit must be boolean")
        rec_cap = readiness_doc.get("recommended_transparency_cap")
        if rec_cap is not None:
            rec_cap_int = _check_int_no_bool(rec_cap, "artifact_readiness.recommended_transparency_cap", lo=0, hi=10)
            assert rec_cap_int is not None
            _apply_cap(caps, "transparency", rec_cap_int, f"artifact_readiness_cap:{rec_cap_int}({r_verdict})", cap_reasons)
        elif r_verdict == "FAIL" or r_ready is False:
            _apply_cap(caps, "transparency", 3, f"artifact_readiness_fail:{r_verdict}", cap_reasons)
        elif r_verdict == "WARN":
            _apply_cap(caps, "transparency", 5, "artifact_readiness_warn", cap_reasons)

        b_reasons = [str(b) for b in (readiness_doc.get("blocking_reasons") or [])]
        r_warns = [str(w) for w in (readiness_doc.get("warnings") or [])]
        raw_r_errs = readiness_doc.get("error_count")
        has_r_errs = type(raw_r_errs) is int and raw_r_errs > 0
        raw_r_warns = readiness_doc.get("warning_count")
        eff_warn_count = max(len(r_warns), raw_r_warns) if type(raw_r_warns) is int and raw_r_warns >= 0 else len(r_warns)

        if r_verdict == "FAIL" or r_ready is False or b_reasons or has_r_errs:
            block_ready = True
            _apply_cap(caps, "transparency", 3, "artifact_readiness_fail", cap_reasons)
            fatal = True
            blocking_reasons.extend(f"artifact_readiness:{b}" for b in (b_reasons or [r_verdict or "FAIL"]))
        elif r_verdict == "WARN":
            warnings.extend(f"artifact_readiness_warn:{w}" for w in (r_warns or ["WARN"]))

        # Check anonymization failures inside artifact readiness
        summary_cats = ((readiness_doc.get("summary") or {}).get("by_category") or {}) if isinstance(readiness_doc.get("summary"), dict) else {}
        anon_cat = summary_cats.get("anonymization") if isinstance(summary_cats, dict) else None
        if isinstance(anon_cat, dict) and anon_cat.get("status") == "FAIL":
            anon_desk_reject_reasons.append("artifact_readiness:anonymization_fail")
        for b in b_reasons:
            if b.startswith("anonymization/") and f"artifact_readiness:{b}" not in anon_desk_reject_reasons:
                anon_desk_reject_reasons.append(f"artifact_readiness:{b}")
        for f in (readiness_doc.get("findings") or []):
            if isinstance(f, dict) and f.get("category") == "anonymization" and f.get("severity") == "FAIL":
                tok = f"artifact_readiness:{f.get('check') or 'anonymization'}"
                if tok not in anon_desk_reject_reasons:
                    anon_desk_reject_reasons.append(tok)

        readiness_summary = {
            "verdict": r_verdict,
            "ready_to_submit": r_ready,
            "recommended_transparency_cap": rec_cap if rec_cap is not None else caps.get("transparency"),
            "blocking_reasons": b_reasons[:20],
            "warning_count": eff_warn_count,
        }

    return {
        "fatal": fatal,
        "block_ready": block_ready,
        "caps": caps,
        "cap_reasons": cap_reasons,
        "blocking_reasons": sorted(set(blocking_reasons)),
        "warnings": sorted(set(warnings)),
        "anon_desk_reject_reasons": sorted(set(anon_desk_reject_reasons)),
        "manuscript_ledger": ledger_summary,
        "artifact_readiness": readiness_summary,
    }


def _evaluate_desk_reject_rules(
    preflight_docs: list[tuple[Path, dict[str, Any]]],
    anon_desk_reasons: list[str],
    novelty_doc: dict[str, Any] | None,
    policy_doc: dict[str, Any] | None,
) -> dict[str, Any]:
    reasons: list[str] = list(anon_desk_reasons)
    warnings: list[str] = []
    preflight_summaries: list[dict[str, Any]] = []

    for path, doc in preflight_docs:
        schema = str(doc.get("schema") or "")
        verdict = str(doc.get("verdict") or "")
        summary = doc.get("summary") if isinstance(doc.get("summary"), dict) else {}
        err_count = summary.get("ERROR", 0)
        warn_count = summary.get("WARN", 0)
        if isinstance(err_count, bool) or type(err_count) is not int:
            err_count = 0
        if isinstance(warn_count, bool) or type(warn_count) is not int:
            warn_count = 0
        findings = [f for f in (doc.get("findings") or []) if isinstance(f, dict)]
        err_findings = [f for f in findings if str(f.get("severity") or "").upper() == "ERROR"]
        is_fail = verdict == "FAIL" or err_count > 0 or bool(err_findings)
        if is_fail:
            checks = sorted({str(f.get("check") or schema or "preflight_error") for f in err_findings}) or [verdict or "FAIL"]
            reasons.append(f"preflight_fail({path.name}):{','.join(checks[:4])}")
        elif verdict == "PASS_WITH_WARNINGS" or warn_count > 0:
            warnings.append(f"preflight_warn({path.name}):{warn_count}_warnings")
        preflight_summaries.append({
            "file": str(path),
            "schema": schema,
            "verdict": verdict,
            "error_count": err_count,
            "warn_count": warn_count,
        })

    timeline_conflicts: list[dict[str, Any]] = []
    if isinstance(novelty_doc, dict):
        if novelty_doc.get("dual_submission_conflict") is True:
            reasons.append("venue_novelty:dual_submission_conflict")
        hc = novelty_doc.get("hard_constraints")
        if isinstance(hc, dict) and hc.get("eligibility") == "failed":
            reasons.append("venue_novelty:eligibility_constraint_failed")
        sr = novelty_doc.get("submission_readiness")
        if isinstance(sr, dict) and "eligibility" in (sr.get("failed_constraints") or []):
            reasons.append("venue_novelty:eligibility_constraint_failed")
        vpr = novelty_doc.get("venue_portfolio_recommendations")
        if isinstance(vpr, dict):
            t_confs = [c for c in (vpr.get("timeline_conflicts") or []) if isinstance(c, dict)]
            timeline_conflicts.extend(t_confs)
            if t_confs and not (vpr.get("recommended_now") or []):
                reasons.append("venue_portfolio:timeline_conflict_without_conflict_free_primary")

    policy_summary: dict[str, Any] | None = None
    if isinstance(policy_doc, dict):
        page_count = policy_doc.get("page_count")
        page_limit = policy_doc.get("page_limit")
        if page_count is not None and page_limit is not None:
            pc = _check_num_no_bool(page_count, "submission_policy.page_count", lo=0)
            pl = _check_num_no_bool(page_limit, "submission_policy.page_limit", lo=0)
            if pc > pl:
                reasons.append(f"desk_reject:page_limit_exceeded({pc}>{pl})")
        if policy_doc.get("page_limit_exceeded") is True:
            reasons.append("desk_reject:page_limit_exceeded")

        if policy_doc.get("template_mismatch") is True or policy_doc.get("template_valid") is False:
            reasons.append("desk_reject:template_mismatch")
        tmpl = policy_doc.get("template")
        exp_tmpl = policy_doc.get("expected_template")
        if isinstance(tmpl, str) and isinstance(exp_tmpl, str) and tmpl.strip() and exp_tmpl.strip():
            if tmpl.strip().lower() != exp_tmpl.strip().lower():
                reasons.append(f"desk_reject:template_mismatch({tmpl.strip()}!={exp_tmpl.strip()})")

        if policy_doc.get("mandatory_checklist_missing") is True or policy_doc.get("checklist_complete") is False:
            reasons.append("desk_reject:mandatory_checklist_missing")
        missing_chk = policy_doc.get("missing_checklists") or policy_doc.get("missing_checklist_items") or []
        if isinstance(missing_chk, list) and missing_chk:
            reasons.append(f"desk_reject:mandatory_checklist_missing({','.join(str(x) for x in missing_chk[:4])})")

        if policy_doc.get("anonymization_leak") is True or policy_doc.get("anonymized") is False:
            reasons.append("desk_reject:anonymization_leak")

        sim_allowed = policy_doc.get("simultaneous_submission_allowed")
        if policy_doc.get("dual_submission_conflict") is True or (
            policy_doc.get("already_submitted_elsewhere") is True and sim_allowed is False
        ):
            reasons.append("desk_reject:dual_submission_conflict")

        policy_summary = dict(policy_doc)

    unique_reasons = sorted(set(reasons))
    return {
        "blocked": bool(unique_reasons),
        "reasons": unique_reasons,
        "warnings": sorted(set(warnings)),
        "preflight_checks": preflight_summaries,
        "artifact_anonymization": anon_desk_reasons,
        "timeline_conflicts": timeline_conflicts,
        "submission_policy": policy_summary,
    }


def _norm_tok(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").strip().lower()).strip()


_NON_MAIN_TRACK_TOKENS = frozenset({
    "findings",
    "workshop",
    "workshops",
    "ws",
    "demo",
    "demos",
    "doctoral",
    "srw",
    "poster",
    "posters",
    "industry",
    "tutorial",
    "tutorials",
    "datasets",
    "benchmark",
    "benchmarks",
})


def _target_matches_conflicted_id(
    tv_norm: str,
    cid: Any,
    *,
    venue_name: Any = None,
    track: Any = None,
) -> bool:
    if not tv_norm:
        return False
    if isinstance(cid, str) and "::" in cid:
        parts = [_norm_tok(p) for p in cid.split("::")]
        p_name = parts[0] if parts else ""
        p_ed = parts[1] if len(parts) >= 2 else ""
        p_track = parts[2] if len(parts) >= 3 else ""
        if p_name:
            if p_track and p_track != "main":
                expected = p_name if p_track in p_name.split() else f"{p_name} {p_track}".strip()
                return tv_norm in {expected, _norm_tok(cid)}
            return tv_norm in {p_name, f"{p_name} main", f"{p_name} {p_ed}".strip(), _norm_tok(cid)}

    vn_norm = _norm_tok(venue_name)
    tr_norm = _norm_tok(track)
    if tr_norm and tr_norm != "main" and vn_norm:
        allowed = {vn_norm} if tr_norm in vn_norm.split() else {f"{vn_norm} {tr_norm}".strip()}
        if _norm_tok(cid):
            allowed.add(_norm_tok(cid))
        return tv_norm in allowed
    if vn_norm and (tv_norm == vn_norm or tv_norm == f"{vn_norm} main"):
        return True

    cid_norm = _norm_tok(cid)
    if not cid_norm:
        return False
    if cid_norm == tv_norm or cid_norm == f"{tv_norm} main":
        return True
    tv_tokens = set(tv_norm.split())
    conflict_tokens = _NON_MAIN_TRACK_TOKENS - tv_tokens
    main_prefix = f"{tv_norm} main "
    if cid_norm.startswith(main_prefix):
        rest_tokens = cid_norm[len(main_prefix):].split()
        return not any(tok in conflict_tokens for tok in rest_tokens)
    ym = re.match(rf"^{re.escape(tv_norm)}\s+20\d\d(?:\s+(.*))?$", cid_norm)
    if ym:
        rest_tokens = (ym.group(1) or "").split()
        return not any(tok in conflict_tokens for tok in rest_tokens)
    return False


def _match_venue_report(
    doc: dict[str, Any],
    ve: dict[str, Any],
    total_venues: int,
    *,
    all_venues: list[dict[str, Any]] | None = None,
) -> bool:
    doc_vid = _norm_tok(doc.get("venue_id"))
    ve_vid = _norm_tok(ve.get("venue_id"))
    if doc_vid and ve_vid:
        return doc_vid == ve_vid

    doc_venue = _norm_tok(doc.get("venue") or doc.get("venue_name"))
    ve_name = _norm_tok(ve.get("venue_name"))
    if total_venues == 1 and ve_name == "target venue" and ve_vid in ("target venue", "primary", ""):
        return True
    ve_track = _norm_tok(ve.get("track"))
    ve_edition = _norm_tok(ve.get("edition"))
    if doc_venue:
        doc_ed = _norm_tok(doc.get("edition"))
        if doc_ed and ve_edition and doc_ed != ve_edition:
            return False
        doc_tr = _norm_tok(doc.get("track"))
        if doc_tr and ve_track and doc_tr != ve_track:
            return False

        if not doc_tr and ve_name and ve_track and ve_track != "main" and all_venues:
            has_same_name_main = any(
                other is not ve
                and _norm_tok(other.get("venue_name")) == ve_name
                and _norm_tok(other.get("track")) in ("", "main")
                for other in all_venues
            )
            if has_same_name_main:
                return False

        doc_variants = {doc_venue}
        if doc_tr:
            doc_variants.add(f"{doc_venue} {doc_tr}")
        if doc_ed:
            doc_variants.add(f"{doc_venue} {doc_ed}")
        if doc_ed and doc_tr:
            doc_variants.add(f"{doc_venue} {doc_ed} {doc_tr}")
            doc_variants.add(f"{doc_venue} {doc_tr} {doc_ed}")
        if not ve_name and not doc_tr:
            doc_variants.add(f"{doc_venue} main")
            if doc_ed:
                doc_variants.add(f"{doc_venue} {doc_ed} main")
                doc_variants.add(f"{doc_venue} main {doc_ed}")

        ve_variants: set[str] = set()
        if ve_name:
            ve_variants.add(ve_name)
            if ve_track:
                ve_variants.add(f"{ve_name} {ve_track}")
            if ve_edition:
                ve_variants.add(f"{ve_name} {ve_edition}")
            if ve_edition and ve_track:
                ve_variants.add(f"{ve_name} {ve_edition} {ve_track}")
                ve_variants.add(f"{ve_name} {ve_track} {ve_edition}")
        if ve_vid:
            ve_variants.add(ve_vid)
            if not ve_name and not doc_ed:
                vid_no_year = re.sub(r"\b20\d\d\b", " ", ve_vid).strip()
                vid_no_year = re.sub(r"\s+", " ", vid_no_year)
                if vid_no_year:
                    ve_variants.add(vid_no_year)

        return bool(doc_variants & ve_variants)

    return total_venues == 1


def _venue_plan_failures(plan: dict[str, Any]) -> list[str]:
    fails: list[str] = []
    raw_si = plan.get("source_issues") or []
    if raw_si:
        for si in raw_si:
            issue = si.get("issue") if isinstance(si, dict) else str(si)
            fails.append(f"venue_plan_source_issue:{issue}")
    si_total = plan.get("source_issues_total")
    if type(si_total) is int and si_total > len(raw_si):
        fails.append(f"venue_plan_source_issue:truncated_count_{si_total}")
    cfp_v = plan.get("cfp_verified")
    if cfp_v is not None and type(cfp_v) is not bool:
        raise ValueError("venue_plan.cfp_verified must be boolean or null")
    if cfp_v is not True:
        fails.append("venue_plan:cfp_unverified")
    wb = plan.get("within_budget")
    if wb is not None and type(wb) is not bool:
        raise ValueError("venue_plan.within_budget must be boolean or null")
    if wb is False:
        fails.append("venue_plan:over_budget")
    elif wb is not True:
        fails.append("venue_plan:within_budget_unverified")
    if plan.get("missing_mandatory_costs"):
        fails.append(f"venue_plan:missing_mandatory_costs({','.join(str(x) for x in plan['missing_mandatory_costs'][:3])})")
    if plan.get("unverified_fee_evidence"):
        fails.append(f"venue_plan:unverified_fee_evidence({','.join(str(x) for x in plan['unverified_fee_evidence'][:3])})")
    if plan.get("stale_fee_evidence"):
        fails.append(f"venue_plan:stale_fee_evidence({','.join(str(x) for x in plan['stale_fee_evidence'][:3])})")
    bw = plan.get("backward_schedule")
    bw_status = bw.get("status") if isinstance(bw, dict) else None
    top_sched_status = plan.get("schedule_status")
    if top_sched_status is not None and not isinstance(top_sched_status, str):
        raise ValueError("venue_plan.schedule_status must be a string or null")
    for sched_status in (bw_status, top_sched_status):
        if sched_status in PLAN_BAD_BACKWARD_STATUSES:
            fails.append(f"venue_plan:backward_schedule_{sched_status}")
    for w in (plan.get("warnings") or []):
        ws = str(w)
        if ws.startswith(PLAN_DISQUALIFYING_WARNING_PREFIXES) or "deadline_already_passed" in ws:
            fails.append(f"venue_plan_warning:{ws}")
    return sorted(set(fails))


def _venue_sources_failures(src: dict[str, Any]) -> list[str]:
    fails: list[str] = []
    if src.get("verification_passed") is False:
        fails.append("venue_sources:verification_failed")
    sts = src.get("source_text_status")
    if sts == "verification_blocked":
        fails.append("venue_sources:verification_blocked")
    elif isinstance(sts, str) and sts and sts != "all_supplied_critical_quotes_found":
        fails.append(f"venue_sources:{sts}")
    blk_issues = src.get("blocking_source_issues") or []
    for bi in blk_issues:
        issue = bi.get("issue") if isinstance(bi, dict) else str(bi)
        fails.append(f"venue_sources_blocking:{issue}")
    blk_total = src.get("blocking_source_issues_total")
    if not blk_issues and type(blk_total) is int and blk_total > 0:
        fails.append("venue_sources_blocking:truncated")
    crit_missing = src.get("critical_fields_without_matched_quote") or []
    if crit_missing:
        fails.append(f"venue_sources:missing_critical_quotes({','.join(str(c) for c in crit_missing[:4])})")
    elif type(src.get("critical_fields_total")) is int and src["critical_fields_total"] > 0:
        fails.append("venue_sources:missing_critical_quotes_truncated")
    seen_claim_fails = False
    for cl in list(src.get("claims") or []) + list(src.get("failed_claims") or []):
        if isinstance(cl, dict) and cl.get("status") and cl.get("status") != "quote_found":
            fails.append(f"venue_sources_claim:{cl.get('field', 'claim')}:{cl['status']}")
            seen_claim_fails = True
    cc = src.get("claim_counts")
    if not seen_claim_fails and isinstance(cc, dict) and type(cc.get("failed")) is int and cc["failed"] > 0:
        fails.append(f"venue_sources_claim:failed_count_{cc['failed']}")
    return sorted(set(fails))


_LOWER_TIER_SINGLE_TOKENS = frozenset({
    "ws", "workshop", "workshops", "preliminary", "doctoral",
    "demo", "demos", "poster", "posters", "srw",
    "q2", "q3", "tierb", "tierc", "ccfc",
})
_SLUG_STOP_PREFIX_TOKENS = frozenset({
    "the", "acm", "ieee", "usenix", "sig", "conf", "eval", "target", "test",
    "international", "conference", "journal", "proceedings", "advances", "transactions",
    "annual", "symposium", "meeting", "of", "on", "in", "and", "for",
})


def _lookup_venue_leads_tier(
    vname_raw: str,
    vtrack_raw: str = "",
    *,
    refs: dict[str, Any] | None = None,
) -> str | None:
    if not isinstance(vname_raw, str) or not vname_raw.strip():
        return None
    vname_norm = vname_raw.replace("_", " ").strip()
    vtrack_norm = vtrack_raw.replace("_", " ").strip() if isinstance(vtrack_raw, str) else ""
    if resolve_venue_tier(venue_name=vname_norm, track=vtrack_norm) is not None:
        return None
    if _has_lower_tier_tokens("", vname_raw, vtrack_raw):
        return None
    toks = [t for t in re.split(r"[^a-z0-9]+", f"{vname_raw} {vtrack_raw}".lower()) if t]
    if "findings" in toks:
        return None

    eff_refs = refs if refs is not None else load_venue_quality_refs()
    candidates: list[str] = []
    seen_c: set[str] = set()

    def _add_cand(s: str) -> None:
        cs = re.sub(r"\s+", " ", s).strip()
        if cs and cs.lower() not in seen_c:
            seen_c.add(cs.lower())
            candidates.append(cs)

    _add_cand(vname_raw)
    _add_cand(vname_norm)
    slug_head = re.split(
        r"\s+(?:main|track|venue|id|(?:19|20)\d{2}|\d{1,3})\b",
        vname_norm,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    _add_cand(slug_head)
    if "_" in vname_raw and " " not in vname_raw.strip():
        slug_parts = [p for p in vname_norm.split() if p]
        for k in range(min(len(slug_parts) - 1, 5), 0, -1):
            sub = " ".join(slug_parts[:k])
            if k == 1 and sub.lower() in _SLUG_STOP_PREFIX_TOKENS:
                continue
            _add_cand(sub)

    for cand in candidates:
        res = lookup_venue_quality(cand, refs=eff_refs)
        qt = str((res or {}).get("quality_tier") or "").strip().upper()
        if qt in ("S", "A", "B", "C"):
            return resolve_venue_tier(venue_name=vname_norm, track=vtrack_norm, quality_tier=qt)
    return None


def _compatible_venue_type(vtype: str | None, vtier: str | None) -> str | None:
    if vtype not in VENUE_TYPE_PROFILES:
        return None
    prof_tier = VENUE_TYPE_PROFILES[vtype]["venue_tier"]
    if vtier is None or prof_tier == vtier:
        return vtype
    if (
        vtype != "workshop_preliminary"
        and vtier in VENUE_TIER_FLOORS
        and prof_tier in VENUE_TIER_FLOORS
        and VENUE_TIER_FLOORS[vtier]["rank"] <= VENUE_TIER_FLOORS[prof_tier]["rank"]
    ):
        return vtype
    return None


def _has_lower_tier_tokens(vid_str: str, vname: str = "", vtrack: str = "") -> bool:
    combined = f"{vid_str} {vname} {vtrack}".lower()
    tokens = [t for t in re.split(r"[^a-z0-9]+", combined) if t]
    if any(t in _LOWER_TIER_SINGLE_TOKENS for t in tokens):
        return True
    for a, b in zip(tokens, tokens[1:]):
        if (
            (a == "tier" and b in ("b", "c"))
            or (a == "ccf" and b == "c")
            or (a == "extended" and b in ("abstract", "abstracts"))
        ):
            return True
    return False


def _evaluate_venue_portfolio(
    novelty_doc: dict[str, Any] | None,
    plan_docs: list[tuple[Path, dict[str, Any]]],
    source_docs: list[tuple[Path, dict[str, Any]]],
    *,
    target_venue: str | None,
    target_venue_tier: str | None,
    post_cap_weighted: str | None,
    post_cap_ratings: dict[str, int | None] | None,
    is_idea: bool,
    cross_tool_fatal: bool,
    score_fatal: bool,
    desk_reject_blocked: bool,
    venue_type: str | None = None,
) -> dict[str, Any]:
    raw_venues: list[dict[str, Any]] = []
    timeline_conflicts: list[dict[str, Any]] = []
    portfolio_invalid_reasons: list[str] = []
    rmt_top_vid: str | None = None

    nv_vtype_raw = None
    if isinstance(novelty_doc, dict):
        nv_vtp = novelty_doc.get("venue_type_profile") if isinstance(novelty_doc.get("venue_type_profile"), dict) else {}
        nv_vobj = novelty_doc.get("venue") if isinstance(novelty_doc.get("venue"), dict) else {}
        nv_vtype_raw = (
            novelty_doc.get("venue_type")
            or novelty_doc.get("venue_profile")
            or nv_vtp.get("venue_type")
            or nv_vobj.get("venue_type")
            or nv_vobj.get("venue_profile")
        )
    nv_vtype = resolve_venue_type(nv_vtype_raw) if nv_vtype_raw is not None else None
    sc_vtype = resolve_venue_type(venue_type) if venue_type is not None else None
    eff_vtype = nv_vtype or sc_vtype
    venue_refs = load_venue_quality_refs()
    explicit_target_tier = resolve_venue_tier(venue_name=target_venue, tier_expectation=target_venue_tier)
    if explicit_target_tier is None and target_venue:
        explicit_target_tier = _lookup_venue_leads_tier(target_venue, refs=venue_refs)
    tv_toks = _norm_tok(target_venue).split() if target_venue else []

    def _matches_target_prefix(vid_str: str, vname_str: str) -> bool:
        if not tv_toks:
            return False
        for cand_s in (vname_str, vid_str):
            c_toks = _norm_tok(cand_s).split()
            if c_toks[:len(tv_toks)] == tv_toks:
                return True
        return False

    def _split_vid_entry(entry: dict[str, Any]) -> dict[str, Any]:
        vid_raw = entry.get("venue_id")
        if not entry.get("venue_name") and isinstance(vid_raw, str) and "::" in vid_raw:
            parts = [p.strip() for p in vid_raw.split("::")]
            if parts and parts[0]:
                entry["venue_name"] = parts[0]
            if len(parts) >= 2 and parts[1] and not entry.get("edition"):
                entry["edition"] = parts[1]
            if len(parts) >= 3 and parts[2] and not entry.get("track"):
                entry["track"] = parts[2]
        return entry

    if isinstance(novelty_doc, dict):
        if (
            novelty_doc.get("mode") == "portfolio"
            or isinstance(novelty_doc.get("venue_evaluations"), list)
            or isinstance(novelty_doc.get("venue_summaries"), list)
        ):
            if novelty_doc.get("status") == "invalid":
                portfolio_invalid_reasons.append("venue_novelty_portfolio:status_invalid")
            top_errs = [str(e) for e in (novelty_doc.get("errors") or []) if str(e).strip()]
            for e in top_errs[:5]:
                portfolio_invalid_reasons.append(f"venue_novelty_portfolio_error:{e}")
            if not top_errs and type(novelty_doc.get("error_count")) is int and novelty_doc["error_count"] > 0:
                portfolio_invalid_reasons.append(f"venue_novelty_portfolio:error_count_{novelty_doc['error_count']}")
            if isinstance(novelty_doc.get("venue_evaluations"), list):
                for ve in novelty_doc["venue_evaluations"]:
                    if isinstance(ve, dict):
                        raw_venues.append(dict(ve))
            elif isinstance(novelty_doc.get("venue_summaries"), list) or novelty_doc.get("mode") == "portfolio":
                for vs in (novelty_doc.get("venue_summaries") or []):
                    if isinstance(vs, dict):
                        raw_venues.append(_split_vid_entry(dict(vs)))
            vpr = novelty_doc.get("venue_portfolio_recommendations")
            if isinstance(vpr, dict):
                timeline_conflicts = [c for c in (vpr.get("timeline_conflicts") or []) if isinstance(c, dict)]
                p_verdict = str(vpr.get("portfolio_verdict") or "")
                if p_verdict in (
                    "invalid_portfolio_too_few_venues",
                    "no_verified_viable_venues",
                    "no_viable_venue_in_portfolio",
                    "hold_for_rework",
                ):
                    portfolio_invalid_reasons.append(f"venue_novelty_portfolio_verdict:{p_verdict}")
                rmt = vpr.get("recommended_matched_tier") if isinstance(vpr.get("recommended_matched_tier"), dict) else {}
                top_vid = str(rmt.get("top_venue_id") or "").strip()
                rmt_top_vid = top_vid or None
                if not isinstance(novelty_doc.get("venue_evaluations"), list):
                    venue_summaries = novelty_doc.get("venue_summaries") or []
                    seen_ids = {str(rv.get("venue_id")) for rv in raw_venues if rv.get("venue_id")}
                    rej_from = {str(x) for x in (rmt.get("retargeted_from_rejected_venues") or [])}
                    matched_t = rmt.get("matched_tier")
                    if (
                        not rej_from
                        and p_verdict == "retargeted_to_matched_tier"
                        and not (vpr.get("recommended_now") or [])
                    ):
                        rej_below_items = [
                            b_item.get("venue_id") if isinstance(b_item, dict) else (str(b_item) if isinstance(b_item, str) else "")
                            for b_item in (vpr.get("rejected_below_venue_tier") or [])
                        ]
                        rej_below_items = [x for x in rej_below_items if x]
                        if rej_below_items:
                            rej_from = {rej_below_items[0]}
                    bucket_map = (
                        ("recommended_now", "recommended_now"),
                        ("viable_fallback", "viable_fallback"),
                        ("stretch_high_risk", "stretch_high_risk"),
                        ("conflicted_fallback", "conflicted_fallback"),
                        ("rejected_below_venue_tier", "rejected_below_venue_tier"),
                        ("blocked_hold_for_rework", "hold_for_rework"),
                        ("hold_for_rework", "hold_for_rework"),
                        ("disqualified", "disqualified"),
                        ("withheld_unverified", "withheld_unverified"),
                    )

                    def _assign_vpr_bucket_tier(entry: dict[str, Any], vid_str: str, bucket_key: str) -> dict[str, Any]:
                        split_e = _split_vid_entry(entry)
                        vname_raw = str(split_e.get("venue_name") or vid_str)
                        vtrack_raw = str(split_e.get("track") or "")
                        res_t = resolve_venue_tier(
                            venue_name=vname_raw.replace("_", " "),
                            track=vtrack_raw.replace("_", " "),
                        )
                        if res_t is not None:
                            split_e["venue_tier"] = res_t
                            toks = re.split(r"[^a-z0-9]+", f"{vid_str} {vname_raw} {vtrack_raw}".lower())
                            if (
                                res_t == "q1_or_tier_a"
                                and eff_vtype == "journal_q1"
                                and not _has_lower_tier_tokens(vid_str, vname_raw, vtrack_raw)
                                and "findings" not in toks
                                and (
                                    (top_vid and vid_str == top_vid and matched_t == "top_tier_flagship")
                                    or bucket_key in ("recommended_now", "stretch_high_risk")
                                    or (split_e.get("role") == "primary" and _matches_target_prefix(vid_str, vname_raw))
                                )
                            ):
                                split_e["venue_tier"] = "top_tier_flagship"
                            return split_e

                        if _has_lower_tier_tokens(vid_str, vname_raw, vtrack_raw):
                            return split_e

                        leads_t = _lookup_venue_leads_tier(vname_raw, vtrack_raw, refs=venue_refs)
                        if leads_t is not None:
                            split_e["venue_tier"] = leads_t
                            return split_e

                        is_primary_or_rec = (
                            bucket_key in ("recommended_now", "stretch_high_risk")
                            or (top_vid and vid_str == top_vid)
                            or (split_e.get("role") == "primary" and _matches_target_prefix(vid_str, vname_raw))
                        )
                        if not is_primary_or_rec:
                            return split_e

                        if top_vid and vid_str == top_vid and matched_t in VENUE_TIER_FLOORS:
                            split_e["venue_tier"] = matched_t
                        elif explicit_target_tier in VENUE_TIER_FLOORS and _matches_target_prefix(vid_str, vname_raw):
                            split_e["venue_tier"] = explicit_target_tier
                        elif matched_t in VENUE_TIER_FLOORS:
                            split_e["venue_tier"] = matched_t
                        elif eff_vtype in VENUE_TYPE_PROFILES and eff_vtype != "workshop_preliminary":
                            split_e["venue_tier"] = VENUE_TYPE_PROFILES[eff_vtype]["venue_tier"]
                        return split_e

                    for b_key, cls_lbl in bucket_map:
                        for b_item in (vpr.get(b_key) or []):
                            vid_s = b_item.get("venue_id") if isinstance(b_item, dict) else (str(b_item) if isinstance(b_item, str) else "")
                            if not vid_s or vid_s in seen_ids:
                                continue
                            seen_ids.add(vid_s)
                            synth: dict[str, Any] = {
                                "venue_id": vid_s,
                                "classification": cls_lbl,
                                "role": "primary" if (vid_s in rej_from or b_key == "recommended_now") else "fallback",
                                "_from_vpr_bucket": True,
                            }
                            raw_venues.append(_assign_vpr_bucket_tier(synth, vid_s, b_key))

                    if not venue_summaries and top_vid and top_vid not in seen_ids:
                        seen_ids.add(top_vid)
                        has_rec_now = bool(vpr.get("recommended_now"))
                        has_viable_fb = bool(vpr.get("viable_fallback"))
                        has_stretch = bool(vpr.get("stretch_high_risk"))
                        if has_rec_now and not rej_from:
                            top_cls = "recommended_now"
                        elif has_viable_fb or has_rec_now or rej_from:
                            top_cls = "viable_fallback"
                        elif has_stretch:
                            top_cls = "stretch_high_risk"
                        else:
                            top_cls = "viable_fallback"
                        synth_top: dict[str, Any] = {
                            "venue_id": top_vid,
                            "classification": top_cls,
                            "role": "primary" if top_vid in rej_from else "fallback",
                            "_from_vpr_bucket": True,
                        }
                        raw_venues.append(_assign_vpr_bucket_tier(synth_top, top_vid, top_cls))

                    if not venue_summaries:
                        for rv_item in (rmt.get("recommended_venues") or []):
                            vid_r = str(rv_item or "").strip() if isinstance(rv_item, str) else ""
                            if not vid_r or vid_r in seen_ids:
                                continue
                            seen_ids.add(vid_r)
                            rv_cls = "recommended_now" if (not vpr.get("recommended_now") and not rej_from) else "viable_fallback"
                            synth_rv: dict[str, Any] = {
                                "venue_id": vid_r,
                                "classification": rv_cls,
                                "role": "primary" if vid_r in rej_from else "fallback",
                                "_from_vpr_bucket": True,
                            }
                            raw_venues.append(_assign_vpr_bucket_tier(synth_rv, vid_r, rv_cls))
        elif "submission_readiness" in novelty_doc or "venue" in novelty_doc:
            v_info = novelty_doc.get("venue") if isinstance(novelty_doc.get("venue"), dict) else {}
            vqc = novelty_doc.get("venue_quality_context") if isinstance(novelty_doc.get("venue_quality_context"), dict) else {}
            sr = novelty_doc.get("submission_readiness") if isinstance(novelty_doc.get("submission_readiness"), dict) else {}
            v_name = v_info.get("name") or sr.get("venue_name") or vqc.get("matched_name") or target_venue
            v_track = v_info.get("track") or ""
            v_ed = str(v_info.get("edition") or "")
            if not v_name:
                inferred_names = [
                    str(d.get("venue") or d.get("venue_name")).strip()
                    for _, d in (*plan_docs, *source_docs)
                    if isinstance(d, dict) and str(d.get("venue") or d.get("venue_name") or "").strip()
                ]
                if len({_norm_tok(n) for n in inferred_names if _norm_tok(n)}) == 1:
                    v_name = inferred_names[0]
            if not v_track:
                inferred_tracks = [
                    str(d.get("track")).strip()
                    for _, d in (*plan_docs, *source_docs)
                    if isinstance(d, dict) and str(d.get("track") or "").strip()
                ]
                if len({_norm_tok(t) for t in inferred_tracks if _norm_tok(t)}) == 1:
                    v_track = inferred_tracks[0]
            if not v_ed:
                inferred_eds = [
                    str(d.get("edition")).strip()
                    for _, d in (*plan_docs, *source_docs)
                    if isinstance(d, dict) and str(d.get("edition") or "").strip()
                ]
                if len({_norm_tok(e) for e in inferred_eds if _norm_tok(e)}) == 1:
                    v_ed = inferred_eds[0]
            v_name = v_name or "target_venue"
            single_vtype = nv_vtype or sc_vtype
            v_tier = sr.get("venue_tier") or resolve_venue_tier(
                venue_name=v_name,
                track=v_track,
                quality_tier=v_info.get("quality_tier") or vqc.get("quality_tier"),
                tier_expectation=target_venue_tier or v_info.get("tier_expectation"),
            ) or _lookup_venue_leads_tier(v_name, v_track, refs=venue_refs)
            if v_tier is None and single_vtype in VENUE_TYPE_PROFILES:
                v_tier = VENUE_TYPE_PROFILES[single_vtype]["venue_tier"]
            verdict = sr.get("verdict")
            ready = sr.get("ready_to_submit")
            cls_name = "recommended_now" if (ready and novelty_doc.get("status") != "invalid") else (
                "rejected_below_venue_tier" if verdict == "rejected_below_venue_tier" else "disqualified"
            )
            single_errs = list(novelty_doc.get("errors") or [])
            if not single_errs and type(novelty_doc.get("error_count")) is int and novelty_doc["error_count"] > 0:
                single_errs = [f"venue_novelty:error_count_{novelty_doc['error_count']}"]
            if novelty_doc.get("status") not in (None, "structurally_checked") and ready is None:
                single_errs.append(f"venue_novelty:status_{novelty_doc['status']}")
            raw_venues.append({
                "venue_id": v_info.get("venue_id") or _norm_tok(v_name).replace(" ", "_") or "primary",
                "venue_name": v_name,
                "edition": v_ed,
                "track": v_track,
                "role": "primary",
                "venue_tier": v_tier,
                "venue_type": _compatible_venue_type(single_vtype, v_tier),
                "classification": cls_name,
                "fit_score_out_of_10": novelty_doc.get("fit_score_out_of_10", sr.get("fit_score_out_of_10")),
                "novelty_comparison": novelty_doc.get("novelty_comparison"),
                "venue_contribution_bar": novelty_doc.get("venue_contribution_bar"),
                "submission_readiness": sr,
                "disqualification_reasons": single_errs + (
                    [f"single_venue_verdict:{verdict}"] if verdict in DISQUALIFYING_SINGLE_VERDICTS else []
                ),
                "rejection_reasons": list(sr.get("tier_rejection_reasons") or []),
                "upgrade_gaps_to_target_tier": dict(sr.get("upgrade_gaps_to_target_tier") or {}),
            })

    # If no compare_venue_novelty supplied, synthesize candidate venue entries from venue_plan / venue_sources / target_venue
    if not raw_venues and (plan_docs or source_docs or target_venue):
        synth_name = target_venue
        if not synth_name and plan_docs:
            synth_name = plan_docs[0][1].get("venue")
        if not synth_name and source_docs:
            synth_name = source_docs[0][1].get("venue")
        synth_name = synth_name or "target_venue"
        synth_track = (plan_docs[0][1].get("track") if plan_docs else None) or ""
        synth_ed = str((plan_docs[0][1].get("edition") if plan_docs else None) or "")
        synth_tier = resolve_venue_tier(venue_name=synth_name, track=synth_track, tier_expectation=target_venue_tier)
        if synth_tier is None:
            synth_tier = _lookup_venue_leads_tier(synth_name, synth_track, refs=venue_refs)
        if synth_tier is None and eff_vtype in VENUE_TYPE_PROFILES:
            synth_tier = VENUE_TYPE_PROFILES[eff_vtype]["venue_tier"]
        raw_venues.append({
            "venue_id": _norm_tok(synth_name).replace(" ", "_") or "primary",
            "venue_name": synth_name,
            "edition": synth_ed,
            "track": synth_track,
            "role": "primary",
            "venue_tier": synth_tier,
            "venue_type": _compatible_venue_type(eff_vtype, synth_tier),
            "classification": "recommended_now",
            "fit_score_out_of_10": None,
            "disqualification_reasons": [],
            "rejection_reasons": [],
            "upgrade_gaps_to_target_tier": {},
        })

    # Compute post-cap baseline matched tier for the paper itself
    target_nov = post_cap_ratings.get("novelty") if isinstance(post_cap_ratings, dict) else None
    eff_target_tier = explicit_target_tier
    if eff_target_tier is None and eff_vtype in VENUE_TYPE_PROFILES:
        eff_target_tier = VENUE_TYPE_PROFILES[eff_vtype]["venue_tier"]
    paper_vtype = _compatible_venue_type(eff_vtype, eff_target_tier)
    paper_tier_fit = evaluate_venue_tier_fit(
        eff_target_tier,
        weighted_unrounded=post_cap_weighted,
        ratings=post_cap_ratings,
        is_idea=is_idea,
        target_novelty=target_nov,
        venue_type=paper_vtype,
    )
    post_cap_matched_tier = paper_tier_fit.get("recommended_matched_tier")
    if cross_tool_fatal or score_fatal:
        post_cap_matched_tier = "none_hold_for_rework"
    elif post_cap_matched_tier is None and isinstance(novelty_doc, dict):
        tr_fb = novelty_doc.get("target_readiness") if isinstance(novelty_doc.get("target_readiness"), dict) else {}
        vpr_fb = novelty_doc.get("venue_portfolio_recommendations") if isinstance(novelty_doc.get("venue_portfolio_recommendations"), dict) else {}
        rmt_fb = vpr_fb.get("recommended_matched_tier") if isinstance(vpr_fb.get("recommended_matched_tier"), dict) else {}
        post_cap_matched_tier = tr_fb.get("recommended_matched_tier") or rmt_fb.get("matched_tier")

    surviving: list[dict[str, Any]] = []
    disqualified: list[dict[str, Any]] = []
    evaluated: list[dict[str, Any]] = []
    total_v = len(raw_venues)

    for ve in raw_venues:
        vid = str(ve.get("venue_id") or ve.get("venue_name") or "venue")
        vname = str(ve.get("venue_name") or vid)
        vtrack = str(ve.get("track") or "")
        ve_vtype_raw = ve.get("venue_type") or ve.get("venue_profile")
        ve_vtype = resolve_venue_type(ve_vtype_raw) if ve_vtype_raw is not None else None
        vtier = ve.get("venue_tier") or resolve_venue_tier(
            venue_name=vname.replace("_", " "),
            track=vtrack.replace("_", " "),
        )
        if vtier is None:
            vtier = _lookup_venue_leads_tier(vname, vtrack, refs=venue_refs)
        if vtier is None:
            cand_vt = ve_vtype or (eff_vtype if not ve.get("_from_vpr_bucket") else None)
            if cand_vt in VENUE_TYPE_PROFILES:
                vtier = VENUE_TYPE_PROFILES[cand_vt]["venue_tier"]
        orig_cls = str(ve.get("classification") or "recommended_now")

        fail_reasons: list[str] = []
        for k in ("disqualification_reasons", "withholding_reasons", "rejection_reasons"):
            for r in (ve.get(k) or []):
                fail_reasons.append(str(r))

        if orig_cls in DISQUALIFIED_NOVELTY_CLASSIFICATIONS:
            fail_reasons.append(f"venue_novelty_classification:{orig_cls}")

        sr = ve.get("submission_readiness") if isinstance(ve.get("submission_readiness"), dict) else {}
        if sr.get("verdict") in DISQUALIFYING_SINGLE_VERDICTS or sr.get("ready_to_submit") is False:
            fail_reasons.append(f"venue_readiness:{sr.get('verdict') or 'not_ready'}")

        # Match and inspect check_venue_plan docs
        for _, plan in plan_docs:
            if _match_venue_report(plan, ve, total_v, all_venues=raw_venues):
                fail_reasons.extend(_venue_plan_failures(plan))

        # Match and inspect check_venue_sources docs
        for _, src in source_docs:
            if _match_venue_report(src, ve, total_v, all_venues=raw_venues):
                fail_reasons.extend(_venue_sources_failures(src))

        # Post-cap venue tier fit re-evaluation
        nc = ve.get("novelty_comparison") if isinstance(ve.get("novelty_comparison"), dict) else {}
        vcb = ve.get("venue_contribution_bar") if isinstance(ve.get("venue_contribution_bar"), dict) else {}
        panel_med_nov = (
            nc.get("accepted_panel_median_score")
            if nc.get("accepted_panel_median_score") is not None
            else vcb.get("panel_median_novelty")
        )
        if panel_med_nov is not None:
            _parse_finite_decimal(panel_med_nov, "venue_contribution_bar.panel_median_novelty")
        panel_med_ov = vcb.get("panel_median_overall")
        pm_dec = (
            _parse_finite_decimal(panel_med_ov, "venue_contribution_bar.panel_median_overall")
            if panel_med_ov is not None
            else None
        )
        vs_venue_delta = vcb.get("target_vs_venue_overall_delta")
        if vs_venue_delta is not None:
            vs_venue_delta = float(str(_parse_finite_decimal(vs_venue_delta, "venue_contribution_bar.target_vs_venue_overall_delta")))
        if post_cap_weighted is not None and pm_dec is not None:
            pw_dec = _parse_finite_decimal(post_cap_weighted, "post_cap_weighted")
            with localcontext(BasicContext) as ctx:
                ctx.prec = 28
                vs_venue_delta = float(str(pw_dec - pm_dec))
        tr_doc = novelty_doc.get("target_readiness") if isinstance(novelty_doc, dict) and isinstance(novelty_doc.get("target_readiness"), dict) else {}
        v_nov = target_nov if target_nov is not None else nc.get("target_novelty_score", tr_doc.get("target_novelty_score"))
        if target_nov is None and v_nov is not None:
            _check_num_no_bool(v_nov, "novelty_comparison.target_novelty_score")
        raw_call_vtype = ve_vtype or (None if (ve.get("_from_vpr_bucket") and vtier is None) else eff_vtype)
        call_vtype = _compatible_venue_type(raw_call_vtype, vtier)
        v_tier_fit = evaluate_venue_tier_fit(
            vtier,
            weighted_unrounded=post_cap_weighted,
            ratings=post_cap_ratings,
            is_idea=is_idea,
            target_novelty=v_nov,
            panel_median_novelty=panel_med_nov,
            target_vs_venue_overall_delta=vs_venue_delta,
            venue_type=call_vtype,
        )
        if v_tier_fit["rejected_below_venue_tier"]:
            fail_reasons.extend(f"post_cap_tier_fit:{r}" for r in v_tier_fit["rejection_reasons"])

        if portfolio_invalid_reasons:
            fail_reasons.extend(portfolio_invalid_reasons)

        if cross_tool_fatal:
            fail_reasons.append("cross_tool_fatal_gate_triggered")
        if score_fatal:
            fail_reasons.append("score_math_fatal_gate_triggered")

        unique_fails = sorted(set(fail_reasons))
        is_surviving = not unique_fails
        entry = {
            "venue_id": vid,
            "venue_name": vname,
            "edition": ve.get("edition"),
            "track": vtrack,
            "role": ve.get("role"),
            "venue_tier": vtier,
            "original_classification": orig_cls,
            "fit_score_out_of_10": ve.get("fit_score_out_of_10"),
            "surviving": is_surviving,
            "disqualification_reasons": unique_fails,
            "upgrade_gaps_to_target_tier": v_tier_fit.get("upgrade_gaps_to_target_tier") or dict(ve.get("upgrade_gaps_to_target_tier") or {}),
        }
        evaluated.append(entry)
        if is_surviving:
            surviving.append(entry)
        else:
            disqualified.append(entry)

    # Sort surviving venues: recommended_now/viable_fallback before stretch_high_risk,
    # preferring matched tier and highest surviving tier rank (0=flagship .. 3=workshop)
    def _surv_key(item: dict[str, Any]) -> tuple[Any, ...]:
        t = item.get("venue_tier")
        t_rank = VENUE_TIER_FLOORS[t]["rank"] if t in VENUE_TIER_FLOORS else 99
        cls_p = CLASSIFICATION_PRIORITY.get(item.get("original_classification") or "", 9)
        non_stretch = 0 if cls_p in (0, 1) else 1
        tier_match = 0 if (post_cap_matched_tier and t == post_cap_matched_tier) else 1
        is_not_top = 0 if (rmt_top_vid and item.get("venue_id") == rmt_top_vid) else 1
        fit = item.get("fit_score_out_of_10")
        fit_val = -(float(fit)) if isinstance(fit, (int, float)) and not isinstance(fit, bool) else 0.0
        return (non_stretch, tier_match, t_rank, cls_p, is_not_top, fit_val, item["venue_id"])

    surviving.sort(key=_surv_key)

    selected_venue: dict[str, Any] | None = None
    no_viable = False
    retargeted = False
    retargeted_from: str | None = None
    if raw_venues:
        if surviving:
            top = surviving[0]
            primary_candidate = None
            if target_venue:
                tv_norm = _norm_tok(target_venue)
                primary_candidate = next(
                    (
                        v for v in evaluated
                        if tv_norm in (_norm_tok(v["venue_name"]), _norm_tok(v["venue_id"]))
                        or f"{tv_norm} main" == _norm_tok(v["venue_id"])
                    ),
                    None,
                ) or next(
                    (v for v in evaluated if v.get("role") == "primary" and tv_norm in _norm_tok(v["venue_name"])),
                    None,
                ) or next(
                    (v for v in evaluated if tv_norm in _norm_tok(v["venue_name"])),
                    None,
                )
            if primary_candidate is None:
                primary_candidate = next((v for v in evaluated if v.get("role") == "primary"), None)
            if primary_candidate is None and isinstance(novelty_doc, dict):
                vpr_r = novelty_doc.get("venue_portfolio_recommendations") if isinstance(novelty_doc.get("venue_portfolio_recommendations"), dict) else {}
                rmt_r = vpr_r.get("recommended_matched_tier") if isinstance(vpr_r.get("recommended_matched_tier"), dict) else {}
                for r_id in (rmt_r.get("retargeted_from_rejected_venues") or []):
                    primary_candidate = next((v for v in evaluated if v["venue_id"] == str(r_id)), None)
                    if primary_candidate is not None:
                        break
            if primary_candidate is None and evaluated:
                primary_candidate = evaluated[0]
            if primary_candidate and primary_candidate["venue_id"] != top["venue_id"] and not primary_candidate["surviving"]:
                retargeted = True
                retargeted_from = primary_candidate["venue_id"]
            selected_venue = {
                "venue_id": top["venue_id"],
                "venue_name": top["venue_name"],
                "venue_tier": top["venue_tier"],
                "classification": top["original_classification"],
                "fit_score_out_of_10": top["fit_score_out_of_10"],
                "retargeted_from": retargeted_from,
            }
            if desk_reject_blocked:
                # Paper itself is desk-reject blocked even if venue CFP is valid
                pass
        else:
            no_viable = True
    elif portfolio_invalid_reasons:
        no_viable = True

    upgrade_gaps = dict(paper_tier_fit.get("upgrade_gaps_to_target_tier") or {})
    if not upgrade_gaps and disqualified:
        upgrade_gaps = dict(disqualified[0].get("upgrade_gaps_to_target_tier") or {})

    return {
        "has_venues": bool(raw_venues),
        "target_venue": target_venue,
        "target_venue_tier": eff_target_tier,
        "selected_venue": selected_venue,
        "no_viable_venue_in_portfolio": no_viable,
        "portfolio_invalid_reasons": portfolio_invalid_reasons,
        "retargeted": retargeted,
        "retargeted_from": retargeted_from,
        "recommended_matched_tier": post_cap_matched_tier,
        "upgrade_gaps_to_target_tier": upgrade_gaps,
        "surviving_venues": surviving,
        "disqualified_venues": disqualified,
        "evaluations": evaluated,
        "timeline_conflicts": timeline_conflicts,
    }


def _evaluate_subfield_criteria(
    preset: str | None,
    rigor_info: dict[str, Any],
    seed_bundle: dict[str, Any] | None,
    ledger_doc: dict[str, Any] | None,
    sc_doc: dict[str, Any] | None = None,
    post_cap_res: dict[str, Any] | None = None,
    target_id: str | None = None,
) -> dict[str, Any] | None:
    if not preset:
        return None
    spec = SUBFIELD_PRESETS[preset]
    covered: set[str] = set(rigor_info.get("covered_checks") or [])
    if isinstance(seed_bundle, dict):
        eff_sb = (
            seed_bundle["idea_seed_bundle"]
            if isinstance(seed_bundle.get("idea_seed_bundle"), dict) and "seeds" not in seed_bundle
            else seed_bundle
        )
        for seed in (eff_sb.get("seeds") or []):
            if isinstance(seed, dict):
                sv = seed.get("subfield_vetting")
                if isinstance(sv, dict) and sv.get("preset") == preset:
                    covered.update(str(c) for c in (sv.get("covered_checks") or []))
    if isinstance(ledger_doc, dict):
        sc_checks = ledger_doc.get("subfield_checks_covered") or []
        if isinstance(sc_checks, list):
            covered.update(str(c) for c in sc_checks)

    def _merge_subfield_checks_map(raw_map: Any) -> None:
        if not isinstance(raw_map, dict):
            return
        for k, v in raw_map.items():
            if not isinstance(k, str):
                continue
            k_s = k.strip()
            if v is True or (isinstance(v, str) and v.strip().lower() in ("pass", "passed", "verified", "true")):
                covered.add(k_s)
            elif v is False or (isinstance(v, str) and v.strip().lower() in ("fail", "failed", "false")):
                covered.discard(k_s)

    def _merge_subfield_readiness_dict(sfr: Any) -> None:
        if isinstance(sfr, dict) and sfr.get("preset") == preset:
            if isinstance(sfr.get("passed_checks"), list):
                for c in sfr["passed_checks"]:
                    covered.add(str(c))
            elif type(sfr.get("passed_count")) is int and sfr["passed_count"] > 0 and isinstance(sfr.get("missing_checks"), list):
                miss_set = {str(x) for x in sfr["missing_checks"]}
                fail_set = {str(x) for x in (sfr.get("failed_checks") or [])}
                for c in spec["required_checks"]:
                    if c not in miss_set and c not in fail_set:
                        covered.add(c)
            for c in (sfr.get("failed_checks") or []):
                covered.discard(str(c))

    if isinstance(sc_doc, dict):
        _merge_subfield_checks_map(sc_doc.get("subfield_checks"))
        _merge_subfield_readiness_dict(sc_doc.get("subfield_readiness"))
        if target_id and isinstance(sc_doc.get("submission_readiness"), dict):
            tsr = sc_doc["submission_readiness"].get(target_id)
            if isinstance(tsr, dict):
                _merge_subfield_readiness_dict(tsr.get("subfield_readiness"))
        if target_id and isinstance(sc_doc.get("profiles"), list):
            for prof in sc_doc["profiles"]:
                if isinstance(prof, dict) and prof.get("id") == target_id:
                    _merge_subfield_checks_map(prof.get("subfield_checks"))
    if isinstance(post_cap_res, dict):
        _merge_subfield_readiness_dict(post_cap_res.get("subfield_readiness"))

    eng_crit = set((rigor_info.get("engineering_diagnostics") or {}).get("critical_categories") or [])
    for c in spec["critical_rigor_focus"]:
        if c in eng_crit:
            covered.discard(c)
    for fc in (rigor_info.get("failed_checks") or []):
        covered.discard(fc)
    missing = [c for c in spec["required_checks"] if c not in covered]
    return {
        "preset": preset,
        "label": spec["label"],
        "required_checks": list(spec["required_checks"]),
        "covered_checks": sorted(covered),
        "missing_checks": missing,
        "critical_rigor_focus": list(spec["critical_rigor_focus"]),
    }


def _inspect_upstream_downstream(
    gap_doc: dict[str, Any] | None,
    qcard_doc: dict[str, Any] | None,
    seed_bundle: dict[str, Any] | None,
    proj_doc: dict[str, Any] | None,
    triage_doc: dict[str, Any] | None,
    prior_sc_doc: dict[str, Any] | None,
    post_cap_overall: int | None,
    post_cap_weighted: str | None,
    post_cap_ratings: dict[str, int | None] | None,
    target_id: str | None,
    cross_tool_fatal: bool,
    *,
    active_dims: tuple[str, ...] = DIMENSIONS,
) -> dict[str, Any]:
    block_ready = False
    blockers: list[str] = []
    warnings: list[str] = []
    out: dict[str, Any] = {}

    if gap_doc is not None:
        valid = gap_doc.get("valid_structure")
        errs = [str(e) for e in (gap_doc.get("errors") or [])]
        if valid is False or errs:
            block_ready = True
            blockers.append(f"gap_record_invalid:{errs[0] if errs else 'valid_structure=False'}")
        out["gap_record"] = {
            "valid_structure": valid,
            "error_count": len(errs),
            "warnings": list(gap_doc.get("warnings") or [])[:10],
            "gap_tier_ceiling": gap_doc.get("gap_tier_ceiling"),
            "root_cause_barrier": gap_doc.get("root_cause_barrier"),
            "so_what_decision_impact": gap_doc.get("so_what_decision_impact"),
            "durability_12_24m": gap_doc.get("durability_12_24m"),
        }

    if qcard_doc is not None:
        valid = qcard_doc.get("valid_structure")
        errs = [str(e) for e in (qcard_doc.get("errors") or [])]
        if valid is False or errs:
            block_ready = True
            blockers.append(f"question_card_invalid:{errs[0] if errs else 'valid_structure=False'}")
        out["question_card"] = {
            "valid_structure": valid,
            "error_count": len(errs),
            "warnings": list(qcard_doc.get("warnings") or [])[:10],
        }

    if seed_bundle is not None:
        root_tts = seed_bundle.get("trajectory_trees") if isinstance(seed_bundle.get("trajectory_trees"), dict) else None
        eff_bundle = (
            seed_bundle["idea_seed_bundle"]
            if isinstance(seed_bundle.get("idea_seed_bundle"), dict) and "seeds" not in seed_bundle
            else seed_bundle
        )
        seeds = [s for s in (eff_bundle.get("seeds") or []) if isinstance(s, dict)]
        seed_summaries: list[dict[str, Any]] = []
        for s in seeds:
            gid = s.get("gap_id") or s.get("id")
            pab = s.get("prior_art_boundary") if isinstance(s.get("prior_art_boundary"), dict) else {}
            tt = s.get("trajectory_tree")
            tt_gens = len(tt.get("generations") or []) if isinstance(tt, dict) else (len(tt) if isinstance(tt, list) else 0)
            portfolio = s.get("idea_portfolio") if isinstance(s.get("idea_portfolio"), list) else []
            res_f = s.get("resource_feasibility") if isinstance(s.get("resource_feasibility"), dict) else {}
            if res_f.get("infeasible_under_user_resources") is True:
                warnings.append(f"idea_seed_infeasible_resources:{gid}")
            if s.get("gap_below_target_venue_tier") is True:
                warnings.append(f"gap_below_target_venue_tier:{gid}")
            if s.get("missing_or_weak_why_now_enabler") is True:
                warnings.append(f"weak_why_now_enabler:{gid}")
            seed_summaries.append({
                "gap_id": gid,
                "gap_tier_ceiling": s.get("gap_tier_ceiling"),
                "gap_below_target_venue_tier": s.get("gap_below_target_venue_tier"),
                "support_ids": list(pab.get("support_ids") or []),
                "cited_ids": list(pab.get("cited_ids") or []),
                "closest_work_ids": list(pab.get("closest_work_ids") or s.get("closest_work_ids") or []),
                "trajectory_generations": tt_gens,
                "idea_portfolio_count": len(portfolio),
                "idea_angles": [p.get("canonical_angle") or p.get("angle") for p in portfolio if isinstance(p, dict)],
                "f32_lenses": {
                    "root_cause_barrier": s.get("root_cause_barrier"),
                    "why_now_enabler": s.get("why_now_enabler"),
                    "evaluation_validity_gap": s.get("evaluation_validity_gap"),
                    "isomorphic_transfer_leads_count": len(s.get("isomorphic_transfer_leads") or []),
                    "so_what_decision_impact": s.get("so_what_decision_impact"),
                    "durability_12_24m": s.get("durability_12_24m"),
                },
            })
        raw_isc = seed_bundle.get("idea_seed_count") if seed_bundle.get("idea_seed_count") is not None else eff_bundle.get("idea_seed_count")
        eff_seed_count = len(seed_summaries) if seed_summaries else (raw_isc if type(raw_isc) is int and raw_isc >= 0 else 0)
        out["idea_seed_bundle"] = {
            "schema": eff_bundle.get("schema") or seed_bundle.get("schema"),
            "topic": eff_bundle.get("topic") or seed_bundle.get("topic"),
            "subfield_preset": eff_bundle.get("subfield_preset") or seed_bundle.get("subfield_preset"),
            "seed_count": eff_seed_count,
            "seeds": seed_summaries,
            "has_root_trajectory_trees": bool(root_tts),
        }

    if proj_doc is not None:
        if isinstance(proj_doc.get("audit"), dict):
            audit = proj_doc["audit"]
        elif isinstance(proj_doc.get("audit_state"), dict):
            audit = proj_doc["audit_state"]
        else:
            audit = proj_doc
        p_status = str(audit.get("status") or proj_doc.get("audit_status") or proj_doc.get("status") or "")
        p_errs = [str(e) for e in (audit.get("errors") or [])]
        raw_p_ec = proj_doc.get("error_count")
        p_err_count = len(p_errs) if p_errs else (raw_p_ec if type(raw_p_ec) is int and raw_p_ec >= 0 else 0)
        if p_status == "issues_detected" or p_err_count > 0:
            warnings.append(f"project_state_issues:{p_err_count}")
        out["project_state"] = {
            "project_id": proj_doc.get("project_id"),
            "status": p_status,
            "errors": p_errs[:10],
            "warnings": list(audit.get("warnings") or [])[:10],
            "lineage_coverage": audit.get("lineage_coverage"),
        }

    if triage_doc is not None:
        fatal_defs = list(triage_doc.get("fatal_defects") or triage_doc.get("fatal") or [])
        major_defs = list(triage_doc.get("major_defects") or triage_doc.get("major") or [])
        minor_defs = list(triage_doc.get("minor_defects") or triage_doc.get("minor") or [])
        for d in (triage_doc.get("defects") or triage_doc.get("substantive_defects") or triage_doc.get("defect_ledger") or []):
            if isinstance(d, dict):
                sev = str(d.get("severity") or d.get("bucket") or "").lower()
                if sev == "fatal":
                    fatal_defs.append(d)
                elif sev == "major":
                    major_defs.append(d)
                elif sev == "minor":
                    minor_defs.append(d)
        t_sr = triage_doc.get("submission_readiness") if isinstance(triage_doc.get("submission_readiness"), dict) else {}
        t_sr_fatal = t_sr.get("fatal_gate_triggered") is True
        t_sr_band_fatal = triage_doc.get("submission_readiness_band") == "not_ready_fatal_gate"
        defect_counts = triage_doc.get("defect_counts") if isinstance(triage_doc.get("defect_counts"), dict) else {}
        counts_map = triage_doc.get("counts") if isinstance(triage_doc.get("counts"), dict) else {}
        dc_fatal = defect_counts.get("fatal")
        t_dc_fatal = type(dc_fatal) is int and dc_fatal > 0
        vb_checks = triage_doc.get("venue_b_checks") if isinstance(triage_doc.get("venue_b_checks"), dict) else {}
        vb_status = str(vb_checks.get("status") or "")
        vb_blocked = vb_status == "resubmission_blocked"
        t_verdict = str(triage_doc.get("overall_verdict") or triage_doc.get("verdict") or triage_doc.get("status") or "")
        blocking_verdicts = {
            "FAIL",
            "HOLD",
            "REJECT",
            "BLOCKED",
            "fatal_gate_triggered",
            "rejected_below_venue_tier",
            "hold_for_rework",
            "resubmission_blocked",
        }
        t_block = (
            bool(fatal_defs)
            or triage_doc.get("blocking") is True
            or t_verdict in blocking_verdicts
            or t_sr_fatal
            or t_sr_band_fatal
            or t_dc_fatal
            or vb_blocked
        )
        eff_fatal_count = max(len(fatal_defs), dc_fatal) if type(dc_fatal) is int and dc_fatal >= 0 else len(fatal_defs)
        if t_block:
            block_ready = True
            reason_tok = t_verdict or (vb_status if vb_blocked else "") or (
                "submission_readiness_fatal_gate" if (t_sr_fatal or t_sr_band_fatal) else f"{eff_fatal_count}_fatal_defects"
            )
            blockers.append(f"triage_reviews_blocking:{reason_tok}")
        dc_major = defect_counts.get("major")
        cnt_sub = counts_map.get("substantive_defects")
        if type(dc_major) is int and dc_major >= 0:
            eff_major_count = max(len(major_defs), dc_major)
        elif type(cnt_sub) is int and cnt_sub >= 0 and (len(major_defs) + eff_fatal_count) < cnt_sub:
            eff_major_count = max(len(major_defs), cnt_sub - eff_fatal_count)
        else:
            eff_major_count = len(major_defs)
        dc_minor = defect_counts.get("minor")
        cnt_min = counts_map.get("minor_polish")
        if type(dc_minor) is int and dc_minor >= 0:
            eff_minor_count = max(len(minor_defs), dc_minor)
        elif type(cnt_min) is int and cnt_min >= 0:
            eff_minor_count = max(len(minor_defs), cnt_min)
        else:
            eff_minor_count = len(minor_defs)
        out["triage_reviews"] = {
            "verdict": t_verdict or vb_status,
            "blocking": t_block,
            "venue_b_status": vb_status or None,
            "fatal_count": eff_fatal_count,
            "major_count": eff_major_count,
            "minor_count": eff_minor_count,
            "fatal_defects": fatal_defs[:5],
            "major_defects": major_defs[:5],
            "minor_defects": minor_defs[:5],
        }

    if prior_sc_doc is not None:
        prior_parsed = _parse_scorecard_input(prior_sc_doc, target_id)
        p_res = prior_parsed.get("pre_cap_result") or {}
        p_w = p_res.get("weighted_unrounded")
        p_o = p_res.get("overall")
        p_r = prior_parsed.get("ratings")
        p_w_dec = _parse_finite_decimal(p_w, "prior_scorecard.weighted_unrounded") if p_w is not None else None
        post_w_dec = _parse_finite_decimal(post_cap_weighted, "scorecard.weighted_unrounded") if post_cap_weighted is not None else None
        w_delta = None
        if p_w_dec is not None and post_w_dec is not None:
            w_delta = round(float(post_w_dec - p_w_dec), 4)
        dim_deltas: dict[str, int] = {}
        if isinstance(p_r, dict) and isinstance(post_cap_ratings, dict):
            for d in active_dims:
                if p_r.get(d) is not None and post_cap_ratings.get(d) is not None:
                    dim_deltas[d] = post_cap_ratings[d] - p_r[d]
        inflation_warnings: list[str] = []
        if w_delta is not None and w_delta >= 1.0 and cross_tool_fatal:
            inflation_warnings.append("revision_grade_inflation_risk:score_increased_while_cross_tool_gate_failed")
        elif w_delta is not None and w_delta >= 1.5:
            inflation_warnings.append("revision_large_score_jump_verify_evidence_receipts")
        out["revision_diff"] = {
            "prior_overall": p_o,
            "prior_weighted_unrounded": str(p_w_dec) if p_w_dec is not None else None,
            "current_overall_post_cap": post_cap_overall,
            "current_weighted_post_cap": post_cap_weighted,
            "weighted_delta": w_delta,
            "dimension_deltas": dim_deltas,
            "grade_inflation_warnings": inflation_warnings,
        }

    return {
        "block_ready": block_ready,
        "blockers": blockers,
        "warnings": warnings,
        "details": out,
    }


def _build_action_plan(
    *,
    desk_audit: dict[str, Any],
    rigor_info: dict[str, Any],
    ledger_info: dict[str, Any],
    sc_parsed: dict[str, Any],
    venue_portfolio: dict[str, Any],
    upstream_info: dict[str, Any],
    subfield_criteria: dict[str, Any] | None,
    what_if_roi: list[dict[str, Any]],
    sanity_warnings: list[str],
    post_cap_sr: dict[str, Any],
    post_cap_rescore_incomplete: bool = False,
    fatal_thresholds: dict[str, int] | None = None,
    post_tier_fit: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    thresholds = fatal_thresholds or FATAL_THRESHOLDS
    plan: list[dict[str, Any]] = []

    for r in desk_audit.get("reasons") or []:
        plan.append({"priority": "P0_BLOCKER", "source": "desk_reject_audit", "code": r, "action": f"Resolve desk-reject blocker: {r}"})
    for b in upstream_info.get("blockers") or []:
        plan.append({"priority": "P0_BLOCKER", "source": "upstream_downstream", "code": b, "action": f"Fix invalid upstream/triage gate: {b}"})
    if venue_portfolio.get("no_viable_venue_in_portfolio"):
        plan.append({
            "priority": "P0_BLOCKER",
            "source": "venue_portfolio",
            "code": "no_viable_venue_in_portfolio",
            "action": f"No verified viable venue in portfolio; retarget to {venue_portfolio.get('recommended_matched_tier')} or resolve tier gaps.",
        })

    for cf in rigor_info.get("critical_failures") or []:
        plan.append({"priority": "P1_GATE_FIX", "source": "rigor_engineering", "code": cf, "action": f"Fix critical experiment/rigor failure: {cf}"})
    for lr in ledger_info.get("blocking_reasons") or []:
        plan.append({"priority": "P1_GATE_FIX", "source": "ledger_readiness", "code": lr, "action": f"Resolve manuscript/artifact readiness gate: {lr}"})
    if post_cap_rescore_incomplete:
        plan.append({
            "priority": "P1_GATE_FIX",
            "source": "score_math",
            "code": "post_cap_rescore_incomplete",
            "action": "Supply raw scorecard dimension ratings so active cross-tool caps can be accurately re-weighted.",
        })
    if sc_parsed.get("present") and not sc_parsed.get("structural_gate_passed"):
        for iss in (sc_parsed.get("issues") or ["scorecard_not_comparable"])[:5]:
            plan.append({"priority": "P1_GATE_FIX", "source": "compare_scorecards", "code": iss, "action": f"Fix scorecard comparability/locator issue: {iss}"})
    fatal_dims = list(post_cap_sr.get("fatal_dimensions") or [])
    for fdim in fatal_dims:
        th = thresholds.get(fdim, 3)
        plan.append({"priority": "P1_GATE_FIX", "source": "score_math", "code": f"fatal_dimension:{fdim}", "action": f"Lift {fdim} above fatal threshold ({th}) with verified evidence."})
    for freason in (post_cap_sr.get("fatal_reasons") or []):
        fr_s = str(freason)
        if any(fr_s.startswith(f"{fd}<=") or fr_s == fd for fd in fatal_dims):
            continue
        plan.append({"priority": "P1_GATE_FIX", "source": "score_math", "code": f"fatal_reason:{fr_s}", "action": f"Resolve score_math fatal gate: {fr_s}"})
    if not venue_portfolio.get("has_venues") and isinstance(post_tier_fit, dict) and post_tier_fit.get("rejected_below_venue_tier"):
        vtype_lbl = post_tier_fit.get("venue_type") or post_tier_fit.get("venue_tier") or "target_tier"
        rec_tier_lbl = post_tier_fit.get("recommended_matched_tier") or "lower_tier"
        for r_reason in (post_tier_fit.get("rejection_reasons") or ["rejected_below_venue_tier"]):
            plan.append({
                "priority": "P1_GATE_FIX",
                "source": "venue_tier_fit",
                "code": f"venue_tier_fit:{r_reason}",
                "action": f"Resolve {vtype_lbl} tier-fit deficit ({r_reason}) or retarget to {rec_tier_lbl}.",
            })

    # P2 Score-Lift ROI + Upgrade Gaps + Subfield Gaps + Triage Major
    upgrade_gaps = venue_portfolio.get("upgrade_gaps_to_target_tier") or {}
    emitted_roi_dims: set[str] = set()
    roi_top_count = 0
    for roi_item in what_if_roi:
        dim = roi_item["dimension"]
        if dim in emitted_roi_dims:
            continue
        if roi_top_count < 3 or dim in upgrade_gaps:
            emitted_roi_dims.add(dim)
            if roi_top_count < 3:
                roi_top_count += 1
            need_note = f" (needed for target tier: +{upgrade_gaps[dim]})" if dim in upgrade_gaps else ""
            plan.append({
                "priority": "P2_SCORE_LIFT_ROI",
                "source": "what_if_roi",
                "code": f"lift_{dim}",
                "action": f"Raise {dim} from {roi_item['current_rating']} to {roi_item['proposed_rating']} (+{roi_item['weighted_lift']} weighted overall){need_note}.",
            })
    for nw in (sc_parsed.get("novelty_inflation_warnings") or []):
        plan.append({"priority": "P2_SCORE_LIFT_ROI", "source": "related_work_comparison", "code": nw, "action": f"Address novelty/baseline warning: {nw}"})
    if subfield_criteria:
        for mc in subfield_criteria.get("missing_checks") or []:
            plan.append({"priority": "P2_SCORE_LIFT_ROI", "source": f"subfield:{subfield_criteria['preset']}", "code": f"missing_check:{mc}", "action": f"Complete {subfield_criteria['label']} check: {mc}"})
    tr_info = (upstream_info.get("details") or {}).get("triage_reviews") or {}
    for idx, mj in enumerate(tr_info.get("major_defects") or []):
        desc = mj.get("summary") or mj.get("issue") or mj.get("id") or str(mj)
        plan.append({"priority": "P2_SCORE_LIFT_ROI", "source": "triage_reviews", "code": f"major_defect_{idx+1}", "action": f"Address major review defect: {desc}"})

    # P3 Polish
    for w in (rigor_info.get("warnings") or []) + (ledger_info.get("warnings") or []) + (desk_audit.get("warnings") or []) + (upstream_info.get("warnings") or []) + sanity_warnings:
        plan.append({"priority": "P3_POLISH", "source": "warnings", "code": w, "action": f"Verify/polish warning: {w}"})

    return plan


def evaluate_submission(
    *,
    manifest_doc: dict[str, Any] | None = None,
    manifest_dir: Path | None = None,
    scorecard_path: Path | None = None,
    target_id: str | None = None,
    prior_scorecard_path: Path | None = None,
    venue_novelty_path: Path | None = None,
    venue_plan_paths: list[Path] | None = None,
    venue_source_paths: list[Path] | None = None,
    rigor_paths: list[Path] | None = None,
    engineering_diag_path: Path | None = None,
    experiment_manifest_path: Path | None = None,
    ledger_path: Path | None = None,
    preflight_paths: list[Path] | None = None,
    artifact_readiness_path: Path | None = None,
    submission_policy_path: Path | None = None,
    gap_record_path: Path | None = None,
    question_card_path: Path | None = None,
    idea_seed_bundle_path: Path | None = None,
    project_state_path: Path | None = None,
    triage_reviews_path: Path | None = None,
    subfield_preset: str | None = None,
    target_venue: str | None = None,
    target_venue_tier: str | None = None,
) -> dict[str, Any]:
    m = manifest_doc or {}
    if not isinstance(m, dict):
        raise ValueError("Manifest JSON must be an object")

    def _pick_single(cli_p: Path | None, *keys: str) -> Path | None:
        if cli_p is not None:
            return cli_p
        for k in keys:
            val = m.get(k)
            if val is not None:
                return _resolve_manifest_ref(val, k, manifest_dir)
        return None

    def _pick_many(cli_ps: list[Path] | None, *keys: str) -> list[Path]:
        out: list[Path] = []
        seen: set[str] = set()
        for p in (cli_ps or []):
            rp = str(p)
            if rp not in seen:
                seen.add(rp)
                out.append(p)
        for k in keys:
            val = m.get(k)
            if val is None:
                continue
            items = val if isinstance(val, list) else [val]
            for idx, item in enumerate(items):
                p = _resolve_manifest_ref(item, f"{k}[{idx}]", manifest_dir)
                rp = str(p)
                if rp not in seen:
                    seen.add(rp)
                    out.append(p)
        return out

    eff_target_id = target_id or m.get("target_id")
    if eff_target_id is not None:
        eff_target_id = _require_nonempty_str(eff_target_id, "target_id")

    eff_target_venue = target_venue or m.get("target_venue")
    if eff_target_venue is not None:
        eff_target_venue = _require_nonempty_str(eff_target_venue, "target_venue")

    eff_target_tier = target_venue_tier or m.get("target_venue_tier")
    if eff_target_tier is not None:
        eff_target_tier = _require_nonempty_str(eff_target_tier, "target_venue_tier")

    # Resolve paths
    sc_p = _pick_single(scorecard_path, "scorecard", "scorecards")
    prior_p = _pick_single(prior_scorecard_path, "prior_scorecard")
    vn_p = _pick_single(venue_novelty_path, "venue_novelty")
    vp_ps = _pick_many(venue_plan_paths, "venue_plan", "venue_plans")
    vs_ps = _pick_many(venue_source_paths, "venue_sources", "venue_source_checks")
    rig_ps = _pick_many(rigor_paths, "rigor", "experiment_rigor")
    eng_p = _pick_single(engineering_diag_path, "engineering_diagnostics")
    exp_p = _pick_single(experiment_manifest_path, "experiment_manifest")
    led_p = _pick_single(ledger_path, "ledger", "manuscript_ledger")
    pre_ps = _pick_many(preflight_paths, "preflight", "submission_preflight")
    art_p = _pick_single(artifact_readiness_path, "artifact_readiness")
    pol_p = _pick_single(submission_policy_path, "submission_policy", "venue_policy") if not isinstance(m.get("submission_policy"), dict) else None
    gap_p = _pick_single(gap_record_path, "gap_record")
    q_p = _pick_single(question_card_path, "question_card")
    seed_p = _pick_single(idea_seed_bundle_path, "idea_seed_bundle")
    proj_p = _pick_single(project_state_path, "project_state")
    tri_p = _pick_single(triage_reviews_path, "triage_reviews")

    # Load all JSONs strictly (resolving 1-hop compact wrapper paths on disk when available)
    sc_doc = _load_json_file(sc_p, "scorecard", resolve_compact_artifact=True) if sc_p else (m.get("inline_scorecard") if isinstance(m.get("inline_scorecard"), dict) else None)
    prior_doc = _load_json_file(prior_p, "prior_scorecard", resolve_compact_artifact=True) if prior_p else None
    vn_doc = _load_json_file(vn_p, "venue_novelty", resolve_compact_artifact=True) if vn_p else None
    vp_docs = [(p, _load_json_file(p, "venue_plan", resolve_compact_artifact=True)) for p in vp_ps]
    vs_docs = [(p, _load_json_file(p, "venue_sources", resolve_compact_artifact=True)) for p in vs_ps]
    rig_docs = [(p, _load_json_file(p, "rigor", resolve_compact_artifact=True)) for p in rig_ps]
    eng_doc = _load_json_file(eng_p, "engineering_diagnostics", resolve_compact_artifact=True) if eng_p else None
    exp_doc = _load_json_file(exp_p, "experiment_manifest", resolve_compact_artifact=True) if exp_p else None
    led_doc = _load_json_file(led_p, "ledger", resolve_compact_artifact=True) if led_p else None
    pre_docs = [(p, _load_json_file(p, "preflight", resolve_compact_artifact=True)) for p in pre_ps]
    art_doc = _load_json_file(art_p, "artifact_readiness", resolve_compact_artifact=True) if art_p else None
    pol_doc = _load_json_file(pol_p, "submission_policy", resolve_compact_artifact=True) if pol_p else (m.get("submission_policy") if isinstance(m.get("submission_policy"), dict) else None)
    gap_doc = _load_json_file(gap_p, "gap_record", resolve_compact_artifact=True) if gap_p else None
    q_doc = _load_json_file(q_p, "question_card", resolve_compact_artifact=True) if q_p else None
    seed_doc = _load_json_file(seed_p, "idea_seed_bundle", resolve_compact_artifact=True) if seed_p else None
    proj_doc = _load_json_file(proj_p, "project_state", resolve_compact_artifact=True) if proj_p else None
    tri_doc = _load_json_file(tri_p, "triage_reviews", resolve_compact_artifact=True) if tri_p else None

    if pol_doc is not None:
        _validate_finite_tree(pol_doc, "submission_policy")

    # Resolve subfield preset defensively
    seed_preset = None
    if isinstance(seed_doc, dict):
        seed_preset = seed_doc.get("subfield_preset")
        if not seed_preset and isinstance(seed_doc.get("idea_seed_bundle"), dict):
            seed_preset = seed_doc["idea_seed_bundle"].get("subfield_preset")
    eff_preset = (
        subfield_preset
        or m.get("subfield_preset")
        or (sc_doc.get("subfield_preset") if isinstance(sc_doc, dict) else None)
        or seed_preset
        or (proj_doc.get("subfield_preset") if isinstance(proj_doc, dict) else None)
        or ((proj_doc.get("state") or {}).get("subfield_preset") if isinstance(proj_doc, dict) and isinstance(proj_doc.get("state"), dict) else None)
    )
    if eff_preset is not None:
        if not isinstance(eff_preset, str) or eff_preset not in SUBFIELD_PRESETS:
            raise ValueError(f"Invalid subfield_preset {eff_preset!r}; expected one of {tuple(SUBFIELD_PRESETS)}")

    # 1. Parse scorecard baseline
    sc_parsed = _parse_scorecard_input(sc_doc, eff_target_id, subfield_preset=eff_preset)
    eff_target_id = sc_parsed["target_id"] or eff_target_id
    m9a = dict(sc_parsed["m9a_fields"])
    active_dims = sc_parsed["active_dims"]
    active_fatal_thresholds = IDEA_FATAL_THRESHOLDS if active_dims == IDEA_DIMENSIONS else FATAL_THRESHOLDS

    # 2. Cross-tool gating: Rigor / Engineering / Experiment Manifest + Ledger / Artifact Readiness
    rigor_info = _evaluate_rigor_and_engineering(rig_docs, eng_doc, exp_doc, exp_p)
    ledger_info = _evaluate_ledger_and_readiness(led_doc, art_doc)

    # Combine caps
    combined_caps: dict[str, int] = {}
    combined_cap_reasons: list[str] = []
    for d, v in rigor_info["caps"].items():
        combined_caps[d] = min(combined_caps[d], v) if d in combined_caps else v
    for d, v in ledger_info["caps"].items():
        combined_caps[d] = min(combined_caps[d], v) if d in combined_caps else v
    combined_cap_reasons.extend(rigor_info["cap_reasons"])
    for cr in ledger_info["cap_reasons"]:
        if cr not in combined_cap_reasons:
            combined_cap_reasons.append(cr)

    cross_tool_fatal_gate = bool(rigor_info["fatal"] or ledger_info["fatal"])

    # 3. Apply caps and re-score via score_math.score()
    pre_ratings = sc_parsed["ratings"]
    weights = sc_parsed["weights"] or dict(DEFAULT_IDEA_WEIGHTS if sc_parsed["is_idea"] else DEFAULT_WEIGHTS)
    is_idea = sc_parsed["is_idea"]
    pre_cap_res = sc_parsed["pre_cap_result"]

    post_ratings: dict[str, int | None] | None = None
    post_cap_res: dict[str, Any] | None = None
    post_cap_rescore_incomplete = False

    if pre_ratings is not None:
        post_ratings = dict(pre_ratings)
        for dim, cap_v in combined_caps.items():
            if post_ratings.get(dim) is not None and post_ratings[dim] > cap_v:
                post_ratings[dim] = cap_v
        sc_extra = dict(sc_parsed.get("score_math_extra") or {})
        if "venue_type" not in sc_extra and "venue_profile" not in sc_extra:
            m_vtype = m.get("venue_type") or m.get("venue_profile")
            if m_vtype is not None:
                sc_extra["venue_type"] = m_vtype
        post_cap_res = score_math_score({
            "weights": weights,
            "ratings": post_ratings,
            **sc_extra,
            **({"mode": "idea"} if is_idea else {}),
        })
        if combined_caps:
            m9a.update(_extract_m9a_fields(post_cap_res))
        if post_cap_res.get("submission_readiness", {}).get("fatal_gate_triggered") and (combined_caps and not cross_tool_fatal_gate):
            for dim, cap_v in combined_caps.items():
                if dim in active_fatal_thresholds and cap_v <= active_fatal_thresholds[dim]:
                    cross_tool_fatal_gate = True
    elif pre_cap_res is not None:
        # No raw ratings (compare_scorecards / score_math summary output)
        post_cap_res = json.loads(json.dumps(pre_cap_res))
        sr = dict(post_cap_res.get("submission_readiness") or {})
        if combined_caps:
            post_cap_rescore_incomplete = True
            post_cap_res["overall"] = None
            post_cap_res["weighted_unrounded"] = None
            post_cap_res["status"] = "not_comparable_post_cap_ratings_missing"
            post_cap_res["post_cap_rescore_incomplete"] = True
            post_cap_res["rescore_note"] = (
                "Raw dimension ratings absent in summary scorecard output; cannot re-weight active "
                "cross-tool caps without raw ratings."
            )
            fatal_capped_dims = [
                d for d, cv in combined_caps.items()
                if d in active_fatal_thresholds and cv <= active_fatal_thresholds[d]
            ]
            if fatal_capped_dims:
                cross_tool_fatal_gate = True
                sr["fatal_gate_triggered"] = True
                sr["fatal_dimensions"] = sorted(set(list(sr.get("fatal_dimensions") or []) + fatal_capped_dims))
                sr["fatal_reasons"] = sorted(set(list(sr.get("fatal_reasons") or []) + [f"{d}<={combined_caps[d]}(capped)" for d in fatal_capped_dims]))
                sr["band"] = "not_ready_fatal_gate"
                sr["ready_for_top_tier_main_track"] = False
                sr["ready_for_findings_or_tier_a"] = False
                sr["recommended_matched_tier"] = "none_hold_for_rework"
            else:
                sr["band"] = "not_comparable_post_cap_ratings_missing"
                sr["ready_for_top_tier_main_track"] = False
                sr["ready_for_findings_or_tier_a"] = False
                sr["recommended_matched_tier"] = None
                caps_desc = ", ".join(f"{d}<={v}" for d, v in sorted(combined_caps.items()))
                sr["guidance"] = (
                    f"Cannot confirm post-cap weighted score or tier readiness: raw dimension ratings "
                    f"missing for active cap(s) ({caps_desc}). Supply raw ratings to re-score."
                )
        post_cap_res["submission_readiness"] = sr

    post_overall = (post_cap_res or {}).get("overall")
    post_weighted = (post_cap_res or {}).get("weighted_unrounded")
    post_sr = dict((post_cap_res or {}).get("submission_readiness") or {})
    if post_sr.get("fatal_gate_triggered") and combined_caps:
        if any(d in active_fatal_thresholds and cv <= active_fatal_thresholds[d] for d, cv in combined_caps.items()):
            cross_tool_fatal_gate = True

    post_weighted_dec = _parse_finite_decimal(post_weighted, "scorecard.weighted_unrounded") if post_weighted is not None else None

    # 4. Desk-reject rules
    desk_audit = _evaluate_desk_reject_rules(
        pre_docs,
        ledger_info["anon_desk_reject_reasons"],
        vn_doc,
        pol_doc,
    )
    desk_reject_blocked = desk_audit["blocked"]

    # If target_venue explicitly selected in venue_novelty is a conflicted_fallback, mark desk_reject_blocked
    if eff_target_venue and isinstance(vn_doc, dict):
        tv_norm = _norm_tok(eff_target_venue)
        is_conflicted_target = False
        for ve in list(vn_doc.get("venue_evaluations") or []) + list(vn_doc.get("venue_summaries") or []):
            if isinstance(ve, dict) and ve.get("classification") == "conflicted_fallback":
                if _target_matches_conflicted_id(
                    tv_norm,
                    ve.get("venue_id"),
                    venue_name=ve.get("venue_name"),
                    track=ve.get("track"),
                ):
                    is_conflicted_target = True
                    break
        if not is_conflicted_target:
            vpr_cf = vn_doc.get("venue_portfolio_recommendations") if isinstance(vn_doc.get("venue_portfolio_recommendations"), dict) else {}
            for cid in (vpr_cf.get("conflicted_fallback") or []):
                if _target_matches_conflicted_id(tv_norm, cid):
                    is_conflicted_target = True
                    break
        if is_conflicted_target:
            desk_reject_blocked = True
            desk_audit["blocked"] = True
            if "venue_portfolio:selected_venue_conflicted_fallback" not in desk_audit["reasons"]:
                desk_audit["reasons"].append("venue_portfolio:selected_venue_conflicted_fallback")

    # 5. Venue disqualification & portfolio auto-retargeting (post-cap)
    score_fatal = bool(post_sr.get("fatal_gate_triggered"))
    sc_vtp = post_cap_res.get("venue_type_profile") if isinstance(post_cap_res, dict) and isinstance(post_cap_res.get("venue_type_profile"), dict) else {}
    sc_vtf = post_cap_res.get("venue_tier_fit") if isinstance(post_cap_res, dict) and isinstance(post_cap_res.get("venue_tier_fit"), dict) else {}
    sc_vtype_raw = (
        sc_vtp.get("venue_type")
        or sc_vtf.get("venue_type")
        or (post_cap_res.get("venue_type") if isinstance(post_cap_res, dict) else None)
        or (post_cap_res.get("venue_profile") if isinstance(post_cap_res, dict) else None)
        or m9a.get("venue_type")
        or m9a.get("venue_profile")
        or (sc_doc.get("venue_type") if isinstance(sc_doc, dict) else None)
        or (sc_doc.get("venue_profile") if isinstance(sc_doc, dict) else None)
        or m.get("venue_type")
        or m.get("venue_profile")
    )
    sc_eff_vtype = resolve_venue_type(sc_vtype_raw) if sc_vtype_raw is not None else None
    venue_portfolio = _evaluate_venue_portfolio(
        vn_doc,
        vp_docs,
        vs_docs,
        target_venue=eff_target_venue,
        target_venue_tier=eff_target_tier,
        post_cap_weighted=post_weighted,
        post_cap_ratings=post_ratings,
        is_idea=is_idea,
        cross_tool_fatal=cross_tool_fatal_gate,
        score_fatal=score_fatal,
        desk_reject_blocked=desk_reject_blocked,
        venue_type=sc_eff_vtype,
    )

    # 6. Native scales, merit/packaging, syntheses, ROI, sanity warnings, subfield, upstream/downstream
    native_scales = _compute_native_scales(
        post_weighted_dec,
        fatal_gate_triggered=score_fatal or cross_tool_fatal_gate,
        desk_reject_blocked=desk_reject_blocked,
        existing_native=None if (combined_caps and pre_ratings is None) else (
            m9a.get("native_venue_scales") or m9a.get("native_scales") or m9a.get("native_scale")
        ),
    )
    mvp = m9a.get("merit_vs_packaging") if isinstance(m9a.get("merit_vs_packaging"), dict) else {}
    up_merit = m9a.get("scientific_merit_score") if m9a.get("scientific_merit_score") is not None else mvp.get("scientific_merit_score")
    up_pack = m9a.get("publishability_packaging_score") if m9a.get("publishability_packaging_score") is not None else mvp.get("publishability_packaging_score")
    if post_ratings is not None:
        merit_score, pack_score = _compute_merit_vs_packaging(weights, post_ratings, active_dims=active_dims)
        if not combined_caps:
            if up_merit is not None:
                merit_score = up_merit
            if up_pack is not None:
                pack_score = up_pack
    elif post_cap_rescore_incomplete:
        merit_score = None if any(d in combined_caps for d in ("importance", "novelty", "soundness", "evidence")) else up_merit
        pack_score = None if any(d in combined_caps for d in ("transparency", "clarity")) else up_pack
    else:
        merit_score, pack_score = up_merit, up_pack

    sanity_warnings = _compute_sanity_warnings(
        post_ratings or {},
        m9a.get("sanity_warnings"),
        existing_list=m9a.get("sanity_warnings_list"),
    )
    what_if_roi = _compute_what_if_roi(
        weights,
        post_ratings or {},
        post_weighted_dec,
        None if (combined_caps and pre_ratings is None) else m9a.get("what_if_roi"),
        active_dims=active_dims,
        fatal_thresholds=active_fatal_thresholds,
    )
    up_rpa = (
        m9a.get("reviewer_panel_analysis")
        if isinstance(m9a.get("reviewer_panel_analysis"), dict)
        else (m9a.get("reviewer_panel_summary") if isinstance(m9a.get("reviewer_panel_summary"), dict) else None)
    )
    up_ac = m9a.get("ac_synthesis")
    if up_ac is None and up_rpa is not None and up_rpa.get("meta_review_verdict") is not None:
        up_ac = {
            "source": "m9a_v2",
            "meta_review_verdict": up_rpa.get("meta_review_verdict"),
            "meta_review_rationale": up_rpa.get("meta_review_rationale"),
            "variance_risk": up_rpa.get("variance_risk"),
            "assassin_reviewer_flag": up_rpa.get("assassin_reviewer_flag"),
        }
    if combined_caps and pre_ratings is None:
        eff_up_rev = None
        eff_up_ac = None
    elif combined_caps:
        post_rpa = (
            post_cap_res.get("reviewer_panel_analysis")
            if isinstance(post_cap_res, dict) and isinstance(post_cap_res.get("reviewer_panel_analysis"), dict)
            else None
        )
        eff_up_rev = post_rpa
        if (
            post_rpa is not None
            and post_rpa.get("meta_review_verdict") is not None
            and not (score_fatal or cross_tool_fatal_gate or desk_reject_blocked)
            and post_weighted_dec is not None
            and post_weighted_dec >= Decimal("6.80")
        ):
            eff_up_ac = {
                "source": "m9a_v2",
                "meta_review_verdict": post_rpa.get("meta_review_verdict"),
                "meta_review_rationale": post_rpa.get("meta_review_rationale"),
                "variance_risk": post_rpa.get("variance_risk"),
                "assassin_reviewer_flag": post_rpa.get("assassin_reviewer_flag"),
            }
        else:
            eff_up_ac = None
    else:
        eff_up_rev = m9a.get("reviewer_synthesis") or up_rpa
        eff_up_ac = up_ac
    rev_synth, ac_synth = _compute_syntheses(
        post_ratings or {},
        post_weighted_dec,
        fatal_gate_triggered=score_fatal,
        cross_tool_fatal_gate=cross_tool_fatal_gate,
        desk_reject_blocked=desk_reject_blocked,
        upstream_rev=eff_up_rev,
        upstream_ac=eff_up_ac,
        active_dims=active_dims,
    )
    sec_diag = _compute_section_diagnostics(
        post_ratings or {},
        None if (combined_caps and pre_ratings is None) else m9a.get("section_diagnostics"),
    )
    worst_sens = _compute_worst_case_sensitivity(
        weights,
        post_ratings or {},
        post_weighted_dec,
        None if (combined_caps and pre_ratings is None) else (m9a.get("deal_breaker_sensitivity") or m9a.get("worst_case_sensitivity")),
        active_dims=active_dims,
        fatal_thresholds=active_fatal_thresholds,
    )

    subfield_criteria = _evaluate_subfield_criteria(
        eff_preset,
        rigor_info,
        seed_doc,
        led_doc,
        sc_doc=sc_doc,
        post_cap_res=post_cap_res,
        target_id=eff_target_id,
    )
    upstream_info = _inspect_upstream_downstream(
        gap_doc,
        q_doc,
        seed_doc,
        proj_doc,
        tri_doc,
        prior_doc,
        post_overall,
        post_weighted,
        post_ratings,
        eff_target_id,
        cross_tool_fatal_gate,
        active_dims=active_dims,
    )

    # 7. Final ready_to_submit & verdict
    scorecard_blocked = sc_parsed["present"] and not sc_parsed["structural_gate_passed"]
    score_band = post_sr.get("band")
    low_score_blocked = False
    if post_weighted_dec is not None:
        if score_fatal or post_weighted_dec < Decimal("5.00"):
            low_score_blocked = True
        elif not venue_portfolio["has_venues"] and post_weighted_dec < Decimal("6.00"):
            # Without a verified workshop venue target, <6.00 is below archival bar
            low_score_blocked = True
    elif sc_parsed["present"] and score_band in ("not_ready_fatal_gate", "not_ready_major_rework", "not_comparable_missing_dimension", "not_comparable_structural_gate", "not_comparable_post_cap_ratings_missing"):
        low_score_blocked = True

    post_tier_fit = (
        post_cap_res.get("venue_tier_fit")
        if isinstance(post_cap_res, dict) and isinstance(post_cap_res.get("venue_tier_fit"), dict)
        else {}
    )
    if not venue_portfolio["has_venues"] and post_tier_fit.get("rejected_below_venue_tier") is True:
        low_score_blocked = True
        if not venue_portfolio["upgrade_gaps_to_target_tier"] and post_tier_fit.get("upgrade_gaps_to_target_tier"):
            venue_portfolio["upgrade_gaps_to_target_tier"] = dict(post_tier_fit["upgrade_gaps_to_target_tier"])

    ready_to_submit = not (
        cross_tool_fatal_gate
        or desk_reject_blocked
        or ledger_info["block_ready"]
        or scorecard_blocked
        or post_cap_rescore_incomplete
        or venue_portfolio["no_viable_venue_in_portfolio"]
        or upstream_info["block_ready"]
        or low_score_blocked
        or is_idea
    )

    if desk_reject_blocked and cross_tool_fatal_gate:
        verdict = "BLOCKED_FATAL_GATE_AND_DESK_REJECT"
    elif desk_reject_blocked:
        verdict = "BLOCKED_DESK_REJECT"
    elif cross_tool_fatal_gate:
        verdict = "BLOCKED_CROSS_TOOL_FATAL_GATE"
    elif ledger_info["block_ready"] or scorecard_blocked or upstream_info["block_ready"] or post_cap_rescore_incomplete:
        verdict = "BLOCKED_INTEGRITY_OR_STRUCTURAL_GATE"
    elif venue_portfolio["no_viable_venue_in_portfolio"]:
        verdict = "BLOCKED_NO_VIABLE_VENUE"
    elif not ready_to_submit:
        verdict = "NOT_READY_BELOW_BAR"
    elif venue_portfolio["retargeted"]:
        verdict = "RETARGETED_READY"
    else:
        verdict = "READY_TO_SUBMIT"

    action_plan = _build_action_plan(
        desk_audit=desk_audit,
        rigor_info=rigor_info,
        ledger_info=ledger_info,
        sc_parsed=sc_parsed,
        venue_portfolio=venue_portfolio,
        upstream_info=upstream_info,
        subfield_criteria=subfield_criteria,
        what_if_roi=what_if_roi,
        sanity_warnings=sanity_warnings,
        post_cap_sr=post_sr,
        post_cap_rescore_incomplete=post_cap_rescore_incomplete,
        fatal_thresholds=active_fatal_thresholds,
        post_tier_fit=post_tier_fit,
    )

    extra_warnings = ["post_cap_rescore_incomplete:supply_raw_ratings"] if post_cap_rescore_incomplete else []
    all_warnings = sorted(set(
        rigor_info["warnings"]
        + ledger_info["warnings"]
        + desk_audit["warnings"]
        + upstream_info["warnings"]
        + sanity_warnings
        + extra_warnings
        + (sc_parsed.get("novelty_inflation_warnings") or [])
    ))

    rec_matched_tier = venue_portfolio.get("recommended_matched_tier")
    if rec_matched_tier is None:
        rec_matched_tier = post_sr.get("recommended_matched_tier")

    score_eval: dict[str, Any] = {
        "target_id": eff_target_id,
        "mode": "idea" if is_idea else "paper",
        "weights": weights if sc_parsed["present"] else None,
        "ratings_pre_cap": pre_ratings,
        "ratings_post_cap": post_ratings,
        "applied_caps": combined_caps,
        "cap_reasons": combined_cap_reasons,
        "post_cap_rescore_incomplete": post_cap_rescore_incomplete,
        "pre_cap": pre_cap_res,
        "post_cap": post_cap_res,
        "submission_readiness": post_sr,
        "native_scales": native_scales,
        "scientific_merit_score": merit_score,
        "publishability_packaging_score": pack_score,
        "reviewer_synthesis": rev_synth,
        "ac_synthesis": ac_synth,
        "what_if_roi": what_if_roi,
        "section_diagnostics": sec_diag,
        "worst_case_sensitivity": worst_sens,
        "sanity_warnings": sanity_warnings,
        "related_work_comparison": sc_parsed.get("related_work_comparison"),
        "revision_diff": (upstream_info["details"] or {}).get("revision_diff"),
    }
    if isinstance(m9a.get("reviewer_panel_summary"), dict) and not combined_caps:
        score_eval["reviewer_panel_summary"] = m9a["reviewer_panel_summary"]
    if m9a.get("pareto_frontier") is not None:
        score_eval["pareto_frontier"] = m9a["pareto_frontier"]
    if m9a.get("linkage_summary") is not None:
        score_eval["linkage_summary"] = m9a["linkage_summary"]
    eff_idea_band = (post_sr.get("idea_viability_band") if isinstance(post_sr, dict) else None) or m9a.get("idea_viability_band")
    if eff_idea_band is not None:
        score_eval["idea_viability_band"] = eff_idea_band
    if m9a.get("evidence_anchor_table") is not None:
        score_eval["evidence_anchor_table"] = m9a["evidence_anchor_table"]

    return {
        "schema": SCHEMA_VERSION,
        "ready_to_submit": ready_to_submit,
        "verdict": verdict,
        "cross_tool_fatal_gate": cross_tool_fatal_gate,
        "desk_reject_blocked": desk_reject_blocked,
        "overall": post_overall,
        "weighted_unrounded": post_weighted,
        "band": score_band,
        "selected_venue": venue_portfolio["selected_venue"],
        "no_viable_venue_in_portfolio": venue_portfolio["no_viable_venue_in_portfolio"],
        "recommended_matched_tier": rec_matched_tier,
        "upgrade_gaps_to_target_tier": venue_portfolio["upgrade_gaps_to_target_tier"],
        "subfield_preset": eff_preset,
        "subfield_criteria": subfield_criteria,
        "score_evaluation": score_eval,
        "cross_tool_gating_audit": {
            "rigor": rigor_info["rigor_summaries"],
            "engineering_diagnostics": rigor_info["engineering_diagnostics"],
            "experiment_manifest": rigor_info["experiment_manifest"],
            "manuscript_ledger": ledger_info["manuscript_ledger"],
            "artifact_readiness": ledger_info["artifact_readiness"],
            "scorecard_structural_gate_passed": sc_parsed["structural_gate_passed"],
            "scorecard_issues": sc_parsed["issues"],
            "applied_caps": combined_caps,
            "cap_reasons": combined_cap_reasons,
            "blocking_reasons": sorted(set(rigor_info["critical_failures"] + ledger_info["blocking_reasons"])),
        },
        "desk_reject_audit": desk_audit,
        "venue_portfolio": venue_portfolio,
        "upstream_downstream_linkage": upstream_info["details"],
        "action_plan": action_plan,
        "warnings": all_warnings,
        "artifact_path": None,
    }


def _encoded_utf8_len(obj: Any) -> int:
    return len(json.dumps(obj, ensure_ascii=False).encode("utf-8"))


def _truncate_str(val: Any, max_chars: int) -> Any:
    if not isinstance(val, str) or len(val) <= max_chars:
        return val
    if max_chars <= 8:
        return val[-max_chars:]
    keep = max_chars - 3
    return "..." + val[-keep:]


def _compact_output(result: dict[str, Any], artifact_path: str | None) -> dict[str, Any]:
    sel_v = result.get("selected_venue")
    compact_sel_v = dict(sel_v) if isinstance(sel_v, dict) else sel_v
    if isinstance(compact_sel_v, dict):
        for k in ("venue_id", "venue_name", "retargeted_from"):
            if isinstance(compact_sel_v.get(k), str) and len(compact_sel_v[k]) > 120:
                compact_sel_v[k] = compact_sel_v[k][:117] + "..."

    compact: dict[str, Any] = {
        "compact": True,
        "schema": result.get("schema"),
        "ready_to_submit": result.get("ready_to_submit"),
        "verdict": result.get("verdict"),
        "cross_tool_fatal_gate": result.get("cross_tool_fatal_gate"),
        "desk_reject_blocked": result.get("desk_reject_blocked"),
        "overall": result.get("overall"),
        "weighted_unrounded": result.get("weighted_unrounded"),
        "band": result.get("band"),
        "selected_venue": compact_sel_v,
        "no_viable_venue_in_portfolio": result.get("no_viable_venue_in_portfolio"),
        "recommended_matched_tier": result.get("recommended_matched_tier"),
        "subfield_preset": result.get("subfield_preset"),
        "applied_caps": (result.get("cross_tool_gating_audit") or {}).get("applied_caps") or {},
        "top_actions": [
            {"priority": a.get("priority"), "code": str(a.get("code") or "")[:90]}
            for a in (result.get("action_plan") or [])[:5]
        ],
        "blocking_count": len((result.get("cross_tool_gating_audit") or {}).get("blocking_reasons") or []) + len((result.get("desk_reject_audit") or {}).get("reasons") or []),
        "warning_count": len(result.get("warnings") or []),
        "artifact_path": artifact_path,
    }

    stage = 0
    while _encoded_utf8_len(compact) > MAX_COMPACT_BYTES:
        if stage == 0:
            compact["artifact_path"] = _truncate_str(compact.get("artifact_path"), 240)
            compact["top_actions"] = compact["top_actions"][:3]
        elif stage == 1:
            compact["top_actions"] = []
            compact.pop("applied_caps", None)
        elif stage == 2:
            compact.pop("subfield_preset", None)
            compact.pop("blocking_count", None)
            compact.pop("warning_count", None)
        elif stage == 3:
            compact["artifact_path"] = _truncate_str(compact.get("artifact_path"), 96)
            if isinstance(compact.get("selected_venue"), dict):
                compact["selected_venue"] = {
                    k: v for k, v in compact["selected_venue"].items()
                    if k in ("venue_id", "venue_tier", "retargeted_from")
                }
        elif stage == 4:
            compact["artifact_path"] = _truncate_str(compact.get("artifact_path"), 32)
        else:
            compact["artifact_path"] = None
            if _encoded_utf8_len(compact) > MAX_COMPACT_BYTES and isinstance(compact.get("selected_venue"), dict):
                compact["selected_venue"] = compact["selected_venue"].get("venue_id")
            break
        stage += 1
    return compact


def _write_atomic_json(out_path: Path, payload: dict[str, Any]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".eval_sub_", suffix=".tmp", dir=str(out_path.parent))
    tmp_path = Path(tmp_name)
    try:
        rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(rendered)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, out_path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest_json", nargs="?", default=None, help="Optional path to submission evaluation manifest JSON")
    parser.add_argument("--manifest", default=None, help="Optional path to submission evaluation manifest JSON")
    parser.add_argument("--scorecard", "--scorecards", dest="scorecard", default=None, help="Path to score_math / compare_scorecards JSON")
    parser.add_argument("--target-id", default=None, help="Target profile ID inside multi-profile scorecard")
    parser.add_argument("--prior-scorecard", default=None, help="Optional prior v1 scorecard JSON for revision diff")
    parser.add_argument("--venue-novelty", default=None, help="Path to compare_venue_novelty JSON (single or portfolio)")
    parser.add_argument("--venue-plan", action="append", default=[], help="Repeatable path to check_venue_plan JSON")
    parser.add_argument("--venue-sources", action="append", default=[], help="Repeatable path to check_venue_sources JSON")
    parser.add_argument("--rigor", action="append", default=[], help="Repeatable path to check_experiment_rigor JSON (repro/rliable/contamination)")
    parser.add_argument("--engineering-diagnostics", default=None, help="Path to check_engineering_diagnostics JSON")
    parser.add_argument("--experiment-manifest", default=None, help="Path to check_experiment_manifest output or raw manifest JSON")
    parser.add_argument("--ledger", default=None, help="Path to check_manuscript_ledger JSON")
    parser.add_argument("--preflight", action="append", default=[], help="Repeatable path to check_submission_preflight JSON")
    parser.add_argument("--artifact-readiness", default=None, help="Path to check_artifact_readiness JSON")
    parser.add_argument("--submission-policy", default=None, help="Path to submission policy JSON (page limits, template, checklist)")
    parser.add_argument("--gap-record", default=None, help="Optional path to check_gap_record JSON")
    parser.add_argument("--question-card", default=None, help="Optional path to check_question_card JSON")
    parser.add_argument("--idea-seed-bundle", default=None, help="Optional path to research_scientist_idea_seed_bundle_v1 JSON")
    parser.add_argument("--project-state", default=None, help="Optional path to project_state JSON")
    parser.add_argument("--triage-reviews", default=None, help="Optional path to triage_reviews JSON")
    parser.add_argument("--subfield-preset", choices=tuple(SUBFIELD_PRESETS.keys()), default=None, help="Optional AI/CS subfield depth preset")
    parser.add_argument("--target-venue", default=None, help="Optional target venue name")
    parser.add_argument("--target-venue-tier", default=None, help="Optional target venue tier override")
    parser.add_argument("--out", default=None, help="Optional output JSON path (written atomically)")
    parser.add_argument("--compact", action="store_true", help="Emit bounded <4096B UTF-8 summary JSON to stdout")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        # Validate --out BEFORE any mkdir or processing
        out_path: Path | None = None
        if args.out is not None:
            out_path = _require_nonempty_path(args.out, "--out")
            if out_path.exists() and out_path.is_dir():
                raise ValueError(f"--out points to an existing directory: {out_path}")

        if args.manifest_json is not None and args.manifest is not None:
            raise ValueError("Provide either positional manifest_json or --manifest, not both")

        raw_manifest = args.manifest_json if args.manifest_json is not None else args.manifest
        manifest_path: Path | None = None
        manifest_doc: dict[str, Any] | None = None
        if raw_manifest is not None:
            manifest_path = _require_nonempty_path(raw_manifest, "manifest")
            manifest_doc = _load_json_file(manifest_path, "manifest")

        # Validate all CLI path flags non-empty before loading
        sc_p = _require_nonempty_path(args.scorecard, "--scorecard") if args.scorecard is not None else None
        prior_p = _require_nonempty_path(args.prior_scorecard, "--prior-scorecard") if args.prior_scorecard is not None else None
        vn_p = _require_nonempty_path(args.venue_novelty, "--venue-novelty") if args.venue_novelty is not None else None
        vp_ps = [_require_nonempty_path(x, "--venue-plan") for x in args.venue_plan]
        vs_ps = [_require_nonempty_path(x, "--venue-sources") for x in args.venue_sources]
        rig_ps = [_require_nonempty_path(x, "--rigor") for x in args.rigor]
        eng_p = _require_nonempty_path(args.engineering_diagnostics, "--engineering-diagnostics") if args.engineering_diagnostics is not None else None
        exp_p = _require_nonempty_path(args.experiment_manifest, "--experiment-manifest") if args.experiment_manifest is not None else None
        led_p = _require_nonempty_path(args.ledger, "--ledger") if args.ledger is not None else None
        pre_ps = [_require_nonempty_path(x, "--preflight") for x in args.preflight]
        art_p = _require_nonempty_path(args.artifact_readiness, "--artifact-readiness") if args.artifact_readiness is not None else None
        pol_p = _require_nonempty_path(args.submission_policy, "--submission-policy") if args.submission_policy is not None else None
        gap_p = _require_nonempty_path(args.gap_record, "--gap-record") if args.gap_record is not None else None
        q_p = _require_nonempty_path(args.question_card, "--question-card") if args.question_card is not None else None
        seed_p = _require_nonempty_path(args.idea_seed_bundle, "--idea-seed-bundle") if args.idea_seed_bundle is not None else None
        proj_p = _require_nonempty_path(args.project_state, "--project-state") if args.project_state is not None else None
        tri_p = _require_nonempty_path(args.triage_reviews, "--triage-reviews") if args.triage_reviews is not None else None

        if (
            manifest_doc is None
            and sc_p is None
            and vn_p is None
            and not vp_ps
            and not vs_ps
            and not rig_ps
            and eng_p is None
            and exp_p is None
            and led_p is None
            and not pre_ps
            and art_p is None
            and pol_p is None
            and gap_p is None
            and q_p is None
            and seed_p is None
            and proj_p is None
            and tri_p is None
        ):
            raise ValueError("At least one input (--manifest, manifest_json, or artifact flag) is required")

        target_id = _require_nonempty_str(args.target_id, "--target-id") if args.target_id is not None else None
        target_venue = _require_nonempty_str(args.target_venue, "--target-venue") if args.target_venue is not None else None
        target_tier = _require_nonempty_str(args.target_venue_tier, "--target-venue-tier") if args.target_venue_tier is not None else None

        result = evaluate_submission(
            manifest_doc=manifest_doc,
            manifest_dir=manifest_path.parent if manifest_path is not None else None,
            scorecard_path=sc_p,
            target_id=target_id,
            prior_scorecard_path=prior_p,
            venue_novelty_path=vn_p,
            venue_plan_paths=vp_ps,
            venue_source_paths=vs_ps,
            rigor_paths=rig_ps,
            engineering_diag_path=eng_p,
            experiment_manifest_path=exp_p,
            ledger_path=led_p,
            preflight_paths=pre_ps,
            artifact_readiness_path=art_p,
            submission_policy_path=pol_p,
            gap_record_path=gap_p,
            question_card_path=q_p,
            idea_seed_bundle_path=seed_p,
            project_state_path=proj_p,
            triage_reviews_path=tri_p,
            subfield_preset=args.subfield_preset,
            target_venue=target_venue,
            target_venue_tier=target_tier,
        )

        out_str: str | None = None
        if out_path is not None:
            out_str = str(out_path)
            result["artifact_path"] = out_str
            _write_atomic_json(out_path, result)

        if args.compact:
            print(json.dumps(_compact_output(result, out_str), ensure_ascii=False))
        else:
            print(json.dumps(result, ensure_ascii=False))
        return 0 if result["ready_to_submit"] else 1
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, RuntimeError, InvalidOperation, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
