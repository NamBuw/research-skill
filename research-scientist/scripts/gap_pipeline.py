#!/usr/bin/env python3
"""Research gap discovery, verification & parsimony gating pipeline (pure stdlib).

Clean-room implementation for per-candidate kill-search (require_abstract=False)
and hypothesis feedback memory.
Permissive attributions:
- grounded-research-ideation (MIT): read-before-cite and dual-regime coverage checks.
- SGHA (Apache-2.0): 5-role skeptic/critic gate and counterevidence linking.
- CKM-HypoGen (MIT): temporal cutoff leak detection and hindsight closure checks.
- AI-Researcher (MIT): stopword-filtered token Jaccard deduplication.
- ResearchRadar (MIT): whole-word plural-boundary matching and limitation/quote checks.
"""
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

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

try:
    import check_engineering_diagnostics as _eng_diag
except ImportError:
    _eng_diag = None

from check_ai_cs_research_plan import _analyze_string_ablation

_STOPWORDS = frozenset({
    'a', 'an', 'and', 'are', 'as', 'at', 'be', 'been', 'by', 'for', 'from', 'has',
    'have', 'in', 'into', 'is', 'it', 'its', 'not', 'of', 'on', 'or', 'such',
    'than', 'that', 'the', 'their', 'these', 'this', 'to', 'under', 'using', 'via',
    'was', 'were', 'which', 'with', 'without', 'remains', 'open', 'unaddressed',
    'uncharacterized', 'existing', 'recent', 'models', 'methods', 'approach',
    'approaches', 'paper', 'papers', 'work', 'study', 'studies', 'benchmark',
    'benchmarking', 'replacing', 'against', 'still', 'only',
})
_INFLATION_RE = re.compile(
    r'\b(?:fundamental\s+crisis|catastrophic\s+failure|plagued\s+by\s+severe\s+limitations|'
    r'paradigm\s+collapse|all\s+prior\s+work\s+fails?)\b',
    re.I,
)
_NOISE_HINT_RE = re.compile(
    r'\b(?:0?\.[0-4]\s*%|noisy|seed\s+fluctuation|2\s+random\s+seeds|hyperparameter\s+mismatch)\b',
    re.I,
)
_BOILERPLATE_ALT = {'', 'na', 'n a', 'none', 'tbd', 'todo', 'unknown', 'not applicable'}
_DISMISSIVE_ALT_RE = re.compile(
    r'\b(?:obviously\s+fail|insufficient|clearly\s+inferior|cannot\s+work|inadequate)\b',
    re.I,
)
_FULL_TEXT_ACCESS = frozenset({'full_text', 'selected_full_text', 'full'})

GAP_TIER_CEILINGS = (
    'q1_top_tier_potential',
    'tier_a_findings_potential',
    'workshop_incremental_only',
    'low_impact_dead_end',
)
_TIER_RANK = {tier: idx for idx, tier in enumerate(GAP_TIER_CEILINGS)}
_TARGET_TIER_TO_MIN_CEILING = {
    'q1': 'q1_top_tier_potential',
    'q1_top_tier': 'q1_top_tier_potential',
    'q1_top_tier_potential': 'q1_top_tier_potential',
    'top_tier': 'q1_top_tier_potential',
    'top_tier_flagship': 'q1_top_tier_potential',
    'flagship': 'q1_top_tier_potential',
    'ccf_a': 'q1_top_tier_potential',
    'tier_s': 'q1_top_tier_potential',
    's': 'q1_top_tier_potential',
    'tier_a': 'tier_a_findings_potential',
    'tier_a_findings_potential': 'tier_a_findings_potential',
    'findings': 'tier_a_findings_potential',
    'ccf_b': 'tier_a_findings_potential',
    'q1_or_tier_a': 'tier_a_findings_potential',
    'a': 'tier_a_findings_potential',
    'q2_q3': 'tier_a_findings_potential',
    'q2': 'tier_a_findings_potential',
    'q3': 'tier_a_findings_potential',
    'tier_b': 'tier_a_findings_potential',
    'ccf_c': 'tier_a_findings_potential',
    'q2_q3_or_tier_b': 'tier_a_findings_potential',
    'workshop': 'workshop_incremental_only',
    'workshop_incremental_only': 'workshop_incremental_only',
    'workshop_or_preliminary': 'workshop_incremental_only',
    'preliminary': 'workshop_incremental_only',
    'low_impact_dead_end': 'low_impact_dead_end',
}
SCOOP_RISK_LEVELS = (
    'low',
    'moderate',
    'high_scoop_risk',
    'high_scaling_obsolescence_risk',
    'unknown',
)
ROOT_CAUSE_BARRIERS = (
    'theoretical_limit',
    'measurement_gap',
    'data_supervision_gap',
    'compute_infra_barrier',
)
EVAL_VALIDITY_SUBTYPES = (
    'shortcut_exploitation',
    'dataset_bias_or_contamination',
    'metric_saturation',
    'construct_validity_mismatch',
)
SO_WHAT_IMPACTS = ('decision_changing', 'marginal_gain')
DURABILITY_LEVELS = ('durable_structural_limit', 'high_scaling_erasure_risk')
PORTFOLIO_ANGLES = (
    'minimal_fix',
    'minimal_fix_f19',
    'high_novelty_mechanism',
    'high_novelty_mechanism_q1',
    'benchmark_diagnostic_analysis',
    'low_gpu_fallback',
)
_CANONICAL_PORTFOLIO_ANGLE = {
    'minimal_fix': 'minimal_fix',
    'minimal_fix_f19': 'minimal_fix',
    'high_novelty_mechanism': 'high_novelty_mechanism',
    'high_novelty_mechanism_q1': 'high_novelty_mechanism',
    'benchmark_diagnostic_analysis': 'benchmark_diagnostic_analysis',
    'low_gpu_fallback': 'low_gpu_fallback',
}
SUBFIELD_PRESETS: dict[str, tuple[str, ...]] = {
    'nlp_llm': (
        'contamination_check',
        'multi_prompt_variance',
        'compute_matched_open_weight_baseline',
        'eval_harness_parity',
    ),
    'cv_multimodal': (
        'backbone_resolution_augmentation_parity',
        'flops_fps_memory_tradeoff',
        'qualitative_failure_analysis',
    ),
    'ml_theory': (
        'assumption_tightness_realism',
        'lower_vs_upper_bound_gap',
        'empirical_sanity_validation',
    ),
    'ai_systems': (
        'end_to_end_vs_microbenchmark',
        'tail_latency_p99',
        'peak_vram_comm_overhead',
        'matched_hardware',
    ),
}
_MECHANISM_SYNONYM_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({'reciprocal rank fusion', 'rrf', 'rank aggregation', 'multi-list score fusion'}),
    frozenset({'temperature scaling', 'post-hoc logit calibration', 'platt scaling'}),
    frozenset({'chain-of-thought', 'step-by-step rationale decoding', 'self-consistency decoding'}),
    frozenset({'test-time adaptation', 'test-time training', 'entropy minimization at test time'}),
    frozenset({'low-rank adaptation', 'lora', 'parameter-efficient fine-tuning', 'peft'}),
    frozenset({'adversarial training', 'minimax robust optimization', 'pgd training'}),
)
_ALT_QUERY_FAMILIES = frozenset({
    'alternate_vocabulary', 'alternate-vocabulary', 'mechanism', 'closure',
    'historical-terms', 'historical_terms', 'adversarial', 'citation_trail',
    'cross_setting_analogy', 'synonym_history', 'adjacent_field', 'kill_search',
})
_CODE_SOLVED_STATUSES = frozenset({'solved', 'implemented', 'shipped'})
_POS_OUTCOME_RE = re.compile(
    r'\b(?:outperforms?|improves?|gains?|increases?|reduces?\s+(?:error|loss|latency|ece)|calibrated|succeeds?)\b',
    re.I,
)
_NEG_OUTCOME_RE = re.compile(
    r'\b(?:degrades?|fails?|drops?|underperforms?|hurts?|no\s+(?:gain|improvement)|miscalibrated|collapses?|broken)\b',
    re.I,
)
_ASSUMPTION_TEXT_RE = re.compile(
    r'\b(?:assumes?|requires?|relies\s+on)\s+(?:that\s+)?([^.;\n]{6,120})',
    re.I,
)
_SCALING_WRAPPER_RE = re.compile(
    r'\b(?:prompt[- ]?(?:wrapper|hack|template)|few[- ]shot\s+prompt|heuristics?\s+for\s+current|'
    r'thin\s+wrapper|band[- ]?aid|small\s+context\s+patch|token[- ]count\s+trick)\b',
    re.I,
)
_DECISION_CHANGING_RE = re.compile(
    r'\b(?:decision[- ]changing|deployment|safety|clinical|falsif|architecture\s+change|'
    r'policy|selection|replaces?|invalidates?|failure\s+mode|outage|hallucination)\b',
    re.I,
)
_IDEA_DIMS = (
    'evidence_coverage',
    'novelty',
    'importance',
    'answerability',
    'feasibility',
    'falsifiability',
)
_EVAL_SUBTYPE_CUES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ('shortcut_exploitation', re.compile(r'\b(?:shortcut|spurious|clever\s+hans|lexical\s+overlap|annotation\s+artifact)\b', re.I)),
    ('dataset_bias_or_contamination', re.compile(r'\b(?:contamination|data\s+leakage|train[- ]test\s+overlap|dataset\s+bias|memorization)\b', re.I)),
    ('metric_saturation', re.compile(r'\b(?:saturation|saturated|ceiling\s+effect|above\s+99%|near[- ]100%)\b', re.I)),
    ('construct_validity_mismatch', re.compile(r'\b(?:construct\s+validity|proxy\s+metric|misaligned\s+metric|leaderboard\s+vs\s+deployment)\b', re.I)),
)


def _reject_nonfinite(token: str) -> Any:
    raise ValueError(f'Non-finite JSON constant not allowed: {token}')


def _coerce_num(val: Any, field_name: str, *, non_negative: bool = False) -> float | None:
    if val is None or val == '':
        return None
    if isinstance(val, bool):
        raise ValueError(f'{field_name} must be numeric, got bool')
    if isinstance(val, (int, float)):
        num = float(val)
        if not math.isfinite(num):
            raise ValueError(f'{field_name} must be finite, got {val!r}')
        if non_negative and num < 0:
            raise ValueError(f'{field_name} must be non-negative, got {val!r}')
        return num
    raise ValueError(f'{field_name} must be numeric, got {type(val).__name__}')


def _parse_iso_date(val: str | None) -> datetime | None:
    if not val or not isinstance(val, str):
        return None
    s = val.strip()[:10]
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', s):
        return None
    try:
        return datetime.strptime(s, '%Y-%m-%d').replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _coerce_int_year(val: Any, field_name: str = 'year') -> int | None:
    if val is None or val == '':
        return None
    if isinstance(val, bool):
        raise ValueError(f'{field_name} must be an integer year, got bool')
    if isinstance(val, int):
        return val
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        if re.fullmatch(r'-?\d+', s):
            return int(s)
    raise ValueError(f'Invalid {field_name}: {val!r}')


def _coerce_date_str(val: Any, field_name: str = 'cutoff_date') -> str | None:
    if val is None or val == '':
        return None
    if not isinstance(val, str):
        raise ValueError(f'{field_name} must be a date string, got {type(val).__name__}')
    s = val.strip()
    return s or None


def _auto_artifact_path(prefix: str) -> Path:
    art_dir = Path(tempfile.gettempdir()) / 'research_scientist_artifacts'
    art_dir.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(prefix=f'{prefix}_', suffix='.json', dir=str(art_dir))
    os.close(fd)
    return Path(raw_path)


def _norm_token(tok: str) -> str:
    t = tok.casefold()
    if len(t) > 4 and t.endswith('ies'):
        return t[:-3] + 'y'
    if len(t) > 4 and t.endswith('s') and not t.endswith('ss'):
        return t[:-1]
    return t


def _tokens(text: str) -> set[str]:
    out = set()
    for raw in re.findall(r'[a-z0-9]{2,}', text.casefold()):
        if raw in _STOPWORDS:
            continue
        norm = _norm_token(raw)
        if norm not in _STOPWORDS:
            out.add(norm)
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _as_list(val: Any) -> list[Any]:
    if isinstance(val, list):
        return val
    if isinstance(val, str) and val.strip():
        return [val.strip()]
    return []


def _load_corpus(path: Path | None) -> tuple[dict[str, dict[str, Any]], str | None]:
    if path is None:
        return {}, None
    raw = json.loads(path.read_text(encoding='utf-8'), parse_constant=_reject_nonfinite)
    cutoff = _coerce_date_str(raw.get('cutoff_date'), 'corpus.cutoff_date') if isinstance(raw, dict) else None
    items = raw.get('papers', []) if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError('corpus JSON must be a list or {"papers": [...]}')
    corpus: dict[str, dict[str, Any]] = {}
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        pid = str(item.get('id') or item.get('paper_id') or item.get('source_id') or f'DOC-{idx + 1}')
        pub_raw = item.get('published_date') if item.get('published_date') is not None else item.get('date')
        pub_date = _coerce_date_str(pub_raw, f'corpus[{pid}].published_date') if pub_raw is not None else None
        year = _coerce_int_year(item.get('year'), f'corpus[{pid}].year')
        if year is None and pub_date and len(pub_date) >= 4 and pub_date[:4].isdigit():
            year = int(pub_date[:4])
        corpus[pid] = {
            'id': pid,
            'source_id': str(item.get('source_id') or ''),
            'dedup_key': str(item.get('dedup_key') or ''),
            'source': str(item.get('source') or ''),
            'family': str(item.get('family') or ''),
            'year': year,
            'published_date': pub_date,
            'title': str(item.get('title') or ''),
            'abstract': item.get('abstract'),
            'text': str(item.get('text') or item.get('full_text_excerpt') or ''),
            'access': str(item.get('access') or ''),
            'retraction_status': str(item.get('retraction_status') or 'clean'),
            'doi': str(item.get('doi') or ''),
            'arxiv_id': str(item.get('arxiv_id') or ''),
            'openalex_id': str(item.get('openalex_id') or ''),
            'preprint_only': bool(item.get('preprint_only')),
            'assumptions': _as_list(item.get('assumptions')),
            'limitations': _as_list(item.get('limitations') or item.get('limitation')),
            'observations': _as_list(item.get('observations') or item.get('findings') or item.get('outcomes')),
            'methods': _as_list(item.get('methods') or item.get('method')),
            'settings': _as_list(item.get('settings') or item.get('setting')),
            'metrics': _as_list(item.get('metrics') or item.get('metric')),
            'regimes': _as_list(item.get('regimes') or item.get('regime')),
            'mechanism_aliases': _as_list(item.get('mechanism_aliases')),
            'alternate_vocabularies': _as_list(item.get('alternate_vocabularies')),
            'bottleneck': str(item.get('bottleneck') or ''),
            'tradeoff': str(item.get('tradeoff') or ''),
            'generation': item.get('generation'),
            'parent_ids': _as_list(item.get('parent_ids')),
        }
    return corpus, cutoff


