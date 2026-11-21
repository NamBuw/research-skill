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

POINT_ID_RE = re.compile(r"\b((?:R\d+|AC|MR)\.\d+)\b")
ANCHOR_RE = re.compile(
    r"(?ix)"
    r"(\bsec(?:tion)?s?[.\s~]*\d)"
    r"|(\btable[s]?[.\s~]*\d)"
    r"|(\bfig(?:ure)?s?[.\s~]*\d)"
    r"|(\beq(?:uation)?s?[.\s~]*\(?\d)"
    r"|(\bappendix\s+[a-z0-9])"
    r"|(\blines?\s+\d+)"
    r"|(\bL\d{2,}\b)"
    r"|(\babstract\b)"
    r"|(\[\d+(?:,\s*\d+)*\])"
)
NEW_EXP_CLAIM_RE = re.compile(
    r"\b(?:we\s+(?:ran|conducted|executed|performed|added)\s+(?:new|additional)\s+(?:experiments?|ablations?|runs?)|"
    r"new\s+experiments?\s+(?:confirm|show|demonstrate))\b",
    re.I,
)
PLANNED_CAVEAT_RE = re.compile(
    r"\b(?:will\s+(?:run|add|include)|planned\s+for\s+camera-?ready|in\s+the\s+revised\s+manuscript)\b",
    re.I,
)


def _err(msg: str) -> int:
    print(json.dumps({"error": msg}), file=sys.stderr)
    return 2


def _nonempty(val: Any, flag: str) -> str:
    if not isinstance(val, str) or not val.strip():
        raise ValueError(f"Empty or invalid path for {flag}")
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


def count_pdf_pages(data: bytes) -> tuple[int, str]:
    page_re = re.compile(rb"/Type\s*/Page(?![s/\w])")
    n = len(page_re.findall(data))
    if n:
        return n, "uncompressed /Type /Page objects"

    inflated: list[bytes] = []
    for m in re.finditer(rb"stream\r?\n", data):
        start = m.end()
        end = data.find(b"endstream", start)
        if end == -1:
            continue
        try:
            inflated.append(zlib.decompress(data[start:end]))
        except zlib.error:
            continue
    blob = b"\n".join(inflated)
    n = len(page_re.findall(blob))
    if n:
        return n, "FlateDecode object streams"

    counts = [int(c) for c in re.findall(rb"/Type\s*/Pages[^>]*?/Count\s+(\d+)", data + b"\n" + blob, re.S)]
    counts += [int(c) for c in re.findall(rb"/Count\s+(\d+)[^>]*?/Type\s*/Pages", data + b"\n" + blob, re.S)]
    counts = [c for c in counts if c > 0]
    if counts:
        return max(counts), "/Count in /Type /Pages node"
    raise ValueError("Could not determine a positive PDF page count")


def check_budget_text(file_path: Path, *, sections_mode: bool = False, limit: int = DEFAULT_CHAR_LIMIT) -> dict[str, Any]:
    if not file_path.is_file():
        raise FileNotFoundError(f"Rebuttal file not found: {file_path}")
    if limit < 1:
        raise ValueError("--limit must be >= 1")
    text = file_path.read_text(encoding="utf-8", errors="replace")
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
        pages, method = count_pdf_pages(data)
    except ValueError:
        try:
            import fitz  # type: ignore

            with fitz.open(str(file_path)) as doc:
                pages = len(doc)
            method = "pymupdf"
        except Exception as exc:
            raise ValueError(f"Could not determine page count for {file_path}: {exc}") from exc
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


def check_coverage(points_path: Path, response_paths: list[Path]) -> dict[str, Any]:
    if not points_path.is_file():
        raise FileNotFoundError(f"Points file not found: {points_path}")
    points_text = points_path.read_text(encoding="utf-8", errors="replace")
    point_ids: list[str] = []
    for pid in POINT_ID_RE.findall(points_text):
        if pid not in point_ids:
            point_ids.append(pid)
    if not point_ids:
        raise ValueError(f"No point IDs (R<k>.<n> / AC.<n> / MR.<n>) found in {points_path}")

    resp_texts: dict[str, str] = {}
    for rp in response_paths:
        if not rp.is_file():
            raise FileNotFoundError(f"Response file not found: {rp}")
        txt = rp.read_text(encoding="utf-8", errors="replace")
        if not txt.strip():
            raise ValueError(f"Response file is empty: {rp}")
        resp_texts[str(rp)] = txt

    all_resp = "\n".join(resp_texts.values())
    resp_ids = set(POINT_ID_RE.findall(all_resp))
    covered = [p for p in point_ids if p in resp_ids]
    missing = [p for p in point_ids if p not in resp_ids]
    orphans = sorted(resp_ids - set(point_ids))

    unanchored: list[str] = []
    unverified_exp_claims: list[str] = []
    n_sections = 0
    for path_s, txt in resp_texts.items():
        sections = split_sections(txt)
        for title, body in sections:
            if (
                title == "(preamble)"
                and len(sections) > 1
                and not POINT_ID_RE.search(body)
                and not NEW_EXP_CLAIM_RE.search(body)
            ):
                continue
            n_sections += 1
            has_anchor = bool(ANCHOR_RE.search(body))
            if not has_anchor:
                unanchored.append(f"{path_s} :: {title}")
            if NEW_EXP_CLAIM_RE.search(body) and not has_anchor and not PLANNED_CAVEAT_RE.search(body):
                unverified_exp_claims.append(f"{path_s} :: {title}")

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
