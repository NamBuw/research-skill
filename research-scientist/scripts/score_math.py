#!/usr/bin/env python3
"""Calculate a declared weighted score; never supply scientific judgments."""
import json
import sys
from decimal import Decimal, ROUND_HALF_UP

DIMENSIONS = ('importance', 'novelty', 'soundness', 'evidence', 'transparency', 'clarity')

def score(document):
    weights = document['weights']
    ratings = document['ratings']
    if set(weights) != set(DIMENSIONS) or set(ratings) != set(DIMENSIONS):
        raise ValueError('Exactly six named dimensions are required')
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 or v > 100 for v in weights.values()):
        raise ValueError('Weights must be integer percentages in 0..100')
    if sum(weights.values()) != 100:
        raise ValueError('Weights must sum to 100')
    if any(v is not None and (isinstance(v, bool) or not isinstance(v, int) or v < 0 or v > 10) for v in ratings.values()):
        raise ValueError('Ratings must be integers in 0..10 or null')
    if any(v is None for v in ratings.values()):
        return {'overall': None, 'status': 'not_comparable', 'reason': 'missing dimension'}
    raw = sum(Decimal(weights[k]) * Decimal(ratings[k]) for k in DIMENSIONS) / Decimal(100)
    return {'overall': int(raw.quantize(Decimal('1'), rounding=ROUND_HALF_UP)), 'weighted_unrounded': str(raw), 'status': 'calculated', 'warning': 'Arithmetic only; inspect evidence, rubric, confidence and fatal gates separately.'}

if __name__ == '__main__':
    try:
        print(json.dumps(score(json.load(sys.stdin))))
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        sys.exit(2)
