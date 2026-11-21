---
name: research-gap-rq-audit
description: "Run falsification-first AI/CS/CV/NLP research gap auditing, STORM exploration, engineering-bug vs genuine-gap triage, parsimony (least is best) checks, and falsifiable RQ formulation."
---

# Research Gap, RQ & Parsimony Audit

Attack and falsify candidate gaps before formulating research questions or plans. Never rebrand a self-inflicted engineering bug, leaky split, or untuned baseline as a scientific gap.

## Mandatory Integrity & Parsimony Gates

1. **Zero sycophancy & attack-first order:** Try to kill every candidate gap via alternate-term search and engineering diagnostics before acknowledging merit. Refuse to endorse gaps lacking full-text precedent reads or known-seed checks.
2. **Engineering-vs-Gap separation (AI/CS/CV/NLP):** Fixed bugs (preprocessing-before-split leakage, train/eval contamination, PyTorch `.train()` in eval, mismatched backbone/resolution/augmentations/HPO budget, seed cherry-picking) are NEVER research gaps.
3. **Mandatory Parsimony Gate (least is best):** Before accepting any gap, RQ, or proposed method:
   - Check for **problem inflation** (dramatizing 0.2% noise or tuning variance as a "fundamental crisis").
   - Identify a concrete `simplest_alternative` and verify whether a simpler baseline/approach with fewer components matches or beats quality.
   - Require single-component ablation justification over the simplest strong baseline.
4. **Read-only vs write contract & `--compact`:** Audit first; pass `surviving_gaps`, `question_card`, and `research_plan` receipts via disk `--out` + `--compact`.

## Workflow & Shared Tools

| Stage | Shared Tool (`../research-scientist/scripts/`) | Gate Output |
|---|---|---|
| Multi-perspective map | [storm_explorer.py](../research-scientist/scripts/storm_explorer.py) | `information_table` & `uncovered_branches` |
| Deep gap pipeline | [gap_pipeline.py](../research-scientist/scripts/gap_pipeline.py), [check_gap_record.py](../research-scientist/scripts/check_gap_record.py), [check_gap_campaign.py](../research-scientist/scripts/check_gap_campaign.py) | `surviving_gaps` / `DROP_*` codes |
| Engineering triage | [check_engineering_diagnostics.py](../research-scientist/scripts/check_engineering_diagnostics.py), [audit_alignment.py](../research-scientist/scripts/audit_alignment.py) | `PASS` vs `ENGINEERING_BUG_DETECTED` |
| RQ & confirmatory plan | [check_question_card.py](../research-scientist/scripts/check_question_card.py), [check_ai_cs_research_plan.py](../research-scientist/scripts/check_ai_cs_research_plan.py) | Valid RQ + `parsimony_audit` + discriminating tests |
| Hypothesis / signals | [check_falsification_controls.py](../research-scientist/modules/kdense-hypothesis-generation/scripts/check_falsification_controls.py), [radar.py](../research-scientist/modules/researchradar/problem-statement-finder/scripts/radar.py) | Rival controls & public limitation leads |

Load [gap, RQ & parsimony protocol](references/gap-rq-parsimony-protocol.md) on demand for drop codes, SGHA critic rules, and RQ fields.
