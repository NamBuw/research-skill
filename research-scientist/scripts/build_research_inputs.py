#!/usr/bin/env python3
"""Zero-friction auto-builder orchestrating PDF/TeX extraction, search, venue leads/panel/CFP into M10A scaffolds."""
from __future__ import annotations

import argparse
import hashlib
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

import capture_venue_sources
import check_gap_record
import check_manuscript_ledger
import check_submission_preflight
import check_venue_plan
import check_venue_sources
import extract_pdf_blocks
import score_math
import search_papers
import venue_leads
import venue_panel_collector


SCHEMA_VERSION = 'research_scientist_build_inputs_v1'
CORPUS_SCHEMA = 'research_scientist_corpus_v1'
SCORECARDS_SCHEMA = 'research_scientist_scorecards_v1'
MAX_COMPACT_BYTES = 4096

DEFAULT_SEARCH_SOURCES = ('openalex', 'arxiv', 's2', 'dblp', 'acl')

SUBFIELD_PRESETS: dict[str, dict[str, Any]] = {
    'nlp_llm': {
        'label': 'NLP / Large Language Models',
        'gap_vetting_checks': [
            'contamination_audit',
            'multi_prompt_template_variance',
            'compute_matched_open_weight_baselines',
            'eval_harness_parity',
        ],
        'required_controls': [
            'frozen_prompt_and_seed_check',
            'pretraining_benchmark_contamination_check',
            'open_weight_baseline_parity',
        ],
        'default_panel_sources': ['acl', 'arxiv', 'openalex', 's2'],
    },
    'cv_multimodal': {
        'label': 'Computer Vision / Multimodal',
        'gap_vetting_checks': [
            'backbone_resolution_augmentation_parity',
            'flops_fps_memory_vs_accuracy_tradeoff',
            'qualitative_failure_analysis',
        ],
        'required_controls': [
            'matched_backbone_and_input_resolution',
            'matched_augmentation_schedule',
            'compute_latency_pareto_report',
        ],
        'default_panel_sources': ['arxiv', 'openalex', 's2', 'dblp'],
    },
    'ml_theory': {
        'label': 'ML Theory / Statistical Learning',
        'gap_vetting_checks': [
            'assumption_tightness_and_realism',
            'lower_vs_upper_bound_gap',
            'empirical_sanity_validation_of_theoretical_claims',
        ],
        'required_controls': [
            'explicit_assumption_falsification_check',
            'matching_lower_bound_comparison',
            'synthetic_toy_sanity_experiment',
        ],
        'default_panel_sources': ['arxiv', 'openalex', 's2', 'dblp'],
    },
    'ai_systems': {
        'label': 'AI Systems / Efficient ML',
        'gap_vetting_checks': [
            'end_to_end_vs_microbenchmark_throughput',
            'tail_latency_p99',
            'peak_vram_and_communication_overhead_matched_hardware',
        ],
        'required_controls': [
            'matched_hardware_and_load_shape',
            'end_to_end_plus_microbenchmark_isolation',
            'p99_tail_latency_and_peak_vram_receipts',
        ],
        'default_panel_sources': ['arxiv', 'openalex', 's2', 'dblp'],
    },
}

_STOPWORDS = {
    'the', 'a', 'an', 'and', 'or', 'of', 'to', 'in', 'on', 'for', 'with', 'by', 'as',
    'is', 'are', 'was', 'were', 'be', 'been', 'that', 'this', 'which', 'from', 'via',
    'using', 'based', 'towards', 'toward', 'study', 'paper', 'we', 'our', 'new', 'novel',
}

_FIT_AXES = (
    'topic_scope_match',
    'contribution_type_match',
    'methodology_standards_match',
    'formatting_length_fit',
    'timeline_budget_eligibility',
)


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
        raise ValueError(f'{label} path is required')
    p = Path(clean)
    if not p.is_file():
        raise ValueError(f'{label} file not found: {clean}')
    return json.loads(p.read_text(encoding='utf-8'), parse_constant=_reject_nonfinite)


def _derive_search_query(topic: str | None, title: str | None, abstract: str | None) -> str:
    if _nonblank(topic):
        q = re.sub(r'\s+', ' ', topic.strip())
        return q[:500]
    parts: list[str] = []
    if _nonblank(title):
        parts.append(re.sub(r'\s+', ' ', title.strip()))
    if _nonblank(abstract):
        words = [
            w for w in re.findall(r'[A-Za-z0-9_-]{3,}', abstract)
            if w.lower() not in _STOPWORDS
        ]
        seen: list[str] = []
        existing = set(re.findall(r'[a-z0-9_-]+', ' '.join(parts).lower()))
        for w in words:
            wl = w.lower()
            if wl not in existing and wl not in {x.lower() for x in seen}:
                seen.append(w)
            if len(seen) >= 8:
                break
        if seen:
            parts.append(' '.join(seen))
    combined = re.sub(r'\s+', ' ', ' '.join(parts)).strip()
    if not combined:
        raise ValueError('could not derive nonblank search query from inputs')
    return combined[:500]


