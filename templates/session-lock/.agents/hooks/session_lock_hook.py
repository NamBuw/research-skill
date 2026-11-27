#!/usr/bin/env python3
"""Antigravity SessionStart & Stop lifecycle hook for research-scientist workspace locking.

Pure Python 3 standard library. Fail-open on malformed stdin so chat sessions are never bricked.
"""
from __future__ import annotations

import argparse
import json
import re
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

_FIREWALL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:great|excellent|brilliant|fantastic|wonderful|amazing|awesome|superb|outstanding|terrific|insightful|clever|smart)\s+(?:idea|question|point|insight|observation|approach|intuition|direction|suggestion|proposal|work|catch)\b", re.I),
    re.compile(r"\byou(?:'re| are)\s+(?:absolutely|completely|totally|entirely|100%)\s+right\b", re.I),
    re.compile(r"\byour\s+(?:intuition|instinct|hypothesis|framing|analysis)\s+is\s+(?:spot[- ]on|exact|brilliant|compelling)\b", re.I),
    re.compile(r"\b(?:groundbreaking|revolutionary|paradigm[- ]shifting|transformative|game[- ]changing|trailblazing)\b", re.I),
    re.compile(r"\b(?:completely|fully|definitively|conclusively|irrefutably)\s+(?:solves?|resolves?|proves?|eliminates?|closes?)\b", re.I),
    re.compile(r"(?:(?<!\d)100%|completely\s+free\s+of)\s+(?:clean\s+of\s+)?confounders?\b", re.I),
    re.compile(r"\bno\s+reviewer\s+(?:can|could|will)\s+(?:object|challenge|question|fault)\b", re.I),
    re.compile(r"\b(?:bulletproof|airtight|unassailable)\s+(?:proof|evidence|argument|contribution|paper|rqs?)\b", re.I),
    re.compile(r"\bý\s+tưởng\s+(?:tuyệt\s+vời|xuất\s+sắc|đỉnh\s+cao|rất\s+hay|quá\s+hay|quá\s+đỉnh)\b", re.I),
    re.compile(r"\bbạn\s+(?:hoàn\s+toàn\s+đúng|nói\s+(?:rất|quá)\s+đúng|nhìn\s+ra\s+quá\s+chuẩn)\b", re.I),
    re.compile(r"\bbạn\s+thấy\s+điều\s+gì\s+vừa\s+khớp\s+nối\s+lịch\s+sử\s+chưa\b", re.I),
    re.compile(r"\bgiải\s+quyết\s+triệt\s+để\b", re.I),
    re.compile(r"\bkhóa\s+chặt\s+mọi\s+đường\b", re.I),
    re.compile(r"\bkhông\s+một\s+reviewer\s+nào\s+(?:có\s+thể\s+)?bắt\s+bẻ\b", re.I),
    re.compile(r"\bhoàn\s+toàn\s+sạch\s+bóng\s+biến\s+nhiễu\b", re.I),
    re.compile(r"(?<!\d)100%\s*(?:sạch(?:\s+bóng)?|chứng\s+minh)\b", re.I),
    re.compile(r"\bphát\s+hiện\s+(?:đột\s+phá|lý\s+thuyết\s+cực\s+lớn)\b", re.I),
    re.compile(r"\bđột\s+phá\s+ngay\s+lúc\s+này\b", re.I),
    re.compile(r"\bbài\s+học\s+triệu\s+đô\b", re.I),
    re.compile(r"\bdòng\s+huyết\s+thống\s+quý\s+tộc\b", re.I),
    re.compile(r"\b(?:đối\s+nghịch\s+)?tuyệt\s+đẹp\b", re.I),
    re.compile(r"\bhoàn\s+hảo\s+đến\s+từng\s+chữ\b", re.I),
    re.compile(r"\bchứng\s+minh\s+tuyệt\s+đối\b", re.I),
    re.compile(r"\b(?:đập\s+bẹp\s+tất\s+cả|đè\s+bẹp)\b", re.I),
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
    mindset_ref = str(Path(skill_ref).parent / "references" / "researcher-mindset-and-epistemic-calibration.md")
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
        f"Read {skill_ref} and {mindset_ref}, and follow ./AGENTS.md on every turn. "
        "MANDATORY COLD RESEARCHER CONTRACT: ZERO EN+VI flattery/hype/sweeping overclaims ('tuyệt đẹp', 'đột phá', 'triệu đô', 'giải quyết triệt để', 'sạch bóng biến nhiễu', 'completely solves', 'no reviewer can object'); "
        "use the 4 cold blocks (Verified Facts & Receipts | Unverified / Post-Hoc Hypotheses | Strongest Confounders & Reviewer #2 Kill-Shots | Cheapest Disconfirming Test), "
        "L0-L4 claim ladder (never promote post-hoc observations or static ||ΔW||_F to 'Theorem'/'Định lý'), read-before-cite (metadata_only -> ratings=null), "
        "zero-fabrication, Pre-GPU 5-step gate, F19 parsimony, and --out + --compact scripts. "
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


