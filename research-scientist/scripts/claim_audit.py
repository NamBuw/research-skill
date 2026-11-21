#!/usr/bin/env python3
"""Audit skill documentation (SKILL.md, references/*.md, optional README.md) against
actual bundled scripts, AST-verified CLI flags, API hosts/services, and Status tables.

Attribution & License Notice:
- Adapted from `kalaris-research-agent-skills/tools/claim_audit.py` and `tools/common.py`
  (MIT License, Copyright (c) 2026 Kalaris Labs).
- Modified for `research-scientist` to operate purely on Python 3.13 stdlib (no PyYAML),
  index `scripts/` and `modules/**/scripts/`, inspect `argparse` AST definitions, support
  multi-line `\\`-continued commands, and check `| Status |` / `| Disposition |` tables.
"""

from __future__ import annotations

import argparse
import ast
import json
import posixpath
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_EXTS = (".py", ".sh", ".js", ".R", ".r")
GENERIC_HOSTS = frozenset({
    "github.com",
    "example.org",
    "example.com",
    "youruni.edu",
    "university.edu",
    "uni.edu",
})

HOST_RE = re.compile(
    r"(?<![\w.-])((?:[a-z0-9-]+\.)+(?:org|com|gov|io|net|edu|ac\.uk|eu|ai|cc))\b",
    re.I,
)
QUERY_SENTENCE_RE = re.compile(
    r"(?:^|(?<=[.?!\n]))[^.?!\n]*\b(?:quer(?:y|ies)|search(?:es)?|fetch(?:es)?|retriev(?:e|es))\b[^.?!\n]*",
    re.I,
)

SERVICES: dict[str, tuple[str, ...]] = {
    "europe pmc": ("www.ebi.ac.uk/europepmc", "europepmc.org"),
    "semantic scholar": ("api.semanticscholar.org", "semanticscholar.org"),
    "openalex": ("api.openalex.org", "openalex.org"),
    "crossref": ("api.crossref.org", "crossref.org"),
    "arxiv": ("export.arxiv.org", "arxiv.org"),
    "pubmed": ("eutils.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov"),
    "dblp": ("dblp.org",),
    "acl anthology": ("aclanthology.org",),
    "huggingface": ("huggingface.co",),
    "scite": ("api.scite.ai", "scite.ai"),
    "unpaywall": ("unpaywall.org",),
    "datacite": ("datacite.org",),
    "zenodo": ("zenodo.org",),
    "orcid": ("orcid.org",),
    "ror": ("ror.org",),
    "openreview": ("openreview.net",),
}