def _extract_pdf_target(pdf_path: Path, sources_dir: Path) -> dict[str, Any]:
    extracted = extract_pdf_blocks.extract(pdf_path, max_pages=200, tables=False, ocr=False)
    blocks_path = sources_dir / f'{pdf_path.stem}_blocks.json'
    blocks_path.parent.mkdir(parents=True, exist_ok=True)
    blocks_path.write_text(json.dumps(extracted, indent=2), encoding='utf-8')

    all_blocks: list[dict[str, Any]] = []
    for page in extracted.get('pages') or []:
        if isinstance(page, list):
            for blk in page:
                if isinstance(blk, dict) and _nonblank(blk.get('text')):
                    all_blocks.append(blk)

    title = pdf_path.stem.replace('_', ' ')
    abstract_parts: list[str] = []
    in_abstract = False
    for blk in all_blocks:
        txt = re.sub(r'\s+', ' ', blk['text'].strip())
        low = txt.lower()
        if blk.get('page_idx', 0) == 0 and title == pdf_path.stem.replace('_', ' ') and len(txt) >= 8:
            if not low.startswith(('abstract', 'section ', '1.', '1 ')):
                title = txt
                continue
        if re.match(r'^(?:abstract\b[:\s-]*)', low):
            in_abstract = True
            rem = re.sub(r'^abstract\b[:\s-]*', '', txt, flags=re.I).strip()
            if rem:
                abstract_parts.append(rem)
            continue
        if in_abstract:
            if re.match(r'^(?:1\.?\s+introduction|section\s+1\b|introduction\b|keywords\b)', low):
                in_abstract = False
            else:
                abstract_parts.append(txt)

    if not abstract_parts and len(all_blocks) > 1:
        abstract_parts.append(re.sub(r'\s+', ' ', all_blocks[1]['text'].strip())[:600])

    if all_blocks:
        reading_basis = 'full_text'
        access = 'full_text'
        first_locator: str | None = f'Page {(all_blocks[0].get("page_idx", 0)) + 1}'
        first_quote: str | None = re.sub(r'\s+', ' ', all_blocks[0]['text'].strip())[:240]
        extraction_warnings: list[str] = []
    else:
        reading_basis = 'unavailable'
        access = 'unavailable'
        first_locator = None
        first_quote = None
        extraction_warnings = ['pdf_zero_extracted_blocks:downgraded_to_unavailable']

    return {
        'input_kind': 'pdf',
        'id': f'target:{pdf_path.stem}',
        'title': title,
        'abstract': ' '.join(abstract_parts).strip(),
        'reading_basis': reading_basis,
        'access': access,
        'source_path': str(pdf_path.resolve()),
        'source_pdf_sha256': extracted.get('source_pdf_sha256'),
        'extracted_blocks_path': str(blocks_path),
        'locator': first_locator,
        'quote': first_quote,
        'blocks_count': len(all_blocks),
        'bib_leads': [],
        'tex_notes': [],
        'extraction_warnings': extraction_warnings,
    }


def _resolve_main_tex(tex_input: Path) -> Path:
    if tex_input.is_symlink():
        raise ValueError('input TeX path must not be a symlink')
    resolved = tex_input.resolve()
    if resolved.is_file():
        if resolved.suffix.lower() != '.tex':
            raise ValueError('TeX input file must have .tex suffix')
        return resolved
    if resolved.is_dir():
        main_cand = resolved / 'main.tex'
        if main_cand.is_file() and not main_cand.is_symlink():
            return main_cand
        tex_files = sorted(p for p in resolved.glob('*.tex') if p.is_file() and not p.is_symlink())
        for cand in tex_files:
            txt = cand.read_text(encoding='utf-8', errors='replace')
            if '\\documentclass' in txt and '\\begin{document}' in txt:
                return cand
        if len(tex_files) == 1:
            return tex_files[0]
        raise ValueError(f'Could not uniquely resolve main .tex file in {resolved}')
    raise ValueError(f'TeX input path does not exist: {tex_input}')


def _parse_bib_entries(root_dir: Path) -> list[dict[str, Any]]:
    leads: list[dict[str, Any]] = []
    for bib in sorted(root_dir.glob('*.bib')):
        if bib.is_symlink() or not bib.is_file():
            continue
        if not bib.resolve().is_relative_to(root_dir.resolve()):
            continue
        raw = bib.read_text(encoding='utf-8', errors='replace')
        for m in re.finditer(r'@\w+\s*\{\s*([^,\s]+)\s*,([\s\S]*?)\n\}', raw):
            key, body = m.group(1).strip(), m.group(2)
            tm = re.search(r'\btitle\s*=\s*[\{\"]([^\}\"]+)[\}\"]', body, re.I)
            ym = re.search(r'\byear\s*=\s*[\{\"]?(\d{4})[\}\"]?', body, re.I)
            title = re.sub(r'\s+', ' ', tm.group(1)).strip() if tm else key
            year = int(ym.group(1)) if ym else None
            leads.append({
                'id': f'bib:{key}',
                'source': 'local_bib',
                'source_id': key,
                'dedup_key': f'bib:{key}',
                'title': title,
                'year': year,
                'abstract': None,
                'authors': [],
                'venue': None,
                'doi': None,
                'arxiv_id': None,
                'url': None,
                'pdf_url': None,
                'preprint_only': False,
                'retraction_status': 'unchecked',
                'sources_seen': ['local_bib'],
                'family': 'unspecified',
                'reading_basis': 'metadata_only',
                'access': 'metadata',
                'full_text_excerpt': None,
                'ratings': None,
            })
    return leads


def _extract_tex_target(tex_input: Path, sources_dir: Path) -> dict[str, Any]:
    main_tex = _resolve_main_tex(tex_input)
    root_dir = main_tex.parent.resolve()
    rows, notes = check_submission_preflight._load_tex_flattened(main_tex, root_dir=root_dir)
    unsafe_notes = [n for n in notes if 'unsafe \\input' in n]
    if unsafe_notes:
        raise ValueError(f'Unsafe LaTeX \\input/\\include traversal blocked: {unsafe_notes[0]}')

    # Reconstruct flattened code safely from root-contained rows
    flattened_code = '\n'.join(code for (_fpath, _ln, code, _comment) in rows)
    sections = check_manuscript_ledger._extract_sections(flattened_code, is_tex=True)
    title = (sections.get('title') or main_tex.stem.replace('_', ' ')).strip()
    abstract = (sections.get('abstract') or '').strip()
    body = (sections.get('body') or '').strip()

    raw_bytes = main_tex.read_bytes()
    sha = hashlib.sha256(raw_bytes).hexdigest()

    out_txt = sources_dir / f'{main_tex.stem}_tex.txt'
    out_txt.parent.mkdir(parents=True, exist_ok=True)
    out_txt.write_text(f'{title}\n\n{abstract}\n\n{body}'.strip(), encoding='utf-8')

    first_quote = (abstract or body or title)[:240]
    bib_leads = _parse_bib_entries(root_dir)

    return {
        'input_kind': 'tex',
        'id': f'target:{main_tex.stem}',
        'title': title,
        'abstract': abstract,
        'section_headings': sections.get('section_headings', ''),
        'reading_basis': 'full_text',
        'access': 'full_text',
        'source_path': str(main_tex),
        'source_tex_sha256': sha,
        'extracted_text_path': str(out_txt),
        'locator': f'{main_tex.name}: Abstract' if abstract else f'{main_tex.name}: Body',
        'quote': first_quote,
        'bib_leads': bib_leads,
        'tex_notes': notes,
    }


