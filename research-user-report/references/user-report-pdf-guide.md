# Multilingual Plain-Language LaTeX-to-PDF Report Guide

Load this guide only when converting verified research outputs (gap audits, precedent searches, `/10` scorecards, venue dossiers, engineering diagnostics, or manuscript audits) into a concise, plain-language executive PDF report.

## 1. Supported Schemas & Canonical JSON Structure

`../../research-scientist/scripts/report_latex_pdf.py` accepts canonical `research_scientist_executive_report_v1` JSON (plus aliases `conclusion`, `metrics`, `evidence`, `risks`, `recommendations`) AND automatically normalizes 12+ raw upstream skill JSON artifacts:
- `check_gap_record.py` (`gap-record`) & `gap_pipeline.py` (`research_scientist_gap_pipeline_v1`)
- `search_papers.py` (`research_scientist_search_v2`) & `search_campaign.py` (`research_scientist_search_campaign_v1`, including `--compact` `top_results`)
- `compare_venue_novelty.py` (`venue-novelty-profile` & `--portfolio` `venue_portfolio_recommendations`) & `compare_scorecards.py` (`profiles`, `rankings`, `ranking_sensitivity`, `related_work_comparison`), including `submission_readiness` when present
- `humanizer_lint.py` & `check_manuscript_ledger.py`
- `check_evidence_map.py`
- `check_engineering_diagnostics.py` (`research_scientist_engineering_diagnostics_v1`) & `check_experiment_manifest.py`
- Venue dossiers (`venue-dossier`) & composite multi-stage bundles

| Field | Required | Purpose & Rules |
|---|---|---|
| `title` | Yes | Short report title (`<= 14` words) |
| `verdict` | Yes | String or object (`status`, `summary`, `label`, `evidence_refs` resolving to grounded IDs) |
| `parsimony_check` / `simplest_alternative` | No | String or object (`simplest_alternative`, `problem_inflation_check`, `verdict`, `source_refs`) rendered inside the Verdict box |
| `key_evidence` | Recommended | Rows with `id`, `claim`, `value`, `status`, `evidence`, `source_refs`, `locator`, `source_url` |
| `flaws_and_risks` | Recommended | Defects, engineering bugs, counterevidence, or unknowns with `id`, `severity`, `summary`, `locator` |
| `next_steps` | Recommended | Concrete next verification actions with `step`, `action`, `target` |
| `metadata` | No | `scope`, `search_date`, `coverage_limits`, `reading_basis` |
| `sources` | No | Source list with `id`, `title`, `locator`, `url` |

**Concise English Example:**
```json
{
  "schema": "research_scientist_executive_report_v1",
  "report_type": "gap_audit",
  "lang": "en",
  "title": "Fictional Split-Leakage Baseline Audit",
  "verdict": {
    "status": "fail",
    "summary": "F1 drops from 84.1% to 61.3% after removing duplicate IDs across train and test [logs/run_02.json].",
    "evidence_refs": ["K1"]
  },
  "parsimony_check": {
    "simplest_alternative": "Deduplicating splits fixes the baseline without adding an extra regularizer.",
    "problem_inflation_check": "Score drop comes from data leakage, not an open method gap.",
    "verdict": "keep_simple"
  },
  "key_evidence": [{"id": "K1", "claim": "Clean split F1", "value": "61.3%", "status": "verified", "locator": "logs/run_02.json#f1"}],
  "flaws_and_risks": [{"id": "R1", "severity": "critical", "summary": "142 duplicate IDs appear in train and test.", "locator": "diag/splits.json"}],
  "next_steps": [{"step": 1, "action": "Rerun baseline on clean splits across 3 seeds.", "target": "logs/run_03.json"}]
}
```

