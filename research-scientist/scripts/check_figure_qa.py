#!/usr/bin/env python3
"""Publication figure & palette QA: WCAG contrast + grayscale delta-L* + DPI/JPEG/TrueType/script checks.

SPDX-License-Identifier: MIT

Attribution & License Notice:
- Palette contrast & CIE L* grayscale screening adapted from `K-Dense-AI/scientific-agent-skills`
  (`skills/scientific-visualization/scripts/palette_audit.py`, MIT License).
- Publication figure & plotting-script QA rules adapted from `Haojae/scipilot-figure-skill`
  (`scripts/check_figure.py`, `scripts/visual_qa.py`, `scripts/setup_style.py`, MIT License).
"""
from __future__ import annotations

import argparse
import ast
import io
import itertools
import json
import math
import os
import re
import struct
import sys
import tokenize
import zlib
from pathlib import Path
from typing import Any

MAX_COMPACT_BYTES = 3800
DEFAULT_BACKGROUND = "#FFFFFF"
DEFAULT_GRAYSCALE_DELTA = 10.0
ROLE_THRESHOLDS = {
    "graphical": 3.0,
    "large-text": 3.0,
    "normal-text": 4.5,
    "enhanced-text": 7.0,
}

BUNDLED_PALETTES: dict[str, list[str]] = {
    "okabe_ito": ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#000000"],
    "tol_bright": ["#4477AA", "#EE6677", "#228833", "#CCBB44", "#66CCEE", "#AA3377", "#BBBBBB"],
    "tol_muted": ["#332288", "#88CCEE", "#44AA99", "#117733", "#999933", "#DDCC77", "#CC6677", "#882255"],
    "viridis_6": ["#440154", "#414487", "#2A788E", "#22A884", "#7AD151", "#FDE725"],
}

_FIG_EXTS = {".png", ".jpg", ".jpeg", ".pdf", ".svg", ".eps"}
_SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "env",
    "node_modules", ".mypy_cache", ".pytest_cache", "build", "dist",
}
_HEX_COLOR_RE = re.compile(r"^#?[0-9A-Fa-f]{6}$")
_MAX_PDF_STREAM_BYTES = 8 * 1024 * 1024
_MAX_PDF_TOTAL_BYTES = 32 * 1024 * 1024
_TAIL_STREAM_RE = re.compile(rb">>\s{0,16}stream(?:\r\n|\n|\r)")
_SAVEFIG_CALL_RE = re.compile(r"savefig\s*\(", re.I)
_RC_PDF_CALL_RE = re.compile(r"\brc\s*\(\s*['\"]pdf['\"]\s*,")
_JPEG_ARG_RE = re.compile(r"""\.(?:jpg|jpeg)['"]|\bformat\s*=\s*['"](?:jpg|jpeg)['"]""", re.I)
_FONTTYPE_42_RE = re.compile(r"\bfonttype\s*=\s*42\b")
_FONTTYPE_3_RE = re.compile(r"\bfonttype\s*=\s*3\b")


def _err(msg: str) -> int:
    print(json.dumps({"error": msg}), file=sys.stderr)
    return 2


def _nonempty(val: Any, flag: str) -> str:
    if not isinstance(val, str) or not val.strip():
        raise ValueError(f"Empty or invalid value for {flag}")
    return val.strip()


def _emit(payload: dict[str, Any], compact: dict[str, Any], args: argparse.Namespace) -> None:
    if getattr(args, "out", None) is not None:
        op = Path(_nonempty(args.out, "--out")).expanduser()
        op.parent.mkdir(parents=True, exist_ok=True)
        op.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    json_arg = getattr(args, "json", None)
    if json_arg is not None and json_arg != "-":
        jp = Path(_nonempty(json_arg, "--json")).expanduser()
        jp.parent.mkdir(parents=True, exist_ok=True)
        jp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if getattr(args, "compact", False):
        trimmed = dict(compact)
        raw = json.dumps(trimmed, separators=(",", ":"))
        for cap in (5, 3, 1, 0):
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


# ---------------------------------------------------------------------------
# 1. WCAG 2.2 contrast & CIE L* grayscale palette audit
# ---------------------------------------------------------------------------

def parse_hex_color(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str):
        raise ValueError(f"Expected hex color string, got {type(value).__name__}")
    stripped = value.strip()
    if not _HEX_COLOR_RE.fullmatch(stripped):
        raise ValueError(f"Expected 6-digit hex color, got {value!r}")
    norm = stripped[1:] if stripped.startswith("#") else stripped
    return (int(norm[0:2], 16), int(norm[2:4], 16), int(norm[4:6], 16))


def canonical_hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{c:02X}" for c in rgb)


