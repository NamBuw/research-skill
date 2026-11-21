#!/usr/bin/env python3
"""Collect OpenAlex publication-source leads and advisory venue-tier context.

Venue normalization, compact matching, and S/A/B/C/Unknown tier classification
rules are ported from yilaai/paper-quality-filter (scripts/rank_papers.py,
snapshot 679cdf3, MIT License, Copyright (c) 2026 yilaai). Raw upstream
journal_scores.json (Clarivate JCR/CAS metrics) is not redistributed verbatim
due to upstream data-source notes; supply --quality-refs-dir to load local
paper-quality-filter reference JSON files.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = 'https://api.openalex.org/works'

LEVEL_ORDER = {'S': 0, 'A': 1, 'B': 2, 'C': 3, 'Unknown': 4}
FRIENDLY_LEVEL_EN = {
    'S': 'Strongly Recommended',
    'A': 'Worth Keeping',
    'B': 'Supplementary',
    'C': 'Supplementary',
    'Unknown': 'Insufficient Venue Evidence',
}

PREPRINT_VENUES = {
    'arxiv',
    'arxiv cornell university',
    'biorxiv',
    'medrxiv',
    'ssrn',
    'ssrn electronic journal',
    'openreview',
    'chemrxiv',
    'research square',
    'techrxiv',
    'preprints',
    'corr',
    'computing research repository',
}

# Curated core AI/CS/CV/NLP venue CCF tiers strictly aligned to CCF 7th Edition (March 2026)
# ("中国计算机学会推荐国际学术会议和期刊目录第七版（2026年3月更新）"), fixing PDF-scraping
# truncations in upstream ccf_conferences.json (e.g. NeurIPS/NIPS/ICLR/IJCAI/AAAI keys),
# removing non-CCF venues (e.g. EACL/WACV/AACL/IMWUT), and disambiguating journal vs
# conference acronym collisions (WWW, FSE, ASE, CSCW).
_BUILTIN_CCF_VENUES: dict[str, str] = {
    # CCF A (tier S)
    'neurips': 'A',
    'nips': 'A',
    'neural information processing systems': 'A',
    'advances in neural information processing systems': 'A',
    'icml': 'A',
    'international conference on machine learning': 'A',
    'iclr': 'A',
    'international conference on learning representations': 'A',
    'aaai': 'A',
    'aaai conference on artificial intelligence': 'A',
    'acl': 'A',
    'annual meeting of the association for computational linguistics': 'A',
    'cvpr': 'A',
    'ieee/cvf computer vision and pattern recognition conference': 'A',
    'ieee/cvf conference on computer vision and pattern recognition': 'A',
    'conference on computer vision and pattern recognition': 'A',
    'iccv': 'A',
    'ieee/cvf international conference on computer vision': 'A',
    'international conference on computer vision': 'A',
    'kdd': 'A',
    'sigkdd': 'A',
    'acm sigkdd conference on knowledge discovery and data mining': 'A',
    'acm sigkdd international conference on knowledge discovery and data mining': 'A',
    'sigir': 'A',
    'www': 'A',
    'thewebconf': 'A',
    'the web conference': 'A',
    'international world wide web conference': 'A',
    'vldb': 'A',
    'pvldb': 'A',
    'proceedings of the vldb endowment': 'A',
    'sigmod': 'A',
    'icde': 'A',
    'icse': 'A',
    'international conference on software engineering': 'A',
    'fse': 'A',
    'esec/fse': 'A',
    'acm international conference on the foundations of software engineering': 'A',
    'ase': 'A',
    'international conference on automated software engineering': 'A',
    'issta': 'A',
    'fm': 'A',
    'osdi': 'A',
    'sosp': 'A',
    'eurosys': 'A',
    'usenix atc': 'A',
    'usenix annual technical conference': 'A',
    'acm sigops atc': 'A',
    'acm sigops annual technical conference': 'A',
    'fast': 'A',
    'usenix security': 'A',
    'usenix security symposium': 'A',
    'ccs': 'A',
    'acm ccs': 'A',
    'ieee s&p': 'A',
    'ieee symposium on security and privacy': 'A',
    'ndss': 'A',
    'chi': 'A',
    'uist': 'A',
    'cscw': 'A',
    'acm conference on computer-supported cooperative work and social computing': 'A',
    'ubicomp': 'A',
    'stoc': 'A',
    'focs': 'A',
    'soda': 'A',
    'popl': 'A',
    'pldi': 'A',
    'jmlr': 'A',
    'journal of machine learning research': 'A',
    'tpami': 'A',
    'ieee transactions on pattern analysis and machine intelligence': 'A',
    'ijcv': 'A',
    'international journal of computer vision': 'A',
    'tkde': 'A',
    'ieee transactions on knowledge and data engineering': 'A',
    'tois': 'A',
    'tods': 'A',
    'tse': 'A',
    'tosem': 'A',
    'tocs': 'A',
    'tifs': 'A',
    'tdsc': 'A',
    'tochi': 'A',
    'siggraph': 'A',
    'cav': 'A',
    'lics': 'A',
    'infocom': 'A',
    'sigcomm': 'A',
    'mobicom': 'A',
    'nsdi': 'A',
    'asplos': 'A',
    'isca': 'A',
    'micro': 'A',
    'hpca': 'A',
    'sc': 'A',
    'dac': 'A',
    'rtss': 'A',
    'crypto': 'A',
    'eurocrypt': 'A',
    'artificial intelligence': 'A',
    # CCF B (tier A)
    'ijcai': 'B',
    'international joint conference on artificial intelligence': 'B',
    'emnlp': 'B',
    'conference on empirical methods in natural language processing': 'B',
    'naacl': 'B',
    'naacl-hlt': 'B',
    'north american chapter of the association for computational linguistics': 'B',
    'conference of the north american chapter of the association for computational linguistics': 'B',
    'coling': 'B',
    'international conference on computational linguistics': 'B',
    'tacl': 'B',
    'transactions of the association for computational linguistics': 'B',
    'eccv': 'B',
    'european conference on computer vision': 'B',
    'colt': 'B',
    'annual conference on computational learning theory': 'B',
    'conference on learning theory': 'B',
    'uai': 'B',
    'conference on uncertainty in artificial intelligence': 'B',
    'uncertainty in artificial intelligence': 'B',
    'cikm': 'B',
    'wsdm': 'B',
    'icdm': 'B',
    'recsys': 'B',
    'aamas': 'B',
    'ecai': 'B',
    'icaps': 'B',
    'kr': 'B',
    'raid': 'B',
    'acsac': 'B',
    'esorics': 'B',
    'fast software encryption': 'B',
    'pods': 'B',
    'edbt': 'B',
    'dasfaa': 'B',
    'icalp': 'B',
    'concur': 'B',
    'socc': 'B',
    'conext': 'B',
    'imc': 'B',
    'icpp': 'B',
    'ipdps': 'B',
    'icws': 'B',
    'world wide web': 'B',
    'automated software engineering': 'B',
    'computer supported cooperative work': 'B',
    # CCF C (tier B)
    'aistats': 'C',
    'msr': 'C',
    'conll': 'C',
    'bmvc': 'C',
    'accv': 'C',
    'pakdd': 'C',
    'ecir': 'C',
    'icann': 'C',
    'ijcnn': 'C',
    'iconip': 'C',
    'pricai': 'C',
    'ictai': 'C',
    'acml': 'C',
    'compsac': 'C',
    'seke': 'C',
    'sac': 'C',
    'hpcc': 'C',
}


def normalize_venue_name(value: Any) -> str:
    text = str(value or '').strip().lower()
    text = re.sub(r'&', ' and ', text)
    text = re.sub(r"[\u2010-\u2015\-_/,:;()\[\]{}.!?\"'`]+", ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def compact_venue_name(value: Any) -> str:
    return re.sub(r'[^a-z0-9\u3400-\u9fff]+', '', normalize_venue_name(value))


def _min_level(current: str, candidate: str) -> str:
    return candidate if LEVEL_ORDER[candidate] < LEVEL_ORDER[current] else current


def _build_index(data: dict[str, Any], *, filter_scraped: bool = False) -> dict[str, tuple[str, Any]]:
    index: dict[str, tuple[str, Any]] = {}
    for key, value in data.items():
        if not isinstance(key, str):
            continue
        clean_key = key.strip()
        if filter_scraped:
            if clean_key.startswith('会议全称'):
                clean_key = clean_key[len('会议全称'):].strip()
            if not clean_key or len(clean_key) > 120:
                continue
        for candidate in (normalize_venue_name(clean_key), compact_venue_name(clean_key)):
            if candidate and candidate not in index:
                index[candidate] = (clean_key, value)
    return index


def _load_json_dict(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    return data if isinstance(data, dict) else {}


def load_venue_quality_refs(references_dir: str | Path | None = None) -> dict[str, Any]:
    explicit_dir = references_dir
    if explicit_dir is None:
        env_dir = os.environ.get('RESEARCH_SCIENTIST_VENUE_REFS_DIR')
        if env_dir and env_dir.strip():
            explicit_dir = env_dir.strip()

    builtin_ccf_index = _build_index(_BUILTIN_CCF_VENUES)
    if explicit_dir is None:
        return {
            'refs_mode': 'builtin_ccf_only',
            'builtin_ccf': builtin_ccf_index,
            'ccf': {},
            'journal': {},
            'ei': {},
            'chinese': {},
        }

    ref_path = Path(explicit_dir).expanduser().resolve()
    if not ref_path.is_dir():
        raise ValueError(f'quality refs directory not found: {explicit_dir}')

    ccf_raw = _load_json_dict(ref_path / 'ccf_conferences.json')
    journal_raw = _load_json_dict(ref_path / 'journal_scores.json')
    ei_raw = _load_json_dict(ref_path / 'eiiRankingName.json')
    chinese_raw = _load_json_dict(ref_path / 'chinese_journal_tags.json')

    return {
        'refs_mode': 'builtin_ccf_plus_external',
        'builtin_ccf': builtin_ccf_index,
        'ccf': _build_index(ccf_raw, filter_scraped=True),
        'journal': _build_index(journal_raw),
        'ei': _build_index(ei_raw),
        'chinese': _build_index(chinese_raw),
    }


_ORDINAL_WORDS_RE = re.compile(
    r'^(?:(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)\s+)?'
    r'(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|'
    r'eleventh|twelfth|thirteenth|fourteenth|fifteenth|sixteenth|'
    r'seventeenth|eighteenth|nineteenth|twentieth|thirtieth|fortieth|fiftieth)\s+'
)
_SECONDARY_TRACK_RE = re.compile(
    r'\b(?:workshops?|findings|tutorials?|demos?|demonstrations?|companions?|'
    r'doctoral\s+(?:consortium|symposium)|adjunct|co[-\s]?located|'
    r'extended\s+abstracts?|posters?|srw|industry\s+track|'
    r'datasets?\s+and\s+benchmarks?|position\s+papers?|'
    r'pre[-\s]?conference\s+symposium)\b',
    re.IGNORECASE,
)


def _venue_lookup_candidates(name: str) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _add(kind: str, probe: str) -> None:
        if probe and (kind, probe) not in seen:
            seen.add((kind, probe))
            candidates.append((kind, probe))

    norm = normalize_venue_name(name)
    comp = compact_venue_name(name)
    _add('normalized', norm)
    _add('compact', comp)

    is_secondary_track = bool(_SECONDARY_TRACK_RE.search(norm))
    if not is_secondary_track:
        paren_stripped = normalize_venue_name(re.sub(r'\([^()]*\)', ' ', name))
        if paren_stripped and paren_stripped != norm:
            _add('normalized', paren_stripped)
            _add('compact', compact_venue_name(paren_stripped))

        for paren_match in re.finditer(r'\(([^()]{2,40})\)', name):
            inner = paren_match.group(1).strip()
            if re.fullmatch(r'(?:19|20)\d{2}', inner):
                continue
            inner_norm = normalize_venue_name(inner)
            inner_comp = compact_venue_name(inner)
            _add('parenthetical_acronym', inner_norm)
            _add('parenthetical_acronym', inner_comp)
            inner_clean = re.sub(r'\b(?:19|20)\d{2}\b', ' ', inner_norm)
            inner_clean = re.sub(r'(?<=[a-z])(?:19|20)\d{2}\b', '', inner_clean)
            inner_clean = re.sub(r'\s+\d{2}$', '', inner_clean)
            inner_clean = re.sub(r'\s+', ' ', inner_clean).strip()
            if inner_clean and inner_clean != inner_norm:
                _add('parenthetical_acronym', inner_clean)
                _add('parenthetical_acronym', compact_venue_name(inner_clean))

        stripped = normalize_venue_name(re.sub(r'\([^()]*\)', ' ', name))
        stripped = re.sub(r'\b(?:19|20)\d{2}\b', ' ', stripped)
        stripped = re.sub(r'\s+', ' ', stripped).strip()
        stripped = re.sub(
            r'^(?:proceedings\s+of\s+the|proceedings\s+of|advances\s+in)\s+',
            '',
            stripped,
        )
        stripped = re.sub(r'^\d+(?:st|nd|rd|th)\s+', '', stripped)
        stripped = _ORDINAL_WORDS_RE.sub('', stripped)
        stripped = re.sub(r'\s+\d{1,3}$', '', stripped)
        stripped = re.sub(r'\s+', ' ', stripped).strip()
        if stripped and stripped != norm:
            _add('proceedings_stripped', stripped)
            _add('proceedings_stripped', compact_venue_name(stripped))

    return candidates


def _is_preprint_venue(name: str) -> bool:
    norm = normalize_venue_name(name)
    comp = compact_venue_name(name)
    stripped_paren = normalize_venue_name(re.sub(r'\([^()]*\)', ' ', name))
    for candidate in (norm, comp, stripped_paren):
        if candidate in PREPRINT_VENUES:
            return True
    if norm.startswith(('arxiv ', 'biorxiv ', 'medrxiv ', 'chemrxiv ', 'techrxiv ', 'ssrn ')):
        return True
    tokens = norm.split()
    if 'preprint' in tokens and any(p in tokens for p in ('arxiv', 'biorxiv', 'medrxiv', 'chemrxiv', 'techrxiv', 'ssrn', 'openreview')):
        return True
    if 'ssrn' in tokens and 'working' in tokens and 'paper' in tokens:
        return True
    return False


def _probe_table(table: dict[str, tuple[str, Any]], candidates: list[tuple[str, str]]) -> tuple[str, str, Any] | None:
    if not table:
        return None
    for match_type, probe in candidates:
        if probe in table:
            matched_name, value = table[probe]
            return match_type, matched_name, value
    return None


def lookup_venue_quality(venue_name: str | None, refs: dict[str, Any] | None = None) -> dict[str, Any]:
    if refs is None:
        refs = load_venue_quality_refs(None)
    raw = str(venue_name or '').strip()
    if not raw:
        return {
            'quality_tier': 'Unknown',
            'recommendation': FRIENDLY_LEVEL_EN['Unknown'],
            'evidence': [],
            'matched_source': '',
            'matched_name': '',
            'match_type': 'unmatched',
            'quality_score': -1.0,
            'confidence': 'low',
            'advisory_only': True,
        }

    if _is_preprint_venue(raw):
        return {
            'quality_tier': 'Unknown',
            'recommendation': FRIENDLY_LEVEL_EN['Unknown'],
            'evidence': ['preprint-only source'],
            'matched_source': '',
            'matched_name': '',
            'match_type': 'preprint_excluded',
            'quality_score': -1.0,
            'confidence': 'low',
            'advisory_only': True,
        }

    candidates = _venue_lookup_candidates(raw)
    evidence: list[str] = []
    matched_source = ''
    matched_name = ''
    match_type = 'unmatched'
    level = 'Unknown'
    score = -1.0

    builtin_ccf = refs.get('builtin_ccf', {})
    external_ccf = refs.get('ccf', {})
    ccf_hit = None
    ccf_source = ''
    for hit_type, probe in candidates:
        if probe in builtin_ccf:
            hit_name, rank = builtin_ccf[probe]
            ccf_hit = (hit_type, hit_name, rank)
            ccf_source = 'builtin_ccf'
            break
        if probe in external_ccf:
            hit_name, rank = external_ccf[probe]
            ccf_hit = (hit_type, hit_name, rank)
            ccf_source = 'ccf_conferences'
            break

    if ccf_hit is not None:
        hit_type, hit_name, rank = ccf_hit
        rank_text = str(rank).strip().upper()
        if rank_text in ('A', 'B', 'C'):
            matched_source = ccf_source
            matched_name = hit_name
            match_type = hit_type
            evidence.append(f'CCF {rank_text}')
            if rank_text == 'A':
                level, score = 'S', max(score, 120.0)
            elif rank_text == 'B':
                level, score = 'A', max(score, 90.0)
            elif rank_text == 'C':
                level, score = 'B', max(score, 60.0)

    journal_hit = _probe_table(refs.get('journal', {}), candidates)
    if journal_hit is not None:
        hit_type, hit_name, info = journal_hit
        matched_source = matched_source or 'journal_scores'
        matched_name = matched_name or hit_name
        if match_type == 'unmatched':
            match_type = hit_type
        info = info if isinstance(info, dict) else {}
        quartile = str(info.get('quartile') or '').upper()
        impact_factor = info.get('if')
        zone = info.get('csa_zone')
        if quartile:
            evidence.append(f'JCR {quartile}')
        if impact_factor not in (None, ''):
            evidence.append(f'IF {impact_factor}')
        if zone not in (None, ''):
            evidence.append(f'CAS Zone {zone}')
        try:
            impact_value = float(impact_factor)
        except (TypeError, ValueError):
            impact_value = 0.0
        try:
            zone_value = int(zone)
        except (TypeError, ValueError):
            zone_value = 0
        if zone_value == 1 or (quartile == 'Q1' and impact_value >= 10):
            level, score = _min_level(level, 'S'), max(score, 110.0 + impact_value)
        elif quartile == 'Q1' or zone_value == 2 or impact_value >= 5:
            level, score = _min_level(level, 'A'), max(score, 80.0 + impact_value)
        elif quartile == 'Q2':
            level, score = _min_level(level, 'B'), max(score, 55.0 + impact_value)
        else:
            level, score = _min_level(level, 'C'), max(score, impact_value)

    ei_hit = _probe_table(refs.get('ei', {}), candidates)
    if ei_hit is not None:
        hit_type, hit_name, _ = ei_hit
        matched_source = matched_source or 'eiiRankingName'
        matched_name = matched_name or hit_name
        if match_type == 'unmatched':
            match_type = hit_type
        evidence.append('EI')
        level, score = _min_level(level, 'B'), max(score, 50.0)

    chinese_hit = _probe_table(refs.get('chinese', {}), candidates)
    if chinese_hit is not None:
        hit_type, hit_name, raw_tags = chinese_hit
        matched_source = matched_source or 'chinese_journal_tags'
        matched_name = matched_name or hit_name
        if match_type == 'unmatched':
            match_type = hit_type
        tags = raw_tags if isinstance(raw_tags, list) else [raw_tags]
        evidence.extend(str(tag) for tag in tags if str(tag).strip())
        level, score = _min_level(level, 'B'), max(score, 48.0)

    dedup_evidence = list(dict.fromkeys(evidence))
    return {
        'quality_tier': level,
        'recommendation': FRIENDLY_LEVEL_EN[level],
        'evidence': dedup_evidence,
        'matched_source': matched_source,
        'matched_name': matched_name,
        'match_type': match_type,
        'quality_score': score,
        'confidence': 'high' if matched_source else 'low',
        'advisory_only': True,
    }


def fetch(params, timeout=20):
    headers = {'Accept': 'application/json', 'User-Agent': 'ResearchScientistSkill/2.1 (venue-leads)'}
    if os.environ.get('OPENALEX_API_KEY'):
        headers['Authorization'] = 'Bearer ' + os.environ['OPENALEX_API_KEY']
    try:
        with urlopen(Request(API + '?' + urlencode(params), headers=headers), timeout=timeout) as response:
            result = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f'http_{exc.code}') from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError('network_failure') from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError('invalid_json') from exc
    if not isinstance(result, dict):
        raise RuntimeError('unexpected_body')
    return result


def collect(query, pages=1, page_size=25, transport=fetch, quality_refs_dir=None):
    if not isinstance(query, str) or not query.strip() or len(query) > 500:
        raise ValueError('query must contain 1..500 nonblank characters')
    if not 1 <= pages <= 5 or not 1 <= page_size <= 100:
        raise ValueError('pages must be 1..5 and page_size 1..100')
    refs = load_venue_quality_refs(quality_refs_dir)
    output = {
        'query': query,
        'checked_at_utc': datetime.now(timezone.utc).isoformat(),
        'status': 'unchecked',
        'pages_read': 0,
        'reported_total': None,
        'related_works_read_as_metadata': 0,
        'source_leads': [],
        'works_without_primary_source': 0,
    }
    groups, seen_pages, seen_works = {}, set(), set()
    for page in range(1, pages + 1):
        try:
            data = transport({'search': query, 'per_page': page_size, 'page': page})
            raw = data.get('results')
            count = (data.get('meta') or {}).get('count')
            if not isinstance(raw, list) or not isinstance(count, int) or count < 0:
                raise RuntimeError('invalid_page')
            signature = tuple(w.get('id') for w in raw if isinstance(w, dict))
            if signature and signature in seen_pages:
                output['status'] = 'repeated_page'
                break
            seen_pages.add(signature)
            output['pages_read'] += 1
            output['reported_total'] = count
            for work in raw:
                if not isinstance(work, dict) or not isinstance(work.get('id'), str) or work['id'] in seen_works:
                    continue
                seen_works.add(work['id'])
                location = work.get('primary_location')
                source = location.get('source') if isinstance(location, dict) else None
                if not isinstance(source, dict) or not isinstance(source.get('id'), str):
                    output['works_without_primary_source'] += 1
                    continue
                source_id = source['id']
                row = groups.setdefault(
                    source_id,
                    {
                        'source_id': source_id,
                        'name': source.get('display_name'),
                        'source_type': source.get('type'),
                        'related_work_ids': [],
                        'years': [],
                    },
                )
                row['related_work_ids'].append(work['id'])
                if isinstance(work.get('publication_year'), int):
                    row['years'].append(work['publication_year'])
            output['status'] = 'valid_zero_results' if count == 0 else (
                'bounded_partial' if len(seen_works) < count else 'complete'
            )
            if not raw or len(seen_works) >= count:
                break
        except RuntimeError as exc:
            output['status'] = str(exc) if not output['pages_read'] else 'partial_' + str(exc)
            break
    output['related_works_read_as_metadata'] = len(seen_works)
    matched = 0
    for row in groups.values():
        row['sample_count'] = len(row['related_work_ids'])
        row['sample_year_range'] = [min(row['years']), max(row['years'])] if row['years'] else None
        del row['years']
        quality = lookup_venue_quality(row.get('name'), refs)
        row['venue_quality'] = quality
        if quality['matched_source']:
            matched += 1
    output['source_leads'] = sorted(groups.values(), key=lambda x: (-x['sample_count'], str(x['name']), x['source_id']))
    total_leads = len(output['source_leads'])
    output['venue_quality_coverage'] = {
        'matched': matched,
        'unmatched': total_leads - matched,
        'match_rate': round((matched / total_leads * 100), 1) if total_leads else 0.0,
        'refs_mode': refs['refs_mode'],
    }
    output['warning'] = (
        'Metadata-frequency leads only: OpenAlex search ranking and primary-location coverage bias this sample. '
        'A source is not an eligible submission venue merely because it hosted a related work. '
        'Verify official current CFP/aims, edition, track, dates, policy, cost and manuscript fit before recommendation.'
        ' Local venue-tier tags are reading-priority signals only; Insufficient Venue Evidence never means low quality,'
        ' and top tier never establishes scope, track, or CFP eligibility.'
    )
    return output


def _compact_output(result: dict[str, Any], out_path: str | None = None) -> dict[str, Any]:
    leads = result.get('source_leads') or []
    return {
        'compact': True,
        'query': result.get('query'),
        'status': result.get('status'),
        'pages_read': result.get('pages_read'),
        'reported_total': result.get('reported_total'),
        'lead_count': len(leads),
        'venue_quality_coverage': result.get('venue_quality_coverage'),
        'top_leads': [
            {
                'source_id': row.get('source_id'),
                'name': row.get('name'),
                'source_type': row.get('source_type'),
                'sample_count': row.get('sample_count'),
                'quality_tier': (row.get('venue_quality') or {}).get('quality_tier'),
            }
            for row in leads[:10]
        ],
        'artifact_path': out_path,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('query')
    parser.add_argument('--pages', type=int, default=1)
    parser.add_argument('--page-size', type=int, default=25)
    parser.add_argument(
        '--quality-refs-dir',
        default=None,
        help='Optional directory containing paper-quality-filter reference JSON files',
    )
    parser.add_argument('--out', default=None, help='Optional output JSON file path for full report')
    parser.add_argument('--compact', action='store_true', help='Emit compact bounded summary JSON to stdout')
    args = parser.parse_args(argv)
    try:
        result = collect(args.query, args.pages, args.page_size, quality_refs_dir=args.quality_refs_dir)
        full_rendered = json.dumps(result, ensure_ascii=False)
        out_str = None
        if args.out:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(full_rendered + '\n', encoding='utf-8')
            out_str = str(out_path)
        if args.compact:
            print(json.dumps(_compact_output(result, out_str), ensure_ascii=False))
        else:
            print(full_rendered)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
