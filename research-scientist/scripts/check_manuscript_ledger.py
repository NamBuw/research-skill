#!/usr/bin/env python3
"""Offline structural audit of manuscript claims, method lineage, and repeated facts.

This checks the declarations in a JSON ledger. It cannot inspect the source passage,
verify that a result was run, or determine whether a claim is scientifically true.
"""
import argparse
import json
import sys
from pathlib import Path

KINDS = {'reported', 'inferred', 'proposed', 'unknown'}
METHOD_ORIGINS = {'reused', 'adapted', 'combined', 'newly_derived'}


def _nonblank(value):
    return isinstance(value, str) and bool(value.strip())


def check(ledger):
    if not isinstance(ledger, dict):
        raise ValueError('ledger must be an object')
    for name in ('sources', 'claims', 'methods', 'numeric_facts'):
        if not isinstance(ledger.get(name), list):
            raise ValueError(f'{name} must be a list')
    issues = []
    source_map = {}
    for index, source in enumerate(ledger['sources']):
        if not isinstance(source, dict) or not _nonblank(source.get('id')):
            raise ValueError(f'invalid source at index {index}')
        sid = source['id']
        if sid in source_map:
            issues.append(f'duplicate_source:{sid}')
        source_map[sid] = source
        if source.get('verified') is True and (not _nonblank(source.get('locator')) or
                                              not _nonblank(source.get('verified_by')) or
                                              not _nonblank(source.get('verified_at'))):
            issues.append(f'unsupported_verification_declaration:{sid}')
    claim_ids = set()
    for index, claim in enumerate(ledger['claims']):
        if not isinstance(claim, dict) or not _nonblank(claim.get('id')):
            raise ValueError(f'invalid claim at index {index}')
        cid = claim['id']
        if cid in claim_ids:
            issues.append(f'duplicate_claim:{cid}')
        claim_ids.add(cid)
        if claim.get('kind') not in KINDS or type(claim.get('material')) is not bool:
            issues.append(f'invalid_claim_classification:{cid}')
        supports = claim.get('source_ids')
        if not isinstance(supports, list) or any(not _nonblank(x) for x in supports):
            issues.append(f'invalid_support_list:{cid}')
            continue
        for sid in supports:
            if sid not in source_map:
                issues.append(f'unknown_source:{cid}:{sid}')
        if claim.get('material') and claim.get('kind') in {'reported', 'inferred'}:
            if not supports:
                issues.append(f'material_claim_without_source:{cid}')
            elif not any(sid in source_map and source_map[sid].get('verified') is True and
                         _nonblank(source_map[sid].get('locator')) and
                         _nonblank(source_map[sid].get('verified_by')) and
                         _nonblank(source_map[sid].get('verified_at')) for sid in supports):
                issues.append(f'material_claim_without_verified_locator:{cid}')
        if claim.get('material') and claim.get('kind') == 'unknown':
            issues.append(f'material_claim_marked_unknown:{cid}')
    method_ids = set()
    for index, method in enumerate(ledger['methods']):
        if not isinstance(method, dict) or not _nonblank(method.get('id')):
            raise ValueError(f'invalid method at index {index}')
        mid = method['id']
        if mid in method_ids:
            issues.append(f'duplicate_method:{mid}')
        method_ids.add(mid)
        origin = method.get('origin')
        if origin not in METHOD_ORIGINS:
            issues.append(f'invalid_method_origin:{mid}')
            continue
        sources = method.get('source_ids')
        if not isinstance(sources, list) or any(not _nonblank(x) for x in sources):
            issues.append(f'invalid_method_sources:{mid}')
            continue
        for sid in sources:
            if sid not in source_map:
                issues.append(f'unknown_method_source:{mid}:{sid}')
            elif origin in {'reused', 'adapted', 'combined'} and (source_map[sid].get('verified') is not True or
                                                               not _nonblank(source_map[sid].get('locator')) or
                                                               not _nonblank(source_map[sid].get('verified_by'))):
                issues.append(f'method_lineage_source_unverified:{mid}:{sid}')
        if origin in {'reused', 'adapted', 'combined'} and not sources:
            issues.append(f'missing_method_lineage:{mid}')
        if origin != 'reused' and not _nonblank(method.get('exact_change')):
            issues.append(f'missing_method_change:{mid}')
        if method.get('novelty_claimed') is True:
            closest = method.get('closest_work_source_ids')
            adjudication = method.get('human_adjudication')
            if not _nonblank(method.get('difference_evidence')) or not isinstance(closest, list) or not closest or any(sid not in source_map for sid in closest) or not isinstance(adjudication, dict) or not _nonblank(adjudication.get('reviewer')) or not _nonblank(adjudication.get('date')) or not _nonblank(adjudication.get('rationale')):
                issues.append(f'unsupported_method_novelty:{mid}')
            if origin == 'reused':
                issues.append(f'reused_method_claimed_as_new:{mid}')
        if method.get('grand_name') is True and origin in {'reused', 'adapted', 'combined'}:
            issues.append(f'inflated_method_name:{mid}')
        elif method.get('grand_name') is True:
            issues.append(f'grand_method_name_requires_review:{mid}')
    fact_ids = set()
    for index, fact in enumerate(ledger['numeric_facts']):
        if not isinstance(fact, dict) or not _nonblank(fact.get('id')):
            raise ValueError(f'invalid numeric fact at index {index}')
        fid = fact['id']
        if fid in fact_ids:
            issues.append(f'duplicate_numeric_fact:{fid}')
        fact_ids.add(fid)
        observations = fact.get('occurrences')
        if not isinstance(observations, list) or not observations:
            issues.append(f'numeric_fact_without_occurrences:{fid}')
            continue
        if any(not isinstance(x, dict) or not _nonblank(x.get('location')) or
               x.get('value') is None or isinstance(x.get('value'), bool) or
               not _nonblank(str(x.get('value'))) or not _nonblank(x.get('unit')) for x in observations):
            issues.append(f'invalid_numeric_occurrence:{fid}')
            continue
        values = {(str(x['value']), x['unit']) for x in observations}
        if len(values) > 1:
            issues.append(f'numeric_fact_mismatch:{fid}')
    return {'status': 'structural_issues' if issues else 'structure_passed', 'issues': sorted(set(issues)),
            'counts': {key: len(ledger[key]) for key in ('sources', 'claims', 'methods', 'numeric_facts')},
            'warning': 'A structural pass does not verify source identity, passage entailment, study conduct, numerical truth, or scientific novelty.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ledger_json')
    args = parser.parse_args()
    try:
        print(json.dumps(check(json.loads(Path(args.ledger_json).read_text(encoding='utf-8')))))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        sys.exit(2)