**Concise Vietnamese Example:**
```json
{
  "schema": "research_scientist_executive_report_v1",
  "report_type": "gap_audit",
  "lang": "vi",
  "title": "Kiểm tra rò rỉ dữ liệu và tối giản mô hình",
  "verdict": {
    "status": "fail",
    "summary": "F1 giảm từ 84.1% xuống 61.3% khi loại bỏ ID trùng giữa train và test [logs/run_02.json].",
    "evidence_refs": ["K1"]
  },
  "parsimony_check": {
    "simplest_alternative": "Chỉ cần tách sạch tập dữ liệu cho baseline, không cần thêm mô-đun mới.",
    "problem_inflation_check": "Lỗi do rò rỉ dữ liệu, không phải khoảng trống nghiên cứu.",
    "verdict": "keep_simple"
  },
  "key_evidence": [{"id": "K1", "claim": "F1 sau khi làm sạch", "value": "61.3%", "status": "verified", "locator": "logs/run_02.json#f1"}],
  "flaws_and_risks": [{"id": "R1", "severity": "critical", "summary": "Có 142 ID trùng giữa train và test.", "locator": "diag/splits.json"}],
  "next_steps": [{"step": 1, "action": "Chạy lại baseline với 3 seed trên tập sạch.", "target": "logs/run_03.json"}]
}
```

## 2. Language Adaptation, Technical Masking & Mandatory Parsimony Summary

- **Auto Language Detection (`--lang auto` + `--input-text`):** Supports `vi`, `en`, `fr`, `de`, `es`, or ISO Latin codes. Before scoring language, `report_latex_pdf.py` masks technical AI/CS loanwords (`RAG`, `LLM`, `transformer`, `baseline`, `ablation`, `leakage`, `F1`), so Vietnamese prompts (including short unaccented Vietnamese like `"kiem tra gap cua paper RAG dung LLM"`) resolve accurately to `vi`, while isolated Vietnamese author names in English prose do not flip language to `vi`.
- **Mandatory Parsimony Summary:** Whenever `simplest_alternative` or `parsimony_check` is present (top-level, inside `verdict`, `metadata`, or primary gap candidate), the renderer prints a crisp **Simpler Alternative / Parsimony Check** (`vi`: **Phương án đơn giản hơn / Kiểm tra tối giản**) callout inside the Verdict box and lints it under the same conciseness and grounding rules.

## 3. Conciseness, Plain-Language & Grounding Linter (`--strict`)

All rendered prose fields (`title`, `verdict`, `parsimony_check`, `key_evidence`, `flaws_and_risks`, `next_steps[*].action`/`target`, `metadata.scope`/`coverage_limits`) are scanned:

- **Hard Word-Count Caps:**
  - `title`: `<= 14` words
  - Sentence: `<= 30` words (`SENTENCE_TOO_LONG`); `> 40` words (`SENTENCE_SEVERE_BLOAT`)
  - Paragraph: `<= 80` words (`warn`), `> 120` words (`error` — `PARAGRAPH_BLOAT`)
  - Section: `<= 180` words (`warn`), `> 260` words (`error` — `SECTION_BLOAT`)
  - Total report prose: `<= 550` words (`warn`), `> 750` words (`error` — `TOTAL_REPORT_BLOAT`)