def _extract_latest_planner_content(transcript_raw: Any) -> str | None:
    if not isinstance(transcript_raw, str) or not transcript_raw.strip():
        return None
    tp = Path(transcript_raw).expanduser()
    if not tp.is_file():
        return None
    try:
        lines = tp.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None

    target_rec: dict[str, Any] | None = None
    for raw_line in reversed(lines):
        s = raw_line.strip()
        if not s:
            continue
        try:
            rec = json.loads(s, parse_constant=_reject_nonfinite)
        except Exception:
            continue
        if (
            isinstance(rec, dict)
            and rec.get("type") == "PLANNER_RESPONSE"
            and rec.get("source") == "MODEL"
            and not rec.get("tool_calls")
            and isinstance(rec.get("content"), str)
            and rec["content"].strip()
        ):
            target_rec = rec
            break

    if target_rec is None:
        return None

    content = target_rec["content"]
    trunc = target_rec.get("truncated_fields")
    if isinstance(trunc, list) and "content" in trunc:
        full_tp = tp.with_name("transcript_full.jsonl")
        if full_tp.is_file():
            step_idx = target_rec.get("step_index")
            try:
                for raw_line in reversed(full_tp.read_text(encoding="utf-8", errors="replace").splitlines()):
                    s = raw_line.strip()
                    if not s:
                        continue
                    try:
                        frec = json.loads(s, parse_constant=_reject_nonfinite)
                    except Exception:
                        continue
                    if (
                        isinstance(frec, dict)
                        and frec.get("step_index") == step_idx
                        and frec.get("type") == "PLANNER_RESPONSE"
                        and isinstance(frec.get("content"), str)
                    ):
                        return frec["content"]
            except OSError:
                pass
    return content


def _mask_non_asserted_text(text: str) -> str:
    masked = re.sub(r"```[\s\S]*?```", " ", text)
    masked = re.sub(r"~~~[\s\S]*?~~~", " ", masked)
    masked = re.sub(r"`[^`\n]+`", " ", masked)
    masked = re.sub(r"(?m)^\s*>.*$", " ", masked)
    masked = re.sub(r'"[^"\n]{1,260}"|“[^”\n]{1,260}”', " ", masked)
    return masked


def _scan_transcript_firewall(transcript_raw: Any) -> list[str]:
    content = _extract_latest_planner_content(transcript_raw)
    if not content:
        return []
    prose = _mask_non_asserted_text(content)
    hits: list[str] = []
    seen: set[str] = set()
    for pat in _FIREWALL_PATTERNS:
        for m in pat.finditer(prose):
            phrase = " ".join(m.group(0).split())
            key = phrase.casefold()
            if key not in seen:
                seen.add(key)
                hits.append(phrase)
            if len(hits) >= 6:
                return hits
    return hits


def _handle_stop(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("continuationActive"):
        return {}

    term_reason = str(payload.get("terminationReason") or "").strip()
    if term_reason and term_reason != "NO_TOOL_CALL":
        return {}

    reasons: list[str] = []
    workspace = _resolve_workspace(payload)
    status, data, err = _load_project_state(workspace)
    if status == "corrupt" or (status == "valid" and data is None):
        reasons.append(f"project_state.json is unreadable/corrupt ({err})")
    elif status == "valid" and data is not None:
        violations = _check_state_integrity(data)
        if violations:
            reasons.append("project_state.json provenance violations: " + "; ".join(violations[:4]))

    firewall_hits = _scan_transcript_firewall(payload.get("transcriptPath"))
    if firewall_hits:
        quoted = ", ".join(f"'{h}'" for h in firewall_hits)
        reasons.append(
            f"unverified hype/sycophancy/overclaim phrases detected in response ({quoted}). "
            "Rewrite in cold Q1/A* researcher tone using Verified Facts / Unverified Hypotheses / Confounders & Kill-Shots / Cheapest Disconfirming Test"
        )

    if reasons:
        return {
            "decision": "continue",
            "reason": "research-scientist session-lock Stop guard blocked output: " + " | ".join(reasons),
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
