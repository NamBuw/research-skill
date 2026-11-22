#!/usr/bin/env python3
"""STORM / Co-STORM multi-perspective topic & gap explorer (pure stdlib).

MIT Attribution: Multi-perspective question planning, deduplicated InformationTable,
hierarchical KnowledgeBase outline, and uncovered-branch tracking adapted from
Stanford OVAL STORM / Co-STORM (knowledge_storm, MIT License).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

_STOPWORDS = frozenset({
    'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from', 'in', 'into',
    'is', 'it', 'of', 'on', 'or', 'that', 'the', 'their', 'this', 'to', 'under',
    'vs', 'versus', 'with', 'without', 'via', 'between', 'across', 'during',
})
_MINING_STOPWORDS = _STOPWORDS | frozenset({
    'outperforms', 'outperform', 'improves', 'improve', 'gains', 'gain', 'superior',
    'stabilizes', 'stabilize', 'calibrated', 'succeeds', 'succeed', 'reduces', 'reduce',
    'degrades', 'degrade', 'fails', 'fail', 'worse', 'inferior', 'miscalibrated',
    'collapses', 'collapse', 'underperforms', 'underperform', 'drops', 'drop',
    'unstable', 'diverges', 'diverge', 'does', 'not', 'only', 'measured', 'observed',
    'study', 'paper', 'method', 'methods', 'model', 'models', 'approach', 'approaches',
    'in_domain', 'ood', 'shift', 'adversarial', 'noisy', 'quantized', 'low', 'resource',
    'domain', 'regime', 'setting', 'evaluation', 'benchmark', 'results', 'result',
})
_NEGATION_RE = re.compile(
    r'(?<![a-z0-9-])(?:no|zero|without|lack(?:s|ing)?|absent|missing|never|not\s+(?:evaluated|tested|measured|reported|studied))\s+'
    r'(?:[a-z0-9-]+\s+){0,3}',
    re.I,
)
_POS_FINDING_RE = re.compile(
    r'\b(?:outperforms?|improves?|gains?|superior|stabilizes?|calibrated|succeeds?|'
    r'reduces?\s+(?:error|loss|latency|ece|variance)|higher\s+(?:accuracy|f1|robustness)|'
    r'lower\s+(?:ece|error|latency))\b',
    re.I,
)
_NEG_FINDING_RE = re.compile(
    r'\b(?:degrades?|fails?|worse|inferior|miscalibrat\w*|collapses?|underperforms?|'
    r'drops?|unstable|diverges?|no\s+(?:gain|improvement|benefit)|'
    r'does\s+not\s+(?:improve|outperform|generalize|scale)|broken)\b',
    re.I,
)
_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?;])\s+|\n+')
_ASSUMPTION_RE = re.compile(
    r'\b(?:assum(?:e|es|ed|ing|ption(?:s)?)\s+(?:that\s+)?|requir(?:e|es|ed|ing)\s+)([^.;\n]{8,140})',
    re.I,
)
_CANONICAL_ASSUMPTIONS: tuple[tuple[str, re.Pattern[str], tuple[str, ...], str], ...] = (
    (
        'i.i.d. / stationary data distribution',
        re.compile(r'\b(?:i\.?i\.?d\.?|independent\s+and\s+identically\s+distributed|stationary)\b', re.I),
        ('ood_shift', 'non_stationary', 'shift', 'domain_shift', 'distribution_shift', 'deployment_constrained'),
        'Test/deployment distribution shifts break train-test stationarity assumed by the method.',
    ),
    (
        'clean / noise-free supervision labels',
        re.compile(r'\b(?:clean\s+labels?|noise[- ]free\s+labels?|oracle\s+labels?|noiseless)\b', re.I),
        ('noisy', 'corrupted', 'low_resource', 'deployment_constrained'),
        'Real-world annotation noise or weak supervision violates clean-label assumptions.',
    ),
    (
        'unbounded memory / context or offline batching',
        re.compile(r'\b(?:unbounded\s+(?:memory|context)|offline\s+batch|full\s+kv\s+cache|quadratic\s+memory)\b', re.I),
        ('long_context', 'low_resource', 'quantized', 'deployment_constrained', 'streaming'),
        'Latency, VRAM, or streaming deployment budgets violate unbounded memory/offline batching.',
    ),
    (
        'oracle retrieval / uncorrupted context',
        re.compile(r'\b(?:oracle\s+retriev\w*|perfect\s+retriev\w*|ground[- ]truth\s+context)\b', re.I),
        ('noisy', 'ood_shift', 'adversarial', 'deployment_constrained'),
        'Noisy or adversarial retrieval inputs break oracle-retrieval assumptions.',
    ),
    (
        'homogeneous / degree-balanced graph or input structure',
        re.compile(r'\b(?:homogeneous\s+graph|homophil\w*|uniform\s+degree)\b', re.I),
        ('high_degree', 'ood_shift', 'heterophil', 'long_tail'),
        'Heterophilic or heavy-tailed degree distributions violate homogeneity assumptions.',
    ),
    (
        'pre-calibrated confidence scores',
        re.compile(r'\b(?:calibrated\s+scores?|well[- ]calibrated\s+probabilit\w*|true\s+posterior)\b', re.I),
        ('ood_shift', 'adversarial', 'quantized', 'deployment_constrained'),
        'Distribution shift or quantization induces overconfident miscalibration.',
    ),
)
_REGIME_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ('ood_shift', re.compile(r'\b(?:ood|out[- ]of[- ]distribution|domain[- ]shift|distribution[- ]shift|covariate[- ]shift|cross[- ]domain)\b', re.I)),
    ('adversarial', re.compile(r'\b(?:adversarial|perturbation|jailbreak|attack)\b', re.I)),
    ('low_resource', re.compile(r'\b(?:low[- ]resource|few[- ]shot|low[- ]budget|small[- ]data)\b', re.I)),
    ('long_context', re.compile(r'\b(?:long[- ]context|long[- ]sequence|128k|32k|extrapolation)\b', re.I)),
    ('noisy', re.compile(r'\b(?:noisy|corrupted|label[- ]noise|ocr[- ]noise)\b', re.I)),
    ('quantized', re.compile(r'\b(?:quantiz\w*|int4|int8|fp8|pruned)\b', re.I)),
    ('deployment_constrained', re.compile(r'\b(?:deployment|edge|streaming|real[- ]time|memory[- ]bound|vram[- ]bound)\b', re.I)),
    ('high_degree', re.compile(r'\b(?:high[- ]degree|degree[- ]shift|long[- ]tail)\b', re.I)),
    ('zero_shot', re.compile(r'\b(?:zero[- ]shot)\b', re.I)),
    ('in_domain', re.compile(r'\b(?:in[- ]domain|iid|in[- ]distribution|standard\s+split)\b', re.I)),
)
_METRIC_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ('calibration', re.compile(r'\b(?:calibration|ece|brier|nll|reliability)\b', re.I)),
    ('latency', re.compile(r'\b(?:latency|p99|runtime|inference\s+time|wall[- ]clock)\b', re.I)),
    ('throughput', re.compile(r'\b(?:throughput|tokens?\s*/\s*s|fps)\b', re.I)),
    ('memory', re.compile(r'\b(?:memory|vram|peak\s+ram|kv[- ]cache)\b', re.I)),
    ('robustness', re.compile(r'\b(?:robustness|worst[- ]group|adversarial\s+acc\w*)\b', re.I)),
    ('construct_validity', re.compile(r'\b(?:construct\s+validity|shortcut|contamination|leakage)\b', re.I)),
    ('accuracy', re.compile(r'\b(?:accuracy|acc|top-1|exact\s+match)\b', re.I)),
    ('f1', re.compile(r'\b(?:macro[- ]?f1|micro[- ]?f1|f1)\b', re.I)),
    ('ndcg', re.compile(r'\b(?:ndcg|mrr|recall@\d+|map)\b', re.I)),
    ('perplexity', re.compile(r'\b(?:perplexity|ppl)\b', re.I)),
    ('flops', re.compile(r'\b(?:flops|macs|compute)\b', re.I)),
)
_BOTTLENECK_CUE_RE = re.compile(
    r'\b(?:bottleneck|limitation|at\s+the\s+cost\s+of|trade-?off|overhead|degrades?|fails?|'
    r'quadratic|o\(n\^2\)|variance|collapse|saturation|miscalibrat\w*)\b',
    re.I,
)
_ISOMORPHIC_DISCIPLINES: tuple[dict[str, Any], ...] = (
    {
        'discipline': 'Control Theory',
        'cues': frozenset({'stability', 'feedback', 'drift', 'oscillation', 'adaptive', 'step', 'closed', 'loop', 'latency', 'divergence'}),
        'mechanism_family': 'Lyapunov stability, gain scheduling, PID feedback, or H-infinity robust control',
        'transfer_hypothesis': 'Treat training/decoding or adaptive routing instability as a closed-loop feedback system with bounded gain constraints.',
        'kill_suffix': 'Lyapunov stability OR gain scheduling OR control theory',
    },
    {
        'discipline': 'Causal Inference',
        'cues': frozenset({'shift', 'ood', 'confounding', 'spurious', 'shortcut', 'selection', 'transport', 'domain', 'bias', 'leakage'}),
        'mechanism_family': 'Transportability, do-calculus, invariant causal prediction, or sensitivity bounds',
        'transfer_hypothesis': 'Model distribution shift and benchmark shortcuts via causal transportability bounds and invariant predictors.',
        'kill_suffix': 'invariant causal prediction OR transportability OR do-calculus',
    },
    {
        'discipline': 'Information Theory',
        'cues': frozenset({'calibration', 'entropy', 'compression', 'bottleneck', 'uncertainty', 'fusion', 'ece', 'quantized', 'bit'}),
        'mechanism_family': 'Proper scoring rules, rate-distortion bounds, information bottleneck, or KL regularization',
        'transfer_hypothesis': 'Bound confidence calibration and representation compression via rate-distortion and strictly proper scoring rules.',
        'kill_suffix': 'rate-distortion OR proper scoring rule OR information bottleneck',
    },
    {
        'discipline': 'Optimization',
        'cues': frozenset({'variance', 'convergence', 'minimax', 'adversarial', 'tail', 'saddle', 'noisy', 'worst', 'robustness'}),
        'mechanism_family': 'Distributionally robust optimization (DRO), mirror descent, or variance-reduced proximal methods',
        'transfer_hypothesis': 'Replace average-case empirical risk with f-divergence or Wasserstein DRO over worst-case tail slices.',
        'kill_suffix': 'distributionally robust optimization OR mirror descent',
    },
    {
        'discipline': 'Statistical Physics',
        'cues': frozenset({'scaling', 'collapse', 'phase', 'depth', 'landscape', 'critical', 'emergent', 'temperature', 'oversmoothing'}),
        'mechanism_family': 'Mean-field phase transitions, spin-glass energy landscapes, or renormalization group flow',
        'transfer_hypothesis': 'Analyze depth/scale representation collapse as a critical phase boundary amenable to mean-field variance preservation.',
        'kill_suffix': 'mean-field phase transition OR renormalization group',
    },
    {
        'discipline': 'Signal Processing',
        'cues': frozenset({'spectral', 'degree', 'graph', 'filter', 'aliasing', 'denoising', 'frequency', 'heterophil', 'smoothing'}),
        'mechanism_family': 'Graph spectral filter banks, compressed sensing, or Nyquist anti-aliasing',
        'transfer_hypothesis': 'Treat feature oversmoothing or degree-shift degradation as spectral band-pass filtering and anti-aliasing.',
        'kill_suffix': 'spectral filter bank OR compressed sensing OR anti-aliasing',
    },
)
_PERSPECTIVES = (
    (
        'P1',
        'Problem Framing & Mechanistic Validity',
        'Formal assumptions, target mechanism, and whether existing methods already resolve the core question.',
        'What assumptions and mechanisms govern {facet} in the current corpus?',
    ),
    (
        'P2',
        'Empirical Robustness, OOD Shift & Calibration',
        'Out-of-distribution generalization, calibration error, failure modes, and adversarial stress tests.',
        'What empirical evidence covers {facet} under shift, calibration, or failure modes?',
    ),
    (
        'P3',
        'Baselines, Engineering Parity & Parsimony',
        'Tuned simple baselines, HPO/compute parity, split integrity, and simplest sufficient alternatives.',
        'Do existing studies on {facet} match baseline tuning, splits, and minimal complexity?',
    ),
    (
        'P4',
        'Cross-Setting Analogy & Closure Synthesis',
        'Adjacent-field precedents, alternate terminology, and direct closure studies.',
        'Which cross-setting analogies or closure papers already address {facet}?',
    ),
)


def _auto_artifact_path(prefix: str) -> Path:
    art_dir = Path(tempfile.gettempdir()) / 'research_scientist_artifacts'
    art_dir.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(prefix=f'{prefix}_', suffix='.json', dir=str(art_dir))
    import os
    os.close(fd)
    return Path(raw_path)


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r'[a-z0-9]{2,}', text.casefold()) if t not in _STOPWORDS]


def _extract_facets(topic: str) -> list[str]:
    parts = [p.strip() for p in re.split(r'\s*(?:&|,|\bvs\.?\b|\bversus\b|\band\b|\bunder\b)\s*', topic, flags=re.I) if p.strip()]
    facets: list[str] = []
    seen: set[str] = set()
    for part in parts:
        toks = _tokens(part)
        if not toks:
            continue
        label = ' '.join(toks[:4])
        if label not in seen:
            seen.add(label)
            facets.append(label)
    if not facets:
        facets.append(' '.join(_tokens(topic)[:4]) or topic.strip().casefold())
    return facets


def _reject_nonfinite(token: str) -> Any:
    raise ValueError(f'Non-finite JSON constant not allowed: {token}')


def _coerce_year(year_val: Any, published_date: str | None = None) -> int | None:
    if isinstance(year_val, bool):
        raise ValueError(f'year must be an integer, got bool ({year_val!r})')
    if isinstance(year_val, int):
        return year_val
    if isinstance(year_val, str):
        s = year_val.strip()
        if s:
            if re.fullmatch(r'-?\d+', s):
                return int(s)
            raise ValueError(f'Invalid year: {year_val!r}')
    if published_date and isinstance(published_date, str):
        p = published_date.strip()
        if len(p) >= 4 and p[:4].isdigit():
            return int(p[:4])
    return None


def _as_str_list(val: Any) -> list[str]:
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val, str) and val.strip():
        return [val.strip()]
    return []


def _load_corpus(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding='utf-8'), parse_constant=_reject_nonfinite)
    items = raw.get('papers', []) if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError('corpus JSON must be a list or {"papers": [...]}')
    normalized: list[dict[str, Any]] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        sid = str(item.get('id') or item.get('paper_id') or item.get('source_id') or f'DOC-{idx + 1}')
        title = str(item.get('title') or '').strip()
        abstract = str(item.get('abstract') or '').strip()
        body = str(item.get('text') or item.get('full_text_excerpt') or '').strip()
        combined = ' '.join(x for x in (title, abstract, body) if x)
        pub_raw = item.get('published_date') if item.get('published_date') is not None else item.get('date')
        pub_date = str(pub_raw).strip() if isinstance(pub_raw, str) and pub_raw.strip() else None
        year = _coerce_year(item.get('year'), pub_date)
        normalized.append({
            'source_id': sid,
            'url': str(item.get('url') or item.get('doi') or sid),
            'title': title,
            'year': year,
            'family': str(item.get('family') or 'unspecified'),
            'text': combined,
            'snippet': (body or abstract or title)[:240],
            'abstract': abstract,
            'published_date': pub_date,
            'methods': _as_str_list(item.get('methods') or item.get('method')),
            'settings': _as_str_list(item.get('settings') or item.get('setting')),
            'metrics': _as_str_list(item.get('metrics') or item.get('metric')),
            'regimes': _as_str_list(item.get('regimes') or item.get('regime')),
            'assumptions': _as_str_list(item.get('assumptions')),
            'findings': item.get('findings') if isinstance(item.get('findings'), list) else [],
            'outcomes': item.get('outcomes') if isinstance(item.get('outcomes'), list) else [],
            'bottleneck': str(item.get('bottleneck') or '').strip(),
            'tradeoff': str(item.get('tradeoff') or '').strip(),
            'limitation': str(item.get('limitation') or '').strip(),
            'generation': item.get('generation'),
            'parent_ids': _as_str_list(item.get('parent_ids')),
            'evaluation_cells': item.get('evaluation_cells') if isinstance(item.get('evaluation_cells'), list) else [],
            'doi': str(item.get('doi') or '').strip(),
            'openalex_id': str(item.get('openalex_id') or '').strip(),
        })
    return normalized


def _load_failure_cases(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding='utf-8'), parse_constant=_reject_nonfinite)
    items = raw.get('failure_cases', []) if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError('failure_cases JSON must be a list or {"failure_cases": [...]}')
    return [x for x in items if isinstance(x, dict)]


def _positive_text(text: str) -> str:
    return _NEGATION_RE.sub(' ', text)


def _match_papers(query_terms: list[str], corpus: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not query_terms:
        return []
    hits: list[tuple[int, dict[str, Any]]] = []
    qset = set(query_terms)
    for doc in corpus:
        pos_tokens = set(_tokens(_positive_text(doc['text'])))
        overlap = len(qset & pos_tokens)
        if overlap > 0:
            hits.append((overlap, doc))
    hits.sort(key=lambda pair: (-pair[0], pair[1]['source_id']))
    return [doc for _, doc in hits]


def _extract_regimes(text: str, explicit: list[str] | None = None) -> list[str]:
    found: list[str] = []
    for item in explicit or []:
        norm = re.sub(r'[^a-z0-9]+', '_', item.casefold()).strip('_')
        if norm and norm not in found:
            found.append(norm)
    for name, pat in _REGIME_PATTERNS:
        if pat.search(text) and name not in found:
            found.append(name)
    return found


def _extract_metrics(text: str, explicit: list[str] | None = None) -> list[str]:
    found: list[str] = []
    for item in explicit or []:
        norm = re.sub(r'[^a-z0-9]+', '_', item.casefold()).strip('_')
        if norm and norm not in found:
            found.append(norm)
    for name, pat in _METRIC_PATTERNS:
        if pat.search(text) and name not in found:
            found.append(name)
    return found


def _sentence_polarity(sentence: str, explicit_pol: str = '') -> str | None:
    pol_low = explicit_pol.strip().casefold()
    if pol_low in {'positive', 'pos', 'gain', 'improves', 'improved'}:
        return 'positive'
    if pol_low in {'negative', 'neg', 'degrades', 'fails', 'failed', 'loss'}:
        return 'negative'
    if _NEG_FINDING_RE.search(sentence):
        return 'negative'
    # Only count positive finding cues on positive_text (un-negated)
    pos_only = _positive_text(sentence)
    if _POS_FINDING_RE.search(pos_only):
        return 'positive'
    return None


def _build_contradiction_matrix(corpus: list[dict[str, Any]]) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for doc in corpus:
        sid = doc['source_id']
        doc_regs = _extract_regimes(doc.get('text', ''), doc.get('regimes'))
        doc_mets = _extract_metrics(doc.get('text', ''), doc.get('metrics'))
        doc_meths = [m.casefold() for m in doc.get('methods', [])]
        entries: list[tuple[str, str, str, str]] = []
        for raw_f in (doc.get('findings') or []) + (doc.get('outcomes') or []):
            if isinstance(raw_f, dict):
                txt = str(raw_f.get('finding') or raw_f.get('outcome') or raw_f.get('text') or raw_f.get('claim') or '').strip()
                if txt:
                    entries.append((
                        txt,
                        str(raw_f.get('polarity') or ''),
                        str(raw_f.get('regime') or raw_f.get('setting') or ''),
                        str(raw_f.get('metric') or ''),
                    ))
            elif isinstance(raw_f, str) and raw_f.strip():
                entries.append((raw_f.strip(), '', '', ''))
        if not entries and doc.get('text'):
            for sent in _SENTENCE_SPLIT_RE.split(doc['text']):
                s = sent.strip()
                if len(s) >= 10:
                    entries.append((s, '', '', ''))
        for sent, exp_pol, exp_reg, exp_met in entries:
            pol = _sentence_polarity(sent, exp_pol)
            if pol is None:
                continue
            regs = _extract_regimes(sent, ([exp_reg] if exp_reg else []) + doc_regs)
            mets = _extract_metrics(sent, ([exp_met] if exp_met else []) + doc_mets)
            reg = regs[0] if regs else 'unspecified'
            met = mets[0] if mets else 'general_performance'
            toks = {t for t in _tokens(sent + ' ' + doc.get('title', '') + ' ' + ' '.join(doc_meths)) if t not in _MINING_STOPWORDS}
            claims.append({
                'source_id': sid,
                'polarity': pol,
                'regime': reg,
                'metric': met,
                'tokens': toks,
                'methods': set(doc_meths),
                'sentence': sent[:200],
            })
    matrix: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str, str, str]] = set()
    for i in range(len(claims)):
        a = claims[i]
        for j in range(i + 1, len(claims)):
            b = claims[j]
            if a['source_id'] == b['source_id'] or a['polarity'] == b['polarity']:
                continue
            first, second = (a, b) if a['source_id'] < b['source_id'] else (b, a)
            shared = sorted(first['tokens'] & second['tokens'])
            same_metric = first['metric'] == second['metric'] and first['metric'] != 'general_performance'
            shared_method = bool(first['methods'] & second['methods'])
            if len(shared) >= 2 or ((same_metric or shared_method) and len(shared) >= 1):
                met = first['metric'] if first['metric'] == second['metric'] else f"{first['metric']}/{second['metric']}"
                key = (first['source_id'], second['source_id'], met, f"{first['regime']}:{second['regime']}")
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)
                matrix.append({
                    'pair_id': f'CM-{len(matrix) + 1}',
                    'paper_a': first['source_id'],
                    'paper_b': second['source_id'],
                    'shared_terms': shared[:8],
                    'metric_or_construct': met,
                    'regime_a': first['regime'],
                    'regime_b': second['regime'],
                    'polarity_a': first['polarity'],
                    'polarity_b': second['polarity'],
                    'conflict_type': 'cross_regime_conflict' if first['regime'] != second['regime'] else 'same_regime_conflict',
                    'evidence_a': first['sentence'],
                    'evidence_b': second['sentence'],
                    'status': 'lead',
                })
    return matrix[:30]


def _build_coverage_hole_matrix(
    topic: str,
    facets: list[str],
    corpus: list[dict[str, Any]],
    target_regime: str | None = None,
) -> dict[str, Any]:
    _METHOD_CUES = ('rrf', 'gcn', 'lora', 'attention', 'rag', 'quantization', 'kd', 'distillation', 'cot', 'dpo', 'ppo', 'transformer', 'mamba')
    _SETTING_CUES = ('beir', 'cora', 'citeseer', 'imagenet', 'mmlu', 'gsm8k', 'retrieval', 'classification', 'generation', 'qa')
    _STRESS_REGIMES = frozenset({
        'ood_shift', 'adversarial', 'low_resource', 'long_context', 'noisy',
        'quantized', 'deployment_constrained', 'high_degree', 'zero_shot', 'few_shot',
    })
    _RELIABILITY_METRICS = frozenset({'calibration', 'ece', 'latency', 'p99', 'vram', 'memory', 'robustness', 'construct_validity'})

    all_methods: list[str] = []
    all_settings: list[str] = []
    all_metrics: list[str] = []
    all_regimes: list[str] = []
    observed_map: dict[tuple[str, str, str, str], list[str]] = {}
    negated_cues: set[str] = set()

    def _add_uniq(lst: list[str], val: str) -> None:
        v = re.sub(r'[^a-z0-9_]+', '_', val.casefold()).strip('_')
        if v and v not in lst:
            lst.append(v)

    for doc in corpus:
        sid = doc['source_id']
        raw_text = doc.get('text', '')
        pos_text = _positive_text(raw_text)
        for m_neg in _NEGATION_RE.finditer(raw_text):
            span_end = min(len(raw_text), m_neg.end() + 48)
            neg_slice = raw_text[m_neg.start():span_end]
            for met in _extract_metrics(neg_slice):
                negated_cues.add(met)
            for reg in _extract_regimes(neg_slice):
                negated_cues.add(reg)

        doc_methods = [m.casefold() for m in doc.get('methods', [])]
        for mc in _METHOD_CUES:
            if re.search(rf'\b{re.escape(mc)}\b', pos_text, re.I) and mc not in doc_methods:
                doc_methods.append(mc)
        if not doc_methods and facets:
            doc_methods = [re.sub(r'[^a-z0-9]+', '_', facets[0].casefold()).strip('_') or 'baseline_method']

        doc_settings = [s.casefold() for s in doc.get('settings', [])]
        for sc in _SETTING_CUES:
            if re.search(rf'\b{re.escape(sc)}\b', pos_text, re.I) and sc not in doc_settings:
                doc_settings.append(sc)
        if not doc_settings:
            doc_settings = ['benchmark_unspecified']

        doc_metrics = _extract_metrics(pos_text, doc.get('metrics')) or ['accuracy']
        doc_regimes = _extract_regimes(pos_text, doc.get('regimes')) or ['in_domain']

        for m in doc_methods:
            _add_uniq(all_methods, m)
        for s in doc_settings:
            _add_uniq(all_settings, s)
        for k in doc_metrics:
            _add_uniq(all_metrics, k)
        for r in doc_regimes:
            _add_uniq(all_regimes, r)

        if doc.get('evaluation_cells'):
            for cell in doc['evaluation_cells']:
                if not isinstance(cell, dict):
                    continue
                cm = str(cell.get('method') or doc_methods[0])
                cs = str(cell.get('setting') or doc_settings[0])
                ck = str(cell.get('metric') or doc_metrics[0])
                cr = str(cell.get('regime') or doc_regimes[0])
                for lst, v in ((all_methods, cm), (all_settings, cs), (all_metrics, ck), (all_regimes, cr)):
                    _add_uniq(lst, v)
                key = (
                    re.sub(r'[^a-z0-9_]+', '_', cm.casefold()).strip('_'),
                    re.sub(r'[^a-z0-9_]+', '_', cs.casefold()).strip('_'),
                    re.sub(r'[^a-z0-9_]+', '_', ck.casefold()).strip('_'),
                    re.sub(r'[^a-z0-9_]+', '_', cr.casefold()).strip('_'),
                )
                observed_map.setdefault(key, [])
                if sid not in observed_map[key]:
                    observed_map[key].append(sid)
        else:
            for cm in doc_methods:
                for cs in doc_settings:
                    for ck in doc_metrics:
                        for cr in doc_regimes:
                            key = (
                                re.sub(r'[^a-z0-9_]+', '_', cm.casefold()).strip('_'),
                                re.sub(r'[^a-z0-9_]+', '_', cs.casefold()).strip('_'),
                                re.sub(r'[^a-z0-9_]+', '_', ck.casefold()).strip('_'),
                                re.sub(r'[^a-z0-9_]+', '_', cr.casefold()).strip('_'),
                            )
                            observed_map.setdefault(key, [])
                            if sid not in observed_map[key]:
                                observed_map[key].append(sid)

    topic_blob = f'{topic} {target_regime or ""}'
    priority_regimes: list[str] = []
    priority_metrics: list[str] = []
    if target_regime:
        _add_uniq(priority_regimes, target_regime)
    for tr in _extract_regimes(topic_blob):
        _add_uniq(priority_regimes, tr)
    for tk in _extract_metrics(topic_blob):
        _add_uniq(priority_metrics, tk)
    for nc in sorted(negated_cues):
        if any(nc == pat_name for pat_name, _ in _METRIC_PATTERNS):
            _add_uniq(priority_metrics, nc)
        else:
            _add_uniq(priority_regimes, nc)

    for r in all_regimes:
        _add_uniq(priority_regimes, r)
    all_regimes = priority_regimes

    for k in all_metrics:
        _add_uniq(priority_metrics, k)
    all_metrics = priority_metrics

    observed_cells = [
        {'method': m, 'setting': s, 'metric': k, 'regime': r, 'source_ids': sids}
        for (m, s, k, r), sids in sorted(observed_map.items())
    ]

    observed_ms = sorted({(m, s) for (m, s, _, _) in observed_map})
    observed_any_s = {(m, k, r) for (m, _, k, r) in observed_map}
    uncovered_cells: list[dict[str, Any]] = []
    genuine_count = 0
    reskin_count = 0
    target_norm = re.sub(r'[^a-z0-9_]+', '_', (target_regime or '').casefold()).strip('_')

    for m, s in observed_ms[:6]:
        for k in all_metrics[:6]:
            for r in all_regimes[:6]:
                if (m, s, k, r) in observed_map:
                    continue
                is_stress = r in _STRESS_REGIMES or (target_norm and r == target_norm)
                is_rel_met = k in _RELIABILITY_METRICS
                is_negated = k in negated_cues or r in negated_cues
                if (m, k, r) in observed_any_s and r in {'in_domain', 'unspecified'} and not is_rel_met and not is_negated:
                    hole_type = 'trivial_reskin_risk'
                    reskin_count += 1
                    reason = f'Already observed for {m} on another setting under {r}; swapping dataset alone risks trivial reskinning.'
                elif is_stress or is_rel_met or is_negated:
                    hole_type = 'genuine_coverage_hole'
                    genuine_count += 1
                    reason = f'Uncovered deployment/reliability cell ({k} under {r}) supported by topic or negated corpus gaps.'
                else:
                    hole_type = 'trivial_reskin_risk'
                    reskin_count += 1
                    reason = f'Uncovered cell ({s}, {k}, {r}) lacks stress-regime or reliability-metric motivation.'
                if len(uncovered_cells) < 30:
                    uncovered_cells.append({
                        'method': m,
                        'setting': s,
                        'metric': k,
                        'regime': r,
                        'hole_type': hole_type,
                        'reason': reason,
                        'status': 'lead',
                    })

    return {
        'axes': {
            'methods': all_methods,
            'settings': all_settings,
            'metrics': all_metrics,
            'regimes': all_regimes,
        },
        'observed_cells': observed_cells[:40],
        'uncovered_cells': uncovered_cells,
        'genuine_holes_count': genuine_count,
        'trivial_reskin_count': reskin_count,
    }


def _build_assumption_violations(
    topic: str,
    corpus: list[dict[str, Any]],
    target_regime: str | None = None,
) -> list[dict[str, Any]]:
    target_blob = f'{topic} {target_regime or ""}'
    corpus_regimes = set(_extract_regimes(target_blob))
    for doc in corpus:
        corpus_regimes.update(_extract_regimes(doc.get('text', ''), doc.get('regimes')))
    corpus_blob = ' '.join(doc.get('text', '') for doc in corpus)

    violations: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for doc in corpus:
        sid = doc['source_id']
        txt = doc.get('text', '')
        candidates: list[str] = list(doc.get('assumptions', []))
        for m in _ASSUMPTION_RE.finditer(txt):
            frag = m.group(1).strip()
            if frag and frag not in candidates:
                candidates.append(frag)
        for label, pat, bad_regs, mech in _CANONICAL_ASSUMPTIONS:
            if pat.search(txt):
                violating = [r for r in bad_regs if r in corpus_regimes or re.search(rf'\b{re.escape(r)}\b', target_blob + ' ' + corpus_blob, re.I)]
                if violating:
                    key = (sid, label)
                    if key not in seen:
                        seen.add(key)
                        contra = [
                            d['source_id'] for d in corpus
                            if d['source_id'] != sid and (set(_extract_regimes(d.get('text', ''), d.get('regimes'))) & set(bad_regs) or re.search(r'\b(?:violat\w*|breaks?\s+under|fails?\s+under)\b', d.get('text', ''), re.I))
                        ]
                        violations.append({
                            'violation_id': f'AV-{len(violations) + 1}',
                            'source_id': sid,
                            'assumption': label,
                            'target_or_violating_regime': violating[0],
                            'violation_mechanism': mech,
                            'evidence_snippet': txt[:180],
                            'contradicting_source_ids': contra[:5],
                            'status': 'lead',
                        })
        for cand_a in candidates:
            # Check explicit assumption string if not already covered
            a_low = cand_a.casefold()
            matched_viol = [r for r in corpus_regimes if r != 'in_domain']
            if any(k in a_low for k in ('iid', 'stationary', 'clean', 'unbounded', 'offline', 'oracle', 'homogeneous', 'calibrat')):
                continue
            if matched_viol and (target_regime or re.search(r'\b(?:violat\w*|breaks?\s+under|fails?\s+under)\b', corpus_blob, re.I)):
                key = (sid, cand_a[:80])
                if key not in seen:
                    seen.add(key)
                    violations.append({
                        'violation_id': f'AV-{len(violations) + 1}',
                        'source_id': sid,
                        'assumption': cand_a[:140],
                        'target_or_violating_regime': target_regime or matched_viol[0],
                        'violation_mechanism': f'Explicit paper assumption "{cand_a[:80]}" may not hold under {target_regime or matched_viol[0]}.',
                        'evidence_snippet': cand_a[:180],
                        'contradicting_source_ids': [],
                        'status': 'lead',
                    })
    return violations[:25]


def _extract_cue_sentence(doc: dict[str, Any], primary_field: str) -> str:
    if doc.get(primary_field):
        return str(doc[primary_field])[:160]
    if doc.get('limitation') and primary_field == 'bottleneck':
        return str(doc['limitation'])[:160]
    for sent in _SENTENCE_SPLIT_RE.split(doc.get('text', '')):
        if _BOTTLENECK_CUE_RE.search(sent):
            return sent.strip()[:160]
    return ''


def _build_research_trajectory(corpus: list[dict[str, Any]]) -> dict[str, Any]:
    dated: list[dict[str, Any]] = []
    missing_year_ids: list[str] = []
    for doc in corpus:
        yr = _coerce_year(doc.get('year'), doc.get('published_date'))
        if yr is None:
            missing_year_ids.append(doc['source_id'])
        else:
            dated.append({**doc, 'year': yr})

    if not dated:
        return {
            'generations': [],
            'edges': [],
            'open_root_limits': [],
            'missing_year_source_ids': missing_year_ids,
            'evolution_summary': 'No dated corpus entries; chronological trajectory unavailable.',
        }

    dated.sort(key=lambda d: (d['year'], str(d.get('generation') or ''), d['source_id']))
    has_explicit_gen = any(d.get('generation') not in (None, '') for d in dated)
    groups: dict[str, list[dict[str, Any]]] = {}
    if has_explicit_gen:
        for d in dated:
            gkey = str(d.get('generation') or f"Y{d['year']}")
            groups.setdefault(gkey, []).append(d)
        ordered_keys = sorted(groups.keys(), key=lambda k: (min(x['year'] for x in groups[k]), k))
    else:
        distinct_years = sorted({d['year'] for d in dated})
        year_to_gen = {yr: f'Gen{idx + 1}' for idx, yr in enumerate(distinct_years)}
        for d in dated:
            groups.setdefault(year_to_gen[d['year']], []).append(d)
        ordered_keys = [f'Gen{idx + 1}' for idx in range(len(distinct_years))]

    generations: list[dict[str, Any]] = []
    for gkey in ordered_keys:
        docs_in_gen = groups[gkey]
        bn = next((_extract_cue_sentence(d, 'bottleneck') for d in docs_in_gen if _extract_cue_sentence(d, 'bottleneck')), '')
        tr = next((_extract_cue_sentence(d, 'tradeoff') for d in docs_in_gen if _extract_cue_sentence(d, 'tradeoff')), '')
        generations.append({
            'generation': gkey,
            'year_range': [min(d['year'] for d in docs_in_gen), max(d['year'] for d in docs_in_gen)],
            'paper_ids': [d['source_id'] for d in docs_in_gen],
            'titles': [d['title'] for d in docs_in_gen if d['title']][:4],
            'observed_bottlenecks': [x for x in (_extract_cue_sentence(d, 'bottleneck') for d in docs_in_gen) if x][:4],
            'observed_tradeoffs': [x for x in (_extract_cue_sentence(d, 'tradeoff') for d in docs_in_gen) if x][:4],
            'primary_bottleneck': bn or tr or 'No explicit bottleneck cue extracted.',
            'primary_tradeoff': tr or '',
        })

    edges: list[dict[str, Any]] = []
    for idx in range(len(generations) - 1):
        cur_g = generations[idx]
        nxt_g = generations[idx + 1]
        edges.append({
            'from_gen': cur_g['generation'],
            'to_gen': nxt_g['generation'],
            'bottleneck_addressed': cur_g['primary_bottleneck'],
            'new_tradeoff': nxt_g['primary_tradeoff'] or nxt_g['primary_bottleneck'],
        })

    latest = generations[-1]
    open_root_limits: list[dict[str, Any]] = []
    for item in (latest['observed_tradeoffs'] or latest['observed_bottlenecks'] or [latest['primary_bottleneck']]):
        if item:
            open_root_limits.append({
                'generation': latest['generation'],
                'limit': item,
                'status': 'lead',
            })

    parts: list[str] = []
    for idx, gen in enumerate(generations):
        yr_lbl = str(gen['year_range'][0]) if gen['year_range'][0] == gen['year_range'][1] else f"{gen['year_range'][0]}-{gen['year_range'][1]}"
        parts.append(f"{gen['generation']} ({yr_lbl})")
        if idx < len(edges):
            parts.append(f"bottleneck: {edges[idx]['bottleneck_addressed'][:60]}")
        elif gen['primary_tradeoff']:
            parts.append(f"tradeoff: {gen['primary_tradeoff'][:60]}")
    if open_root_limits:
        parts.append(f"open_root_limit: {open_root_limits[0]['limit'][:70]}")

    return {
        'generations': generations,
        'edges': edges,
        'open_root_limits': open_root_limits,
        'missing_year_source_ids': missing_year_ids,
        'evolution_summary': ' -> '.join(parts),
    }


def _build_isomorphic_transfer_leads(
    topic: str,
    facets: list[str],
    corpus: list[dict[str, Any]],
    bottlenecks: list[str] | None = None,
    assumption_violations: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    blob_parts = [topic] + list(facets) + list(bottlenecks or [])
    for av in assumption_violations or []:
        blob_parts.append(str(av.get('assumption') or ''))
        blob_parts.append(str(av.get('target_or_violating_regime') or ''))
    query_toks = set(_tokens(' '.join(blob_parts)))
    analogy_ids = [
        d['source_id'] for d in corpus
        if d.get('family') == 'cross_setting_analogy' or ({'analogy', 'cross', 'adjacent'} & set(_tokens(d.get('text', ''))))
    ]
    facet_label = facets[0] if facets else topic[:40]
    scored: list[tuple[int, dict[str, Any]]] = []
    for spec in _ISOMORPHIC_DISCIPLINES:
        hits = sorted(query_toks & spec['cues'])
        if hits:
            scored.append((len(hits), {
                'discipline': spec['discipline'],
                'matched_cues': hits,
                'mechanism_family': spec['mechanism_family'],
                'transfer_hypothesis': spec['transfer_hypothesis'],
                'corpus_analogy_source_ids': analogy_ids[:5],
                'suggested_kill_queries': [
                    f"{facet_label} {spec['kill_suffix']}",
                    f"{' '.join(hits[:2])} {spec['discipline'].casefold()} equivalence",
                ],
                'evidence_level': 'lead',
                'requires_primary_verification': True,
                'supporting_evidence': [],
                'status': 'lead',
            }))
    scored.sort(key=lambda pair: (-pair[0], pair[1]['discipline']))
    leads = [item for _, item in scored[:4]]
    if not leads:
        leads.append({
            'discipline': 'Adjacent Literature Scan',
            'matched_cues': [],
            'mechanism_family': 'Cross-discipline mechanism equivalence check',
            'transfer_hypothesis': f'Check whether "{facet_label}" is already formalized under alternate terminology in adjacent CS/math fields.',
            'corpus_analogy_source_ids': analogy_ids[:5],
            'suggested_kill_queries': [f'{facet_label} equivalence OR isomorphism OR alternate terminology'],
            'evidence_level': 'lead',
            'requires_primary_verification': True,
            'supporting_evidence': [],
            'status': 'lead',
        })
    return leads


def _mine_failure_first_patterns(
    failure_cases: list[dict[str, Any]],
    corpus: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not failure_cases:
        return []
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for idx, fc in enumerate(failure_cases):
        err_type = str(fc.get('error_type') or fc.get('failure_mode') or fc.get('symptom') or f'failure_{idx + 1}').strip()
        reg_slice = str(fc.get('slice') or fc.get('regime') or 'unspecified_slice').strip()
        groups.setdefault((err_type, reg_slice), []).append(fc)

    patterns: list[dict[str, Any]] = []
    for (err_type, reg_slice), items in sorted(groups.items()):
        desc_parts = [err_type, reg_slice] + [str(it.get('description') or it.get('notes') or '') for it in items]
        q_toks = list(dict.fromkeys(_tokens(' '.join(desc_parts))))
        matched = _match_papers(q_toks, corpus)
        baselines = sorted({str(it.get('baseline') or it.get('model') or '').strip() for it in items if str(it.get('baseline') or it.get('model') or '').strip()})
        facet_lbl = ' '.join(q_toks[:4]) if q_toks else err_type.casefold()
        patterns.append({
            'pattern_id': f'FP-{len(patterns) + 1}',
            'error_type': err_type,
            'slice_or_regime': reg_slice,
            'recurrence_count': len(items),
            'affected_slices': [reg_slice],
            'affected_baselines': baselines,
            'candidate_facets': [facet_lbl] if facet_lbl else [],
            'matched_prior_art_source_ids': [d['source_id'] for d in matched[:5]],
            'suggested_kill_queries': [f'{err_type} {reg_slice} prior work OR fix'],
            'engineering_check_required': True,
            'status': 'lead',
        })
    return patterns


def explore(
    topic: str,
    corpus: list[dict[str, Any]],
    max_turns: int = 12,
    failure_cases: list[dict[str, Any]] | None = None,
    target_regime: str | None = None,
) -> dict[str, Any]:
    if not topic.strip():
        raise ValueError('topic must be non-empty')
    facets = _extract_facets(topic)
    failure_patterns = _mine_failure_first_patterns(failure_cases or [], corpus) if failure_cases else []
    for fp in failure_patterns:
        for cf in fp.get('candidate_facets', []):
            if cf and cf not in facets:
                facets.append(cf)

    perspectives: list[dict[str, Any]] = []
    qa_turns: list[dict[str, Any]] = []
    info_index: dict[str, dict[str, Any]] = {}
    outline: list[dict[str, Any]] = []
    uncovered: list[dict[str, Any]] = []
    seen_uncovered: set[str] = set()

    perspectives_by_id: dict[str, dict[str, Any]] = {}
    p_sources_map: dict[str, list[str]] = {}
    for pid, pname, pfocus, q_tmpl in _PERSPECTIVES:
        questions = [q_tmpl.format(facet=f) for f in facets[:6]]
        perspectives_by_id[pid] = {'id': pid, 'name': pname, 'focus': pfocus, 'questions': questions}
        p_sources_map[pid] = []

    schedule: list[tuple[int, int]] = []
    seen_pairs: set[tuple[int, int]] = set()
    total_pairs = len(facets) * len(_PERSPECTIVES)
    span = max(len(facets), len(_PERSPECTIVES))
    for shift in range(span):
        for step in range(span):
            pair = (step % len(facets), (step + shift) % len(_PERSPECTIVES))
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                schedule.append(pair)
            if len(schedule) >= total_pairs or len(schedule) >= max_turns:
                break
        if len(schedule) >= total_pairs or len(schedule) >= max_turns:
            break

    turn_num = 0
    for f_idx, p_idx in schedule[:max_turns]:
        facet = facets[f_idx]
        pid, pname, _, q_tmpl = _PERSPECTIVES[p_idx]
        turn_num += 1
        question = q_tmpl.format(facet=facet)
        terms = _tokens(facet)
        if pid == 'P2':
            terms = list(dict.fromkeys(terms + ['calibration', 'ood', 'shift', 'robustness', 'adversarial', 'failure']))
        elif pid == 'P3':
            terms = list(dict.fromkeys(terms + ['baseline', 'tuned', 'ablation', 'latency', 'split']))
        elif pid == 'P4':
            terms = list(dict.fromkeys(terms + ['analogy', 'cross', 'closure', 'precedent']))
        matched = _match_papers(_tokens(facet) if pid == 'P1' else terms, corpus)
        # For P2/P3/P4 require at least one topic-facet term or perspective-specific term
        if pid == 'P2':
            spec = {'calibration', 'ood', 'shift', 'robustness', 'adversarial', 'failure'}
            matched = [d for d in matched if spec & set(_tokens(_positive_text(d['text'])))]
        elif pid == 'P4':
            matched = [d for d in matched if d['family'] in {'cross_setting_analogy', 'kill_search'} or {'analogy', 'cross', 'adjacent'} & set(_tokens(d['text']))]
        matched_ids = [d['source_id'] for d in matched[:5]]
        for d in matched[:5]:
            sid = d['source_id']
            if sid not in p_sources_map[pid]:
                p_sources_map[pid].append(sid)
            entry = info_index.setdefault(sid, {
                'source_id': sid,
                'url': d.get('url') or d.get('doi') or sid,
                'title': d.get('title') or '',
                'year': d.get('year'),
                'family': d.get('family') or 'unspecified',
                'snippets': [],
                'perspectives_covered': [],
            })
            snip = d.get('snippet') or d.get('text', '')[:240]
            if snip and snip not in entry['snippets']:
                entry['snippets'].append(snip)
            if pid not in entry['perspectives_covered']:
                entry['perspectives_covered'].append(pid)
        summary = (
            f'Matched {len(matched_ids)} source(s): {", ".join(matched_ids)}.'
            if matched_ids else f'No positive corpus support found for {facet} under {pname}.'
        )
        qa_turns.append({
            'turn': turn_num,
            'perspective_id': pid,
            'perspective': pname,
            'facet': facet,
            'question': question,
            'matched_source_ids': matched_ids,
            'summary': summary,
        })

    for pid, pname, _, _ in _PERSPECTIVES:
        perspectives.append(perspectives_by_id[pid])
        p_sources = p_sources_map[pid]
        outline.append({
            'section': pname,
            'perspective_id': pid,
            'subtopics': facets,
            'coverage': 'covered' if p_sources else 'uncovered',
            'supporting_source_ids': p_sources,
        })
        if not p_sources and pname not in seen_uncovered:
            seen_uncovered.add(pname)
            uncovered.append({
                'branch': pname,
                'reason': f'Zero corpus evidence mapped to perspective {pid} ({pname}).',
                'missing_terms': facets,
            })

    # Facet-level coverage audit across positive corpus tokens
    for facet in facets:
        f_terms = _tokens(facet)
        facet_hits = []
        for doc in corpus:
            pos_toks = set(_tokens(_positive_text(doc['text'])))
            if all(t in pos_toks for t in f_terms):
                facet_hits.append(doc['source_id'])
        if not facet_hits and facet not in seen_uncovered:
            seen_uncovered.add(facet)
            uncovered.append({
                'branch': facet,
                'reason': f'Topic facet "{facet}" lacks positive evidence in corpus.',
                'missing_terms': f_terms,
            })

    # Dual-regime coverage check (same_problem + cross_setting_analogy)
    families = {d['family'] for d in corpus if d['family'] != 'unspecified'}
    if families and 'cross_setting_analogy' not in families and 'cross_setting_analogy' not in seen_uncovered:
        seen_uncovered.add('cross_setting_analogy')
        uncovered.append({
            'branch': 'cross_setting_analogy',
            'reason': 'Corpus covers only single regime without cross_setting_analogy studies.',
            'missing_terms': ['cross_setting_analogy'],
        })

    contradictions = _build_contradiction_matrix(corpus)
    coverage_holes = _build_coverage_hole_matrix(topic, facets, corpus, target_regime=target_regime)
    assumption_violations = _build_assumption_violations(topic, corpus, target_regime=target_regime)
    trajectory = _build_research_trajectory(corpus)
    bottleneck_texts = [g.get('primary_bottleneck', '') for g in trajectory.get('generations', [])]
    transfer_leads = _build_isomorphic_transfer_leads(
        topic, facets, corpus, bottlenecks=bottleneck_texts, assumption_violations=assumption_violations,
    )

    storm_state = {
        'perspectives': perspectives,
        'qa_turns': qa_turns,
        'information_table': list(info_index.values()),
        'outline': outline,
        'uncovered_branches': uncovered,
        'contradiction_matrix': contradictions,
        'coverage_hole_matrix': coverage_holes,
        'assumption_violations': assumption_violations,
        'research_trajectory': trajectory,
        'isomorphic_transfer_leads': transfer_leads,
        'failure_first_patterns': failure_patterns,
    }
    return {
        'schema': 'research_scientist_storm_v1',
        'topic': topic,
        'storm_state': storm_state,
        **storm_state,
    }


def compact_summary(report: dict[str, Any], artifact_path: Path) -> dict[str, Any]:
    state = report['storm_state']
    holes = state.get('coverage_hole_matrix') or {}
    traj = state.get('research_trajectory') or {}
    out = {
        'compact': True,
        'schema': report['schema'],
        'artifact_path': str(artifact_path),
        'topic': str(report['topic'])[:200],
        'perspectives_count': len(state['perspectives']),
        'qa_turns_count': len(state['qa_turns']),
        'information_table_count': len(state['information_table']),
        'outline_count': len(state['outline']),
        'uncovered_branches_count': len(state['uncovered_branches']),
        'contradictions_count': len(state.get('contradiction_matrix') or []),
        'genuine_coverage_holes_count': int(holes.get('genuine_holes_count') or 0),
        'trivial_reskin_count': int(holes.get('trivial_reskin_count') or 0),
        'assumption_violations_count': len(state.get('assumption_violations') or []),
        'isomorphic_transfer_leads_count': len(state.get('isomorphic_transfer_leads') or []),
        'failure_first_patterns_count': len(state.get('failure_first_patterns') or []),
        'evolution_summary': str(traj.get('evolution_summary') or '')[:180],
        'uncovered_branches': [
            {'branch': str(b['branch'])[:120], 'reason': str(b['reason'])[:120]}
            for b in state['uncovered_branches'][:5]
        ],
    }
    while len(json.dumps(out, separators=(',', ':'), ensure_ascii=False).encode('utf-8')) >= 4096 and out['uncovered_branches']:
        out['uncovered_branches'].pop()
    if len(json.dumps(out, separators=(',', ':'), ensure_ascii=False).encode('utf-8')) >= 4096:
        out['evolution_summary'] = out['evolution_summary'][:80]
    if len(json.dumps(out, separators=(',', ':'), ensure_ascii=False).encode('utf-8')) >= 4096:
        out['evolution_summary'] = ''
        out['topic'] = out['topic'][:80]
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--topic', required=True, help='Research topic or hypothesis to explore')
    parser.add_argument('--corpus', type=Path, required=True, help='Corpus JSON path (list or {"papers": [...]})')
    parser.add_argument('--failure-cases', type=Path, default=None, help='Optional failure_cases JSON path for failure-first mining')
    parser.add_argument('--target-regime', type=str, default=None, help='Optional target deployment/stress regime for coverage and assumption checks')
    parser.add_argument('--out', type=Path, default=None, help='Optional output JSON file path')
    parser.add_argument('--max-turns', type=int, default=12, help='Maximum Q&A exploration turns')
    parser.add_argument('--compact', action='store_true', help='Emit bounded <4096B stdout summary + disk artifact path')
    args = parser.parse_args()
    try:
        corpus = _load_corpus(args.corpus)
        failure_cases: list[dict[str, Any]] | None = None
        if args.failure_cases is not None:
            failure_cases = _load_failure_cases(args.failure_cases)
        else:
            raw_corpus = json.loads(args.corpus.read_text(encoding='utf-8'), parse_constant=_reject_nonfinite)
            if isinstance(raw_corpus, dict) and isinstance(raw_corpus.get('failure_cases'), list):
                failure_cases = [x for x in raw_corpus['failure_cases'] if isinstance(x, dict)]
        report = explore(
            args.topic,
            corpus,
            max_turns=max(1, args.max_turns),
            failure_cases=failure_cases,
            target_regime=args.target_regime,
        )
        out_path = args.out
        if args.compact and out_path is None:
            out_path = _auto_artifact_path('storm_explorer')
        if out_path is not None:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
        if args.compact:
            print(json.dumps(compact_summary(report, out_path), separators=(',', ':'), ensure_ascii=False))
        else:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())

