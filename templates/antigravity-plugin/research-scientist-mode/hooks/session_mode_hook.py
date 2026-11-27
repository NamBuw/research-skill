#!/usr/bin/env python3
"""Per-conversation Antigravity toggle hook (/research-scientist <-> /research-off).

Pure Python 3 stdlib. Fail-open on missing/malformed stdin so chat sessions never break.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPECTED_SCHEMA = "research_scientist_project_state_v1"
REMINDER_INTERVAL_TURNS = 2
STALE_SESSION_SECONDS = 30 * 86400
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

OFF_RE = re.compile(r"(?:^|\s)/research[-_ ]?off(?:\s|$|[.,!?:;])", re.I)
ON_RE = re.compile(r"(?:^|\s)/research[-_ ]?(?:scientist|on)(?:\s|$|[.,!?:;])", re.I)

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


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def _resolve_state_dir(cli_state_dir: str | None) -> Path:
    if isinstance(cli_state_dir, str) and cli_state_dir.strip():
        p = Path(cli_state_dir).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        return p

    plugin_data = os.environ.get("PLUGIN_DATA", "").strip()
    if plugin_data:
        try:
            cand = Path(plugin_data).expanduser() / "sessions"
            cand.mkdir(parents=True, exist_ok=True)
            if os.access(cand, os.W_OK | os.X_OK):
                return cand
        except OSError:
            pass

    fallback = Path.home() / ".gemini" / "antigravity" / "scratch" / "research_scientist_mode_sessions"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def _session_file(state_dir: Path, conversation_id: str) -> Path:
    safe_prefix = re.sub(r"[^A-Za-z0-9._-]+", "_", conversation_id).strip("._")[:80] or "conv"
    cid_hash = hashlib.sha256(conversation_id.encode("utf-8")).hexdigest()[:8]
    return state_dir / f"{safe_prefix}_{cid_hash}.json"


def _prune_stale_sessions(state_dir: Path) -> None:
    cutoff = time.time() - STALE_SESSION_SECONDS
    try:
        for entry in state_dir.iterdir():
            if entry.is_file() and entry.suffix == ".json":
                try:
                    if entry.stat().st_mtime < cutoff:
                        entry.unlink(missing_ok=True)
                except OSError:
                    continue
    except OSError:
        pass


def _load_session_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw, parse_constant=_reject_nonfinite)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_session_state(path: Path, state: dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _resolve_workspace(payload: dict[str, Any]) -> Path | None:
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
    return None


def _find_installed_skill() -> str:
    for cand in SKILL_CANDIDATES:
        if cand.is_file():
            return str(cand)
    return "~/.agents/skills/research-scientist/SKILL.md"


def _load_project_state(workspace: Path | None) -> tuple[str, dict[str, Any] | None, str | None]:
    if workspace is None:
        return "absent", None, None
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


def _summarize_state(workspace: Path | None, status: str, data: dict[str, Any] | None, err: str | None) -> str:
    if workspace is None:
        return "No workspace directory detected; maintain provenance in project_state.json when working in a project."
    if status == "valid" and data is not None:
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
            f"project_state.json loaded from {workspace} (project_id={pid}, subfield_preset={preset}, "
            f"target_venue={venue}, target_venue_tier={tier}; {counts_str})."
        )
    if status == "corrupt":
        return f"WARNING: {workspace / 'project_state.json'} is invalid ({err}). Repair it before trusting prior state."
    return (
        f"No project_state.json found in {workspace} yet; ask <=3 Socratic intake questions if scope is unsettled "
        "and initialize project_state.json via research-scientist/scripts/project_state.py --init."
    )


def _activation_message(skill_ref: str, state_note: str) -> str:
    mindset_ref = str(Path(skill_ref).parent / "references" / "researcher-mindset-and-epistemic-calibration.md")
    return (
        "[research-scientist session mode ACTIVE for this conversation] "
        f"Read {skill_ref} and {mindset_ref} immediately. Keep this session locked to Q1/A* researcher rigor across all 6 spokes "
        "(Precedent -> Gap/RQ/Parsimony -> Pre-GPU 5-Step Gate & Rigor -> Novelty/Venue/Rebuttal -> Writing/Preflight -> User Report). "
        "MANDATORY COLD CONTRACT: (1) Zero EN+VI flattery/hype/sweeping claims ('great idea', 'ý tưởng tuyệt vời', 'tuyệt đẹp', 'đột phá', 'triệu đô', "
        "'đập bẹp', 'giải quyết triệt để', 'khóa chặt mọi đường', 'không một reviewer nào bắt bẻ', 'hoàn toàn sạch bóng biến nhiễu', '100% free of confounders', 'completely solves'). "
        "(2) Enforce the L0-L4 Claim-Strength Ladder: never call untested hypotheses or post-hoc observations 'Theorem'/'Định lý'; static weight norms ||ΔW||_F do not prove behavior; "
        "tag exploratory post-hoc explanations explicitly; enforce 1-2 Acronym Budget and Cross-Paradigm Baselines. "
        "(3) Format substantive critiques strictly into 4 blocks: Verified Facts & Receipts | Unverified / Post-Hoc Hypotheses | Strongest Confounders & Reviewer #2 Kill-Shots | Cheapest Disconfirming Test. "
        "(4) Read-before-cite (metadata_only -> ratings=null), zero-fabrication, engineering-before-novelty, F19 parsimony, and --out + --compact scripts. "
        f"{state_note}"
    )


def _refresh_message(skill_ref: str, state_note: str, compacted: bool) -> str:
    reason = "context compaction detected" if compacted else "periodic 2-turn cold researcher anchor"
    return (
        f"[research-scientist session mode REMINDER ({reason})] Re-anchor to {skill_ref}: "
        "ZERO EN+VI flattery, hype ('tuyệt đẹp', 'đột phá', 'triệu đô'), or sweeping overclaims ('giải quyết triệt để', 'sạch bóng biến nhiễu', 'completely solves', 'no reviewer can object'). "
        "Never promote L0/L1 post-hoc hypotheses to 'Theorem'/'Định lý'; use 4 cold blocks (Verified / Unverified / Confounders & Kill-Shots / Cheapest Disconfirming Test), "
        f"read-before-cite, F19 parsimony, and --out + --compact scripts. {state_note}"
    )


def _as_int(val: Any) -> int | None:
    if isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val
    return None


def _is_same_turn_tool_loop(
    state: dict[str, Any],
    input_hash: str,
    invocation_num: int | None,
) -> bool:
    prev_hash = state.get("last_input_hash")
    prev_inv = _as_int(state.get("last_invocation_num"))
    return (
        prev_hash == input_hash
        and invocation_num is not None
        and prev_inv is not None
        and invocation_num > prev_inv
    )


def _handle_pre_invocation(payload: dict[str, Any], state_dir: Path) -> dict[str, Any]:
    cid = str(payload.get("conversationId") or "").strip()
    if not cid:
        return {}

    last_input = str(payload.get("lastUserInput") or "")
    input_hash = hashlib.sha256(last_input.encode("utf-8")).hexdigest()[:16]
    invocation_num = _as_int(payload.get("invocationNum"))
    initial_steps = _as_int(payload.get("initialNumSteps"))

    sess_path = _session_file(state_dir, cid)
    state = _load_session_state(sess_path)
    currently_active = bool(state.get("active"))

    if OFF_RE.search(last_input):
        if currently_active:
            new_state = {
                **state,
                "conversation_id": cid,
                "active": False,
                "last_input_hash": input_hash,
                "last_invocation_num": invocation_num,
                "last_initial_steps": initial_steps,
                "turns_since_reminder": 0,
                "deactivated_at_utc": _utc_now(),
            }
            _save_session_state(sess_path, new_state)
            return {
                "injectSteps": [
                    {
                        "systemMessage": {
                            "systemMessage": "[research-scientist session mode DEACTIVATED] Normal chat mode restored for this conversation.",
                            "metadata": {
                                "user_markdown": "🔓 **Research Scientist mode đã TẮT** cho đoạn chat này.",
                            },
                        }
                    }
                ]
            }
        return {}

    workspace = _resolve_workspace(payload)
    skill_ref = _find_installed_skill()
    ps_status, ps_data, ps_err = _load_project_state(workspace)
    state_note = _summarize_state(workspace, ps_status, ps_data, ps_err)

    if ON_RE.search(last_input):
        if not currently_active:
            _prune_stale_sessions(state_dir)
            new_state = {
                "conversation_id": cid,
                "active": True,
                "last_input_hash": input_hash,
                "last_invocation_num": invocation_num,
                "last_initial_steps": initial_steps,
                "turns_since_reminder": 0,
                "activated_at_utc": _utc_now(),
                "updated_at_utc": _utc_now(),
            }
            _save_session_state(sess_path, new_state)
            return {
                "injectSteps": [
                    {
                        "systemMessage": {
                            "systemMessage": _activation_message(skill_ref, state_note),
                            "metadata": {
                                "user_markdown": "🔒 **Research Scientist mode ACTIVE** (Q1/A* Epistemic Lock + Live Firewall; gõ `/research-off` để tắt).",
                            },
                        }
                    }
                ]
            }

        if _is_same_turn_tool_loop(state, input_hash, invocation_num):
            state["last_invocation_num"] = invocation_num
            state["updated_at_utc"] = _utc_now()
            _save_session_state(sess_path, state)
            return {}

        new_state = {
            **state,
            "conversation_id": cid,
            "active": True,
            "last_input_hash": input_hash,
            "last_invocation_num": invocation_num,
            "last_initial_steps": initial_steps,
            "turns_since_reminder": 0,
            "updated_at_utc": _utc_now(),
        }
        _save_session_state(sess_path, new_state)
        return {
            "injectSteps": [
                {
                    "systemMessage": {
                        "systemMessage": _refresh_message(skill_ref, state_note, compacted=False),
                        "metadata": {
                            "user_markdown": "🔒 **Research Scientist mode đang ACTIVE** (gõ `/research-off` để tắt).",
                        },
                    }
                }
            ]
        }

    if not currently_active:
        return {}

    if _is_same_turn_tool_loop(state, input_hash, invocation_num):
        state["last_invocation_num"] = invocation_num
        state["updated_at_utc"] = _utc_now()
        _save_session_state(sess_path, state)
        return {}

    prev_initial = _as_int(state.get("last_initial_steps"))
    compacted = initial_steps is not None and prev_initial is not None and initial_steps < prev_initial
    turns_since = int(state.get("turns_since_reminder") or 0) + 1

    if compacted or turns_since >= REMINDER_INTERVAL_TURNS:
        new_state = {
            **state,
            "last_input_hash": input_hash,
            "last_invocation_num": invocation_num,
            "last_initial_steps": initial_steps,
            "turns_since_reminder": 0,
            "updated_at_utc": _utc_now(),
        }
        _save_session_state(sess_path, new_state)
        return {
            "injectSteps": [
                {
                    "systemMessage": {
                        "systemMessage": _refresh_message(skill_ref, state_note, compacted=compacted),
                    }
                }
            ]
        }

    new_state = {
        **state,
        "last_input_hash": input_hash,
        "last_invocation_num": invocation_num,
        "last_initial_steps": initial_steps,
        "turns_since_reminder": turns_since,
        "updated_at_utc": _utc_now(),
    }
    _save_session_state(sess_path, new_state)
    return {}


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


def _handle_stop(payload: dict[str, Any], state_dir: Path) -> dict[str, Any]:
    if payload.get("continuationActive"):
        return {}

    term_reason = str(payload.get("terminationReason") or "").strip()
    if term_reason and term_reason != "NO_TOOL_CALL":
        return {}

    cid = str(payload.get("conversationId") or "").strip()
    if not cid:
        return {}

    state = _load_session_state(_session_file(state_dir, cid))
    if not state.get("active"):
        return {}

    reasons: list[str] = []
    workspace = _resolve_workspace(payload)
    status, data, err = _load_project_state(workspace)
    if status == "corrupt" or (status == "valid" and (data is None or workspace is None)):
        reasons.append(
            f"project_state.json is unreadable/corrupt ({err})"
        )
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
            "reason": "research-scientist session mode Stop guard blocked output: " + " | ".join(reasons),
        }
    return {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Antigravity per-chat research-scientist toggle hook")
    parser.add_argument("--event", required=True, choices=("PreInvocation", "Stop"))
    parser.add_argument("--state-dir", default=None, help="Optional override for per-conversation lock state directory")
    args = parser.parse_args(argv)

    payload = _read_stdin_payload()
    if not payload:
        sys.stdout.write("{}\n")
        return 0

    state_dir = _resolve_state_dir(args.state_dir)
    if args.event == "PreInvocation":
        result = _handle_pre_invocation(payload, state_dir)
    else:
        result = _handle_stop(payload, state_dir)
    sys.stdout.write(json.dumps(result) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