def _load_digests(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    raw = json.loads(path.read_text(encoding='utf-8'), parse_constant=_reject_nonfinite)
    if not isinstance(raw, dict):
        raise ValueError('digests JSON must be an object')
    entries = raw.get('digests') if isinstance(raw.get('digests'), dict) else raw
    out: dict[str, dict[str, Any]] = {}
    for pid, val in entries.items():
        if not isinstance(val, dict):
            continue
        access = str(val.get('access') or val.get('read_status') or '').strip().lower()
        digest_text = str(val.get('digest') or val.get('quote') or '').strip()
        out[str(pid)] = {'source_id': str(pid), 'access': access, 'digest': digest_text}
    return out


def _load_candidates(path: Path | None) -> tuple[list[dict[str, Any]], str | None]:
    if path is None:
        return [], None
    raw = json.loads(path.read_text(encoding='utf-8'), parse_constant=_reject_nonfinite)
    if isinstance(raw, dict):
        items = raw.get('candidates', [])
        cutoff = _coerce_date_str(raw.get('cutoff_date'), 'candidates.cutoff_date')
    elif isinstance(raw, list):
        items = raw
        cutoff = None
    else:
        raise ValueError('candidates JSON must be a list or {"candidates": [...]}')
    return [c for c in items if isinstance(c, dict)], cutoff


def _load_candidates_context(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    raw = json.loads(path.read_text(encoding='utf-8'), parse_constant=_reject_nonfinite)
    if not isinstance(raw, dict):
        return {}
    ctx: dict[str, Any] = {}
    for key in ('target_venue_tier', 'user_resources', 'author_profile', 'subfield_preset', 'failure_cases', 'code_prior_art', 'as_of_date'):
        if key in raw and raw[key] is not None:
            ctx[key] = raw[key]
    return ctx


def _load_json_payload(val_or_path: str | Path | None, list_key: str | None = None) -> Any:
    if val_or_path is None:
        return None
    if isinstance(val_or_path, Path):
        raw = json.loads(val_or_path.read_text(encoding='utf-8'), parse_constant=_reject_nonfinite)
    else:
        s = str(val_or_path).strip()
        if not s:
            return None
        if s.startswith('{') or s.startswith('['):
            raw = json.loads(s, parse_constant=_reject_nonfinite)
        else:
            p = Path(s)
            if not p.is_file():
                raise ValueError(f'JSON file not found: {s}')
            raw = json.loads(p.read_text(encoding='utf-8'), parse_constant=_reject_nonfinite)
    if list_key is not None:
        if isinstance(raw, dict):
            val = raw.get(list_key, [])
            if not isinstance(val, list):
                raise ValueError(f'{list_key} must be a list')
            return [x for x in val if isinstance(x, dict)]
        if isinstance(raw, list):
            return [x for x in raw if isinstance(x, dict)]
        raise ValueError(f'Expected list or {{"{list_key}": [...]}}')
    return raw


def _load_workspace(ws_dir: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, Any]], str | None, bool, str]:
    if not ws_dir.is_dir():
        raise ValueError(f'workspace directory not found: {ws_dir}')
    corpus_file = next(iter(sorted(ws_dir.glob('corpus*.json'))), None)
    digests_file = next(iter(sorted(ws_dir.glob('digests*.json'))), None)
    cands_file = next(iter(sorted(ws_dir.glob('candidates*.json'))), None)
    corpus, c_cut = _load_corpus(corpus_file)
    digests = _load_digests(digests_file)
    candidates, k_cut = _load_candidates(cands_file)
    cutoff = k_cut or c_cut

    ws_eng_failed = False
    ws_eng_detail = ''
    for plan_file in sorted(ws_dir.glob('plan*.json')):
        pdata = json.loads(plan_file.read_text(encoding='utf-8'), parse_constant=_reject_nonfinite)
        eng = pdata.get('engineering_checks') or {}
        if isinstance(eng, dict):
            bad = [k for k, v in eng.items() if isinstance(v, dict) and v.get('status') in ('failed', 'planned', 'unknown')]
            if bad:
                ws_eng_failed = True
                ws_eng_detail = f'{plan_file.name} unresolved engineering_checks: {", ".join(bad)}'
    if _eng_diag is not None:
        splits_file = next(iter(sorted(ws_dir.glob('splits*.csv'))), None)
        metrics_file = next(iter(sorted(ws_dir.glob('metrics*.json'))), None)
        diag = _eng_diag.diagnose(code_dir=ws_dir, splits_path=splits_file, metrics_path=metrics_file)
        if diag.get('verdict') == 'ENGINEERING_BUG_DETECTED':
            ws_eng_failed = True
            ws_eng_detail = '; '.join(f.get('detail', '') for f in diag.get('findings', [])[:3])

    if not candidates:
        for gap_file in sorted(ws_dir.glob('gap*.json')):
            gdata = json.loads(gap_file.read_text(encoding='utf-8'), parse_constant=_reject_nonfinite)
            for ev in gdata.get('evidence', []) or []:
                if isinstance(ev, dict) and ev.get('id') and ev.get('access') in ('full_text', 'selected_full_text'):
                    digests.setdefault(ev['id'], {'source_id': ev.get('source_id', ev['id']), 'access': ev['access'], 'digest': ev.get('claim', '')})
            for cand in gdata.get('candidates', []) or []:
                if isinstance(cand, dict):
                    c_copy = dict(cand)
                    c_copy.setdefault('cited_ids', cand.get('support_evidence_ids', []))
                    c_copy.setdefault('support_ids', cand.get('support_evidence_ids', []))
                    candidates.append(c_copy)
    return corpus, digests, candidates, cutoff, ws_eng_failed, ws_eng_detail


def _load_workspace_context(ws_dir: Path) -> dict[str, Any]:
    ctx: dict[str, Any] = {}
    if not ws_dir.is_dir():
        return ctx
    cands_file = next(iter(sorted(ws_dir.glob('candidates*.json'))), None)
    if cands_file is not None:
        ctx.update(_load_candidates_context(cands_file))
    for pattern, key, list_key in (
        ('storm*.json', 'storm_report', None),
        ('campaign*.json', 'campaign', None),
        ('citation_graph*.json', 'citation_graph', None),
        ('failure_cases*.json', 'failure_cases', 'failure_cases'),
        ('code_prior_art*.json', 'code_prior_art', 'code_prior_art'),
        ('user_resources*.json', 'user_resources', None),
        ('author_profile*.json', 'author_profile', None),
    ):
        found = next(iter(sorted(ws_dir.glob(pattern))), None)
        if found is not None and key not in ctx:
            ctx[key] = _load_json_payload(found, list_key=list_key)
    for plan_file in sorted(ws_dir.glob('plan*.json')):
        pdata = json.loads(plan_file.read_text(encoding='utf-8'), parse_constant=_reject_nonfinite)
        if isinstance(pdata, dict):
            for k in ('target_venue_tier', 'subfield_preset', 'user_resources', 'author_profile'):
                if k in pdata and pdata[k] is not None and k not in ctx:
                    ctx[k] = pdata[k]
    return ctx


def _reject(cid: str, code: str, reason: str, evidence_ids: list[str] | None = None) -> dict[str, Any]:
    return {
        'id': cid,
        'candidate_id': cid,
        'reason_code': code,
        'code': code,
        'drop_code': code,
        'reasons': [code],
        'reason': reason,
        'evidence_ids': evidence_ids or [],
    }


def _is_after_cutoff(paper: dict[str, Any], cutoff_date: str | None, cutoff_year: int | None) -> bool:
    pdate = _coerce_date_str(paper.get('published_date'), f"corpus[{paper.get('id', '?')}].published_date")
    cdate = _coerce_date_str(cutoff_date, 'cutoff_date')
    pyear = _coerce_int_year(paper.get('year'), f"corpus[{paper.get('id', '?')}].year")
    cyear = _coerce_int_year(cutoff_year, 'cutoff_year')
    if cdate and pdate:
        return pdate > cdate
    if cyear is not None and pyear is not None:
        return pyear > cyear
    if cdate and len(cdate) >= 4 and cdate[:4].isdigit() and pyear is not None:
        return pyear > int(cdate[:4])
    return False


def _expand_alias_phrases(cand: dict[str, Any], campaign: dict[str, Any] | None = None) -> tuple[list[str], list[set[str]]]:
    claim = str(cand.get('claim') or '')
    claim_low = claim.casefold()
    phrases: list[str] = []
    seen: set[str] = set()

    def _add_phrase(p: str) -> None:
        ps = str(p or '').strip()
        pl = ps.casefold()
        if ps and pl not in seen:
            seen.add(pl)
            phrases.append(ps)

    for key in ('mechanism_aliases', 'alternate_vocabularies', 'synonyms'):
        for item in _as_list(cand.get(key)):
            _add_phrase(str(item))

    # Activate built-in synonym groups when claim or declared aliases match a phrase in that group
    declared_blob = ' '.join([claim_low] + [p.casefold() for p in phrases])
    for group in _MECHANISM_SYNONYM_GROUPS:
        if any(re.search(rf'\b{re.escape(g)}\b', declared_blob) for g in group):
            for g in group:
                _add_phrase(g)

    # Also incorporate alternate_vocabulary / closure query strings from campaign if relevant to candidate
    if isinstance(campaign, dict):
        c_toks = _tokens(claim)
        alias_tok_union = set().union(*(_tokens(p) for p in phrases)) if phrases else set()
        for qrun in (campaign.get('query_runs') or campaign.get('queries') or []):
            if not isinstance(qrun, dict):
                continue
            fam = str(qrun.get('family') or '').strip().lower()
            if fam in {'alternate_vocabulary', 'alternate-vocabulary', 'closure', 'mechanism'}:
                q_str = str(qrun.get('query') or '').strip()
                q_toks = _tokens(q_str)
                if q_str and (len(q_toks & (c_toks | alias_tok_union)) >= 2):
                    _add_phrase(q_str)

    alias_token_sets = [_tokens(p) for p in phrases if _tokens(p)]
    return phrases, alias_token_sets


def _doc_matches_claim_or_aliases(
    claim_toks: set[str],
    alias_phrases: list[str],
    alias_token_sets: list[set[str]],
    title: str,
    doc_blob: str,
    is_kill_family: bool = False,
) -> bool:
    title_toks = _tokens(title)
    doc_toks = _tokens(doc_blob)
    if not doc_toks:
        return False
    if claim_toks:
        claim_recall = len(claim_toks & doc_toks) / len(claim_toks)
        title_recall = len(claim_toks & title_toks) / len(claim_toks)
        shared_count = len(claim_toks & doc_toks)
        if title_recall >= 0.70 or (claim_recall >= 0.50 and shared_count >= 3) or (is_kill_family and claim_recall >= 0.45 and shared_count >= 3):
            return True
    doc_low = doc_blob.casefold()
    for phrase in alias_phrases:
        words = phrase.split()
        if len(words) >= 2 and re.search(rf'\b{re.escape(phrase.casefold())}\b', doc_low):
            return True
    for a_toks in alias_token_sets:
        if len(a_toks) >= 2:
            overlap = len(a_toks & doc_toks)
            if a_toks.issubset(doc_toks) or (overlap / len(a_toks) >= 0.75 and overlap >= 2):
                return True
        elif len(a_toks) == 1:
            tok = next(iter(a_toks))
            if tok in title_toks and (not claim_toks or len(claim_toks & doc_toks) >= 2):
                return True
    return False


_DOI_PREFIXES = ('doi:', 'http://doi.org/', 'https://doi.org/', 'http://dx.doi.org/', 'https://dx.doi.org/')
_ARXIV_PREFIXES = ('arxiv:', 'http://arxiv.org/', 'https://arxiv.org/')
_OPENALEX_PREFIXES = (
    'openalex:',
    'http://openalex.org/',
    'https://openalex.org/',
    'http://api.openalex.org/works/',
    'https://api.openalex.org/works/',
)
_BARE_DOI_RE = re.compile(r'^10\.\d{4,9}/\S+$', re.I)
_BARE_ARXIV_RE = re.compile(r'^(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z-]+)?/\d{7})(?:v\d+)?$', re.I)
_OPENALEX_WID_RE = re.compile(r'^[wW]\d+$')
_REF_ID_KEYS = ('id', 'source_id', 'dedup_key', 'doi', 'arxiv_id', 'openalex_id')


def _norm_doi(val: str) -> str:
    s = re.sub(r'^doi:', '', str(val or '').strip(), flags=re.I).strip()
    s = re.sub(r'^https?://(?:dx\.)?doi\.org/', '', s, flags=re.I)
    return re.sub(r'^doi:', '', s, flags=re.I).strip()


def _norm_arxiv(val: str) -> str:
    s = re.sub(r'^arxiv:', '', str(val or '').strip(), flags=re.I).strip()
    s = re.sub(r'^https?://arxiv\.org/(?:abs|pdf)/', '', s, flags=re.I)
    s = re.sub(r'^arxiv:', '', s, flags=re.I).strip()
    s = re.sub(r'\.pdf$', '', s, flags=re.I)
    s = re.sub(r'v\d+$', '', s, flags=re.I)
    return s.strip()


def _norm_openalex(val: str) -> str:
    s = re.sub(r'^openalex:', '', str(val or '').strip(), flags=re.I).strip()
    s = re.sub(r'^https?://(?:api\.)?openalex\.org/(?:works/)?', '', s, flags=re.I)
    return s.strip().strip('/')


def _ref_variants(val: Any, key: str = '') -> list[str]:
    s = str(val or '').strip()
    if not s:
        return []
    out: list[str] = [s, s.casefold()]
    low = s.casefold()
    if key == 'doi' or low.startswith(_DOI_PREFIXES) or _BARE_DOI_RE.fullmatch(s):
        nd = _norm_doi(s)
        if nd:
            out.extend((nd, nd.casefold(), f'doi:{nd}', f'doi:{nd}'.casefold()))
            if nd.casefold().startswith('10.48550/arxiv.'):
                na = _norm_arxiv(nd[len('10.48550/arxiv.'):])
                if na:
                    out.extend((na, na.casefold(), f'arxiv:{na}', f'arxiv:{na}'.casefold()))
    if key == 'arxiv_id' or low.startswith(_ARXIV_PREFIXES) or _BARE_ARXIV_RE.fullmatch(s):
        na = _norm_arxiv(s)
        if na:
            out.extend((na, na.casefold(), f'arxiv:{na}', f'arxiv:{na}'.casefold()))
    if key == 'openalex_id' or low.startswith(_OPENALEX_PREFIXES) or _OPENALEX_WID_RE.fullmatch(s):
        wid = _norm_openalex(s)
        if _OPENALEX_WID_RE.fullmatch(wid):
            wid_up = wid.upper()
            wid_low = wid.casefold()
            oa_url = f'https://openalex.org/{wid_up}'
            out.extend((wid, wid_up, wid_low, f'openalex:{wid_low}', oa_url, oa_url.casefold()))
    return list(dict.fromkeys(x for x in out if x))


def _record_in_candidate_refs(rec: dict[str, Any], candidate_ids: set[str]) -> bool:
    norm_refs = {str(x).strip().casefold() for x in candidate_ids if str(x).strip()}
    if not norm_refs:
        return False
    for key in _REF_ID_KEYS:
        val = str(rec.get(key) or '').strip()
        if not val:
            continue
        for variant in _ref_variants(val, key=key):
            if variant in candidate_ids or variant.casefold() in norm_refs:
                return True
    return False


