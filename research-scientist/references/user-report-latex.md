# Concise Multilingual User Report (LaTeX-to-PDF)

Use this guide when converting verified research outputs (gap audits, precedent searches, `/10` novelty scorecards, venue checks, engineering diagnostics, or manuscript audits) into a concise, plain-language executive PDF report via `scripts/report_latex_pdf.py`.

## Core rules

1. **Match the user's prior input language.** Pass `--input-text` (the prior user prompt) or set `"lang"` (`vi`, `en`, `fr`, `de`, `es`, or `auto`). Technical AI/CS terms (`RAG`, `LLM`, `transformer`, `baseline`, `ablation`, `leakage`, `F1`) are masked before scoring so Vietnamese prompts (including short unaccented prompts) mixed with English terminology still resolve to `vi`, while isolated Vietnamese author diacritics inside English text do not flip the report language.
2. **Direct verdict first.** Lead with the conclusion (`verdict`), followed by key numbers (`key_evidence`), concrete flaws/unknowns (`flaws_and_risks`), actionable next steps (`next_steps`), and verified sources (`sources`).
3. **Plain language and strict brevity.** Keep sentences short (`<= 30` words), paragraphs tight (`<= 80` words recommended; `> 120` blocked), and total prose compact (`<= 550` words recommended; `> 750` blocked). Do not use obscure jargon, filler transitions, convoluted nominalizations, sycophancy, praise-sandwiches, or grandiose coined method names. All rendered prose fields (`title`, `verdict`, `parsimony_check`, `key_evidence`, `flaws_and_risks`, `next_steps[*].action`/`target`, `metadata.scope`/`coverage_limits`) are scanned.
4. **Parsimony check when present.** If `simplest_alternative` or `parsimony_check` is included (top-level, under `verdict`, `metadata`, or primary gap candidate), the generator renders a crisp 1–2 line **Simpler Alternative / Parsimony Check** (`vi`: **Phương án đơn giản hơn / Kiểm tra tối giản**) inside the Verdict box and subjects it to the same conciseness and grounding rules.
5. **Ground every number and citation.** Every numeric/metric claim (including `mAP@0.5`, `Pass@1`, `RMSE`, `MAE`, `Top-1`, hyphenated metrics like `ROUGE-L`, and Vietnamese ranges like `từ ... lên ...`) in prose and `metadata.scope`/`coverage_limits`, as well as every `key_evidence` row, must carry a non-blank direct `locator`, `evidence`, or `source_url`, or `source_refs`/`evidence_ids` whose entries resolve against `sources` or other grounded IDs (or a valid inline numbered structural cue such as `Table 1`/`Section 2`/`Bảng 1`, file path, or grounded `[S1]`/`[K1]` ref). `verdict.evidence_refs` and `parsimony_check.source_refs`/`evidence_refs` must reference existing grounded IDs in `key_evidence`, `sources`, or `flaws_and_risks`, and inline citations (`Author (YYYY)`, `(Author, YYYY)`, `(Author YYYY)`, `Author1 & Author2 (YYYY)`, `Author et al.`, `[N]`, `[S1]`/`[SC1]`/`[F99]`, `arXiv:`, DOIs) must match `sources` (including all co-author surnames) or grounded IDs with word/digit boundary checks.

## Input JSON schemas

`scripts/report_latex_pdf.py` accepts canonical `research_scientist_executive_report_v1` JSON (plus aliases `conclusion`, `metrics`, `evidence`, `risks`, `recommendations`) as well as raw upstream artifacts from `check_gap_record.py` / `gap_pipeline.py`, `search_papers.py` / `search_campaign.py` (`schema` or `format` `research_scientist_search_campaign_v1`, plus `--compact` `top_results`), `compare_venue_novelty.py`, `compare_scorecards.py` (both scorecard `profiles` and CLI `rankings`/`ranking_sensitivity` output), `humanizer_lint.py`, `check_manuscript_ledger.py`, `check_evidence_map.py`, `check_engineering_diagnostics.py`, `check_experiment_manifest.py`, venue dossiers (`venue-dossier`), and composite bundles.

Canonical executive schema fields:

