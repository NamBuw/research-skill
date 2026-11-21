# Bundled literature-review toolkit

This directory contains a curated subset of the `skills/literature-review` folder from [K-Dense Scientific Agent Skills](https://github.com/K-Dense-AI/scientific-agent-skills), snapshot `ec59a29a03d5c40f73ab40878df04860bc00e876`, inspected on 2026-11-21. The upstream folder's `SKILL.md` is stored as `UPSTREAM_SKILL.md` so this package has one agent entrypoint at `research-scientist/SKILL.md`. `LICENSE.md` is the upstream repository's MIT license and copyright notice.

Included files:
- `assets/review_template.md` and `references/` (5 Markdown guides: `citation_styles.md`, `core_workflow.md`, `database_strategies.md`, `example_workflow.md`, `search_and_citation.md`), copied without functional changes.
- `scripts/search_databases.py` (pure stdlib; offline local JSON array deduplication, year filtering, ranking, and JSON/Markdown/BibTeX formatting — does not query external databases), copied without functional changes.
- `scripts/verify_citations.py` (DOI registration lookup via `doi.org/api/handles/` and Crossref metadata lookup via `api.crossref.org/works/`): adapted with a `try ... except ImportError:` wrapper around `import requests` providing a pure-stdlib `urllib.request` fallback (including `http.client.HTTPException` parity and defensive Crossref `date-parts` parsing) while preserving `CitationVerifier.session` when `requests` is installed so both `requests` and offline/stdlib paths run cleanly.

Intentionally excluded upstream scripts (external binary/API dependencies unavailable or unconfigured in this bundle):
- `scripts/generate_pdf.py` (requires external `pandoc` and `xelatex` binaries).
- `scripts/generate_schematic.py` and `scripts/generate_schematic_ai.py` (require `OPENROUTER_API_KEY` and external OpenRouter API calls).

The root `research-scientist` skill owns multi-source paper discovery (`scripts/search_papers.py`, `scripts/search_campaign.py`) and citation/full-text verification. DOI registration and Crossref metadata checks do not prove that a citation supports a claim or screen for retractions. Check the upstream repository before importing later updates; do not silently replace these files or delete attribution.
