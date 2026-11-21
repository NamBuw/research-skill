#!/usr/bin/env python3
"""Check run-receipt structure, on-disk SHA-256/log verification, claims comparison, and repo completeness.

Apache-2.0 Attribution: Tolerance-aware numeric metric comparison (parse_number,
compare_values, _flatten, compare) and ML Code Completeness checklist
(audit_repo_completeness) adapted from research-paper-lifecycle-skills
(Copyright 2026 Shaishav Maisuria, Apache License 2.0).
"""
import argparse
import csv
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

HEX64 = re.compile(r'^[0-9a-fA-F]{64}$')
REQUIRED = ('run_id', 'role', 'protocol_version', 'code_commit', 'data_version',
            'split_manifest_sha256', 'metric_id', 'metric_script_sha256',
            'command', 'started_at_utc', 'ended_at_utc', 'exit_code',
            'result_artifact_sha256', 'result_value', 'deviations', 'decision_timing')
MATCH_FIELDS = ('protocol_version', 'data_version', 'split_manifest_sha256',
                'metric_id', 'metric_script_sha256')

def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed if parsed.utcoffset() is not None else None

def check(manifest):
    errors, warnings = [], []
    if not isinstance(manifest, dict):
        return {'status': 'invalid', 'errors': ['manifest must be an object'], 'warnings': []}
    for key in ('question_id', 'protocol_version', 'runs'):
        if key not in manifest:
            errors.append(f'missing {key}')
    frozen = timestamp(manifest.get('protocol_frozen_at_utc'))
    if frozen is None:
        errors.append('protocol_frozen_at_utc must include a timezone')
    runs = manifest.get('runs')
    if not isinstance(runs, list) or not runs:
        errors.append('runs must be a nonempty list')
        runs = []
    ids, valid = set(), []
    for index, run in enumerate(runs):
        label = f'runs[{index}]'
        if not isinstance(run, dict):
            errors.append(f'{label} must be an object')
            continue
        for field in REQUIRED:
            if field not in run:
                errors.append(f'{label} missing {field}')
        run_id = run.get('run_id')
        if not isinstance(run_id, str) or not run_id.strip():
            errors.append(f'{label} invalid run_id')
        elif run_id in ids:
            errors.append(f'{label} duplicate run_id {run_id}')
        else:
            ids.add(run_id)
        if run.get('role') not in ('baseline', 'candidate', 'control'):
            errors.append(f'{label} invalid role')
        if run.get('decision_timing') not in ('prespecified', 'amended', 'exploratory'):
            errors.append(f'{label} invalid decision_timing')
        for field in ('split_manifest_sha256', 'metric_script_sha256', 'result_artifact_sha256'):
            if not isinstance(run.get(field), str) or not HEX64.fullmatch(run[field]):
                errors.append(f'{label} invalid {field}')
        start, end = timestamp(run.get('started_at_utc')), timestamp(run.get('ended_at_utc'))
        if start is None or end is None:
            errors.append(f'{label} timestamps must include timezones')
        elif start > end:
            errors.append(f'{label} start after end')
        if not isinstance(run.get('exit_code'), int) or isinstance(run.get('exit_code'), bool):
            errors.append(f'{label} exit_code must be an integer')
        elif run['exit_code'] != 0:
            warnings.append(f'{label} nonzero exit; result is not a successful run')
        if not isinstance(run.get('deviations'), list):
            errors.append(f'{label} deviations must be a list')
        if not isinstance(run.get('command'), str) or not run['command'].strip():
            errors.append(f'{label} missing executable command')
        if run.get('exit_code') == 0 and (run.get('result_value') is None or isinstance(run.get('result_value'), bool)):
            errors.append(f'{label} successful run needs a recorded result_value')
        if run.get('protocol_version') != manifest.get('protocol_version'):
            warnings.append(f'{label} uses another protocol version; justify amendment')
        if frozen and start and start < frozen and run.get('decision_timing') == 'prespecified':
            errors.append(f'{label} cannot be prespecified by a later frozen protocol')
        valid.append(run)
    baselines = [r for r in valid if r.get('role') == 'baseline' and r.get('exit_code') == 0]
    candidates = [r for r in valid if r.get('role') == 'candidate' and r.get('exit_code') == 0]
    if not baselines or not candidates:
        warnings.append('a successful baseline and candidate are both needed for a comparison')
    comparable = []
    for candidate in candidates:
        for baseline in baselines:
            differences = [field for field in MATCH_FIELDS if candidate.get(field) != baseline.get(field)]
            if not differences:
                comparable.append([baseline.get('run_id'), candidate.get('run_id')])
            else:
                warnings.append(f"{baseline.get('run_id')} vs {candidate.get('run_id')}: mismatched {', '.join(differences)}")
    if baselines and candidates and not comparable:
        warnings.append('no structurally matched successful baseline/candidate pair')
    if any(r.get('decision_timing') != 'prespecified' for r in valid):
        warnings.append('amended or exploratory runs cannot be described as wholly prespecified')
    return {'status': 'invalid' if errors else 'structurally_checked',
            'comparison_status': 'matched_receipts_found' if comparable else 'no_matched_successful_pair',
            'errors': errors, 'warnings': warnings, 'comparable_run_pairs': comparable,
            'disclaimer': 'This check does not read logs, verify hashes against files, reproduce runs, validate data/metrics, or establish a scientific claim.'}


