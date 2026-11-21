# Paper Writing, Compression, Figure QA & Preflight (AI/CS/CV/NLP)

Load this guide only when drafting, tightening, visualizing, or packaging an AI/CS/CV/NLP manuscript.

## 1. ML/CV/NLP Structure & 7 Compression Patterns
- **Reverse outlining (`Research-Paper-Writing-Skills`):** Every paragraph delivers one clear claim supported by evidence; explain each module as *why needed -> exact mechanism -> why this minimal choice* (or drop it per Parsimony Gate).
- **7 Compression Patterns (`codex-claude-academic-skills`):**
  1. Delete filler openers (*"In recent years..."*, *"It is worth noting..."*).
  2. Replace unquantified praise (*"significant/innovative/state-of-the-art"*) with exact metrics and baselines.
  3. Collapse cross-section repetition (keep setup details in Experiments, contributions in Intro).
  4. Merge fragmented 1-sentence bullets into crisp prose when hierarchy adds no clarity.
  5. Convert passive nominalizations to direct active verbs (*"perform an evaluation of"* -> *"evaluate"*).
  6. Prune off-RQ background paragraphs and redundant transition sentences.
  7. Keep limitations calibrated and explicit without hiding weaknesses.

## 2. Executable Writing, Figure & Preflight Gates
- Prose & baseline claim preservation: `python3 ../../research-scientist/scripts/humanizer_lint.py draft.md --strict --compare-baseline orig.md --compact`
- Method lineage & numeric ledger: `python3 ../../research-scientist/scripts/check_manuscript_ledger.py --ledger ledger.json --manuscript draft.md --sources-dir sources/`
- Palette & figure QA: `python3 ../../research-scientist/scripts/check_figure_qa.py palette --palette okabe_ito --fail-on any --compact` and `python3 ../../research-scientist/scripts/check_figure_qa.py figure figs/ --strict --compact`
- Double-blind / camera-ready scan: `python3 ../../research-scientist/scripts/check_submission_preflight.py anonymize paper.tex --mode submission --strict --compact`
- arXiv cleanup & BibTeX verification: `python3 ../../research-scientist/scripts/check_submission_preflight.py arxiv-clean src/ --strict --compact` and `python3 ../../research-scientist/scripts/check_submission_preflight.py bibtex refs.bib --tex paper.tex --protect-caps --compact`