def split_frontmatter(text: str) -> tuple[dict[str, str], str, int]:
    """Pure-stdlib parser for simple YAML frontmatter (name, description, compatibility, etc.)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text, 0
    end_idx = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx == -1:
        return {}, text, 0

    meta: dict[str, str] = {}
    fm_lines = lines[1:end_idx]
    current_key: str | None = None
    buf: list[str] = []
    block_mode: str | None = None

    def _flush() -> None:
        nonlocal current_key, buf, block_mode
        if current_key is not None and buf:
            meta[current_key] = " ".join(x.strip() for x in buf if x.strip())
        current_key = None
        buf = []
        block_mode = None

    for raw in fm_lines:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if not raw[0].isspace():
            _flush()
            m = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", raw)
            if not m:
                continue
            key, val = m.group(1).strip(), m.group(2).strip()
            if val in {">", "|", ">-", "|-"}:
                current_key = key
                block_mode = val
                buf = []
            elif val:
                if (val.startswith('"') and val.endswith('"')) or (
                    val.startswith("'") and val.endswith("'")
                ):
                    val = val[1:-1]
                meta[key] = val
        else:
            if current_key is not None and block_mode is not None:
                buf.append(raw.strip())
            elif current_key is not None:
                # Nested mapping line; append value if scalar
                buf.append(raw.strip())

    _flush()
    body = "\n".join(lines[end_idx + 1 :])
    return meta, body, end_idx + 1


def collect_scripts(root: Path) -> dict[str, str]:
    """Collect all scripts under <root>/scripts/ and <root>/modules/**/scripts/."""
    root_resolved = root.resolve()
    scripts: dict[str, str] = {}
    scripts_dir = root / "scripts"
    try:
        scripts_in_root = scripts_dir.is_dir() and scripts_dir.resolve().is_relative_to(root_resolved)
    except OSError:
        scripts_in_root = False
    if scripts_in_root:
        for p in sorted(scripts_dir.rglob("*")):
            if "__pycache__" in p.parts or not p.is_file():
                continue
            try:
                if not p.resolve().is_relative_to(root_resolved):
                    continue
            except OSError:
                continue
            if p.suffix in SCRIPT_EXTS:
                scripts[p.relative_to(root).as_posix()] = p.read_text(
                    encoding="utf-8", errors="replace"
                )

    modules_dir = root / "modules"
    try:
        modules_in_root = modules_dir.is_dir() and modules_dir.resolve().is_relative_to(root_resolved)
    except OSError:
        modules_in_root = False
    if modules_in_root:
        for mod_scripts in sorted(modules_dir.rglob("scripts")):
            try:
                if not mod_scripts.is_dir() or not mod_scripts.resolve().is_relative_to(root_resolved):
                    continue
            except OSError:
                continue
            for p in sorted(mod_scripts.rglob("*")):
                if "__pycache__" in p.parts or not p.is_file():
                    continue
                try:
                    if not p.resolve().is_relative_to(root_resolved):
                        continue
                except OSError:
                    continue
                if p.suffix in SCRIPT_EXTS:
                    scripts[p.relative_to(root).as_posix()] = p.read_text(
                        encoding="utf-8", errors="replace"
                    )
    return scripts


def extract_flags(rel_path: str, src: str) -> set[str]:
    """Extract supported CLI --flags from Python AST add_argument calls, with literal fallback."""
    flags = {"--help", "--version"}
    if rel_path.endswith(".py"):
        try:
            tree = ast.parse(src)
            found_add_arg = False
            ast_flags: set[str] = set()
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                func_name = (
                    func.id
                    if isinstance(func, ast.Name)
                    else (func.attr if isinstance(func, ast.Attribute) else "")
                )
                if func_name == "add_argument":
                    found_add_arg = True
                    for arg in node.args:
                        if (
                            isinstance(arg, ast.Constant)
                            and isinstance(arg.value, str)
                            and arg.value.startswith("--")
                        ):
                            ast_flags.add(arg.value)
            if found_add_arg:
                return flags | ast_flags
        except SyntaxError:
            pass

    for m in re.finditer(r"""['"](--[a-zA-Z0-9][a-zA-Z0-9-]*)['"]""", src):
        flags.add(m.group(1))
    return flags


def _logical_lines(text: str, line_offset: int = 0) -> list[tuple[int, str]]:
    """Join trailing '\\' line continuations while preserving starting 1-based line numbers."""
    raw_lines = text.splitlines()
    out: list[tuple[int, str]] = []
    i = 0
    while i < len(raw_lines):
        start_ln = line_offset + i + 1
        buf = raw_lines[i]
        while buf.rstrip().endswith("\\") and i + 1 < len(raw_lines):
            buf = buf.rstrip()[:-1] + " " + raw_lines[i + 1].lstrip()
            i += 1
        out.append((start_ln, buf))
        i += 1
    return out


def _normalize_script_ref(raw_ref: str, root_name: str, allow_rs_prefix: bool = True) -> str:
    norm = raw_ref
    while norm.startswith("./") or norm.startswith("../"):
        if norm.startswith("./"):
            norm = norm[2:]
        elif norm.startswith("../"):
            norm = norm[3:]
    prefixes = (f"{root_name}/", "research-scientist/") if allow_rs_prefix else (f"{root_name}/",)
    for prefix in prefixes:
        if norm.startswith(prefix):
            norm = norm[len(prefix) :]
            break
    return posixpath.normpath(norm)


