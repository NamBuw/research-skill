# AI/CS/CV/NLP Good-Question Pressure Cases

Adapted from `Rimagination/good-question` (`pressure-cases`, `orchestra-lenses`, and `platt-strong-inference`, MIT License, Copyright (c) 2026 Rimagination), specialized strictly for AI, computer science, computer vision, and NLP.

## Core Gate Rule

Before promoting any weak benchmark score, reproduction failure, or qualitative observation into a research gap or novelty claim, execute `scripts/check_engineering_diagnostics.py` (`--code-dir`, `--splits`, `--metrics`, `--compact`) and `scripts/check_experiment_manifest.py` (`--verify-files`, `--compact`). Fixing a defect yields `"repaired_engineering_bug"`, never `"genuine_scientific_novelty"`.

## Eight AI/CS/CV/NLP Pressure Cases

1. **Method-First Architecture Reskinning**
   - *Raw input*: "Apply Mamba/Transformer/Diffusion to dataset X because nobody has tried it there yet."
   - *Trap*: Solution-first framing without an empirical bottleneck, baseline parity, or mechanistic uncertainty.
   - *Pass*: Convert into an uncertainty comparing mechanisms; require a tuned simple baseline (`simplest_alternative`) and falsifying prediction.
   - *Fail / Kill*: Reject if no decision or mechanism changes or if a tuned simple baseline matches performance.

2. **Grandiose Stitched Pipeline (No Parsimony)**
   - *Raw input*: "Introduce Unified Multi-Agent Neuro-Symbolic Framework combining RAG + CoT + Reranker + Critic."
   - *Trap*: Coining a grand name over known components without proving every module earns its complexity.
   - *Pass*: Strip coined acronyms, trace every component to prior art, require component-by-component ablation with `>0` marginal gain over the simplest baseline.
   - *Fail / Kill*: Reject (`DROP_OVERCOMPLICATED`) if `simplest_alternative` is missing/boilerplate or extra modules yield `<=0` gain.

3. **Self-Inflicted Engineering Bug Promoted as a Gap**
   - *Raw input*: "The baseline collapsed / gave NaN / underperformed, proving prior work fails here, so we add a stabilization module."
   - *Trap*: Disguising local implementation errors under `benchmark_observation` or `literature_synthesis` triggers.
   - *Pass*: Freeze failing code/configs, run `scripts/check_engineering_diagnostics.py`, repair the defect, and re-benchmark the clean baseline.
   - *Fail / Kill*: Block promotion (`DROP_ENGINEERING_BUG`) whenever any of the 6 `ENGINEERING_CHECKS` remain failed, planned, or unknown in `confirmatory` mode.

4. **Asymmetric HPO & Baseline Neglect (Dacrema Trap)**
   - *Raw input*: "Our neural model beats default ItemKNN / BM25 / ResNet-50 across benchmarks."
   - *Trap*: Giving the candidate 50 HPO trials and 5 seeds while running the baseline untuned (1 trial, 1 seed).
   - *Pass*: Enforce identical HPO trial budgets, tuning splits, and seed counts against a tuned reference baseline.
   - *Fail / Kill*: Reject (`hpo_budget_asymmetry` / `seed_count_mismatch`) or reclassify as `repaired_engineering_bug` if the tuned baseline ties or wins.

5. **NLP Benchmark Contamination & Single-Prompt Fragility**
   - *Raw input*: "A revised prompt template improves GSM8K / MMLU accuracy by +8%."
   - *Trap*: Test-set contamination, evaluating on training splits, or tuning one brittle prompt directly on test examples.
   - *Pass*: Audit contamination, freeze prompt versions prior to held-out evaluation, and test >=3 prompt paraphrases reporting variance.
   - *Fail / Kill*: Reject on `nlp_benchmark_contamination`, `nlp_eval_on_train_split`, or `nlp_prompt_template_sensitivity_missing`.

6. **CV Mismatched Backbone / Resolution / Augmentation Budget**
   - *Raw input*: "Our attention block improves ImageNet/COCO over published ResNet-50 (224px) baselines."
   - *Trap*: Changing backbone capacity, input resolution (384px vs 224px), crop ratio, augmentation (RandAugment/Mixup), or epochs simultaneously.
   - *Pass*: Isolate one `variable_changed` per experiment while holding backbone, resolution, crop, augmentation, and epoch budget constant.
   - *Fail / Kill*: Reject (`budget_or_config_mismatch`) unless an explicit single-variable ablation isolates the proposed change.

7. **Split Leakage & Single-Seed Cherry-Picking (Kapoor Trap)**
   - *Raw input*: "Global feature normalization + our classifier boosts tabular accuracy by +12%; 2 diverged seeds were excluded."
   - *Trap*: Fitting `StandardScaler` / `TfidfVectorizer` before `train_test_split`, overlapping sample/group IDs across splits, and dropping failed seeds.
   - *Pass*: Run `scripts/audit_alignment.py` (`--split-column`, `--group-column`) and `scripts/check_engineering_diagnostics.py`; report every attempted run in `scripts/check_experiment_manifest.py` (`--verify-files`).
   - *Fail / Kill*: Reject (`preprocessing_before_split_leakage`, `split_overlap_leakage`, `excluded_failed_runs`, `single_seed_cherry_picking`).

8. **Problem Inflation & Missing Platt Strong-Inference Falsifier**
   - *Raw input*: "A 0.2% accuracy fluctuation exposes a catastrophic crisis requiring a 4-stage framework."
   - *Trap*: Dramatizing minor seed/hyperparameter noise into a crisis without a discriminating three-hypothesis test.
   - *Pass*: Check effect size + 95% CI across >=3 seeds and specify Platt Strong Inference hypotheses: `H1` (focal mechanism), `H2` (strongest rival), `H3` (null / engineering artifact), with non-identical predictions and explicit falsifiers.
   - *Fail / Kill*: Reject (`DROP_PROBLEM_INFLATION` / `predictions_do_not_discriminate`).