def _parse_arxiv_xml_string(xml_text: str) -> dict[str, Any]:
    root = search_papers.DET.fromstring(xml_text.encode('utf-8'))
    atom = '{http://www.w3.org/2005/Atom}'
    arxiv_ns = '{http://arxiv.org/schemas/atom}'
    total_text = root.findtext('{http://a9.com/-/spec/opensearch/1.1/}totalResults')
    total = int(total_text) if total_text and total_text.isdigit() else 0
    entries = []
    for entry in root.findall(atom + 'entry'):
        authors = [
            a.findtext(atom + 'name').strip()
            for a in entry.findall(atom + 'author')
            if a.findtext(atom + 'name')
        ]
        pdf_url = None
        for link in entry.findall(atom + 'link'):
            if link.attrib.get('title') == 'pdf' or link.attrib.get('type') == 'application/pdf':
                pdf_url = link.attrib.get('href')
                break
        entries.append({
            'id': entry.findtext(atom + 'id'),
            'title': re.sub(r'\s+', ' ', entry.findtext(atom + 'title') or '').strip() or None,
            'summary': re.sub(r'\s+', ' ', entry.findtext(atom + 'summary') or '').strip() or None,
            'published': entry.findtext(atom + 'published'),
            'authors': authors,
            'doi': entry.findtext(arxiv_ns + 'doi'),
            'journal_ref': entry.findtext(arxiv_ns + 'journal_ref'),
            'pdf_url': pdf_url,
        })
    return {'entries': entries, 'total': total}


def _make_mock_search_transport(mock_data: dict[str, Any]):
    def _transport(source: str, params: dict[str, Any]) -> Any:
        if source in mock_data:
            val = mock_data[source]
            if source == 'arxiv' and isinstance(val, str):
                return _parse_arxiv_xml_string(val)
            return val
        matching_keys = sorted(
            (k for k in mock_data.keys() if k.startswith(f'{source}_')),
            key=lambda k: (0 if 'direct' in k else 1, k),
        )
        if not matching_keys:
            if source == 'openalex':
                return {'meta': {'count': 0}, 'results': []}
            if source == 'arxiv':
                return {'entries': [], 'total': 0}
            if source == 's2':
                return {'data': [], 'total': 0}
            if source == 'dblp':
                return {'result': {'hits': {'@total': '0', 'hit': []}}}
            return {'records': [], 'total': 0}
        if source == 'arxiv':
            merged_entries: list[dict[str, Any]] = []
            total = 0
            for k in matching_keys:
                v = mock_data[k]
                parsed = _parse_arxiv_xml_string(v) if isinstance(v, str) else v
                if isinstance(parsed, dict):
                    merged_entries.extend(parsed.get('entries') or [])
                    total = max(total, int(parsed.get('total') or 0))
            return {'entries': merged_entries, 'total': max(total, len(merged_entries))}
        if source == 'openalex':
            merged_res: list[dict[str, Any]] = []
            total = 0
            for k in matching_keys:
                v = mock_data[k]
                if isinstance(v, dict):
                    merged_res.extend(v.get('results') or [])
                    total = max(total, int((v.get('meta') or {}).get('count') or 0))
            return {'meta': {'count': max(total, len(merged_res))}, 'results': merged_res}
        return mock_data[matching_keys[0]]

    return _transport


def _make_mock_venue_http_transport(mock_map: dict[str, Any]):
    def _transport(url: str) -> dict[str, Any]:
        visited = [url]
        cur = url
        hops = 0
        while hops < 5:
            rec = mock_map.get(cur)
            if not isinstance(rec, dict):
                raise RuntimeError(f'mock_http_404:{cur}')
            status = int(rec.get('status', 200))
            loc = rec.get('location')
            if status in (301, 302, 303, 307, 308) and isinstance(loc, str) and loc:
                visited.append(loc)
                cur = loc
                hops += 1
                continue
            body = rec.get('body', '')
            body_bytes = body.encode('utf-8') if isinstance(body, str) else body
            return {
                'final_url': cur,
                'redirect_chain': visited,
                'content_type': rec.get('content_type', 'text/html; charset=utf-8'),
                'body': body_bytes,
                'http_status': status,
            }
        raise RuntimeError(f'mock_too_many_redirects:{url}')

    return _transport


def _normalize_corpus_paper(raw: dict[str, Any], idx: int) -> dict[str, Any]:
    pid = str(raw.get('dedup_key') or raw.get('id') or raw.get('source_id') or f'PAPER-{idx}').strip()
    abstract = raw.get('abstract')
    has_abs = _nonblank(abstract)
    return {
        'id': pid,
        'source': raw.get('source', 'unknown'),
        'source_id': raw.get('source_id') or pid,
        'dedup_key': raw.get('dedup_key') or pid,
        'title': raw.get('title') or 'Untitled',
        'authors': list(raw.get('authors') or []),
        'year': raw.get('year'),
        'venue': raw.get('venue'),
        'doi': raw.get('doi'),
        'arxiv_id': raw.get('arxiv_id'),
        'openalex_id': raw.get('openalex_id'),
        's2_id': raw.get('s2_id'),
        'dblp_key': raw.get('dblp_key'),
        'abstract': abstract if has_abs else None,
        'url': raw.get('url'),
        'pdf_url': raw.get('pdf_url'),
        'preprint_only': bool(raw.get('preprint_only', False)),
        'retraction_status': raw.get('retraction_status', 'unchecked'),
        'sources_seen': list(raw.get('sources_seen') or ([raw['source']] if raw.get('source') else [])),
        'family': raw.get('family', 'same_problem'),
        'reading_basis': 'metadata_only',
        'access': 'abstract' if has_abs else 'metadata',
        'full_text_excerpt': None,
        'ratings': None,
    }


