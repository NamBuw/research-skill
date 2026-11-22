#!/usr/bin/env python3
"""Calculate a declared weighted score; never supply scientific judgments."""
import argparse
import json
import re
import sys
from decimal import BasicContext, Decimal, ROUND_HALF_UP, localcontext
from pathlib import Path

DIMENSIONS = ('importance', 'novelty', 'soundness', 'evidence', 'transparency', 'clarity')
FATAL_THRESHOLDS = {
    'importance': 2,
    'novelty': 2,
    'soundness': 4,
    'evidence': 4,
    'transparency': 3,
    'clarity': 2,
}
TOP_TIER_COMPETITIVE_THRESHOLD = Decimal('6.80')

VENUE_TIER_ORDER = (
    'top_tier_flagship',
    'q1_or_tier_a',
    'q2_q3_or_tier_b',
    'workshop_or_preliminary',
)

VENUE_TIER_FLOORS = {
    'top_tier_flagship': {
        'label': 'Top-Tier Flagship / CCF-A / Flagship Q1',
        'rank': 0,
        'competitive_overall': Decimal('6.80'),
        'min_viable_overall': Decimal('6.00'),
        'min_dimensions': {'soundness': 6, 'evidence': 6, 'novelty': 5},
        'min_any_dimension': 5,
    },
    'q1_or_tier_a': {
        'label': 'Q1 Journal / Tier-A / CCF-B / Findings',
        'rank': 1,
        'competitive_overall': Decimal('6.35'),
        'min_viable_overall': Decimal('6.00'),
        'min_dimensions': {'soundness': 6, 'evidence': 6, 'novelty': 5},
        'min_any_dimension': 5,
    },
    'q2_q3_or_tier_b': {
        'label': 'Q2-Q3 Journal / Tier-B / CCF-C',
        'rank': 2,
        'competitive_overall': Decimal('5.80'),
        'min_viable_overall': Decimal('5.50'),
        'min_dimensions': {'soundness': 5, 'evidence': 5},
        'min_any_dimension': 4,
    },
    'workshop_or_preliminary': {
        'label': 'Workshop / Preliminary Track',
        'rank': 3,
        'competitive_overall': Decimal('5.50'),
        'min_viable_overall': Decimal('5.00'),
        'min_dimensions': {},
        'min_any_dimension': 3,
    },
}

_TIER_ALIASES = {
    'top_tier_flagship': 'top_tier_flagship',
    'top_tier_main_track': 'top_tier_flagship',
    'flagship': 'top_tier_flagship',
    'tier_s': 'top_tier_flagship',
    's': 'top_tier_flagship',
    'ccf_a': 'top_tier_flagship',
    'q1_or_tier_a': 'q1_or_tier_a',
    'q1': 'q1_or_tier_a',
    'tier_a': 'q1_or_tier_a',
    'a': 'q1_or_tier_a',
    'ccf_b': 'q1_or_tier_a',
    'findings': 'q1_or_tier_a',
    'q2_q3_or_tier_b': 'q2_q3_or_tier_b',
    'q2_q3': 'q2_q3_or_tier_b',
    'q2': 'q2_q3_or_tier_b',
    'q3': 'q2_q3_or_tier_b',
    'tier_b': 'q2_q3_or_tier_b',
    'b': 'q2_q3_or_tier_b',
    'c': 'q2_q3_or_tier_b',
    'ccf_c': 'q2_q3_or_tier_b',
    'workshop_or_preliminary': 'workshop_or_preliminary',
    'workshop': 'workshop_or_preliminary',
    'preliminary': 'workshop_or_preliminary',
}