def _auto_artifact_path(prefix):
    art_dir = Path(tempfile.gettempdir()) / 'research_scientist_artifacts'
    art_dir.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(prefix=f'{prefix}_', suffix='.json', dir=str(art_dir))
    os.close(fd)
    return Path(raw_path)


def _sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def _resolve_artifact(rel_or_abs, base_dir):
    p = Path(rel_or_abs)
    if p.is_absolute():
        return p
    if base_dir is not None:
        return Path(base_dir) / p
    return p


def parse_number(raw):
    if isinstance(raw, bool):
        return None, False
    if isinstance(raw, (int, float)):
        return (None, False) if (math.isnan(raw) or math.isinf(raw)) else (float(raw), False)
    if not isinstance(raw, str):
        return None, False
    s = raw.strip().replace(',', '')
    if not s:
        return None, False
    is_pct = s.endswith('%')
    if is_pct:
        s = s[:-1].strip()
    m = re.match(r'^([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)', s)
    if not m:
        return None, is_pct
    val = float(m.group(1))
    return (None, is_pct) if (math.isnan(val) or math.isinf(val)) else (val, is_pct)


def _as_fraction(val, is_pct, scale_hint=None):
    if scale_hint == 'percent' or (is_pct and scale_hint != 'fraction'):
        return val / 100.0
    if scale_hint == 'fraction':
        return val
    return val / 100.0 if is_pct else val


def compare_values(paper_val, paper_pct, run_val, run_pct, rel_tol=0.001, abs_tol=0.0005, scale_hint=None):
    p = _as_fraction(paper_val, paper_pct, scale_hint)
    r = _as_fraction(run_val, run_pct, None)
    if paper_pct != run_pct and abs(p - r) > max(rel_tol * abs(p), abs_tol):
        if paper_pct and not run_pct and abs((paper_val / 100.0) - run_val) <= max(rel_tol * abs(paper_val / 100.0), abs_tol):
            return True, 0.0
        if run_pct and not paper_pct and abs(paper_val - (run_val / 100.0)) <= max(rel_tol * abs(paper_val), abs_tol):
            return True, 0.0
    diff = abs(p - r)
    tol = max(rel_tol * abs(p), abs_tol)
    return diff <= tol, diff


def _flatten(obj, prefix=''):
    flat = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f'{prefix}.{k}' if prefix else str(k)
            if isinstance(v, (dict, list)):
                flat.update(_flatten(v, key))
            else:
                num, pct = parse_number(v)
                if num is not None:
                    flat[key] = (num, pct)
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            if isinstance(item, dict) and ('metric' in item or 'name' in item) and ('value' in item or 'val' in item):
                name = str(item.get('metric') or item.get('name'))
                num, pct = parse_number(item.get('value') if 'value' in item else item.get('val'))
                if num is not None:
                    flat[name] = (num, pct)
            else:
                flat.update(_flatten(item, f'{prefix}[{idx}]'))
    return flat


