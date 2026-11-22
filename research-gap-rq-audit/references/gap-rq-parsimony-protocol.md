# Gap, RQ & Parsimony Protocol (AI/CS/CV/NLP)

Load this guide only during research-gap discovery, engineering-vs-gap triage, F19 parsimony auditing, or falsifiable RQ and confirmatory experiment-plan validation.

## 1. STORM / Co-STORM Multi-Perspective Exploration (`storm_explorer.py`)

Run multi-perspective coverage mapping before candidate filtering so gap framing is not trapped by a single vocabulary:

```bash
python3 ../../research-scientist/scripts/storm_explorer.py --topic "retrieval calibration under domain shift" --corpus corpus.json --max-turns 12 --out storm.json --compact
```

- **Four Built-in Perspectives (`P1–P4`):**
  - `P1` *Problem Framing & Mechanistic Validity* — formal assumptions, target mechanism, and whether prior work already resolves the claim.
  - `P2` *Empirical Robustness, OOD Shift & Calibration* — OOD generalization, calibration error, failure modes, and stress tests.
  - `P3` *Baselines, Engineering Parity & Parsimony* — tuned simple baselines, HPO/compute parity, split integrity, and minimal sufficient alternatives.
  - `P4` *Cross-Setting Analogy & Closure Synthesis* — adjacent-field precedents, older terminology, and direct closure studies.
- **Negation Stripping & Coverage Artifacts:** `_NEGATION_RE` strips negative assertions (*"no evaluation of X"*, *"without X"*, *"lacks X"*) before matching positive evidence so negated mentions do not falsely satisfy coverage. Outputs `storm_state` containing `perspectives`, `qa_turns`, deduplicated `information_table`, hierarchical `outline`, `uncovered_branches`, and a dual-regime check verifying both `same_problem` and `cross_setting_analogy` coverage. Personas are discovery leads, never independent evidence.

## 2. Sequential Gap Falsification Funnel (`gap_pipeline.py` + Record & Campaign Gates)

Advance candidates strictly through `lead` -> `bounded_uncertainty` -> `source_checked` -> `challenged` -> `supported_candidate` ([parent gap audit](../../research-scientist/references/gap-audit.md)). Execute the deterministic 9-gate pipeline:

```bash
python3 ../../research-scientist/scripts/gap_pipeline.py --topic "<topic>" --corpus corpus.json --digests digests.json --candidates candidates.json --feedback-store rejected_memory.json --allow-partial --out gap_out.json --compact
```

| Gate | Exact Rejection Code | Deterministic Trigger / Threshold |
|---|---|---|
| 1. Temporal cutoff (`CKM-HypoGen`) | `DROP_TEMPORAL_LEAK` | Any cited/supporting paper post-dates `cutoff_date` or `cutoff_year` |
| 2a. Read-before-cite | `DROP_UNREAD_CITATION` | Any `cited_ids` / `support_ids` entry lacks a full-text digest (`quote`/`digest` + full-text `access`) |
| 2b. Retraction screen | `DROP_RETRACTED_SUPPORT` | Any supporting work has `retraction_status == "retracted"` |
| 3. Engineering gate | `DROP_ENGINEERING_BUG` | `engineering_checked` is `False`, status in `{unchecked, failed, not_checked}`, or `ENGINEERING_BUG_DETECTED` |
| 4. Kill-search (`Lit-Gap`) | `DROP_ALREADY_SOLVED` | Clean-room `require_abstract=False` search (`title + abstract + text`): `title_recall >= 0.70`, or `claim_recall >= 0.50` (`>= 0.45` on `kill_search` family) with `>= 3` shared tokens |
| 5a. Problem inflation (F19) | `DROP_PROBLEM_INFLATION` | `problem_inflation_detected=True` or dramatized crisis regex paired with `abs(measured_delta) <= 0.005`, noise hints, or missing `95% CI` |
| 5b. Overcomplication (F19) | `DROP_OVERCOMPLICATED` | `simpler_equal_or_better=True`, `complexity_justified=False`, non-positive ablation gain, or `>= 3` modules lacking concrete `simplest_alternative` and positive numeric ablation |
| 6. Dual-regime & STORM | `DROP_INSUFFICIENT_COVERAGE` | Non-empty `uncovered_branches` or corpus lacks both `same_problem` and `cross_setting_analogy` families |
| 7. Fragility floor | `DROP_SINGLE_PAPER_FRAGILE` | Fewer than `2` unique `support_ids` (`< 2` independent studies) |
| 8. SGHA 5-role critic | `DROP_ARTIFICIAL_SCOPE` / `DROP_SGHA_CRITIC_REJECT` | `sgha_critics_passed=False` / `artificial_scope=True`, or critic `verdict in {REJECT, DROP}`, `survival_score < 0.60`, or `critic_confidence < 0.50` |
| 9. Memory & dedup (`IRIS` / `AI-Researcher`) | `DROP_DUPLICATE` | Token Jaccard `>= 0.80` against prior `--feedback-store` rejected claims or an already surviving candidate |

