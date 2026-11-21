---
name: research-paper-writing
description: "Draft and audit publication-grade AI/CS/CV/NLP papers with Humanizer §1-§26 lint, anti-fabrication/anti-padding/anti-grandiose ledger checks, figure/palette QA, double-blind anonymization, and arXiv/BibTeX preflight."
---

# Research Paper Writing, Figures & Submission Preflight

Produce concise, honest, publication-ready AI/CS/CV/NLP manuscripts. Refuse to polish drafts lacking verified run receipts, source locators, or parsimony/ablation evidence.

## Four Mandatory Manuscript Gates

1. **Anti-fabrication:** Trace every number, ablation, and citation to disk receipts and primary sources. Zero invented results or citations.
2. **Anti-padding & compression (`Research-Paper-Writing-Skills` + `codex-claude-academic-skills`, MIT):** Enforce reverse outlining (one message per paragraph), module motivation triad (need -> mechanism -> why this design), and 7 compression patterns (cut throat-clearing, unquantified adjectives like *"significant/innovative/novel"*, and off-RQ background).
3. **Anti-grandiose & Humanizer:** Ban coined names (`-Net`, `-Cascade`, `Unified Framework`) on stitched/reused parts, problem inflation, sycophancy, and Humanizer §1–§26 AI tells.
4. **Visual, Anonymization & BibTeX Preflight:** Require colorblind-safe vector/high-DPI figures (no JPEG, no Type3, no rainbow), zero double-blind leaks, stripped `%` comments for arXiv, and protected acronym caps (`BERT`, `ResNet`, `3D`).

## Shared Tools (`../research-scientist/scripts/` & `modules/`)

| Gate | Shared Tool | Output / Exit Contract |
|---|---|---|
| Prose & AI-tell lint | [humanizer_lint.py](../research-scientist/scripts/humanizer_lint.py) (`--strict`, `--compare-baseline`, `--compact`) | Zero risks, zero sycophancy, preserved claims |
| Lineage & numeric ledger | [check_manuscript_ledger.py](../research-scientist/scripts/check_manuscript_ledger.py) (`--ledger`, `--manuscript`, `--sources-dir`) | Verified numbers, quotes, and parsimony/ablation |
| Figure & palette QA | [check_figure_qa.py](../research-scientist/scripts/check_figure_qa.py) (`palette`, `figure`) | WCAG + delta-L*, blocks JPEG/Type3/rainbow |
| Anonymize, arXiv, BibTeX | [check_submission_preflight.py](../research-scientist/scripts/check_submission_preflight.py) (`anonymize`, `arxiv-clean`, `bibtex`) | Zero leaks, unused/comment hygiene, protected caps |
| K-Dense writing suite | [audit_claims.py](../research-scientist/modules/kdense-scientific-writing/scripts/audit_claims.py), [check_references.py](../research-scientist/modules/kdense-scientific-writing/scripts/check_references.py) | Claim-evidence & citation consistency |

Load [paper writing & preflight guide](references/paper-writing-preflight-guide.md) on demand for the 7 compression patterns and preflight commands.
