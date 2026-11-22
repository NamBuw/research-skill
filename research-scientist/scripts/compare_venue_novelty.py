#!/usr/bin/env python3
"""Compare claim-level novelty with a documented same-track accepted-paper panel.

Scores are reviewer judgments supplied with source locators. Arithmetic does
not establish novelty, venue standards, fit, acceptance odds or paper quality.
"""
from __future__ import annotations

import argparse
import copy
import ipaddress
import json
import math
import re
import statistics
import sys
import unicodedata
from datetime import datetime, timezone
from decimal import BasicContext, Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path
from urllib.parse import urlparse

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from compare_scorecards import _snapshot_is_blocked, index_sources_dir, verify_locator
from score_math import (
    DEFAULT_PAPER_WEIGHTS,
    DIMENSIONS as SCORECARD_DIMENSIONS,
    SUBFIELD_PRESETS,
    VENUE_TIER_FLOORS,
    VENUE_TIER_ORDER,
    VENUE_TYPE_PROFILES,
    build_evidence_anchor_table,
    compute_deal_breaker_sensitivity,
    compute_merit_vs_packaging,
    evaluate_subfield_readiness,
    evaluate_venue_profile_checks,
    evaluate_venue_tier_fit,
    resolve_venue_tier,
    resolve_venue_type,
    score as score_math_score,
    simulate_reviewer_panel,
    simulate_what_if_roi,
    translate_to_native_scales,
)
from venue_leads import load_venue_quality_refs, lookup_venue_quality

AXES = ('scope_audience', 'contribution_track', 'evidence_maturity',
        'format_eligibility', 'user_constraints')
HARD_CONSTRAINTS = ('deadline', 'budget', 'eligibility')
VALID_TOPIC_RELATIONS = ('same_topic', 'adjacent_topic', 'different_topic')
DEFAULT_PANEL_WEIGHTS = {
    'importance': 15,
    'novelty': 20,
    'soundness': 20,
    'evidence': 20,
    'transparency': 15,
    'clarity': 10,
}
_DNS_LABEL_RE = re.compile(r'^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$')


def _filled(value):
    return isinstance(value, str) and bool(value.strip())


def _valid_hostname(host, netloc=''):
    if not host:
        return False
    if netloc.startswith('['):
        try:
            return ipaddress.ip_address(host).version == 6
        except ValueError:
            return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    try:
        ascii_host = host.encode('idna').decode('ascii')
    except UnicodeError:
        return False
    if not ascii_host or len(ascii_host) > 253:
        return False
    labels = ascii_host.split('.')
    if any(not lbl or not _DNS_LABEL_RE.match(lbl) for lbl in labels):
        return False
    if labels[-1].isdigit():
        return False
    return True


def _https(value):
    if not _filled(value):
        return False
    if any(ch.isspace() or unicodedata.category(ch) in {'Cc', 'Cf'} for ch in value):
        return False
    try:
        parsed = urlparse(value)
        port = parsed.port
        if parsed.scheme != 'https':
            return False
        netloc = parsed.netloc or ''
        if '@' in netloc or parsed.username is not None or parsed.password is not None:
            return False
        if port is not None and port < 1:
            return False
        return _valid_hostname(parsed.hostname, netloc)
    except ValueError:
        return False


def _time(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.utcoffset() is not None
    except ValueError:
        return False


def _check_rating(item, prefix, errors):
    for field in ('id', 'claim', 'closest_work_id', 'closest_work_locator',
                  'contribution_delta', 'search_manifest', 'score_reason', 'assessment_boundary',
                  'contribution_type'):
        if not _filled(item.get(field)):
            errors.append(f'{prefix}:missing_or_blank:{field}')
    if not _time(item.get('assessed_at_utc')):
        errors.append(f'{prefix}:assessed_at_utc_must_have_timezone')
    if item.get('reading_basis') != 'full_text':
        errors.append(f'{prefix}:full_text_required_for_novelty_comparison')
    for field in ('score', 'low', 'high'):
        value = item.get(field)
        if type(value) is not int or not 0 <= value <= 10:
            errors.append(f'{prefix}:invalid_{field}')
    if all(type(item.get(k)) is int for k in ('score', 'low', 'high')) and not (
            0 <= item['low'] <= item['score'] <= item['high'] <= 10):
        errors.append(f'{prefix}:score_outside_interval')


def _parse_overall_decimal(value, label='target_overall'):
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f'{label} must be a finite number in 0..10, not bool')
    try:
        dec = Decimal(str(value).strip()) if isinstance(value, str) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f'{label} must be a finite number in 0..10') from exc
    if not dec.is_finite() or dec < Decimal('0') or dec > Decimal('10'):
        raise ValueError(f'{label} must be in 0..10')
    return dec


def _band_for_decimal(dec):
    if dec < Decimal('5.00'):
        return 'not_ready_major_rework'
    if dec < Decimal('6.00'):
        return 'workshop_or_preliminary_only'
    if dec < Decimal('6.80'):
        return 'borderline_top_tier_competitive_findings_tier_a'
    if dec < Decimal('7.80'):
        return 'competitive_top_tier_main_track'
    return 'strong_top_tier_contender'


def _extract_panel_overall(item, prefix, errors):
    has_overall = 'overall_score' in item and item['overall_score'] is not None
    has_ratings = 'ratings' in item and item['ratings'] is not None
    overall_dec = None
    if has_overall:
        val = item['overall_score']
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(float(val)) or not (0 <= float(val) <= 10):
            errors.append(f'{prefix}:invalid_overall_score')
        else:
            overall_dec = Decimal(str(val))
    if has_ratings:
        ratings = item['ratings']
        weights = item.get('weights') if item.get('weights') is not None else DEFAULT_PANEL_WEIGHTS
        try:
            sc = score_math_score({'weights': weights, 'ratings': ratings})
            if sc.get('status') != 'calculated':
                errors.append(f'{prefix}:invalid_ratings_missing_dimension')
            elif overall_dec is None:
                overall_dec = Decimal(sc['weighted_unrounded'])
        except (ValueError, KeyError, TypeError):
            errors.append(f'{prefix}:invalid_ratings')
    return overall_dec


def _extract_target_scorecard_info(profile, target, target_overall_override=None):
    weighted_dec = None
    ratings = None
    fatal_gate = False
    fatal_reasons = []
    band = None
    has_explicit_overall = False

    target_is_idea = any(
        isinstance(target.get(k), str) and target[k].strip().lower() == 'idea'
        for k in ('status', 'object_type')
    )
    if target_is_idea:
        fatal_gate = True
        fatal_reasons.append('unrun_idea_results')
    if 'fatal_gate_triggered' in target and target['fatal_gate_triggered'] is not None:
        if type(target['fatal_gate_triggered']) is not bool:
            raise ValueError('target.fatal_gate_triggered must be a boolean')
        if target['fatal_gate_triggered']:
            fatal_gate = True
            fatal_reasons.append('target_fatal_gate')
    if type(target.get('score')) is int and target['score'] <= 2:
        fatal_gate = True
        fatal_reasons.append(f"target_novelty_{target['score']}<=2")

    ts = profile.get('target_scorecard')
    if ts is not None:
        if not isinstance(ts, dict):
            raise ValueError('target_scorecard must be a JSON object')
        if 'weights' in ts and 'ratings' in ts:
            sc = score_math_score(ts)
            ratings = ts['ratings']
            sr = sc['submission_readiness']
            if sc.get('weighted_unrounded') is not None:
                weighted_dec = Decimal(sc['weighted_unrounded'])
                has_explicit_overall = True
            band = sr.get('band')
            if sr.get('fatal_gate_triggered'):
                fatal_gate = True
                for r in sr.get('fatal_reasons') or []:
                    if r not in fatal_reasons:
                        fatal_reasons.append(r)
        elif isinstance(ts.get('submission_readiness'), dict):
            sr = ts['submission_readiness']
            if 'fatal_gate_triggered' in sr and sr['fatal_gate_triggered'] is not None:
                if type(sr['fatal_gate_triggered']) is not bool:
                    raise ValueError('target_scorecard.submission_readiness.fatal_gate_triggered must be bool')
                if sr['fatal_gate_triggered']:
                    fatal_gate = True
                    for r in sr.get('fatal_reasons') or ['target_scorecard_fatal_gate']:
                        if r not in fatal_reasons:
                            fatal_reasons.append(r)
            band = sr.get('band')
            if ts.get('weighted_unrounded') is not None:
                weighted_dec = _parse_overall_decimal(ts['weighted_unrounded'], 'target_scorecard.weighted_unrounded')
                has_explicit_overall = True
        elif ts.get('weighted_unrounded') is not None:
            weighted_dec = _parse_overall_decimal(ts['weighted_unrounded'], 'target_scorecard.weighted_unrounded')
            has_explicit_overall = True

    if 'submission_readiness' in profile and profile['submission_readiness'] is not None:
        sr = profile['submission_readiness']
        if not isinstance(sr, dict):
            raise ValueError('submission_readiness must be a JSON object')
        if 'fatal_gate_triggered' in sr and sr['fatal_gate_triggered'] is not None:
            if type(sr['fatal_gate_triggered']) is not bool:
                raise ValueError('submission_readiness.fatal_gate_triggered must be bool')
            if sr['fatal_gate_triggered']:
                fatal_gate = True
                for r in sr.get('fatal_reasons') or ['submission_readiness_fatal_gate']:
                    if r not in fatal_reasons:
                        fatal_reasons.append(r)
        if band is None:
            band = sr.get('band')
        if weighted_dec is None and sr.get('weighted_unrounded') is not None:
            weighted_dec = _parse_overall_decimal(sr['weighted_unrounded'], 'submission_readiness.weighted_unrounded')
            has_explicit_overall = True

    if weighted_dec is None:
        for key in ('weighted_unrounded', 'target_overall_score'):
            if key in profile and profile[key] is not None:
                weighted_dec = _parse_overall_decimal(profile[key], key)
                has_explicit_overall = True
                break
    if weighted_dec is None and target.get('ratings') is not None:
        sc = score_math_score({'weights': target.get('weights') or DEFAULT_PANEL_WEIGHTS, 'ratings': target['ratings']})
        ratings = target['ratings']
        if sc.get('weighted_unrounded') is not None:
            weighted_dec = Decimal(sc['weighted_unrounded'])
            has_explicit_overall = True
        if sc['submission_readiness'].get('fatal_gate_triggered'):
            fatal_gate = True
            for r in sc['submission_readiness'].get('fatal_reasons') or []:
                if r not in fatal_reasons:
                    fatal_reasons.append(r)
    if weighted_dec is None and target.get('overall_score') is not None:
        weighted_dec = _parse_overall_decimal(target['overall_score'], 'target.overall_score')
        has_explicit_overall = True

    if target_overall_override is not None:
        weighted_dec = _parse_overall_decimal(target_overall_override, '--target-overall')
        has_explicit_overall = True

    if 'fatal_gate_triggered' in profile and profile['fatal_gate_triggered'] is not None:
        if type(profile['fatal_gate_triggered']) is not bool:
            raise ValueError('fatal_gate_triggered must be a boolean')
        if profile['fatal_gate_triggered']:
            fatal_gate = True
            if 'portfolio_fatal_gate_triggered' not in fatal_reasons:
                fatal_reasons.append('portfolio_fatal_gate_triggered')

    if band is None:
        if fatal_gate:
            band = 'not_ready_fatal_gate'
        elif weighted_dec is not None:
            band = _band_for_decimal(weighted_dec)

    return {
        'weighted_dec': weighted_dec,
        'weighted_unrounded': str(weighted_dec) if weighted_dec is not None else None,
        'ratings': ratings,
        'fatal_gate_triggered': fatal_gate,
        'fatal_reasons': fatal_reasons,
        'band': band,
        'has_explicit_overall': has_explicit_overall,
        'target_novelty_score': target.get('score') if type(target.get('score')) is int else None,
    }


