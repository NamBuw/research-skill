#!/usr/bin/env python3
"""Canonical project state, lineage graph, ideation framing, MPU sizing, and Interactive Advisor."""
from __future__ import annotations

import argparse
import hashlib
import json
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
    import score_math
except ImportError:  # pragma: no cover - defensive fallback
    score_math = None  # type: ignore[assignment]

try:
    import venue_leads
except ImportError:  # pragma: no cover
    venue_leads = None  # type: ignore[assignment]

try:
    import check_question_card
except ImportError:  # pragma: no cover
    check_question_card = None  # type: ignore[assignment]

try:
    import check_experiment_manifest
except ImportError:  # pragma: no cover
    check_experiment_manifest = None  # type: ignore[assignment]

try:
    import check_gap_record
except ImportError:  # pragma: no cover
    check_gap_record = None  # type: ignore[assignment]


SCHEMA_VERSION = 'research_scientist_project_state_v1'
ADVISOR_SCHEMA = 'research_scientist_advisor_v1'
MAX_COMPACT_BYTES = 4096

ALLOWED_SUBFIELD_PRESETS = ('nlp_llm', 'cv_multimodal', 'ml_theory', 'ai_systems')
FULL_TEXT_ACCESS_LEVELS = {'full_text', 'selected_full_text'}
VALID_ACCESS_LEVELS = {'full_text', 'selected_full_text', 'abstract', 'metadata', 'metadata_only', 'unavailable'}
ACCESS_RANK = {
    'unavailable': 0,
    'metadata': 1,
    'metadata_only': 1,
    'abstract': 2,
    'selected_full_text': 3,
    'full_text': 4,
}

ROOT_CAUSE_BARRIERS = {'theoretical_limit', 'measurement_gap', 'data_supervision_gap', 'compute_infra_barrier'}
DURABILITY_CLASSES = {'durable_structural_limit', 'moderate_horizon_risk', 'high_scaling_erasure_risk'}
DECISION_IMPACT_CLASSES = {'decision_changing', 'marginal_gain'}
CONTRIBUTION_TYPES = (
    'method',
    'empirical_analysis',
    'diagnostic',
    'scaling_law',
    'theoretical_bound',
    'benchmark_dataset',
)
HEX64_RE = re.compile(r'^[0-9a-fA-F]{64}$')

_STITCHING_RE = re.compile(
    r'\b(?:combine|stitch|fuse|stack|plug[- ]and[- ]play|hybrid|ensemble|cascade|integrate)\b'
    r'.*?(?:\b(?:and|with|into|plus)\b|\+)',
    re.I,
)
_PLACEHOLDER_RE = re.compile(
    r'^(?:tbd|todo|none|n/?a|unknown|placeholder|to be determined|fill later|none yet)$',
    re.I,
)


def _reject_nonfinite(token: str) -> None:
    raise ValueError(f'Non-finite JSON constant not allowed: {token}')


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _nonblank(val: Any) -> bool:
    return isinstance(val, str) and bool(val.strip())


def _is_placeholder(val: Any) -> bool:
    if not _nonblank(val):
        return True
    cleaned = re.sub(r'\s+', ' ', val.strip())
    return bool(_PLACEHOLDER_RE.match(cleaned))


