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
import os
import re
import sys
import tempfile
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


def _load_corpus(path: Path | None) -> tuple[dict[str, dict[str, Any]], str | None]:
    if path is None:
        return {}, None
    raw = json.loads(path.read_text(encoding='utf-8'))
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
            'source': str(item.get('source') or ''),
            'family': str(item.get('family') or ''),
            'year': year,
            'published_date': pub_date,
            'title': str(item.get('title') or ''),
            'abstract': item.get('abstract'),
            'text': str(item.get('text') or item.get('full_text_excerpt') or ''),
            'access': str(item.get('access') or ''),
            'retraction_status': str(item.get('retraction_status') or 'clean'),
        }
    return corpus, cutoff


def _load_digests(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    raw = json.loads(path.read_text(encoding='utf-8'))
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
    raw = json.loads(path.read_text(encoding='utf-8'))
    if isinstance(raw, dict):
        items = raw.get('candidates', [])
        cutoff = _coerce_date_str(raw.get('cutoff_date'), 'candidates.cutoff_date')
    elif isinstance(raw, list):
        items = raw
        cutoff = None
    else:
        raise ValueError('candidates JSON must be a list or {"candidates": [...]}')
    return [c for c in items if isinstance(c, dict)], cutoff


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
        pdata = json.loads(plan_file.read_text(encoding='utf-8'))
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
            gdata = json.loads(gap_file.read_text(encoding='utf-8'))
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


def _kill_search_matches(claim: str, candidate_ids: set[str], corpus: dict[str, dict[str, Any]],
                         eval_date: str | None, eval_year: int | None) -> list[str]:
    claim_toks = _tokens(claim)
    if not claim_toks:
        return []
    hits: list[str] = []
    for pid, paper in corpus.items():
        if pid in candidate_ids:
            continue
        if eval_date or eval_year is not None:
            if _is_after_cutoff(paper, eval_date, eval_year):
                continue
        title_toks = _tokens(paper['title'])
        # Clean-room require_abstract=False: evaluate title + optional abstract + text
        doc_blob = ' '.join(x for x in (paper['title'], paper.get('abstract') or '', paper.get('text') or '') if x)
        doc_toks = _tokens(doc_blob)
        if not doc_toks:
            continue
        claim_recall = len(claim_toks & doc_toks) / len(claim_toks)
        title_recall = len(claim_toks & title_toks) / len(claim_toks)
        shared_count = len(claim_toks & doc_toks)
        is_kill_family = paper.get('family') == 'kill_search'
        if title_recall >= 0.70 or (claim_recall >= 0.50 and shared_count >= 3) or (is_kill_family and claim_recall >= 0.45 and shared_count >= 3):
            hits.append(pid)
    return hits


def _ablation_dict_nonpositive_or_empty(ablation: dict[str, Any], cand: dict[str, Any], require_numeric: bool = False) -> str | None:
    mg = ablation.get('marginal_gain')
    if isinstance(mg, (int, float)) and not isinstance(mg, bool):
        if mg <= 0:
            return 'Ablation evidence shows non-positive marginal_gain over simplest baseline.'
        return None
    b_val = ablation.get('baseline_score')
    p_val = ablation.get('proposed_score')
    if (isinstance(b_val, (int, float)) and not isinstance(b_val, bool)
            and isinstance(p_val, (int, float)) and not isinstance(p_val, bool)):
        direction = str(ablation.get('metric_direction') or cand.get('metric_direction') or 'higher').lower()
        delta = (b_val - p_val) if direction == 'lower' else (p_val - b_val)
        if delta <= 0:
            return 'Ablation evidence fails to outperform simplest baseline.'
        return None
    if require_numeric:
        return 'Multi-module ablation dict lacks numeric marginal_gain or baseline/proposed scores.'
    return None


def _check_parsimony_candidate(cand: dict[str, Any]) -> tuple[str, str] | None:
    claim_blob = ' '.join(str(x or '') for x in (cand.get('claim'), cand.get('rationale')))
    audit = cand.get('parsimony_audit') if isinstance(cand.get('parsimony_audit'), dict) else {}
    delta = cand.get('measured_delta')
    tiny_delta = isinstance(delta, (int, float)) and not isinstance(delta, bool) and abs(delta) <= 0.005
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
        if verdict in {'REJECT', 'DROP'} or (isinstance(score, (int, float)) and score < 0.60) or (isinstance(conf, (int, float)) and conf < 0.50):
            return False, 'DROP_SGHA_CRITIC_REJECT', 'SGHA 5-role critic panel rejected candidate below survival threshold.'
    return True, '', ''


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
) -> dict[str, Any]:
    prior_rejected_tokens: list[set[str]] = []
    prior_store: dict[str, Any] = {'rejected_claims': []}
    if feedback_store and feedback_store.is_file():
        loaded = json.loads(feedback_store.read_text(encoding='utf-8'))
        if isinstance(loaded, dict) and isinstance(loaded.get('rejected_claims'), list):
            prior_store = loaded
            for item in loaded['rejected_claims']:
                if isinstance(item, dict) and item.get('claim'):
                    prior_rejected_tokens.append(_tokens(str(item['claim'])))

    families = sorted({p['family'] for p in corpus.values() if p.get('family')})
    non_kill_families = {p['family'] for p in corpus.values() if p.get('family') and p.get('family') != 'kill_search'}
    dual_regime_ok = (not non_kill_families) or ({'same_problem', 'cross_setting_analogy'}.issubset(non_kill_families))

    surviving: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
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

        # 3. Engineering-bug gate
        eng_diag = cand.get('engineering_diagnostics')
        eng_bad = (
            ws_eng_failed
            or cand.get('engineering_checked') is False
            or cand.get('engineering_status') in {'unchecked', 'failed', 'not_checked'}
            or (isinstance(eng_diag, dict) and eng_diag.get('verdict') == 'ENGINEERING_BUG_DETECTED')
        )
        if eng_bad:
            detail = ws_eng_detail or 'Unresolved or failed engineering diagnostics block gap promotion.'
            rejected.append(_reject(cid, 'DROP_ENGINEERING_BUG', detail))
            continue

        # 4. Per-candidate kill-search (clean-room, require_abstract=False)
        hindsight_date = _coerce_date_str(cand.get('hindsight_eval_date'), f'candidates[{cid}].hindsight_eval_date')
        eval_date = hindsight_date or cutoff_date
        eval_year = None if hindsight_date else cutoff_year
        kill_hits = _kill_search_matches(claim, set(all_refs), corpus, eval_date, eval_year)
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

        surviving_tokens.append(c_toks)
        surviving.append({**cand, 'id': cid})

    if feedback_store is not None and rejected:
        for rej in rejected:
            prior_store['rejected_claims'].append({'id': rej['id'], 'reason_code': rej['reason_code'], 'claim': claims_by_cid.get(rej['id'], '')})
        feedback_store.parent.mkdir(parents=True, exist_ok=True)
        feedback_store.write_text(json.dumps(prior_store, indent=2, ensure_ascii=False), encoding='utf-8')

    passed = bool(surviving) and (allow_partial or not rejected)
    exit_code = 0 if passed else 1
    return {
        'schema': 'research_scientist_gap_pipeline_v1',
        'topic': topic,
        'surviving_gaps': surviving,
        'rejected_gaps': rejected,
        'coverage': {'corpus_size': len(corpus), 'families': families, 'dual_regime_ok': dual_regime_ok},
        'exit_code': exit_code,
    }