def _build_venue_contribution_bar(panel, panel_overall_decs, target_overall_dec, comparison):
    if comparison is None:
        return None
    same_count = 0
    adj_count = 0
    diff_count = 0
    unspec_count = 0
    for item in panel:
        if not isinstance(item, dict):
            continue
        rel = item.get('topic_relation')
        if rel == 'same_topic':
            same_count += 1
        elif rel == 'adjacent_topic':
            adj_count += 1
        elif rel == 'different_topic':
            diff_count += 1
        else:
            unspec_count += 1
    cross_count = adj_count + diff_count

    panel_med_overall = None
    delta_overall = None
    target_overall_float = None
    with localcontext(BasicContext) as ctx:
        ctx.prec = 28
        if panel_overall_decs:
            med_dec = statistics.median(panel_overall_decs)
            med_q = med_dec.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            panel_med_overall = float(str(med_q))
            if target_overall_dec is not None:
                delta_dec = (target_overall_dec - med_dec).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                delta_overall = float(str(delta_dec))
        if target_overall_dec is not None:
            t_q = target_overall_dec.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            target_overall_float = float(str(t_q))

    if panel_med_overall is None:
        guidance = (
            'Accepted panel entries lack overall_score/ratings; supply overall_score or 6-dim ratings '
            'to calibrate the cross-topic venue contribution bar.'
        )
    elif delta_overall is None:
        guidance = (
            f'Cross-topic venue bar median overall is {panel_med_overall:.2f}/10 '
            f'({cross_count} cross-topic papers); supply target overall/scorecard to compute delta.'
        )
    else:
        guidance = (
            f'Target overall ({target_overall_float:.2f}/10) vs venue accepted panel median '
            f'({panel_med_overall:.2f}/10 across {len(panel_overall_decs)} papers, {cross_count} cross-topic): '
            f'delta {delta_overall:+.2f}.'
        )
    return {
        'panel_median_overall': panel_med_overall,
        'panel_overall_count': len(panel_overall_decs),
        'panel_median_novelty': comparison['accepted_panel_median_score'],
        'same_topic_count': same_count,
        'adjacent_topic_count': adj_count,
        'different_topic_count': diff_count,
        'cross_topic_count': cross_count,
        'unspecified_topic_count': unspec_count,
        'target_overall_score': target_overall_float,
        'target_vs_venue_overall_delta': delta_overall,
        'guidance': guidance,
    }


def _build_venue_submission_readiness(
    target,
    comparison,
    fit_score,
    axis_map,
    constraint_map,
    errors,
    *,
    venue_tier=None,
    venue_type=None,
    target_info=None,
    contribution_bar=None,
    has_tier_context=False,
):
    target_score = target.get('score') if type(target.get('score')) is int else None
    target_low = target.get('low') if type(target.get('low')) is int else None
    target_high = target.get('high') if type(target.get('high')) is int else None
    target_interval = [target_low, target_high] if (target_low is not None and target_high is not None) else None
    target_is_idea = any(
        isinstance(target.get(k), str) and target[k].strip().lower() == 'idea'
        for k in ('status', 'object_type')
    )
    if target_info and target_info.get('fatal_gate_triggered'):
        target_is_idea = target_is_idea or ('unrun_idea_results' in (target_info.get('fatal_reasons') or []))

    if comparison is not None and target_score is not None and target_low is not None and target_high is not None:
        panel_median = comparison['accepted_panel_median_score']
        delta_vs_panel_median = round(float(target_score - panel_median), 2)
        n_higher = len(comparison['target_definitely_higher_than_ids'])
        n_lower = len(comparison['target_definitely_lower_than_ids'])
        n_overlap = len(comparison['overlapping_intervals_with_ids'])
        panel_size = comparison['accepted_panel_size']
        if target_low > panel_median:
            standing = 'above_panel_median'
        elif target_high < panel_median:
            standing = 'below_panel_median'
        else:
            standing = 'at_or_overlapping_panel_median'
        interval_dominance = {
            'strictly_higher_than_count': n_higher,
            'strictly_lower_than_count': n_lower,
            'overlapping_count': n_overlap,
            'panel_size': panel_size,
            'target_interval_above_panel_median': target_low > panel_median,
            'target_interval_below_panel_median': target_high < panel_median,
        }
    else:
        panel_median = None
        delta_vs_panel_median = None
        standing = 'unavailable'
        interval_dominance = None

    constraints_status = {
        c: (constraint_map[c].get('status') if c in constraint_map else 'missing')
        for c in HARD_CONSTRAINTS
    }
    failed_constraints = [c for c in HARD_CONSTRAINTS if constraints_status[c] == 'failed']
    unverified_constraints = [c for c in HARD_CONSTRAINTS if constraints_status[c] in ('unverified', 'missing')]
    hard_constraints_met = (
        not failed_constraints
        and not unverified_constraints
        and not any(e.startswith('hard_constraints:') for e in errors)
    )
    weak_fit_axes = [
        ax for ax in AXES
        if ax in axis_map and type(axis_map[ax].get('score')) is int and axis_map[ax]['score'] < 2
    ]

    tier_fit = evaluate_venue_tier_fit(
        venue_tier,
        weighted_unrounded=(target_info or {}).get('weighted_dec'),
        ratings=(target_info or {}).get('ratings'),
        is_idea=target_is_idea,
        target_novelty=target_score,
        panel_median_novelty=panel_median,
        target_vs_venue_overall_delta=(contribution_bar or {}).get('target_vs_venue_overall_delta'),
        venue_type=venue_type,
    )
    tier_rejected = tier_fit['rejected_below_venue_tier']

    if errors:
        verdict = 'not_ready_invalid_evidence'
        ready_to_submit = False
        guidance = f"Blocked by {len(errors)} structural/locator error(s); resolve missing full-text evidence or CFP errors first."
    elif target_is_idea or (target_score is not None and target_score <= 2) or (target_info and target_info.get('fatal_gate_triggered')):
        verdict = 'not_ready_fatal_gate'
        ready_to_submit = False
        reasons = (target_info or {}).get('fatal_reasons') or []
        reason = ', '.join(reasons) if reasons else (
            'unrun idea stage' if target_is_idea else f'target novelty {target_score}/10 <= 2'
        )
        guidance = f'Not ready for archival submission: fatal gate ({reason}).'
    elif failed_constraints:
        verdict = 'do_not_submit_constraint_failed'
        ready_to_submit = False
        guidance = f"Do not submit to this venue: failed hard constraint(s) ({', '.join(failed_constraints)})."
    elif fit_score is None:
        verdict = 'blocked_unverified_fit_or_constraints'
        ready_to_submit = False
        blockers = unverified_constraints or ['stale_or_unverified_cfp']
        guidance = f"Submission blocked until CFP freshness and hard constraints are verified ({', '.join(blockers)})."
    elif comparison is None:
        if tier_rejected:
            verdict = 'rejected_below_venue_tier'
            ready_to_submit = False
            matched = tier_fit.get('recommended_matched_tier') or 'workshop_or_preliminary'
            guidance = (
                f"Rejected for {venue_tier or 'target'} tier: paper contribution falls below venue floor "
                f"({', '.join(tier_fit['rejection_reasons'][:3])}). Target matched tier: {matched}."
            )
        else:
            verdict = 'provisional_panel_withheld'
            ready_to_submit = False
            guidance = 'Accepted-panel novelty comparison withheld (< 5 recent same-track papers); complete panel before judging venue standing.'
    elif tier_rejected:
        verdict = 'rejected_below_venue_tier'
        ready_to_submit = False
        matched = tier_fit.get('recommended_matched_tier') or 'workshop_or_preliminary'
        guidance = (
            f"Rejected for {venue_tier or 'target'} tier (not viable stretch): contribution falls below venue floor "
            f"({', '.join(tier_fit['rejection_reasons'][:3])}). Target matched tier: {matched}."
        )
    elif fit_score < 6:
        verdict = 'not_ready_weak_venue_fit'
        ready_to_submit = False
        guidance = f"Weak venue fit ({fit_score}/10 < 6): address weak fit axes ({', '.join(weak_fit_axes) or 'fit_axes'}) or choose a better-aligned venue."
    elif standing == 'below_panel_median':
        verdict = 'below_panel_median_strengthen_or_retarget'
        ready_to_submit = False
        guidance = (
            f'Target novelty ({target_score}/10, interval {target_interval}) sits below same-track accepted panel median '
            f'({panel_median}/10, delta {delta_vs_panel_median:+.2f}); strengthen core contribution or target Findings / Tier-A / workshop venue.'
        )
    elif target_score is not None and target_score <= 4:
        verdict = 'below_panel_median_strengthen_or_retarget'
        ready_to_submit = False
        guidance = (
            f'Target novelty is too weak ({target_score}/10 <= 4, interval {target_interval}, panel median '
            f'{panel_median}/10, delta {delta_vs_panel_median:+.2f}); strengthen core contribution or target a preliminary/workshop venue.'
        )
    elif standing == 'at_or_overlapping_panel_median':
        if fit_score >= 7:
            verdict = 'conditional_competitive_borderline_panel_overlap'
            ready_to_submit = True
            guidance = (
                f'Target novelty ({target_score}/10, interval {target_interval}) overlaps accepted panel median '
                f'({panel_median}/10) with solid venue fit ({fit_score}/10); competitive with reviewer-variance risk'
                + (f" — tighten weak fit axes ({', '.join(weak_fit_axes)})." if weak_fit_axes else '.')
            )
        else:
            verdict = 'borderline_moderate_fit_and_panel_overlap'
            ready_to_submit = False
            guidance = (
                f'Borderline standing: target overlaps panel median ({panel_median}/10) with moderate venue fit ({fit_score}/10); '
                f"strengthen weak fit axes ({', '.join(weak_fit_axes)}) before submitting."
            )
    else:
        if fit_score >= 7:
            verdict = 'ready_strong_panel_standing_and_fit'
            ready_to_submit = True
            guidance = (
                f'Ready to submit: target novelty ({target_score}/10, interval {target_interval}) exceeds accepted panel median '
                f'({panel_median}/10) and venue fit is strong ({fit_score}/10) with hard constraints met.'
            )
        else:
            verdict = 'conditional_above_panel_moderate_fit'
            ready_to_submit = True
            guidance = (
                f'Conditionally ready: target exceeds accepted panel median ({panel_median}/10) but venue fit is moderate '
                f"({fit_score}/10); tighten weak fit axes ({', '.join(weak_fit_axes)})."
            )

    sr_out = {
        'verdict': verdict,
        'ready_to_submit': ready_to_submit,
        'standing_vs_accepted_panel': standing,
        'target_novelty_score': target_score,
        'target_interval': target_interval,
        'accepted_panel_median_score': panel_median,
        'delta_vs_panel_median': delta_vs_panel_median,
        'interval_dominance': interval_dominance,
        'fit_score_out_of_10': fit_score,
        'weak_fit_axes': weak_fit_axes,
        'hard_constraints_met': hard_constraints_met,
        'hard_constraints': constraints_status,
        'failed_constraints': failed_constraints,
        'unverified_constraints': unverified_constraints,
        'guidance': guidance,
    }
    if tier_rejected or has_tier_context:
        sr_out['venue_tier'] = venue_tier
        sr_out['tier_rejection_reasons'] = tier_fit['rejection_reasons']
        sr_out['upgrade_gaps_to_target_tier'] = tier_fit['upgrade_gaps_to_target_tier']
        sr_out['recommended_matched_tier'] = tier_fit['recommended_matched_tier']
    return sr_out


