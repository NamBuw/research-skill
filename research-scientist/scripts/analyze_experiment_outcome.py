#!/usr/bin/env python3
"""Post-experiment error-slice gate, HARKing blocker, pivot recommender, and failure-cases exporter."""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

try:
    import check_question_card
except ImportError:  # pragma: no cover
    check_question_card = None  # type: ignore[assignment]

try:
    import check_experiment_manifest
except ImportError:  # pragma: no cover
    check_experiment_manifest = None  # type: ignore[assignment]

try:
    import score_math
except ImportError:  # pragma: no cover
    score_math = None  # type: ignore[assignment]

try:
    import venue_leads
except ImportError:  # pragma: no cover
    venue_leads = None  # type: ignore[assignment]


SCHEMA_VERSION = 'research_scientist_experiment_outcome_v1'
FAILURE_CASES_SCHEMA = 'research_scientist_failure_cases_v1'
MAX_COMPACT_BYTES = 4096

SLICE_DIMENSIONS = (
    'length',
    'difficulty',
    'ood_shift',
    'scale',
    'subgroup',
    'domain',
    'noise',
    'class_frequency',
    'prompt_template',
    'compute_budget',
)

ALLOWED_PIVOT_ACTIONS = (
    'add_targeted_ablation',
    'narrow_claim_scope',
    'pivot_to_negative_or_diagnostic_paper',
    'downgrade_venue_tier',
)

_STOPWORDS = {
    'the', 'a', 'an', 'and', 'or', 'of', 'to', 'in', 'on', 'for', 'with', 'by', 'as',
    'is', 'are', 'was', 'were', 'be', 'been', 'that', 'this', 'which', 'under', 'over',
    'than', 'vs', 'versus', 'when', 'where', 'how', 'does', 'do', 'not', 'only',
}

_PRIOR_EXPOSURE_RE = re.compile(
    r'\b(?:seen|inspected|viewed|exposed|yes|true|peeked|tampered|already[_\s-]?(?:inspected|viewed|seen|exposed)|'
    r'outcomes?[_\s-]?seen|seen[_\s-]?results?|post[_\s-]?hoc|retrospective)\b',
    re.I,
)
_SAFE_EXPOSURE_VALUES = {
    '', 'none', 'none uninspected', 'uninspected', 'unseen', 'blinded',
    'no', 'false', 'not inspected', 'not seen', 'no exposure', 'no prior exposure',
}
_NEGATED_EXPOSURE_RE = re.compile(
    r'^(?:no|not|never|none|without)\b.*\b(?:seen|inspected|viewed|exposed|peeked|exposure)\b',
    re.I,
)