def _check_status_tables(
    rel_file: str,
    text: str,
    line_offset: int,
    blob: str,
    findings: list[dict[str, Any]],
) -> None:
    lines = text.splitlines()
    i = 0
    while i + 1 < len(lines):
        hdr = lines[i].strip()
        sep = lines[i + 1].strip()
        if hdr.startswith("|") and sep.startswith("|") and re.match(r"^\|[\s:|-]+\|?$", sep):
            cols = [c.strip().lower() for c in hdr.strip("|").split("|")]
            if cols and cols[0] in {"status", "disposition"}:
                j = i + 2
                while j < len(lines) and lines[j].strip().startswith("|"):
                    row = lines[j].strip()
                    first_cell = row.strip("|").split("|")[0]
                    for m in re.finditer(r"`([A-Za-z][A-Za-z0-9_-]+)`", first_cell):
                        tok = m.group(1)
                        if f'"{tok}"' not in blob and f"'{tok}'" not in blob:
                            findings.append({
                                "file": rel_file,
                                "line": line_offset + j + 1,
                                "kind": "missing-status",
                                "token": tok,
                                "detail": f"Status/Disposition table token `{tok}` not found in bundled scripts",
                            })
                    j += 1
                i = j
                continue
        i += 1


def _measure_skill_footprint(
    raw_text: str,
    max_lines: int = 120,
    max_est_tokens: int = 1600,
    max_frontmatter_tokens: int = 150,
) -> dict[str, Any]:
    lines = raw_text.splitlines()
    line_count = len(lines)
    word_count = len(raw_text.split())
    est_tokens = int(round(word_count * 1.35))

    fm_words = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                fm_words = len("\n".join(lines[1:i]).split())
                break
    fm_est_tokens = int(round(fm_words * 1.35))

    return {
        "lines": line_count,
        "words": word_count,
        "est_tokens": est_tokens,
        "frontmatter_words": fm_words,
        "frontmatter_est_tokens": fm_est_tokens,
        "max_lines": max_lines,
        "max_est_tokens": max_est_tokens,
        "max_frontmatter_est_tokens": max_frontmatter_tokens,
    }