def _check_single_venue(
    profile,
    as_of=None,
    sources_dir=None,
    quality_refs_dir=None,
    *,
    source_index=None,
    refs=None,
    portfolio_optional_panel=False,
    target_overall_override=None,
    venue_type=None,
    subfield_preset=None,
    what_if=False,
):
    errors, warnings = [], []
    as_of = as_of or datetime.now(timezone.utc)
    if refs is None:
        refs = load_venue_quality_refs(quality_refs_dir)

    venue = profile.get('venue')
    if not isinstance(venue, dict):
        errors.append('venue:must_be_object')
        venue = {}
    for field in ('name', 'edition', 'track'):
        if not _filled(venue.get(field)):
            errors.append(f'venue:missing_or_blank:{field}')
    if not _https(venue.get('official_cfp_url')):
        errors.append('venue:official_cfp_url_must_be_https')
    venue_fresh = False
    if not _time(venue.get('checked_at_utc')):
        errors.append('venue:checked_at_utc_must_have_timezone')
    else:
        checked = datetime.fromisoformat(venue['checked_at_utc'].replace('Z', '+00:00'))
        max_age = venue.get('max_source_age_days', 14)
        if type(max_age) is not int or max_age < 0:
            errors.append('venue:max_source_age_days_invalid')
        else:
            age = (as_of - checked).total_seconds() / 86400
            venue_fresh = 0 <= age <= max_age
            if not venue_fresh:
                warnings.append('venue:cfp_source_stale_or_future;_fit_score_withheld')

    for t_field in ('submission_deadline_utc', 'notification_date_utc'):
        if t_field in venue and venue[t_field] is not None and not _time(venue[t_field]):
            errors.append(f'venue:invalid_{t_field}')
    if 'simultaneous_submission_allowed' in venue and venue['simultaneous_submission_allowed'] is not None:
        if type(venue['simultaneous_submission_allowed']) is not bool:
            errors.append('venue:invalid_simultaneous_submission_allowed')

    venue_quality_context = lookup_venue_quality(venue.get('name'), refs) if _filled(venue.get('name')) else None

    target = profile.get('target')
    if not isinstance(target, dict):
        errors.append('target:must_be_object')
        target = {}
    _check_rating(target, 'target', errors)
    if _time(target.get('assessed_at_utc')) and datetime.fromisoformat(target['assessed_at_utc'].replace('Z', '+00:00')) > as_of:
        errors.append('target:assessment_time_in_future')

    target_info = _extract_target_scorecard_info(profile, target, target_overall_override=target_overall_override)

    has_panel_data = (
        isinstance(profile.get('accepted_panel'), list) and len(profile['accepted_panel']) > 0
    ) or ('panel_selection' in profile and profile['panel_selection'] is not None)
    skip_panel_validation = portfolio_optional_panel and not has_panel_data

    panel = []
    panel_overall_decs = []
    if skip_panel_validation:
        warnings.append('accepted_panel:omitted_in_portfolio_mode; comparison_withheld')
    else:
        selection = profile.get('panel_selection')
        if not isinstance(selection, dict):
            errors.append('panel_selection:must_be_object')
            selection = {}
        for field in ('search_manifest', 'inclusion_rule', 'exclusion_log', 'date_window',
                      'rubric_version', 'calibration_notes', 'selection_bias'):
            if not _filled(selection.get(field)):
                errors.append(f'panel_selection:missing_or_blank:{field}')
        screened = selection.get('screened_count')
        if type(screened) is not int or screened < 0:
            errors.append('panel_selection:invalid_screened_count')

        panel = profile.get('accepted_panel')
        if not isinstance(panel, list):
            errors.append('accepted_panel:must_be_list')
            panel = []
        if len(panel) < 5:
            warnings.append('accepted_panel:fewer_than_five_comparable_papers; distribution_not_reported')
        if type(screened) is int and screened < len(panel):
            errors.append('panel_selection:screened_count_less_than_included')
        ids = set()
        for index, item in enumerate(panel):
            prefix = f'accepted_panel:{index}'
            if not isinstance(item, dict):
                errors.append(f'{prefix}:must_be_object')
                continue
            _check_rating(item, prefix, errors)
            if 'topic_relation' in item and item['topic_relation'] is not None:
                if item['topic_relation'] not in VALID_TOPIC_RELATIONS:
                    errors.append(f'{prefix}:invalid_topic_relation')
            ov_dec = _extract_panel_overall(item, prefix, errors)
            if ov_dec is not None:
                panel_overall_decs.append(ov_dec)
            if _filled(item.get('contribution_type')) and _filled(target.get('contribution_type')) and \
                    item['contribution_type'] != target['contribution_type']:
                errors.append(f'{prefix}:contribution_type_mismatch')
            if _time(item.get('assessed_at_utc')) and datetime.fromisoformat(item['assessed_at_utc'].replace('Z', '+00:00')) > as_of:
                errors.append(f'{prefix}:assessment_time_in_future')
            if not _https(item.get('official_acceptance_url')):
                errors.append(f'{prefix}:official_acceptance_url_must_be_https')
            if item.get('track') != venue.get('track'):
                errors.append(f'{prefix}:track_mismatch')
            if type(item.get('year')) is not int or not 1900 <= item['year'] <= as_of.year:
                errors.append(f'{prefix}:invalid_year')
            if _filled(item.get('id')) and item['id'] in ids:
                errors.append(f'{prefix}:duplicate_id')
            if _filled(item.get('id')):
                ids.add(item['id'])

    axes = profile.get('fit_axes')
    if not isinstance(axes, list):
        errors.append('fit_axes:must_be_list')
        axes = []
    axis_map = {}
    for index, item in enumerate(axes):
        prefix = f'fit_axes:{index}'
        if not isinstance(item, dict):
            errors.append(f'{prefix}:must_be_object')
            continue
        name = item.get('name')
        if not isinstance(name, str) or name not in AXES or name in axis_map:
            errors.append(f'{prefix}:invalid_or_duplicate_axis')
            continue
        axis_map[name] = item
        if type(item.get('score')) is not int or not 0 <= item['score'] <= 2:
            errors.append(f'{prefix}:score_must_be_0_to_2')
        if not _https(item.get('source_url')) or not _filled(item.get('locator')) or not _filled(item.get('reason')):
            errors.append(f'{prefix}:source_locator_and_reason_required')
    if set(axis_map) != set(AXES):
        errors.append('fit_axes:all_five_axes_required')

    constraints = profile.get('hard_constraints')
    if not isinstance(constraints, list):
        errors.append('hard_constraints:must_be_list')
        constraints = []
    constraint_map = {}
    for index, item in enumerate(constraints):
        prefix = f'hard_constraints:{index}'
        if not isinstance(item, dict):
            errors.append(f'{prefix}:must_be_object')
            continue
        name = item.get('name')
        if not isinstance(name, str) or name not in HARD_CONSTRAINTS or name in constraint_map:
            errors.append(f'{prefix}:invalid_or_duplicate_constraint')
            continue
        constraint_map[name] = item
        if item.get('status') not in ('met', 'failed', 'unverified'):
            errors.append(f'{prefix}:invalid_status')
        if not _filled(item.get('reason')):
            errors.append(f'{prefix}:reason_required')
        if item.get('status') in ('met', 'failed') and not _https(item.get('source_url')):
            errors.append(f'{prefix}:verified_status_needs_source_url')
    if set(constraint_map) != set(HARD_CONSTRAINTS):
        errors.append('hard_constraints:deadline_budget_eligibility_required')

    locator_verification = None
    if source_index is not None or sources_dir is not None:
        if source_index is None:
            source_index = index_sources_dir(sources_dir)
        checked = 0
        verified = 0
        failed = 0

        if _filled(target.get('closest_work_locator')):
            checked += 1
            ok, reason = verify_locator(
                target['closest_work_locator'],
                source_index,
                default_source_ids=(target.get('closest_work_id'), target.get('id')),
                extra_quotes=(target.get('closest_work_quote'), target.get('quote')),
            )
            if ok:
                verified += 1
            else:
                failed += 1
                errors.append(f'target:closest_work_locator_unverified:{reason}')

        for index, item in enumerate(panel):
            if not isinstance(item, dict) or not _filled(item.get('closest_work_locator')):
                continue
            checked += 1
            ok, reason = verify_locator(
                item['closest_work_locator'],
                source_index,
                default_source_ids=(item.get('closest_work_id'), item.get('id')),
                extra_quotes=(item.get('closest_work_quote'), item.get('quote')),
            )
            if ok:
                verified += 1
            else:
                failed += 1
                errors.append(f'accepted_panel:{index}:closest_work_locator_unverified:{reason}')

        for index, item in enumerate(axes):
            if not isinstance(item, dict) or not _filled(item.get('locator')):
                continue
            checked += 1
            ok, reason = verify_locator(
                item['locator'],
                source_index,
                source_url=item.get('source_url'),
                extra_quotes=(item.get('quote'),),
                require_url_snapshot=True,
            )
            if ok:
                verified += 1
            else:
                failed += 1
                errors.append(f'fit_axes:{index}:locator_unverified:{reason}')

        for index, item in enumerate(constraints):
            if not isinstance(item, dict) or item.get('status') not in ('met', 'failed'):
                continue
            url = item.get('source_url')
            if not _https(url):
                continue
            if url not in source_index['venue_snapshots']:
                errors.append(f'hard_constraints:{index}:source_snapshot_missing')
            elif _snapshot_is_blocked(source_index['venue_snapshots'][url]):
                errors.append(f'hard_constraints:{index}:unverified_or_stale_venue_snapshot')

        locator_verification = {
            'sources_dir': str(source_index['root']),
            'sources_indexed': source_index['sources_indexed'],
            'skipped_files': source_index['skipped_files'],
            'checked': checked,
            'verified': verified,
            'failed': failed,
        }

    recent_panel_count = sum(type(item.get('year')) is int and item['year'] >= as_of.year - 3
                             for item in panel if isinstance(item, dict))
    if not skip_panel_validation and recent_panel_count < 5:
        warnings.append('accepted_panel:fewer_than_five_recent_same_track_papers; comparison_withheld')
    score_errors = any(item.startswith(('target:', 'accepted_panel:', 'venue:', 'panel_selection:')) for item in errors)
    comparison = None
    if not skip_panel_validation and not score_errors and len(panel) >= 5 and recent_panel_count >= 5:
        scores = [item['score'] for item in panel]
        definitely_higher = [item['id'] for item in panel if target['low'] > item['high']]
        definitely_lower = [item['id'] for item in panel if target['high'] < item['low']]
        overlaps = [item['id'] for item in panel if item['id'] not in definitely_higher + definitely_lower]
        comparison = {'target_novelty_score': target['score'],
                      'target_interval': [target['low'], target['high']],
                      'accepted_panel_size': len(panel),
                      'accepted_panel_median_score': statistics.median(scores),
                      'accepted_panel_score_range': [min(scores), max(scores)],
                      'target_definitely_higher_than_ids': definitely_higher,
                      'target_definitely_lower_than_ids': definitely_lower,
                      'overlapping_intervals_with_ids': overlaps,
                      'interpretation': 'Descriptive scores for a selected same-track panel; no venue novelty threshold or acceptance probability.'}

    contribution_bar = _build_venue_contribution_bar(
        panel, panel_overall_decs, target_info['weighted_dec'], comparison
    )

    hard_statuses = [item.get('status') for item in constraint_map.values()]
    fit_score = None
    if venue_fresh and not any(item.startswith(('fit_axes:', 'hard_constraints:', 'venue:')) for item in errors) and len(axis_map) == 5 and len(constraint_map) == 3:
        if all(status == 'met' for status in hard_statuses):
            fit_score = sum(item['score'] for item in axis_map.values())
        elif 'failed' in hard_statuses:
            warnings.append('venue:hard_constraint_conflict; do_not_recommend_as_feasible')
        else:
            warnings.append('venue:hard_constraint_unverified;_fit_score_withheld')

    tier_exp = profile.get('tier_expectation') or profile.get('venue_tier') or venue.get('tier_expectation')
    q_tier = (venue_quality_context or {}).get('quality_tier', 'Unknown')
    eff_vtype = resolve_venue_type(
        venue_type if venue_type is not None else (profile.get('venue_type') or profile.get('venue_profile') or venue.get('venue_type'))
    )
    venue_profile_eval = evaluate_venue_profile_checks(eff_vtype, profile) if eff_vtype is not None else None
    eff_preset = subfield_preset if subfield_preset is not None else profile.get('subfield_preset')
    subfield_readiness = (
        evaluate_subfield_readiness(eff_preset, profile.get('subfield_checks'))
        if eff_preset is not None
        else None
    )

    checks_fatal = bool(venue_profile_eval and venue_profile_eval.get('checks_gate_failed'))
    eff_panel = (
        profile.get('reviewer_panel')
        if profile.get('reviewer_panel') is not None
        else (profile.get('target_scorecard') or {}).get('reviewer_panel')
    )
    t_weights = (
        (profile.get('target_scorecard') or {}).get('weights')
        or target.get('weights')
        or (VENUE_TYPE_PROFILES[eff_vtype]['weights'] if eff_vtype in VENUE_TYPE_PROFILES else DEFAULT_PANEL_WEIGHTS)
    )
    panel_analysis = (
        simulate_reviewer_panel(
            eff_panel,
            t_weights,
            aggregate_fatal_gate=bool(target_info['fatal_gate_triggered'] or checks_fatal),
        )
        if eff_panel is not None
        else None
    )

    venue_tier = resolve_venue_tier(venue.get('name'), venue.get('track'), q_tier, tier_exp)
    if venue_tier is None and venue_profile_eval is not None:
        venue_tier = venue_profile_eval['venue_tier']
    has_tier_context = bool(
        target_info['has_explicit_overall']
        or (isinstance(tier_exp, str) and tier_exp.strip())
        or (contribution_bar is not None and contribution_bar.get('panel_median_overall') is not None)
    )

    submission_readiness = _build_venue_submission_readiness(
        target,
        comparison,
        fit_score,
        axis_map,
        constraint_map,
        errors,
        venue_tier=venue_tier,
        venue_type=eff_vtype,
        target_info=target_info,
        contribution_bar=contribution_bar,
        has_tier_context=has_tier_context,
    )
    if checks_fatal and not errors:
        submission_readiness['ready_to_submit'] = False
        submission_readiness['verdict'] = 'not_ready_fatal_gate'
        check_parts = []
        if venue_profile_eval.get('failed_checks'):
            check_parts.append(f"failed: {', '.join(venue_profile_eval['failed_checks'])}")
        if eff_vtype == 'dataset_benchmark' and venue_profile_eval.get('missing_checks'):
            check_parts.append(f"unverified: {', '.join(venue_profile_eval['missing_checks'])}")
        detail = '; '.join(check_parts) or 'required checks not verified'
        submission_readiness['guidance'] = (
            f"Blocked by {eff_vtype} profile gate ({detail}). "
            + submission_readiness['guidance']
        )
    if panel_analysis and panel_analysis.get('fatal_defect_blocks_averaging') and not errors:
        submission_readiness['ready_to_submit'] = False
        submission_readiness['verdict'] = 'not_ready_fatal_gate'
        submission_readiness['guidance'] = (
            f"Blocked by reviewer panel fatal defect ({panel_analysis.get('meta_review_verdict')}): "
            + submission_readiness['guidance']
        )

    evidence_anchor_table = None
    if isinstance(profile.get('evidence_anchors'), list) and profile['evidence_anchors']:
        evidence_anchor_table = build_evidence_anchor_table(target, profile['evidence_anchors'])
    else:
        anchor_items = [
            item for item in panel
            if isinstance(item, dict)
            and (isinstance(item.get('evidence_profile'), dict) or isinstance(item.get('evidence_anchors'), dict))
        ]
        if len(anchor_items) >= 2:
            evidence_anchor_table = build_evidence_anchor_table(target, anchor_items[:3])

    overall_fatal_gate = bool(
        target_info['fatal_gate_triggered']
        or checks_fatal
        or (panel_analysis and panel_analysis.get('fatal_defect_blocks_averaging'))
    )
    non_rating_fatal = bool(
        checks_fatal
        or (panel_analysis and panel_analysis.get('panel_verified_fatal_defect'))
    )

    native_venue_scales = None
    if target_info['weighted_dec'] is not None:
        native_venue_scales = translate_to_native_scales(
            target_info['weighted_dec'],
            fatal_gate_triggered=overall_fatal_gate,
            ratings=target_info['ratings'],
            reviewer_confidence=profile.get('reviewer_confidence') if profile.get('reviewer_confidence') is not None else target.get('confidence'),
            reviewer_panel=eff_panel,
        )

    merit_vs_packaging = None
    deal_breaker_sensitivity = None
    what_if_roi = None
    if isinstance(target_info['ratings'], dict):
        merit_vs_packaging = compute_merit_vs_packaging(t_weights, target_info['ratings'])
        deal_breaker_sensitivity = compute_deal_breaker_sensitivity(
            t_weights,
            target_info['ratings'],
            venue_tier=venue_tier,
            venue_type=eff_vtype,
            reviewer_panel=eff_panel,
            is_idea=(target_info['fatal_gate_triggered'] and 'unrun_idea_results' in target_info['fatal_reasons']),
        )
        if what_if:
            what_if_roi = simulate_what_if_roi(
                t_weights,
                target_info['ratings'],
                venue_tier=venue_tier,
                venue_type=eff_vtype,
                is_idea=(target_info['fatal_gate_triggered'] and 'unrun_idea_results' in target_info['fatal_reasons']),
                non_rating_fatal_gate=non_rating_fatal,
            )

    out = {
        'status': 'invalid' if errors else 'structurally_checked',
        'errors': errors,
        'warnings': warnings,
        'fit_score_out_of_10': fit_score,
        'novelty_comparison': comparison,
        'venue_contribution_bar': contribution_bar,
        'venue_quality_context': venue_quality_context,
        'submission_readiness': submission_readiness,
        'disclaimer': (
            'All novelty and fit ratings are supplied reviewer judgments. Verify original papers, '
            'closest work, official accepted-paper/CFP records, fees and constraints. A venue has no '
            'intrinsic novelty score; a selected panel is not an acceptance threshold or probability. '
            'Advisory venue_quality_context tiers (S/A/B/C/Unknown) reflect local reference lookup only '
            'and never contribute to fit_score_out_of_10 or novelty_comparison.'
        ),
    }
    if eff_vtype is not None:
        out['venue_type'] = eff_vtype
        out['venue_type_profile'] = venue_profile_eval
    if subfield_readiness is not None:
        out['subfield_preset'] = eff_preset.strip().lower()
        out['subfield_readiness'] = subfield_readiness
    if evidence_anchor_table is not None:
        out['evidence_anchor_table'] = evidence_anchor_table
    if native_venue_scales is not None:
        out['native_venue_scales'] = native_venue_scales
    if merit_vs_packaging is not None:
        out['merit_vs_packaging'] = merit_vs_packaging
    if deal_breaker_sensitivity is not None:
        out['deal_breaker_sensitivity'] = deal_breaker_sensitivity
    if what_if_roi is not None:
        out['what_if_roi'] = what_if_roi
    if panel_analysis is not None:
        out['reviewer_panel_analysis'] = panel_analysis
    if locator_verification is not None:
        out['locator_verification'] = locator_verification
    return out


