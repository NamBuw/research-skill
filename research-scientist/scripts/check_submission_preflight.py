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
import bisect
import difflib
import json
import math
import os
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

try:
    import defusedxml.ElementTree as ET  # type: ignore
except ImportError:
    import xml.etree.ElementTree as ET

MAX_COMPACT_BYTES = 3800

_ANON_OK_RE = re.compile(
    r"anon|blind|omitted|hidden|redacted|withheld|paper\s*(?:id|#|number)|submission\s*(?:id|#|number)|under\s+review",
    re.I,
)
_IDENTITY_HOSTS = (
    "github.com", "gitlab.com", "bitbucket.org", "huggingface.co",
    "sites.google.com", "drive.google.com", "dropbox.com", "onedrive.live.com", "1drv.ms",
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
_ML_STY_RE = re.compile(r"\\usepackage\s*(?:\[([^\]]*)\]\s*)?\{(neurips_\d{4}|icml\d{4}|iclr\d{4}_conference)\}")
_DOCCLASS_RE = re.compile(r"\\documentclass\s*(?:\[([^\]]*)\]\s*)?\{([^}]+)\}")
_INPUT_RE = re.compile(r"\\(?:input|include)\s*\{([^}]+)\}")
_GRAPHIC_RE = re.compile(r"\\includegraphics\s*(?:\[[^\]]*\]\s*)?\{([^}]+)\}")
_CITE_RE = re.compile(r"\\(?:cite[a-zA-Z*]*|autocite|textcite|parencite)\s*(?:\[[^\]]*\]\s*)*\{([^}]+)\}")
_VERBATIM_ENVS = {"verbatim", "verbatim*", "Verbatim", "Verbatim*", "lstlisting", "minted", "alltt"}
_BEGIN_ENV_RE = re.compile(r"\\begin\s*\{([^}]+)\}")

_AI_ACRONYMS = {
    "AI", "ML", "NLP", "CV", "LLM", "LLMs", "GPT", "GPT-4", "BERT", "RoBERTa",
    "ResNet", "ViT", "CLIP", "SAM", "GAN", "VAE", "RL", "RLHF", "DPO", "PPO",
    "RAG", "LoRA", "MMLU", "GSM8K", "ImageNet", "NeurIPS", "ICML", "ICLR",
    "CVPR", "ICCV", "ECCV", "ACL", "EMNLP", "NAACL", "AAAI", "TMLR", "TPAMI",
    "3D", "2D", "CNN", "RNN", "LSTM", "GRU", "GNN", "GCN", "MLP", "SGD", "AdamW",
}
_ARXIV_ID_RE = re.compile(r"(?:arXiv:)?(\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+/\d{7}(?:v\d+)?)", re.I)
_BIB_ENTRY_START_RE = re.compile(r"@([A-Za-z]+)\s*([{(])")
_BIB_FIELD_NAME_RE = re.compile(r"([A-Za-z0-9_-]+)\s*=\s*")


def _err(msg: str) -> int:
    print(json.dumps({"error": msg}), file=sys.stderr)
    return 2


def _nonempty(val: Any, flag: str) -> str:
    if not isinstance(val, str) or not val.strip():
        raise ValueError(f"Empty or invalid value for {flag}")
    return val.strip()


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
        for cap in (8, 4, 2, 0):
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


def _scan_tex_lines(text: str) -> list[tuple[int, str, str, str, bool, bool]]:
    """Return (lineno, raw_line, code_part, comment_part, has_comment, in_verbatim) per line."""
    rows: list[tuple[int, str, str, str, bool, bool]] = []
    active_env: str | None = None

    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        i = 0
        n = len(raw_line)
        code_buf: list[str] = []
        comment_part = ""
        has_comment = False
        line_in_verb = False

        if active_env is not None:
            end_tag = f"\\end{{{active_env}}}"
            end_pos = raw_line.find(end_tag)
            if end_pos == -1:
                rows.append((lineno, raw_line, raw_line, "", False, True))
                continue
            verb_end = end_pos + len(end_tag)
            code_buf.append(raw_line[:verb_end])
            i = verb_end
            active_env = None
            if i >= n:
                rows.append((lineno, raw_line, raw_line, "", False, True))
                continue

        while i < n:
            if raw_line.startswith("\\verb", i):
                j = i + 5
                if j < n and raw_line[j] == "*":
                    j += 1
                if j < n and not raw_line[j].isalpha():
                    delim = raw_line[j]
                    end_pos = raw_line.find(delim, j + 1)
                    if end_pos != -1:
                        code_buf.append(raw_line[i : end_pos + 1])
                        i = end_pos + 1
                        continue
            if raw_line.startswith("\\begin", i):
                bm = _BEGIN_ENV_RE.match(raw_line, i)
                if bm and bm.group(1).strip() in _VERBATIM_ENVS:
                    env_name = bm.group(1).strip()
                    end_tag = f"\\end{{{env_name}}}"
                    same_end = raw_line.find(end_tag, bm.end())
                    if same_end == -1:
                        code_buf.append(raw_line[i:])
                        active_env = env_name
                        line_in_verb = True
                        i = n
                        break
                    verb_end = same_end + len(end_tag)
                    code_buf.append(raw_line[i:verb_end])
                    i = verb_end
                    if i >= n:
                        line_in_verb = True
                        break
                    continue
            ch = raw_line[i]
            if ch == "\\" and i + 1 < n:
                code_buf.append(raw_line[i : i + 2])
                i += 2
                continue
            if ch == "%":
                comment_part = raw_line[i + 1 :]
                has_comment = True
                break
            code_buf.append(ch)
            i += 1

        rows.append((lineno, raw_line, "".join(code_buf), comment_part, has_comment, line_in_verb))
    return rows


def _resolve_tex_child(child_name: str, caller_dir: Path, root_dir: Path) -> tuple[Path | None, str | None]:
    """Safely resolve a LaTeX \\input/\\include target within root_dir."""
    if not child_name or child_name.startswith("/"):
        return None, "unsafe"
    candidates: list[Path] = [
        root_dir / child_name,
        caller_dir / child_name,
    ]
    if not child_name.endswith(".tex"):
        candidates.extend([
            root_dir / f"{child_name}.tex",
            caller_dir / f"{child_name}.tex",
        ])
    for cand in candidates:
        if cand.exists() or cand.is_symlink():
            try:
                res = cand.resolve()
            except OSError:
                return None, "unsafe"
            if not res.is_relative_to(root_dir):
                return None, "unsafe"
            if res.is_file():
                return res, None
    # Also detect explicit traversal string when target does not exist
    try:
        probe = (caller_dir / child_name).resolve()
        if not probe.is_relative_to(root_dir):
            return None, "unsafe"
    except OSError:
        return None, "unsafe"
    return None, "missing"


def _load_tex_flattened(
    tex_path: Path,
    seen: set[str] | None = None,
    depth: int = 0,
    *,
    root_dir: Path | None = None,
) -> tuple[list[tuple[str, int, str, str]], list[str]]:
    if not tex_path.is_file():
        raise FileNotFoundError(f"TeX file not found: {tex_path}")
    root = (root_dir or tex_path.parent).resolve()
    key_path = tex_path.resolve()
    if not key_path.is_relative_to(root):
        return [], [f"{tex_path}: unsafe \\input escapes root {root}"]
    seen = seen if seen is not None else set()
    key = str(key_path)
    if key in seen or depth > 8:
        return [], []
    seen.add(key)
    notes: list[str] = []
    rows: list[tuple[str, int, str, str]] = []
    raw = tex_path.read_text(encoding="utf-8", errors="replace")
    scanned = _scan_tex_lines(raw)
    code_lines: list[str] = []
    for lineno, _raw_line, code, comment, _has_comment, in_verb in scanned:
        rows.append((str(tex_path), lineno, code, comment))
        code_lines.append("" if in_verb else code)
    code_joined = "\n".join(code_lines)
    for m in _INPUT_RE.finditer(code_joined):
        child_name = m.group(1).strip()
        lineno = code_joined[: m.start()].count("\n") + 1
        cpath, err_kind = _resolve_tex_child(child_name, tex_path.parent, root)
        if err_kind == "unsafe":
            notes.append(f"{tex_path}:{lineno}: unsafe \\input{{{child_name}}} escapes root")
        elif cpath is not None:
            sub_rows, sub_notes = _load_tex_flattened(cpath, seen, depth + 1, root_dir=root)
            rows.extend(sub_rows)
            notes.extend(sub_notes)
        else:
            notes.append(f"{tex_path}:{lineno}: missing \\input{{{child_name}}}")
    return rows, notes


def _find_tex_cmd(text: str, cmd: str) -> list[tuple[int, str]]:
    boundary = r"\b" if cmd[-1].isalnum() else ""
    matches = list(re.finditer(r"\\" + re.escape(cmd) + boundary + r"\s*(?:\[[^\]]*\]\s*)?\{", text))
    if not matches:
        return []
    out: list[tuple[int, str]] = []
    if len(matches) == 1:
        m = matches[0]
        start = m.end() - 1
        depth = 0
        i = start
        n = len(text)
        while i < n:
            if text[i] == "\\" and i + 1 < n:
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

    close_map: dict[int, int] = {}
    stack: list[int] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch == "{":
            stack.append(i)
        elif ch == "}":
            if stack:
                close_map[stack.pop()] = i
        i += 1
    for m in matches:
        start = m.end() - 1
        end_idx = close_map.get(start)
        if end_idx is not None:
            out.append((m.start(), text[start + 1 : end_idx]))
    return out


def _extract_url_host(url: str) -> str:
    low = url.strip().lower()
    if "://" not in low:
        low = "https://" + low
    try:
        return (urllib.parse.urlparse(low).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def _host_matches(host: str, targets: tuple[str, ...]) -> bool:
    if not host:
        return False
    for t in targets:
        if host == t or host.endswith("." + t):
            return True
    if targets is _IDENTITY_HOSTS and "onedrive" in host.split("."):
        return True
    return False


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

    for note in notes:
        if "unsafe \\input" in note:
            add("ERROR", "anonymization/unsafe-input", str(tex_path), None, note)

    if mode == "submission":
        style_matches = list(_ML_STY_RE.finditer(full_code))
        template = "neurips" if any("neurips" in sm.group(2) for sm in style_matches) else None
        has_deanonymizing_opt = any(
            re.search(r"\b(?:final|preprint|accepted)\b", sm.group(1) or "")
            for sm in style_matches
        )
        author_sev = "WARN" if (template == "neurips" and not has_deanonymizing_opt) else "ERROR"
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

        for sec_cmd in ("section", "section*", "subsection", "subsection*", "paragraph", "paragraph*"):
            for p, arg in _find_tex_cmd(full_code, sec_cmd):
                if re.search(r"acknowledg", arg, re.I):
                    f, ln = _loc(p)
                    add("ERROR", "anonymization/acknowledgments", f, ln, f"Acknowledgments section present: {arg[:40]}")
        for env in ("acks", "ack", "acknowledgments", "acknowledgements"):
            begin_re = re.compile(rf"\\begin\s*\{{{env}\}}")
            end_re = re.compile(rf"\\end\s*\{{{env}\}}")
            pos_env = 0
            while True:
                bm = begin_re.search(full_code, pos_env)
                if bm is None:
                    break
                em = end_re.search(full_code, bm.end())
                if em is None:
                    break
                if full_code[bm.end() : em.start()].strip():
                    f, ln = _loc(bm.start())
                    add("ERROR", "anonymization/acknowledgments", f, ln, f"\\begin{{{env}}} present")
                pos_env = em.end()

        for m in _URL_RE.finditer(full_code):
            url = m.group(0).rstrip(".,;)]\"'")
            low = url.lower()
            host = _extract_url_host(url)
            f, ln = _loc(m.start())
            if _host_matches(host, _ANON_OK_HOSTS):
                add("INFO", "anonymization/link-ok", f, ln, f"Anonymized mirror link: {url}")
            elif _host_matches(host, _IDENTITY_HOSTS) or re.search(r"/~[a-z]", low):
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

        for sm_style in style_matches:
            opt_m = re.search(r"\b(final|preprint|accepted)\b", sm_style.group(1) or "")
            if opt_m:
                f, ln = _loc(sm_style.start())
                add("ERROR", "anonymization/class-option", f, ln, f"{sm_style.group(2)} loaded with [{opt_m.group(1)}]")
        for im in re.finditer(r"\\iclrfinalcopy(?![A-Za-z])", full_code):
            f, ln = _loc(im.start())
            add("ERROR", "anonymization/class-option", f, ln, "\\iclrfinalcopy de-anonymizes ICLR submission")
        dm = _DOCCLASS_RE.search(full_code)
        if dm and dm.group(2).strip() == "acmart":
            opts = [re.sub(r"\s+", "", opt).lower() for opt in (dm.group(1) or "").split(",") if opt.strip()]
            if not any(opt in {"anonymous", "anonymous=true"} for opt in opts):
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
            if _host_matches(_extract_url_host(url), _ANON_OK_HOSTS):
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
        for em in _EMAIL_RE.finditer(comment):
            if not _OK_EMAIL_RE.search(em.group(0)):
                add("WARN", "anonymization/comment-leak", file_s, ln, f"Comment leaks email: {em.group(0)}")
        for um in _URL_RE.finditer(comment):
            url = um.group(0).rstrip(".,;)]\"'")
            if _host_matches(_extract_url_host(url), _IDENTITY_HOSTS):
                add("WARN", "anonymization/comment-leak", file_s, ln, f"Comment leaks identifying URL: {url}")

    if pdf_path is not None:
        if not pdf_path.is_file():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        raw_pdf_bytes = pdf_path.read_bytes()
        raw_pdf = raw_pdf_bytes.decode("latin-1", errors="replace")
        for m in re.finditer(r"/Author\s*\(((?:\\.|[^\\)])*)\)", raw_pdf):
            val = m.group(1).strip()
            if val and not _ANON_OK_RE.search(val):
                add("ERROR", "anonymization/pdf-author", str(pdf_path), None, f"PDF /Author metadata: {val[:50]}")
        for hm in re.finditer(rb"/Author\s*<([0-9A-Fa-f\s]+)>", raw_pdf_bytes):
            hex_str = re.sub(rb"\s+", b"", hm.group(1)).decode("ascii", errors="ignore")
            if len(hex_str) % 2 == 1:
                hex_str += "0"
            try:
                raw_val = bytes.fromhex(hex_str)
            except ValueError:
                continue
            if raw_val.startswith(b"\xfe\xff"):
                val = raw_val[2:].decode("utf-16-be", errors="replace").strip("\x00 ")
            elif raw_val.startswith(b"\xff\xfe"):
                val = raw_val[2:].decode("utf-16-le", errors="replace").strip("\x00 ")
            else:
                val = raw_val.decode("latin-1", errors="replace").strip("\x00 ")
            if val and not _ANON_OK_RE.search(val):
                add("ERROR", "anonymization/pdf-author", str(pdf_path), None, f"PDF /Author metadata: {val[:50]}")

    if supplementary is not None:
        if not supplementary.is_dir():
            raise FileNotFoundError(f"Supplementary dir not found: {supplementary}")
        supp_root = supplementary.resolve()
        for dirpath, dirnames, filenames in os.walk(supplementary, followlinks=False):
            dp = Path(dirpath)
            kept_dirs: list[str] = []
            for d in sorted(dirnames):
                p = dp / d
                if d == ".git":
                    add("ERROR", "anonymization/supplementary-git", str(p), None, ".git directory inside supplementary bundle")
                    continue
                if p.is_symlink():
                    if not p.exists() or not p.resolve().is_relative_to(supp_root):
                        add("ERROR", "anonymization/unsafe-symlink", str(p), None, f"Escaping/broken symlink in supplementary: {p}")
                    continue
                kept_dirs.append(d)
            dirnames[:] = kept_dirs
            for fn in sorted(filenames):
                p = dp / fn
                if p.is_symlink():
                    if not p.exists() or not p.resolve().is_relative_to(supp_root):
                        add("ERROR", "anonymization/unsafe-symlink", str(p), None, f"Escaping/broken symlink in supplementary: {p}")
                    continue
                if fn in ("AUTHORS", "NOTICE"):
                    add("WARN", "anonymization/supplementary-file", str(p), None, f"Identity file {fn} in supplementary")

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
    for _lineno, raw_line, code_part, _comment_part, has_comment, in_verb in _scan_tex_lines(text):
        if in_verb:
            cleaned_lines.append(raw_line)
        elif has_comment and not code_part.strip():
            continue
        else:
            cleaned_lines.append(code_part.rstrip())
    return "\n".join(cleaned_lines) + ("\n" if text.endswith("\n") else "")


def _normalize_rel_prefix(raw_p: str) -> str:
    p = raw_p.strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    p = p.lstrip("/")
    if p and not p.endswith("/"):
        p += "/"
    return p


def _match_graphic_ref(img_rel: str, gref: str, graphicspaths: list[str]) -> bool:
    norm = gref.strip().replace("\\", "/")
    while norm.startswith("./"):
        norm = norm[2:]
    if not norm:
        return False
    img_stem_rel = img_rel.rsplit(".", 1)[0] if "." in img_rel else img_rel
    candidates = [norm]
    for gp in graphicspaths:
        candidates.append(f"{gp}{norm}")
    for cand in candidates:
        if img_rel == cand or img_stem_rel == cand:
            return True
    return False


def audit_arxiv_dir(
    tex_dir: Path,
    *,
    max_image_mb: float = 5.0,
    strip_out: Path | None = None,
    prune_unused: bool = False,
) -> dict[str, Any]:
    if not tex_dir.exists() or not tex_dir.is_dir():
        raise FileNotFoundError(f"LaTeX directory not found: {tex_dir}")
    if isinstance(max_image_mb, bool) or not isinstance(max_image_mb, (int, float)) or not math.isfinite(float(max_image_mb)) or float(max_image_mb) <= 0:
        raise ValueError("--max-image-mb must be finite and > 0")
    max_image_mb = float(max_image_mb)
    if prune_unused and strip_out is None:
        raise ValueError("--prune-unused requires --strip-comments-out")

    tex_root = tex_dir.resolve()
    out_root: Path | None = None
    if strip_out is not None:
        out_root = strip_out.expanduser().resolve()
        if out_root == tex_root or out_root.is_relative_to(tex_root) or tex_root.is_relative_to(out_root):
            raise ValueError("--strip-comments-out must not overlap input tex_dir")
        if out_root.exists() and not out_root.is_dir():
            raise ValueError(f"--strip-comments-out exists and is not a directory: {out_root}")

    findings: list[dict[str, Any]] = []
    tex_files: list[Path] = []
    image_files: list[Path] = []
    safe_files: list[Path] = []

    for dirpath, dirnames, filenames in os.walk(tex_dir, followlinks=False):
        dp = Path(dirpath)
        kept_dirs: list[str] = []
        for d in sorted(dirnames):
            dp_sub = dp / d
            rel = dp_sub.relative_to(tex_dir).as_posix()
            if d in _CLUTTER_DIRS:
                findings.append({"severity": "ERROR", "check": "arxiv/clutter-dir", "file": rel, "message": f"Remove {d}/ before arXiv upload"})
                continue
            if dp_sub.is_symlink():
                try:
                    resolved = dp_sub.resolve()
                    ok = dp_sub.exists() and resolved.is_relative_to(tex_root)
                except OSError:
                    ok = False
                if not ok:
                    findings.append({"severity": "ERROR", "check": "arxiv/unsafe-symlink", "file": rel, "message": f"Unsafe or escaping symlink directory: {rel}"})
                continue
            kept_dirs.append(d)
        dirnames[:] = kept_dirs

        for fn in sorted(filenames):
            p = dp / fn
            rel = p.relative_to(tex_dir).as_posix()
            if p.is_symlink():
                try:
                    resolved = p.resolve()
                    ok = p.exists() and resolved.is_relative_to(tex_root)
                except OSError:
                    ok = False
                if not ok:
                    findings.append({"severity": "ERROR", "check": "arxiv/unsafe-symlink", "file": rel, "message": f"Unsafe or escaping symlink: {rel}"})
                    continue
            if not p.is_file():
                continue
            safe_files.append(p)
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
    tex_parsed: dict[str, tuple[Path, list[tuple[int, str, str, str, bool, bool]]]] = {}
    code_joined_map: dict[str, str] = {}
    docclass_rels: list[str] = []
    graphicspaths: list[str] = []

    for tf in tex_files:
        rel = tf.relative_to(tex_dir).as_posix()
        raw = tf.read_text(encoding="utf-8", errors="replace")
        scanned = _scan_tex_lines(raw)
        tex_parsed[rel] = (tf, scanned)
        code_joined = "\n".join(r[2] for r in scanned if not r[5])
        code_joined_map[rel] = code_joined
        if _DOCCLASS_RE.search(code_joined):
            docclass_rels.append(rel)
        for _pos, gp_arg in _find_tex_cmd(code_joined, "graphicspath"):
            for gm in re.finditer(r"\{([^}]*)\}", gp_arg):
                pref = _normalize_rel_prefix(gm.group(1))
                if pref and pref not in graphicspaths:
                    graphicspaths.append(pref)
        for lineno, _raw_line, _code, comment, _hc, in_verb in scanned:
            if not in_verb and comment.strip():
                comment_lines += 1
                if re.search(r"(?:TODO|FIXME|XXX|@|/(?:home|Users)/)", comment, re.I):
                    findings.append({
                        "severity": "WARN",
                        "check": "arxiv/comment-leak",
                        "file": f"{rel}:{lineno}",
                        "message": f"Strip internal/TODO/leak LaTeX comment: %{comment.strip()[:60]}",
                    })

    # Trace reachable .tex files from \documentclass entrypoints (or all .tex if none)
    roots = docclass_rels if docclass_rels else sorted(tex_parsed.keys())
    reachable_tex: set[str] = set()
    queue = list(roots)
    while queue:
        cur_rel = queue.pop(0)
        if cur_rel in reachable_tex or cur_rel not in tex_parsed:
            continue
        reachable_tex.add(cur_rel)
        cur_path, _scanned = tex_parsed[cur_rel]
        for im in _INPUT_RE.finditer(code_joined_map[cur_rel]):
            t = im.group(1).strip()
            cpath, err_kind = _resolve_tex_child(t, cur_path.parent, tex_root)
            if err_kind is None and cpath is not None:
                try:
                    crel = cpath.relative_to(tex_root).as_posix()
                except ValueError:
                    continue
                if crel in tex_parsed and crel not in reachable_tex:
                    queue.append(crel)

    referenced_graphic_refs: list[str] = []
    for rel in sorted(reachable_tex):
        for gm in _GRAPHIC_RE.finditer(code_joined_map[rel]):
            gref = gm.group(1).strip()
            if gref:
                referenced_graphic_refs.append(gref)

    unused_image_rels: set[str] = set()
    for img in image_files:
        rel = img.relative_to(tex_dir).as_posix()
        if not any(_match_graphic_ref(rel, gref, graphicspaths) for gref in referenced_graphic_refs):
            unused_image_rels.add(rel)
            msg = f"Image {rel} is not referenced via \\includegraphics"
            if prune_unused:
                msg += " (pruned from --strip-comments-out)"
            findings.append({
                "severity": "WARN",
                "check": "arxiv/unused-figure",
                "file": rel,
                "message": msg,
            })

    unused_tex_rels: set[str] = set()
    if len(tex_files) > 1:
        for rel in sorted(tex_parsed.keys()):
            if rel not in reachable_tex:
                unused_tex_rels.add(rel)
                msg = f"Secondary .tex file {rel} is not referenced via \\input/\\include"
                if prune_unused:
                    msg += " (pruned from --strip-comments-out)"
                findings.append({
                    "severity": "WARN",
                    "check": "arxiv/unused-tex",
                    "file": rel,
                    "message": msg,
                })

    stripped_dir: str | None = None
    pruned_files: list[str] = []
    if out_root is not None:
        out_root.mkdir(parents=True, exist_ok=True)
        if prune_unused:
            for child in list(out_root.iterdir()):
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        prune_set = (unused_image_rels | unused_tex_rels) if prune_unused else set()
        for p in safe_files:
            rel_path = p.relative_to(tex_dir)
            rel_posix = rel_path.as_posix()
            if rel_posix in prune_set:
                pruned_files.append(rel_posix)
                continue
            dest = out_root / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            if p.suffix.lower() == ".tex":
                dest.write_text(_strip_comments_text(p.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
            else:
                shutil.copy2(p, dest)
        stripped_dir = str(out_root)

    counts = {s: sum(1 for x in findings if x["severity"] == s) for s in ("ERROR", "WARN")}
    out_payload: dict[str, Any] = {
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
    if prune_unused:
        out_payload["pruned_files"] = sorted(pruned_files)
    return out_payload


# ---------------------------------------------------------------------------
# 3. BibTeX Verifier & rebiber protect_title_caps
# ---------------------------------------------------------------------------

def _is_fully_outer_braced(s: str) -> bool:
    if len(s) < 2 or not (s.startswith("{") and s.endswith("}")):
        return False
    depth = 0
    i = 0
    n = len(s)
    while i < n:
        if s[i] == "\\" and i + 1 < n:
            i += 2
            continue
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return i == n - 1
        i += 1
    return False


def _split_brace_segments(word: str) -> list[tuple[bool, str]]:
    """Split word into (is_braced, text) segments; never wraps existing {...} groups."""
    segs: list[tuple[bool, str]] = []
    i = 0
    n = len(word)
    buf: list[str] = []
    while i < n:
        if word[i] == "\\" and i + 1 < n:
            buf.append(word[i : i + 2])
            i += 2
            continue
        if word[i] == "{":
            if buf:
                segs.append((False, "".join(buf)))
                buf = []
            end_pos, ok = _skip_balanced_group(word, i, "{", "}")
            if not ok:
                segs.append((False, word[i:]))
                return segs
            segs.append((True, word[i:end_pos]))
            i = end_pos
            continue
        buf.append(word[i])
        i += 1
    if buf:
        segs.append((False, "".join(buf)))
    return segs


def _protect_atomic_token(word: str) -> str:
    if not word or _is_fully_outer_braced(word):
        return word
    core = word.strip(",:;.?!")
    if not core:
        return word
    if core in _AI_ACRONYMS:
        lead = word[: len(word) - len(word.lstrip(",:;.\"'("))]
        trail = word[len(word.rstrip(",:;.\"')")) :]
        mid = word[len(lead) : len(word) - len(trail) if trail else len(word)]
        if mid and not _is_fully_outer_braced(mid):
            return f"{lead}{{{mid}}}{trail}"
        return word

    needs_brace = False
    if any(c.isdigit() for c in core) and any(c.isalpha() for c in core):
        needs_brace = True
    elif sum(1 for c in core if c.isupper()) >= 2:
        needs_brace = True
    elif any(c.isupper() for c in core[1:]):
        needs_brace = True

    if not needs_brace:
        return word
    lead = word[: len(word) - len(word.lstrip(",:;.\"'("))]
    trail = word[len(word.rstrip(",:;.\"')")) :]
    mid = word[len(lead) : len(word) - len(trail) if trail else len(word)]
    if mid and not _is_fully_outer_braced(mid):
        return f"{lead}{{{mid}}}{trail}"
    return word


def _protect_unbraced_seg(seg: str, *, split_hyphen: bool) -> str:
    if not seg or "{" in seg or "\\" in seg:
        return seg
    if "/" in seg:
        return "/".join(_protect_unbraced_seg(part, split_hyphen=split_hyphen) for part in seg.split("/"))
    if "--" in seg:
        return "--".join(_protect_unbraced_seg(part, split_hyphen=split_hyphen) for part in seg.split("--"))
    if split_hyphen and "-" in seg:
        return "-".join(_protect_atomic_token(part) for part in seg.split("-"))
    return _protect_atomic_token(seg)


def _protect_token(word: str) -> str:
    if not word or _is_fully_outer_braced(word):
        return word
    if "{" in word:
        if "\\" in word:
            return word
        segs = _split_brace_segments(word)
        out_parts: list[str] = []
        for is_braced, seg in segs:
            if is_braced or "{" in seg or "\\" in seg or seg == word:
                out_parts.append(seg)
            else:
                out_parts.append(_protect_unbraced_seg(seg, split_hyphen=True))
        return "".join(out_parts)
    return _protect_unbraced_seg(word, split_hyphen=False)


def protect_title_caps(title: str) -> str:
    """Adapt yuchenlin/rebiber protect_title_caps: protect acronyms/mixed-case tokens without {{...}}."""
    if not isinstance(title, str):
        raise ValueError("title must be a string")
    if _is_fully_outer_braced(title):
        return title
    parts = re.split(r"(\s+)", title)
    return "".join(part if (not part or part.isspace()) else _protect_token(part) for part in parts)


def _skip_balanced_group(text: str, open_pos: int, open_ch: str, close_ch: str) -> tuple[int, bool]:
    n = len(text)
    pos = open_pos + 1
    depth = 1
    while pos < n and depth > 0:
        ch = text[pos]
        if ch == "\\" and pos + 1 < n:
            pos += 2
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
        pos += 1
    return pos, depth == 0


def _has_balanced_closing_quote(
    buf: str,
    start: int,
    limit: int,
    init_depth: int,
    terminators: tuple[str, ...],
    *,
    stop_at_entry: bool = False,
) -> tuple[bool, int]:
    d = init_depth
    p = start
    while p < limit:
        c = buf[p]
        if c == "\\" and p + 1 < limit:
            p += 2
            continue
        if c == "{":
            d += 1
        elif c == "}":
            if d > 0:
                d -= 1
            else:
                return False, -1
        elif c == '"' and d == 0:
            nx = p + 1
            while nx < limit and buf[nx] in " \t\r\n":
                nx += 1
            if nx >= limit or buf[nx] in terminators:
                return True, p
        elif stop_at_entry and c == "@" and d == 0:
            if _BIB_ENTRY_START_RE.match(buf, p):
                return False, -1
        p += 1
    return False, -1


class _BibQuoteOracle:
    """Linear-time O(N) precomputed index answering _has_balanced_closing_quote queries in O(log N)."""

    def __init__(
        self,
        buf: str,
        limit: int,
        terminators: tuple[str, ...],
        *,
        stop_at_entry: bool = False,
    ) -> None:
        self.limit = limit
        self.bal_at = [0] * (limit + 1)
        self.close_by_bal: dict[int, list[int]] = {}
        self.events_by_bal: dict[int, list[tuple[int, int]]] = {}
        bal = 0
        p = 0
        while p < limit:
            self.bal_at[p] = bal
            c = buf[p]
            if c == "\\" and p + 1 < limit:
                p += 2
                continue
            if c == "{":
                bal += 1
            elif c == "}":
                self.events_by_bal.setdefault(bal, []).append((p, -1))
                bal -= 1
                self.close_by_bal.setdefault(bal, []).append(p)
            elif c == '"':
                nx = p + 1
                while nx < limit and buf[nx] in " \t\r\n":
                    nx += 1
                if nx >= limit or buf[nx] in terminators:
                    self.events_by_bal.setdefault(bal, []).append((p, p))
            elif stop_at_entry and c == "@":
                if _BIB_ENTRY_START_RE.match(buf, p):
                    self.events_by_bal.setdefault(bal, []).append((p, -1))
            p += 1
        self.bal_at[limit] = bal

    def query(self, start: int, init_depth: int) -> tuple[bool, int]:
        if start >= self.limit:
            return False, -1
        target_bal = self.bal_at[start] - init_depth
        if init_depth > 0:
            closes = self.close_by_bal.get(target_bal)
            if not closes:
                return False, -1
            idx = bisect.bisect_left(closes, start)
            if idx >= len(closes):
                return False, -1
            q0 = closes[idx] + 1
        else:
            q0 = start
        events = self.events_by_bal.get(target_bal)
        if not events:
            return False, -1
        eidx = bisect.bisect_left(events, (q0, -1))
        if eidx >= len(events):
            return False, -1
        _epos, res_pos = events[eidx]
        return (True, res_pos) if res_pos >= 0 else (False, -1)


def _query_balanced_closing_quote(
    buf: str,
    start: int,
    limit: int,
    init_depth: int,
    terminators: tuple[str, ...],
    *,
    stop_at_entry: bool = False,
    oracle_state: dict[str, Any] | None = None,
) -> tuple[bool, int]:
    if oracle_state is None:
        return _has_balanced_closing_quote(
            buf, start, limit, init_depth, terminators, stop_at_entry=stop_at_entry
        )
    oracle: _BibQuoteOracle | None = oracle_state.get("oracle")
    if oracle is None:
        calls = oracle_state.get("calls", 0) + 1
        oracle_state["calls"] = calls
        if calls < 2:
            return _has_balanced_closing_quote(
                buf, start, limit, init_depth, terminators, stop_at_entry=stop_at_entry
            )
        oracle = _BibQuoteOracle(buf, limit, terminators, stop_at_entry=stop_at_entry)
        oracle_state["oracle"] = oracle
    return oracle.query(start, init_depth)


def _skip_entry_group(
    text: str,
    open_pos: int,
    open_ch: str,
    close_ch: str,
    *,
    _oracle_state: dict[str, Any] | None = None,
) -> tuple[int, bool]:
    n = len(text)
    pos = open_pos + 1
    brace_depth = 1 if open_ch == "{" else 0
    paren_depth = 1 if open_ch == "(" else 0
    top_brace = brace_depth
    top_paren = paren_depth
    in_quote = False
    q_brace = 0
    verified_quote_pos = -1
    state = _oracle_state if _oracle_state is not None else {"calls": 0, "oracle": None}
    while pos < n:
        ch = text[pos]
        if ch == "\\" and pos + 1 < n:
            pos += 2
            continue
        if in_quote:
            if ch == "{":
                q_brace += 1
            elif ch == "}" and q_brace > 0:
                q_brace -= 1
            elif ch == '"':
                if q_brace == 0:
                    in_quote = False
                    verified_quote_pos = -1
                else:
                    nxt = pos + 1
                    while nxt < n and text[nxt] in " \t\r\n":
                        nxt += 1
                    if nxt >= n or text[nxt] in (",", close_ch, "#"):
                        if pos < verified_quote_pos:
                            pass
                        else:
                            ok_q, close_q_pos = _query_balanced_closing_quote(
                                text,
                                pos + 1,
                                n,
                                q_brace,
                                (",", close_ch, "#"),
                                stop_at_entry=True,
                                oracle_state=state,
                            )
                            if ok_q:
                                verified_quote_pos = close_q_pos
                            else:
                                in_quote = False
                                q_brace = 0
                                verified_quote_pos = -1
            pos += 1
            continue
        if ch == '"' and brace_depth == top_brace and paren_depth == top_paren:
            in_quote = True
            q_brace = 0
            verified_quote_pos = -1
        elif ch == "{":
            brace_depth += 1
        elif ch == "}":
            if brace_depth > 0:
                brace_depth -= 1
                if open_ch == "{" and brace_depth == 0:
                    return pos + 1, True
        elif ch == "(":
            if brace_depth == top_brace:
                paren_depth += 1
        elif ch == ")":
            if brace_depth == top_brace and paren_depth > 0:
                paren_depth -= 1
                if open_ch == "(" and paren_depth == 0:
                    return pos + 1, True
        pos += 1
    return pos, False


def _parse_bibtex_with_errors(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(text, str):
        raise ValueError("BibTeX input must be a string")
    entries: list[dict[str, Any]] = []
    errors: list[str] = []
    strings: dict[str, str] = {}
    entry_oracle_states: dict[str, dict[str, Any]] = {}
    i = 0
    n = len(text)

    while i < n:
        at = text.find("@", i)
        if at == -1:
            break
        hm = _BIB_ENTRY_START_RE.match(text, at)
        if not hm:
            i = at + 1
            continue
        etype = hm.group(1).lower()
        open_ch = hm.group(2)
        close_ch = "}" if open_ch == "{" else ")"
        open_pos = hm.end() - 1
        if etype in {"comment", "preamble"}:
            end_pos, balanced = _skip_balanced_group(text, open_pos, open_ch, close_ch)
        else:
            o_state = entry_oracle_states.setdefault(close_ch, {"calls": 0, "oracle": None})
            end_pos, balanced = _skip_entry_group(
                text, open_pos, open_ch, close_ch, _oracle_state=o_state
            )
        if not balanced:
            errors.append(f"Unclosed BibTeX @{etype} entry starting at offset {at}")
            break
        raw_inner = text[open_pos + 1 : end_pos - 1]
        i = end_pos

        if etype in {"comment", "preamble"}:
            continue
        if etype == "string":
            sm = re.match(r"\s*([A-Za-z0-9_-]+)\s*=\s*(.+)$", raw_inner.strip(), re.S)
            if sm:
                sname = sm.group(1).lower()
                sval = sm.group(2).strip()
                if (sval.startswith("{") and sval.endswith("}")) or (sval.startswith('"') and sval.endswith('"')):
                    sval = sval[1:-1]
                strings[sname] = " ".join(sval.split())
            continue

        km = re.match(r"\s*([^,\s{}()]*)\s*,([\s\S]*)$", raw_inner)
        if not km:
            errors.append(f"Malformed BibTeX @{etype} entry missing comma after key")
            continue
        key = km.group(1).strip()
        if not key:
            errors.append(f"Malformed BibTeX @{etype} entry missing citation key")
            continue
        body = km.group(2)

        fields: dict[str, str] = {}
        j = 0
        bn = len(body)
        entry_malformed = False
        body_oracle_state: dict[str, Any] = {"calls": 0, "oracle": None}
        while j < bn:
            while j < bn and body[j] in " \t\r\n,":
                j += 1
            if j >= bn:
                break
            fm = _BIB_FIELD_NAME_RE.match(body, j)
            if not fm:
                errors.append(f"Malformed field syntax in entry '{key}'")
                entry_malformed = True
                break
            fname = fm.group(1).lower()
            k = fm.end()
            if k >= bn:
                errors.append(f"Missing value for field '{fname}' in entry '{key}'")
                entry_malformed = True
                break
            if body[k] == "{":
                end_v, ok_v = _skip_balanced_group(body, k, "{", "}")
                if not ok_v:
                    errors.append(f"Unclosed braced field '{fname}' in entry '{key}'")
                    entry_malformed = True
                    break
                val = body[k + 1 : end_v - 1]
                k = end_v
            elif body[k] == '"':
                k += 1
                vs = k
                bdepth = 0
                closed_q = False
                verified_quote_pos = -1
                while k < bn:
                    ch = body[k]
                    if ch == "\\" and k + 1 < bn:
                        k += 2
                        continue
                    if ch == "{":
                        bdepth += 1
                    elif ch == "}" and bdepth > 0:
                        bdepth -= 1
                    elif ch == '"':
                        if bdepth == 0:
                            closed_q = True
                            break
                        nxt = k + 1
                        while nxt < bn and body[nxt] in " \t\r\n":
                            nxt += 1
                        if nxt >= bn or body[nxt] in (",", "#"):
                            if k < verified_quote_pos:
                                pass
                            else:
                                ok_q, close_q_pos = _query_balanced_closing_quote(
                                    body,
                                    k + 1,
                                    bn,
                                    bdepth,
                                    (",", "#"),
                                    oracle_state=body_oracle_state,
                                )
                                if ok_q:
                                    verified_quote_pos = close_q_pos
                                else:
                                    closed_q = True
                                    break
                    k += 1
                if not closed_q:
                    errors.append(f"Unclosed quoted field '{fname}' in entry '{key}'")
                    entry_malformed = True
                    break
                val = body[vs:k]
                k += 1
            else:
                vs = k
                while k < bn and body[k] not in ",\r\n":
                    k += 1
                val = body[vs:k].strip()
                if val.lower() in strings:
                    val = strings[val.lower()]
            fields[fname] = " ".join(val.split())
            j = k

        if not entry_malformed:
            entries.append({"type": etype, "key": key, "fields": fields})
    return entries, errors


def parse_bibtex(text: str) -> list[dict[str, Any]]:
    entries, _errors = _parse_bibtex_with_errors(text)
    return entries


def _norm_doi(raw_doi: str) -> str:
    d = raw_doi.strip()
    d = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", d, flags=re.I)
    d = re.sub(r"^doi:\s*", "", d, flags=re.I)
    return d.strip()


def _extract_arxiv_id(fields: dict[str, str], doi: str = "") -> str | None:
    eprint = fields.get("eprint", "").strip()
    arch = fields.get("archiveprefix", "").strip().lower()
    if eprint and (not arch or arch == "arxiv"):
        m = _ARXIV_ID_RE.search(eprint)
        if m:
            return m.group(1)
    for k in ("arxiv", "arxivid"):
        if fields.get(k):
            m = _ARXIV_ID_RE.search(fields[k])
            if m:
                return m.group(1)
    url = fields.get("url", "")
    if "arxiv.org" in url.lower():
        m = re.search(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+/\d{7}(?:v\d+)?)", url, re.I)
        if m:
            return m.group(1)
    if doi:
        m = re.match(r"^10\.48550/arxiv\.(\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+/\d{7}(?:v\d+)?)$", doi, re.I)
        if m:
            return m.group(1)
    return None


def _norm_title_cmp(s: str) -> str:
    clean = re.sub(r"[{}]", "", s.lower())
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", clean).split())


def _has_subtitle_prefix(shorter_raw: str, longer_raw: str, shorter_norm: str) -> bool:
    l_clean = " ".join(re.sub(r"[{}]", "", longer_raw).strip().lower().split())
    if not l_clean:
        return False
    words = shorter_norm.split()
    if not words:
        return False
    pat = r"^\s*" + r"[^a-z0-9]+".join(re.escape(w) for w in words) + r"\s*(?::|\u2014|\u2013|\s-\s)"
    return bool(re.match(pat, l_clean))


def _titles_match(bib_title: str, remote_title: str) -> bool:
    nb = _norm_title_cmp(bib_title)
    nr = _norm_title_cmp(remote_title)
    if not nb or not nr:
        return False
    if nb == nr:
        return True
    tb = nb.split()
    tr = nr.split()
    if not tb or not tr:
        return False
    union = set(tb) | set(tr)
    jac = len(set(tb) & set(tr)) / len(union)
    ratio = difflib.SequenceMatcher(None, nb, nr).ratio()
    if min(len(tb), len(tr)) >= 5 and (nr.startswith(nb + " ") or nb.startswith(nr + " ")):
        shorter_raw, longer_raw, shorter_norm = (
            (bib_title, remote_title, nb) if len(tb) <= len(tr) else (remote_title, bib_title, nr)
        )
        if (
            min(len(tb), len(tr)) / max(len(tb), len(tr)) >= 0.6
            and (_has_subtitle_prefix(shorter_raw, longer_raw, shorter_norm) or jac >= 0.85)
        ):
            return True
    return jac >= 0.82 and ratio >= 0.88


def _verify_doi_online(doi: str, title: str, year: str, *, api_base: str | None = None) -> list[str]:
    issues: list[str] = []
    norm_d = _norm_doi(doi)
    base = (api_base or os.environ.get("CROSSREF_API_BASE") or "https://api.crossref.org").rstrip("/")
    url = f"{base}/works/{urllib.parse.quote(norm_d)}"
    req = urllib.request.Request(url, headers={"User-Agent": "research-scientist-preflight/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace")).get("message", {})
        if not isinstance(data, dict):
            data = {}
        cr_titles = data.get("title") or []
        remote_title = str(cr_titles[0]).strip() if cr_titles else ""
        if title:
            if not remote_title:
                issues.append(f"DOI missing remote title in Crossref response for {doi}")
            elif not _titles_match(title, remote_title):
                issues.append(f"DOI title mismatch: bib={title[:50]!r} vs crossref={remote_title[:50]!r}")
        parts = (data.get("issued") or {}).get("date-parts") or [[]]
        issued = parts[0][0] if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0] else None
        if issued is not None and year.isdigit() and str(issued).isdigit() and abs(int(issued) - int(year)) > 1:
            issues.append(f"DOI year mismatch: bib={year} vs crossref={issued}")
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        issues.append(f"Online DOI check error for {doi}: {exc}")
    return issues


def _verify_arxiv_online(arxiv_id: str, title: str, year: str) -> tuple[bool, list[str]]:
    base = (os.environ.get("ARXIV_API_BASE") or "https://export.arxiv.org").rstrip("/")
    url = f"{base}/api/query?id_list={urllib.parse.quote(arxiv_id)}"
    req = urllib.request.Request(url, headers={"User-Agent": "research-scientist-preflight/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            xml_bytes = resp.read()
        root = ET.fromstring(xml_bytes)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall("atom:entry", ns)
        if not entries:
            entries = [el for el in root if el.tag.endswith("entry")]
        if not entries:
            return False, [f"arXiv ID {arxiv_id} not found"]
        ent = entries[0]
        title_el = ent.find("atom:title", ns)
        if title_el is None:
            title_el = next((c for c in ent if c.tag.endswith("title")), None)
        pub_el = ent.find("atom:published", ns)
        if pub_el is None:
            pub_el = next((c for c in ent if c.tag.endswith("published")), None)
        remote_title = " ".join((title_el.text or "").split()) if title_el is not None else ""
        if remote_title.lower() == "error":
            return False, [f"arXiv ID {arxiv_id} returned error entry"]
        issues: list[str] = []
        if title:
            if not remote_title:
                issues.append(f"arXiv entry {arxiv_id} missing <title>")
            elif not _titles_match(title, remote_title):
                issues.append(f"arXiv title mismatch: bib={title[:50]!r} vs arxiv={remote_title[:50]!r}")
        if pub_el is not None and pub_el.text and year.isdigit():
            ym = re.match(r"(\d{4})", pub_el.text.strip())
            if ym and abs(int(ym.group(1)) - int(year)) > 1:
                issues.append(f"arXiv year mismatch: bib={year} vs arxiv={ym.group(1)}")
        return True, issues
    except Exception as exc:
        return False, [f"Online arXiv check error for {arxiv_id}: {exc}"]


def _verify_openalex_online(doi: str, title: str, year: str) -> tuple[bool, list[str]]:
    base = (os.environ.get("OPENALEX_API_BASE") or "https://api.openalex.org").rstrip("/")
    if doi:
        norm_d = _norm_doi(doi)
        url = f"{base}/works/https://doi.org/{urllib.parse.quote(norm_d)}"
    elif title:
        url = f"{base}/works?search={urllib.parse.quote(title)}&per-page=3"
    else:
        return False, []
    req = urllib.request.Request(url, headers={"User-Agent": "research-scientist-preflight/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        if not isinstance(data, dict):
            return False, ["Invalid OpenAlex response"]
        works = data.get("results") if "results" in data else [data]
        if not isinstance(works, list) or not works:
            return False, [f"OpenAlex record not found for {doi or title[:40]}"]
        # Match best work if searching by title
        best = works[0]
        if title:
            for w in works:
                if isinstance(w, dict) and _titles_match(title, str(w.get("title") or w.get("display_name") or "")):
                    best = w
                    break
        remote_title = str(best.get("title") or best.get("display_name") or "").strip()
        remote_year = best.get("publication_year")
        issues: list[str] = []
        if title:
            if not remote_title:
                issues.append("OpenAlex record missing title")
            elif not _titles_match(title, remote_title):
                issues.append(f"OpenAlex title mismatch: bib={title[:50]!r} vs openalex={remote_title[:50]!r}")
        if remote_year is not None and year.isdigit() and str(remote_year).isdigit() and abs(int(remote_year) - int(year)) > 1:
            issues.append(f"OpenAlex year mismatch: bib={year} vs openalex={remote_year}")
        return True, issues
    except Exception as exc:
        return False, [f"Online OpenAlex check error for {doi or title[:30]}: {exc}"]


def _verify_entry_online(fields: dict[str, str], title: str, year: str) -> list[str]:
    doi = fields.get("doi", "").strip()
    arxiv_id = _extract_arxiv_id(fields, _norm_doi(doi) if doi else "")
    has_oa_env = bool(os.environ.get("OPENALEX_API_BASE"))
    has_ax_env = bool(os.environ.get("ARXIV_API_BASE"))
    has_cr_env = bool(os.environ.get("CROSSREF_API_BASE"))

    if doi:
        issues = _verify_doi_online(doi, title, year)
        if not issues:
            return []
        # Preserve offline localhost CROSSREF_API_BASE test behavior unless arXiv/OpenAlex bases are explicitly configured
        if has_cr_env and not (has_oa_env or has_ax_env):
            return issues
        is_404_or_err = any("404" in i or "Online DOI check error" in i for i in issues)
        if is_404_or_err:
            if arxiv_id:
                ok_ax, ax_issues = _verify_arxiv_online(arxiv_id, title, year)
                if ok_ax:
                    return ax_issues
            ok_oa, oa_issues = _verify_openalex_online(doi, title, year)
            if ok_oa:
                return oa_issues
        return issues

    if arxiv_id:
        ok_ax, ax_issues = _verify_arxiv_online(arxiv_id, title, year)
        if ok_ax:
            return ax_issues
        if has_ax_env and not has_oa_env:
            return ax_issues
        ok_oa, oa_issues = _verify_openalex_online("", title, year)
        if ok_oa:
            return oa_issues
        return ax_issues

    if title:
        _ok_oa, oa_issues = _verify_openalex_online("", title, year)
        return oa_issues
    return []


def _has_balanced_braces(s: str) -> bool:
    depth = 0
    i = 0
    n = len(s)
    while i < n:
        if s[i] == "\\":
            if i + 1 >= n:
                return False
            i += 2
            continue
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth < 0:
                return False
        i += 1
    return depth == 0


def _format_bibtex_field_value(v: str) -> str:
    if _has_balanced_braces(v):
        return f"{{{v}}}"
    out: list[str] = []
    i = 0
    n = len(v)
    while i < n:
        ch = v[i]
        if ch == "\\" and i + 1 < n:
            out.append(v[i : i + 2])
            i += 2
            continue
        if ch == '"':
            out.append('\\"')
        else:
            out.append(ch)
        i += 1
    if out and out[-1] == "\\":
        out.append("\\")
    return '"' + "".join(out) + '"'


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
    entries, parse_errors = _parse_bibtex_with_errors(raw)
    if not entries:
        detail = f": {parse_errors[0]}" if parse_errors else ""
        raise ValueError(f"No valid BibTeX entries parsed in {bib_path}{detail}")

    findings: list[dict[str, Any]] = []
    for pe in parse_errors:
        findings.append({"severity": "ERROR", "check": "bibtex/malformed-entry", "key": "", "message": pe})

    seen_keys_lower: set[str] = set()
    bib_keys: set[str] = set()

    for ent in entries:
        key = ent["key"]
        etype = ent["type"]
        fields = ent["fields"]
        if key.lower() in seen_keys_lower:
            findings.append({"severity": "ERROR", "check": "bibtex/duplicate-key", "key": key, "message": f"Duplicate BibTeX key (case-insensitive): {key}"})
        seen_keys_lower.add(key.lower())
        bib_keys.add(key)

        for req in ("title", "author", "year"):
            val = fields.get(req, "").strip()
            stripped_val = re.sub(r"[{}~\s]+", "", val)
            if not val or not stripped_val:
                findings.append({"severity": "ERROR", "check": "bibtex/missing-field", "key": key, "message": f"Missing required field '{req}'"})
            elif re.fullmatch(r"(?:tbd|todo|unknown|n/?a|placeholder|et\s*al\.?|true|false|null|none)", stripped_val, re.I):
                findings.append({"severity": "ERROR", "check": "bibtex/placeholder-field", "key": key, "message": f"Suspicious boolean/placeholder in '{req}': {val}"})

        year = fields.get("year", "").strip()
        if year and not re.fullmatch(r"(?:19|20)\d{2}", year):
            findings.append({"severity": "ERROR", "check": "bibtex/invalid-year", "key": key, "message": f"Invalid year format: {year}"})

        if etype == "inproceedings" and not re.sub(r"[{}~\s]+", "", fields.get("booktitle", "")):
            findings.append({"severity": "ERROR", "check": "bibtex/missing-venue", "key": key, "message": "inproceedings missing 'booktitle'"})
        elif etype == "article" and not (
            re.sub(r"[{}~\s]+", "", fields.get("journal", "")) or re.sub(r"[{}~\s]+", "", fields.get("eprint", ""))
        ):
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

        if verify_online:
            for iss in _verify_entry_online(fields, title, year):
                findings.append({"severity": "ERROR", "check": "bibtex/online-mismatch", "key": key, "message": iss})

    if tex_path is not None:
        rows, tex_notes = _load_tex_flattened(tex_path)
        for note in tex_notes:
            if "unsafe \\input" in note:
                findings.append({"severity": "ERROR", "check": "bibtex/unsafe-input", "key": "", "message": note})
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
            body_lines = [f"  {k} = {_format_bibtex_field_value(v)}" for k, v in ent["fields"].items()]
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
    p_ax.add_argument("--prune-unused", action="store_true", help="Omit unused figures/.tex files when writing --strip-comments-out")
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
    p_bb.add_argument("--verify-online", action="store_true", help="Query Crossref / arXiv / OpenAlex APIs to verify entries")
    p_bb.add_argument("--strict", action="store_true", help="Treat warnings as failures (exit 1)")
    p_bb.add_argument("--out", help="Write full JSON output to PATH")
    p_bb.add_argument("--json", nargs="?", const="-", help="Emit JSON output")
    p_bb.add_argument("--compact", action="store_true", help="Bounded <4KB stdout summary")

    args = parser.parse_args(argv)
    try:
        if args.out is not None:
            _nonempty(args.out, "--out")
        if args.json is not None and args.json != "-":
            _nonempty(args.json, "--json")

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
            res = audit_arxiv_dir(td, max_image_mb=args.max_image_mb, strip_out=so, prune_unused=args.prune_unused)
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
