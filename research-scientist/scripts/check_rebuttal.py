#!/usr/bin/env python3
"""Peer-review rebuttal checker: OpenReview/CVPR-1p budget + R1.1/AC.1 coverage & anchor/non-fabrication guard.

SPDX-License-Identifier: Apache-2.0

Attribution & License Notice:
- Budget & coverage logic adapted from `ShaishavMaisuria/research-paper-lifecycle-skills`
  (`skills/write-rebuttal/scripts/check_budget.py` & `check_coverage.py`, Apache-2.0 License,
  Copyright 2026 Shaishav Maisuria).
- Rebuttal non-fabrication guard inspired by `chtc66/academic-skills` (`review-rebuttal`, MIT License).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zlib
from pathlib import Path
from typing import Any

MAX_COMPACT_BYTES = 3800
DEFAULT_CHAR_LIMIT = 10000
DEFAULT_MAX_PAGES = 1
_MAX_STREAM_BYTES = 16 * 1024 * 1024
_MAX_TOTAL_INFLATED = 64 * 1024 * 1024

_PT_ID_TOK = r"(?:(?:R\d+|AC|MR)[.-]\d+|R\d+[.-][QWCM]\d+|[QWCM]\d+)"
_MD_OPEN = r"(?:[*_]{1,3}\[?|\[[*_]{0,3})?"
_MD_CLOSE = r"(?:\][*_]{0,3}|[*_]{1,3}\]?)?"

STRUCTURED_POINT_RE = re.compile(r"\b((?:R\d+|AC|MR)[.-]\d+|R\d+[.-][QWCM]\d+)\b")
SHORT_POINT_DEF_RE = re.compile(
    rf"(?m)^[ \t]*(?=\S)(?:(?:[-*+]|\d+[.)]|#{{1,4}})[ \t]*)?{_MD_OPEN}([QWCM]\d+){_MD_CLOSE}(?=[ \t]*[:.)\]\u2014-])"
)
POINT_ID_RE = STRUCTURED_POINT_RE

ANCHOR_RE = re.compile(
    r"(?ix)"
    r"(\bsec(?:tion)?s?[.\s~]*(?:[AS]?\d|[IVX]+\b))"
    r"|(\btab(?:le)?s?[.\s~]*[AS]?\d)"
    r"|(\bfig(?:ure)?s?[.\s~]*[AS]?\d)"
    r"|(\beq(?:uation)?s?[.\s~]*\(?\d)"
    r"|(\bapp(?:endix)?[.\s~]+[a-z0-9])"
    r"|(\balg(?:orithm)?s?[.\s~]*\d)"
    r"|(\blines?\s+\d+)"
    r"|(\bL\d{2,}\b)"
    r"|(\babstract\b)"
    r"|((?<![\w\\\]\)])\[\d+(?:,\s*\d+)*\])"
)
RECEIPT_RE = re.compile(
    r"(?ix)"
    r"(?:\brun[_-]?id\s*[:=]\s*[A-Za-z0-9._-]+"
    r"|\b(?:sha256|commit|hash)\s*[:=]\s*[0-9a-f]{7,}\b"
    r"|(?:^|[\s(\[`'\"])(?:[A-Za-z0-9_.-]+/){0,6}[A-Za-z0-9_.-]+\.(?:json|jsonl|csv|tsv|log|txt|yaml|yml|md|pdf|png|svg)\b)"
)
NEW_EXP_CLAIM_RE = re.compile(
    r"\b(?:we\s+(?:also\s+|have\s+|already\s+|newly\s+)?(?:ran|run|conducted|executed|performed|added|completed)\s+"
    r"(?:new|additional|extra|further|follow-up)\s+(?:experiments?|ablations?|runs?|evaluations?|studies)"
    r"|(?:new|additional|extra|further|follow-up)\s+(?:experiments?|ablations?|runs?|evaluations?)\s+"
    r"(?:confirm|show|demonstrate|indicate|reveal|verify|yield|prove))\b",
    re.I,
)
_NEGATION_RE = re.compile(
    r"(?:\b(?:did|do|does|have|has|had|could|can|were|was|are|is|will|would)\s+not\s+(?:\w+\s+){0,2}$"
    r"|\b(?:didn't|don't|haven't|hasn't|hadn't|couldn't|won't|wouldn't|never|cannot)\s+(?:\w+\s+){0,2}$"
    r"|\bno\s+$)",
    re.I,
)
PLANNED_CAVEAT_RE = re.compile(
    r"\b(?:will\s+(?:run|add|include|conduct|perform|evaluate|provide)"
    r"|plan(?:ned)?\s+(?:to\s+(?:run|add|include|conduct)|for\s+(?:camera-?ready|revision))"
    r"|deferred\s+to\s+(?:camera-?ready|future\s+work))\b",
    re.I,
)
SYCOPHANCY_RE = re.compile(
    r"\b(?:brilliant|genius|extraordinary\s+insight|invaluable\s+wisdom|completely\s+right|100%\s+agree|wholeheartedly\s+agree)\b",
    re.I,
)
VAGUE_PROMISE_RE = re.compile(
    r"\bwe\s+will\s+(?:address|improve|fix|polish|clarify)\s+(?:this|it|the\s+writing)\b",
    re.I,
)
_REV_QUOTE_PREFIX_RE = re.compile(
    r"^\s*(?:[-*+]\s*)?(?:\*\*|__)?(?:Reviewer(?:\s+\w+)?\s+(?:comment|question|concern|point)|Original\s+(?:comment|critique))(?:\*\*|__)?\s*:\s*([\"“])",
    re.I,
)
_SUBPOINT_LINE_RE = re.compile(
    rf"^\s*(?=\S)(?:>\s*)?(?:(?:[-*+]|\d+[.)])\s*)?{_MD_OPEN}(?:(?:Addressing|For|Regarding|Response\s+to)\s+)?({_PT_ID_TOK}){_MD_CLOSE}(?=\s*(?:[:.)\]\u2014-]|,|and\b|&))",
    re.I,
)
_LEADING_POINT_HEADER_RE = re.compile(
    rf"^\s*(?=\S)(?:(?:[-*+]|\d+[.)]|#{{1,4}})\s*)?{_MD_OPEN}(?:(?:Addressing|For|Regarding|Response\s+to)\s+)?"
    rf"(?:{_PT_ID_TOK}{_MD_CLOSE}"
    rf"(?:\s*(?:,|and|&)\s*{_MD_OPEN}{_PT_ID_TOK}{_MD_CLOSE})*)"
    rf"(?:\s*[:.)\]\u2014-]+)?{_MD_CLOSE}(?:\s*[:.)\]\u2014-]+)?",
    re.I,
)
_HANGING_END_RE = re.compile(
    r"(?:[,;:\-(\[]|\b(?:and|or|but|in|on|at|to|for|by|of|with|via|from|that|which|where|as|the|a|an|see|showing|confirming|demonstrating|comparing|against|across|between))$",
    re.I,
)
_ABBREV_MASK_RE = re.compile(
    r"\b(?:Sec|Fig|Eq|Tab|App|Alg|Ref|No|Dr|Prof|Mr|Ms|et\s+al|e\.g|i\.e|vs)\.",
    re.I,
)
_TAIL_STREAM_RE = re.compile(rb">>\s{0,16}stream(?:\r\n|\n|\r)")
_HEADING_LINE_RE = re.compile(r"^\s*#{1,4}\s+")
_BLOCKQUOTE_LINE_RE = re.compile(r"^\s*>")
_SUB_H_RE = re.compile(r"^\s*#{3,4}\s+(.+)")
_CONT_LINE_BLOCK_RE = re.compile(r"^(?:[-*+]|\d+[.)]|#{1,4}|>)\s*")
_SENT_SPLIT_RE = re.compile(r"(?:(?<![.!?])[.!?]+(?:\s+|$)|\n+)")
_POINT_DEC_MASK_RE = re.compile(r"\b(?:R\d+|AC|MR)\.\d+\b|\d+\.\d+")
_SHORT_ID_FULL_RE = re.compile(r"[QWCM]\d+")
_SHORT_ID_TOKEN_RE = re.compile(r"\b([QWCM]\d+)\b")
_TITLE_SHORT_ID_RE = re.compile(
    r"(?i)(?:^|\b(?:addressing|for|regarding|response\s+to)\s+|,\s*|&\s*|\band\s+)"
    r"(?:\*\*?|__?|\[)?([QWCM]\d+)(?:\*\*?|__?|\])?(?=$|\s*(?:[:.)\]\u2014-]|,|&|\band\b))"
)


def _err(msg: str) -> int:
    print(json.dumps({"error": msg}), file=sys.stderr)
    return 2


def _nonempty(val: Any, flag: str) -> str:
    if not isinstance(val, str) or not val.strip():
        raise ValueError(f"Empty or invalid path for {flag}")
    return val.strip()


def _read_text_checked(path: Path, label: str) -> str:
    raw = path.read_bytes()
    if b"\x00" in raw:
        raise ValueError(f"{label} appears to be a binary file (contains NUL bytes): {path}")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} is not valid UTF-8 text: {path}") from exc


def _emit(payload: dict[str, Any], compact: dict[str, Any], args: argparse.Namespace) -> None:
    if getattr(args, "out", None) is not None:
        op = Path(_nonempty(args.out, "--out"))
        op.parent.mkdir(parents=True, exist_ok=True)
        op.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    json_arg = getattr(args, "json", None)
    if json_arg is not None and json_arg != "-":
        jp = Path(_nonempty(json_arg, "--json"))
        jp.parent.mkdir(parents=True, exist_ok=True)
        jp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if getattr(args, "compact", False):
        trimmed = dict(compact)
        raw = json.dumps(trimmed, separators=(",", ":"))
        for cap in (5, 2, 1, 0):
            if len(raw.encode("utf-8")) <= MAX_COMPACT_BYTES:
                break
            for k in list(trimmed):
                if isinstance(trimmed[k], list) and len(trimmed[k]) > cap:
                    trimmed[k] = trimmed[k][:cap]
            raw = json.dumps(trimmed, separators=(",", ":"))
        print(raw)
    elif json_arg == "-":
        print(json.dumps(payload, indent=2))
    elif json_arg is not None:
        print(json.dumps(compact, separators=(",", ":")))
    else:
        print(json.dumps(payload, indent=2))


def split_sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    title = "(preamble)"
    buf: list[str] = []
    for line in text.splitlines():
        if line.startswith("## ") and not line.startswith("###"):
            sections.append((title, "\n".join(buf)))
            title = line[3:].strip() or "(untitled section)"
            buf = []
        else:
            buf.append(line)
    sections.append((title, "\n".join(buf)))
    return [
        (name, body.strip("\n"))
        for name, body in sections
        if not (name == "(preamble)" and not body.strip())
    ]


def _try_zlib_decompress_span(
    mv: memoryview,
    start: int,
    end: int,
    max_bytes: int,
    _stats: list[int] | None = None,
) -> tuple[bytes, int, bool]:
    if max_bytes <= 0:
        return b"", start, False
    if end - start >= 2:
        cmf = mv[start]
        flg = mv[start + 1]
        if (cmf & 0x0F) != 8 or (cmf >> 4) > 7 or (flg & 0x20) != 0 or (((cmf << 8) | flg) % 31) != 0:
            if _stats is not None:
                _stats[0] += 2
            raise zlib.error("invalid zlib header")
    d = zlib.decompressobj()
    chunks: list[bytes] = []
    total_out = 0
    pos = start
    step = 64
    while pos < end and not d.eof and total_out < max_bytes:
        nxt = min(pos + step, end)
        if _stats is not None:
            _stats[0] += nxt - pos
        out = d.decompress(mv[pos:nxt], max_bytes - total_out)
        if out:
            chunks.append(out)
            total_out += len(out)
        pos = nxt
        if step < 16384:
            step = min(step * 4, 16384)
    consumed_end = (pos - len(d.unused_data)) if d.eof else pos
    return b"".join(chunks), consumed_end, d.eof


def _try_zlib_decompress(
    mv: memoryview,
    start: int,
    end: int,
    max_bytes: int,
    _stats: list[int] | None = None,
) -> bytes:
    decomp, _, _ = _try_zlib_decompress_span(mv, start, end, max_bytes, _stats)
    return decomp


def count_pdf_pages(data: bytes) -> tuple[int, str]:
    page_re = re.compile(rb"/Type\s*/Page(?![s/\w])")
    n = len(page_re.findall(data))
    if n:
        return n, "uncompressed /Type /Page objects"

    inflated: list[bytes] = []
    total_inflated = 0
    pos = 0
    cached_end = -1
    block_start = -1
    block_failed = 0
    mv = memoryview(data)
    stream_re = re.compile(rb"(?:>>|[\x00\t\n\f\r ])stream(?:\r\n|\n|\r)")
    while pos < len(data) and total_inflated < _MAX_TOTAL_INFLATED:
        m = stream_re.search(data, pos)
        if not m:
            break
        start = m.end()
        if cached_end < start:
            cached_end = data.find(b"endstream", start)
            block_start = start
            block_failed = 0
        end = cached_end
        if end == -1:
            break
        stats = [0]
        try:
            decomp, consumed_end, hit_eof = _try_zlib_decompress_span(
                mv, start, end, _MAX_STREAM_BYTES, stats
            )
            if decomp:
                inflated.append(decomp)
                total_inflated += len(decomp)
            if hit_eof and total_inflated < _MAX_TOTAL_INFLATED:
                next_pos = max(consumed_end, start)
                inner = stream_re.search(data, next_pos, end)
                if inner is not None:
                    pos = inner.start()
                    continue
        except zlib.error:
            block_failed += max(stats[0], 1)
            budget = max(2 * (end - block_start), 4096)
            if block_failed < budget:
                inner = stream_re.search(data, start, end)
                if inner is not None:
                    pos = inner.start()
                    continue
            else:
                tail_budget = max(2 * (end - block_start), 4096)
                tail_failed = 0
                tm_iter = _TAIL_STREAM_RE.finditer(data, start, end)
                cur_tm = next(tm_iter, None)
                while cur_tm is not None:
                    if total_inflated >= _MAX_TOTAL_INFLATED or tail_failed >= tail_budget:
                        break
                    nxt_tm = next(tm_iter, None)
                    span_end = nxt_tm.start() if nxt_tm is not None else end
                    if cur_tm.end() > start:
                        tail_stats = [0]
                        try:
                            decomp = _try_zlib_decompress(
                                mv, cur_tm.end(), span_end, _MAX_STREAM_BYTES, tail_stats
                            )
                            if decomp:
                                inflated.append(decomp)
                                total_inflated += len(decomp)
                        except zlib.error:
                            tail_failed += max(tail_stats[0], 1)
                    cur_tm = nxt_tm
        pos = end + 9
    blob = b"\n".join(inflated)
    n = len(page_re.findall(blob))
    if n:
        return n, "FlateDecode object streams"

    pages_re_1 = re.compile(rb"/Type\s*/Pages[^>]{0,1000}?/Count\s+(\d+)", re.S)
    pages_re_2 = re.compile(rb"/Count\s+(\d+)[^>]{0,1000}?/Type\s*/Pages", re.S)
    counts: list[int] = []
    for buf in (data, blob):
        if buf:
            counts.extend(int(c) for c in pages_re_1.findall(buf))
            counts.extend(int(c) for c in pages_re_2.findall(buf))
    counts = [c for c in counts if c > 0]
    if counts:
        return max(counts), "/Count in /Type /Pages node"
    raise ValueError("Could not determine a positive PDF page count")


def check_budget_text(file_path: Path, *, sections_mode: bool = False, limit: int = DEFAULT_CHAR_LIMIT) -> dict[str, Any]:
    if not file_path.is_file():
        raise FileNotFoundError(f"Rebuttal file not found: {file_path}")
    if limit < 1:
        raise ValueError("--limit must be >= 1")
    text = _read_text_checked(file_path, "Rebuttal file")
    if not text.strip():
        raise ValueError(f"Rebuttal file is empty: {file_path}")
    secs = split_sections(text) if sections_mode else [("(whole file)", text.strip("\n"))]
    if not secs:
        raise ValueError(f"No content found in {file_path}")

    rows: list[dict[str, Any]] = []
    over: list[str] = []
    for title, body in secs:
        chars = len(body)
        words = len(body.split())
        margin = limit - chars
        status = "OK" if margin >= 0 else "OVER"
        if margin < 0:
            over.append(title)
        rows.append({"section": title, "chars": chars, "words": words, "margin": margin, "status": status})

    return {
        "schema": "rebuttal_budget_v1",
        "mode": "text",
        "file": str(file_path),
        "limit": limit,
        "sections": rows,
        "over_budget_sections": over,
        "verdict": "OVER_BUDGET" if over else "PASS",
    }


def check_budget_pdf(file_path: Path, *, max_pages: int = DEFAULT_MAX_PAGES) -> dict[str, Any]:
    if not file_path.is_file():
        raise FileNotFoundError(f"PDF file not found: {file_path}")
    if max_pages < 1:
        raise ValueError("--max-pages must be >= 1")
    data = file_path.read_bytes()
    if not data.startswith(b"%PDF"):
        raise ValueError(f"File is not a valid PDF (missing %PDF header): {file_path}")

    try:
        import fitz  # type: ignore

        try:
            with fitz.open(str(file_path)) as doc:
                pages = len(doc)
            method = "pymupdf"
        except Exception as exc:
            raise ValueError(f"Corrupt or unreadable PDF {file_path}: {exc}") from exc
    except ImportError:
        pages, method = count_pdf_pages(data)

    if pages < 1:
        raise ValueError(f"PDF has 0 pages: {file_path}")
    return {
        "schema": "rebuttal_budget_v1",
        "mode": "pdf",
        "file": str(file_path),
        "pages": pages,
        "max_pages": max_pages,
        "method": method,
        "verdict": "OVER_BUDGET" if pages > max_pages else "PASS",
    }


def _find_closing_quote(line: str, start: int, targets: tuple[str, ...]) -> int:
    i = start
    n = len(line)
    while i < n:
        if line[i] == "\\" and i + 1 < n:
            i += 2
            continue
        if line[i] in targets:
            return i
        i += 1
    return -1


def _has_closing_quote_before_heading(
    lines: list[str],
    start_idx: int,
    targets: tuple[str, ...],
    qcache: dict[tuple[str, ...], tuple[int, bool]] | None = None,
) -> bool:
    if qcache is not None:
        cached = qcache.get(targets)
        if cached is not None and start_idx <= cached[0]:
            return cached[1]
    for j in range(start_idx, len(lines)):
        ln = lines[j]
        if _HEADING_LINE_RE.match(ln) or _REV_QUOTE_PREFIX_RE.match(ln) or _BLOCKQUOTE_LINE_RE.match(ln):
            if qcache is not None:
                qcache[targets] = (j, False)
            return False
        if _find_closing_quote(ln, 0, targets) != -1:
            if qcache is not None:
                qcache[targets] = (j, True)
            return True
    if qcache is not None and lines:
        qcache[targets] = (len(lines) - 1, False)
    return False


def _scan_reviewer_quote_lines(text: str) -> tuple[str, list[bool]]:
    lines = text.splitlines()
    kept: list[str] = []
    in_rev_quote: list[bool] = []
    in_quote: str | None = None
    qcache: dict[tuple[str, ...], tuple[int, bool]] = {}
    for idx, line in enumerate(lines):
        if in_quote is not None:
            targets = ('"',) if in_quote == '"' else ("”", '"')
            if _HEADING_LINE_RE.match(line) or (
                _SUBPOINT_LINE_RE.match(line)
                and not _has_closing_quote_before_heading(lines, idx, targets, qcache)
            ):
                in_quote = None
            else:
                in_rev_quote.append(True)
                close_idx = _find_closing_quote(line, 0, targets)
                if close_idx != -1:
                    in_quote = None
                    tail = line[close_idx + 1 :]
                    kept.append(tail if tail.strip() else "")
                else:
                    kept.append("")
                continue

        if _BLOCKQUOTE_LINE_RE.match(line):
            in_rev_quote.append(False)
            kept.append("")
            continue

        qm = _REV_QUOTE_PREFIX_RE.match(line)
        if qm:
            in_rev_quote.append(True)
            open_q = qm.group(1)
            targets = ('"',) if open_q == '"' else ("”", '"')
            close_idx = _find_closing_quote(line, qm.end(), targets)
            if close_idx != -1:
                tail = line[close_idx + 1 :]
                kept.append(tail if tail.strip() else "")
            else:
                in_quote = open_q
                kept.append("")
            continue

        in_rev_quote.append(False)
        kept.append(line)
    return "\n".join(kept), in_rev_quote


def _strip_reviewer_quotes(text: str) -> str:
    stripped, _ = _scan_reviewer_quote_lines(text)
    return stripped


def _extract_point_ids(text: str, short_ids: list[str] | None = None, *, include_short_defs: bool = True) -> list[str]:
    hits: list[tuple[int, str]] = []
    for m in STRUCTURED_POINT_RE.finditer(text):
        hits.append((m.start(), m.group(1)))
    if include_short_defs:
        for m in SHORT_POINT_DEF_RE.finditer(text):
            hits.append((m.start(1), m.group(1)))
    if short_ids:
        short_set = set(short_ids)
        if all(_SHORT_ID_FULL_RE.fullmatch(s) for s in short_set):
            for m in _SHORT_ID_TOKEN_RE.finditer(text):
                tok = m.group(1)
                if tok in short_set:
                    hits.append((m.start(1), tok))
        else:
            pat = re.compile(r"\b(" + "|".join(re.escape(s) for s in short_ids) + r")\b")
            for m in pat.finditer(text):
                hits.append((m.start(1), m.group(1)))
    hits.sort(key=lambda item: item[0])
    ordered: list[str] = []
    seen: set[str] = set()
    for _, pid in hits:
        if pid not in seen:
            seen.add(pid)
            ordered.append(pid)
    return ordered


def _split_subpoints(sec_body: str, short_ids: list[str]) -> list[tuple[str | None, str, bool]]:
    """Split a section body into (sub_label, sub_body, from_quote_only) tuples."""
    lines = sec_body.splitlines()
    _, in_rev_quote = _scan_reviewer_quote_lines(sec_body)
    blocks: list[tuple[str | None, list[str], bool]] = []
    cur_label: str | None = None
    cur_lines: list[str] = []
    cur_quote_header = False
    in_fence = False

    for idx, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            cur_lines.append(line)
            continue
        if in_fence or (idx < len(in_rev_quote) and in_rev_quote[idx]):
            cur_lines.append(line)
            continue

        is_quote = bool(_BLOCKQUOTE_LINE_RE.match(line))
        sub_h = _SUB_H_RE.match(line) if not is_quote else None
        pt_m = _SUBPOINT_LINE_RE.match(line)

        new_label: str | None = None
        if sub_h:
            ids_in_h = _extract_point_ids(sub_h.group(1), short_ids)
            new_label = ", ".join(ids_in_h) if ids_in_h else sub_h.group(1).strip()
        elif pt_m:
            # Capture all point IDs on the starting line (handles "Addressing R1.1 and R1.2:")
            ids_in_line = _extract_point_ids(line, short_ids)
            if ids_in_line:
                new_label = ", ".join(ids_in_line)
            else:
                new_label = pt_m.group(1)

        if new_label is not None:
            # If previous block was opened by a `>` quote header with same label and no author prose yet, merge
            if (
                not is_quote
                and cur_label == new_label
                and cur_quote_header
                and not _strip_reviewer_quotes("\n".join(cur_lines)).strip()
            ):
                cur_quote_header = False
                cur_lines.append(line)
                continue
            if cur_lines:
                blocks.append((cur_label, cur_lines, cur_quote_header))
            cur_label = new_label
            cur_lines = [line]
            cur_quote_header = is_quote
        else:
            cur_lines.append(line)

    if cur_lines:
        blocks.append((cur_label, cur_lines, cur_quote_header))

    return [(lbl, "\n".join(bl), qh) for lbl, bl, qh in blocks]


def _has_non_negated_exp_claim(clause: str) -> bool:
    for m in NEW_EXP_CLAIM_RE.finditer(clause):
        prefix = clause[max(0, m.start() - 40) : m.start()]
        if _NEGATION_RE.search(prefix):
            continue
        return True
    return False


def _split_clauses(text: str) -> list[str]:
    """Split author prose into sentence/clause units while keeping protected dots and parentheticals intact."""
    chars = list(text)
    # Mask dots in protected abbreviations, point IDs, and decimals
    for m in _ABBREV_MASK_RE.finditer(text):
        for idx in range(m.start(), m.end()):
            if chars[idx] == ".":
                chars[idx] = "\x01"
    for m in _POINT_DEC_MASK_RE.finditer(text):
        for idx in range(m.start(), m.end()):
            if chars[idx] == ".":
                chars[idx] = "\x01"

    # Mask .!?; inside matched (...) and [...] on the same line only; never leak unclosed delimiters
    stack: list[tuple[str, int, list[int]]] = []
    for idx, ch in enumerate(chars):
        if ch == "\n":
            stack.clear()
        elif ch in "([":
            if ch == "(" and idx > 0 and text[idx - 1] in ":;=-":
                continue
            stack.append((ch, idx, []))
        elif ch == ")":
            if stack and stack[-1][0] == "(":
                _och, _oidx, puncts = stack.pop()
                for pidx in puncts:
                    chars[pidx] = "\x02" if chars[pidx] == ";" else "\x01"
            elif stack and stack[-1][0] == "[" and idx - stack[-1][1] <= 40:
                # Half-open math interval [a, b)
                stack.pop()
        elif ch == "]":
            if stack and stack[-1][0] == "[":
                _och, _oidx, puncts = stack.pop()
                for pidx in puncts:
                    chars[pidx] = "\x02" if chars[pidx] == ";" else "\x01"
            elif stack and stack[-1][0] == "(" and idx - stack[-1][1] <= 40:
                # Half-open math interval (a, b]
                stack.pop()
        elif stack and ch in ".!?;":
            stack[-1][2].append(idx)

    masked = "".join(chars)
    groups: list[list[str]] = []
    for raw_ln in masked.splitlines():
        ln = raw_ln.strip()
        if not ln:
            groups.append([])
            continue
        if (
            groups
            and groups[-1]
            and groups[-1][-1][-1] not in ".!?"
            and not _CONT_LINE_BLOCK_RE.match(ln)
            and (
                ln[0] in "([,;:"
                or ln[0].islower()
                or bool(_HANGING_END_RE.search(groups[-1][-1][-32:]))
            )
        ):
            groups[-1].append(ln)
        else:
            groups.append([ln])

    normalized = "\n".join(" ".join(g) if g else "" for g in groups)
    raw_sentences = _SENT_SPLIT_RE.split(normalized)
    clauses: list[str] = []
    for sent in raw_sentences:
        restored = sent.replace("\x01", ".").strip()
        if not restored:
            continue
        if ";" in restored:
            parts = [p.replace("\x02", ";").strip() for p in restored.split(";") if p.replace("\x02", ";").strip()]
            # Keep "We ran new experiments; see Table 3" together if right side has no new claim and has anchor
            if len(parts) == 2 and not _has_non_negated_exp_claim(parts[1]) and (ANCHOR_RE.search(parts[1]) or RECEIPT_RE.search(parts[1])):
                clauses.append(restored.replace("\x02", ";"))
            else:
                clauses.extend(parts)
        else:
            clauses.append(restored.replace("\x02", ";"))
    return clauses


def _extract_title_point_ids(title: str, short_ids: list[str]) -> list[str]:
    if not title or title == "(preamble)":
        return []
    hits: list[tuple[int, str]] = []
    for m in STRUCTURED_POINT_RE.finditer(title):
        hits.append((m.start(), m.group(1)))
    for m in SHORT_POINT_DEF_RE.finditer(title):
        hits.append((m.start(1), m.group(1)))
    if short_ids:
        short_set = set(short_ids)
        if all(_SHORT_ID_FULL_RE.fullmatch(s) for s in short_set):
            short_upper = {s.upper() for s in short_set}
            for m in _TITLE_SHORT_ID_RE.finditer(title):
                tok = m.group(1)
                if tok.upper() in short_upper:
                    hits.append((m.start(1), tok))
        else:
            pat = re.compile(
                r"(?i)(?:^|\b(?:addressing|for|regarding|response\s+to)\s+|,\s*|&\s*|\band\s+)"
                r"(?:\*\*?|__?|\[)?(" + "|".join(re.escape(s) for s in short_ids) + r")(?:\*\*?|__?|\])?"
                r"(?=$|\s*(?:[:.)\]\u2014-]|,|&|\band\b))"
            )
            for m in pat.finditer(title):
                hits.append((m.start(1), m.group(1)))
    hits.sort(key=lambda item: item[0])
    ordered: list[str] = []
    seen: set[str] = set()
    for _, pid in hits:
        if pid not in seen:
            seen.add(pid)
            ordered.append(pid)
    return ordered


def _has_substantive_author_text(author_sub: str, sub_lbl: str | None) -> bool:
    stripped = author_sub.strip()
    if not stripped:
        return False
    if sub_lbl is None:
        return True
    lines = stripped.splitlines()
    rest_first = _LEADING_POINT_HEADER_RE.sub("", lines[0], count=1).strip()
    remainder = "\n".join([rest_first, *lines[1:]]).strip()
    return bool(remainder)


def check_coverage(points_path: Path, response_paths: list[Path]) -> dict[str, Any]:
    if not points_path.is_file():
        raise FileNotFoundError(f"Points file not found: {points_path}")
    points_text = _read_text_checked(points_path, "Points file")
    point_ids = _extract_point_ids(points_text, include_short_defs=True)
    if not point_ids:
        raise ValueError(f"No point IDs (R<k>.<n> / AC.<n> / MR.<n> / Q<n> / W<n>) found in {points_path}")
    short_ids = [p for p in point_ids if re.fullmatch(r"[QWCM]\d+", p)]

    resp_texts: dict[str, str] = {}
    for rp in response_paths:
        if not rp.is_file():
            raise FileNotFoundError(f"Response file not found: {rp}")
        txt = _read_text_checked(rp, "Response file")
        if not txt.strip():
            raise ValueError(f"Response file is empty: {rp}")
        resp_texts[str(rp)] = txt

    resp_ids_set: set[str] = set()
    unanchored: list[str] = []
    unverified_exp_claims: list[str] = []
    sycophancy_warnings: list[str] = []
    vague_promise_warnings: list[str] = []
    n_sections = 0

    for path_s, txt in resp_texts.items():
        sections = split_sections(txt)
        for title, body in sections:
            author_sec = _strip_reviewer_quotes(body)
            if (
                title == "(preamble)"
                and len(sections) > 1
                and not _extract_point_ids(author_sec, short_ids)
                and not _has_non_negated_exp_claim(author_sec)
            ):
                continue

            sub_blocks = _split_subpoints(body, short_ids)
            has_labeled_subpoints = any(lbl is not None for lbl, _, _ in sub_blocks)
            multi_block = len(sub_blocks) > 1 and has_labeled_subpoints
            section_has_point_subblocks = any(
                lbl is not None and bool(_extract_point_ids(lbl, short_ids))
                for lbl, _, _ in sub_blocks
            )

            for idx, (sub_lbl, sub_raw, _qh) in enumerate(sub_blocks):
                author_sub = _strip_reviewer_quotes(sub_raw)
                # Skip leading section intro before first labeled point if it has no point IDs or exp claims
                if (
                    multi_block
                    and idx == 0
                    and sub_lbl is None
                    and not _extract_point_ids(author_sub, short_ids)
                    and not _has_non_negated_exp_claim(author_sub)
                ):
                    continue

                if _has_substantive_author_text(author_sub, sub_lbl):
                    resp_ids_set.update(_extract_point_ids(author_sub, short_ids))
                    # If the sub-block header itself came from a `>` quote (e.g. `> **R1.1**: ...`)
                    # and non-empty author text followed it, credit that point ID as addressed.
                    if sub_lbl is not None:
                        resp_ids_set.update(_extract_point_ids(sub_lbl, short_ids))
                    if title != "(preamble)" and not section_has_point_subblocks:
                        resp_ids_set.update(_extract_title_point_ids(title, short_ids))

                n_sections += 1
                label = f"{path_s} :: {title} :: {sub_lbl}" if (multi_block and sub_lbl) else (
                    f"{path_s} :: {title} :: (intro)" if multi_block else f"{path_s} :: {title}"
                )

                has_anchor = bool(ANCHOR_RE.search(author_sub) or RECEIPT_RE.search(author_sub))
                if not has_anchor:
                    unanchored.append(label)

                clauses = _split_clauses(author_sub)
                bad_claim = False
                for clause in clauses:
                    if _has_non_negated_exp_claim(clause):
                        if not (ANCHOR_RE.search(clause) or RECEIPT_RE.search(clause) or PLANNED_CAVEAT_RE.search(clause)):
                            bad_claim = True
                            break
                if bad_claim:
                    unverified_exp_claims.append(label)

                if SYCOPHANCY_RE.search(author_sub):
                    sycophancy_warnings.append(label)
                if VAGUE_PROMISE_RE.search(author_sub) and not has_anchor:
                    vague_promise_warnings.append(label)

    covered = [p for p in point_ids if p in resp_ids_set]
    missing = [p for p in point_ids if p not in resp_ids_set]
    orphans = sorted(resp_ids_set - set(point_ids))

    verdict = "FAIL" if missing else ("PASS_WITH_WARNINGS" if (unanchored or unverified_exp_claims) else "PASS")
    return {
        "schema": "rebuttal_coverage_v1",
        "points_file": str(points_path),
        "response_files": list(resp_texts.keys()),
        "total_points": len(point_ids),
        "covered_points": covered,
        "missing_points": missing,
        "orphan_ids": orphans,
        "sections_checked": n_sections,
        "unanchored_sections": unanchored,
        "unverified_experiment_claims": unverified_exp_claims,
        "sycophancy_warnings": sycophancy_warnings,
        "vague_promise_warnings": vague_promise_warnings,
        "verdict": verdict,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_b = sub.add_parser("budget", help="Check OpenReview char limits or CVPR 1-page PDF budget")
    p_b.add_argument("file", help="Path to markdown/text or compiled PDF rebuttal")
    p_b.add_argument("--mode", choices=("auto", "text", "pdf"), default="auto", help="Budget check mode")
    p_b.add_argument("--sections", action="store_true", help="Treat each '## ' heading as a separate OpenReview box")
    p_b.add_argument("--limit", type=int, default=DEFAULT_CHAR_LIMIT, help="Character limit per section (default 10000)")
    p_b.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES, help="Max PDF pages (default 1)")
    p_b.add_argument("--out", help="Write full JSON output to PATH")
    p_b.add_argument("--json", nargs="?", const="-", help="Emit JSON output")
    p_b.add_argument("--compact", action="store_true", help="Bounded <4KB stdout summary")

    p_c = sub.add_parser("coverage", help="Check R1.1/AC.1/MR.1 coverage and paper evidence anchors")
    p_c.add_argument("points", help="Triage matrix file with R1.1/AC.1/MR.1 point IDs")
    p_c.add_argument("responses", nargs="+", help="One or more response draft files")
    p_c.add_argument("--strict", action="store_true", help="Fail (exit 1) on unanchored sections or unverified claims")
    p_c.add_argument("--out", help="Write full JSON output to PATH")
    p_c.add_argument("--json", nargs="?", const="-", help="Emit JSON output")
    p_c.add_argument("--compact", action="store_true", help="Bounded <4KB stdout summary")

    args = parser.parse_args(argv)
    try:
        if args.out is not None:
            _nonempty(args.out, "--out")
        if args.json is not None and args.json != "-":
            _nonempty(args.json, "--json")

        if args.cmd == "budget":
            fp = Path(_nonempty(args.file, "file"))
            mode = args.mode
            if mode == "auto":
                mode = "pdf" if fp.suffix.lower() == ".pdf" else "text"
            if mode == "pdf":
                res = check_budget_pdf(fp, max_pages=args.max_pages)
                compact = {
                    "compact": True,
                    "schema": res["schema"],
                    "mode": "pdf",
                    "pages": res["pages"],
                    "max_pages": res["max_pages"],
                    "verdict": res["verdict"],
                    "out": args.out,
                }
            else:
                res = check_budget_text(fp, sections_mode=args.sections, limit=args.limit)
                compact = {
                    "compact": True,
                    "schema": res["schema"],
                    "mode": "text",
                    "limit": res["limit"],
                    "section_count": len(res["sections"]),
                    "over_budget_sections": res["over_budget_sections"][:10],
                    "verdict": res["verdict"],
                    "out": args.out,
                }
            _emit(res, compact, args)
            return 1 if res["verdict"] != "PASS" else 0

        pts = Path(_nonempty(args.points, "points"))
        resps = [Path(_nonempty(r, "responses")) for r in args.responses]
        res = check_coverage(pts, resps)
        compact = {
            "compact": True,
            "schema": res["schema"],
            "total_points": res["total_points"],
            "covered_count": len(res["covered_points"]),
            "missing_points": res["missing_points"][:10],
            "unanchored_sections": res["unanchored_sections"][:5],
            "unverified_experiment_claims": res["unverified_experiment_claims"][:5],
            "verdict": res["verdict"],
            "out": args.out,
        }
        _emit(res, compact, args)
        fail_cond = bool(res["missing_points"]) or (
            args.strict and bool(res["unanchored_sections"] or res["unverified_experiment_claims"])
        )
        return 1 if fail_cond else 0
    except (OSError, ValueError, FileNotFoundError) as exc:
        return _err(str(exc))


if __name__ == "__main__":
    sys.exit(main())
