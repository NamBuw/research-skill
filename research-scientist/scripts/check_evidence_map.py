#!/usr/bin/env python3
"""Check structural provenance gates in a research evidence map JSON file.

Passing cannot verify the truth of a source passage or scientific inference.
"""
import argparse
import json
import sys
from pathlib import Path

ACCESS = {'original_full_text', 'extracted_full_text', 'abstract', 'metadata_only', 'unavailable'}
RELATIONS = {'supports', 'contradicts', 'qualifies', 'context', 'unresolved'}
CLAIM_STATES = {'supported', 'qualified', 'unresolved'}


def _nonblank(value):
    return isinstance(value, str) and bool(value.strip())


def check(data):
    issues = []
    if not isinstance(data, dict):
        return {'ready_for_sourced_answer': False, 'issues': ['root must be an object']}
    mode = data.get('source_mode')
    if mode not in {'supplied_corpus', 'live_literature', 'hybrid'}:
        issues.append('source_mode must be supplied_corpus, live_literature, or hybrid')
    if not _nonblank(data.get('corpus_boundary')):
        issues.append('corpus_boundary must state what was and was not searched')
    for key in ('sources', 'questions', 'evidence', 'claims', 'outline'):
        if not isinstance(data.get(key), list):
            issues.append(f'{key} must be a list')
    if issues:
        return {'ready_for_sourced_answer': False, 'issues': issues}

    indexes = {}
    for key in ('sources', 'questions', 'evidence', 'claims'):
        index = {}
        for n, row in enumerate(data[key]):
            if not isinstance(row, dict) or not _nonblank(row.get('id')):
                issues.append(f'{key}[{n}] needs a nonempty id')
                continue
            if row['id'] in index:
                issues.append(f'duplicate {key} id: {row["id"]}')
            index[row['id']] = row
        indexes[key] = index
    sources, questions, evidence, claims = (indexes[k] for k in ('sources', 'questions', 'evidence', 'claims'))
    if not sources or not questions or not claims or not data['outline']:
        issues.append('a sourced answer needs at least one source, question, claim, and outline section')

    for sid, source in sources.items():
        if not _nonblank(source.get('title')) or not _nonblank(source.get('identifier')):
            issues.append(f'source {sid} needs title and stable identifier or official URL')
        if source.get('access') not in ACCESS:
            issues.append(f'source {sid} has invalid access level')
        if not _nonblank(source.get('study_group')):
            issues.append(f'source {sid} needs study_group to avoid counting reports as independent studies')
        if not isinstance(source.get('identity_verified'), bool):
            issues.append(f'source {sid} needs identity_verified boolean')

    for qid, question in questions.items():
        if not _nonblank(question.get('text')) or not _nonblank(question.get('perspective')):
            issues.append(f'question {qid} needs text and perspective')
        if question.get('status') not in {'answered', 'qualified', 'unresolved'}:
            issues.append(f'question {qid} has invalid status')
        if not isinstance(question.get('searches'), list):
            issues.append(f'question {qid} needs searches list (empty is allowed but must be disclosed)')

    for eid, row in evidence.items():
        sid, qid = row.get('source_id'), row.get('question_id')
        if sid not in sources:
            issues.append(f'evidence {eid} cites unknown source {sid}')
        if qid not in questions:
            issues.append(f'evidence {eid} cites unknown question {qid}')
        if not _nonblank(row.get('locator')) or not _nonblank(row.get('passage')):
            issues.append(f'evidence {eid} needs locator and short original passage/paraphrase')
        if row.get('relation') not in RELATIONS:
            issues.append(f'evidence {eid} has invalid relation')
        if not isinstance(row.get('original_checked'), bool):
            issues.append(f'evidence {eid} needs original_checked boolean')
        if not _nonblank(row.get('entailment_reason')):
            issues.append(f'evidence {eid} needs entailment_reason')

    for qid, question in questions.items():
        if question.get('status') in {'answered', 'qualified'} and not any(
                row.get('question_id') == qid for row in evidence.values()):
            issues.append(f'question {qid} is marked answered without an evidence passage')

    for cid, claim in claims.items():
        if not _nonblank(claim.get('text')):
            issues.append(f'claim {cid} needs exact text')
        state = claim.get('status')
        if state not in CLAIM_STATES:
            issues.append(f'claim {cid} has invalid status')
        ids = claim.get('evidence_ids')
        if not isinstance(ids, list):
            issues.append(f'claim {cid} needs evidence_ids list')
            continue
        for eid in ids:
            if eid not in evidence:
                issues.append(f'claim {cid} cites unknown evidence {eid}')
        if state in {'supported', 'qualified'}:
            if not ids:
                issues.append(f'claim {cid} is asserted without evidence')
            usable = []
            for eid in ids:
                row = evidence.get(eid)
                if not row:
                    continue
                source = sources.get(row.get('source_id'))
                if (source and source.get('identity_verified') is True and
                    source.get('access') == 'original_full_text' and
                    row.get('original_checked') is True and
                    row.get('relation') in ({'supports'} if state == 'supported' else {'supports', 'qualifies'})):
                    usable.append(eid)
            if not usable:
                issues.append(f'claim {cid} lacks verified original full-text support; narrow or mark unresolved')
        if state == 'unresolved' and not _nonblank(claim.get('needed_next')):
            issues.append(f'unresolved claim {cid} needs needed_next')

    for n, section in enumerate(data['outline']):
        if not isinstance(section, dict) or not _nonblank(section.get('heading')):
            issues.append(f'outline[{n}] needs heading')
            continue
        qids, cids = section.get('question_ids'), section.get('claim_ids')
        if not isinstance(qids, list) or not isinstance(cids, list):
            issues.append(f'outline[{n}] needs question_ids and claim_ids lists')
            continue
        for qid in qids:
            if qid not in questions:
                issues.append(f'outline[{n}] names unknown question {qid}')
        for cid in cids:
            if cid not in claims:
                issues.append(f'outline[{n}] names unknown claim {cid}')

    return {'ready_for_sourced_answer': not issues, 'issues': issues,
            'counts': {'sources': len(sources), 'study_groups': len({s.get('study_group') for s in sources.values() if s.get('study_group')}),
                       'questions': len(questions), 'evidence_passages': len(evidence),
                       'claims': len(claims), 'unresolved_claims': sum(c.get('status') == 'unresolved' for c in claims.values())},
            'warning': 'Structural checks cannot verify passage authenticity, semantic entailment, independent studies, retrieval coverage, or scientific conclusions.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('map_json')
    args = parser.parse_args()
    try:
        result = check(json.loads(Path(args.map_json).read_text(encoding='utf-8')))
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(0 if result['ready_for_sourced_answer'] else 1)
    except (OSError, ValueError, UnicodeError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        sys.exit(2)
