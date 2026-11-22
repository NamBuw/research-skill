#!/usr/bin/env python3
"""Artifact, license, PII, reproducibility, path, secret, and double-blind anonymization readiness checker.

Pure Python 3 stdlib. Outputs deterministic JSON (`artifact_readiness_v1`) wireable into
`evaluate_submission.py` (`ready_to_submit`, `ready_for_release`, `recommended_transparency_cap`).
"""
from __future__ import annotations

import argparse
import ast
import csv
import io
import json
import math
import os
import re
import sys
import tokenize
from pathlib import Path
from typing import Any

MAX_COMPACT_BYTES = 3800
MAX_FILE_BYTES = 2 * 1024 * 1024

SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "env",
    "node_modules", ".mypy_cache", ".pytest_cache", "build", "dist",
}
BINARY_EXTS = {
    ".pyc", ".pyo", ".so", ".dll", ".dylib", ".exe", ".bin", ".dat",
    ".pt", ".pth", ".ckpt", ".safetensors", ".onnx", ".pkl", ".pickle",
    ".npy", ".npz", ".parquet", ".arrow", ".png", ".jpg", ".jpeg", ".gif",
    ".webp", ".bmp", ".ico", ".svg", ".pdf", ".zip", ".tar", ".gz", ".bz2",
    ".xz", ".7z", ".whl", ".egg", ".woff", ".woff2", ".ttf", ".eot",
}
README_NAMES = {"readme", "readme.md", "readme.rst", "readme.txt", "readme.markdown"}
LICENSE_FILENAMES = {
    "license", "license.md", "license.txt", "license.rst",
    "licence", "licence.md", "licence.txt", "copying", "copying.md", "copying.txt",
}
ENV_FILES = {
    "requirements.txt": "pip requirements",
    "requirements-dev.txt": "pip requirements (dev)",
    "environment.yml": "conda environment",
    "environment.yaml": "conda environment",
    "conda.yml": "conda environment",
    "pyproject.toml": "PEP 621 / poetry project",
    "setup.py": "setuptools",
    "setup.cfg": "setuptools",
    "pipfile": "pipenv",
    "pipfile.lock": "pipenv lockfile (pinned)",
    "poetry.lock": "poetry lockfile (pinned)",
    "renv.lock": "R renv lockfile (pinned)",
    "uv.lock": "uv lockfile (pinned)",
    "dockerfile": "Docker image recipe",
    "containerfile": "OCI image recipe",
    "package.json": "npm package",
    "package-lock.json": "npm lockfile (pinned)",
}
LOCKFILES = {"pipfile.lock", "poetry.lock", "renv.lock", "uv.lock", "package-lock.json"}
ENTRYPOINT_FILES = {
    "makefile", "run.sh", "run.py", "main.py", "train.py", "evaluate.py",
    "eval.py", "reproduce.sh", "reproduce.py", "repro.sh", "experiment.py",
}
SOURCE_EXTS = {".py", ".sh", ".r", ".jl", ".ipynb"}
DATA_EXTS = {".csv", ".tsv", ".jsonl", ".json"}
DATA_DIR_NAMES = {"data", "datasets", "dataset"}
ANON_METADATA_FILES = {"citation.cff", "authors", "authors.md", "authors.txt", "notice", "notice.md", "notice.txt"}
TEMPLATE_ENV_NAMES = {".env.example", ".env.template", ".env.sample", ".env.dist"}

SEED_RE = re.compile(
    r"\brandom\.seed\s*\(|\bnp\.random\.seed\s*\(|\bnumpy\.random\.seed\s*\("
    r"|\bnp\.random\.default_rng\s*\(|\btorch\.manual_seed\s*\("
    r"|\btorch\.cuda\.manual_seed(?:_all)?\s*\(|\bset_seed\s*\("
    r"|\bseed_everything\s*\(|\bPYTHONHASHSEED\b|\bdeterministic\s*=\s*True",
    re.I,
)
MAIN_GUARD_RE = re.compile(r"if\s+__name__\s*==\s*['\"]__main__['\"]")
RESULTS_CMD_RE = re.compile(
    r"(reproduce|to\s+reproduce|^\s*(?:python|python3|bash|sh|make|\./run)\b)",
    re.I | re.M,
)
_FENCED_CMD_RE = re.compile(r"(?:\b(?:python|python3|bash|sh|make|docker\s+run)\b|\./)", re.I)

# License patterns
_LICENSE_PLACEHOLDER_RE = re.compile(
    r"^(?:tbd|todo|unknown|unspecified|none|n/?a|<license>|insert\s+license|\.\.\.|-+)$",
    re.I,
)
_HARD_PROPRIETARY_RE = re.compile(
    r"\b(?:proprietary|internal[- ]only|confidential|no[- ]redistribution|not\s+for\s+redistribution)\b",
    re.I,
)
_ALL_RIGHTS_RESERVED_RE = re.compile(r"\ball\s+rights\s+reserved\b", re.I)
_PROPRIETARY_RE = re.compile(
    r"\b(?:proprietary|all\s+rights\s+reserved|internal[- ]only|confidential|no[- ]redistribution|not\s+for\s+redistribution)\b",
    re.I,
)
_RAIL_RE = re.compile(
    r"\b(?:openrail|rail-?[ms]|creativeml-openrail|llama\s+community\s+license|llama-?2-?community|llama-?3-?community)\b",
    re.I,
)
_NON_COMMERCIAL_RE = re.compile(
    r"\bcc-by-nc(?:-[a-z]+)?\b|\bnon[- ]?commercial\b|\bresearch[- ]?only\b",
    re.I,
)
_STRONG_COPYLEFT_RE = re.compile(
    r"\b(?:a?gpl(?:-[23](?:\.0)?)?|gnu\s+(?:affero\s+)?general\s+public\s+license|cc-by-sa(?:-\d\.\d)?)\b",
    re.I,
)
_PERMISSIVE_RE = re.compile(
    r"\b(?:mit(?:\s+license)?|apache(?:[- ]2\.0)?|bsd(?:-\d-clause)?|isc|unlicense|cc0(?:-\d\.\d)?|cc-by(?:-\d\.\d)?)\b|"
    r"redistribution\s+and\s+use\s+in\s+source\s+and\s+binary\s+forms,\s+with\s+or\s+without\s+modification,\s+are\s+permitted|"
    r"permission\s+is\s+hereby\s+granted,\s+free\s+of\s+charge",
    re.I,
)
_KNOWN_LICENSE_RE = re.compile(
    r"\b(?:mit|apache|bsd|isc|unlicense|cc0|cc-by|gpl|agpl|lgpl|mpl|rail|openrail|proprietary|mozilla\s+public\s+license|eclipse\s+public\s+license|creative\s+commons)\b",
    re.I,
)

# PII patterns (linear-time, bounded)
_SSN_RE = re.compile(r"\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b")
_CARD_CAND_RE = re.compile(r"(?<![A-Za-z0-9_./-])(\d(?:[ -]?\d){12,18})(?![A-Za-z0-9_./-])")
_INTL_PHONE_RE = re.compile(r"(?<!\w)(\+\d{1,3}[-.\s]\(?\d{2,4}\)?[-.\s]\d{3,4}[-.\s]\d{4})\b")
_US_PHONE_PAREN_RE = re.compile(r"(\(\d{3}\)\s?\d{3}[-.\s]\d{4})\b")
_KEY_PHONE_RE = re.compile(
    r"(?i)\b(?:phone|tel|telephone|mobile|cell)(?:_number)?\s*[:=]\s*[\"']?(\+?\d[\d\s().-]{7,18}\d)[\"']?"
)
_EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+-])([A-Za-z0-9][A-Za-z0-9._%+-]{0,63}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})+)\b"
)
_ALLOW_EMAIL_RE = re.compile(
    r"(?:@example\.(?:com|org|net|edu)$|@(?:anon|anonymous|placeholder|localhost)\b|^anon)",
    re.I,
)
_IPV4_RE = re.compile(
    r"(?<![\dvV.])((?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3})(?![\d.])"
)
_SENSITIVE_FIELD_NAMES = {
    "ssn", "social_security", "social_security_number", "passport", "passport_number",
    "credit_card", "card_number", "cvv", "bank_account", "iban", "tax_id",
    "dob", "date_of_birth", "home_address", "street_address", "medical_record_number", "mrn",
}