### Structural Record & Campaign Cross-Checks
```bash
python3 ../../research-scientist/scripts/check_gap_record.py gap_record.json --evidence-dir extracted_blocks/
python3 ../../research-scientist/scripts/check_gap_campaign.py gap_record.json campaign.json
```
- `check_gap_record.py` requires **all** `closest_work_ids` to have `full_text` or `selected_full_text` with source locators for `supported_candidate`, requires `>= 2` sources and `>= 2` query families unless `coverage_exception` is documented, rejects `author_future_work` alone or `direct_precedent`, and with `--evidence-dir` verifies quotes, page bounds, and polarity inside extracted blocks.
- `check_gap_campaign.py` cross-checks gap queries against `search_campaign.py` (`research_scientist_search_campaign_v1`) and **errors** on empty or missed `known_seed_checks` for `supported_candidate`.

## 3. Engineering-Bug vs Genuine-Gap Triage & 8 AI/CS Pressure Cases

Never promote a weak baseline score, crash, or failed reproduction into a gap until engineering diagnostics pass:

```bash
python3 ../../research-scientist/scripts/check_engineering_diagnostics.py --code-dir src --splits splits.csv --metrics metrics.json --out diag.json --compact
python3 ../../research-scientist/scripts/audit_alignment.py features.csv labels.csv --id-column sample_id --split-column split --group-column group_id --compact
```

**Gap Status Taxonomy:** Separate `implementation_error` (local bug — fix it, not a gap), `protocol_mismatch` (align setup), `under_specified_reproducibility` (report missing spec), `candidate_method_boundary` (assumptions fail in target regime), `candidate_nonreplication` (matched independent failure), `candidate_robustness` (prespecified perturbation fragility), and `unresolved`.

**Eight AI/CS/CV/NLP Pressure Cases (`../../research-scientist/references/good-question-pressure-cases.md`):**
1. **Method-First Reskinning** (*"Apply Mamba/Diffusion to X"*): Require mechanistic uncertainty + tuned simple baseline (`simplest_alternative`), else reject.
2. **Grandiose Stitched Pipeline**: Strip coined acronyms; trace component origins; require positive marginal ablation gain (`> 0`) per component.
3. **Self-Inflicted Bug**: Freeze code, run `check_engineering_diagnostics.py`, repair baseline; block promotion (`DROP_ENGINEERING_BUG`) whenever any confirmatory engineering check is unpassed.
4. **Asymmetric HPO (Dacrema Trap)**: Enforce identical HPO trial counts and seed counts between candidate and baseline (`hpo_budget_asymmetry`).
5. **NLP Contamination & Single-Prompt Fragility**: Audit n-gram overlap, ban `split="train"` eval, freeze prompts pre-test, test `>= 3` paraphrases.
6. **CV Backbone/Resolution/Augmentation Mismatch**: Change one variable at a time (`budget_or_config_mismatch`).
7. **Split Leakage & Seed Cherry-Picking (Kapoor Trap)**: Fit scalers/vectorizers strictly on `train`, check ID/group disjointness (`audit_alignment.py`), report all attempted seeds (`excluded_failed_runs`).
8. **Problem Inflation & Missing Platt Strong Inference**: Require `>= 3` seeds + 95% CI and discriminating `H1`/`H2`/`H3` predictions (`predictions_do_not_discriminate`).

## 4. F19 Mandatory Parsimony Interrogation Matrix ("Ít nhất mà tốt nhất")

Every multi-component method or `confirmatory` `method` plan must pass all four parsimony questions before proposal or drafting:

| # | Interrogation Question | Executable Gate Enforcement (`check_ai_cs_research_plan.py` / `gap_pipeline.py`) |
|---|---|---|
| Q1 | **Problem Inflation:** Is minor seed/hyperparameter variance being dramatized into a crisis? | Blocks `_INFLATION_RE` (*"fundamental crisis"*, *"catastrophic failure"*, *"paradigm collapse"*) paired with small delta (`<= 0.005`), noise hints, or missing `95% CI` / bootstrap / seeds |
| Q2 | **Simpler Alternative:** Can a simpler baseline, hyperparameter fix, or single-stage method achieve equal or better quality? | Requires non-boilerplate `simplest_alternative` (`>= 4` words, concrete metric/baseline, not dismissive without numbers); rejects if `simpler_equal_or_better=True` |
| Q3 | **Minimal Sufficient Ablation:** What happens when each extra module, loss, or stage is ablated back to the simplest strong baseline? | For `>= 2` components in plans (`>= 3` modules in `gap_pipeline.py`), requires `ablation` role experiment, `ablation_over_simplest_baseline` with positive numeric `marginal_gain > 0` (`proposed - baseline > 0` or `< 0` when lower-is-better) |
| Q4 | **Earned Complexity:** Does every retained component have a specific, measurable justification? | Requires `component_justifications` mapping each component to positive marginal gain or explicit removal (`retained: false`) |

