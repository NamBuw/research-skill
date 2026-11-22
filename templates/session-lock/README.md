# Research Scientist Session-Lock Template Pack

Drop this template pack into any **research project workspace** to keep entire multi-turn conversations anchored to the `research-scientist` Hub-and-Spoke skill suite (even across long chats, context compaction, and reopened sessions).

> **Keep these files out of the skill installer repo itself.** Copy them only into the project directories where you want every turn locked to the research workflow.

## What Is Included

| File | Discovered By | Role |
|---|---|---|
| `AGENTS.md` | Antigravity, Codex CLI, Gemini CLI | `always_on` workspace rule enforcing startup anchor, 6-spoke phase routing, speech/cross-domain checks, F1 zero sycophancy, read-before-cite, zero fabrication, and F19 parsimony. |
| `CLAUDE.md` | Claude Code | Thin adapter directing Claude Code to follow `./AGENTS.md` and load `~/.claude/skills/research-scientist/SKILL.md`. |
| `.agents/hooks.json` | Antigravity | Enables the `research-scientist-session-lock` lifecycle hooks (`SessionStart` + `Stop`). |
| `.agents/hooks/session_lock_hook.py` | Antigravity hook runner | Pure-stdlib hook script that injects current `project_state.json` context on `SessionStart` and guards `project_state.json` schema/provenance invariants on `Stop` (with loop & cancellation safeguards). |

## Install into a Research Project (1 Command)

Run from the root of `research-skill-release` (use `-rn` so existing project files are never overwritten):

```bash
cp -rn templates/session-lock/. /path/to/your-research-project/
```

Verify executable permissions if needed:

```bash
chmod +x /path/to/your-research-project/.agents/hooks/session_lock_hook.py
```

## How It Behaves

1. **Antigravity / Codex / Gemini CLI:** Automatically loads `AGENTS.md` on every turn. In Antigravity, `.agents/hooks.json` also fires `SessionStart` to summarize `project_state.json` (or prompt initialization) and `Stop` (`NO_TOOL_CALL` only, skipped when `continuationActive` is true) to prevent finishing with corrupt `project_state.json`, `full_text` digests lacking a locator, or untagged `isomorphic_transfer_leads`.
2. **Claude Code:** Automatically loads `CLAUDE.md`, which delegates to `./AGENTS.md` and `~/.claude/skills/research-scientist/SKILL.md`.

## Temporarily Disabling Hooks

To keep `AGENTS.md` active while turning off lifecycle hooks in `.agents/hooks.json`, set `"enabled": false` under `"research-scientist-session-lock"`.
