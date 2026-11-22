# Install and Use (`research-scientist` Hub-and-Spoke Suite)

This repository packages a **7-skill Hub-and-Spoke suite** in the open Agent Skills format (`SKILL.md` + `references/` + `agents/openai.yaml`):

- **Parent Orchestrator:** `research-scientist/` (owns all shared `scripts/`, `modules/`, `THIRD_PARTY_NOTICES.md`, and cross-cutting `references/`)
- **Six Sibling Specialist Sub-Skills** (must be installed alongside `research-scientist/` in the same skills parent directory so `../research-scientist/scripts/` and `../research-scientist/modules/` resolve cleanly without duplicating code):
  1. `research-precedent-corpus/` — multi-source retrieval, citation graph, PDF/OCR blocks, PaperQA2 corpus Q&A
  2. `research-gap-rq-audit/` — STORM exploration, gap pipeline, engineering-vs-gap triage, parsimony gate, RQ cards
  3. `research-experiment-coding/` — 4-phase debugging, TDD, verification-before-completion, PyTorch hygiene, `repro`, `rliable`, contamination, SHA-256 receipts
  4. `research-novelty-venue/` — /10 scorecards, `>=5` accepted-panel novelty, live CFP/fee verification, rebuttal budget/coverage & H1–H17 fairness
  5. `research-paper-writing/` — Humanizer §1–§26 lint, anti-fabrication/anti-padding/anti-grandiose ledger, figure QA, anonymization, arXiv/BibTeX preflight
  6. `research-user-report/` — concise, plain-language multilingual LaTeX-to-PDF user report (`report_latex_pdf.py`)

## Multi-Skill Install & Sync (`sync_skills.py`)

Use `research-scientist/scripts/sync_skills.py` to install or update all 7 skills together with verified relative links (`shared_scripts_resolved: true`) across Codex, Claude Code, and Gemini CLI:

1. **Preview the sync (dry run):**

   ```bash
   python3 research-scientist/scripts/sync_skills.py --dry-run --compact
   ```

2. **Sync to default detected CLI directories** (`~/.agents/skills` for Codex/Gemini CLI, `~/.claude/skills` for Claude Code, plus `~/.codex/skills` if that directory exists):

   ```bash
   python3 research-scientist/scripts/sync_skills.py --compact
   ```

3. **Or explicitly target Codex, Claude Code, and Gemini CLI directories:**

   ```bash
   python3 research-scientist/scripts/sync_skills.py \
     --target-dir ~/.codex/skills \
     --target-dir ~/.claude/skills \
     --target-dir ~/.agents/skills \
     --compact
   ```

4. **Verify installed parity non-destructively (exits `0` if in sync, `1` if out of sync):**

   ```bash
   python3 research-scientist/scripts/sync_skills.py --suite-root . --check --compact --out /tmp/sync-check.json
   ```

Start a new session or refresh the skill list in your client (e.g., `gemini skills list` or `/skills reload` in Gemini CLI).

## Post-Install Verification (`claim_audit.py`)

Verify documentation, script/flag consistency, `agents/openai.yaml` metadata, token budgets (`<50` lines / `<900` est. tokens per `SKILL.md`), and non-duplication after syncing:

```bash
# Verify repository suite (all 7 skills) + README.md
python3 research-scientist/scripts/claim_audit.py --suite-root . --readme README.md --compact

# Verify parent skill + README.md
python3 research-scientist/scripts/claim_audit.py --root research-scientist --readme README.md --compact

# Verify installed copy (example: ~/.agents/skills)
python3 ~/.agents/skills/research-scientist/scripts/claim_audit.py --suite-root ~/.agents/skills --compact
```

Every check must exit `0` with `finding_count: 0`.

## Package Contents (`research-scientist/`)

