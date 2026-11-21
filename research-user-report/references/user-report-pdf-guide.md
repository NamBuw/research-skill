# Multilingual Plain-Language LaTeX-to-PDF Report Guide

Load this guide only when exporting a final user-facing executive PDF report.

## 1. Execution Contract
- Run: `python3 ../../research-scientist/scripts/report_latex_pdf.py --input report.json --out report.pdf --tex-out report.tex --lang auto --input-text "user prompt" --strict --json --compact`
- Supported modes: `gap_audit`, `precedent_search`, `novelty_venue`, `manuscript_audit`, and parsimony summaries.
- Exit `0` requires zero `--strict` lint findings (`lint_findings: []`), successful LaTeX compilation, non-empty PDF (`page_count >= 1`), and PyMuPDF-verified UTF-8 text (`diacritics_verified: true` for Vietnamese).

## 2. Plain-Language & Conciseness Checklist
- Lead with a blunt verdict (`REJECT GAP`, `PASS PARSIMONY GATE`, `GIỮ BASELINE ĐƠN GIẢN`, etc.).
- Every numeric value in `verdict`, `key_evidence`, `flaws_and_risks`, and `next_steps` requires a valid `locator`.
- Avoid obscure academic jargon, convoluted nested clauses, filler transitions, or praise openers; `--strict` blocks bloat, sycophancy, problem inflation (`PI01`), and missing locators (`MISSING_EVIDENCE_LOCATOR`).
- See parent schema details in [parent user-report guide](../../research-scientist/references/user-report-latex.md).
