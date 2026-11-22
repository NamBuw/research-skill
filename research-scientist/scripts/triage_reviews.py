#!/usr/bin/env python3
"""Deterministic adversarial mock-review (Mode 1) & post-reject triage (Mode 2) CLI.

Integrates F23-F25 score_math calibration, F29#6 3-persona defect ledger and
H1-H17 / M1-M5 / T1-T2 / R1-R5 / G1-G4 post-reject triage, F30#5-8 deep diagnostics
(anchor contrast, merit vs publishability split, 6-section diagnostics, worst-case
reviewer floor & deal-breaker sensitivity), and F31#2 4-subfield depth presets.

Pure Python stdlib + local score_math import; strictly rejects NaN/Infinity/bool
inputs with exit code 2, enforces --compact < 4096 UTF-8 bytes, and never invents
percentage acceptance probabilities.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import re
import sys
from datetime import datetime, timedelta, timezone
from decimal import BasicContext, Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import score_math  # noqa: E402

SCHEMA_MOCK_REVIEW = "research_scientist_mock_review_v1"
SCHEMA_POST_REJECT = "research_scientist_post_reject_triage_v1"
MAX_COMPACT_BYTES = 3850

PERSONAS = ("method_theory", "experiments_baselines", "novelty_positioning")
SECTIONS = ("abstract", "introduction", "related_work", "method", "experiments", "limitations")
SCALES = ("native", "arr_1_5", "neurips_1_6", "iclr_1_10")

# Exact 5 subfield preset keys matching gap_pipeline.py & build_research_inputs.py
SUBFIELD_PRESETS: dict[str, tuple[str, ...]] = {
    "nlp_llm": (
        "contamination_check",
        "multi_prompt_variance",
        "compute_matched_open_weight_baseline",
        "eval_harness_parity",
    ),
    "cv_multimodal": (
        "backbone_resolution_augmentation_parity",
        "flops_fps_memory_tradeoff",
        "qualitative_failure_analysis",
    ),
    "ml_theory": (
        "assumption_tightness_realism",
        "lower_vs_upper_bound_gap",
        "empirical_sanity_validation",
    ),
    "ai_systems": (
        "end_to_end_vs_microbenchmark",
        "tail_latency_p99",
        "peak_vram_comm_overhead",
        "matched_hardware",
    ),
    "speech_audio": (
        "speaker_session_disjoint_split",
        "audio_metric_and_normalization_parity",
        "decoding_vocoder_embedding_parity",
        "speech_slice_significance_and_consent",
    ),
}

_PRESET_CRITICAL_CHECKS = frozenset({
    "contamination_check",
    "backbone_resolution_augmentation_parity",
    "assumption_tightness_realism",
    "end_to_end_vs_microbenchmark",
    "matched_hardware",
    "speaker_session_disjoint_split",
    "audio_metric_and_normalization_parity",
    "decoding_vocoder_embedding_parity",
})

_PRESET_PERSONA_MAP = {
    "nlp_llm": "experiments_baselines",
    "cv_multimodal": "experiments_baselines",
    "ml_theory": "method_theory",
    "ai_systems": "experiments_baselines",
    "speech_audio": "experiments_baselines",
}

_DEFAULT_WEIGHTS = {
    "importance": 15,
    "novelty": 20,
    "soundness": 20,
    "evidence": 20,
    "transparency": 15,
    "clarity": 10,
}

_MERIT_DIMS = ("importance", "novelty", "soundness", "evidence")
_PACKAGING_DIMS = ("transparency", "clarity")

_PERSONA_WEIGHTS: dict[str, dict[str, int]] = {
    "method_theory": {
        "importance": 15,
        "novelty": 15,
        "soundness": 40,
        "evidence": 15,
        "transparency": 5,
        "clarity": 10,
    },
    "experiments_baselines": {
        "importance": 10,
        "novelty": 5,
        "soundness": 15,
        "evidence": 40,
        "transparency": 25,
        "clarity": 5,
    },
    "novelty_positioning": {
        "importance": 25,
        "novelty": 40,
        "soundness": 15,
        "evidence": 10,
        "transparency": 5,
        "clarity": 5,
    },
}

_ANCHOR_COLUMNS = (
    "benchmarks_count",
    "sota_baselines_covered",
    "ablation_depth",
    "theoretical_rigor",
    "effect_size_ci_stability",
    "code_artifact_openness",
)

# Status / disposition token constants (referenced & verified by claim_audit)
STATUS_PASS = "PASS"
STATUS_WARN = "WARN"
STATUS_FAIL = "FAIL"
STATUS_PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
STATUS_NOT_SELECTED = "NOT_SELECTED"
STATUS_FATAL_GATE = "fatal_gate_triggered"
STATUS_REJECTED_TIER = "rejected_below_venue_tier"
STATUS_HOLD_REWORK = "hold_for_rework"
STATUS_READY_RESUB = "ready_for_resubmission"
STATUS_BLOCKED_RESUB = "resubmission_blocked"
STATUS_UNVERIFIED = "unverified"
DISP_FILTERED_HEURISTIC = "filtered_illegitimate_heuristic"
DISP_SUBSTANTIVE_DEFECT = "substantive_defect"
DISP_MINOR_POLISH = "presentation_minor"

# H1-H17 illegitimate heuristic catalog
H_RULES: dict[str, dict[str, str]] = {
    "H1": {"name": "not_surprising", "rationale": "Hindsight bias; intuitive hypotheses still require empirical testing."},
    "H2": {"name": "contradicts_expectations", "rationale": "Confirmation bias; requires concrete methodological or data flaw."},
    "H3": {"name": "bare_novelty_dismissal", "rationale": "Bare novelty dismissal without citing specific closing prior art."},
    "H4": {"name": "no_precedent", "rationale": "Conservatism bias penalizing original directions without precedent."},
    "H5": {"name": "not_sota", "rationale": "SOTA unnecessary when efficiency, calibration, interpretability, or analysis is claimed."},
    "H6": {"name": "negative_results", "rationale": "Publication bias against well-controlled null or negative findings."},
    "H7": {"name": "too_simple", "rationale": "Simplicity is a scientific virtue under the Parsimony Gate."},
    "H8": {"name": "preferred_method_bias", "rationale": "Reviewers must evaluate the chosen method against the stated RQ."},
    "H9": {"name": "too_niche", "rationale": "Specialized subfields and low-resource settings are valid archival contributions."},
    "H10": {"name": "monolingual_scope", "rationale": "Monolingual work is valid when cross-lingual universality is not claimed."},
    "H11": {"name": "language_errors", "rationale": "Presentation polish is minor when scientific claims stay intelligible."},
    "H12": {"name": "recent_or_preprint_omission", "rationale": "Works <3 months pre-deadline or arXiv-only preprints are optional suggestions."},
    "H13": {"name": "extra_experiment_wishlist", "rationale": "Only evidence required for the claimed scope is mandatory."},
    "H14": {"name": "closed_model_comparison", "rationale": "Proprietary APIs suffer contamination, version drift, and opacity."},
    "H15": {"name": "different_paper_bias", "rationale": "Critiques asking for a different paper do not invalidate the stated RQ."},
    "H16": {"name": "weaponized_limitations", "rationale": "Candid disclosed limitations must not be weaponized unless fatal to main claims."},
    "H17": {"name": "citation_count_bias", "rationale": "Low citation count of prior work or venue does not invalidate premise."},
}

# Substantive ARR issue taxonomy (M1-M5, T1-T2, R1-R5, G1-G4)
ARR_DEFECT_CATALOG: dict[str, dict[str, Any]] = {
    "M1": {"group": "Methodology", "title": "Unvalidated LLM-only evaluation", "impact": "medium_empirical_rigor", "effort_days": 3, "priority": 2, "section": "experiments"},
    "M2": {"group": "Methodology", "title": "Reproducibility / anonymity / artifact gaps", "impact": "medium_empirical_rigor", "effort_days": 2, "priority": 2, "section": "experiments"},
    "M3": {"group": "Methodology", "title": "Undisclosed data quality or contamination defects", "impact": "high_framing_or_soundness", "effort_days": 4, "priority": 1, "section": "experiments"},
    "M4": {"group": "Methodology", "title": "Unmotivated model or benchmark selection", "impact": "medium_empirical_rigor", "effort_days": 3, "priority": 2, "section": "experiments"},
    "M5": {"group": "Methodology", "title": "Incomplete theorem assumptions or proofs", "impact": "high_framing_or_soundness", "effort_days": 4, "priority": 1, "section": "method"},
    "T1": {"group": "Artifact_Ethics", "title": "Human-annotation ethics or compensation gaps", "impact": "high_framing_or_soundness", "effort_days": 2, "priority": 1, "section": "limitations"},
    "T2": {"group": "Artifact_Ethics", "title": "Unclear dataset or model release license terms", "impact": "medium_empirical_rigor", "effort_days": 1, "priority": 2, "section": "limitations"},
    "R1": {"group": "Experimental_Results", "title": "Cherry-picking, untuned baselines, or leakage", "impact": "high_framing_or_soundness", "effort_days": 4, "priority": 1, "section": "experiments"},
    "R2": {"group": "Experimental_Results", "title": "Overgeneralizing narrow sample to broad capability", "impact": "high_framing_or_soundness", "effort_days": 2, "priority": 1, "section": "abstract"},
    "R3": {"group": "Experimental_Results", "title": "Hypotheses stated as established conclusions", "impact": "high_framing_or_soundness", "effort_days": 2, "priority": 1, "section": "introduction"},
    "R4": {"group": "Experimental_Results", "title": "Construct-validity or novelty overclaiming", "impact": "high_framing_or_soundness", "effort_days": 2, "priority": 1, "section": "introduction"},
    "R5": {"group": "Experimental_Results", "title": "Missing statistical significance, CIs, or effect sizes", "impact": "medium_empirical_rigor", "effort_days": 3, "priority": 2, "section": "experiments"},
    "G1": {"group": "General", "title": "Unclear RQ, contribution, or method positioning", "impact": "high_framing_or_soundness", "effort_days": 2, "priority": 1, "section": "introduction"},
    "G2": {"group": "General", "title": "Reliance on discredited precedent", "impact": "high_framing_or_soundness", "effort_days": 3, "priority": 1, "section": "related_work"},
    "G3": {"group": "General", "title": "Missing or misrepresented >=3-month published related work", "impact": "high_framing_or_soundness", "effort_days": 2, "priority": 1, "section": "related_work"},
    "G4": {"group": "General", "title": "Undefined key technical terms or notation", "impact": "low_clarification", "effort_days": 1, "priority": 3, "section": "method"},
}

_PRECEDENT_CITE_RE = re.compile(
    r"(?:\[\d+(?:\s*,\s*\d+)*\]|\bet\s+al\.|\b(?:19|20)\d{2}[a-z]?\b|\barxiv:\d{4}\.\d+|\bdoi:\s*10\.)",
    re.I,
)


def _reject_nonfinite(token: str) -> None:
    raise ValueError(f"Non-finite JSON constant not allowed: {token}")


def _require_nonempty_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _require_dict_or_none(value: Any, name: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return value


_SINGLE_READINESS_KEYS = {
    "band",
    "fatal_gate_triggered",
    "fatal_dimensions",
    "bottleneck_dimensions",
    "fatal_reasons",
    "recommended_matched_tier",
    "ready_for_top_tier_main_track",
    "ready_for_findings_or_tier_a",
}


def _validate_readiness_dict(sr: dict[str, Any], name: str) -> dict[str, Any]:
    band = sr.get("band")
    if band is not None and (not isinstance(band, str) or not band.strip()):
        raise ValueError(f"{name}.band must be a non-empty string")
    rec_tier = sr.get("recommended_matched_tier")
    if rec_tier is not None and (not isinstance(rec_tier, str) or not rec_tier.strip()):
        raise ValueError(f"{name}.recommended_matched_tier must be a non-empty string")
    fgt = sr.get("fatal_gate_triggered")
    if fgt is not None and not isinstance(fgt, bool):
        raise ValueError(f"{name}.fatal_gate_triggered must be a boolean")
    for field in ("fatal_dimensions", "bottleneck_dimensions", "fatal_reasons"):
        raw = sr.get(field)
        if raw is not None:
            if not isinstance(raw, list) or any(not isinstance(item, str) or not item.strip() for item in raw):
                raise ValueError(f"{name}.{field} must be a list of non-empty strings")
    return sr


def _parse_json_file(path_str: str, label: str, expected_type: type | tuple[type, ...] | None = dict) -> Any:
    clean = _require_nonempty_str(path_str, label)
    p = Path(clean)
    if not p.is_file():
        raise ValueError(f"{label} file not found: {clean}")
    raw = p.read_text(encoding="utf-8")
    data = json.loads(raw, parse_constant=_reject_nonfinite)
    if expected_type is not None and not isinstance(data, expected_type):
        if expected_type is dict:
            raise ValueError(f"{label} must be a JSON object")
        raise ValueError(f"{label} has invalid JSON root type")
    return data


def _load_reviews_and_meta(path_str: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    clean = _require_nonempty_str(path_str, "--reviews")
    p = Path(clean)
    if not p.is_file():
        raise ValueError(f"--reviews file not found: {clean}")
    raw = p.read_text(encoding="utf-8")
    stripped = raw.strip()
    if stripped.startswith("{") or stripped.startswith("[") or clean.lower().endswith(".json"):
        data = json.loads(raw, parse_constant=_reject_nonfinite)
        if isinstance(data, list):
            if any(not isinstance(c, dict) for c in data):
                raise ValueError("--reviews JSON list entries must all be objects")
            return list(data), {}
        if isinstance(data, dict):
            if "comments" in data:
                if not isinstance(data["comments"], list) or any(not isinstance(c, dict) for c in data["comments"]):
                    raise ValueError("--reviews.comments must be a list of JSON objects")
                return list(data["comments"]), data
            if "reviews" in data:
                if not isinstance(data["reviews"], list):
                    raise ValueError("--reviews.reviews must be a list")
                out: list[dict[str, Any]] = []
                for idx, rev in enumerate(data["reviews"], start=1):
                    if not isinstance(rev, dict):
                        raise ValueError(f"--reviews.reviews[{idx - 1}] must be a JSON object")
                    if isinstance(rev.get("points"), list):
                        for pt in rev["points"]:
                            if not isinstance(pt, dict):
                                raise ValueError(f"--reviews.reviews[{idx - 1}].points entries must be JSON objects")
                            merged = dict(pt)
                            merged.setdefault("reviewer", rev.get("reviewer") or f"R{idx}")
                            out.append(merged)
                    else:
                        out.append(rev)
                if out:
                    return out, data
        raise ValueError("--reviews JSON must be a list or object with 'comments'/'reviews'")

    # Plain-text / Markdown fallback: extract bullet or R#.# lines
    comments: list[dict[str, Any]] = []
    pat = re.compile(r"^\s*(?:[-*]\s*)?(?:\*\*([A-Za-z0-9_.-]+)\*\*|([A-Za-z]+\d+(?:\.\d+)?))\s*[:\-]\s*(.+)$")
    for idx, line in enumerate(raw.splitlines(), start=1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = pat.match(s)
        if m:
            pid = (m.group(1) or m.group(2) or f"C{idx}").strip()
            comments.append({"id": pid, "reviewer": pid.split(".")[0], "text": m.group(3).strip()})
        elif s.startswith(("-", "*")):
            comments.append({"id": f"C{len(comments) + 1}", "reviewer": "Reviewer", "text": s.lstrip("-* ").strip()})
    if not comments:
        raise ValueError("No review comments found in --reviews file")
    return comments, {}


def _parse_text_or_json_reviews(path_str: str) -> list[dict[str, Any]]:
    comments, _ = _load_reviews_and_meta(path_str)
    return comments


def _parse_int_strict(value: Any, name: str, *, min_val: int | None = None, max_val: int | None = None) -> int:
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer (got {type(value).__name__})")
    if min_val is not None and value < min_val:
        raise ValueError(f"{name} must be >= {min_val} (got {value})")
    if max_val is not None and value > max_val:
        raise ValueError(f"{name} must be <= {max_val} (got {value})")
    return value


def _parse_number_strict(value: Any, name: str, *, min_val: float | None = None, max_val: float | None = None) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"{name} must be a finite number")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    try:
        dec = Decimal(str(value).strip())
    except Exception as exc:
        raise ValueError(f"{name} is not a valid number: {value!r}") from exc
    if not dec.is_finite():
        raise ValueError(f"{name} must be finite")
    if min_val is not None and dec < Decimal(str(min_val)):
        raise ValueError(f"{name} must be >= {min_val}")
    if max_val is not None and dec > Decimal(str(max_val)):
        raise ValueError(f"{name} must be <= {max_val}")
    return dec


def _parse_iso_utc(value: Any, name: str) -> datetime:
    s = _require_nonempty_str(value, name)
    if s.endswith(" AoE"):
        dt = datetime.fromisoformat(s[:-4])
        if dt.tzinfo is not None:
            raise ValueError(f"{name}: AoE timestamp must not carry an offset")
        return dt.replace(tzinfo=timezone(timedelta(hours=-12))).astimezone(timezone.utc)
    if len(s) == 10 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone or YYYY-MM-DD date")
    return dt.astimezone(timezone.utc)


def _quant2(dec: Decimal) -> Decimal:
    with localcontext(BasicContext) as ctx:
        ctx.prec = 28
        return dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _resolve_tier_arg(raw_tier: str | None) -> str | None:
    if raw_tier is None:
        return None
    clean = _require_nonempty_str(raw_tier, "--venue-tier")
    resolved = score_math.resolve_venue_tier(venue_name=clean, tier_expectation=clean)
    if resolved is not None:
        return resolved
    low = clean.lower()
    if any(tok in low for tok in ("neurips", "icml", "iclr", "cvpr", "iccv", "eccv", "acl", "emnlp", "aaai", "kdd", "tpami", "jmlr")):
        return "top_tier_flagship"
    if any(tok in low for tok in ("tmlr", "tacl", "naacl", "coling", "ijcai")):
        return "q1_or_tier_a"
    raise ValueError(f"Unrecognized --venue-tier: {raw_tier}")


def _validate_ratings_and_weights(ratings_raw: dict[str, Any], weights_raw: dict[str, Any] | None) -> tuple[dict[str, int | None], dict[str, int]]:
    if not isinstance(ratings_raw, dict):
        raise ValueError("ratings must be a JSON object")
    if set(ratings_raw.keys()) != set(score_math.DIMENSIONS):
        raise ValueError("ratings must contain exactly the 6 canonical dimensions")
    clean_ratings: dict[str, int | None] = {}
    for dim in score_math.DIMENSIONS:
        v = ratings_raw[dim]
        if v is None:
            clean_ratings[dim] = None
        else:
            clean_ratings[dim] = _parse_int_strict(v, f"ratings.{dim}", min_val=0, max_val=10)
    if weights_raw is None:
        clean_weights = dict(_DEFAULT_WEIGHTS)
    else:
        if not isinstance(weights_raw, dict) or set(weights_raw.keys()) != set(score_math.DIMENSIONS):
            raise ValueError("weights must contain exactly the 6 canonical dimensions")
        clean_weights = {
            dim: _parse_int_strict(weights_raw[dim], f"weights.{dim}", min_val=0, max_val=100)
            for dim in score_math.DIMENSIONS
        }
        if sum(clean_weights.values()) != 100:
            raise ValueError("weights must sum to 100")
    return clean_ratings, clean_weights


def _extract_scorecard_state(
    bundle: dict[str, Any],
    scorecard_obj: Any,
) -> dict[str, Any]:
    """Extract normalized ratings, weights, score_math result, and compare_scorecards signals."""
    _require_dict_or_none(scorecard_obj, "--scorecard")
    b_sc = _require_dict_or_none(bundle.get("scorecard"), "scorecard")
    b_scb = _require_dict_or_none(bundle.get("scorecards_bundle"), "scorecards_bundle")
    b_scs = _require_dict_or_none(bundle.get("scorecards"), "scorecards")

    target_id = bundle.get("target_id")
    status_meta = bundle.get("status")
    object_type_meta = bundle.get("object_type")

    def _parse_single_source(src: dict[str, Any], cur_tid: Any) -> dict[str, Any]:
        work = src
        if (
            "ratings" not in work
            and not ("profiles" in work and isinstance(work.get("profiles"), list))
            and "submission_readiness" not in work
            and "rankings" not in work
            and not ("compact" in work and "status" in work)
            and "scorecard" in work
        ):
            inner = _require_dict_or_none(work.get("scorecard"), "scorecard.scorecard")
            if inner is not None:
                cur_tid = cur_tid or work.get("target_id")
                work = inner

        parsed: dict[str, Any] = {
            "ratings": None,
            "weights": None,
            "status_meta": work.get("status"),
            "object_type_meta": work.get("object_type"),
            "target_id": cur_tid,
            "score_math_output": None,
            "compare_scorecards": None,
        }
        if "ratings" in work:
            if not isinstance(work["ratings"], dict):
                raise ValueError("scorecard.ratings must be a JSON object")
            if "submission_readiness" in work and work["submission_readiness"] is not None:
                _validate_readiness_dict(
                    _require_dict_or_none(work["submission_readiness"], "scorecard.submission_readiness") or {},
                    "scorecard.submission_readiness",
                )
            r_clean, w_clean = _validate_ratings_and_weights(work["ratings"], work.get("weights"))
            parsed["ratings"] = r_clean
            parsed["weights"] = w_clean
        elif "profiles" in work and isinstance(work["profiles"], list):
            tid = cur_tid or work.get("target_id")
            chosen = None
            for prof in work["profiles"]:
                if isinstance(prof, dict):
                    if tid and prof.get("id") == tid:
                        chosen = prof
                        break
                    if chosen is None:
                        chosen = prof
            if chosen is not None and "ratings" in chosen:
                if not isinstance(chosen["ratings"], dict):
                    raise ValueError("scorecards_bundle.profiles[].ratings must be a JSON object")
                scenarios = work.get("weight_scenarios") or []
                w0 = scenarios[0] if scenarios and isinstance(scenarios[0], dict) else None
                r_clean, w_clean = _validate_ratings_and_weights(chosen["ratings"], w0)
                parsed["ratings"] = r_clean
                parsed["weights"] = w_clean
                parsed["status_meta"] = chosen.get("status", parsed["status_meta"])
                parsed["object_type_meta"] = chosen.get("object_type", parsed["object_type_meta"])
                parsed["target_id"] = chosen.get("id") or tid
        elif "submission_readiness" in work:
            sr_val = _require_dict_or_none(work["submission_readiness"], "submission_readiness") or {}
            is_single_sr = "rankings" not in work and (
                any(k in _SINGLE_READINESS_KEYS for k in sr_val)
                or (bool(sr_val) and not all(isinstance(v, dict) for v in sr_val.values()))
                or (not sr_val and ("weighted_unrounded" in work or "overall" in work))
            )
            if is_single_sr:
                _validate_readiness_dict(sr_val, "scorecard.submission_readiness")
                parsed["score_math_output"] = work
            else:
                for k, v in sr_val.items():
                    v_dict = _require_dict_or_none(v, f"scorecard.submission_readiness.{k}")
                    if v_dict is not None:
                        _validate_readiness_dict(v_dict, f"scorecard.submission_readiness.{k}")
                parsed["compare_scorecards"] = work
                tid = cur_tid
                rwc_val = _require_dict_or_none(work.get("related_work_comparison"), "scorecard.related_work_comparison")
                if rwc_val is not None:
                    tid = tid or rwc_val.get("target_id")
                if not tid and sr_val:
                    tid = next(iter(sr_val.keys()))
                parsed["target_id"] = tid
        elif "rankings" in work or ("compact" in work and "status" in work):
            parsed["compare_scorecards"] = work
        return parsed

    def _build_score_res_from_signals(
        sm_out: dict[str, Any] | None,
        csc: dict[str, Any] | None,
        cur_tid: Any,
    ) -> tuple[dict[str, Any] | None, Any, dict[str, Any] | None, dict[str, Any] | None, dict[str, int | None] | None]:
        res_out: dict[str, Any] | None = None
        pre_mp: dict[str, Any] | None = None
        pre_db: dict[str, Any] | None = None
        inferred_r: dict[str, int | None] | None = None
        tid = cur_tid

        if sm_out is not None:
            if sm_out.get("weighted_unrounded") is not None:
                _parse_number_strict(sm_out["weighted_unrounded"], "scorecard.weighted_unrounded", min_val=0, max_val=10)
            if sm_out.get("overall") is not None:
                _parse_number_strict(sm_out["overall"], "scorecard.overall", min_val=0, max_val=10)
            sm_sr = _require_dict_or_none(sm_out.get("submission_readiness"), "scorecard.submission_readiness")
            if sm_sr is not None:
                _validate_readiness_dict(sm_sr, "scorecard.submission_readiness")
            res_out = sm_out
            pre_mp = _require_dict_or_none(sm_out.get("merit_vs_packaging"), "scorecard.merit_vs_packaging")
            pre_db = _require_dict_or_none(sm_out.get("deal_breaker_sensitivity"), "scorecard.deal_breaker_sensitivity")

        if isinstance(csc, dict):
            sr_map = _require_dict_or_none(csc.get("submission_readiness"), "scorecard.submission_readiness") or {}
            for k, v in sr_map.items():
                v_dict = _require_dict_or_none(v, f"scorecard.submission_readiness.{k}")
                if v_dict is not None:
                    _validate_readiness_dict(v_dict, f"scorecard.submission_readiness.{k}")
            rwc = _require_dict_or_none(csc.get("related_work_comparison"), "scorecard.related_work_comparison") or {}
            tid = tid or rwc.get("target_id")
            if not tid and sr_map:
                tid = next(iter(sr_map.keys()))
            elif not tid and isinstance(csc.get("rankings"), list) and csc["rankings"]:
                first_r = csc["rankings"][0]
                if isinstance(first_r, dict) and isinstance(first_r.get("ordered"), list) and first_r["ordered"]:
                    first_row = first_r["ordered"][0]
                    if isinstance(first_row, dict):
                        tid = first_row.get("id")

            if res_out is None:
                t_sr: dict[str, Any] = {}
                if tid and tid in sr_map:
                    t_sr = dict(_require_dict_or_none(sr_map[tid], f"scorecard.submission_readiness.{tid}") or {})
                elif sr_map:
                    first_k = next(iter(sr_map.keys()))
                    t_sr = dict(_require_dict_or_none(sr_map[first_k], f"scorecard.submission_readiness.{first_k}") or {})
                _validate_readiness_dict(t_sr, "scorecard.submission_readiness")

                w_unrounded = t_sr.get("weighted_unrounded")
                if w_unrounded is None and isinstance(csc.get("rankings"), list) and csc["rankings"]:
                    first_r = csc["rankings"][0]
                    ordered = first_r.get("ordered") if isinstance(first_r, dict) else None
                    if isinstance(ordered, list):
                        for row in ordered:
                            if isinstance(row, dict) and (not tid or row.get("id") == tid):
                                w_unrounded = row.get("weighted_unrounded")
                                break
                        if w_unrounded is None and ordered and isinstance(ordered[0], dict):
                            w_unrounded = ordered[0].get("weighted_unrounded")

                if w_unrounded is not None:
                    _parse_number_strict(w_unrounded, "scorecard.weighted_unrounded", min_val=0, max_val=10)
                if t_sr.get("overall") is not None:
                    _parse_number_strict(t_sr["overall"], "scorecard.overall", min_val=0, max_val=10)

                if t_sr.get("band") == "not_ready_fatal_gate":
                    t_sr["fatal_gate_triggered"] = True
                if t_sr.get("fatal_gate_triggered") and not t_sr.get("fatal_reasons"):
                    fdims = t_sr.get("fatal_dimensions") or []
                    t_sr["fatal_reasons"] = (
                        [f"{d}<={score_math.FATAL_THRESHOLDS.get(d, 4)}" for d in fdims]
                        if fdims
                        else ["fatal_gate_triggered"]
                    )

                if t_sr or w_unrounded is not None:
                    band_val = t_sr.get("band")
                    is_not_comp = (
                        band_val in ("not_comparable_missing_dimension", "not_comparable_structural_gate")
                        or w_unrounded is None
                    )
                    res_out = {
                        "overall": t_sr.get("overall"),
                        "weighted_unrounded": str(w_unrounded) if w_unrounded is not None else None,
                        "status": "not_comparable" if is_not_comp else "calculated",
                        "submission_readiness": t_sr,
                    }

            max_rel = _require_dict_or_none(rwc.get("max_related_by_dimension"), "scorecard.related_work_comparison.max_related_by_dimension")
            deltas_rel = _require_dict_or_none(rwc.get("dimension_deltas_vs_max_related"), "scorecard.related_work_comparison.dimension_deltas_vs_max_related")
            if max_rel is not None and deltas_rel is not None:
                cand_inf: dict[str, int | None] = {}
                ok = True
                for dim in score_math.DIMENSIONS:
                    mx = max_rel.get(dim)
                    dl = deltas_rel.get(dim)
                    if type(mx) is int and type(dl) is int and 0 <= mx + dl <= 10:
                        cand_inf[dim] = mx + dl
                    elif dl is None and type(mx) is int:
                        cand_inf[dim] = None
                    else:
                        ok = False
                        break
                if ok and len(cand_inf) == len(score_math.DIMENSIONS):
                    inferred_r = cand_inf

            if pre_mp is None and csc.get("merit_vs_packaging") is not None:
                mvp_map = _require_dict_or_none(csc.get("merit_vs_packaging"), "scorecard.merit_vs_packaging") or {}
                if "scientific_merit_score" in mvp_map:
                    pre_mp = mvp_map
                elif tid and mvp_map.get(tid) is not None:
                    pre_mp = _require_dict_or_none(mvp_map[tid], f"scorecard.merit_vs_packaging.{tid}")
                else:
                    pre_mp = next((v for v in mvp_map.values() if isinstance(v, dict)), None)

            if pre_db is None and csc.get("deal_breaker_sensitivity") is not None:
                db_map = _require_dict_or_none(csc.get("deal_breaker_sensitivity"), "scorecard.deal_breaker_sensitivity") or {}
                if "worst_case_reviewer_floor" in db_map:
                    pre_db = db_map
                elif tid and db_map.get(tid) is not None:
                    pre_db = _require_dict_or_none(db_map[tid], f"scorecard.deal_breaker_sensitivity.{tid}")
                else:
                    pre_db = next((v for v in db_map.values() if isinstance(v, dict)), None)

        return res_out, tid, pre_mp, pre_db, inferred_r

    ratings: dict[str, int | None] | None = None
    weights: dict[str, int] | None = None
    score_res: dict[str, Any] | None = None
    csc: dict[str, Any] | None = None
    precomputed_merit_packaging: dict[str, Any] | None = None
    precomputed_deal_breaker: dict[str, Any] | None = None
    inferred_ratings: dict[str, int | None] | None = None

    bundle_sources = [cand for cand in (b_sc, b_scb, b_scs) if cand is not None]

    if scorecard_obj is not None:
        cli_parsed = _parse_single_source(scorecard_obj, target_id)
        if cli_parsed["target_id"] is not None:
            target_id = cli_parsed["target_id"]
        if cli_parsed["status_meta"] is not None:
            status_meta = cli_parsed["status_meta"]
        if cli_parsed["object_type_meta"] is not None:
            object_type_meta = cli_parsed["object_type_meta"]

        if cli_parsed["ratings"] is not None and cli_parsed["weights"] is not None:
            ratings = cli_parsed["ratings"]
            weights = cli_parsed["weights"]
            score_payload: dict[str, Any] = {"weights": weights, "ratings": ratings}
            if status_meta is not None:
                score_payload["status"] = status_meta
            if object_type_meta is not None:
                score_payload["object_type"] = object_type_meta
            score_res = score_math.score(score_payload)
        else:
            csc = cli_parsed["compare_scorecards"]
            score_res, target_id, precomputed_merit_packaging, precomputed_deal_breaker, inferred_ratings = (
                _build_score_res_from_signals(cli_parsed["score_math_output"], csc, target_id)
            )
            # Only accept supplemental raw ratings/weights from --input bundle when consistent with --scorecard
            if score_res is not None:
                cli_sr = _validate_readiness_dict(
                    _require_dict_or_none(score_res.get("submission_readiness"), "scorecard.submission_readiness") or {},
                    "scorecard.submission_readiness",
                )
                cli_w = score_res.get("weighted_unrounded")
                cli_fatal = bool(cli_sr.get("fatal_gate_triggered"))
                cli_fdims = list(cli_sr.get("fatal_dimensions") or [])
                cli_band = cli_sr.get("band")
                cli_bdims = set(cli_sr.get("bottleneck_dimensions") or [])
                cli_rec_tier = cli_sr.get("recommended_matched_tier")
                for b_cand in bundle_sources:
                    bp = _parse_single_source(b_cand, target_id)
                    if bp["ratings"] is None or bp["weights"] is None:
                        continue
                    b_payload: dict[str, Any] = {"weights": bp["weights"], "ratings": bp["ratings"]}
                    b_status = bp["status_meta"] if bp["status_meta"] is not None else status_meta
                    b_otype = bp["object_type_meta"] if bp["object_type_meta"] is not None else object_type_meta
                    if b_status is not None:
                        b_payload["status"] = b_status
                    if b_otype is not None:
                        b_payload["object_type"] = b_otype
                    b_res = score_math.score(b_payload)
                    b_sr = _validate_readiness_dict(
                        _require_dict_or_none(b_res.get("submission_readiness"), "bundle.scorecard.submission_readiness") or {},
                        "bundle.scorecard.submission_readiness",
                    )
                    b_w = b_res.get("weighted_unrounded")
                    if cli_w is None:
                        w_match = b_w is None
                    elif b_w is None:
                        w_match = False
                    else:
                        w_match = Decimal(str(cli_w)) == Decimal(str(b_w))
                    fatal_match = bool(b_sr.get("fatal_gate_triggered")) == cli_fatal
                    fdims_match = (not cli_fdims) or (set(b_sr.get("fatal_dimensions") or []) == set(cli_fdims))
                    band_match = b_sr.get("band") == cli_band
                    bdims_match = set(b_sr.get("bottleneck_dimensions") or []) == cli_bdims
                    rec_tier_match = (not cli_rec_tier) or (b_sr.get("recommended_matched_tier") == cli_rec_tier)
                    if w_match and fatal_match and fdims_match and band_match and bdims_match and rec_tier_match:
                        ratings = bp["ratings"]
                        weights = bp["weights"]
                        if b_status is not None:
                            status_meta = b_status
                        if b_otype is not None:
                            object_type_meta = b_otype
                        break
    else:
        sm_out = None
        for b_cand in bundle_sources:
            bp = _parse_single_source(b_cand, target_id)
            if bp["ratings"] is not None and ratings is None:
                ratings = bp["ratings"]
                weights = bp["weights"]
                if bp["status_meta"] is not None:
                    status_meta = bp["status_meta"]
                if bp["object_type_meta"] is not None:
                    object_type_meta = bp["object_type_meta"]
                if bp["target_id"] is not None:
                    target_id = bp["target_id"]
            if bp["score_math_output"] is not None and sm_out is None:
                sm_out = bp["score_math_output"]
            if bp["compare_scorecards"] is not None and csc is None:
                csc = bp["compare_scorecards"]
                if bp["target_id"] is not None:
                    target_id = bp["target_id"]

        if ratings is not None and weights is not None:
            score_payload = {"weights": weights, "ratings": ratings}
            if status_meta is not None:
                score_payload["status"] = status_meta
            if object_type_meta is not None:
                score_payload["object_type"] = object_type_meta
            score_res = score_math.score(score_payload)
        sig_res, target_id, precomputed_merit_packaging, precomputed_deal_breaker, inferred_ratings = (
            _build_score_res_from_signals(sm_out, csc, target_id)
        )
        if score_res is None:
            score_res = sig_res

    return {
        "target_id": target_id,
        "ratings": ratings,
        "inferred_ratings": inferred_ratings,
        "weights": weights or dict(_DEFAULT_WEIGHTS),
        "is_idea": any(
            isinstance(x, str) and x.strip().lower() == "idea"
            for x in (status_meta, object_type_meta)
        ),
        "score_result": score_res,
        "compare_scorecards": csc,
        "precomputed_merit_packaging": precomputed_merit_packaging,
        "precomputed_deal_breaker": precomputed_deal_breaker,
    }


def _reconcile_tier_fit_with_readiness(
    tier_fit: dict[str, Any] | None,
    sr: dict[str, Any] | None,
    effective_tier: str | None,
    *,
    ratings: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if tier_fit is None or not isinstance(sr, dict):
        return tier_fit
    _validate_readiness_dict(sr, "submission_readiness")
    reasons = list(tier_fit.get("rejection_reasons") or [])
    if sr.get("fatal_gate_triggered") or sr.get("band") == "not_ready_fatal_gate":
        tier_fit["rejected_below_venue_tier"] = True
        tier_fit["recommended_matched_tier"] = "none_hold_for_rework"
        for fr in (sr.get("fatal_reasons") or ["fatal_gate_triggered"]):
            if fr not in reasons:
                reasons.append(fr)
        tier_fit["rejection_reasons"] = reasons
        return tier_fit

    if ratings is not None:
        return tier_fit

    rec_tier = sr.get("recommended_matched_tier")
    if rec_tier == "none_hold_for_rework":
        tier_fit["recommended_matched_tier"] = "none_hold_for_rework"
        if effective_tier in score_math.VENUE_TIER_ORDER:
            tier_fit["rejected_below_venue_tier"] = True
            if not reasons:
                reasons.append("recommended_matched_tier_none_hold_for_rework")
    elif rec_tier in score_math.VENUE_TIER_ORDER and effective_tier in score_math.VENUE_TIER_ORDER:
        if effective_tier == "top_tier_flagship":
            below_floor = rec_tier in ("q2_q3_or_tier_b", "workshop_or_preliminary")
        else:
            below_floor = score_math.VENUE_TIER_ORDER.index(rec_tier) > score_math.VENUE_TIER_ORDER.index(effective_tier)
        if below_floor:
            tier_fit["rejected_below_venue_tier"] = True
            tier_fit["recommended_matched_tier"] = rec_tier
            b_dims = [str(d) for d in (sr.get("bottleneck_dimensions") or []) if isinstance(d, str)]
            reason_tok = (
                f"bottleneck_below_{effective_tier}_floor:{','.join(b_dims)}"
                if b_dims
                else f"recommended_matched_tier_{rec_tier}_below_{effective_tier}"
            )
            if reason_tok not in reasons:
                reasons.append(reason_tok)
        elif tier_fit.get("recommended_matched_tier") is None or (
            tier_fit["recommended_matched_tier"] in score_math.VENUE_TIER_ORDER
            and score_math.VENUE_TIER_ORDER.index(rec_tier) > score_math.VENUE_TIER_ORDER.index(tier_fit["recommended_matched_tier"])
        ):
            tier_fit["recommended_matched_tier"] = rec_tier
    elif rec_tier is None and effective_tier in ("top_tier_flagship", "q1_or_tier_a"):
        b_dims = [str(d) for d in (sr.get("bottleneck_dimensions") or []) if isinstance(d, str)]
        w_raw = sr.get("weighted_unrounded")
        w_dec: Decimal | None = None
        if w_raw is not None:
            w_dec = _parse_number_strict(w_raw, "submission_readiness.weighted_unrounded", min_val=0, max_val=10)
        high_score_core_floor_fail = (
            w_dec is not None and w_dec >= Decimal("6.80") and any(d in ("soundness", "evidence") for d in b_dims)
        )
        single_core_bottleneck_fail = (
            w_dec is not None
            and Decimal("6.00") <= w_dec < Decimal("6.80")
            and len(b_dims) == 1
            and b_dims[0] in ("soundness", "evidence")
        )
        if high_score_core_floor_fail or single_core_bottleneck_fail:
            tier_fit["rejected_below_venue_tier"] = True
            tier_fit["recommended_matched_tier"] = "q2_q3_or_tier_b"
            reason_tok = f"bottleneck_below_{effective_tier}_floor:{','.join(b_dims)}"
            if reason_tok not in reasons:
                reasons.append(reason_tok)

    tier_fit["rejection_reasons"] = reasons
    return tier_fit


def _detect_and_ingest_upstream(
    bundle: dict[str, Any],
    *,
    venue_novelty_obj: Any = None,
    rigor_objs: list[Any] | None = None,
    ledger_obj: Any = None,
    preflight_objs: list[Any] | None = None,
    artifact_obj: Any = None,
    venue_sources_obj: Any = None,
    venue_plan_obj: Any = None,
    eng_diag_obj: Any = None,
) -> dict[str, Any]:
    """Normalize both full and --compact upstream JSON outputs."""
    for name, obj in (
        ("--venue-novelty", venue_novelty_obj),
        ("--ledger", ledger_obj),
        ("--artifact-readiness", artifact_obj),
        ("--venue-sources", venue_sources_obj),
        ("--venue-plan", venue_plan_obj),
        ("--engineering-diagnostics", eng_diag_obj),
    ):
        if obj is not None and not isinstance(obj, dict):
            raise ValueError(f"{name} must be a JSON object")

    out: dict[str, Any] = {
        "venue_novelty": _require_dict_or_none(
            venue_novelty_obj if venue_novelty_obj is not None else (
                bundle.get("venue_novelty") if bundle.get("venue_novelty") is not None else bundle.get("venue_portfolio")
            ),
            "venue_novelty",
        ),
        "rigor": [],
        "ledger": _require_dict_or_none(
            ledger_obj if ledger_obj is not None else (
                bundle.get("ledger") if bundle.get("ledger") is not None else bundle.get("manuscript_ledger")
            ),
            "ledger",
        ),
        "preflight": [],
        "artifact_readiness": _require_dict_or_none(
            artifact_obj if artifact_obj is not None else bundle.get("artifact_readiness"),
            "artifact_readiness",
        ),
        "venue_sources": _require_dict_or_none(
            venue_sources_obj if venue_sources_obj is not None else bundle.get("venue_sources"),
            "venue_sources",
        ),
        "venue_plan": _require_dict_or_none(
            venue_plan_obj if venue_plan_obj is not None else bundle.get("venue_plan"),
            "venue_plan",
        ),
        "engineering_diagnostics": _require_dict_or_none(
            eng_diag_obj if eng_diag_obj is not None else bundle.get("engineering_diagnostics"),
            "engineering_diagnostics",
        ),
    }
    raw_rigor = rigor_objs if rigor_objs is not None else (
        bundle.get("rigor") if bundle.get("rigor") is not None else (bundle.get("experiment_rigor") or [])
    )
    if isinstance(raw_rigor, dict):
        raw_rigor = [raw_rigor]
    if isinstance(raw_rigor, list):
        if rigor_objs is not None and any(not isinstance(r, dict) for r in raw_rigor):
            raise ValueError("--rigor entries must be JSON objects")
        out["rigor"] = [r for r in raw_rigor if isinstance(r, dict)]

    raw_preflight = preflight_objs if preflight_objs is not None else (bundle.get("preflight") or [])
    if isinstance(raw_preflight, dict):
        raw_preflight = [raw_preflight]
    if isinstance(raw_preflight, list):
        if preflight_objs is not None and any(not isinstance(p, dict) for p in raw_preflight):
            raise ValueError("--preflight entries must be JSON objects")
        out["preflight"] = [p for p in raw_preflight if isinstance(p, dict)]

    return out


def _add_defect(
    defects: list[dict[str, Any]],
    *,
    persona: str,
    severity: str,
    code: str,
    source_tool: str,
    section: str | None,
    summary: str,
    remediation: str,
) -> None:
    defects.append({
        "id": f"DEF-{len(defects) + 1:03d}",
        "persona": persona,
        "severity": severity,
        "code": code,
        "source_tool": source_tool,
        "section": section,
        "summary": summary,
        "remediation": remediation,
    })


def _eval_subfield_preset(
    preset_key: str | None,
    subfield_checks: dict[str, Any] | None,
    upstream: dict[str, Any],
    defects: list[dict[str, Any]],
) -> dict[str, Any]:
    preset_catalog: dict[str, dict[str, Any]] = {}
    if preset_key is not None and preset_key not in SUBFIELD_PRESETS:
        raise ValueError(f"Unknown subfield preset: {preset_key}")

    # Infer automatic passes/failures from rigor reports (never let pass overwrite fail)
    inferred: dict[str, str] = {}
    for r in upstream["rigor"]:
        if r.get("schema") == "experiment_rigor_contamination_v1":
            if r.get("verdict") == "CONTAMINATION_DETECTED":
                inferred["contamination_check"] = "fail"
            elif inferred.get("contamination_check") != "fail":
                inferred["contamination_check"] = "pass"
        if r.get("schema") == "experiment_rigor_rliable_v1":
            warns = r.get("warnings") or []
            if any(isinstance(w, str) and w.startswith("underpowered_seeds") for w in warns):
                inferred.setdefault("multi_prompt_variance", "warn")

    eng_diag = upstream.get("engineering_diagnostics")
    if preset_key == "speech_audio" and isinstance(eng_diag, dict):
        speech_cfg_tokens = (
            "sample_rate",
            "vocoder",
            "lm_decoding",
            "decoding_strategy",
            "embedding_backend",
            "score_normalization",
        )
        for finding in (eng_diag.get("findings") or []):
            if not isinstance(finding, dict):
                continue
            cat = str(finding.get("category") or "")
            loc = str(finding.get("location") or "").casefold()
            det = str(finding.get("detail") or "").casefold()
            if cat in ("group_leakage_across_splits", "split_overlap_leakage"):
                inferred["speaker_session_disjoint_split"] = "fail"
            elif cat == "budget_or_config_mismatch" and any(tok in loc or tok in det for tok in speech_cfg_tokens):
                inferred["decoding_vocoder_embedding_parity"] = "fail"

    checks_input = subfield_checks if isinstance(subfield_checks, dict) else {}
    active_result: dict[str, Any] = {
        "active_preset": preset_key,
        "status": STATUS_NOT_SELECTED if preset_key is None else STATUS_PASS,
        "required_checks": list(SUBFIELD_PRESETS.get(preset_key, ())),
        "covered_checks": [],
        "missing_checks": [],
        "failed_checks": [],
    }

    for key, reqs in SUBFIELD_PRESETS.items():
        is_active = key == preset_key
        covered: list[str] = []
        missing: list[str] = []
        failed: list[str] = []
        if is_active:
            for chk in reqs:
                raw_val = checks_input.get(chk, inferred.get(chk))
                status_tok = None
                detail = ""
                if isinstance(raw_val, bool):
                    status_tok = "pass" if raw_val else "fail"
                elif isinstance(raw_val, str):
                    status_tok = raw_val.strip().lower()
                elif isinstance(raw_val, dict):
                    status_tok = str(raw_val.get("status", "")).strip().lower()
                    detail = str(raw_val.get("detail") or raw_val.get("reason") or "")

                if status_tok in ("pass", "passed", "ok", "verified", "true"):
                    covered.append(chk)
                elif status_tok in ("fail", "failed", "error", "contaminated"):
                    failed.append(chk)
                    sev = "fatal" if chk in _PRESET_CRITICAL_CHECKS else "major"
                    _add_defect(
                        defects,
                        persona=_PRESET_PERSONA_MAP[key],
                        severity=sev,
                        code="M5" if key == "ml_theory" else ("M3" if chk == "contamination_check" else "R1"),
                        source_tool="subfield_preset_audit",
                        section="method" if key == "ml_theory" else "experiments",
                        summary=f"[{key}] Subfield preset control failed: {chk}" + (f" ({detail})" if detail else ""),
                        remediation=f"Resolve and verify `{chk}` control for `{key}` preset before submission.",
                    )
                else:
                    missing.append(chk)
                    _add_defect(
                        defects,
                        persona=_PRESET_PERSONA_MAP[key],
                        severity="major",
                        code="M5" if key == "ml_theory" else "M4",
                        source_tool="subfield_preset_audit",
                        section="method" if key == "ml_theory" else "experiments",
                        summary=f"[{key}] Missing required subfield preset control: {chk}",
                        remediation=f"Supply verified `{chk}` control evidence under `{key}` rubric.",
                    )
            active_result["covered_checks"] = covered
            active_result["missing_checks"] = missing
            active_result["failed_checks"] = failed
            if failed:
                active_result["status"] = STATUS_FAIL
            elif missing:
                active_result["status"] = STATUS_WARN
            else:
                active_result["status"] = STATUS_PASS
            preset_status = active_result["status"]
        else:
            preset_status = STATUS_NOT_SELECTED

        preset_catalog[key] = {
            "active": is_active,
            "status": preset_status,
            "required_checks": list(reqs),
            "covered_checks": covered if is_active else [],
            "missing_checks": missing if is_active else [],
            "failed_checks": failed if is_active else [],
        }

    # Exact 5 preset keys guaranteed under `presets`
    active_result["presets"] = preset_catalog
    return active_result


def _normalize_anchor_row(raw: dict[str, Any], target_overall: Decimal | None) -> dict[str, Any]:
    aid = str(raw.get("anchor_id") or raw.get("id") or "anchor_unknown")
    topic_rel = str(raw.get("topic_relation") or raw.get("relation") or STATUS_UNVERIFIED)
    ratings_raw = raw.get("ratings")
    if ratings_raw is not None and not isinstance(ratings_raw, dict):
        raise ValueError(f"anchor.{aid}.ratings must be a JSON object")
    r_clean: dict[str, int | None] | None = None
    w_clean: dict[str, int] | None = None
    if isinstance(ratings_raw, dict):
        r_clean, w_clean = _validate_ratings_and_weights(ratings_raw, raw.get("weights"))

    overall_raw = raw.get("overall_score") if raw.get("overall_score") is not None else raw.get("overall")
    overall_dec: Decimal | None = None
    if overall_raw is not None:
        overall_dec = _parse_number_strict(overall_raw, f"anchor.{aid}.overall_score", min_val=0, max_val=10)
    elif r_clean is not None and w_clean is not None:
        sr = score_math.score({"weights": w_clean, "ratings": r_clean})
        if sr.get("weighted_unrounded") is not None:
            overall_dec = _parse_number_strict(sr["weighted_unrounded"], f"anchor.{aid}.weighted_unrounded", min_val=0, max_val=10)

    raw_nov = raw.get("novelty_score") if raw.get("novelty_score") is not None else raw.get("score")
    if raw_nov is not None:
        nov_dec = _parse_number_strict(raw_nov, f"anchor.{aid}.novelty_score", min_val=0, max_val=10)
        novelty_score: int | float | None = int(nov_dec) if nov_dec == int(nov_dec) else float(str(_quant2(nov_dec)))
    elif r_clean is not None:
        novelty_score = r_clean.get("novelty")
    else:
        novelty_score = None

    columns = {}
    for col in _ANCHOR_COLUMNS:
        val = raw.get(col)
        columns[col] = val if val is not None else STATUS_UNVERIFIED

    delta_overall = None
    if target_overall is not None and overall_dec is not None:
        delta_overall = float(str(_quant2(target_overall - overall_dec)))

    return {
        "anchor_id": aid,
        "topic_relation": topic_rel,
        "overall_score": float(str(_quant2(overall_dec))) if overall_dec is not None else None,
        "novelty_score": novelty_score,
        "target_delta_overall": delta_overall,
        **columns,
    }


def _build_anchor_contrast(
    bundle: dict[str, Any],
    anchors_arg: Any,
    upstream: dict[str, Any],
    sc_state: dict[str, Any],
) -> dict[str, Any]:
    target_overall = None
    sr = sc_state.get("score_result")
    if isinstance(sr, dict) and sr.get("weighted_unrounded") is not None:
        target_overall = _parse_number_strict(sr["weighted_unrounded"], "scorecard.weighted_unrounded", min_val=0, max_val=10)

    raw_anchors: list[dict[str, Any]] = []
    if anchors_arg is not None:
        if isinstance(anchors_arg, list):
            if any(not isinstance(a, dict) for a in anchors_arg):
                raise ValueError("--anchors list items must be JSON objects")
            raw_anchors = list(anchors_arg)
        elif isinstance(anchors_arg, dict):
            if not isinstance(anchors_arg.get("anchors"), list) or any(not isinstance(a, dict) for a in anchors_arg["anchors"]):
                raise ValueError("--anchors JSON object must contain an 'anchors' list of objects")
            raw_anchors = list(anchors_arg["anchors"])
        else:
            raise ValueError("--anchors must be a JSON list or object with 'anchors' list")
    elif bundle.get("anchors") is not None:
        if not isinstance(bundle["anchors"], list) or any(not isinstance(a, dict) for a in bundle["anchors"]):
            raise ValueError("anchors must be a list of JSON objects")
        raw_anchors = list(bundle["anchors"])

    # Fallback: derive from accepted_panel or scorecards_bundle non-target profiles
    if not raw_anchors and anchors_arg is None:
        vn = upstream.get("venue_novelty")
        if isinstance(vn, dict):
            panel = vn.get("accepted_panel")
            if not panel and isinstance(vn.get("candidate_venues"), list) and vn["candidate_venues"]:
                if isinstance(vn["candidate_venues"][0], dict):
                    panel = vn["candidate_venues"][0].get("accepted_panel")
            if isinstance(panel, list):
                for item in panel[:3]:
                    if isinstance(item, dict):
                        raw_anchors.append(item)
        if not raw_anchors and isinstance(bundle.get("scorecards_bundle"), dict):
            tid = sc_state.get("target_id")
            for prof in (bundle["scorecards_bundle"].get("profiles") or []):
                if isinstance(prof, dict) and prof.get("id") != tid:
                    raw_anchors.append({**prof, "topic_relation": prof.get("topic_relation", "same_topic")})
                    if len(raw_anchors) >= 3:
                        break

    normalized_anchors = [_normalize_anchor_row(a, target_overall) for a in raw_anchors[:3]]
    target_meta = bundle.get("target_comparison_profile") if isinstance(bundle.get("target_comparison_profile"), dict) else {}
    target_cols = {col: (target_meta[col] if target_meta.get(col) is not None else STATUS_UNVERIFIED) for col in _ANCHOR_COLUMNS}

    same_count = sum(1 for a in normalized_anchors if a["topic_relation"] == "same_topic")
    cross_count = sum(1 for a in normalized_anchors if a["topic_relation"] in ("adjacent_topic", "different_topic", "cross_topic"))

    return {
        "anchor_count": len(normalized_anchors),
        "same_topic_count": same_count,
        "cross_topic_count": cross_count,
        "target_profile": {
            "id": sc_state.get("target_id") or "target",
            "overall_score": float(str(_quant2(target_overall))) if target_overall is not None else None,
            **target_cols,
        },
        "anchors": normalized_anchors,
        "status": "evaluated" if len(normalized_anchors) >= 2 else "insufficient_anchors",
    }


def _compute_merit_vs_packaging(
    sc_state: dict[str, Any],
    upstream: dict[str, Any],
    defects: list[dict[str, Any]],
    tier_fit: dict[str, Any] | None,
) -> dict[str, Any]:
    ratings = sc_state.get("ratings")
    weights = sc_state.get("weights") or dict(_DEFAULT_WEIGHTS)

    # Determine packaging caps from artifact_readiness & manuscript_ledger
    trans_cap = None
    evid_cap = None
    ar = upstream.get("artifact_readiness")
    if isinstance(ar, dict) and type(ar.get("recommended_transparency_cap")) is int:
        trans_cap = ar["recommended_transparency_cap"]
    ledger = upstream.get("ledger")
    if isinstance(ledger, dict):
        arg = _require_dict_or_none(ledger.get("argument_audit"), "ledger.argument_audit") or {}
        if type(arg.get("recommended_transparency_cap")) is int:
            cap_val = arg["recommended_transparency_cap"]
            trans_cap = cap_val if trans_cap is None else min(trans_cap, cap_val)
        if type(arg.get("recommended_evidence_cap")) is int:
            evid_cap = arg["recommended_evidence_cap"]

    merit_dec: Decimal | None = None
    eff_pkg_dec: Decimal | None = None
    merit_score = None
    raw_packaging = None
    adj_packaging = None
    applied_adjustments: list[str] = []

    if isinstance(ratings, dict) and all(ratings.get(d) is not None for d in _MERIT_DIMS):
        merit_w_sum = sum(weights[d] for d in _MERIT_DIMS)
        if merit_w_sum > 0:
            eff_ratings = dict(ratings)
            if evid_cap is not None and eff_ratings["evidence"] > evid_cap:
                eff_ratings["evidence"] = evid_cap
                applied_adjustments.append(f"evidence_capped_at_{evid_cap}_by_argument_audit")
            merit_dec = sum(Decimal(weights[d]) * Decimal(eff_ratings[d]) for d in _MERIT_DIMS) / Decimal(merit_w_sum)
            merit_score = float(str(_quant2(merit_dec)))

    # Bounded packaging penalties from preflight / artifact_readiness / venue_sources / venue_plan
    pkg_penalty = Decimal("0.00")
    for pf in upstream["preflight"]:
        if pf.get("verdict") == STATUS_FAIL:
            pkg_penalty += Decimal("1.00")
            applied_adjustments.append(f"preflight_fail:{pf.get('schema', 'preflight')}")
        elif pf.get("verdict") == STATUS_PASS_WITH_WARNINGS:
            pkg_penalty += Decimal("0.25")
    if isinstance(ar, dict):
        if ar.get("verdict") == STATUS_FAIL:
            pkg_penalty += Decimal("1.00")
            applied_adjustments.append("artifact_readiness_fail")
        elif ar.get("verdict") == STATUS_WARN:
            pkg_penalty += Decimal("0.50")
            applied_adjustments.append("artifact_readiness_warn")
    vs = upstream.get("venue_sources")
    if isinstance(vs, dict) and not vs.get("verification_passed", True):
        pkg_penalty += Decimal("0.75")
        applied_adjustments.append(f"venue_sources:{vs.get('source_text_status', 'unverified')}")
    vp = upstream.get("venue_plan")
    if isinstance(vp, dict) and (vp.get("warnings") or vp.get("within_budget") is False or vp.get("cfp_verified") is False or vp.get("source_issues")):
        pkg_penalty += Decimal("0.50")
        applied_adjustments.append("venue_plan_issues")

    if isinstance(ratings, dict) and all(ratings.get(d) is not None for d in _PACKAGING_DIMS):
        pkg_w_sum = sum(weights[d] for d in _PACKAGING_DIMS)
        if pkg_w_sum > 0:
            raw_pkg_dec = sum(Decimal(weights[d]) * Decimal(ratings[d]) for d in _PACKAGING_DIMS) / Decimal(pkg_w_sum)
            raw_packaging = float(str(_quant2(raw_pkg_dec)))
            eff_trans = ratings["transparency"]
            if trans_cap is not None and eff_trans > trans_cap:
                eff_trans = trans_cap
                applied_adjustments.append(f"transparency_capped_at_{trans_cap}")
            eff_pkg_dec = (Decimal(weights["transparency"]) * Decimal(eff_trans) + Decimal(weights["clarity"]) * Decimal(ratings["clarity"])) / Decimal(pkg_w_sum)
            eff_pkg_dec = max(Decimal("0.00"), eff_pkg_dec - min(pkg_penalty, Decimal("4.00")))
            adj_packaging = float(str(_quant2(eff_pkg_dec)))
    elif isinstance(sc_state.get("precomputed_merit_packaging"), dict):
        pre_mp = sc_state["precomputed_merit_packaging"]
        if merit_dec is None and pre_mp.get("scientific_merit_score") is not None:
            merit_dec = _parse_number_strict(
                pre_mp["scientific_merit_score"],
                "merit_vs_packaging.scientific_merit_score",
                min_val=0,
                max_val=10,
            )
            merit_score = float(str(_quant2(merit_dec)))
        if pre_mp.get("publishability_packaging_score") is not None:
            raw_pkg_dec = _parse_number_strict(
                pre_mp["publishability_packaging_score"],
                "merit_vs_packaging.publishability_packaging_score",
                min_val=0,
                max_val=10,
            )
            raw_packaging = float(str(_quant2(raw_pkg_dec)))
            eff_pkg_dec = max(Decimal("0.00"), raw_pkg_dec - min(pkg_penalty, Decimal("4.00")))
            adj_packaging = float(str(_quant2(eff_pkg_dec)))

    sr_meta = _require_dict_or_none((sc_state.get("score_result") or {}).get("submission_readiness"), "submission_readiness") or {}
    sci_fatal = bool(
        sr_meta.get("fatal_gate_triggered")
        and any(d in ("importance", "novelty", "soundness", "evidence") for d in (sr_meta.get("fatal_dimensions") or []))
    ) or any(d["severity"] == "fatal" and d["source_tool"] in ("check_experiment_rigor", "check_engineering_diagnostics", "subfield_preset_audit") for d in defects)

    pkg_fatal = bool(
        (tier_fit or {}).get("rejected_below_venue_tier")
        or any(d["severity"] == "fatal" and d["source_tool"] in ("check_submission_preflight", "check_artifact_readiness", "check_venue_sources", "check_venue_plan") for d in defects)
    )

    sci_low = sci_fatal or (merit_score is not None and merit_score < 6.80)
    pkg_low = pkg_fatal or (adj_packaging is not None and adj_packaging < 6.50)

    if sci_low and pkg_low:
        diagnosis = "both_bottlenecked"
    elif sci_low:
        diagnosis = "science_bottleneck"
    elif pkg_low:
        diagnosis = "packaging_and_venue_bottleneck"
    else:
        diagnosis = "aligned"

    return {
        "scientific_merit_score": merit_score,
        "raw_packaging_score": raw_packaging,
        "publishability_packaging_score": adj_packaging,
        "merit_minus_packaging": float(str(_quant2(merit_dec - eff_pkg_dec))) if (merit_dec is not None and eff_pkg_dec is not None) else None,
        "recommended_transparency_cap": trans_cap,
        "recommended_evidence_cap": evid_cap,
        "applied_caps_and_penalties": applied_adjustments,
        "bottleneck_diagnosis": diagnosis,
    }


def _build_section_diagnostics(
    sections_input: dict[str, Any] | None,
    defects: list[dict[str, Any]],
    sc_state: dict[str, Any],
    upstream: dict[str, Any],
) -> dict[str, Any]:
    if sections_input is not None and not isinstance(sections_input, dict):
        raise ValueError("sections must be a JSON object")
    sec_in = sections_input if isinstance(sections_input, dict) else {}
    ratings = sc_state.get("ratings") or {}

    diag: dict[str, dict[str, Any]] = {}
    for sec in SECTIONS:
        entry = sec_in.get(sec)
        sec_score = None
        sec_status = "not_assessed"
        linked: list[str] = []
        fixes: list[str] = []

        if isinstance(entry, dict):
            if entry.get("score") is not None:
                sec_score = float(str(_quant2(_parse_number_strict(entry["score"], f"sections.{sec}.score", min_val=0, max_val=10))))
            if isinstance(entry.get("status"), str) and entry["status"].strip().lower() in ("pass", "weak", "fatal", "not_assessed"):
                sec_status = entry["status"].strip().lower()
            elif sec_score is not None:
                sec_status = "fatal" if sec_score <= 4.0 else ("weak" if sec_score < 6.5 else "pass")
            for iss in (entry.get("issues") or []):
                if isinstance(iss, str) and iss.strip():
                    linked.append(iss.strip())
        elif entry is not None:
            sec_score = float(str(_quant2(_parse_number_strict(entry, f"sections.{sec}", min_val=0, max_val=10))))
            sec_status = "fatal" if sec_score <= 4.0 else ("weak" if sec_score < 6.5 else "pass")

        # Attach deterministic defects linked to this section
        sec_defects = [d for d in defects if d.get("section") == sec]
        for d in sec_defects:
            linked.append(f"{d['id']}({d['severity']}): {d['summary']}")
            fixes.append(d["remediation"])

        # Infer baseline section status from ratings/upstream if not explicitly overridden
        if sec == "method" and ratings.get("soundness") is not None and sec_score is None:
            sec_score = float(ratings["soundness"])
        elif sec == "experiments" and ratings.get("evidence") is not None and sec_score is None:
            sec_score = float(ratings["evidence"])
        elif sec == "related_work" and ratings.get("novelty") is not None and sec_score is None:
            sec_score = float(ratings["novelty"])
        elif sec in ("abstract", "introduction") and ratings.get("clarity") is not None and sec_score is None:
            sec_score = float(ratings["clarity"])
        elif sec == "limitations" and isinstance(upstream.get("artifact_readiness"), dict) and sec_status == "not_assessed":
            ar_v = upstream["artifact_readiness"].get("verdict")
            sec_status = "fatal" if ar_v == STATUS_FAIL else ("weak" if ar_v == STATUS_WARN else "pass")

        if any(d["severity"] == "fatal" for d in sec_defects):
            sec_status = "fatal"
        elif any(d["severity"] == "major" for d in sec_defects) and sec_status != "fatal":
            sec_status = "weak"
        elif sec_status == "not_assessed" and sec_score is not None:
            sec_status = "fatal" if sec_score <= 4.0 else ("weak" if sec_score < 6.5 else "pass")

        diag[sec] = {
            "status": sec_status,
            "score": sec_score,
            "linked_issues": linked,
            "recommended_fix": fixes[0] if fixes else ("No blocking action flagged." if sec_status == "pass" else "Audit section against rubric."),
        }

    sev_rank = {"fatal": 0, "weak": 1, "not_assessed": 2, "pass": 3}
    priority_order = sorted(
        SECTIONS,
        key=lambda s: (
            sev_rank.get(diag[s]["status"], 2),
            diag[s]["score"] if diag[s]["score"] is not None else 99.0,
            SECTIONS.index(s),
        ),
    )
    return {**diag, "priority_edit_order": priority_order}


def _compute_worst_case_sensitivity(
    bundle: dict[str, Any],
    sc_state: dict[str, Any],
    defects: list[dict[str, Any]],
    effective_tier: str | None,
) -> dict[str, Any]:
    ratings = sc_state.get("ratings")
    weights = sc_state.get("weights") or dict(_DEFAULT_WEIGHTS)
    sr = (sc_state.get("score_result") or {}).get("submission_readiness") or {}
    is_idea = sc_state.get("is_idea", False)

    persona_scores: dict[str, float | None] = {p: None for p in PERSONAS}
    worst_floor = None
    worst_persona = None

    # Optional explicit multi-reviewer ratings list
    rev_list = bundle.get("reviewer_ratings")
    if rev_list is not None:
        if not isinstance(rev_list, list):
            raise ValueError("reviewer_ratings must be a list of rating objects")
        scored_revs = []
        for idx, rr in enumerate(rev_list, start=1):
            if not isinstance(rr, dict):
                raise ValueError(f"reviewer_ratings[{idx - 1}] must be a JSON object")
            r_clean, w_clean = _validate_ratings_and_weights(rr, weights)
            res = score_math.score({"weights": w_clean, "ratings": r_clean})
            if res.get("weighted_unrounded") is not None:
                scored_revs.append((f"reviewer_{idx}", Decimal(res["weighted_unrounded"])))
        if scored_revs:
            min_name, min_val = min(scored_revs, key=lambda x: x[1])
            worst_floor = float(str(_quant2(min_val)))
            worst_persona = min_name

    if isinstance(ratings, dict) and all(ratings.get(d) is not None for d in score_math.DIMENSIONS):
        for p in PERSONAS:
            pw = _PERSONA_WEIGHTS[p]
            raw_p = sum(Decimal(pw[d]) * Decimal(ratings[d]) for d in score_math.DIMENSIONS) / Decimal(100)
            p_fatals = sum(1 for d in defects if d["persona"] == p and d["severity"] == "fatal")
            p_majors = sum(1 for d in defects if d["persona"] == p and d["severity"] == "major")
            penalty = min(Decimal("1.50"), Decimal("0.35") * p_fatals + Decimal("0.15") * p_majors)
            eff = max(Decimal("0.00"), raw_p - penalty)
            persona_scores[p] = float(str(_quant2(eff)))
        if worst_floor is None:
            worst_persona = min(PERSONAS, key=lambda p: persona_scores[p] if persona_scores[p] is not None else 99.0)
            worst_floor = persona_scores[worst_persona]

    deal_breakers: list[str] = []
    deal_breaker_details: list[dict[str, Any]] = []
    non_rescuable: list[str] = []

    if isinstance(ratings, dict) and all(ratings.get(d) is not None for d in score_math.DIMENSIONS):
        base_fatal = bool(sr.get("fatal_gate_triggered"))
        base_tier_rej = False
        if effective_tier:
            base_fit = score_math.evaluate_venue_tier_fit(
                effective_tier,
                weighted_unrounded=(sc_state.get("score_result") or {}).get("weighted_unrounded"),
                ratings=ratings,
                is_idea=is_idea,
            )
            base_tier_rej = bool(base_fit["rejected_below_venue_tier"])

        for dim in score_math.DIMENSIONS:
            if ratings[dim] > 0:
                down = dict(ratings)
                down[dim] = ratings[dim] - 1
                down_sc = score_math.score({"weights": weights, "ratings": down, **({"status": "idea"} if is_idea else {})})
                down_fatal = bool(down_sc["submission_readiness"]["fatal_gate_triggered"])
                down_tier_rej = False
                if effective_tier:
                    down_fit = score_math.evaluate_venue_tier_fit(
                        effective_tier,
                        weighted_unrounded=down_sc.get("weighted_unrounded"),
                        ratings=down,
                        is_idea=is_idea,
                    )
                    down_tier_rej = bool(down_fit["rejected_below_venue_tier"])
                if (not base_fatal and down_fatal) or (not base_tier_rej and down_tier_rej):
                    deal_breakers.append(dim)
                    deal_breaker_details.append({
                        "dimension": dim,
                        "current_rating": ratings[dim],
                        "perturbed_rating": down[dim],
                        "trigger": "fatal_gate" if (not base_fatal and down_fatal) else "tier_rejection",
                    })

            if (base_fatal or base_tier_rej) and ratings[dim] < 10:
                up = dict(ratings)
                up[dim] = ratings[dim] + 1
                up_sc = score_math.score({"weights": weights, "ratings": up, **({"status": "idea"} if is_idea else {})})
                up_fatal = bool(up_sc["submission_readiness"]["fatal_gate_triggered"])
                up_tier_rej = False
                if effective_tier:
                    up_fit = score_math.evaluate_venue_tier_fit(
                        effective_tier,
                        weighted_unrounded=up_sc.get("weighted_unrounded"),
                        ratings=up,
                        is_idea=is_idea,
                    )
                    up_tier_rej = bool(up_fit["rejected_below_venue_tier"])
                if (base_fatal and up_fatal) or (base_tier_rej and up_tier_rej):
                    non_rescuable.append(dim)
    elif isinstance(sc_state.get("precomputed_deal_breaker"), dict):
        pre_db = sc_state["precomputed_deal_breaker"]
        wcf = _require_dict_or_none(pre_db.get("worst_case_reviewer_floor"), "deal_breaker_sensitivity.worst_case_reviewer_floor")
        if worst_floor is None and wcf is not None:
            w_val = wcf.get("worst_case_score") if wcf.get("worst_case_score") is not None else wcf.get("worst_reviewer_score")
            if w_val is not None:
                w_dec = _parse_number_strict(
                    w_val,
                    "deal_breaker_sensitivity.worst_case_reviewer_floor.worst_case_score",
                    min_val=0,
                    max_val=10,
                )
                worst_floor = float(str(_quant2(w_dec)))
                worst_persona = str(wcf.get("worst_reviewer_id") or wcf.get("basis") or "worst_case_floor")
        if isinstance(pre_db.get("deal_breaker_axes"), list):
            deal_breakers = list(pre_db["deal_breaker_axes"])
        if isinstance(pre_db.get("non_rescuing_axes"), list):
            non_rescuable = list(pre_db["non_rescuing_axes"])

    return {
        "persona_scores": persona_scores,
        "worst_case_reviewer_floor": worst_floor,
        "worst_case_persona": worst_persona,
        "deal_breaker_dimensions": deal_breakers,
        "deal_breaker_details": deal_breaker_details,
        "non_rescuable_dimensions": non_rescuable,
    }


def _scale_equivalents(weighted_str: str | None, scale: str) -> dict[str, Any]:
    if weighted_str is None:
        return {"requested_scale": scale, "native_10": None, "mapped_score": None, "note": "missing dimension(s)"}
    dec = _parse_number_strict(weighted_str, "weighted_unrounded", min_val=0, max_val=10)
    mapped: str
    if scale == "arr_1_5":
        val = _quant2(Decimal("1.0") + dec * Decimal("0.4"))
        mapped = f"{val} / 5 (ARR approx: >=3.5 strong, 3.0 borderline)"
    elif scale == "neurips_1_6":
        val = _quant2(Decimal("1.0") + dec * Decimal("0.5"))
        mapped = f"{val} / 6 (NeurIPS approx: 4 borderline accept)"
    elif scale == "iclr_1_10":
        val = _quant2(dec)
        mapped = f"{val} / 10 (ICLR approx: 6 weak accept, 8 strong accept)"
    else:
        val = _quant2(dec)
        mapped = f"{val} / 10 (native rubric)"
    return {
        "requested_scale": scale,
        "native_10": float(str(_quant2(dec))),
        "mapped_value": float(str(val)),
        "calibration_anchor": mapped,
    }


def run_mock_review(
    bundle: dict[str, Any],
    *,
    scorecard_obj: Any = None,
    venue_novelty_obj: Any = None,
    rigor_objs: list[Any] | None = None,
    ledger_obj: Any = None,
    preflight_objs: list[Any] | None = None,
    artifact_obj: Any = None,
    venue_sources_obj: Any = None,
    venue_plan_obj: Any = None,
    eng_diag_obj: Any = None,
    sections_obj: Any = None,
    anchors_obj: Any = None,
    venue_tier: str | None = None,
    scale: str = "native",
    subfield_preset: str | None = None,
) -> dict[str, Any]:
    if not isinstance(bundle, dict):
        raise ValueError("Input dossier must be a JSON object")
    if scale not in SCALES:
        raise ValueError(f"Invalid scale: {scale}")

    preset_key = subfield_preset or bundle.get("subfield_preset")
    if preset_key is not None and preset_key not in SUBFIELD_PRESETS:
        raise ValueError(f"Unknown subfield preset: {preset_key}")

    sc_state = _extract_scorecard_state(bundle, scorecard_obj)
    upstream = _detect_and_ingest_upstream(
        bundle,
        venue_novelty_obj=venue_novelty_obj,
        rigor_objs=rigor_objs,
        ledger_obj=ledger_obj,
        preflight_objs=preflight_objs,
        artifact_obj=artifact_obj,
        venue_sources_obj=venue_sources_obj,
        venue_plan_obj=venue_plan_obj,
        eng_diag_obj=eng_diag_obj,
    )

    # Fallback score_result & precomputed F30 metrics from compare_venue_novelty --portfolio
    vn_pre = upstream.get("venue_novelty")
    if isinstance(vn_pre, dict):
        tr = _require_dict_or_none(vn_pre.get("target_readiness"), "venue_novelty.target_readiness")
        if tr is not None:
            _validate_readiness_dict(tr, "venue_novelty.target_readiness")
        if sc_state.get("score_result") is None and tr is not None:
            if tr.get("weighted_unrounded") is not None or tr.get("band") is not None or tr.get("fatal_gate_triggered") is not None:
                w_unr = tr.get("weighted_unrounded")
                if w_unr is not None:
                    _parse_number_strict(w_unr, "venue_novelty.target_readiness.weighted_unrounded", min_val=0, max_val=10)
                f_gate = bool(tr.get("fatal_gate_triggered"))
                f_reasons = list(tr.get("fatal_reasons") or [])
                if f_gate and not f_reasons:
                    f_reasons = ["fatal_gate_triggered"]
                b_val = tr.get("band")
                sr_synth = {
                    "band": b_val,
                    "fatal_gate_triggered": f_gate,
                    "fatal_reasons": f_reasons,
                    "fatal_dimensions": [],
                    "recommended_matched_tier": tr.get("recommended_matched_tier"),
                    "ready_for_top_tier_main_track": False if (f_gate or b_val in ("not_ready_major_rework", "workshop_or_preliminary_only", "borderline_top_tier_competitive_findings_tier_a", "not_comparable_missing_dimension")) else True,
                    "ready_for_findings_or_tier_a": False if (f_gate or b_val in ("not_ready_major_rework", "workshop_or_preliminary_only", "not_comparable_missing_dimension")) else True,
                }
                sc_state["score_result"] = {
                    "overall": None,
                    "weighted_unrounded": str(w_unr) if w_unr is not None else None,
                    "status": "not_comparable" if (w_unr is None or b_val == "not_comparable_missing_dimension") else "calculated",
                    "submission_readiness": sr_synth,
                }
        vn_mp = _require_dict_or_none(vn_pre.get("merit_vs_packaging"), "venue_novelty.merit_vs_packaging")
        if sc_state.get("precomputed_merit_packaging") is None and vn_mp is not None:
            sc_state["precomputed_merit_packaging"] = vn_mp
        vn_db = _require_dict_or_none(vn_pre.get("deal_breaker_sensitivity"), "venue_novelty.deal_breaker_sensitivity")
        if sc_state.get("precomputed_deal_breaker") is None and vn_db is not None:
            sc_state["precomputed_deal_breaker"] = vn_db

    defects: list[dict[str, Any]] = []

    # 1. Scorecard / score_math F23-F25 checks
    score_res = sc_state.get("score_result") or {}
    sr = _validate_readiness_dict(
        _require_dict_or_none(score_res.get("submission_readiness"), "submission_readiness") or {},
        "submission_readiness",
    )
    ratings = sc_state.get("ratings")
    effective_ratings = ratings if isinstance(ratings, dict) else sc_state.get("inferred_ratings")
    if sr.get("fatal_gate_triggered"):
        fatal_reasons = sr.get("fatal_reasons") or [
            f"{d}<={score_math.FATAL_THRESHOLDS.get(d, 4)}" for d in (sr.get("fatal_dimensions") or [])
        ] or ["fatal_gate_triggered"]
        for reason in fatal_reasons:
            dim = reason.split("<=")[0] if "<=" in reason else "evidence"
            persona = "method_theory" if dim in ("soundness", "clarity") else ("novelty_positioning" if dim in ("novelty", "importance") else "experiments_baselines")
            code = "M5" if dim == "soundness" else ("G4" if dim == "clarity" else ("G1" if dim in ("novelty", "importance") else ("M2" if dim == "transparency" else "R1")))
            sec = "method" if dim in ("soundness", "clarity") else ("related_work" if dim == "novelty" else "experiments")
            _add_defect(
                defects,
                persona=persona,
                severity="fatal",
                code=code,
                source_tool="score_math",
                section=sec,
                summary=f"Fatal scorecard gate triggered: {reason}",
                remediation=f"Resolve fatal defect on `{dim}` before any archival submission.",
            )
    if score_res.get("status") == "not_comparable" or sr.get("band") == "not_comparable_missing_dimension":
        missing_dims = [d for d, v in ratings.items() if v is None] if isinstance(ratings, dict) else []
        miss_str = ", ".join(missing_dims) if missing_dims else "missing dimension(s)"
        persona = "experiments_baselines" if (not missing_dims or "evidence" in missing_dims or "transparency" in missing_dims) else "method_theory"
        sec = "experiments" if (not missing_dims or "evidence" in missing_dims or "transparency" in missing_dims) else ("method" if "soundness" in missing_dims else "related_work")
        _add_defect(
            defects,
            persona=persona,
            severity="major",
            code="M2",
            source_tool="score_math",
            section=sec,
            summary=f"Incomplete scorecard (`not_comparable_missing_dimension`): missing rating(s) for {miss_str}.",
            remediation="Score all 6 canonical dimensions from full-text evidence before submission.",
        )
    if isinstance(effective_ratings, dict):
        for dim, val in effective_ratings.items():
            if val is None or dim in (sr.get("fatal_dimensions") or []):
                continue
            if val == 5 and dim in ("soundness", "evidence"):
                _add_defect(
                    defects,
                    persona="method_theory" if dim == "soundness" else "experiments_baselines",
                    severity="major",
                    code="M5" if dim == "soundness" else "R5",
                    source_tool="score_math",
                    section="method" if dim == "soundness" else "experiments",
                    summary=f"Borderline dimension `{dim}={val}` fails Q1/Top-Tier floor (>=6).",
                    remediation=f"Strengthen `{dim}` to >=6 via tighter controls or ablations.",
                )
            elif val in (3, 4) and dim == "novelty":
                _add_defect(
                    defects,
                    persona="novelty_positioning",
                    severity="major",
                    code="G1",
                    source_tool="score_math",
                    section="related_work",
                    summary=f"Low novelty rating (`novelty={val}`) fails Q1/Top-Tier floor (>=5).",
                    remediation="Sharpen conceptual differentiation or retarget to Workshop/Findings.",
                )
            elif val == 4 and dim == "transparency":
                _add_defect(
                    defects,
                    persona="experiments_baselines",
                    severity="major",
                    code="M2",
                    source_tool="score_math",
                    section="experiments",
                    summary="Transparency=4 risks reproducibility objections.",
                    remediation="Publish split manifests, seeds, and artifact checklist.",
                )
            elif val in (5, 6) and dim == "clarity":
                _add_defect(
                    defects,
                    persona="method_theory",
                    severity="minor",
                    code="G4",
                    source_tool="score_math",
                    section="abstract",
                    summary=f"Clarity={val} leaves minor exposition/notation ambiguity.",
                    remediation="Tighten problem statement, notation, and abstract scope.",
                )
    elif (
        sr.get("recommended_matched_tier") in ("q2_q3_or_tier_b", "workshop_or_preliminary", "none_hold_for_rework")
        and not sr.get("fatal_gate_triggered")
    ):
        for dim in (sr.get("bottleneck_dimensions") or []):
            if dim in ("soundness", "evidence", "novelty", "transparency"):
                _add_defect(
                    defects,
                    persona="method_theory" if dim == "soundness" else ("novelty_positioning" if dim == "novelty" else "experiments_baselines"),
                    severity="major",
                    code="M5" if dim == "soundness" else ("G1" if dim == "novelty" else ("M2" if dim == "transparency" else "R5")),
                    source_tool="score_math",
                    section="method" if dim == "soundness" else ("related_work" if dim == "novelty" else "experiments"),
                    summary=f"Bottleneck dimension `{dim}` fails Q1/Top-Tier floor (recommended_matched_tier={sr.get('recommended_matched_tier')}).",
                    remediation=f"Strengthen `{dim}` to clear Q1/Top-Tier dimension floor.",
                )

    csc = sc_state.get("compare_scorecards")
    if isinstance(csc, dict):
        if csc.get("status") == "not_comparable":
            _add_defect(
                defects,
                persona="novelty_positioning",
                severity="major",
                code="G3",
                source_tool="compare_scorecards",
                section="related_work",
                summary="Scorecard panel is not_comparable (missing locators or <3 scored closest-work papers).",
                remediation="Score >=3 full-text closest-work papers with verified locators.",
            )
        rwc = _require_dict_or_none(csc.get("related_work_comparison"), "scorecard.related_work_comparison") or {}
        for warn in (rwc.get("novelty_inflation_warnings") or []):
            _add_defect(
                defects,
                persona="novelty_positioning",
                severity="major",
                code="R4",
                source_tool="compare_scorecards",
                section="related_work",
                summary=f"Novelty inflation warning: {warn}",
                remediation="Document concrete contribution_delta or baseline tradeoff.",
            )

    # 2. Venue novelty & tier fit (F23-F25)
    vn = upstream.get("venue_novelty")
    effective_tier = venue_tier
    if effective_tier is None and bundle.get("venue_tier"):
        effective_tier = _resolve_tier_arg(str(bundle["venue_tier"]))

    panel_med_nov = None
    target_nov = effective_ratings.get("novelty") if isinstance(effective_ratings, dict) else None
    target_vs_panel_delta = None
    vn_matched_rejected: list[dict[str, Any]] = []

    if isinstance(vn, dict):
        vn_venue = _require_dict_or_none(vn.get("venue"), "venue_novelty.venue")
        vqc = _require_dict_or_none(vn.get("venue_quality_context"), "venue_novelty.venue_quality_context") or {}
        if vn_venue is not None and effective_tier is None:
            effective_tier = score_math.resolve_venue_tier(
                venue_name=vn_venue.get("name"),
                track=vn_venue.get("track"),
                quality_tier=vqc.get("quality_tier"),
                tier_expectation=vn.get("tier_expectation"),
            )
        tr_vn = _require_dict_or_none(vn.get("target_readiness"), "venue_novelty.target_readiness") or {}
        if target_nov is None and type(tr_vn.get("target_novelty_score")) is int:
            target_nov = tr_vn["target_novelty_score"]
        vcb = _require_dict_or_none(vn.get("venue_contribution_bar"), "venue_novelty.venue_contribution_bar")
        if vcb is not None:
            panel_med_nov = vcb.get("panel_median_novelty")
            target_vs_panel_delta = vcb.get("target_vs_venue_overall_delta")
        nc = _require_dict_or_none(vn.get("novelty_comparison"), "venue_novelty.novelty_comparison")
        if nc is not None and panel_med_nov is None:
            panel_med_nov = nc.get("accepted_panel_median_score")
        vn_target = _require_dict_or_none(vn.get("target"), "venue_novelty.target")
        if vn_target is not None and target_nov is None and type(vn_target.get("score")) is int:
            target_nov = vn_target["score"]

        vsr = _validate_readiness_dict(
            _require_dict_or_none(vn.get("submission_readiness"), "venue_novelty.submission_readiness") or {},
            "venue_novelty.submission_readiness",
        )
        verdict = vsr.get("verdict")
        if verdict == STATUS_REJECTED_TIER:
            _add_defect(
                defects,
                persona="novelty_positioning",
                severity="fatal",
                code="G1",
                source_tool="compare_venue_novelty",
                section="related_work",
                summary="Rejected below target venue tier floor (contribution mismatch).",
                remediation=f"Retarget to `{vsr.get('recommended_matched_tier')}` or close `upgrade_gaps_to_target_tier`.",
            )
        elif verdict in ("not_ready_fatal_gate", "not_ready_invalid_evidence", "do_not_submit_constraint_failed") or vn.get("status") == "invalid":
            _add_defect(
                defects,
                persona="novelty_positioning",
                severity="fatal",
                code="G1",
                source_tool="compare_venue_novelty",
                section="limitations",
                summary=f"Venue readiness blocked ({verdict or vn.get('status')}).",
                remediation="Resolve hard venue constraints, locators, or fatal score gate.",
            )
        elif verdict in ("blocked_unverified_fit_or_constraints", "provisional_panel_withheld", "below_panel_median_strengthen_or_retarget"):
            _add_defect(
                defects,
                persona="novelty_positioning",
                severity="major",
                code="G3",
                source_tool="compare_venue_novelty",
                section="related_work",
                summary=f"Venue standing/verification incomplete ({verdict}).",
                remediation="Verify >=5 same-track accepted panel papers and official CFP constraints.",
            )

        eval_rows = vn.get("venue_evaluations") if isinstance(vn.get("venue_evaluations"), list) else (
            vn.get("venue_summaries") if isinstance(vn.get("venue_summaries"), list) else []
        )
        if effective_tier is not None:
            vn_matched_rejected = [
                ve for ve in eval_rows
                if isinstance(ve, dict)
                and ve.get("classification") == STATUS_REJECTED_TIER
                and ve.get("venue_tier") == effective_tier
            ]

        vpr = _require_dict_or_none(vn.get("venue_portfolio_recommendations"), "venue_novelty.venue_portfolio_recommendations")
        pv = vpr.get("portfolio_verdict") if isinstance(vpr, dict) else None
        vpr_rec_obj = (
            _require_dict_or_none(vpr.get("recommended_matched_tier"), "venue_novelty.venue_portfolio_recommendations.recommended_matched_tier")
            if isinstance(vpr, dict)
            else None
        )
        vpr_matched_tier = vpr_rec_obj.get("matched_tier") if isinstance(vpr_rec_obj, dict) else None
        if vpr_matched_tier is not None and (not isinstance(vpr_matched_tier, str) or not vpr_matched_tier.strip()):
            raise ValueError("venue_novelty.venue_portfolio_recommendations.recommended_matched_tier.matched_tier must be a non-empty string")
        matched_tier_rec = vpr_matched_tier or tr_vn.get("recommended_matched_tier")

        if vn_matched_rejected:
            v_ids = ", ".join(str(v.get("venue_id", "venue")) for v in vn_matched_rejected[:3])
            _add_defect(
                defects,
                persona="novelty_positioning",
                severity="fatal",
                code="G1",
                source_tool="compare_venue_novelty",
                section="related_work",
                summary=f"Rejected below target venue tier floor (`{effective_tier}`): {v_ids} classified rejected_below_venue_tier.",
                remediation=f"Retarget to `{matched_tier_rec or 'workshop_or_preliminary'}` or close upgrade gaps.",
            )
        elif isinstance(vpr, dict):
            if pv == STATUS_HOLD_REWORK:
                _add_defect(
                    defects,
                    persona="novelty_positioning",
                    severity="fatal",
                    code="G1",
                    source_tool="compare_venue_novelty",
                    section="related_work",
                    summary=f"Portfolio verdict: {pv}.",
                    remediation="Hold for core rework or search matched-tier venues.",
                )
            elif pv == "no_viable_venue_in_portfolio":
                rej_list = vpr.get("rejected_below_venue_tier") or []
                is_tier_rej_only = bool(rej_list) and not sr.get("fatal_gate_triggered")
                _add_defect(
                    defects,
                    persona="novelty_positioning",
                    severity="fatal",
                    code="G1",
                    source_tool="compare_venue_novelty",
                    section="related_work",
                    summary=(
                        f"Rejected below target venue tier floor: portfolio has no viable venue ({', '.join(str(x) for x in rej_list[:3])})."
                        if is_tier_rej_only
                        else f"Portfolio verdict: {pv}."
                    ),
                    remediation="Hold for core rework or search matched-tier venues.",
                )
            elif pv in ("retargeted_to_matched_tier", "no_verified_viable_venues"):
                rej_list = vpr.get("rejected_below_venue_tier") or []
                compact_tier_rej = (
                    pv == "retargeted_to_matched_tier"
                    and effective_tier is not None
                    and bool(rej_list)
                    and not eval_rows
                    and matched_tier_rec in score_math.VENUE_TIER_ORDER
                    and effective_tier in score_math.VENUE_TIER_ORDER
                    and score_math.VENUE_TIER_ORDER.index(effective_tier) < score_math.VENUE_TIER_ORDER.index(matched_tier_rec)
                )
                if compact_tier_rej:
                    _add_defect(
                        defects,
                        persona="novelty_positioning",
                        severity="fatal",
                        code="G1",
                        source_tool="compare_venue_novelty",
                        section="related_work",
                        summary=f"Rejected below target venue tier floor (`{effective_tier}`): portfolio retargeted to `{matched_tier_rec}`.",
                        remediation=f"Retarget to `{matched_tier_rec}` or close upgrade gaps.",
                    )
                else:
                    _add_defect(
                        defects,
                        persona="novelty_positioning",
                        severity="major",
                        code="G1",
                        source_tool="compare_venue_novelty",
                        section="related_work",
                        summary=f"Portfolio retargeted away from flagship ({pv}).",
                        remediation="Align submission with recommended_matched_tier or strengthen bottlenecks.",
                    )

    tier_fit = None
    if effective_tier is not None:
        tier_fit = score_math.evaluate_venue_tier_fit(
            effective_tier,
            weighted_unrounded=(sc_state.get("score_result") or {}).get("weighted_unrounded"),
            ratings=effective_ratings,
            is_idea=sc_state.get("is_idea", False),
            target_novelty=target_nov,
            panel_median_novelty=panel_med_nov,
            target_vs_venue_overall_delta=target_vs_panel_delta,
        )
        tier_fit = _reconcile_tier_fit_with_readiness(
            tier_fit,
            sr,
            effective_tier,
            ratings=effective_ratings,
        )
        if vn_matched_rejected and not tier_fit["rejected_below_venue_tier"]:
            tier_fit["rejected_below_venue_tier"] = True
            for ve in vn_matched_rejected:
                for r in (ve.get("rejection_reasons") or []):
                    if r not in tier_fit["rejection_reasons"]:
                        tier_fit["rejection_reasons"].append(r)
            if not tier_fit["rejection_reasons"]:
                tier_fit["rejection_reasons"].append("portfolio_venue_rejected_below_venue_tier")
            if not tier_fit.get("recommended_matched_tier") and isinstance(vn, dict):
                vpr_obj = _require_dict_or_none(vn.get("venue_portfolio_recommendations"), "venue_novelty.venue_portfolio_recommendations") or {}
                vpr_m = _require_dict_or_none(vpr_obj.get("recommended_matched_tier"), "venue_novelty.venue_portfolio_recommendations.recommended_matched_tier") or {}
                tr_obj = _require_dict_or_none(vn.get("target_readiness"), "venue_novelty.target_readiness") or {}
                tier_fit["recommended_matched_tier"] = vpr_m.get("matched_tier") or tr_obj.get("recommended_matched_tier")
        if tier_fit["rejected_below_venue_tier"] and not any(d["source_tool"] == "compare_venue_novelty" and d["severity"] == "fatal" for d in defects):
            _add_defect(
                defects,
                persona="novelty_positioning",
                severity="fatal",
                code="G1",
                source_tool="score_math",
                section="related_work",
                summary=f"Below `{effective_tier}` venue tier floor: {', '.join(tier_fit['rejection_reasons'])}",
                remediation=f"Retarget to `{tier_fit['recommended_matched_tier']}` or close upgrade gaps.",
            )

    # 3. Experiment rigor (repro, rliable, contamination; full & --compact)
    for r in upstream["rigor"]:
        sch = r.get("schema", "")
        ver = r.get("verdict", "")
        if sch == "experiment_rigor_contamination_v1" and ver == "CONTAMINATION_DETECTED":
            _add_defect(
                defects,
                persona="experiments_baselines",
                severity="fatal",
                code="M3",
                source_tool="check_experiment_rigor",
                section="experiments",
                summary=f"Benchmark contamination detected ({r.get('contaminated_eval_count', 'unknown')} contaminated items).",
                remediation="Purge overlapping eval examples or replace with uncontaminated OOD split.",
            )
        elif sch == "experiment_rigor_repro_v1":
            if ver == STATUS_FAIL:
                miss = ", ".join(r.get("missing") or ["reproducibility essentials"])
                _add_defect(
                    defects,
                    persona="experiments_baselines",
                    severity="major",
                    code="M2",
                    source_tool="check_experiment_rigor",
                    section="experiments",
                    summary=f"Reproducibility checklist FAIL (missing: {miss}).",
                    remediation="Add fixed seeds, entrypoint command, dataset manifest, and environment pin.",
                )
            elif ver == STATUS_PASS_WITH_WARNINGS:
                _add_defect(
                    defects,
                    persona="experiments_baselines",
                    severity="minor",
                    code="M2",
                    source_tool="check_experiment_rigor",
                    section="experiments",
                    summary=f"Reproducibility warnings: {'; '.join(r.get('warnings') or ['check pinned deps'])}",
                    remediation="Pin dependency versions and results collection commands.",
                )
        elif sch == "experiment_rigor_rliable_v1":
            for w in (r.get("warnings") or []):
                sev = "major" if isinstance(w, str) and (w.startswith("underpowered_seeds") or w.startswith("no_clear_improvement")) else "minor"
                _add_defect(
                    defects,
                    persona="experiments_baselines",
                    severity=sev,
                    code="R5",
                    source_tool="check_experiment_rigor",
                    section="experiments",
                    summary=f"Multi-seed statistical rigor issue: {w}",
                    remediation="Run >=3-5 seeds and report IQM + 95% stratified bootstrap CI.",
                )

    # 4. Engineering diagnostics
    ed = upstream.get("engineering_diagnostics")
    if isinstance(ed, dict) and ed.get("verdict") == "ENGINEERING_BUG_DETECTED":
        raw_findings = ed.get("findings") or [{"category": "engineering_bug", "detail": "Engineering bug detected"}]
        if not isinstance(raw_findings, list):
            raise ValueError("engineering_diagnostics.findings must be a list")
        for f in raw_findings[:5]:
            if not isinstance(f, dict):
                raise ValueError("engineering_diagnostics.findings entries must be JSON objects")
            cat = str(f.get("category", "engineering_bug"))
            sev = "fatal" if str(f.get("severity", "error")).lower() in ("error", "fatal", "critical") else "major"
            _add_defect(
                defects,
                persona="experiments_baselines",
                severity=sev,
                code="R1",
                source_tool="check_engineering_diagnostics",
                section="experiments",
                summary=f"Engineering bug ({cat}): {f.get('detail', '')}",
                remediation=str(f.get("remediation") or "Fix leakage/split/metric parity bug before claiming novelty."),
            )

    # 5. Manuscript ledger (full & --compact)
    ledger = upstream.get("ledger")
    if isinstance(ledger, dict):
        ledger_defect_added = False
        issues = ledger.get("issues") or []
        arg = _require_dict_or_none(ledger.get("argument_audit"), "ledger.argument_audit") or {}
        g_cnt = ledger.get("grandiose_finding_count", 0)
        if any(isinstance(i, str) and (i.startswith("inflated_method_name") or i.startswith("overcomplicated_method")) for i in issues) or (isinstance(g_cnt, int) and g_cnt > 0) or bool(ledger.get("grandiose_findings")):
            _add_defect(
                defects,
                persona="method_theory",
                severity="fatal",
                code="G1",
                source_tool="check_manuscript_ledger",
                section="method",
                summary="Grandiose method rebranding or overcomplicated method without parsimony ablation.",
                remediation="Use plain lineage attribution and add simplest-alternative ablation.",
            )
            ledger_defect_added = True
        csa = _require_dict_or_none(arg.get("claim_scope_alignment"), "ledger.argument_audit.claim_scope_alignment") or {}
        if csa.get("status") == STATUS_FAIL:
            _add_defect(
                defects,
                persona="method_theory",
                severity="fatal",
                code="R2",
                source_tool="check_manuscript_ledger",
                section="abstract",
                summary=f"Claim-Scope alignment audit FAIL ({csa.get('finding_count', 1)} findings).",
                remediation="Narrow abstract/intro claims to match verified experimental scope.",
            )
            ledger_defect_added = True
        cem = _require_dict_or_none(arg.get("contribution_evidence_map"), "ledger.argument_audit.contribution_evidence_map") or {}
        if cem.get("status") == STATUS_FAIL:
            _add_defect(
                defects,
                persona="experiments_baselines",
                severity="fatal",
                code="R4",
                source_tool="check_manuscript_ledger",
                section="experiments",
                summary=f"Contribution-to-Evidence map FAIL ({cem.get('orphan_count', 1)} orphan contributions).",
                remediation="Bind every stated contribution 1-to-1 to verified experimental evidence.",
            )
            ledger_defect_added = True
        rwd = _require_dict_or_none(arg.get("related_work_differentiation"), "ledger.argument_audit.related_work_differentiation") or {}
        if rwd.get("status") == STATUS_FAIL:
            _add_defect(
                defects,
                persona="novelty_positioning",
                severity="fatal",
                code="G3",
                source_tool="check_manuscript_ledger",
                section="related_work",
                summary="Related-work differentiation audit FAIL (missing or undifferentiated competitors).",
                remediation="Explicitly differentiate mechanism and empirical delta against all scored competitors.",
            )
            ledger_defect_added = True
        other_issues = [
            i for i in issues
            if isinstance(i, str)
            and not i.startswith(("inflated_method_name", "overcomplicated_method", "claim_scope_", "orphan_contribution", "related_work_"))
        ]
        total_iss = ledger.get("total_issues")
        has_structural_issues = (
            ledger.get("status") == "structural_issues"
            or (isinstance(total_iss, int) and not isinstance(total_iss, bool) and total_iss > 0)
        )
        if other_issues or (has_structural_issues and not ledger_defect_added):
            _add_defect(
                defects,
                persona="experiments_baselines",
                severity="major",
                code="M2",
                source_tool="check_manuscript_ledger",
                section="experiments",
                summary=f"Manuscript ledger structural issues: {', '.join(other_issues[:3]) or 'unverified locators/numbers'}",
                remediation="Verify all numeric facts and source locators against local evidence files.",
            )

    # 6. Preflight (anonymize, arxiv-clean, bibtex)
    for pf in upstream["preflight"]:
        sch = pf.get("schema", "")
        ver = pf.get("verdict", "")
        if sch == "submission_anonymization_v1":
            if ver == STATUS_FAIL:
                _add_defect(
                    defects,
                    persona="experiments_baselines",
                    severity="fatal",
                    code="M2",
                    source_tool="check_submission_preflight",
                    section="limitations",
                    summary="Anonymization preflight FAIL (author/institution/URL/PDF metadata leak).",
                    remediation="Strip identity leaks and regenerate blind PDF/supplementary archive.",
                )
            elif ver == STATUS_PASS_WITH_WARNINGS:
                _add_defect(
                    defects,
                    persona="experiments_baselines",
                    severity="minor",
                    code="M2",
                    source_tool="check_submission_preflight",
                    section="limitations",
                    summary="Anonymization preflight warnings detected.",
                    remediation="Inspect anonymization warnings before upload.",
                )
        elif sch == "submission_arxiv_clean_v1" and ver in (STATUS_FAIL, STATUS_PASS_WITH_WARNINGS):
            _add_defect(
                defects,
                persona="experiments_baselines",
                severity="major" if ver == STATUS_FAIL else "minor",
                code="M2",
                source_tool="check_submission_preflight",
                section="limitations",
                summary=f"LaTeX/arXiv package hygiene {ver}.",
                remediation="Remove commented-out drafts, unused artifacts, or leaking macros.",
            )
        elif sch == "submission_bibtex_v1" and ver in (STATUS_FAIL, STATUS_PASS_WITH_WARNINGS):
            _add_defect(
                defects,
                persona="novelty_positioning",
                severity="major" if ver == STATUS_FAIL else "minor",
                code="G3",
                source_tool="check_submission_preflight",
                section="related_work",
                summary=f"BibTeX verification {ver}.",
                remediation="Fix missing DOIs, venue fields, or duplicate/undefined citation keys.",
            )

    # 7. Artifact readiness
    ar = upstream.get("artifact_readiness")
    if isinstance(ar, dict):
        ver = ar.get("verdict")
        if ver == STATUS_FAIL:
            reasons = ", ".join(ar.get("blocking_reasons") or ["secrets/PII/license/anonymization"])
            _add_defect(
                defects,
                persona="experiments_baselines",
                severity="fatal",
                code="T2",
                source_tool="check_artifact_readiness",
                section="limitations",
                summary=f"Artifact readiness FAIL: {reasons}",
                remediation="Remove secrets/PII/local paths and add explicit open license & repro manifest.",
            )
        elif ver == STATUS_WARN:
            _add_defect(
                defects,
                persona="experiments_baselines",
                severity="major",
                code="M2",
                source_tool="check_artifact_readiness",
                section="limitations",
                summary=f"Artifact readiness WARN: {', '.join(ar.get('warnings') or ['check release hygiene'])}",
                remediation="Resolve artifact release warnings before final submission.",
            )

    # 8. Venue sources & venue plan
    vs = upstream.get("venue_sources")
    if isinstance(vs, dict):
        if vs.get("blocking_source_issues") or vs.get("source_text_status") == "verification_blocked":
            _add_defect(
                defects,
                persona="novelty_positioning",
                severity="fatal",
                code="G1",
                source_tool="check_venue_sources",
                section="limitations",
                summary=f"Venue CFP source verification blocked ({vs.get('source_text_status')}).",
                remediation="Capture fresh non-redirected official CFP & fee snapshots.",
            )
        elif not vs.get("verification_passed", True):
            _add_defect(
                defects,
                persona="novelty_positioning",
                severity="major",
                code="G1",
                source_tool="check_venue_sources",
                section="limitations",
                summary="Venue CFP quote coverage incomplete.",
                remediation="Verify exact official CFP deadline/fee quotes.",
            )

    vp = upstream.get("venue_plan")
    if isinstance(vp, dict):
        if vp.get("within_budget") is False:
            _add_defect(
                defects,
                persona="novelty_positioning",
                severity="fatal",
                code="G1",
                source_tool="check_venue_plan",
                section="limitations",
                summary="Venue plan budget check failed (within_budget=false).",
                remediation="Verify mandatory venue fees fit available budget before submission.",
            )
        if vp.get("cfp_verified") is False:
            _add_defect(
                defects,
                persona="novelty_positioning",
                severity="fatal",
                code="G1",
                source_tool="check_venue_plan",
                section="limitations",
                summary="Venue plan CFP verification failed (cfp_verified=false).",
                remediation="Capture fresh official CFP & fee snapshots via check_venue_plan.py --sources.",
            )
        src_issues = vp.get("source_issues") or []
        src_total = vp.get("source_issues_total")
        if src_issues or (isinstance(src_total, int) and not isinstance(src_total, bool) and src_total > 0):
            issue_labels = [str(x.get("issue", x)) if isinstance(x, dict) else str(x) for x in src_issues[:3]]
            _add_defect(
                defects,
                persona="novelty_positioning",
                severity="fatal",
                code="G1",
                source_tool="check_venue_plan",
                section="limitations",
                summary=f"Venue plan source issues detected: {', '.join(issue_labels) or 'cfp/fee source blocked'}",
                remediation="Resolve CFP/fee redirect, dynamic page, or bot-block source issues.",
            )
        if vp.get("warnings"):
            warns = [str(w) for w in vp["warnings"]]
            blocking = any(
                "already_passed" in w
                or "redirect_year_mismatch" in w
                or "unverified_dynamic_page" in w
                or w.startswith("cfp_source_")
                or w.startswith("fee_source_")
                for w in warns
            )
            _add_defect(
                defects,
                persona="novelty_positioning",
                severity="fatal" if blocking else "major",
                code="G1",
                source_tool="check_venue_plan",
                section="limitations",
                summary=f"Venue plan warnings: {', '.join(warns[:3])}",
                remediation="Verify milestone deadlines and fee budget against official CFP.",
            )

    # 9. F31#2 Subfield depth preset audit
    subfield_checks_obj = _require_dict_or_none(bundle.get("subfield_checks"), "subfield_checks")
    preset_audit = _eval_subfield_preset(preset_key, subfield_checks_obj, upstream, defects)

    # 10. F30#5-8 Deep diagnostics
    eff_sections = sections_obj if sections_obj is not None else bundle.get("sections")
    anchor_contrast = _build_anchor_contrast(bundle, anchors_obj, upstream, sc_state)
    merit_packaging = _compute_merit_vs_packaging(sc_state, upstream, defects, tier_fit)
    section_diag = _build_section_diagnostics(eff_sections, defects, sc_state, upstream)
    sensitivity = _compute_worst_case_sensitivity(bundle, sc_state, defects, effective_tier)

    fatal_count = sum(1 for d in defects if d["severity"] == "fatal")
    major_count = sum(1 for d in defects if d["severity"] == "major")
    minor_count = sum(1 for d in defects if d["severity"] == "minor")
    persona_summary = {
        p: {
            "persona_score": sensitivity["persona_scores"].get(p),
            "fatal": sum(1 for d in defects if d["persona"] == p and d["severity"] == "fatal"),
            "major": sum(1 for d in defects if d["persona"] == p and d["severity"] == "major"),
            "minor": sum(1 for d in defects if d["persona"] == p and d["severity"] == "minor"),
        }
        for p in PERSONAS
    }

    _tier_rej_prefixes = ("Below `", "Rejected below target venue tier")
    non_tier_fatal_count = sum(
        1 for d in defects
        if d["severity"] == "fatal" and not (
            d["source_tool"] in ("score_math", "compare_venue_novelty")
            and str(d.get("summary", "")).startswith(_tier_rej_prefixes)
        )
    )
    has_tier_rej = bool(
        (tier_fit and tier_fit["rejected_below_venue_tier"])
        or any(
            d["source_tool"] == "compare_venue_novelty"
            and str(d.get("summary", "")).startswith("Rejected below target venue tier")
            for d in defects
        )
    )
    overall_verdict = (
        STATUS_FATAL_GATE if (non_tier_fatal_count > 0 or sr.get("fatal_gate_triggered"))
        else (STATUS_REJECTED_TIER if has_tier_rej
              else ("major_revisions_required" if (major_count > 0 or score_res.get("status") == "not_comparable" or sr.get("band") == "not_comparable_missing_dimension") else "ready_for_submission_check"))
    )

    weighted_str = (sc_state.get("score_result") or {}).get("weighted_unrounded")
    return {
        "schema": SCHEMA_MOCK_REVIEW,
        "mode": "mock-review",
        "target_id": sc_state.get("target_id") or "target",
        "overall_verdict": overall_verdict,
        "defect_counts": {"fatal": fatal_count, "major": major_count, "minor": minor_count, "total": len(defects)},
        "personas": persona_summary,
        "defect_ledger": defects,
        "submission_readiness": sr,
        "venue_tier_fit": tier_fit,
        "scale_calibration": _scale_equivalents(weighted_str, scale),
        "subfield_preset_audit": preset_audit,
        "side_by_side_anchor_contrast": anchor_contrast,
        "merit_vs_publishability": merit_packaging,
        "section_diagnostics": section_diag,
        "worst_case_sensitivity": sensitivity,
        "warning": (
            "Deterministic pre-submission triage only; does not compute acceptance probability percentages "
            "or replace human peer review."
        ),
    }


def _classify_comment(comment: dict[str, Any], h12_cutoff_months: int = 3) -> dict[str, Any]:
    cid = str(comment.get("id") or "C?")
    reviewer = str(comment.get("reviewer") or "Reviewer")
    text = _require_nonempty_str(comment.get("text") or comment.get("comment") or comment.get("summary"), f"comment[{cid}].text")
    explicit_effort: int | None = None
    if "effort_days" in comment and comment["effort_days"] is not None:
        explicit_effort = _parse_int_strict(comment["effort_days"], f"comment[{cid}].effort_days", min_val=1, max_val=14)
    low = text.lower()
    explicit_h = comment.get("heuristic_tag")
    explicit_code = comment.get("code_hint")
    cited_prec = bool(
        (isinstance(comment.get("cited_precedent"), str) and comment["cited_precedent"].strip())
        or (isinstance(comment.get("cited_precedent"), list) and len(comment["cited_precedent"]) > 0)
        or _PRECEDENT_CITE_RE.search(text)
    )

    # Determine H1-H17 match with context caveats
    matched_h: str | None = None
    if isinstance(explicit_h, str) and explicit_h.strip().upper() in H_RULES:
        cand_h = explicit_h.strip().upper()
        # Enforce context caveats even when hinted
        if cand_h == "H3" and cited_prec:
            matched_h = None
        elif cand_h == "H5" and bool(comment.get("author_claimed_sota")):
            matched_h = None
        elif cand_h == "H10" and bool(comment.get("claimed_cross_lingual")):
            matched_h = None
        elif cand_h == "H12":
            months = comment.get("reference_months_before_deadline")
            is_preprint = bool(comment.get("reference_is_preprint_only"))
            if not is_preprint and isinstance(months, (int, float)) and not isinstance(months, bool) and months >= h12_cutoff_months:
                matched_h = None  # Substantive G3!
            else:
                matched_h = "H12"
        elif cand_h == "H13" and bool(comment.get("core_claim_fails_without_it")):
            matched_h = None
        elif cand_h == "H14" and bool(comment.get("claim_targets_proprietary_api")):
            matched_h = None
        else:
            matched_h = cand_h

    if matched_h is None and not (isinstance(explicit_code, str) and explicit_code.strip().upper() in ARR_DEFECT_CATALOG):
        if "not surprising" in low or "unsurprising" in low or "obvious outcome" in low:
            matched_h = "H1"
        elif "contradicts" in low and ("expectation" in low or "intuition" in low):
            matched_h = "H2"
        elif ("not novel" in low or "lacks novelty" in low) and not cited_prec:
            matched_h = "H3"
        elif "no precedent" in low:
            matched_h = "H4"
        elif ("surpass" in low or "beat" in low or "outperform" in low) and "sota" in low and not bool(comment.get("author_claimed_sota")):
            matched_h = "H5"
        elif "negative result" in low or "null result" in low:
            matched_h = "H6"
        elif "too simple" in low or "only a simple" in low or "overly simple" in low:
            matched_h = "H7"
        elif "preferred method" in low or "should instead use" in low:
            matched_h = "H8"
        elif "too niche" in low or "too narrow" in low:
            matched_h = "H9"
        elif ("only on english" in low or "monolingual" in low or "only one language" in low) and not bool(comment.get("claimed_cross_lingual")):
            matched_h = "H10"
        elif any(tok in low for tok in ("typo", "grammar", "writing polish", "language error")):
            matched_h = "H11"
        elif any(tok in low for tok in ("missing reference", "recent preprint", "concurrent arxiv", "concurrent work")):
            months = comment.get("reference_months_before_deadline")
            is_preprint = bool(comment.get("reference_is_preprint_only"))
            if is_preprint or "preprint" in low or "arxiv" in low or (isinstance(months, (int, float)) and not isinstance(months, bool) and months < h12_cutoff_months):
                matched_h = "H12"
        elif any(tok in low for tok in ("could also", "extra experiment", "would be nice to test")) and not bool(comment.get("core_claim_fails_without_it")):
            matched_h = "H13"
        elif any(tok in low for tok in ("closed model", "gpt-4", "claude", "proprietary api")) and not bool(comment.get("claim_targets_proprietary_api")):
            matched_h = "H14"
        elif "should have done" in low or "different paper" in low:
            matched_h = "H15"
        elif "limitations section" in low or "authors admit in limitations" in low:
            matched_h = "H16"
        elif "citation count" in low or "few citations" in low:
            matched_h = "H17"

    if matched_h is not None:
        return {
            "id": cid,
            "reviewer": reviewer,
            "disposition": DISP_MINOR_POLISH if matched_h == "H11" else DISP_FILTERED_HEURISTIC,
            "heuristic_id": matched_h,
            "rationale": H_RULES[matched_h]["rationale"],
            "text": text,
            "rebuttal_action": (
                "Fix minor grammar/typos during final polish pass; exclude from blocking rework."
                if matched_h == "H11"
                else f"Filter from rework backlog under {matched_h}; respond concisely anchoring claimed scope/precedent."
            ),
            "reference_published_at": comment.get("reference_published_at"),
            "reference_is_preprint_only": bool(comment.get("reference_is_preprint_only")),
        }

    # Substantive ARR classification (M1-M5, T1-T2, R1-R5, G1-G4)
    months_val = comment.get("reference_months_before_deadline")
    is_preprint_val = bool(comment.get("reference_is_preprint_only"))
    h12_substantive_ref = (
        not is_preprint_val
        and isinstance(months_val, (int, float))
        and not isinstance(months_val, bool)
        and months_val >= h12_cutoff_months
    )
    code = explicit_code.strip().upper() if isinstance(explicit_code, str) and explicit_code.strip().upper() in ARR_DEFECT_CATALOG else None
    if code is None:
        if "llm-only" in low or "llm judge" in low:
            code = "M1"
        elif any(tok in low for tok in ("significance", "confidence interval", "error bar", "effect size", "std")):
            code = "R5"
        elif any(tok in low for tok in ("reproduc", "seed", "code missing", "hyperparameter")):
            code = "M2"
        elif any(tok in low for tok in ("contamination", "data quality", "corrupt", "duplicate")):
            code = "M3"
        elif "theorem" in low or "proof" in low or "assumption" in low:
            code = "M5"
        elif any(tok in low for tok in ("ethics", "annotator", "compensation", "irb")):
            code = "T1"
        elif "license" in low:
            code = "T2"
        elif any(tok in low for tok in ("leakage", "cherry-pick", "untuned baseline", "p-hack")):
            code = "R1"
        elif any(tok in low for tok in ("overgeneral", "overclaim", "claimed scope")):
            code = "R2"
        elif "hypothesis" in low and "conclusion" in low:
            code = "R3"
        elif any(tok in low for tok in ("missing", "related work", "citation", "prior work")) and (cited_prec or h12_substantive_ref):
            code = "G3"
        elif "undefined" in low or "terminology" in low or "notation" in low:
            code = "G4"
        elif "benchmark" in low or "baseline" in low:
            code = "M4"
        else:
            code = "G1"

    meta = ARR_DEFECT_CATALOG[code]
    sev = str(comment.get("severity_hint") or "").strip().lower()
    if sev not in ("fatal", "major", "minor"):
        sev = "fatal" if code in ("M3", "M5", "R1", "T1") else ("minor" if code == "G4" else "major")

    effort = explicit_effort if explicit_effort is not None else meta["effort_days"]

    return {
        "id": cid,
        "reviewer": reviewer,
        "disposition": DISP_SUBSTANTIVE_DEFECT,
        "code": code,
        "group": meta["group"],
        "severity": sev,
        "impact_tier": meta["impact"],
        "priority_rank": meta["priority"],
        "effort_days": effort,
        "section": meta["section"],
        "text": text,
    }


def _evaluate_venue_b(
    venue_b_obj: Any,
    venue_sources_obj: Any,
    venue_plan_obj: Any,
    preflight_objs: list[dict[str, Any]],
    artifact_obj: Any,
    sc_state: dict[str, Any],
    as_of_dt: datetime,
    weeks: int,
) -> tuple[dict[str, Any], datetime | None]:
    if venue_b_obj is not None and not isinstance(venue_b_obj, (dict, str)):
        raise ValueError("--venue-b must be a JSON object or venue name string")
    vb = venue_b_obj if isinstance(venue_b_obj, dict) else ({"name": str(venue_b_obj)} if isinstance(venue_b_obj, str) and venue_b_obj.strip() else {})
    vp = _require_dict_or_none(venue_plan_obj, "--venue-plan")
    _require_dict_or_none(venue_sources_obj, "--venue-sources")
    _require_dict_or_none(artifact_obj, "--artifact-readiness")
    blocking_reasons: list[str] = []
    warnings: list[str] = []

    deadline_str = vb.get("submission_deadline_utc") or vb.get("deadline_utc")
    if not deadline_str and vp is not None:
        mut = _require_dict_or_none(vp.get("milestones_user_timezone"), "venue_plan.milestones_user_timezone") or {}
        converted = _require_dict_or_none(vp.get("converted_milestones"), "venue_plan.converted_milestones") or {}
        milestones = _require_dict_or_none(vp.get("milestones"), "venue_plan.milestones") or {}
        deadline_str = mut.get("full_paper") or converted.get("full_paper") or milestones.get("full_paper")

    deadline_dt: datetime | None = None
    days_remaining: int | None = None
    if deadline_str:
        deadline_dt = _parse_iso_utc(deadline_str, "venue_b.submission_deadline_utc")
        days_remaining = int((deadline_dt - as_of_dt).total_seconds() // 86400)
        if days_remaining < 0:
            blocking_reasons.append(f"venue_b_deadline_already_passed ({days_remaining}d)")
        elif days_remaining < 7:
            blocking_reasons.append(f"venue_b_deadline_too_close ({days_remaining}d < 7d minimum)")
        elif days_remaining < weeks * 7:
            warnings.append(f"venue_b_deadline_shorter_than_revision_window ({days_remaining}d < {weeks * 7}d)")

    if vb.get("resubmission_allowed") is False:
        blocking_reasons.append("venue_b_resubmission_not_allowed_or_cooldown_active")
    if vb.get("dual_submission_conflict") is True:
        blocking_reasons.append("venue_b_dual_submission_conflict")
    if vb.get("anonymity_reset_verified") is False:
        blocking_reasons.append("venue_b_anonymity_reset_not_verified")

    for pf in preflight_objs:
        if pf.get("schema") == "submission_anonymization_v1" and pf.get("verdict") == STATUS_FAIL:
            blocking_reasons.append("preflight_anonymization_fail")
        elif pf.get("verdict") == STATUS_FAIL:
            warnings.append(f"preflight_{pf.get('schema', 'check')}_fail")

    if isinstance(artifact_obj, dict) and artifact_obj.get("verdict") == STATUS_FAIL:
        blocking_reasons.append("artifact_readiness_fail")

    if isinstance(venue_sources_obj, dict):
        if venue_sources_obj.get("blocking_source_issues") or venue_sources_obj.get("source_text_status") == "verification_blocked":
            blocking_reasons.append(f"venue_sources_blocked:{venue_sources_obj.get('source_text_status', 'blocked')}")
        elif not venue_sources_obj.get("verification_passed", True):
            warnings.append("venue_sources_quote_coverage_incomplete")

    if vp is not None:
        if vp.get("within_budget") is False:
            blocking_reasons.append("venue_plan:within_budget_false")
        if vp.get("cfp_verified") is False:
            blocking_reasons.append("venue_plan:cfp_not_verified")
        vp_src_issues = vp.get("source_issues") or []
        vp_src_total = vp.get("source_issues_total")
        if vp_src_issues or (isinstance(vp_src_total, int) and not isinstance(vp_src_total, bool) and vp_src_total > 0):
            blocking_reasons.append("venue_plan:source_issues_detected")
        for w in (vp.get("warnings") or []):
            ws = str(w)
            if (
                "already_passed" in ws
                or "redirect_year_mismatch" in ws
                or "unverified_dynamic_page" in ws
                or ws.startswith("cfp_source_")
                or ws.startswith("fee_source_")
            ):
                blocking_reasons.append(f"venue_plan:{ws}")
            else:
                warnings.append(f"venue_plan:{ws}")

    # F25 tier fit check against Venue B (fall back to --venue-plan venue/track/quality_tier when vb omits them)
    eff_venue_b_name = vb.get("name") or (vp.get("venue") if vp is not None else None)
    eff_track = vb.get("track") or (vp.get("track") if vp is not None else None)
    eff_quality_tier = vb.get("quality_tier") or (vp.get("quality_tier") if vp is not None else None)
    eff_tier_exp = vb.get("tier_expectation") or (vp.get("tier_expectation") if vp is not None else None)

    tier_key = None
    if any(x is not None for x in (eff_venue_b_name, eff_track, eff_quality_tier, eff_tier_exp)):
        tier_key = score_math.resolve_venue_tier(
            venue_name=eff_venue_b_name,
            track=eff_track,
            quality_tier=eff_quality_tier,
            tier_expectation=eff_tier_exp,
        )
        if tier_key is None and isinstance(eff_venue_b_name, str) and eff_venue_b_name.strip():
            try:
                tier_key = _resolve_tier_arg(eff_venue_b_name)
            except ValueError:
                tier_key = None
    tier_fit = None
    if sc_state.get("score_result") is not None:
        sc_sr = _validate_readiness_dict(
            _require_dict_or_none(sc_state["score_result"].get("submission_readiness"), "scorecard.submission_readiness") or {},
            "scorecard.submission_readiness",
        )
        if sc_sr.get("fatal_gate_triggered"):
            reasons_txt = ", ".join(sc_sr.get("fatal_reasons") or ["fatal_gate_triggered"])
            blocking_reasons.append(f"scorecard_fatal_gate:{reasons_txt}")
        if tier_key is not None:
            effective_ratings = sc_state.get("ratings") if isinstance(sc_state.get("ratings"), dict) else sc_state.get("inferred_ratings")
            tier_fit = score_math.evaluate_venue_tier_fit(
                tier_key,
                weighted_unrounded=sc_state["score_result"].get("weighted_unrounded"),
                ratings=effective_ratings,
                is_idea=sc_state.get("is_idea", False),
            )
            tier_fit = _reconcile_tier_fit_with_readiness(
                tier_fit,
                sc_sr,
                tier_key,
                ratings=effective_ratings,
            )
            if tier_fit["rejected_below_venue_tier"]:
                blocking_reasons.append(f"rejected_below_venue_b_tier:{tier_key}")

    if blocking_reasons:
        status = STATUS_BLOCKED_RESUB
    elif deadline_dt is None and not vb and not eff_venue_b_name:
        status = STATUS_UNVERIFIED
    else:
        status = STATUS_READY_RESUB

    h12_cutoff_dt = (deadline_dt - timedelta(days=90)).isoformat() if deadline_dt is not None else None
    return {
        "status": status,
        "venue_b_name": eff_venue_b_name,
        "venue_b_tier": tier_key,
        "as_of_utc": as_of_dt.isoformat(),
        "submission_deadline_utc": deadline_dt.isoformat() if deadline_dt else None,
        "days_remaining": days_remaining,
        "h12_three_month_cutoff_utc": h12_cutoff_dt,
        "blocking_reasons": blocking_reasons,
        "warnings": warnings,
        "venue_b_tier_fit": tier_fit,
    }, deadline_dt


def run_post_reject_triage(
    comments: list[dict[str, Any]],
    *,
    venue_a: str | None = None,
    venue_b_obj: Any = None,
    venue_sources_obj: Any = None,
    venue_plan_obj: Any = None,
    preflight_objs: list[dict[str, Any]] | None = None,
    artifact_obj: Any = None,
    scorecard_obj: Any = None,
    as_of_str: str | None = None,
    weeks: int = 3,
    subfield_preset: str | None = None,
) -> dict[str, Any]:
    _parse_int_strict(weeks, "--weeks", min_val=2, max_val=4)
    if subfield_preset is not None and subfield_preset not in SUBFIELD_PRESETS:
        raise ValueError(f"Unknown --subfield-preset: {subfield_preset}")
    if not isinstance(comments, list) or not comments:
        raise ValueError("At least one review comment is required for post-reject triage")

    as_of_dt = _parse_iso_utc(as_of_str, "--as-of") if as_of_str is not None else datetime.now(timezone.utc)
    sc_state = _extract_scorecard_state({}, scorecard_obj) if scorecard_obj is not None else {"ratings": None, "score_result": None, "is_idea": False}
    preflight_list = [p for p in (preflight_objs or []) if isinstance(p, dict)]

    venue_b_checks, vb_deadline = _evaluate_venue_b(
        venue_b_obj, venue_sources_obj, venue_plan_obj, preflight_list, artifact_obj, sc_state, as_of_dt, weeks
    )

    filtered_heuristics: list[dict[str, Any]] = []
    minor_polish: list[dict[str, Any]] = []
    substantive_defects: list[dict[str, Any]] = []

    for c in comments:
        classified = _classify_comment(c)
        # Re-check H12 against Venue B 3-month cutoff if reference_published_at is provided
        if classified["disposition"] == DISP_FILTERED_HEURISTIC and classified.get("heuristic_id") == "H12":
            pub_raw = classified.get("reference_published_at")
            if vb_deadline is not None and pub_raw and not classified.get("reference_is_preprint_only"):
                pub_dt = _parse_iso_utc(pub_raw, f"comment[{classified['id']}].reference_published_at")
                if (vb_deadline - pub_dt).days >= 90:
                    # Promoted to mandatory G3 for Venue B!
                    meta = ARR_DEFECT_CATALOG["G3"]
                    classified = {
                        "id": classified["id"],
                        "reviewer": classified["reviewer"],
                        "disposition": DISP_SUBSTANTIVE_DEFECT,
                        "code": "G3",
                        "group": meta["group"],
                        "severity": "major",
                        "impact_tier": meta["impact"],
                        "priority_rank": meta["priority"],
                        "effort_days": meta["effort_days"],
                        "section": meta["section"],
                        "text": classified["text"],
                        "promoted_from_h12_for_venue_b": True,
                    }

        if classified["disposition"] == DISP_FILTERED_HEURISTIC:
            filtered_heuristics.append(classified)
        elif classified["disposition"] == DISP_MINOR_POLISH:
            minor_polish.append(classified)
        else:
            substantive_defects.append(classified)

    # Sort substantive defects: priority_rank (1=framing/soundness, 2=empirical, 3=clarification), fatal before major, effort ascending
    sev_order = {"fatal": 0, "major": 1, "minor": 2}
    substantive_defects.sort(
        key=lambda d: (d["priority_rank"], sev_order.get(d["severity"], 1), d["effort_days"], d["id"])
    )

    # Allocate substantive defects across Week 1..N (2 <= N <= 4)
    capacity_per_week = 5  # working days/week
    total_capacity_days = weeks * capacity_per_week
    if venue_b_checks["days_remaining"] is not None and venue_b_checks["days_remaining"] >= 0:
        effective_budget = min(total_capacity_days, max(0, int(venue_b_checks["days_remaining"] * 5 / 7)))
    else:
        effective_budget = total_capacity_days

    weekly_plan: dict[str, list[dict[str, Any]]] = {f"Week {w}": [] for w in range(1, weeks + 1)}
    week_loads = {w: 0 for w in range(1, weeks + 1)}
    overflow_tasks: list[dict[str, Any]] = []

    for task in substantive_defects:
        placed = False
        # Framing/soundness priority 1 aims for Week 1 first; empirical priority 2 aims for Week 1..N-1; priority 3 aims for final week
        start_w = 1 if task["priority_rank"] == 1 else (min(2, weeks) if task["priority_rank"] == 2 else weeks)
        candidate_weeks = list(range(start_w, weeks + 1)) + list(range(1, start_w))
        for w in candidate_weeks:
            if week_loads[w] + task["effort_days"] <= capacity_per_week:
                weekly_plan[f"Week {w}"].append({
                    "id": task["id"],
                    "code": task["code"],
                    "severity": task["severity"],
                    "effort_days": task["effort_days"],
                    "action": f"[{task['code']}] {task['text']}",
                })
                week_loads[w] += task["effort_days"]
                placed = True
                break
        if not placed:
            overflow_tasks.append(task)

    total_effort_days = sum(t["effort_days"] for t in substantive_defects)
    deferral_warnings: list[str] = []
    if overflow_tasks:
        deferral_warnings.append(
            f"Substantive effort ({total_effort_days}d) exceeds {weeks}-week capacity ({weeks * capacity_per_week}d); "
            f"{len(overflow_tasks)} task(s) overflow — narrow scope or defer to next cycle."
        )
    if venue_b_checks["days_remaining"] is not None and total_effort_days > effective_budget:
        deferral_warnings.append(
            f"Estimated revision effort ({total_effort_days}d) exceeds working days before Venue B deadline ({effective_budget}d)."
        )
    if any(t["severity"] == "fatal" for t in overflow_tasks):
        deferral_warnings.append("Fatal defect(s) overflow revision window; do not rush Venue B submission.")

    preset_audit = _eval_subfield_preset(subfield_preset, None, {"rigor": [], "preflight": preflight_list}, []) if subfield_preset else None

    return {
        "schema": SCHEMA_POST_REJECT,
        "mode": "post-reject",
        "venue_a": venue_a,
        "revision_window_weeks": weeks,
        "counts": {
            "total_comments": len(comments),
            "filtered_illegitimate_heuristics": len(filtered_heuristics),
            "minor_polish": len(minor_polish),
            "substantive_defects": len(substantive_defects),
            "excluded_from_plan": len(filtered_heuristics),
            "overflow_tasks": len(overflow_tasks),
        },
        "filtered_illegitimate_heuristics": filtered_heuristics,
        "minor_polish": minor_polish,
        "substantive_defects": substantive_defects,
        "venue_b_checks": venue_b_checks,
        "revision_plan": {
            "weeks": weeks,
            "capacity_days": weeks * capacity_per_week,
            "total_effort_days": total_effort_days,
            "schedule": weekly_plan,
            "overflow_tasks": [{"id": t["id"], "code": t["code"], "severity": t["severity"], "effort_days": t["effort_days"]} for t in overflow_tasks],
            "scope_narrowing_or_deferral_recommended": bool(deferral_warnings),
            "deferral_or_scope_narrowing_warnings": deferral_warnings,
        },
        "subfield_preset_audit": preset_audit,
        "warning": (
            "Heuristic filtering separates illegitimate review bias from substantive M/T/R/G defects; "
            "it never invents acceptance probability percentages."
        ),
    }


def _compact_payload(full: dict[str, Any], out_path: str | None) -> dict[str, Any]:
    mode = full.get("mode")
    if mode == "mock-review":
        compact: dict[str, Any] = {
            "compact": True,
            "schema": full["schema"],
            "mode": mode,
            "target_id": full["target_id"],
            "overall_verdict": full["overall_verdict"],
            "defect_counts": full["defect_counts"],
            "personas": full["personas"],
            "defect_ledger": full["defect_ledger"][:8],
            "submission_readiness_band": (full.get("submission_readiness") or {}).get("band"),
            "merit_vs_publishability": {
                "scientific_merit_score": full["merit_vs_publishability"]["scientific_merit_score"],
                "publishability_packaging_score": full["merit_vs_publishability"]["publishability_packaging_score"],
                "bottleneck_diagnosis": full["merit_vs_publishability"]["bottleneck_diagnosis"],
            },
            "worst_case_sensitivity": {
                "worst_case_reviewer_floor": full["worst_case_sensitivity"]["worst_case_reviewer_floor"],
                "worst_case_persona": full["worst_case_sensitivity"]["worst_case_persona"],
                "deal_breaker_dimensions": full["worst_case_sensitivity"]["deal_breaker_dimensions"],
            },
            "subfield_preset_audit": {
                "active_preset": full["subfield_preset_audit"]["active_preset"],
                "status": full["subfield_preset_audit"]["status"],
                "missing_checks": full["subfield_preset_audit"]["missing_checks"],
                "failed_checks": full["subfield_preset_audit"]["failed_checks"],
            },
            "artifact_path": out_path,
        }
    else:
        compact = {
            "compact": True,
            "schema": full["schema"],
            "mode": mode,
            "venue_a": full.get("venue_a"),
            "revision_window_weeks": full.get("revision_window_weeks"),
            "counts": full["counts"],
            "filtered_heuristic_ids": [h.get("heuristic_id") for h in full["filtered_illegitimate_heuristics"]],
            "substantive_defects": [
                {"id": d["id"], "code": d["code"], "severity": d["severity"], "effort_days": d["effort_days"]}
                for d in full["substantive_defects"][:10]
            ],
            "venue_b_checks": {
                "status": full["venue_b_checks"]["status"],
                "days_remaining": full["venue_b_checks"]["days_remaining"],
                "blocking_reasons": full["venue_b_checks"]["blocking_reasons"][:5],
            },
            "revision_plan_summary": {
                "total_effort_days": full["revision_plan"]["total_effort_days"],
                "capacity_days": full["revision_plan"]["capacity_days"],
                "scope_narrowing_or_deferral_recommended": full["revision_plan"]["scope_narrowing_or_deferral_recommended"],
            },
            "artifact_path": out_path,
        }

    def _byte_len(obj: dict[str, Any]) -> int:
        return len(json.dumps(obj, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8"))

    if _byte_len(compact) <= MAX_COMPACT_BYTES:
        return compact

    def _shrink_path_once(path_val: str) -> str | None:
        if len(path_val.encode("utf-8")) > 180:
            name = Path(path_val).name
            cand = ".../" + name if name else ""
            if cand and len(cand.encode("utf-8")) <= 180:
                return cand
        if len(path_val) <= 16:
            return None
        cut = max(1, len(path_val) // 4)
        return "..." + path_val[cut:]

    # Staged trimming loop strictly < 4096 UTF-8 bytes
    for cap in (4, 2, 1, 0):
        if mode == "mock-review":
            compact["defect_ledger"] = [
                {"id": d["id"], "persona": d["persona"], "severity": d["severity"], "code": d["code"]}
                for d in full["defect_ledger"][:cap]
            ]
        else:
            compact["substantive_defects"] = compact["substantive_defects"][:cap]
            compact["filtered_heuristic_ids"] = compact["filtered_heuristic_ids"][:cap]
        if cap == 0 and isinstance(compact.get("artifact_path"), str) and _byte_len(compact) > MAX_COMPACT_BYTES:
            compact["artifact_path"] = _shrink_path_once(compact["artifact_path"])
        if _byte_len(compact) <= MAX_COMPACT_BYTES:
            return compact

    # Minimal fallback strictly bounded <= MAX_COMPACT_BYTES (< 4096 UTF-8 bytes)
    fallback: dict[str, Any] = {
        "compact": True,
        "schema": full["schema"],
        "mode": mode,
        "status": full.get("overall_verdict") or full.get("venue_b_checks", {}).get("status"),
        "artifact_path": out_path,
    }
    while _byte_len(fallback) > MAX_COMPACT_BYTES and isinstance(fallback.get("artifact_path"), str):
        fallback["artifact_path"] = _shrink_path_once(fallback["artifact_path"])
    if _byte_len(fallback) > MAX_COMPACT_BYTES:
        fallback["artifact_path"] = None
    if _byte_len(fallback) > MAX_COMPACT_BYTES and fallback.get("status") is not None:
        fallback["status"] = str(fallback["status"])[:64]
    return fallback


def _should_strict_fail(result: dict[str, Any]) -> bool:
    if result.get("mode") == "mock-review":
        if result["defect_counts"]["fatal"] > 0:
            return True
        if (result.get("submission_readiness") or {}).get("fatal_gate_triggered"):
            return True
        if (result.get("venue_tier_fit") or {}).get("rejected_below_venue_tier"):
            return True
        return False
    vb_status = (result.get("venue_b_checks") or {}).get("status")
    if vb_status == STATUS_BLOCKED_RESUB:
        return True
    if any(t.get("severity") == "fatal" for t in (result.get("revision_plan") or {}).get("overflow_tasks", [])):
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="subcommand", required=True)

    p1 = sub.add_parser("mock-review", help="Mode 1: pre-submission 3-persona adversarial mock review")
    p1.add_argument("--input", help="Consolidated dossier/submission bundle JSON")
    p1.add_argument("--scorecard", help="score_math or compare_scorecards JSON path")
    p1.add_argument("--venue-novelty", help="compare_venue_novelty JSON path")
    p1.add_argument("--rigor", nargs="+", help="One or more check_experiment_rigor JSON paths")
    p1.add_argument("--ledger", help="check_manuscript_ledger JSON path")
    p1.add_argument("--preflight", nargs="+", help="One or more check_submission_preflight JSON paths")
    p1.add_argument("--artifact-readiness", help="check_artifact_readiness JSON path")
    p1.add_argument("--venue-sources", help="check_venue_sources JSON path")
    p1.add_argument("--venue-plan", help="check_venue_plan JSON path")
    p1.add_argument("--engineering-diagnostics", help="check_engineering_diagnostics JSON path")
    p1.add_argument("--sections", help="Optional 6-section diagnostics JSON path")
    p1.add_argument("--anchors", help="Optional 2-3 accepted-paper anchors JSON path")
    p1.add_argument("--venue-tier", help="Target venue tier or canonical tier key")
    p1.add_argument("--scale", choices=SCALES, default="native", help="Score display scale")
    p1.add_argument("--subfield-preset", choices=sorted(SUBFIELD_PRESETS.keys()), default=None, help="F31#2 subfield depth preset")
    p1.add_argument("--strict", action="store_true", help="Exit 1 on fatal defects, fatal gate, or tier rejection")
    p1.add_argument("--out", help="Write full JSON report to PATH")
    p1.add_argument("--compact", action="store_true", help="Emit bounded <4096B JSON summary to stdout")

    p2 = sub.add_parser("post-reject", help="Mode 2: post-reject H1-H17 triage & 2-4 week Venue B plan")
    p2.add_argument("--reviews", required=True, help="Venue A reviews JSON or Markdown/text path")
    p2.add_argument("--venue-a", help="Rejected Venue A label or JSON path")
    p2.add_argument("--venue-b", help="Target Venue B constraints JSON path or venue name")
    p2.add_argument("--venue-sources", help="check_venue_sources JSON path for Venue B")
    p2.add_argument("--venue-plan", help="check_venue_plan JSON path for Venue B")
    p2.add_argument("--preflight", nargs="+", help="One or more check_submission_preflight JSON paths")
    p2.add_argument("--artifact-readiness", help="check_artifact_readiness JSON path")
    p2.add_argument("--scorecard", help="score_math or compare_scorecards JSON path")
    p2.add_argument("--as-of", help="Override UTC reference date/timestamp (ISO 8601)")
    p2.add_argument("--weeks", type=int, default=3, help="Bounded revision horizon in weeks (2..4)")
    p2.add_argument("--subfield-preset", choices=sorted(SUBFIELD_PRESETS.keys()), default=None, help="F31#2 subfield depth preset")
    p2.add_argument("--strict", action="store_true", help="Exit 1 on resubmission_blocked or fatal overflow")
    p2.add_argument("--out", help="Write full JSON report to PATH")
    p2.add_argument("--compact", action="store_true", help="Emit bounded <4096B JSON summary to stdout")

    args = parser.parse_args(argv)
    try:
        out_path: str | None = None
        if args.out is not None:
            out_path = _require_nonempty_str(args.out, "--out")

        if args.subcommand == "mock-review":
            bundle = _parse_json_file(args.input, "--input") if args.input is not None else {}
            if not any([
                args.input is not None, args.scorecard is not None, args.venue_novelty is not None,
                args.rigor is not None, args.ledger is not None, args.preflight is not None,
                args.artifact_readiness is not None, args.venue_sources is not None,
                args.venue_plan is not None, args.engineering_diagnostics is not None,
            ]):
                raise ValueError("Provide --input or at least one upstream artifact flag")

            result = run_mock_review(
                bundle,
                scorecard_obj=_parse_json_file(args.scorecard, "--scorecard") if args.scorecard is not None else None,
                venue_novelty_obj=_parse_json_file(args.venue_novelty, "--venue-novelty") if args.venue_novelty is not None else None,
                rigor_objs=[_parse_json_file(p, "--rigor") for p in args.rigor] if args.rigor is not None else None,
                ledger_obj=_parse_json_file(args.ledger, "--ledger") if args.ledger is not None else None,
                preflight_objs=[_parse_json_file(p, "--preflight") for p in args.preflight] if args.preflight is not None else None,
                artifact_obj=_parse_json_file(args.artifact_readiness, "--artifact-readiness") if args.artifact_readiness is not None else None,
                venue_sources_obj=_parse_json_file(args.venue_sources, "--venue-sources") if args.venue_sources is not None else None,
                venue_plan_obj=_parse_json_file(args.venue_plan, "--venue-plan") if args.venue_plan is not None else None,
                eng_diag_obj=_parse_json_file(args.engineering_diagnostics, "--engineering-diagnostics") if args.engineering_diagnostics is not None else None,
                sections_obj=_parse_json_file(args.sections, "--sections") if args.sections is not None else None,
                anchors_obj=_parse_json_file(args.anchors, "--anchors", expected_type=(list, dict)) if args.anchors is not None else None,
                venue_tier=_resolve_tier_arg(args.venue_tier) if args.venue_tier is not None else None,
                scale=args.scale,
                subfield_preset=args.subfield_preset,
            )
        else:
            comments, reviews_meta = _load_reviews_and_meta(args.reviews)
            venue_a_val = None
            if args.venue_a is not None:
                clean_va = _require_nonempty_str(args.venue_a, "--venue-a")
                venue_a_val = clean_va
            elif isinstance(reviews_meta, dict) and isinstance(reviews_meta.get("venue_a"), str):
                venue_a_val = reviews_meta["venue_a"]
            venue_b_val: Any = None
            if args.venue_b is not None:
                clean_vb = _require_nonempty_str(args.venue_b, "--venue-b")
                if Path(clean_vb).is_file():
                    venue_b_val = _parse_json_file(clean_vb, "--venue-b")
                elif clean_vb.endswith(".json") or "/" in clean_vb:
                    raise ValueError(f"--venue-b file not found: {clean_vb}")
                else:
                    venue_b_val = {"name": clean_vb}
            elif isinstance(reviews_meta, dict) and reviews_meta.get("venue_b") is not None:
                venue_b_val = reviews_meta["venue_b"]

            sc_obj = _parse_json_file(args.scorecard, "--scorecard") if args.scorecard is not None else (
                reviews_meta.get("scorecard") if isinstance(reviews_meta, dict) else None
            )

            result = run_post_reject_triage(
                comments,
                venue_a=venue_a_val,
                venue_b_obj=venue_b_val,
                venue_sources_obj=_parse_json_file(args.venue_sources, "--venue-sources") if args.venue_sources is not None else None,
                venue_plan_obj=_parse_json_file(args.venue_plan, "--venue-plan") if args.venue_plan is not None else None,
                preflight_objs=[_parse_json_file(p, "--preflight") for p in args.preflight] if args.preflight is not None else None,
                artifact_obj=_parse_json_file(args.artifact_readiness, "--artifact-readiness") if args.artifact_readiness is not None else None,
                scorecard_obj=sc_obj,
                as_of_str=args.as_of,
                weeks=args.weeks,
                subfield_preset=args.subfield_preset,
            )

        if out_path is not None:
            out_file = Path(out_path)
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")

        stdout_obj = _compact_payload(result, out_path) if args.compact else result
        print(json.dumps(stdout_obj, separators=(",", ":") if args.compact else None, ensure_ascii=False, allow_nan=False))
        if args.strict and _should_strict_fail(result):
            return 1
        return 0
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, json.JSONDecodeError, InvalidOperation) as exc:
        print(json.dumps({"error": str(exc)}, allow_nan=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
