#!/usr/bin/env python3
"""Calculate a declared weighted score; never supply scientific judgments."""
import argparse
import json
import math
import re
import sys
from decimal import BasicContext, Decimal, ROUND_HALF_UP, localcontext
from pathlib import Path

DIMENSIONS = ('importance', 'novelty', 'soundness', 'evidence', 'transparency', 'clarity')
IDEA_DIMENSIONS = (
    'evidence_coverage',
    'novelty',
    'importance',
    'answerability',
    'feasibility',
    'falsifiability',
)
FATAL_THRESHOLDS = {
    'importance': 2,
    'novelty': 2,
    'soundness': 4,
    'evidence': 4,
    'transparency': 3,
    'clarity': 2,
}
IDEA_FATAL_THRESHOLDS = {
    'evidence_coverage': 2,
    'novelty': 2,
    'importance': 2,
    'answerability': 3,
    'feasibility': 3,
    'falsifiability': 3,
}
IDEA_VIABILITY_BANDS = (
    'pursue_high_priority',
    'refine_and_de_risk',
    'pivot_or_narrow',
    'kill_early',
)
DEFAULT_PAPER_WEIGHTS = {
    'importance': 15,
    'novelty': 20,
    'soundness': 20,
    'evidence': 20,
    'transparency': 15,
    'clarity': 10,
}
DEFAULT_IDEA_WEIGHTS = {
    'evidence_coverage': 15,
    'novelty': 20,
    'importance': 20,
    'answerability': 15,
    'feasibility': 15,
    'falsifiability': 15,
}
TOP_TIER_COMPETITIVE_THRESHOLD = Decimal('6.80')
MERIT_DIMENSIONS = ('importance', 'novelty', 'soundness', 'evidence')
PACKAGING_DIMENSIONS = ('transparency', 'clarity')
IDEA_MERIT_DIMENSIONS = ('evidence_coverage', 'novelty', 'importance', 'falsifiability')
IDEA_PACKAGING_DIMENSIONS = ('answerability', 'feasibility')
DIAGNOSTIC_SECTIONS = ('abstract', 'introduction', 'related_work', 'method', 'experiments', 'limitations')
SECTION_TO_DIMENSIONS = {
    'abstract': ('importance', 'clarity'),
    'introduction': ('importance', 'clarity', 'novelty'),
    'related_work': ('novelty', 'transparency'),
    'method': ('soundness', 'clarity'),
    'experiments': ('evidence', 'soundness', 'transparency'),
    'limitations': ('transparency', 'soundness'),
}
HEX64_RE = re.compile(r'^[0-9a-fA-F]{64}$')

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


def _tier_deficits(
    tier_key,
    weighted_dec,
    ratings,
    target_novelty,
    panel_median_novelty,
    target_vs_venue_overall_delta,
    *,
    venue_type=None,
):
    floor_label = venue_type if venue_type in VENUE_TYPE_PROFILES else tier_key
    floor = VENUE_TYPE_PROFILES[venue_type] if venue_type in VENUE_TYPE_PROFILES else VENUE_TIER_FLOORS[tier_key]
    reasons = []
    upgrade_gaps = {}
    if weighted_dec is not None and weighted_dec < floor['min_viable_overall']:
        with localcontext(BasicContext) as ctx:
            ctx.prec = 28
            gap_min = (floor['min_viable_overall'] - weighted_dec).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        reasons.append(f'weighted_{weighted_dec}_below_{floor_label}_min_{floor["min_viable_overall"]}')
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
                reasons.append(f'{dim}_{rv}_below_{floor_label}_min_{min_val}')
                upgrade_gaps[dim] = max(upgrade_gaps.get(dim, 0), min_val - rv)
        min_any = floor['min_any_dimension']
        for dim in DIMENSIONS:
            rv = ratings.get(dim)
            if type(rv) is int and rv < min_any:
                reasons.append(f'{dim}_{rv}_below_{floor_label}_dim_floor_{min_any}')
                upgrade_gaps[dim] = max(upgrade_gaps.get(dim, 0), min_any - rv)
    elif target_novelty is not None and 'novelty' in floor['min_dimensions']:
        min_nov = floor['min_dimensions']['novelty']
        if target_novelty < min_nov:
            reasons.append(f'novelty_{target_novelty}_below_{floor_label}_min_{min_nov}')
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
    venue_type=None,
):
    """Evaluate paper contribution against canonical venue-tier floors (Decimal-trap safe)."""
    eff_vtype = resolve_venue_type(venue_type) if venue_type is not None else None
    eff_tier = (
        venue_tier
        if venue_tier in VENUE_TIER_FLOORS
        else (VENUE_TYPE_PROFILES[eff_vtype]['venue_tier'] if eff_vtype else venue_tier)
    )
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
        if eff_tier in VENUE_TIER_FLOORS or eff_vtype in VENUE_TYPE_PROFILES:
            rejection_reasons, upgrade_gaps = _tier_deficits(
                eff_tier,
                weighted_dec,
                ratings,
                target_novelty,
                panel_median_novelty,
                target_vs_venue_overall_delta,
                venue_type=eff_vtype,
            )
        else:
            delta_dec = _to_decimal_or_none(target_vs_venue_overall_delta)
            if delta_dec is not None and delta_dec <= Decimal('-1.0'):
                rejection_reasons.append(f'target_vs_venue_overall_delta_{delta_dec:+.2f}_below_venue_bar')
                need = (-delta_dec).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                upgrade_gaps['overall_vs_venue_panel_median'] = float(str(need))
    out = {
        'venue_tier': eff_tier,
        'rejected_below_venue_tier': bool(rejection_reasons),
        'rejection_reasons': rejection_reasons,
        'upgrade_gaps_to_target_tier': upgrade_gaps,
        'recommended_matched_tier': matched_tier,
    }
    if eff_vtype is not None:
        out['venue_type'] = eff_vtype
    return out


def _reject_nonfinite(token):
    raise ValueError(f'Non-finite JSON constant not allowed: {token}')


VENUE_TYPE_PROFILES = {
    'conference_top_tier': {
        'label': 'Top-Tier ML/AI/CV/NLP Conference (NeurIPS / ICML / ICLR / CVPR / ACL)',
        'venue_tier': 'top_tier_flagship',
        'weights': {
            'importance': 15,
            'novelty': 25,
            'soundness': 20,
            'evidence': 20,
            'transparency': 10,
            'clarity': 10,
        },
        'competitive_overall': Decimal('6.80'),
        'min_viable_overall': Decimal('6.00'),
        'min_dimensions': {'soundness': 6, 'evidence': 6, 'novelty': 5},
        'min_any_dimension': 5,
        'required_checks': (),
        'emphasis': 'High novelty/insight and technical depth with matched SOTA baselines.',
    },
    'journal_q1': {
        'label': 'Q1 Journal (TPAMI / JMLR / TACL / IJCV / AIJ)',
        'venue_tier': 'q1_or_tier_a',
        'weights': {
            'importance': 15,
            'novelty': 15,
            'soundness': 25,
            'evidence': 25,
            'transparency': 10,
            'clarity': 10,
        },
        'competitive_overall': Decimal('6.80'),
        'min_viable_overall': Decimal('6.00'),
        'min_dimensions': {'soundness': 6, 'evidence': 6, 'transparency': 6, 'novelty': 5},
        'min_any_dimension': 5,
        'required_checks': ('comprehensive_ablations', 'reproducibility_details'),
        'emphasis': 'Heavy soundness, exhaustive ablations, statistical rigor, and full reproducibility.',
    },
    'dataset_benchmark': {
        'label': 'Datasets & Benchmarks Track (NeurIPS D&B / LREC / Resources)',
        'venue_tier': 'q1_or_tier_a',
        'weights': {
            'importance': 15,
            'novelty': 15,
            'soundness': 20,
            'evidence': 20,
            'transparency': 20,
            'clarity': 10,
        },
        'competitive_overall': Decimal('6.50'),
        'min_viable_overall': Decimal('6.00'),
        'min_dimensions': {'transparency': 6, 'soundness': 6, 'evidence': 6},
        'min_any_dimension': 5,
        'required_checks': ('data_quality_audit', 'annotation_protocol', 'ethics_and_license_t1_t2'),
        'emphasis': 'T1-T2 data quality, annotation protocol/IAA, ethics/compensation, and release license rigor.',
    },
    'survey_review': {
        'label': 'Survey / Systematic Review (CSUR / TMLR Survey)',
        'venue_tier': 'q1_or_tier_a',
        'weights': {
            'importance': 15,
            'novelty': 15,
            'soundness': 20,
            'evidence': 25,
            'transparency': 15,
            'clarity': 10,
        },
        'competitive_overall': Decimal('6.50'),
        'min_viable_overall': Decimal('6.00'),
        'min_dimensions': {'evidence': 6, 'clarity': 6, 'transparency': 5},
        'min_any_dimension': 5,
        'required_checks': ('systematic_coverage_protocol',),
        'emphasis': 'Exhaustive taxonomy, explicit search protocol, synthesis breadth, and clarity.',
    },
    'workshop_preliminary': {
        'label': 'Workshop / Preliminary Track',
        'venue_tier': 'workshop_or_preliminary',
        'weights': {
            'importance': 15,
            'novelty': 20,
            'soundness': 20,
            'evidence': 15,
            'transparency': 15,
            'clarity': 15,
        },
        'competitive_overall': Decimal('5.50'),
        'min_viable_overall': Decimal('5.00'),
        'min_dimensions': {'soundness': 5},
        'min_any_dimension': 3,
        'required_checks': (),
        'emphasis': 'Early promising mechanism/insight with honest boundaries; not full archival bar.',
    },
}