def _check_portfolio(
    profile,
    as_of=None,
    sources_dir=None,
    quality_refs_dir=None,
    *,
    require_panels=False,
    min_venues=None,
    target_overall=None,
    venue_type=None,
    subfield_preset=None,
    what_if=False,
):
    as_of = as_of or datetime.now(timezone.utc)
    eff_require_panels = require_panels
    if not eff_require_panels and 'require_panels' in profile and profile['require_panels'] is not None:
        if type(profile['require_panels']) is not bool:
            raise ValueError('require_panels must be a boolean')
        eff_require_panels = profile['require_panels']

    raw_min = min_venues if min_venues is not None else profile.get('min_venues')
    if raw_min is not None:
        if type(raw_min) is not int or raw_min < 1:
            raise ValueError('min_venues must be an integer >= 1')
        eff_min_venues = raw_min
    else:
        eff_min_venues = 3

    top_errors = []
    top_warnings = []

    refs = load_venue_quality_refs(quality_refs_dir)
    source_index = index_sources_dir(sources_dir) if sources_dir is not None else None

    top_target = profile.get('target')
    if not isinstance(top_target, dict):
        top_errors.append('target:must_be_object')
        top_target = {}
    else:
        _check_rating(top_target, 'target', top_errors)
        if _time(top_target.get('assessed_at_utc')) and datetime.fromisoformat(top_target['assessed_at_utc'].replace('Z', '+00:00')) > as_of:
            top_errors.append('target:assessment_time_in_future')

    target_info = _extract_target_scorecard_info(profile, top_target, target_overall_override=target_overall)
    if top_target and 'closest_work_locator' in top_target and source_index is not None and _filled(top_target.get('closest_work_locator')):
        ok_cw, reason_cw = verify_locator(
            top_target['closest_work_locator'],
            source_index,
            default_source_ids=(top_target.get('closest_work_id'), top_target.get('id')),
            extra_quotes=(top_target.get('closest_work_quote'), top_target.get('quote')),
        )
        if not ok_cw:
            top_errors.append(f'target:closest_work_locator_unverified:{reason_cw}')

    eff_vtype = resolve_venue_type(
        venue_type if venue_type is not None else (profile.get('venue_type') or profile.get('venue_profile'))
    )
    top_vtype_prof = evaluate_venue_profile_checks(eff_vtype, profile) if eff_vtype is not None else None
    top_checks_fatal = bool(top_vtype_prof and top_vtype_prof.get('checks_gate_failed'))
    top_panel = (
        profile.get('reviewer_panel')
        if profile.get('reviewer_panel') is not None
        else (profile.get('target_scorecard') or {}).get('reviewer_panel')
    )
    top_panel_analysis = None
    if top_panel is not None:
        t_weights = (
            (profile.get('target_scorecard') or {}).get('weights')
            or top_target.get('weights')
            or (VENUE_TYPE_PROFILES[eff_vtype]['weights'] if eff_vtype in VENUE_TYPE_PROFILES else DEFAULT_PANEL_WEIGHTS)
        )
        top_panel_analysis = simulate_reviewer_panel(
            top_panel,
            t_weights,
            aggregate_fatal_gate=bool(target_info['fatal_gate_triggered'] or top_checks_fatal),
        )
    top_fatal_reasons = list(target_info['fatal_reasons'])
    if top_checks_fatal and top_vtype_prof:
        if top_vtype_prof.get('failed_checks'):
            r_msg = f"venue_checks_failed:{','.join(top_vtype_prof['failed_checks'])}"
            if r_msg not in top_fatal_reasons:
                top_fatal_reasons.append(r_msg)
        if eff_vtype == 'dataset_benchmark' and top_vtype_prof.get('missing_checks'):
            r_msg = f"venue_checks_unverified:{','.join(top_vtype_prof['missing_checks'])}"
            if r_msg not in top_fatal_reasons:
                top_fatal_reasons.append(r_msg)
    if top_panel_analysis and top_panel_analysis.get('panel_verified_fatal_defect'):
        if 'reviewer_panel_fatal_defect' not in top_fatal_reasons:
            top_fatal_reasons.append('reviewer_panel_fatal_defect')
    top_fatal_gate = bool(
        target_info['fatal_gate_triggered']
        or top_checks_fatal
        or (top_panel_analysis and top_panel_analysis.get('fatal_defect_blocks_averaging'))
    )

    candidates = profile.get('candidate_venues')
    if not isinstance(candidates, list):
        top_errors.append('candidate_venues:must_be_list')
        candidates = []
    elif len(candidates) < eff_min_venues:
        top_errors.append(f'candidate_venues:fewer_than_min_venues:{len(candidates)}_lt_{eff_min_venues}')

    seen_ids = set()
    seen_keys = set()
    venue_evaluations = []
    agg_errors = list(top_errors)
    agg_warnings = list(top_warnings)

    total_checked = 0
    total_verified = 0
    total_failed = 0

    for idx, cand in enumerate(candidates):
        if not isinstance(cand, dict):
            err = f'candidate_venues:{idx}:must_be_object'
            agg_errors.append(err)
            venue_evaluations.append({
                'venue_id': f'venue_{idx}',
                'role': 'alternative',
                'classification': 'withheld_unverified',
                'errors': [err],
                'warnings': [],
                'disqualification_reasons': [],
                'withholding_reasons': [err],
                'rejection_reasons': [],
                'risk_reasons': [],
                'upgrade_gaps_to_target_tier': {},
            })
            continue

        cand_venue = cand.get('venue') if isinstance(cand.get('venue'), dict) else {}
        v_name = str(cand_venue.get('name') or '').strip()
        v_ed = str(cand_venue.get('edition') or '').strip()
        v_tr = str(cand_venue.get('track') or '').strip()
        cand_id = cand['venue_id'].strip() if _filled(cand.get('venue_id')) else (
            f'{v_name}::{v_ed}::{v_tr}' if (v_name or v_ed or v_tr) else f'venue_{idx}'
        )
        cand_role = str(cand.get('role') or 'alternative').strip().lower()

        is_dup = False
        norm_key = (v_name.lower(), v_ed.lower(), v_tr.lower())
        if cand_id in seen_ids or (all(norm_key) and norm_key in seen_keys):
            is_dup = True
            dup_err = f'candidate_venues:{idx}:duplicate_venue:{cand_id}'
            top_errors.append(dup_err)
            agg_errors.append(dup_err)
        seen_ids.add(cand_id)
        if all(norm_key):
            seen_keys.add(norm_key)

        cand_target = copy.deepcopy(cand['target']) if isinstance(cand.get('target'), dict) else copy.deepcopy(top_target)
        if 'status' not in cand_target and 'status' in top_target:
            cand_target['status'] = top_target['status']
        if 'object_type' not in cand_target and 'object_type' in top_target:
            cand_target['object_type'] = top_target['object_type']

        sub_profile = {
            'venue': cand.get('venue'),
            'target': cand_target,
            'fit_axes': cand.get('fit_axes'),
            'hard_constraints': cand.get('hard_constraints'),
        }
        if 'panel_selection' in cand and cand['panel_selection'] is not None:
            sub_profile['panel_selection'] = cand['panel_selection']
        if 'accepted_panel' in cand and cand['accepted_panel'] is not None:
            sub_profile['accepted_panel'] = cand['accepted_panel']
        if 'target_scorecard' in profile and profile['target_scorecard'] is not None:
            sub_profile['target_scorecard'] = profile['target_scorecard']
        for carry_key in ('weighted_unrounded', 'target_overall_score', 'fatal_gate_triggered', 'submission_readiness'):
            if carry_key in profile and profile[carry_key] is not None:
                sub_profile[carry_key] = profile[carry_key]
        if cand.get('tier_expectation') is not None:
            sub_profile['tier_expectation'] = cand['tier_expectation']
        if cand.get('venue_tier') is not None:
            sub_profile['venue_tier'] = cand['venue_tier']
        cand_vtype = cand.get('venue_type') or cand.get('venue_profile') or venue_type or profile.get('venue_type') or profile.get('venue_profile')
        if cand_vtype is not None:
            sub_profile['venue_type'] = cand_vtype
        for pass_k in (
            'venue_checks', 'dataset_checks', 'ethics_license_verified', 't1_t2_verified',
            'subfield_checks', 'evidence_anchors', 'reviewer_panel', 'reviewer_confidence', 'confidence',
        ):
            if pass_k in cand:
                sub_profile[pass_k] = cand[pass_k]
            elif pass_k in profile:
                sub_profile[pass_k] = profile[pass_k]

        cand_res = _check_single_venue(
            sub_profile,
            as_of=as_of,
            source_index=source_index,
            refs=refs,
            portfolio_optional_panel=not eff_require_panels,
            target_overall_override=target_overall,
            venue_type=cand_vtype,
            subfield_preset=(subfield_preset if subfield_preset is not None else profile.get('subfield_preset')),
            what_if=what_if,
        )
        cand_errors = list(cand_res['errors'])
        if is_dup:
            cand_errors.append(f'duplicate_venue:{cand_id}')
        for e in cand_res['errors']:
            agg_errors.append(f'candidate_venues:{idx}:{cand_id}:{e}')
        for w in cand_res['warnings']:
            agg_warnings.append(f'candidate_venues:{idx}:{cand_id}:{w}')

        lv = cand_res.get('locator_verification')
        if isinstance(lv, dict):
            total_checked += lv.get('checked', 0)
            total_verified += lv.get('verified', 0)
            total_failed += lv.get('failed', 0)

        sr = cand_res['submission_readiness']
        fit_score = cand_res['fit_score_out_of_10']
        failed_constraints = sr['failed_constraints']
        unverified_constraints = sr['unverified_constraints']

        cand_vtype_prof = cand_res.get('venue_type_profile')
        cand_panel_analysis = cand_res.get('reviewer_panel_analysis')
        q_tier = (cand_res.get('venue_quality_context') or {}).get('quality_tier', 'Unknown')
        tier_exp = cand.get('tier_expectation') or cand.get('venue_tier') or cand_venue.get('tier_expectation')
        venue_tier = resolve_venue_tier(cand_venue.get('name'), cand_venue.get('track'), q_tier, tier_exp)
        if venue_tier is None and isinstance(cand_vtype_prof, dict):
            venue_tier = cand_vtype_prof.get('venue_tier')
        vbar = cand_res.get('venue_contribution_bar')
        panel_med_nov = (cand_res.get('novelty_comparison') or {}).get('accepted_panel_median_score')
        tier_fit = evaluate_venue_tier_fit(
            venue_tier,
            weighted_unrounded=target_info['weighted_dec'],
            ratings=target_info['ratings'],
            is_idea=target_info['fatal_gate_triggered'] and 'unrun_idea_results' in target_info['fatal_reasons'],
            target_novelty=target_info['target_novelty_score'],
            panel_median_novelty=panel_med_nov,
            target_vs_venue_overall_delta=(vbar or {}).get('target_vs_venue_overall_delta'),
            venue_type=cand_res.get('venue_type'),
        )

        # Classification in exact precedence order
        disq_reasons = []
        withhold_reasons = []
        rej_reasons = []
        risk_reasons = []

        if is_dup:
            disq_reasons.append('duplicate_venue')
        for fc in failed_constraints:
            disq_reasons.append(f'failed_constraint:{fc}')
        if fit_score is not None and fit_score <= 4:
            disq_reasons.append(f'fit_score_too_low:{fit_score}<=4')

        if not disq_reasons:
            if cand_res['errors']:
                withhold_reasons.extend(cand_res['errors'])
            if 'venue:cfp_source_stale_or_future;_fit_score_withheld' in cand_res['warnings']:
                withhold_reasons.append('stale_or_future_cfp')
            for uc in unverified_constraints:
                withhold_reasons.append(f'unverified_constraint:{uc}')
            if fit_score is None and not withhold_reasons:
                withhold_reasons.append('fit_score_withheld')
            if eff_require_panels and cand_res['novelty_comparison'] is None:
                withhold_reasons.append('missing_required_accepted_panel')

        cand_fatal_gate = bool(
            top_fatal_gate
            or (isinstance(cand_vtype_prof, dict) and cand_vtype_prof.get('checks_gate_failed'))
            or (isinstance(cand_panel_analysis, dict) and cand_panel_analysis.get('fatal_defect_blocks_averaging'))
            or sr.get('verdict') == 'not_ready_fatal_gate'
        )
        if disq_reasons:
            classification = 'disqualified'
        elif withhold_reasons:
            classification = 'withheld_unverified'
        elif cand_fatal_gate:
            classification = 'hold_for_rework'
        elif tier_fit['rejected_below_venue_tier']:
            classification = 'rejected_below_venue_tier'
            rej_reasons = list(tier_fit['rejection_reasons'])
        else:
            standing = sr['standing_vs_accepted_panel']
            is_top_main = venue_tier == 'top_tier_flagship'
            is_workshop = venue_tier == 'workshop_or_preliminary'
            wdec = target_info['weighted_dec']
            if fit_score < 6:
                risk_reasons.append(f'moderate_weak_fit:{fit_score}<6')
            if standing == 'below_panel_median':
                risk_reasons.append('below_panel_median')
            if is_top_main and wdec is not None and wdec < Decimal('6.80'):
                risk_reasons.append(f'weighted_{wdec}_below_top_tier_competitive_6.80')
            if not is_workshop and wdec is not None and wdec < Decimal('6.00'):
                risk_reasons.append(f'weighted_{wdec}_below_archival_6.00')
            if cand_role == 'primary' and fit_score < 7:
                risk_reasons.append(f'primary_fit_{fit_score}<7')
            if is_top_main and wdec is None and cand_res['novelty_comparison'] is None:
                risk_reasons.append('unanchored_tier_s_score_and_panel')

            if risk_reasons:
                classification = 'stretch_high_risk'
            elif cand_role == 'fallback':
                classification = 'viable_fallback'
            elif fit_score >= 7:
                classification = 'recommended_now'
            else:
                classification = 'viable_fallback'

        dead_iso = cand_venue.get('submission_deadline_utc')
        notif_iso = cand_venue.get('notification_date_utc')
        sim_allowed = cand_venue.get('simultaneous_submission_allowed')
        if sim_allowed is None:
            sim_allowed = False
        timeline_info = {
            'submission_deadline_utc': dead_iso if _time(dead_iso) else None,
            'notification_date_utc': notif_iso if _time(notif_iso) else None,
            'simultaneous_submission_allowed': bool(sim_allowed) if type(sim_allowed) is bool else False,
            'has_timeline_conflict': False,
            'clean_fallback_timeline': None,
        }

        venue_evaluations.append({
            'venue_id': cand_id,
            'venue_name': v_name,
            'edition': v_ed,
            'track': v_tr,
            'role': cand_role,
            'venue_tier': venue_tier,
            'classification': classification,
            'fit_score_out_of_10': fit_score,
            'novelty_comparison': cand_res['novelty_comparison'],
            'venue_contribution_bar': vbar,
            'venue_quality_context': cand_res['venue_quality_context'],
            'submission_readiness': sr,
            'disqualification_reasons': disq_reasons,
            'withholding_reasons': withhold_reasons,
            'rejection_reasons': rej_reasons,
            'risk_reasons': risk_reasons,
            'upgrade_gaps_to_target_tier': tier_fit['upgrade_gaps_to_target_tier'],
            'timeline': timeline_info,
            'errors': cand_errors,
            'warnings': cand_res['warnings'],
            'locator_verification': lv,
        })

    bucket_rank = {
        'recommended_now': 0,
        'viable_fallback': 1,
        'stretch_high_risk': 2,
        'hold_for_rework': 3,
        'rejected_below_venue_tier': 4,
        'conflicted_fallback': 5,
        'withheld_unverified': 6,
        'disqualified': 7,
    }

    def _sort_key(ve):
        delta = ve['submission_readiness'].get('delta_vs_panel_median')
        fit = ve['fit_score_out_of_10']
        return (
            bucket_rank.get(ve['classification'], 9),
            -(fit if fit is not None else -1),
            -(delta if delta is not None else -999.0),
            ve['venue_id'],
        )

    pre_sorted = sorted(venue_evaluations, key=_sort_key)

    # Cross-venue timeline & double-submission conflict check
    timeline_conflicts = []
    anchors = [
        ve for ve in pre_sorted
        if ve['role'] == 'primary'
        and ve['classification'] in ('recommended_now', 'stretch_high_risk')
        and ve['timeline']['notification_date_utc']
    ]
    if not anchors:
        anchors = [
            ve for ve in pre_sorted
            if ve['classification'] == 'recommended_now'
            and ve['role'] != 'fallback'
            and ve['timeline']['notification_date_utc']
        ]
    if not anchors:
        anchors = [
            ve for ve in pre_sorted
            if ve['classification'] == 'stretch_high_risk'
            and ve['role'] != 'fallback'
            and ve['timeline']['notification_date_utc']
        ]
    if not anchors:
        anchors = [
            ve for ve in pre_sorted
            if ve['classification'] in ('recommended_now', 'stretch_high_risk')
            and ve['timeline']['notification_date_utc']
        ]

    for anchor in anchors:
        notif_str = anchor['timeline']['notification_date_utc']
        if not notif_str:
            continue
        t_notif = datetime.fromisoformat(notif_str.replace('Z', '+00:00'))
        for other in venue_evaluations:
            if other['venue_id'] == anchor['venue_id']:
                continue
            if other['classification'] in ('disqualified', 'withheld_unverified', 'hold_for_rework', 'rejected_below_venue_tier'):
                continue
            dead_str = other['timeline']['submission_deadline_utc']
            if not dead_str:
                continue
            t_dead = datetime.fromisoformat(dead_str.replace('Z', '+00:00'))
            both_sim = anchor['timeline']['simultaneous_submission_allowed'] and other['timeline']['simultaneous_submission_allowed']
            if t_dead < t_notif and not both_sim:
                overlap_days = round((t_notif - t_dead).total_seconds() / 86400, 1)
                conflict = {
                    'primary_venue_id': anchor['venue_id'],
                    'fallback_venue_id': other['venue_id'],
                    'primary_notification_date_utc': notif_str,
                    'fallback_submission_deadline_utc': dead_str,
                    'simultaneous_submission_allowed': False,
                    'overlap_days': overlap_days,
                    'conflict_type': 'double_submission_timeline_conflict',
                    'detail': (
                        f"{other['venue_id']} deadline ({dead_str}) precedes {anchor['venue_id']} "
                        f"notification ({notif_str}) by {overlap_days}d while simultaneous submission is prohibited."
                    ),
                }
                timeline_conflicts.append(conflict)
                other['timeline']['has_timeline_conflict'] = True
                other['timeline']['clean_fallback_timeline'] = False
                if other['classification'] == 'viable_fallback' or other['role'] == 'fallback':
                    other['classification'] = 'conflicted_fallback'
                    if 'double_submission_timeline_conflict_precedes_primary_notification' not in other['risk_reasons']:
                        other['risk_reasons'].append('double_submission_timeline_conflict_precedes_primary_notification')
            elif not other['timeline']['has_timeline_conflict']:
                other['timeline']['clean_fallback_timeline'] = True

    sorted_evals = sorted(venue_evaluations, key=_sort_key)
    recommended_now = [ve['venue_id'] for ve in sorted_evals if ve['classification'] == 'recommended_now']
    stretch_high_risk = [ve['venue_id'] for ve in sorted_evals if ve['classification'] == 'stretch_high_risk']
    viable_fallback = [ve['venue_id'] for ve in sorted_evals if ve['classification'] == 'viable_fallback']
    conflicted_fallback = [ve['venue_id'] for ve in sorted_evals if ve['classification'] == 'conflicted_fallback']
    rejected_below_tier = [ve['venue_id'] for ve in sorted_evals if ve['classification'] == 'rejected_below_venue_tier']
    hold_blocked = [ve['venue_id'] for ve in sorted_evals if ve['classification'] == 'hold_for_rework']
    disqualified = [ve['venue_id'] for ve in sorted_evals if ve['classification'] == 'disqualified']
    withheld_unverified = [ve['venue_id'] for ve in sorted_evals if ve['classification'] == 'withheld_unverified']
    ranked_order = [ve['venue_id'] for ve in sorted_evals]

    # Contribution-matched retargeting (F25)
    paper_tier_eval = evaluate_venue_tier_fit(
        None,
        weighted_unrounded=target_info['weighted_dec'],
        ratings=target_info['ratings'],
        is_idea=target_info['fatal_gate_triggered'] and 'unrun_idea_results' in target_info['fatal_reasons'],
        target_novelty=target_info['target_novelty_score'],
    )
    paper_matched_tier = paper_tier_eval.get('recommended_matched_tier')

    surviving_matched = [
        ve for ve in sorted_evals
        if ve['classification'] in ('recommended_now', 'viable_fallback')
    ]
    if not surviving_matched:
        surviving_matched = [ve for ve in sorted_evals if ve['classification'] == 'stretch_high_risk']

    # Order surviving matched venues by highest venue tier achievable without rejection, then bucket & fit
    def _matched_rank(ve):
        t_rank = VENUE_TIER_FLOORS.get(ve['venue_tier'], {}).get('rank', 9)
        return (
            0 if ve['classification'] == 'recommended_now' else (1 if ve['classification'] == 'viable_fallback' else 2),
            t_rank,
            -(ve['fit_score_out_of_10'] or -1),
            ve['venue_id'],
        )

    matched_sorted = sorted(surviving_matched, key=_matched_rank)
    matched_ids = [ve['venue_id'] for ve in matched_sorted]
    top_matched = matched_sorted[0] if matched_sorted else None

    if top_fatal_gate:
        matched_rationale = 'Hold for rework: target triggered a fatal gate blocking all archival venues.'
        action_if_empty = 'Resolve fatal scorecard/idea/panel/profile defects before targeting any archival venue.'
    elif top_matched is not None:
        top_gaps_note = ''
        if rejected_below_tier:
            first_rej = next(ve for ve in sorted_evals if ve['venue_id'] == rejected_below_tier[0])
            top_gaps_note = (
                f" Rejected {', '.join(rejected_below_tier)} for tier mismatch; "
                f"upgrade gaps for {first_rej['venue_id']}: {first_rej['upgrade_gaps_to_target_tier']}."
            )
        matched_rationale = (
            f"Best verified contribution-matched venue is {top_matched['venue_id']} "
            f"(tier={top_matched['venue_tier'] or 'unclassified'}, fit={top_matched['fit_score_out_of_10']}/10)."
            + top_gaps_note
        )
        action_if_empty = None
    else:
        matched_rationale = (
            'No surviving verified venue in portfolio matches current contribution strength.'
        )
        action_if_empty = (
            f"Search and add a verified Workshop ({paper_matched_tier or 'workshop_or_preliminary'}) or Q2-Q3 / CCF-C target; "
            'never submit to unverified, stale, or tier-mismatched venues.'
        )

    recommended_matched_tier_obj = {
        'matched_tier': paper_matched_tier,
        'recommended_venues': matched_ids,
        'top_venue_id': top_matched['venue_id'] if top_matched else None,
        'retargeted_from_rejected_venues': rejected_below_tier,
        'match_rationale': matched_rationale,
        'action_if_empty': action_if_empty,
    }

    structural_error_count = sum(1 for ve in venue_evaluations if ve['errors'])
    all_venues_errored = bool(venue_evaluations) and not (
        recommended_now or stretch_high_risk or viable_fallback or hold_blocked or rejected_below_tier
    ) and structural_error_count == len(venue_evaluations)

    if top_errors or all_venues_errored:
        portfolio_status = 'invalid'
    else:
        portfolio_status = 'structurally_checked'

    if top_fatal_gate:
        portfolio_verdict = 'hold_for_rework'
        guidance = (
            'Hold for rework: target triggered fatal gate ('
            + ', '.join(top_fatal_reasons)
            + '); all archival venues blocked.'
        )
    elif len(candidates) < eff_min_venues or top_errors:
        portfolio_verdict = 'invalid_portfolio_too_few_venues' if len(candidates) < eff_min_venues else 'no_verified_viable_venues'
        guidance = f"Portfolio invalid ({', '.join(top_errors[:3])}); supply >= {eff_min_venues} valid unique venues."
    elif not (recommended_now or stretch_high_risk or viable_fallback):
        if rejected_below_tier:
            portfolio_verdict = 'no_viable_venue_in_portfolio'
            guidance = (
                f"No viable venue in portfolio: {', '.join(rejected_below_tier)} rejected below venue tier. "
                + (action_if_empty or '')
            )
        elif hold_blocked:
            portfolio_verdict = 'hold_for_rework'
            guidance = (
                f"Hold for rework: all evaluated venues blocked by fatal gate ({', '.join(hold_blocked)})."
            )
        else:
            portfolio_verdict = 'no_verified_viable_venues'
            guidance = 'No verified viable venues remain after disqualification, withholding, and timeline checks.'
    elif recommended_now and viable_fallback:
        portfolio_verdict = 'ready_with_primary_and_fallback'
        guidance = (
            f"Recommended now: {', '.join(recommended_now)}; clean fallback: {', '.join(viable_fallback)}."
        )
    elif rejected_below_tier and matched_ids:
        portfolio_verdict = 'retargeted_to_matched_tier'
        guidance = matched_rationale
    else:
        portfolio_verdict = 'stretch_or_fallback_only'
        guidance = (
            f"No immediate Tier-S recommendation; stretch={stretch_high_risk}, fallback={viable_fallback}, "
            f"matched={matched_ids}."
        )

    eff_preset = subfield_preset if subfield_preset is not None else profile.get('subfield_preset')
    subfield_readiness = (
        evaluate_subfield_readiness(eff_preset, profile.get('subfield_checks'))
        if eff_preset is not None
        else None
    )

    out = {
        'mode': 'portfolio',
        'status': portfolio_status,
        'errors': agg_errors,
        'warnings': agg_warnings,
        'min_venues': eff_min_venues,
        'require_panels': eff_require_panels,
        'venue_count': len(candidates),
        'target_readiness': {
            'fatal_gate_triggered': top_fatal_gate,
            'fatal_reasons': top_fatal_reasons,
            'weighted_unrounded': target_info['weighted_unrounded'],
            'band': 'not_ready_fatal_gate' if top_fatal_gate else target_info['band'],
            'target_novelty_score': target_info['target_novelty_score'],
            'recommended_matched_tier': paper_matched_tier,
        },
        'venue_portfolio_recommendations': {
            'portfolio_verdict': portfolio_verdict,
            'hold_for_rework': top_fatal_gate or (portfolio_verdict == 'hold_for_rework'),
            'recommended_now': recommended_now,
            'stretch_high_risk': stretch_high_risk,
            'viable_fallback': viable_fallback,
            'conflicted_fallback': conflicted_fallback,
            'rejected_below_venue_tier': rejected_below_tier,
            'blocked_hold_for_rework': hold_blocked,
            'disqualified': disqualified,
            'withheld_unverified': withheld_unverified,
            'recommended_matched_tier': recommended_matched_tier_obj,
            'timeline_conflicts': timeline_conflicts,
            'ranked_order': ranked_order,
            'guidance': guidance,
        },
        'venue_evaluations': venue_evaluations,
        'disclaimer': (
            'Portfolio checks verify CFP freshness, 5 fit axes, hard constraints, tier floors, and timeline conflicts '
            'from supplied evidence only; never invent acceptance probabilities.'
        ),
    }
    if eff_vtype is not None:
        out['venue_type'] = eff_vtype
        out['venue_type_profile'] = top_vtype_prof
    if subfield_readiness is not None:
        out['subfield_preset'] = eff_preset.strip().lower()
        out['subfield_readiness'] = subfield_readiness
    if target_info['weighted_dec'] is not None:
        out['native_venue_scales'] = translate_to_native_scales(
            target_info['weighted_dec'],
            fatal_gate_triggered=top_fatal_gate,
            ratings=target_info['ratings'],
            reviewer_confidence=profile.get('reviewer_confidence') if profile.get('reviewer_confidence') is not None else top_target.get('confidence'),
            reviewer_panel=top_panel,
        )
    if isinstance(target_info['ratings'], dict):
        t_weights = (
            (profile.get('target_scorecard') or {}).get('weights')
            or top_target.get('weights')
            or (VENUE_TYPE_PROFILES[eff_vtype]['weights'] if eff_vtype in VENUE_TYPE_PROFILES else DEFAULT_PANEL_WEIGHTS)
        )
        out['merit_vs_packaging'] = compute_merit_vs_packaging(t_weights, target_info['ratings'])
        out['deal_breaker_sensitivity'] = compute_deal_breaker_sensitivity(
            t_weights,
            target_info['ratings'],
            venue_type=eff_vtype,
            reviewer_panel=top_panel,
            is_idea=(target_info['fatal_gate_triggered'] and 'unrun_idea_results' in target_info['fatal_reasons']),
        )
        if what_if:
            non_rating_fatal_top = bool(
                top_checks_fatal
                or (top_panel_analysis and top_panel_analysis.get('panel_verified_fatal_defect'))
            )
            out['what_if_roi'] = simulate_what_if_roi(
                t_weights,
                target_info['ratings'],
                venue_type=eff_vtype,
                is_idea=(target_info['fatal_gate_triggered'] and 'unrun_idea_results' in target_info['fatal_reasons']),
                non_rating_fatal_gate=non_rating_fatal_top,
            )
    if top_panel_analysis is not None:
        out['reviewer_panel_analysis'] = top_panel_analysis
    if isinstance(profile.get('evidence_anchors'), list) and profile['evidence_anchors']:
        out['evidence_anchor_table'] = build_evidence_anchor_table(top_target, profile['evidence_anchors'])
    if source_index is not None:
        out['locator_verification'] = {
            'sources_dir': str(source_index['root']),
            'sources_indexed': source_index['sources_indexed'],
            'skipped_files': source_index['skipped_files'],
            'checked': total_checked,
            'verified': total_verified,
            'failed': total_failed,
        }
    return out


