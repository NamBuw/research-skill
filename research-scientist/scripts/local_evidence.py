#!/usr/bin/env python3
"""Search local text, MinerU Content List V2, or extracted PDF blocks with chunking, BM25, MMR, and abstention gate.

Adapted / ported patterns:
- paper-qa (Apache-2.0): overlapping page-aware chunking, Shannon entropy filter (maybe_is_text),
  citation-keyed context packing, and hard ABSTAIN gate on insufficient studies/evidence.
- gpt-researcher (Apache-2.0): English plural stemming and stopword filtering for lexical BM25.
- sgha (Apache-2.0): max-ratio normalized Maximal Marginal Relevance (MMR) reranking with fallback.
- khoj (AGPL-3.0 — NOT copied): clean-room stdlib urllib.request HTTP client for optional --khoj-url.

The tool ranks extracted spans. It does not establish bibliographic identity, claim entailment, or field coverage.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import re
import sys
import tempfile
from collections import Counter
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

TOKEN = re.compile(r'[^\W_]+', re.UNICODE)
ALLOWED = {'.md', '.txt', '.json'}
ATOMIC_V2_TYPES = {'table', 'image', 'chart', 'equation', 'equation_interline', 'algorithm', 'code'}

# GPT Researcher (Apache-2.0) stopwords
_STOPWORDS = {
    'a', 'an', 'and', 'are', 'as', 'at', 'be', 'but', 'by', 'for', 'if', 'in', 'into',
    'is', 'it', 'no', 'not', 'of', 'on', 'or', 'such', 'that', 'the', 'their', 'then',
    'there', 'these', 'they', 'this', 'to', 'was', 'will', 'with',
}


def _stem(token: str) -> str:
    """Lightweight English plural stemmer (GPT Researcher Apache-2.0)."""
    if len(token) > 4 and token.endswith('ies'):
        return token[:-3] + 'y'
    if len(token) > 5 and token.endswith(('sses', 'xes', 'zes', 'ches', 'shes')):
        return token[:-2]
    if len(token) > 4 and token.endswith('s') and not token.endswith('ss'):
        return token[:-1]
    return token


def tokens(value: str, *, use_stopwords: bool = True, stem: bool = True) -> list[str]:
    """Tokenize Unicode words, retaining 1-char alphanumeric tokens (e.g. 'x')."""
    raw = [match.group().casefold() for match in TOKEN.finditer(value or '')]
    if not raw:
        return []
    filtered = [t for t in raw if not (use_stopwords and t in _STOPWORDS)]
    if not filtered:
        filtered = raw
    return [_stem(t) if stem else t for t in filtered]


def clean_invalid_unicode(text: str) -> str:
    if not isinstance(text, str):
        return ''
    return ''.join(ch for ch in text if ch != '\x00' and not (0xD800 <= ord(ch) <= 0xDFFF))


def shannon_entropy(text: str) -> float:
    s = re.sub(r'\s+', '', text or '')
    if not s:
        return 0.0
    counts = Counter(s)
    total = len(s)
    return -sum((cnt / total) * math.log2(cnt / total) for cnt in counts.values())


def maybe_is_text(text: str, thresh: float = 2.5, min_chars: int = 20) -> bool:
    """PaperQA2 Shannon entropy text gate preserving short titles/equations (< min_chars)."""
    s = re.sub(r'\s+', '', clean_invalid_unicode(text))
    if not s:
        return False
    if len(s) >= 8 and len(set(s)) <= 2:
        return False
    ent = shannon_entropy(s)
    if ent >= 8.0:
        return False
    if len(s) >= min_chars and ent <= thresh:
        return False
    return True


def _spans(value) -> str:
    if not isinstance(value, list):
        return ''
    return ''.join(
        item.get('content', '')
        for item in value
        if isinstance(item, dict) and isinstance(item.get('content'), str)
    )


def _v2_text(item: dict) -> str:
    content = item.get('content')
    kind = item.get('type')
    if isinstance(content, dict):
        if kind == 'paragraph':
            txt = _spans(content.get('paragraph_content'))
            if txt:
                return txt
        elif kind == 'title':
            txt = _spans(content.get('title_content'))
            if txt:
                return txt
        elif kind == 'page_footnote':
            txt = _spans(content.get('page_footnote_content'))
            if txt:
                return txt
        elif kind in {'equation_interline', 'equation'}:
            mc = content.get('math_content')
            if isinstance(mc, str) and mc:
                return mc
        elif kind == 'list':
            txt = ' '.join(
                _spans(x.get('item_content'))
                for x in content.get('list_items', [])
                if isinstance(x, dict)
            )
            if txt:
                return txt
        elif kind == 'table':
            parts = [_spans(content.get('table_caption')), _spans(content.get('table_footnote'))]
            html_source = content.get('html')
            if isinstance(html_source, str):
                parts.append(re.sub(r'<[^>]+>', ' ', html_source))
            txt = ' '.join(p for p in parts if p)
            if txt:
                return txt
        elif kind in {'image', 'chart'}:
            txt = ' '.join(_spans(content.get(f'{kind}_{suffix}')) for suffix in ('caption', 'footnote')).strip()
            if txt:
                return txt
        elif kind in {'algorithm', 'code'}:
            key = 'algorithm_content' if kind == 'algorithm' else 'code_content'
            txt = _spans(content.get(key))
            if txt:
                return txt
    flat = item.get('text')
    return flat if isinstance(flat, str) else ''


def _sliding_windows(text: str, chunk_chars: int, chunk_overlap: int) -> list[str]:
    if len(text) <= chunk_chars:
        return [text]
    step = max(chunk_chars - chunk_overlap, 1)
    chunks = []
    pos = 0
    while pos < len(text):
        part = text[pos:pos + chunk_chars].strip()
        if part:
            chunks.append(part)
        if pos + chunk_chars >= len(text):
            break
        pos += step
    return chunks


def _text_segments(source: Path, chunk_chars: int = 1200, chunk_overlap: int = 200):
    text = clean_invalid_unicode(source.read_text(encoding='utf-8'))
    lines = text.splitlines()
    current = []
    start = None

    def _emit(buf, lstart, lend):
        joined = '\n'.join(buf)
        for part in _sliding_windows(joined, chunk_chars, chunk_overlap):
            yield {'text': part, 'line_start': lstart, 'line_end': lend, 'kind': 'text_paragraph'}

    for n, line in enumerate(lines, start=1):
        if line.strip():
            if start is None:
                start = n
            current.append(line)
        elif current:
            yield from _emit(current, start, n - 1)
            current, start = [], None
    if current:
        yield from _emit(current, start, len(lines))


def _json_segments(source: Path, chunk_chars: int = 1200, chunk_overlap: int = 200):
    payload = json.loads(source.read_text(encoding='utf-8'))
    source_pdf_hash = None
    if isinstance(payload, dict) and payload.get('format') == 'research_scientist_pdf_blocks_v1':
        source_pdf_hash = payload.get('source_pdf_sha256')
        payload = payload.get('pages')
    if not isinstance(payload, list):
        raise ValueError('MinerU Content List V2 must be a list of pages or a flat item list')
    if payload and all(isinstance(x, dict) for x in payload):
        pages = [payload]
        flat = True
    elif all(isinstance(page, list) for page in payload):
        pages = payload
        flat = False
    else:
        raise ValueError('unsupported Content List V2 shape')

    # PaperQA2 overlapping page-aware chunking for prose items; atomic items stay untouched
    buf_text = ''
    buf_pages: list[int] = []
    buf_bbox = None
    buf_visual = False
    buf_item_idx = 0

    def _flush_prose():
        nonlocal buf_text, buf_pages, buf_bbox, buf_visual
        while buf_text:
            if len(buf_text) <= chunk_chars:
                out_txt = buf_text.strip()
                if out_txt:
                    seg = {
                        'kind': 'paragraph',
                        'item_index': buf_item_idx,
                        'text': out_txt,
                        'visual_check_required': buf_visual,
                        'page_index_zero_based': buf_pages[0],
                        'page_span': [buf_pages[0], buf_pages[-1]],
                    }
                    if buf_bbox is not None:
                        seg['bbox_as_provided'] = buf_bbox
                    if source_pdf_hash:
                        seg['source_pdf_sha256_as_declared'] = source_pdf_hash
                    yield seg
                buf_text = ''
                buf_pages = []
                buf_bbox = None
                buf_visual = False
                break
            chunk_str = buf_text[:chunk_chars].strip()
            if chunk_str:
                seg = {
                    'kind': 'paragraph',
                    'item_index': buf_item_idx,
                    'text': chunk_str,
                    'visual_check_required': buf_visual,
                    'page_index_zero_based': buf_pages[0],
                    'page_span': [buf_pages[0], buf_pages[-1]],
                }
                if buf_bbox is not None:
                    seg['bbox_as_provided'] = buf_bbox
                if source_pdf_hash:
                    seg['source_pdf_sha256_as_declared'] = source_pdf_hash
                yield seg
            keep_from = max(chunk_chars - chunk_overlap, 1)
            buf_text = buf_text[keep_from:]
            buf_pages = [buf_pages[-1]] if buf_pages else [0]

    for page_number, page in enumerate(pages, start=1):
        for item_number, item in enumerate(page, start=1):
            if not isinstance(item, dict):
                continue
            value = clean_invalid_unicode(html.unescape(_v2_text(item))).strip()
            if not value:
                continue
            kind = item.get('type')
            page_idx = item.get('page_idx') if flat else page_number - 1
            if not isinstance(page_idx, int) or page_idx < 0:
                page_idx = page_number - 1
            bbox = item.get('bbox')
            valid_bbox = bbox if isinstance(bbox, list) and len(bbox) == 4 and all(isinstance(x, (int, float)) for x in bbox) else None
            vis = (item.get('visual_check_required') is True) or (kind in ATOMIC_V2_TYPES)

            if kind in ATOMIC_V2_TYPES:
                # Flush accumulated prose before atomic item
                yield from _flush_prose()
                locator = {
                    'kind': kind,
                    'item_index': item_number - 1,
                    'text': value,
                    'visual_check_required': vis,
                    'page_index_zero_based': page_idx,
                    'page_span': [page_idx, page_idx],
                }
                if valid_bbox is not None:
                    locator['bbox_as_provided'] = valid_bbox
                if isinstance(item.get('anchor'), str):
                    locator['anchor'] = item['anchor']
                if source_pdf_hash:
                    locator['source_pdf_sha256_as_declared'] = source_pdf_hash
                yield locator
            else:
                if not buf_text:
                    buf_bbox = valid_bbox
                    buf_item_idx = item_number - 1
                else:
                    buf_text += '\n'
                buf_text += value
                if page_idx not in buf_pages:
                    buf_pages.append(page_idx)
                buf_visual = buf_visual or vis
                if len(buf_text) > chunk_chars:
                    # Emit full chunks while leaving tail overlap
                    while len(buf_text) > chunk_chars:
                        chunk_str = buf_text[:chunk_chars].strip()
                        if chunk_str:
                            seg = {
                                'kind': 'paragraph',
                                'item_index': buf_item_idx,
                                'text': chunk_str,
                                'visual_check_required': buf_visual,
                                'page_index_zero_based': buf_pages[0],
                                'page_span': [buf_pages[0], buf_pages[-1]],
                            }
                            if buf_bbox is not None:
                                seg['bbox_as_provided'] = buf_bbox
                            if source_pdf_hash:
                                seg['source_pdf_sha256_as_declared'] = source_pdf_hash
                            yield seg
                        keep_from = max(chunk_chars - chunk_overlap, 1)
                        buf_text = buf_text[keep_from:]
                        buf_pages = [page_idx]
                        buf_bbox = valid_bbox
                        buf_item_idx = item_number - 1

    if buf_text:
        yield from _flush_prose()


def _resolve_study_id(path: Path, digest: str, seg: dict, study_map: dict[str, str] | None) -> str:
    if study_map:
        for key in (str(path), path.name, path.stem):
            if key in study_map and str(study_map[key]).strip():
                return str(study_map[key]).strip()
    pdf_hash = seg.get('source_pdf_sha256_as_declared')
    if isinstance(pdf_hash, str) and len(pdf_hash) >= 12:
        return f'pdf:{pdf_hash[:12]}'
    return f'{path.stem}:{digest[:8]}'


def load(paths, *, chunk_chars: int = 1200, chunk_overlap: int = 200, study_map: dict[str, str] | None = None):
    if not isinstance(chunk_chars, int) or isinstance(chunk_chars, bool) or chunk_chars < 1:
        raise ValueError('chunk_chars must be >= 1')
    if not isinstance(chunk_overlap, int) or isinstance(chunk_overlap, bool) or chunk_overlap < 0:
        raise ValueError('chunk_overlap must be >= 0')
    sources = {}
    for raw in paths:
        path = Path(raw).expanduser().resolve()
        if path.is_dir():
            for candidate in path.rglob('*'):
                if candidate.is_file() and candidate.suffix.lower() in ALLOWED:
                    sources.setdefault(candidate, False)
        elif path.is_file():
            if path.suffix.lower() not in ALLOWED:
                raise ValueError(f'unsupported file type: {path}')
            sources[path] = True
        else:
            raise ValueError(f'path not found: {path}')
    segments = []
    skipped = []
    loaded = 0
    dropped_low_entropy = 0
    for path in sorted(sources):
        try:
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            iterator = (
                _json_segments(path, chunk_chars=chunk_chars, chunk_overlap=chunk_overlap)
                if path.suffix.lower() == '.json'
                else _text_segments(path, chunk_chars=chunk_chars, chunk_overlap=chunk_overlap)
            )
            extracted = list(iterator)
        except (ValueError, OSError, json.JSONDecodeError, UnicodeError) as exc:
            if sources[path]:
                raise
            skipped.append({'path': str(path), 'error': type(exc).__name__, 'detail': str(exc)})
            continue
        loaded += 1
        for index, segment in enumerate(extracted, start=1):
            text_val = segment['text'].strip()
            if not text_val:
                continue
            if not maybe_is_text(text_val):
                dropped_low_entropy += 1
                continue
            study_id = _resolve_study_id(path, digest, segment, study_map)
            segments.append({
                'source': str(path),
                'sha256': digest,
                'source_id': study_id,
                'segment_id': f'{digest[:12]}:{index}',
                **segment,
            })
    return segments, loaded, skipped, dropped_low_entropy


def _cosine_matrix_pure(texts: list[str]) -> list[list[float]]:
    vecs = [Counter(tokens(t)) for t in texts]
    norms = [math.sqrt(sum(v * v for v in vec.values())) for vec in vecs]
    n = len(texts)
    mat = [[0.0] * n for _ in range(n)]
    for i in range(n):
        mat[i][i] = 1.0
        for j in range(i + 1, n):
            if norms[i] == 0.0 or norms[j] == 0.0:
                sim = 0.0
            else:
                dot = sum(val * vecs[j].get(k, 0) for k, val in vecs[i].items())
                sim = dot / (norms[i] * norms[j])
            mat[i][j] = sim
            mat[j][i] = sim
    return mat


def _mmr_rerank(candidates: list[dict], texts: list[str], limit: int, mmr_lambda: float) -> tuple[list[dict], str]:
    """SGHA / PaperQA2 TF-IDF cosine MMR reranking with safe fallback."""
    if mmr_lambda >= 1.0 or len(candidates) < 2:
        for cand in candidates:
            cand['mmr_score'] = cand['score']
        return candidates[:limit], 'bm25_fallback'

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        vec = TfidfVectorizer(stop_words=None)
        tfidf = vec.fit_transform(texts)
        sim_mat = cosine_similarity(tfidf).tolist()
    except Exception:
        sim_mat = _cosine_matrix_pure(texts)

    raw_scores = [c['score'] for c in candidates]
    s_max = max(raw_scores) if raw_scores else 0.0
    if s_max > 0.0:
        norm_scores = [s / s_max for s in raw_scores]
    else:
        norm_scores = [1.0 for _ in raw_scores]

    selected_indices: list[int] = []
    remaining = list(range(len(candidates)))
    while remaining and len(selected_indices) < limit:
        best_idx = None
        best_mmr = -1e9
        for idx in remaining:
            rel = norm_scores[idx]
            max_sim = max((sim_mat[idx][s_idx] for s_idx in selected_indices), default=0.0)
            mmr_val = mmr_lambda * rel - (1.0 - mmr_lambda) * max_sim
            if mmr_val > best_mmr:
                best_mmr = mmr_val
                best_idx = idx
        assert best_idx is not None
        candidates[best_idx]['mmr_score'] = round(best_mmr, 5)
        selected_indices.append(best_idx)
        remaining.remove(best_idx)

    return [candidates[i] for i in selected_indices], 'bm25_mmr'


def search(segments, query, limit=10, *, mmr_lambda: float = 0.7):
    q = set(tokens(query))
    if not q:
        raise ValueError('query has no searchable terms')
    if not 1 <= limit <= 100:
        raise ValueError('limit must be 1..100')
    if not 0.0 <= float(mmr_lambda) <= 1.0:
        raise ValueError('mmr_lambda must be 0.0..1.0')

    terms = [Counter(tokens(s['text'])) for s in segments]
    docfreq = Counter(term for counts in terms for term in counts)
    average_length = (sum(sum(c.values()) for c in terms) / len(terms)) if terms else 1.0
    if average_length <= 0.0:
        average_length = 1.0

    ranked = []
    ranked_texts = []
    for segment, counts in zip(segments, terms):
        length = sum(counts.values())
        score = 0.0
        matched = []
        for term in q:
            frequency = counts[term]
            if frequency:
                matched.append(term)
                idf = math.log(1 + (len(segments) - docfreq[term] + 0.5) / (docfreq[term] + 0.5))
                # GPT Researcher (Apache-2.0) BM25 k1=1.5, b=0.75
                score += idf * frequency * 2.5 / (frequency + 1.5 * (0.25 + 0.75 * length / average_length))
        if score > 0.0:
            lead = {key: value for key, value in segment.items() if key != 'text'}
            lead.update({
                'score': round(score, 5),
                'matched_terms': sorted(matched),
                'excerpt': segment['text'][:700],
                'excerpt_truncated': len(segment['text']) > 700,
                'origin': 'local_corpus',
            })
            ranked.append((lead, segment['text']))

    ranked.sort(key=lambda x: (-x[0]['score'], x[0]['source'], x[0]['segment_id']))
    total_matching = len(ranked)
    fetch_k = max(limit * 3, 20)
    pool = ranked[:fetch_k]
    candidates = [p[0] for p in pool]
    pool_texts = [p[1] for p in pool]
    selected, reranker_mode = _mmr_rerank(candidates, pool_texts, limit, float(mmr_lambda))
    return selected, total_matching, reranker_mode


def query_khoj(khoj_url: str, query: str, limit: int = 10, token_env: str = 'KHOJ_API_KEY') -> tuple[list[dict], str]:
    """Clean-room stdlib HTTP adapter for Khoj GET /api/search (AGPL-3.0 code NOT copied)."""
    if not isinstance(khoj_url, str) or not khoj_url.strip():
        return [], 'not_requested'
    parsed = urlparse(khoj_url.strip())
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
        return [], 'invalid_url'
    base = khoj_url.strip().rstrip('/')
    endpoint = f'{base}/api/search?q={quote(query)}&n={limit}&t=all'
    headers = {'Accept': 'application/json', 'User-Agent': 'ResearchScientistSkill/2.6 (khoj-client)'}
    token = os.environ.get(token_env, '').strip()
    if token:
        headers['Authorization'] = f'Bearer {token}'
    try:
        with urlopen(Request(endpoint, headers=headers), timeout=10) as resp:
            payload = json.loads(resp.read(2_000_000))
    except HTTPError:
        return [], 'http_error'
    except (URLError, HTTPException, TimeoutError, OSError):
        return [], 'unavailable'
    except (json.JSONDecodeError, UnicodeDecodeError):
        return [], 'invalid_response'
    if not isinstance(payload, list):
        return [], 'invalid_response'
    normalized = []
    for idx, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            continue
        entry = str(item.get('entry') or '').strip()
        if not entry:
            continue
        corpus_id = str(item.get('corpus_id') or f'khoj-{idx}')
        normalized.append({
            'source_id': f'khoj:{corpus_id}',
            'entry': entry,
            'score': item.get('score'),
            'cross_score': item.get('cross_score'),
            'additional': item.get('additional'),
            'corpus_id': corpus_id,
            'origin': 'khoj_remote',
        })
    return normalized, 'ok'


def _citation_key(passage: dict) -> str:
    sid = passage.get('source_id', 'src')
    if passage.get('page_index_zero_based') is not None:
        return f"{sid}:p{passage['page_index_zero_based'] + 1}"
    if passage.get('line_start') is not None:
        return f"{sid}:L{passage['line_start']}-{passage.get('line_end', passage['line_start'])}"
    return sid


def run(
    paths,
    query,
    limit=10,
    *,
    chunk_chars: int = 1200,
    chunk_overlap: int = 200,
    mmr_lambda: float = 0.7,
    min_studies: int = 2,
    min_evidence: int = 2,
    study_map: dict[str, str] | None = None,
    khoj_url: str | None = None,
    khoj_token_env: str = 'KHOJ_API_KEY',
):
    segments, source_count, skipped, dropped_low_entropy = load(
        paths, chunk_chars=chunk_chars, chunk_overlap=chunk_overlap, study_map=study_map
    )
    results, matching_count, reranker_mode = search(segments, query, limit, mmr_lambda=mmr_lambda)

    khoj_results: list[dict] = []
    khoj_status = 'not_requested'
    if khoj_url:
        khoj_results, khoj_status = query_khoj(khoj_url, query, limit=limit, token_env=khoj_token_env)

    ranked_passages = []
    for item in results:
        ck = _citation_key(item)
        ranked_passages.append({
            'source_id': item.get('source_id'),
            'citation_key': ck,
            'page_idx': item.get('page_index_zero_based'),
            'page_span': item.get('page_span'),
            'line_start': item.get('line_start'),
            'line_end': item.get('line_end'),
            'quote': item.get('excerpt', ''),
            'score': item.get('score'),
            'mmr_score': item.get('mmr_score'),
            'visual_check_required': item.get('visual_check_required', False),
            'origin': item.get('origin', 'local_corpus'),
        })
    for k_item in khoj_results:
        ranked_passages.append({
            'source_id': k_item['source_id'],
            'citation_key': k_item['source_id'],
            'page_idx': None,
            'page_span': None,
            'line_start': None,
            'line_end': None,
            'quote': k_item['entry'][:700],
            'score': k_item.get('score'),
            'mmr_score': None,
            'visual_check_required': False,
            'origin': 'khoj_remote',
        })

    study_ids = sorted({p['source_id'] for p in ranked_passages if p.get('source_id')})
    distinct_studies = len(study_ids)
    if distinct_studies >= min_studies and len(ranked_passages) >= min_evidence:
        gate_status = 'ANSWERABLE'
        abstain_reason = None
    else:
        gate_status = 'ABSTAIN'
        reasons = []
        if len(ranked_passages) < min_evidence:
            reasons.append(f'evidence_count ({len(ranked_passages)}) < min_evidence ({min_evidence})')
        if distinct_studies < min_studies:
            reasons.append(f'distinct_studies ({distinct_studies}) < min_studies ({min_studies})')
        abstain_reason = '; '.join(reasons)

    packed_lines = []
    total_len = 0
    for p in ranked_passages:
        line = f"[{p['citation_key']}] {p['quote']}"
        if total_len + len(line) + 1 > 8000:
            break
        packed_lines.append(line)
        total_len += len(line) + 1
    context_packed = '\n'.join(packed_lines)

    return {
        'query': query,
        'question': query,
        'source_files': source_count,
        'skipped_files': skipped,
        'segments_indexed': len(segments),
        'matching_segments': matching_count,
        'returned': len(results),
        'results': results,
        'ranked_passages': ranked_passages,
        'distinct_studies': distinct_studies,
        'study_ids': study_ids,
        'gate_status': gate_status,
        'abstain_reason': abstain_reason,
        'context_packed': context_packed,
        'reranker_mode': reranker_mode,
        'dropped_low_entropy_chunks': dropped_low_entropy,
        'khoj_status': khoj_status,
        'khoj_results': khoj_results,
        'warning': (
            'Lexical matches are passage leads only. Verify source identity, original PDF layout, '
            'and claim entailment manually; no full-text or field coverage is implied.'
        ),
    }


def _auto_artifact_path(prefix: str) -> Path:
    art_dir = Path(tempfile.gettempdir()) / 'research_scientist_artifacts'
    art_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f'{prefix}_', suffix='.json', dir=str(art_dir))
    os.close(fd)
    return Path(tmp_name).resolve()


def _compact_evidence_summary(report: dict, artifact_path: Path) -> dict:
    top_passages = []
    for p in report.get('ranked_passages', [])[:10]:
        q_txt = re.sub(r'\s+', ' ', str(p.get('quote') or '')).strip()
        preview = q_txt if len(q_txt) <= 240 else q_txt[:237].rstrip() + '...'
        top_passages.append({
            'citation_key': p.get('citation_key'),
            'source_id': p.get('source_id'),
            'page_idx': p.get('page_idx'),
            'score': p.get('score'),
            'quote_preview': preview,
        })
    return {
        'compact': True,
        'artifact_path': str(artifact_path),
        'question': report.get('question'),
        'gate_status': report.get('gate_status'),
        'abstain_reason': report.get('abstain_reason'),
        'distinct_studies': report.get('distinct_studies'),
        'reranker_mode': report.get('reranker_mode'),
        'returned': report.get('returned'),
        'dropped_low_entropy_chunks': report.get('dropped_low_entropy_chunks'),
        'top_passages': top_passages,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('query', nargs='?', help='Search query (or use --question)')
    parser.add_argument('paths', nargs='*', help='Local .md/.txt files, MinerU Content List V2 .json, or directories')
    parser.add_argument('--question', help='Question/query string (overrides positional query)')
    parser.add_argument('--inputs', nargs='+', help='Input files or directories (overrides positional paths)')
    parser.add_argument('--limit', type=int, default=10)
    parser.add_argument('--chunk-chars', type=int, default=1200)
    parser.add_argument('--chunk-overlap', type=int, default=200)
    parser.add_argument('--mmr-lambda', type=float, default=0.7)
    parser.add_argument('--min-studies', type=int, default=2)
    parser.add_argument('--min-evidence', type=int, default=2)
    parser.add_argument('--study-map', type=Path, help='Optional JSON mapping file/path -> study_id')
    parser.add_argument('--khoj-url', help='Optional external Khoj base URL (e.g. http://127.0.0.1:42110)')
    parser.add_argument('--khoj-token-env', default='KHOJ_API_KEY')
    parser.add_argument('--out', type=Path, help='Optional output JSON path')
    parser.add_argument('--strict-gate', action='store_true', help='Exit 1 when gate_status == ABSTAIN')
    parser.add_argument('--compact', action='store_true', help='Write full evidence JSON to --out (or auto-artifact) and print compact stdout JSON')
    args = parser.parse_args()

    if args.question is not None and args.inputs and (args.query is not None or args.paths):
        print(json.dumps({'error': 'unexpected positional arguments when both --question and --inputs are provided'}), file=sys.stderr)
        return 2
    if args.inputs and args.paths:
        print(json.dumps({'error': 'unexpected positional path arguments when --inputs is provided'}), file=sys.stderr)
        return 2
    if args.question is not None and not args.question.strip():
        print(json.dumps({'error': '--question must be nonblank'}), file=sys.stderr)
        return 2

    query_text = args.question if args.question is not None else args.query
    if args.question is not None and not args.inputs and args.query is not None:
        input_paths = [args.query, *args.paths]
    else:
        input_paths = args.inputs or args.paths
    if not query_text or not input_paths:
        print(json.dumps({'error': 'query/--question and paths/--inputs are required'}), file=sys.stderr)
        return 2
    try:
        study_map = None
        if args.study_map is not None:
            study_map = json.loads(args.study_map.expanduser().resolve().read_text(encoding='utf-8'))
            if not isinstance(study_map, dict):
                raise ValueError('--study-map must be a JSON object')
        report = run(
            input_paths,
            query_text,
            args.limit,
            chunk_chars=args.chunk_chars,
            chunk_overlap=args.chunk_overlap,
            mmr_lambda=args.mmr_lambda,
            min_studies=args.min_studies,
            min_evidence=args.min_evidence,
            study_map=study_map,
            khoj_url=args.khoj_url,
            khoj_token_env=args.khoj_token_env,
        )
        rendered = json.dumps(report, ensure_ascii=False)
        out_path = args.out.expanduser().resolve() if args.out is not None else (_auto_artifact_path('local_evidence') if args.compact else None)
        if out_path is not None:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(rendered, encoding='utf-8')
        if args.compact:
            print(json.dumps(_compact_evidence_summary(report, out_path), ensure_ascii=False, separators=(',', ':')))
        else:
            print(rendered)
        if args.strict_gate and report['gate_status'] == 'ABSTAIN':
            return 1
        return 0
    except (ValueError, OSError, json.JSONDecodeError, UnicodeError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
