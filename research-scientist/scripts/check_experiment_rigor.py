#!/usr/bin/env python3
"""Experiment code rigor audit: reproducibility prerequisites, rliable multi-seed stats, and train/eval contamination.

SPDX-License-Identifier: Apache-2.0

Attribution & License Notice:
- Reproducibility check (`repro`) adapted from `ShaishavMaisuria/research-paper-lifecycle-skills`
  (`skills/test-research-code/scripts/repro_check.py`, Apache-2.0 License, Copyright 2026 Shaishav Maisuria).
- Multi-seed IQM, stratified bootstrap CIs, optimality gap, and probability of improvement (`rliable`)
  follow `google-research/rliable` (Apache-2.0 License, Agarwal et al., NeurIPS 2021).
- Deterministic n-gram train/eval contamination check (`contamination`) added for AI/NLP/CV benchmark hygiene.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import sys
from pathlib import Path
from typing import Any

MAX_COMPACT_BYTES = 3800

README_NAMES = {"readme", "readme.md", "readme.rst", "readme.txt", "readme.markdown"}
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
    "dockerfile": "Docker image recipe",
    "containerfile": "OCI image recipe",
    "uv.lock": "uv lockfile (pinned)",
}
LOCKFILES = {"pipfile.lock", "poetry.lock", "renv.lock", "uv.lock"}
ENTRYPOINT_FILES = {
    "makefile", "run.sh", "run.py", "main.py", "train.py", "evaluate.py",
    "eval.py", "reproduce.sh", "reproduce.py", "repro.sh", "experiment.py",
}
SOURCE_EXTS = {".py", ".sh", ".r", ".jl", ".ipynb"}
SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "env",
    "node_modules", ".mypy_cache", ".pytest_cache", "build", "dist",
}
SEED_RE = re.compile(
    r"\brandom\.seed\s*\(|\bnp\.random\.seed\s*\(|\bnumpy\.random\.seed\s*\("
    r"|\bnp\.random\.default_rng\s*\(|\btorch\.manual_seed\s*\("
    r"|\btorch\.cuda\.manual_seed(?:_all)?\s*\(|\bset_seed\s*\("
    r"|\bseed_everything\s*\(|\bPYTHONHASHSEED\b|\bdeterministic\s*=\s*True",
    re.I,
)
TEST_DIR_NAMES = {"test", "tests"}
TEST_FILE_RE = re.compile(r"(^test_.*\.py$)|(.*_test\.py$)|(^test.*\.sh$)", re.I)
DATA_README_RE = re.compile(
    r"\b(download|dataset|data\s*set|wget|curl|kaggle|huggingface|hf\s+hub|zenodo|obtain\s+the\s+data)\b",
    re.I,
)
RESULTS_CMD_RE = re.compile(
    r"(reproduce|to\s+reproduce|```[\s\S]*?(?:python|bash|sh|make|\./|docker\s+run)[\s\S]*?```|^\s*(?:python|bash|sh|make|\./run)\b)",
    re.I | re.M,
)
DATA_DIR_NAMES = {"data", "datasets", "dataset"}
DATA_SCRIPT_RE = re.compile(r"(download|fetch|get|prepare).*data|data.*(download|fetch|prepare)", re.I)
MAIN_GUARD_RE = re.compile(r"if\s+__name__\s*==\s*['\"]__main__['\"]")


def _err(msg: str) -> int:
    print(json.dumps({"error": msg}), file=sys.stderr)
    return 2


def _validate_nonempty_str(val: Any, flag: str) -> str:
    if not isinstance(val, str) or not val.strip():
        raise ValueError(f"Empty or invalid path for {flag}")
    return val.strip()


def _emit_output(payload: dict[str, Any], compact_payload: dict[str, Any], args: argparse.Namespace) -> None:
    if getattr(args, "out", None):
        out_path = Path(_validate_nonempty_str(args.out, "--out"))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if getattr(args, "compact", False):
        raw = json.dumps(compact_payload, separators=(",", ":"))
        if len(raw.encode("utf-8")) > MAX_COMPACT_BYTES:
            trimmed = dict(compact_payload)
            for k in list(trimmed.keys()):
                if isinstance(trimmed[k], list) and len(trimmed[k]) > 5:
                    trimmed[k] = trimmed[k][:5]
            raw = json.dumps(trimmed, separators=(",", ":"))
        print(raw)
    elif getattr(args, "json", None) == "-":
        print(json.dumps(payload, indent=2))
    elif getattr(args, "json", None):
        jp = Path(_validate_nonempty_str(args.json, "--json"))
        jp.parent.mkdir(parents=True, exist_ok=True)
        jp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(compact_payload, separators=(",", ":")))
    else:
        print(json.dumps(payload, indent=2))


# ---------------------------------------------------------------------------
# 1. Reproducibility audit (repro_check)
# ---------------------------------------------------------------------------

def audit_repro(root: Path, max_files: int = 2000) -> dict[str, Any]:
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Directory not found: {root}")
    if max_files < 1:
        raise ValueError("--max-files must be >= 1")

    readme_path: Path | None = None
    readme_text = ""
    env_files: list[tuple[str, str]] = []
    pinned = False
    entrypoints: list[str] = []
    seed_hits: list[str] = []
    has_main_guard = False
    data_dir = False
    data_scripts: list[str] = []
    test_dirs: list[str] = []
    test_files: list[str] = []
    n_source = 0
    scanned = 0
    truncated = False

    for path in sorted(root.rglob("*")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        rel = path.relative_to(root).as_posix()
        if path.is_dir():
            low = path.name.lower()
            if low in TEST_DIR_NAMES:
                test_dirs.append(rel)
            if low in DATA_DIR_NAMES:
                data_dir = True
            continue
        if not path.is_file():
            continue
        low = path.name.lower()
        if low in README_NAMES and readme_path is None:
            readme_path = path
            readme_text = path.read_text(encoding="utf-8", errors="replace")
        if low in ENV_FILES:
            env_files.append((rel, ENV_FILES[low]))
            if low in LOCKFILES:
                pinned = True
        if low in ENTRYPOINT_FILES:
            entrypoints.append(rel)
        if TEST_FILE_RE.match(path.name):
            test_files.append(rel)
        if DATA_SCRIPT_RE.search(low):
            data_scripts.append(rel)
        if path.suffix.lower() in SOURCE_EXTS:
            n_source += 1
            if scanned < max_files:
                scanned += 1
                text = path.read_text(encoding="utf-8", errors="replace")
                if SEED_RE.search(text):
                    seed_hits.append(rel)
                if MAIN_GUARD_RE.search(text):
                    has_main_guard = True
            else:
                truncated = True

    if not pinned:
        for rel, _ in env_files:
            p = root / rel
            if p.name.lower().startswith("requirements") and p.suffix == ".txt":
                body = p.read_text(encoding="utf-8", errors="replace")
                if re.search(r"(==|@|https?://|git\+)", body):
                    pinned = True
                    break

    data_in_readme = bool(readme_text and DATA_README_RE.search(readme_text))
    results_cmd = bool(readme_text and RESULTS_CMD_RE.search(readme_text))

    essentials: list[dict[str, str]] = []
    essentials.append({
        "name": "README",
        "status": "OK" if readme_path else "MISSING",
        "detail": f"found {readme_path.name}" if readme_path else "no top-level README found",
    })
    if env_files:
        essentials.append({
            "name": "ENV",
            "status": "OK" if pinned else "WARN",
            "detail": f"{', '.join(sorted({lbl for _, lbl in env_files}))} ({'pinned' if pinned else 'NOT pinned'})",
        })
    else:
        essentials.append({"name": "ENV", "status": "MISSING", "detail": "no dependency manifest found"})
    essentials.append({
        "name": "SEED",
        "status": "OK" if seed_hits else "MISSING",
        "detail": f"seeding found in {len(seed_hits)} file(s)" if seed_hits else "no deterministic seed-setting found",
    })
    ep_bits = list(entrypoints) + (["__main__ guard"] if has_main_guard else [])
    essentials.append({
        "name": "ENTRYPOINT",
        "status": "OK" if ep_bits else "MISSING",
        "detail": ", ".join(ep_bits[:4]) if ep_bits else "no runnable entrypoint found",
    })
    data_bits = (["data/ directory"] if data_dir else []) + ([f"script:{data_scripts[0]}"] if data_scripts else []) + (["README data docs"] if data_in_readme else [])
    essentials.append({
        "name": "DATA",
        "status": "OK" if data_bits else "MISSING",
        "detail": ", ".join(data_bits) if data_bits else "no data instructions or download script",
    })
    essentials.append({
        "name": "RESULTS_CMD",
        "status": "OK" if results_cmd else ("MISSING" if readme_path is None else "WARN"),
        "detail": "README documents run/reproduce command" if results_cmd else "README lacks explicit reproduce command",
    })

    missing = [e["name"] for e in essentials if e["status"] == "MISSING"]
    warns = [e["name"] for e in essentials if e["status"] == "WARN"]
    return {
        "schema": "experiment_rigor_repro_v1",
        "path": str(root),
        "verdict": "FAIL" if missing else ("PASS_WITH_WARNINGS" if warns else "PASS"),
        "essentials": essentials,
        "missing": missing,
        "warnings": warns,
        "deps_pinned": pinned,
        "tests_present": bool(test_dirs or test_files),
        "test_files": test_files,
        "scanned_files": scanned,
        "source_files": n_source,
        "truncated": truncated,
    }


# ---------------------------------------------------------------------------
# 2. rliable multi-seed IQM, stratified bootstrap CI, optimality gap, P(X > Y)
# ---------------------------------------------------------------------------

def compute_iqm(values: list[float]) -> float:
    """Exact 25% trimmed mean (Interquartile Mean) matching google-research/rliable."""
    n = len(values)
    if n == 0:
        raise ValueError("Cannot compute IQM of empty sequence")
    s = sorted(values)
    lo = n * 0.25
    hi = n * 0.75
    total_w = 0.0
    weighted = 0.0
    for idx, val in enumerate(s):
        overlap = max(0.0, min(float(idx + 1), hi) - max(float(idx), lo))
        if overlap > 0.0:
            weighted += overlap * val
            total_w += overlap
    return weighted / total_w if total_w > 0 else sum(s) / n


def _normalize_matrix(raw_scores: Any, method_name: str) -> list[list[float]]:
    if not isinstance(raw_scores, list) or not raw_scores:
        raise ValueError(f"Method {method_name!r} must map to a non-empty list of scores")
    if isinstance(raw_scores[0], list):
        mat: list[list[float]] = []
        n_tasks = len(raw_scores[0])
        if n_tasks == 0:
            raise ValueError(f"Method {method_name!r} has empty task list")
        for row in raw_scores:
            if not isinstance(row, list) or len(row) != n_tasks:
                raise ValueError(f"Method {method_name!r} has ragged seed/task matrix")
            parsed_row = [float(x) for x in row]
            if not all(math.isfinite(x) for x in parsed_row):
                raise ValueError(f"Method {method_name!r} contains non-finite value")
            mat.append(parsed_row)
        return mat
    parsed = [float(x) for x in raw_scores]
    if not all(math.isfinite(x) for x in parsed):
        raise ValueError(f"Method {method_name!r} contains non-finite value")
    return [[x] for x in parsed]


def _percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    pos = q * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = min(len(sorted_vals) - 1, lo + 1)
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def _prob_of_improvement(mat_x: list[list[float]], mat_y: list[list[float]]) -> float:
    n_tasks = min(len(mat_x[0]), len(mat_y[0]))
    task_probs: list[float] = []
    for t in range(n_tasks):
        xs = [row[t] for row in mat_x]
        ys = [row[t] for row in mat_y]
        wins = 0.0
        for x in xs:
            for y in ys:
                if x > y:
                    wins += 1.0
                elif x == y:
                    wins += 0.5
        task_probs.append(wins / (len(xs) * len(ys)))
    return sum(task_probs) / len(task_probs)


def compute_rliable_stats(
    data: dict[str, Any],
    *,
    tau: float = 1.0,
    reps: int = 1000,
    seed: int = 0,
    baseline: str | None = None,
) -> dict[str, Any]:
    if not math.isfinite(tau):
        raise ValueError("--tau must be finite")
    if reps < 10:
        raise ValueError("--reps must be >= 10")

    methods_raw = data.get("methods") or data.get("scores")
    if not isinstance(methods_raw, dict) or not methods_raw:
        raise ValueError("Input JSON must contain non-empty 'methods' or 'scores' mapping")

    matrices = {name: _normalize_matrix(vals, name) for name, vals in methods_raw.items()}
    rng = random.Random(seed)
    base_name = baseline or data.get("baseline")
    if base_name is not None and base_name not in matrices:
        raise ValueError(f"Baseline method {base_name!r} not found in input")

    summary: dict[str, Any] = {}
    warnings: list[str] = []
    for name, mat in matrices.items():
        n_seeds = len(mat)
        n_tasks = len(mat[0])
        flat = [v for row in mat for v in row]
        iqm = compute_iqm(flat)
        mean_v = sum(flat) / len(flat)
        s_flat = sorted(flat)
        median_v = _percentile(s_flat, 0.5)
        opt_gap = sum(max(0.0, tau - v) for v in flat) / len(flat)

        boot_iqm: list[float] = []
        for _ in range(reps):
            sample: list[float] = []
            for t in range(n_tasks):
                col = [mat[s][t] for s in range(n_seeds)]
                for _s in range(n_seeds):
                    sample.append(col[rng.randrange(n_seeds)])
            boot_iqm.append(compute_iqm(sample))
        boot_iqm.sort()
        ci_low = _percentile(boot_iqm, 0.025)
        ci_high = _percentile(boot_iqm, 0.975)

        entry: dict[str, Any] = {
            "n_seeds": n_seeds,
            "n_tasks": n_tasks,
            "iqm": round(iqm, 6),
            "iqm_ci95": [round(ci_low, 6), round(ci_high, 6)],
            "mean": round(mean_v, 6),
            "median": round(median_v, 6),
            "optimality_gap": round(opt_gap, 6),
        }
        if n_seeds < 3:
            warnings.append(f"underpowered_seeds:{name}:n_seeds={n_seeds}<3")

        if base_name and name != base_name:
            base_mat = matrices[base_name]
            poi = _prob_of_improvement(mat, base_mat)
            boot_poi: list[float] = []
            b_seeds = len(base_mat)
            c_tasks = min(n_tasks, len(base_mat[0]))
            for _ in range(reps):
                sx = [[mat[rng.randrange(n_seeds)][t] for t in range(c_tasks)] for _s in range(n_seeds)]
                sy = [[base_mat[rng.randrange(b_seeds)][t] for t in range(c_tasks)] for _s in range(b_seeds)]
                boot_poi.append(_prob_of_improvement(sx, sy))
            boot_poi.sort()
            entry["prob_improvement_vs_baseline"] = round(poi, 6)
            entry["prob_improvement_ci95"] = [round(_percentile(boot_poi, 0.025), 6), round(_percentile(boot_poi, 0.975), 6)]
            if poi <= 0.5:
                warnings.append(f"no_clear_improvement:{name}_vs_{base_name}:P={poi:.3f}")

        summary[name] = entry

    return {
        "schema": "experiment_rigor_rliable_v1",
        "tau": tau,
        "bootstrap_reps": reps,
        "baseline": base_name,
        "methods": summary,
        "warnings": warnings,
        "verdict": "PASS_WITH_WARNINGS" if warnings else "PASS",
    }


# ---------------------------------------------------------------------------
# 3. Deterministic n-gram train/eval contamination check
# ---------------------------------------------------------------------------

def _load_texts(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Path not found: {path}")
    files = sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]
    texts: list[str] = []
    for f in files:
        suf = f.suffix.lower()
        raw = f.read_text(encoding="utf-8", errors="replace")
        if not raw.strip():
            continue
        if suf == ".jsonl":
            for line in raw.splitlines():
                if not line.strip():
                    continue
                obj = json.loads(line)
                texts.append(json.dumps(obj, ensure_ascii=False) if isinstance(obj, dict) else str(obj))
        elif suf == ".json":
            obj = json.loads(raw)
            if isinstance(obj, list):
                for item in obj:
                    if isinstance(item, dict):
                        txt = " ".join(str(v) for k, v in item.items() if k in {"text", "prompt", "question", "input", "output", "answer", "content"} and v)
                        texts.append(txt or json.dumps(item, ensure_ascii=False))
                    else:
                        texts.append(str(item))
            elif isinstance(obj, dict):
                texts.append(json.dumps(obj, ensure_ascii=False))
        elif suf == ".csv":
            for row in csv.reader(raw.splitlines()):
                joined = " ".join(row).strip()
                if joined:
                    texts.append(joined)
        else:
            for line in raw.splitlines():
                if line.strip():
                    texts.append(line.strip())
    if not texts:
        raise ValueError(f"No readable non-empty text records found at {path}")
    return texts


def _norm_tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def check_contamination(train_path: Path, eval_path: Path, ngram: int = 8, threshold: float = 0.05) -> dict[str, Any]:
    if ngram < 3:
        raise ValueError("--ngram must be >= 3")
    if not (0.0 <= threshold <= 1.0):
        raise ValueError("--threshold must be in [0, 1]")
    train_texts = _load_texts(train_path)
    eval_texts = _load_texts(eval_path)

    train_exact = {" ".join(_norm_tokens(t)) for t in train_texts if _norm_tokens(t)}
    train_ngrams: set[tuple[str, ...]] = set()
    for t in train_texts:
        toks = _norm_tokens(t)
        if len(toks) >= ngram:
            for i in range(len(toks) - ngram + 1):
                train_ngrams.add(tuple(toks[i : i + ngram]))

    exact_hits: list[int] = []
    ngram_hits: list[dict[str, Any]] = []
    for idx, et in enumerate(eval_texts):
        toks = _norm_tokens(et)
        norm_s = " ".join(toks)
        is_exact = norm_s in train_exact and bool(norm_s)
        if is_exact:
            exact_hits.append(idx)
        overlap_count = 0
        total_ngrams = max(0, len(toks) - ngram + 1)
        if total_ngrams > 0:
            for i in range(total_ngrams):
                if tuple(toks[i : i + ngram]) in train_ngrams:
                    overlap_count += 1
        if is_exact or overlap_count > 0:
            ngram_hits.append({
                "eval_index": idx,
                "exact_match": is_exact,
                "matching_ngrams": overlap_count,
                "total_ngrams": total_ngrams,
                "preview": et[:100],
            })

    contaminated_frac = len(ngram_hits) / len(eval_texts)
    detected = bool(exact_hits) or contaminated_frac >= threshold
    return {
        "schema": "experiment_rigor_contamination_v1",
        "ngram_size": ngram,
        "threshold": threshold,
        "train_count": len(train_texts),
        "eval_count": len(eval_texts),
        "exact_match_count": len(exact_hits),
        "contaminated_eval_count": len(ngram_hits),
        "contaminated_fraction": round(contaminated_frac, 6),
        "hits": ngram_hits,
        "verdict": "CONTAMINATION_DETECTED" if detected else "PASS",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_repro = sub.add_parser("repro", help="Audit research code directory for reproducibility essentials")
    p_repro.add_argument("path", help="Path to code directory")
    p_repro.add_argument("--strict", action="store_true", help="Treat warnings as failures (exit 1)")
    p_repro.add_argument("--max-files", type=int, default=2000, help="Max source files to scan")
    p_repro.add_argument("--out", help="Write full JSON output to PATH")
    p_repro.add_argument("--json", nargs="?", const="-", help="Emit JSON output")
    p_repro.add_argument("--compact", action="store_true", help="Bounded <4KB stdout summary")

    p_rl = sub.add_parser("rliable", help="Compute IQM, stratified bootstrap 95%% CI, optimality gap, and P(X>Y)")
    p_rl.add_argument("scores_json", help="Path to multi-seed scores JSON")
    p_rl.add_argument("--tau", type=float, default=1.0, help="Optimality threshold (default 1.0)")
    p_rl.add_argument("--reps", type=int, default=1000, help="Bootstrap replicates (default 1000)")
    p_rl.add_argument("--seed", type=int, default=0, help="RNG seed for bootstrap")
    p_rl.add_argument("--baseline", help="Optional baseline method name for P(X>Y)")
    p_rl.add_argument("--strict", action="store_true", help="Exit 1 on warnings (e.g. <3 seeds)")
    p_rl.add_argument("--out", help="Write full JSON output to PATH")
    p_rl.add_argument("--json", nargs="?", const="-", help="Emit JSON output")
    p_rl.add_argument("--compact", action="store_true", help="Bounded <4KB stdout summary")

    p_contam = sub.add_parser("contamination", help="Deterministic exact + n-gram train/eval overlap check")
    p_contam.add_argument("--train", required=True, help="Train corpus file or directory")
    p_contam.add_argument("--eval", required=True, help="Eval corpus file or directory")
    p_contam.add_argument("--ngram", type=int, default=8, help="Word n-gram size (default 8)")
    p_contam.add_argument("--threshold", type=float, default=0.05, help="Contamination fraction threshold (default 0.05)")
    p_contam.add_argument("--out", help="Write full JSON output to PATH")
    p_contam.add_argument("--json", nargs="?", const="-", help="Emit JSON output")
    p_contam.add_argument("--compact", action="store_true", help="Bounded <4KB stdout summary")

    args = parser.parse_args(argv)
    try:
        if args.cmd == "repro":
            target = Path(_validate_nonempty_str(args.path, "path"))
            res = audit_repro(target, max_files=args.max_files)
            compact = {
                "compact": True,
                "schema": res["schema"],
                "verdict": res["verdict"],
                "missing": res["missing"],
                "warnings": res["warnings"],
                "deps_pinned": res["deps_pinned"],
                "tests_present": res["tests_present"],
                "out": args.out,
            }
            _emit_output(res, compact, args)
            return 1 if res["missing"] or (args.strict and res["warnings"]) else 0

        if args.cmd == "rliable":
            spath = Path(_validate_nonempty_str(args.scores_json, "scores_json"))
            if not spath.is_file():
                raise FileNotFoundError(f"Scores JSON not found: {spath}")
            raw = json.loads(spath.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("Scores JSON root must be a JSON object")
            res = compute_rliable_stats(
                raw, tau=args.tau, reps=args.reps, seed=args.seed, baseline=args.baseline
            )
            compact = {
                "compact": True,
                "schema": res["schema"],
                "verdict": res["verdict"],
                "baseline": res["baseline"],
                "methods": res["methods"],
                "warnings": res["warnings"][:10],
                "out": args.out,
            }
            _emit_output(res, compact, args)
            return 1 if (args.strict and res["warnings"]) else 0

        train_p = Path(_validate_nonempty_str(args.train, "--train"))
        eval_p = Path(_validate_nonempty_str(args.eval, "--eval"))
        res = check_contamination(train_p, eval_p, ngram=args.ngram, threshold=args.threshold)
        compact = {
            "compact": True,
            "schema": res["schema"],
            "verdict": res["verdict"],
            "exact_match_count": res["exact_match_count"],
            "contaminated_eval_count": res["contaminated_eval_count"],
            "contaminated_fraction": res["contaminated_fraction"],
            "sample_hits": res["hits"][:5],
            "out": args.out,
        }
        _emit_output(res, compact, args)
        return 1 if res["verdict"] != "PASS" else 0
    except (OSError, ValueError, json.JSONDecodeError, FileNotFoundError) as exc:
        return _err(str(exc))


if __name__ == "__main__":
    sys.exit(main())