def audit_skill(
    root: Path,
    readme: Path | None = None,
    max_skill_lines: int = 120,
    max_skill_tokens: int = 1600,
    max_frontmatter_tokens: int = 150,
) -> dict[str, Any]:
    """Audit <root>/SKILL.md, <root>/references/*.md, and optional README.md against bundled scripts."""
    root = root.resolve()
    skill_md = root / "SKILL.md"
    if not root.is_dir() or not skill_md.is_file():
        raise FileNotFoundError(f"Invalid skill root (missing SKILL.md): {root}")
    if readme is not None and not readme.is_file():
        raise FileNotFoundError(f"README file not found: {readme}")

    scripts = collect_scripts(root)
    script_flags = {rel: extract_flags(rel, src) for rel, src in scripts.items()}
    blob = "\n".join(scripts.values())
    blob_lower = blob.lower()

    script_ref_re = re.compile(
        rf"(?<![\w/.-])((?:\./|\.\./)*(?:(?:research-scientist|{re.escape(root.name)})/)?"
        rf"(?:scripts|modules/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*/scripts)/"
        rf"(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.(?:py|sh|js|R|r))"
    )
    ref_doc_re = re.compile(
        rf"(?<![\w/.-])((?:\./|\.\./)*(?:(?:research-scientist|{re.escape(root.name)})/)?"
        r"references/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.md)(?:#[A-Za-z0-9_.-]+)?"
    )
    flag_re = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]*)")

    findings: list[dict[str, Any]] = []
    files_audited: list[str] = []
    docs: list[tuple[str, str]] = []

    if not skill_md.resolve().is_relative_to(root):
        skill_footprint = _measure_skill_footprint(
            "",
            max_lines=max_skill_lines,
            max_est_tokens=max_skill_tokens,
            max_frontmatter_tokens=max_frontmatter_tokens,
        )
        findings.append({
            "file": "SKILL.md",
            "line": 1,
            "kind": "outside-root-symlink",
            "token": "SKILL.md",
            "detail": f"`SKILL.md` resolves outside skill root `{root.name}/`",
        })
    else:
        skill_raw = skill_md.read_text(encoding="utf-8")
        skill_footprint = _measure_skill_footprint(
            skill_raw,
            max_lines=max_skill_lines,
            max_est_tokens=max_skill_tokens,
            max_frontmatter_tokens=max_frontmatter_tokens,
        )
        if skill_footprint["lines"] > max_skill_lines or skill_footprint["est_tokens"] > max_skill_tokens:
            findings.append({
                "file": "SKILL.md",
                "line": 1,
                "kind": "skill-bloat",
                "token": f"{skill_footprint['lines']}L/{skill_footprint['est_tokens']}tok",
                "detail": (
                    f"SKILL.md footprint ({skill_footprint['lines']} lines, {skill_footprint['est_tokens']} est. tokens) "
                    f"exceeds lean budget ({max_skill_lines} lines / {max_skill_tokens} est. tokens)"
                ),
            })
        if skill_footprint["frontmatter_est_tokens"] > max_frontmatter_tokens:
            findings.append({
                "file": "SKILL.md",
                "line": 1,
                "kind": "frontmatter-bloat",
                "token": f"{skill_footprint['frontmatter_est_tokens']}tok",
                "detail": (
                    f"SKILL.md YAML frontmatter ({skill_footprint['frontmatter_est_tokens']} est. tokens) "
                    f"exceeds budget ({max_frontmatter_tokens} est. tokens)"
                ),
            })
        docs.append(("SKILL.md", skill_raw))

    refs_dir = root / "references"
    refs_outside = False
    if refs_dir.is_symlink():
        try:
            refs_outside = not refs_dir.resolve().is_relative_to(root)
        except OSError:
            refs_outside = True
    if refs_outside:
        findings.append({
            "file": "references",
            "line": 1,
            "kind": "outside-root-symlink",
            "token": "references",
            "detail": f"`references/` resolves outside skill root `{root.name}/`",
        })
    elif refs_dir.is_dir():
        for entry in sorted(refs_dir.rglob("*")):
            try:
                resolved_entry = entry.resolve()
            except OSError:
                continue
            rel_entry = entry.relative_to(root).as_posix()
            if not resolved_entry.is_relative_to(root):
                if entry.is_symlink() or entry.suffix.lower() == ".md":
                    findings.append({
                        "file": rel_entry,
                        "line": 1,
                        "kind": "outside-root-symlink",
                        "token": rel_entry,
                        "detail": f"Reference path `{rel_entry}` resolves outside skill root `{root.name}/`",
                    })
                continue
            if resolved_entry.is_file() and entry.suffix.lower() == ".md":
                docs.append((rel_entry, entry.read_text(encoding="utf-8")))

    for dir_name in ("scripts", "modules"):
        sub_dir = root / dir_name
        if sub_dir.is_symlink():
            try:
                sub_outside = not sub_dir.resolve().is_relative_to(root)
            except OSError:
                sub_outside = True
            if sub_outside:
                findings.append({
                    "file": dir_name,
                    "line": 1,
                    "kind": "outside-root-symlink",
                    "token": dir_name,
                    "detail": f"`{dir_name}/` resolves outside skill root `{root.name}/`",
                })
                continue
        if sub_dir.is_dir():
            for entry in sorted(sub_dir.rglob("*")):
                if "__pycache__" in entry.parts or not (entry.is_symlink() and entry.is_dir()):
                    continue
                try:
                    entry_outside = not entry.resolve().is_relative_to(root)
                except OSError:
                    entry_outside = True
                if entry_outside:
                    rel_entry = entry.relative_to(root).as_posix()
                    findings.append({
                        "file": rel_entry,
                        "line": 1,
                        "kind": "outside-root-symlink",
                        "token": rel_entry,
                        "detail": f"Directory symlink `{rel_entry}` resolves outside skill root `{root.name}/`",
                    })
    if readme is not None:
        docs.append((readme.name, readme.read_text(encoding="utf-8")))

    for rel_file, raw_text in docs:
        files_audited.append(rel_file)
        if rel_file == "SKILL.md":
            meta, body, offset = split_frontmatter(raw_text)
            compat = meta.get("compatibility", "")
            for hm in HOST_RE.finditer(compat):
                host = hm.group(1).lower()
                if host not in GENERIC_HOSTS and host not in blob_lower:
                    findings.append({
                        "file": rel_file,
                        "line": 1,
                        "kind": "missing-host",
                        "token": host,
                        "detail": f"Frontmatter compatibility host `{host}` not found in scripts",
                    })
            desc = meta.get("description", "")
            for sm in QUERY_SENTENCE_RE.finditer(desc):
                sent_low = sm.group(0).lower()
                for svc, needles in SERVICES.items():
                    if svc in sent_low and not any(n in blob_lower for n in needles):
                        findings.append({
                            "file": rel_file,
                            "line": 1,
                            "kind": "missing-service",
                            "token": svc,
                            "detail": f"Frontmatter description service `{svc}` not matched in scripts",
                        })
        else:
            body, offset = raw_text, 0

        is_readme_file = readme is not None and rel_file == readme.name
        doc_dir = readme.parent if is_readme_file else (root / rel_file).parent
        allow_dotdot = rel_file != "SKILL.md"
        for lineno, line_text in _logical_lines(body, line_offset=offset):
            matches = list(script_ref_re.finditer(line_text))
            norm_matches: list[tuple[int, str]] = []
            for m in matches:
                raw_ref = m.group(1)
                doc_target = (doc_dir / raw_ref).resolve()
                allow_rs_prefix = (root.name == "research-scientist") or (
                    is_readme_file and doc_target.is_relative_to(root)
                )
                norm = _normalize_script_ref(raw_ref, root.name, allow_rs_prefix=allow_rs_prefix)
                norm_matches.append((m.start(), norm))
                in_root_doc = allow_dotdot and doc_target.is_relative_to(root) and doc_target.is_file()
                in_root_norm = (".." not in Path(raw_ref).parts) and (norm in scripts)
                if not ((in_root_doc or in_root_norm) and norm in scripts):
                    findings.append({
                        "file": rel_file,
                        "line": lineno,
                        "kind": "missing-script",
                        "token": norm,
                        "detail": f"Referenced script `{norm}` does not exist under `{root.name}/`",
                    })

            for rm in ref_doc_re.finditer(line_text):
                raw_ref = rm.group(1)
                doc_target = (doc_dir / raw_ref).resolve()
                allow_rs_prefix = (root.name == "research-scientist") or (
                    is_readme_file and doc_target.is_relative_to(root)
                )
                norm_ref = _normalize_script_ref(raw_ref, root.name, allow_rs_prefix=allow_rs_prefix)
                root_target = (root / norm_ref).resolve()
                in_root_doc = allow_dotdot and doc_target.is_relative_to(root) and doc_target.is_file()
                in_root_norm = (".." not in Path(raw_ref).parts) and root_target.is_relative_to(root) and root_target.is_file()
                if not in_root_doc and not in_root_norm:
                    findings.append({
                        "file": rel_file,
                        "line": lineno,
                        "kind": "missing-reference",
                        "token": norm_ref,
                        "detail": f"Referenced guide `{norm_ref}` does not exist under `{root.name}/`",
                    })

            if norm_matches:
                for fm in flag_re.finditer(line_text):
                    flag = fm.group(1)
                    fpos = fm.start()
                    preceding = [nm for pos, nm in norm_matches if pos <= fpos]
                    targets = [preceding[-1]] if preceding else [nm for _, nm in norm_matches]
                    for tgt in targets:
                        if tgt in script_flags and flag not in script_flags[tgt]:
                            findings.append({
                                "file": rel_file,
                                "line": lineno,
                                "kind": "missing-flag",
                                "token": flag,
                                "detail": f"Flag `{flag}` is not defined in `{tgt}`",
                            })

            # API host checks in body
            has_local_script = bool(norm_matches)
            for hm in HOST_RE.finditer(line_text):
                host = hm.group(1).lower()
                if host in GENERIC_HOSTS:
                    continue
                is_api_sub = host.startswith(("api.", "eutils.", "export."))
                start, end = hm.span()
                is_backticked = (
                    start > 0
                    and end < len(line_text)
                    and line_text[start - 1] == "`"
                    and line_text[end] == "`"
                )
                if (is_api_sub or is_backticked or has_local_script) and host not in blob_lower:
                    findings.append({
                        "file": rel_file,
                        "line": lineno,
                        "kind": "missing-host",
                        "token": host,
                        "detail": f"API/endpoint host `{host}` not found in bundled scripts",
                    })

        _check_status_tables(rel_file, body, offset, blob, findings)

    return {
        "status": "passed" if not findings else "failed",
        "root": str(root),
        "skill_footprint": skill_footprint,
        "files_audited": files_audited,
        "scripts_indexed": sorted(scripts.keys()),
        "finding_count": len(findings),
        "findings": findings,
    }


