#!/usr/bin/env python3
"""Search local text or MinerU Content List V2 for inspectable passage leads.

The tool ranks extracted spans. It does not establish bibliographic identity,
claim entailment, parser fidelity, or literature coverage.
"""
import argparse
import hashlib
import html
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
ALLOWED = {'.md', '.txt', '.json'}


def tokens(value):
    return [match.group().casefold() for match in TOKEN.finditer(value)]


def _spans(value):
    if not isinstance(value, list):
        return ''
    return ''.join(item.get('content', '') for item in value
                   if isinstance(item, dict) and isinstance(item.get('content'), str))


def _v2_text(item):
    content = item.get('content')
    if not isinstance(content, dict):
        return ''
    kind = item.get('type')
    if kind == 'paragraph':
        return _spans(content.get('paragraph_content'))
    if kind == 'title':
        return _spans(content.get('title_content'))
    if kind == 'page_footnote':
        return _spans(content.get('page_footnote_content'))
    if kind == 'equation_interline':
        return content.get('math_content', '') if isinstance(content.get('math_content'), str) else ''
    if kind == 'list':
        return ' '.join(_spans(x.get('item_content')) for x in content.get('list_items', [])
                        if isinstance(x, dict))
    if kind == 'table':
        parts = [_spans(content.get('table_caption')), _spans(content.get('table_footnote'))]
        html_source = content.get('html')
        if isinstance(html_source, str):
            parts.append(re.sub(r'<[^>]+>', ' ', html_source))
        return ' '.join(parts)
    if kind in {'image', 'chart'}:
        return ' '.join(_spans(content.get(f'{kind}_{suffix}')) for suffix in ('caption', 'footnote'))
    if kind in {'algorithm', 'code'}:
        key = 'algorithm_content' if kind == 'algorithm' else 'code_content'
        return _spans(content.get(key))
    return ''


def _text_segments(source):
    text = source.read_text(encoding='utf-8')
    lines = text.splitlines()
    current = []
    start = None
    for n, line in enumerate(lines, start=1):
        if line.strip():
            if start is None:
                start = n
            current.append(line)
        elif current:
            yield {'text': '\n'.join(current), 'line_start': start, 'line_end': n - 1,
                   'kind': 'text_paragraph'}
            current, start = [], None
    if current:
        yield {'text': '\n'.join(current), 'line_start': start, 'line_end': len(lines),
               'kind': 'text_paragraph'}


def _json_segments(source):
    payload = json.loads(source.read_text(encoding='utf-8'))
    if not isinstance(payload, list):
        raise ValueError('MinerU Content List V2 must be a list of pages or a flat item list')
    if payload and all(isinstance(x, dict) for x in payload):
        pages = [payload]
        flat = True
    elif all(isinstance(page, list) for page in payload):
        pages = payload
        flat = False
    else:
        raise ValueError('unsupported Content List V2 shape')
    for page_number, page in enumerate(pages, start=1):
        for item_number, item in enumerate(page, start=1):
            if not isinstance(item, dict):
                continue
            value = html.unescape(_v2_text(item)).strip()
            if not value:
                continue
            page_idx = item.get('page_idx') if flat else page_number - 1
            locator = {'kind': item.get('type'), 'item_index': item_number - 1,
                       'text': value, 'visual_check_required': item.get('type') in
                       {'table', 'image', 'chart', 'equation_interline', 'algorithm', 'code'}}
            if isinstance(page_idx, int) and page_idx >= 0:
                locator['page_index_zero_based'] = page_idx
            bbox = item.get('bbox')
            if isinstance(bbox, list) and len(bbox) == 4 and all(isinstance(x, (int, float)) for x in bbox):
                locator['bbox_as_provided'] = bbox
            if isinstance(item.get('anchor'), str):
                locator['anchor'] = item['anchor']
            yield locator


def load(paths):
    sources = {}
    for raw in paths:
        path = Path(raw).expanduser().resolve()
        if path.is_dir():
            for candidate in path.rglob('*'):
                if candidate.is_file() and candidate.suffix.lower() in ALLOWED:
                    sources.setdefault(candidate, False)
        elif path.is_file():
            if path.suffix.lower() not in ALLOWED:
                raise ValueError(f'unsupported file type: {path}')
            sources[path] = True
        else:
            raise ValueError(f'path not found: {path}')
    segments = []
    skipped = []
    loaded = 0
    for path in sorted(sources):
        try:
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            iterator = _json_segments(path) if path.suffix.lower() == '.json' else _text_segments(path)
            extracted = list(iterator)
        except (ValueError, OSError, json.JSONDecodeError, UnicodeError) as exc:
            if sources[path]:
                raise
            skipped.append({'path': str(path), 'error': type(exc).__name__, 'detail': str(exc)})
            continue
        loaded += 1
        for index, segment in enumerate(extracted, start=1):
            if not segment['text'].strip():
                continue
            segments.append({'source': str(path), 'sha256': digest, 'segment_id': f'{digest[:12]}:{index}',
                             **segment})
    return segments, loaded, skipped


def search(segments, query, limit=10):
    q = set(tokens(query))
    if not q:
        raise ValueError('query has no searchable terms')
    if not 1 <= limit <= 100:
        raise ValueError('limit must be 1..100')
    terms = [Counter(tokens(s['text'])) for s in segments]
    docfreq = Counter(term for counts in terms for term in counts)
    average_length = sum(sum(c.values()) for c in terms) / len(terms) if terms else 1
    ranked = []
    for segment, counts in zip(segments, terms):
        length = sum(counts.values())
        score = 0.0
        matched = []
        for term in q:
            frequency = counts[term]
            if frequency:
                matched.append(term)
                idf = math.log(1 + (len(segments) - docfreq[term] + .5) / (docfreq[term] + .5))
                score += idf * frequency * 2.2 / (frequency + 1.2 * (.25 + .75 * length / average_length))
        if score:
            lead = {key: value for key, value in segment.items() if key != 'text'}
            lead.update({'score': round(score, 5), 'matched_terms': sorted(matched),
                         'excerpt': segment['text'][:700], 'excerpt_truncated': len(segment['text']) > 700})
            ranked.append(lead)
    ranked.sort(key=lambda x: (-x['score'], x['source'], x['segment_id']))
    return ranked[:limit], len(ranked)


def run(paths, query, limit=10):
    segments, source_count, skipped = load(paths)
    results, matching_count = search(segments, query, limit)
    return {'query': query, 'source_files': source_count, 'skipped_files': skipped,
            'segments_indexed': len(segments),
            'matching_segments': matching_count, 'returned': len(results), 'results': results,
            'warning': 'Lexical matches are passage leads only. Verify source identity, original PDF layout, and claim entailment manually; no full-text or field coverage is implied.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('query')
    parser.add_argument('paths', nargs='+', help='Local .md/.txt files, MinerU Content List V2 .json, or directories')
    parser.add_argument('--limit', type=int, default=10)
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.paths, args.query, args.limit), ensure_ascii=False))
    except (ValueError, OSError, json.JSONDecodeError, UnicodeError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        sys.exit(2)