def _linear_channel(channel: int) -> float:
    enc = channel / 255.0
    return enc / 12.92 if enc <= 0.04045 else ((enc + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = (_linear_channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(c1: tuple[int, int, int], c2: tuple[int, int, int]) -> float:
    l1 = relative_luminance(c1)
    l2 = relative_luminance(c2)
    return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)


def cie_lstar(rgb: tuple[int, int, int]) -> float:
    lum = relative_luminance(rgb)
    delta = 6.0 / 29.0
    t = lum ** (1.0 / 3.0) if lum > delta**3 else (lum / (3.0 * delta**2) + 4.0 / 29.0)
    return 116.0 * t - 16.0


def audit_palette(
    colors: list[str],
    *,
    background: str = DEFAULT_BACKGROUND,
    role: str = "graphical",
    contrast_threshold: float | None = None,
    grayscale_min_delta: float = DEFAULT_GRAYSCALE_DELTA,
    name: str | None = None,
) -> dict[str, Any]:
    if role not in ROLE_THRESHOLDS and contrast_threshold is None:
        raise ValueError(f"Unknown role {role!r}")
    if contrast_threshold is not None:
        if isinstance(contrast_threshold, bool) or not isinstance(contrast_threshold, (int, float)):
            raise ValueError("Contrast threshold must be numeric")
        threshold = float(contrast_threshold)
    else:
        threshold = ROLE_THRESHOLDS[role]
    if not math.isfinite(threshold) or threshold <= 1.0:
        raise ValueError("Contrast threshold must be finite and > 1")
    if isinstance(grayscale_min_delta, bool) or not isinstance(grayscale_min_delta, (int, float)):
        raise ValueError("Grayscale delta-L* threshold must be numeric")
    grayscale_min_delta = float(grayscale_min_delta)
    if not math.isfinite(grayscale_min_delta) or grayscale_min_delta <= 0.0:
        raise ValueError("Grayscale delta-L* threshold must be finite and > 0")
    if not colors or len(colors) > 32:
        raise ValueError("Provide between 1 and 32 palette colors")

    bg_rgb = parse_hex_color(background)
    parsed = [parse_hex_color(c) for c in colors]
    canon = [canonical_hex(rgb) for rgb in parsed]

    color_records: list[dict[str, Any]] = []
    for idx, (hx, rgb) in enumerate(zip(canon, parsed)):
        cr = contrast_ratio(rgb, bg_rgb)
        color_records.append({
            "index": idx,
            "hex": hx,
            "cie_lstar": round(cie_lstar(rgb), 3),
            "contrast_against_background": round(cr, 3),
            "background_screen": "pass" if cr >= threshold else "review",
        })

    pair_records: list[dict[str, Any]] = []
    for i, j in itertools.combinations(range(len(parsed)), 2):
        dl = abs(cie_lstar(parsed[i]) - cie_lstar(parsed[j]))
        pair_records.append({
            "first_hex": canon[i],
            "second_hex": canon[j],
            "grayscale_delta_lstar": round(dl, 3),
            "grayscale_screen": "pass" if dl >= grayscale_min_delta else "review",
        })

    bg_reviews = sum(1 for r in color_records if r["background_screen"] == "review")
    gs_reviews = sum(1 for p in pair_records if p["grayscale_screen"] == "review")
    return {
        "schema": "figure_palette_audit_v1",
        "palette_name": name or "custom",
        "background": canonical_hex(bg_rgb),
        "role": role,
        "contrast_threshold": threshold,
        "grayscale_min_delta": grayscale_min_delta,
        "background_review_count": bg_reviews,
        "grayscale_review_count": gs_reviews,
        "colors": color_records,
        "pairs": pair_records,
        "verdict": "REVIEW_REQUIRED" if (bg_reviews or gs_reviews) else "PASS",
    }


# ---------------------------------------------------------------------------
# 2. Publication figure & script QA (scipilot-figure-skill)
# ---------------------------------------------------------------------------

def _corrupt_png(path: Path, msg: str) -> list[dict[str, Any]]:
    return [{"severity": "ERROR", "check": "figure/corrupt-png", "file": str(path), "message": msg}]


def _inspect_png(path: Path, min_dpi: int) -> list[dict[str, Any]]:
    data = path.read_bytes()
    if len(data) < 8 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return _corrupt_png(path, "Invalid PNG signature")

    findings: list[dict[str, Any]] = []
    pos = 8
    chunk_idx = 0
    seen_ihdr = False
    seen_iend = False
    width = height = 0
    dpi_vals: list[float] = []

    while pos < len(data):
        if pos + 12 > len(data):
            return _corrupt_png(path, "Truncated PNG chunk header")
        length, ctype = struct.unpack(">I4s", data[pos : pos + 8])
        if length > 0x7FFFFFFF or pos + 12 + length > len(data):
            return _corrupt_png(path, f"Corrupt or out-of-bounds PNG chunk length ({length})")
        chunk = data[pos + 8 : pos + 8 + length]
        expected_crc = struct.unpack(">I", data[pos + 8 + length : pos + 12 + length])[0]
        actual_crc = zlib.crc32(ctype + chunk) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            return _corrupt_png(path, f"PNG chunk CRC mismatch in {ctype.decode('latin-1', errors='replace')}")
        if chunk_idx == 0 and ctype != b"IHDR":
            return _corrupt_png(path, "Missing leading IHDR chunk")
        if ctype == b"IHDR":
            if length != 13:
                return _corrupt_png(path, f"Invalid IHDR chunk length ({length})")
            width, height = struct.unpack(">II", chunk[:8])
            if width == 0 or height == 0:
                return _corrupt_png(path, f"Invalid zero IHDR dimensions ({width}x{height})")
            seen_ihdr = True
        elif ctype == b"pHYs":
            if length != 9:
                return _corrupt_png(path, f"Invalid pHYs chunk length ({length})")
            ppux, ppuy, unit = struct.unpack(">IIB", chunk)
            if unit == 1:
                if ppux > 0:
                    dpi_vals.append(ppux * 0.0254)
                if ppuy > 0:
                    dpi_vals.append(ppuy * 0.0254)
        elif ctype == b"IEND":
            if length != 0:
                return _corrupt_png(path, f"Invalid non-empty IEND chunk ({length})")
            seen_iend = True
            pos += 12 + length
            break
        chunk_idx += 1
        pos += 12 + length

    if not seen_ihdr or not seen_iend:
        return _corrupt_png(path, "Truncated PNG missing IHDR or IEND chunk")
    if pos != len(data):
        return _corrupt_png(path, f"Trailing data after PNG IEND chunk ({len(data) - pos} bytes)")

    if width < 600:
        findings.append({
            "severity": "WARN",
            "check": "figure/low-resolution",
            "file": str(path),
            "message": f"PNG width {width}px (<600px) may pixelate in double-column print",
        })
    if dpi_vals:
        dpi_min = min(dpi_vals)
        if round(dpi_min, 1) < float(min_dpi):
            findings.append({
                "severity": "WARN",
                "check": "figure/low-dpi",
                "file": str(path),
                "message": f"PNG DPI {dpi_min:.1f} < {min_dpi} DPI publication minimum",
            })
    return findings


def _strip_pdf_strings_and_comments(buf: bytes) -> bytes:
    if b"(" not in buf and b"%" not in buf:
        return buf
    out = bytearray()
    i = 0
    n = len(buf)
    paren_depth = 0
    while i < n:
        b = buf[i]
        if paren_depth > 0:
            if b == 0x5C and i + 1 < n:
                i += 2
                continue
            if b == 0x28:
                paren_depth += 1
            elif b == 0x29:
                paren_depth -= 1
            i += 1
            continue
        if b == 0x28:
            paren_depth = 1
            out.append(0x20)
            i += 1
            continue
        if b == 0x25:
            while i < n and buf[i] not in (0x0A, 0x0D):
                i += 1
            out.append(0x20)
            continue
        out.append(b)
        i += 1
    return bytes(out)


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


def _inflate_pdf_streams_meta(data: bytes) -> list[tuple[bool, bytes]]:
    inflated: list[tuple[bool, bytes]] = []
    total = 0
    pos = 0
    last_stream_end = 0
    cached_end = -1
    block_start = -1
    block_failed = 0
    mv = memoryview(data)
    stream_re = re.compile(rb"(?:>>|[\x00\t\n\f\r ])stream(?:\r\n|\n|\r)")
    obj_hdr_re = re.compile(rb"(?:^|[\r\n\s])\d+\s+\d+\s+obj\b")
    objstm_re = re.compile(rb"/Type\s*/ObjStm(?![A-Za-z0-9_])")

    def _record_stream(stream_match_start: int, decomp: bytes) -> None:
        nonlocal total
        lookback = data[max(last_stream_end, stream_match_start - 4096) : stream_match_start]
        if b"ObjStm" not in lookback:
            inflated.append((False, decomp))
            total += len(decomp)
            return
        clean_lb = _strip_pdf_strings_and_comments(lookback)
        obj_matches = list(obj_hdr_re.finditer(clean_lb))
        if obj_matches:
            clean_lb = clean_lb[obj_matches[-1].end() :]
        is_objstm = bool(objstm_re.search(clean_lb))
        inflated.append((is_objstm, decomp))
        total += len(decomp)

    while pos < len(data) and total < _MAX_PDF_TOTAL_BYTES:
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
                mv, start, end, _MAX_PDF_STREAM_BYTES, stats
            )
            if decomp:
                _record_stream(m.start(), decomp)
            if hit_eof and total < _MAX_PDF_TOTAL_BYTES:
                next_pos = max(consumed_end, start)
                last_stream_end = max(last_stream_end, next_pos)
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
                    if total >= _MAX_PDF_TOTAL_BYTES or tail_failed >= tail_budget:
                        break
                    nxt_tm = next(tm_iter, None)
                    span_end = nxt_tm.start() if nxt_tm is not None else end
                    if cur_tm.end() > start:
                        tail_stats = [0]
                        try:
                            decomp, _, tail_hit_eof = _try_zlib_decompress_span(
                                mv, cur_tm.end(), span_end, _MAX_PDF_STREAM_BYTES, tail_stats
                            )
                            if decomp:
                                _record_stream(cur_tm.start(), decomp)
                            if decomp or tail_hit_eof:
                                last_stream_end = max(last_stream_end, cur_tm.end())
                        except zlib.error:
                            tail_failed += max(tail_stats[0], 1)
                    cur_tm = nxt_tm
        pos = end + 9
        last_stream_end = pos
    return inflated


def _inflate_pdf_streams(data: bytes) -> list[bytes]:
    return [buf for _, buf in _inflate_pdf_streams_meta(data)]


def _inspect_pdf_figure(path: Path) -> list[dict[str, Any]]:
    data = path.read_bytes()
    if not data.startswith(b"%PDF"):
        return [{"severity": "ERROR", "check": "figure/corrupt-pdf", "file": str(path), "message": "Invalid PDF header"}]
    findings: list[dict[str, Any]] = []
    streams_meta = _inflate_pdf_streams_meta(data)
    all_bufs = [data, *(buf for _, buf in streams_meta)]
    meta_bufs = [data, *(buf for is_objstm, buf in streams_meta if is_objstm)]
    if any(re.search(rb"/Subtype\s*/Type3(?![A-Za-z0-9_])", buf) for buf in all_bufs):
        findings.append({
            "severity": "ERROR",
            "check": "figure/type3-font",
            "file": str(path),
            "message": "PDF contains Type3 bitmap fonts; set plt.rcParams['pdf.fonttype'] = 42 (TrueType)",
        })
    if not any(b"/MediaBox" in buf or b"/CropBox" in buf for buf in meta_bufs):
        findings.append({
            "severity": "WARN",
            "check": "figure/missing-bbox",
            "file": str(path),
            "message": "PDF missing MediaBox/CropBox metadata",
        })
    return findings


def _strip_html_comments(text: str) -> str:
    if "<!--" not in text:
        return text
    parts: list[str] = []
    pos = 0
    n = len(text)
    while pos < n:
        idx = text.find("<!--", pos)
        if idx == -1:
            parts.append(text[pos:])
            break
        parts.append(text[pos:idx])
        end_idx = text.find("-->", idx + 4)
        if end_idx == -1:
            parts.append(text[idx:])
            break
        pos = end_idx + 3
    return "".join(parts)


def _inspect_svg(path: Path) -> list[dict[str, Any]]:
    raw = path.read_bytes()
    if b"\x00" in raw or not raw.strip():
        return [{"severity": "ERROR", "check": "figure/corrupt-svg", "file": str(path), "message": "Empty or binary SVG file"}]
    text = raw.decode("utf-8", errors="replace")
    stripped = _strip_html_comments(text)
    low = stripped.lower()
    if "<svg" not in low:
        return [{"severity": "ERROR", "check": "figure/corrupt-svg", "file": str(path), "message": "SVG file missing <svg root element"}]
    findings: list[dict[str, Any]] = []
    if "data:image/jpeg" in low or "data:image/jpg" in low:
        findings.append({
            "severity": "ERROR",
            "check": "figure/jpeg-prohibited",
            "file": str(path),
            "message": "SVG embeds lossy JPEG raster data; embed lossless PNG or vector primitives",
        })
    if "viewbox" not in low and not ("width=" in low and "height=" in low):
        findings.append({
            "severity": "WARN",
            "check": "figure/missing-bbox",
            "file": str(path),
            "message": "SVG missing viewBox or explicit width/height attributes",
        })
    return findings


def _inspect_eps(path: Path) -> list[dict[str, Any]]:
    raw = path.read_bytes()
    if b"\x00" in raw or not raw.strip():
        return [{"severity": "ERROR", "check": "figure/corrupt-eps", "file": str(path), "message": "Empty or binary EPS file"}]
    if not raw.lstrip().startswith(b"%!"):
        return [{"severity": "ERROR", "check": "figure/corrupt-eps", "file": str(path), "message": "EPS file missing %!PS-Adobe header"}]
    if b"%%BoundingBox" not in raw:
        return [{
            "severity": "WARN",
            "check": "figure/missing-bbox",
            "file": str(path),
            "message": "EPS file missing %%BoundingBox comment",
        }]
    return []


def _utf8_byte_col_to_char_col(line: str, byte_col: int) -> int:
    if byte_col <= 0:
        return 0
    raw = line.encode("utf-8", errors="surrogateescape")
    return len(raw[:byte_col].decode("utf-8", errors="surrogateescape"))


def _collect_docstring_spans(
    tree: ast.AST,
    lines: list[str],
) -> tuple[set[tuple[int, int]], list[tuple[tuple[int, int], tuple[int, int]]]]:
    starts: set[tuple[int, int]] = set()
    ranges: list[tuple[tuple[int, int], tuple[int, int]]] = []
    n_lines = len(lines)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr):
                    is_str_doc = isinstance(first.value, ast.Constant) and isinstance(first.value.value, str)
                    is_const_fstr = isinstance(first.value, ast.JoinedStr) and not any(
                        isinstance(v, ast.FormattedValue) for v in first.value.values
                    )
                    if is_str_doc or is_const_fstr:
                        s_row = first.value.lineno
                        if 1 <= s_row <= n_lines:
                            s_col = _utf8_byte_col_to_char_col(lines[s_row - 1], first.value.col_offset)
                            starts.add((s_row, s_col))
                            e_row = getattr(first.value, "end_lineno", None)
                            e_byte_col = getattr(first.value, "end_col_offset", None)
                            if isinstance(e_row, int) and isinstance(e_byte_col, int) and 1 <= e_row <= n_lines:
                                e_col = _utf8_byte_col_to_char_col(lines[e_row - 1], e_byte_col)
                                ranges.append(((s_row, s_col), (e_row, e_col)))
    return starts, ranges