def _extract_artifact_metrics(path, metric_id, run_id=None, return_meta=False):
    p = Path(path)
    suf = p.suffix.lower()
    if suf == '.json':
        data = json.loads(p.read_text(encoding='utf-8'))
        flat = _flatten(data)
        return (flat, False) if return_meta else flat
    if suf in {'.csv', '.tsv'}:
        delim = '\t' if suf == '.tsv' else ','
        flat = {}
        is_tall = False
        with p.open(newline='', encoding='utf-8-sig') as stream:
            rows = list(csv.DictReader(stream, delimiter=delim))
        if run_id and rows:
            id_col = next(
                (col for col in rows[0].keys() if col and col.strip().casefold() in {'run_id', 'run', 'id'}),
                None,
            )
            if id_col is not None:
                matched_rows = [r for r in rows if (r.get(id_col) or '').strip() == run_id]
                if matched_rows:
                    rows = matched_rows
                elif id_col.strip().casefold() in {'run_id', 'run'}:
                    rows = []
        for row in rows:
            col_map = {col.strip().casefold(): col for col in row.keys() if col}
            metric_col = col_map.get('metric') or col_map.get('metric_id')
            val_col = col_map['value'] if 'value' in col_map else col_map.get('result_value')
            if metric_col is not None:
                is_tall = True
                mname = str(row.get(metric_col) or '').strip()
                mval = row.get(val_col) if val_col is not None else None
                num, pct = parse_number(mval)
                if mname and num is not None:
                    flat[mname] = (num, pct)
            else:
                for col, raw in row.items():
                    if not col:
                        continue
                    num, pct = parse_number(raw)
                    if num is not None:
                        flat[col.strip()] = (num, pct)
        return (flat, is_tall) if return_meta else flat
    return ({}, False) if return_meta else {}


def _find_metric(flat, metric_id, allow_fallback=True):
    if not flat:
        return None
    if metric_id in flat:
        return flat[metric_id]
    low = metric_id.casefold()
    for k, v in flat.items():
        if k.casefold() == low or k.casefold().endswith('.' + low):
            return v
    if allow_fallback:
        if 'result_value' in flat:
            return flat['result_value']
        if 'value' in flat:
            return flat['value']
        if len(flat) == 1:
            return next(iter(flat.values()))
    return None


