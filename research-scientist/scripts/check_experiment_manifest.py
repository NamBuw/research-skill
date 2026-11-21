#!/usr/bin/env python3
"""Check run-receipt structure and comparability; never certify scientific validity."""
import argparse
import json
import re
import sys
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

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    try:
        result = check(json.loads(args.manifest.read_text(encoding='utf-8')))
    except (OSError, json.JSONDecodeError) as exc:
        result = {'status': 'invalid', 'errors': [str(exc)], 'warnings': []}
    print(json.dumps(result, indent=2))
    sys.exit(0 if result['status'] == 'structurally_checked' else 2)