SUBFIELD_PRESETS = {
    'nlp_llm': {
        'label': 'NLP / Large Language Models',
        'required_checks': (
            'contamination_check',
            'multi_prompt_variance',
            'compute_matched_open_weight_baseline',
            'eval_harness_parity',
        ),
        'aliases': {
            'contamination_audit': ('contamination_check',),
            'pretraining_benchmark_contamination_check': ('contamination_check',),
            'multi_prompt_template_variance': ('multi_prompt_variance',),
            'frozen_prompt_and_seed_check': ('multi_prompt_variance',),
            'compute_matched_open_weight_baselines': ('compute_matched_open_weight_baseline',),
            'open_weight_baseline_parity': ('compute_matched_open_weight_baseline',),
        },
        'recommended_weights_paper': {
            'importance': 15,
            'novelty': 20,
            'soundness': 20,
            'evidence': 20,
            'transparency': 15,
            'clarity': 10,
        },
        'readiness_guidance': (
            'Verify contamination audit, multi-prompt/template variance, compute-matched '
            'open-weight baselines, and identical evaluation harness parity.'
        ),
    },
    'cv_multimodal': {
        'label': 'Computer Vision / Multimodal',
        'required_checks': (
            'backbone_resolution_augmentation_parity',
            'flops_fps_memory_tradeoff',
            'qualitative_failure_analysis',
        ),
        'aliases': {
            'matched_backbone_and_input_resolution': ('backbone_resolution_augmentation_parity',),
            'matched_augmentation_schedule': ('backbone_resolution_augmentation_parity',),
            'flops_fps_memory_vs_accuracy_tradeoff': ('flops_fps_memory_tradeoff',),
            'compute_latency_pareto_report': ('flops_fps_memory_tradeoff',),
        },
        'recommended_weights_paper': {
            'importance': 15,
            'novelty': 20,
            'soundness': 20,
            'evidence': 25,
            'transparency': 10,
            'clarity': 10,
        },
        'readiness_guidance': (
            'Verify backbone/resolution/augmentation parity, FLOPs/FPS/memory vs accuracy '
            'tradeoff reporting, and qualitative failure analysis.'
        ),
    },
    'ml_theory': {
        'label': 'ML Theory / Statistical Learning',
        'required_checks': (
            'assumption_tightness_realism',
            'lower_vs_upper_bound_gap',
            'empirical_sanity_validation',
        ),
        'aliases': {
            'assumption_tightness_and_realism': ('assumption_tightness_realism',),
            'explicit_assumption_falsification_check': ('assumption_tightness_realism',),
            'matching_lower_bound_comparison': ('lower_vs_upper_bound_gap',),
            'empirical_sanity_validation_of_theoretical_claims': ('empirical_sanity_validation',),
            'synthetic_toy_sanity_experiment': ('empirical_sanity_validation',),
        },
        'recommended_weights_paper': {
            'importance': 15,
            'novelty': 20,
            'soundness': 25,
            'evidence': 20,
            'transparency': 10,
            'clarity': 10,
        },
        'readiness_guidance': (
            'Verify theorem assumption tightness/realism, lower-vs-upper bound gap analysis, '
            'and empirical sanity validation of theoretical bounds.'
        ),
    },
    'ai_systems': {
        'label': 'AI Systems / Efficient ML',
        'required_checks': (
            'end_to_end_vs_microbenchmark',
            'tail_latency_p99',
            'peak_vram_comm_overhead',
            'matched_hardware',
        ),
        'aliases': {
            'end_to_end_vs_microbenchmark_throughput': ('end_to_end_vs_microbenchmark',),
            'end_to_end_plus_microbenchmark_isolation': ('end_to_end_vs_microbenchmark',),
            'peak_vram_and_communication_overhead_matched_hardware': (
                'peak_vram_comm_overhead',
                'matched_hardware',
            ),
            'p99_tail_latency_and_peak_vram_receipts': ('tail_latency_p99', 'peak_vram_comm_overhead'),
            'matched_hardware_and_load_shape': ('matched_hardware',),
        },
        'recommended_weights_paper': {
            'importance': 15,
            'novelty': 15,
            'soundness': 25,
            'evidence': 20,
            'transparency': 15,
            'clarity': 10,
        },
        'readiness_guidance': (
            'Verify end-to-end vs microbenchmark throughput, p99 tail latency, peak VRAM and '
            'communication overhead, and matched hardware parity.'
        ),
    },
    'speech_audio': {
        'label': 'Speech & Audio (STT/ASR, TTS, Speech-to-Vector)',
        'required_checks': (
            'speaker_session_disjoint_split',
            'audio_metric_and_normalization_parity',
            'decoding_vocoder_embedding_parity',
            'speech_slice_significance_and_consent',
        ),
        'aliases': {
            'speaker_and_session_disjoint_split': ('speaker_session_disjoint_split',),
            'speaker_disjoint_split': ('speaker_session_disjoint_split',),
            'audio_text_normalization_and_metric_parity': ('audio_metric_and_normalization_parity',),
            'wer_cer_eer_mos_metric_parity': ('audio_metric_and_normalization_parity',),
            'lm_vocoder_embedding_backend_parity': ('decoding_vocoder_embedding_parity',),
            'decoding_and_vocoder_parity': ('decoding_vocoder_embedding_parity',),
            'paired_utterance_significance_and_consent': ('speech_slice_significance_and_consent',),
            'low_resource_speech_slices_and_consent': ('speech_slice_significance_and_consent',),
        },
        'recommended_weights_paper': {
            'importance': 15,
            'novelty': 15,
            'soundness': 20,
            'evidence': 25,
            'transparency': 15,
            'clarity': 10,
        },
        'readiness_guidance': (
            'Verify speaker/session-disjoint splits, unified WER/CER/PER/EER/MOS/SECS normalization, '
            'matched LM-decoding/vocoder/embedding backends, and paired utterance significance with speaker consent.'
        ),
    },
}


def resolve_venue_type(venue_type):
    if venue_type is None:
        return None
    if type(venue_type) is not str or not venue_type.strip():
        raise ValueError('venue_type must be a nonblank string')
    key = venue_type.strip().lower()
    if key not in VENUE_TYPE_PROFILES:
        raise ValueError(f'Unknown venue_type: {venue_type!r}')
    return key


def evaluate_venue_profile_checks(venue_type, document=None):
    vkey = resolve_venue_type(venue_type)
    if vkey is None:
        return None
    prof = VENUE_TYPE_PROFILES[vkey]
    doc = document if isinstance(document, dict) else {}
    req_checks = list(prof['required_checks'])
    raw_checks = doc.get('venue_checks')
    if raw_checks is None and vkey == 'dataset_benchmark':
        raw_checks = doc.get('dataset_checks')
    if raw_checks is not None and not isinstance(raw_checks, dict):
        raise ValueError('venue_checks / dataset_checks must be a JSON object when provided')
    checks_map = dict(raw_checks or {})
    if vkey == 'dataset_benchmark':
        if 'ethics_license_verified' in doc and doc['ethics_license_verified'] is not None:
            if type(doc['ethics_license_verified']) is not bool:
                raise ValueError('ethics_license_verified must be a boolean')
            checks_map.setdefault('ethics_and_license_t1_t2', doc['ethics_license_verified'])
        if 't1_t2_verified' in doc and doc['t1_t2_verified'] is not None:
            if type(doc['t1_t2_verified']) is not bool:
                raise ValueError('t1_t2_verified must be a boolean')
            checks_map.setdefault('ethics_and_license_t1_t2', doc['t1_t2_verified'])

    passed, failed, missing = [], [], []
    for chk in req_checks:
        val = checks_map.get(chk)
        if val is True or (isinstance(val, str) and val.strip().lower() in {'pass', 'passed', 'verified', 'true'}):
            passed.append(chk)
        elif val is False or (isinstance(val, str) and val.strip().lower() in {'fail', 'failed', 'false'}):
            failed.append(chk)
        else:
            missing.append(chk)

    return {
        'venue_type': vkey,
        'label': prof['label'],
        'venue_tier': prof['venue_tier'],
        'profile_weights': dict(prof['weights']),
        'competitive_overall': float(str(prof['competitive_overall'])),
        'min_viable_overall': float(str(prof['min_viable_overall'])),
        'min_dimensions': dict(prof['min_dimensions']),
        'required_checks': req_checks,
        'passed_checks': passed,
        'failed_checks': failed,
        'missing_checks': missing,
        'checks_gate_failed': bool(failed) or (vkey == 'dataset_benchmark' and bool(missing)),
    }


def evaluate_subfield_readiness(subfield_preset, subfield_checks=None, *, strict=False):
    if subfield_preset is None:
        return None
    if type(subfield_preset) is not str or not subfield_preset.strip():
        raise ValueError('subfield_preset must be a nonblank string')
    key = subfield_preset.strip().lower()
    if key not in SUBFIELD_PRESETS:
        raise ValueError(f'Unknown subfield_preset: {subfield_preset!r}')
    if subfield_checks is not None and not isinstance(subfield_checks, dict):
        raise ValueError('subfield_checks must be a JSON object')

    spec = SUBFIELD_PRESETS[key]
    req_checks = list(spec['required_checks'])
    aliases = spec['aliases']
    norm_checks = {}
    for raw_k, raw_v in (subfield_checks or {}).items():
        if not isinstance(raw_k, str):
            continue
        k_clean = raw_k.strip().lower()
        targets = (k_clean,) if k_clean in req_checks else aliases.get(k_clean, ())
        for target_chk in targets:
            if target_chk not in norm_checks:
                norm_checks[target_chk] = raw_v
            elif raw_v is False or (isinstance(raw_v, str) and raw_v.strip().lower() in {'fail', 'failed', 'false'}):
                norm_checks[target_chk] = False

    passed, failed, missing = [], [], []
    for chk in req_checks:
        val = norm_checks.get(chk)
        if val is True or (isinstance(val, str) and val.strip().lower() in {'pass', 'passed', 'verified', 'true'}):
            passed.append(chk)
        elif val is False or (isinstance(val, str) and val.strip().lower() in {'fail', 'failed', 'false'}):
            failed.append(chk)
        else:
            missing.append(chk)

    warnings = []
    if failed:
        warnings.append(f'subfield_preset:{key}:failed_checks:{",".join(failed)}')
    if missing:
        warnings.append(f'subfield_preset:{key}:missing_checks:{",".join(missing)}')

    return {
        'preset': key,
        'label': spec['label'],
        'required_checks': req_checks,
        'passed_checks': passed,
        'failed_checks': failed,
        'missing_checks': missing,
        'subfield_checks_passed': (not failed and (not missing if strict else True)),
        'all_required_verified': (not failed and not missing),
        'readiness_guidance': spec['readiness_guidance'],
        'readiness_warnings': warnings,
    }