def verify_files(manifest, base_dir=None, rel_tol=0.001, abs_tol=0.0005):
    file_errors = []
    file_warnings = []
    receipts = []
    runs = manifest.get('runs') if isinstance(manifest, dict) and isinstance(manifest.get('runs'), list) else []
    for idx, run in enumerate(runs):
        if not isinstance(run, dict):
            continue
        rid = run.get('run_id', f'runs[{idx}]')
        rec = {'run_id': rid, 'checked_files': []}
        for path_key, sha_key, required in (
            ('split_manifest_path', 'split_manifest_sha256', False),
            ('metric_script_path', 'metric_script_sha256', False),
            ('result_artifact_path', 'result_artifact_sha256', True),
        ):
            rel = run.get(path_key)
            if not rel:
                if required:
                    file_errors.append(f'{rid}: missing {path_key} required for --verify-files')
                continue
            target = _resolve_artifact(rel, base_dir)
            if not target.is_file():
                file_errors.append(f'{rid}: missing file on disk for {path_key}: {rel}')
                continue
            actual_sha = _sha256_file(target)
            expected_sha = str(run.get(sha_key) or '').lower()
            if actual_sha.lower() != expected_sha:
                file_errors.append(f'{rid}: sha256 mismatch for {path_key} ({rel})')
            else:
                rec['checked_files'].append({'field': path_key, 'path': str(target), 'sha256_ok': True})

        res_rel = run.get('result_artifact_path')
        if res_rel and run.get('exit_code') == 0:
            res_path = _resolve_artifact(res_rel, base_dir)
            if res_path.is_file() and res_path.suffix.lower() in {'.json', '.csv', '.tsv'}:
                flat, is_tall = _extract_artifact_metrics(res_path, str(run.get('metric_id') or ''), run_id=str(rid), return_meta=True)
                found = _find_metric(flat, str(run.get('metric_id') or ''), allow_fallback=not is_tall)
                run_num, run_pct = parse_number(run.get('result_value'))
                if found is None:
                    file_errors.append(f'{rid}: metric {run.get("metric_id")} missing from artifact {res_rel}')
                elif run_num is not None:
                    ok, diff = compare_values(run_num, run_pct, found[0], found[1], rel_tol=rel_tol, abs_tol=abs_tol)
                    if not ok:
                        file_errors.append(
                            f'{rid}: value discrepancy vs {res_rel} (manifest={run_num}, artifact={found[0]}, diff={diff:.6g})'
                        )

        log_rel = run.get('run_log_path') or run.get('log_path')
        if log_rel:
            log_path = _resolve_artifact(log_rel, base_dir)
            if not log_path.is_file():
                file_errors.append(f'{rid}: missing run log file {log_rel}')
            elif log_path.stat().st_size == 0:
                file_errors.append(f'{rid}: empty run log file {log_rel}')
            elif log_path.suffix.lower() == '.json':
                try:
                    ldata = json.loads(log_path.read_text(encoding='utf-8'))
                    if isinstance(ldata, dict):
                        if ldata.get('run_id') and ldata['run_id'] != rid:
                            file_errors.append(f'{rid}: run_id mismatch in {log_rel}')
                        if 'exit_code' in ldata and ldata['exit_code'] != run.get('exit_code'):
                            file_errors.append(f'{rid}: exit_code mismatch in {log_rel}')
                        if 'result_value' in ldata:
                            lnum, lpct = parse_number(ldata['result_value'])
                            rnum, rpct = parse_number(run.get('result_value'))
                            if lnum is not None and rnum is not None:
                                ok, diff = compare_values(rnum, rpct, lnum, lpct, rel_tol=rel_tol, abs_tol=abs_tol)
                                if not ok:
                                    file_errors.append(f'{rid}: value discrepancy vs {log_rel} (manifest={rnum}, log={lnum}, diff={diff:.6g})')
                except (OSError, json.JSONDecodeError) as exc:
                    file_errors.append(f'{rid}: invalid JSON run log {log_rel}: {exc}')
        receipts.append(rec)
    return {'files_verified': not file_errors, 'file_errors': file_errors, 'file_warnings': file_warnings, 'file_checks': receipts}


def compare_claims(manifest, claims_data, base_dir=None, rel_tol=0.001, abs_tol=0.0005, key_map=None):
    key_map = key_map or {}
    produced = {}
    for run in manifest.get('runs', []) or []:
        if not isinstance(run, dict) or run.get('exit_code') != 0:
            continue
        rid = str(run.get('run_id') or '')
        mid = str(run.get('metric_id') or '')
        rnum, rpct = parse_number(run.get('result_value'))
        if rnum is not None:
            if mid:
                produced.setdefault(mid, (rnum, rpct))
            if rid:
                produced[f'{rid}.{mid}' if mid else rid] = (rnum, rpct)
        if run.get('result_artifact_path'):
            ap = _resolve_artifact(run['result_artifact_path'], base_dir)
            if ap.is_file() and ap.suffix.lower() in {'.json', '.csv', '.tsv'}:
                for k, v in _extract_artifact_metrics(ap, mid, run_id=rid).items():
                    produced.setdefault(k, v)
                    if rid:
                        produced.setdefault(f'{rid}.{k}', v)

    claims = claims_data.get('claims') if isinstance(claims_data, dict) else claims_data
    findings = []
    counts = {'MATCH': 0, 'MISMATCH': 0, 'MISSING': 0}
    for claim in (claims or []):
        if not isinstance(claim, dict):
            continue
        cid = str(claim.get('id') or claim.get('metric') or '')
        metric = str(key_map.get(cid) or claim.get('metric') or cid)
        pval, ppct = parse_number(claim.get('value'))
        ppct = ppct or bool(claim.get('is_percent'))
        matched_val = produced.get(metric)
        if matched_val is None:
            low = metric.casefold()
            matched_val = next((v for k, v in produced.items() if k.casefold() == low or k.casefold().endswith('.' + low)), None)
        if matched_val is None or pval is None:
            counts['MISSING'] += 1
            findings.append({'id': cid, 'metric': metric, 'status': 'MISSING'})
        else:
            ok, diff = compare_values(pval, ppct, matched_val[0], matched_val[1], rel_tol=rel_tol, abs_tol=abs_tol, scale_hint=claim.get('scale_hint'))
            status = 'MATCH' if ok else 'MISMATCH'
            counts[status] += 1
            findings.append({'id': cid, 'metric': metric, 'status': status, 'claimed': pval, 'produced': matched_val[0], 'diff': diff})
    return {'matched': counts['MATCH'], 'mismatched': counts['MISMATCH'], 'missing': counts['MISSING'], 'findings': findings}


