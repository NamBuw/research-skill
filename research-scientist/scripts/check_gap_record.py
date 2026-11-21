#!/usr/bin/env python3
"""Check the audit trail behind a proposed research gap.

This checks internal links and minimum evidence gates. It cannot judge source
accuracy, search recall, scientific importance, or whether a gap is real.
"""
import argparse
import json
import sys
from pathlib import Path

DISPOSITIONS = {'not_a_gap', 'early_signal', 'supported_candidate', 'insufficient_evidence'}
ACCESS = {'full_text', 'selected_full_text', 'abstract', 'metadata', 'unavailable'}
RELATIONS = {'direct_precedent', 'partial_precedent', 'adjacent_precedent', 'counterevidence', 'analogy_only'}
QUERY_STATES = {'complete', 'bounded_partial', 'valid_zero_results', 'rate_limited', 'failed', 'not_run'}
SUCCESS = {'complete', 'bounded_partial', 'valid_zero_results'}
EVIDENCE_ROLES = {'result', 'method', 'assumption', 'limitation', 'author_future_work', 'context'}
KILL_FAMILIES = {'closure', 'adversarial', 'alternate_vocabulary', 'citation_trail'}


def _nonblank(value):
    return isinstance(value, str) and bool(value.strip())


def _unscreened(query):
    retrieved, inspected = query.get('retrieved'), query.get('inspected')
    return (isinstance(retrieved, int) and not isinstance(retrieved, bool) and
            isinstance(inspected, int) and not isinstance(inspected, bool) and
            inspected < retrieved)


def _objects_by_id(items, label, errors):
    if not isinstance(items, list):
        errors.append(f'{label}:must_be_list')
        return {}
    indexed = {}
    for item in items:
        if not isinstance(item, dict) or not _nonblank(item.get('id')):
            errors.append(f'{label}:invalid_item_or_id')
            continue
        identifier = item['id']
        if identifier in indexed:
            errors.append(f'{label}:duplicate_id:{identifier}')
        indexed[identifier] = item
    return indexed


def _ids(item, field, label, known, errors):
    value = item.get(field)
    if not isinstance(value, list) or any(not _nonblank(x) for x in value):
        errors.append(f'{label}:{field}:must_be_id_list')
        return []
    for identifier in value:
        if identifier not in known:
            errors.append(f'{label}:{field}:unknown_id:{identifier}')
    return value