def _kill_search_matches(
    claim: str,
    candidate_ids: set[str],
    corpus: dict[str, dict[str, Any]],
    eval_date: str | None,
    eval_year: int | None,
    *,
    cand: dict[str, Any] | None = None,
    campaign: dict[str, Any] | None = None,
    citation_graph: dict[str, Any] | None = None,
    code_prior_art: list[dict[str, Any]] | None = None,
) -> list[str]:
    claim_toks = _tokens(claim)
    cand_obj = cand or {'claim': claim}
    alias_phrases, alias_token_sets = _expand_alias_phrases(cand_obj, campaign=campaign)
    if not claim_toks and not alias_token_sets and not cand_obj.get('code_prior_art') and not cand_obj.get('code_prior_art_ids'):
        return []

    known_refs: set[str] = set()

    def _add_known_ref(val: Any, key: str = '') -> None:
        known_refs.update(_ref_variants(val, key=key))

    for cref in candidate_ids:
        _add_known_ref(cref)

    for pid, paper in corpus.items():
        if not isinstance(paper, dict):
            continue
        pid_s = str(pid).strip()
        if pid_s in known_refs or pid_s.casefold() in known_refs or _record_in_candidate_refs(paper, known_refs):
            _add_known_ref(pid)
            for k in _REF_ID_KEYS:
                _add_known_ref(paper.get(k), key=k)

    seed_wids: set[str] = set()
    if isinstance(citation_graph, dict):
        for sr in (citation_graph.get('seeds_resolved') or []):
            if not isinstance(sr, dict):
                continue
            probe: list[str] = []
            for k in (*_REF_ID_KEYS, 'requested'):
                probe.extend(_ref_variants(sr.get(k), key=k))
            if any(v in known_refs for v in probe):
                known_refs.update(probe)
                oa = str(sr.get('openalex_id') or '').strip()
                if oa:
                    seed_wids.add(oa)

    hits: list[str] = []
    seen_hits: set[str] = set()

    def _add_hit(hid: str) -> None:
        if hid and hid not in seen_hits:
            seen_hits.add(hid)
            hits.append(hid)

    # 1. Corpus check (lexicon + mechanism aliases / alternate vocabularies)
    for pid, paper in corpus.items():
        if pid in known_refs or pid.casefold() in known_refs or _record_in_candidate_refs(paper, known_refs):
            continue
        if eval_date or eval_year is not None:
            if _is_after_cutoff(paper, eval_date, eval_year):
                continue
        doc_blob = ' '.join(x for x in (
            paper['title'],
            paper.get('abstract') or '',
            paper.get('text') or '',
            ' '.join(str(a) for a in (paper.get('mechanism_aliases') or [])),
            ' '.join(str(a) for a in (paper.get('alternate_vocabularies') or [])),
        ) if x)
        is_kill_family = paper.get('family') in _ALT_QUERY_FAMILIES
        if _doc_matches_claim_or_aliases(claim_toks, alias_phrases, alias_token_sets, paper['title'], doc_blob, is_kill_family=is_kill_family):
            _add_hit(pid)

    # 2. Read-only search_campaign.py cross-check (combined_results OR source_records fallback)
    if isinstance(campaign, dict):
        qrun_map: dict[str, dict[str, Any]] = {}
        alt_qids: set[str] = set()
        for qr in (campaign.get('query_runs') or campaign.get('queries') or []):
            if not isinstance(qr, dict):
                continue
            qid = str(qr.get('id') or '').strip()
            fam = str(qr.get('family') or '').strip().lower()
            qtext = str(qr.get('query') or '')
            exec_queries = [qtext]
            if isinstance(qr.get('sources'), dict):
                for sinfo in qr['sources'].values():
                    if isinstance(sinfo, dict) and sinfo.get('executed_query'):
                        exec_queries.append(str(sinfo['executed_query']))
            if qid:
                qrun_map[qid] = {'family': fam, 'tokens': _tokens(' '.join(exec_queries))}
                if fam in _ALT_QUERY_FAMILIES:
                    alt_qids.add(qid)

        records = campaign.get('combined_results') or campaign.get('source_records') or []
        if isinstance(records, list):
            for rec in records:
                if not isinstance(rec, dict) or _record_in_candidate_refs(rec, known_refs):
                    continue
                if eval_date or eval_year is not None:
                    if _is_after_cutoff(rec, eval_date, eval_year):
                        continue
                title = str(rec.get('title') or '')
                abstract = str(rec.get('abstract') or '')
                blob = ' '.join(x for x in (title, abstract) if x)
                disc_by = {str(q) for q in (rec.get('discovered_by') or [])}
                from_alt = bool(disc_by & alt_qids)
                matched = _doc_matches_claim_or_aliases(
                    claim_toks, alias_phrases, alias_token_sets, title, blob, is_kill_family=from_alt
                )
                if not matched and from_alt:
                    # Provenance-linked alternate-vocab match: query bridges candidate to discovered paper
                    doc_toks = _tokens(blob)
                    all_alias_toks = set().union(*alias_token_sets) if alias_token_sets else set()
                    for qid in (disc_by & alt_qids):
                        q_toks = qrun_map.get(qid, {}).get('tokens', set())
                        if q_toks and (len(q_toks & (claim_toks | all_alias_toks)) >= 2) and len(q_toks & doc_toks) >= 2:
                            matched = True
                            break
                if matched:
                    rec_id = str(rec.get('dedup_key') or rec.get('source_id') or rec.get('doi') or rec.get('arxiv_id') or title[:48])
                    _add_hit(rec_id)

    # 3. Read-only citation_graph.py cross-check (clusters + co-citation + title/aliases)
    if isinstance(citation_graph, dict):
        seed_clusters: set[str] = set()
        for cl in (citation_graph.get('clusters') or []):
            if isinstance(cl, dict):
                mids = {str(m) for m in (cl.get('member_ids') or [])}
                if mids & (seed_wids | known_refs):
                    cid_str = str(cl.get('cluster_id') or '')
                    if cid_str:
                        seed_clusters.add(cid_str)
        for nb in (citation_graph.get('results') or []):
            if not isinstance(nb, dict) or _record_in_candidate_refs(nb, known_refs):
                continue
            if eval_date or eval_year is not None:
                if _is_after_cutoff(nb, eval_date, eval_year):
                    continue
            title = str(nb.get('title') or '')
            title_toks = _tokens(title)
            matched = _doc_matches_claim_or_aliases(claim_toks, alias_phrases, alias_token_sets, title, title, is_kill_family=True)
            if not matched:
                overlap_cnt = nb.get('seed_overlap_count')
                has_struct_link = (
                    (isinstance(overlap_cnt, int) and not isinstance(overlap_cnt, bool) and overlap_cnt >= 2)
                    or (str(nb.get('cluster_id') or '') in seed_clusters)
                    or any(isinstance(e, dict) and e.get('relation') == 'cite' and str(e.get('seed_id') or '') in (seed_wids | known_refs) for e in (nb.get('edges') or []))
                )
                if has_struct_link and title_toks:
                    for a_toks in alias_token_sets:
                        shared = len(a_toks & title_toks)
                        if shared >= 2 and (shared / len(a_toks)) >= 0.50:
                            matched = True
                            break
                    if not matched and claim_toks:
                        shared_c = len(claim_toks & title_toks)
                        if shared_c >= 2 and (shared_c / len(claim_toks)) >= 0.40:
                            matched = True
            if matched:
                _add_hit(str(nb.get('openalex_id') or nb.get('doi') or title[:48]))

    # 4. F30.4 code_prior_art screening (candidate-level + linked code_prior_art_ids + global)
    for entry in (cand_obj.get('code_prior_art') or []):
        if not isinstance(entry, dict):
            continue
        rel = str(entry.get('relation') or '').strip().lower()
        st = str(entry.get('status') or '').strip().lower()
        if rel == 'direct_equivalent' or st in _CODE_SOLVED_STATUSES:
            _add_hit(str(entry.get('id') or entry.get('repo_or_url') or entry.get('url') or entry.get('title') or 'code_prior_art'))

    cpa_by_id: dict[str, dict[str, Any]] = {}
    for entry in (code_prior_art or []):
        if isinstance(entry, dict):
            eid = str(entry.get('id') or '').strip()
            if eid:
                cpa_by_id[eid] = entry

    for cpa_id in _as_list(cand_obj.get('code_prior_art_ids')):
        cid_str = str(cpa_id or '').strip()
        entry = cpa_by_id.get(cid_str)
        if isinstance(entry, dict):
            rel = str(entry.get('relation') or '').strip().lower()
            st = str(entry.get('status') or '').strip().lower()
            if rel == 'direct_equivalent' or st in _CODE_SOLVED_STATUSES:
                _add_hit(str(entry.get('id') or entry.get('repo_or_url') or entry.get('url') or cid_str))

    for entry in (code_prior_art or []):
        if not isinstance(entry, dict):
            continue
        rel = str(entry.get('relation') or '').strip().lower()
        st = str(entry.get('status') or '').strip().lower()
        if rel != 'direct_equivalent' and st not in _CODE_SOLVED_STATUSES:
            continue
        title = str(entry.get('title') or entry.get('name') or '')
        blob = ' '.join(str(x) for x in (title, entry.get('summary') or '', entry.get('description') or '', ' '.join(str(a) for a in _as_list(entry.get('mechanism_aliases')))) if x)
        if _doc_matches_claim_or_aliases(claim_toks, alias_phrases, alias_token_sets, title, blob, is_kill_family=True):
            _add_hit(str(entry.get('id') or entry.get('repo_or_url') or entry.get('url') or title[:48] or 'code_prior_art'))

    return hits


def _ablation_dict_nonpositive_or_empty(ablation: dict[str, Any], cand: dict[str, Any], require_numeric: bool = False) -> str | None:
    mg = ablation.get('marginal_gain')
    b_val = ablation.get('baseline_score')
    p_val = ablation.get('proposed_score')
    if isinstance(mg, bool) or isinstance(b_val, bool) or isinstance(p_val, bool):
        return 'Ablation evidence contains invalid boolean value for marginal_gain, baseline_score, or proposed_score.'
    if (isinstance(b_val, (int, float)) and not math.isfinite(b_val)) or (isinstance(p_val, (int, float)) and not math.isfinite(p_val)):
        return 'Ablation evidence contains non-finite baseline_score or proposed_score.'
    if isinstance(mg, (int, float)):
        if not math.isfinite(mg) or mg <= 0:
            return 'Ablation evidence shows non-positive marginal_gain over simplest baseline.'
        return None
    if isinstance(b_val, (int, float)) and isinstance(p_val, (int, float)):
        direction = str(ablation.get('metric_direction') or cand.get('metric_direction') or 'higher').lower()
        delta = (b_val - p_val) if direction == 'lower' else (p_val - b_val)
        if not math.isfinite(delta) or delta <= 0:
            return 'Ablation evidence fails to outperform simplest baseline.'
        return None
    if require_numeric:
        return 'Multi-module ablation dict lacks numeric marginal_gain or baseline/proposed scores.'
    return None


def _check_parsimony_candidate(cand: dict[str, Any]) -> tuple[str, str] | None:
    claim_blob = ' '.join(str(x or '') for x in (cand.get('claim'), cand.get('rationale')))
    audit = cand.get('parsimony_audit') if isinstance(cand.get('parsimony_audit'), dict) else {}
    delta = cand.get('measured_delta')
    if isinstance(delta, bool) or (isinstance(delta, (int, float)) and not math.isfinite(delta)):
        return 'DROP_PROBLEM_INFLATION', 'measured_delta must be a finite numeric value (not bool or non-finite float).'
    tiny_delta = isinstance(delta, (int, float)) and abs(delta) <= 0.005
    if audit.get('problem_inflation_detected') is True:
        return 'DROP_PROBLEM_INFLATION', 'Parsimony audit flagged problem inflation.'
    if _INFLATION_RE.search(claim_blob) and (tiny_delta or _NOISE_HINT_RE.search(claim_blob) or not re.search(r'\b95%\s*ci\b', claim_blob, re.I)):
        return 'DROP_PROBLEM_INFLATION', 'Dramatized problem framing around minor variance or unverified setup.'

    raw_modules = cand.get('proposed_modules')
    if raw_modules is None or (isinstance(raw_modules, (list, dict)) and not raw_modules):
        alt_modules = cand.get('components')
        if alt_modules is not None:
            raw_modules = alt_modules
    if isinstance(raw_modules, dict):
        modules = list(raw_modules.keys())
    elif isinstance(raw_modules, list):
        modules = raw_modules
    elif raw_modules is not None:
        return 'DROP_OVERCOMPLICATED', 'proposed_modules/components must be a structured list or dict.'
    else:
        modules = []
    if audit.get('simpler_equal_or_better') is True or audit.get('complexity_justified') is False or audit.get('passed') is False:
        return 'DROP_OVERCOMPLICATED', 'Parsimony audit rejected added complexity over simplest alternative.'
    direction = str(audit.get('metric_direction') or cand.get('metric_direction') or 'higher').lower()
    ablation = cand.get('ablation_evidence') if cand.get('ablation_evidence') is not None else audit.get('ablation_over_simplest_baseline')
    is_multi = len(modules) >= 3
    for ab_val in (ablation, audit.get('ablation_over_simplest_baseline')):
        if isinstance(ab_val, dict):
            ab_err = _ablation_dict_nonpositive_or_empty(ab_val, cand, require_numeric=is_multi)
            if ab_err:
                return 'DROP_OVERCOMPLICATED', ab_err
        elif isinstance(ab_val, str) and ab_val.strip():
            has_ev, nonpos = _analyze_string_ablation(ab_val, direction)
            if nonpos or (is_multi and not has_ev):
                return 'DROP_OVERCOMPLICATED', 'Ablation evidence fails to show positive numeric gain over simplest baseline.'
    if is_multi:
        alt = str(cand.get('simplest_alternative') or audit.get('simplest_alternative') or '').strip()
        alt_norm = re.sub(r'\W+', ' ', alt.casefold()).strip()
        if (not alt or alt_norm in _BOILERPLATE_ALT or len(alt.split()) < 4
                or (_DISMISSIVE_ALT_RE.search(alt) and not re.search(r'\d', alt))):
            return 'DROP_OVERCOMPLICATED', 'Multi-module proposal lacks concrete simplest_alternative baseline.'
        if not ablation:
            return 'DROP_OVERCOMPLICATED', 'Multi-module proposal lacks numeric ablation evidence over simplest baseline.'
        if isinstance(ablation, str):
            has_ev, nonpos = _analyze_string_ablation(ablation, direction)
            if not has_ev or nonpos:
                return 'DROP_OVERCOMPLICATED', 'Multi-module proposal lacks positive numeric ablation gain over simplest baseline.'
        elif not isinstance(ablation, dict):
            return 'DROP_OVERCOMPLICATED', 'Multi-module proposal lacks numeric ablation evidence over simplest baseline.'
    return None


def _sgha_5role_passed(cand: dict[str, Any]) -> tuple[bool, str, str]:
    if cand.get('sgha_critics_passed') is False:
        return False, 'DROP_ARTIFICIAL_SCOPE', 'Candidate failed SGHA 5-role critic verification.'
    critics = cand.get('sgha_critics')
    if isinstance(critics, dict):
        if critics.get('artificial_scope') is True:
            return False, 'DROP_ARTIFICIAL_SCOPE', 'SGHA critic flagged artificial scope restriction.'
        score = critics.get('survival_score')
        conf = critics.get('critic_confidence')
        verdict = str(critics.get('verdict') or '').upper()
        if (verdict in {'REJECT', 'DROP'}
                or isinstance(score, bool)
                or (isinstance(score, (int, float))
                    and (not math.isfinite(score) or score < 0.60))
                or isinstance(conf, bool)
                or (isinstance(conf, (int, float))
                    and (not math.isfinite(conf) or conf < 0.50))):
            return False, 'DROP_SGHA_CRITIC_REJECT', 'SGHA 5-role critic panel rejected candidate below survival threshold.'
    return True, '', ''