# Local path patterns
_UNIX_HOME_RE = re.compile(r"(?<![A-Za-z0-9_:])/(?:home|Users)/([A-Za-z0-9_.-]+)(?:/[^\s\"'`<>)}\]]*)?")
_WIN_HOME_RE = re.compile(r"[A-Za-z]:\\+Users\\+([A-Za-z0-9_.-]+)(?:\\[^\s\"'`<>)}\]]*)?")
_FILE_URI_HOME_RE = re.compile(r"file:///(?:home|Users|[A-Za-z]:/Users)/([A-Za-z0-9_.-]+)", re.I)
_GENERIC_USERS = {"user", "username", "yourname", "your_name", "you", "anon", "anonymous"}

# Secret patterns (linear-time)
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai", re.compile(r"\b(sk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,})\b")),
    ("anthropic", re.compile(r"\b(sk-ant-[A-Za-z0-9_-]{20,})\b")),
    ("huggingface", re.compile(r"\b(hf_[A-Za-z0-9]{20,})\b")),
    ("aws_key_id", re.compile(r"\b((?:AKIA|ASIA|AROA|AIDA)[0-9A-Z]{16})\b")),
    ("aws_secret", re.compile(r"(?i)\baws_secret_access_key\s*[:=]\s*[\"']([A-Za-z0-9/+=]{20,})[\"']")),
    ("github", re.compile(r"\b((?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")),
    ("gcp", re.compile(r"\b(AIza[0-9A-Za-z_-]{30,})\b")),
    ("slack", re.compile(r"\b(xox[baprs]-[0-9A-Za-z-]{10,})\b")),
    ("pypi", re.compile(r"\b(pypi-AgEIcHlwaS5vcmc[A-Za-z0-9_-]{10,})\b")),
    ("stripe_wandb", re.compile(r"\b([sr]k_live_[A-Za-z0-9]{16,}|wandb_v1_[A-Za-z0-9_]{20,})\b")),
    ("private_key", re.compile(r"(-----BEGIN [A-Z0-9 ]{0,30}PRIVATE KEY-----)")),
)
_GENERIC_SECRET_ASSIGN_RE = re.compile(
    r"(?i)\b(?:OPENAI_API_KEY|HF_TOKEN|HUGGINGFACE_TOKEN|S2_API_KEY|ANTHROPIC_API_KEY|"
    r"WANDB_API_KEY|GITHUB_TOKEN|GITLAB_TOKEN|API_KEY|SECRET_KEY|ACCESS_TOKEN|AUTH_TOKEN)\s*[:=]\s*[\"']([^\"'\n]{16,})[\"']"
)
_SECRET_PLACEHOLDER_RE = re.compile(
    r"^(?:your[_-]|placeholder|example|changeme|replace[_-]?me|dummy|test[_-]|sample[_-]|<[^>]+>|x{4,}|\*{4,}|0{6,})",
    re.I,
)

# Anonymization patterns
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
_URL_RE = re.compile(r"(?:https?://|www\.)[^\s{}\\]+", re.I)
_TILDE_USER_RE = re.compile(r"https?://[^\s/]+/~[A-Za-z0-9_.-]+", re.I)
_ACK_GRANT_RE = re.compile(
    r"(?i)(?:^\s*#{1,6}\s*acknowledg(?:e)?ments?\b|\b(?:funded|supported)\s+by\b|\bgrant\s+(?:no\.?|number|id|#)\b|\backnowledg(?:e)?ments?\s*:)"
)
_COPYRIGHT_NAME_RE = re.compile(r"(?i)copyright\s*(?:\(c\)|©)?\s*(?:19|20)\d{2}(?:\s*-\s*(?:19|20)\d{2})?\s+([^\n,;]+)")


def _reject_nonfinite(tok: str) -> Any:
    raise ValueError(f"Non-finite JSON constant not allowed: {tok}")


def _err(msg: str) -> int:
    print(json.dumps({"error": msg}), file=sys.stderr)
    return 2


def _validate_nonempty_str(val: Any, flag: str) -> str:
    if not isinstance(val, str) or not val.strip():
        raise ValueError(f"Empty or invalid value for {flag}")
    return val.strip()


def _mask_secret(token: str) -> str:
    s = str(token).strip()
    if len(s) <= 8:
        return "****"
    if "PRIVATE KEY" in s:
        return "-----BEGIN **** PRIVATE KEY-----"
    return f"{s[:4]}****{s[-4:]}"


def _mask_pii(kind: str, val: str) -> str:
    s = str(val).strip()
    if kind == "ssn":
        return f"***-**-{s[-4:]}" if len(s) >= 4 else "***-**-****"
    if kind == "card":
        digits = re.sub(r"\D", "", s)
        return f"****-****-****-{digits[-4:]}" if len(digits) >= 4 else "****"
    if kind == "phone":
        digits = re.sub(r"\D", "", s)
        return f"***-***-{digits[-4:]}" if len(digits) >= 4 else "***-****"
    if kind == "email" and "@" in s:
        local, dom = s.split("@", 1)
        return f"{local[:1]}***@{dom[:1]}***"
    if kind == "ip":
        parts = s.split(".")
        return f"x.x.x.{parts[-1]}" if len(parts) == 4 else "x.x.x.x"
    return "[REDACTED]"


def _luhn_ok(digits: str) -> bool:
    if not (13 <= len(digits) <= 19) or not digits.isdigit():
        return False
    if len(set(digits)) == 1:
        return False
    if digits in "01234567890123456789" or digits in "98765432109876543210":
        return False
    total = 0
    rev = digits[::-1]
    for idx, ch in enumerate(rev):
        d = int(ch)
        if idx % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (total % 10) == 0


def _is_public_ipv4(ip_str: str) -> bool:
    parts = [int(p) for p in ip_str.split(".")]
    a, b, c, d = parts
    if a in (0, 10, 127, 255):
        return False
    if a == 192 and b == 168:
        return False
    if a == 172 and 16 <= b <= 31:
        return False
    if a == 169 and b == 254:
        return False
    if a == 192 and b == 0 and c == 2:
        return False
    if a == 198 and b == 51 and c == 100:
        return False
    if a == 203 and b == 0 and c == 113:
        return False
    if a >= 224:
        return False
    return True


def _extract_url_host(url: str) -> str:
    low = url.lower()
    if low.startswith("www."):
        low = "http://" + low
    after = low.split("://", 1)[1] if "://" in low else low
    host = after.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0].split(":", 1)[0]
    return host.lstrip("www.")


def _host_matches(host: str, targets: tuple[str, ...]) -> bool:
    if not host:
        return False
    if host in targets or any(host.endswith("." + t) for t in targets):
        return True
    if "onedrive" in host.split("."):
        return True
    return False


def _is_identifying_url(url: str) -> bool:
    host = _extract_url_host(url)
    if any(host == ah or host.endswith("." + ah) for ah in _ANON_OK_HOSTS):
        return False
    if _host_matches(host, _IDENTITY_HOSTS):
        return True
    if _TILDE_USER_RE.match(url):
        return True
    if re.search(r"(?:\.edu|\.ac\.[a-z]{2})$", host, re.I):
        return True
    return False


def _strip_hash_comments(text: str, *, escape_single_quotes: bool = True) -> str:
    out_lines: list[str] = []
    for line in text.splitlines():
        quote: str | None = None
        i = 0
        cut = len(line)
        while i < len(line):
            ch = line[i]
            if quote is None:
                if ch in ("'", '"'):
                    quote = ch
                elif ch == "#":
                    cut = i
                    break
            else:
                if ch == "\\" and (quote == '"' or (quote == "'" and escape_single_quotes)) and i + 1 < len(line):
                    i += 2
                    continue
                if ch == quote:
                    quote = None
            i += 1
        out_lines.append(line[:cut])
    return "\n".join(out_lines)


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
        if not isinstance(node, ast.Expr):
            continue
        val = node.value
        is_str_doc = isinstance(val, ast.Constant) and isinstance(val.value, str)
        is_const_fstr = isinstance(val, ast.JoinedStr) and not any(
            isinstance(part, ast.FormattedValue) for part in val.values
        )
        if is_str_doc or is_const_fstr:
            s_row = val.lineno
            if 1 <= s_row <= n_lines:
                s_col = _utf8_byte_col_to_char_col(lines[s_row - 1], val.col_offset)
                starts.add((s_row, s_col))
                e_row = getattr(val, "end_lineno", None)
                e_byte_col = getattr(val, "end_col_offset", None)
                if isinstance(e_row, int) and isinstance(e_byte_col, int) and 1 <= e_row <= n_lines:
                    e_col = _utf8_byte_col_to_char_col(lines[e_row - 1], e_byte_col)
                    ranges.append(((s_row, s_col), (e_row, e_col)))
    return starts, ranges