def check(record):
    if not isinstance(record, dict):
        raise ValueError('record must be a JSON object')
    errors, warnings = [], []
    for field in ('scope', 'search_date', 'coverage_limits', 'next_check'):
        if not _nonblank(record.get(field)):
            errors.append(f'missing_or_blank:{field}')
    queries = _objects_by_id(record.get('queries'), 'queries', errors)
    evidence = _objects_by_id(record.get('evidence'), 'evidence', errors)
    works = _objects_by_id(record.get('closest_works'), 'closest_works', errors)
    candidates = _objects_by_id(record.get('candidates'), 'candidates', errors)

    for qid, query in queries.items():
        for field in ('source', 'query', 'family'):
            if not _nonblank(query.get(field)):
                errors.append(f'queries:{qid}:missing_{field}')
        if query.get('status') not in QUERY_STATES:
            errors.append(f'queries:{qid}:invalid_status')
        returned, inspected = query.get('retrieved'), query.get('inspected')
        if not isinstance(returned, int) or isinstance(returned, bool) or returned < 0:
            errors.append(f'queries:{qid}:invalid_retrieved_count')
        if not isinstance(inspected, int) or isinstance(inspected, bool) or inspected < 0:
            errors.append(f'queries:{qid}:invalid_inspected_count')
        if isinstance(returned, int) and isinstance(inspected, int) and inspected > returned:
            errors.append(f'queries:{qid}:inspected_exceeds_retrieved')
        if query.get('status') == 'valid_zero_results' and returned != 0:
            errors.append(f'queries:{qid}:zero_status_with_hits')
    for eid, entry in evidence.items():
        for field in ('source_id', 'study_id', 'locator', 'claim'):
            if not _nonblank(entry.get(field)):
                errors.append(f'evidence:{eid}:missing_{field}')
        if entry.get('access') not in ACCESS:
            errors.append(f'evidence:{eid}:invalid_access')
        if entry.get('role') not in EVIDENCE_ROLES:
            errors.append(f'evidence:{eid}:invalid_role')
    for wid, work in works.items():
        if not _nonblank(work.get('source_id')):
            errors.append(f'closest_works:{wid}:missing_source_id')
        if work.get('relation') not in RELATIONS:
            errors.append(f'closest_works:{wid}:invalid_relation')
        if work.get('access') not in ACCESS:
            errors.append(f'closest_works:{wid}:invalid_access')
        if not _nonblank(work.get('difference')):
            errors.append(f'closest_works:{wid}:missing_difference')
        linked = _ids(work, 'evidence_ids', f'closest_works:{wid}', evidence, errors)
        for eid in linked:
            if evidence.get(eid, {}).get('source_id') != work.get('source_id'):
                errors.append(f'closest_works:{wid}:evidence_source_mismatch:{eid}')

    for cid, candidate in candidates.items():
        prefix = f'candidates:{cid}'
        disposition = candidate.get('disposition')
        if disposition not in DISPOSITIONS:
            errors.append(f'{prefix}:invalid_disposition')
        for field in ('claim', 'type', 'rationale', 'engineering_status'):
            if not _nonblank(candidate.get(field)):
                errors.append(f'{prefix}:missing_{field}')
        support = _ids(candidate, 'support_evidence_ids', prefix, evidence, errors)
        counter = _ids(candidate, 'counter_evidence_ids', prefix, evidence, errors)
        close = _ids(candidate, 'closest_work_ids', prefix, works, errors)
        kill = _ids(candidate, 'kill_query_ids', prefix, queries, errors)
        if disposition != 'supported_candidate':
            continue
        if not support:
            errors.append(f'{prefix}:no_support_evidence')
        elif not any(evidence.get(eid, {}).get('access') in {'full_text', 'selected_full_text'} for eid in support):
            errors.append(f'{prefix}:support_not_checked_in_full_text')
        if support and all(evidence.get(eid, {}).get('role') == 'author_future_work' for eid in support):
            errors.append(f'{prefix}:author_future_work_alone_cannot_establish_gap')
        if not close:
            errors.append(f'{prefix}:no_closest_work_assessed')
        elif not any(works.get(wid, {}).get('access') in {'full_text', 'selected_full_text'} and
                     any(evidence.get(eid, {}).get('access') in {'full_text', 'selected_full_text'}
                         for eid in works.get(wid, {}).get('evidence_ids', []))
                     for wid in close):
            errors.append(f'{prefix}:closest_work_unread')
        if close and not any(works.get(wid, {}).get('evidence_ids') for wid in close):
            errors.append(f'{prefix}:closest_work_has_no_locator_evidence')
        if any(works.get(wid, {}).get('relation') == 'direct_precedent' for wid in close):
            errors.append(f'{prefix}:direct_precedent_conflicts_with_positive_gap')
        if not kill or not any(queries.get(qid, {}).get('status') in SUCCESS and
                               queries.get(qid, {}).get('family') in KILL_FAMILIES for qid in kill):
            errors.append(f'{prefix}:no_completed_kill_search')
        if any(queries.get(qid, {}).get('status') in SUCCESS and _unscreened(queries.get(qid, {}))
               for qid in kill):
            errors.append(f'{prefix}:kill_search_retrieved_records_unscreened')
        successful_queries = [q for q in queries.values() if q.get('status') in SUCCESS]
        source_count = len({q.get('source') for q in successful_queries if _nonblank(q.get('source'))})
        family_count = len({q.get('family') for q in successful_queries if _nonblank(q.get('family'))})
        if (source_count < 2 or family_count < 2) and not _nonblank(candidate.get('coverage_exception')):
            errors.append(f'{prefix}:single_source_or_query_family_without_exception')
        elif source_count < 2 or family_count < 2:
            warnings.append(f'{prefix}:coverage_exception_requires_scientific_review')
        if not _nonblank(candidate.get('consequence')) or not _nonblank(candidate.get('answer_path')):
            errors.append(f'{prefix}:missing_consequence_or_answer_path')
        if candidate.get('trigger') == 'failed_implementation' and candidate.get('engineering_status') not in {'implementation_checked', 'protocol_matched'}:
            errors.append(f'{prefix}:engineering_failure_unresolved')
        if not counter:
            warnings.append(f'{prefix}:counterevidence_queue_empty; explain whether a search found none')
        if any(queries.get(qid, {}).get('status') == 'bounded_partial' for qid in kill):
            warnings.append(f'{prefix}:kill_search_bounded_partial; inspect unexamined results')

    return {'valid_structure': not errors, 'errors': errors, 'warnings': warnings,
            'scope': 'Structural audit only; a passing record is not a verified gap or novelty certificate.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('record_json')
    args = parser.parse_args()
    try:
        record = json.loads(Path(args.record_json).read_text(encoding='utf-8'))
        result = check(record)
        print(json.dumps(result))
        sys.exit(0 if result['valid_structure'] else 1)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        sys.exit(2)
