# Writing, review, scoring, and venue source reading

This note records the inspected upstream source snapshots, the five bundled MIT K-Dense suites plus the Humanizer catalog under `modules/`, and the local verification scripts in `scripts/`. It is not an instruction to install external repositories or bypass `research-scientist/SKILL.md`. All root scripts under `scripts/` were written for this repository; no Sakana code was copied.

## Source and integration inventory

| Source snapshot and files read | Mechanism inspected | Implementation here and boundary |
|---|---|---|
| [Humanizer](https://github.com/blader/humanizer), local `SKILL.md` v4.0.0, MIT | Whole-document editorial pass: structural repetition, staged openings, formulaic contrast and closers, author-voice calibration, fact-preserving rewrite. | The [complete pattern catalog](../modules/humanizer/VENDOR.md) is bundled with its MIT notice and applied by the [paper-writing workflow](humanizer-paper-writing.md) and `../scripts/humanizer_lint.py` after scientific claims are settled. Rechecks numbers, methods, caveats, and citations; does not claim to evade AI detectors. |
| [K-Dense Scientific Writing](https://github.com/K-Dense-AI/scientific-agent-skills/tree/main/skills/scientific-writing), snapshot `ec59a29a03d5c40f73ab40878df04860bc00e876`, MIT | Evidence/claim manifest, numeric/method consistency checks, reporting guideline selection, human authorship and disclosure, confidentiality boundary. | The complete [offline toolkit](../modules/kdense-scientific-writing/VENDOR.md) (8 runnable pure-stdlib CLIs + `_common.py`) is bundled with MIT notice for manuscript checks alongside `../scripts/check_manuscript_ledger.py`. Neither verifies actual source passages or study conduct. |
| [K-Dense Hypothesis Generation](https://github.com/K-Dense-AI/scientific-agent-skills/tree/main/skills/hypothesis-generation), snapshot `ec59a29a03d5c40f73ab40878df04860bc00e876`, MIT | Hypothesis record schema, operationalization audit, prediction-rival matrix, causal-claim lexical lint, falsification controls, evidence-ledger audit, preregistration scaffold. | The complete [offline toolkit](../modules/kdense-hypothesis-generation/VENDOR.md) (7 runnable pure-stdlib CLIs + `_common.py`) is bundled with MIT notice and complements [gap/RQ sources](gap-rq-source-details.md), `../scripts/check_question_card.py`, and `../scripts/check_ai_cs_research_plan.py`. |
| [K-Dense Peer Review](https://github.com/K-Dense-AI/scientific-agent-skills/tree/main/skills/peer-review), snapshot `ec59a29a03d5c40f73ab40878df04860bc00e876`, MIT | Intake/confidentiality gating, author/editor channel linting, reporting-guideline checks, claim-evidence alignment, statistical reproducibility, Pandoc citation audit. | The complete [offline toolkit](../modules/kdense-peer-review/VENDOR.md) (7 runnable pure-stdlib CLIs + `_common.py`) is bundled with MIT notice and integrated with the [scoring rubric](scoring-and-venue-fit.md). Numerical ratings remain human judgments. |
| [K-Dense Scholar Evaluation](https://github.com/K-Dense-AI/scientific-agent-skills/tree/main/skills/scholar-evaluation), snapshot `ec59a29a03d5c40f73ab40878df04860bc00e876`, MIT | Rubric validation, missingness-aware weighted scoring with uncertainty intervals, evidence traceability, inter-rater agreement, weight-sensitivity perturbation, low-stakes governance checks. | The complete [offline toolkit](../modules/kdense-scholar-evaluation/VENDOR.md) (7 runnable pure-stdlib CLIs + `_common.py`) is bundled with MIT notice alongside `../scripts/compare_scorecards.py`. Hard safety boundary: never rank people or automate hiring, tenure, grant, admissions, or editorial decisions. |
| [K-Dense Literature Review](https://github.com/K-Dense-AI/scientific-agent-skills/tree/main/skills/literature-review), snapshot `ec59a29a03d5c40f73ab40878df04860bc00e876`, MIT | Local search-export deduplication/filtering/ranking/formatting (`search_databases.py`) and DOI registration + Crossref metadata check (`verify_citations.py`). | Curated subset bundled in [literature-review notice](../modules/kdense-literature-review/VENDOR.md): offline `search_databases.py` (pure stdlib) and `verify_citations.py` (uses `requests` when present with a pure-stdlib `urllib.request` fallback; excludes `generate_pdf.py` and `generate_schematic*.py`). Multi-source discovery belongs to `../scripts/search_papers.py` and `../scripts/search_campaign.py`. |
| [Sakana AI Scientist V1](https://github.com/SakanaAI/AI-Scientist), local `ai_scientist/perform_writeup.py` and `perform_review.py`; custom license | Section drafting/refinement, related-work citation search, LaTeX/reference/figure checks; review form with numerical ratings and confidence. | The writing module checks section-specific claim and method consistency; `../scripts/compare_scorecards.py` and `../scripts/compare_venue_novelty.py` enforce evidence-locator and full-text gates plus quantitative venue comparisons. No Sakana code is copied and model review scores are not treated as validated quality measures. |
| [Awesome Conference Skills](https://github.com/CHB-learner/Awesome-Conference-Skills), local `skills/conference-router/SKILL.md` and venue-skill inventory | Candidate routing from contribution type and recent accepted-paper patterns; policy facts kept distinct from corpus patterns. | [Venue dossier](scoring-and-venue-fit.md#submission-opportunity-dossier-and-calendar) requires current official CFP, track, dates, fees, and a backward plan verified by `../scripts/capture_venue_sources.py`, `../scripts/check_venue_sources.py`, `../scripts/check_venue_plan.py`, and `../scripts/venue_leads.py`. Historical accepted papers do not become official policy or acceptance odds. |

## Bundled K-Dense CLI reference

Run commands from `research-scientist/` using `python3`. All bundled K-Dense scripts except `verify_citations.py` are strictly offline and pure standard library.

### `kdense-scientific-writing` (`modules/kdense-scientific-writing/scripts/`, exit `0` pass / `1` fail or error)

- `modules/kdense-scientific-writing/scripts/scaffold_manuscript.py --output-dir <dir> --document-id <id> --study-design <design> [--guideline <id> ...]`
- `modules/kdense-scientific-writing/scripts/validate_manifest.py <manifest.json> [--kind {auto,manuscript,source}] [--require-verified]`
- `modules/kdense-scientific-writing/scripts/select_reporting_guidelines.py select --study-design <design> [--protocol] [--ai] [--llm] [--routinely-collected] [--qualitative-component]`
- `modules/kdense-scientific-writing/scripts/select_reporting_guidelines.py check <coverage.json>`
- `modules/kdense-scientific-writing/scripts/audit_claims.py <manuscript.md> <claims.csv> <sources.json>`
- `modules/kdense-scientific-writing/scripts/check_consistency.py <registry.json>`
- `modules/kdense-scientific-writing/scripts/check_references.py <sources.json>`
- `modules/kdense-scientific-writing/scripts/validate_authorship.py <authorship.json>`
- `modules/kdense-scientific-writing/scripts/lint_manuscript.py <manuscript.md> [--manifest <manifest.json>]`

### `kdense-hypothesis-generation` (`modules/kdense-hypothesis-generation/scripts/`, exit `0` pass / `1` invalid / `2` `ValidationError`)

- `modules/kdense-hypothesis-generation/scripts/validate_hypothesis_schema.py <record.json> [-o <out.json>] [--force]`
- `modules/kdense-hypothesis-generation/scripts/check_operationalization.py <checklist.json> [-o <out.json>] [--force]`
- `modules/kdense-hypothesis-generation/scripts/validate_prediction_matrix.py <matrix.csv> [--record <record.json>] [-o <out.json>] [--force]`
- `modules/kdense-hypothesis-generation/scripts/lint_causal_claims.py <document.md> [-o <out.json>] [--force]`
- `modules/kdense-hypothesis-generation/scripts/check_falsification_controls.py <checklist.json> [--record <record.json>] [-o <out.json>] [--force]`
- `modules/kdense-hypothesis-generation/scripts/audit_evidence_ledger.py <ledger.csv> <search_boundary.json> [--record <record.json>] [-o <out.json>] [--force]`
- `modules/kdense-hypothesis-generation/scripts/generate_preregistration_scaffold.py <record.json> -o <out.md> [--force]` (`-o`/`--output` required; fails with exit `2` if safety/feasibility gates are unresolved)

### `kdense-peer-review` (`modules/kdense-peer-review/scripts/`, exit `0` pass / `1` blocked or invalid / `2` `ValidationError`)

- `modules/kdense-peer-review/scripts/validate_review_intake.py <intake.json> [-o <out.json>] [--force]`
- `modules/kdense-peer-review/scripts/generate_review_scaffold.py <intake.json> -o <out.md> [--force]` (`-o`/`--output` required; requires valid intake)
- `modules/kdense-peer-review/scripts/lint_review.py <review.md> [-o <out.json>] [--force]`
- `modules/kdense-peer-review/scripts/select_reporting_guidelines.py <profile.json> [--coverage <checklist.csv>] [-o <out.json>] [--force]`
- `modules/kdense-peer-review/scripts/validate_claim_evidence.py <matrix.csv> [-o <out.json>] [--force]`
- `modules/kdense-peer-review/scripts/audit_statistics_reproducibility.py <checklist.json> [-o <out.json>] [--force]`
- `modules/kdense-peer-review/scripts/audit_citations.py <manuscript.md> <references.csv> [-o <out.json>] [--force]`

### `kdense-scholar-evaluation` (`modules/kdense-scholar-evaluation/scripts/`, exit `0` pass / `2` invalid, blocked, or error; uses `--output` without `-o`)

- `modules/kdense-scholar-evaluation/scripts/validate_rubric.py --rubric <rubric.json> [--output <out.json>] [--force]`
- `modules/kdense-scholar-evaluation/scripts/calculate_scores.py --rubric <rubric.json> --evaluation <eval.json> [--output <out.json>] [--force]`
- `modules/kdense-scholar-evaluation/scripts/check_traceability.py --rubric <rubric.json> --evaluation <eval.json> --evidence <evidence.json> [--output <out.json>] [--force]`
- `modules/kdense-scholar-evaluation/scripts/summarize_agreement.py --rubric <rubric.json> --ratings <ratings.csv> [--output <out.json>] [--force]`
- `modules/kdense-scholar-evaluation/scripts/weight_sensitivity.py --rubric <rubric.json> --evaluation <eval1.json> --evaluation <eval2.json> [--delta 0.2] [--output <out.json>] [--force]`
- `modules/kdense-scholar-evaluation/scripts/check_process.py --process <process.json> [--output <out.json>] [--force]`
- `modules/kdense-scholar-evaluation/scripts/generate_report_scaffold.py --rubric <rubric.json> --evaluation <eval.json> [--traceability <json>] [--agreement <json>] [--sensitivity <json>] [--process <json>] [--output <out.json>] [--force]`

### `kdense-literature-review` (`modules/kdense-literature-review/scripts/`)

- `modules/kdense-literature-review/scripts/search_databases.py <results.json> [--format {json,markdown,bibtex}] [--output <path>] [--rank {citations,year,relevance}] [--year-start <Y>] [--year-end <Y>] [--deduplicate] [--summary]` (offline; expects a JSON array of paper dicts)
- `modules/kdense-literature-review/scripts/verify_citations.py <markdown_file> [--email <addr>] [-o <report.json>]` (live HTTPS checks against `doi.org/api/handles/` and `api.crossref.org/works/`, with `urllib.request` fallback if `requests` is absent; exits `0` when zero failed DOIs, `1` on unresolved DOIs or network errors)

## Shared boundaries and non-goals

- **Local safety caps:** Bundled K-Dense validators operate on bounded UTF-8 JSON/CSV/Markdown files, reject symlinks, reject duplicate JSON keys and non-finite numbers, and refuse to overwrite existing output files unless `--force` is passed.
- **No live policy or semantic truth verification:** The present package does not include a live venue-policy database, a semantic source-to-claim entailment verifier, or a validated scientific quality estimator. DOI registration checks in `verify_citations.py` do not verify claim support or screen for retractions. Those require current official sources, full-text original papers, and accountable human review.
- **Person-ranking prohibition:** `kdense-scholar-evaluation` tools are strictly limited to developmental review of scholarly works and must never be used to rank people or automate hiring, tenure, promotion, funding, admissions, or editorial decisions.