## 5. Falsifiable RQ Cards, Confirmatory Plan Gating & Optional Signal Lanes

- **RQ Card Validation (18 Required Fields):**
  ```bash
  python3 ../../research-scientist/scripts/check_question_card.py question_card.json
  ```
  Checks all 18 fields (`question`, `question_type`, `target_scope`, `unit_of_observation`, `unit_of_analysis`, `construct_or_estimand`, `measurement`, `closest_work`, `prior_art_boundary`, `rival_explanation`, `expected_if_focal`, `expected_if_rival`, `discriminating_test`, `falsifying_result`, `indeterminate_result`, `pilot`, `engineering_diagnosis`, `prior_outcome_exposure`). Rejects placeholder `rival_explanation`, identical focal vs rival expectations, identical falsifying vs indeterminate outcomes, and `causal` RQs missing `identification_assumptions`. Frame competing tests via Platt Strong Inference (`H1` focal mechanism, `H2` strongest rival, `H3` null/artifact).
- **Confirmatory AI/CS Plan Gate (3-Plan Portfolio & 6 `ENGINEERING_CHECKS`):**
  ```bash
  python3 ../../research-scientist/scripts/check_ai_cs_research_plan.py gap.json question.json plan.json --campaign campaign.json
  ```
  In `claim_mode == "confirmatory"`, `--campaign` is mandatory, gap must be `supported_candidate`, `prior_outcome_exposure` must be unseen, all `closest_work_ids` must be resolved, and **all six** `ENGINEERING_CHECKS` (`data_identity`, `split_integrity`, `preprocessing`, `metric_sanity`, `baseline_fidelity`, `reference_reproduction`) must be `passed` regardless of candidate `trigger`. Structure the portfolio across (1) Small Diagnostic, (2) Primary Discriminating Test, and (3) Robustness & Mechanism Follow-up.
- **K-Dense & ResearchRadar Complementary Lanes:** Validate falsification controls via `../../research-scientist/modules/kdense-hypothesis-generation/scripts/check_falsification_controls.py` (`--record`), `validate_prediction_matrix.py`, and `lint_causal_claims.py`. Mine peer-review limit leads via `../../research-scientist/modules/researchradar/problem-statement-finder/scripts/radar.py` (`check`, `limits`, `iclr`, `verify`) — note OpenReview `403 ChallengeRequiredError` limits mean review signals are leads only, never primary gap proof.

## 6. Structured Gap Mining, Trajectory & Deep Lenses (F27, F30, F32, F31)

1. **Structured Mining & Failure-First Discovery (`storm_explorer.py`):**
   ```bash
   python3 ../../research-scientist/scripts/storm_explorer.py --topic "<topic>" --corpus corpus.json --failure-cases failure_cases.json --target-regime ood_shift --out storm.json --compact
   ```
   - **Contradiction Matrix (`contradiction_matrix`):** Surfaces cross-paper polarity conflicts separated into `cross_regime_conflict` vs `same_regime_conflict`, tagged `status: "lead"`.
   - **Coverage-Hole Matrix (`coverage_hole_matrix`):** Maps `Method × Setting × Metric × Regime` using `_positive_text` so negated mentions do not satisfy coverage; separates `genuine_coverage_hole` from `trivial_reskin_risk`.
   - **Assumption-Violation Mining (`assumption_violations`):** Links paper assumptions (`i.i.d.`, `clean labels`, `unbounded memory`, `oracle retrieval`, `homogeneous`) against violating target regimes.
   - **Chronological Trajectory (`research_trajectory`):** Builds `Gen1 -> bottleneck -> Gen2 -> tradeoff -> open_root_limit` without fabricating missing years.
   - **P4 Isomorphic Transfer (`isomorphic_transfer_leads`):** Maps abstract bottlenecks to adjacent disciplines (Control Theory, Causal Inference, Information Theory, Optimization, Statistical Physics, Signal Processing) strictly tagged `evidence_level: "lead"`, `requires_primary_verification: true`, `supporting_evidence: []`.
   - **Failure-First (`failure_first_patterns`):** Groups empirical baseline error logs (`--failure-cases`) into recurring patterns with prior-art cross-checks while still requiring engineering clearance.