def _compact_report(report: dict[str, Any], limit: int = 10) -> dict[str, Any]:
    return {
        "compact": True,
        "status": report["status"],
        "root": report["root"],
        "skill_footprint": report["skill_footprint"],
        "total_files_audited": len(report["files_audited"]),
        "files_audited": report["files_audited"][:limit],
        "total_scripts_indexed": len(report["scripts_indexed"]),
        "scripts_indexed": report["scripts_indexed"][:limit],
        "finding_count": report["finding_count"],
        "findings_truncated": max(0, len(report["findings"]) - limit),
        "findings": report["findings"][:limit],
    }


def main(argv: list[str] | None = None) -> int:
    default_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(default_root), help="Path to skill root directory containing SKILL.md")
    parser.add_argument("--readme", help="Optional path to README.md to audit")
    parser.add_argument("--json", nargs="?", const="-", metavar="PATH", help="Emit JSON report to stdout or write to PATH")
    parser.add_argument("--compact", action="store_true", help="Emit compact bounded summary capping verbose lists")
    args = parser.parse_args(argv)

    try:
        if not isinstance(args.root, str) or not args.root.strip():
            raise ValueError("Invalid empty path passed to --root")
        if args.readme is not None and (not isinstance(args.readme, str) or not args.readme.strip()):
            raise ValueError("Invalid empty path passed to --readme")
        if args.json is not None and args.json != "-" and not args.json.strip():
            raise ValueError("Invalid empty output path passed to --json")
        report = audit_skill(
            Path(args.root),
            readme=Path(args.readme) if args.readme is not None else None,
        )
    except (OSError, UnicodeError, FileNotFoundError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2

    out_report = _compact_report(report) if args.compact else report
    if args.json == "-":
        print(json.dumps(out_report, separators=(",", ":")) if args.compact else json.dumps(out_report, indent=2))
    elif args.json is not None:
        if not args.json.strip():
            print(json.dumps({"error": "Invalid empty output path passed to --json"}), file=sys.stderr)
            return 2
        out_path = Path(args.json)
        try:
            out_path.write_text(
                (json.dumps(out_report, separators=(",", ":")) if args.compact else json.dumps(out_report, indent=2)) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 2
        print(
            f"claim_audit: {report['status']} "
            f"({report['finding_count']} findings across {len(report['files_audited'])} files; wrote {out_path})"
        )
    else:
        fp = report["skill_footprint"]
        print(
            f"claim_audit: {report['status']} "
            f"({report['finding_count']} findings across {len(report['files_audited'])} files; "
            f"SKILL.md={fp['lines']}L/{fp['est_tokens']}tok, fm={fp['frontmatter_est_tokens']}tok)"
        )
        items = out_report["findings"]
        for item in items:
            print(f"- [{item['kind']}] {item['file']}:{item['line']} `{item['token']}` — {item['detail']}")
        if args.compact and out_report.get("findings_truncated"):
            print(f"... ({out_report['findings_truncated']} more finding(s) truncated)")

    return 0 if report["finding_count"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