| Field | Required | Purpose |
|---|---|---|
| `title` | Yes | Short report title (`<= 14` words) |
| `verdict` | Yes | String or object (`status`, `summary`, `label`, `evidence_refs`) |
| `simplest_alternative` / `parsimony_check` | No | String or object (`simplest_alternative`, `problem_inflation_check`, `verdict`) |
| `key_evidence` | Recommended | Rows with `claim`, `value`, `status`, `evidence`, `source_refs`, `locator`, `source_url` |
| `flaws_and_risks` | Recommended | Defects, engineering bugs, counterevidence, or unknowns with `severity` and `locator` |
| `next_steps` | Recommended | Concrete verification actions with `action` and `target` |
| `metadata` | No | `scope`, `search_date`, `coverage_limits`, `reading_basis` |
| `sources` | No | Source list with `id`, `title`, `locator`, `url` |

Fictional canonical example:

```json
{
  "schema": "research_scientist_executive_report_v1",
  "report_type": "gap_audit",
  "lang": "en",
  "title": "Fictional Split-Leakage Audit",
  "verdict": {
    "status": "fail",
    "summary": "Accuracy drops from 84.1% to 61.3% after removing duplicate IDs across splits [logs/run_02.json].",
    "evidence_refs": ["K1"]
  },
  "parsimony_check": {
    "simplest_alternative": "Deduplicating splits fixes the baseline without adding a custom regularizer.",
    "problem_inflation_check": "Failure stems from split leakage, not an open gap.",
    "verdict": "keep_simple"
  },
  "key_evidence": [
    {
      "id": "K1",
      "claim": "Clean split F1 score",
      "value": "61.3%",
      "status": "verified",
      "locator": "logs/run_02.json#f1"
    }
  ],
  "flaws_and_risks": [
    {
      "id": "R1",
      "severity": "critical",
      "summary": "142 duplicate document IDs appear in both train and test splits.",
      "locator": "diagnostics/splits.json"
    }
  ],
  "next_steps": [
    {"step": 1, "action": "Re-run baseline on deduplicated splits across 3 seeds.", "target": "logs/run_03.json"}
  ]
}
```

## CLI usage, flags, and exit codes

```bash
python3 scripts/report_latex_pdf.py \
  --input report.json \
  --out output/report.pdf \
  --tex-out output/report.tex \
  --lang auto \
  --input-text "Hãy kiểm tra gap của paper RAG dùng LLM" \
  --engine auto \
  --strict \
  --json \
  --compact
```

| Flag | Default | Description |
|---|---|---|
| `--input` | required | Path to input JSON report or upstream skill JSON |
| `--out` | required | Destination path for compiled `.pdf` |
| `--tex-out` | none | Optional destination path to save generated `.tex` source |
| `--lang` | `auto` | Target language (`auto`, `vi`, `en`, `fr`, `de`, `es`, or ISO Latin code) |
| `--input-text` | `""` | Prior user prompt used when `--lang auto` |
| `--engine` | `auto` | TeX engine preference (`auto`, `pdflatex`, `xelatex`, `lualatex`) |
| `--strict` | off | Exit `1` without writing PDF if any `error`/`critical` lint finding occurs |
| `--json` | off | Print structured JSON receipt to stdout |
| `--compact` | off | Emit bounded compact stdout receipt (caps `lint_findings` to 5 items; never dumps raw `.tex` or full logs) |

Exit codes and receipt `status` tokens:

- `0` (`status`: `"ok"`): PDF compiled cleanly, non-empty, `page_count >= 1`, `diacritics_verified == true`.
- `1` (`status`: `"lint_failed"`, `"compile_failed"`, or `"verify_failed"`): `--strict` lint rejection, LaTeX build failure, or post-compile `pymupdf` verification failure.
- `2`: Invalid CLI arguments, missing/malformed JSON, unrecognized schema, or no capable LaTeX engine / `pymupdf` unavailable.

Required JSON receipt keys: `status`, `pdf_path`, `tex_path`, `lang`, `engine`, `page_count`, `diacritics_verified`, `lint_summary`, `lint_findings`.

## Engine probing and Unicode/Vietnamese verification

`select_latex_engine()` probes engine capabilities rather than trusting `PATH` presence alone:

1. `xelatex`: requires `fontspec.sty` and a Vietnamese TTF/OTF font via `fc-list` when Vietnamese text is present.
2. `lualatex`: requires `fontspec.sty` **and** `luaotfload-main.lua` (plus a Vietnamese font when needed). Hosts missing `texlive-luatex` fail `luaotfload-main.lua` and are skipped cleanly.
3. `pdflatex`: uses `cmap`, `[utf8]{inputenc}`, `[T1,T5]{fontenc}` (requiring `t5enc.def` / `vietnam.sty` for Vietnamese, or `[T5,T1]` with `T5` spans only when Vietnamese-specific `T5` glyphs appear inside non-Vietnamese reports — keeping `T1`-native `fr`/`es`/`de` accents on `[T1]`, plus `T1` spans for extended Latin characters `äöüßñçœæëïåøîûÿ¿¡` inside Vietnamese reports), `lmodern` (when present), `microtype` (`\DisableLigatures[-]{encoding = *, family = tt*}`), `\emergencystretch=3em`, allowbreak wrapping in prose and `tabularx` cells, full uppercase/lowercase Greek mapping, non-ASCII UTF-8 percent-encoding in `escape_latex_url()`, and `hyperref` (`pdfencoding=auto,psdextra`). Never loads `babel[vietnamese]`.

After compilation inside an isolated temporary directory, `verify_pdf_output()` opens the PDF with `pymupdf` (`fitz`) to confirm `page_count >= 1`, non-empty extracted text, zero `U+FFFD` replacement glyphs, and 100% survival of input Vietnamese diacritic characters, Greek characters, and sample phrases (with symmetric `NFKC` normalization for `pdflatex` Mathematical Italic Greek ToUnicode glyphs).

## Linter rules (`lint_report()`)

| Pattern ID | Category | Severity | Trigger |
|---|---|---|---|
| `STRUCT_MISSING_VERDICT` | `structure` | `error` | Missing `verdict` / `conclusion` summary |
| `RPT_PLACEHOLDER` | `structure` | `error` | `TODO`, `TBD`, `TK`, `XXXX`, `[insert ...]`, AI assistant residue |
| `SENTENCE_TOO_LONG` / `SENTENCE_SEVERE_BLOAT` | `conciseness` | `error` | Sentence `> 30` words / `> 40` words |
| `PARAGRAPH_BLOAT` / `SECTION_BLOAT` / `TOTAL_REPORT_BLOAT` | `conciseness` | `warn` / `error` | Paragraph `> 80`/`120`, section `> 180`/`260`, total `> 550`/`750` words |
| `JARGON_AI_BUZZWORD` / `JARGON_VI_BUZZWORD` | `plain_language` | `error` / `warn` | Obscure jargon or AI buzzwords (preserving `humanizer_lint.py` technical exemptions such as `leverage score`, `robust optimization`, `loss landscape`, `attention gate`) |
| `FILLER_TRANSITION` / `NOMINALIZATION` | `plain_language` | `error` | Staged filler transitions and convoluted nominalizations (EN & VI) |
| `SYC_FLATTERY` / `SYC_CHEERLEADING` / `SYC_PRAISE_SANDWICH` | `sycophancy` | `error` | User flattery, cheerleading, or sentence-ordered praise-before-critique sandwich (EN & VI; exempts standard ML baseline comparisons such as `strong baseline`, `clean baseline`, `hợp lý`) |
| `PI01` | `parsimony` | `error` | Dramatized problem-inflation phrasing (`fundamental crisis`, `catastrophic failure`, `khủng hoảng nền tảng`, `sụp đổ hoàn toàn`; exempts standard ML term `catastrophic forgetting`) |
| `RPT_GRAND_BRANDING` | `integrity` | `error` | Coined/grandiose method branding (`Hyper*`, `Unified Framework`, `khung lý thuyết hợp nhất`; exempts standard hyphenated/compound ML terms like `Early-Fusion`, `Neuro-symbolic`) |
| `UNGROUNDED_NUMERIC_CLAIM` / `UNGROUNDED_CITATION` / `MISSING_EVIDENCE_LOCATOR` | `integrity` | `error` | Metric/numeric claims, citations, or `key_evidence` rows lacking a locator or source reference |

## Integrity disclaimer

A passing `report_latex_pdf.py --strict` run certifies formatting, conciseness, plain-language compliance, structural locator presence, and PDF glyph integrity only. It does **not** verify the external scientific truth or statistical validity of the underlying claims.