def check(
    profile,
    as_of=None,
    sources_dir=None,
    quality_refs_dir=None,
    *,
    portfolio=False,
    require_panels=False,
    min_venues=None,
    target_overall=None,
    venue_type=None,
    subfield_preset=None,
    what_if=False,
):
    if not isinstance(profile, dict):
        raise ValueError('profile must be an object')
    as_of = as_of or datetime.now(timezone.utc)
    if as_of.utcoffset() is None:
        raise ValueError('as_of must have timezone')
    if type(portfolio) is not bool:
        raise ValueError('portfolio must be a boolean')
    if type(require_panels) is not bool:
        raise ValueError('require_panels must be a boolean')
    if type(what_if) is not bool:
        raise ValueError('what_if must be a boolean')
    if min_venues is not None and (type(min_venues) is not int or min_venues < 1):
        raise ValueError('min_venues must be an integer >= 1')
    if venue_type is not None:
        resolve_venue_type(venue_type)
    if subfield_preset is not None:
        evaluate_subfield_readiness(subfield_preset)
    parsed_target_overall = _parse_overall_decimal(target_overall, '--target-overall') if target_overall is not None else None

    if 'venue' in profile and 'candidate_venues' in profile:
        raise ValueError('profile cannot specify both single-venue "venue" and portfolio "candidate_venues"')

    if portfolio:
        if profile == {}:
            return {
                'mode': 'portfolio',
                'status': 'invalid',
                'errors': ['candidate_venues:must_be_list'],
                'warnings': [],
                'min_venues': min_venues or 3,
                'require_panels': require_panels,
                'venue_count': 0,
                'target_readiness': {
                    'fatal_gate_triggered': False,
                    'fatal_reasons': [],
                    'weighted_unrounded': None,
                    'band': None,
                    'target_novelty_score': None,
                    'recommended_matched_tier': None,
                },
                'venue_portfolio_recommendations': {
                    'portfolio_verdict': 'invalid_portfolio_too_few_venues',
                    'hold_for_rework': False,
                    'recommended_now': [],
                    'stretch_high_risk': [],
                    'viable_fallback': [],
                    'conflicted_fallback': [],
                    'rejected_below_venue_tier': [],
                    'blocked_hold_for_rework': [],
                    'disqualified': [],
                    'withheld_unverified': [],
                    'recommended_matched_tier': {
                        'matched_tier': None,
                        'recommended_venues': [],
                        'top_venue_id': None,
                        'retargeted_from_rejected_venues': [],
                        'match_rationale': 'Empty portfolio object.',
                        'action_if_empty': 'Provide candidate_venues list.',
                    },
                    'timeline_conflicts': [],
                    'ranked_order': [],
                    'guidance': 'Portfolio requires candidate_venues list.',
                },
                'venue_evaluations': [],
                'disclaimer': 'Portfolio validation failed on empty input.',
            }
        if 'candidate_venues' not in profile:
            raise ValueError('--portfolio requires candidate_venues list')
        return _check_portfolio(
            profile,
            as_of=as_of,
            sources_dir=sources_dir,
            quality_refs_dir=quality_refs_dir,
            require_panels=require_panels,
            min_venues=min_venues,
            target_overall=parsed_target_overall,
            venue_type=venue_type,
            subfield_preset=subfield_preset,
            what_if=what_if,
        )

    if 'candidate_venues' in profile:
        return _check_portfolio(
            profile,
            as_of=as_of,
            sources_dir=sources_dir,
            quality_refs_dir=quality_refs_dir,
            require_panels=require_panels,
            min_venues=min_venues,
            target_overall=parsed_target_overall,
            venue_type=venue_type,
            subfield_preset=subfield_preset,
            what_if=what_if,
        )

    return _check_single_venue(
        profile,
        as_of=as_of,
        sources_dir=sources_dir,
        quality_refs_dir=quality_refs_dir,
        target_overall_override=parsed_target_overall,
        venue_type=venue_type,
        subfield_preset=subfield_preset,
        what_if=what_if,
    )


