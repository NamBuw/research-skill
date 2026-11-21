# Gap, RQ & Parsimony Protocol (AI/CS/CV/NLP)

Load this guide only during gap discovery, engineering-vs-gap triage, or RQ/plan validation.

## 1. STORM Exploration & Deep Gap Pipeline
- Build multi-perspective questions and outline coverage via `../../research-scientist/scripts/storm_explorer.py` (`--topic`, `--corpus`, `--out`, `--compact`).
- Execute the 6-gate falsification pipeline via `../../research-scientist/scripts/gap_pipeline.py` (`--topic`, `--corpus`, `--digests`, `--candidates`, `--out`, `--compact`).
- Rejection codes enforced: `DROP_UNREAD_CITATION`, `DROP_ALREADY_SOLVED`, `DROP_ENGINEERING_BUG`, `DROP_SINGLE_PAPER_FRAGILE`, `DROP_TEMPORAL_LEAK`, `DROP_INSUFFICIENT_COVERAGE`, `DROP_OVERCOMPLICATED`, `DROP_PROBLEM_INFLATION`.
- Verify single gap records and multi-query campaigns via `../../research-scientist/scripts/check_gap_record.py` (requires ALL `closest_work_ids` at full-text) and `../../research-scientist/scripts/check_gap_campaign.py` (blocks empty `known_seed_checks` in confirmatory mode).

## 2. AI/CS/CV/NLP Engineering-Bug vs Genuine-Gap Triage
- Always run `../../research-scientist/scripts/check_engineering_diagnostics.py` (`--code-dir`, `--splits`, `--metrics`, `--compact`) and `../../research-scientist/scripts/audit_alignment.py` before declaring any empirical anomaly a gap.
- Fixed split leaks, missing constant/shuffled sanity controls, untuned baselines, or compute/resolution asymmetries invalidate the gap.

## 3. Falsifiable RQ Cards & Mandatory Parsimony Gate
- Validate RQ cards (estimand, falsifier, indeterminate outcome, minimal pilot) via `../../research-scientist/scripts/check_question_card.py`.
- Validate confirmatory plans via `../../research-scientist/scripts/check_ai_cs_research_plan.py` (`--campaign`): requires non-boilerplate `simplest_alternative`, per-component ablation over the simplest strong baseline with positive marginal gain, and all `ENGINEERING_CHECKS` resolved.
