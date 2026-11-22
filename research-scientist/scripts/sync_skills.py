#!/usr/bin/env python3
"""Multi-skill sync for the research-scientist Hub-and-Spoke suite (parent + 6 sibling sub-skills).

SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
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

IGNORE_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".DS_Store"}
IGNORE_SUFFIXES = {".pyc", ".pyo"}
IGNORE_PATTERNS = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".pytest_cache", ".mypy_cache", ".DS_Store")


def _err(msg: str) -> int:
    print(json.dumps({"error": msg}), file=sys.stderr)
    return 2


def _nonempty(val: Any, flag: str) -> str:
    if not isinstance(val, str) or not val.strip():
        raise ValueError(f"Empty or invalid path for {flag}")
    return val.strip()


def _is_ignored_name(name: str) -> bool:
    return name in IGNORE_NAMES or any(name.endswith(suf) for suf in IGNORE_SUFFIXES)


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


def _check_broken_ancestor_symlinks(path: Path) -> Path:
    """Walk up from path to nearest existing ancestor, rejecting broken intermediate symlinks."""
    cur = path
    while not cur.exists():
        if cur.is_symlink():
            raise ValueError(f"Path traverses a broken symlink: {cur}")
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    return cur


def _probe_dir_writable(target_dir: Path, label: str) -> None:
    anc = _check_broken_ancestor_symlinks(target_dir)
    if not anc.is_dir():
        raise NotADirectoryError(f"{label} ancestor is not a directory: {anc}")
    if not os.access(anc, os.W_OK | os.X_OK):
        raise PermissionError(f"{label} is not writable: {anc}")
    with tempfile.TemporaryDirectory(prefix=".sync-probe-", dir=anc):
        pass


def _validate_output_path(
    raw_path: str,
    flag: str,
    *,
    suite_root: Path | None = None,
    target_dirs: list[Path] | None = None,
) -> Path:
    val = _nonempty(raw_path, flag)
    p = Path(val).expanduser()
    if p.is_symlink() and not p.exists():
        raise ValueError(f"{flag} path is a broken symlink: {p}")
    _check_broken_ancestor_symlinks(p)
    out_abs = Path(os.path.abspath(str(p)))
    out_res = p.resolve()

    if suite_root is not None:
        sroot_exp = suite_root.expanduser()
        _check_broken_ancestor_symlinks(sroot_exp)
        sroot_abs = Path(os.path.abspath(str(sroot_exp)))
        sroot_res = sroot_exp.resolve()
        for base in (sroot_abs, sroot_res):
            for cand in (out_abs, out_res):
                if cand == base or cand.is_relative_to(base):
                    raise ValueError(f"{flag} path {p} overlaps suite root {sroot_res}")

    if target_dirs:
        for raw_t in target_dirs:
            t_exp = raw_t.expanduser()
            _check_broken_ancestor_symlinks(t_exp)
            t_abs = Path(os.path.abspath(str(t_exp)))
            t_res = t_exp.resolve()
            for sname in SUITE_SKILLS:
                skill_cands = [t_abs / sname, t_res / sname]
                if (t_res / sname).exists() or (t_res / sname).is_symlink():
                    skill_cands.append((t_res / sname).resolve())
                for sbase in skill_cands:
                    for cand in (out_abs, out_res):
                        if cand == sbase or cand.is_relative_to(sbase):
                            raise ValueError(
                                f"{flag} path {p} overlaps target skill directory {t_res / sname}"
                            )

    if p.exists():
        if p.is_dir():
            raise IsADirectoryError(f"{flag} path is an existing directory: {p}")
        if not os.access(p, os.W_OK):
            raise PermissionError(f"{flag} file is not writable: {p}")
        return p
    _probe_dir_writable(p.parent, flag)
    return p


def _dir_ancestors(base: Path, dp: Path, initial: set[tuple[int, int]]) -> set[tuple[int, int]]:
    anc = set(initial)
    cur = base
    st0 = os.stat(cur)
    anc.add((st0.st_dev, st0.st_ino))
    rel = dp.relative_to(base)
    for part in rel.parts:
        cur = cur / part
        st = os.stat(cur)
        anc.add((st.st_dev, st.st_ino))
    return anc


def _check_source_symlinks(
    sdir: Path,
    sdir_res: Path,
    *,
    skill_name: str | None = None,
    ancestors: set[tuple[int, int]] | None = None,
) -> None:
    sname = skill_name or sdir.name
    base_anc = set(ancestors or set())
    st_root = os.stat(sdir)
    base_anc.add((st_root.st_dev, st_root.st_ino))
    for dirpath, dirnames, filenames in os.walk(sdir, followlinks=False):
        dp = Path(dirpath)
        cur_anc = _dir_ancestors(sdir, dp, base_anc)
        kept_dirs: list[str] = []
        for d in sorted(dirnames):
            if _is_ignored_name(d):
                continue
            p = dp / d
            if p.is_symlink():
                if not p.exists():
                    raise ValueError(f"Broken symlink inside source skill {sname}: {p}")
                if not p.resolve().is_relative_to(sdir_res):
                    raise ValueError(f"Escaping symlink inside source skill {sname}: {p}")
                if p.is_dir():
                    st_t = os.stat(p)
                    key_t = (st_t.st_dev, st_t.st_ino)
                    if key_t in cur_anc:
                        raise ValueError(f"Cyclic internal symlink inside source skill {sname}: {p}")
                    _check_source_symlinks(p, sdir_res, skill_name=sname, ancestors=cur_anc | {key_t})
                continue
            kept_dirs.append(d)
        dirnames[:] = kept_dirs
        for fn in sorted(filenames):
            if _is_ignored_name(fn):
                continue
            p = dp / fn
            if p.is_symlink():
                if not p.exists():
                    raise ValueError(f"Broken symlink inside source skill {sname}: {p}")
                if not p.resolve().is_relative_to(sdir_res):
                    raise ValueError(f"Escaping symlink inside source skill {sname}: {p}")


def validate_suite_root(suite_root: Path) -> list[Path]:
    suite_exp = suite_root.expanduser()
    if not suite_exp.exists() or not suite_exp.is_dir():
        raise FileNotFoundError(f"Suite root directory not found: {suite_root}")
    suite_res = suite_exp.resolve()
    skill_dirs: list[Path] = []
    missing: list[str] = []
    for name in SUITE_SKILLS:
        sdir = suite_res / name
        if sdir.is_symlink() and (not sdir.exists() or not sdir.resolve().is_relative_to(suite_res)):
            raise ValueError(f"Source skill symlink escapes suite root: {sdir}")
        if not sdir.is_dir() or not (sdir / "SKILL.md").is_file():
            missing.append(f"{name}/SKILL.md")
        elif not (sdir / "agents" / "openai.yaml").is_file():
            missing.append(f"{name}/agents/openai.yaml")
        else:
            sdir_res = sdir.resolve()
            if not sdir_res.is_relative_to(suite_res):
                raise ValueError(f"Source skill {sdir} resolves outside suite root {suite_res}")
            _check_source_symlinks(sdir, sdir_res)
            skill_dirs.append(sdir)
    if missing:
        raise FileNotFoundError(f"Suite root missing required skill files: {', '.join(missing)}")
    if not (suite_res / "research-scientist" / "scripts" / "claim_audit.py").is_file():
        raise FileNotFoundError(f"Suite root missing shared scripts/claim_audit.py under {suite_res}")
    return skill_dirs


def _collect_source_inodes(sdir: Path) -> set[tuple[int, int]]:
    inodes: set[tuple[int, int]] = set()
    st_root = os.lstat(sdir)
    inodes.add((st_root.st_dev, st_root.st_ino))
    for dirpath, dirnames, filenames in os.walk(sdir, followlinks=False):
        dirnames[:] = [d for d in dirnames if not _is_ignored_name(d)]
        dp = Path(dirpath)
        for d in dirnames:
            st = os.lstat(dp / d)
            inodes.add((st.st_dev, st.st_ino))
        for fn in filenames:
            if _is_ignored_name(fn):
                continue
            st = os.lstat(dp / fn)
            inodes.add((st.st_dev, st.st_ino))
    return inodes


def _validate_targets(
    suite_root_res: Path,
    skill_dirs: list[Path],
    target_dirs: list[Path],
    *,
    check_writable: bool = False,
) -> list[Path]:
    if not target_dirs:
        raise ValueError("No target directories specified")

    deduped: list[Path] = []
    seen: set[Path] = set()
    for raw_t in target_dirs:
        t_exp = raw_t.expanduser()
        if t_exp.is_symlink() and not t_exp.exists():
            raise ValueError(f"Target directory is a broken symlink: {raw_t}")
        _check_broken_ancestor_symlinks(t_exp)
        tdir = t_exp.resolve()
        if tdir not in seen:
            seen.add(tdir)
            deduped.append(tdir)

    source_inodes = {sdir.name: _collect_source_inodes(sdir) for sdir in skill_dirs}
    all_source_inodes: set[tuple[int, int]] = set().union(*source_inodes.values())

    for tdir in deduped:
        if tdir.exists() and not tdir.is_dir():
            raise ValueError(f"Target path is not a directory: {tdir}")
        if tdir == suite_root_res or tdir.is_relative_to(suite_root_res) or suite_root_res.is_relative_to(tdir):
            raise ValueError(f"Target directory {tdir} overlaps suite root {suite_root_res}")
        if tdir.exists() and os.path.samefile(tdir, suite_root_res):
            raise ValueError(f"Target directory {tdir} is the same file as suite root {suite_root_res}")
        if check_writable:
            _probe_dir_writable(tdir, f"Target directory {tdir}")

        for sdir in skill_dirs:
            sdir_res = sdir.resolve()
            dest = tdir / sdir.name
            dest_res = dest.resolve()
            if (
                dest_res == sdir_res
                or dest_res.is_relative_to(sdir_res)
                or sdir_res.is_relative_to(dest_res)
                or dest_res == suite_root_res
                or dest_res.is_relative_to(suite_root_res)
                or suite_root_res.is_relative_to(dest_res)
            ):
                raise ValueError(f"Destination {dest} overlaps suite root or source skill {sdir_res}")
            if dest.exists() or dest.is_symlink():
                if dest.exists() and os.path.samefile(dest_res, sdir_res):
                    raise ValueError(f"Destination {dest} resolves to source skill {sdir_res}")
                if dest.is_dir() and not dest.is_symlink():
                    st_dest = os.lstat(dest)
                    if (st_dest.st_dev, st_dest.st_ino) in all_source_inodes:
                        raise ValueError(f"Destination {dest} shares inode with source {sdir_res}")
                    for dirpath, dirnames, filenames in os.walk(dest, followlinks=False):
                        dp = Path(dirpath)
                        for name in dirnames + filenames:
                            if _is_ignored_name(name):
                                continue
                            entry = dp / name
                            st = os.lstat(entry)
                            if (st.st_dev, st.st_ino) in all_source_inodes:
                                raise ValueError(f"Destination {dest} shares hardlinked/samefile entry {entry} with source {sdir_res}")
                            if entry.is_symlink() and entry.exists():
                                er = entry.resolve()
                                if er == suite_root_res or er.is_relative_to(suite_root_res):
                                    raise ValueError(f"Destination {dest} contains symlink {entry} pointing into suite root {suite_root_res}")
    return deduped


def _collect_rel_entries(
    base: Path,
    *,
    allow_internal_symlinks: bool,
    root_res: Path | None = None,
    ancestors: set[tuple[int, int]] | None = None,
) -> dict[str, tuple[str, bytes | None]]:
    entries: dict[str, tuple[str, bytes | None]] = {}
    eff_root = root_res or base.resolve()
    base_anc = set(ancestors or set())
    st_base = os.stat(base)
    base_anc.add((st_base.st_dev, st_base.st_ino))

    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        dp = Path(dirpath)
        cur_anc = _dir_ancestors(base, dp, base_anc)
        kept_dirs: list[str] = []
        for d in sorted(dirnames):
            if _is_ignored_name(d):
                continue
            p = dp / d
            rel = p.relative_to(base).as_posix()
            if p.is_symlink():
                if allow_internal_symlinks and p.exists() and p.resolve().is_relative_to(eff_root):
                    if p.is_dir():
                        st_t = os.stat(p)
                        key_t = (st_t.st_dev, st_t.st_ino)
                        if key_t in cur_anc:
                            raise ValueError(f"Cyclic internal directory symlink detected: {p}")
                        entries[rel] = ("dir", None)
                        sub = _collect_rel_entries(
                            p,
                            allow_internal_symlinks=True,
                            root_res=eff_root,
                            ancestors=cur_anc | {key_t},
                        )
                        for sr, sval in sub.items():
                            entries[f"{rel}/{sr}"] = sval
                    else:
                        entries[rel] = ("file", p.read_bytes())
                else:
                    entries[rel] = ("symlink", None)
                continue
            entries[rel] = ("dir", None)
            kept_dirs.append(d)
        dirnames[:] = kept_dirs
        for fn in sorted(filenames):
            if _is_ignored_name(fn):
                continue
            p = dp / fn
            rel = p.relative_to(base).as_posix()
            if p.is_symlink():
                if allow_internal_symlinks and p.exists() and p.resolve().is_relative_to(eff_root) and p.is_file():
                    entries[rel] = ("file", p.read_bytes())
                else:
                    entries[rel] = ("symlink", None)
            else:
                entries[rel] = ("file", p.read_bytes())
    return entries


def _check_target_parity(tdir: Path, skill_dirs: list[Path]) -> tuple[list[dict[str, str]], bool]:
    diffs: list[dict[str, str]] = []
    if not tdir.is_dir():
        for sdir in skill_dirs:
            diffs.append({"skill": sdir.name, "kind": "missing_skill", "path": sdir.name})
        return diffs, False

    for sdir in skill_dirs:
        dest = tdir / sdir.name
        if not dest.exists() and not dest.is_symlink():
            diffs.append({"skill": sdir.name, "kind": "missing_skill", "path": sdir.name})
            continue
        if dest.is_symlink() or not dest.is_dir():
            diffs.append({"skill": sdir.name, "kind": "type_mismatch", "path": sdir.name})
            continue

        src_files = _collect_rel_entries(sdir, allow_internal_symlinks=True)
        dst_files = _collect_rel_entries(dest, allow_internal_symlinks=False)

        for rel in sorted(src_files.keys() - dst_files.keys()):
            kind = "missing_dir" if src_files[rel][0] == "dir" else "missing_file"
            diffs.append({"skill": sdir.name, "kind": kind, "path": f"{sdir.name}/{rel}"})
        for rel in sorted(dst_files.keys() - src_files.keys()):
            kind = "extra_dir" if dst_files[rel][0] == "dir" else "extra_file"
            diffs.append({"skill": sdir.name, "kind": kind, "path": f"{sdir.name}/{rel}"})
        for rel in sorted(src_files.keys() & dst_files.keys()):
            sk, sb = src_files[rel]
            dk, db = dst_files[rel]
            if sk != dk:
                diffs.append({"skill": sdir.name, "kind": "type_mismatch", "path": f"{sdir.name}/{rel}"})
            elif sb != db:
                diffs.append({"skill": sdir.name, "kind": "modified_file", "path": f"{sdir.name}/{rel}"})

    verified_links = _verify_shared_links(tdir)
    return diffs, verified_links


def _verify_shared_links(tdir: Path) -> bool:
    parent_dir = tdir / "research-scientist"
    if not parent_dir.is_dir() or parent_dir.is_symlink():
        return False
    for sname in SUITE_SKILLS[1:]:
        sdir = tdir / sname
        if not sdir.is_dir() or sdir.is_symlink():
            return False
        probe = (sdir / ".." / "research-scientist" / "scripts" / "claim_audit.py").resolve()
        if not probe.is_file():
            return False
    return True


def _atomic_replace_skill(sdir: Path, dest: Path, tdir: Path) -> None:
    with tempfile.TemporaryDirectory(prefix=f".sync-{sdir.name}-", dir=tdir) as tmp:
        staged = Path(tmp) / sdir.name
        shutil.copytree(sdir, staged, ignore=IGNORE_PATTERNS, symlinks=False)
        backup: Path | None = None
        if dest.exists() or dest.is_symlink():
            backup = tdir / f".bak-{sdir.name}-{os.getpid()}-{id(staged)}"
            if backup.exists() or backup.is_symlink():
                if backup.is_dir() and not backup.is_symlink():
                    shutil.rmtree(backup)
                else:
                    backup.unlink()
            shutil.move(str(dest), str(backup))
        try:
            shutil.move(str(staged), str(dest))
        except Exception:
            if backup is not None and (backup.exists() or backup.is_symlink()) and not (dest.exists() or dest.is_symlink()):
                shutil.move(str(backup), str(dest))
            raise
        if backup is not None and (backup.exists() or backup.is_symlink()):
            if backup.is_dir() and not backup.is_symlink():
                shutil.rmtree(backup)
            else:
                backup.unlink()


def sync_suite(
    suite_root: Path,
    target_dirs: list[Path],
    *,
    dry_run: bool = False,
    check_only: bool = False,
) -> dict[str, Any]:
    if dry_run and check_only:
        raise ValueError("--dry-run and --check are mutually exclusive")
    suite_root_res = suite_root.expanduser().resolve()
    skill_dirs = validate_suite_root(suite_root_res)
    resolved_targets = _validate_targets(
        suite_root_res,
        skill_dirs,
        target_dirs,
        check_writable=(not dry_run and not check_only),
    )

    results: list[dict[str, Any]] = []
    for tdir in resolved_targets:
        if check_only:
            diffs, verified_links = _check_target_parity(tdir, skill_dirs)
            in_sync = (len(diffs) == 0) and verified_links
            results.append({
                "target_dir": str(tdir),
                "skills": [s.name for s in skill_dirs],
                "count": len(skill_dirs),
                "shared_scripts_resolved": verified_links,
                "in_sync": in_sync,
                "diff_count": len(diffs),
                "diffs": diffs,
                "dry_run": False,
                "check": True,
            })
            continue

        synced_skills: list[str] = []
        if not dry_run:
            tdir.mkdir(parents=True, exist_ok=True)
        for sdir in skill_dirs:
            dest = tdir / sdir.name
            if not dry_run:
                _atomic_replace_skill(sdir, dest, tdir)
            synced_skills.append(sdir.name)

        verified_links = True if dry_run else _verify_shared_links(tdir)
        results.append({
            "target_dir": str(tdir),
            "skills": synced_skills,
            "count": len(synced_skills),
            "shared_scripts_resolved": verified_links,
            "dry_run": dry_run,
        })

    if check_only:
        all_in_sync = all(t["in_sync"] for t in results)
        status = "in_sync" if all_in_sync else "out_of_sync"
    elif dry_run:
        status = "dry_run"
    else:
        status = "synced"

    return {
        "schema": "sync_skills_v1",
        "status": status,
        "suite_root": str(suite_root_res),
        "skills_count": len(SUITE_SKILLS),
        "targets": results,
    }


def _build_compact_report(report: dict[str, Any], out_arg: str | None) -> dict[str, Any]:
    targets_compact: list[dict[str, Any]] = []
    for t in report["targets"]:
        item: dict[str, Any] = {
            "target_dir": t["target_dir"],
            "count": t["count"],
            "resolved": t["shared_scripts_resolved"],
        }
        if t.get("check"):
            item["in_sync"] = t["in_sync"]
            item["diff_count"] = t["diff_count"]
            item["diffs"] = t["diffs"][:5]
        targets_compact.append(item)

    compact_report: dict[str, Any] = {
        "compact": True,
        "schema": report["schema"],
        "status": report["status"],
        "skills_count": report["skills_count"],
        "targets": targets_compact,
        "out": out_arg,
    }
    raw = json.dumps(compact_report, separators=(",", ":"))
    if len(raw.encode("utf-8")) > MAX_COMPACT_BYTES:
        for t in compact_report["targets"]:
            if "diffs" in t:
                t["diffs"] = t["diffs"][:2]
        raw = json.dumps(compact_report, separators=(",", ":"))
    if len(raw.encode("utf-8")) > MAX_COMPACT_BYTES:
        for t in compact_report["targets"]:
            if "diffs" in t:
                t["diffs"] = []
        for cap in (5, 3, 1, 0):
            compact_report["targets"] = compact_report["targets"][:cap]
            raw = json.dumps(compact_report, separators=(",", ":"))
            if len(raw.encode("utf-8")) <= MAX_COMPACT_BYTES:
                break
    return compact_report


def _emit(report: dict[str, Any], compact_report: dict[str, Any], args: argparse.Namespace) -> None:
    if getattr(args, "out", None) is not None:
        op = Path(_nonempty(args.out, "--out")).expanduser()
        op.parent.mkdir(parents=True, exist_ok=True)
        op.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    json_arg = getattr(args, "json", None)
    if json_arg is not None and json_arg != "-":
        jp = Path(_nonempty(json_arg, "--json")).expanduser()
        jp.parent.mkdir(parents=True, exist_ok=True)
        jp.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if getattr(args, "compact", False):
        print(json.dumps(compact_report, separators=(",", ":")))
    elif json_arg == "-":
        print(json.dumps(report, indent=2))
    elif json_arg is not None:
        print(json.dumps(compact_report, separators=(",", ":")))
    else:
        print(json.dumps(report, indent=2))


def main(argv: list[str] | None = None) -> int:
    default_suite = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite-root", default=str(default_suite), help="Root directory containing research-scientist and 6 sibling sub-skills")
    parser.add_argument("--target-dir", action="append", default=[], help="Target CLI skills directory (repeatable; defaults to ~/.agents/skills, ~/.claude/skills, ~/.codex/skills if present)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Plan sync without modifying target directories")
    mode.add_argument("--check", action="store_true", help="Non-destructively verify target directories match suite root")
    parser.add_argument("--out", help="Write full JSON output to PATH")
    parser.add_argument("--json", nargs="?", const="-", metavar="PATH", help="Emit JSON report to stdout or write to PATH")
    parser.add_argument("--compact", action="store_true", help="Bounded <4KB stdout summary")
    args = parser.parse_args(argv)

    try:
        sroot = Path(_nonempty(args.suite_root, "--suite-root"))
        if args.target_dir:
            tdirs = [Path(_nonempty(t, "--target-dir")) for t in args.target_dir]
        else:
            tdirs = discover_default_targets()
        if args.out is not None:
            _validate_output_path(args.out, "--out", suite_root=sroot, target_dirs=tdirs)
        if args.json is not None and args.json != "-":
            _validate_output_path(args.json, "--json", suite_root=sroot, target_dirs=tdirs)

        report = sync_suite(sroot, tdirs, dry_run=args.dry_run, check_only=args.check)
        compact_report = _build_compact_report(report, args.out)
        _emit(report, compact_report, args)
    except (OSError, ValueError, FileNotFoundError) as exc:
        return _err(str(exc))

    if args.check:
        return 0 if report["status"] == "in_sync" else 1
    if not args.dry_run and any(not t["shared_scripts_resolved"] for t in report["targets"]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