def resolve_venue_tier(venue_name=None, track=None, quality_tier=None, tier_expectation=None):
    """Map venue name/track/quality tier or explicit expectation to a canonical tier floor key."""
    if isinstance(tier_expectation, str) and tier_expectation.strip():
        norm_exp = re.sub(r'[\s\-/]+', '_', tier_expectation.strip().lower())
        if norm_exp in _TIER_ALIASES:
            return _TIER_ALIASES[norm_exp]
    combined = f'{venue_name or ""} {track or ""}'.lower()
    if re.search(r'\b(?:workshops?|preliminary|doctoral|demos?|posters?|srw|extended\s+abstracts?)\b', combined):
        return 'workshop_or_preliminary'
    if re.search(r'\bfindings\b', combined):
        return 'q1_or_tier_a'
    if re.search(r'\b(?:q1|tier[-\s]?a|ccf[-\s]?b)\b', combined):
        return 'q1_or_tier_a'
    if re.search(r'\b(?:q2|q3|tier[-\s]?b|ccf[-\s]?c)\b', combined):
        return 'q2_q3_or_tier_b'
    qt = str(quality_tier or '').strip().upper()
    if qt == 'S':
        return 'top_tier_flagship'
    if qt == 'A':
        return 'q1_or_tier_a'
    if qt in ('B', 'C'):
        return 'q2_q3_or_tier_b'
    return None


def _to_decimal_or_none(val):
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, Decimal):
        return val if val.is_finite() else None
    if isinstance(val, (int, float)):
        if isinstance(val, float) and (val != val or val in (float('inf'), float('-inf'))):
            return None
        return Decimal(str(val))
    if isinstance(val, str) and val.strip():
        try:
            d = Decimal(val.strip())
            return d if d.is_finite() else None
        except Exception:
            return None
    return None


def _tier_deficits(tier_key, weighted_dec, ratings, target_novelty, panel_median_novelty, target_vs_venue_overall_delta):
    floor = VENUE_TIER_FLOORS[tier_key]
    reasons = []
    upgrade_gaps = {}
    if weighted_dec is not None and weighted_dec < floor['min_viable_overall']:
        with localcontext(BasicContext) as ctx:
            ctx.prec = 28
            gap_min = (floor['min_viable_overall'] - weighted_dec).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        reasons.append(f'weighted_{weighted_dec}_below_{tier_key}_min_{floor["min_viable_overall"]}')
        upgrade_gaps['weighted_to_min_viable'] = float(str(gap_min))
    if weighted_dec is not None and weighted_dec < floor['competitive_overall']:
        with localcontext(BasicContext) as ctx:
            ctx.prec = 28
            gap_comp = (floor['competitive_overall'] - weighted_dec).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        upgrade_gaps['weighted_to_competitive'] = float(str(gap_comp))
    if isinstance(ratings, dict):
        for dim, min_val in floor['min_dimensions'].items():
            rv = ratings.get(dim)
            if type(rv) is int and rv < min_val:
                reasons.append(f'{dim}_{rv}_below_{tier_key}_min_{min_val}')
                upgrade_gaps[dim] = max(upgrade_gaps.get(dim, 0), min_val - rv)
        min_any = floor['min_any_dimension']
        for dim in DIMENSIONS:
            rv = ratings.get(dim)
            if type(rv) is int and rv < min_any:
                reasons.append(f'{dim}_{rv}_below_{tier_key}_dim_floor_{min_any}')
                upgrade_gaps[dim] = max(upgrade_gaps.get(dim, 0), min_any - rv)
    elif target_novelty is not None and 'novelty' in floor['min_dimensions']:
        min_nov = floor['min_dimensions']['novelty']
        if target_novelty < min_nov:
            reasons.append(f'novelty_{target_novelty}_below_{tier_key}_min_{min_nov}')
            upgrade_gaps['novelty'] = min_nov - target_novelty

    delta_dec = _to_decimal_or_none(target_vs_venue_overall_delta)
    if delta_dec is not None and delta_dec <= Decimal('-1.0'):
        reasons.append(f'target_vs_venue_overall_delta_{delta_dec:+.2f}_below_venue_bar')
        with localcontext(BasicContext) as ctx:
            ctx.prec = 28
            need = (-delta_dec).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        upgrade_gaps['overall_vs_venue_panel_median'] = float(str(need))

    pm_dec = _to_decimal_or_none(panel_median_novelty)
    if tier_key in ('top_tier_flagship', 'q1_or_tier_a') and pm_dec is not None and type(target_novelty) is int:
        with localcontext(BasicContext) as ctx:
            ctx.prec = 28
            nov_gap = pm_dec - Decimal(target_novelty)
        if nov_gap >= Decimal('2'):
            reasons.append(f'novelty_{target_novelty}_trails_panel_median_{pm_dec}_by_{nov_gap}')
            upgrade_gaps['novelty_vs_panel_median'] = max(
                upgrade_gaps.get('novelty_vs_panel_median', 0),
                int(nov_gap) - 1 if nov_gap == int(nov_gap) else int(nov_gap),
            )
    return reasons, upgrade_gaps