| Pattern ID | Category | Severity | Trigger & Domain Exemptions |
|---|---|---|---|
| `STRUCT_MISSING_VERDICT` | `structure` | `error` | Missing `verdict` / `conclusion` summary |
| `RPT_PLACEHOLDER` | `structure` | `error` | `TODO`, `TBD`, `TK`, `XXXX`, `[insert ...]`, chat assistant residue |
| `SENTENCE_TOO_LONG` / `SENTENCE_SEVERE_BLOAT` | `conciseness` | `error` | Sentence `> 30` / `> 40` words |
| `PARAGRAPH_BLOAT` / `SECTION_BLOAT` / `TOTAL_REPORT_BLOAT` | `conciseness` | `warn`/`error` | Paragraph `> 80/120`, section `> 180/260`, total `> 550/750` words |
| `JARGON_AI_BUZZWORD` / `JARGON_VI_BUZZWORD` | `plain_language` | `error`/`warn` | Obscure jargon or AI buzzwords (exempts standard ML terms: `leverage score`, `robust optimization`, `loss landscape`, `attention gate`) |
| `FILLER_TRANSITION` / `NOMINALIZATION` | `plain_language` | `error` | Staged filler transitions and convoluted nominalizations (EN & VI) |
| `SYC_FLATTERY` / `SYC_CHEERLEADING` / `SYC_PRAISE_SANDWICH` | `sycophancy` | `error` | Flattery, cheerleading, or praise-before-critique sandwich (exempts `strong baseline`, `clean baseline`, `hợp lý`) |
| `PI01` | `parsimony` | `error` | Problem inflation (*"fundamental crisis"*, *"catastrophic failure"*, *"khủng hoảng nền tảng"*; exempts `catastrophic forgetting`) |
| `RPT_GRAND_BRANDING` | `integrity` | `error` | Coined grandiose method names (`Hyper*`, `Unified Framework`, `khung lý thuyết hợp nhất`; exempts `Early-Fusion`, `Neuro-symbolic`) |
| `UNGROUNDED_NUMERIC_CLAIM` / `UNGROUNDED_CITATION` / `MISSING_EVIDENCE_LOCATOR` | `integrity` | `error` | Metric/number (including `mAP@0.5`, `Pass@1`, `ROUGE-L`, `từ ... lên ...`), citation (`Author (YYYY)`, `[S1]`, `arXiv:`, DOI), or `key_evidence` row without a verified locator or matching `sources` ID |

## 4. LaTeX Engine Probing, Diacritics Verification & CLI Contract

```bash
python3 ../../research-scientist/scripts/report_latex_pdf.py --input report.json --out report.pdf --tex-out report.tex --lang auto --input-text "Hãy kiểm tra gap của paper này" --engine auto --strict --json --compact
```

- **Engine Probing (`select_latex_engine()`):** Probes actual compiler + font/package capabilities instead of trusting `PATH`:
  1. `xelatex`: requires `fontspec.sty` + a Vietnamese TTF/OTF font via `fc-list` when Vietnamese glyphs exist.
  2. `lualatex`: requires `fontspec.sty` **and** `luaotfload-main.lua` (+ Vietnamese font when needed).
  3. `pdflatex`: uses `cmap`, `[utf8]{inputenc}`, `[T1,T5]{fontenc}` (using `T5` spans for Vietnamese glyphs and `T1` spans for extended Latin `äöüßñçœæëïåøîûÿ¿¡`), `lmodern`, `microtype`, `\emergencystretch=3em`, full Greek mapping, and UTF-8 URL escaping. **Never loads `babel[vietnamese]`.**
- **Post-Compile `pymupdf` Verification (`verify_pdf_output()`):** `compile_pdf()` runs LaTeX inside an isolated temp dir and copies `pdf_path`, then `verify_pdf_output()` opens `pdf_path` with `pymupdf`, checks `page_count >= 1`, non-empty extracted text, zero `U+FFFD` replacement characters, and 100% survival of Vietnamese diacritics and Greek symbols (`diacritics_verified: true`, symmetric `NFKC` handling for `pdflatex` math glyphs).
- **Exit Codes & Receipt Status Tokens:**
  - `0` (`status: "ok"`): compiled cleanly, lint passed, `page_count >= 1`, `diacritics_verified: true`.
  - `1` (`status: "lint_failed"`, `"compile_failed"`, or `"verify_failed"`): `--strict` lint block, TeX compilation failure, or `pymupdf` verification failure.
  - `2`: invalid CLI flags, missing/empty/`NaN` JSON, unrecognized schema, invalid language tag, or missing TeX/`pymupdf` runtime.
- **Integrity Boundary:** A passing `--strict` run certifies formatting, conciseness, plain-language style, structural locator presence, and UTF-8 PDF glyph integrity only — never external scientific truth. See [parent LaTeX report spec](../../research-scientist/references/user-report-latex.md).

## 5. Mandatory Submission Readiness Guidance (`Khả năng nộp bài`)

Whenever generating a PDF report for `/10` scorecards or venue evaluations (`report_type: "novelty_scoring"` or `"venue_dossier"`), translate numeric scores into crisp, plain-language **Submission Readiness** (`vi`: **Khả năng nộp bài**) guidance—never bare numbers alone, and never invented `%` acceptance odds.