def _require_nonempty_arg(value: str | None, flag_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{flag_name} must be a nonblank string')
    return value.strip()


def _load_json(path_str: str, label: str = 'input') -> Any:
    clean = _require_nonempty_arg(path_str, label)
    if clean is None:
        raise ValueError(f'{label} path is required')
    p = Path(clean)
    if not p.is_file():
        raise ValueError(f'{label} file not found: {clean}')
    raw = p.read_text(encoding='utf-8')
    return json.loads(raw, parse_constant=_reject_nonfinite)


def _sha256_text(text: str) -> str:
    norm = re.sub(r'\s+', ' ', text.strip())
    return hashlib.sha256(norm.encode('utf-8')).hexdigest()


def _validate_target_venue_tier(target_venue_tier: str | None) -> str | None:
    if target_venue_tier is None:
        return None
    if not _nonblank(target_venue_tier):
        raise ValueError('--target-venue-tier must be a nonblank string')
    if score_math is not None:
        resolved = score_math.resolve_venue_tier(tier_expectation=target_venue_tier)
        if resolved is None or resolved not in score_math.VENUE_TIER_ORDER:
            raise ValueError(f'unrecognized target_venue_tier: {target_venue_tier!r}')
        return resolved
    return target_venue_tier.strip()


def _resolve_tier(target_venue: str | None = None, target_venue_tier: str | None = None) -> str | None:
    if score_math is None:
        return target_venue_tier
    q_tier = None
    if _nonblank(target_venue) and venue_leads is not None:
        try:
            q_info = venue_leads.lookup_venue_quality(target_venue)
            qt = q_info.get('quality_tier')
            if qt in {'S', 'A', 'B', 'C'}:
                q_tier = qt
        except Exception:
            q_tier = None
    return score_math.resolve_venue_tier(
        venue_name=target_venue,
        quality_tier=q_tier,
        tier_expectation=target_venue_tier,
    )


def init_state(
    project_id: str,
    title: str = '',
    subfield_preset: str | None = None,
    target_venue: str | None = None,
    target_venue_tier: str | None = None,
    author_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not _nonblank(project_id):
        raise ValueError('project_id must be a nonblank string')
    if subfield_preset is not None:
        if subfield_preset not in ALLOWED_SUBFIELD_PRESETS:
            raise ValueError(f'subfield_preset must be one of {ALLOWED_SUBFIELD_PRESETS}')
    if target_venue is not None and not _nonblank(target_venue):
        raise ValueError('target_venue must be a nonblank string')
    validated_tier = _validate_target_venue_tier(target_venue_tier)
    resolved_tier = _resolve_tier(target_venue=target_venue, target_venue_tier=validated_tier)
    if author_profile is not None and not isinstance(author_profile, dict):
        raise ValueError('author_profile must be a JSON object')
    now = _utc_now()
    return {
        'schema': SCHEMA_VERSION,
        'project_id': project_id.strip(),
        'title': title.strip() if isinstance(title, str) else '',
        'subfield_preset': subfield_preset,
        'target_venue': target_venue.strip() if _nonblank(target_venue) else None,
        'target_venue_tier': resolved_tier,
        'created_at_utc': now,
        'updated_at_utc': now,
        'author_profile': dict(author_profile) if author_profile else {},
        'corpus_digests': {},
        'trajectory_tree': [],
        'gaps': {},
        'ideas': {},
        'rqs': {},
        'experiments': {},
        'manuscript_claims': {},
        'scorecards': {},
        'venue_verdicts': {},
        'rebuttal_points': {},
        'failure_cases': [],
        'lineage_edges': [],
        'provenance_events': [],
    }


def _add_edge(state: dict[str, Any], from_type: str, from_id: str, to_type: str, to_id: str) -> None:
    if not (_nonblank(from_id) and _nonblank(to_id)):
        return
    edge = {'from_type': from_type, 'from_id': from_id, 'to_type': to_type, 'to_id': to_id}
    edges = state.setdefault('lineage_edges', [])
    if edge not in edges:
        edges.append(edge)


def register_corpus_digest(state: dict[str, Any], entry: dict[str, Any]) -> tuple[str, list[str]]:
    """Register or update a corpus digest while preventing silent upgrades or downgrades."""
    if not isinstance(entry, dict):
        raise ValueError('corpus digest entry must be a JSON object')
    source_id = str(entry.get('source_id') or entry.get('id') or '').strip()
    if not source_id:
        raise ValueError('corpus digest entry requires source_id or id')
    raw_access = str(entry.get('access') or entry.get('reading_basis') or 'metadata_only').strip()
    access = 'metadata_only' if raw_access == 'metadata' else raw_access
    if access not in VALID_ACCESS_LEVELS:
        raise ValueError(f'invalid access level {raw_access!r} for {source_id}')

    locator = str(entry.get('locator') or '').strip()
    quote = str(entry.get('quote') or '').strip()
    explicit_digest = str(entry.get('digest') or entry.get('claim') or '').strip()
    abstract_text = str(entry.get('abstract') or '').strip()
    digest_text = explicit_digest or abstract_text
    events = state.setdefault('provenance_events', [])
    warnings: list[str] = []

    digests = state.setdefault('corpus_digests', {})
    existing = digests.get(source_id)

    # Guard 1: Cannot claim full_text / selected_full_text without a concrete non-placeholder locator AND quote/digest
    has_real_locator = (not _is_placeholder(locator)) and locator.lower() not in {'abstract', 'metadata', 'metadata_record'}
    has_real_quote_or_digest = (not _is_placeholder(quote)) or (not _is_placeholder(explicit_digest))
    if access in FULL_TEXT_ACCESS_LEVELS and (not has_real_locator or not has_real_quote_or_digest):
        msg = f'silent_full_text_upgrade_blocked:{source_id}:missing_locator_or_digest'
        warnings.append(msg)
        events.append({'event': 'silent_full_text_upgrade_blocked', 'source_id': source_id, 'at_utc': _utc_now()})
        if existing is not None:
            return source_id, warnings
        has_abs_or_digest = not _is_placeholder(abstract_text or explicit_digest)
        access = 'abstract' if has_abs_or_digest else 'metadata_only'
        if _is_placeholder(locator) or locator.lower() == 'abstract':
            locator = ''
        if _is_placeholder(quote):
            quote = ''
        if _is_placeholder(digest_text):
            digest_text = ''

    # Guard 2: Do not silently downgrade an existing full_text digest with metadata_only/abstract
    if isinstance(existing, dict):
        old_access = existing.get('access', 'metadata_only')
        if ACCESS_RANK.get(old_access, 0) > ACCESS_RANK.get(access, 0):
            msg = f'provenance_downgrade_blocked:{source_id}:{old_access}_preserved_over_{access}'
            warnings.append(msg)
            events.append({'event': 'provenance_downgrade_blocked', 'source_id': source_id, 'at_utc': _utc_now()})
            return source_id, warnings

    raw_hash = entry.get('digest_sha256')
    if isinstance(raw_hash, str) and HEX64_RE.fullmatch(raw_hash.strip()):
        digest_sha = raw_hash.strip().lower()
    elif quote or digest_text:
        digest_sha = _sha256_text(quote or digest_text)
    else:
        digest_sha = None

    digests[source_id] = {
        'source_id': source_id,
        'title': str(entry.get('title') or (existing or {}).get('title') or '').strip() or None,
        'access': access,
        'locator': locator or None,
        'quote': quote or None,
        'digest': digest_text or None,
        'digest_sha256': digest_sha,
        'inspected_at_utc': str(entry.get('inspected_at_utc') or _utc_now()),
    }
    return source_id, warnings


def _validate_f32_lenses(lenses: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(lenses, dict):
        return errors, warnings

    rcb = lenses.get('root_cause_barrier')
    if rcb is not None and rcb not in ROOT_CAUSE_BARRIERS:
        errors.append(f'invalid_root_cause_barrier:{rcb}')

    dur = lenses.get('durability_12_24m')
    if dur is not None:
        if dur not in DURABILITY_CLASSES:
            errors.append(f'invalid_durability_12_24m:{dur}')
        elif dur == 'high_scaling_erasure_risk':
            warnings.append('high_scaling_erasure_risk')

    imp = lenses.get('so_what_decision_impact')
    if imp is not None and imp not in DECISION_IMPACT_CLASSES:
        errors.append(f'invalid_so_what_decision_impact:{imp}')

    if any(k in lenses for k in ('root_cause_barrier', 'durability_12_24m', 'so_what_decision_impact', 'evaluation_validity_gap')):
        if not _nonblank(lenses.get('why_now_enabler')):
            warnings.append('missing_why_now_enabler')

    leads = lenses.get('isomorphic_transfer_leads')
    if isinstance(leads, list):
        for idx, lead in enumerate(leads):
            if not isinstance(lead, dict):
                errors.append(f'invalid_isomorphic_transfer_lead:{idx}')
                continue
            status = lead.get('status')
            if status != 'lead':
                errors.append(f'isomorphic_transfer_lead_must_be_tagged_lead:{idx}:{status}')
    return errors, warnings


F32_LENS_KEYS = (
    'root_cause_barrier',
    'why_now_enabler',
    'evaluation_validity_gap',
    'isomorphic_transfer_leads',
    'so_what_decision_impact',
    'durability_12_24m',
)


def _dedup_str_ids(*sources: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for src in sources:
        if not isinstance(src, list):
            continue
        for item in src:
            if isinstance(item, dict):
                val = str(item.get('source_id') or item.get('id') or '').strip()
            elif isinstance(item, str):
                val = item.strip()
            else:
                val = ''
            if val and val not in seen:
                seen.add(val)
                out.append(val)
    return out


def _extract_f32_lenses(obj: dict[str, Any]) -> dict[str, Any]:
    lenses = dict(obj.get('lenses_f32')) if isinstance(obj.get('lenses_f32'), dict) else {}
    for k in F32_LENS_KEYS:
        if k in obj and k not in lenses:
            lenses[k] = obj[k]
    return lenses


def _merge_f32_lenses(existing: Any, incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing) if isinstance(existing, dict) else {}
    for lk, lv in incoming.items():
        if lv is not None and lv != '' and lv != [] and lv != {}:
            merged[lk] = lv
        elif lk not in merged:
            merged[lk] = lv
    return merged


def _extract_gap_sources(obj: dict[str, Any]) -> tuple[list[str], list[str]]:
    pab = obj.get('prior_art_boundary') if isinstance(obj.get('prior_art_boundary'), dict) else {}
    sup_srcs = _dedup_str_ids(
        obj.get('support_source_ids'),
        obj.get('support_ids'),
        obj.get('cited_ids'),
        obj.get('cited_paper_ids'),
        pab.get('support_source_ids'),
        pab.get('support_ids'),
        pab.get('cited_ids'),
    )
    cw_srcs = _dedup_str_ids(
        obj.get('closest_work_ids'),
        pab.get('closest_work_ids'),
        obj.get('closest_works'),
    )
    return sup_srcs, cw_srcs


def _store_trajectory_tree(state: dict[str, Any], tree: Any) -> None:
    if isinstance(tree, list):
        state['trajectory_tree'] = list(tree)
    elif isinstance(tree, dict):
        state['trajectory_tree'] = dict(tree)


def _ingest_seed_digests(state: dict[str, Any], raw_digests: Any) -> list[str]:
    warnings: list[str] = []
    if isinstance(raw_digests, dict):
        items = [(k, v) for k, v in raw_digests.items()]
    elif isinstance(raw_digests, list):
        items = [(str(v.get('source_id') or v.get('id') or ''), v) for v in raw_digests if isinstance(v, dict)]
    else:
        return warnings
    for sid_key, d_obj in items:
        if not isinstance(d_obj, dict):
            continue
        sid = str(d_obj.get('source_id') or d_obj.get('id') or sid_key).strip()
        if not sid:
            continue
        existing = (state.get('corpus_digests') or {}).get(sid)
        locator = str(d_obj.get('locator') or '').strip()
        has_real_loc = (not _is_placeholder(locator)) and locator.lower() not in {'abstract', 'metadata', 'metadata_record'}
        if isinstance(existing, dict) and existing.get('access') in FULL_TEXT_ACCESS_LEVELS and not has_real_loc:
            # gap_pipeline._load_digests strips locator; preserve pre-registered verified full_text without false upgrade warning
            continue
        _, w = register_corpus_digest(state, {**d_obj, 'source_id': sid})
        warnings.extend(w)
    return warnings


def _upsert_gap_record(
    state: dict[str, Any],
    gid: str,
    obj: dict[str, Any],
    lenses: dict[str, Any],
    sup_srcs: list[str],
    cw_srcs: list[str],
    *,
    default_disposition: str = 'supported_candidate',
) -> tuple[dict[str, Any], list[str], list[str]]:
    gaps = state.setdefault('gaps', {})
    fc_block = obj.get('failure_cases') if isinstance(obj.get('failure_cases'), dict) else {}
    fc_ids = _dedup_str_ids(obj.get('failure_case_ids'), fc_block.get('failure_case_ids'))
    is_fc_origin = (obj.get('trigger') == 'failure_cases') or (fc_block.get('trigger') == 'failure_cases') or bool(fc_ids)
    origin_mode = obj.get('origin_mode') or ('failure_cases' if is_fc_origin else 'literature_first')

    if gid not in gaps:
        merged_lenses = dict(lenses)
        l_errs, l_warns = _validate_f32_lenses(merged_lenses)
        gaps[gid] = {
            'id': gid,
            'claim': obj.get('claim') or obj.get('gap_claim') or '',
            'disposition': obj.get('disposition', default_disposition),
            'origin_mode': origin_mode,
            'failure_case_ids': fc_ids,
            'support_source_ids': sup_srcs,
            'closest_work_ids': cw_srcs,
            'prior_art_boundary': obj.get('prior_art_boundary') if obj.get('prior_art_boundary') is not None else '',
            'gap_tier_ceiling': obj.get('gap_tier_ceiling'),
            'resource_feasibility': obj.get('resource_feasibility'),
            'scoop_and_obsolescence_risk': obj.get('scoop_and_obsolescence_risk'),
            'lenses_f32': merged_lenses,
        }
        return merged_lenses, l_errs, l_warns

    existing_gap = gaps[gid]
    merged_lenses = _merge_f32_lenses(existing_gap.get('lenses_f32'), lenses)
    l_errs, l_warns = _validate_f32_lenses(merged_lenses)
    existing_gap['lenses_f32'] = merged_lenses
    if not _nonblank(existing_gap.get('claim')) and _nonblank(obj.get('claim') or obj.get('gap_claim')):
        existing_gap['claim'] = obj.get('claim') or obj.get('gap_claim') or ''
    if not existing_gap.get('support_source_ids') and sup_srcs:
        existing_gap['support_source_ids'] = sup_srcs
    if not existing_gap.get('closest_work_ids') and cw_srcs:
        existing_gap['closest_work_ids'] = cw_srcs
    if not existing_gap.get('failure_case_ids') and fc_ids:
        existing_gap['failure_case_ids'] = fc_ids
    if (not existing_gap.get('prior_art_boundary')) and obj.get('prior_art_boundary'):
        existing_gap['prior_art_boundary'] = obj.get('prior_art_boundary')
    elif isinstance(obj.get('prior_art_boundary'), dict) and not isinstance(existing_gap.get('prior_art_boundary'), dict):
        existing_gap['prior_art_boundary'] = obj.get('prior_art_boundary')
    for meta_k in ('gap_tier_ceiling', 'resource_feasibility', 'scoop_and_obsolescence_risk'):
        if existing_gap.get(meta_k) is None and obj.get(meta_k) is not None:
            existing_gap[meta_k] = obj.get(meta_k)
    return merged_lenses, l_errs, l_warns


def _ingest_gap_ideas(
    state: dict[str, Any],
    gid: str,
    b: dict[str, Any],
    merged_lenses: dict[str, Any],
    links: dict[str, Any],
) -> list[str]:
    ideas_list = b.get('idea_portfolio') or b.get('candidate_ideas') or b.get('ideas') or []
    if not ideas_list and (_nonblank(b.get('idea_id')) or _nonblank(b.get('title')) or _nonblank(b.get('proposed_mechanism'))):
        ideas_list = [b]
    pre_mortem = b.get('pre_mortem') if isinstance(b.get('pre_mortem'), dict) else {}
    idea_ids: list[str] = []
    for idea_item in ideas_list:
        if not isinstance(idea_item, dict):
            continue
        iid = str(idea_item.get('id') or idea_item.get('idea_id') or links.get('idea_id') or f'IDEA-{len(state["ideas"]) + 1}').strip()
        mech_dec = dict(idea_item.get('mechanism_decomposition')) if isinstance(idea_item.get('mechanism_decomposition'), dict) else {
            'bottleneck_target': idea_item.get('bottleneck_target', ''),
            'why_sota_fails': idea_item.get('why_sota_fails', ''),
            'proposed_mechanism': idea_item.get('proposed_mechanism') or idea_item.get('mechanism_summary') or '',
            'components': list(idea_item.get('components') or []),
            'simplest_alternative': idea_item.get('simplest_alternative', ''),
        }
        mech_res = assess_mechanism_decomposition(
            {'title': idea_item.get('title', ''), 'summary': idea_item.get('summary', ''), 'mechanism_decomposition': mech_dec}
        )
        mech_dec['is_vague_stitching'] = mech_res['is_vague_stitching']
        stored_idea = {
            'id': iid,
            'gap_id': gid,
            'angle': idea_item.get('angle', 'high_novelty_mechanism'),
            'contribution_type': idea_item.get('contribution_type', 'method'),
            'title': idea_item.get('title', ''),
            'mechanism_decomposition': mech_dec,
            'top_failure_modes': list(idea_item.get('top_failure_modes') or pre_mortem.get('top_failure_modes') or []),
            'killer_experiment': idea_item.get('killer_experiment') or pre_mortem.get('killer_experiment') or {},
            'pivot_path': idea_item.get('pivot_path') or pre_mortem.get('pivot_path') or '',
            'planned_contributions_count': idea_item.get('planned_contributions_count', 1),
            'planned_datasets_count': idea_item.get('planned_datasets_count', 2),
            'estimated_weeks': idea_item.get('estimated_weeks'),
            'required_gpu_hours': idea_item.get('required_gpu_hours'),
            'required_strengths': list(idea_item.get('required_strengths') or []),
            'required_assets': list(idea_item.get('required_assets') or []),
            'gap_tier_ceiling': b.get('gap_tier_ceiling'),
            'lenses_f32': dict(merged_lenses),
        }
        for opt_k in ('canonical_angle', 'goal_tags', 'summary', 'mechanism_summary', 'ratings', 'closest_work'):
            if opt_k in idea_item:
                stored_idea[opt_k] = idea_item[opt_k]
        state.setdefault('ideas', {})[iid] = stored_idea
        _add_edge(state, 'gap', gid, 'idea', iid)
        idea_ids.append(iid)
    return idea_ids


def ingest_artifact(
    state: dict[str, Any],
    kind: str,
    payload: Any,
    *,
    link_ids: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(state, dict) or state.get('schema') != SCHEMA_VERSION:
        raise ValueError('invalid project_state object')
    links = link_ids or {}
    warnings: list[str] = []
    errors: list[str] = []
    ingested_ids: list[str] = []

    if kind == 'corpus_digests':
        entries = payload.get('digests') if isinstance(payload, dict) else payload
        if isinstance(entries, dict):
            entries = list(entries.values())
        if not isinstance(entries, list):
            raise ValueError('corpus_digests payload must be a list or {digests: ...}')
        for item in entries:
            sid, w = register_corpus_digest(state, item)
            ingested_ids.append(sid)
            warnings.extend(w)

    elif kind == 'corpus':
        papers = payload.get('papers') if isinstance(payload, dict) else payload
        if not isinstance(papers, list):
            raise ValueError('corpus payload must be a list or {papers: ...}')
        for p in papers:
            if not isinstance(p, dict):
                continue
            sid = str(p.get('source_id') or p.get('id') or p.get('dedup_key') or '').strip()
            if not sid:
                continue
            raw_access = p.get('access')
            raw_rb = p.get('reading_basis')
            if raw_access in FULL_TEXT_ACCESS_LEVELS or raw_rb in FULL_TEXT_ACCESS_LEVELS:
                access = raw_access if raw_access in FULL_TEXT_ACCESS_LEVELS else raw_rb
                entry = {
                    'source_id': sid,
                    'title': p.get('title'),
                    'access': access,
                    'locator': p.get('locator') or '',
                    'quote': p.get('quote') or p.get('full_text_excerpt') or '',
                    'digest': p.get('digest') or '',
                    'abstract': p.get('abstract') or '',
                }
            else:
                access = raw_access or raw_rb or ('abstract' if _nonblank(p.get('abstract')) else 'metadata_only')
                entry = {
                    'source_id': sid,
                    'title': p.get('title'),
                    'access': access,
                    'locator': p.get('locator') or ('abstract' if _nonblank(p.get('abstract')) else ''),
                    'quote': p.get('quote') or '',
                    'digest': p.get('digest') or p.get('abstract') or p.get('title') or '',
                }
            _, w = register_corpus_digest(state, entry)
            ingested_ids.append(sid)
            warnings.extend(w)

    elif kind == 'gap_record':
        if not isinstance(payload, dict):
            raise ValueError('gap_record must be a JSON object')
        ev_by_id: dict[str, dict[str, Any]] = {}
        for ev in payload.get('evidence') or []:
            if isinstance(ev, dict) and _nonblank(ev.get('id')):
                ev_by_id[ev['id']] = ev
                if _nonblank(ev.get('source_id')):
                    _, w = register_corpus_digest(
                        state,
                        {
                            'source_id': ev['source_id'],
                            'access': ev.get('access', 'metadata_only'),
                            'locator': ev.get('locator', ''),
                            'quote': ev.get('quote', ''),
                            'digest': ev.get('claim', ''),
                        },
                    )
                    warnings.extend(w)
        cw_by_id: dict[str, dict[str, Any]] = {}
        for cw in payload.get('closest_works') or []:
            if isinstance(cw, dict) and _nonblank(cw.get('id')):
                cw_by_id[cw['id']] = cw
        for cand in payload.get('candidates') or []:
            if not isinstance(cand, dict) or not _nonblank(cand.get('id')):
                continue
            gid = cand['id'].strip()
            sup_srcs = []
            for eid in cand.get('support_evidence_ids') or []:
                src = ev_by_id.get(eid, {}).get('source_id')
                if _nonblank(src) and src not in sup_srcs:
                    sup_srcs.append(src)
            cw_srcs = []
            for wid in cand.get('closest_work_ids') or []:
                src = cw_by_id.get(wid, {}).get('source_id') or wid
                if _nonblank(src) and src not in cw_srcs:
                    cw_srcs.append(src)
            lenses = _extract_f32_lenses(cand)
            l_errs, l_warns = _validate_f32_lenses(lenses)
            errors.extend(l_errs)
            warnings.extend(l_warns)
            state.setdefault('gaps', {})[gid] = {
                'id': gid,
                'claim': cand.get('claim', ''),
                'disposition': cand.get('disposition', 'insufficient_evidence'),
                'origin_mode': cand.get('origin_mode', 'literature_first'),
                'failure_case_ids': list(cand.get('failure_case_ids') or []),
                'support_source_ids': sup_srcs,
                'closest_work_ids': cw_srcs,
                'prior_art_boundary': cand.get('prior_art_boundary') or payload.get('scope', ''),
                'gap_tier_ceiling': cand.get('gap_tier_ceiling'),
                'resource_feasibility': cand.get('resource_feasibility'),
                'scoop_and_obsolescence_risk': cand.get('scoop_and_obsolescence_risk'),
                'lenses_f32': lenses,
            }
            ingested_ids.append(gid)
        if isinstance(payload.get('trajectory_tree'), (list, dict)):
            _store_trajectory_tree(state, payload['trajectory_tree'])

    elif kind == 'gap_pipeline':
        if not isinstance(payload, dict):
            raise ValueError('gap_pipeline must be a JSON object')
        traj_trees = payload.get('trajectory_trees')
        if isinstance(traj_trees, dict):
            state['trajectory_trees'] = dict(traj_trees)
        if isinstance(payload.get('trajectory_tree'), (list, dict)):
            _store_trajectory_tree(state, payload['trajectory_tree'])
        elif isinstance(traj_trees, dict):
            chosen_tree = next(
                (v for k, v in traj_trees.items() if k != '_corpus' and isinstance(v, (dict, list))),
                traj_trees.get('_corpus'),
            )
            if isinstance(chosen_tree, (dict, list)):
                _store_trajectory_tree(state, chosen_tree)
        for g in payload.get('surviving_gaps') or []:
            if not isinstance(g, dict):
                continue
            gid = str(g.get('id') or g.get('gap_id') or '').strip()
            if not gid:
                continue
            lenses = _extract_f32_lenses(g)
            sup_srcs, cw_srcs = _extract_gap_sources(g)
            if not cw_srcs and sup_srcs and not isinstance(payload.get('idea_seed_bundle'), dict):
                cw_srcs = list(sup_srcs)
            merged_lenses, l_errs, l_warns = _upsert_gap_record(
                state, gid, g, lenses, sup_srcs, cw_srcs, default_disposition='supported_candidate',
            )
            errors.extend(l_errs)
            warnings.extend(l_warns)
            if isinstance(g.get('trajectory_tree'), (dict, list)) and not state.get('trajectory_tree'):
                _store_trajectory_tree(state, g['trajectory_tree'])
            if gid not in ingested_ids:
                ingested_ids.append(gid)
            if not isinstance(payload.get('idea_seed_bundle'), dict):
                for iid in _ingest_gap_ideas(state, gid, g, merged_lenses, links):
                    if iid not in ingested_ids:
                        ingested_ids.append(iid)
        if isinstance(payload.get('idea_seed_bundle'), dict):
            nested_res = ingest_artifact(state, 'idea_seed_bundle', payload['idea_seed_bundle'], link_ids=links)
            for nid in nested_res['ingested_ids']:
                if nid not in ingested_ids:
                    ingested_ids.append(nid)
            errors.extend(nested_res['errors'])
            warnings.extend(nested_res['warnings'])

    elif kind == 'idea_seed_bundle':
        if not isinstance(payload, dict):
            raise ValueError('idea_seed_bundle must be a JSON object')
        if isinstance(payload.get('seeds'), list):
            bundles = payload['seeds']
        elif isinstance(payload.get('idea_seed_bundles'), list):
            bundles = payload['idea_seed_bundles']
        else:
            bundles = [payload]
        for idx, b in enumerate(bundles):
            if not isinstance(b, dict):
                continue
            gid = str(b.get('gap_id') or b.get('id') or links.get('gap_id') or f'G-BUNDLE-{idx + 1}').strip()
            warnings.extend(_ingest_seed_digests(state, b.get('full_text_digests')))
            lenses = _extract_f32_lenses(b)
            sup_srcs, cw_srcs = _extract_gap_sources(b)
            merged_lenses, l_errs, l_warns = _upsert_gap_record(
                state, gid, b, lenses, sup_srcs, cw_srcs, default_disposition='supported_candidate',
            )
            errors.extend(l_errs)
            warnings.extend(l_warns)
            if gid not in ingested_ids:
                ingested_ids.append(gid)
            if isinstance(b.get('trajectory_tree'), (list, dict)):
                _store_trajectory_tree(state, b['trajectory_tree'])
            for iid in _ingest_gap_ideas(state, gid, b, merged_lenses, links):
                if iid not in ingested_ids:
                    ingested_ids.append(iid)

    elif kind == 'question_card':
        if not isinstance(payload, dict):
            raise ValueError('question_card must be a JSON object')
        qc_check = check_question_card.check(payload) if check_question_card is not None else {'valid_structure': True, 'errors': []}
        rq_id = str(payload.get('id') or links.get('rq_id') or f'RQ-{len(state["rqs"]) + 1}').strip()
        idea_id = str(payload.get('idea_id') or links.get('idea_id') or '').strip() or None
        gap_id = str(payload.get('gap_id') or links.get('gap_id') or '').strip() or None
        state.setdefault('rqs', {})[rq_id] = {
            'id': rq_id,
            'idea_id': idea_id,
            'gap_id': gap_id,
            'question': payload.get('question', ''),
            'question_type': payload.get('question_type', ''),
            'rival_explanation': payload.get('rival_explanation', ''),
            'expected_if_focal': payload.get('expected_if_focal', ''),
            'expected_if_rival': payload.get('expected_if_rival', ''),
            'falsifying_result': payload.get('falsifying_result', ''),
            'protocol_frozen_at_utc': payload.get('protocol_frozen_at_utc'),
            'valid_structure': bool(qc_check.get('valid_structure')),
            'validation_errors': list(qc_check.get('errors') or []),
        }
        if idea_id:
            _add_edge(state, 'idea', idea_id, 'rq', rq_id)
        elif gap_id:
            _add_edge(state, 'gap', gap_id, 'rq', rq_id)
        ingested_ids.append(rq_id)

    elif kind == 'experiment_manifest':
        if not isinstance(payload, dict):
            raise ValueError('experiment_manifest must be a JSON object')
        m_check = check_experiment_manifest.check(payload) if check_experiment_manifest is not None else {'status': 'structurally_checked', 'errors': []}
        rq_id = str(links.get('rq_id') or payload.get('question_id') or '').strip()
        frozen_ts = payload.get('protocol_frozen_at_utc')
        if rq_id and rq_id in state.get('rqs', {}) and frozen_ts and not state['rqs'][rq_id].get('protocol_frozen_at_utc'):
            state['rqs'][rq_id]['protocol_frozen_at_utc'] = frozen_ts
        for run in payload.get('runs') or []:
            if not isinstance(run, dict) or not _nonblank(run.get('run_id')):
                continue
            rid = run['run_id'].strip()
            state.setdefault('experiments', {})[rid] = {
                'run_id': rid,
                'rq_id': rq_id or None,
                'role': run.get('role'),
                'protocol_version': run.get('protocol_version'),
                'decision_timing': run.get('decision_timing'),
                'result_artifact_sha256': run.get('result_artifact_sha256'),
                'split_manifest_sha256': run.get('split_manifest_sha256'),
                'metric_script_sha256': run.get('metric_script_sha256'),
                'metric_id': run.get('metric_id'),
                'result_value': run.get('result_value'),
                'files_verified': bool(payload.get('files_verified', False)),
                'engineering_verdict': payload.get('engineering_verdict', 'PASS' if m_check.get('status') != 'invalid' else 'FAILED'),
                'outcome_analysis_status': payload.get('outcome_analysis_status', 'pending'),
                'outcome_status': payload.get('outcome_status', payload.get('outcome_analysis_status', 'pending')),
                'outcome_classification': payload.get('outcome_classification'),
                'harking_detected': bool(payload.get('harking_detected', False)),
                'manifest_errors': list(m_check.get('errors') or []),
            }
            if rq_id:
                _add_edge(state, 'rq', rq_id, 'experiment', rid)
            ingested_ids.append(rid)

    elif kind == 'experiment_outcome':
        if not isinstance(payload, dict):
            raise ValueError('experiment_outcome must be a JSON object')
        harking_flag = bool(payload.get('harking_detected', False))
        raw_status = str(payload.get('status') or '').strip()
        if not raw_status:
            raw_status = 'blocked_harking' if harking_flag else 'analyzed'
        if raw_status == 'blocked_harking':
            harking_flag = True
        outcome_classification = str(payload.get('outcome_classification') or raw_status).strip()
        rq_id = str(links.get('rq_id') or payload.get('question_id') or '').strip()
        run_ids = list(links.get('run_ids') or payload.get('run_ids') or [])
        if not run_ids and links.get('run_id'):
            run_ids = [links['run_id']]
        if not run_ids and rq_id:
            run_ids = [rid for rid, r in state.get('experiments', {}).items() if r.get('rq_id') == rq_id]
        for rid in run_ids:
            if rid in state.get('experiments', {}):
                state['experiments'][rid]['outcome_status'] = raw_status
                state['experiments'][rid]['outcome_classification'] = outcome_classification
                state['experiments'][rid]['outcome_analysis_status'] = raw_status
                state['experiments'][rid]['harking_detected'] = harking_flag
                state['experiments'][rid]['outcome_errors'] = list(payload.get('errors') or [])
                state['experiments'][rid]['pivot_recommendations'] = list(payload.get('pivot_recommendations') or [])
                ingested_ids.append(rid)
        fcs = payload.get('failure_cases')
        if isinstance(fcs, list):
            ingest_artifact(state, 'failure_cases', {'failure_cases': fcs})

    elif kind == 'manuscript_ledger':
        if not isinstance(payload, dict):
            raise ValueError('manuscript_ledger must be a JSON object')
        raw_issues = payload.get('issues') if isinstance(payload.get('issues'), list) else []
        raw_errors = payload.get('errors') if isinstance(payload.get('errors'), list) else []
        combined_errors: list[str] = []
        for item in raw_errors + raw_issues:
            s_item = str(item).strip()
            if s_item and s_item not in combined_errors:
                combined_errors.append(s_item)
        raw_status = payload.get('status')
        status_str = str(raw_status).strip().lower() if _nonblank(raw_status) else None
        passing_statuses = {'passed', 'structure_passed', 'ok', 'valid'}
        if 'passed' in payload and payload.get('passed') is not None:
            ledger_passed = bool(payload.get('passed'))
            if status_str is not None and status_str not in passing_statuses:
                ledger_passed = False
            if combined_errors:
                ledger_passed = False
        elif status_str is not None:
            ledger_passed = (status_str in passing_statuses) and (not combined_errors)
        else:
            ledger_passed = not combined_errors
        state['manuscript_ledger_status'] = {
            'passed': ledger_passed,
            'status': raw_status if _nonblank(raw_status) else ('passed' if ledger_passed else 'failed'),
            'errors': combined_errors,
        }
        for src in payload.get('sources') or []:
            if isinstance(src, dict) and _nonblank(src.get('id')):
                src_id = src['id'].strip()
                existing = (state.get('corpus_digests') or {}).get(src_id)
                has_src_excerpt = (not _is_placeholder(src.get('quote'))) or (
                    not _is_placeholder(src.get('digest') or src.get('claim'))
                )
                if (
                    src.get('verified')
                    and isinstance(existing, dict)
                    and existing.get('access') in FULL_TEXT_ACCESS_LEVELS
                    and not _is_placeholder(src.get('locator'))
                    and not has_src_excerpt
                ):
                    continue
                access = 'full_text' if src.get('verified') else 'metadata_only'
                _, w = register_corpus_digest(
                    state,
                    {
                        'source_id': src_id,
                        'title': src.get('title'),
                        'access': access,
                        'locator': src.get('locator', ''),
                        'quote': src.get('quote', ''),
                        'digest': src.get('digest') or src.get('claim') or '',
                        'abstract': src.get('abstract', ''),
                        'inspected_at_utc': src.get('verified_at') or _utc_now(),
                    },
                )
                warnings.extend(w)
        claims_payload = payload.get('claims') or []
        if not claims_payload:
            for existing_claim in (state.get('manuscript_claims') or {}).values():
                if isinstance(existing_claim, dict):
                    existing_claim['ledger_verified'] = ledger_passed
                    existing_claim['ledger_passed'] = ledger_passed
        for claim in claims_payload:
            if not isinstance(claim, dict) or not _nonblank(claim.get('id')):
                continue
            cid = claim['id'].strip()
            rq_id = claim.get('rq_id') or (claim.get('rq_ids')[0] if isinstance(claim.get('rq_ids'), list) and claim.get('rq_ids') else None) or links.get('rq_id')
            run_ids = list(claim.get('run_ids') or claim.get('evidence_ids') or links.get('run_ids') or [])
            if not run_ids and links.get('run_id'):
                run_ids = [links['run_id']]
            state.setdefault('manuscript_claims', {})[cid] = {
                'id': cid,
                'rq_id': rq_id,
                'kind': claim.get('kind', 'reported'),
                'material': bool(claim.get('material', True)),
                'target_ref': claim.get('target_ref') or claim.get('location') or '',
                'run_ids': run_ids,
                'source_ids': list(claim.get('source_ids') or []),
                'ledger_verified': ledger_passed,
                'ledger_passed': ledger_passed,
            }
            for rid in run_ids:
                if rid in state.get('experiments', {}):
                    _add_edge(state, 'experiment', rid, 'claim', cid)
            if rq_id and not run_ids:
                _add_edge(state, 'rq', rq_id, 'claim', cid)
            ingested_ids.append(cid)

    elif kind == 'scorecards':
        if not isinstance(payload, dict):
            raise ValueError('scorecards must be a JSON object')
        sr_map = payload.get('submission_readiness') if isinstance(payload.get('submission_readiness'), dict) else {}
        rwc = payload.get('related_work_comparison') if isinstance(payload.get('related_work_comparison'), dict) else {}
        profiles = payload.get('profiles') or []
        if not isinstance(profiles, list):
            profiles = []
        nested_sr = {k: v for k, v in sr_map.items() if isinstance(v, dict)}
        sc_issues = [
            str(x).strip()
            for x in (payload.get('issues') or [])
            if _nonblank(str(x))
        ] if isinstance(payload.get('issues'), list) else []
        sc_status = payload.get('status')

        def _entry_not_comparable(entry: dict[str, Any]) -> bool:
            band = str(entry.get('band') or '')
            return (
                entry.get('structural_gate_passed') is False
                or bool(entry.get('profile_issues'))
                or band.startswith('not_comparable')
                or entry.get('status') == 'not_comparable'
            )

        explicit_target_id = str(
            payload.get('target_id') or links.get('target_id') or rwc.get('target_id') or ''
        ).strip() or None

        if explicit_target_id is not None:
            target_id = explicit_target_id
            if target_id in nested_sr:
                sr = nested_sr[target_id]
            elif not nested_sr and sr_map:
                sr = sr_map
            else:
                sr = {}
            fatal_gate = bool(payload.get('fatal_gate_triggered') or sr.get('fatal_gate_triggered'))
            if _entry_not_comparable(sr) and (not sc_status or sc_status == 'structurally_comparable'):
                sc_status = 'not_comparable'
        else:
            failing_sr_ids = [
                pid for pid, entry in nested_sr.items()
                if entry.get('fatal_gate_triggered') or _entry_not_comparable(entry)
            ]
            failing_prof_ids = [
                str(p.get('id')).strip()
                for p in profiles
                if isinstance(p, dict)
                and _nonblank(p.get('id'))
                and (p.get('fatal_gate_triggered') or p.get('status') == 'not_comparable')
            ]
            if failing_sr_ids:
                target_id = failing_sr_ids[0]
            elif failing_prof_ids:
                target_id = failing_prof_ids[0]
            elif nested_sr:
                target_id = next(iter(nested_sr.keys()))
            elif profiles and isinstance(profiles[0], dict) and _nonblank(profiles[0].get('id')):
                target_id = str(profiles[0]['id']).strip()
            else:
                target_id = f'SC-{len(state.get("scorecards", {})) + 1}'

            if target_id in nested_sr:
                sr = nested_sr[target_id]
            elif not nested_sr and sr_map:
                sr = sr_map
            else:
                sr = {}

            any_sr_fatal = any(bool(entry.get('fatal_gate_triggered')) for entry in nested_sr.values())
            any_prof_fatal = any(bool(p.get('fatal_gate_triggered')) for p in profiles if isinstance(p, dict))
            fatal_gate = bool(
                payload.get('fatal_gate_triggered')
                or sr.get('fatal_gate_triggered')
                or any_sr_fatal
                or any_prof_fatal
            )
            any_sr_nc = any(_entry_not_comparable(entry) for entry in nested_sr.values())
            any_prof_nc = any(p.get('status') == 'not_comparable' for p in profiles if isinstance(p, dict))
            if any_sr_nc or any_prof_nc:
                sc_status = 'not_comparable'

        if sc_issues and sc_status != 'not_comparable':
            sc_status = 'not_comparable'

        rankings = payload.get('rankings') or []
        weighted_unrounded = None
        if rankings and isinstance(rankings[0], dict):
            for row in rankings[0].get('ordered') or []:
                if isinstance(row, dict) and row.get('id') == target_id:
                    weighted_unrounded = row.get('weighted_unrounded')
                    break
        if weighted_unrounded is None and isinstance(sr, dict):
            weighted_unrounded = sr.get('weighted_unrounded')
        overall = payload.get('overall')
        if overall is None and isinstance(sr, dict) and sr.get('overall') is not None:
            overall = sr.get('overall')
        if overall is None and weighted_unrounded is not None:
            try:
                overall = int(round(float(weighted_unrounded)))
            except Exception:
                overall = None
        target_profile = next((p for p in profiles if isinstance(p, dict) and p.get('id') == target_id), None)
        closest_ids = list((target_profile or {}).get('closest_work') or payload.get('closest_work_ids') or [])
        reading_basis = (target_profile or {}).get('reading_basis') or payload.get('reading_basis') or 'metadata_only'
        sid = str(links.get('scorecard_id') or f'SC-{len(state.get("scorecards", {})) + 1}').strip()
        state.setdefault('scorecards', {})[sid] = {
            'id': sid,
            'target_id': target_id,
            'overall': overall,
            'weighted_unrounded': weighted_unrounded,
            'band': sr.get('band') if isinstance(sr, dict) else None,
            'fatal_gate_triggered': fatal_gate,
            'reading_basis': reading_basis,
            'closest_work_ids': closest_ids,
            'status': sc_status,
            'scorecard_status': sc_status,
            'issues': sc_issues,
        }
        claim_ids = list(links.get('claim_ids') or [])
        if links.get('claim_id'):
            claim_ids.append(links['claim_id'])
        if not claim_ids and state.get('manuscript_claims'):
            claim_ids = list(state['manuscript_claims'].keys())
        for cid in claim_ids:
            _add_edge(state, 'claim', cid, 'scorecard', sid)
        ingested_ids.append(sid)

    elif kind == 'venue_novelty':
        if not isinstance(payload, dict):
            raise ValueError('venue_novelty must be a JSON object')
        sr = payload.get('submission_readiness') if isinstance(payload.get('submission_readiness'), dict) else {}
        port = payload.get('venue_portfolio_recommendations') if isinstance(payload.get('venue_portfolio_recommendations'), dict) else {}
        venue_obj = payload.get('venue') if isinstance(payload.get('venue'), dict) else {}
        vid = str(links.get('venue_verdict_id') or f'VV-{len(state.get("venue_verdicts", {})) + 1}').strip()
        venue_id = venue_obj.get('name') or sr.get('venue_id') or state.get('target_venue') or 'unspecified_venue'
        venue_tier = sr.get('venue_tier') or _resolve_tier(target_venue=venue_id, target_venue_tier=state.get('target_venue_tier'))
        verdict = sr.get('verdict') or port.get('portfolio_verdict') or payload.get('status') or 'unverified'
        ready = bool(sr.get('ready_to_submit', payload.get('ready_to_submit', False)))
        matched = sr.get('recommended_matched_tier') or port.get('recommended_matched_tier')
        state.setdefault('venue_verdicts', {})[vid] = {
            'id': vid,
            'venue_id': venue_id,
            'venue_tier': venue_tier,
            'verdict': verdict,
            'venue_verdict': verdict,
            'ready_to_submit': ready,
            'recommended_matched_tier': matched,
        }
        sc_ids = [links['scorecard_id']] if _nonblank(links.get('scorecard_id')) else list(state.get('scorecards', {}).keys())
        for sid in sc_ids:
            _add_edge(state, 'scorecard', sid, 'venue_verdict', vid)
        ingested_ids.append(vid)

    elif kind == 'rebuttal':
        if not isinstance(payload, dict):
            raise ValueError('rebuttal must be a JSON object')
        pts = payload.get('points') or payload.get('rebuttal_points') or []
        if isinstance(pts, dict):
            pts = list(pts.values())
        for pt in pts:
            if not isinstance(pt, dict):
                continue
            pid = str(pt.get('point_id') or pt.get('id') or '').strip()
            if not pid:
                continue
            claim_ids = list(pt.get('claim_ids') or links.get('claim_ids') or [])
            if links.get('claim_id') and links['claim_id'] not in claim_ids:
                claim_ids.append(links['claim_id'])
            run_ids = list(pt.get('run_ids') or links.get('run_ids') or [])
            state.setdefault('rebuttal_points', {})[pid] = {
                'point_id': pid,
                'claim_ids': claim_ids,
                'run_ids': run_ids,
                'anchor': pt.get('anchor', ''),
                'status': pt.get('status', 'pending'),
            }
            for cid in claim_ids:
                _add_edge(state, 'claim', cid, 'rebuttal_point', pid)
            ingested_ids.append(pid)

    elif kind == 'failure_cases':
        if not isinstance(payload, dict) or not isinstance(payload.get('failure_cases'), list):
            raise ValueError('failure_cases payload must be an object with failure_cases list')
        existing_ids = {fc.get('id') for fc in state.setdefault('failure_cases', []) if isinstance(fc, dict)}
        for fc in payload['failure_cases']:
            if not isinstance(fc, dict):
                continue
            fc_id = str(fc.get('id') or f'FC-{len(state["failure_cases"]) + 1}').strip()
            if fc_id not in existing_ids:
                copy_fc = dict(fc)
                copy_fc['id'] = fc_id
                state['failure_cases'].append(copy_fc)
                existing_ids.add(fc_id)
                ingested_ids.append(fc_id)

    else:
        raise ValueError(f'unsupported ingest_kind: {kind}')

    state['updated_at_utc'] = _utc_now()
    return {
        'ingested_kind': kind,
        'ingested_ids': ingested_ids,
        'errors': errors,
        'warnings': warnings,
    }


def _entity_exists(state: dict[str, Any], entity_type: str, entity_id: str) -> bool:
    mapping = {
        'gap': 'gaps',
        'idea': 'ideas',
        'rq': 'rqs',
        'experiment': 'experiments',
        'claim': 'manuscript_claims',
        'scorecard': 'scorecards',
        'venue_verdict': 'venue_verdicts',
        'rebuttal_point': 'rebuttal_points',
    }
    bucket = mapping.get(entity_type)
    if not bucket:
        return False
    return entity_id in (state.get(bucket) or {})


def audit_state(state: dict[str, Any], *, strict: bool = False) -> dict[str, Any]:
    if not isinstance(state, dict) or state.get('schema') != SCHEMA_VERSION:
        raise ValueError('invalid project_state object')
    errors: list[str] = []
    warnings: list[str] = []
    digests = state.get('corpus_digests') or {}

    for ev in state.get('provenance_events') or []:
        if isinstance(ev, dict) and ev.get('event') == 'silent_full_text_upgrade_blocked':
            msg = f"silent_full_text_upgrade_blocked:{ev.get('source_id')}"
            if strict:
                errors.append(msg)
            else:
                warnings.append(msg)

    for edge in state.get('lineage_edges') or []:
        if not isinstance(edge, dict):
            errors.append('malformed_lineage_edge')
            continue
        ft, fi = edge.get('from_type', ''), edge.get('from_id', '')
        tt, ti = edge.get('to_type', ''), edge.get('to_id', '')
        if not _entity_exists(state, ft, fi):
            errors.append(f'unknown_edge_source:{ft}:{fi}')
        if not _entity_exists(state, tt, ti):
            errors.append(f'unknown_edge_target:{tt}:{ti}')

    for gid, gap in (state.get('gaps') or {}).items():
        if gap.get('disposition') == 'supported_candidate':
            sup_ids = list(gap.get('support_source_ids') or [])
            cw_ids = list(gap.get('closest_work_ids') or [])
            if not sup_ids and not cw_ids:
                errors.append(f'gap_missing_supporting_sources:{gid}')
            for sid in dict.fromkeys(sup_ids + cw_ids):
                d = digests.get(sid)
                if not isinstance(d, dict) or d.get('access') not in FULL_TEXT_ACCESS_LEVELS:
                    errors.append(f'unread_or_metadata_only_source:gap:{gid}:{sid}')
        l_errs, l_warns = _validate_f32_lenses(gap.get('lenses_f32') or {})
        errors.extend(f'gap:{gid}:{e}' for e in l_errs)
        warnings.extend(f'gap:{gid}:{w}' for w in l_warns)

    for iid, idea in (state.get('ideas') or {}).items():
        gid = idea.get('gap_id')
        if _nonblank(gid) and gid not in (state.get('gaps') or {}):
            errors.append(f'unknown_parent_gap:idea:{iid}:{gid}')
        elif strict and not _nonblank(gid):
            errors.append(f'unlinked_idea_missing_gap:{iid}')

    for rqid, rq in (state.get('rqs') or {}).items():
        if not rq.get('valid_structure'):
            errors.append(f'invalid_question_card:{rqid}')
        iid = rq.get('idea_id')
        gid = rq.get('gap_id')
        if _nonblank(iid) and iid not in (state.get('ideas') or {}):
            errors.append(f'unknown_parent_idea:rq:{rqid}:{iid}')
        if _nonblank(gid) and gid not in (state.get('gaps') or {}):
            errors.append(f'unknown_parent_gap:rq:{rqid}:{gid}')

    for rid, run in (state.get('experiments') or {}).items():
        rqid = run.get('rq_id')
        if not _nonblank(rqid) or rqid not in (state.get('rqs') or {}):
            errors.append(f'unlinked_experiment_run:{rid}:{rqid}')
        for sha_field in ('result_artifact_sha256', 'split_manifest_sha256', 'metric_script_sha256'):
            val = run.get(sha_field)
            if not isinstance(val, str) or not HEX64_RE.fullmatch(val):
                errors.append(f'invalid_run_receipt_sha256:{rid}:{sha_field}')
        out_status = run.get('outcome_status') or run.get('outcome_analysis_status')
        if out_status in ('blocked_harking', 'gate_failed') or run.get('harking_detected'):
            errors.append(f'experiment_outcome_blocked:{rid}:{out_status or "blocked"}')
        if strict and run.get('engineering_verdict') != 'PASS':
            errors.append(f'experiment_engineering_failed:{rid}')

    ledger_meta = state.get('manuscript_ledger_status') or {}
    if ledger_meta.get('passed') is False or bool(ledger_meta.get('errors')):
        errors.append('manuscript_ledger_failed')
        for lerr in ledger_meta.get('errors') or []:
            errors.append(f'manuscript_ledger_issue:{lerr}')

    for cid, claim in (state.get('manuscript_claims') or {}).items():
        rqid = claim.get('rq_id')
        if claim.get('ledger_verified') is False or claim.get('ledger_passed') is False:
            errors.append(f'manuscript_ledger_claim_unverified:{cid}')
        if claim.get('material'):
            if not _nonblank(rqid) or rqid not in (state.get('rqs') or {}):
                errors.append(f'claim_missing_lineage_receipt:{cid}:rq_id')
            if claim.get('kind') == 'reported':
                rids = claim.get('run_ids') or []
                if not rids or any(r not in (state.get('experiments') or {}) for r in rids):
                    errors.append(f'claim_missing_lineage_receipt:{cid}:run_ids')
            for sid in claim.get('source_ids') or []:
                if sid not in digests:
                    errors.append(f'claim_missing_lineage_receipt:{cid}:source_id:{sid}')

    for sid, sc in (state.get('scorecards') or {}).items():
        if sc.get('fatal_gate_triggered'):
            errors.append(f'scorecard_fatal_gate_triggered:{sid}')
        if (sc.get('scorecard_status') or sc.get('status')) == 'not_comparable':
            errors.append(f'scorecard_not_comparable:{sid}')
        if sc.get('issues'):
            errors.append(f'scorecard_issues:{sid}')
        if sc.get('reading_basis') == 'full_text':
            for cw in sc.get('closest_work_ids') or []:
                d = digests.get(cw)
                if d is not None and d.get('access') not in FULL_TEXT_ACCESS_LEVELS:
                    errors.append(f'unread_or_metadata_only_source:scorecard:{sid}:{cw}')
                elif strict and d is None:
                    errors.append(f'unread_or_metadata_only_source:scorecard:{sid}:{cw}')

    for vid, vv in (state.get('venue_verdicts') or {}).items():
        v_verdict = vv.get('venue_verdict') or vv.get('verdict')
        if v_verdict == 'rejected_below_venue_tier':
            errors.append(f'venue_rejected_below_venue_tier:{vid}')
        if vv.get('ready_to_submit') is False:
            errors.append(f'venue_not_ready_to_submit:{vid}')

    for pid, pt in (state.get('rebuttal_points') or {}).items():
        if not _nonblank(pt.get('anchor')):
            errors.append(f'rebuttal_point_missing_anchor:{pid}')
        for cid in pt.get('claim_ids') or []:
            if cid not in (state.get('manuscript_claims') or {}):
                errors.append(f'unknown_claim_in_rebuttal:{pid}:{cid}')
        for rid in pt.get('run_ids') or []:
            if rid not in (state.get('experiments') or {}):
                errors.append(f'unknown_run_in_rebuttal:{pid}:{rid}')

    if strict:
        for vid, vv in (state.get('venue_verdicts') or {}).items():
            if vv.get('ready_to_submit'):
                if not state.get('experiments') or not state.get('scorecards'):
                    errors.append(f'strict_missing_upstream_for_venue_verdict:{vid}')
                if any(r.get('engineering_verdict') != 'PASS' for r in (state.get('experiments') or {}).values()):
                    errors.append(f'strict_upstream_engineering_failure_blocks_venue:{vid}')

    stage_summary = {
        'corpus_digests': len(digests),
        'full_text_digests': sum(1 for d in digests.values() if d.get('access') in FULL_TEXT_ACCESS_LEVELS),
        'gaps': len(state.get('gaps') or {}),
        'ideas': len(state.get('ideas') or {}),
        'rqs': len(state.get('rqs') or {}),
        'experiments': len(state.get('experiments') or {}),
        'manuscript_claims': len(state.get('manuscript_claims') or {}),
        'scorecards': len(state.get('scorecards') or {}),
        'venue_verdicts': len(state.get('venue_verdicts') or {}),
        'rebuttal_points': len(state.get('rebuttal_points') or {}),
        'failure_cases': len(state.get('failure_cases') or []),
        'lineage_edges': len(state.get('lineage_edges') or []),
    }
    return {
        'status': 'passed' if not errors else 'issues_detected',
        'errors': errors,
        'warnings': warnings,
        'stage_summary': stage_summary,
        'lineage_coverage': {
            'has_full_text_digest': stage_summary['full_text_digests'] > 0,
            'has_edges': stage_summary['lineage_edges'] > 0,
        },
    }


def assess_mechanism_decomposition(idea: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(idea, dict):
        raise ValueError('idea must be a JSON object')
    md = idea.get('mechanism_decomposition') if isinstance(idea.get('mechanism_decomposition'), dict) else idea
    title = str(idea.get('title') or '').strip()
    summary = str(idea.get('summary') or idea.get('description') or '').strip()
    bottleneck = str(md.get('bottleneck_target') or '').strip()
    why_fails = str(md.get('why_sota_fails') or '').strip()
    mechanism = str(md.get('proposed_mechanism') or '').strip()
    simplest = str(md.get('simplest_alternative') or '').strip()
    components = md.get('components') if isinstance(md.get('components'), list) else []

    combined_text = ' '.join(x for x in (title, summary, mechanism) if x)
    stitch_cue = bool(_STITCHING_RE.search(combined_text)) or len(components) >= 2

    issues: list[str] = []
    warnings: list[str] = []
    if _is_placeholder(bottleneck) or len(bottleneck.split()) < 3:
        issues.append('missing_or_vague_bottleneck_target')
    if _is_placeholder(why_fails) or len(why_fails.split()) < 3:
        issues.append('missing_or_vague_why_sota_fails')
    if _is_placeholder(mechanism) or len(mechanism.split()) < 3:
        issues.append('missing_or_vague_proposed_mechanism')
    if _is_placeholder(simplest) or len(simplest.split()) < 4:
        issues.append('missing_or_weak_simplest_alternative')

    is_vague_stitching = bool(stitch_cue and issues)
    if is_vague_stitching:
        issues.append('vague_module_stitching_rejected')
    elif stitch_cue:
        warnings.append('multi_component_proposal_requires_component_ablation')

    return {
        'passed': not issues,
        'is_vague_stitching': is_vague_stitching,
        'stitching_cue_detected': stitch_cue,
        'issues': issues,
        'warnings': warnings,
    }


def advise_contribution_pivot(
    idea: dict[str, Any],
    *,
    evidence_signals: dict[str, Any] | None = None,
    author_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(idea, dict):
        raise ValueError('idea must be a JSON object')
    signals = evidence_signals or {}
    profile = author_profile or {}
    current = str(idea.get('contribution_type') or 'method').strip()
    if current not in CONTRIBUTION_TYPES:
        current = 'method'
    lenses = idea.get('lenses_f32') if isinstance(idea.get('lenses_f32'), dict) else {}
    eval_gap = lenses.get('evaluation_validity_gap') if isinstance(lenses.get('evaluation_validity_gap'), dict) else {}
    mech = assess_mechanism_decomposition(idea)

    candidates: list[str] = []
    rationale_parts: list[str] = []
    strength = str(profile.get('strength_profile') or '').strip()

    is_eval_gap = bool(eval_gap.get('is_eval_gap')) or (
        eval_gap.get('is_eval_gap') is not False
        and (eval_gap.get('subtype') is not None or bool(eval_gap.get('cues')) or bool(eval_gap.get('subtypes')))
    )
    if is_eval_gap:
        candidates.extend(['benchmark_dataset', 'diagnostic'])
        rationale_parts.append('Evaluation validity gap detected: benchmark/diagnostic framing directly targets construct flaws.')

    if lenses.get('durability_12_24m') == 'high_scaling_erasure_risk':
        candidates.extend(['scaling_law', 'diagnostic', 'theoretical_bound'])
        rationale_parts.append('High 12-24m scaling erasure risk: pivot from wrapper method to scaling law, diagnostic, or theory.')

    if signals.get('simplest_alternative_equal_or_better') or signals.get('negative_or_mixed_delta') or mech['is_vague_stitching']:
        if strength == 'math_theory':
            candidates.append('theoretical_bound')
        candidates.extend(['diagnostic', 'empirical_analysis'])
        rationale_parts.append('Method gain not established over simplest baseline or stitching lacks bottleneck justification.')

    if strength == 'math_theory' and current == 'method' and signals.get('needs_formal_guarantee'):
        candidates.append('theoretical_bound')

    deduped = []
    for c in candidates:
        if c not in deduped:
            deduped.append(c)

    recommended = deduped[0] if deduped else current
    pivot_needed = recommended != current
    if not rationale_parts:
        rationale_parts.append(f'Keep {current} framing; verify simplest alternative and killer experiment before full scaling.')

    return {
        'current_type': current,
        'recommended_type': recommended,
        'pivot_needed': pivot_needed,
        'rationale': ' '.join(rationale_parts),
        'candidate_pivots': deduped or [current],
    }


def score_author_advantage(gap_or_idea: dict[str, Any], author_profile: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(gap_or_idea, dict):
        raise ValueError('gap_or_idea must be a JSON object')
    profile = author_profile or {}
    strength = str(profile.get('strength_profile') or '').strip()
    gpu_budget = profile.get('gpu_budget_hours')
    avail_weeks = profile.get('timeline_weeks')
    owned_assets = set(str(x).strip().lower() for x in (profile.get('proprietary_assets') or []) if _nonblank(x))

    req_strengths = [str(x).strip() for x in (gap_or_idea.get('required_strengths') or []) if _nonblank(x)]
    req_gpu = gap_or_idea.get('required_gpu_hours')
    est_weeks = gap_or_idea.get('estimated_weeks')
    req_assets = [str(x).strip().lower() for x in (gap_or_idea.get('required_assets') or []) if _nonblank(x)]

    advantages: list[str] = []
    mismatches: list[str] = []
    questions: list[str] = []

    if req_strengths:
        if strength and strength in req_strengths:
            advantages.append(f'strength_match:{strength}')
        elif strength:
            mismatches.append(f'strength_mismatch:author={strength}:required={req_strengths}')
            questions.append(f'This direction demands {req_strengths}, whereas your profile is {strength}. Can you re-scope around {strength}?')
        else:
            questions.append(f'Which author strength applies here ({", ".join(req_strengths)})?')

    if isinstance(req_gpu, (int, float)) and not isinstance(req_gpu, bool):
        if isinstance(gpu_budget, (int, float)) and not isinstance(gpu_budget, bool):
            if req_gpu > gpu_budget:
                mismatches.append(f'gpu_budget_exceeded:required={req_gpu}:available={gpu_budget}')
                questions.append(f'Required GPU budget ({req_gpu}h) exceeds available ({gpu_budget}h); can you test a low-GPU proxy or analytical slice first?')
            elif req_gpu <= gpu_budget * 0.5:
                advantages.append('comfortable_gpu_margin')
        else:
            questions.append('What GPU-hour budget is available for pilot and full runs?')

    if isinstance(est_weeks, (int, float)) and not isinstance(est_weeks, bool):
        if isinstance(avail_weeks, (int, float)) and not isinstance(avail_weeks, bool):
            if est_weeks > avail_weeks:
                mismatches.append(f'timeline_exceeded:estimated={est_weeks}w:available={avail_weeks}w')
                questions.append(f'Estimated timeline ({est_weeks}w) exceeds {avail_weeks}w; what minimal 1-2 day killer experiment can de-risk it now?')

    missing_assets = [a for a in req_assets if a not in owned_assets]
    if missing_assets:
        mismatches.append(f'missing_required_assets:{missing_assets}')
        questions.append(f'How will you obtain required assets ({", ".join(missing_assets)}) without unverified assumptions?')
    elif req_assets:
        advantages.append('proprietary_asset_advantage')

    if any(m.startswith(('gpu_budget_exceeded', 'timeline_exceeded', 'missing_required_assets', 'strength_mismatch')) for m in mismatches):
        fit = 'misaligned_or_infeasible'
    elif advantages:
        fit = 'strong_comparative_advantage'
    else:
        fit = 'feasible_neutral'

    return {
        'fit_classification': fit,
        'mismatches': mismatches,
        'advantages': advantages,
        'socratic_questions': questions[:3],
    }


def assess_mpu_scope(
    idea: dict[str, Any],
    *,
    target_venue: str | None = None,
    target_venue_tier: str | None = None,
    timeline_weeks: float | None = None,
) -> dict[str, Any]:
    if not isinstance(idea, dict):
        raise ValueError('idea must be a JSON object')
    resolved_tier = _resolve_tier(target_venue=target_venue, target_venue_tier=target_venue_tier)
    md = idea.get('mechanism_decomposition') if isinstance(idea.get('mechanism_decomposition'), dict) else {}
    components = md.get('components') if isinstance(md.get('components'), list) else (idea.get('components') or [])
    planned_contribs = idea.get('planned_contributions_count', 1)
    planned_datasets = idea.get('planned_datasets_count', 2)
    est_weeks = idea.get('estimated_weeks')
    ceiling = idea.get('gap_tier_ceiling')

    issues: list[str] = []
    recs: list[str] = []

    over_scoped = False
    if isinstance(planned_contribs, int) and not isinstance(planned_contribs, bool) and planned_contribs >= 3:
        over_scoped = True
        issues.append(f'too_many_bundled_contributions:{planned_contribs}')
    if isinstance(components, list) and len(components) >= 4:
        over_scoped = True
        issues.append(f'excessive_component_count:{len(components)}')
    if (
        isinstance(est_weeks, (int, float))
        and not isinstance(est_weeks, bool)
        and isinstance(timeline_weeks, (int, float))
        and not isinstance(timeline_weeks, bool)
        and timeline_weeks > 0
        and est_weeks > timeline_weeks * 1.5
    ):
        over_scoped = True
        issues.append(f'timeline_overscoped:{est_weeks}w_vs_{timeline_weeks}w')

    under_scoped = False
    if resolved_tier in {'top_tier_flagship', 'q1_or_tier_a'}:
        if ceiling in {'workshop_incremental_only', 'low_impact_dead_end'}:
            under_scoped = True
            issues.append(f'gap_tier_ceiling_below_target:{ceiling}')
        if isinstance(planned_datasets, int) and not isinstance(planned_datasets, bool) and planned_datasets < 2 and idea.get('contribution_type', 'method') != 'theoretical_bound':
            under_scoped = True
            issues.append('single_dataset_insufficient_for_q1_or_top_tier')

    if over_scoped:
        verdict = 'over_scoped_for_mpu'
        recs.append('Split independent mechanisms into a focused 1-contribution MPU and isolate secondary ideas for follow-up.')
    elif under_scoped:
        verdict = 'under_scoped_for_target_tier'
        recs.append('Either deepen mechanistic/multi-regime validation or retarget from Q1/Top-Tier to Workshop / Findings.')
    else:
        verdict = 'well_scoped_mpu'
        recs.append('Scope fits a cohesive Minimum Publishable Unit; lock a 1-2 day killer experiment next.')

    return {
        'mpu_verdict': verdict,
        'target_venue_tier': resolved_tier,
        'issues': issues,
        'recommendations': recs,
    }


def evaluate_ideation(state: dict[str, Any], idea: dict[str, Any]) -> dict[str, Any]:
    mech = assess_mechanism_decomposition(idea)
    pivot = advise_contribution_pivot(idea, author_profile=state.get('author_profile'))
    adv = score_author_advantage(idea, state.get('author_profile'))
    avail_weeks = (state.get('author_profile') or {}).get('timeline_weeks')
    mpu = assess_mpu_scope(
        idea,
        target_venue=state.get('target_venue'),
        target_venue_tier=state.get('target_venue_tier'),
        timeline_weeks=avail_weeks,
    )
    passed = (
        mech['passed']
        and mpu['mpu_verdict'] == 'well_scoped_mpu'
        and adv['fit_classification'] != 'misaligned_or_infeasible'
    )
    return {
        'passed': passed,
        'mechanism_decomposition': mech,
        'contribution_pivot': pivot,
        'author_advantage': adv,
        'mpu_scope': mpu,
    }


def generate_next_step_prompt(state: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(state, dict) or state.get('schema') != SCHEMA_VERSION:
        raise ValueError('invalid project_state object')
    audit = audit_state(state, strict=True)
    profile = state.get('author_profile') or {}
    digests = state.get('corpus_digests') or {}
    gaps = state.get('gaps') or {}
    ideas = state.get('ideas') or {}
    rqs = state.get('rqs') or {}
    experiments = state.get('experiments') or {}
    claims = state.get('manuscript_claims') or {}
    scorecards = state.get('scorecards') or {}
    venues = state.get('venue_verdicts') or {}
    rebuttals = state.get('rebuttal_points') or {}

    blocking = list(audit['errors'])
    questions: list[str] = []
    cmds: list[str] = []

    if not profile or not state.get('target_venue_tier') or not profile.get('strength_profile'):
        stage = 'intake'
        if not state.get('target_venue_tier'):
            questions.append('Target venue tier: Q1 / Top-Tier Main Track (NeurIPS/ICML/ICLR/CVPR/ACL) or fast/bounded publication (Findings/Tier-A/Workshop)?')
        if not profile.get('gpu_budget_hours') or not profile.get('timeline_weeks'):
            questions.append('What GPU-hour budget, dataset access, and calendar weeks are available?')
        if not profile.get('strength_profile'):
            questions.append('What is your comparative advantage (math_theory, systems_engineering, empirical_eval, or data_curation)?')
        questions = questions[:3]
        next_step = 'Complete 2-3 question Socratic intake and scaffold initial corpus/gap/dossier inputs.'
        cmds = ['python3 research-scientist/scripts/build_research_inputs.py --topic "<your topic>" --offline --out-dir ./inputs --compact']
    elif not digests or not gaps:
        stage = 'gap_discovery'
        next_step = 'Build corpus & scaffold inputs, read closest works in full_text, and shortlist <=3 surviving gaps.'
        cmds = [
            'python3 research-scientist/scripts/build_research_inputs.py --topic "<your topic>" --out-dir ./inputs --compact',
            'python3 research-scientist/scripts/gap_pipeline.py --corpus ./inputs/corpus.json --digests ./digests.json --candidates ./candidates.json --out ./gap_pipeline.json --compact',
        ]
    elif not ideas:
        stage = 'ideation_framing'
        next_step = 'Decompose the exact SOTA bottleneck, avoid module stitching, assess MPU scope, and design a 1-2 day killer experiment.'
        cmds = ['python3 research-scientist/scripts/project_state.py --state project_state.json --evaluate-ideation idea.json --compact']
    else:
        ideation_bad = [iid for iid, idea in ideas.items() if not evaluate_ideation(state, idea)['passed']]
        if ideation_bad:
            stage = 'ideation_framing'
            blocking.append(f'ideation_gate_failed:{",".join(ideation_bad)}')
            next_step = 'Resolve mechanism stitching, author-advantage mismatch, or MPU over/under-scoping before freezing RQ.'
            cmds = ['python3 research-scientist/scripts/project_state.py --state project_state.json --evaluate-ideation idea.json --compact']
        elif not rqs or any(not rq.get('valid_structure') for rq in rqs.values()):
            stage = 'rq_formulation'
            next_step = 'Freeze a falsifiable Question Card with rival explanation and 1-2 day killer pilot criteria.'
            cmds = [
                'python3 research-scientist/scripts/check_question_card.py question_card.json',
                'python3 research-scientist/scripts/project_state.py --state project_state.json --ingest-kind question_card --ingest-file question_card.json --compact',
            ]
        elif not experiments or any(
            r.get('engineering_verdict') != 'PASS'
            or (r.get('outcome_status') or r.get('outcome_analysis_status')) in ('pending', 'blocked_harking', 'gate_failed')
            or r.get('harking_detected')
            for r in experiments.values()
        ):
            stage = 'experiment_and_outcome_audit'
            next_step = 'Verify run receipts (SHA-256), run engineering diagnostics, and audit error slices against frozen question_card.json.'
            cmds = [
                'python3 research-scientist/scripts/check_experiment_manifest.py manifest.json --verify-files --compact',
                'python3 research-scientist/scripts/analyze_experiment_outcome.py --question-card question_card.json --outcomes outcomes.json --manifest manifest.json --compact',
            ]
        elif (
            not claims
            or not scorecards
            or (state.get('manuscript_ledger_status') or {}).get('passed') is False
            or bool((state.get('manuscript_ledger_status') or {}).get('errors'))
            or any(c.get('ledger_verified') is False or c.get('ledger_passed') is False for c in claims.values())
            or any(
                sc.get('fatal_gate_triggered')
                or (sc.get('scorecard_status') or sc.get('status')) == 'not_comparable'
                or bool(sc.get('issues'))
                for sc in scorecards.values()
            )
        ):
            stage = 'manuscript_and_scoring'
            next_step = 'Audit manuscript claim-to-evidence ledger and score >=3 closest full-text baselines via compare_scorecards.py.'
            cmds = [
                'python3 research-scientist/scripts/check_manuscript_ledger.py --ledger ledger.json --manuscript paper.tex --compact',
                'python3 research-scientist/scripts/compare_scorecards.py scorecards.json --target-id target_paper --strict-related-panel --compact',
            ]
        elif not venues or any(
            (not vv.get('ready_to_submit')) or (vv.get('venue_verdict') or vv.get('verdict')) == 'rejected_below_venue_tier'
            for vv in venues.values()
        ):
            stage = 'venue_evaluation'
            next_step = 'Verify CFP snapshots and evaluate multi-venue portfolio & cross-topic contribution bar.'
            cmds = [
                'python3 research-scientist/scripts/compare_venue_novelty.py profile.json --portfolio --require-panels --compact',
            ]
        elif any(pt.get('status') == 'pending' for pt in rebuttals.values()):
            stage = 'rebuttal'
            next_step = 'Verify every rebuttal point carries a concrete Table/Figure/Run anchor.'
            cmds = ['python3 research-scientist/scripts/check_rebuttal.py coverage triage_points.md rebuttal.md --strict --compact']
        elif blocking:
            if any(e.startswith(('silent_full_text_upgrade_blocked', 'unread_or_metadata_only_source:gap:', 'gap_missing_supporting_sources')) for e in blocking):
                stage = 'gap_discovery'
                next_step = 'Resolve unverified full_text provenance or missing supporting sources on candidate gaps.'
                cmds = ['python3 research-scientist/scripts/project_state.py --state project_state.json --audit --strict --compact']
            elif any(e.startswith(('unlinked_experiment_run:', 'invalid_run_receipt_sha256:')) for e in blocking):
                stage = 'experiment_and_outcome_audit'
                next_step = 'Fix missing RQ links or invalid SHA-256 run receipts in experiment manifest.'
                cmds = ['python3 research-scientist/scripts/check_experiment_manifest.py manifest.json --verify-files --compact']
            elif any(e.startswith(('rebuttal_point_', 'unknown_claim_in_rebuttal', 'unknown_run_in_rebuttal')) for e in blocking):
                stage = 'rebuttal'
                next_step = 'Fix missing anchors or unknown claim/run links in rebuttal points.'
                cmds = ['python3 research-scientist/scripts/check_rebuttal.py coverage triage_points.md rebuttal.md --strict --compact']
            else:
                stage = 'manuscript_and_scoring'
                next_step = 'Resolve remaining lineage and provenance audit errors before reporting.'
                cmds = ['python3 research-scientist/scripts/project_state.py --state project_state.json --audit --strict --compact']
        else:
            stage = 'ready_for_reporting'
            next_step = 'All lifecycle gates passed; generate concise EN/VI user report PDF.'
            cmds = ['python3 research-scientist/scripts/report_latex_pdf.py --input summary.json --out report.pdf --strict --compact']

    prompt_text = f'[{stage}] {next_step}'
    if blocking:
        prompt_text += f' Blocking: {"; ".join(blocking[:3])}.'
    return {
        'schema': ADVISOR_SCHEMA,
        'project_id': state.get('project_id'),
        'current_stage': stage,
        'blocking_issues': blocking,
        'warnings': audit['warnings'],
        'socratic_questions': questions,
        'recommended_next_step': next_step,
        'recommended_commands': cmds,
        'advisor_prompt': prompt_text,
    }


def _auto_artifact_path(prefix: str) -> Path:
    art_dir = Path(tempfile.gettempdir()) / 'research_scientist_artifacts'
    art_dir.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(prefix=f'{prefix}_', suffix='.json', dir=str(art_dir))
    import os
    os.close(fd)
    return Path(raw_path)


def _compact_payload(result: dict[str, Any], out_path: str | None) -> dict[str, Any]:
    target = Path(out_path) if out_path else _auto_artifact_path('project_state')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2), encoding='utf-8')
    compact: dict[str, Any] = {
        'compact': True,
        'schema': result.get('schema', SCHEMA_VERSION),
        'artifact_path': str(target),
    }
    for key in ('status', 'project_id', 'current_stage', 'passed', 'recommended_next_step'):
        if key in result:
            compact[key] = result[key]
    if 'audit' in result and isinstance(result['audit'], dict):
        compact['audit_status'] = result['audit'].get('status')
        compact['error_count'] = len(result['audit'].get('errors') or [])
    if 'errors' in result and isinstance(result['errors'], list):
        compact['errors'] = result['errors'][:5]
    if 'blocking_issues' in result and isinstance(result['blocking_issues'], list):
        compact['blocking_issues'] = result['blocking_issues'][:5]
    if 'socratic_questions' in result and isinstance(result['socratic_questions'], list):
        compact['socratic_questions'] = result['socratic_questions'][:3]
    if 'recommended_commands' in result and isinstance(result['recommended_commands'], list):
        compact['recommended_commands'] = result['recommended_commands'][:2]
    encoded = json.dumps(compact, ensure_ascii=False).encode('utf-8')
    if len(encoded) >= MAX_COMPACT_BYTES:
        compact = {
            'compact': True,
            'schema': compact['schema'],
            'status': compact.get('status') or compact.get('audit_status'),
            'artifact_path': str(target),
        }
    return compact


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', help='Path to project_state.json')
    parser.add_argument('--init', action='store_true', help='Initialize a new project_state.json')
    parser.add_argument('--project-id', help='Project identifier when initializing state')
    parser.add_argument('--title', default='', help='Project title')
    parser.add_argument('--subfield-preset', choices=ALLOWED_SUBFIELD_PRESETS, help='Subfield preset')
    parser.add_argument('--target-venue', help='Target venue name')
    parser.add_argument('--target-venue-tier', help='Target venue tier')
    parser.add_argument('--author-profile', help='Path to author_profile JSON')
    parser.add_argument('--ingest-kind', help='Artifact kind to ingest into project state')
    parser.add_argument('--ingest-file', help='Path to artifact JSON to ingest')
    parser.add_argument('--link-gap', help='Optional gap ID for lineage linking')
    parser.add_argument('--link-idea', help='Optional idea ID for lineage linking')
    parser.add_argument('--link-rq', help='Optional RQ ID for lineage linking')
    parser.add_argument('--link-run', help='Optional run ID for lineage linking')
    parser.add_argument('--link-claim', help='Optional claim ID for lineage linking')
    parser.add_argument('--link-scorecard', help='Optional scorecard ID for lineage linking')
    parser.add_argument('--audit', action='store_true', help='Audit lineage & provenance integrity')
    parser.add_argument('--strict', action='store_true', help='Strict cross-stage lineage audit')
    parser.add_argument('--evaluate-ideation', help='Path to idea JSON or existing idea ID in state')
    parser.add_argument('--advise', action='store_true', help='Emit Interactive Advisor next-step prompt')
    parser.add_argument('--out', help='Path to persist output JSON')
    parser.add_argument('--compact', action='store_true', help='Emit <4096B compact JSON summary')
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        state_arg = _require_nonempty_arg(args.state, '--state')
        out_arg = _require_nonempty_arg(args.out, '--out')
        author_arg = _require_nonempty_arg(args.author_profile, '--author-profile')
        ingest_kind = _require_nonempty_arg(args.ingest_kind, '--ingest-kind')
        ingest_file = _require_nonempty_arg(args.ingest_file, '--ingest-file')
        eval_arg = _require_nonempty_arg(args.evaluate_ideation, '--evaluate-ideation')
        target_venue_arg = _require_nonempty_arg(args.target_venue, '--target-venue')
        target_venue_tier_arg = _require_nonempty_arg(args.target_venue_tier, '--target-venue-tier')

        if args.init:
            pid = _require_nonempty_arg(args.project_id, '--project-id') or 'proj-001'
            ap = _load_json(author_arg, '--author-profile') if author_arg else None
            state = init_state(
                pid,
                title=args.title,
                subfield_preset=args.subfield_preset,
                target_venue=target_venue_arg,
                target_venue_tier=target_venue_tier_arg,
                author_profile=ap,
            )
            if state_arg:
                sp = Path(state_arg)
                sp.parent.mkdir(parents=True, exist_ok=True)
                sp.write_text(json.dumps(state, indent=2), encoding='utf-8')
        else:
            if not state_arg:
                raise ValueError('--state is required unless --init is used')
            state = _load_json(state_arg, '--state')
            if author_arg:
                ap = _load_json(author_arg, '--author-profile')
                if not isinstance(ap, dict):
                    raise ValueError('--author-profile must be a JSON object')
                state['author_profile'] = ap
            if args.subfield_preset:
                state['subfield_preset'] = args.subfield_preset
            if target_venue_tier_arg is not None:
                _validate_target_venue_tier(target_venue_tier_arg)
            if target_venue_arg is not None:
                state['target_venue'] = target_venue_arg
            if target_venue_tier_arg is not None or target_venue_arg is not None:
                state['target_venue_tier'] = _resolve_tier(
                    target_venue=state.get('target_venue'),
                    target_venue_tier=target_venue_tier_arg or state.get('target_venue_tier'),
                )

        exit_code = 0
        result: dict[str, Any] = {'schema': SCHEMA_VERSION, 'project_id': state.get('project_id')}

        if ingest_kind or ingest_file:
            if not (ingest_kind and ingest_file):
                raise ValueError('--ingest-kind and --ingest-file must be provided together')
            payload = _load_json(ingest_file, '--ingest-file')
            links = {
                k: v for k, v in (
                    ('gap_id', _require_nonempty_arg(args.link_gap, '--link-gap')),
                    ('idea_id', _require_nonempty_arg(args.link_idea, '--link-idea')),
                    ('rq_id', _require_nonempty_arg(args.link_rq, '--link-rq')),
                    ('run_id', _require_nonempty_arg(args.link_run, '--link-run')),
                    ('claim_id', _require_nonempty_arg(args.link_claim, '--link-claim')),
                    ('scorecard_id', _require_nonempty_arg(args.link_scorecard, '--link-scorecard')),
                ) if v is not None
            }
            ingest_res = ingest_artifact(state, ingest_kind, payload, link_ids=links)
            result['ingest'] = ingest_res
            if ingest_res['errors']:
                exit_code = 1

        if eval_arg:
            if eval_arg in (state.get('ideas') or {}):
                idea_obj = state['ideas'][eval_arg]
            else:
                idea_obj = _load_json(eval_arg, '--evaluate-ideation')
            eval_res = evaluate_ideation(state, idea_obj)
            result['ideation_evaluation'] = eval_res
            result['passed'] = eval_res['passed']
            if not eval_res['passed']:
                exit_code = 1

        if args.audit:
            audit_res = audit_state(state, strict=args.strict)
            result['audit'] = audit_res
            result['status'] = audit_res['status']
            if audit_res['status'] != 'passed':
                exit_code = 1

        if args.advise:
            adv_res = generate_next_step_prompt(state)
            result['advisor'] = adv_res
            result['current_stage'] = adv_res['current_stage']
            result['recommended_next_step'] = adv_res['recommended_next_step']
            result['socratic_questions'] = adv_res['socratic_questions']
            result['recommended_commands'] = adv_res['recommended_commands']
            result['blocking_issues'] = adv_res['blocking_issues']

        if state_arg:
            sp = Path(state_arg)
            sp.parent.mkdir(parents=True, exist_ok=True)
            sp.write_text(json.dumps(state, indent=2), encoding='utf-8')
            result['state_path'] = str(sp)

        if not any((args.audit, args.advise, eval_arg, ingest_kind)):
            result['state'] = state
            result['status'] = 'initialized' if args.init else 'loaded'

        if out_arg and not args.compact:
            op = Path(out_arg)
            op.parent.mkdir(parents=True, exist_ok=True)
            op.write_text(json.dumps(result, indent=2), encoding='utf-8')

        if args.compact:
            print(json.dumps(_compact_payload(result, out_arg), ensure_ascii=False))
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        return exit_code
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
