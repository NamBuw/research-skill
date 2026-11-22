# Claude Code Session Lock

For every turn in this workspace, read and strictly follow `./AGENTS.md`.

1. Load `~/.claude/skills/research-scientist/SKILL.md` (fallback: `~/.agents/skills/research-scientist/SKILL.md`) before responding to research tasks or resuming after compaction.
2. Persist and verify state in `./project_state.json` using the shared CLI tools under `research-scientist/scripts/`, using `--out` + `--compact` to avoid context bloat.
3. Enforce all Zero Sycophancy, Read-Before-Cite (`metadata_only` -> `ratings: null`), Zero Fabrication, Engineering-Before-Novelty, and F19 Parsimony rules stated in `./AGENTS.md`.
