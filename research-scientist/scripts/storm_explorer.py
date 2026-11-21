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
_NEGATION_RE = re.compile(
    r'(?<![a-z0-9-])(?:no|zero|without|lack(?:s|ing)?|absent|missing|never|not\s+(?:evaluated|tested|measured|reported|studied))\s+'
    r'(?:[a-z0-9-]+\s+){0,3}',
    re.I,
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


def _load_corpus(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding='utf-8'))
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
        normalized.append({
            'source_id': sid,
            'url': str(item.get('url') or item.get('doi') or sid),
            'title': title,
            'year': item.get('year'),
            'family': str(item.get('family') or 'unspecified'),
            'text': combined,
            'snippet': (body or abstract or title)[:240],
        })
    return normalized


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


def explore(topic: str, corpus: list[dict[str, Any]], max_turns: int = 12) -> dict[str, Any]:
    if not topic.strip():
        raise ValueError('topic must be non-empty')
    facets = _extract_facets(topic)
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
                'url': d['url'],
                'title': d['title'],
                'year': d['year'],
                'family': d['family'],
                'snippets': [],
                'perspectives_covered': [],
            })
            if d['snippet'] and d['snippet'] not in entry['snippets']:
                entry['snippets'].append(d['snippet'])
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

    storm_state = {
        'perspectives': perspectives,
        'qa_turns': qa_turns,
        'information_table': list(info_index.values()),
        'outline': outline,
        'uncovered_branches': uncovered,
    }
    return {
        'schema': 'research_scientist_storm_v1',
        'topic': topic,
        'storm_state': storm_state,
        **storm_state,
    }


def compact_summary(report: dict[str, Any], artifact_path: Path) -> dict[str, Any]:
    state = report['storm_state']
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
        'uncovered_branches': [
            {'branch': str(b['branch'])[:120], 'reason': str(b['reason'])[:120]}
            for b in state['uncovered_branches'][:5]
        ],
    }
    while len(json.dumps(out, separators=(',', ':'), ensure_ascii=False).encode('utf-8')) >= 4096 and out['uncovered_branches']:
        out['uncovered_branches'].pop()
    if len(json.dumps(out, separators=(',', ':'), ensure_ascii=False).encode('utf-8')) >= 4096:
        out['topic'] = out['topic'][:80]
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--topic', required=True, help='Research topic or hypothesis to explore')
    parser.add_argument('--corpus', type=Path, required=True, help='Corpus JSON path (list or {"papers": [...]})')
    parser.add_argument('--out', type=Path, default=None, help='Optional output JSON file path')
    parser.add_argument('--max-turns', type=int, default=12, help='Maximum Q&A exploration turns')
    parser.add_argument('--compact', action='store_true', help='Emit bounded <4096B stdout summary + disk artifact path')
    args = parser.parse_args()
    try:
        corpus = _load_corpus(args.corpus)
        report = explore(args.topic, corpus, max_turns=max(1, args.max_turns))
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