def translate_to_native_scales(
    weighted_unrounded,
    *,
    fatal_gate_triggered=False,
    ratings=None,
    reviewer_confidence=None,
    reviewer_panel=None,
):
    """Map /10 weighted score to ARR 1-5, NeurIPS 1-6, ICLR 1-10+conf, and Journal bands deterministically."""
    with localcontext(BasicContext) as ctx:
        ctx.prec = 28
        raw_dec = _to_decimal_or_none(weighted_unrounded)
        if raw_dec is None:
            return None

        # Resolve ICLR reviewer confidence strictly from supplied panel or declared integer (never invented)
        conf_val = None
        conf_source = 'not_provided'
        if isinstance(reviewer_panel, list) and reviewer_panel:
            confs = [
                r['confidence'] for r in reviewer_panel
                if isinstance(r, dict) and type(r.get('confidence')) is int and 1 <= r['confidence'] <= 5
            ]
            if confs:
                mean_c = (sum(Decimal(c) for c in confs) / Decimal(len(confs))).quantize(
                    Decimal('0.01'), rounding=ROUND_HALF_UP
                )
                conf_val = float(str(mean_c))
                conf_source = 'reviewer_panel'
        if conf_val is None and reviewer_confidence is not None:
            if type(reviewer_confidence) is not int or not (1 <= reviewer_confidence <= 5):
                raise ValueError('reviewer_confidence must be an integer in 1..5')
            conf_val = reviewer_confidence
            conf_source = 'declared'

        # ARR 1-5 (0.5 increments): >=3.5 strong, 3.0 borderline, <3.0 below bar
        if raw_dec < Decimal('4.00'):
            arr_score = Decimal('1.5')
        elif raw_dec < Decimal('5.00'):
            arr_score = Decimal('2.0')
        elif raw_dec < Decimal('5.80'):
            arr_score = Decimal('2.5')
        elif raw_dec < Decimal('6.80'):
            arr_score = Decimal('3.0')
        elif raw_dec < Decimal('7.50'):
            arr_score = Decimal('3.5')
        elif raw_dec < Decimal('8.50'):
            arr_score = Decimal('4.0')
        elif raw_dec < Decimal('9.30'):
            arr_score = Decimal('4.5')
        else:
            arr_score = Decimal('5.0')
        if fatal_gate_triggered and arr_score > Decimal('2.5'):
            arr_score = Decimal('2.5')
        if arr_score >= Decimal('3.5'):
            arr_band = 'strong'
        elif arr_score == Decimal('3.0'):
            arr_band = 'borderline'
        else:
            arr_band = 'below_bar'

        # NeurIPS 1-6 (4 = borderline accept)
        if raw_dec < Decimal('4.00'):
            neurips_score = 1
        elif raw_dec < Decimal('5.00'):
            neurips_score = 2
        elif raw_dec < Decimal('6.00'):
            neurips_score = 3
        elif raw_dec < Decimal('6.80'):
            neurips_score = 4
        elif raw_dec < Decimal('7.80'):
            neurips_score = 5
        else:
            neurips_score = 6
        if fatal_gate_triggered and neurips_score > 3:
            neurips_score = 3
        neurips_labels = {
            1: 'strong_reject',
            2: 'reject',
            3: 'borderline_reject',
            4: 'borderline_accept',
            5: 'accept',
            6: 'strong_accept',
        }

        # ICLR 1-10 (6 = weak accept, 8 = strong accept)
        if raw_dec < Decimal('3.50'):
            iclr_score = 2
        elif raw_dec < Decimal('4.50'):
            iclr_score = 3
        elif raw_dec < Decimal('6.00'):
            iclr_score = 5
        elif raw_dec < Decimal('6.80'):
            iclr_score = 6
        elif raw_dec < Decimal('7.50'):
            iclr_score = 7
        elif raw_dec < Decimal('8.50'):
            iclr_score = 8
        elif raw_dec < Decimal('9.30'):
            iclr_score = 9
        else:
            iclr_score = 10
        if fatal_gate_triggered and iclr_score > 3:
            iclr_score = 3
        if iclr_score <= 3:
            iclr_band = 'reject'
        elif iclr_score <= 5:
            iclr_band = 'marginally_below_acceptance_threshold'
        elif iclr_score <= 7:
            iclr_band = 'weak_accept'
        else:
            iclr_band = 'strong_accept'

        # Journal decision bands
        low_core = isinstance(ratings, dict) and (
            (type(ratings.get('soundness')) is int and ratings['soundness'] <= 5)
            or (type(ratings.get('evidence')) is int and ratings['evidence'] <= 5)
        )
        all_ge_6 = isinstance(ratings, dict) and all(
            type(ratings.get(d)) is int and ratings[d] >= 6
            for d in DIMENSIONS if d in ratings
        )
        if fatal_gate_triggered or raw_dec < Decimal('5.50'):
            journal_decision = 'Reject'
        elif raw_dec < Decimal('6.35'):
            journal_decision = 'Major Revision'
        elif raw_dec < Decimal('7.50'):
            journal_decision = 'Major Revision' if low_core else 'Minor Revision'
        else:
            journal_decision = 'Accept' if all_ge_6 else 'Minor Revision'

    return {
        'arr_1_to_5': {
            'score': float(str(arr_score)),
            'band': arr_band,
            'capped_by_fatal_gate': bool(fatal_gate_triggered),
        },
        'neurips_1_to_6': {
            'score': neurips_score,
            'band': neurips_labels[neurips_score],
            'capped_by_fatal_gate': bool(fatal_gate_triggered),
        },
        'iclr_1_to_10': {
            'score': iclr_score,
            'band': iclr_band,
            'confidence': conf_val,
            'confidence_source': conf_source,
            'capped_by_fatal_gate': bool(fatal_gate_triggered),
        },
        'journal_decision': journal_decision,
        'note': 'Deterministic scale translation from weighted /10 and fatal gates; zero invented acceptance probability.',
    }


def _validate_ratings_and_weights(weights, ratings, active_dims):
    if not isinstance(weights, dict) or not isinstance(ratings, dict):
        raise ValueError('Weights and ratings must be JSON objects')
    if set(weights) != set(active_dims) or set(ratings) != set(active_dims):
        raise ValueError('Exactly six named dimensions are required')
    if any(type(v) is not int or v < 0 or v > 100 for v in weights.values()):
        raise ValueError('Weights must be integer percentages in 0..100')
    if sum(weights.values()) != 100:
        raise ValueError('Weights must sum to 100')
    if any(v is not None and (type(v) is not int or v < 0 or v > 10) for v in ratings.values()):
        raise ValueError('Ratings must be integers in 0..10 or null')


