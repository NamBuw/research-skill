#!/usr/bin/env python3
"""Unified opaque-box E2E test runner and structural preflight validator for research-scientist."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import py_compile
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

E2E_DIR = Path(__file__).resolve().parent
EVAL_DIR = E2E_DIR.parent
REPO_ROOT = E2E_DIR.parents[1]
REFS_DIR = REPO_ROOT / "research-scientist" / "references"


def _discover_e2e_py_files() -> list[Path]:
    files = []
    for p in sorted(E2E_DIR.glob("*.py")):
        if p.name.startswith("_"):
            continue
        files.append(p)
    return files


def _discover_test_files() -> list[Path]:
    return sorted(E2E_DIR.glob("test_e2e_*.py"))


def _resolve_tier_targets(tier: str) -> tuple[list[Path], str | None]:
    all_tests = _discover_test_files()
    if tier == "all":
        return ([E2E_DIR] if all_tests else []), None

    tier_map = {
        "1": E2E_DIR / "test_e2e_tier1.py",
        "2": E2E_DIR / "test_e2e_tier2.py",
        "3": E2E_DIR / "test_e2e_tier3.py",
        "4": E2E_DIR / "test_e2e_tier4_real_cases.py",
    }
    targets: list[Path] = []
    primary = tier_map[tier]
    if primary.exists():
        targets.append(primary)

    if tier in {"1", "2", "3"}:
        feature_files: list[Path] = []
        for fpath in sorted(E2E_DIR.glob("test_e2e_f*.py")):
            src = fpath.read_text(encoding="utf-8", errors="replace")
            if re.search(rf"def test_t{tier}_", src):
                targets.append(fpath)
                feature_files.append(fpath)
        if feature_files:
            primary_expr = f" or {primary.stem}" if primary.exists() else ""
            return targets, f"test_t{tier}_{primary_expr}"
    return targets, None


def run_structural_check() -> dict[str, Any]:
    """Validate syntax, dependencies, imports, pytest collection, fixtures, and unit suite parity."""
    checks: dict[str, Any] = {}
    ok = True

    # 1. No evaluation/e2e/__init__.py (preserves unittest discover -s evaluation)
    init_exists = (E2E_DIR / "__init__.py").exists()
    checks["no_e2e_init_py"] = {"passed": not init_exists, "path": str(E2E_DIR / "__init__.py")}
    if init_exists:
        ok = False

    # 2. Syntax compile check on all E2E Python files
    compiled: list[str] = []
    compile_errors: list[dict[str, str]] = []
    for py_file in _discover_e2e_py_files():
        try:
            py_compile.compile(str(py_file), doraise=True)
            compiled.append(str(py_file.relative_to(REPO_ROOT)))
        except py_compile.PyCompileError as exc:
            compile_errors.append({"file": str(py_file), "error": str(exc)})
            ok = False
    checks["py_compile"] = {"passed": not compile_errors, "compiled": compiled, "errors": compile_errors}

    # 3. Runtime dependency & helper import check
    dep_errors: list[str] = []
    for mod in ("fitz", "pdfplumber", "PIL", "ssl", "pytest", "requests"):
        if importlib.util.find_spec(mod) is None:
            dep_errors.append(f"missing python module: {mod}")
    for bin_name in ("openssl", "tesseract"):
        if shutil.which(bin_name) is None:
            dep_errors.append(f"missing binary: {bin_name}")
    try:
        sys.path.insert(0, str(E2E_DIR))
        import helpers  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        dep_errors.append(f"helpers import error: {exc}")
    finally:
        if str(E2E_DIR) in sys.path:
            sys.path.remove(str(E2E_DIR))
    checks["dependencies_and_imports"] = {"passed": not dep_errors, "errors": dep_errors}
    if dep_errors:
        ok = False

    # 4. Fixture JSON integrity check
    json_errors: list[dict[str, str]] = []
    json_checked = 0
    for root_dir in (E2E_DIR / "fixtures", EVAL_DIR / "fixtures", REFS_DIR):
        if not root_dir.exists():
            continue
        for jf in sorted(root_dir.rglob("*.json")):
            json_checked += 1
            try:
                json.loads(jf.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                json_errors.append({"file": str(jf), "error": str(exc)})
                ok = False
    checks["fixture_json_integrity"] = {"passed": not json_errors, "checked": json_checked, "errors": json_errors}

    # 5. Pytest collection check across evaluation/
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    col_proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", str(EVAL_DIR)],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    collected_lines = [ln for ln in col_proc.stdout.splitlines() if "::" in ln]
    col_passed = col_proc.returncode == 0 and len(collected_lines) > 0
    checks["pytest_collect_only"] = {
        "passed": col_passed,
        "returncode": col_proc.returncode,
        "collected_count": len(collected_lines),
        "stderr": col_proc.stderr.strip(),
    }
    if not col_passed:
        ok = False

    # 6. Existing unittest discovery parity (122 baseline tests)
    unit_proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", str(EVAL_DIR), "-v"],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    ran_match = re.search(r"Ran\s+(\d+)\s+tests?", unit_proc.stderr + "\n" + unit_proc.stdout)
    unit_count = int(ran_match.group(1)) if ran_match else 0
    unit_passed = unit_proc.returncode == 0 and unit_count >= 122
    checks["existing_unittest_suite"] = {
        "passed": unit_passed,
        "returncode": unit_proc.returncode,
        "tests_ran": unit_count,
    }
    if not unit_passed:
        ok = False

    return {"passed": ok, "checks": checks}


def run_pytest_tier(tier: str, *, live: bool) -> dict[str, Any]:
    targets, k_expr = _resolve_tier_targets(tier)
    if not targets:
        return {"returncode": 2, "error": f"No test files found for tier={tier}", "stdout": "", "stderr": ""}

    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if live:
        env["RUN_LIVE_AUDITS"] = "1"
        env["RESEARCH_SCIENTIST_LIVE"] = "1"

    cmd = [sys.executable, "-m", "pytest", "-v", "-p", "no:cacheprovider"]
    if live:
        cmd.append("--live")
    if k_expr:
        cmd.extend(["-k", k_expr])
    cmd.extend(str(t) for t in targets)

    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "command": cmd,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "discovered_files": [str(p.relative_to(REPO_ROOT)) for p in _discover_test_files()],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Unified E2E runner for research-scientist.")
    parser.add_argument("--tier", choices=["1", "2", "3", "4", "all"], default="all")
    parser.add_argument("--live", action="store_true", help="Enable @pytest.mark.live external network audits.")
    parser.add_argument("--structural-check", action="store_true", help="Validate syntax, imports, collection, fixtures, and unit parity.")
    parser.add_argument("--json-report", type=Path, help="Optional path to write JSON execution summary.")
    args = parser.parse_args(argv)

    report: dict[str, Any] = {"tier": args.tier, "live": args.live}
    if args.structural_check:
        struct = run_structural_check()
        report["structural_check"] = struct
        if args.json_report:
            args.json_report.parent.mkdir(parents=True, exist_ok=True)
            args.json_report.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0 if struct["passed"] else 1

    run_res = run_pytest_tier(args.tier, live=args.live)
    report["pytest"] = {k: v for k, v in run_res.items() if k != "stdout"}
    if run_res.get("stdout"):
        print(run_res["stdout"], end="")
    if run_res.get("stderr"):
        print(run_res["stderr"], file=sys.stderr, end="")

    # Parse pytest summary counts if available
    summary_line = ""
    for line in reversed((run_res.get("stdout") or "").splitlines()):
        if "passed" in line or "failed" in line or "error" in line:
            summary_line = line.strip()
            break
    report["summary_line"] = summary_line
    report["returncode"] = run_res["returncode"]

    if args.json_report:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return int(run_res["returncode"])


if __name__ == "__main__":
    raise SystemExit(main())