def _recommend_matched_tier(weighted_dec, ratings, is_idea, target_novelty=None, panel_median_novelty=None, target_vs_venue_overall_delta=None):
    if is_idea:
        return 'none_hold_for_rework'
    if type(target_novelty) is int and target_novelty <= 2:
        return 'none_hold_for_rework'
    if isinstance(ratings, dict):
        for dim in DIMENSIONS:
            rv = ratings.get(dim)
            if type(rv) is int and rv <= FATAL_THRESHOLDS[dim]:
                return 'none_hold_for_rework'
    if weighted_dec is not None:
        if weighted_dec < Decimal('5.00'):
            return 'none_hold_for_rework'
        for tier_key in VENUE_TIER_ORDER:
            floor = VENUE_TIER_FLOORS[tier_key]
            threshold = floor['competitive_overall'] if tier_key == 'top_tier_flagship' else floor['min_viable_overall']
            if weighted_dec < threshold:
                continue
            reasons, _ = _tier_deficits(tier_key, weighted_dec, ratings, target_novelty, None, None)
            if not reasons:
                return tier_key
        return 'none_hold_for_rework'
    delta_dec = _to_decimal_or_none(target_vs_venue_overall_delta)
    if (delta_dec is not None and delta_dec <= Decimal('-1.0')) or (type(target_novelty) is int and target_novelty <= 4):
        return 'workshop_or_preliminary'
    pm_dec = _to_decimal_or_none(panel_median_novelty)
    if pm_dec is not None and type(target_novelty) is int:
        with localcontext(BasicContext) as ctx:
            ctx.prec = 28
            if (pm_dec - Decimal(target_novelty)) >= Decimal('2'):
                return 'q2_q3_or_tier_b'
    return None


def evaluate_venue_tier_fit(
    venue_tier,
    *,
    weighted_unrounded=None,
    ratings=None,
    is_idea=False,
    target_novelty=None,
    panel_median_novelty=None,
    target_vs_venue_overall_delta=None,
):
    """Evaluate paper contribution against canonical venue-tier floors (Decimal-trap safe)."""
    with localcontext(BasicContext) as ctx:
        ctx.prec = 28
        weighted_dec = _to_decimal_or_none(weighted_unrounded)
        matched_tier = _recommend_matched_tier(
            weighted_dec,
            ratings,
            is_idea,
            target_novelty=target_novelty,
            panel_median_novelty=panel_median_novelty,
            target_vs_venue_overall_delta=target_vs_venue_overall_delta,
        )
        rejection_reasons = []
        upgrade_gaps = {}
        if venue_tier in VENUE_TIER_FLOORS:
            rejection_reasons, upgrade_gaps = _tier_deficits(
                venue_tier,
                weighted_dec,
                ratings,
                target_novelty,
                panel_median_novelty,
                target_vs_venue_overall_delta,
            )
        else:
            delta_dec = _to_decimal_or_none(target_vs_venue_overall_delta)
            if delta_dec is not None and delta_dec <= Decimal('-1.0'):
                rejection_reasons.append(f'target_vs_venue_overall_delta_{delta_dec:+.2f}_below_venue_bar')
                need = (-delta_dec).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                upgrade_gaps['overall_vs_venue_panel_median'] = float(str(need))
    return {
        'venue_tier': venue_tier,
        'rejected_below_venue_tier': bool(rejection_reasons),
        'rejection_reasons': rejection_reasons,
        'upgrade_gaps_to_target_tier': upgrade_gaps,
        'recommended_matched_tier': matched_tier,
    }