- `SKILL.md` — lean Parent Orchestrator prompt, global zero-sycophancy / falsification-first / parsimony laws, and 6-spoke routing table.
- `agents/openai.yaml` — Codex UI metadata (present in `research-scientist/` and all 6 sibling sub-skills).
- `THIRD_PARTY_NOTICES.md` — consolidated MIT and Apache-2.0 attributions plus excluded/clean-room license boundaries.
- `references/` — modular on-demand workflow guides, schemas, fixtures, and `repository-landscape.md` (33-repo triage matrix).
- `scripts/` — 41 runnable Python CLIs supporting `--help` and `--compact` disk-offloaded workflows:
  - **Retrieval & Corpus (`research-precedent-corpus`):** `search_papers.py`, `search_campaign.py`, `resolve_fulltext.py`, `citation_trails.py`, `citation_graph.py`, `fulltext_mining.py`, `extract_pdf_blocks.py`, `local_evidence.py`, `check_evidence_map.py`
  - **Gap, RQ & Parsimony (`research-gap-rq-audit`):** `storm_explorer.py`, `gap_pipeline.py`, `check_gap_record.py`, `check_gap_campaign.py`, `check_question_card.py`, `check_ai_cs_research_plan.py`
  - **Experiment Coding & Rigor (`research-experiment-coding`):** `check_engineering_diagnostics.py`, `audit_alignment.py`, `check_experiment_manifest.py`, `check_experiment_rigor.py` (`repro`, `rliable`, `contamination`), `analyze_experiment_outcome.py`
  - **Novelty, Venue & Rebuttal (`research-novelty-venue`):** `venue_leads.py`, `venue_panel_collector.py`, `capture_venue_sources.py`, `check_venue_sources.py`, `check_venue_plan.py`, `compare_scorecards.py` (`paper`/`idea`), `compare_venue_novelty.py`, `score_math.py`, `triage_reviews.py` (`mock-review`, `post-reject`), `evaluate_submission.py`, `check_rebuttal.py` (`budget`, `coverage`)
  - **Paper Writing, Figures & Preflight (`research-paper-writing`):** `humanizer_lint.py`, `check_manuscript_ledger.py` (claims, lineage & argument audits), `check_artifact_readiness.py` (license, PII, repro, secrets, anonymization), `check_figure_qa.py` (`palette`, `figure`), `check_submission_preflight.py` (`anonymize`, `arxiv-clean`, `bibtex`)
  - **Multilingual User Report (`research-user-report`):** `report_latex_pdf.py`
  - **Suite Lifecycle, Auto-Builder & Sync (`research-scientist`):** `build_research_inputs.py`, `project_state.py`, `claim_audit.py`, `sync_skills.py`
- `modules/` — bundled MIT-licensed offline/tool suites (`kdense-scientific-writing/`, `kdense-peer-review/`, `kdense-scholar-evaluation/`, `kdense-hypothesis-generation/`, `kdense-literature-review/`, `humanizer/`, `researchradar/`), each with `VENDOR.md` and `LICENSE.md`.

## Runtime Dependencies, Optional Tools & API Keys

- **Core Python:** Most governance, gap/RQ, experiment-rigor, figure-QA, rebuttal, preflight, humanizer, scoring, and sync scripts run on Python 3 standard library.
- **XML & PDF parsing:** `search_papers.py` and `fulltext_mining.py` use `defusedxml`. PDF extraction (`extract_pdf_blocks.py`), PDF CFP snapshots (`capture_venue_sources.py`), PDF rebuttal page counts (`check_rebuttal.py`), and post-compile PDF verification (`report_latex_pdf.py`) use `PyMuPDF` (`fitz`). `extract_pdf_blocks.py` optionally uses `pdfplumber` (`--tables`) and `Pillow` + the `tesseract` binary (`--ocr`), or an externally installed `mineru` CLI (`--use-mineru`; zero MinerU source is bundled).
- **Optional external Khoj:** `local_evidence.py --khoj-url` connects over HTTP to a user-operated Khoj server (zero Khoj AGPL source is bundled).
- **Optional LaTeX engines for `report_latex_pdf.py`:** Automatically probes `xelatex` → `lualatex` → `pdflatex` (with `vntex` / T5 encoding support for Vietnamese diacritics when using `pdflatex` or Unicode fonts under `lualatex`/`xelatex`) and verifies extracted PDF text via `PyMuPDF`. If no LaTeX compiler is installed, `--tex-out` still writes the validated `.tex` source, while PDF compilation reports an explicit missing-engine error.
- **API keys & credentials:** No credentials are stored or bundled. Supply `S2_API_KEY` through your runtime environment for higher Semantic Scholar rate limits. Check presence without printing key values, and never commit secrets into skill files, logs, or reports.