2. **Cross-Vocabulary Kill-Search, Tier Ceiling, Feasibility & Deep Lenses (`gap_pipeline.py` & `check_gap_record.py`):**
   ```bash
   python3 ../../research-scientist/scripts/gap_pipeline.py --topic "<topic>" --corpus corpus.json --digests digests.json --candidates candidates.json --storm storm.json --campaign campaign.json --citation-graph graph.json --failure-cases failure_cases.json --code-prior-art code_repos.json --target-venue-tier q1_or_tier_a --subfield-preset nlp_llm --allow-partial --seed-bundle-out seed_bundle.json --out gap_out.json --compact
   ```
   - **Cross-Vocab `DROP_ALREADY_SOLVED` (F27.5) & `code_prior_art` (F30.4):** Expands `mechanism_aliases` / `alternate_vocabularies`, cross-checks `search_campaign.py` (`combined_results` / `source_records` + `query_runs`) and `citation_graph.py` co-citation clusters, and blocks solutions already shipped in open-source GitHub/HuggingFace repos (`relation == "direct_equivalent"` or `status in {solved, implemented}`).
   - **Venue Tier Ceiling & Early Rejection (F27.2):** Classifies surviving gaps into `q1_top_tier_potential`, `tier_a_findings_potential`, `workshop_incremental_only`, or `low_impact_dead_end` and flags `gap_below_target_venue_tier` (or drops with `DROP_BELOW_TARGET_VENUE_TIER` / `DROP_LOW_IMPACT_DEAD_END` under `--strict-triage`).
   - **Scoop & Bitter-Lesson Obsolescence (F27.3):** Scores `low`, `moderate`, `high_scoop_risk`, `high_scaling_obsolescence_risk`, or `unknown` with explicit `unknown_disclosures` and `null` preprint counts whenever `published_date` metadata is missing (zero fabrication).
   - **Resource Feasibility & Author Advantage (F27.4, F30.3):** Checks GPU/VRAM, budget, dataset access, and timeline (`--user-resources`) flagging `infeasible_under_user_resources` (or `DROP_RESOURCE_INFEASIBLE` under `--strict-triage`), and scores `author_advantage_fit` (`--author-profile`: `math_theory` vs `systems_engineering`).
   - **Four Deep Gap Lenses (F32):** (1) `root_cause_barrier` (`theoretical_limit`, `measurement_gap`, `data_supervision_gap`, `compute_infra_barrier`) + `missing_or_weak_why_now_enabler` warning; (2) `evaluation_validity_gap` (`shortcut_exploitation`, `dataset_bias_or_contamination`, `metric_saturation`, `construct_validity_mismatch`); (3) `isomorphic_transfer_leads` tagged `lead`; (4) `so_what_decision_impact` (`decision_changing` vs `marginal_gain`) & `durability_12_24m` (`durable_structural_limit` vs `high_scaling_erasure_risk`).
   - **Subfield Depth Hook (F31 `--subfield-preset`):** Deterministic vetting criteria for `nlp_llm`, `cv_multimodal`, `ml_theory`, and `ai_systems`.

## 7. F28 Idea Portfolio, Pre-Mortem & `idea_seed_bundle` Handoff

- **Multi-Angle Idea Portfolio (`--require-idea-portfolio`):** Rejects tunnel-vision single-idea dumps (`DROP_TUNNEL_VISION_PORTFOLIO`) when portfolio mode is enabled; expects `3–4` structurally distinct ideas across `minimal_fix` (`minimal_fix_f19`), `high_novelty_mechanism` (`high_novelty_mechanism_q1`), `benchmark_diagnostic_analysis`, and `low_gpu_fallback`.
- **Pre-Mortem & 1–2 Day Killer Experiment (`--require-pre-mortem`):** Requires `top_failure_modes` (`>= 3`), a `1–2` day `killer_experiment` with an explicit `kill_threshold`, and a `pivot_path` (`DROP_INCOMPLETE_PRE_MORTEM` when missing/incomplete).
- **Standardized `idea_seed_bundle` (`--seed-bundle-out`, `research_scientist_idea_seed_bundle_v1`):** Exports surviving gaps with `gap_id`, `closest_work_ids`, `prior_art_boundary`, `full_text_digests`, `gap_tier_ceiling`, `resource_feasibility`, `scoop_and_obsolescence_risk`, F28 portfolio/pre-mortem, F30 trajectory/failure/author/code fields, F32 lenses, and F31 `subfield_vetting` (with unassessed idea `ratings` kept strictly `null` for downstream idea scoring and project-state tracking).