def _reject_nonfinite(token):
    raise ValueError(f'Non-finite JSON constant not allowed: {token}')


def _build_submission_readiness(weights, ratings, raw, delta, is_idea):
    fatal_dimensions = [
        d for d in DIMENSIONS
        if ratings[d] is not None and ratings[d] <= FATAL_THRESHOLDS[d]
    ]
    fatal_reasons = (['unrun_idea_results'] if is_idea else []) + [
        f'{d}<={FATAL_THRESHOLDS[d]}' for d in fatal_dimensions
    ]
    fatal_gate_triggered = is_idea or bool(fatal_dimensions)

    weak = [
        d for d in DIMENSIONS
        if ratings[d] is not None and (ratings[d] <= FATAL_THRESHOLDS[d] or ratings[d] <= 5)
    ]
    if not weak and raw is not None and not fatal_gate_triggered and raw < TOP_TIER_COMPETITIVE_THRESHOLD:
        non_null_vals = [ratings[d] for d in DIMENSIONS if ratings[d] is not None]
        if non_null_vals:
            min_r = min(non_null_vals)
            weak = [d for d in DIMENSIONS if ratings[d] == min_r and ratings[d] <= 6]
    bottleneck_dimensions = sorted(weak, key=lambda d: (ratings[d], -weights[d], DIMENSIONS.index(d)))

    if raw is None:
        band = 'not_ready_fatal_gate' if fatal_gate_triggered else 'not_comparable_missing_dimension'
        ready_top = False
        ready_findings = False
        if fatal_gate_triggered:
            guidance = (
                'Not ready for submission: fatal gate triggered ('
                + ', '.join(fatal_reasons)
                + '); missing dimension(s) also prevent full scoring.'
            )
        else:
            guidance = 'Cannot assess submission readiness: missing dimension(s) make overall score not_comparable.'
    else:
        if fatal_gate_triggered:
            band = 'not_ready_fatal_gate'
            ready_top = False
            ready_findings = False
            guidance = (
                'Not ready for submission: fatal gate triggered ('
                + ', '.join(fatal_reasons)
                + '). Resolve fatal defects before any archival submission.'
            )
        elif raw < Decimal('5.00'):
            band = 'not_ready_major_rework'
            ready_top = False
            ready_findings = False
            guidance = (
                f'Not ready for submission (weighted {raw} < 5.00): '
                f"major rework needed on {', '.join(bottleneck_dimensions)}."
            )
        elif raw < Decimal('6.00'):
            band = 'workshop_or_preliminary_only'
            ready_top = False
            ready_findings = False
            guidance = (
                f'Workshop/preliminary only (weighted {raw} in 5.00-5.99): '
                f"below archival main-track bar; strengthen {', '.join(bottleneck_dimensions)}."
            )
        elif raw < TOP_TIER_COMPETITIVE_THRESHOLD:
            band = 'borderline_top_tier_competitive_findings_tier_a'
            ready_top = False
            ready_findings = True
            guidance = (
                f'Borderline for Top-Tier Main Track (weighted {raw}, delta {delta:+.2f} vs 6.80): '
                'above all-submissions average (~4.8-5.5) but below typical top-tier accepted median '
                '(~6.8-7.6) with reviewer-variance risk; competitive now for Findings, Tier-A/CCF-B '
                'conferences, strong workshops, or Q1-Q2 journals. '
                f"Strengthen {', '.join(bottleneck_dimensions)} for main track."
            )
        elif raw < Decimal('7.80'):
            band = 'competitive_top_tier_main_track'
            ready_top = True
            ready_findings = True
            guidance = (
                f'Competitive for Top-Tier Main Track (weighted {raw}, delta {delta:+.2f} vs 6.80): '
                'within typical accepted-paper band if CFP fit and hard constraints hold.'
            )
            if bottleneck_dimensions:
                guidance += f" Watch bottleneck: {', '.join(bottleneck_dimensions)}."
        else:
            band = 'strong_top_tier_contender'
            ready_top = True
            ready_findings = True
            guidance = (
                f'Strong Top-Tier contender (weighted {raw} >= 7.80, delta {delta:+.2f} vs 6.80): '
                'upper-tier accepted band; verify CFP fit, hard constraints, and closest-work locators.'
            )

    matched_tier = _recommend_matched_tier(raw, ratings, is_idea) if raw is not None else (
        'none_hold_for_rework' if fatal_gate_triggered else None
    )
    return {
        'band': band,
        'ready_for_top_tier_main_track': ready_top,
        'ready_for_findings_or_tier_a': ready_findings,
        'fatal_gate_triggered': fatal_gate_triggered,
        'fatal_dimensions': fatal_dimensions,
        'fatal_reasons': fatal_reasons,
        'bottleneck_dimensions': bottleneck_dimensions,
        'delta_to_competitive_top_tier': delta,
        'recommended_matched_tier': matched_tier,
        'guidance': guidance,
    }