def build_inputs(
    *,
    topic: str | None = None,
    input_path: str | None = None,
    pdf_path: str | None = None,
    tex_path: str | None = None,
    target_venue: str | None = None,
    venue_track: str = 'Main',
    venue_edition: str | None = None,
    cfp_url: str | None = None,
    subfield_preset: str | None = None,
    constraints: dict[str, Any] | None = None,
    budget_usd: float | None = None,
    gpu_budget: str | None = None,
    deadline_window: str | None = None,
    user_timezone: str = 'UTC',
    sources: list[str] | tuple[str, ...] = DEFAULT_SEARCH_SOURCES,
    search_mode: str = 'balanced',
    search_size: int = 10,
    search_pages: int = 1,
    panel_source: str | None = None,
    panel_venue_id: str | None = None,
    panel_limit: int = 5,
    quality_refs_dir: str | None = None,
    offline: bool = False,
    mock_search_data: dict[str, Any] | None = None,
    corpus_data: Any = None,
    offline_leads_data: dict[str, Any] | None = None,
    offline_panel_html: str | None = None,
    offline_venue_responses: dict[str, Any] | None = None,
    venue_sources_bundle: dict[str, Any] | None = None,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    if subfield_preset is not None and subfield_preset not in SUBFIELD_PRESETS:
        raise ValueError(f'subfield_preset must be one of {tuple(SUBFIELD_PRESETS.keys())}')
    if budget_usd is not None:
        if isinstance(budget_usd, bool) or not isinstance(budget_usd, (int, float)) or not math.isfinite(float(budget_usd)) or float(budget_usd) < 0:
            raise ValueError('budget_usd must be a finite nonnegative number')
    if cfp_url is not None and (not isinstance(cfp_url, str) or not cfp_url.startswith('https://')):
        raise ValueError('cfp_url must start with https://')

    resolved_pdf: Path | None = None
    resolved_tex: Path | None = None
    if input_path is not None:
        ip = Path(input_path)
        if ip.is_symlink():
            raise ValueError('--input must not be a symlink')
        if ip.is_dir() or ip.suffix.lower() == '.tex':
            resolved_tex = ip
        elif ip.suffix.lower() == '.pdf':
            resolved_pdf = ip
        else:
            raise ValueError(f'--input must be a .pdf, .tex, or TeX directory: {input_path}')
    if pdf_path is not None:
        resolved_pdf = Path(pdf_path)
    if tex_path is not None:
        resolved_tex = Path(tex_path)
    if resolved_pdf is not None and resolved_tex is not None:
        raise ValueError('Provide either a PDF or a TeX input, not both')
    if not _nonblank(topic) and resolved_pdf is None and resolved_tex is None:
        raise ValueError('Provide --topic or a local PDF/TeX manuscript (--input / --pdf / --tex)')

    work_dir = Path(out_dir) if out_dir is not None else Path(tempfile.mkdtemp(prefix='rs_inputs_'))
    work_dir.mkdir(parents=True, exist_ok=True)
    sources_dir = work_dir / 'sources'
    sources_dir.mkdir(parents=True, exist_ok=True)

    subfield_criteria = SUBFIELD_PRESETS.get(subfield_preset) if subfield_preset else None
    warnings: list[str] = []
    target_manuscript: dict[str, Any] | None = None
    if resolved_pdf is not None:
        target_manuscript = _extract_pdf_target(resolved_pdf, sources_dir)
        for w in target_manuscript.pop('extraction_warnings', []):
            warnings.append(w)
    elif resolved_tex is not None:
        target_manuscript = _extract_tex_target(resolved_tex, sources_dir)
    else:
        target_manuscript = {
            'input_kind': 'topic',
            'id': 'target_topic',
            'title': topic.strip() if topic else '',
            'abstract': '',
            'reading_basis': 'not_applicable',
            'access': 'unavailable',
            'source_path': None,
        }

    search_query = _derive_search_query(
        topic,
        target_manuscript.get('title'),
        target_manuscript.get('abstract'),
    )
    now_iso = _utc_now()
    today_str = now_iso[:10]

    # 1. Search / Corpus orchestration
    search_summary: dict[str, Any]
    raw_papers: list[dict[str, Any]] = []
    search_queries_log: list[dict[str, Any]] = []

    if corpus_data is not None:
        if isinstance(corpus_data, dict):
            if corpus_data.get('papers') is not None:
                raw_list = corpus_data.get('papers')
            elif 'results' in corpus_data:
                raw_list = corpus_data.get('results')
            else:
                raw_list = None
        else:
            raw_list = corpus_data
        if not isinstance(raw_list, list):
            raise ValueError('corpus_json must be a list or contain papers/results list')
        raw_papers = [_normalize_corpus_paper(p, i + 1) for i, p in enumerate(raw_list) if isinstance(p, dict)]
        search_summary = {'status': 'loaded_local_corpus', 'query': search_query, 'retrieved_count': len(raw_papers)}
        search_queries_log.append({
            'id': 'Q1',
            'source': 'local_corpus',
            'query': search_query,
            'family': 'direct',
            'status': 'complete',
            'retrieved': len(raw_papers),
            'inspected': 0,
        })
    elif mock_search_data is not None:
        mock_src = search_papers.search(
            search_query,
            sources=tuple(sources),
            size=search_size,
            pages=search_pages,
            transport=_make_mock_search_transport(mock_search_data),
            mode=search_mode,
        )
        raw_papers = [_normalize_corpus_paper(p, i + 1) for i, p in enumerate(mock_src.get('results') or [])]
        search_summary = {
            'status': 'mock_search_completed',
            'query': search_query,
            'sources': mock_src.get('sources'),
            'retrieved_count': len(raw_papers),
        }
        for qi, (src_name, src_info) in enumerate((mock_src.get('sources') or {}).items(), start=1):
            st = src_info.get('status', 'complete')
            if st not in check_gap_record.QUERY_STATES:
                st = 'source_failed'
            cnt = int(src_info.get('parsed_count', 0) or 0)
            search_queries_log.append({
                'id': f'Q{qi}',
                'source': src_name,
                'query': search_query,
                'family': 'direct',
                'status': st,
                'retrieved': cnt,
                'inspected': 0,
            })
    elif offline:
        bib_leads = list((target_manuscript or {}).get('bib_leads') or [])
        raw_papers = bib_leads
        search_summary = {
            'status': 'not_run_offline',
            'query': search_query,
            'retrieved_count': len(raw_papers),
        }
        search_queries_log.append({
            'id': 'Q1',
            'source': 'offline_mode',
            'query': search_query,
            'family': 'direct',
            'status': 'not_run',
            'retrieved': 0,
            'inspected': 0,
        })
        warnings.append('offline_search_skipped:no_mock_or_corpus_supplied')
    else:
        live_src = search_papers.search(
            search_query,
            sources=tuple(sources),
            size=search_size,
            pages=search_pages,
            mode=search_mode,
        )
        raw_papers = [_normalize_corpus_paper(p, i + 1) for i, p in enumerate(live_src.get('results') or [])]
        search_summary = {
            'status': 'live_search_completed',
            'query': search_query,
            'sources': live_src.get('sources'),
            'retrieved_count': len(raw_papers),
        }
        for qi, (src_name, src_info) in enumerate((live_src.get('sources') or {}).items(), start=1):
            st = src_info.get('status', 'source_failed')
            if st not in check_gap_record.QUERY_STATES:
                st = 'source_failed'
            cnt = int(src_info.get('parsed_count', 0) or 0)
            search_queries_log.append({
                'id': f'Q{qi}',
                'source': src_name,
                'query': search_query,
                'family': 'direct',
                'status': st,
                'retrieved': cnt,
                'inspected': 0,
            })

    # Enforce strict zero-fabrication on every retrieved/corpus paper
    for p in raw_papers:
        p['reading_basis'] = 'metadata_only'
        p['access'] = 'abstract' if _nonblank(p.get('abstract')) else 'metadata'
        p['full_text_excerpt'] = None
        p['ratings'] = None

    corpus_doc = {
        'schema': CORPUS_SCHEMA,
        'topic': search_query,
        'generated_at_utc': now_iso,
        'mode': 'offline' if offline else 'live',
        'subfield_preset': subfield_preset,
        'subfield_criteria': subfield_criteria,
        'target_manuscript': target_manuscript,
        'search_summary': search_summary,
        'papers': raw_papers,
    }

    # 2. Venue quality leads & optional panel collection
    refs = venue_leads.load_venue_quality_refs(quality_refs_dir)
    venue_name = target_venue.strip() if _nonblank(target_venue) else 'UNSPECIFIED_TARGET_VENUE'
    venue_quality_ctx = venue_leads.lookup_venue_quality(venue_name, refs) if target_venue else {
        'quality_tier': 'Unknown',
        'evidence': [],
        'matched_source': None,
        'matched_name': None,
        'advisory_only': True,
    }
    leads_summary: dict[str, Any] = {'status': 'not_run_offline'}
    if offline_leads_data is not None:
        leads_summary = venue_leads.collect(
            search_query,
            pages=1,
            page_size=25,
            transport=lambda _params: offline_leads_data,
            quality_refs_dir=quality_refs_dir,
        )
    elif not offline:
        try:
            leads_summary = venue_leads.collect(search_query, pages=1, page_size=10, quality_refs_dir=quality_refs_dir)
        except Exception as exc:
            leads_summary = {'status': f'failed:{exc}'}
            warnings.append(f'venue_leads_failed:{exc}')

    panel_doc: dict[str, Any] | None = None
    if panel_source and panel_venue_id:
        if offline_panel_html is not None or not offline:
            try:
                panel_doc = venue_panel_collector.collect_panel(
                    panel_source,
                    panel_venue_id,
                    limit=panel_limit,
                    track=venue_track if venue_track != 'Main' else None,
                    offline_html=offline_panel_html,
                )
                for ap in panel_doc.get('accepted_panel') or []:
                    ap['reading_basis'] = 'metadata_only'
                    ap['ratings'] = None
                    ap['score'] = None
                    ap['low'] = None
                    ap['high'] = None
            except venue_panel_collector.PanelCollectionError as exc:
                warnings.append(f'venue_panel_skipped:{exc.error_code}')
        else:
            warnings.append('venue_panel_skipped:offline_without_offline_panel_html')

    # 3. Scaffold gap_record.json (passes check_gap_record with insufficient_evidence)
    evidences: list[dict[str, Any]] = []
    closest_works: list[dict[str, Any]] = []
    if target_manuscript and target_manuscript.get('reading_basis') == 'full_text':
        evidences.append({
            'id': 'E-TARGET',
            'source_id': target_manuscript['id'],
            'study_id': target_manuscript['id'],
            'locator': target_manuscript.get('locator') or 'Page 1',
            'claim': target_manuscript.get('quote') or target_manuscript.get('title') or search_query,
            'role': 'context',
            'access': 'full_text',
            'quote': target_manuscript.get('quote') or '',
        })
    for idx, p in enumerate(raw_papers[:5], start=1):
        eid = f'E-{idx}'
        wid = f'W-{idx}'
        acc = 'abstract' if _nonblank(p.get('abstract')) else 'metadata'
        evidences.append({
            'id': eid,
            'source_id': p['id'],
            'study_id': p['id'],
            'locator': 'abstract' if acc == 'abstract' else 'metadata_record',
            'claim': (p.get('abstract') or p.get('title') or 'Metadata entry')[:400],
            'role': 'context',
            'access': acc,
        })
        closest_works.append({
            'id': wid,
            'source_id': p['id'],
            'relation': 'adjacent_precedent',
            'access': acc,
            'difference': 'UNVERIFIED — metadata_only; inspect full text before claiming difference',
            'evidence_ids': [eid],
        })

    gap_candidates: list[dict[str, Any]] = [
        {
            'id': 'G1',
            'claim': f'Preliminary unverified candidate around: {search_query}',
            'type': 'boundary',
            'disposition': 'insufficient_evidence',
            'rationale': 'Auto-scaffolded from topic/manuscript metadata; requires full_text inspection, kill-search, and engineering checks.',
            'engineering_status': 'unchecked',
            'support_evidence_ids': ['E-TARGET'] if target_manuscript.get('reading_basis') == 'full_text' else [],
            'counter_evidence_ids': [],
            'closest_work_ids': [w['id'] for w in closest_works],
            'kill_query_ids': [],
            'subfield_preset': subfield_preset,
            'subfield_vetting_checklist': (subfield_criteria or {}).get('gap_vetting_checks', []),
        }
    ]
    cov_parts = [f'mode={corpus_doc["mode"]}', f'retrieved_metadata_only={len(raw_papers)}']
    if offline:
        cov_parts.append('offline_mode:no_live_network_coverage')
    gap_record = {
        'scope': f'Auto-scaffolded input for {search_query}',
        'search_date': today_str,
        'coverage_limits': '; '.join(cov_parts),
        'next_check': 'Read top closest works in full_text, supply digests/locators, run kill-search and engineering diagnostics.',
        'subfield_preset': subfield_preset,
        'subfield_criteria': subfield_criteria,
        'queries': search_queries_log,
        'evidence': evidences,
        'closest_works': closest_works,
        'candidates': gap_candidates,
    }
    gap_check = check_gap_record.check(gap_record)
    if not gap_check.get('valid_structure'):
        raise RuntimeError(f"Scaffolded gap_record failed structural check: {gap_check.get('errors')}")

    # 4. Scaffold scorecards.json (zero-fabrication: all ratings None -> compare_scorecards returns not_comparable)
    target_sc_id = target_manuscript['id'] if target_manuscript else 'target_topic'
    cw_ids_for_sc = [p['id'] for p in raw_papers[:3]] or ['UNVERIFIED_CLOSEST_WORK_PENDING_SEARCH']
    profiles: list[dict[str, Any]] = [
        {
            'id': target_sc_id,
            'reading_basis': 'full_text' if target_manuscript.get('reading_basis') == 'full_text' else 'metadata_only',
            'closest_work': cw_ids_for_sc,
            'ratings': {d: None for d in score_math.DIMENSIONS},
            'ratings_status': 'unscored_null',
            'evidence_locators': {d: [] for d in score_math.DIMENSIONS},
        }
    ]
    for p in raw_papers[:3]:
        profiles.append({
            'id': p['id'],
            'reading_basis': 'metadata_only',
            'closest_work': [target_sc_id],
            'ratings': {d: None for d in score_math.DIMENSIONS},
            'ratings_status': 'unscored_null',
            'evidence_locators': {d: [] for d in score_math.DIMENSIONS},
        })
    if len(profiles) < 2:
        profiles.append({
            'id': 'UNVERIFIED_CLOSEST_WORK_PENDING_SEARCH',
            'reading_basis': 'metadata_only',
            'closest_work': [target_sc_id],
            'ratings': {d: None for d in score_math.DIMENSIONS},
            'ratings_status': 'unscored_null',
            'evidence_locators': {d: [] for d in score_math.DIMENSIONS},
        })

    scorecards_doc = {
        'schema': SCORECARDS_SCHEMA,
        'target_id': target_sc_id,
        'strict_related_panel': True,
        'min_related': 3,
        'subfield_preset': subfield_preset,
        'subfield_criteria': subfield_criteria,
        'weight_scenarios': [
            {'importance': 15, 'novelty': 20, 'soundness': 20, 'evidence': 20, 'transparency': 15, 'clarity': 10}
        ],
        'profiles': profiles,
        'metadata_only_papers': [
            {'id': p['id'], 'title': p['title'], 'reading_basis': 'metadata_only', 'ratings': None}
            for p in raw_papers
        ],
    }

    # 5. Scaffold dossier.json (zero-fabrication: unverified CFP/fees/milestones)
    resolved_tier = score_math.resolve_venue_tier(
        venue_name=target_venue,
        track=venue_track,
        quality_tier=venue_quality_ctx.get('quality_tier') if venue_quality_ctx.get('quality_tier') in {'S', 'A', 'B', 'C'} else None,
    )
    dossier_doc: dict[str, Any] = {
        'venue': venue_name,
        'edition': venue_edition.strip() if _nonblank(venue_edition) else 'unverified',
        'track': venue_track.strip() if _nonblank(venue_track) else 'Main',
        'official_cfp_url': cfp_url,
        'checked_at': now_iso,
        'user_timezone': user_timezone,
        'subfield_preset': subfield_preset,
        'subfield_criteria': subfield_criteria,
        'constraints': {
            **(constraints or {}),
            'gpu_budget': gpu_budget,
            'deadline_window': deadline_window,
            'budget_usd': budget_usd,
        },
        'milestones': {
            'abstract_registration': None,
            'full_paper': None,
            'notification': None,
            'camera_ready': None,
        },
        'currency': 'USD',
        'budget_currency': 'USD',
        'budget': budget_usd,
        'presentation_mode': 'not_applicable',
        'fees': [
            {'name': 'Submission Fee', 'mandatory': True, 'category': 'submission', 'amount': None, 'verification_status': 'unverified', 'source_url': None, 'checked_at': None},
            {'name': 'Publication Fee', 'mandatory': True, 'category': 'publication', 'amount': None, 'verification_status': 'unverified', 'source_url': None, 'checked_at': None},
            {'name': 'Author Registration', 'mandatory': True, 'category': 'author_registration', 'amount': None, 'verification_status': 'unverified', 'source_url': None, 'checked_at': None},
            {'name': 'Overlength Page Fee', 'mandatory': False, 'category': 'overlength', 'amount': None, 'verification_status': 'unverified', 'source_url': None, 'checked_at': None},
            {'name': 'Tax / Processing', 'mandatory': True, 'category': 'tax', 'amount': None, 'verification_status': 'unverified', 'source_url': None, 'checked_at': None},
        ],
        'evidence_claims': [],
        'venue_quality_context': venue_quality_ctx,
        'resolved_venue_tier': resolved_tier,
        'verification_summary': {
            'cfp_status': 'unverified',
            'fees_status': 'unverified',
            'deadlines_status': 'unverified',
        },
        'novelty_profile_scaffold': {
            'venue': {
                'name': venue_name,
                'edition': venue_edition.strip() if _nonblank(venue_edition) else 'unverified',
                'track': venue_track.strip() if _nonblank(venue_track) else 'Main',
                'official_cfp_url': cfp_url,
            },
            'target': {
                'id': target_sc_id,
                'reading_basis': target_manuscript.get('reading_basis', 'metadata_only'),
                'score': None,
                'low': None,
                'high': None,
                'ratings': None,
            },
            'accepted_panel': (panel_doc or {}).get('accepted_panel', []),
            'hard_constraints': [
                {'name': c, 'status': 'unverified', 'reason': 'Not yet verified against official CFP/fee snapshot'}
                for c in ('deadline', 'budget', 'eligibility')
            ],
            'fit_axes': [
                {'name': ax, 'score': None, 'source_url': None, 'locator': None, 'reason': 'unverified'}
                for ax in _FIT_AXES
            ],
        },
    }

    captured_sources_doc = venue_sources_bundle
    if captured_sources_doc is None and cfp_url is not None:
        if offline_venue_responses is not None:
            captured_sources_doc = capture_venue_sources.capture_dossier(
                dossier_doc,
                transport=_make_mock_venue_http_transport(offline_venue_responses),
                artifacts_dir=str(sources_dir),
            )
        elif not offline:
            try:
                captured_sources_doc = capture_venue_sources.capture_dossier(
                    dossier_doc,
                    artifacts_dir=str(sources_dir),
                )
            except Exception as exc:
                warnings.append(f'cfp_capture_failed:{exc}')

    if captured_sources_doc is not None and cfp_url is not None:
        src_check = check_venue_sources.check(dossier_doc, captured_sources_doc)
        plan_check = check_venue_plan.check(dossier_doc, source_bundle=captured_sources_doc)
        dossier_doc['venue_sources_check'] = src_check
        dossier_doc['venue_plan_check'] = plan_check
        # Keep unverified unless quotes/deadlines/fees are verified
        dossier_doc['verification_summary']['cfp_status'] = (
            'snapshot_captured_unverified_claims' if not src_check.get('verification_passed') else 'snapshot_checked'
        )

    # Persist artifacts to out_dir
    corpus_path = work_dir / 'corpus.json'
    gap_path = work_dir / 'gap_record.json'
    scorecards_path = work_dir / 'scorecards.json'
    dossier_path = work_dir / 'dossier.json'

    corpus_path.write_text(json.dumps(corpus_doc, indent=2), encoding='utf-8')
    gap_path.write_text(json.dumps(gap_record, indent=2), encoding='utf-8')
    scorecards_path.write_text(json.dumps(scorecards_doc, indent=2), encoding='utf-8')
    dossier_path.write_text(json.dumps(dossier_doc, indent=2), encoding='utf-8')

    artifacts: dict[str, str] = {
        'out_dir': str(work_dir),
        'corpus_json': str(corpus_path),
        'gap_record_json': str(gap_path),
        'scorecards_json': str(scorecards_path),
        'dossier_json': str(dossier_path),
    }
    if panel_doc is not None:
        p_path = work_dir / 'panel.json'
        p_path.write_text(json.dumps(panel_doc, indent=2), encoding='utf-8')
        artifacts['panel_json'] = str(p_path)
    if captured_sources_doc is not None:
        vs_path = work_dir / 'venue_sources.json'
        vs_path.write_text(json.dumps(captured_sources_doc, indent=2), encoding='utf-8')
        artifacts['venue_sources_json'] = str(vs_path)

    return {
        'schema': SCHEMA_VERSION,
        'status': 'scaffolded',
        'mode': corpus_doc['mode'],
        'query': search_query,
        'subfield_preset': subfield_preset,
        'paper_count': len(raw_papers),
        'unread_metadata_only_count': len(raw_papers),
        'target_reading_basis': target_manuscript.get('reading_basis'),
        'leads_status': leads_summary.get('status'),
        'artifacts': artifacts,
        'warnings': warnings,
        'corpus': corpus_doc,
        'gap_record': gap_record,
        'scorecards': scorecards_doc,
        'dossier': dossier_doc,
    }


def _auto_artifact_path(prefix: str) -> Path:
    art_dir = Path(tempfile.gettempdir()) / 'research_scientist_artifacts'
    art_dir.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(prefix=f'{prefix}_', suffix='.json', dir=str(art_dir))
    os.close(fd)
    return Path(raw_path)


def _compact_output(result: dict[str, Any], out_path: str | None) -> dict[str, Any]:
    serializable = {
        k: v for k, v in result.items()
        if k not in ('corpus', 'gap_record', 'scorecards', 'dossier')
    }
    target = Path(out_path) if out_path else _auto_artifact_path('build_inputs')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(serializable, indent=2), encoding='utf-8')
    compact = {
        'compact': True,
        'schema': result.get('schema'),
        'status': result.get('status'),
        'mode': result.get('mode'),
        'subfield_preset': result.get('subfield_preset'),
        'paper_count': result.get('paper_count'),
        'unread_metadata_only_count': result.get('unread_metadata_only_count'),
        'target_reading_basis': result.get('target_reading_basis'),
        'artifacts': result.get('artifacts'),
        'warnings': (result.get('warnings') or [])[:5],
        'artifact_path': str(target),
    }
    if len(json.dumps(compact, ensure_ascii=False).encode('utf-8')) >= MAX_COMPACT_BYTES:
        compact = {
            'compact': True,
            'schema': result.get('schema'),
            'status': result.get('status'),
            'artifacts': result.get('artifacts'),
            'artifact_path': str(target),
        }
    return compact


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--topic', help='Research topic or query string')
    parser.add_argument('--input', help='Local .pdf, .tex, or TeX directory')
    parser.add_argument('--pdf', help='Local PDF manuscript path')
    parser.add_argument('--tex', help='Local .tex file or TeX project directory')
    parser.add_argument('--target-venue', help='Optional target venue name')
    parser.add_argument('--venue-track', default='Main', help='Target venue track')
    parser.add_argument('--venue-edition', help='Target venue edition/year')
    parser.add_argument('--cfp-url', help='Optional official HTTPS CFP URL')
    parser.add_argument('--subfield-preset', choices=tuple(SUBFIELD_PRESETS.keys()), help='Subfield depth preset')
    parser.add_argument('--constraints-json', help='Path to JSON constraints file')
    parser.add_argument('--budget-usd', type=float, help='Budget constraint in USD')
    parser.add_argument('--gpu-budget', help='GPU/VRAM budget description')
    parser.add_argument('--deadline-window', help='Target submission timeline window')
    parser.add_argument('--user-timezone', default='UTC', help='IANA timezone (default UTC)')
    parser.add_argument('--sources', action='append', help='Scholarly source(s) for search_papers')
    parser.add_argument('--search-mode', choices=('speed', 'balanced', 'quality'), default='balanced')
    parser.add_argument('--search-size', type=int, default=10)
    parser.add_argument('--search-pages', type=int, default=1)
    parser.add_argument('--panel-source', choices=('pmlr', 'acl', 'dblp'), help='Accepted panel source')
    parser.add_argument('--panel-venue-id', help='Accepted panel venue ID')
    parser.add_argument('--panel-limit', type=int, default=5)
    parser.add_argument('--quality-refs-dir', help='Optional external venue quality refs dir')
    parser.add_argument('--offline', action='store_true', help='Disable all network calls')
    parser.add_argument('--mock-search-json', help='Mock search responses JSON path')
    parser.add_argument('--corpus-json', help='Local pre-collected corpus JSON path')
    parser.add_argument('--offline-leads-json', help='Offline OpenAlex leads JSON path')
    parser.add_argument('--offline-panel-html', help='Offline HTML proceedings file path')
    parser.add_argument('--offline-venue-responses', help='Mock HTTP responses JSON for CFP capture')
    parser.add_argument('--venue-sources-json', help='Pre-captured venue_sources_v1 JSON path')
    parser.add_argument('--out-dir', help='Directory to write scaffolded JSON files')
    parser.add_argument('--out', help='Path to write builder manifest JSON')
    parser.add_argument('--compact', action='store_true', help='Emit <4096B compact JSON summary')
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        topic_arg = _require_nonempty_arg(args.topic, '--topic')
        input_arg = _require_nonempty_arg(args.input, '--input')
        pdf_arg = _require_nonempty_arg(args.pdf, '--pdf')
        tex_arg = _require_nonempty_arg(args.tex, '--tex')
        venue_arg = _require_nonempty_arg(args.target_venue, '--target-venue')
        cfp_arg = _require_nonempty_arg(args.cfp_url, '--cfp-url')
        constraints_arg = _require_nonempty_arg(args.constraints_json, '--constraints-json')
        quality_dir = _require_nonempty_arg(args.quality_refs_dir, '--quality-refs-dir')
        mock_search_arg = _require_nonempty_arg(args.mock_search_json, '--mock-search-json')
        corpus_arg = _require_nonempty_arg(args.corpus_json, '--corpus-json')
        leads_arg = _require_nonempty_arg(args.offline_leads_json, '--offline-leads-json')
        panel_html_arg = _require_nonempty_arg(args.offline_panel_html, '--offline-panel-html')
        venue_resp_arg = _require_nonempty_arg(args.offline_venue_responses, '--offline-venue-responses')
        venue_src_arg = _require_nonempty_arg(args.venue_sources_json, '--venue-sources-json')
        out_dir_arg = _require_nonempty_arg(args.out_dir, '--out-dir')
        out_arg = _require_nonempty_arg(args.out, '--out')

        constraints_obj = _load_json(constraints_arg, '--constraints-json') if constraints_arg else None
        if constraints_obj is not None and not isinstance(constraints_obj, dict):
            raise ValueError('--constraints-json must be a JSON object')

        mock_search_obj = _load_json(mock_search_arg, '--mock-search-json') if mock_search_arg else None
        corpus_obj = _load_json(corpus_arg, '--corpus-json') if corpus_arg else None
        leads_obj = _load_json(leads_arg, '--offline-leads-json') if leads_arg else None
        venue_resp_obj = _load_json(venue_resp_arg, '--offline-venue-responses') if venue_resp_arg else None
        venue_src_obj = _load_json(venue_src_arg, '--venue-sources-json') if venue_src_arg else None

        sources_list: list[str] = []
        for s in (args.sources or []):
            for part in s.split(','):
                if part.strip():
                    sources_list.append(part.strip())
        eff_sources = tuple(sources_list) if sources_list else DEFAULT_SEARCH_SOURCES

        result = build_inputs(
            topic=topic_arg,
            input_path=input_arg,
            pdf_path=pdf_arg,
            tex_path=tex_arg,
            target_venue=venue_arg,
            venue_track=args.venue_track,
            venue_edition=args.venue_edition,
            cfp_url=cfp_arg,
            subfield_preset=args.subfield_preset,
            constraints=constraints_obj,
            budget_usd=args.budget_usd,
            gpu_budget=args.gpu_budget,
            deadline_window=args.deadline_window,
            user_timezone=args.user_timezone,
            sources=eff_sources,
            search_mode=args.search_mode,
            search_size=args.search_size,
            search_pages=args.search_pages,
            panel_source=args.panel_source,
            panel_venue_id=args.panel_venue_id,
            panel_limit=args.panel_limit,
            quality_refs_dir=quality_dir,
            offline=args.offline,
            mock_search_data=mock_search_obj,
            corpus_data=corpus_obj,
            offline_leads_data=leads_obj,
            offline_panel_html=panel_html_arg,
            offline_venue_responses=venue_resp_obj,
            venue_sources_bundle=venue_src_obj,
            out_dir=out_dir_arg,
        )

        manifest_out = {
            k: v for k, v in result.items()
            if k not in ('corpus', 'gap_record', 'scorecards', 'dossier')
        }
        if out_arg and not args.compact:
            op = Path(out_arg)
            op.parent.mkdir(parents=True, exist_ok=True)
            op.write_text(json.dumps(manifest_out, indent=2), encoding='utf-8')

        if args.compact:
            print(json.dumps(_compact_output(result, out_arg), ensure_ascii=False))
        else:
            print(json.dumps(manifest_out, indent=2, ensure_ascii=False))
        return 0
    except (OSError, UnicodeError, ValueError, TypeError, RuntimeError, json.JSONDecodeError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