def _storm_field(storm_report: dict[str, Any] | None, key: str, default: Any = None) -> Any:
    if not isinstance(storm_report, dict):
        return default
    if key in storm_report and storm_report[key] is not None:
        return storm_report[key]
    state = storm_report.get('storm_state')
    if isinstance(state, dict) and key in state and state[key] is not None:
        return state[key]
    return default


def _mine_structured_matrices(
    corpus: dict[str, dict[str, Any]],
    storm_report: dict[str, Any] | None = None,
    failure_cases: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    # 1. Contradiction Matrix
    contradictions: list[dict[str, Any]] = []
    seen_cm: set[tuple[str, str, str]] = set()
    for row in (_storm_field(storm_report, 'contradiction_matrix', []) or []):
        if isinstance(row, dict):
            pa = str(row.get('paper_a') or '')
            pb = str(row.get('paper_b') or '')
            met = str(row.get('metric_or_construct') or row.get('construct') or '')
            key = (min(pa, pb), max(pa, pb), met)
            if key not in seen_cm:
                seen_cm.add(key)
                contradictions.append(row)

    claims: list[dict[str, Any]] = []
    for pid, paper in sorted(corpus.items()):
        obs_list = list(paper.get('observations') or [])
        blob_lines: list[tuple[str, str, str, str]] = []
        for ob in obs_list:
            if isinstance(ob, dict):
                txt = str(ob.get('finding') or ob.get('outcome') or ob.get('text') or ob.get('claim') or '').strip()
                if txt:
                    blob_lines.append((
                        txt,
                        str(ob.get('polarity') or ''),
                        str(ob.get('regime') or ob.get('setting') or ''),
                        str(ob.get('metric') or ''),
                    ))
            elif isinstance(ob, str) and ob.strip():
                blob_lines.append((ob.strip(), '', '', ''))
        if not blob_lines:
            txt_blob = ' '.join(str(x) for x in (paper.get('title') or '', paper.get('abstract') or '', paper.get('text') or '') if x)
            for sent in re.split(r'(?<=[.!?;])\s+|\n+', txt_blob):
                s = sent.strip()
                if len(s) >= 10:
                    blob_lines.append((s, '', '', ''))
        for sent, exp_pol, exp_reg, exp_met in blob_lines:
            pol_low = exp_pol.strip().casefold()
            if pol_low in {'positive', 'pos', 'improves', 'gain'}:
                pol = 'positive'
            elif pol_low in {'negative', 'neg', 'degrades', 'fails'}:
                pol = 'negative'
            elif _NEG_OUTCOME_RE.search(sent):
                pol = 'negative'
            elif _POS_OUTCOME_RE.search(sent):
                pol = 'positive'
            else:
                continue
            toks = _tokens(sent + ' ' + str(paper.get('title') or ''))
            reg = exp_reg or (str(paper['regimes'][0]) if paper.get('regimes') else 'unspecified')
            met = exp_met or (str(paper['metrics'][0]) if paper.get('metrics') else 'general_metric')
            claims.append({'pid': pid, 'pol': pol, 'reg': reg, 'met': met, 'toks': toks, 'sent': sent[:180]})

    for i in range(len(claims)):
        a = claims[i]
        for j in range(i + 1, len(claims)):
            b = claims[j]
            if a['pid'] == b['pid'] or a['pol'] == b['pol']:
                continue
            first, second = (a, b) if a['pid'] < b['pid'] else (b, a)
            shared = sorted(first['toks'] & second['toks'])
            same_met = first['met'] == second['met'] and first['met'] != 'general_metric'
            if len(shared) >= 2 or (same_met and len(shared) >= 1):
                met = first['met'] if first['met'] == second['met'] else f"{first['met']}/{second['met']}"
                key = (first['pid'], second['pid'], met)
                if key not in seen_cm:
                    seen_cm.add(key)
                    contradictions.append({
                        'cell_id': f'CM-{len(contradictions) + 1}',
                        'paper_a': first['pid'],
                        'paper_b': second['pid'],
                        'metric_or_construct': met,
                        'construct_tokens': shared[:8],
                        'regime_a': first['reg'],
                        'regime_b': second['reg'],
                        'polarity_a': first['pol'],
                        'polarity_b': second['pol'],
                        'conflict_type': 'cross_regime_conflict' if first['reg'] != second['reg'] else 'same_regime_conflict',
                        'summary': f"{first['pid']} ({first['pol']} on {first['reg']}) vs {second['pid']} ({second['pol']} on {second['reg']})",
                    })

    # 2. Coverage-Hole Matrix
    storm_cov = _storm_field(storm_report, 'coverage_hole_matrix', None)
    if isinstance(storm_cov, dict) and isinstance(storm_cov.get('uncovered_cells'), list):
        cov_matrix = storm_cov
    else:
        obs_cells: dict[tuple[str, str, str, str], list[str]] = {}
        methods_set: list[str] = []
        settings_set: list[str] = []
        metrics_set: list[str] = []
        regimes_set: list[str] = []
        for pid, paper in sorted(corpus.items()):
            ms = [str(x).casefold() for x in (paper.get('methods') or ['baseline'])]
            ss = [str(x).casefold() for x in (paper.get('settings') or ['benchmark'])]
            ks = [str(x).casefold() for x in (paper.get('metrics') or ['accuracy'])]
            rs = [str(x).casefold() for x in (paper.get('regimes') or ['in_domain'])]
            for lst, src in ((methods_set, ms), (settings_set, ss), (metrics_set, ks), (regimes_set, rs)):
                for item in src:
                    if item not in lst:
                        lst.append(item)
            for m in ms:
                for s in ss:
                    for k in ks:
                        for r in rs:
                            obs_cells.setdefault((m, s, k, r), []).append(pid)
        uncovered_cells: list[dict[str, Any]] = []
        genuine_cnt = 0
        reskin_cnt = 0
        obs_ms = sorted({(m, s) for (m, s, _, _) in obs_cells})
        obs_mkr = {(m, k, r) for (m, _, k, r) in obs_cells}
        stress_regs = {'ood_shift', 'ood', 'adversarial', 'low_resource', 'long_context', 'noisy', 'quantized', 'deployment_constrained'}
        rel_mets = {'calibration', 'ece', 'latency', 'p99', 'vram', 'memory', 'robustness', 'construct_validity'}
        for m, s in obs_ms[:5]:
            for k in metrics_set[:5]:
                for r in regimes_set[:5]:
                    if (m, s, k, r) in obs_cells:
                        continue
                    if (m, k, r) in obs_mkr and r in {'in_domain', 'unspecified'} and k not in rel_mets:
                        htype = 'trivial_reskin_risk'
                        reskin_cnt += 1
                    elif r in stress_regs or k in rel_mets:
                        htype = 'genuine_coverage_hole'
                        genuine_cnt += 1
                    else:
                        htype = 'trivial_reskin_risk'
                        reskin_cnt += 1
                    if len(uncovered_cells) < 25:
                        uncovered_cells.append({
                            'method': m, 'setting': s, 'metric': k, 'regime': r,
                            'hole_type': htype, 'status': 'lead',
                        })
        cov_matrix = {
            'axes': {'methods': methods_set, 'settings': settings_set, 'metrics': metrics_set, 'regimes': regimes_set},
            'observed_cells': [{'method': m, 'setting': s, 'metric': k, 'regime': r, 'source_ids': pids} for (m, s, k, r), pids in sorted(obs_cells.items())],
            'uncovered_cells': uncovered_cells,
            'genuine_holes_count': genuine_cnt,
            'trivial_reskin_count': reskin_cnt,
        }

    # 3. Assumption Violations
    assumptions_out: list[dict[str, Any]] = []
    seen_av: set[tuple[str, str]] = set()
    for av in (_storm_field(storm_report, 'assumption_violations', []) or []):
        if isinstance(av, dict):
            sid = str(av.get('source_id') or av.get('paper_id') or '')
            assump = str(av.get('assumption') or '')
            if (sid, assump) not in seen_av:
                seen_av.add((sid, assump))
                assumptions_out.append(av)
    viol_cue_re = re.compile(r'\b(?:ood|shift|non[- ]stationary|long[- ]tail|low[- ]resource|noisy|violat\w*|breaks?\s+under)\b', re.I)
    for pid, paper in sorted(corpus.items()):
        blob = ' '.join(str(x) for x in (paper.get('title') or '', paper.get('abstract') or '', paper.get('text') or '') if x)
        extracted = [str(a) for a in (paper.get('assumptions') or [])]
        for m in _ASSUMPTION_TEXT_RE.finditer(blob):
            frag = m.group(1).strip()
            if frag not in extracted:
                extracted.append(frag)
        has_viol_in_corpus = any(
            viol_cue_re.search(' '.join(str(x) for x in (p.get('text') or '', ' '.join(str(r) for r in (p.get('regimes') or [])))))
            for p in corpus.values()
        )
        if failure_cases:
            has_viol_in_corpus = True
        for assump in extracted:
            if has_viol_in_corpus and (pid, assump) not in seen_av:
                seen_av.add((pid, assump))
                assumptions_out.append({
                    'paper_id': pid,
                    'source_id': pid,
                    'assumption': assump[:140],
                    'violating_regime': 'target_deployment_or_ood',
                    'source': 'explicit' if assump in (paper.get('assumptions') or []) else 'text_cue',
                    'status': 'lead',
                })

    return {
        'contradiction_matrix': contradictions[:30],
        'coverage_hole_matrix': cov_matrix,
        'assumption_violations': assumptions_out[:25],
        'summary_counts': {
            'contradictions': len(contradictions),
            'genuine_coverage_holes': int(cov_matrix.get('genuine_holes_count') or 0),
            'trivial_reskin_risks': int(cov_matrix.get('trivial_reskin_count') or 0),
            'assumption_violations': len(assumptions_out),
        },
    }


def _process_failure_cases(
    failure_cases: list[dict[str, Any]] | None,
    corpus: dict[str, dict[str, Any]],
    *,
    campaign: dict[str, Any] | None = None,
    citation_graph: dict[str, Any] | None = None,
    code_prior_art: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    if not failure_cases:
        return {}, []
    by_id: dict[str, dict[str, Any]] = {}
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for idx, fc in enumerate(failure_cases):
        if not isinstance(fc, dict):
            continue
        fc_id = str(fc.get('id') or fc.get('case_id') or f'FC-{idx + 1}')
        by_id[fc_id] = fc
        err_type = str(fc.get('error_type') or fc.get('failure_mode') or fc.get('symptom') or 'unspecified_error').strip()
        reg_slice = str(fc.get('slice') or fc.get('regime') or 'unspecified_slice').strip()
        groups.setdefault((err_type, reg_slice), []).append(fc)

    patterns: list[dict[str, Any]] = []
    for (err_type, reg_slice), items in sorted(groups.items()):
        desc_blob = f'{err_type} {reg_slice} ' + ' '.join(str(it.get('description') or it.get('notes') or '') for it in items)
        prior_hits = _kill_search_matches(
            desc_blob, set(), corpus, None, None,
            cand={'claim': desc_blob}, campaign=campaign, citation_graph=citation_graph, code_prior_art=code_prior_art,
        )
        baselines = sorted({str(it.get('baseline') or it.get('model') or '').strip() for it in items if str(it.get('baseline') or it.get('model') or '').strip()})
        eng_checked_all = all(
            it.get('engineering_checked') is True
            or str(it.get('engineering_status') or '').strip().lower() in {'implementation_checked', 'protocol_matched', 'clean', 'passed'}
            for it in items
        )
        patterns.append({
            'pattern_id': f'FP-{len(patterns) + 1}',
            'error_type': err_type,
            'slice_or_regime': reg_slice,
            'count': len(items),
            'affected_baselines': baselines,
            'engineering_checked': eng_checked_all,
            'prior_art_hits': prior_hits,
        })
    return by_id, patterns


def _build_trajectory_tree(
    corpus: dict[str, dict[str, Any]],
    cutoff_date: str | None = None,
    cutoff_year: int | None = None,
    cand: dict[str, Any] | None = None,
    storm_report: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    eff_cutoff_year = _coerce_int_year(cutoff_year, 'cutoff_year')
    if eff_cutoff_year is None and cutoff_date and len(cutoff_date) >= 4 and cutoff_date[:4].isdigit():
        eff_cutoff_year = int(cutoff_date[:4])

    if isinstance(cand, dict) and isinstance(cand.get('trajectory_tree'), dict):
        tree = cand['trajectory_tree']
        gens = tree.get('generations')
        if not isinstance(gens, list) or not gens:
            errors.append('trajectory_tree_missing_generations')
            return dict(tree), errors
        norm_gens: list[dict[str, Any]] = []
        prev_year: int | None = None
        for g in gens:
            if not isinstance(g, dict):
                errors.append('trajectory_tree_invalid_generation')
                break
            g_copy = dict(g)
            yr = _coerce_int_year(g.get('year'), 'trajectory_tree.year')
            if yr is not None:
                g_copy['year'] = yr
                if eff_cutoff_year is not None and yr > eff_cutoff_year:
                    errors.append(f'trajectory_tree_temporal_leak:year_{yr}')
                    break
                if prev_year is not None and yr < prev_year:
                    errors.append('trajectory_tree_non_monotonic_years')
                    break
                prev_year = yr
            elif 'year' in g_copy:
                g_copy['year'] = None
            leaked_pid = next(
                (pid for pid in _as_list(g.get('paper_ids'))
                 if pid in corpus and (cutoff_date or cutoff_year is not None) and _is_after_cutoff(corpus[pid], cutoff_date, cutoff_year)),
                None,
            )
            if leaked_pid is not None:
                errors.append(f'trajectory_tree_temporal_leak:{leaked_pid}')
                break
            norm_gens.append(g_copy)
        out_tree = dict(tree)
        out_tree['generations'] = norm_gens
        return out_tree, errors

    storm_traj = _storm_field(storm_report, 'research_trajectory', None)
    if isinstance(storm_traj, dict) and isinstance(storm_traj.get('generations'), list) and storm_traj['generations']:
        # Filter out any post-cutoff papers and generations, then rebuild all summary/edge fields strictly from clean_gens
        clean_gens: list[dict[str, Any]] = []
        for g in storm_traj['generations']:
            if not isinstance(g, dict):
                continue
            orig_pids = [str(pid) for pid in (g.get('paper_ids') or []) if str(pid).strip()]
            raw_yr = g.get('year')
            coerced_range: list[int] = []
            if isinstance(g.get('year_range'), list):
                for ry in g['year_range']:
                    cy = _coerce_int_year(ry, 'storm_trajectory.year_range')
                    if cy is not None:
                        coerced_range.append(cy)
            yr_val = _coerce_int_year(raw_yr, 'storm_trajectory.year')
            if yr_val is None and coerced_range:
                yr_val = coerced_range[0]

            pids: list[str] = []
            for pid in orig_pids:
                if pid in corpus:
                    if (cutoff_date or cutoff_year is not None) and _is_after_cutoff(corpus[pid], cutoff_date, cutoff_year):
                        continue
                    pids.append(pid)
                else:
                    if eff_cutoff_year is None or yr_val is None or yr_val <= eff_cutoff_year:
                        pids.append(pid)

            if orig_pids and not pids:
                continue
            if not orig_pids and eff_cutoff_year is not None and yr_val is not None and yr_val > eff_cutoff_year:
                continue

            corpus_pids = [pid for pid in pids if pid in corpus]
            if corpus_pids:
                gen_years = [int(corpus[pid]['year']) for pid in corpus_pids if corpus[pid].get('year') is not None]
                if eff_cutoff_year is not None:
                    gen_years = [y for y in gen_years if y <= eff_cutoff_year]
                yr_val = min(gen_years) if gen_years else yr_val
                yr_range = [min(gen_years), max(gen_years)] if gen_years else ([yr_val, yr_val] if yr_val is not None else [])
                gen_titles = [str(corpus[pid].get('title') or '') for pid in corpus_pids if str(corpus[pid].get('title') or '').strip()][:4]
                if len(pids) < len(orig_pids) or not g.get('observed_bottlenecks'):
                    obs_bn = [
                        str(corpus[pid].get('bottleneck') or lim).strip()[:160]
                        for pid in corpus_pids
                        for lim in ([corpus[pid].get('bottleneck')] if corpus[pid].get('bottleneck') else (corpus[pid].get('limitations') or []))
                        if str(lim or '').strip()
                    ][:4]
                else:
                    obs_bn = [str(x) for x in (g.get('observed_bottlenecks') or []) if str(x).strip()][:4]
                if len(pids) < len(orig_pids) or not g.get('observed_tradeoffs'):
                    obs_tr = [
                        str(corpus[pid].get('tradeoff') or '').strip()[:160]
                        for pid in corpus_pids
                        if str(corpus[pid].get('tradeoff') or '').strip()
                    ][:4]
                else:
                    obs_tr = [str(x) for x in (g.get('observed_tradeoffs') or []) if str(x).strip()][:4]
                primary_bn = obs_bn[0] if obs_bn else (str(g.get('primary_bottleneck') or '') if len(pids) == len(orig_pids) else 'No explicit bottleneck cue extracted.')
                primary_tr = obs_tr[0] if obs_tr else (str(g.get('primary_tradeoff') or '') if len(pids) == len(orig_pids) else '')
            else:
                if eff_cutoff_year is not None and yr_val is not None and yr_val > eff_cutoff_year:
                    continue
                if eff_cutoff_year is not None:
                    coerced_range = [y for y in coerced_range if y <= eff_cutoff_year]
                yr_range = [min(coerced_range), max(coerced_range)] if coerced_range else ([yr_val, yr_val] if yr_val is not None else [])
                gen_titles = [str(t) for t in (g.get('titles') or []) if str(t).strip()][:4]
                obs_bn = [str(x) for x in (g.get('observed_bottlenecks') or []) if str(x).strip()][:4]
                obs_tr = [str(x) for x in (g.get('observed_tradeoffs') or []) if str(x).strip()][:4]
                primary_bn = str(g.get('primary_bottleneck') or (obs_bn[0] if obs_bn else '')).strip()
                primary_tr = str(g.get('primary_tradeoff') or (obs_tr[0] if obs_tr else '')).strip()

            if eff_cutoff_year is not None and yr_val is not None and yr_val > eff_cutoff_year:
                continue

            method_p = str(g.get('method_or_paradigm') or ', '.join(gen_titles or pids) or g.get('generation') or '').strip()
            bn_t = str(
                (g.get('bottleneck_or_tradeoff') if len(pids) == len(orig_pids) else '')
                or primary_bn
                or primary_tr
                or 'Bottleneck not explicitly specified'
            ).strip()
            clean_gens.append({
                'generation': str(g.get('generation') or f'Gen{len(clean_gens) + 1}'),
                'year': yr_val,
                'year_range': yr_range,
                'paper_ids': pids,
                'titles': gen_titles,
                'observed_bottlenecks': obs_bn,
                'observed_tradeoffs': obs_tr,
                'primary_bottleneck': primary_bn or 'No explicit bottleneck cue extracted.',
                'primary_tradeoff': primary_tr,
                'method_or_paradigm': method_p,
                'bottleneck_or_tradeoff': bn_t,
            })
        if clean_gens:
            edges_out: list[dict[str, Any]] = []
            for i in range(len(clean_gens) - 1):
                cur_g = clean_gens[i]
                nxt_g = clean_gens[i + 1]
                edges_out.append({
                    'from_gen': cur_g['generation'],
                    'to_gen': nxt_g['generation'],
                    'bottleneck_addressed': cur_g['primary_bottleneck'],
                    'new_tradeoff': nxt_g['primary_tradeoff'] or nxt_g['primary_bottleneck'],
                })
            latest = clean_gens[-1]
            open_limits: list[dict[str, Any]] = []
            for item in (latest['observed_tradeoffs'] or latest['observed_bottlenecks'] or [latest['primary_bottleneck']]):
                if item:
                    open_limits.append({
                        'generation': latest['generation'],
                        'limit': item,
                        'status': 'lead',
                    })
            parts: list[str] = []
            for i, gen in enumerate(clean_gens):
                yr_r = gen['year_range']
                if len(yr_r) >= 2:
                    yr_lbl = str(yr_r[0]) if yr_r[0] == yr_r[1] else f"{yr_r[0]}-{yr_r[1]}"
                elif gen['year'] is not None:
                    yr_lbl = str(gen['year'])
                else:
                    yr_lbl = 'undated'
                parts.append(f"{gen['generation']} ({yr_lbl})")
                if i < len(edges_out):
                    parts.append(f"bottleneck: {edges_out[i]['bottleneck_addressed'][:60]}")
                elif gen['primary_tradeoff']:
                    parts.append(f"tradeoff: {gen['primary_tradeoff'][:60]}")
            if open_limits:
                parts.append(f"open_root_limit: {open_limits[0]['limit'][:70]}")
            open_root_str = str(cand['claim']) if (isinstance(cand, dict) and cand.get('claim')) else (open_limits[0]['limit'] if open_limits else latest['bottleneck_or_tradeoff'])
            missing_ids = [
                mid for mid in (storm_traj.get('missing_year_source_ids') or [])
                if mid not in corpus or not ((cutoff_date or cutoff_year is not None) and _is_after_cutoff(corpus[mid], cutoff_date, cutoff_year))
            ]
            return {
                'generations': clean_gens,
                'edges': edges_out,
                'open_root_limits': open_limits,
                'open_root_limit': open_root_str,
                'missing_year_source_ids': missing_ids,
                'evolution_summary': ' -> '.join(parts),
            }, errors

    dated: list[dict[str, Any]] = []
    missing_year_ids: list[str] = []
    for pid, p in sorted(corpus.items()):
        if (cutoff_date or cutoff_year is not None) and _is_after_cutoff(p, cutoff_date, cutoff_year):
            continue
        yr = p.get('year')
        if yr is None:
            missing_year_ids.append(pid)
        else:
            dated.append(p)
    dated.sort(key=lambda p: (int(p['year']), str(p.get('generation') or ''), p['id']))
    generations: list[dict[str, Any]] = []
    if dated:
        years = sorted({int(p['year']) for p in dated})
        yr_to_gen = {y: f'Gen{i + 1}' for i, y in enumerate(years)}
        grouped: dict[str, list[dict[str, Any]]] = {}
        for p in dated:
            g_lbl = str(p.get('generation') or yr_to_gen[int(p['year'])])
            grouped.setdefault(g_lbl, []).append(p)
        ordered = sorted(grouped.keys(), key=lambda g: (min(int(x['year']) for x in grouped[g]), g))
        for g_lbl in ordered:
            grp = grouped[g_lbl]
            lims = [str(l) for x in grp for l in (x.get('limitations') or []) if str(l).strip()]
            bns = [str(x.get('bottleneck') or x.get('tradeoff') or '').strip() for x in grp if str(x.get('bottleneck') or x.get('tradeoff') or '').strip()]
            generations.append({
                'generation': g_lbl,
                'year': min(int(x['year']) for x in grp),
                'paper_ids': [x['id'] for x in grp],
                'method_or_paradigm': str(grp[0].get('title') or grp[0]['id'])[:120],
                'bottleneck_or_tradeoff': (bns[0] if bns else (lims[0] if lims else 'Bottleneck not explicitly specified'))[:160],
            })
    edges: list[dict[str, Any]] = []
    for i in range(len(generations) - 1):
        edges.append({
            'from_gen': generations[i]['generation'],
            'to_gen': generations[i + 1]['generation'],
            'bottleneck_addressed': generations[i]['bottleneck_or_tradeoff'],
            'new_tradeoff': generations[i + 1]['bottleneck_or_tradeoff'],
        })
    open_root = str(cand.get('claim') or '') if isinstance(cand, dict) else ''
    summary_parts = [f"{g['generation']} ({g['year']}): {g['bottleneck_or_tradeoff'][:50]}" for g in generations]
    if open_root:
        summary_parts.append(f"open_root_limit: {open_root[:80]}")
    tree_out = {
        'generations': generations,
        'edges': edges,
        'open_root_limit': open_root or (generations[-1]['bottleneck_or_tradeoff'] if generations else ''),
        'missing_year_source_ids': missing_year_ids,
        'summary': ' -> '.join(summary_parts) if summary_parts else 'No dated corpus entries; chronological trajectory unavailable.',
    }
    return tree_out, errors


def _normalize_target_venue_tier(raw_tier: str | None) -> tuple[str | None, str | None]:
    if raw_tier is None or not str(raw_tier).strip():
        return None, None
    norm = re.sub(r'[^a-z0-9]+', '_', str(raw_tier).strip().casefold()).strip('_')
    mapped = _TARGET_TIER_TO_MIN_CEILING.get(norm)
    if mapped is None:
        raise ValueError(f'Unknown target_venue_tier: {raw_tier!r}')
    return norm, mapped


def _normalize_isomorphic_leads(raw_leads: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_leads, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw_leads:
        if not isinstance(item, dict):
            continue
        out.append({
            **item,
            'evidence_level': 'lead',
            'requires_primary_verification': True,
            'supporting_evidence': [],
            'status': 'lead',
        })
    return out


def _evaluate_candidate_triage(
    cand: dict[str, Any],
    cid: str,
    all_refs: list[str],
    corpus: dict[str, dict[str, Any]],
    digests: dict[str, dict[str, Any]],
    *,
    storm_report: dict[str, Any] | None,
    structured_mining: dict[str, Any],
    failure_patterns: list[dict[str, Any]],
    code_prior_art: list[dict[str, Any]] | None,
    target_venue_tier: str | None,
    user_resources: dict[str, Any] | None,
    author_profile: dict[str, Any] | None,
    subfield_preset: str | None,
    as_of_date: str | None,
    cutoff_date: str | None,
    cutoff_year: int | None,
    strict_triage: bool,
    require_idea_portfolio: bool,
    require_pre_mortem: bool,
    require_code_prior_art: bool,
) -> tuple[dict[str, Any], dict[str, Any], tuple[str, str] | None, list[str]]:
    cand_warnings: list[str] = []
    claim = str(cand.get('claim') or '').strip()
    rationale = str(cand.get('rationale') or '').strip()
    consequence = str(cand.get('consequence') or '').strip()
    claim_blob = f'{claim} {rationale} {consequence}'

    # F32.1 Root-cause barrier & why_now_enabler
    barrier = cand.get('root_cause_barrier')
    if barrier is not None:
        barrier = str(barrier).strip()
        if barrier not in ROOT_CAUSE_BARRIERS:
            raise ValueError(f'candidates[{cid}].root_cause_barrier invalid: {barrier!r}')
    else:
        if re.search(r'\b(?:bound|theorem|convergence|identifiability|rank|capacity|minimax)\b', claim_blob, re.I):
            barrier = 'theoretical_limit'
        elif re.search(r'\b(?:vram|latency|compute|memory|throughput|hardware|quantiz|batch)\b', claim_blob, re.I):
            barrier = 'compute_infra_barrier'
        elif re.search(r'\b(?:label|supervision|annotation|dataset|scarce|unlabeled|corpus)\b', claim_blob, re.I):
            barrier = 'data_supervision_gap'
        else:
            barrier = 'measurement_gap'

    why_now = str(cand.get('why_now_enabler') or '').strip()
    why_now_norm = re.sub(r'\W+', ' ', why_now.casefold()).strip()
    why_now_weak = (not why_now) or (why_now_norm in _BOILERPLATE_ALT) or (len(why_now.split()) < 4)
    if why_now_weak:
        cand_warnings.append('missing_or_weak_why_now_enabler')

    # F32.2 Evaluation-validity gap lens
    ev_gap_raw = cand.get('evaluation_validity_gap')
    ev_subtype: str | None = None
    ev_cues: list[str] = []
    if isinstance(ev_gap_raw, dict):
        if ev_gap_raw.get('subtype') is not None:
            ev_subtype = str(ev_gap_raw['subtype']).strip()
            if ev_subtype not in EVAL_VALIDITY_SUBTYPES:
                raise ValueError(f'candidates[{cid}].evaluation_validity_gap.subtype invalid: {ev_subtype!r}')
        ev_cues = [str(c) for c in _as_list(ev_gap_raw.get('cues'))]
    for sub_name, pat in _EVAL_SUBTYPE_CUES:
        if pat.search(claim_blob):
            if ev_subtype is None:
                ev_subtype = sub_name
            if sub_name not in ev_cues:
                ev_cues.append(sub_name)
    if cand.get('type') == 'evaluation_validity_gap' and ev_subtype is None:
        ev_subtype = 'construct_validity_mismatch'
    eval_validity_obj = {'subtype': ev_subtype, 'cues': ev_cues}

    # F32.3 Isomorphic transfer leads (strictly tagged 'lead')
    iso_raw = cand.get('isomorphic_transfer_leads')
    if iso_raw is None:
        iso_raw = _storm_field(storm_report, 'isomorphic_transfer_leads', [])
    iso_leads = _normalize_isomorphic_leads(iso_raw)

    # F32.4 So What & 12-24m Durability
    delta_val = cand.get('measured_delta')
    if isinstance(delta_val, bool) or (isinstance(delta_val, (int, float)) and not math.isfinite(delta_val)):
        return cand, {}, ('DROP_PROBLEM_INFLATION', 'measured_delta must be a finite numeric value (not bool or non-finite float).'), cand_warnings
    so_what = cand.get('so_what_decision_impact')
    if so_what is not None:
        so_what = str(so_what).strip()
        if so_what not in SO_WHAT_IMPACTS:
            raise ValueError(f'candidates[{cid}].so_what_decision_impact invalid: {so_what!r}')
    else:
        tiny_delta = isinstance(delta_val, (int, float)) and abs(delta_val) <= 0.01
        if tiny_delta or re.search(r'\b(?:minor|marginal|0\.\d%|slight\s+gain)\b', claim_blob, re.I):
            so_what = 'marginal_gain'
        elif consequence and _DECISION_CHANGING_RE.search(claim_blob):
            so_what = 'decision_changing'
        else:
            so_what = 'decision_changing' if consequence else 'marginal_gain'

    durability = cand.get('durability_12_24m')
    if durability is not None:
        durability = str(durability).strip()
        if durability not in DURABILITY_LEVELS:
            raise ValueError(f'candidates[{cid}].durability_12_24m invalid: {durability!r}')
    else:
        if _SCALING_WRAPPER_RE.search(claim_blob):
            durability = 'high_scaling_erasure_risk'
        else:
            durability = 'durable_structural_limit'
    if durability == 'high_scaling_erasure_risk':
        cand_warnings.append('high_scaling_erasure_risk')

    # F27.3 Scoop & Scaling Obsolescence Risk (Zero-fabrication on missing dates!)
    if as_of_date is not None:
        if not isinstance(as_of_date, str):
            raise ValueError(f'as_of_date must be an ISO date string (YYYY-MM-DD), got {type(as_of_date).__name__}')
        if as_of_date.strip():
            ref_date_str = as_of_date.strip()
            ref_dt = _parse_iso_date(ref_date_str)
            if ref_dt is None:
                raise ValueError(f'Invalid as_of_date (expected YYYY-MM-DD): {as_of_date!r}')
        else:
            ref_date_str = cutoff_date or datetime.now(timezone.utc).date().isoformat()
            ref_dt = _parse_iso_date(ref_date_str) or datetime.now(timezone.utc)
    else:
        ref_date_str = cutoff_date or datetime.now(timezone.utc).date().isoformat()
        ref_dt = _parse_iso_date(ref_date_str) or datetime.now(timezone.utc)

    claim_toks = _tokens(claim)
    alias_toks = set().union(*(_tokens(str(a)) for a in _as_list(cand.get('mechanism_aliases')) + _as_list(cand.get('alternate_vocabularies'))))
    match_toks = claim_toks | alias_toks

    dated_papers = 0
    undated_relevant = 0
    count_3m = 0
    count_12m = 0
    for pid, p in corpus.items():
        if pid in all_refs or p.get('family') == 'kill_search':
            continue
        ptoks = _tokens(' '.join(str(x) for x in (p.get('title') or '', p.get('abstract') or '', p.get('text') or '') if x))
        is_relevant = (not match_toks) or len(match_toks & ptoks) >= 2
        pdt = _parse_iso_date(p.get('published_date'))
        if pdt is None:
            if is_relevant:
                undated_relevant += 1
            continue
        dated_papers += 1
        delta_days = (ref_dt - pdt).days
        if delta_days < 0 or delta_days > 366:
            continue
        if is_relevant:
            count_12m += 1
            if delta_days <= 92:
                count_3m += 1

    unknown_disclosures: list[str] = []
    if dated_papers == 0:
        recent_3m: int | None = None
        recent_12m: int | None = None
        recency_known = False
        unknown_disclosures.append('preprint_recency_metadata_unavailable')
        cand_warnings.append('preprint_recency_metadata_unavailable')
        scoop_level = 'high_scaling_obsolescence_risk' if durability == 'high_scaling_erasure_risk' else 'unknown'
    elif undated_relevant > 0 and count_12m == 0:
        recent_3m = None
        recent_12m = None
        recency_known = False
        unknown_disclosures.append('preprint_recency_metadata_partial_or_unavailable')
        cand_warnings.append('preprint_recency_metadata_partial_or_unavailable')
        scoop_level = 'high_scaling_obsolescence_risk' if durability == 'high_scaling_erasure_risk' else 'unknown'
    else:
        recent_3m = count_3m
        recent_12m = count_12m
        recency_known = True
        if undated_relevant > 0:
            unknown_disclosures.append('preprint_recency_metadata_partial_or_unavailable')
            cand_warnings.append('preprint_recency_metadata_partial_or_unavailable')
        if durability == 'high_scaling_erasure_risk':
            scoop_level = 'high_scaling_obsolescence_risk'
        elif count_3m >= 3 or count_12m >= 6:
            scoop_level = 'high_scoop_risk'
            cand_warnings.append('high_scoop_risk')
        elif count_3m >= 1 or count_12m >= 2:
            scoop_level = 'moderate'
        else:
            scoop_level = 'low'

    scoop_obj = {
        'risk_level': scoop_level,
        'recent_preprints_3m': recent_3m,
        'recent_preprints_12m': recent_12m,
        'recent_preprint_count': recent_12m,
        'recency_metadata_available': recency_known,
        'as_of_date': ref_date_str,
        'unknown_disclosures': unknown_disclosures,
        'bitter_lesson_exposure': durability,
    }

    # F27.2 Gap Tier Ceiling & Early Target-Venue Warning
    reskinning_risk = bool(cand.get('reskinning_risk')) or (
        structured_mining.get('summary_counts', {}).get('genuine_coverage_holes', 0) == 0
        and structured_mining.get('summary_counts', {}).get('trivial_reskin_risks', 0) > 0
        and not consequence
    )
    declared_ceiling = cand.get('gap_tier_ceiling')
    if declared_ceiling is not None:
        declared_ceiling = str(declared_ceiling).strip()
        if declared_ceiling not in GAP_TIER_CEILINGS:
            raise ValueError(f'candidates[{cid}].gap_tier_ceiling invalid: {declared_ceiling!r}')
        ceiling = declared_ceiling
    else:
        if reskinning_risk and durability == 'high_scaling_erasure_risk':
            ceiling = 'low_impact_dead_end'
        elif durability == 'high_scaling_erasure_risk' or so_what == 'marginal_gain' or reskinning_risk:
            ceiling = 'workshop_incremental_only'
        elif not why_now_weak and so_what == 'decision_changing' and durability == 'durable_structural_limit' and scoop_level in {'low', 'moderate', 'unknown'}:
            ceiling = 'q1_top_tier_potential'
        else:
            ceiling = 'tier_a_findings_potential'

    # Cap overly optimistic declared ceiling when structural signals downgrade it
    if durability == 'high_scaling_erasure_risk' and _TIER_RANK[ceiling] < _TIER_RANK['workshop_incremental_only']:
        ceiling = 'workshop_incremental_only'
    elif so_what == 'marginal_gain' and _TIER_RANK[ceiling] < _TIER_RANK['workshop_incremental_only']:
        ceiling = 'workshop_incremental_only'

    effective_target = cand.get('target_venue_tier') or target_venue_tier
    norm_target, required_min_ceiling = _normalize_target_venue_tier(effective_target)
    below_target = False
    if required_min_ceiling is not None and _TIER_RANK[ceiling] > _TIER_RANK[required_min_ceiling]:
        below_target = True
        cand_warnings.append('gap_below_target_venue_tier')

    if strict_triage:
        if ceiling == 'low_impact_dead_end':
            return cand, {}, ('DROP_LOW_IMPACT_DEAD_END', f'Gap ceiling classified as {ceiling}.'), cand_warnings
        if below_target:
            return cand, {}, ('DROP_BELOW_TARGET_VENUE_TIER', f'Gap ceiling ({ceiling}) is below target venue tier ({norm_target}).'), cand_warnings

    # F27.4 Resource Feasibility Gate
    raw_req_res = cand.get('resource_requirements')
    if raw_req_res is not None and not isinstance(raw_req_res, dict):
        raise ValueError('resource_requirements must be a JSON object')
    req_res = raw_req_res if isinstance(raw_req_res, dict) else {}

    raw_avail_res = cand.get('user_resources')
    if raw_avail_res is not None and not isinstance(raw_avail_res, dict):
        raise ValueError('user_resources must be a JSON object')
    avail_res = raw_avail_res if isinstance(raw_avail_res, dict) else (user_resources if isinstance(user_resources, dict) else {})

    req_nums: dict[str, float | None] = {}
    avail_nums: dict[str, float | None] = {}
    for dim, req_key, avail_key in (
        ('gpu_count', 'gpu_count', 'gpu_count'),
        ('vram_gb', 'vram_gb', 'vram_gb'),
        ('total_vram_gb', 'total_vram_gb', 'total_vram_gb'),
        ('api_budget_usd', 'api_budget_usd', 'api_budget_usd'),
        ('timeline_days', 'timeline_days', 'timeline_days'),
        ('estimated_weeks', 'estimated_weeks', 'estimated_weeks'),
    ):
        req_nums[dim] = _coerce_num(req_res.get(req_key), f'resource_requirements.{req_key}', non_negative=True)
        avail_nums[dim] = _coerce_num(avail_res.get(avail_key), f'user_resources.{avail_key}', non_negative=True)

    blocking_constraints: list[str] = []
    if not req_res or not avail_res:
        res_status = 'unverified_missing_constraints'
        infeasible = False
    else:
        for dim in ('gpu_count', 'vram_gb', 'total_vram_gb', 'api_budget_usd', 'timeline_days', 'estimated_weeks'):
            rv = req_nums[dim]
            av = avail_nums[dim]
            if rv is not None and av is not None and rv > av:
                blocking_constraints.append(f'{dim}: requires {rv} > available {av}')
        req_ds = str(req_res.get('dataset_access') or '').strip().lower()
        avail_ds = str(avail_res.get('dataset_access') or '').strip().lower()
        req_prop = (req_res.get('requires_proprietary_data') is True) or (req_ds in {'restricted', 'proprietary', 'closed'})
        user_has_prop = (
            (avail_res.get('has_proprietary_data') is True)
            or (avail_ds in {'proprietary', 'restricted', 'all', 'full'})
        )
        if req_prop and (avail_res.get('has_proprietary_data') is False or not user_has_prop):
            req_desc = req_ds or 'proprietary'
            avail_desc = avail_ds or ('has_proprietary_data=False' if avail_res.get('has_proprietary_data') is False else 'unspecified')
            blocking_constraints.append(f'dataset_access: requires {req_desc}, user has {avail_desc}')

        infeasible = bool(blocking_constraints)
        res_status = 'infeasible_under_user_resources' if infeasible else 'feasible'
        if infeasible:
            cand_warnings.append('infeasible_under_user_resources')
            if strict_triage:
                return cand, {}, ('DROP_RESOURCE_INFEASIBLE', '; '.join(blocking_constraints)), cand_warnings

    res_obj = {
        'status': res_status,
        'infeasible_under_user_resources': infeasible,
        'blocking_constraints': blocking_constraints,
        'required': req_res,
        'available': avail_res,
    }

    # F30.3 Author-Advantage Socratic Scoping
    prof = cand.get('author_profile') if isinstance(cand.get('author_profile'), dict) else (author_profile if isinstance(author_profile, dict) else {})
    matched_adv: list[str] = []
    mismatch_warns: list[str] = []
    scoping_qs: list[str] = [
        'Does this gap exploit your comparative advantage (theory vs systems vs proprietary data) rather than competing head-on with frontier-lab compute?',
    ]
    if prof:
        strength = str(prof.get('strength_profile') or prof.get('strength') or '').strip().lower()
        if strength == 'math_theory':
            if barrier == 'theoretical_limit':
                matched_adv.append('math_theory aligns with theoretical_limit barrier')
            elif barrier == 'compute_infra_barrier':
                mismatch_warns.append('math_theory profile mismatched with compute_infra_barrier gap')
        elif strength == 'systems_engineering':
            if barrier == 'compute_infra_barrier':
                matched_adv.append('systems_engineering aligns with compute_infra_barrier')
            elif barrier == 'theoretical_limit':
                mismatch_warns.append('systems_engineering profile may face theory depth risk on theoretical_limit gap')
        elif strength in {'empirical_eval', 'data_curation'}:
            if barrier in {'measurement_gap', 'data_supervision_gap'}:
                matched_adv.append(f'{strength} aligns with {barrier}')
        if prof.get('proprietary_data_access') is True and barrier == 'data_supervision_gap':
            matched_adv.append('proprietary_data_access strengthens data_supervision_gap')
        if infeasible:
            mismatch_warns.append('gap exceeds author GPU/budget/timeline constraints')
        if mismatch_warns:
            cand_warnings.append('author_advantage_mismatch')
        alignment = 'strong' if (matched_adv and not mismatch_warns) else ('misaligned' if mismatch_warns and not matched_adv else 'partial')
    else:
        alignment = 'unverified'
    author_fit_obj = {
        'alignment': alignment,
        'profile': prof,
        'matched_advantages': matched_adv,
        'mismatch_warnings': mismatch_warns,
        'scoping_questions': scoping_qs,
    }

    # F30.1 Chronological Trajectory
    traj_tree, traj_errs = _build_trajectory_tree(corpus, cutoff_date=cutoff_date, cutoff_year=cutoff_year, cand=cand, storm_report=storm_report)
    if traj_errs:
        if any(e.startswith('trajectory_tree_temporal_leak:') for e in traj_errs):
            return cand, {}, ('DROP_TEMPORAL_LEAK', '; '.join(traj_errs)), cand_warnings
        if strict_triage:
            return cand, {}, ('DROP_INSUFFICIENT_COVERAGE', '; '.join(traj_errs)), cand_warnings
        cand_warnings.extend(traj_errs)

    # F30.4 Code prior art summary
    cand_cpa = cand.get('code_prior_art') if isinstance(cand.get('code_prior_art'), list) else []
    global_cpa = code_prior_art or []
    cpa_screened = cand.get('code_prior_art_screened')
    if cpa_screened is None:
        cpa_screened = bool(cand_cpa or global_cpa)
    if not cpa_screened:
        cand_warnings.append('code_prior_art_not_screened')
        if require_code_prior_art:
            return cand, {}, ('DROP_UNSCREENED_CODE_PRIOR_ART', 'Code-first / open-source prior-art screening not completed.'), cand_warnings

    cpa_by_id = {
        str(e.get('id') or '').strip(): e
        for e in global_cpa
        if isinstance(e, dict) and str(e.get('id') or '').strip()
    }
    linked_cpa = [
        cpa_by_id[str(x).strip()]
        for x in _as_list(cand.get('code_prior_art_ids'))
        if str(x).strip() in cpa_by_id
    ]
    claim_toks_cpa = _tokens(claim)
    alias_phrases_cpa, alias_token_sets_cpa = _expand_alias_phrases(cand, campaign=None)

    def _is_cpa_overlap(entry: dict[str, Any]) -> bool:
        rel = str(entry.get('relation') or '').strip().lower()
        st = str(entry.get('status') or '').strip().lower()
        return rel in {'direct_equivalent', 'partial_implementation'} or st in (_CODE_SOLVED_STATUSES | {'partial'})

    cpa_overlap_found = any(_is_cpa_overlap(e) for e in (cand_cpa + linked_cpa) if isinstance(e, dict))
    if not cpa_overlap_found:
        for e in global_cpa:
            if not isinstance(e, dict) or not _is_cpa_overlap(e):
                continue
            cpa_title = str(e.get('title') or e.get('name') or '')
            cpa_blob = ' '.join(str(x) for x in (
                cpa_title, e.get('summary') or '', e.get('description') or '',
                ' '.join(str(a) for a in _as_list(e.get('mechanism_aliases'))),
            ) if x)
            if not cpa_blob.strip() or _doc_matches_claim_or_aliases(claim_toks_cpa, alias_phrases_cpa, alias_token_sets_cpa, cpa_title, cpa_blob, is_kill_family=True):
                cpa_overlap_found = True
                break

    code_pa_obj = {
        'screened': bool(cpa_screened),
        'repos_checked': [str(e.get('repo_or_url') or e.get('url') or e.get('id') or '') for e in (cand_cpa + global_cpa) if isinstance(e, dict)],
        'overlap_found': cpa_overlap_found,
    }

    # F28 Idea Portfolio & Pre-Mortem Validation
    raw_portfolio = cand.get('idea_portfolio')
    portfolio_out: list[dict[str, Any]] = []
    if raw_portfolio is not None:
        if not isinstance(raw_portfolio, list):
            return cand, {}, ('DROP_TUNNEL_VISION_PORTFOLIO', 'idea_portfolio must be a list of 3-4 distinct ideas.'), cand_warnings
        distinct_ideas: list[set[str]] = []
        distinct_angles: set[str] = set()
        for idx_i, idea in enumerate(raw_portfolio):
            if not isinstance(idea, dict):
                return cand, {}, ('DROP_TUNNEL_VISION_PORTFOLIO', 'idea_portfolio items must be JSON objects.'), cand_warnings
            raw_angle = str(idea.get('angle') or '').strip()
            if raw_angle not in _CANONICAL_PORTFOLIO_ANGLE:
                return cand, {}, ('DROP_TUNNEL_VISION_PORTFOLIO', f'Invalid idea_portfolio angle: {raw_angle!r}'), cand_warnings
            canon_ang = _CANONICAL_PORTFOLIO_ANGLE[raw_angle]
            summary_parts = [
                str(idea.get(k) or '').strip()
                for k in ('title', 'mechanism_summary', 'summary')
                if isinstance(idea.get(k), str) and str(idea.get(k)).strip()
            ]
            if not summary_parts:
                return cand, {}, ('DROP_TUNNEL_VISION_PORTFOLIO', f'idea_portfolio[{idx_i}] missing title/summary.'), cand_warnings
            title_s = summary_parts[0]
            s_toks = _tokens(' '.join(dict.fromkeys(summary_parts)))
            is_redundant = bool(s_toks) and any(_jaccard(s_toks, prev) >= 0.80 for prev in distinct_ideas)
            if is_redundant:
                if 'idea_portfolio_redundant_ideas' not in cand_warnings:
                    cand_warnings.append('idea_portfolio_redundant_ideas')
            else:
                if s_toks:
                    distinct_ideas.append(s_toks)
                distinct_angles.add(canon_ang)

            # Enforce zero-fabrication ratings: null unless caller explicitly provides verified numeric ratings
            raw_ratings = idea.get('ratings') if isinstance(idea.get('ratings'), dict) else {}
            norm_ratings: dict[str, Any] = {}
            for dim in _IDEA_DIMS:
                rv = raw_ratings.get(dim)
                if rv is not None:
                    if isinstance(rv, bool) or not isinstance(rv, (int, float)) or not math.isfinite(rv):
                        raise ValueError(f'idea_portfolio[{idx_i}].ratings.{dim} must be finite numeric or null')
                    norm_ratings[dim] = rv
                else:
                    norm_ratings[dim] = None

            iid = str(idea.get('id') or idea.get('idea_id') or f'{cid}_{raw_angle}')
            goal_tags = _as_list(idea.get('goal_tags'))
            if not goal_tags:
                if _CANONICAL_PORTFOLIO_ANGLE[raw_angle] == 'minimal_fix':
                    goal_tags = ['safe_fast_publish']
                elif _CANONICAL_PORTFOLIO_ANGLE[raw_angle] == 'high_novelty_mechanism':
                    goal_tags = ['high_risk_q1_top_tier']
                elif _CANONICAL_PORTFOLIO_ANGLE[raw_angle] == 'low_gpu_fallback':
                    goal_tags = ['low_compute_constrained']
                else:
                    goal_tags = ['safe_fast_publish']

            portfolio_out.append({
                'id': iid,
                'idea_id': iid,
                'gap_id': cid,
                'angle': raw_angle,
                'canonical_angle': canon_ang,
                'goal_tags': goal_tags,
                'object_type': 'idea',
                'status': 'idea',
                'reading_basis': 'full_text',
                'closest_work': list(cand.get('closest_work_ids') or all_refs),
                'title': str(idea.get('title') or title_s[:100]),
                'summary': str(idea.get('summary') or title_s),
                'mechanism_summary': str(idea.get('mechanism_summary') or idea.get('summary') or title_s),
                'ratings': norm_ratings,
                'evidence_locators': idea.get('evidence_locators') if isinstance(idea.get('evidence_locators'), dict) else {},
            })

        if (require_idea_portfolio or cand.get('portfolio_mode') is True) and (len(distinct_ideas) < 3 or len(distinct_angles) < 3):
            return cand, {}, (
                'DROP_TUNNEL_VISION_PORTFOLIO',
                f'Portfolio mode requires 3-4 non-redundant ideas spanning >=3 distinct angles (got {len(distinct_ideas)} distinct ideas, {len(distinct_angles)} distinct angles).',
            ), cand_warnings
    elif require_idea_portfolio or cand.get('portfolio_mode') is True:
        return cand, {}, ('DROP_TUNNEL_VISION_PORTFOLIO', 'Missing required multi-angle idea_portfolio (3-4 distinct ideas).'), cand_warnings

    pre_mortem_raw = cand.get('pre_mortem')
    if pre_mortem_raw is not None:
        if not isinstance(pre_mortem_raw, dict):
            return cand, {}, ('DROP_INCOMPLETE_PRE_MORTEM', 'pre_mortem must be a JSON object.'), cand_warnings
        fms = pre_mortem_raw.get('top_failure_modes')
        kexp = pre_mortem_raw.get('killer_experiment')
        pivot = str(pre_mortem_raw.get('pivot_path') or '').strip()
        pm_errs: list[str] = []
        if not isinstance(fms, list) or len([f for f in fms if isinstance(f, str) and bool(f.strip())]) < 3:
            pm_errs.append('top_failure_modes requires >=3 non-empty failure hypotheses')
        if not isinstance(kexp, dict):
            pm_errs.append('killer_experiment must be an object')
        else:
            dur = _coerce_num(kexp.get('duration_days'), 'pre_mortem.killer_experiment.duration_days')
            if dur is None or dur <= 0 or dur > 2:
                pm_errs.append('killer_experiment.duration_days must be in (0, 2]')
            if not str(kexp.get('kill_threshold') or '').strip():
                pm_errs.append('killer_experiment.kill_threshold must be non-blank')
        if not pivot:
            pm_errs.append('pivot_path must be non-blank')
        if pm_errs:
            if require_pre_mortem or strict_triage:
                return cand, {}, ('DROP_INCOMPLETE_PRE_MORTEM', '; '.join(pm_errs)), cand_warnings
            cand_warnings.append('incomplete_pre_mortem')
    elif require_pre_mortem:
        return cand, {}, ('DROP_INCOMPLETE_PRE_MORTEM', 'Missing required pre_mortem (top_failure_modes, 1-2d killer_experiment, pivot_path).'), cand_warnings

    # F31 Subfield Preset Gap Vetting Hook
    eff_preset = cand.get('subfield_preset') or subfield_preset
    subfield_vetting: dict[str, Any] | None = None
    if eff_preset is not None:
        preset_key = str(eff_preset).strip().lower()
        if preset_key not in SUBFIELD_PRESETS:
            raise ValueError(f'Unknown subfield_preset: {eff_preset!r}')
        req_checks = list(SUBFIELD_PRESETS[preset_key])
        cand_checks = cand.get('subfield_checks') if isinstance(cand.get('subfield_checks'), dict) else {}
        eng_diag = cand.get('engineering_diagnostics') if isinstance(cand.get('engineering_diagnostics'), dict) else {}
        covered_checks: list[str] = []
        missing_checks: list[str] = []
        for chk in req_checks:
            if cand_checks.get(chk) is True or eng_diag.get(chk) is True or re.search(rf'\b{re.escape(chk.replace("_", " "))}\b', claim_blob, re.I):
                covered_checks.append(chk)
            else:
                missing_checks.append(chk)
        if missing_checks:
            cand_warnings.append(f'subfield_preset:{preset_key}:missing_checks:{",".join(missing_checks)}')
        subfield_vetting = {
            'preset': preset_key,
            'required_checks': req_checks,
            'covered_checks': covered_checks,
            'missing_checks': missing_checks,
        }

    # Build enriched surviving candidate & standardized idea_seed_bundle entry
    closest_ids = list(cand.get('closest_work_ids') or all_refs)
    ft_digests = {
        pid: digests[pid] for pid in all_refs if pid in digests
    }
    fc_ids = [str(x) for x in _as_list(cand.get('failure_case_ids'))]
    linked_patterns = [fp for fp in failure_patterns] if (cand.get('trigger') == 'failure_cases' or fc_ids) else []

    enriched = {
        **cand,
        'id': cid,
        'gap_tier_ceiling': ceiling,
        'gap_below_target_venue_tier': below_target,
        'scoop_and_obsolescence_risk': scoop_obj,
        'resource_feasibility': res_obj,
        'trajectory_tree': traj_tree,
        'author_advantage_fit': author_fit_obj,
        'code_prior_art_summary': code_pa_obj,
        'root_cause_barrier': barrier,
        'why_now_enabler': why_now,
        'missing_or_weak_why_now_enabler': why_now_weak,
        'evaluation_validity_gap': eval_validity_obj,
        'isomorphic_transfer_leads': iso_leads,
        'so_what_decision_impact': so_what,
        'durability_12_24m': durability,
        'subfield_vetting': subfield_vetting,
        'triage_warnings': list(dict.fromkeys(cand_warnings)),
    }

    seed_entry = {
        'gap_id': cid,
        'claim': claim,
        'disposition': cand.get('disposition') or 'supported_candidate',
        'closest_work_ids': closest_ids,
        'closest_works': cand.get('closest_works') or [{'id': wid} for wid in closest_ids],
        'prior_art_boundary': {
            'closest_work_ids': closest_ids,
            'cited_ids': list(cand.get('cited_ids') or cand.get('cited_paper_ids') or []),
            'support_ids': list(cand.get('support_ids') or cand.get('cited_ids') or []),
            'cutoff_date': cutoff_date,
            'cutoff_year': cutoff_year,
            'mechanism_aliases': list(_as_list(cand.get('mechanism_aliases'))),
            'alternate_vocabularies': list(_as_list(cand.get('alternate_vocabularies'))),
            'code_prior_art_screened': bool(cpa_screened),
            'summary': str(cand.get('prior_art_boundary') or f'Verified against {len(closest_ids)} closest works up to {cutoff_date or cutoff_year or "corpus cutoff"}.'),
        },
        'full_text_digests': ft_digests,
        'gap_tier_ceiling': ceiling,
        'gap_tier_ceiling_detail': {
            'ceiling': ceiling,
            'target_venue_tier': norm_target,
            'gap_below_target_venue_tier': below_target,
        },
        'gap_below_target_venue_tier': below_target,
        'resource_feasibility': res_obj,
        'scoop_and_obsolescence_risk': scoop_obj,
        'trajectory_tree': traj_tree,
        'failure_cases': {
            'trigger': cand.get('trigger'),
            'failure_case_ids': fc_ids,
            'patterns': linked_patterns,
        } if (cand.get('trigger') == 'failure_cases' or fc_ids) else None,
        'author_advantage_fit': author_fit_obj,
        'code_prior_art': code_pa_obj,
        'root_cause_barrier': barrier,
        'why_now_enabler': why_now,
        'missing_or_weak_why_now_enabler': why_now_weak,
        'evaluation_validity_gap': eval_validity_obj,
        'isomorphic_transfer_leads': iso_leads,
        'so_what_decision_impact': so_what,
        'durability_12_24m': durability,
        'subfield_vetting': subfield_vetting,
        'idea_portfolio': portfolio_out,
        'pre_mortem': pre_mortem_raw,
        'triage_warnings': list(dict.fromkeys(cand_warnings)),
    }
    return enriched, seed_entry, None, cand_warnings


def _fc_entry_verified(fc: dict[str, Any]) -> bool:
    if fc.get('engineering_checked') is False:
        return False
    st = str(fc.get('engineering_status') or '').strip().lower()
    if st in {'unchecked', 'failed', 'not_checked'}:
        return False
    return (fc.get('engineering_checked') is True) or (st in {'implementation_checked', 'protocol_matched', 'clean', 'passed'})


def run_pipeline(
    topic: str,
    corpus: dict[str, dict[str, Any]],
    digests: dict[str, dict[str, Any]],
    candidates: list[dict[str, Any]],
    *,
    default_cutoff: str | None = None,
    feedback_store: Path | None = None,
    allow_partial: bool = False,
    ws_eng_failed: bool = False,
    ws_eng_detail: str = '',
    storm_report: dict[str, Any] | None = None,
    campaign: dict[str, Any] | None = None,
    citation_graph: dict[str, Any] | None = None,
    failure_cases: list[dict[str, Any]] | None = None,
    code_prior_art: list[dict[str, Any]] | None = None,
    target_venue_tier: str | None = None,
    user_resources: dict[str, Any] | None = None,
    author_profile: dict[str, Any] | None = None,
    subfield_preset: str | None = None,
    as_of_date: str | None = None,
    strict_triage: bool = False,
    require_idea_portfolio: bool = False,
    require_pre_mortem: bool = False,
    require_code_prior_art: bool = False,
) -> dict[str, Any]:
    if as_of_date is not None:
        if not isinstance(as_of_date, str):
            raise ValueError(f'as_of_date must be an ISO date string (YYYY-MM-DD), got {type(as_of_date).__name__}')
        if as_of_date.strip() and _parse_iso_date(as_of_date) is None:
            raise ValueError(f'Invalid as_of_date (expected YYYY-MM-DD): {as_of_date!r}')
    if user_resources is not None:
        if not isinstance(user_resources, dict):
            raise ValueError('user_resources must be a JSON object')
        for rk in ('gpu_count', 'vram_gb', 'total_vram_gb', 'api_budget_usd', 'timeline_days', 'estimated_weeks'):
            _coerce_num(user_resources.get(rk), f'user_resources.{rk}', non_negative=True)

    prior_rejected_tokens: list[set[str]] = []
    prior_store: dict[str, Any] = {'rejected_claims': []}
    if feedback_store and feedback_store.is_file():
        loaded = json.loads(feedback_store.read_text(encoding='utf-8'), parse_constant=_reject_nonfinite)
        if isinstance(loaded, dict) and isinstance(loaded.get('rejected_claims'), list):
            prior_store = loaded
            for item in loaded['rejected_claims']:
                if isinstance(item, dict) and item.get('claim'):
                    prior_rejected_tokens.append(_tokens(str(item['claim'])))

    families = sorted({p['family'] for p in corpus.values() if p.get('family')})
    non_kill_families = {p['family'] for p in corpus.values() if p.get('family') and p.get('family') != 'kill_search'}
    dual_regime_ok = (not non_kill_families) or ({'same_problem', 'cross_setting_analogy'}.issubset(non_kill_families))

    structured_mining = _mine_structured_matrices(corpus, storm_report=storm_report, failure_cases=failure_cases)
    fc_by_id, failure_patterns = _process_failure_cases(
        failure_cases, corpus, campaign=campaign, citation_graph=citation_graph, code_prior_art=code_prior_art,
    )

    surviving: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seeds: list[dict[str, Any]] = []
    triage_warnings: list[str] = []
    trajectory_trees: dict[str, Any] = {}
    surviving_tokens: list[set[str]] = []
    claims_by_cid: dict[str, str] = {}

    for idx, cand in enumerate(candidates):
        cid = str(cand.get('id') or cand.get('candidate_id') or f'C{idx + 1}')
        claim = str(cand.get('claim') or '').strip()
        claims_by_cid[cid] = claim
        cited = list(cand.get('cited_ids') or cand.get('cited_paper_ids') or [])
        support = list(cand.get('support_ids') or cited)
        all_refs = list(dict.fromkeys(cited + support))
        cutoff_date = _coerce_date_str(cand.get('cutoff_date'), f'candidates[{cid}].cutoff_date') or _coerce_date_str(default_cutoff, 'default_cutoff')
        cutoff_year = _coerce_int_year(cand.get('cutoff_year'), f'candidates[{cid}].cutoff_year')

        # 1. Temporal leak check (CKM-HypoGen)
        leaked = [pid for pid in all_refs if pid in corpus and _is_after_cutoff(corpus[pid], cutoff_date, cutoff_year)]
        if leaked:
            rejected.append(_reject(cid, 'DROP_TEMPORAL_LEAK', f'Cites post-cutoff paper(s): {", ".join(leaked)}', leaked))
            continue

        # 2. Read-before-cite & retraction check (grounded-research-ideation + PaperQA2)
        unread = [
            pid for pid in all_refs
            if pid not in digests
            or not str(digests[pid].get('digest') or digests[pid].get('quote') or '').strip()
            or str(digests[pid].get('access') or digests[pid].get('read_status') or '').strip().lower() not in _FULL_TEXT_ACCESS
        ]
        if unread:
            rejected.append(_reject(cid, 'DROP_UNREAD_CITATION', f'Unread or missing digest for: {", ".join(unread)}', unread))
            continue
        retracted = [pid for pid in all_refs if pid in corpus and corpus[pid].get('retraction_status') == 'retracted']
        if retracted:
            rejected.append(_reject(cid, 'DROP_RETRACTED_SUPPORT', f'Support includes retracted work(s): {", ".join(retracted)}', retracted))
            continue

        # 3. Engineering-bug gate (extended for F30.2 failure_cases)
        eng_diag = cand.get('engineering_diagnostics')
        fc_ids = [str(x) for x in _as_list(cand.get('failure_case_ids'))]
        fc_bad = False
        fc_bad_detail = ''
        if cand.get('trigger') == 'failure_cases' or fc_ids:
            if cand.get('engineering_checked') is not True and str(cand.get('engineering_status') or '').strip().lower() not in {'implementation_checked', 'protocol_matched', 'clean', 'passed'}:
                fc_bad = True
                fc_bad_detail = 'Failure-first candidate lacks verified engineering check before gap promotion.'
            elif fc_ids:
                if not fc_by_id:
                    fc_bad = True
                    fc_bad_detail = f'failure_cases input missing for linked failure_case_ids: {", ".join(fc_ids)}'
                else:
                    missing_fc = [fid for fid in fc_ids if fid not in fc_by_id]
                    unchecked_fc = [fid for fid in fc_ids if fid in fc_by_id and not _fc_entry_verified(fc_by_id[fid])]
                    if missing_fc:
                        fc_bad = True
                        fc_bad_detail = f'Unknown failure_case_ids: {", ".join(missing_fc)}'
                    elif unchecked_fc:
                        fc_bad = True
                        fc_bad_detail = f'Linked failure cases failed or skipped engineering checks: {", ".join(unchecked_fc)}'

        eng_bad = (
            ws_eng_failed
            or fc_bad
            or cand.get('engineering_checked') is False
            or cand.get('engineering_status') in {'unchecked', 'failed', 'not_checked'}
            or (isinstance(eng_diag, dict) and eng_diag.get('verdict') == 'ENGINEERING_BUG_DETECTED')
        )
        if eng_bad:
            detail = fc_bad_detail or ws_eng_detail or 'Unresolved or failed engineering diagnostics block gap promotion.'
            rejected.append(_reject(cid, 'DROP_ENGINEERING_BUG', detail))
            continue

        # 4. Per-candidate kill-search (hardened F27.5 cross-vocab + campaign + citation_graph + F30.4 code_prior_art)
        hindsight_date = _coerce_date_str(cand.get('hindsight_eval_date'), f'candidates[{cid}].hindsight_eval_date')
        eval_date = hindsight_date or cutoff_date
        eval_year = None if hindsight_date else cutoff_year
        kill_hits = _kill_search_matches(
            claim, set(all_refs), corpus, eval_date, eval_year,
            cand=cand, campaign=campaign, citation_graph=citation_graph, code_prior_art=code_prior_art,
        )
        if kill_hits:
            rejected.append(_reject(cid, 'DROP_ALREADY_SOLVED', f'Closed by prior/hindsight work(s): {", ".join(kill_hits)}', kill_hits))
            continue

        # 5. F19 Parsimony & Anti-Problem-Inflation gate
        pars_fail = _check_parsimony_candidate(cand)
        if pars_fail is not None:
            rejected.append(_reject(cid, pars_fail[0], pars_fail[1]))
            continue

        # 6. Dual-regime & uncovered-branches coverage gate
        uncovered = cand.get('uncovered_branches') or []
        if (isinstance(uncovered, list) and len(uncovered) > 0) or not dual_regime_ok:
            rejected.append(_reject(cid, 'DROP_INSUFFICIENT_COVERAGE', 'Uncovered STORM branches or missing dual-regime coverage.'))
            continue

        # 7. Single-paper fragility gate
        if len(set(support)) < 2:
            rejected.append(_reject(cid, 'DROP_SINGLE_PAPER_FRAGILE', f'Only {len(set(support))} independent supporting paper(s); >=2 required.', support))
            continue

        # 8. SGHA 5-role critic & artificial scope gate
        sgha_ok, sgha_code, sgha_msg = _sgha_5role_passed(cand)
        if not sgha_ok:
            rejected.append(_reject(cid, sgha_code, sgha_msg))
            continue

        # 9. IRIS feedback memory & AI-Researcher token-Jaccard dedup
        c_toks = _tokens(claim)
        if any(_jaccard(c_toks, prev) >= 0.80 for prev in prior_rejected_tokens):
            rejected.append(_reject(cid, 'DROP_DUPLICATE', 'Matches previously killed hypothesis in feedback memory.'))
            continue
        if any(_jaccard(c_toks, prev) >= 0.80 for prev in surviving_tokens):
            rejected.append(_reject(cid, 'DROP_DUPLICATE', 'Token-similar duplicate of an already surviving candidate.'))
            continue

        # 10. Stage 10 Triage (F27, F28, F30, F31, F32)
        enriched, seed_entry, triage_rej, cand_warns = _evaluate_candidate_triage(
            cand, cid, all_refs, corpus, digests,
            storm_report=storm_report,
            structured_mining=structured_mining,
            failure_patterns=failure_patterns,
            code_prior_art=code_prior_art,
            target_venue_tier=target_venue_tier,
            user_resources=user_resources,
            author_profile=author_profile,
            subfield_preset=subfield_preset,
            as_of_date=as_of_date,
            cutoff_date=cutoff_date,
            cutoff_year=cutoff_year,
            strict_triage=strict_triage,
            require_idea_portfolio=require_idea_portfolio,
            require_pre_mortem=require_pre_mortem,
            require_code_prior_art=require_code_prior_art,
        )
        if triage_rej is not None:
            rejected.append(_reject(cid, triage_rej[0], triage_rej[1]))
            continue

        surviving_tokens.append(c_toks)
        surviving.append(enriched)
        seeds.append(seed_entry)
        trajectory_trees[cid] = enriched['trajectory_tree']
        for w in cand_warns:
            if w not in triage_warnings:
                triage_warnings.append(w)

    if feedback_store is not None and rejected:
        for rej in rejected:
            prior_store['rejected_claims'].append({'id': rej['id'], 'reason_code': rej['reason_code'], 'claim': claims_by_cid.get(rej['id'], '')})
        feedback_store.parent.mkdir(parents=True, exist_ok=True)
        feedback_store.write_text(json.dumps(prior_store, indent=2, ensure_ascii=False), encoding='utf-8')

    corpus_traj, _ = _build_trajectory_tree(corpus, cutoff_date=default_cutoff, storm_report=storm_report)
    trajectory_trees['_corpus'] = corpus_traj

    norm_target_tier, _ = _normalize_target_venue_tier(target_venue_tier)
    eff_preset_top = str(subfield_preset).strip().lower() if subfield_preset else None
    if eff_preset_top and eff_preset_top not in SUBFIELD_PRESETS:
        raise ValueError(f'Unknown subfield_preset: {subfield_preset!r}')

    idea_seed_bundle = {
        'schema': 'research_scientist_idea_seed_bundle_v1',
        'source_pipeline_schema': 'research_scientist_gap_pipeline_v1',
        'topic': topic,
        'subfield_preset': eff_preset_top,
        'target_venue_tier': norm_target_tier,
        'seeds': seeds,
    }

    passed = bool(surviving) and (allow_partial or not rejected)
    exit_code = 0 if passed else 1
    return {
        'schema': 'research_scientist_gap_pipeline_v1',
        'topic': topic,
        'surviving_gaps': surviving,
        'rejected_gaps': rejected,
        'coverage': {'corpus_size': len(corpus), 'families': families, 'dual_regime_ok': dual_regime_ok},
        'structured_gap_mining': structured_mining,
        'trajectory_trees': trajectory_trees,
        'failure_pattern_summary': failure_patterns,
        'triage_warnings': triage_warnings,
        'idea_seed_bundle': idea_seed_bundle,
        'exit_code': exit_code,
    }


def compact_summary(report: dict[str, Any], artifact_path: Path) -> dict[str, Any]:
    bundle = report.get('idea_seed_bundle') or {}
    warns = report.get('triage_warnings') or []
    out = {
        'compact': True,
        'schema': report['schema'],
        'artifact_path': str(artifact_path),
        'topic': str(report['topic'])[:200],
        'surviving_count': len(report['surviving_gaps']),
        'rejected_count': len(report['rejected_gaps']),
        'idea_seed_count': len(bundle.get('seeds') or []),
        'triage_warnings_count': len(warns),
        'subfield_preset': bundle.get('subfield_preset'),
        'target_venue_tier': bundle.get('target_venue_tier'),
        'surviving_ids': [str(g['id'])[:80] for g in report['surviving_gaps'][:10]],
        'rejected_summary': [
            {'id': str(r['id'])[:80], 'reason_code': str(r['reason_code'])[:80]}
            for r in report['rejected_gaps'][:10]
        ],
        'exit_code': report['exit_code'],
    }
    while len(json.dumps(out, separators=(',', ':'), ensure_ascii=False).encode('utf-8')) >= 4096 and (out['rejected_summary'] or out['surviving_ids']):
        if out['rejected_summary']:
            out['rejected_summary'].pop()
        elif out['surviving_ids']:
            out['surviving_ids'].pop()
    if len(json.dumps(out, separators=(',', ':'), ensure_ascii=False).encode('utf-8')) >= 4096:
        out['topic'] = out['topic'][:80]
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--topic', default='', help='Target research topic')
    parser.add_argument('--corpus', type=Path, default=None, help='Corpus JSON path')
    parser.add_argument('--digests', type=Path, default=None, help='Read digests JSON path')
    parser.add_argument('--candidates', type=Path, default=None, help='Gap candidates JSON path')
    parser.add_argument('--workspace', type=Path, default=None, help='Workspace directory with gap/plan/code artifacts')
    parser.add_argument('--feedback-store', type=Path, default=None, help='Optional JSON file storing rejected hypothesis memory')
    parser.add_argument('--storm', type=Path, default=None, help='Optional storm_explorer.py JSON output')
    parser.add_argument('--campaign', type=Path, default=None, help='Optional search_campaign.py JSON output')
    parser.add_argument('--citation-graph', type=Path, default=None, help='Optional citation_graph.py JSON output')
    parser.add_argument('--failure-cases', type=Path, default=None, help='Optional empirical failure_cases JSON path')
    parser.add_argument('--code-prior-art', type=Path, default=None, help='Optional open-source code_prior_art JSON path')
    parser.add_argument('--target-venue-tier', type=str, default=None, help='Target venue tier (e.g., q1_or_tier_a, top_tier_flagship, workshop)')
    parser.add_argument('--user-resources', type=str, default=None, help='User resource constraints JSON path or inline JSON')
    parser.add_argument('--author-profile', type=str, default=None, help='Author advantage profile JSON path or inline JSON')
    parser.add_argument('--as-of-date', type=str, default=None, help='Reference ISO date (YYYY-MM-DD) for scoop-risk recency calculations')
    parser.add_argument('--subfield-preset', choices=sorted(SUBFIELD_PRESETS.keys()), default=None, help='Optional AI/CS subfield depth preset')
    parser.add_argument('--strict-triage', action='store_true', help='Hard-reject candidates failing venue-tier, resource feasibility, or pre-mortem checks')
    parser.add_argument('--require-idea-portfolio', action='store_true', help='Hard-reject candidates missing a 3-4 angle idea_portfolio')
    parser.add_argument('--require-pre-mortem', action='store_true', help='Hard-reject candidates missing a complete pre_mortem with 1-2d killer_experiment')
    parser.add_argument('--require-code-prior-art', action='store_true', help='Hard-reject candidates lacking open-source code_prior_art screening')
    parser.add_argument('--seed-bundle-out', type=Path, default=None, help='Optional output JSON path for standalone idea_seed_bundle export')
    parser.add_argument('--allow-partial', action='store_true', help='Exit 0 if >=1 candidate survives even when others are rejected')
    parser.add_argument('--out', type=Path, default=None, help='Optional output JSON path')
    parser.add_argument('--compact', action='store_true', help='Emit bounded <4096B stdout summary + disk artifact path')
    args = parser.parse_args()
    try:
        ws_eng_failed = False
        ws_eng_detail = ''
        ctx: dict[str, Any] = {}
        if args.workspace is not None:
            corpus, digests, candidates, default_cutoff, ws_eng_failed, ws_eng_detail = _load_workspace(args.workspace)
            ctx = _load_workspace_context(args.workspace)
            topic = args.topic or args.workspace.name
        else:
            if args.corpus is None or args.digests is None or args.candidates is None:
                raise ValueError('Provide either --workspace or all of --corpus, --digests, --candidates')
            corpus, c_cut = _load_corpus(args.corpus)
            digests = _load_digests(args.digests)
            candidates, k_cut = _load_candidates(args.candidates)
            ctx = _load_candidates_context(args.candidates)
            default_cutoff = k_cut or c_cut
            topic = args.topic or 'research_gap_audit'

        storm_report = _load_json_payload(args.storm) if args.storm is not None else ctx.get('storm_report')
        campaign = _load_json_payload(args.campaign) if args.campaign is not None else ctx.get('campaign')
        citation_graph = _load_json_payload(args.citation_graph) if args.citation_graph is not None else ctx.get('citation_graph')
        failure_cases = _load_json_payload(args.failure_cases, list_key='failure_cases') if args.failure_cases is not None else ctx.get('failure_cases')
        code_prior_art = _load_json_payload(args.code_prior_art, list_key='code_prior_art') if args.code_prior_art is not None else ctx.get('code_prior_art')
        user_resources = _load_json_payload(args.user_resources) if args.user_resources is not None else ctx.get('user_resources')
        author_profile = _load_json_payload(args.author_profile) if args.author_profile is not None else ctx.get('author_profile')
        target_venue_tier = args.target_venue_tier or ctx.get('target_venue_tier')
        subfield_preset = args.subfield_preset or ctx.get('subfield_preset')
        as_of_date = args.as_of_date or ctx.get('as_of_date')

        report = run_pipeline(
            topic, corpus, digests, candidates,
            default_cutoff=default_cutoff,
            feedback_store=args.feedback_store,
            allow_partial=args.allow_partial,
            ws_eng_failed=ws_eng_failed,
            ws_eng_detail=ws_eng_detail,
            storm_report=storm_report,
            campaign=campaign,
            citation_graph=citation_graph,
            failure_cases=failure_cases,
            code_prior_art=code_prior_art,
            target_venue_tier=target_venue_tier,
            user_resources=user_resources,
            author_profile=author_profile,
            subfield_preset=subfield_preset,
            as_of_date=as_of_date,
            strict_triage=args.strict_triage,
            require_idea_portfolio=args.require_idea_portfolio,
            require_pre_mortem=args.require_pre_mortem,
            require_code_prior_art=args.require_code_prior_art,
        )
        if args.seed_bundle_out is not None:
            args.seed_bundle_out.parent.mkdir(parents=True, exist_ok=True)
            args.seed_bundle_out.write_text(json.dumps(report['idea_seed_bundle'], indent=2, ensure_ascii=False), encoding='utf-8')
        out_path = args.out
        if args.compact and out_path is None:
            out_path = _auto_artifact_path('gap_pipeline')
        if out_path is not None:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
        if args.compact:
            print(json.dumps(compact_summary(report, out_path), separators=(',', ':'), ensure_ascii=False))
        else:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        return report['exit_code']
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())