def simulate_reviewer_panel(
    reviewer_panel,
    weights,
    *,
    active_dims=DIMENSIONS,
    fatal_thresholds=FATAL_THRESHOLDS,
    aggregate_fatal_gate=False,
):
    if not isinstance(reviewer_panel, list) or len(reviewer_panel) < 3:
        raise ValueError('reviewer_panel must be a list of at least 3 reviewers')
    summaries = []
    seen_ids = set()
    with localcontext(BasicContext) as ctx:
        ctx.prec = 28
        for idx, rev in enumerate(reviewer_panel):
            if not isinstance(rev, dict):
                raise ValueError(f'reviewer_panel[{idx}] must be a JSON object')
            rid = str(rev.get('reviewer_id') or rev.get('id') or f'R{idx + 1}').strip()
            if not rid or rid in seen_ids:
                raise ValueError(f'reviewer_panel[{idx}] duplicate or blank reviewer_id')
            seen_ids.add(rid)
            role = str(rev.get('role') or f'reviewer_{idx + 1}').strip()
            if not role:
                raise ValueError(f'reviewer_panel[{idx}] role must be nonblank')
            conf = rev.get('confidence')
            if type(conf) is not int or not (1 <= conf <= 5):
                raise ValueError(f'reviewer_panel[{idx}].confidence must be integer in 1..5')
            r_ratings = rev.get('ratings')
            if not isinstance(r_ratings, dict) or set(r_ratings) != set(active_dims):
                raise ValueError(f'reviewer_panel[{idx}].ratings must contain all 6 dimensions')
            if any(type(v) is not int or v < 0 or v > 10 for v in r_ratings.values()):
                raise ValueError(f'reviewer_panel[{idx}].ratings must be integers in 0..10')

            raw_r = sum(Decimal(weights[d]) * Decimal(r_ratings[d]) for d in active_dims) / Decimal(100)
            fatal_dims = [d for d in active_dims if r_ratings[d] <= fatal_thresholds[d]]
            verified_fatal = bool(rev.get('verified_fatal_defect'))
            summaries.append({
                'reviewer_id': rid,
                'role': role,
                'confidence': conf,
                'ratings': dict(r_ratings),
                'raw_dec': raw_r,
                'weighted_unrounded': str(raw_r),
                'fatal_dimensions': fatal_dims,
                'has_fatal_defect': bool(fatal_dims) or verified_fatal,
                'verified_fatal_defect': verified_fatal or (bool(fatal_dims) and conf >= 3),
            })

        total_conf = sum(s['confidence'] for s in summaries)
        conf_mean_dec = (
            sum(Decimal(s['confidence']) * s['raw_dec'] for s in summaries) / Decimal(total_conf)
        ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        unweighted_mean_dec = (
            sum(s['raw_dec'] for s in summaries) / Decimal(len(summaries))
        ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        scores_dec = [s['raw_dec'] for s in summaries]
        min_dec = min(scores_dec)
        max_dec = max(scores_dec)
        spread_dec = (max_dec - min_dec).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        var_dec = sum((s_d - unweighted_mean_dec) ** 2 for s_d in scores_dec) / Decimal(len(scores_dec))
        std_dev_val = round(math.sqrt(float(str(var_dec))), 2)
        std_dev_dec = Decimal(str(std_dev_val))

        if spread_dec >= Decimal('1.50') or std_dev_dec >= Decimal('0.75') or (
            max_dec >= Decimal('6.80') and min_dec < Decimal('5.50')
        ):
            variance_risk = 'high_disagreement'
        elif spread_dec >= Decimal('0.75') or std_dev_dec >= Decimal('0.35'):
            variance_risk = 'moderate'
        else:
            variance_risk = 'low'

        assassin_ids = [
            s['reviewer_id'] for s in summaries
            if s['has_fatal_defect']
            or s['raw_dec'] <= Decimal('4.50')
            or (s['raw_dec'] <= conf_mean_dec - Decimal('1.50') and s['confidence'] >= 3)
        ]
        champion_ids = [
            s['reviewer_id'] for s in summaries
            if not s['has_fatal_defect']
            and (s['raw_dec'] >= Decimal('7.50') or (s['raw_dec'] >= Decimal('7.00') and s['confidence'] >= 4))
        ]
        assassin_flag = bool(assassin_ids)
        champion_flag = bool(champion_ids)

        verified_fatal_present = bool(aggregate_fatal_gate) or any(s['verified_fatal_defect'] for s in summaries)
        if verified_fatal_present:
            ac_verdict = 'reject_fatal_defect'
            ac_rationale = (
                'Area Chair blocks acceptance: verified fatal defect or fatal gate cannot be averaged away '
                'by high mean or champion scores.'
            )
        elif conf_mean_dec < Decimal('5.00'):
            ac_verdict = 'reject'
            ac_rationale = f'Confidence-weighted mean {conf_mean_dec} < 5.00; reject.'
        elif conf_mean_dec < Decimal('6.00'):
            ac_verdict = 'reject_workshop_level'
            ac_rationale = f'Confidence-weighted mean {conf_mean_dec} in 5.00-5.99; below archival bar.'
        elif conf_mean_dec < Decimal('6.80'):
            if variance_risk == 'high_disagreement' or assassin_flag:
                ac_verdict = 'borderline_high_variance_risk'
                ac_rationale = (
                    f'Confidence-weighted mean {conf_mean_dec} with {variance_risk}; '
                    'outcome depends on rebuttal resolving critical reviewer concerns.'
                )
            else:
                ac_verdict = 'borderline_discussion_needed'
                ac_rationale = f'Confidence-weighted mean {conf_mean_dec}; borderline AC discussion needed.'
        else:
            if variance_risk == 'high_disagreement' or assassin_flag:
                ac_verdict = 'accept_pending_rebuttal'
                ac_rationale = (
                    f'Confidence-weighted mean {conf_mean_dec} >= 6.80 but variance/assassin flag raised; '
                    'rebuttal must resolve outlier objections.'
                )
            else:
                ac_verdict = 'accept'
                ac_rationale = f'Confidence-weighted mean {conf_mean_dec} >= 6.80 without fatal defects or high variance.'

        per_dim_min = {
            d: min(s['ratings'][d] for s in summaries)
            for d in active_dims
        }
        worst_composite_dec = (
            sum(Decimal(weights[d]) * Decimal(per_dim_min[d]) for d in active_dims) / Decimal(100)
        )
        worst_rev = min(summaries, key=lambda s: (s['raw_dec'], -s['confidence'], s['reviewer_id']))
        min_q = min_dec.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        max_q = max_dec.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        worst_rev_q = worst_rev['raw_dec'].quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        worst_comp_q = worst_composite_dec.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    return {
        'reviewer_count': len(summaries),
        'confidence_weighted_mean': float(str(conf_mean_dec)),
        'unweighted_mean': float(str(unweighted_mean_dec)),
        'min_score': float(str(min_q)),
        'max_score': float(str(max_q)),
        'spread': float(str(spread_dec)),
        'std_dev': std_dev_val,
        'variance_risk': variance_risk,
        'assassin_reviewer_flag': assassin_flag,
        'assassin_reviewer_ids': assassin_ids,
        'champion_flag': champion_flag,
        'champion_reviewer_ids': champion_ids,
        'panel_verified_fatal_defect': any(s['verified_fatal_defect'] for s in summaries),
        'fatal_defect_blocks_averaging': verified_fatal_present,
        'meta_review_verdict': ac_verdict,
        'meta_review_rationale': ac_rationale,
        'worst_case_reviewer_floor': {
            'worst_reviewer_id': worst_rev['reviewer_id'],
            'worst_reviewer_score': float(str(worst_rev_q)),
            'per_dimension_min_across_reviewers': per_dim_min,
            'worst_case_composite_score': float(str(worst_comp_q)),
        },
        'per_reviewer_summary': [
            {
                'reviewer_id': s['reviewer_id'],
                'role': s['role'],
                'confidence': s['confidence'],
                'weighted_unrounded': s['weighted_unrounded'],
                'fatal_dimensions': s['fatal_dimensions'],
                'has_fatal_defect': s['has_fatal_defect'],
            }
            for s in summaries
        ],
    }


def detect_halo_sanity_warnings(
    ratings,
    context=None,
    *,
    active_dims=DIMENSIONS,
    related_count=None,
    unread_closest_count=None,
):
    if not isinstance(ratings, dict):
        return []
    ctx = context if isinstance(context, dict) else {}
    warnings = []

    if 'soundness' in active_dims:
        snd = ratings.get('soundness')
        tr = ratings.get('transparency')
        cl = ratings.get('clarity')
        if type(snd) is int and type(tr) is int and snd >= 8 and tr <= 4:
            warnings.append('halo_warning:high_soundness_low_transparency')
        if type(cl) is int and type(snd) is int and cl >= 9 and snd <= 4:
            warnings.append('halo_warning:high_clarity_with_fatal_soundness')

    ev_key = 'evidence_coverage' if 'evidence_coverage' in active_dims else 'evidence'
    ev = ratings.get(ev_key)
    if type(ev) is int and ev >= 8:
        ev_rigor = ctx.get('evidence_rigor') if isinstance(ctx.get('evidence_rigor'), dict) else {}
        has_explicit_support = bool(
            ev_rigor.get('has_ci_or_error_bars')
            or ev_rigor.get('has_ablation')
            or (type(ev_rigor.get('seed_count')) is int and ev_rigor['seed_count'] >= 3)
            or ctx.get('has_ci_or_error_bars') is True
            or ctx.get('has_ablation') is True
            or (type(ctx.get('seed_count')) is int and ctx['seed_count'] >= 3)
            or (isinstance(ctx.get('ablation_results'), (list, dict)) and bool(ctx.get('ablation_results')))
        )
        text_blobs = []
        locators = ctx.get('evidence_locators') if isinstance(ctx.get('evidence_locators'), dict) else {}
        for lk in (ev_key, 'evidence', 'soundness'):
            lv = locators.get(lk)
            if isinstance(lv, list):
                text_blobs.extend(str(x) for x in lv if isinstance(x, str))
        for tk in ('evidence_notes', 'notes', 'ablation_summary', 'statistical_summary'):
            tv = ctx.get(tk)
            if isinstance(tv, str):
                text_blobs.append(tv)
        blob = ' '.join(text_blobs).lower()
        cue_pat = r'(?:95%\s*ci|confidence\s+intervals?|error\s+bars?|p-values?|ablations?|seeds?|bootstrap|std|ci)'
        neg_pat = r'(?:no|without|lacks?|missing|absent|neither)'
        blob_clean = re.sub(
            rf'\b{neg_pat}\s+(?:[a-z0-9-]+\s+){{0,3}}(?:(?:and|or|nor)\s+)?{cue_pat}'
            rf'(?:\s*(?:,|/|and|or|nor)\s*(?:[a-z0-9-]+\s+){{0,2}}{cue_pat}){{0,4}}\b'
            r'|\bsingle\s+seed\b|\bonly\s+(?:1|one)\s+seed\b',
            ' ',
            blob,
        )
        has_text_cue = bool(re.search(
            r'\b(?:ci|95%\s*ci|confidence\s+interval|seed|seeds|ablation|ablations|std|error\s+bar|p-value|bootstrap)\b',
            blob_clean,
        ))
        if not has_explicit_support and not has_text_cue:
            warnings.append('halo_warning:high_evidence_without_ci_seed_or_ablation')

    nov = ratings.get('novelty')
    if type(nov) is int and nov >= 8:
        cw = ctx.get('closest_work')
        cw_count = len([x for x in cw if isinstance(x, str) and x.strip()]) if isinstance(cw, list) else None
        rb = ctx.get('reading_basis')
        thin_cw = cw_count is not None and cw_count < 3
        unread_basis = rb is not None and rb != 'full_text'
        thin_related = related_count is not None and related_count < 3
        unread_cw = unread_closest_count is not None and unread_closest_count > 0
        if thin_cw or unread_basis or thin_related or unread_cw:
            warnings.append('halo_warning:high_novelty_with_thin_or_unread_closest_work')

    feas = ratings.get('feasibility')
    res_feas = ctx.get('resource_feasibility')
    if type(feas) is int and feas >= 8 and isinstance(res_feas, dict) and res_feas.get('infeasible_under_user_resources') is True:
        warnings.append('halo_warning:high_feasibility_despite_resource_infeasibility')

    return warnings


def _greedy_lift_plan(
    weights,
    ratings,
    *,
    active_dims=DIMENSIONS,
    fatal_thresholds=FATAL_THRESHOLDS,
    target_weighted=None,
    venue_tier=None,
    venue_type=None,
    clear_fatal=False,
    clear_tier=False,
    is_idea=False,
    non_rating_fatal_gate=False,
):
    if is_idea and (clear_fatal or clear_tier or target_weighted is not None):
        # Unrun ideas remain blocked from archival submission regardless of hypothetical lifts
        pass
    cur = dict(ratings)
    steps = []
    floor = None
    if venue_type in VENUE_TYPE_PROFILES:
        vprof = VENUE_TYPE_PROFILES[venue_type]
        floor = {
            'min_viable_overall': vprof['min_viable_overall'],
            'competitive_overall': vprof['competitive_overall'],
            'min_dimensions': vprof['min_dimensions'],
            'min_any_dimension': vprof['min_any_dimension'],
        }
    elif venue_tier in VENUE_TIER_FLOORS:
        floor = VENUE_TIER_FLOORS[venue_tier]

    def _add_step(dim, new_val, reason):
        old_val = cur[dim]
        if new_val <= old_val:
            return
        cur[dim] = new_val
        steps.append({
            'dimension': dim,
            'from': old_val,
            'to': new_val,
            'delta': new_val - old_val,
            'reason': reason,
        })

    with localcontext(BasicContext) as ctx:
        ctx.prec = 28
        if clear_fatal or clear_tier or target_weighted is not None:
            for d in active_dims:
                if cur[d] <= fatal_thresholds[d]:
                    _add_step(d, min(10, fatal_thresholds[d] + 1), f'clear_fatal_threshold_{d}<={fatal_thresholds[d]}')
        if clear_tier and floor is not None:
            for d, min_v in floor['min_dimensions'].items():
                if d in cur and cur[d] < min_v:
                    _add_step(d, min_v, f'meet_tier_min_{d}>={min_v}')
            min_any = floor['min_any_dimension']
            for d in active_dims:
                if cur[d] < min_any:
                    _add_step(d, min_any, f'meet_tier_any_dim>={min_any}')

        goal_w = target_weighted
        if clear_tier and floor is not None:
            tier_w = floor['min_viable_overall']
            goal_w = tier_w if goal_w is None else max(goal_w, tier_w)

        def _raw_w(r_map):
            return sum(Decimal(weights[d]) * Decimal(r_map[d]) for d in active_dims) / Decimal(100)

        while goal_w is not None and _raw_w(cur) < goal_w:
            candidates = [
                d for d in active_dims
                if cur[d] < 10 and weights[d] > 0
            ]
            if not candidates:
                break
            best_d = max(candidates, key=lambda d: (weights[d], -cur[d], -active_dims.index(d)))
            _add_step(best_d, cur[best_d] + 1, f'lift_weighted_toward_{goal_w}')

        final_w = _raw_w(cur)
        still_fatal = is_idea or bool(non_rating_fatal_gate) or any(cur[d] <= fatal_thresholds[d] for d in active_dims)
        still_tier_rej = False
        if floor is not None:
            if final_w < floor['min_viable_overall']:
                still_tier_rej = True
            for d, mv in floor['min_dimensions'].items():
                if d in cur and cur[d] < mv:
                    still_tier_rej = True
            if any(cur[d] < floor['min_any_dimension'] for d in active_dims):
                still_tier_rej = True
        reachable = True
        if clear_fatal and still_fatal:
            reachable = False
        if clear_tier and (still_tier_rej or is_idea):
            reachable = False
        if goal_w is not None and final_w < goal_w:
            reachable = False

    # Collapse multiple +1 steps on the same dimension cleanly while preserving order
    merged = {}
    for st in steps:
        d = st['dimension']
        if d not in merged:
            merged[d] = dict(st)
        else:
            merged[d]['to'] = st['to']
            merged[d]['delta'] += st['delta']
            if st['reason'] not in merged[d]['reason']:
                merged[d]['reason'] += f"; {st['reason']}"
    merged_steps = sorted(
        merged.values(),
        key=lambda s: (-weights[s['dimension']], -s['delta'], active_dims.index(s['dimension'])),
    )
    return {
        'reachable': reachable,
        'blocked_by_unrun_idea': bool(is_idea),
        'blocked_by_non_rating_fatal_gate': bool(non_rating_fatal_gate),
        'total_points_added': sum(s['delta'] for s in merged_steps),
        'resulting_weighted': str(final_w),
        'steps': merged_steps,
    }


def simulate_what_if_roi(
    weights,
    ratings,
    *,
    active_dims=DIMENSIONS,
    fatal_thresholds=FATAL_THRESHOLDS,
    venue_tier=None,
    venue_type=None,
    is_idea=False,
    non_rating_fatal_gate=False,
):
    """Simulate minimal +1/+2 single-axis upgrades and minimal multi-axis paths ranked by ROI leverage."""
    with localcontext(BasicContext) as ctx:
        ctx.prec = 28
        base_raw = sum(Decimal(weights[d]) * Decimal(ratings[d]) for d in active_dims) / Decimal(100)
        eff_tier = VENUE_TYPE_PROFILES[venue_type]['venue_tier'] if venue_type in VENUE_TYPE_PROFILES else venue_tier
        venue_bar = VENUE_TYPE_PROFILES[venue_type]['competitive_overall'] if venue_type in VENUE_TYPE_PROFILES else (
            VENUE_TIER_FLOORS[eff_tier]['competitive_overall'] if eff_tier in VENUE_TIER_FLOORS else TOP_TIER_COMPETITIVE_THRESHOLD
        )
        base_fatal = is_idea or bool(non_rating_fatal_gate) or any(ratings[d] <= fatal_thresholds[d] for d in active_dims)
        base_tier_rej = False
        if (eff_tier in VENUE_TIER_FLOORS or venue_type in VENUE_TYPE_PROFILES) and active_dims == DIMENSIONS:
            base_tier_rej = evaluate_venue_tier_fit(
                eff_tier, weighted_unrounded=base_raw, ratings=ratings, is_idea=is_idea, venue_type=venue_type
            )['rejected_below_venue_tier']

        single_moves = []
        for d in active_dims:
            is_blocking_fatal = ratings[d] <= fatal_thresholds[d]
            for step in (1, 2):
                if ratings[d] + step > 10:
                    continue
                mod_r = dict(ratings)
                mod_r[d] = ratings[d] + step
                new_raw = sum(Decimal(weights[k]) * Decimal(mod_r[k]) for k in active_dims) / Decimal(100)
                gain = (new_raw - base_raw).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                new_fatal = is_idea or bool(non_rating_fatal_gate) or any(mod_r[k] <= fatal_thresholds[k] for k in active_dims)
                new_tier_rej = False
                if (eff_tier in VENUE_TIER_FLOORS or venue_type in VENUE_TYPE_PROFILES) and active_dims == DIMENSIONS:
                    new_tier_rej = evaluate_venue_tier_fit(
                        eff_tier, weighted_unrounded=new_raw, ratings=mod_r, is_idea=is_idea, venue_type=venue_type
                    )['rejected_below_venue_tier']
                clears_fatal = bool(base_fatal and not new_fatal)
                clears_tier = bool(base_tier_rej and not new_tier_rej)
                clears_6_00 = bool(base_raw < Decimal('6.00') <= new_raw and not new_fatal)
                clears_6_80 = bool(base_raw < Decimal('6.80') <= new_raw and not new_fatal)
                gate_priority = 2 if clears_fatal else (1 if (clears_tier or is_blocking_fatal) else 0)
                leverage = float(str((Decimal(weights[d]) / Decimal(100)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)))
                single_moves.append({
                    'dimension': d,
                    'step': step,
                    'from_rating': ratings[d],
                    'new_rating': mod_r[d],
                    'new_weighted_unrounded': str(new_raw),
                    'weighted_gain': float(str(gain)),
                    'roi_leverage_per_point': leverage,
                    'gate_clearing_priority': gate_priority,
                    'clears_fatal_gate': clears_fatal,
                    'clears_tier_rejection': clears_tier,
                    'clears_6_00': clears_6_00,
                    'clears_6_80': clears_6_80,
                })

        single_moves.sort(
            key=lambda m: (
                -m['gate_clearing_priority'],
                -(1 if m['clears_6_80'] or m['clears_6_00'] else 0),
                -m['roi_leverage_per_point'],
                m['step'],
                m['from_rating'],
                active_dims.index(m['dimension']),
            )
        )

        minimal_paths = {
            'clear_fatal_gate': _greedy_lift_plan(
                weights, ratings, active_dims=active_dims, fatal_thresholds=fatal_thresholds,
                clear_fatal=True, is_idea=is_idea, non_rating_fatal_gate=non_rating_fatal_gate,
            ),
            'reach_6_00': _greedy_lift_plan(
                weights, ratings, active_dims=active_dims, fatal_thresholds=fatal_thresholds,
                target_weighted=Decimal('6.00'), clear_fatal=True, is_idea=is_idea,
                non_rating_fatal_gate=non_rating_fatal_gate,
            ),
            'reach_6_80': _greedy_lift_plan(
                weights, ratings, active_dims=active_dims, fatal_thresholds=fatal_thresholds,
                target_weighted=Decimal('6.80'), clear_fatal=True, is_idea=is_idea,
                non_rating_fatal_gate=non_rating_fatal_gate,
            ),
            'reach_venue_competitive_bar': _greedy_lift_plan(
                weights, ratings, active_dims=active_dims, fatal_thresholds=fatal_thresholds,
                target_weighted=venue_bar, venue_tier=eff_tier, venue_type=venue_type,
                clear_fatal=True, clear_tier=bool(eff_tier or venue_type in VENUE_TYPE_PROFILES),
                is_idea=is_idea, non_rating_fatal_gate=non_rating_fatal_gate,
            ),
        }
        if eff_tier in VENUE_TIER_FLOORS or venue_type in VENUE_TYPE_PROFILES:
            minimal_paths['clear_venue_tier_rejection'] = _greedy_lift_plan(
                weights, ratings, active_dims=active_dims, fatal_thresholds=fatal_thresholds,
                venue_tier=eff_tier, venue_type=venue_type,
                clear_fatal=True, clear_tier=True, is_idea=is_idea,
                non_rating_fatal_gate=non_rating_fatal_gate,
            )

    return {
        'baseline_weighted_unrounded': str(base_raw),
        'venue_competitive_bar': float(str(venue_bar)),
        'blocked_by_unrun_idea': bool(is_idea),
        'blocked_by_non_rating_fatal_gate': bool(non_rating_fatal_gate),
        'single_axis_upgrades': single_moves,
        'minimal_paths': minimal_paths,
    }


def _extract_receipt_digests(profile):
    """Extract normalized 64-hex SHA-256 receipt entries from a profile/document."""
    out = {}
    if not isinstance(profile, dict):
        return out
    raw_list = []
    for key in ('run_receipts', 'experiment_receipts', 'receipts'):
        val = profile.get(key)
        if isinstance(val, list):
            raw_list.extend(val)
        elif isinstance(val, dict):
            raw_list.append(val)
    for item in raw_list:
        if isinstance(item, str):
            s = item.strip()
            if s.lower().startswith('sha256:'):
                s = s.split(':', 1)[1].strip()
            if HEX64_RE.match(s):
                out[s.lower()] = {'sha256': s.lower(), 'path': None, 'dimensions': None}
        elif isinstance(item, dict):
            h = str(item.get('sha256') or item.get('hash') or '').strip()
            if h.lower().startswith('sha256:'):
                h = h.split(':', 1)[1].strip()
            if HEX64_RE.match(h):
                dims = item.get('dimensions')
                out[h.lower()] = {
                    'sha256': h.lower(),
                    'path': item.get('path'),
                    'dimensions': list(dims) if isinstance(dims, list) else None,
                }
    rev_ev = profile.get('revision_evidence')
    if isinstance(rev_ev, dict):
        for dim, entry in rev_ev.items():
            items = entry if isinstance(entry, list) else [entry]
            for it in items:
                if isinstance(it, str):
                    s = it.strip()
                    if s.lower().startswith('sha256:'):
                        s = s.split(':', 1)[1].strip()
                    if HEX64_RE.match(s):
                        out[s.lower()] = {'sha256': s.lower(), 'path': None, 'dimensions': [dim]}
                elif isinstance(it, dict):
                    h = str(it.get('sha256') or '').strip()
                    if h.lower().startswith('sha256:'):
                        h = h.split(':', 1)[1].strip()
                    if HEX64_RE.match(h):
                        out[h.lower()] = {'sha256': h.lower(), 'path': it.get('path'), 'dimensions': [dim]}
    return out


def diff_scorecards(
    v1_profile,
    v2_profile,
    weights,
    *,
    active_dims=DIMENSIONS,
    fatal_thresholds=FATAL_THRESHOLDS,
    verified_v2_locators=None,
):
    """Compute per-dimension & weighted deltas, defect changes, and anti-grade-inflation audit."""
    if not isinstance(v1_profile, dict) or not isinstance(v2_profile, dict):
        raise ValueError('v1 and v2 profiles must be JSON objects')
    r1 = v1_profile.get('ratings')
    r2 = v2_profile.get('ratings')
    _validate_ratings_and_weights(weights, r1, active_dims)
    _validate_ratings_and_weights(weights, r2, active_dims)
    if any(r1[d] is None for d in active_dims) or any(r2[d] is None for d in active_dims):
        raise ValueError('Revision diff requires non-null ratings across all 6 dimensions in both v1 and v2')

    with localcontext(BasicContext) as ctx:
        ctx.prec = 28
        w1 = sum(Decimal(weights[d]) * Decimal(r1[d]) for d in active_dims) / Decimal(100)
        w2 = sum(Decimal(weights[d]) * Decimal(r2[d]) for d in active_dims) / Decimal(100)
        w_delta = (w2 - w1).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    dim_deltas = {d: r2[d] - r1[d] for d in active_dims}
    v1_fatal = {d for d in active_dims if r1[d] <= fatal_thresholds[d]}
    v2_fatal = {d for d in active_dims if r2[d] <= fatal_thresholds[d]}
    v1_bottle = {d for d in active_dims if r1[d] <= 5}
    v2_bottle = {d for d in active_dims if r2[d] <= 5}

    v1_defects = {
        str(x).strip()
        for x in (v1_profile.get('defects') or v1_profile.get('open_defects') or v1_profile.get('issues') or [])
        if isinstance(x, str) and x.strip()
    }
    v2_defects = {
        str(x).strip()
        for x in (v2_profile.get('defects') or v2_profile.get('open_defects') or v2_profile.get('issues') or [])
        if isinstance(x, str) and x.strip()
    }

    v1_locs = v1_profile.get('evidence_locators') if isinstance(v1_profile.get('evidence_locators'), dict) else {}
    v2_locs = v2_profile.get('evidence_locators') if isinstance(v2_profile.get('evidence_locators'), dict) else {}
    v1_receipts = _extract_receipt_digests(v1_profile)
    v2_receipts = _extract_receipt_digests(v2_profile)
    new_receipts = {k: v for k, v in v2_receipts.items() if k not in v1_receipts}

    unsubstantiated = []
    inflation_warnings = []
    gain_evidence = {}
    for d in active_dims:
        delta_d = dim_deltas[d]
        if delta_d <= 0:
            continue
        old_set = {x.strip() for x in (v1_locs.get(d) or []) if isinstance(x, str) and x.strip()}
        cur_list = [x.strip() for x in (v2_locs.get(d) or []) if isinstance(x, str) and x.strip()]
        new_locs = [x for x in cur_list if x not in old_set]
        if verified_v2_locators is not None:
            verified_new = [x for x in new_locs if (d, x) in verified_v2_locators]
        else:
            verified_new = new_locs
        dim_new_receipts = [
            h for h, info in new_receipts.items()
            if info['dimensions'] is None or d in info['dimensions']
        ]
        gain_evidence[d] = {
            'delta': delta_d,
            'new_locators': new_locs,
            'verified_new_locators': verified_new,
            'new_sha256_receipts': dim_new_receipts,
        }
        if not verified_new and not dim_new_receipts:
            unsubstantiated.append(d)
            inflation_warnings.append(
                f'unsubstantiated_score_gain:{d}:+{delta_d}:missing_new_locator_or_sha256_receipt'
            )

    suspected = bool(unsubstantiated)
    return {
        'status': 'grade_inflation_suspected' if suspected else 'verified_revision',
        'suspected_grade_inflation': suspected,
        'v1_weighted_unrounded': str(w1),
        'v2_weighted_unrounded': str(w2),
        'weighted_delta': float(str(w_delta)),
        'dimension_deltas': dim_deltas,
        'unsubstantiated_gain_dimensions': unsubstantiated,
        'inflation_warnings': inflation_warnings,
        'gain_evidence': gain_evidence,
        'resolved_fatal_dimensions': sorted(v1_fatal - v2_fatal),
        'remaining_fatal_dimensions': sorted(v1_fatal & v2_fatal),
        'newly_introduced_fatal_dimensions': sorted(v2_fatal - v1_fatal),
        'resolved_bottleneck_dimensions': sorted(v1_bottle - v2_bottle),
        'remaining_bottleneck_dimensions': sorted(v1_bottle & v2_bottle),
        'resolved_v1_defects': sorted(v1_defects - v2_defects),
        'remaining_v1_defects': sorted(v1_defects & v2_defects),
        'newly_introduced_defects': sorted(v2_defects - v1_defects),
    }


def build_evidence_anchor_table(target_entry, anchor_entries):
    """Build F30#5 side-by-side evidence anchor table across 2-3 verified accepted papers (zero fabrication)."""
    if not isinstance(target_entry, dict):
        raise ValueError('target_entry must be a JSON object')
    if not isinstance(anchor_entries, list) or not anchor_entries:
        return None

    def _row(entry, is_target=False):
        prof = entry.get('evidence_profile') if isinstance(entry.get('evidence_profile'), dict) else {}
        anchors = entry.get('evidence_anchors') if isinstance(entry.get('evidence_anchors'), dict) else {}
        src = {**prof, **anchors}

        def _pick(key):
            if key in src and src[key] is not None:
                return src[key]
            if key in entry and entry[key] is not None:
                return entry[key]
            return None

        b_cnt = _pick('benchmarks_count')
        if b_cnt is not None and (type(b_cnt) is not int or b_cnt < 0):
            raise ValueError('benchmarks_count must be a non-negative integer or null')
        sota = _pick('sota_baselines_covered')
        if type(sota) is int and sota < 0:
            raise ValueError('sota_baselines_covered must be a non-negative integer or list')
        sota_count = len(sota) if isinstance(sota, list) else (sota if type(sota) is int else None)
        ablation = _pick('ablation_depth')
        theory = _pick('theoretical_rigor')
        ci_stab = _pick('effect_size_ci_stability')
        code_open = _pick('code_artifact_openness')
        return {
            'id': str(entry.get('id') or ('target' if is_target else 'anchor')),
            'role': 'target' if is_target else 'accepted_anchor',
            'topic_relation': None if is_target else (entry.get('topic_relation') or 'unspecified'),
            'reading_basis': entry.get('reading_basis') or 'unspecified',
            'benchmarks_count': b_cnt,
            'sota_baselines_covered': sota if sota is not None else 'unreported',
            'sota_baselines_count': sota_count,
            'ablation_depth': ablation if ablation is not None else 'unreported',
            'theoretical_rigor': theory if theory is not None else 'unreported',
            'effect_size_ci_stability': ci_stab if ci_stab is not None else 'unreported',
            'code_artifact_openness': code_open if code_open is not None else 'unreported',
        }

    t_row = _row(target_entry, is_target=True)
    a_rows = [_row(a, is_target=False) for a in anchor_entries[:3] if isinstance(a, dict)]
    if not a_rows:
        return None
    warnings = []
    if len(a_rows) < 2:
        warnings.append(f'fewer_than_two_evidence_anchors:{len(a_rows)}')
    for ar in a_rows:
        if ar['reading_basis'] != 'full_text':
            warnings.append(f"anchor_not_full_text:{ar['id']}")

    b_vals = sorted(ar['benchmarks_count'] for ar in a_rows if type(ar['benchmarks_count']) is int)
    b_med = None
    b_delta = None
    if b_vals:
        mid = len(b_vals) // 2
        b_med = b_vals[mid] if len(b_vals) % 2 == 1 else (b_vals[mid - 1] + b_vals[mid]) / 2.0
        if type(t_row['benchmarks_count']) is int:
            b_delta = round(float(t_row['benchmarks_count']) - b_med, 2)

    s_vals = sorted(ar['sota_baselines_count'] for ar in a_rows if type(ar['sota_baselines_count']) is int)
    s_med = None
    s_delta = None
    if s_vals:
        mid = len(s_vals) // 2
        s_med = s_vals[mid] if len(s_vals) % 2 == 1 else (s_vals[mid - 1] + s_vals[mid]) / 2.0
        if type(t_row['sota_baselines_count']) is int:
            s_delta = round(float(t_row['sota_baselines_count']) - s_med, 2)

    same_cnt = sum(1 for ar in a_rows if ar['topic_relation'] == 'same_topic')
    cross_cnt = sum(1 for ar in a_rows if ar['topic_relation'] in {'adjacent_topic', 'different_topic'})

    return {
        'axes': [
            'benchmarks_count',
            'sota_baselines_covered',
            'ablation_depth',
            'theoretical_rigor',
            'effect_size_ci_stability',
            'code_artifact_openness',
        ],
        'anchor_count': len(a_rows),
        'same_topic_anchor_count': same_cnt,
        'cross_topic_anchor_count': cross_cnt,
        'target': t_row,
        'anchors': a_rows,
        'target_vs_anchors_summary': {
            'anchor_median_benchmarks_count': b_med,
            'target_benchmarks_delta': b_delta,
            'anchor_median_sota_baselines_count': s_med,
            'target_sota_baselines_delta': s_delta,
            'target_reports_effect_size_ci': t_row['effect_size_ci_stability'],
            'target_code_artifact_openness': t_row['code_artifact_openness'],
        },
        'warnings': warnings,
    }


def compute_merit_vs_packaging(
    weights,
    ratings,
    *,
    active_dims=DIMENSIONS,
    fatal_thresholds=FATAL_THRESHOLDS,
):
    """Split /10 profile into scientific_merit_score vs publishability_packaging_score (Decimal-safe)."""
    if active_dims == IDEA_DIMENSIONS:
        merit_dims = IDEA_MERIT_DIMENSIONS
        pack_dims = IDEA_PACKAGING_DIMENSIONS
    else:
        merit_dims = MERIT_DIMENSIONS
        pack_dims = PACKAGING_DIMENSIONS

    with localcontext(BasicContext) as ctx:
        ctx.prec = 28
        m_w_sum = sum(weights[d] for d in merit_dims)
        p_w_sum = sum(weights[d] for d in pack_dims)
        if m_w_sum > 0:
            merit_dec = (sum(Decimal(weights[d]) * Decimal(ratings[d]) for d in merit_dims) / Decimal(m_w_sum)).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
        else:
            merit_dec = (sum(Decimal(ratings[d]) for d in merit_dims) / Decimal(len(merit_dims))).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
        if p_w_sum > 0:
            pack_dec = (sum(Decimal(weights[d]) * Decimal(ratings[d]) for d in pack_dims) / Decimal(p_w_sum)).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
        else:
            pack_dec = (sum(Decimal(ratings[d]) for d in pack_dims) / Decimal(len(pack_dims))).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
        gap_dec = (merit_dec - pack_dec).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        merit_fatal = any(ratings[d] <= fatal_thresholds[d] for d in merit_dims)
        if merit_fatal or merit_dec < Decimal('6.00'):
            diagnosis = 'deeper_science_needed'
        elif merit_dec >= Decimal('6.80') and pack_dec < Decimal('6.00'):
            diagnosis = 'packaging_and_reproducibility_bottleneck'
        elif merit_dec >= Decimal('6.80') and pack_dec >= Decimal('6.80'):
            diagnosis = 'balanced_strong'
        else:
            diagnosis = 'both_need_strengthening'

    return {
        'scientific_merit_score': float(str(merit_dec)),
        'publishability_packaging_score': float(str(pack_dec)),
        'merit_packaging_gap': float(str(gap_dec)),
        'merit_dimensions': list(merit_dims),
        'packaging_dimensions': list(pack_dims),
        'diagnosis': diagnosis,
    }


def score_section_diagnostics(section_diagnostics):
    """F30#7 optional per-section diagnostic breakdown over abstract/intro/related_work/method/experiments/limitations."""
    if section_diagnostics is None:
        return None
    if not isinstance(section_diagnostics, dict) or not section_diagnostics:
        raise ValueError('section_diagnostics must be a non-empty JSON object')

    entries = []
    scores = []
    for sec in DIAGNOSTIC_SECTIONS:
        if sec not in section_diagnostics:
            continue
        raw_val = section_diagnostics[sec]
        if type(raw_val) is int:
            if not (0 <= raw_val <= 10):
                raise ValueError(f'section_diagnostics.{sec} must be integer in 0..10')
            sec_score = raw_val
            issues = []
            locator = None
        elif isinstance(raw_val, dict):
            sec_score = raw_val.get('score')
            if type(sec_score) is not int or not (0 <= sec_score <= 10):
                raise ValueError(f'section_diagnostics.{sec}.score must be integer in 0..10')
            raw_iss = raw_val.get('issues')
            issues = [str(x).strip() for x in raw_iss if isinstance(x, str) and x.strip()] if isinstance(raw_iss, list) else []
            locator = raw_val.get('locator') if isinstance(raw_val.get('locator'), str) else None
        else:
            raise ValueError(f'section_diagnostics.{sec} must be an integer or JSON object')
        scores.append(sec_score)
        entries.append({
            'section': sec,
            'score': sec_score,
            'impacted_dimensions': list(SECTION_TO_DIMENSIONS[sec]),
            'issues': issues,
            'locator': locator,
        })

    unknown_secs = [k for k in section_diagnostics if k not in DIAGNOSTIC_SECTIONS]
    if unknown_secs:
        raise ValueError(f'Unknown diagnostic sections: {", ".join(sorted(unknown_secs))}')
    if not entries:
        raise ValueError('section_diagnostics contained no recognized sections')

    with localcontext(BasicContext) as ctx:
        ctx.prec = 28
        mean_dec = (sum(Decimal(s) for s in scores) / Decimal(len(scores))).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )

    min_s = min(scores)
    weakest = [e['section'] for e in entries if e['score'] < 6 or e['score'] == min_s]
    edit_order = sorted(
        entries,
        key=lambda e: (e['score'], -len(e['issues']), DIAGNOSTIC_SECTIONS.index(e['section'])),
    )
    return {
        'section_mean': float(str(mean_dec)),
        'sections_scored': [e['section'] for e in entries],
        'weakest_sections': weakest,
        'prioritized_edit_order': edit_order,
    }


def compute_deal_breaker_sensitivity(
    weights,
    ratings,
    *,
    active_dims=DIMENSIONS,
    fatal_thresholds=FATAL_THRESHOLDS,
    venue_tier=None,
    venue_type=None,
    reviewer_panel=None,
    is_idea=False,
):
    """F30#8 worst-case reviewer floor and per-dimension -1/+1 deal-breaker sensitivity."""
    with localcontext(BasicContext) as ctx:
        ctx.prec = 28
        base_raw = sum(Decimal(weights[d]) * Decimal(ratings[d]) for d in active_dims) / Decimal(100)
        eff_tier = VENUE_TYPE_PROFILES[venue_type]['venue_tier'] if venue_type in VENUE_TYPE_PROFILES else venue_tier
        per_dim = {}
        deal_breaker_axes = []
        non_rescuing_axes = []
        minus1_scores = []

        for d in active_dims:
            r_minus = max(0, ratings[d] - 1)
            mod_m = dict(ratings)
            mod_m[d] = r_minus
            raw_m = sum(Decimal(weights[k]) * Decimal(mod_m[k]) for k in active_dims) / Decimal(100)
            minus1_scores.append(raw_m)
            m_fatal = is_idea or any(mod_m[k] <= fatal_thresholds[k] for k in active_dims)
            m_tier_rej = False
            if (eff_tier in VENUE_TIER_FLOORS or venue_type in VENUE_TYPE_PROFILES) and active_dims == DIMENSIONS:
                m_tier_rej = evaluate_venue_tier_fit(
                    eff_tier, weighted_unrounded=raw_m, ratings=mod_m, is_idea=is_idea, venue_type=venue_type
                )['rejected_below_venue_tier']
            drops_6_00 = bool(base_raw >= Decimal('6.00') > raw_m)
            drops_6_80 = bool(base_raw >= Decimal('6.80') > raw_m)
            is_deal_breaker = bool(m_fatal or m_tier_rej or drops_6_00 or drops_6_80)
            if is_deal_breaker:
                deal_breaker_axes.append(d)

            r_plus = min(10, ratings[d] + 1)
            mod_p = dict(ratings)
            mod_p[d] = r_plus
            raw_p = sum(Decimal(weights[k]) * Decimal(mod_p[k]) for k in active_dims) / Decimal(100)
            p_fatal = is_idea or any(mod_p[k] <= fatal_thresholds[k] for k in active_dims)
            p_tier_rej = False
            if (eff_tier in VENUE_TIER_FLOORS or venue_type in VENUE_TYPE_PROFILES) and active_dims == DIMENSIONS:
                p_tier_rej = evaluate_venue_tier_fit(
                    eff_tier, weighted_unrounded=raw_p, ratings=mod_p, is_idea=is_idea, venue_type=venue_type
                )['rejected_below_venue_tier']
            cannot_rescue = bool(p_fatal or p_tier_rej or raw_p < Decimal('6.80'))
            if cannot_rescue:
                non_rescuing_axes.append(d)

            per_dim[d] = {
                'current_rating': ratings[d],
                'drop_minus_1': {
                    'new_rating': r_minus,
                    'new_weighted': float(str(raw_m.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))),
                    'triggers_fatal_gate': m_fatal,
                    'triggers_tier_rejection': m_tier_rej,
                    'drops_below_6_00': drops_6_00,
                    'drops_below_6_80': drops_6_80,
                    'is_deal_breaker': is_deal_breaker,
                },
                'lift_plus_1': {
                    'new_rating': r_plus,
                    'new_weighted': float(str(raw_p.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))),
                    'still_fatal_gate': p_fatal,
                    'still_tier_rejected': p_tier_rej,
                    'still_below_6_80': bool(raw_p < Decimal('6.80')),
                    'cannot_rescue': cannot_rescue,
                },
            }

        if isinstance(reviewer_panel, list) and len(reviewer_panel) >= 3:
            panel_res = simulate_reviewer_panel(
                reviewer_panel, weights, active_dims=active_dims, fatal_thresholds=fatal_thresholds,
            )
            worst_floor = {
                'basis': 'reviewer_panel_min',
                **panel_res['worst_case_reviewer_floor'],
            }
        else:
            min_m = min(minus1_scores)
            worst_floor = {
                'basis': 'single_axis_minus1_floor',
                'worst_case_score': float(str(min_m.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))),
            }

    return {
        'worst_case_reviewer_floor': worst_floor,
        'deal_breaker_axes': deal_breaker_axes,
        'non_rescuing_axes': non_rescuing_axes,
        'per_dimension': per_dim,
    }


