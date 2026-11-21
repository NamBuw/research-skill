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
import itertools
import json
import math
import re
import struct
import sys
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


def _err(msg: str) -> int:
    print(json.dumps({"error": msg}), file=sys.stderr)
    return 2


def _nonempty(val: Any, flag: str) -> str:
    if not isinstance(val, str) or not val.strip():
        raise ValueError(f"Empty or invalid value for {flag}")
    return val.strip()


def _emit(payload: dict[str, Any], compact: dict[str, Any], args: argparse.Namespace) -> None:
    if getattr(args, "out", None):
        op = Path(_nonempty(args.out, "--out"))
        op.parent.mkdir(parents=True, exist_ok=True)
        op.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if getattr(args, "compact", False):
        raw = json.dumps(compact, separators=(",", ":"))
        if len(raw.encode("utf-8")) > MAX_COMPACT_BYTES:
            trimmed = dict(compact)
            for k in list(trimmed):
                if isinstance(trimmed[k], list) and len(trimmed[k]) > 5:
                    trimmed[k] = trimmed[k][:5]
            raw = json.dumps(trimmed, separators=(",", ":"))
        print(raw)
    elif getattr(args, "json", None) == "-":
        print(json.dumps(payload, indent=2))
    elif getattr(args, "json", None):
        jp = Path(_nonempty(args.json, "--json"))
        jp.parent.mkdir(parents=True, exist_ok=True)
        jp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(compact, separators=(",", ":")))
    else:
        print(json.dumps(payload, indent=2))


# ---------------------------------------------------------------------------
# 1. WCAG 2.2 contrast & CIE L* grayscale palette audit
# ---------------------------------------------------------------------------

def parse_hex_color(value: str) -> tuple[int, int, int]:
    norm = value.strip().lstrip("#")
    if len(norm) != 6:
        raise ValueError(f"Expected 6-digit hex color, got {value!r}")
    try:
        return (int(norm[0:2], 16), int(norm[2:4], 16), int(norm[4:6], 16))
    except ValueError as exc:
        raise ValueError(f"Invalid hex color: {value!r}") from exc


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
    threshold = float(contrast_threshold) if contrast_threshold is not None else ROLE_THRESHOLDS[role]
    if not math.isfinite(threshold) or threshold <= 1.0:
        raise ValueError("Contrast threshold must be finite and > 1")
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

def _inspect_png(path: Path, min_dpi: int) -> list[dict[str, Any]]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return [{"severity": "ERROR", "check": "figure/corrupt-png", "file": str(path), "message": "Invalid PNG signature"}]
    findings: list[dict[str, Any]] = []
    pos = 8
    width = height = 0
    dpi_x: float | None = None
    while pos + 8 <= len(data):
        length, ctype = struct.unpack(">I4s", data[pos : pos + 8])
        chunk = data[pos + 8 : pos + 8 + length]
        if ctype == b"IHDR" and len(chunk) >= 8:
            width, height = struct.unpack(">II", chunk[:8])
        elif ctype == b"pHYs" and len(chunk) >= 9:
            ppux, _ppuy, unit = struct.unpack(">IIB", chunk[:9])
            if unit == 1 and ppux > 0:
                dpi_x = ppux * 0.0254
        elif ctype == b"IEND":
            break
        pos += 12 + length
    if width and width < 600:
        findings.append({
            "severity": "WARN",
            "check": "figure/low-resolution",
            "file": str(path),
            "message": f"PNG width {width}px (<600px) may pixelate in double-column print",
        })
    if dpi_x is not None and round(dpi_x, 1) < float(min_dpi):
        findings.append({
            "severity": "WARN",
            "check": "figure/low-dpi",
            "file": str(path),
            "message": f"PNG DPI {dpi_x:.1f} < {min_dpi} DPI publication minimum",
        })
    return findings


def _inspect_pdf_figure(path: Path) -> list[dict[str, Any]]:
    data = path.read_bytes()
    if not data.startswith(b"%PDF"):
        return [{"severity": "ERROR", "check": "figure/corrupt-pdf", "file": str(path), "message": "Invalid PDF header"}]
    findings: list[dict[str, Any]] = []
    if re.search(rb"/Subtype\s*/Type3\b", data):
        findings.append({
            "severity": "ERROR",
            "check": "figure/type3-font",
            "file": str(path),
            "message": "PDF contains Type3 bitmap fonts; set plt.rcParams['pdf.fonttype'] = 42 (TrueType)",
        })
    if b"/MediaBox" not in data and b"/CropBox" not in data:
        findings.append({
            "severity": "WARN",
            "check": "figure/missing-bbox",
            "file": str(path),
            "message": "PDF missing MediaBox/CropBox metadata",
        })
    return findings


def _inspect_plot_script(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    findings: list[dict[str, Any]] = []
    if re.search(r"""cmap\s*=\s*['"](?:jet|rainbow|hsv)['"]|cm\.(?:jet|rainbow|hsv)\b""", text):
        findings.append({
            "severity": "ERROR",
            "check": "figure/rainbow-colormap",
            "file": str(path),
            "message": "Non-perceptual rainbow/jet colormap used; switch to viridis/cividis/Okabe-Ito",
        })
    if re.search(r"""savefig\([^)]*\.(?:jpg|jpeg)['"]""", text, re.I):
        findings.append({
            "severity": "ERROR",
            "check": "figure/jpeg-export",
            "file": str(path),
            "message": "Script exports figure as lossy JPEG; export vector PDF/SVG or >=300 DPI PNG",
        })
    if ".pdf" in text.lower() and "savefig" in text and "fonttype" not in text:
        findings.append({
            "severity": "WARN",
            "check": "figure/missing-truetype-rcparam",
            "file": str(path),
            "message": "PDF export without pdf.fonttype=42 risks Type3 fonts on IEEE/NeurIPS checks",
        })
    if re.search(r"\b(?:bar|barh)\s*\(", text) and re.search(r"\bset_ylim\s*\(\s*[1-9]", text):
        findings.append({
            "severity": "WARN",
            "check": "figure/truncated-bar-axis",
            "file": str(path),
            "message": "Bar chart may truncate non-zero Y axis baseline (distorts visual magnitude)",
        })
    return findings


def audit_figures(target: Path, *, min_dpi: int = 300) -> dict[str, Any]:
    if not target.exists():
        raise FileNotFoundError(f"Figure path not found: {target}")
    if min_dpi < 72:
        raise ValueError("--min-dpi must be >= 72")
    files = sorted(p for p in target.rglob("*") if p.is_file()) if target.is_dir() else [target]
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
        if args.cmd == "palette":
            if args.list_palettes:
                res = {"schema": "figure_palettes_v1", "palettes": BUNDLED_PALETTES}
                _emit(res, {"compact": True, **res}, args)
                return 0
            if args.palette:
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
