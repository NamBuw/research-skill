"""Unit & state-machine tests for templates/antigravity-plugin/research-scientist-mode."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = REPO_ROOT / "templates" / "antigravity-plugin" / "research-scientist-mode"
HOOK_SCRIPT = PLUGIN_DIR / "hooks" / "session_mode_hook.py"
PROJECT_STATE_SCRIPT = REPO_ROOT / "research-scientist" / "scripts" / "project_state.py"

ALLOWED_PLUGIN_TOP_KEYS = frozenset({
    "name",
    "displayName",
    "version",
    "description",
    "author",
    "homepage",
    "repository",
    "disabled",
    "logo",
    "suggestedPrompts",
})


def _run_mode_hook(
    event: str,
    payload: str | dict[str, object],
    state_dir: Path,
    *,
    hook_path: Path = HOOK_SCRIPT,
) -> subprocess.CompletedProcess[str]:
    stdin_text = payload if isinstance(payload, str) else json.dumps(payload)
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(hook_path), "--event", event, "--state-dir", str(state_dir)],
        input=stdin_text,
        cwd=str(hook_path.parents[1]),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


class TestSessionModePlugin(unittest.TestCase):
    def test_plugin_bundle_schema_and_no_shadowing(self) -> None:
        manifest = json.loads((PLUGIN_DIR / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest.get("name"), "research-scientist-mode")
        self.assertTrue(set(manifest.keys()).issubset(ALLOWED_PLUGIN_TOP_KEYS))
        self.assertIsInstance(manifest.get("suggestedPrompts"), list)
        self.assertEqual(len(manifest["suggestedPrompts"]), 3)

        hooks_cfg = json.loads((PLUGIN_DIR / "hooks.json").read_text(encoding="utf-8"))
        entry = hooks_cfg["research-scientist-mode"]
        self.assertIs(entry.get("enabled"), True)
        for event in ("PreInvocation", "Stop"):
            handlers = entry.get(event)
            self.assertIsInstance(handlers, list)
            self.assertEqual(len(handlers), 1)
            self.assertEqual(handlers[0].get("type"), "command")
            self.assertIn("./hooks/session_mode_hook.py", handlers[0].get("command", ""))
            self.assertIn(f"--event {event}", handlers[0].get("command", ""))

        mode = HOOK_SCRIPT.stat().st_mode
        self.assertTrue(mode & stat.S_IXUSR, "session_mode_hook.py must be executable")

        off_skill = PLUGIN_DIR / "skills" / "research-off" / "SKILL.md"
        self.assertTrue(off_skill.is_file())
        off_text = off_skill.read_text(encoding="utf-8")
        self.assertIn("name: research-off", off_text)
        self.assertFalse(
            (PLUGIN_DIR / "skills" / "research-scientist").exists(),
            "Plugin must not duplicate or shadow research-scientist skill",
        )

    def test_pre_invocation_toggle_isolation_loop_and_compaction(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_dir = root / "state"
            ws = root / "workspace"
            ws.mkdir()

            # (a) Unlocked normal prompt -> {} and zero state files
            r0 = _run_mode_hook(
                "PreInvocation",
                {"conversationId": "conv-a", "lastUserInput": "Fix pytest bug", "invocationNum": 1, "initialNumSteps": 2, "cwd": str(ws)},
                state_dir,
            )
            self.assertEqual(r0.returncode, 0, r0.stderr)
            self.assertEqual(json.loads(r0.stdout), {})
            self.assertEqual(list(state_dir.glob("*.json")) if state_dir.exists() else [], [])

            # (b) Activate via /research-scientist
            r_on = _run_mode_hook(
                "PreInvocation",
                {
                    "conversationId": "conv-a",
                    "lastUserInput": "/research-scientist audit my low-resource ASR experiment",
                    "invocationNum": 1,
                    "initialNumSteps": 5,
                    "cwd": str(ws),
                },
                state_dir,
            )
            self.assertEqual(r_on.returncode, 0, r_on.stderr)
            out_on = json.loads(r_on.stdout)
            sys_msg = out_on["injectSteps"][0]["systemMessage"]
            self.assertIn("ACTIVE", sys_msg["systemMessage"])
            self.assertIn("ACTIVE", sys_msg["metadata"]["user_markdown"])
            self.assertEqual(len(list(state_dir.glob("*.json"))), 1)

            # (c) Same-turn tool-loop re-invocation (same input, higher invocationNum) -> {}
            r_loop = _run_mode_hook(
                "PreInvocation",
                {
                    "conversationId": "conv-a",
                    "lastUserInput": "/research-scientist audit my low-resource ASR experiment",
                    "invocationNum": 2,
                    "initialNumSteps": 7,
                    "cwd": str(ws),
                },
                state_dir,
            )
            self.assertEqual(json.loads(r_loop.stdout), {})

            # (d) Distinct conversationId remains unlocked -> {}
            r_other = _run_mode_hook(
                "PreInvocation",
                {"conversationId": "conv-other", "lastUserInput": "Hello world", "invocationNum": 1, "initialNumSteps": 1, "cwd": str(ws)},
                state_dir,
            )
            self.assertEqual(json.loads(r_other.stdout), {})

            # (e) Follow-up turn 1 -> {}, follow-up turn 2 -> periodic reminder
            rt1 = _run_mode_hook(
                "PreInvocation",
                {"conversationId": "conv-a", "lastUserInput": "Follow up question 1", "invocationNum": 1, "initialNumSteps": 10, "cwd": str(ws)},
                state_dir,
            )
            self.assertEqual(json.loads(rt1.stdout), {}, "Unexpected reminder on follow-up turn 1")

            r_periodic = _run_mode_hook(
                "PreInvocation",
                {"conversationId": "conv-a", "lastUserInput": "Follow up question 2", "invocationNum": 1, "initialNumSteps": 12, "cwd": str(ws)},
                state_dir,
            )
            periodic_out = json.loads(r_periodic.stdout)
            self.assertIn("REMINDER", periodic_out["injectSteps"][0]["systemMessage"]["systemMessage"])

            steps = 12

            # (f) Context compaction (initialNumSteps drops) triggers immediate refresh
            r_compact = _run_mode_hook(
                "PreInvocation",
                {"conversationId": "conv-a", "lastUserInput": "Continue after compact", "invocationNum": 1, "initialNumSteps": 4, "cwd": str(ws)},
                state_dir,
            )
            compact_out = json.loads(r_compact.stdout)
            self.assertIn("compaction", compact_out["injectSteps"][0]["systemMessage"]["systemMessage"].lower())

            # (g) /research-off deactivates lock, then subsequent turns stay {}
            r_off = _run_mode_hook(
                "PreInvocation",
                {"conversationId": "conv-a", "lastUserInput": "/research-off", "invocationNum": 1, "initialNumSteps": 6, "cwd": str(ws)},
                state_dir,
            )
            off_out = json.loads(r_off.stdout)
            self.assertIn("DEACTIVATED", off_out["injectSteps"][0]["systemMessage"]["systemMessage"])
            self.assertIn("TẮT", off_out["injectSteps"][0]["systemMessage"]["metadata"]["user_markdown"])

            r_after_off = _run_mode_hook(
                "PreInvocation",
                {"conversationId": "conv-a", "lastUserInput": "Back to normal coding", "invocationNum": 1, "initialNumSteps": 8, "cwd": str(ws)},
                state_dir,
            )
            self.assertEqual(json.loads(r_after_off.stdout), {})

            # (h) Malformed/empty stdin -> fail-open {}
            r_bad = _run_mode_hook("PreInvocation", "not-json", state_dir)
            self.assertEqual(r_bad.returncode, 0)
            self.assertEqual(json.loads(r_bad.stdout), {})

    def test_stop_guard_only_enforced_when_locked(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_dir = root / "state"
            ws = root / "workspace"
            ws.mkdir()
            ps_file = ws / "project_state.json"

            # (a) Unlocked chat ignores corrupt project_state.json
            ps_file.write_text("{corrupt", encoding="utf-8")
            s_unlocked = _run_mode_hook(
                "Stop",
                {"conversationId": "conv-stop", "terminationReason": "NO_TOOL_CALL", "cwd": str(ws)},
                state_dir,
            )
            self.assertEqual(json.loads(s_unlocked.stdout), {})

            # Activate lock
            _run_mode_hook(
                "PreInvocation",
                {"conversationId": "conv-stop", "lastUserInput": "/research-scientist start", "invocationNum": 1, "initialNumSteps": 1, "cwd": str(ws)},
                state_dir,
            )

            # (b) Locked chat + corrupt project_state.json -> continue
            s_corrupt = _run_mode_hook(
                "Stop",
                {"conversationId": "conv-stop", "terminationReason": "NO_TOOL_CALL", "cwd": str(ws)},
                state_dir,
            )
            self.assertEqual(json.loads(s_corrupt.stdout).get("decision"), "continue")

            # (c) Locked chat + continuationActive or USER_CANCELED -> {}
            self.assertEqual(
                json.loads(
                    _run_mode_hook(
                        "Stop",
                        {"conversationId": "conv-stop", "continuationActive": True, "terminationReason": "NO_TOOL_CALL", "cwd": str(ws)},
                        state_dir,
                    ).stdout
                ),
                {},
            )
            self.assertEqual(
                json.loads(
                    _run_mode_hook(
                        "Stop",
                        {"conversationId": "conv-stop", "terminationReason": "USER_CANCELED", "cwd": str(ws)},
                        state_dir,
                    ).stdout
                ),
                {},
            )

            # (d) Valid project_state.json -> {}
            init_proc = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_STATE_SCRIPT),
                    "--state",
                    str(ps_file),
                    "--init",
                    "--project-id",
                    "p-mode-test",
                    "--subfield-preset",
                    "speech_audio",
                    "--compact",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(init_proc.returncode, 0, init_proc.stderr)
            self.assertEqual(
                json.loads(
                    _run_mode_hook(
                        "Stop",
                        {"conversationId": "conv-stop", "terminationReason": "NO_TOOL_CALL", "cwd": str(ws)},
                        state_dir,
                    ).stdout
                ),
                {},
            )

            # (e) Provenance violation when locked -> continue
            ps_file.write_text(
                json.dumps({
                    "schema": "research_scientist_project_state_v1",
                    "project_id": "p-bad",
                    "corpus_digests": {"P1": {"source_id": "P1", "access": "full_text", "locator": "tbd"}},
                }),
                encoding="utf-8",
            )
            s_prov = _run_mode_hook(
                "Stop",
                {"conversationId": "conv-stop", "terminationReason": "NO_TOOL_CALL", "cwd": str(ws)},
                state_dir,
            )
            self.assertEqual(json.loads(s_prov.stdout).get("decision"), "continue")

            # (f) After /research-off -> {} even with provenance violation
            _run_mode_hook(
                "PreInvocation",
                {"conversationId": "conv-stop", "lastUserInput": "/research-off", "invocationNum": 1, "initialNumSteps": 5, "cwd": str(ws)},
                state_dir,
            )
            s_after_off = _run_mode_hook(
                "Stop",
                {"conversationId": "conv-stop", "terminationReason": "NO_TOOL_CALL", "cwd": str(ws)},
                state_dir,
            )
            self.assertEqual(json.loads(s_after_off.stdout), {})

    def test_stop_transcript_firewall(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_dir = root / "state"
            ws = root / "workspace"
            ws.mkdir()
            tp = root / "transcript.jsonl"

            def _write_transcript(content: str) -> None:
                recs = [
                    {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "tool_calls": [{"id": "t1"}]},
                    {"step_index": 2, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE", "content": content},
                ]
                tp.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")

            hype_msg = (
                "Ý tưởng tuyệt vời! Đây là PHÁT HIỆN ĐỘT PHÁ hoàn toàn sạch bóng biến nhiễu "
                "và không một Reviewer nào bắt bẻ được."
            )
            _write_transcript(hype_msg)

            # (e) Skips unlocked conversation
            s_unlocked = _run_mode_hook(
                "Stop",
                {"conversationId": "conv-fw", "terminationReason": "NO_TOOL_CALL", "cwd": str(ws), "transcriptPath": str(tp)},
                state_dir,
            )
            self.assertEqual(json.loads(s_unlocked.stdout), {})

            # Activate lock
            _run_mode_hook(
                "PreInvocation",
                {"conversationId": "conv-fw", "lastUserInput": "/research-scientist audit", "invocationNum": 1, "initialNumSteps": 1, "cwd": str(ws)},
                state_dir,
            )

            # (a) Catches unquoted Vietnamese hype/overclaims
            s_blocked = _run_mode_hook(
                "Stop",
                {"conversationId": "conv-fw", "terminationReason": "NO_TOOL_CALL", "cwd": str(ws), "transcriptPath": str(tp)},
                state_dir,
            )
            out_blocked = json.loads(s_blocked.stdout)
            self.assertEqual(out_blocked.get("decision"), "continue")
            self.assertIn("PHÁT HIỆN ĐỘT PHÁ", out_blocked.get("reason", ""))

            # (d) Respects continuationActive: true (max 1 retry)
            s_cont = _run_mode_hook(
                "Stop",
                {"conversationId": "conv-fw", "continuationActive": True, "terminationReason": "NO_TOOL_CALL", "cwd": str(ws), "transcriptPath": str(tp)},
                state_dir,
            )
            self.assertEqual(json.loads(s_cont.stdout), {})

            # (b) Ignores quoted/backticked/fenced examples
            quoted_msg = (
                "Các cụm như \"PHÁT HIỆN ĐỘT PHÁ\" hoặc `hoàn toàn sạch bóng biến nhiễu` cần bị cấm.\n"
                "> không một Reviewer nào bắt bẻ được\n"
                "```text\nÝ tưởng tuyệt vời\n```\n"
            )
            _write_transcript(quoted_msg)
            s_quoted = _run_mode_hook(
                "Stop",
                {"conversationId": "conv-fw", "terminationReason": "NO_TOOL_CALL", "cwd": str(ws), "transcriptPath": str(tp)},
                state_dir,
            )
            self.assertEqual(json.loads(s_quoted.stdout), {})

            # (c) Allows cold Vietnamese critique
            cold_msg = (
                "### Verified Facts & Receipts\n"
                "Đã đo trên 982 câu NXB v3.\n\n"
                "### Strongest Confounders & Reviewer #2 Kill-Shots\n"
                "Chưa tách được biến nhiễu từ chính tả ở encoder và thiếu đối chứng LLM đa ngữ.\n"
            )
            _write_transcript(cold_msg)
            s_clean = _run_mode_hook(
                "Stop",
                {"conversationId": "conv-fw", "terminationReason": "NO_TOOL_CALL", "cwd": str(ws), "transcriptPath": str(tp)},
                state_dir,
            )
            self.assertEqual(json.loads(s_clean.stdout), {})


if __name__ == "__main__":
    unittest.main()