def _build_idea_viability_band(ratings, raw_dec, document=None):
    doc = document if isinstance(document, dict) else {}
    fatal_dims = [d for d in IDEA_DIMENSIONS if ratings[d] is not None and ratings[d] <= IDEA_FATAL_THRESHOLDS[d]]
    dead_end = str(doc.get('gap_tier_ceiling') or '').strip() == 'low_impact_dead_end'
    if raw_dec is None:
        return None, fatal_dims
    if fatal_dims or raw_dec < Decimal('4.80') or dead_end:
        return 'kill_early', fatal_dims
    if raw_dec < Decimal('6.00') or ratings['feasibility'] <= 4 or ratings['falsifiability'] <= 4:
        return 'pivot_or_narrow', fatal_dims
    if raw_dec < Decimal('7.20') or any(ratings[d] <= 5 for d in IDEA_DIMENSIONS):
        return 'refine_and_de_risk', fatal_dims
    return 'pursue_high_priority', fatal_dims


def _build_submission_readiness(
    weights,
    ratings,
    raw,
    delta,
    is_idea,
    *,
    active_dims=DIMENSIONS,
    fatal_thresholds=FATAL_THRESHOLDS,
    venue_profile_eval=None,
    idea_viability_band=None,
):
    fatal_dimensions = [
        d for d in active_dims
        if ratings[d] is not None and ratings[d] <= fatal_thresholds[d]
    ]
    fatal_reasons = (['unrun_idea_results'] if is_idea else []) + [
        f'{d}<={fatal_thresholds[d]}' for d in fatal_dimensions
    ]
    if venue_profile_eval and venue_profile_eval.get('checks_gate_failed'):
        if venue_profile_eval.get('failed_checks'):
            fatal_reasons.append(f"venue_checks_failed:{','.join(venue_profile_eval['failed_checks'])}")
        if venue_profile_eval.get('venue_type') == 'dataset_benchmark' and venue_profile_eval.get('missing_checks'):
            fatal_reasons.append(f"venue_checks_unverified:{','.join(venue_profile_eval['missing_checks'])}")
    fatal_gate_triggered = is_idea or bool(fatal_dimensions) or bool(
        venue_profile_eval and venue_profile_eval.get('checks_gate_failed')
    )

    weak = [
        d for d in active_dims
        if ratings[d] is not None and (ratings[d] <= fatal_thresholds[d] or ratings[d] <= 5)
    ]
    if not weak and raw is not None and not fatal_gate_triggered and raw < TOP_TIER_COMPETITIVE_THRESHOLD:
        non_null_vals = [ratings[d] for d in active_dims if ratings[d] is not None]
        if non_null_vals:
            min_r = min(non_null_vals)
            weak = [d for d in active_dims if ratings[d] == min_r and ratings[d] <= 6]
    bottleneck_dimensions = sorted(weak, key=lambda d: (ratings[d], -weights[d], active_dims.index(d)))

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

    matched_tier = (
        'none_hold_for_rework'
        if (is_idea or fatal_gate_triggered or active_dims != DIMENSIONS)
        else (_recommend_matched_tier(raw, ratings, is_idea) if raw is not None else None)
    )
    out = {
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
    if idea_viability_band is not None:
        out['idea_viability_band'] = idea_viability_band
    return out


def score(document):
    if not isinstance(document, dict):
        raise ValueError('Document must be a JSON object')
    for meta_key in ('status', 'object_type', 'mode'):
        if meta_key in document and document[meta_key] is not None and type(document[meta_key]) is not str:
            raise ValueError(f'{meta_key} must be a string or null')

    explicit_mode = str(document.get('mode') or '').strip().lower()
    if explicit_mode and explicit_mode not in {'auto', 'paper', 'idea'}:
        raise ValueError(f'Unknown mode: {document.get("mode")!r}')

    is_idea = explicit_mode == 'idea' or any(
        isinstance(document.get(k), str) and document[k].strip().lower() == 'idea'
        for k in ('status', 'object_type')
    )

    ratings = document['ratings']
    if not isinstance(ratings, dict):
        raise ValueError('Weights and ratings must be JSON objects')

    if set(ratings) == set(IDEA_DIMENSIONS) and (is_idea or explicit_mode in {'', 'auto'}):
        active_dims = IDEA_DIMENSIONS
        fatal_thresholds = IDEA_FATAL_THRESHOLDS
        is_idea = True
    elif explicit_mode == 'idea' and set(ratings) != set(DIMENSIONS):
        active_dims = IDEA_DIMENSIONS
        fatal_thresholds = IDEA_FATAL_THRESHOLDS
    else:
        active_dims = DIMENSIONS
        fatal_thresholds = FATAL_THRESHOLDS

    venue_type_raw = document.get('venue_type') if document.get('venue_type') is not None else document.get('venue_profile')
    venue_profile_eval = evaluate_venue_profile_checks(venue_type_raw, document) if venue_type_raw is not None else None

    if 'weights' in document and document['weights'] is not None:
        weights = document['weights']
    elif active_dims == IDEA_DIMENSIONS:
        weights = dict(DEFAULT_IDEA_WEIGHTS)
    elif venue_profile_eval is not None:
        weights = dict(venue_profile_eval['profile_weights'])
    else:
        raise ValueError('weights are required')

    _validate_ratings_and_weights(weights, ratings, active_dims)

    subfield_preset_raw = document.get('subfield_preset')
    subfield_readiness = (
        evaluate_subfield_readiness(subfield_preset_raw, document.get('subfield_checks'))
        if subfield_preset_raw is not None
        else None
    )

    sanity_warnings = detect_halo_sanity_warnings(ratings, document, active_dims=active_dims)

    if any(v is None for v in ratings.values()):
        sr = _build_submission_readiness(
            weights,
            ratings,
            None,
            None,
            is_idea,
            active_dims=active_dims,
            fatal_thresholds=fatal_thresholds,
            venue_profile_eval=venue_profile_eval,
        )
        out_missing = {
            'overall': None,
            'status': 'not_comparable',
            'reason': 'missing dimension',
            'submission_readiness': sr,
            'sanity_warnings': sanity_warnings,
        }
        if active_dims == IDEA_DIMENSIONS or is_idea:
            out_missing['mode'] = 'idea'
            out_missing['archival_submission_blocked'] = True
        if venue_profile_eval is not None:
            out_missing['venue_type_profile'] = venue_profile_eval
        if subfield_readiness is not None:
            out_missing['subfield_readiness'] = subfield_readiness
        return out_missing

    with localcontext(BasicContext) as ctx:
        ctx.prec = 28
        raw = sum(Decimal(weights[k]) * Decimal(ratings[k]) for k in active_dims) / Decimal(100)
        overall = int(raw.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        delta_dec = (raw - TOP_TIER_COMPETITIVE_THRESHOLD).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    delta = float(str(delta_dec))

    idea_viability_band = None
    if active_dims == IDEA_DIMENSIONS:
        idea_viability_band, _ = _build_idea_viability_band(ratings, raw, document)

    sr = _build_submission_readiness(
        weights,
        ratings,
        raw,
        delta,
        is_idea,
        active_dims=active_dims,
        fatal_thresholds=fatal_thresholds,
        venue_profile_eval=venue_profile_eval,
        idea_viability_band=idea_viability_band,
    )

    reviewer_panel = document.get('reviewer_panel')
    panel_analysis = (
        simulate_reviewer_panel(
            reviewer_panel,
            weights,
            active_dims=active_dims,
            fatal_thresholds=fatal_thresholds,
            aggregate_fatal_gate=sr['fatal_gate_triggered'],
        )
        if reviewer_panel is not None
        else None
    )

    venue_tier = document.get('venue_tier') or (venue_profile_eval['venue_tier'] if venue_profile_eval else None)
    native_scales = (
        translate_to_native_scales(
            raw,
            fatal_gate_triggered=sr['fatal_gate_triggered'],
            ratings=ratings if active_dims == DIMENSIONS else None,
            reviewer_confidence=document.get('reviewer_confidence') if document.get('reviewer_confidence') is not None else document.get('confidence'),
            reviewer_panel=reviewer_panel,
        )
        if active_dims == DIMENSIONS
        else None
    )
    merit_packaging = compute_merit_vs_packaging(
        weights, ratings, active_dims=active_dims, fatal_thresholds=fatal_thresholds
    )
    non_rating_fatal = bool(
        (venue_profile_eval and venue_profile_eval.get('checks_gate_failed'))
        or (panel_analysis and panel_analysis.get('panel_verified_fatal_defect'))
    )
    what_if_roi = simulate_what_if_roi(
        weights,
        ratings,
        active_dims=active_dims,
        fatal_thresholds=fatal_thresholds,
        venue_tier=venue_tier,
        venue_type=(venue_profile_eval['venue_type'] if venue_profile_eval else None),
        is_idea=is_idea,
        non_rating_fatal_gate=non_rating_fatal,
    )
    deal_breaker = compute_deal_breaker_sensitivity(
        weights,
        ratings,
        active_dims=active_dims,
        fatal_thresholds=fatal_thresholds,
        venue_tier=venue_tier,
        venue_type=(venue_profile_eval['venue_type'] if venue_profile_eval else None),
        reviewer_panel=reviewer_panel,
        is_idea=is_idea,
    )

    result = {
        'overall': overall,
        'weighted_unrounded': str(raw),
        'status': 'calculated',
        'warning': 'Arithmetic only; inspect evidence, rubric, confidence and fatal gates separately.',
        'submission_readiness': sr,
        'merit_vs_packaging': merit_packaging,
        'what_if_roi': what_if_roi,
        'deal_breaker_sensitivity': deal_breaker,
        'sanity_warnings': sanity_warnings,
    }
    if native_scales is not None:
        result['native_venue_scales'] = native_scales
    if active_dims == IDEA_DIMENSIONS or is_idea:
        result['mode'] = 'idea'
        result['archival_submission_blocked'] = True
        if idea_viability_band is not None:
            result['idea_viability_band'] = idea_viability_band
            result['idea_readiness'] = {
                'idea_viability_band': idea_viability_band,
                'methods_execution_status': 'not_yet_assessed',
                'results_status': 'not_yet_assessed',
                'archival_submission_blocked': True,
            }
    if venue_profile_eval is not None:
        result['venue_type_profile'] = venue_profile_eval
        if active_dims == DIMENSIONS:
            result['venue_tier_fit'] = evaluate_venue_tier_fit(
                venue_profile_eval['venue_tier'],
                weighted_unrounded=raw,
                ratings=ratings,
                is_idea=is_idea,
                venue_type=venue_profile_eval['venue_type'],
            )
    if panel_analysis is not None:
        result['reviewer_panel_analysis'] = panel_analysis
    if document.get('section_diagnostics') is not None:
        result['section_diagnostics'] = score_section_diagnostics(document['section_diagnostics'])
    if document.get('evidence_anchors') is not None:
        result['evidence_anchor_table'] = build_evidence_anchor_table(document, document['evidence_anchors'])
    if subfield_readiness is not None:
        result['subfield_readiness'] = subfield_readiness
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input_json', nargs='?', help='Optional path to JSON input (defaults to stdin)')
    parser.add_argument('--venue-type', default=None, choices=sorted(VENUE_TYPE_PROFILES), help='Optional venue-type profile')
    parser.add_argument('--venue-profile', default=None, choices=sorted(VENUE_TYPE_PROFILES), help='Alias for --venue-type')
    parser.add_argument('--mode', default=None, choices=['auto', 'paper', 'idea'], help='Scoring mode (paper or idea)')
    parser.add_argument('--subfield-preset', default=None, choices=sorted(SUBFIELD_PRESETS), help='Optional AI/CS subfield preset')
    parser.add_argument('--what-if', action='store_true', help='Include and highlight What-If Score-Lift ROI plan')
    args = parser.parse_args(argv)
    try:
        if args.input_json is not None and not str(args.input_json).strip():
            raise ValueError('input_json path cannot be blank')
        if args.input_json and args.input_json != '-':
            raw_text = Path(args.input_json).read_text(encoding='utf-8')
            payload = json.loads(raw_text, parse_constant=_reject_nonfinite)
        else:
            payload = json.load(sys.stdin, parse_constant=_reject_nonfinite)
        if not isinstance(payload, dict):
            raise ValueError('Document must be a JSON object')
        if args.venue_type and args.venue_profile and args.venue_type != args.venue_profile:
            raise ValueError('--venue-type and --venue-profile cannot conflict')
        eff_vtype = args.venue_type or args.venue_profile
        if eff_vtype is not None:
            payload = {**payload, 'venue_type': eff_vtype}
        if args.mode is not None:
            payload = {**payload, 'mode': args.mode}
        if args.subfield_preset is not None:
            payload = {**payload, 'subfield_preset': args.subfield_preset}
        res = score(payload)
        if args.what_if and 'what_if_roi' in res:
            res = {**res, 'what_if_requested': True}
        print(json.dumps(res))
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
