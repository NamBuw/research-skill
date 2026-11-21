# Install and use

This skill uses the open Agent Skills folder format: `SKILL.md` plus optional references. It has been installed for the current user in:

- **Codex:** `~/.agents/skills/research-scientist/`
- **Gemini CLI:** `~/.agents/skills/research-scientist/` (the current Gemini CLI documents `~/.agents/skills/` as an alias for user skills)
- **Claude Code:** `~/.claude/skills/research-scientist/`

Codex and Gemini share the canonical `.agents/skills` directory. Claude Code's user-level directory is mirrored from that canonical copy. If you edit the skill later, update both folders:

```bash
cp -a ~/.agents/skills/research-scientist/. ~/.claude/skills/research-scientist/
```

Start a new session or refresh the skill list. On the locally checked Gemini CLI 0.65.0, `gemini skills list` reported `research-scientist [Enabled]` at `~/.agents/skills/research-scientist/SKILL.md`; its interactive `/skills list` and `/skills reload` commands are also available. Codex and Claude Code discover user skills from their documented directories. The agent still needs appropriate search/PDF/database tools to perform live research. The skill adapts to available tools and does not install or assume a particular backend.

## Package contents

- `SKILL.md` — router and core evidence rules, loaded when the skill activates.
- `references/gap-audit.md` — mandatory detailed gate for gap/novelty tasks.
- `references/research-workflow.md` — review designs, search, evidence, question and study workflows.
- `references/artifact-templates.md` — formats for durable, auditable research artifacts.
- `references/repository-landscape.md` — source-reading provenance, outside the runtime workflow.
- `scripts/search_papers.py` — bounded six-source scholarly discovery with source-status logging.
- `scripts/search_campaign.py` — sequential multi-query discovery campaign with query-family and known-seed provenance; see `references/search-campaign.example.json`.
- `scripts/citation_trails.py` — bounded OpenAlex one-hop backward/forward citation leads for a verified work ID.
- `scripts/local_evidence.py` — local lexical passage leads from text and MinerU Content List V2 exports.
- `scripts/extract_pdf_blocks.py` — optional local text-based PDF block/page extraction using PyMuPDF; no OCR.
- `scripts/check_evidence_map.py` — structural question, passage, claim, and outline links.
- `scripts/check_gap_record.py` — structural evidence/source/kill-search checks for a proposed gap.
- `scripts/check_experiment_manifest.py` — structural run-receipt and baseline/candidate comparison checks.
- `scripts/check_question_card.py` — structural RQ/rival/measurement check; an example JSON card is under `references/`.
- `scripts/check_venue_plan.py` — deadline conversion and fee completeness; official facts still require review.
- `scripts/capture_venue_sources.py` — dated HTML/plain/PDF snapshots of supplied venue source URLs.
- `scripts/check_venue_sources.py` — exact quote matching from dossier facts to captured source text; interpretation still requires review.
- `scripts/venue_leads.py` — bounded related-paper publication-source leads, requiring official venue verification.
- `scripts/check_manuscript_ledger.py` — structural claim, numeric fact, and method-lineage checks for a manuscript.
- `scripts/compare_scorecards.py` — declared reading/locator basis and weight-sensitivity checks across papers.
- `scripts/score_math.py` — guarded score arithmetic.
- `scripts/audit_alignment.py` — optional read-only CSV identity/split diagnostic.
- `modules/kdense-scientific-writing/` — bundled MIT-licensed offline paper-writing toolkit with workspace, claim, reference, consistency, reporting, authorship and lint commands. See its `VENDOR.md` and `LICENSE.md`; invoke it through this skill's paper-production workflow.
- `modules/humanizer/` — bundled MIT-licensed 26-pattern prose-editing catalog, applied after scientific checks through this skill's writing workflow.
- `modules/researchradar/` — bundled MIT-licensed public-review, paper, citation, limitation and exact-quote tools, used as a gap-evidence lane. Network routes have source-specific access and optional large datasets; see its `VENDOR.md`.
- `agents/openai.yaml` — optional Codex UI metadata.

The folder is self-contained and has no hard dependency on a specific external service. The paper-writing toolkit is a bundled copy of the named upstream MIT module with its license and source notice; the rest of the skill's scripts are written for this repository.

The core checkers use Python's standard library. `scripts/extract_pdf_blocks.py` additionally needs PyMuPDF for local text-based PDF extraction; if it is unavailable, use an authorized extractor and pass its text or MinerU Content List V2 export to `scripts/local_evidence.py`. OCR or reliable table/formula parsing requires an appropriate parser and visual verification; this package does not bundle MinerU model weights.

## Credentials and capability checks

This package does not contain a Semantic Scholar key. For Semantic Scholar API work, ask the user to supply `S2_API_KEY` through the runtime's secret/environment mechanism. Check presence without printing its value. Do not store keys in skill text, agent prompts, logs, commits, or generated reports. Send a provided key only to the official API in its authentication header.

Suggested disclosure: “Without an S2 key, shared access/rate limits may reduce the Semantic Scholar papers and citation trails we can inspect within the available time. Other sources may offset some loss; I will report which searches completed and which coverage remains unchecked.” A key improves access conditions; it does not guarantee scientific quality or completeness. Continue independent searches while awaiting a key. Check each alternative source's own access requirements.

The package also includes modular references for prior-art retrieval, failure diagnosis, scoring and venue planning, scientific integrity, Humanizer-based scholarly editing, agent orchestration, and quality evaluation. Load only the modules needed. Parallel work uses the host agent's available delegation tools, with a sequential fallback; no framework-specific agent API is assumed.
