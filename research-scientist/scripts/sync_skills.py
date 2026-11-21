#!/usr/bin/env python3
"""Multi-skill sync for the research-scientist Hub-and-Spoke suite (parent + 6 sibling sub-skills).

SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

MAX_COMPACT_BYTES = 3800

SUITE_SKILLS = (
    "research-scientist",
    "research-precedent-corpus",
    "research-gap-rq-audit",
    "research-experiment-coding",
    "research-novelty-venue",
    "research-paper-writing",
    "research-user-report",
)

IGNORE_PATTERNS = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", ".DS_Store")


def _err(msg: str) -> int:
    print(json.dumps({"error": msg}), file=sys.stderr)
    return 2


def _nonempty(val: Any, flag: str) -> str:
    if not isinstance(val, str) or not val.strip():
        raise ValueError(f"Empty or invalid path for {flag}")
    return val.strip()


def discover_default_targets(home: Path | None = None) -> list[Path]:
    """Return canonical CLI skill directories: Codex/Gemini (~/.agents/skills), Claude (~/.claude/skills), and ~/.codex/skills if present."""
    base = home or Path.home()
    targets = [
        base / ".agents" / "skills",
        base / ".claude" / "skills",
    ]
    codex_dir = base / ".codex" / "skills"
    if codex_dir.is_dir():
        targets.append(codex_dir)
    return targets


def validate_suite_root(suite_root: Path) -> list[Path]:
    if not suite_root.exists() or not suite_root.is_dir():
        raise FileNotFoundError(f"Suite root directory not found: {suite_root}")
    skill_dirs: list[Path] = []
    missing: list[str] = []
    for name in SUITE_SKILLS:
        sdir = suite_root / name
        if not sdir.is_dir() or not (sdir / "SKILL.md").is_file():
            missing.append(f"{name}/SKILL.md")
        elif not (sdir / "agents" / "openai.yaml").is_file():
            missing.append(f"{name}/agents/openai.yaml")
        else:
            skill_dirs.append(sdir)
    if missing:
        raise FileNotFoundError(f"Suite root missing required skill files: {', '.join(missing)}")
    return skill_dirs


def sync_suite(
    suite_root: Path,
    target_dirs: list[Path],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    skill_dirs = validate_suite_root(suite_root.resolve())
    if not target_dirs:
        raise ValueError("No target directories specified")

    resolved_targets = [t.expanduser().resolve() for t in target_dirs]
    results: list[dict[str, Any]] = []
    for tdir in resolved_targets:
        synced_skills: list[str] = []
        if not dry_run:
            tdir.mkdir(parents=True, exist_ok=True)
        for sdir in skill_dirs:
            dest = tdir / sdir.name
            if not dry_run:
                if dest.exists() or dest.is_symlink():
                    if dest.is_symlink() or dest.is_file():
                        dest.unlink()
                    else:
                        shutil.rmtree(dest)
                shutil.copytree(sdir, dest, ignore=IGNORE_PATTERNS, symlinks=False)
            synced_skills.append(sdir.name)

        verified_links = True
        if not dry_run:
            for sname in SUITE_SKILLS[1:]:
                probe = (tdir / sname / ".." / "research-scientist" / "scripts" / "claim_audit.py").resolve()
                if not probe.is_file():
                    verified_links = False
                    break
        results.append({
            "target_dir": str(tdir),
            "skills": synced_skills,
            "count": len(synced_skills),
            "shared_scripts_resolved": verified_links,
            "dry_run": dry_run,
        })

    return {
        "schema": "sync_skills_v1",
        "status": "dry_run" if dry_run else "synced",
        "suite_root": str(suite_root.resolve()),
        "skills_count": len(SUITE_SKILLS),
        "targets": results,
    }


def main(argv: list[str] | None = None) -> int:
    default_suite = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite-root", default=str(default_suite), help="Root directory containing research-scientist and 6 sibling sub-skills")
    parser.add_argument("--target-dir", action="append", default=[], help="Target CLI skills directory (repeatable; defaults to ~/.agents/skills, ~/.claude/skills, ~/.codex/skills if present)")
    parser.add_argument("--dry-run", action="store_true", help="Plan sync without modifying target directories")
    parser.add_argument("--json", nargs="?", const="-", metavar="PATH", help="Emit JSON report to stdout or write to PATH")
    parser.add_argument("--compact", action="store_true", help="Bounded <4KB stdout summary")
    args = parser.parse_args(argv)

    try:
        sroot = Path(_nonempty(args.suite_root, "--suite-root"))
        if args.target_dir:
            tdirs = [Path(_nonempty(t, "--target-dir")) for t in args.target_dir]
        else:
            tdirs = discover_default_targets()
        if args.json is not None and args.json != "-":
            _nonempty(args.json, "--json")
        report = sync_suite(sroot, tdirs, dry_run=args.dry_run)
    except (OSError, ValueError, FileNotFoundError) as exc:
        return _err(str(exc))

    compact_report = {
        "compact": True,
        "schema": report["schema"],
        "status": report["status"],
        "skills_count": report["skills_count"],
        "targets": [
            {"target_dir": t["target_dir"], "count": t["count"], "resolved": t["shared_scripts_resolved"]}
            for t in report["targets"]
        ],
    }

    if args.compact:
        raw = json.dumps(compact_report, separators=(",", ":"))
        if len(raw.encode("utf-8")) > MAX_COMPACT_BYTES:
            compact_report["targets"] = compact_report["targets"][:5]
            raw = json.dumps(compact_report, separators=(",", ":"))
        print(raw)
    elif args.json == "-":
        print(json.dumps(report, indent=2))
    elif args.json is not None:
        jp = Path(args.json)
        jp.parent.mkdir(parents=True, exist_ok=True)
        jp.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(compact_report, separators=(",", ":")))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