def _encoded_utf8_len(obj: dict) -> int:
    return len(json.dumps(obj, ensure_ascii=False).encode('utf-8'))


def _truncate_artifact_path(path_str: str | None, max_bytes: int = 180) -> str | None:
    if not isinstance(path_str, str):
        return path_str
    if len(path_str.encode('utf-8')) <= max_bytes:
        return path_str
    name = Path(path_str).name
    candidate = '.../' + name if name else ''
    if candidate and len(candidate.encode('utf-8')) <= max_bytes:
        return candidate
    suffix = path_str
    while len(('...' + suffix).encode('utf-8')) > max_bytes and len(suffix) > 1:
        suffix = suffix[max(1, len(suffix) // 4):]
    return '...' + suffix


def _compact_portfolio_output(result: dict, out_path: str | None = None) -> dict:
    rec = result.get('venue_portfolio_recommendations') or {}
    evals = result.get('venue_evaluations') or []
    summaries = []
    for ve in evals[:8]:
        summaries.append({
            'venue_id': ve.get('venue_id'),
            'role': ve.get('role'),
            'venue_tier': ve.get('venue_tier'),
            'classification': ve.get('classification'),
            'fit_score_out_of_10': ve.get('fit_score_out_of_10'),
            'standing': (ve.get('submission_readiness') or {}).get('standing_vs_accepted_panel'),
            'delta_vs_panel': (ve.get('submission_readiness') or {}).get('delta_vs_panel_median'),
            'rejection_reasons': (ve.get('rejection_reasons') or [])[:2],
        })
    errors = result.get('errors') or []
    warnings = result.get('warnings') or []
    raw_matched = rec.get('recommended_matched_tier')
    compact_matched = copy.deepcopy(raw_matched) if isinstance(raw_matched, dict) else raw_matched
    if isinstance(compact_matched, dict):
        if isinstance(compact_matched.get('match_rationale'), str):
            compact_matched['match_rationale'] = compact_matched['match_rationale'][:240]
        if isinstance(compact_matched.get('action_if_empty'), str):
            compact_matched['action_if_empty'] = compact_matched['action_if_empty'][:180]
        if isinstance(compact_matched.get('recommended_venues'), list):
            compact_matched['recommended_venues'] = compact_matched['recommended_venues'][:8]
        if isinstance(compact_matched.get('retargeted_from_rejected_venues'), list):
            compact_matched['retargeted_from_rejected_venues'] = compact_matched['retargeted_from_rejected_venues'][:8]
    loc_ver = result.get('locator_verification')
    loc_summary = None
    if isinstance(loc_ver, dict):
        loc_summary = {k: v for k, v in loc_ver.items() if k != 'skipped_files'}
        if isinstance(loc_ver.get('skipped_files'), list):
            loc_summary['skipped_files_count'] = len(loc_ver['skipped_files'])
    compact_rec = {
        'portfolio_verdict': rec.get('portfolio_verdict'),
        'hold_for_rework': rec.get('hold_for_rework'),
        'recommended_now': (rec.get('recommended_now') or [])[:8],
        'stretch_high_risk': (rec.get('stretch_high_risk') or [])[:8],
        'viable_fallback': (rec.get('viable_fallback') or [])[:8],
        'conflicted_fallback': (rec.get('conflicted_fallback') or [])[:6],
        'rejected_below_venue_tier': (rec.get('rejected_below_venue_tier') or [])[:8],
        'blocked_hold_for_rework': (rec.get('blocked_hold_for_rework') or [])[:8],
        'disqualified': (rec.get('disqualified') or [])[:8],
        'withheld_unverified': (rec.get('withheld_unverified') or [])[:8],
        'recommended_matched_tier': compact_matched,
        'timeline_conflicts': (rec.get('timeline_conflicts') or [])[:3],
        'ranked_order': (rec.get('ranked_order') or [])[:12],
        'guidance': (rec.get('guidance') or '')[:200],
    }
    compact = {
        'compact': True,
        'mode': 'portfolio',
        'status': result.get('status'),
        'min_venues': result.get('min_venues'),
        'require_panels': result.get('require_panels'),
        'venue_count': result.get('venue_count'),
        'target_readiness': copy.deepcopy(result.get('target_readiness')),
        'venue_portfolio_recommendations': compact_rec,
        'venue_summaries': summaries,
        'venue_summaries_truncated': max(0, len(evals) - len(summaries)),
        'locator_verification': loc_summary,
        'error_count': len(errors),
        'warning_count': len(warnings),
        'errors': [e[:120] for e in errors[:10]],
        'warnings': [w[:120] for w in warnings[:10]],
        'artifact_path': out_path,
    }
    for opt_k in ('venue_type', 'subfield_preset'):
        if result.get(opt_k) is not None:
            compact[opt_k] = result[opt_k]
    if isinstance(result.get('subfield_readiness'), dict):
        sfr = result['subfield_readiness']
        compact['subfield_readiness'] = {
            'preset': sfr.get('preset'),
            'passed_count': len(sfr.get('passed_checks') or []),
            'failed_checks': sfr.get('failed_checks'),
            'missing_checks': sfr.get('missing_checks'),
            'subfield_checks_passed': sfr.get('subfield_checks_passed'),
        }
    if isinstance(result.get('native_venue_scales'), dict):
        compact['native_venue_scales'] = copy.deepcopy(result['native_venue_scales'])
    if isinstance(result.get('merit_vs_packaging'), dict):
        compact['merit_vs_packaging'] = copy.deepcopy(result['merit_vs_packaging'])
    if isinstance(result.get('reviewer_panel_analysis'), dict):
        rpa = result['reviewer_panel_analysis']
        compact['reviewer_panel_summary'] = {
            'reviewer_count': rpa.get('reviewer_count'),
            'confidence_weighted_mean': rpa.get('confidence_weighted_mean'),
            'variance_risk': rpa.get('variance_risk'),
            'assassin_reviewer_flag': rpa.get('assassin_reviewer_flag'),
            'fatal_defect_blocks_averaging': rpa.get('fatal_defect_blocks_averaging'),
            'meta_review_verdict': rpa.get('meta_review_verdict'),
        }
    if isinstance(result.get('evidence_anchor_table'), dict):
        eat = result['evidence_anchor_table']
        compact['evidence_anchor_table'] = {
            'anchor_count': eat.get('anchor_count'),
            'same_topic_anchor_count': eat.get('same_topic_anchor_count'),
            'cross_topic_anchor_count': eat.get('cross_topic_anchor_count'),
            'target_vs_anchors_summary': eat.get('target_vs_anchors_summary'),
        }
    id_list_keys = (
        'recommended_now', 'stretch_high_risk', 'viable_fallback',
        'conflicted_fallback', 'rejected_below_venue_tier', 'blocked_hold_for_rework',
        'disqualified', 'withheld_unverified', 'ranked_order',
    )
    m9a_p_keys = (
        'reviewer_panel_summary',
        'evidence_anchor_table',
        'merit_vs_packaging',
        'native_venue_scales',
        'subfield_readiness',
    )
    trim_stage = 0
    while _encoded_utf8_len(compact) > 3950:
        if trim_stage == 0:
            compact['artifact_path'] = _truncate_artifact_path(compact.get('artifact_path'), 180)
            compact['errors'] = [e[:80] for e in compact['errors'][:4]]
            compact['warnings'] = [w[:80] for w in compact['warnings'][:4]]
            compact_rec['timeline_conflicts'] = compact_rec['timeline_conflicts'][:1]
            for s in compact['venue_summaries']:
                s.pop('rejection_reasons', None)
        elif trim_stage == 1:
            compact['venue_summaries'] = compact['venue_summaries'][:4]
            compact['venue_summaries_truncated'] = max(0, len(evals) - len(compact['venue_summaries']))
            compact_rec['guidance'] = compact_rec['guidance'][:120]
            compact_rec['ranked_order'] = compact_rec['ranked_order'][:6]
            compact.pop('evidence_anchor_table', None)
            compact.pop('merit_vs_packaging', None)
        elif trim_stage == 2:
            compact['errors'] = []
            compact['warnings'] = []
            compact['venue_summaries'] = compact['venue_summaries'][:2]
            compact['venue_summaries_truncated'] = max(0, len(evals) - len(compact['venue_summaries']))
            compact_rec['timeline_conflicts'] = []
            for mk in m9a_p_keys:
                compact.pop(mk, None)
            if isinstance(compact_rec.get('recommended_matched_tier'), dict):
                compact_rec['recommended_matched_tier'] = {
                    'matched_tier': compact_rec['recommended_matched_tier'].get('matched_tier'),
                    'top_venue_id': compact_rec['recommended_matched_tier'].get('top_venue_id'),
                    'recommended_venues': (compact_rec['recommended_matched_tier'].get('recommended_venues') or [])[:3],
                }
        elif trim_stage == 3:
            compact['venue_summaries'] = []
            compact['venue_summaries_truncated'] = len(evals)
            for k in ('recommended_now', 'stretch_high_risk', 'viable_fallback', 'rejected_below_venue_tier', 'blocked_hold_for_rework'):
                compact_rec[k] = compact_rec[k][:3]
            for k in ('conflicted_fallback', 'disqualified', 'withheld_unverified'):
                compact_rec[k] = compact_rec[k][:2]
            compact_rec['ranked_order'] = compact_rec['ranked_order'][:4]
            if isinstance(compact_rec.get('recommended_matched_tier'), dict):
                compact_rec['recommended_matched_tier']['recommended_venues'] = (
                    compact_rec['recommended_matched_tier'].get('recommended_venues') or []
                )[:2]
        elif trim_stage == 4:
            compact_rec['guidance'] = ''
            for k in id_list_keys:
                cap = 2 if k == 'ranked_order' else 1
                compact_rec[k] = [
                    (v[:61] + '...') if isinstance(v, str) and len(v) > 64 else v
                    for v in compact_rec[k][:cap]
                ]
            if isinstance(compact_rec.get('recommended_matched_tier'), dict):
                rm = compact_rec['recommended_matched_tier']
                if isinstance(rm.get('top_venue_id'), str) and len(rm['top_venue_id']) > 64:
                    rm['top_venue_id'] = rm['top_venue_id'][:61] + '...'
                rm['recommended_venues'] = [
                    (v[:61] + '...') if isinstance(v, str) and len(v) > 64 else v
                    for v in (rm.get('recommended_venues') or [])[:1]
                ]
            if isinstance(compact.get('locator_verification'), dict):
                compact['locator_verification'].pop('sources_dir', None)
        elif trim_stage == 5:
            compact['artifact_path'] = _truncate_artifact_path(compact.get('artifact_path'), 64)
            compact_rec['ranked_order'] = compact_rec['ranked_order'][:1]
            if isinstance(compact_rec.get('recommended_matched_tier'), dict):
                compact_rec['recommended_matched_tier']['recommended_venues'] = []
            if isinstance(compact.get('target_readiness'), dict) and isinstance(compact['target_readiness'].get('fatal_reasons'), list):
                compact['target_readiness']['fatal_reasons'] = compact['target_readiness']['fatal_reasons'][:2]
        else:
            compact['locator_verification'] = (
                {'skipped_files_count': loc_summary['skipped_files_count']}
                if isinstance(loc_summary, dict) and 'skipped_files_count' in loc_summary
                else None
            )
            compact_rec['ranked_order'] = []
            if _encoded_utf8_len(compact) > 3950:
                compact['locator_verification'] = None
                compact['target_readiness'] = None
                compact['artifact_path'] = None
            break
        trim_stage += 1
    return compact


def _compact_output(result: dict, out_path: str | None = None) -> dict:
    if result.get('mode') == 'portfolio':
        return _compact_portfolio_output(result, out_path=out_path)
    comp = result.get('novelty_comparison')
    comp_summary = None
    if isinstance(comp, dict):
        comp_summary = {
            'target_novelty_score': comp.get('target_novelty_score'),
            'target_interval': comp.get('target_interval'),
            'accepted_panel_size': comp.get('accepted_panel_size'),
            'accepted_panel_median_score': comp.get('accepted_panel_median_score'),
            'accepted_panel_score_range': comp.get('accepted_panel_score_range'),
        }
    vqc = result.get('venue_quality_context')
    vqc_summary = None
    if isinstance(vqc, dict):
        vqc_summary = {
            'quality_tier': vqc.get('quality_tier'),
            'matched_name': vqc.get('matched_name'),
            'matched_source': vqc.get('matched_source'),
        }
    sr = result.get('submission_readiness')
    sr_summary = None
    if isinstance(sr, dict):
        sr_summary = {
            'verdict': sr.get('verdict'),
            'ready_to_submit': sr.get('ready_to_submit'),
            'standing_vs_accepted_panel': sr.get('standing_vs_accepted_panel'),
            'delta_vs_panel_median': sr.get('delta_vs_panel_median'),
            'interval_dominance': sr.get('interval_dominance'),
            'fit_score_out_of_10': sr.get('fit_score_out_of_10'),
            'hard_constraints_met': sr.get('hard_constraints_met'),
            'failed_constraints': sr.get('failed_constraints'),
            'unverified_constraints': sr.get('unverified_constraints'),
            'weak_fit_axes': sr.get('weak_fit_axes'),
            'guidance': (sr.get('guidance') or '')[:200],
        }
        for opt_key in ('venue_tier', 'recommended_matched_tier', 'upgrade_gaps_to_target_tier'):
            if opt_key in sr:
                sr_summary[opt_key] = sr[opt_key]
    errors = result.get('errors') or []
    warnings = result.get('warnings') or []
    loc_ver = result.get('locator_verification')
    loc_summary = None
    if isinstance(loc_ver, dict):
        loc_summary = {k: v for k, v in loc_ver.items() if k != 'skipped_files'}
        if isinstance(loc_ver.get('skipped_files'), list):
            loc_summary['skipped_files_count'] = len(loc_ver['skipped_files'])
    compact = {
        'compact': True,
        'status': result.get('status'),
        'fit_score_out_of_10': result.get('fit_score_out_of_10'),
        'novelty_comparison': comp_summary,
        'venue_contribution_bar': result.get('venue_contribution_bar'),
        'venue_quality_context': vqc_summary,
        'submission_readiness': sr_summary,
        'locator_verification': loc_summary,
        'error_count': len(errors),
        'warning_count': len(warnings),
        'errors': errors[:20],
        'warnings': warnings[:20],
        'artifact_path': out_path,
    }
    for opt_k in ('venue_type', 'subfield_preset'):
        if result.get(opt_k) is not None:
            compact[opt_k] = result[opt_k]
    if isinstance(result.get('subfield_readiness'), dict):
        sfr = result['subfield_readiness']
        compact['subfield_readiness'] = {
            'preset': sfr.get('preset'),
            'passed_count': len(sfr.get('passed_checks') or []),
            'failed_checks': sfr.get('failed_checks'),
            'missing_checks': sfr.get('missing_checks'),
            'subfield_checks_passed': sfr.get('subfield_checks_passed'),
        }
    if isinstance(result.get('native_venue_scales'), dict):
        compact['native_venue_scales'] = copy.deepcopy(result['native_venue_scales'])
    if isinstance(result.get('merit_vs_packaging'), dict):
        compact['merit_vs_packaging'] = copy.deepcopy(result['merit_vs_packaging'])
    if isinstance(result.get('reviewer_panel_analysis'), dict):
        rpa = result['reviewer_panel_analysis']
        compact['reviewer_panel_summary'] = {
            'reviewer_count': rpa.get('reviewer_count'),
            'confidence_weighted_mean': rpa.get('confidence_weighted_mean'),
            'variance_risk': rpa.get('variance_risk'),
            'assassin_reviewer_flag': rpa.get('assassin_reviewer_flag'),
            'fatal_defect_blocks_averaging': rpa.get('fatal_defect_blocks_averaging'),
            'meta_review_verdict': rpa.get('meta_review_verdict'),
        }
    if isinstance(result.get('evidence_anchor_table'), dict):
        eat = result['evidence_anchor_table']
        compact['evidence_anchor_table'] = {
            'anchor_count': eat.get('anchor_count'),
            'same_topic_anchor_count': eat.get('same_topic_anchor_count'),
            'cross_topic_anchor_count': eat.get('cross_topic_anchor_count'),
            'target_vs_anchors_summary': eat.get('target_vs_anchors_summary'),
        }
    m9a_s_keys = (
        'reviewer_panel_summary',
        'evidence_anchor_table',
        'merit_vs_packaging',
        'native_venue_scales',
        'subfield_readiness',
    )
    trim_stage = 0
    while _encoded_utf8_len(compact) > 3950:
        if trim_stage == 0:
            compact['artifact_path'] = _truncate_artifact_path(compact.get('artifact_path'), 180)
            compact['errors'] = [e[:100] for e in compact['errors'][:5]]
            compact['warnings'] = [w[:100] for w in compact['warnings'][:5]]
            if isinstance(compact.get('venue_contribution_bar'), dict):
                compact['venue_contribution_bar'] = {
                    k: v for k, v in compact['venue_contribution_bar'].items() if k != 'guidance'
                }
        elif trim_stage == 1:
            if isinstance(compact.get('submission_readiness'), dict):
                compact['submission_readiness'].pop('guidance', None)
            compact.pop('evidence_anchor_table', None)
            compact.pop('merit_vs_packaging', None)
        elif trim_stage == 2:
            if isinstance(compact.get('submission_readiness'), dict):
                compact['submission_readiness'].pop('upgrade_gaps_to_target_tier', None)
                compact['submission_readiness'].pop('weak_fit_axes', None)
            for mk in m9a_s_keys:
                compact.pop(mk, None)
        elif trim_stage == 3:
            compact['errors'] = []
            compact['warnings'] = []
            if isinstance(compact.get('submission_readiness'), dict):
                compact['submission_readiness'].pop('failed_constraints', None)
                compact['submission_readiness'].pop('unverified_constraints', None)
        elif trim_stage == 4:
            if isinstance(compact.get('submission_readiness'), dict):
                compact['submission_readiness'].pop('interval_dominance', None)
            if isinstance(compact.get('locator_verification'), dict):
                compact['locator_verification'].pop('sources_dir', None)
        elif trim_stage == 5:
            compact['venue_contribution_bar'] = None
        elif trim_stage == 6:
            compact['novelty_comparison'] = None
            compact['venue_quality_context'] = None
        elif trim_stage == 7:
            compact['artifact_path'] = _truncate_artifact_path(compact.get('artifact_path'), 64)
        else:
            compact['locator_verification'] = None
            if _encoded_utf8_len(compact) > 3950:
                compact['artifact_path'] = None
            break
        trim_stage += 1
    return compact


def _reject_nonfinite(token):
    raise ValueError(f'Non-finite JSON constant not allowed: {token}')


def _require_nonempty_path(val, flag):
    if not isinstance(val, str) or not val.strip():
        raise ValueError(f'Empty or invalid path for {flag}')
    return val.strip()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile_json')
    parser.add_argument('--sources-dir', default=None, help='Optional directory of local source files (.txt, .md, .json, .pdf) for locator verification')
    parser.add_argument('--quality-refs-dir', default=None, help='Optional directory containing paper-quality-filter reference JSON files')
    parser.add_argument('--portfolio', action='store_true', help='Evaluate candidate_venues portfolio under full strict venue verification')
    parser.add_argument('--require-panels', action='store_true', help='Require >= 5 recent same-track full-text accepted_panel for every portfolio venue')
    parser.add_argument('--min-venues', type=int, default=None, help='Minimum candidate venues required in portfolio mode (default: 3)')
    parser.add_argument('--target-overall', default=None, help='Optional target overall /10 score for cross-topic venue bar comparison')
    parser.add_argument('--venue-type', default=None, choices=sorted(VENUE_TYPE_PROFILES), help='Optional venue-type profile')
    parser.add_argument('--venue-profile', default=None, choices=sorted(VENUE_TYPE_PROFILES), help='Alias for --venue-type')
    parser.add_argument('--subfield-preset', default=None, choices=sorted(SUBFIELD_PRESETS), help='Optional AI/CS subfield depth preset')
    parser.add_argument('--what-if', action='store_true', help='Include What-If Score-Lift ROI plan when target ratings are present')
    parser.add_argument('--out', default=None, help='Optional output JSON file path for full report')
    parser.add_argument('--compact', action='store_true', help='Emit compact bounded summary JSON to stdout')
    args = parser.parse_args(argv)
    try:
        prof_path = Path(_require_nonempty_path(args.profile_json, 'profile_json'))
        if args.out is not None:
            _require_nonempty_path(args.out, '--out')
        if args.sources_dir is not None:
            _require_nonempty_path(args.sources_dir, '--sources-dir')
        if args.quality_refs_dir is not None:
            _require_nonempty_path(args.quality_refs_dir, '--quality-refs-dir')
        if args.target_overall is not None:
            _require_nonempty_path(args.target_overall, '--target-overall')
        if args.venue_type and args.venue_profile and args.venue_type != args.venue_profile:
            raise ValueError('--venue-type and --venue-profile cannot conflict')
        profile = json.loads(prof_path.read_text(encoding='utf-8'), parse_constant=_reject_nonfinite)
        result = check(
            profile,
            sources_dir=args.sources_dir,
            quality_refs_dir=args.quality_refs_dir,
            portfolio=bool(args.portfolio),
            require_panels=bool(args.require_panels),
            min_venues=args.min_venues,
            target_overall=args.target_overall,
            venue_type=(args.venue_type or args.venue_profile),
            subfield_preset=args.subfield_preset,
            what_if=bool(args.what_if),
        )
        full_rendered = json.dumps(result, ensure_ascii=False)
        out_str = None
        if args.out is not None:
            out_path = Path(args.out.strip())
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(full_rendered + '\n', encoding='utf-8')
            out_str = str(out_path)
        if args.compact:
            print(json.dumps(_compact_output(result, out_str), ensure_ascii=False))
        else:
            print(full_rendered)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError, RuntimeError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2
    return 0 if result['status'] == 'structurally_checked' else 1


if __name__ == '__main__':
    sys.exit(main())