_RAINBOW_CMAPS = {"jet", "rainbow", "hsv"}


def _strip_python_comments_and_docstrings(text: str) -> tuple[str, ast.AST | None]:
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    lines = io.StringIO(text).readlines()
    if not lines:
        return "", None
    out_chars = [list(ln) for ln in lines]

    tree: ast.AST | None = None
    doc_starts: set[tuple[int, int]] = set()
    doc_ranges: list[tuple[tuple[int, int], tuple[int, int]]] = []
    try:
        tree = ast.parse(text)
        doc_starts, doc_ranges = _collect_docstring_spans(tree, lines)
    except SyntaxError:
        tree = None

    def _blank_span(start: tuple[int, int], end: tuple[int, int]) -> None:
        s_row, s_col = start
        e_row, e_col = end
        for r in range(s_row - 1, min(e_row, len(out_chars))):
            row_chars = out_chars[r]
            c0 = s_col if r == s_row - 1 else 0
            c1 = e_col if r == e_row - 1 else len(row_chars)
            for c in range(max(0, c0), min(c1, len(row_chars))):
                if row_chars[c] not in "\r\n":
                    row_chars[c] = " "

    for s_pos, e_pos in doc_ranges:
        _blank_span(s_pos, e_pos)

    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                _blank_span(tok.start, tok.end)
            elif tok.type == tokenize.STRING and tok.start in doc_starts:
                _blank_span(tok.start, tok.end)
    except (tokenize.TokenError, IndentationError):
        pass
    return "".join("".join(row) for row in out_chars), tree