1. **Required 4 points (short sentences `<= 30` words, grounded with locators):**
   - **Fatal-gate check:** State immediately if `not_ready_fatal_gate` triggers (`soundness <= 4`, `evidence <= 4`, `novelty <= 2`, `transparency <= 3`, any axis `<= 2`, or unrun `idea`).
   - **Standing vs all submissions & accepted panel:** Compare weighted `/10` against all-submissions average (`~4.8–5.5`) and top-tier accepted median (`~6.8–7.6`), citing panel standing if available.
   - **Realistic venue tier right now:** State clearly whether the work fits rework/workshop (`<6.0`), `Findings` / Tier-A / focused Q1–Q2 (`6.0–6.79`), or Top-Tier Main Track (`>=6.8`, when CFP fit and hard constraints pass).
   - **Top fixes before submission:** Name the `bottleneck_dimensions`, gap to `6.80`, and concrete missing experiments/ablations in `flaws_and_risks` and `next_steps`.
2. **Plain-Language EN/VI Examples (`--strict` lint-clean):**
   - **EN (`6.35/10`, `verdict.summary`):** `"Weighted score 6.35/10 passes fatal gates but sits below top-tier main-track accepted median (~6.8-7.6) [scorecards.json]. Competitive now for Findings or Tier-A venues; strengthen soundness before NeurIPS."`
   - **VI (`6.35/10`, `verdict.summary`):** `"Điểm 6.35/10 vượt mức trung bình toàn bộ bài nộp (~4.8-5.5) nhưng thấp hơn mức bài được nhận top-tier (~6.8-7.6) [scorecards.json]. Phù hợp nộp Findings hoặc hội nghị Tier-A hiện tại."`
   - **VI (Fatal-gate override, `verdict.summary`):** `"Chưa đủ điều kiện nộp dù điểm trung bình đạt 6.6/10 do vướng lỗi chí mạng ở độ chặt phương pháp (4/10) [scorecards.json]. Cần sửa thiết kế thí nghiệm trước khi nộp."`

## 6. Closest-Work Anchor, Cross-Topic Venue Bar & Portfolio Guidance

Whenever summarizing `compare_scorecards.py --target-id` or `compare_venue_novelty.py --portfolio` outputs, also include:
1. **Closest-work & cross-topic venue deltas:** Report `target_delta_vs_best_related_overall` across `>= 3` full-text closest works and `target_vs_venue_overall_delta` vs `venue_contribution_bar` (`different_topic` / `cross_topic_count`).
2. **Tier-mismatch rejection & retargeting:** When `rejected_below_venue_tier` triggers (e.g., workshop-scale `< 6.0` targeting Q1/Top-Tier), state the rejection bluntly, list `upgrade_gaps_to_target_tier`, and point to `recommended_matched_tier` (or `no_viable_venue_in_portfolio`) across verified candidates (`recommended_now`, `stretch_high_risk`, `viable_fallback`, `hold_for_rework`, `disqualified`, `withheld_unverified`, `timeline_conflicts`).
3. **`--strict` Portfolio EN/VI Examples:**
   - **EN (`verdict.summary`):** `"Target scores 6.35/10 (-0.45 vs 6.80; -0.65 vs best related work 7.00) [scorecards.json]. Recommended now: EMNLP Findings (fit 8/10); NeurIPS Main Track is stretch_high_risk [portfolio.json]."`
   - **VI (`verdict.summary`):** `"Bài đạt 6.35/10 (kém bài liên quan mạnh nhất 0.65 điểm) [scorecards.json]. Nên nộp EMNLP Findings (fit 8/10); NeurIPS Main Track ở mức rủi ro cao [portfolio.json]."`
   - **VI (Tier-mismatch rejection -> Workshop retarget, `verdict.summary`):** `"Bài đạt 5.40/10, chưa đạt ngưỡng tạp chí Q1 (tối thiểu 6.00/10) [portfolio.json]. Đề xuất chuyển hướng sang hội thảo kiểm chứng đạt 8/10 độ phù hợp [portfolio.json]."`
