# Install and use

This skill uses the open Agent Skills folder format: `SKILL.md` plus optional references. It has been installed for the current user in:

- **Codex:** `~/.agents/skills/research-scientist/`
- **Gemini CLI:** `~/.agents/skills/research-scientist/` (the current Gemini CLI documents `~/.agents/skills/` as an alias for user skills)
- **Claude Code:** `~/.claude/skills/research-scientist/`

Codex and Gemini share the canonical `.agents/skills` directory. Claude Code's user-level directory is mirrored from that canonical copy. If you edit the skill later, update both folders:

```bash
cp -a ~/.agents/skills/research-scientist/. ~/.claude/skills/research-scientist/
```

Start a new session or refresh the skill list. Gemini CLI supports `/skills list` and `/skills reload`; Codex and Claude Code discover user skills from their documented directories. The agent still needs appropriate search/PDF/database tools to perform live research. The skill adapts to available tools and does not install or assume a particular backend.

## Package contents

- `SKILL.md` — router and core evidence rules, loaded when the skill activates.
- `references/gap-audit.md` — mandatory detailed gate for gap/novelty tasks.
- `references/research-workflow.md` — review designs, search, evidence, question and study workflows.
- `references/artifact-templates.md` — formats for durable, auditable research artifacts.
- `references/repository-landscape.md` — source-reading provenance, outside the runtime workflow.
- `scripts/search_papers.py` — bounded four-source scholarly discovery with source-status logging.
- `scripts/check_question_card.py` — structural RQ/rival/measurement check; an example JSON card is under `references/`.
- `scripts/score_math.py` — guarded score arithmetic.
- `scripts/audit_alignment.py` — optional read-only CSV identity/split diagnostic.
- `agents/openai.yaml` — optional Codex UI metadata.

The folder is self-contained; it contains no copied project code and no hard dependency on a specific external service.

## Credentials and capability checks

This package does not contain a Semantic Scholar key. For Semantic Scholar API work, ask the user to supply `S2_API_KEY` through the runtime's secret/environment mechanism. Check presence without printing its value. Do not store keys in skill text, agent prompts, logs, commits, or generated reports. Send a provided key only to the official API in its authentication header.

Suggested disclosure: “Without an S2 key, shared access/rate limits may reduce the Semantic Scholar papers and citation trails we can inspect within the available time. Other sources may offset some loss; I will report which searches completed and which coverage remains unchecked.” A key improves access conditions; it does not guarantee scientific quality or completeness. Continue independent searches while awaiting a key. Check each alternative source's own access requirements.

The package also includes modular references for prior-art retrieval, failure diagnosis, scoring and venue planning, scientific integrity, Humanizer-based scholarly editing, agent orchestration, and quality evaluation. Load only the modules needed. Parallel work uses the host agent's available delegation tools, with a sequential fallback; no framework-specific agent API is assumed.
