#!/usr/bin/env python3
"""Read-only CSV identity/split audit. Counts are diagnostic, never proof of leakage."""
import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def load(path, id_column, split_column):
    with Path(path).open(newline='', encoding='utf-8-sig') as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        required = [id_column] + ([split_column] if split_column else [])
        if any(name not in fields for name in required):
            raise ValueError(f'{path}: required column missing')
        ids, splits = [], defaultdict(set)
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
    return ids, splits


def audit(feature_ids, label_ids, feature_splits=None, label_splits=None):
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
    result['interpretation'] = 'Counts identify checks to investigate. Repeated IDs or cross-split presence may be valid for the study design; positional mismatch matters only if joining by row position. This audit does not establish leakage, label correctness, method failure, or a research gap.'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('features_csv')
    parser.add_argument('labels_csv')
    parser.add_argument('--id-column', default='sample_id')
    parser.add_argument('--split-column', default=None)
    args = parser.parse_args()
    try:
        fids, fsplits = load(args.features_csv, args.id_column, args.split_column)
        lids, lsplits = load(args.labels_csv, args.id_column, args.split_column)
        print(json.dumps(audit(fids, lids, fsplits if args.split_column else None, lsplits if args.split_column else None)))
    except (OSError, UnicodeError, ValueError, csv.Error) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2
    return 0

if __name__ == '__main__':
    sys.exit(main())
