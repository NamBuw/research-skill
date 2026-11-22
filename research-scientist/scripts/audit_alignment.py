#!/usr/bin/env python3
"""Read-only CSV identity/split audit. Counts are diagnostic, never proof of leakage."""
import argparse
import csv
import json
import os
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

_AUTO_GROUP_COLS = (
    'group_id', 'patient_id', 'user_id', 'subject_id', 'author_id',
    'session_id', 'speaker_id', 'recording_id', 'channel_id',
)


def _auto_artifact_path(prefix):
    art_dir = Path(tempfile.gettempdir()) / 'research_scientist_artifacts'
    art_dir.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(prefix=f'{prefix}_', suffix='.json', dir=str(art_dir))
    os.close(fd)
    return Path(raw_path)


def load_with_groups(path, id_column, split_column, group_column=None):
    with Path(path).open(newline='', encoding='utf-8-sig') as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        required = [id_column] + ([split_column] if split_column else []) + ([group_column] if group_column else [])
        if any(name not in fields for name in required):
            raise ValueError(f'{path}: required column missing')
        ids, splits, groups = [], defaultdict(set), defaultdict(set)
        for row in reader:
            key = (row.get(id_column) or '').strip()
            if not key:
                raise ValueError(f'{path}: blank sample ID at data row {len(ids) + 1}')
            ids.append(key)
            if split_column:
                split = (row.get(split_column) or '').strip()
                if not split:
                    raise ValueError(f'{path}: blank split at data row {len(ids)}')
                splits[key].add(split)
                if group_column:
                    grp = (row.get(group_column) or '').strip()
                    if not grp:
                        raise ValueError(f'{path}: blank group ID at data row {len(ids)}')
                    groups[grp].add(split)
            elif group_column:
                grp = (row.get(group_column) or '').strip()
                if not grp:
                    raise ValueError(f'{path}: blank group ID at data row {len(ids)}')
                groups[grp].add('unsplit')
    return ids, splits, groups


def load(path, id_column, split_column):
    ids, splits, _ = load_with_groups(path, id_column, split_column, group_column=None)
    return ids, splits


def inspect_splits_csv(path, id_column='sample_id', split_column='split', group_column=None):
    with Path(path).open(newline='', encoding='utf-8-sig') as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        if id_column not in fields:
            fallback = next((c for c in ('id', 'utterance_id', 'utt_id', 'audio_id') if c in fields), None)
            if fallback:
                id_column = fallback
        if group_column == 'auto':
            group_column = next((c for c in _AUTO_GROUP_COLS if c in fields), None)
        required = [id_column, split_column] + ([group_column] if group_column else [])
        if any(name not in fields for name in required):
            raise ValueError(f'{path}: required column missing')
        ids, splits, groups = [], defaultdict(set), defaultdict(set)
        split_counts = Counter()
        for row in reader:
            key = (row.get(id_column) or '').strip()
            if not key:
                raise ValueError(f'{path}: blank sample ID at data row {len(ids) + 1}')
            split = (row.get(split_column) or '').strip()
            if not split:
                raise ValueError(f'{path}: blank split at data row {len(ids) + 1}')
            ids.append(key)
            splits[key].add(split)
            split_counts[split] += 1
            if group_column:
                grp = (row.get(group_column) or '').strip()
                if not grp:
                    raise ValueError(f'{path}: blank group ID at data row {len(ids)}')
                groups[grp].add(split)
    counts = Counter(ids)
    return {
        'rows': len(ids),
        'unique_ids': len(counts),
        'duplicate_id_rows': sum(n - 1 for n in counts.values() if n > 1),
        'ids_in_multiple_splits': sum(len(v) > 1 for v in splits.values()),
        'groups_in_multiple_splits': sum(len(v) > 1 for v in groups.values()) if group_column else 0,
        'split_counts': dict(split_counts),
    }


def audit(feature_ids, label_ids, feature_splits=None, label_splits=None,
          feature_groups=None, label_groups=None):
    f, l = Counter(feature_ids), Counter(label_ids)
    shared = f.keys() & l.keys()
    result = {
        'feature_rows': len(feature_ids),
        'label_rows': len(label_ids),
        'feature_duplicate_id_rows': sum(n - 1 for n in f.values() if n > 1),
        'label_duplicate_id_rows': sum(n - 1 for n in l.values() if n > 1),
        'feature_ids_without_labels': len(f.keys() - l.keys()),
        'label_ids_without_features': len(l.keys() - f.keys()),
        'shared_ids_with_different_multiplicity': sum(f[k] != l[k] for k in shared),
        'positionwise_id_mismatches': sum(a != b for a, b in zip(feature_ids, label_ids)),
        'positionwise_comparison_rows': min(len(feature_ids), len(label_ids)),
    }
    if feature_splits is not None:
        result['feature_ids_in_multiple_splits'] = sum(len(v) > 1 for v in feature_splits.values())
    if label_splits is not None:
        result['label_ids_in_multiple_splits'] = sum(len(v) > 1 for v in label_splits.values())
    if feature_splits is not None and label_splits is not None:
        result['shared_ids_with_split_disagreement'] = sum(feature_splits[k] != label_splits[k] for k in shared)
    if feature_groups is not None:
        result['feature_groups_in_multiple_splits'] = sum(len(v) > 1 for v in feature_groups.values())
    if label_groups is not None:
        result['label_groups_in_multiple_splits'] = sum(len(v) > 1 for v in label_groups.values())
    if feature_groups is not None and label_groups is not None:
        shared_groups = feature_groups.keys() & label_groups.keys()
        result['shared_groups_with_split_disagreement'] = sum(
            feature_groups[g] != label_groups[g] for g in shared_groups
        )
    result['interpretation'] = 'Counts identify checks to investigate. Repeated IDs or cross-split presence may be valid for the study design; positional mismatch matters only if joining by row position. This audit does not establish leakage, label correctness, method failure, or a research gap.'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('features_csv')
    parser.add_argument('labels_csv')
    parser.add_argument('--id-column', default='sample_id')
    parser.add_argument('--split-column', default=None)
    parser.add_argument('--group-column', default=None)
    parser.add_argument('--out', type=Path, default=None)
    parser.add_argument('--compact', action='store_true')
    args = parser.parse_args()
    try:
        fids, fsplits, fgroups = load_with_groups(args.features_csv, args.id_column, args.split_column, args.group_column)
        lids, lsplits, lgroups = load_with_groups(args.labels_csv, args.id_column, args.split_column, args.group_column)
        report = audit(
            fids, lids,
            fsplits if args.split_column else None,
            lsplits if args.split_column else None,
            fgroups if args.group_column else None,
            lgroups if args.group_column else None,
        )
        out_path = args.out
        if args.compact and out_path is None:
            out_path = _auto_artifact_path('audit_alignment')
        if out_path is not None:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
        if args.compact:
            summary = {k: v for k, v in report.items() if k != 'interpretation'}
            summary['compact'] = True
            summary['artifact_path'] = str(out_path)
            print(json.dumps(summary, separators=(',', ':'), ensure_ascii=False))
        else:
            print(json.dumps(report))
    except (OSError, UnicodeError, ValueError, csv.Error) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
