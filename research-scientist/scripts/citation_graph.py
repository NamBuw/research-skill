#!/usr/bin/env python3
"""Multi-seed OpenAlex/Crossref citation graph expansion and co-citation clustering.

Adapted from:
- research-paper-lifecycle-skills (Apache-2.0): multi-seed degree ranking, Crossref reference fallback,
  and COMPLETE vs PARTIAL coverage reporting.
- scipip (MIT): UnionFind, complete-linkage can_merge, CoCite matrix, and cluster-diverse selection.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from urllib.parse import quote

_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from citation_trails import BASE as OA_WORKS_BASE
from citation_trails import extract_wid, polite_get

CR_WORKS_BASE = 'https://api.crossref.org/works'
OA_BATCH = 25
WORD_RE = re.compile(r'[a-z0-9]{2,}')
ARXIV_RE = re.compile(r'^(?:https?://arxiv\.org/(?:abs|pdf)/|arxiv:)?(\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+(?:\.[a-z-]+)?/\d{7}(?:v\d+)?)$', re.I)
DOI_RE = re.compile(r'^(?:https?://(?:dx\.)?doi\.org/|doi:)?(10\.\d{4,9}/\S+)$', re.I)


class UnionFind:
    """Disjoint-set structure with path compression and union by rank (scipip, MIT)."""

    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            nxt = self.parent[x]
            self.parent[x] = root
            x = nxt
        return root

    def union(self, x: int, y: int) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self.rank[rx] < self.rank[ry]:
            self.parent[rx] = ry
        elif self.rank[rx] > self.rank[ry]:
            self.parent[ry] = rx
        else:
            self.parent[ry] = rx
            self.rank[rx] += 1


def can_merge(uf: UnionFind, sim_matrix: list[list[float]], i: int, j: int, threshold: float) -> bool:
    """Complete-linkage merge guard: every pair across clusters must meet threshold (scipip, MIT)."""
    ri, rj = uf.find(i), uf.find(j)
    if ri == rj:
        return True
    members_i = [idx for idx in range(len(sim_matrix)) if uf.find(idx) == ri]
    members_j = [idx for idx in range(len(sim_matrix)) if uf.find(idx) == rj]
    for a in members_i:
        row = sim_matrix[a]
        for b in members_j:
            if row[b] < threshold:
                return False
    return True


def build_cocite_map(edges_by_seed: dict[str, set[str]]) -> dict[str, dict[str, int]]:
    """Build symmetric co-citation/co-reference count matrix across seed neighborhoods (scipip, MIT)."""
    comap: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for neighbor_ids in edges_by_seed.values():
        ordered = sorted(neighbor_ids)
        for a, b in combinations(ordered, 2):
            comap[a][b] += 1
            comap[b][a] += 1
    return {k: dict(v) for k, v in comap.items()}


def _title_tokens(title: str | None) -> set[str]:
    if not isinstance(title, str):
        return set()
    return set(WORD_RE.findall(title.lower()))


def _cosine_dict(vec_a: dict[str, int | float], vec_b: dict[str, int | float]) -> float:
    if not vec_a or not vec_b:
        return 0.0
    dot = sum(val * vec_b.get(key, 0.0) for key, val in vec_a.items())
    if dot <= 0.0:
        return 0.0
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def cluster_neighbors(
    neighbors: list[dict],
    cocite_map: dict[str, dict[str, int]],
    threshold: float = 0.25,
) -> tuple[list[dict], list[dict]]:
    """Cluster neighbor works using CoCite cosine + title Jaccard + complete-linkage UnionFind."""
    n = len(neighbors)
    if n == 0:
        return [], []
    ids = [item['openalex_id'] for item in neighbors]
    title_sets = [_title_tokens(item.get('title')) for item in neighbors]
    sim_matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        sim_matrix[i][i] = 1.0
        vec_i = cocite_map.get(ids[i], {})
        ti = title_sets[i]
        for j in range(i + 1, n):
            vec_j = cocite_map.get(ids[j], {})
            cocite_sim = _cosine_dict(vec_i, vec_j)
            # Also grant direct co-occurrence boost when neighbors directly co-occur in cocite_map
            if ids[j] in vec_i:
                cocite_sim = max(cocite_sim, 0.5)
            tj = title_sets[j]
            if ti and tj:
                union_len = len(ti | tj)
                title_sim = len(ti & tj) / union_len if union_len else 0.0
            else:
                title_sim = 0.0
            sim = 0.6 * cocite_sim + 0.4 * title_sim
            sim_matrix[i][j] = sim
            sim_matrix[j][i] = sim

    uf = UnionFind(n)
    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            if sim_matrix[i][j] >= threshold:
                pairs.append((sim_matrix[i][j], i, j))
    pairs.sort(key=lambda x: (-x[0], x[1], x[2]))
    for _, i, j in pairs:
        if can_merge(uf, sim_matrix, i, j, threshold):
            uf.union(i, j)

    groups: dict[int, list[int]] = defaultdict(list)
    for idx in range(n):
        groups[uf.find(idx)].append(idx)

    # Assign deterministic cluster IDs ordered by best member rank
    ordered_roots = sorted(groups.keys(), key=lambda r: min(groups[r]))
    root_to_cid = {root: f'C{k + 1}' for k, root in enumerate(ordered_roots)}
    clusters_summary = []
    for root in ordered_roots:
        cid = root_to_cid[root]
        members = groups[root]
        for idx in members:
            neighbors[idx]['cluster_id'] = cid
        clusters_summary.append({
            'cluster_id': cid,
            'size': len(members),
            'member_ids': [neighbors[idx]['openalex_id'] for idx in members],
        })
    return neighbors, clusters_summary


def _cr_get(url: str, params: dict | None = None, timeout: int = 20):
    return polite_get(url, params=params, timeout=timeout, min_interval=0.5)


def _normalize_doi(value: str | None) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    val = value.strip()
    val = re.sub(r'^https?://(?:dx\.)?doi\.org/', '', val, flags=re.I)
    val = re.sub(r'^doi:', '', val, flags=re.I)
    return val.lower() or None


def _resolve_single_seed(raw_seed: str | dict, oa_transport) -> tuple[dict | None, str | None]:
    if isinstance(raw_seed, dict):
        candidate = (
            raw_seed.get('openalex_id')
            or raw_seed.get('id')
            or raw_seed.get('doi')
            or raw_seed.get('arxiv_id')
            or raw_seed.get('title')
            or ''
        )
        seed_str = str(candidate).strip()
    else:
        seed_str = str(raw_seed).strip()
    if not seed_str:
        return None, 'empty_seed'

    select = 'id,title,display_name,doi,publication_year,referenced_works,cited_by_count'
    wid = extract_wid(seed_str)
    try:
        if wid:
            data = oa_transport(f'{OA_WORKS_BASE}/{wid}', {'select': select})
            work = data
        else:
            doi_match = DOI_RE.match(seed_str)
            arxiv_match = ARXIV_RE.match(seed_str) if not doi_match else None
            if doi_match:
                doi = doi_match.group(1).lower()
                data = oa_transport(f'{OA_WORKS_BASE}/doi:{quote(doi, safe="")}', {'select': select})
                work = data
            elif arxiv_match:
                bare = re.sub(r'v\d+$', '', arxiv_match.group(1), flags=re.I).lower()
                data = oa_transport(f'{OA_WORKS_BASE}/doi:10.48550/arxiv.{bare}', {'select': select})
                work = data
            else:
                data = oa_transport(OA_WORKS_BASE, {'filter': f'title.search:{seed_str}', 'per_page': 1, 'select': select})
                results = data.get('results') if isinstance(data, dict) else None
                work = results[0] if isinstance(results, list) and results else None
                if work is None:
                    return None, 'seed_not_found'
    except RuntimeError as exc:
        return None, str(exc)

    if not isinstance(work, dict) or not extract_wid(work.get('id', '')):
        return None, 'invalid_seed_work'
    return work, None


def _crossref_reference_wids(doi: str, oa_transport, cr_transport) -> tuple[list[str], list[str]]:
    errors = []
    norm_doi = _normalize_doi(doi)
    if not norm_doi:
        return [], errors
    try:
        cr_data = cr_transport(f'{CR_WORKS_BASE}/{quote(norm_doi, safe="")}', None)
    except RuntimeError as exc:
        return [], [f'crossref_fallback:{norm_doi}:{exc}']
    msg = cr_data.get('message') if isinstance(cr_data, dict) else None
    refs = msg.get('reference') if isinstance(msg, dict) else None
    if not isinstance(refs, list):
        return [], errors
    ref_dois = []
    seen = set()
    for ref in refs:
        if isinstance(ref, dict) and isinstance(ref.get('DOI'), str):
            d = _normalize_doi(ref['DOI'])
            if d and d not in seen:
                seen.add(d)
                ref_dois.append(d)
    wids = []
    for i in range(0, len(ref_dois), OA_BATCH):
        chunk = ref_dois[i:i + OA_BATCH]
        try:
            filter_val = 'doi:' + '|'.join(chunk)
            oa_data = oa_transport(
                OA_WORKS_BASE,
                {'filter': filter_val, 'per_page': OA_BATCH, 'select': 'id,doi'},
            )
            for item in (oa_data.get('results') or []):
                if isinstance(item, dict):
                    w = extract_wid(item.get('id', ''))
                    if w:
                        wids.append(w)
        except RuntimeError as exc:
            errors.append(f'crossref_oa_batch:{exc}')
    return wids, errors


def build_citation_graph(
    seeds: list[str | dict],
    direction: str = 'both',
    top: int = 25,
    min_overlap: int = 1,
    cites_per_seed: int = 50,
    similarity_threshold: float = 0.25,
    cluster_diverse: bool = False,
    oa_transport=None,
    cr_transport=None,
) -> dict:
    if direction not in ('refs', 'cites', 'both'):
        raise ValueError("direction must be 'refs', 'cites', or 'both'")
    if not isinstance(top, int) or isinstance(top, bool) or top < 1:
        raise ValueError('top must be >= 1')
    if not isinstance(min_overlap, int) or isinstance(min_overlap, bool) or min_overlap < 1:
        raise ValueError('min_overlap must be >= 1')
    if not isinstance(cites_per_seed, int) or isinstance(cites_per_seed, bool) or not 1 <= cites_per_seed <= 100:
        raise ValueError('cites_per_seed must be 1..100')
    if not 0.0 <= float(similarity_threshold) <= 1.0:
        raise ValueError('similarity_threshold must be 0.0..1.0')
    if not seeds:
        raise ValueError('at least one seed is required')

    oa_fn = oa_transport or polite_get
    cr_fn = cr_transport or _cr_get

    partial_reasons: list[str] = []
    providers = {'openalex': 'ok', 'crossref_fallback': 'not_used'}
    seeds_resolved = []
    seeds_unresolved = []

    resolved_works = []
    for raw_seed in seeds:
        work, err = _resolve_single_seed(raw_seed, oa_fn)
        if work is None:
            seeds_unresolved.append({'seed': raw_seed, 'error': err})
            partial_reasons.append(f'seed_unresolved:{raw_seed}:{err}')
            if err and ('http_' in err or err == 'network_failure'):
                providers['openalex'] = 'partial'
        else:
            wid = extract_wid(work['id'])
            resolved_works.append((wid, work))
            seeds_resolved.append({
                'requested': raw_seed,
                'openalex_id': wid,
                'doi': _normalize_doi(work.get('doi')),
                'title': work.get('title') or work.get('display_name'),
                'year': work.get('publication_year'),
            })

    seed_wid_set = {wid for wid, _ in resolved_works}
    neighbors: dict[str, dict] = {}
    edges_by_seed: dict[str, set[str]] = defaultdict(set)

    def _touch_neighbor(wid: str, seed_wid: str, relation: str, meta: dict | None = None):
        if wid in seed_wid_set:
            return
        entry = neighbors.get(wid)
        if entry is None:
            entry = {
                'openalex_id': wid,
                'doi': None,
                'title': None,
                'year': None,
                'global_citations': None,
                'seed_ids': [],
                'edges': [],
                'co_cited_with': [],
            }
            neighbors[wid] = entry
        if meta:
            if not entry['doi'] and meta.get('doi'):
                entry['doi'] = _normalize_doi(meta.get('doi'))
            if not entry['title'] and (meta.get('title') or meta.get('display_name')):
                entry['title'] = meta.get('title') or meta.get('display_name')
            if entry['year'] is None and meta.get('publication_year') is not None:
                entry['year'] = meta.get('publication_year')
            if entry['global_citations'] is None and meta.get('cited_by_count') is not None:
                entry['global_citations'] = meta.get('cited_by_count')
        if seed_wid not in entry['seed_ids']:
            entry['seed_ids'].append(seed_wid)
        edge = {'seed_id': seed_wid, 'relation': relation}
        if edge not in entry['edges']:
            entry['edges'].append(edge)
        edges_by_seed[seed_wid].add(wid)

    for seed_wid, work in resolved_works:
        if direction in ('refs', 'both'):
            ref_list = work.get('referenced_works')
            if isinstance(ref_list, list) and ref_list:
                for ref in ref_list:
                    rwid = extract_wid(ref) if isinstance(ref, str) else None
                    if rwid:
                        _touch_neighbor(rwid, seed_wid, 'ref')
            elif work.get('doi'):
                if providers['crossref_fallback'] == 'not_used':
                    providers['crossref_fallback'] = 'used'
                cr_wids, cr_errs = _crossref_reference_wids(work['doi'], oa_fn, cr_fn)
                for err in cr_errs:
                    partial_reasons.append(err)
                    providers['crossref_fallback'] = 'partial'
                for rwid in cr_wids:
                    _touch_neighbor(rwid, seed_wid, 'ref')

        if direction in ('cites', 'both'):
            try:
                cites_data = oa_fn(
                    OA_WORKS_BASE,
                    {
                        'filter': f'cites:{seed_wid}',
                        'per_page': cites_per_seed,
                        'select': 'id,title,display_name,doi,publication_year,cited_by_count',
                    },
                )
                cites_results = cites_data.get('results')
                if not isinstance(cites_results, list):
                    raise RuntimeError('missing_result_list')
                meta = cites_data.get('meta') if isinstance(cites_data.get('meta'), dict) else {}
                total_cites = meta.get('count')
                if isinstance(total_cites, int) and total_cites > len(cites_results):
                    partial_reasons.append(f'cites_capped:{seed_wid}:{len(cites_results)}/{total_cites}')
                for item in cites_results:
                    if isinstance(item, dict):
                        cwid = extract_wid(item.get('id', ''))
                        if cwid:
                            _touch_neighbor(cwid, seed_wid, 'cite', meta=item)
            except RuntimeError as exc:
                partial_reasons.append(f'cites_failed:{seed_wid}:{exc}')
                providers['openalex'] = 'partial'

    # Filter survivors by min_overlap
    survivors = []
    for wid, entry in neighbors.items():
        entry['seed_overlap_count'] = len(entry['seed_ids'])
        if entry['seed_overlap_count'] >= min_overlap:
            survivors.append(entry)

    # Batch-resolve metadata for refs neighbors missing title/year/citations
    missing_meta_wids = [item['openalex_id'] for item in survivors if item['title'] is None]
    for i in range(0, len(missing_meta_wids), OA_BATCH):
        chunk = missing_meta_wids[i:i + OA_BATCH]
        try:
            batch_data = oa_fn(
                OA_WORKS_BASE,
                {
                    'filter': 'ids.openalex:' + '|'.join(chunk),
                    'per_page': OA_BATCH,
                    'select': 'id,title,display_name,doi,publication_year,cited_by_count',
                },
            )
            by_wid = {}
            for item in (batch_data.get('results') or []):
                if isinstance(item, dict):
                    w = extract_wid(item.get('id', ''))
                    if w:
                        by_wid[w] = item
            for entry in survivors:
                meta = by_wid.get(entry['openalex_id'])
                if meta:
                    entry['doi'] = entry['doi'] or _normalize_doi(meta.get('doi'))
                    entry['title'] = entry['title'] or meta.get('title') or meta.get('display_name')
                    if entry['year'] is None:
                        entry['year'] = meta.get('publication_year')
                    if entry['global_citations'] is None:
                        entry['global_citations'] = meta.get('cited_by_count')
        except RuntimeError as exc:
            partial_reasons.append(f'neighbor_meta_batch_failed:{exc}')
            providers['openalex'] = 'partial'

    # Build CoCite map over all seed edges (restricted to survivors for co_cited_with)
    survivor_ids = {item['openalex_id'] for item in survivors}
    filtered_edges = {sid: (wids & survivor_ids) for sid, wids in edges_by_seed.items()}
    cocite_map = build_cocite_map(filtered_edges)
    for item in survivors:
        peers = cocite_map.get(item['openalex_id'], {})
        item['co_cited_with'] = sorted(peers.keys(), key=lambda pid: (-peers[pid], pid))[:10]

    # Sort deterministically by seed_overlap_count desc, global_citations desc, openalex_id asc
    survivors.sort(key=lambda x: (-x['seed_overlap_count'], -(x['global_citations'] or 0), x['openalex_id']))

    # Cluster with SciPIP complete-linkage UnionFind
    survivors, clusters = cluster_neighbors(survivors, cocite_map, threshold=float(similarity_threshold))

    if cluster_diverse and clusters:
        buckets: dict[str, list[dict]] = defaultdict(list)
        for item in survivors:
            buckets[item['cluster_id']].append(item)
        selected = []
        cluster_order = [c['cluster_id'] for c in clusters]
        while len(selected) < top:
            progressed = False
            for cid in cluster_order:
                if buckets[cid]:
                    selected.append(buckets[cid].pop(0))
                    progressed = True
                    if len(selected) >= top:
                        break
            if not progressed:
                break
    else:
        selected = survivors[:top]

    status = 'COMPLETE' if (not partial_reasons and len(seeds_unresolved) == 0) else 'PARTIAL'
    return {
        'schema': 'research_scientist_citation_graph_v1',
        'checked_at_utc': datetime.now(timezone.utc).isoformat(),
        'direction': direction,
        'status': status,
        'partial_reasons': partial_reasons,
        'providers': providers,
        'seeds_requested': len(seeds),
        'seeds_resolved': seeds_resolved,
        'seeds_unresolved': seeds_unresolved,
        'neighbors_total': len(survivors),
        'clusters': clusters,
        'results': selected,
        'warning': (
            'Citation graph neighbors are discovery leads ranked by multi-seed overlap. '
            'OpenAlex referenced_works and capped citing sets can omit printed references or recent citations; '
            'read full texts before judging novelty.'
        ),
    }


def parse_seeds_input(seeds_arg: str | None, extra_seeds: list[str] | None = None) -> list[str | dict]:
    collected: list[str | dict] = []
    if seeds_arg:
        if seeds_arg == '-':
            raw = sys.stdin.read().strip()
        else:
            p = Path(seeds_arg).expanduser()
            if p.is_file():
                raw = p.read_text(encoding='utf-8').strip()
            else:
                raw = seeds_arg.strip()
        if raw.startswith('[') or raw.startswith('{'):
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                collected.extend(parsed)
            elif isinstance(parsed, dict):
                for key in ('seeds', 'known_seeds', 'combined_results', 'results', 'records'):
                    if isinstance(parsed.get(key), list):
                        collected.extend(parsed[key])
                        break
                else:
                    collected.append(parsed)
        else:
            for part in re.split(r'[,\n]+', raw):
                if part.strip():
                    collected.append(part.strip())
    if extra_seeds:
        for item in extra_seeds:
            if item.strip():
                collected.append(item.strip())
    if not collected:
        raise ValueError('no seeds provided')
    return collected


def _auto_artifact_path(prefix: str) -> Path:
    art_dir = Path(tempfile.gettempdir()) / 'research_scientist_artifacts'
    art_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f'{prefix}_', suffix='.json', dir=str(art_dir))
    os.close(fd)
    return Path(tmp_name).resolve()


def compact_graph_summary(report: dict, artifact_path: Path) -> dict:
    top_neighbors = [
        {
            'openalex_id': item.get('openalex_id'),
            'title': item.get('title'),
            'year': item.get('year'),
            'seed_overlap_count': item.get('seed_overlap_count'),
            'global_citations': item.get('global_citations'),
            'cluster_id': item.get('cluster_id'),
        }
        for item in report.get('results', [])[:10]
    ]
    return {
        'compact': True,
        'schema': report.get('schema'),
        'artifact_path': str(artifact_path),
        'status': report.get('status'),
        'partial_reasons': report.get('partial_reasons', []),
        'seeds_resolved': report.get('seeds_resolved', []),
        'seeds_unresolved': report.get('seeds_unresolved', []),
        'neighbors_total': report.get('neighbors_total', 0),
        'clusters_count': len(report.get('clusters', [])),
        'top_neighbors': top_neighbors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds', help='JSON file path, "-", inline JSON, or comma-separated IDs/DOIs/titles')
    parser.add_argument('--seed', action='append', help='Repeatable single seed (W-ID, DOI, arXiv, or title)')
    parser.add_argument('--direction', choices=('refs', 'cites', 'both'), default='both')
    parser.add_argument('--top', type=int, default=25)
    parser.add_argument('--min-overlap', type=int, default=1)
    parser.add_argument('--cites-per-seed', type=int, default=50)
    parser.add_argument('--similarity-threshold', type=float, default=0.25)
    parser.add_argument('--cluster-diverse', action='store_true')
    parser.add_argument('--out', type=Path, help='Optional output JSON path')
    parser.add_argument('--compact', action='store_true', help='Write full graph JSON to --out (or auto-artifact) and print bounded compact summary')
    args = parser.parse_args()
    try:
        seeds = parse_seeds_input(args.seeds, args.seed)
        report = build_citation_graph(
            seeds=seeds,
            direction=args.direction,
            top=args.top,
            min_overlap=args.min_overlap,
            cites_per_seed=args.cites_per_seed,
            similarity_threshold=args.similarity_threshold,
            cluster_diverse=args.cluster_diverse,
        )
        rendered = json.dumps(report, ensure_ascii=False)
        out_path = args.out.expanduser().resolve() if args.out is not None else (_auto_artifact_path('citation_graph') if args.compact else None)
        if out_path is not None:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(rendered, encoding='utf-8')
        if args.compact:
            print(json.dumps(compact_graph_summary(report, out_path), ensure_ascii=False, separators=(',', ':')))
        else:
            print(rendered)
        if not report['seeds_resolved']:
            return 2
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
