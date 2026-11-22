#!/usr/bin/env python3
"""Antigravity SessionStart & Stop lifecycle hook for research-scientist workspace locking.

Pure Python 3 standard library. Fail-open on malformed stdin so chat sessions are never bricked.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

EXPECTED_SCHEMA = "research_scientist_project_state_v1"
FULL_TEXT_LEVELS = frozenset({"full_text", "selected_full_text"})
PLACEHOLDER_LOCATORS = frozenset({
    "",
    "tbd",
    "todo",
    "none",
    "n/a",
    "na",
    "unknown",
    "placeholder",
    "to be determined",
    "fill later",
    "none yet",
    "abstract",
    "metadata",
    "metadata_record",
})
SKILL_CANDIDATES = (
    Path.home() / ".agents" / "skills" / "research-scientist" / "SKILL.md",
    Path.home() / ".claude" / "skills" / "research-scientist" / "SKILL.md",
    Path.home() / ".codex" / "skills" / "research-scientist" / "SKILL.md",
)


def _reject_nonfinite(token: str) -> Any:
    raise ValueError(f"Non-finite JSON constant not allowed: {token}")


def _read_stdin_payload() -> dict[str, Any]:
    try:
        raw = sys.stdin.read()
    except Exception:
        return {}
    if not raw or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw, parse_constant=_reject_nonfinite)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _resolve_workspace(payload: dict[str, Any]) -> Path:
    cwd_raw = payload.get("cwd")
    if isinstance(cwd_raw, str) and cwd_raw.strip():
        cand = Path(cwd_raw).expanduser()
        if cand.is_dir():
            return cand.resolve()

    ws_paths = payload.get("workspacePaths")
    if isinstance(ws_paths, list):
        for raw_ws in ws_paths:
            if isinstance(raw_ws, str) and raw_ws.strip():
                cand = Path(raw_ws).expanduser()
                if cand.is_dir():
                    return cand.resolve()

    return Path(__file__).resolve().parents[2]


def _find_installed_skill() -> str | None:
    for cand in SKILL_CANDIDATES:
        if cand.is_file():
            return str(cand)
    return None


def _load_project_state(workspace: Path) -> tuple[str, dict[str, Any] | None, str | None]:
    state_path = workspace / "project_state.json"
    if not state_path.exists():
        return "absent", None, None
    if state_path.is_dir():
        return "corrupt", None, "project_state.json is a directory instead of a JSON file"
    try:
        raw = state_path.read_text(encoding="utf-8")
        data = json.loads(raw, parse_constant=_reject_nonfinite)
    except Exception as exc:
        return "corrupt", None, f"project_state.json parse error: {exc}"
    if not isinstance(data, dict):
        return "corrupt", None, "project_state.json root must be a JSON object"
    return "valid", data, None


def _summarize_state(data: dict[str, Any]) -> str:
    pid = str(data.get("project_id") or "").strip() or "<missing project_id>"
    preset = data.get("subfield_preset") or "unspecified"
    venue = data.get("target_venue") or "unspecified"
    tier = data.get("target_venue_tier") or "unspecified"
    counts: list[str] = []
    for key in ("corpus_digests", "gaps", "ideas", "rqs", "experiments", "scorecards", "venue_verdicts"):
        val = data.get(key)
        if isinstance(val, (dict, list)):
            counts.append(f"{key}={len(val)}")
    counts_str = ", ".join(counts) if counts else "empty"
    return (
        f"project_state.json loaded (project_id={pid}, subfield_preset={preset}, "
        f"target_venue={venue}, target_venue_tier={tier}; {counts_str})."
    )


def _handle_session_start(payload: dict[str, Any]) -> dict[str, Any]:
    workspace = _resolve_workspace(payload)
    skill_path = _find_installed_skill()
    skill_ref = skill_path or "~/.agents/skills/research-scientist/SKILL.md"
    status, data, err = _load_project_state(workspace)

    if status == "valid" and data is not None:
        state_note = _summarize_state(data)
    elif status == "corrupt":
        state_note = f"WARNING: {workspace / 'project_state.json'} is invalid ({err}). Repair it before trusting prior state."
    else:
        state_note = (
            f"No project_state.json found in {workspace} yet; ask <=3 Socratic intake questions if scope is unclear "
            "and initialize project_state.json via research-scientist/scripts/project_state.py --init."
        )

    msg = (
        f"[research-scientist session lock active in {workspace}] "
        f"Read {skill_ref} and follow ./AGENTS.md on every turn. "
        "Enforce zero-sycophancy falsification-first checks, read-before-cite (unread papers remain metadata_only with ratings=null), "
        "zero-fabrication, engineering-before-novelty, and F19 parsimony; run shared CLI scripts with --out and --compact. "
        f"{state_note}"
    )
    return {
        "injectSteps": [
            {
                "systemMessage": {
                    "systemMessage": msg,
                }
            }
        ]
    }


def _check_state_integrity(data: dict[str, Any]) -> list[str]:
    violations: list[str] = []

    schema = data.get("schema")
    if schema != EXPECTED_SCHEMA:
        violations.append(f"invalid schema {schema!r} (expected {EXPECTED_SCHEMA!r})")

    project_id = data.get("project_id")
    if not isinstance(project_id, str) or not project_id.strip():
        violations.append("missing non-blank project_id")

    digests = data.get("corpus_digests")
    if isinstance(digests, dict):
        for sid, entry in digests.items():
            if not isinstance(entry, dict):
                violations.append(f"corpus_digests[{sid!r}] is not an object")
                continue
            access = str(entry.get("access") or "").strip()
            if access in FULL_TEXT_LEVELS:
                raw_loc = entry.get("locator")
                loc_norm = raw_loc.strip().lower() if isinstance(raw_loc, str) else ""
                if not isinstance(raw_loc, str) or loc_norm in PLACEHOLDER_LOCATORS:
                    violations.append(
                        f"corpus_digests[{sid!r}] claims {access!r} without a non-placeholder locator"
                    )

    gaps = data.get("gaps")
    if isinstance(gaps, dict):
        for gid, gap in gaps.items():
            if not isinstance(gap, dict):
                violations.append(f"gaps[{gid!r}] is not an object")
                continue
            lenses = gap.get("lenses_f32")
            lead_lists: list[tuple[str, Any]] = []
            if isinstance(lenses, dict) and "isomorphic_transfer_leads" in lenses:
                lead_lists.append((f"gaps[{gid!r}].lenses_f32", lenses.get("isomorphic_transfer_leads")))
            if "isomorphic_transfer_leads" in gap:
                lead_lists.append((f"gaps[{gid!r}]", gap.get("isomorphic_transfer_leads")))
            for loc_prefix, leads in lead_lists:
                if leads is None:
                    continue
                if not isinstance(leads, list):
                    violations.append(f"{loc_prefix}.isomorphic_transfer_leads must be a list")
                    continue
                for idx, lead in enumerate(leads):
                    if not isinstance(lead, dict):
                        violations.append(f"{loc_prefix}.isomorphic_transfer_leads[{idx}] is not an object")
                        continue
                    if lead.get("status") != "lead" or lead.get("evidence_level") != "lead":
                        violations.append(
                            f"{loc_prefix}.isomorphic_transfer_leads[{idx}] must tag status='lead' and evidence_level='lead'"
                        )

    return violations


def _handle_stop(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("continuationActive"):
        return {}

    term_reason = str(payload.get("terminationReason") or "").strip()
    if term_reason and term_reason != "NO_TOOL_CALL":
        return {}

    workspace = _resolve_workspace(payload)
    status, data, err = _load_project_state(workspace)
    if status == "absent":
        return {}
    if status == "corrupt" or data is None:
        return {
            "decision": "continue",
            "reason": (
                f"research-scientist session-lock Stop check failed: {workspace / 'project_state.json'} "
                f"is unreadable/corrupt ({err}). Fix project_state.json before finishing."
            ),
        }

    violations = _check_state_integrity(data)
    if violations:
        preview = "; ".join(violations[:5])
        return {
            "decision": "continue",
            "reason": (
                f"research-scientist session-lock Stop check detected provenance/state violations in "
                f"{workspace / 'project_state.json'}: {preview}. Repair project_state.json before finishing."
            ),
        }
    return {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="research-scientist workspace SessionStart/Stop hook")
    parser.add_argument("--event", required=True, choices=("SessionStart", "Stop"))
    args = parser.parse_args(argv)

    payload = _read_stdin_payload()
    if args.event == "SessionStart":
        result = _handle_session_start(payload)
    else:
        result = _handle_stop(payload)
    sys.stdout.write(json.dumps(result) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
