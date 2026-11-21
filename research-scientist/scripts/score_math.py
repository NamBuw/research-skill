#!/usr/bin/env python3
"""Calculate a declared weighted score; never supply scientific judgments."""
import argparse
import json
import sys
from decimal import BasicContext, Decimal, ROUND_HALF_UP, localcontext
from pathlib import Path

DIMENSIONS = ('importance', 'novelty', 'soundness', 'evidence', 'transparency', 'clarity')


def _reject_nonfinite(token):
    raise ValueError(f'Non-finite JSON constant not allowed: {token}')


def score(document):
    if not isinstance(document, dict):
        raise ValueError('Document must be a JSON object')
    weights = document['weights']
    ratings = document['ratings']
    if not isinstance(weights, dict) or not isinstance(ratings, dict):
        raise ValueError('Weights and ratings must be JSON objects')
    if set(weights) != set(DIMENSIONS) or set(ratings) != set(DIMENSIONS):
        raise ValueError('Exactly six named dimensions are required')
    if any(type(v) is not int or v < 0 or v > 100 for v in weights.values()):
        raise ValueError('Weights must be integer percentages in 0..100')
    if sum(weights.values()) != 100:
        raise ValueError('Weights must sum to 100')
    if any(v is not None and (type(v) is not int or v < 0 or v > 10) for v in ratings.values()):
        raise ValueError('Ratings must be integers in 0..10 or null')
    if any(v is None for v in ratings.values()):
        return {'overall': None, 'status': 'not_comparable', 'reason': 'missing dimension'}
    with localcontext(BasicContext) as ctx:
        ctx.prec = 28
        raw = sum(Decimal(weights[k]) * Decimal(ratings[k]) for k in DIMENSIONS) / Decimal(100)
        overall = int(raw.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    return {
        'overall': overall,
        'weighted_unrounded': str(raw),
        'status': 'calculated',
        'warning': 'Arithmetic only; inspect evidence, rubric, confidence and fatal gates separately.',
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input_json', nargs='?', help='Optional path to JSON input (defaults to stdin)')
    args = parser.parse_args(argv)
    try:
        if args.input_json and args.input_json != '-':
            raw_text = Path(args.input_json).read_text(encoding='utf-8')
            payload = json.loads(raw_text, parse_constant=_reject_nonfinite)
        else:
            payload = json.load(sys.stdin, parse_constant=_reject_nonfinite)
        print(json.dumps(score(payload)))
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