def audit_repo_completeness(repo_dir, blind='none'):
    repo = Path(repo_dir)
    if not repo.is_dir():
        raise ValueError(f'repo directory not found: {repo_dir}')
    files = [p.relative_to(repo).as_posix() for p in repo.rglob('*') if p.is_file() and '.git' not in p.parts and '__pycache__' not in p.parts]
    low_files = {f.lower(): f for f in files}
    has_deps = any(Path(f).name.lower() in {'requirements.txt', 'pyproject.toml', 'environment.yml', 'setup.py', 'setup.cfg'} for f in files)
    has_train = any('train' in Path(f).name.lower() and f.endswith('.py') for f in files)
    has_eval = any(any(tok in Path(f).name.lower() for tok in ('eval', 'test', 'infer', 'predict')) and f.endswith('.py') for f in files)
    has_tests = any(f.startswith('tests/') or '/tests/' in f or Path(f).name.startswith('test_') for f in files)
    readme_key = next((low_files[k] for k in ('readme.md', 'readme.rst', 'readme.txt') if k in low_files), None)
    readme_text = (repo / readme_key).read_text(encoding='utf-8', errors='replace') if readme_key else ''
    has_pretrained = bool(re.search(r'(?:checkpoint|weights|pretrained|huggingface\.co|download)', readme_text, re.I)) or any(f.endswith(('.pt', '.pth', '.safetensors', '.ckpt')) for f in files)
    has_archival_doi = bool(re.search(r'10\.5281/zenodo|10\.6084/m9|10\.7910/dvn|archive\.org', readme_text, re.I))
    has_table_and_cmd = bool(readme_text) and ('|' in readme_text or '---' in readme_text) and bool(re.search(r'python|bash|```', readme_text, re.I))

    gaps = []
    if not has_deps:
        gaps.append('missing_dependencies_spec')
    if not has_train:
        gaps.append('missing_training_entrypoint')
    if not has_eval:
        gaps.append('missing_eval_entrypoint')
    if not has_pretrained:
        gaps.append('missing_pretrained_weights_note')
    if not readme_key or not has_table_and_cmd:
        gaps.append('incomplete_readme_results_or_command')
    if not has_tests:
        gaps.append('missing_tests_directory')
    if not has_archival_doi:
        gaps.append('no_archival_doi_warning')

    blind_leaks = []
    if blind == 'double':
        for f in files:
            if f.endswith(('.md', '.py', '.txt', '.json', '.yaml', '.yml')):
                txt = (repo / f).read_text(encoding='utf-8', errors='replace')
                if re.search(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', txt):
                    blind_leaks.append(f'{f}:email_detected')
                if re.search(r'https?://github\.com/[A-Za-z0-9_-]+/', txt, re.I):
                    blind_leaks.append(f'{f}:non_anonymous_github_url')
    return {
        'repo_dir': str(repo),
        'blind_mode': blind,
        'checks': {
            'dependencies': has_deps, 'training_code': has_train, 'eval_code': has_eval,
            'pretrained': has_pretrained, 'readme_table_and_cmd': has_table_and_cmd,
            'tests_present': has_tests, 'archival_doi': has_archival_doi,
        },
        'gaps': gaps,
        'blind_leaks': blind_leaks,
        'complete': not gaps and not blind_leaks,
    }


def _compact_summary(result, artifact_path):
    out = {
        'compact': True,
        'artifact_path': str(artifact_path),
        'status': result.get('status'),
        'comparison_status': result.get('comparison_status'),
        'files_verified': result.get('files_verified'),
        'comparable_run_pairs': [
            [str(x)[:80] for x in p[:2]] if isinstance(p, (list, tuple)) else str(p)[:80]
            for p in (result.get('comparable_run_pairs') or [])[:5]
        ],
        'error_count': len(result.get('errors', [])),
        'errors': [str(e)[:200] for e in (result.get('errors') or [])[:5]],
        'warning_count': len(result.get('warnings', [])),
    }
    while len(json.dumps(out, separators=(',', ':'), ensure_ascii=False).encode('utf-8')) >= 4095 and (
        out['errors'] or out['comparable_run_pairs']
    ):
        if out['errors']:
            out['errors'].pop()
        elif out['comparable_run_pairs']:
            out['comparable_run_pairs'].pop()
    if len(json.dumps(out, separators=(',', ':'), ensure_ascii=False).encode('utf-8')) >= 4095:
        out['artifact_path'] = out['artifact_path'][-200:]
    return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--verify-files', action='store_true', help='Verify SHA-256 hashes, run logs, and numeric artifacts on disk')
    parser.add_argument('--claims', type=Path, default=None, help='Optional claims JSON to compare against run results')
    parser.add_argument('--rel-tol', type=float, default=0.001, help='Relative tolerance for numeric comparisons')
    parser.add_argument('--abs-tol', type=float, default=0.0005, help='Absolute tolerance for numeric comparisons')
    parser.add_argument('--map', action='append', default=[], help='Metric name mapping NAME=CLAIMID')
    parser.add_argument('--audit-repo', type=Path, default=None, help='Optional repository directory to audit for ML code completeness')
    parser.add_argument('--blind', choices=('none', 'single', 'double'), default='none', help='Anonymity check level for --audit-repo')
    parser.add_argument('--strict-repo', action='store_true', help='Fail manifest check if --audit-repo finds completeness gaps')
    parser.add_argument('--out', type=Path, default=None, help='Optional output JSON file path')
    parser.add_argument('--compact', action='store_true', help='Emit bounded <4096B stdout summary + disk artifact path')
    args = parser.parse_args()
    try:
        manifest_obj = json.loads(args.manifest.read_text(encoding='utf-8'))
        result = check(manifest_obj)
        base_dir = args.manifest.resolve().parent
        if args.verify_files:
            vf = verify_files(manifest_obj, base_dir=base_dir, rel_tol=args.rel_tol, abs_tol=args.abs_tol)
            result['files_verified'] = vf['files_verified']
            result['file_checks'] = vf['file_checks']
            result['errors'].extend(vf['file_errors'])
            result['warnings'].extend(vf['file_warnings'])
            result['status'] = 'invalid' if result['errors'] else 'structurally_checked'
        if args.claims is not None:
            claims_obj = json.loads(args.claims.read_text(encoding='utf-8'))
            kmap = {}
            for item in args.map:
                if '=' in item:
                    k, v = item.split('=', 1)
                    kmap[v.strip()] = k.strip()
            comp = compare_claims(manifest_obj, claims_obj, base_dir=base_dir, rel_tol=args.rel_tol, abs_tol=args.abs_tol, key_map=kmap)
            result['claim_comparisons'] = comp
            for f in comp['findings']:
                if f['status'] in {'MISMATCH', 'MISSING'}:
                    result['errors'].append(f"claim_{f['status'].lower()}:{f['id']} ({f['metric']})")
            result['status'] = 'invalid' if result['errors'] else 'structurally_checked'
        if args.audit_repo is not None:
            repo_rep = audit_repo_completeness(args.audit_repo, blind=args.blind)
            result['repo_completeness'] = repo_rep
            target_list = result['errors'] if args.strict_repo else result['warnings']
            for g in repo_rep['gaps']:
                target_list.append(f'repo_completeness:{g}')
            for bl in repo_rep['blind_leaks']:
                target_list.append(f'repo_blind_leak:{bl}')
            result['status'] = 'invalid' if result['errors'] else 'structurally_checked'
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        result = {'status': 'invalid', 'errors': [str(exc)], 'warnings': []}

    out_path = args.out
    if args.compact and out_path is None:
        out_path = _auto_artifact_path('experiment_manifest')
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    if args.compact:
        print(json.dumps(_compact_summary(result, out_path), separators=(',', ':'), ensure_ascii=False))
    else:
        print(json.dumps(result, indent=2))
    sys.exit(0 if result['status'] == 'structurally_checked' else 2)