def score(document):
    if not isinstance(document, dict):
        raise ValueError('Document must be a JSON object')
    for meta_key in ('status', 'object_type'):
        if meta_key in document and document[meta_key] is not None and type(document[meta_key]) is not str:
            raise ValueError(f'{meta_key} must be a string or null')
    is_idea = any(
        isinstance(document.get(k), str) and document[k].strip().lower() == 'idea'
        for k in ('status', 'object_type')
    )
    weights = document['weights']
    ratings = document['ratings']
    if not isinstance(weights, dict) or not isinstance(ratings, dict):
        raise ValueError('Weights and ratings must be JSON objects')
    if set(weights) != set(DIMENSIONS) or set(ratings) != set(DIMENSIONS):
        raise ValueError('Exactly six named dimensions are required')
    if any(type(v) is not int or v < 0 or v > 100 for v in weights.values()):
        raise ValueError('Weights must be integer percentages in 0..100')
    if sum(weights.values()) != 100:
        raise ValueError('Weights must sum to 100')
    if any(v is not None and (type(v) is not int or v < 0 or v > 10) for v in ratings.values()):
        raise ValueError('Ratings must be integers in 0..10 or null')
    if any(v is None for v in ratings.values()):
        return {
            'overall': None,
            'status': 'not_comparable',
            'reason': 'missing dimension',
            'submission_readiness': _build_submission_readiness(weights, ratings, None, None, is_idea),
        }
    with localcontext(BasicContext) as ctx:
        ctx.prec = 28
        raw = sum(Decimal(weights[k]) * Decimal(ratings[k]) for k in DIMENSIONS) / Decimal(100)
        overall = int(raw.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        delta_dec = (raw - TOP_TIER_COMPETITIVE_THRESHOLD).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    delta = float(str(delta_dec))
    return {
        'overall': overall,
        'weighted_unrounded': str(raw),
        'status': 'calculated',
        'warning': 'Arithmetic only; inspect evidence, rubric, confidence and fatal gates separately.',
        'submission_readiness': _build_submission_readiness(weights, ratings, raw, delta, is_idea),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input_json', nargs='?', help='Optional path to JSON input (defaults to stdin)')
    args = parser.parse_args(argv)
    try:
        if args.input_json and args.input_json != '-':
            raw_text = Path(args.input_json).read_text(encoding='utf-8')
            payload = json.loads(raw_text, parse_constant=_reject_nonfinite)
        else:
            payload = json.load(sys.stdin, parse_constant=_reject_nonfinite)
        print(json.dumps(score(payload)))
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