def compact_summary(report: dict[str, Any], artifact_path: Path) -> dict[str, Any]:
    out = {
        'compact': True,
        'schema': report['schema'],
        'artifact_path': str(artifact_path),
        'topic': str(report['topic'])[:200],
        'surviving_count': len(report['surviving_gaps']),
        'rejected_count': len(report['rejected_gaps']),
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
    parser.add_argument('--allow-partial', action='store_true', help='Exit 0 if >=1 candidate survives even when others are rejected')
    parser.add_argument('--out', type=Path, default=None, help='Optional output JSON path')
    parser.add_argument('--compact', action='store_true', help='Emit bounded <4096B stdout summary + disk artifact path')
    args = parser.parse_args()
    try:
        ws_eng_failed = False
        ws_eng_detail = ''
        if args.workspace is not None:
            corpus, digests, candidates, default_cutoff, ws_eng_failed, ws_eng_detail = _load_workspace(args.workspace)
            topic = args.topic or args.workspace.name
        else:
            if args.corpus is None or args.digests is None or args.candidates is None:
                raise ValueError('Provide either --workspace or all of --corpus, --digests, --candidates')
            corpus, c_cut = _load_corpus(args.corpus)
            digests = _load_digests(args.digests)
            candidates, k_cut = _load_candidates(args.candidates)
            default_cutoff = k_cut or c_cut
            topic = args.topic or 'research_gap_audit'
        report = run_pipeline(
            topic, corpus, digests, candidates,
            default_cutoff=default_cutoff,
            feedback_store=args.feedback_store,
            allow_partial=args.allow_partial,
            ws_eng_failed=ws_eng_failed,
            ws_eng_detail=ws_eng_detail,
        )
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

