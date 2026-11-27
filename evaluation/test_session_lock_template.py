"""Unit & contract tests for templates/session-lock workspace rule + hook pack."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = REPO_ROOT / "templates" / "session-lock"
HOOK_SCRIPT = TEMPLATE_DIR / ".agents" / "hooks" / "session_lock_hook.py"
PROJECT_STATE_SCRIPT = REPO_ROOT / "research-scientist" / "scripts" / "project_state.py"


def _run_hook(
    hook_path: Path,
    event: str,
    payload: str | dict[str, object],
    *,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    stdin_text = payload if isinstance(payload, str) else json.dumps(payload)
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(hook_path), "--event", event],
        input=stdin_text,
        cwd=str(cwd or hook_path.parents[1]),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


class TestSessionLockTemplate(unittest.TestCase):
    def test_template_files_present_bounded_and_not_at_repo_root(self) -> None:
        expected = (
            TEMPLATE_DIR / "AGENTS.md",
            TEMPLATE_DIR / "CLAUDE.md",
            TEMPLATE_DIR / "README.md",
            TEMPLATE_DIR / ".agents" / "hooks.json",
            HOOK_SCRIPT,
        )
        for path in expected:
            self.assertTrue(path.is_file(), f"Missing template file: {path}")

        agents_bytes = (TEMPLATE_DIR / "AGENTS.md").read_bytes()
        self.assertLess(len(agents_bytes), 24000, "AGENTS.md exceeds 24 KB rule cap")

        agents_text = agents_bytes.decode("utf-8")
        for needle in (
            "research-scientist/SKILL.md",
            "project_state.json",
            "speech_audio",
            "isomorphic_transfer_leads",
            "metadata_only",
        ):
            self.assertIn(needle, agents_text)

        claude_text = (TEMPLATE_DIR / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("AGENTS.md", claude_text)
        self.assertIn("research-scientist/SKILL.md", claude_text)

        self.assertFalse((REPO_ROOT / "AGENTS.md").exists(), "Repo root must not activate AGENTS.md")
        self.assertFalse((REPO_ROOT / "CLAUDE.md").exists(), "Repo root must not activate CLAUDE.md")
        self.assertFalse(
            (REPO_ROOT / ".agents" / "hooks.json").exists(),
            "Repo root must not activate .agents/hooks.json",
        )

    def test_hooks_json_schema_and_executable_bit(self) -> None:
        hooks_cfg = json.loads((TEMPLATE_DIR / ".agents" / "hooks.json").read_text(encoding="utf-8"))
        self.assertIn("research-scientist-session-lock", hooks_cfg)
        entry = hooks_cfg["research-scientist-session-lock"]
        self.assertIs(entry.get("enabled"), True)

        for event in ("SessionStart", "Stop"):
            handlers = entry.get(event)
            self.assertIsInstance(handlers, list)
            self.assertEqual(len(handlers), 1)
            h = handlers[0]
            self.assertEqual(h.get("type"), "command")
            cmd = str(h.get("command") or "")
            self.assertIn("./hooks/session_lock_hook.py", cmd)
            self.assertIn(f"--event {event}", cmd)
            resolved = (TEMPLATE_DIR / ".agents" / "hooks" / "session_lock_hook.py").resolve()
            self.assertTrue(resolved.is_file())

        mode = HOOK_SCRIPT.stat().st_mode
        self.assertTrue(mode & stat.S_IXUSR, "session_lock_hook.py should be executable")

    def test_session_start_absent_valid_and_corrupt_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            # (a) Absent project_state.json
            p1 = _run_hook(HOOK_SCRIPT, "SessionStart", {"cwd": str(ws)})
            self.assertEqual(p1.returncode, 0, p1.stderr)
            out1 = json.loads(p1.stdout)
            msg1 = out1["injectSteps"][0]["systemMessage"]["systemMessage"]
            self.assertIn("No project_state.json found", msg1)
            self.assertIn("research-scientist", msg1)

            # (b) Real project_state.py --init output
            state_file = ws / "project_state.json"
            init_proc = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_STATE_SCRIPT),
                    "--state",
                    str(state_file),
                    "--init",
                    "--project-id",
                    "jrai-speech-01",
                    "--subfield-preset",
                    "speech_audio",
                    "--target-venue",
                    "TALLIP",
                    "--compact",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(init_proc.returncode, 0, init_proc.stderr)
            p2 = _run_hook(HOOK_SCRIPT, "SessionStart", {"workspacePaths": [str(ws)]})
            self.assertEqual(p2.returncode, 0, p2.stderr)
            out2 = json.loads(p2.stdout)
            msg2 = out2["injectSteps"][0]["systemMessage"]["systemMessage"]
            self.assertIn("jrai-speech-01", msg2)
            self.assertIn("speech_audio", msg2)
            self.assertIn("TALLIP", msg2)

            # (c) Corrupt project_state.json
            state_file.write_text("{corrupt json", encoding="utf-8")
            p3 = _run_hook(HOOK_SCRIPT, "SessionStart", {"cwd": str(ws)})
            self.assertEqual(p3.returncode, 0, p3.stderr)
            out3 = json.loads(p3.stdout)
            msg3 = out3["injectSteps"][0]["systemMessage"]["systemMessage"]
            self.assertIn("WARNING", msg3)
            self.assertIn("invalid", msg3.casefold())

    def test_stop_hook_guards_and_safeguards(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            state_file = ws / "project_state.json"

            # (a) No project_state.json -> {}
            r_abs = _run_hook(HOOK_SCRIPT, "Stop", {"cwd": str(ws), "terminationReason": "NO_TOOL_CALL"})
            self.assertEqual(r_abs.returncode, 0)
            self.assertEqual(json.loads(r_abs.stdout), {})

            # (b) Valid project_state.json -> {}
            init_proc = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_STATE_SCRIPT),
                    "--state",
                    str(state_file),
                    "--init",
                    "--project-id",
                    "proj-valid",
                    "--subfield-preset",
                    "speech_audio",
                    "--compact",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(init_proc.returncode, 0, init_proc.stderr)
            r_valid = _run_hook(HOOK_SCRIPT, "Stop", {"cwd": str(ws), "terminationReason": "NO_TOOL_CALL"})
            self.assertEqual(r_valid.returncode, 0)
            self.assertEqual(json.loads(r_valid.stdout), {})

            # (c) Corrupt project_state.json -> decision: continue
            state_file.write_text("{broken", encoding="utf-8")
            r_corrupt = _run_hook(HOOK_SCRIPT, "Stop", {"cwd": str(ws), "terminationReason": "NO_TOOL_CALL"})
            self.assertEqual(r_corrupt.returncode, 0)
            corrupt_out = json.loads(r_corrupt.stdout)
            self.assertEqual(corrupt_out.get("decision"), "continue")
            self.assertIn("corrupt", corrupt_out.get("reason", "").casefold())

            # (d) continuationActive: true -> {} even when corrupt
            r_cont = _run_hook(
                HOOK_SCRIPT,
                "Stop",
                {"cwd": str(ws), "continuationActive": True, "terminationReason": "NO_TOOL_CALL"},
            )
            self.assertEqual(r_cont.returncode, 0)
            self.assertEqual(json.loads(r_cont.stdout), {})

            # (e) terminationReason: USER_CANCELED -> {} even when corrupt
            r_cancel = _run_hook(
                HOOK_SCRIPT,
                "Stop",
                {"cwd": str(ws), "terminationReason": "USER_CANCELED"},
            )
            self.assertEqual(r_cancel.returncode, 0)
            self.assertEqual(json.loads(r_cancel.stdout), {})

            # (f) Provenance violations -> decision: continue
            bad_state = {
                "schema": "research_scientist_project_state_v1",
                "project_id": "proj-bad-prov",
                "corpus_digests": {
                    "P1": {"source_id": "P1", "access": "full_text", "locator": ""}
                },
                "gaps": {
                    "G1": {
                        "id": "G1",
                        "lenses_f32": {
                            "isomorphic_transfer_leads": [
                                {"discipline": "Signal Processing", "status": "confirmed", "evidence_level": "verified"}
                            ]
                        },
                    }
                },
            }
            state_file.write_text(json.dumps(bad_state), encoding="utf-8")
            r_prov = _run_hook(HOOK_SCRIPT, "Stop", {"cwd": str(ws), "terminationReason": "NO_TOOL_CALL"})
            self.assertEqual(r_prov.returncode, 0)
            prov_out = json.loads(r_prov.stdout)
            self.assertEqual(prov_out.get("decision"), "continue")
            self.assertIn("locator", prov_out.get("reason", ""))
            self.assertIn("isomorphic_transfer_leads", prov_out.get("reason", ""))

            # (g) Malformed/empty stdin -> fail-open {} with exit 0
            r_bad_stdin = _run_hook(HOOK_SCRIPT, "Stop", "not-json-at-all")
            self.assertEqual(r_bad_stdin.returncode, 0)
            self.assertEqual(json.loads(r_bad_stdin.stdout), {})

    def test_cp_rn_deployment_and_relative_hook_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target_ws = Path(tmpdir) / "my_research_project"
            target_ws.mkdir()
            cp_proc = subprocess.run(
                ["cp", "-rn", f"{TEMPLATE_DIR}/.", str(target_ws)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(cp_proc.returncode, 0, cp_proc.stderr)
            self.assertTrue((target_ws / "AGENTS.md").is_file())
            self.assertTrue((target_ws / "CLAUDE.md").is_file())
            self.assertTrue((target_ws / ".agents" / "hooks.json").is_file())
            copied_hook = target_ws / ".agents" / "hooks" / "session_lock_hook.py"
            self.assertTrue(copied_hook.is_file())

            # Execute from <target_ws>/.agents/ with relative command path matching hooks.json
            hooks_dir = target_ws / ".agents"
            res = subprocess.run(
                [sys.executable, "./hooks/session_lock_hook.py", "--event", "SessionStart"],
                input=json.dumps({"cwd": str(target_ws)}),
                cwd=str(hooks_dir),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(res.returncode, 0, res.stderr)
            out = json.loads(res.stdout)
            self.assertIn("injectSteps", out)
            msg = out["injectSteps"][0]["systemMessage"]["systemMessage"]
            self.assertIn(str(target_ws.resolve()), msg)

            # Verify cp -rn preserves pre-existing AGENTS.md
            shutil.rmtree(target_ws)
            target_ws.mkdir()
            custom_agents = "# Existing Project Rules\nKeep me.\n"
            (target_ws / "AGENTS.md").write_text(custom_agents, encoding="utf-8")
            cp2 = subprocess.run(
                ["cp", "-rn", f"{TEMPLATE_DIR}/.", str(target_ws)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(cp2.returncode, 0, cp2.stderr)
            self.assertEqual((target_ws / "AGENTS.md").read_text(encoding="utf-8"), custom_agents)

    def test_stop_transcript_firewall(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ws = root / "ws"
            ws.mkdir()
            tp = root / "transcript.jsonl"

            def _write_transcript(content: str) -> None:
                recs = [
                    {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE", "content": content},
                ]
                tp.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")

            _write_transcript("Bài học triệu đô này giải quyết triệt để vấn đề.")
            res_bad = _run_hook(
                HOOK_SCRIPT,
                "Stop",
                {"cwd": str(ws), "terminationReason": "NO_TOOL_CALL", "transcriptPath": str(tp)},
            )
            self.assertEqual(res_bad.returncode, 0)
            out_bad = json.loads(res_bad.stdout)
            self.assertEqual(out_bad.get("decision"), "continue")
            self.assertIn("giải quyết triệt để", out_bad.get("reason", ""))

            _write_transcript("Cần loại bỏ cụm `giải quyết triệt để` khi phản biện.\n### Verified Facts & Receipts\nChưa chạy thử.")
            res_ok = _run_hook(
                HOOK_SCRIPT,
                "Stop",
                {"cwd": str(ws), "terminationReason": "NO_TOOL_CALL", "transcriptPath": str(tp)},
            )
            self.assertEqual(res_ok.returncode, 0)
            self.assertEqual(json.loads(res_ok.stdout), {})


if __name__ == "__main__":
    unittest.main()
