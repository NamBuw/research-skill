#!/usr/bin/env python3
"""Submission preflight tool: double-blind/camera-ready anonymization, arXiv LaTeX cleanup, and BibTeX verification.

SPDX-License-Identifier: Apache-2.0 AND MIT

Attribution & License Notice:
- Double-blind & camera-ready anonymization checks adapted from `ShaishavMaisuria/research-paper-lifecycle-skills`
  (`skills/anonymize-paper/scripts/scan_anonymization.py` & `preflight-check/scripts/run_preflight.py`,
  Apache-2.0 License, Copyright 2026 Shaishav Maisuria).
- arXiv LaTeX comment stripping & unused-file/image checks adapted from `google-research/arxiv-latex-cleaner`
  (Apache-2.0 License).
- BibTeX acronym case protection (`protect_title_caps`) adapted from `yuchenlin/rebiber` (MIT License);
  deterministic BibTeX field/crossref/OpenAlex hygiene inspired by `amos689/paper-preflight` &
  `Altman-conquer/bibtex-verifier` (MIT License).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

MAX_COMPACT_BYTES = 3800

_ANON_OK_RE = re.compile(
    r"anon|blind|omitted|hidden|redacted|withheld|paper\s*(?:id|#|number)|submission\s*(?:id|#|number)|under\s+review",
    re.I,
)
_IDENTITY_HOSTS = (
    "github.com", "gitlab.com", "bitbucket.org", "huggingface.co",
    "sites.google.com", "drive.google.com", "dropbox.com", "onedrive",
    "kaggle.com", "linkedin.com", "twitter.com", "x.com", "zenodo.org", "osf.io",
)
_ANON_OK_HOSTS = ("anonymous.4open.science", "anonymous.science")
_URL_RE = re.compile(r"(?:https?://|www\.)[^\s{}\\%]+", re.I)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_OK_EMAIL_RE = re.compile(r"example\.(?:com|org|edu)|anon", re.I)
_HOME_PATH_RE = re.compile(r"(?:/(?:Users|home)/([A-Za-z0-9_.-]+)|[A-Za-z]:\\+Users\\+([A-Za-z0-9_.-]+))")
_GENERIC_USERS = {"user", "username", "you", "anon", "anonymous", "runner", "ubuntu", "root", "ci"}
_SELF_CITE_RES = [
    re.compile(r"\bour (?:previous|prior|earlier|recent|own) (?:work|workshop paper|paper|papers|study|studies|approach|system|method|results?)\b", re.I),
    re.compile(r"\bwe (?:previously|recently|earlier) (?:showed|proposed|presented|introduced|demonstrated|developed|published|reported)\b", re.I),
    re.compile(r"\b(?:extends?|builds? (?:up)?on|following[- ]up (?:to|on)) our\b", re.I),
    re.compile(r"\bour\b[^.\n]{0,40}?\\cite", re.I),
]
_FUNDING_RES = [
    re.compile(r"\bgrant\s+(?:no\.?|number|agreement)\b", re.I),
    re.compile(r"\b(?:funded|financially supported)\s+by\b", re.I),
    re.compile(r"\b(?:NSF|NIH|ERC|DFG|DARPA|ONR|AFOSR|EPSRC|NSERC|JSPS)\b[^.\n]{0,30}\d"),
]
_INSTITUTION_RE = re.compile(r"\b(?:our|my) (?:university|institution|institute|laboratory|research group|department|team|campus)\b", re.I)
_PLACEHOLDER_TEXT_RE = re.compile(
    r"anonymi[sz]ed for (?:the )?(?:review|submission)|omitted (?:for|due to) (?:double-?blind |anonymous )?(?:review|submission|anonymity)|under double-?blind review",
    re.I,
)
_ML_STY_RE = re.compile(r"\\usepackage\s*(?:\[([^\]]*)\])?\s*\{(neurips_\d{4}|icml\d{4}|iclr\d{4}_conference)\}")
_DOCCLASS_RE = re.compile(r"\\documentclass\s*(?:\[([^\]]*)\])?\s*\{([^}]+)\}")
_INPUT_RE = re.compile(r"\\(?:input|include)\s*\{([^}]+)\}")
_GRAPHIC_RE = re.compile(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}")
_CITE_RE = re.compile(r"\\(?:cite[a-zA-Z*]*|autocite|textcite|parencite)\s*(?:\[[^\]]*\]\s*)*\{([^}]+)\}")

_AI_ACRONYMS = {
    "AI", "ML", "NLP", "CV", "LLM", "LLMs", "GPT", "GPT-4", "BERT", "RoBERTa",
    "ResNet", "ViT", "CLIP", "SAM", "GAN", "VAE", "RL", "RLHF", "DPO", "PPO",
    "RAG", "LoRA", "MMLU", "GSM8K", "ImageNet", "NeurIPS", "ICML", "ICLR",
    "CVPR", "ICCV", "ECCV", "ACL", "EMNLP", "NAACL", "AAAI", "TMLR", "TPAMI",
    "3D", "2D", "CNN", "RNN", "LSTM", "GRU", "GNN", "GCN", "MLP", "SGD", "AdamW",
}


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


def _split_tex_comment(line: str) -> tuple[str, str]:
    out: list[str] = []
    i = 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            out.append(line[i : i + 2])
            i += 2
            continue
        if c == "%":
            return "".join(out), line[i + 1 :]
        out.append(c)
        i += 1
    return "".join(out), ""


def _load_tex_flattened(tex_path: Path, seen: set[str] | None = None, depth: int = 0) -> tuple[list[tuple[str, int, str, str]], list[str]]:
    if not tex_path.is_file():
        raise FileNotFoundError(f"TeX file not found: {tex_path}")
    seen = seen if seen is not None else set()
    key = str(tex_path.resolve())
    if key in seen or depth > 8:
        return [], []
    seen.add(key)
    notes: list[str] = []
    rows: list[tuple[str, int, str, str]] = []
    raw = tex_path.read_text(encoding="utf-8", errors="replace")
    for lineno, line in enumerate(raw.splitlines(), start=1):
        code, comment = _split_tex_comment(line)
        rows.append((str(tex_path), lineno, code, comment))
        for m in _INPUT_RE.finditer(code):
            child_name = m.group(1).strip()
            cpath = tex_path.parent / child_name
            if not cpath.suffix:
                cpath = cpath.with_suffix(".tex")
            if cpath.is_file():
                sub_rows, sub_notes = _load_tex_flattened(cpath, seen, depth + 1)
                rows.extend(sub_rows)
                notes.extend(sub_notes)
            else:
                notes.append(f"{tex_path}:{lineno}: missing \\input{{{child_name}}}")
    return rows, notes


def _find_tex_cmd(text: str, cmd: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    boundary = r"\b" if cmd[-1].isalnum() else ""
    for m in re.finditer(r"\\" + re.escape(cmd) + boundary + r"\s*(?:\[[^\]]*\]\s*)?\{", text):
        start = m.end() - 1
        depth = 0
        i = start
        while i < len(text):
            if text[i] == "\\":
                i += 2
                continue
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    out.append((m.start(), text[start + 1 : i]))
                    break
            i += 1
    return out


# ---------------------------------------------------------------------------
# 1. Double-blind / camera-ready anonymization scanner
# ---------------------------------------------------------------------------

def scan_anonymization(
    tex_path: Path,
    *,
    mode: str = "submission",
    names: str = "",
    pdf_path: Path | None = None,
    supplementary: Path | None = None,
) -> dict[str, Any]:
    rows, notes = _load_tex_flattened(tex_path)
    full_code = "\n".join(r[2] for r in rows)
    starts: list[int] = []
    pos = 0
    for r in rows:
        starts.append(pos)
        pos += len(r[2]) + 1

    def _loc(char_pos: int) -> tuple[str, int]:
        lo, hi = 0, max(0, len(starts) - 1)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if starts[mid] <= char_pos:
                lo = mid
            else:
                hi = mid - 1
        return (rows[lo][0], rows[lo][1]) if rows else (str(tex_path), 1)

    findings: list[dict[str, Any]] = []

    def add(sev: str, check: str, file_s: str, line: int | None, msg: str) -> None:
        findings.append({"severity": sev, "check": check, "file": file_s, "line": line, "message": msg})

    if mode == "submission":
        sm_style = _ML_STY_RE.search(full_code)
        template = "neurips" if (sm_style and "neurips" in sm_style.group(2)) else None
        author_sev = "WARN" if template == "neurips" else "ERROR"
        for cmd, check in (
            ("author", "anonymization/author-block"),
            ("affiliation", "anonymization/affiliation"),
            ("institute", "anonymization/affiliation"),
            ("institution", "anonymization/affiliation"),
        ):
            for p, arg in _find_tex_cmd(full_code, cmd):
                cleaned = re.sub(r"\\[a-zA-Z@]+\s*(?:\[[^\]]*\])?|[{}~\s]+", " ", arg).strip()
                if cleaned and not _ANON_OK_RE.search(cleaned):
                    f, ln = _loc(p)
                    add(author_sev, check, f, ln, f"\\{cmd} has non-anonymous content: {cleaned[:60]}")

        for p, arg in _find_tex_cmd(full_code, "email"):
            if arg.strip() and not _ANON_OK_RE.search(arg) and not _OK_EMAIL_RE.search(arg):
                f, ln = _loc(p)
                add("ERROR", "anonymization/email", f, ln, f"\\email present: {arg[:60]}")

        for p, arg in _find_tex_cmd(full_code, "orcid"):
            if arg.strip():
                f, ln = _loc(p)
                add("ERROR", "anonymization/orcid", f, ln, f"ORCID present: {arg[:40]}")

        for p, arg in _find_tex_cmd(full_code, "thanks"):
            if arg.strip():
                f, ln = _loc(p)
                add("WARN", "anonymization/thanks", f, ln, f"\\thanks may leak funding/affiliation: {arg[:60]}")

        for p, arg in _find_tex_cmd(full_code, "section") + _find_tex_cmd(full_code, "section*"):
            if re.search(r"acknowledg", arg, re.I):
                f, ln = _loc(p)
                add("ERROR", "anonymization/acknowledgments", f, ln, f"Acknowledgments section present: {arg[:40]}")
        for env in ("acks", "ack", "acknowledgments", "acknowledgements"):
            for m in re.finditer(rf"\\begin\s*\{{{env}\}}(.*?)\\end\s*\{{{env}\}}", full_code, re.S):
                if m.group(1).strip():
                    f, ln = _loc(m.start())
                    add("ERROR", "anonymization/acknowledgments", f, ln, f"\\begin{{{env}}} present")

        for m in _URL_RE.finditer(full_code):
            url = m.group(0).rstrip(".,;)]\"'")
            low = url.lower()
            f, ln = _loc(m.start())
            if any(h in low for h in _ANON_OK_HOSTS):
                add("INFO", "anonymization/link-ok", f, ln, f"Anonymized mirror link: {url}")
            elif any(h in low for h in _IDENTITY_HOSTS) or re.search(r"/~[a-z]", low):
                add("ERROR", "anonymization/identifying-link", f, ln, f"Identifying link: {url}")

        for m in _EMAIL_RE.finditer(full_code):
            if not _OK_EMAIL_RE.search(m.group(0)):
                f, ln = _loc(m.start())
                add("ERROR", "anonymization/email", f, ln, f"Email address in body: {m.group(0)}")

        for pat in _SELF_CITE_RES:
            for m in pat.finditer(full_code):
                f, ln = _loc(m.start())
                add("WARN", "anonymization/self-citation", f, ln, f"First-person self-citation: {m.group(0)[:60]}")

        for m in _INSTITUTION_RE.finditer(full_code):
            f, ln = _loc(m.start())
            add("WARN", "anonymization/institution-mention", f, ln, f"Institutional self-reference: {m.group(0)}")

        for rex in _FUNDING_RES:
            for m in rex.finditer(full_code):
                f, ln = _loc(m.start())
                add("WARN", "anonymization/funding", f, ln, f"Possible funding/grant reference: {m.group(0)}")

        for m in re.finditer(r"pdfauthor\s*=\s*\{([^}]*)\}", full_code):
            val = m.group(1).strip()
            if val and not _ANON_OK_RE.search(val):
                f, ln = _loc(m.start())
                add("ERROR", "anonymization/pdf-metadata", f, ln, f"hyperref pdfauthor set: {val[:50]}")

        if sm_style and "final" in (sm_style.group(1) or ""):
            f, ln = _loc(sm_style.start())
            add("WARN", "anonymization/class-option", f, ln, f"{sm_style.group(2)} loaded with [final]")
        dm = _DOCCLASS_RE.search(full_code)
        if dm and dm.group(2).strip() == "acmart" and "anonymous" not in (dm.group(1) or ""):
            f, ln = _loc(dm.start())
            add("WARN", "anonymization/class-option", f, ln, "acmart missing 'anonymous' option")

        for name in [n.strip() for n in names.split(",") if n.strip()]:
            for m in re.finditer(re.escape(name), full_code, re.I):
                f, ln = _loc(m.start())
                add("WARN", "anonymization/name-match", f, ln, f"Supplied name/institution '{name}' matched")
    else:
        authors = _find_tex_cmd(full_code, "author")
        if not authors:
            add("ERROR", "reversal/missing-author", str(tex_path), None, "Missing \\author command for camera-ready")
        for cmd in ("author", "affiliation", "institute", "institution", "email"):
            for p, arg in _find_tex_cmd(full_code, cmd):
                cleaned = re.sub(r"\\[a-zA-Z@]+|[{}~\s]+", " ", arg).strip()
                f, ln = _loc(p)
                if not cleaned or _ANON_OK_RE.search(cleaned) or _OK_EMAIL_RE.search(cleaned):
                    add("ERROR", "reversal/placeholder-author", f, ln, f"\\{cmd} still anonymized/empty: {cleaned[:50]}")
        for m in _URL_RE.finditer(full_code):
            url = m.group(0).rstrip(".,;)]\"'")
            if any(h in url.lower() for h in _ANON_OK_HOSTS):
                f, ln = _loc(m.start())
                add("ERROR", "reversal/anon-link", f, ln, f"Anonymized link leftover: {url}")
        for m in _PLACEHOLDER_TEXT_RE.finditer(full_code):
            f, ln = _loc(m.start())
            add("WARN", "reversal/placeholder-text", f, ln, f"Anonymization text leftover: {m.group(0)}")

    # Source hygiene (both modes): home-dir paths & leaked comments
    for m in _HOME_PATH_RE.finditer(full_code):
        user = (m.group(1) or m.group(2) or "").lower()
        if user not in _GENERIC_USERS:
            f, ln = _loc(m.start())
            add("ERROR", "anonymization/home-path", f, ln, f"Home path leaks username: {m.group(0)}")
    for file_s, ln, _code, comment in rows:
        if not comment.strip():
            continue
        em = _EMAIL_RE.search(comment)
        if em and not _OK_EMAIL_RE.search(em.group(0)):
            add("WARN", "anonymization/comment-leak", file_s, ln, f"Comment leaks email: {em.group(0)}")
        um = _URL_RE.search(comment)
        if um and any(h in um.group(0).lower() for h in _IDENTITY_HOSTS):
            add("WARN", "anonymization/comment-leak", file_s, ln, f"Comment leaks identifying URL: {um.group(0)}")

    if pdf_path is not None:
        if not pdf_path.is_file():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        raw_pdf = pdf_path.read_bytes().decode("latin-1", errors="replace")
        for m in re.finditer(r"/Author\s*\(((?:\\.|[^\\)])*)\)", raw_pdf):
            val = m.group(1).strip()
            if val and not _ANON_OK_RE.search(val):
                add("ERROR", "anonymization/pdf-author", str(pdf_path), None, f"PDF /Author metadata: {val[:50]}")

    if supplementary is not None:
        if not supplementary.is_dir():
            raise FileNotFoundError(f"Supplementary dir not found: {supplementary}")
        for p in sorted(supplementary.rglob("*")):
            if p.is_dir() and p.name == ".git":
                add("ERROR", "anonymization/supplementary-git", str(p), None, ".git directory inside supplementary bundle")
            elif p.is_file() and p.name in ("AUTHORS", "NOTICE") and ".git" not in p.parts:
                add("WARN", "anonymization/supplementary-file", str(p), None, f"Identity file {p.name} in supplementary")

    counts = {s: sum(1 for x in findings if x["severity"] == s) for s in ("ERROR", "WARN", "INFO")}
    return {
        "schema": "submission_anonymization_v1",
        "mode": mode,
        "tex": str(tex_path),
        "notes": notes,
        "summary": counts,
        "findings": findings,
        "verdict": "FAIL" if counts["ERROR"] else ("PASS_WITH_WARNINGS" if counts["WARN"] else "PASS"),
    }


# ---------------------------------------------------------------------------
# 2. arXiv LaTeX Cleaner audit + optional comment stripping
# ---------------------------------------------------------------------------

_CLUTTER_DIRS = {".git", ".ipynb_checkpoints", "__pycache__"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".pdf", ".eps"}


def _strip_comments_text(text: str) -> str:
    cleaned_lines: list[str] = []
    for raw in text.splitlines():
        if raw.lstrip().startswith("%"):
            continue
        code, _comment = _split_tex_comment(raw)
        cleaned_lines.append(code.rstrip())
    return "\n".join(cleaned_lines) + ("\n" if text.endswith("\n") else "")


def audit_arxiv_dir(
    tex_dir: Path,
    *,
    max_image_mb: float = 5.0,
    strip_out: Path | None = None,
) -> dict[str, Any]:
    if not tex_dir.exists() or not tex_dir.is_dir():
        raise FileNotFoundError(f"LaTeX directory not found: {tex_dir}")
    if max_image_mb <= 0:
        raise ValueError("--max-image-mb must be > 0")

    findings: list[dict[str, Any]] = []
    referenced_graphics: set[str] = set()
    referenced_tex: set[str] = set()
    tex_files: list[Path] = []
    image_files: list[Path] = []

    for p in sorted(tex_dir.rglob("*")):
        rel = p.relative_to(tex_dir).as_posix()
        if any(part in _CLUTTER_DIRS for part in p.parts):
            if p.is_dir() and p.name in _CLUTTER_DIRS:
                findings.append({"severity": "ERROR", "check": "arxiv/clutter-dir", "file": rel, "message": f"Remove {p.name}/ before arXiv upload"})
            continue
        if not p.is_file():
            continue
        suf = p.suffix.lower()
        if suf == ".tex":
            tex_files.append(p)
        elif suf in _IMAGE_EXTS:
            image_files.append(p)
            size_mb = p.stat().st_size / (1024 * 1024)
            if size_mb > max_image_mb:
                findings.append({
                    "severity": "ERROR",
                    "check": "arxiv/oversized-image",
                    "file": rel,
                    "message": f"Image size {size_mb:.2f}MB exceeds {max_image_mb:.2f}MB limit",
                })

    if not tex_files:
        raise ValueError(f"No .tex files found in {tex_dir}")

    comment_lines = 0
    for tf in tex_files:
        rel = tf.relative_to(tex_dir).as_posix()
        raw = tf.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(raw.splitlines(), start=1):
            code, comment = _split_tex_comment(line)
            if comment.strip():
                comment_lines += 1
                if re.search(r"(?:TODO|FIXME|XXX|@|/(?:home|Users)/)", comment, re.I):
                    findings.append({
                        "severity": "WARN",
                        "check": "arxiv/comment-leak",
                        "file": f"{rel}:{lineno}",
                        "message": f"Strip internal/TODO/leak LaTeX comment: %{comment.strip()[:60]}",
                    })
            for gm in _GRAPHIC_RE.finditer(code):
                referenced_graphics.add(Path(gm.group(1).strip()).name)
                referenced_graphics.add(Path(gm.group(1).strip()).stem)
            for im in _INPUT_RE.finditer(code):
                t = im.group(1).strip()
                referenced_tex.add(t if t.endswith(".tex") else f"{t}.tex")

    for img in image_files:
        rel = img.relative_to(tex_dir).as_posix()
        if img.name not in referenced_graphics and img.stem not in referenced_graphics:
            findings.append({
                "severity": "WARN",
                "check": "arxiv/unused-figure",
                "file": rel,
                "message": f"Image {rel} is not referenced via \\includegraphics",
            })

    if len(tex_files) > 1:
        for tf in tex_files:
            rel = tf.relative_to(tex_dir).as_posix()
            raw = tf.read_text(encoding="utf-8", errors="replace")
            if "\\documentclass" in raw:
                continue
            if rel not in referenced_tex and tf.name not in referenced_tex:
                findings.append({
                    "severity": "WARN",
                    "check": "arxiv/unused-tex",
                    "file": rel,
                    "message": f"Secondary .tex file {rel} is not referenced via \\input/\\include",
                })

    stripped_dir: str | None = None
    if strip_out is not None:
        if strip_out.resolve() == tex_dir.resolve():
            raise ValueError("--strip-comments-out must differ from input tex_dir")
        strip_out.mkdir(parents=True, exist_ok=True)
        for p in sorted(tex_dir.rglob("*")):
            if any(part in _CLUTTER_DIRS for part in p.parts):
                continue
            rel = p.relative_to(tex_dir)
            dest = strip_out / rel
            if p.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
            elif p.is_file():
                dest.parent.mkdir(parents=True, exist_ok=True)
                if p.suffix.lower() == ".tex":
                    dest.write_text(_strip_comments_text(p.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
                else:
                    shutil.copy2(p, dest)
        stripped_dir = str(strip_out)

    counts = {s: sum(1 for x in findings if x["severity"] == s) for s in ("ERROR", "WARN")}
    return {
        "schema": "submission_arxiv_clean_v1",
        "tex_dir": str(tex_dir),
        "tex_files": len(tex_files),
        "image_files": len(image_files),
        "comment_lines": comment_lines,
        "stripped_out": stripped_dir,
        "summary": counts,
        "findings": findings,
        "verdict": "FAIL" if counts["ERROR"] else ("PASS_WITH_WARNINGS" if counts["WARN"] else "PASS"),
    }


# ---------------------------------------------------------------------------
# 3. BibTeX Verifier & rebiber protect_title_caps
# ---------------------------------------------------------------------------

def protect_title_caps(title: str) -> str:
    """Adapt yuchenlin/rebiber protect_title_caps: protect acronyms/mixed-case tokens without {{...}}."""
    if title.startswith("{") and title.endswith("}"):
        return title
    words = title.split(" ")
    out: list[str] = []
    for idx, word in enumerate(words):
        if not word:
            out.append(word)
            continue
        if word.startswith("{") and word.endswith("}"):
            out.append(word)
            continue
        core = word.strip(",:;.?!")
        needs_brace = False
        if core in _AI_ACRONYMS:
            needs_brace = True
        elif any(c.isdigit() for c in core) and any(c.isalpha() for c in core):
            needs_brace = True
        elif sum(1 for c in core if c.isupper()) >= 2:
            needs_brace = True
        elif idx > 0 and any(c.isupper() for c in core[1:]):
            needs_brace = True
        if needs_brace:
            lead = word[: len(word) - len(word.lstrip(",:;.\"'("))]
            trail = word[len(word.rstrip(",:;.\"')")) :]
            mid = word[len(lead) : len(word) - len(trail) if trail else len(word)]
            if not (mid.startswith("{") and mid.endswith("}")):
                out.append(f"{lead}{{{mid}}}{trail}")
            else:
                out.append(word)
        else:
            out.append(word)
    return " ".join(out)


def parse_bibtex(text: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    i = 0
    n = len(text)
    while i < n:
        at = text.find("@", i)
        if at == -1:
            break
        m = re.match(r"@([A-Za-z]+)\s*\{\s*([^,\s]+)\s*,", text[at:])
        if not m:
            i = at + 1
            continue
        etype = m.group(1).lower()
        key = m.group(2).strip()
        if etype in {"comment", "preamble", "string"}:
            i = at + m.end()
            continue
        pos = at + m.end()
        depth = 1
        start_body = pos
        while pos < n and depth > 0:
            if text[pos] == "{":
                depth += 1
            elif text[pos] == "}":
                depth -= 1
            pos += 1
        body = text[start_body : pos - 1]
        fields: dict[str, str] = {}
        j = 0
        bn = len(body)
        while j < bn:
            fm = re.match(r"[\s,]*([A-Za-z0-9_-]+)\s*=\s*", body[j:])
            if not fm:
                break
            fname = fm.group(1).lower()
            k = j + fm.end()
            if k >= bn:
                break
            if body[k] == "{":
                d = 1
                k += 1
                vs = k
                while k < bn and d > 0:
                    if body[k] == "{":
                        d += 1
                    elif body[k] == "}":
                        d -= 1
                    k += 1
                val = body[vs : k - 1]
            elif body[k] == '"':
                k += 1
                vs = k
                while k < bn and not (body[k] == '"' and body[k - 1] != "\\"):
                    k += 1
                val = body[vs:k]
                k += 1
            else:
                vs = k
                while k < bn and body[k] not in ",\n":
                    k += 1
                val = body[vs:k].strip()
            fields[fname] = " ".join(val.split())
            j = k
        entries.append({"type": etype, "key": key, "fields": fields})
        i = pos
    return entries


def _verify_doi_online(doi: str, title: str, year: str, *, api_base: str | None = None) -> list[str]:
    issues: list[str] = []
    base = (api_base or os.environ.get("CROSSREF_API_BASE") or "https://api.crossref.org").rstrip("/")
    url = f"{base}/works/{urllib.parse.quote(doi)}"
    req = urllib.request.Request(url, headers={"User-Agent": "research-scientist-preflight/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace")).get("message", {})
        if not isinstance(data, dict):
            data = {}
        cr_titles = data.get("title") or []
        if cr_titles and title:
            norm_bib = re.sub(r"[^a-z0-9 ]", "", title.lower())
            norm_cr = re.sub(r"[^a-z0-9 ]", "", str(cr_titles[0]).lower())
            if norm_bib and norm_cr and norm_bib[:25] not in norm_cr and norm_cr[:25] not in norm_bib:
                issues.append(f"DOI title mismatch: bib={title[:50]!r} vs crossref={str(cr_titles[0])[:50]!r}")
        parts = (data.get("issued") or {}).get("date-parts") or [[]]
        issued = parts[0][0] if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0] else None
        if issued is not None and year.isdigit() and str(issued).isdigit() and abs(int(issued) - int(year)) > 1:
            issues.append(f"DOI year mismatch: bib={year} vs crossref={issued}")
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        issues.append(f"Online DOI check error for {doi}: {exc}")
    return issues


def audit_bibtex(
    bib_path: Path,
    *,
    tex_path: Path | None = None,
    protect_caps: bool = False,
    fix_out: Path | None = None,
    verify_online: bool = False,
) -> dict[str, Any]:
    if not bib_path.is_file():
        raise FileNotFoundError(f"BibTeX file not found: {bib_path}")
    raw = bib_path.read_text(encoding="utf-8", errors="replace")
    if not raw.strip():
        raise ValueError(f"BibTeX file is empty: {bib_path}")
    entries = parse_bibtex(raw)
    if not entries:
        raise ValueError(f"No valid BibTeX entries parsed in {bib_path}")

    findings: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    bib_keys: set[str] = set()

    for ent in entries:
        key = ent["key"]
        etype = ent["type"]
        fields = ent["fields"]
        if key in seen_keys:
            findings.append({"severity": "ERROR", "check": "bibtex/duplicate-key", "key": key, "message": f"Duplicate BibTeX key: {key}"})
        seen_keys.add(key)
        bib_keys.add(key)

        for req in ("title", "author", "year"):
            val = fields.get(req, "").strip()
            if not val:
                findings.append({"severity": "ERROR", "check": "bibtex/missing-field", "key": key, "message": f"Missing required field '{req}'"})
            elif re.fullmatch(r"(?:tbd|todo|unknown|n/?a|placeholder|et\s+al\.?)", val, re.I):
                findings.append({"severity": "ERROR", "check": "bibtex/placeholder-field", "key": key, "message": f"Suspicious placeholder in '{req}': {val}"})

        year = fields.get("year", "").strip()
        if year and not re.fullmatch(r"(?:19|20)\d{2}", year):
            findings.append({"severity": "ERROR", "check": "bibtex/invalid-year", "key": key, "message": f"Invalid year format: {year}"})

        if etype == "inproceedings" and not fields.get("booktitle"):
            findings.append({"severity": "ERROR", "check": "bibtex/missing-venue", "key": key, "message": "inproceedings missing 'booktitle'"})
        elif etype == "article" and not (fields.get("journal") or fields.get("eprint")):
            findings.append({"severity": "ERROR", "check": "bibtex/missing-venue", "key": key, "message": "article missing 'journal' or 'eprint'"})

        journal_blob = (fields.get("journal", "") + " " + fields.get("booktitle", "")).lower()
        if "arxiv" in journal_blob or fields.get("archiveprefix", "").lower() == "arxiv":
            findings.append({"severity": "WARN", "check": "bibtex/preprint-entry", "key": key, "message": "Preprint entry; check via rebiber/DBLP if peer-reviewed proceedings exist"})

        title = fields.get("title", "")
        if title:
            protected = protect_title_caps(title)
            if protected != title:
                findings.append({
                    "severity": "WARN",
                    "check": "bibtex/unprotected-caps",
                    "key": key,
                    "message": f"Unprotected acronyms/caps in title: {title!r} -> {protected!r}",
                })
                if protect_caps or fix_out is not None:
                    fields["title"] = protected

        if verify_online and fields.get("doi"):
            for iss in _verify_doi_online(fields["doi"], title, year):
                findings.append({"severity": "ERROR", "check": "bibtex/online-mismatch", "key": key, "message": iss})

    if tex_path is not None:
        rows, _ = _load_tex_flattened(tex_path)
        tex_code = "\n".join(r[2] for r in rows)
        cited: set[str] = set()
        for m in _CITE_RE.finditer(tex_code):
            for ck in m.group(1).split(","):
                ck = ck.strip()
                if ck:
                    cited.add(ck)
        for missing_k in sorted(cited - bib_keys):
            findings.append({"severity": "ERROR", "check": "bibtex/undefined-cite", "key": missing_k, "message": f"Undefined \\cite{{{missing_k}}} not in {bib_path.name}"})
        for unused_k in sorted(bib_keys - cited):
            findings.append({"severity": "WARN", "check": "bibtex/unused-entry", "key": unused_k, "message": f"Unused BibTeX key {unused_k} not cited in {tex_path.name}"})

    if fix_out is not None:
        fix_out.parent.mkdir(parents=True, exist_ok=True)
        rendered: list[str] = []
        for ent in entries:
            body_lines = [f"  {k} = {{{v}}}" for k, v in ent["fields"].items()]
            rendered.append(f"@{ent['type']}{{{ent['key']},\n" + ",\n".join(body_lines) + "\n}")
        fix_out.write_text("\n\n".join(rendered) + "\n", encoding="utf-8")

    counts = {s: sum(1 for x in findings if x["severity"] == s) for s in ("ERROR", "WARN")}
    return {
        "schema": "submission_bibtex_v1",
        "bib": str(bib_path),
        "entry_count": len(entries),
        "fixed_out": str(fix_out) if fix_out else None,
        "summary": counts,
        "findings": findings,
        "verdict": "FAIL" if counts["ERROR"] else ("PASS_WITH_WARNINGS" if counts["WARN"] else "PASS"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_an = sub.add_parser("anonymize", help="Scan LaTeX/PDF/supplementary for double-blind or camera-ready leaks")
    p_an.add_argument("tex", help="Main .tex file")
    p_an.add_argument("--mode", choices=("submission", "camera-ready"), default="submission")
    p_an.add_argument("--names", default="", help="Comma-separated author/institution names to check")
    p_an.add_argument("--pdf", help="Optional compiled PDF to scan for /Author metadata")
    p_an.add_argument("--supplementary", help="Optional supplementary directory to scan")
    p_an.add_argument("--strict", action="store_true", help="Treat warnings as failures (exit 1)")
    p_an.add_argument("--out", help="Write full JSON output to PATH")
    p_an.add_argument("--json", nargs="?", const="-", help="Emit JSON output")
    p_an.add_argument("--compact", action="store_true", help="Bounded <4KB stdout summary")

    p_ax = sub.add_parser("arxiv-clean", help="Audit arXiv LaTeX directory for %% comment leaks and unused/oversized assets")
    p_ax.add_argument("tex_dir", help="Path to LaTeX submission directory")
    p_ax.add_argument("--strip-comments-out", help="Optional destination directory to write comment-stripped copy")
    p_ax.add_argument("--max-image-mb", type=float, default=5.0, help="Max allowed image size in MB (default 5.0)")
    p_ax.add_argument("--strict", action="store_true", help="Treat warnings as failures (exit 1)")
    p_ax.add_argument("--out", help="Write full JSON output to PATH")
    p_ax.add_argument("--json", nargs="?", const="-", help="Emit JSON output")
    p_ax.add_argument("--compact", action="store_true", help="Bounded <4KB stdout summary")

    p_bb = sub.add_parser("bibtex", help="Verify BibTeX fields, citation keys, and rebiber title-cap protection")
    p_bb.add_argument("bib", help="Path to .bib file")
    p_bb.add_argument("--tex", help="Optional .tex file to verify \\cite{} keys")
    p_bb.add_argument("--protect-caps", action="store_true", help="Apply rebiber protect_title_caps when writing --fix-out")
    p_bb.add_argument("--fix-out", help="Write normalized .bib with protected title caps")
    p_bb.add_argument("--verify-online", action="store_true", help="Query Crossref API to verify DOIs")
    p_bb.add_argument("--strict", action="store_true", help="Treat warnings as failures (exit 1)")
    p_bb.add_argument("--out", help="Write full JSON output to PATH")
    p_bb.add_argument("--json", nargs="?", const="-", help="Emit JSON output")
    p_bb.add_argument("--compact", action="store_true", help="Bounded <4KB stdout summary")

    args = parser.parse_args(argv)
    try:
        if args.cmd == "anonymize":
            tp = Path(_nonempty(args.tex, "tex"))
            pp = Path(_nonempty(args.pdf, "--pdf")) if args.pdf is not None else None
            sp = Path(_nonempty(args.supplementary, "--supplementary")) if args.supplementary is not None else None
            res = scan_anonymization(tp, mode=args.mode, names=args.names, pdf_path=pp, supplementary=sp)
            compact = {
                "compact": True,
                "schema": res["schema"],
                "mode": res["mode"],
                "summary": res["summary"],
                "verdict": res["verdict"],
                "findings": res["findings"][:8],
                "out": args.out,
            }
            _emit(res, compact, args)
            return 1 if res["summary"]["ERROR"] or (args.strict and res["summary"]["WARN"]) else 0

        if args.cmd == "arxiv-clean":
            td = Path(_nonempty(args.tex_dir, "tex_dir"))
            so = Path(_nonempty(args.strip_comments_out, "--strip-comments-out")) if args.strip_comments_out is not None else None
            res = audit_arxiv_dir(td, max_image_mb=args.max_image_mb, strip_out=so)
            compact = {
                "compact": True,
                "schema": res["schema"],
                "tex_files": res["tex_files"],
                "image_files": res["image_files"],
                "summary": res["summary"],
                "verdict": res["verdict"],
                "findings": res["findings"][:8],
                "out": args.out,
            }
            _emit(res, compact, args)
            return 1 if res["summary"]["ERROR"] or (args.strict and res["summary"]["WARN"]) else 0

        bp = Path(_nonempty(args.bib, "bib"))
        tp = Path(_nonempty(args.tex, "--tex")) if args.tex is not None else None
        fo = Path(_nonempty(args.fix_out, "--fix-out")) if args.fix_out is not None else None
        res = audit_bibtex(bp, tex_path=tp, protect_caps=args.protect_caps, fix_out=fo, verify_online=args.verify_online)
        compact = {
            "compact": True,
            "schema": res["schema"],
            "entry_count": res["entry_count"],
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
