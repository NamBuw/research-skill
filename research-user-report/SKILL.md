---
name: research-user-report
description: "Export verified research verdicts into a concise, plain-language multilingual LaTeX-to-PDF user report matching the user's input language with intact UTF-8 diacritics."
---

# Research User Report (Concise Multilingual LaTeX-to-PDF)

Compile verified research findings (gap audit, precedent search, /10 scoring, venue fit, or manuscript audit) into a crisp, readable PDF in the user's language.

## Mandatory Language, Conciseness & Integrity Rules

1. **Match user input language:** Detect language automatically from `--input-text` or structured `--input` (`vi`, `en`, etc.) and render headings, verdicts, and labels consistently with verified UTF-8/Vietnamese diacritics (`xelatex`/`lualatex`/`pdflatex` + PyMuPDF text check).
2. **Concise, direct, plain-language prose:** Lead with the direct verdict, then key numbers/evidence, concrete flaws/risks, and actionable next steps. Keep sentences short and plain; reject bloated prose, obscure jargon, filler, and sycophancy.
3. **Zero ungrounded claims:** Every metric, finding, and recommendation in the report JSON must link to a verified evidence locator or source receipt. Include the Parsimony ("least is best") verdict whenever evaluating candidate methods or plans.
4. **Compact JSON receipt:** Use `--strict --json --compact` so stdout stays bounded (`<4096B`) with PDF/TeX paths and lint status.

## Shared Tool (`../research-scientist/scripts/`)

- **Generator & linter:** [report_latex_pdf.py](../research-scientist/scripts/report_latex_pdf.py) (`--input`, `--out`, `--tex-out`, `--lang`, `--input-text`, `--strict`, `--json`, `--compact`).

Load [user report PDF guide](references/user-report-pdf-guide.md) on demand for the JSON input schema, Vietnamese/English localization checks, and `--strict` lint rules.