def _strip_python_comments_and_docstrings(text: str) -> str:
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    lines = io.StringIO(text).readlines()
    if not lines:
        return ""
    out_chars = [list(ln) for ln in lines]
    doc_starts: set[tuple[int, int]] = set()
    doc_ranges: list[tuple[tuple[int, int], tuple[int, int]]] = []
    parsed = False
    try:
        tree = ast.parse(text)
        doc_starts, doc_ranges = _collect_docstring_spans(tree, lines)
        parsed = True
    except SyntaxError:
        parsed = False

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

    tok_ok = False
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                _blank_span(tok.start, tok.end)
            elif tok.type == tokenize.STRING and tok.start in doc_starts:
                _blank_span(tok.start, tok.end)
        tok_ok = True
    except (tokenize.TokenError, IndentationError):
        tok_ok = False

    cleaned = "".join("".join(row) for row in out_chars)
    if not parsed and not tok_ok:
        return _strip_hash_comments(cleaned, escape_single_quotes=True)
    return cleaned


def _extract_executable_code_from_text(text: str, suf: str) -> str:
    if suf == ".py":
        return _strip_python_comments_and_docstrings(text)
    if suf == ".ipynb":
        try:
            nb = json.loads(text)
        except json.JSONDecodeError:
            return ""
        if not isinstance(nb, dict) or not isinstance(nb.get("cells"), list):
            return ""
        chunks: list[str] = []
        for cell in nb["cells"]:
            if not isinstance(cell, dict) or cell.get("cell_type") != "code":
                continue
            src = cell.get("source", "")
            cell_text = "".join(str(x) for x in src) if isinstance(src, list) else (src if isinstance(src, str) else "")
            if not cell_text:
                continue
            cell_text = cell_text.lstrip("\ufeff")
            py_lines: list[str] = []
            for ln in cell_text.splitlines():
                st = ln.lstrip()
                if st.startswith(("%", "!")):
                    indent = ln[: len(ln) - len(st)]
                    py_lines.append(f"{indent}pass")
                else:
                    py_lines.append(ln)
            chunks.append(_strip_python_comments_and_docstrings("\n".join(py_lines)))
        return "\n".join(chunks)
    if suf == ".sh":
        return _strip_hash_comments(text, escape_single_quotes=False)
    if suf in {".r", ".jl"}:
        return _strip_hash_comments(text, escape_single_quotes=True)
    return text


def _extract_ipynb_all_text(text: str) -> str:
    try:
        nb = json.loads(text)
    except json.JSONDecodeError:
        return text
    if not isinstance(nb, dict) or not isinstance(nb.get("cells"), list):
        return text
    parts: list[str] = []
    for cell in nb["cells"]:
        if not isinstance(cell, dict):
            continue
        src = cell.get("source", "")
        parts.append("".join(str(x) for x in src) if isinstance(src, list) else str(src))
        outs = cell.get("outputs")
        if isinstance(outs, list):
            for out in outs:
                if isinstance(out, dict):
                    for k in ("text", "data", "evalue"):
                        val = out.get(k)
                        if isinstance(val, str):
                            parts.append(val)
                        elif isinstance(val, list):
                            parts.extend(str(x) for x in val)
                        elif isinstance(val, dict):
                            for dv in val.values():
                                parts.append("".join(str(x) for x in dv) if isinstance(dv, list) else str(dv))
    return "\n".join(parts)


def _has_results_cmd(readme_text: str) -> bool:
    if not readme_text:
        return False
    if RESULTS_CMD_RE.search(readme_text):
        return True
    pos = 0
    while True:
        start = readme_text.find("```", pos)
        if start == -1:
            return False
        end = readme_text.find("```", start + 3)
        if end == -1:
            return False
        if _FENCED_CMD_RE.search(readme_text[start + 3 : end]):
            return True
        pos = end + 3


def _classify_license(text: str) -> str:
    s = text.strip()
    if not s or _LICENSE_PLACEHOLDER_RE.match(s):
        return "invalid"
    low = s.lower()
    if _HARD_PROPRIETARY_RE.search(low):
        return "proprietary"
    if _RAIL_RE.search(low):
        return "rail"
    if _NON_COMMERCIAL_RE.search(low):
        return "non_commercial"
    if _STRONG_COPYLEFT_RE.search(low):
        if "lgpl" in low and "agpl" not in low and re.search(r"\bgnu\s+lesser\b|\blgpl\b", low) and not re.search(r"(?<!l)gpl", low):
            return "lgpl"
        return "strong_copyleft"
    if "lgpl" in low:
        return "lgpl"
    if "mpl" in low or "mozilla public license" in low:
        return "weak_copyleft"
    if _PERMISSIVE_RE.search(low) or "the mit license" in low or "apache license" in low:
        return "permissive"
    if _KNOWN_LICENSE_RE.search(low):
        return "known_other"
    if _ALL_RIGHTS_RESERVED_RE.search(low):
        return "proprietary"
    return "unrecognized"


def _detect_license_name(text: str) -> str:
    low = text.lower()
    for pat, label in (
        (r"\bagpl[- ]?3\.0\b|\baffero\s+general\s+public\s+license\b", "agpl-3.0"),
        (r"\bgpl[- ]?3\.0\b|\bgpl[- ]?v3\b", "gpl-3.0"),
        (r"\bgpl[- ]?2\.0\b|\bgpl[- ]?v2\b", "gpl-2.0"),
        (r"\blgpl\b|\blesser\s+general\s+public\s+license\b", "lgpl"),
        (r"\bcc-by-nc-sa\b", "cc-by-nc-sa"),
        (r"\bcc-by-nc\b|\bnon[- ]?commercial\b", "cc-by-nc"),
        (r"\bcc-by-sa\b", "cc-by-sa"),
        (r"\bcc-by(?:-\d\.\d)?\b", "cc-by"),
        (r"\bcc0\b", "cc0"),
        (r"\bopenrail\b|\brail\b", "rail"),
        (r"\bapache[- ]?2\.0\b|\bapache\s+license\b", "apache-2.0"),
        (r"\bmit\b|\bpermission\s+is\s+hereby\s+granted,\s+free\s+of\s+charge\b", "mit"),
        (r"\bbsd[- ]?3\b|\bbsd[- ]?2\b|\bbsd\b|redistribution\s+and\s+use\s+in\s+source\s+and\s+binary\s+forms", "bsd"),
        (r"\bisc\b", "isc"),
        (r"\bunlicense\b", "unlicense"),
    ):
        if re.search(pat, low):
            return label
    first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return first_line[:48].lower() if first_line else "unknown"


def _validate_manifest_paths(manifest: dict[str, Any], repo_root: Path | None) -> None:
    def _check_val(val: Any, key_name: str) -> None:
        if not isinstance(val, str) or not val.strip():
            return
        s = val.strip()
        if s.startswith(("http://", "https://")):
            return
        p = Path(s)
        if ".." in p.parts:
            raise ValueError(f"Unsafe '..' path traversal in manifest field '{key_name}': {s}")
        if p.is_absolute():
            if repo_root is None or not p.resolve(strict=False).is_relative_to(repo_root):
                raise ValueError(f"Absolute path outside repository in manifest field '{key_name}': {s}")

    path_keys = {"path", "file", "local_path", "run_log_path", "artifact_path", "script_path", "license_file"}

    def _walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in path_keys:
                    _check_val(v, k)
                else:
                    _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(manifest)


def _flatten_manifest_strings(obj: Any, prefix: str = "") -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if isinstance(obj, str):
        if obj.strip():
            out.append((prefix or "manifest", obj))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            nxt = f"{prefix}.{k}" if prefix else str(k)
            out.extend(_flatten_manifest_strings(v, nxt))
    elif isinstance(obj, list):
        for idx, v in enumerate(obj):
            out.extend(_flatten_manifest_strings(v, f"{prefix}[{idx}]"))
    return out