def _has_prior_outcome_exposure(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    if not isinstance(val, str):
        return False
    norm = re.sub(r'[\W_]+', ' ', val.strip().lower()).strip()
    if norm in _SAFE_EXPOSURE_VALUES:
        return False
    if _NEGATED_EXPOSURE_RE.match(norm) and not re.search(r'\b(?:tampered|peeked|yes)\b', norm):
        return False
    return bool(_PRIOR_EXPOSURE_RE.search(norm))


def _mentions_slice(text_low: str, slice_name: str) -> bool:
    sn = slice_name.strip().lower()
    if not sn:
        return False
    for variant in (sn, sn.replace('_', ' '), sn.replace('-', ' ')):
        if re.search(r'(?<![a-z0-9_])' + re.escape(variant) + r'(?![a-z0-9_])', text_low):
            return True
    return False


def _reject_nonfinite(token: str) -> None:
    raise ValueError(f'Non-finite JSON constant not allowed: {token}')


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _nonblank(val: Any) -> bool:
    return isinstance(val, str) and bool(val.strip())


def _require_nonempty_arg(value: str | None, flag_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{flag_name} must be a nonblank string')
    return value.strip()


def _load_json(path_str: str, label: str) -> Any:
    clean = _require_nonempty_arg(path_str, label)
    if clean is None:
        raise ValueError(f'{label} is required')
    p = Path(clean)
    if not p.is_file():
        raise ValueError(f'{label} file not found: {clean}')
    raw = p.read_text(encoding='utf-8')
    return json.loads(raw, parse_constant=_reject_nonfinite)


def _finite_number(val: Any) -> float | None:
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return None
    f = float(val)
    if not math.isfinite(f):
        raise ValueError(f'Non-finite numeric value not allowed: {val}')
    return f


def _content_tokens(text: str) -> set[str]:
    toks = {t for t in re.findall(r'[a-z0-9_]+', text.lower()) if len(t) >= 3 and t not in _STOPWORDS}
    return toks


def _compute_delta(baseline: float | None, candidate: float | None, direction: str) -> float | None:
    if baseline is None or candidate is None:
        return None
    if direction == 'lower':
        return round(baseline - candidate, 6)
    return round(candidate - baseline, 6)


def _resolve_venue_tier_safe(target_venue: str | None, target_venue_tier: str | None) -> str | None:
    if score_math is None:
        return target_venue_tier
    qt = None
    if _nonblank(target_venue) and venue_leads is not None:
        try:
            qinfo = venue_leads.lookup_venue_quality(target_venue)
            if qinfo.get('quality_tier') in {'S', 'A', 'B', 'C'}:
                qt = qinfo['quality_tier']
        except Exception:
            qt = None
    return score_math.resolve_venue_tier(
        venue_name=target_venue,
        quality_tier=qt,
        tier_expectation=target_venue_tier,
    )


def analyze(
    question_card: dict[str, Any],
    outcomes: dict[str, Any],
    *,
    manifest: dict[str, Any] | None = None,
    manifest_dir: Path | None = None,
    verify_files: bool = False,
) -> dict[str, Any]:
    if not isinstance(question_card, dict):
        raise ValueError('question_card must be a JSON object')
    if not isinstance(outcomes, dict):
        raise ValueError('outcomes must be a JSON object')

    errors: list[str] = []
    warnings: list[str] = []

    qc_res = (
        check_question_card.check(question_card)
        if check_question_card is not None
        else {'valid_structure': True, 'errors': [], 'warnings': []}
    )
    if not qc_res.get('valid_structure'):
        errors.append('question_card_invalid')
        for e in qc_res.get('errors') or []:
            errors.append(f'question_card:{e}')

    manifest_errors: list[str] = []
    manifest_warnings: list[str] = []
    manifest_sha256s: list[str] = []
    manifest_has_non_prespecified = False
    files_verified_ok = True
    if manifest is not None:
        if not isinstance(manifest, dict):
            raise ValueError('manifest must be a JSON object')
        if check_experiment_manifest is not None:
            m_res = check_experiment_manifest.check(manifest)
            if m_res.get('status') == 'invalid':
                manifest_errors.extend(m_res.get('errors') or ['manifest_invalid'])
            manifest_warnings.extend(m_res.get('warnings') or [])
            if verify_files:
                v_res = check_experiment_manifest.verify_files(manifest, manifest_dir or Path('.'))
                if not v_res.get('files_verified', True) or v_res.get('file_errors'):
                    files_verified_ok = False
                    manifest_errors.extend(v_res.get('file_errors') or ['manifest_verify_files_failed'])
        for r in manifest.get('runs') or []:
            if isinstance(r, dict):
                if r.get('decision_timing') in ('amended', 'exploratory'):
                    manifest_has_non_prespecified = True
                sha = r.get('result_artifact_sha256')
                if isinstance(sha, str) and len(sha) == 64:
                    manifest_sha256s.append(sha)
        errors.extend(manifest_errors)
        warnings.extend(manifest_warnings)

    metric = outcomes.get('primary_metric')
    if not isinstance(metric, dict):
        raise ValueError('outcomes.primary_metric must be a JSON object')
    metric_name = str(metric.get('name') or 'primary_metric').strip()
    direction = str(metric.get('direction') or 'higher').strip().lower()
    if direction not in ('higher', 'lower'):
        raise ValueError('primary_metric.direction must be higher or lower')
    base_val = _finite_number(metric.get('baseline'))
    cand_val = _finite_number(metric.get('candidate'))
    primary_delta = _compute_delta(base_val, cand_val, direction)
    if primary_delta is None:
        raw_delta = _finite_number(metric.get('delta'))
        primary_delta = raw_delta
    if primary_delta is None:
        raise ValueError('primary_metric requires baseline+candidate or delta')

    ci95 = metric.get('ci95')
    ci_spans_zero = False
    if ci95 is not None:
        if not isinstance(ci95, list) or len(ci95) != 2:
            raise ValueError('primary_metric.ci95 must be a 2-element list')
        ci_lo = _finite_number(ci95[0])
        ci_hi = _finite_number(ci95[1])
        if ci_lo is None or ci_hi is None or ci_lo > ci_hi:
            raise ValueError('primary_metric.ci95 must contain finite ordered bounds')
        if ci_lo <= 0.0 <= ci_hi:
            ci_spans_zero = True

    # Error slices enforcement
    raw_slices = outcomes.get('error_slices')
    valid_slices: list[dict[str, Any]] = []
    seen_slices: set[tuple[str, str]] = set()
    if not isinstance(raw_slices, list) or not raw_slices:
        errors.append('missing_error_slices')
    else:
        for idx, sl in enumerate(raw_slices):
            if not isinstance(sl, dict):
                errors.append(f'invalid_error_slice:{idx}')
                continue
            s_type = str(sl.get('slice_type') or '').strip()
            s_name = str(sl.get('slice_name') or '').strip()
            if not s_type or not s_name:
                errors.append(f'incomplete_error_slice:{idx}')
                continue
            slice_key = (s_type.lower(), s_name.lower())
            if slice_key in seen_slices:
                if 'duplicate_error_slices' not in errors:
                    errors.append('duplicate_error_slices')
                continue
            seen_slices.add(slice_key)
            sb = _finite_number(sl.get('baseline'))
            sc = _finite_number(sl.get('candidate'))
            sd = _compute_delta(sb, sc, direction)
            if sd is None:
                sd = _finite_number(sl.get('delta'))
            if sd is None:
                errors.append(f'non_numeric_error_slice:{s_name}')
                continue
            n_val = sl.get('n')
            if n_val is not None and (isinstance(n_val, bool) or not isinstance(n_val, int) or n_val < 0):
                raise ValueError(f'slice {s_name} n must be a nonnegative integer')
            valid_slices.append({
                'slice_type': s_type,
                'slice_name': s_name,
                'baseline': sb,
                'candidate': sc,
                'delta': sd,
                'n': n_val,
                'notes': str(sl.get('notes') or '').strip(),
            })
        if len(valid_slices) < 2:
            errors.append('insufficient_error_slices:need_at_least_2')

    slice_types_used = {s['slice_type'] for s in valid_slices}
    canonical_used = slice_types_used & set(SLICE_DIMENSIONS)
    if valid_slices and not canonical_used:
        warnings.append('nonstandard_slice_dimensions_only')
    elif valid_slices and len(slice_types_used) < 2:
        warnings.append('single_slice_dimension_only')

    winning_slices = [s for s in valid_slices if s['delta'] > 0]
    losing_slices = [s for s in valid_slices if s['delta'] < 0]
    flat_slices = [s for s in valid_slices if s['delta'] == 0]
    worst_slice = min(valid_slices, key=lambda s: s['delta']) if valid_slices else None

    # HARKing detection
    claim_mode = str(outcomes.get('claim_mode') or 'confirmatory').strip().lower()
    if claim_mode not in ('confirmatory', 'exploratory'):
        raise ValueError('claim_mode must be confirmatory or exploratory')
    claimed_outcome = str(outcomes.get('claimed_outcome') or '').strip().lower()
    claimed_hypothesis = str(outcomes.get('claimed_hypothesis') or '').strip()
    post_hoc_changed = bool(outcomes.get('post_hoc_hypothesis_changed', False))

    harking_violations: list[str] = []
    if post_hoc_changed and (claim_mode == 'confirmatory' or (manifest is not None and not manifest_has_non_prespecified)):
        harking_violations.append('post_hoc_hypothesis_changed_under_confirmatory_or_prespecified_protocol')

    if _has_prior_outcome_exposure(question_card.get('prior_outcome_exposure')) and claim_mode == 'confirmatory':
        harking_violations.append('prior_outcome_exposure_blocks_confirmatory_claim')

    if claimed_outcome == 'supports_focal':
        if primary_delta <= 0:
            harking_violations.append('falsifier_or_nonpositive_delta_claimed_as_supports_focal')
        if ci_spans_zero and claim_mode == 'confirmatory':
            harking_violations.append('inconclusive_ci_claimed_as_supports_focal_confirmatory')
        if claim_mode == 'confirmatory' and (manifest_has_non_prespecified or not files_verified_ok):
            harking_violations.append('amended_or_unverified_manifest_claimed_as_confirmatory_support')
        if valid_slices and len(losing_slices) > len(winning_slices):
            harking_violations.append('cherry_picked_slice_harking:majority_slices_regress')
        if valid_slices and losing_slices and claimed_hypothesis:
            ch_low = claimed_hypothesis.lower()
            mentions_win = any(_mentions_slice(ch_low, s['slice_name']) for s in winning_slices)
            mentions_loss = any(_mentions_slice(ch_low, s['slice_name']) for s in losing_slices)
            if mentions_win and not mentions_loss:
                harking_violations.append('cherry_picked_slice_harking:omits_regressing_slice')

    if claimed_hypothesis and claim_mode == 'confirmatory' and claimed_outcome == 'supports_focal':
        frozen_toks = _content_tokens(
            f"{question_card.get('question', '')} {question_card.get('expected_if_focal', '')}"
        )
        claimed_toks = _content_tokens(claimed_hypothesis)
        if len(frozen_toks) >= 3 and len(claimed_toks) >= 3:
            union = frozen_toks | claimed_toks
            jaccard = len(frozen_toks & claimed_toks) / len(union)
            if jaccard < 0.25:
                harking_violations.append(f'frozen_question_hypothesis_mismatch:jaccard={jaccard:.2f}')

    harking_detected = bool(harking_violations)
    if harking_detected:
        errors.extend(f'harking:{v}' for v in harking_violations)

    eng_verdict = str(outcomes.get('engineering_diagnostics_verdict') or 'PASS').strip().upper()
    if eng_verdict != 'PASS' or not files_verified_ok or manifest_errors:
        outcome_classification = 'engineering_artifact_unresolved'
    elif primary_delta <= 0 and not winning_slices:
        outcome_classification = 'rival_or_null_supported'
    elif primary_delta <= 0 and winning_slices and losing_slices:
        outcome_classification = 'mixed_slice_dependent'
    elif winning_slices and losing_slices:
        outcome_classification = 'mixed_slice_dependent'
    elif primary_delta > 0 and ci_spans_zero:
        outcome_classification = 'indeterminate'
    elif primary_delta > 0 and not losing_slices:
        outcome_classification = 'focal_supported'
    else:
        outcome_classification = 'indeterminate'

    # Pivot recommendations strictly from ALLOWED_PIVOT_ACTIONS
    pivots: list[dict[str, str]] = []
    seen_actions: set[str] = set()

    def _add_pivot(action: str, reason: str) -> None:
        if action not in ALLOWED_PIVOT_ACTIONS or action in seen_actions:
            return
        seen_actions.add(action)
        pivots.append({'action': action, 'reason': reason})

    ablations = outcomes.get('ablation_results')
    if outcome_classification in ('mixed_slice_dependent', 'engineering_artifact_unresolved') or not ablations:
        if outcome_classification != 'focal_supported':
            _add_pivot(
                'add_targeted_ablation',
                'Isolate mechanism failures across regressing error slices or unresolved engineering/ablation gaps.',
            )

    if outcome_classification == 'mixed_slice_dependent':
        win_names = ', '.join(s['slice_name'] for s in winning_slices) or 'winning slices'
        lose_names = ', '.join(s['slice_name'] for s in losing_slices) or 'regressing slices'
        _add_pivot(
            'narrow_claim_scope',
            f'Restrict claims to {win_names}; explicitly scope out failure regime ({lose_names}).',
        )

    if outcome_classification == 'rival_or_null_supported' and eng_verdict == 'PASS':
        _add_pivot(
            'pivot_to_negative_or_diagnostic_paper',
            'Focal hypothesis was cleanly falsified under verified engineering checks; reframe as diagnostic/negative-result study.',
        )

    target_venue = outcomes.get('target_venue')
    target_tier = _resolve_venue_tier_safe(target_venue, outcomes.get('target_venue_tier'))
    proposed_score = _finite_number(outcomes.get('proposed_paper_score'))
    tier_fit = None
    if score_math is not None and target_tier is not None:
        tier_fit = score_math.evaluate_venue_tier_fit(
            target_tier,
            weighted_unrounded=proposed_score,
        )
    need_downgrade = False
    if target_tier in ('top_tier_flagship', 'q1_or_tier_a'):
        if outcome_classification in ('rival_or_null_supported',):
            need_downgrade = True
        elif outcome_classification == 'mixed_slice_dependent' and primary_delta <= 0:
            need_downgrade = True
        elif tier_fit and tier_fit.get('rejected_below_venue_tier'):
            need_downgrade = True
    if need_downgrade:
        rec_tier = (tier_fit or {}).get('recommended_matched_tier') or 'workshop_or_preliminary'
        _add_pivot(
            'downgrade_venue_tier',
            f'Current empirical evidence does not support {target_tier}; retarget to {rec_tier}.',
        )

    # Build F30#2 failure_cases export payload
    failure_cases: list[dict[str, Any]] = []
    for idx, sl in enumerate(losing_slices, start=1):
        if eng_verdict != 'PASS':
            f_cat = 'engineering_artifact'
        elif sl['slice_type'] in ('length', 'scale', 'compute_budget'):
            f_cat = 'scale_or_length_degradation'
        elif outcome_classification == 'rival_or_null_supported':
            f_cat = 'rival_supported'
        else:
            f_cat = 'mechanistic_boundary'
        desc = sl['notes'] or f"{sl['slice_name']} ({sl['slice_type']}) regressed by {sl['delta']} on {metric_name}"
        failure_cases.append({
            'id': f'FC-{idx}',
            'slice_type': sl['slice_type'],
            'slice_name': sl['slice_name'],
            'metric': metric_name,
            'baseline_value': sl['baseline'],
            'candidate_value': sl['candidate'],
            'delta': sl['delta'],
            'n': sl['n'],
            'failure_category': f_cat,
            'description': desc,
            'prior_art_crosscheck_queries': [
                f"{sl['slice_name']} {sl['slice_type']} {metric_name} degradation",
                f"{sl['slice_type']} failure mode {question_card.get('construct_or_estimand', '')}".strip(),
            ],
        })

    failure_cases_payload = {
        'schema': FAILURE_CASES_SCHEMA,
        'source_question': question_card.get('question', ''),
        'generated_at_utc': _utc_now(),
        'run_receipt_sha256s': manifest_sha256s,
        'failure_cases': failure_cases,
    }

    if harking_detected:
        status = 'blocked_harking'
    elif errors:
        status = 'gate_failed'
    else:
        status = 'analyzed'

    recommended_action = pivots[0]['action'] if pivots else 'proceed_to_full_study'
    return {
        'schema': SCHEMA_VERSION,
        'status': status,
        'question_id': question_card.get('id') or (manifest or {}).get('question_id'),
        'claim_mode': claim_mode,
        'primary_metric': {
            'name': metric_name,
            'direction': direction,
            'baseline': base_val,
            'candidate': cand_val,
            'delta': primary_delta,
            'ci95': ci95,
            'ci_spans_zero': ci_spans_zero,
        },
        'slice_summary': {
            'total_valid_slices': len(valid_slices),
            'winning_count': len(winning_slices),
            'losing_count': len(losing_slices),
            'flat_count': len(flat_slices),
            'slice_types': sorted(slice_types_used),
            'worst_slice': worst_slice,
        },
        'harking_detected': harking_detected,
        'harking_violations': harking_violations,
        'outcome_classification': outcome_classification,
        'recommended_action': recommended_action,
        'pivot_recommendations': pivots,
        'tier_fit': tier_fit,
        'errors': errors,
        'warnings': warnings,
        'failure_cases_payload': failure_cases_payload,
        'failure_cases': failure_cases,
    }


def _auto_artifact_path(prefix: str) -> Path:
    art_dir = Path(tempfile.gettempdir()) / 'research_scientist_artifacts'
    art_dir.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(prefix=f'{prefix}_', suffix='.json', dir=str(art_dir))
    os.close(fd)
    return Path(raw_path)


def _compact_output(result: dict[str, Any], out_path: str | None) -> dict[str, Any]:
    target = Path(out_path) if out_path else _auto_artifact_path('experiment_outcome')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2), encoding='utf-8')
    compact = {
        'compact': True,
        'schema': result.get('schema'),
        'status': result.get('status'),
        'outcome_classification': result.get('outcome_classification'),
        'harking_detected': result.get('harking_detected'),
        'recommended_action': result.get('recommended_action'),
        'pivot_actions': [p['action'] for p in (result.get('pivot_recommendations') or [])],
        'failure_case_count': len(result.get('failure_cases') or []),
        'errors': (result.get('errors') or [])[:5],
        'artifact_path': str(target),
    }
    if len(json.dumps(compact, ensure_ascii=False).encode('utf-8')) >= MAX_COMPACT_BYTES:
        compact = {
            'compact': True,
            'schema': result.get('schema'),
            'status': result.get('status'),
            'harking_detected': result.get('harking_detected'),
            'artifact_path': str(target),
        }
    return compact


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--question-card', required=True, help='Path to frozen question_card.json')
    parser.add_argument('--outcomes', required=True, help='Path to experiment outcomes.json')
    parser.add_argument('--manifest', help='Optional path to experiment_manifest.json')
    parser.add_argument('--verify-files', action='store_true', help='Verify manifest SHA-256 files on disk')
    parser.add_argument('--export-failure-cases', help='Write research_scientist_failure_cases_v1 JSON')
    parser.add_argument('--out', help='Write full outcome analysis JSON')
    parser.add_argument('--compact', action='store_true', help='Emit <4096B compact JSON summary')
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        qc_path = _require_nonempty_arg(args.question_card, '--question-card')
        out_in = _require_nonempty_arg(args.outcomes, '--outcomes')
        man_path = _require_nonempty_arg(args.manifest, '--manifest')
        fc_path = _require_nonempty_arg(args.export_failure_cases, '--export-failure-cases')
        out_path = _require_nonempty_arg(args.out, '--out')

        qc_data = _load_json(qc_path, '--question-card')
        outcomes_data = _load_json(out_in, '--outcomes')
        man_data = _load_json(man_path, '--manifest') if man_path else None
        man_dir = Path(man_path).resolve().parent if man_path else None

        result = analyze(
            qc_data,
            outcomes_data,
            manifest=man_data,
            manifest_dir=man_dir,
            verify_files=args.verify_files,
        )

        if fc_path:
            fp = Path(fc_path)
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(json.dumps(result['failure_cases_payload'], indent=2), encoding='utf-8')
            result['failure_cases_path'] = str(fp)

        if out_path and not args.compact:
            op = Path(out_path)
            op.parent.mkdir(parents=True, exist_ok=True)
            op.write_text(json.dumps(result, indent=2), encoding='utf-8')

        if args.compact:
            print(json.dumps(_compact_output(result, out_path), ensure_ascii=False))
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False))

        return 0 if result['status'] == 'analyzed' else 1
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