def _infer_savefig_ext(expr: ast.AST) -> str | None:
    sv = _const_str(expr)
    if sv is not None:
        return sv.strip().lower()
    if isinstance(expr, ast.Call):
        cname = _call_name(expr)
        if cname == "with_suffix" and expr.args:
            suf = _const_str(expr.args[0])
            return suf.strip().lower() if suf is not None else None
        if cname in {"join", "Path", "PurePath", "PurePosixPath", "str"} and expr.args:
            return _infer_savefig_ext(expr.args[-1])
        return None
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, (ast.Div, ast.Add)):
        return _infer_savefig_ext(expr.right)
    if isinstance(expr, ast.JoinedStr) and expr.values:
        return _infer_savefig_ext(expr.values[-1])
    return None


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _attr_tail(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _const_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _const_int(node: ast.AST | None) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return node.value
    return None


def _const_num(node: ast.AST | None) -> float | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        inner = _const_num(node.operand)
        if inner is not None:
            return -inner if isinstance(node.op, ast.USub) else inner
    return None


def _iter_bounded_call_args(code_text: str, call_re: re.Pattern[str], max_span: int = 512) -> list[str]:
    matches = list(call_re.finditer(code_text))
    if not matches:
        return []
    windows: list[str] = []
    n = len(code_text)
    for idx, m in enumerate(matches):
        bound = matches[idx + 1].start() if idx + 1 < len(matches) else n
        limit = min(m.end() + max_span, bound)
        depth = 1
        i = m.end()
        while i < limit and depth > 0:
            ch = code_text[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        windows.append(code_text[m.end() : i])
    return windows


def _inspect_plot_script(path: Path) -> list[dict[str, Any]]:
    raw_text = path.read_text(encoding="utf-8-sig", errors="replace")
    code_text, tree = _strip_python_comments_and_docstrings(raw_text)
    findings: list[dict[str, Any]] = []

    rainbow_hit = False
    jpeg_export = False
    pdf_export = False
    has_pdf_42 = False
    explicit_type3 = False
    has_vbar = False
    has_hbar = False
    truncated_y = False
    truncated_x = False

    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                if node.attr.lower() in _RAINBOW_CMAPS and _attr_tail(node.value) == "cm":
                    rainbow_hit = True
            elif isinstance(node, ast.Subscript):
                if _attr_tail(node.value) in {"colormaps", "cm"}:
                    sv = _const_str(node.slice)
                    if sv is not None and sv.lower() in _RAINBOW_CMAPS:
                        rainbow_hit = True
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for tgt in targets:
                    if isinstance(tgt, ast.Subscript) and _const_str(tgt.slice) == "pdf.fonttype":
                        iv = _const_int(node.value)
                        if iv == 42:
                            has_pdf_42 = True
                        elif iv == 3:
                            explicit_type3 = True
            elif isinstance(node, ast.AugAssign) and isinstance(node.op, ast.BitOr):
                if _attr_tail(node.target) in {"rcParams", "rcParamsDefault"} and isinstance(node.value, ast.Dict):
                    for dk, dv in zip(node.value.keys, node.value.values):
                        if _const_str(dk) == "pdf.fonttype":
                            iv = _const_int(dv)
                            if iv == 42:
                                has_pdf_42 = True
                            elif iv == 3:
                                explicit_type3 = True
            elif isinstance(node, ast.Call):
                cname = _call_name(node)
                if cname in {"get_cmap", "set_cmap"}:
                    for arg in node.args[:1]:
                        sv = _const_str(arg)
                        if sv is not None and sv.lower() in _RAINBOW_CMAPS:
                            rainbow_hit = True
                    for kw in node.keywords:
                        if kw.arg in {"name", "cmap"}:
                            sv = _const_str(kw.value)
                            if sv is not None and sv.lower() in _RAINBOW_CMAPS:
                                rainbow_hit = True
                for kw in node.keywords:
                    if kw.arg == "cmap":
                        sv = _const_str(kw.value)
                        if sv is not None and sv.lower() in _RAINBOW_CMAPS:
                            rainbow_hit = True
                if cname == "savefig":
                    fmt_val: str | None = None
                    for kw in node.keywords:
                        if kw.arg == "format":
                            sv = _const_str(kw.value)
                            if sv is not None:
                                fmt_val = sv.strip().lower().lstrip(".")
                            break
                    if fmt_val is not None:
                        if fmt_val in {"jpg", "jpeg"}:
                            jpeg_export = True
                        elif fmt_val == "pdf":
                            pdf_export = True
                    else:
                        target_expr: ast.AST | None = node.args[0] if node.args else None
                        if target_expr is None:
                            for kw in node.keywords:
                                if kw.arg in {"fname", "file"}:
                                    target_expr = kw.value
                                    break
                        if target_expr is not None:
                            ext_hint = _infer_savefig_ext(target_expr)
                            if ext_hint:
                                if ext_hint.endswith((".jpg", ".jpeg")):
                                    jpeg_export = True
                                elif ext_hint.endswith(".pdf"):
                                    pdf_export = True
                elif cname == "rc":
                    if node.args and _const_str(node.args[0]) == "pdf":
                        for kw in node.keywords:
                            if kw.arg == "fonttype":
                                iv = _const_int(kw.value)
                                if iv == 42:
                                    has_pdf_42 = True
                                elif iv == 3:
                                    explicit_type3 = True
                            elif kw.arg is None and isinstance(kw.value, ast.Dict):
                                for dk, dv in zip(kw.value.keys, kw.value.values):
                                    if _const_str(dk) == "fonttype":
                                        iv = _const_int(dv)
                                        if iv == 42:
                                            has_pdf_42 = True
                                        elif iv == 3:
                                            explicit_type3 = True
                elif cname == "update" and isinstance(node.func, ast.Attribute):
                    if _attr_tail(node.func.value) in {"rcParams", "rcParamsDefault"} and node.args:
                        d0 = node.args[0]
                        if isinstance(d0, ast.Dict):
                            for dk, dv in zip(d0.keys, d0.values):
                                if _const_str(dk) == "pdf.fonttype":
                                    iv = _const_int(dv)
                                    if iv == 42:
                                        has_pdf_42 = True
                                    elif iv == 3:
                                        explicit_type3 = True
                        elif isinstance(d0, (ast.List, ast.Tuple)):
                            for elt in d0.elts:
                                if isinstance(elt, (ast.Tuple, ast.List)) and len(elt.elts) == 2:
                                    if _const_str(elt.elts[0]) == "pdf.fonttype":
                                        iv = _const_int(elt.elts[1])
                                        if iv == 42:
                                            has_pdf_42 = True
                                        elif iv == 3:
                                            explicit_type3 = True
                elif cname == "bar":
                    has_vbar = True
                elif cname == "barh":
                    has_hbar = True
                elif cname in {"set_ylim", "ylim"}:
                    lb: float | None = None
                    for kw in node.keywords:
                        if kw.arg in {"bottom", "ymin"}:
                            lb = _const_num(kw.value)
                            break
                    if lb is None and node.args:
                        arg0 = node.args[0]
                        if isinstance(arg0, (ast.Tuple, ast.List)) and arg0.elts:
                            lb = _const_num(arg0.elts[0])
                        else:
                            lb = _const_num(arg0)
                    if lb is not None and lb > 0:
                        truncated_y = True
                elif cname in {"set_xlim", "xlim"}:
                    lb = None
                    for kw in node.keywords:
                        if kw.arg in {"left", "xmin"}:
                            lb = _const_num(kw.value)
                            break
                    if lb is None and node.args:
                        arg0 = node.args[0]
                        if isinstance(arg0, (ast.Tuple, ast.List)) and arg0.elts:
                            lb = _const_num(arg0.elts[0])
                        else:
                            lb = _const_num(arg0)
                    if lb is not None and lb > 0:
                        truncated_x = True
                elif cname == "set":
                    for kw in node.keywords:
                        if kw.arg == "ylim" and isinstance(kw.value, (ast.Tuple, ast.List)) and kw.value.elts:
                            lb = _const_num(kw.value.elts[0])
                            if lb is not None and lb > 0:
                                truncated_y = True
                        elif kw.arg == "xlim" and isinstance(kw.value, (ast.Tuple, ast.List)) and kw.value.elts:
                            lb = _const_num(kw.value.elts[0])
                            if lb is not None and lb > 0:
                                truncated_x = True
    else:
        rainbow_hit = bool(
            re.search(
                r"""cmap\s*=\s*['"](?:jet|rainbow|hsv)['"]|cm\.(?:jet|rainbow|hsv)\b|(?:get_cmap|set_cmap)\s*\(\s*['"](?:jet|rainbow|hsv)['"]|colormaps\s*\[\s*['"](?:jet|rainbow|hsv)['"]\s*\]""",
                code_text,
                re.I,
            )
        )
        jpeg_export = any(_JPEG_ARG_RE.search(win) for win in _iter_bounded_call_args(code_text, _SAVEFIG_CALL_RE))
        pdf_export = ".pdf" in code_text.lower() and "savefig" in code_text
        rc_pdf_windows = _iter_bounded_call_args(code_text, _RC_PDF_CALL_RE)
        has_pdf_42 = bool(
            re.search(
                r"""['"]pdf\.fonttype['"](?:\s*\])?\s*=\s*42\b|['"]pdf\.fonttype['"]\s*:\s*42\b""",
                code_text,
            )
        ) or any(_FONTTYPE_42_RE.search(win) for win in rc_pdf_windows)
        explicit_type3 = bool(
            re.search(
                r"""pdf\.fonttype['"]?(?:\s*\])?\s*=\s*3\b|['"]pdf\.fonttype['"]\s*:\s*3\b""",
                code_text,
            )
        ) or any(_FONTTYPE_3_RE.search(win) for win in rc_pdf_windows)
        has_vbar = bool(re.search(r"\bbar\s*\(", code_text))
        has_hbar = bool(re.search(r"\bbarh\s*\(", code_text))
        truncated_y = bool(
            re.search(
                r"\b(?:set_ylim|ylim)\s*\(\s*(?:(?:bottom|ymin)\s*=\s*|[\[(]\s*)?(?:0?\.[0-9]*[1-9]|[1-9])",
                code_text,
            )
        )
        truncated_x = bool(
            re.search(
                r"\b(?:set_xlim|xlim)\s*\(\s*(?:(?:left|xmin)\s*=\s*|[\[(]\s*)?(?:0?\.[0-9]*[1-9]|[1-9])",
                code_text,
            )
        )

    truncated_bar = (has_vbar and truncated_y) or (has_hbar and truncated_x)

    if rainbow_hit:
        findings.append({
            "severity": "ERROR",
            "check": "figure/rainbow-colormap",
            "file": str(path),
            "message": "Non-perceptual rainbow/jet colormap used; switch to viridis/cividis/Okabe-Ito",
        })
    if jpeg_export:
        findings.append({
            "severity": "ERROR",
            "check": "figure/jpeg-export",
            "file": str(path),
            "message": "Script exports figure as lossy JPEG; export vector PDF/SVG or >=300 DPI PNG",
        })
    if pdf_export and (not has_pdf_42 or explicit_type3):
        findings.append({
            "severity": "WARN",
            "check": "figure/missing-truetype-rcparam",
            "file": str(path),
            "message": "PDF export without pdf.fonttype=42 risks Type3 fonts on IEEE/NeurIPS checks",
        })
    if truncated_bar:
        findings.append({
            "severity": "WARN",
            "check": "figure/truncated-bar-axis",
            "file": str(path),
            "message": "Bar chart may truncate non-zero Y/X axis baseline (distorts visual magnitude)",
        })
    return findings


def _collect_figure_files(target: Path) -> list[Path]:
    if not target.is_dir():
        return [target]
    target_res = target.resolve()
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(target, followlinks=False):
        dp = Path(dirpath)
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in _SKIP_DIRS and not (dp / d).is_symlink()
        )
        for fn in sorted(filenames):
            p = dp / fn
            if p.is_symlink():
                if not p.exists() or not p.resolve().is_relative_to(target_res):
                    continue
            files.append(p)
    return files


def audit_figures(target: Path, *, min_dpi: int = 300) -> dict[str, Any]:
    if not target.exists():
        raise FileNotFoundError(f"Figure path not found: {target}")
    if isinstance(min_dpi, bool) or not isinstance(min_dpi, int) or min_dpi < 72:
        raise ValueError("--min-dpi must be an integer >= 72")
    files = _collect_figure_files(target)
    checked: list[str] = []
    findings: list[dict[str, Any]] = []
    for f in files:
        suf = f.suffix.lower()
        if suf not in _FIG_EXTS and suf != ".py":
            continue
        checked.append(str(f))
        if suf in {".jpg", ".jpeg"}:
            findings.append({
                "severity": "ERROR",
                "check": "figure/jpeg-prohibited",
                "file": str(f),
                "message": "JPEG is prohibited for charts/diagrams (compression artifacts); use vector PDF/SVG or PNG >=300 DPI",
            })
        elif suf == ".png":
            findings.extend(_inspect_png(f, min_dpi))
        elif suf == ".pdf":
            findings.extend(_inspect_pdf_figure(f))
        elif suf == ".svg":
            findings.extend(_inspect_svg(f))
        elif suf == ".eps":
            findings.extend(_inspect_eps(f))
        elif suf == ".py":
            findings.extend(_inspect_plot_script(f))
    if not checked:
        raise ValueError(f"No supported figure or plotting script files found at {target}")
    counts = {s: sum(1 for x in findings if x["severity"] == s) for s in ("ERROR", "WARN")}
    return {
        "schema": "figure_qa_v1",
        "target": str(target),
        "checked_count": len(checked),
        "summary": counts,
        "findings": findings,
        "verdict": "FAIL" if counts["ERROR"] else ("PASS_WITH_WARNINGS" if counts["WARN"] else "PASS"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_pal = sub.add_parser("palette", help="Audit palette WCAG contrast & grayscale delta-L*")
    src = p_pal.add_mutually_exclusive_group(required=False)
    src.add_argument("--palette", help="Bundled palette name (use --list-palettes)")
    src.add_argument("--color", action="append", default=[], help="Six-digit hex color (repeatable)")
    p_pal.add_argument("--list-palettes", action="store_true", help="List bundled colorblind-safe palettes")
    p_pal.add_argument("--background", default=DEFAULT_BACKGROUND, help="Background hex color (default #FFFFFF)")
    p_pal.add_argument("--role", choices=sorted(ROLE_THRESHOLDS), default="graphical")
    p_pal.add_argument("--contrast-threshold", type=float, default=None)
    p_pal.add_argument("--grayscale-min-delta", type=float, default=DEFAULT_GRAYSCALE_DELTA)
    p_pal.add_argument("--fail-on", choices=("none", "background", "grayscale", "any"), default="none")
    p_pal.add_argument("--out", help="Write full JSON output to PATH")
    p_pal.add_argument("--json", nargs="?", const="-", help="Emit JSON output")
    p_pal.add_argument("--compact", action="store_true", help="Bounded <4KB stdout summary")

    p_fig = sub.add_parser("figure", help="Check figure assets (JPEG/DPI/Type3) and plotting scripts")
    p_fig.add_argument("path", help="Figure file or directory")
    p_fig.add_argument("--min-dpi", type=int, default=300, help="Minimum raster DPI (default 300)")
    p_fig.add_argument("--strict", action="store_true", help="Treat warnings as failures (exit 1)")
    p_fig.add_argument("--out", help="Write full JSON output to PATH")
    p_fig.add_argument("--json", nargs="?", const="-", help="Emit JSON output")
    p_fig.add_argument("--compact", action="store_true", help="Bounded <4KB stdout summary")

    args = parser.parse_args(argv)
    try:
        if args.out is not None:
            _nonempty(args.out, "--out")
        if args.json is not None and args.json != "-":
            _nonempty(args.json, "--json")

        if args.cmd == "palette":
            if args.list_palettes:
                res = {"schema": "figure_palettes_v1", "palettes": BUNDLED_PALETTES}
                _emit(res, {"compact": True, **res}, args)
                return 0
            if args.palette is not None:
                pname = _nonempty(args.palette, "--palette")
                if pname not in BUNDLED_PALETTES:
                    raise ValueError(f"Unknown palette {pname!r}; available: {', '.join(sorted(BUNDLED_PALETTES))}")
                colors = BUNDLED_PALETTES[pname]
                name = pname
            else:
                colors = args.color
                name = "custom"
            if not colors:
                raise ValueError("Provide --palette or at least one --color")
            res = audit_palette(
                colors,
                background=args.background,
                role=args.role,
                contrast_threshold=args.contrast_threshold,
                grayscale_min_delta=args.grayscale_min_delta,
                name=name,
            )
            compact = {
                "compact": True,
                "schema": res["schema"],
                "palette_name": res["palette_name"],
                "background_review_count": res["background_review_count"],
                "grayscale_review_count": res["grayscale_review_count"],
                "verdict": res["verdict"],
                "out": args.out,
            }
            _emit(res, compact, args)
            bg_fail = res["background_review_count"] > 0
            gs_fail = res["grayscale_review_count"] > 0
            should_fail = (
                (args.fail_on in {"background", "any"} and bg_fail)
                or (args.fail_on in {"grayscale", "any"} and gs_fail)
            )
            return 1 if should_fail else 0

        fp = Path(_nonempty(args.path, "path"))
        res = audit_figures(fp, min_dpi=args.min_dpi)
        compact = {
            "compact": True,
            "schema": res["schema"],
            "checked_count": res["checked_count"],
            "summary": res["summary"],
            "verdict": res["verdict"],
            "findings": res["findings"][:8],
            "out": args.out,
        }
        _emit(res, compact, args)
        return 1 if res["summary"]["ERROR"] or (args.strict and res["summary"]["WARN"]) else 0
    except (OSError, ValueError, FileNotFoundError) as exc:
        return _err(str(exc))


if __name__ == "__main__":
    sys.exit(main())