def _inspect_sensitive_schema(rel: str, text: str) -> tuple[list[tuple[str, int | None]], bool]:
    """Return ([(field_name, line_no)], has_data_rows) for structured tabular/JSON data."""
    suf = Path(rel).suffix.lower()
    hits: list[tuple[str, int | None]] = []
    has_rows = False
    if suf in {".csv", ".tsv"}:
        delim = "\t" if suf == ".tsv" else ","
        try:
            reader = csv.reader(io.StringIO(text), delimiter=delim)
            rows = list(reader)
        except csv.Error:
            return hits, False
        if not rows:
            return hits, False
        headers = [h.strip().lower().replace(" ", "_") for h in rows[0]]
        has_rows = len(rows) > 1
        for h in headers:
            if h in _SENSITIVE_FIELD_NAMES:
                hits.append((h, 1))
        return hits, has_rows
    if suf == ".jsonl":
        lines = [ln for ln in text.splitlines() if ln.strip()]
        has_rows = len(lines) > 0
        seen: set[str] = set()
        for ln_no, ln in enumerate(lines[:200], start=1):
            try:
                obj = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                for k in obj.keys():
                    kl = str(k).strip().lower().replace(" ", "_")
                    if kl in _SENSITIVE_FIELD_NAMES and kl not in seen:
                        seen.add(kl)
                        hits.append((kl, ln_no))
        return hits, has_rows
    if suf == ".json":
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            return hits, False
        records: list[dict[str, Any]] = []
        if isinstance(obj, list):
            records = [x for x in obj if isinstance(x, dict)]
        elif isinstance(obj, dict):
            for k in ("data", "examples", "samples", "records", "rows", "items"):
                if isinstance(obj.get(k), list):
                    records.extend(x for x in obj[k] if isinstance(x, dict))
            if not records:
                records = [obj]
        has_rows = bool(records)
        seen_j: set[str] = set()
        for rec in records[:200]:
            for k in rec.keys():
                kl = str(k).strip().lower().replace(" ", "_")
                if kl in _SENSITIVE_FIELD_NAMES and kl not in seen_j:
                    seen_j.add(kl)
                    hits.append((kl, None))
        return hits, has_rows
    return hits, False


def check_readiness(
    repo_dir: str | Path | None = None,
    manifest: dict[str, Any] | str | Path | None = None,
    *,
    anonymous: bool = False,
    max_files: int = 2000,
) -> dict[str, Any]:
    if type(max_files) is not int or max_files < 1:
        raise ValueError("--max-files must be a positive integer >= 1")
    if repo_dir is None and manifest is None:
        raise ValueError("At least one of --repo-dir or --manifest is required")

    root: Path | None = None
    root_res: Path | None = None
    if repo_dir is not None:
        if isinstance(repo_dir, str) and not repo_dir.strip():
            raise ValueError("Empty value for --repo-dir")
        root = Path(repo_dir)
        if not root.exists() or not root.is_dir():
            raise FileNotFoundError(f"Repository directory not found: {root}")
        root_res = root.resolve()

    manifest_path_str: str | None = None
    manifest_res: Path | None = None
    manifest_obj: dict[str, Any] | None = None
    if manifest is not None:
        if isinstance(manifest, dict):
            manifest_obj = manifest
        else:
            if isinstance(manifest, str) and not manifest.strip():
                raise ValueError("Empty value for --manifest")
            mp = Path(manifest)
            if not mp.exists() or not mp.is_file():
                raise FileNotFoundError(f"Manifest file not found: {mp}")
            manifest_path_str = str(mp)
            manifest_res = mp.resolve()
            raw_m = mp.read_bytes()
            if b"\x00" in raw_m:
                raise ValueError(f"Manifest file contains binary NUL bytes: {mp}")
            parsed = json.loads(raw_m.decode("utf-8-sig"), parse_constant=_reject_nonfinite)
            if not isinstance(parsed, dict):
                raise ValueError("Manifest JSON root must be an object")
            manifest_obj = parsed
        _validate_manifest_paths(manifest_obj, root_res)

    findings: list[dict[str, Any]] = []
    seen_finding_keys: set[tuple[str, str, str, int | None]] = set()

    def _add(
        category: str,
        check_id: str,
        severity: str,
        file_rel: str | None,
        line_no: int | None,
        message: str,
        remediation: str,
    ) -> None:
        dedup_k = (category, check_id, file_rel or "", line_no)
        if dedup_k in seen_finding_keys:
            return
        seen_finding_keys.add(dedup_k)
        findings.append({
            "id": f"ART-{len(findings) + 1:03d}",
            "category": category,
            "check": check_id,
            "severity": severity,
            "file": file_rel,
            "line": line_no,
            "message": message,
            "remediation": remediation,
        })

    scanned_files = 0
    skipped_files = 0
    truncated = False

    # Reproducibility & license & metadata collectors
    readme_rel: str | None = None
    readme_depth = 10**9
    readme_text = ""
    license_files: list[tuple[str, str]] = []
    env_files: list[tuple[str, str]] = []
    pinned_deps = False
    entrypoints: list[str] = []
    seed_files: list[str] = []
    has_main_guard = False
    text_records: list[tuple[str, str, bool]] = []  # (rel, text, is_data_file)
    pyproject_meta: list[tuple[str, str]] = []
    package_json_meta: list[tuple[str, str]] = []

    if root is not None and root_res is not None:
        # Inspect .git & .git/config BEFORE skipping .git internals
        git_dir = root / ".git"
        if anonymous and git_dir.exists():
            _add(
                "anonymization",
                "anonymization/git-dir-present",
                "FAIL",
                ".git",
                None,
                ".git directory present in anonymous release bundle (may retain commit author history).",
                "Remove .git/ from anonymous artifact archive.",
            )
            git_cfg = git_dir / "config"
            if git_cfg.is_file() and not git_cfg.is_symlink():
                try:
                    cfg_txt = git_cfg.read_text(encoding="utf-8", errors="replace")
                    section = ""
                    for ln_no, ln in enumerate(cfg_txt.splitlines(), start=1):
                        st = ln.strip()
                        if st.startswith("[") and st.endswith("]"):
                            section = st.lower()
                            continue
                        if section.startswith("[remote") and re.match(r"url\s*=", st, re.I):
                            val = st.split("=", 1)[1].strip()
                            if not _ANON_OK_RE.search(val) and not any(ah in val.lower() for ah in _ANON_OK_HOSTS):
                                _add(
                                    "anonymization",
                                    "anonymization/git-remote-leak",
                                    "FAIL",
                                    ".git/config",
                                    ln_no,
                                    "Git remote URL in .git/config may reveal author identity.",
                                    "Strip .git/ directory before anonymous release.",
                                )
                        elif section.startswith("[user") and re.match(r"(?:name|email)\s*=", st, re.I):
                            val = st.split("=", 1)[1].strip()
                            if val and not _ANON_OK_RE.search(val):
                                _add(
                                    "anonymization",
                                    "anonymization/git-user-leak",
                                    "FAIL",
                                    ".git/config",
                                    ln_no,
                                    "Git [user] identity present in .git/config.",
                                    "Strip .git/ directory before anonymous release.",
                                )
                except OSError:
                    pass

        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dp = Path(dirpath)
            kept_dirs: list[str] = []
            for d in sorted(dirnames):
                d_path = dp / d
                if d in SKIP_DIRS:
                    continue
                if d_path.is_symlink():
                    try:
                        res_d = d_path.resolve(strict=True)
                        if not res_d.is_relative_to(root_res):
                            _add(
                                "local_paths",
                                "security/unsafe-symlink",
                                "FAIL",
                                d_path.relative_to(root).as_posix(),
                                None,
                                f"Symlink directory escapes repository root: {d}",
                                "Remove escaping symlink before artifact release.",
                            )
                    except OSError:
                        _add(
                            "local_paths",
                            "security/unsafe-symlink",
                            "FAIL",
                            d_path.relative_to(root).as_posix(),
                            None,
                            f"Broken symlink directory in repository: {d}",
                            "Remove broken symlink.",
                        )
                    continue
                kept_dirs.append(d)
            dirnames[:] = kept_dirs

            for fn in sorted(filenames):
                path = dp / fn
                rel = path.relative_to(root).as_posix()
                if path.is_symlink():
                    try:
                        res_p = path.resolve(strict=True)
                        if not res_p.is_relative_to(root_res):
                            _add(
                                "local_paths",
                                "security/unsafe-symlink",
                                "FAIL",
                                rel,
                                None,
                                f"Symlink file escapes repository root: {rel}",
                                "Replace escaping symlink with in-repo file or remove.",
                            )
                    except OSError:
                        _add(
                            "local_paths",
                            "security/unsafe-symlink",
                            "FAIL",
                            rel,
                            None,
                            f"Broken symlink in repository: {rel}",
                            "Remove broken symlink.",
                        )
                    skipped_files += 1
                    continue

                if scanned_files >= max_files:
                    truncated = True
                    skipped_files += 1
                    continue

                low = fn.lower()
                suf = path.suffix.lower()
                if suf in BINARY_EXTS:
                    skipped_files += 1
                    continue
                try:
                    st_size = path.stat().st_size
                except OSError:
                    skipped_files += 1
                    continue
                if st_size > MAX_FILE_BYTES:
                    skipped_files += 1
                    continue
                try:
                    raw_bytes = path.read_bytes()
                except OSError:
                    skipped_files += 1
                    continue
                if b"\x00" in raw_bytes:
                    skipped_files += 1
                    continue

                if manifest_res is not None:
                    try:
                        if path.resolve() == manifest_res:
                            continue
                    except OSError:
                        pass

                scanned_files += 1
                text = raw_bytes.decode("utf-8-sig", errors="replace")
                rel_depth = len(Path(rel).parts)
                is_data_file = (suf in DATA_EXTS) or any(part.lower() in DATA_DIR_NAMES for part in Path(rel).parts[:-1])

                if low in README_NAMES and (readme_rel is None or rel_depth < readme_depth):
                    readme_rel = rel
                    readme_depth = rel_depth
                    readme_text = text

                if rel_depth == 1 and (low in LICENSE_FILENAMES or low.startswith(("license", "licence", "copying"))):
                    license_files.append((rel, text))

                if low in ENV_FILES:
                    env_files.append((rel, ENV_FILES[low]))
                    if low in LOCKFILES:
                        pinned_deps = True

                if low == "pyproject.toml":
                    pyproject_meta.append((rel, text))
                elif low == "package.json":
                    package_json_meta.append((rel, text))

                if low in ENTRYPOINT_FILES:
                    entrypoints.append(rel)

                if suf in SOURCE_EXTS:
                    exec_code = _extract_executable_code_from_text(text, suf)
                    if SEED_RE.search(exec_code):
                        seed_files.append(rel)
                    if MAIN_GUARD_RE.search(exec_code):
                        has_main_guard = True

                scan_txt = _extract_ipynb_all_text(text) if suf == ".ipynb" else text
                text_records.append((rel, scan_txt, is_data_file))

                # Non-template .env file check
                if (low == ".env" or (low.startswith(".env.") and low not in TEMPLATE_ENV_NAMES)):
                    has_kv = any(
                        ln.strip() and not ln.lstrip().startswith("#") and "=" in ln
                        for ln in text.splitlines()
                    )
                    if has_kv:
                        _add(
                            "secrets",
                            "secrets/env-file-present",
                            "FAIL",
                            rel,
                            None,
                            f"Non-template environment file '{rel}' included in artifact bundle.",
                            "Remove .env files and provide .env.example with placeholders only.",
                        )

                if anonymous and low in ANON_METADATA_FILES and not _ANON_OK_RE.search(text):
                    _add(
                        "anonymization",
                        "anonymization/author-metadata",
                        "FAIL",
                        rel,
                        None,
                        f"Identity metadata file '{rel}' lacks anonymization marker.",
                        "Exclude or redact CITATION.cff / AUTHORS / NOTICE in anonymous release.",
                    )

    # ------------------------------------------------------------------
    # 1. License Declaration & Compatibility
    # ------------------------------------------------------------------
    intended_release = str(manifest_obj.get("intended_release", "public")).strip().lower() if manifest_obj else "public"
    repo_lic_class: str | None = None
    repo_lic_name: str | None = None
    repo_lic_file: str | None = None

    if license_files:
        repo_lic_file, lic_txt = license_files[0]
        repo_lic_class = _classify_license(lic_txt)
        repo_lic_name = _detect_license_name(lic_txt)
        if repo_lic_class == "invalid":
            _add(
                "license",
                "license/invalid-license",
                "FAIL",
                repo_lic_file,
                None,
                f"License file '{repo_lic_file}' is empty or contains a placeholder.",
                "Populate LICENSE with a valid SPDX open-source license text.",
            )
        elif repo_lic_class == "proprietary":
            sev = "WARN" if intended_release == "internal_restricted" else "FAIL"
            _add(
                "license",
                "license/proprietary-not-releasable",
                sev,
                repo_lic_file,
                None,
                f"License file '{repo_lic_file}' declares proprietary / non-releasable terms.",
                "Choose a releasable license or set intended_release='internal_restricted'.",
            )
        elif repo_lic_class == "unrecognized":
            _add(
                "license",
                "license/unrecognized-license",
                "WARN",
                repo_lic_file,
                None,
                f"License file '{repo_lic_file}' uses an unrecognized custom license requiring manual review.",
                "Use a standard SPDX license identifier (e.g., MIT, Apache-2.0) or verify legal terms.",
            )
        elif repo_lic_class == "rail":
            rail_doc = bool(manifest_obj and manifest_obj.get("rail_restrictions_documented") is True)
            if not rail_doc:
                _add(
                    "license",
                    "license/rail-use-restriction-notice",
                    "WARN",
                    repo_lic_file,
                    None,
                    "RAIL license carries behavioral use-restriction clauses; document restrictions in README/manifest.",
                    "Document RAIL use restrictions and set rail_restrictions_documented: true.",
                )
    else:
        meta_lic_raw: str | None = None
        meta_lic_file: str | None = None
        for rel, ptxt in pyproject_meta:
            m = re.search(r'(?m)^\s*license\s*=\s*(?:\{\s*text\s*=\s*)?["\']([^"\']+)["\']', ptxt)
            if m:
                meta_lic_raw = m.group(1).strip()
                meta_lic_file = rel
                break
        if meta_lic_raw is None:
            for rel, jtxt in package_json_meta:
                try:
                    pobj = json.loads(jtxt)
                    if isinstance(pobj, dict) and isinstance(pobj.get("license"), str):
                        meta_lic_raw = pobj["license"].strip()
                        meta_lic_file = rel
                        break
                except json.JSONDecodeError:
                    pass
        if meta_lic_raw is not None:
            repo_lic_class = _classify_license(meta_lic_raw)
            repo_lic_name = _detect_license_name(meta_lic_raw)
            repo_lic_file = meta_lic_file
            _add(
                "license",
                "license/missing-license-file",
                "WARN",
                meta_lic_file,
                None,
                f"License '{meta_lic_raw}' declared in {meta_lic_file}, but top-level LICENSE file is missing.",
                "Add a top-level LICENSE file matching the declared metadata license.",
            )
        elif manifest_obj and (isinstance(manifest_obj.get("code_license"), str) or isinstance(manifest_obj.get("license"), str)):
            m_lic = str(manifest_obj.get("code_license") or manifest_obj.get("license")).strip()
            repo_lic_class = _classify_license(m_lic)
            repo_lic_name = _detect_license_name(m_lic)
            if repo_lic_class == "invalid":
                _add(
                    "license",
                    "license/invalid-license",
                    "FAIL",
                    manifest_path_str,
                    None,
                    "Manifest declares empty or placeholder code license.",
                    "Specify a valid license (e.g., MIT, Apache-2.0).",
                )
            elif repo_lic_class == "proprietary":
                sev = "WARN" if intended_release == "internal_restricted" else "FAIL"
                _add(
                    "license",
                    "license/proprietary-not-releasable",
                    sev,
                    manifest_path_str,
                    None,
                    "Manifest declares proprietary code license.",
                    "Use a releasable license or set intended_release='internal_restricted'.",
                )
            elif root is not None:
                _add(
                    "license",
                    "license/missing-license-file",
                    "WARN",
                    None,
                    None,
                    f"Code license '{m_lic}' declared in manifest, but top-level LICENSE file is missing in repo.",
                    "Add a top-level LICENSE file to the repository.",
                )
        else:
            _add(
                "license",
                "license/missing-license",
                "FAIL",
                None,
                None,
                "No LICENSE file or license metadata found in repository or manifest.",
                "Add a top-level LICENSE file (e.g., MIT, Apache-2.0) before release.",
            )

    if repo_lic_class == "non_commercial" and intended_release == "commercial":
        _add(
            "license",
            "license/non-commercial-conflict",
            "FAIL",
            repo_lic_file or manifest_path_str,
            None,
            f"Non-commercial repository license ({repo_lic_name or 'non-commercial'}) conflicts with intended_release='commercial'.",
            "Use a commercially compatible license or change intended_release from 'commercial'.",
        )
    if manifest_obj and (isinstance(manifest_obj.get("code_license"), str) or isinstance(manifest_obj.get("license"), str)):
        m_code_lic = str(manifest_obj.get("code_license") or manifest_obj.get("license")).strip()
        m_code_class = _classify_license(m_code_lic)
        if m_code_class == "non_commercial" and intended_release == "commercial":
            _add(
                "license",
                "license/non-commercial-conflict",
                "FAIL",
                manifest_path_str or repo_lic_file,
                None,
                f"Manifest code license '{m_code_lic}' is non-commercial and conflicts with intended_release='commercial'.",
                "Use a commercially compatible code license or change intended_release from 'commercial'.",
            )

    assets_checked = 0
    if manifest_obj:
        asset_groups = (
            ("datasets", manifest_obj.get("datasets")),
            ("pretrained_models", manifest_obj.get("pretrained_models")),
            ("models", manifest_obj.get("models")),
            ("dependencies", manifest_obj.get("dependencies")),
        )
        for group_name, items in asset_groups:
            if not isinstance(items, list):
                continue
            for idx, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                assets_checked += 1
                aname = str(item.get("name") or item.get("id") or f"{group_name}[{idx}]")
                alic = item.get("license")
                redist = item.get("redistribution_allowed")
                bundled = item.get("bundled") is True or item.get("released") is True
                if not isinstance(alic, str) or _classify_license(alic) == "invalid":
                    _add(
                        "license",
                        "license/undeclared-asset-license",
                        "FAIL",
                        manifest_path_str,
                        None,
                        f"Asset '{aname}' ({group_name}) has missing or unknown license.",
                        "Declare the exact upstream SPDX/model license for every dataset/model/dependency.",
                    )
                    continue
                aclass = _classify_license(alic)
                if redist is False or (aclass == "proprietary" and (bundled or intended_release != "internal_restricted")):
                    _add(
                        "license",
                        "license/restricted-asset-redistribution",
                        "FAIL",
                        manifest_path_str,
                        None,
                        f"Asset '{aname}' prohibits redistribution or uses proprietary license '{alic}'.",
                        "Remove bundled asset and document external download instructions only if permitted.",
                    )
                elif aclass == "non_commercial":
                    if repo_lic_class == "permissive" or intended_release == "commercial":
                        _add(
                            "license",
                            "license/non-commercial-conflict",
                            "FAIL",
                            manifest_path_str,
                            None,
                            f"Non-commercial asset '{aname}' ({alic}) conflicts with permissive/commercial release ({repo_lic_name or intended_release}).",
                            "Restrict release scope to academic/non-commercial or replace asset.",
                        )
                    else:
                        _add(
                            "license",
                            "license/non-commercial-restriction",
                            "WARN",
                            manifest_path_str,
                            None,
                            f"Asset '{aname}' ({alic}) carries non-commercial use restrictions.",
                            "Ensure release documentation preserves non-commercial restrictions.",
                        )
                elif aclass == "strong_copyleft":
                    if repo_lic_class == "permissive":
                        _add(
                            "license",
                            "license/copyleft-incompatibility",
                            "FAIL",
                            manifest_path_str,
                            None,
                            f"Strong copyleft asset/dependency '{aname}' ({alic}) is incompatible with permissive repo license ({repo_lic_name}).",
                            "Align repo license with copyleft terms or replace copyleft dependency.",
                        )
                elif aclass == "rail":
                    rail_doc = bool(item.get("rail_restrictions_documented") is True or manifest_obj.get("rail_restrictions_documented") is True)
                    if not rail_doc:
                        _add(
                            "license",
                            "license/rail-use-restriction-notice",
                            "WARN",
                            manifest_path_str,
                            None,
                            f"Asset '{aname}' ({alic}) uses RAIL restrictions requiring downstream notice.",
                            "Include RAIL behavioral use-restriction notice in README/manifest.",
                        )
                elif aclass == "unrecognized":
                    _add(
                        "license",
                        "license/unrecognized-license",
                        "WARN",
                        manifest_path_str,
                        None,
                        f"Asset '{aname}' uses unrecognized license '{alic}' requiring manual legal review.",
                        "Verify exact license compatibility manually.",
                    )

    # ------------------------------------------------------------------
    # 2. Reproducibility (Seeds, Dependencies, Entrypoint, README)
    # ------------------------------------------------------------------
    if not pinned_deps:
        for rel, _ in env_files:
            if root is None:
                continue
            p = root / rel
            low = p.name.lower()
            try:
                body = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if low.startswith("requirements") and p.suffix.lower() == ".txt":
                for line in body.splitlines():
                    code_line = line.split("#", 1)[0].strip()
                    if code_line and re.search(r"(==|@|https?://|git\+)", code_line):
                        pinned_deps = True
                        break
            elif low in {"environment.yml", "environment.yaml", "conda.yml"}:
                if re.search(r"(?:==|=[^=\s]+)", body):
                    pinned_deps = True
            elif low == "pyproject.toml":
                if re.search(r"==\s*[0-9]", body):
                    pinned_deps = True
            if pinned_deps:
                break

    manifest_repro = manifest_obj.get("reproducibility", {}) if isinstance(manifest_obj and manifest_obj.get("reproducibility"), dict) else {}
    manifest_runs = manifest_obj.get("runs", []) if isinstance(manifest_obj and manifest_obj.get("runs"), list) else []
    manifest_has_seed = (
        manifest_repro.get("deterministic") is True
        or manifest_repro.get("seed") is not None
        or any(isinstance(r, dict) and r.get("seed") is not None for r in manifest_runs)
    )
    manifest_has_env = bool(
        manifest_repro.get("lockfile")
        or manifest_repro.get("dependencies")
        or (manifest_obj and manifest_obj.get("dependencies"))
    )
    manifest_has_pinned = bool(manifest_repro.get("lockfile") or manifest_repro.get("pinned_dependencies") is True)
    manifest_has_ep = bool(manifest_repro.get("entrypoint"))

    if root is not None:
        if not seed_files:
            _add(
                "reproducibility",
                "reproducibility/missing-seed",
                "FAIL",
                None,
                None,
                "No executable deterministic seed-setting found (comments/docstrings ignored).",
                "Set random/numpy/torch seeds in executable training/evaluation code.",
            )
        if not env_files:
            _add(
                "reproducibility",
                "reproducibility/missing-dependency-spec",
                "FAIL",
                None,
                None,
                "No dependency specification file (requirements.txt, pyproject.toml, environment.yml, or lockfile) found.",
                "Add pinned requirements.txt or lockfile (uv.lock / poetry.lock).",
            )
        elif not pinned_deps:
            _add(
                "reproducibility",
                "reproducibility/unpinned-dependencies",
                "WARN",
                env_files[0][0],
                None,
                f"Dependency file '{env_files[0][0]}' lacks exact version pins (==) or lockfile.",
                "Pin exact package versions (==) or include uv.lock/poetry.lock.",
            )
        if not entrypoints and not has_main_guard:
            _add(
                "reproducibility",
                "reproducibility/missing-entrypoint",
                "FAIL",
                None,
                None,
                "No reproducible entrypoint script (run.sh/train.py/main.py/Makefile or __main__ guard) found.",
                "Provide a single runnable reproduction script or __main__ entrypoint.",
            )
        if readme_rel is None:
            _add(
                "reproducibility",
                "reproducibility/missing-readme",
                "FAIL",
                None,
                None,
                "No README file found in repository.",
                "Add README.md documenting environment setup and exact reproduction commands.",
            )
        elif not _has_results_cmd(readme_text):
            _add(
                "reproducibility",
                "reproducibility/missing-run-instructions",
                "WARN",
                readme_rel,
                None,
                f"'{readme_rel}' does not document explicit CLI commands to reproduce results.",
                "Add exact reproduction commands (e.g., `python3 run.py` or `bash reproduce.sh`) to README.",
            )
    else:
        # --manifest only mode
        if not manifest_has_seed:
            _add(
                "reproducibility",
                "reproducibility/missing-seed",
                "FAIL",
                manifest_path_str,
                None,
                "Manifest lacks deterministic seed metadata in runs[] or reproducibility.",
                "Record fixed seeds in manifest runs[].seed or reproducibility.seed.",
            )
        if not manifest_has_env:
            _add(
                "reproducibility",
                "reproducibility/missing-dependency-spec",
                "FAIL",
                manifest_path_str,
                None,
                "Manifest lacks dependency/lockfile specification.",
                "Add reproducibility.lockfile or dependencies metadata.",
            )
        elif not manifest_has_pinned:
            _add(
                "reproducibility",
                "reproducibility/unpinned-dependencies",
                "WARN",
                manifest_path_str,
                None,
                "Manifest dependency specification lacks explicit lockfile or pinned versions.",
                "Add a lockfile or pin exact dependency versions.",
            )
        if not manifest_has_ep:
            _add(
                "reproducibility",
                "reproducibility/missing-entrypoint",
                "FAIL",
                manifest_path_str,
                None,
                "Manifest lacks reproducibility.entrypoint.",
                "Specify reproducibility.entrypoint command/script.",
            )

    # ------------------------------------------------------------------
    # 3. Text Scanning: PII, Local Paths, Secrets, Anonymization
    # ------------------------------------------------------------------
    manifest_authors: list[str] = []
    if anonymous and manifest_obj:
        for k in ("authors", "author", "affiliations", "affiliation", "institution", "institutions", "maintainers", "organization"):
            val = manifest_obj.get(k)
            if isinstance(val, str) and len(val.strip()) >= 4:
                manifest_authors.append(val.strip())
            elif isinstance(val, list):
                for elem in val:
                    if isinstance(elem, str) and len(elem.strip()) >= 4:
                        manifest_authors.append(elem.strip())
                    elif isinstance(elem, dict):
                        for dk in ("name", "affiliation", "institution"):
                            dv = elem.get(dk)
                            if isinstance(dv, str) and len(dv.strip()) >= 4:
                                manifest_authors.append(dv.strip())

    author_res = [
        (au, re.compile(rf"(?<!\w){re.escape(au)}(?!\w)", re.I))
        for au in dict.fromkeys(manifest_authors)
        if not _ANON_OK_RE.search(au)
    ]

    scan_items: list[tuple[str, str, bool]] = list(text_records)
    if manifest_obj:
        for mkey, mval in _flatten_manifest_strings(manifest_obj):
            # Do not flag manifest's own author field against itself, only scan paths/secrets/PII in manifest
            scan_items.append((f"{manifest_path_str or 'manifest'}#{mkey}", mval, mkey.startswith("datasets")))

    for rel, txt, is_data_file in scan_items:
        is_manifest_item = "#" in rel and (manifest_path_str is None or rel.startswith(manifest_path_str))
        # Structured sensitive column/field names
        if not is_manifest_item and Path(rel).suffix.lower() in DATA_EXTS:
            field_hits, has_rows = _inspect_sensitive_schema(rel, txt)
            for fname, fline in field_hits:
                _add(
                    "pii",
                    "pii/sensitive-data-field",
                    "FAIL" if has_rows else "WARN",
                    rel,
                    fline,
                    f"Sensitive PII field '{fname}' detected in data artifact.",
                    "Remove or anonymize sensitive PII columns before releasing data.",
                )

        # Line-by-line scan for PII, local paths, secrets, anonymization
        for ln_no, line in enumerate(txt.splitlines(), start=1):
            if not line.strip():
                continue

            # SSNs
            for m in _SSN_RE.finditer(line):
                _add(
                    "pii",
                    "pii/ssn-detected",
                    "FAIL",
                    rel,
                    ln_no,
                    f"Potential SSN detected (redacted: {_mask_pii('ssn', m.group(0))}).",
                    "Remove SSNs from repository and data files.",
                )

            # Credit card numbers (Luhn validated)
            if not re.search(r"\b(?:doi|arxiv|sha256|run_id)\b", line, re.I):
                for m in _CARD_CAND_RE.finditer(line):
                    digits = re.sub(r"\D", "", m.group(1))
                    if _luhn_ok(digits):
                        _add(
                            "pii",
                            "pii/credit-card-detected",
                            "FAIL",
                            rel,
                            ln_no,
                            f"Potential credit card number detected (redacted: {_mask_pii('card', digits)}).",
                            "Remove payment card numbers immediately.",
                        )

            # Phone numbers
            phone_matches: list[str] = []
            for pat in (_INTL_PHONE_RE, _US_PHONE_PAREN_RE, _KEY_PHONE_RE):
                for m in pat.finditer(line):
                    ph = m.group(1)
                    if re.search(r"\b555[-.\s]?01\d{2}\b", ph):
                        continue
                    phone_matches.append(ph)
            if phone_matches:
                _add(
                    "pii",
                    "pii/phone-detected",
                    "FAIL" if is_data_file else "WARN",
                    rel,
                    ln_no,
                    f"Potential phone number detected (redacted: {_mask_pii('phone', phone_matches[0])}).",
                    "Remove or mask personal phone numbers.",
                )

            # Emails (in data files -> pii; in --anonymous -> anonymization)
            if "@" in line:
                for m in _EMAIL_RE.finditer(line):
                    em = m.group(1)
                    if _ALLOW_EMAIL_RE.search(em):
                        continue
                    if is_data_file:
                        _add(
                            "pii",
                            "pii/email-in-data",
                            "FAIL",
                            rel,
                            ln_no,
                            f"Non-placeholder email address in data file (redacted: {_mask_pii('email', em)}).",
                            "Scrub personal/user email addresses from dataset files.",
                        )
                    if anonymous and not is_manifest_item:
                        _add(
                            "anonymization",
                            "anonymization/email-leak",
                            "FAIL",
                            rel,
                            ln_no,
                            f"Non-anonymous email address leaks author/contact identity (redacted: {_mask_pii('email', em)}).",
                            "Replace real emails with example.org or omit for double-blind review.",
                        )

            # Public IPv4
            for m in _IPV4_RE.finditer(line):
                ip_s = m.group(1)
                if _is_public_ipv4(ip_s):
                    _add(
                        "pii",
                        "pii/public-ip-address",
                        "WARN",
                        rel,
                        ln_no,
                        f"Public IPv4 address detected (redacted: {_mask_pii('ip', ip_s)}).",
                        "Verify IP is non-sensitive documentation or replace with RFC 5737 test IP (192.0.2.x).",
                    )

            # Hardcoded local user paths
            url_spans = [(um.start(), um.end()) for um in _URL_RE.finditer(line)]
            for pat in (_UNIX_HOME_RE, _WIN_HOME_RE, _FILE_URI_HOME_RE):
                for m in pat.finditer(line):
                    if pat is _UNIX_HOME_RE and any(s <= m.start() < e for s, e in url_spans):
                        continue
                    uname = m.group(1)
                    if uname.lower() in _GENERIC_USERS:
                        continue
                    _add(
                        "local_paths",
                        "local_paths/hardcoded-user-path",
                        "FAIL",
                        rel,
                        ln_no,
                        f"Hardcoded local user directory path references username '{uname}'.",
                        "Replace machine-specific home paths with relative paths or environment variables.",
                    )
                    if anonymous and not is_manifest_item:
                        _add(
                            "anonymization",
                            "anonymization/home-path-leak",
                            "FAIL",
                            rel,
                            ln_no,
                            f"Local home path leaks username '{uname}' in anonymous bundle.",
                            "Replace hardcoded user paths with relative repository paths.",
                        )

            # Secrets / API keys
            for skind, spat in _SECRET_PATTERNS:
                for m in spat.finditer(line):
                    tok = m.group(1)
                    if _SECRET_PLACEHOLDER_RE.match(tok):
                        continue
                    _add(
                        "secrets",
                        "secrets/api-key-detected",
                        "FAIL",
                        rel,
                        ln_no,
                        f"Potential {skind} secret/token detected (redacted: {_mask_secret(tok)}).",
                        "Revoke leaked credential and load secrets strictly from environment variables.",
                    )
            if "os.environ" not in line and "os.getenv" not in line:
                for m in _GENERIC_SECRET_ASSIGN_RE.finditer(line):
                    val = m.group(1).strip()
                    if _SECRET_PLACEHOLDER_RE.match(val):
                        continue
                    _add(
                        "secrets",
                        "secrets/api-key-detected",
                        "FAIL",
                        rel,
                        ln_no,
                        f"Hardcoded secret/API key assignment detected (redacted: {_mask_secret(val)}).",
                        "Move secrets to runtime environment variables (os.environ.get).",
                    )

            # Anonymization checks (URLs, manifest author names, acknowledgments, copyright)
            if anonymous and not is_manifest_item:
                for um in _URL_RE.finditer(line):
                    url = um.group(0).rstrip(".,;)]\"'")
                    if _is_identifying_url(url):
                        _add(
                            "anonymization",
                            "anonymization/identifying-url",
                            "FAIL",
                            rel,
                            ln_no,
                            f"Identifying URL leaks author/org host: {_extract_url_host(url)}",
                            "Use anonymous.4open.science or redact institutional/personal URLs.",
                        )
                for au, areg in author_res:
                    if areg.search(line):
                        _add(
                            "anonymization",
                            "anonymization/author-name-leak",
                            "FAIL",
                            rel,
                            ln_no,
                            "Manifest author/affiliation identifier appears in repository file.",
                            "Remove author names and institutional affiliations for double-blind review.",
                        )
                if _ACK_GRANT_RE.search(line) and not _ANON_OK_RE.search(line):
                    _add(
                        "anonymization",
                        "anonymization/acknowledgments",
                        "FAIL",
                        rel,
                        ln_no,
                        "Acknowledgments or funding/grant disclosure lacks anonymization.",
                        "Omit or redact acknowledgments and grant IDs during double-blind review.",
                    )
                if Path(rel).name.lower().startswith(("license", "licence")):
                    cm = _COPYRIGHT_NAME_RE.search(line)
                    if cm and not _ANON_OK_RE.search(cm.group(1)):
                        _add(
                            "anonymization",
                            "anonymization/author-metadata",
                            "FAIL",
                            rel,
                            ln_no,
                            "LICENSE copyright holder line exposes non-anonymous identity.",
                            "Redact copyright holder to 'Anonymous Authors' for double-blind bundle.",
                        )

    # Check pyproject.toml / package.json / setup.cfg author/url fields in --anonymous mode
    if anonymous and root is not None:
        for rel, ptxt in pyproject_meta:
            for ln_no, ln in enumerate(ptxt.splitlines(), start=1):
                if re.match(r"^\s*(?:authors?|maintainers?|homepage|repository)\s*=", ln, re.I):
                    if not _ANON_OK_RE.search(ln) and not any(ah in ln.lower() for ah in _ANON_OK_HOSTS):
                        _add(
                            "anonymization",
                            "anonymization/author-metadata",
                            "FAIL",
                            rel,
                            ln_no,
                            f"Package metadata in '{rel}' contains non-anonymous author/URL field.",
                            "Anonymize or remove author/repository metadata in pyproject.toml.",
                        )
        for rel, jtxt in package_json_meta:
            try:
                pobj = json.loads(jtxt)
            except json.JSONDecodeError:
                continue
            if isinstance(pobj, dict):
                for fk in ("author", "authors", "maintainers", "contributors", "homepage", "repository"):
                    fv = pobj.get(fk)
                    if fv and not _ANON_OK_RE.search(json.dumps(fv)) and not any(ah in json.dumps(fv).lower() for ah in _ANON_OK_HOSTS):
                        _add(
                            "anonymization",
                            "anonymization/author-metadata",
                            "FAIL",
                            rel,
                            None,
                            f"Package metadata '{fk}' in '{rel}' exposes non-anonymous identity.",
                            "Redact author/repository metadata in package.json.",
                        )

    # Build category summaries
    categories = ("license", "pii", "reproducibility", "local_paths", "secrets", "anonymization")
    by_category: dict[str, dict[str, Any]] = {}
    for cat in categories:
        if cat == "anonymization" and not anonymous:
            by_category[cat] = {"status": "SKIPPED", "fail": 0, "warn": 0}
            continue
        cat_f = [f for f in findings if f["category"] == cat]
        cf = sum(1 for f in cat_f if f["severity"] == "FAIL")
        cw = sum(1 for f in cat_f if f["severity"] == "WARN")
        cst = "FAIL" if cf > 0 else ("WARN" if cw > 0 else "PASS")
        by_category[cat] = {"status": cst, "fail": cf, "warn": cw}

    fail_count = sum(1 for f in findings if f["severity"] == "FAIL")
    warn_count = sum(1 for f in findings if f["severity"] == "WARN")
    info_count = sum(1 for f in findings if f["severity"] == "INFO")

    verdict = "FAIL" if fail_count > 0 else ("WARN" if warn_count > 0 else "PASS")
    ready = verdict != "FAIL"
    cap = 3 if verdict == "FAIL" else (5 if verdict == "WARN" else None)

    blocking_reasons = sorted(
        {
            f"{f['check']}:{f['file']}" if f.get("file") else f["check"]
            for f in findings
            if f["severity"] == "FAIL"
        }
    )
    warnings_list = sorted(
        {
            f"{f['check']}:{f['file']}" if f.get("file") else f["check"]
            for f in findings
            if f["severity"] == "WARN"
        }
    )

    checks_detail: dict[str, Any] = {
        "license": {
            "status": by_category["license"]["status"],
            "repo_license": repo_lic_name,
            "license_file": repo_lic_file,
            "assets_checked": assets_checked,
        },
        "pii": {"status": by_category["pii"]["status"]},
        "reproducibility": {
            "status": by_category["reproducibility"]["status"],
            "seed_files": seed_files[:20],
            "env_files": [rel for rel, _ in env_files[:20]],
            "deps_pinned": pinned_deps or manifest_has_pinned,
            "entrypoints": entrypoints[:20],
            "readme": readme_rel,
            "results_cmd": _has_results_cmd(readme_text) if readme_rel else False,
        },
        "local_paths": {"status": by_category["local_paths"]["status"]},
        "secrets": {"status": by_category["secrets"]["status"]},
        "anonymization": {
            "status": by_category["anonymization"]["status"],
            "enabled": bool(anonymous),
        },
    }

    return {
        "schema": "artifact_readiness_v1",
        "status": verdict,
        "verdict": verdict,
        "ready_to_submit": ready,
        "ready_for_release": ready,
        "recommended_transparency_cap": cap,
        "repo_dir": str(root) if root is not None else None,
        "manifest_path": manifest_path_str,
        "anonymous": bool(anonymous),
        "blocking_reasons": blocking_reasons,
        "warnings": warnings_list,
        "summary": {
            "total_findings": len(findings),
            "fail_count": fail_count,
            "warn_count": warn_count,
            "info_count": info_count,
            "errors": fail_count,
            "warnings": warn_count,
            "files_scanned": scanned_files,
            "skipped_files": skipped_files,
            "by_category": by_category,
        },
        "checks": checks_detail,
        "findings": findings,
        "scanned_files": scanned_files,
        "skipped_files": skipped_files,
        "truncated": truncated,
    }


def _build_compact_payload(payload: dict[str, Any], out_path: str | None) -> dict[str, Any]:
    compact: dict[str, Any] = {
        "compact": True,
        "schema": payload["schema"],
        "status": payload["status"],
        "verdict": payload["verdict"],
        "ready_to_submit": payload["ready_to_submit"],
        "ready_for_release": payload["ready_for_release"],
        "recommended_transparency_cap": payload["recommended_transparency_cap"],
        "blocking_reasons": list(payload["blocking_reasons"]),
        "warnings": list(payload["warnings"]),
        "summary": payload["summary"],
        "error_count": payload["summary"]["fail_count"],
        "warning_count": payload["summary"]["warn_count"],
        "artifact_path": out_path,
        "out": out_path,
    }
    raw = json.dumps(compact, separators=(",", ":"))
    if len(raw.encode("utf-8")) <= MAX_COMPACT_BYTES:
        return compact

    for cap in (10, 5, 2, 1, 0):
        compact["blocking_reasons"] = payload["blocking_reasons"][:cap]
        compact["warnings"] = payload["warnings"][:cap]
        raw = json.dumps(compact, separators=(",", ":"))
        if len(raw.encode("utf-8")) <= MAX_COMPACT_BYTES:
            return compact

    compact["summary"] = {
        "total_findings": payload["summary"]["total_findings"],
        "fail_count": payload["summary"]["fail_count"],
        "warn_count": payload["summary"]["warn_count"],
        "files_scanned": payload["summary"]["files_scanned"],
    }
    return compact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-dir", help="Repository or artifact directory to scan")
    parser.add_argument("--manifest", help="Optional artifact/dataset/model manifest JSON path")
    parser.add_argument("--anonymous", action="store_true", help="Enable strict double-blind anonymization leak checks")
    parser.add_argument("--strict", action="store_true", help="Exit 1 on WARN as well as FAIL")
    parser.add_argument("--out", help="Write full JSON report to path")
    parser.add_argument("--compact", action="store_true", help="Emit bounded compact JSON summary (< 4096 bytes)")
    parser.add_argument("--max-files", type=int, default=2000, help="Maximum repository files to scan (default: 2000)")
    args = parser.parse_args(argv)

    try:
        if args.repo_dir is not None:
            _validate_nonempty_str(args.repo_dir, "--repo-dir")
        if args.manifest is not None:
            _validate_nonempty_str(args.manifest, "--manifest")
        out_str: str | None = None
        if args.out is not None:
            out_str = _validate_nonempty_str(args.out, "--out")

        payload = check_readiness(
            repo_dir=args.repo_dir,
            manifest=args.manifest,
            anonymous=args.anonymous,
            max_files=args.max_files,
        )
        if out_str is not None:
            op = Path(out_str)
            op.parent.mkdir(parents=True, exist_ok=True)
            op.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            payload["artifact_path"] = str(op)
            payload["out"] = str(op)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return _err(str(exc))

    if args.compact:
        compact_out = _build_compact_payload(payload, out_str)
        print(json.dumps(compact_out, separators=(",", ":")))
    else:
        print(json.dumps(payload, indent=2))

    if payload["verdict"] == "FAIL":
        return 1
    if args.strict and payload["verdict"] == "WARN":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
