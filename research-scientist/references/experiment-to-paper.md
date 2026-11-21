# From research question to defensible experiment and paper

Use this module when a question requires code, data, experiments, simulations, proofs, or a reproducibility study. It turns a candidate idea into an inspectable study. The agent may plan and audit experiments; running generated code requires the user's authorized execution environment and explicit resource boundaries. The scientific claim is limited by the evidence that actually exists.

## Freeze the study before seeing outcomes

Start from a question card with a named target, rival explanation, observable distinction, and a result that would leave the issue undecided. Record a protocol version and timestamp. Specify the unit of analysis, inclusion rules, data version, split creation and access policy, primary metric and its implementation, statistical comparison, exclusion rules, tuning budget, baseline, seed policy, failure handling, and planned sensitivity checks. Use prospective language only for decisions made before inspecting the relevant outcomes. Later changes are allowed, but label them amendments or exploratory analyses with a reason and timestamp.

For computational work, preserve the exact repository commit, environment or lockfile, dependencies, hardware where material, data identifiers, model/checkpoint versions, command, random seed, logs, result artifacts and hashes. A hash identifies bytes; it does not establish that the data or metric is scientifically correct. Keep private data paths and credentials out of shareable reports.

## Validate the apparatus before testing a scientific claim

1. Reproduce a reference or simple baseline under its documented protocol. If the source omits necessary details, record the ambiguity and test plausible choices separately.
2. Audit sample IDs, labels, units, exclusions, transformations, temporal order, groups and train/validation/test boundaries. Check that fitting, retrieval, prompt construction and feature selection do not use information unavailable at deployment or prediction time. Use [engineering diagnosis](engineering-vs-gap.md) when the result begins with a failure.
3. Check the metric on a tiny hand-worked example, including direction, denominator, missing cases, thresholds and aggregation. A plausible score from a broken metric is not evidence.
4. Match baseline and candidate on data, preprocessing, information access, compute, tuning budget, seeds and evaluation code. Record every deviation; do not silently compare unlike conditions.
5. Run a minimum viable pilot that can invalidate the proposed mechanism. Move to expensive runs only if the pilot passes the protocol and the unanswered question still matters.

If a defect invalidates a run, keep its receipt and mark it invalid. Correct the defect and rerun; do not use the broken result as evidence of a research gap. When a method underperforms, distinguish a confirmed observation from a causal explanation by controlled ablation or an equivalent discriminating check.

## Run with receipts and bounded iteration

Before each run, record what the run tests and the comparison it will make. Afterward, store exit status, logs, result values, artifact hashes and failures. An agent may propose the next run using existing results, but this is adaptive exploration unless the decision rule was prespecified. Reserve untouched data or independent replication for a confirmatory claim. Do not use an LLM's positive review or a visually appealing figure as a stopping rule.

Track experiments in a run table with these fields: `run_id`, `role`, `protocol_version`, `code_commit`, `data_version`, `split_manifest_sha256`, `metric_id`, `metric_script_sha256`, `command`, `started_at_utc`, `ended_at_utc`, `exit_code`, `result_artifact_sha256`, `result_value`, `deviations`, and `decision_timing`. Start with the [fictional JSON example](experiment-manifest.schema-example.json), replace every fixture value, and run `python scripts/check_experiment_manifest.py your-manifest.json`. The optional checker catches missing provenance and comparison mismatches. It is a structural check, not reproduction or statistical validation.

Use a fixed run, request, time and compute budget. When an experiment fails, preserve the error and replan explicitly. Do not let repeated autonomous code edits or review loops erase earlier results. Execute untrusted or model-written code only in an environment with appropriate isolation, data access and resource limits; inspect actions and generated artifacts before relying on them.

## Analyze and report all decision-relevant outcomes

Report the primary comparison specified by the protocol, including negative and inconclusive results. Distinguish exploratory subgroup findings, hyperparameter-selected results and post hoc exclusions. Include effect sizes or appropriate estimates, uncertainty, sample/seed basis and meaningful failure modes; choose the analysis for the design rather than imposing one generic significance test. Compare the closest eligible methods under a fair protocol. Show ablations only when they test a stated mechanism, and explain what each ablation can and cannot rule out.

Every plot and table must trace to a stored result artifact and transformation script. Check axis labels, units, denominators, missing runs, error bars, numerical rounding and whether the prose describes the same quantity. A failed plotting script does not invalidate the underlying experiment automatically, but an unverifiable plot cannot support a central claim.

## Convert evidence into a manuscript

Write the methods from the run receipts and actual data-processing history. Write results from verified artifacts, including failures material to the claim. Write related work from read sources and a contribution lineage; never infer method details from abstracts. Draft the title and abstract last, so their scope matches the results. Use the [paper-writing module](humanizer-paper-writing.md) for section construction, citation-to-claim checks and a final style pass.

Before submission, conduct a skeptical review: Can another researcher reconstruct the comparison? Are the baseline and candidate matched? Is the apparent gain robust to reasonable choices? Does an older paper already contain the mechanism or result? Does the conclusion survive the strongest alternate explanation? Does the venue require particular ethics, data/code, authorship or AI-use disclosures? Treat reviewer scores as critiques, not measurements of scientific truth. Record unresolved objections and narrow claims when the evidence does not settle them.

## Stop conditions

Do not advance a positive method or scientific-gap claim while any of these remains decisive and unresolved: invalid split/labels/metric, unmatched baseline, failed or uninspectable run, inaccessible closest precedent, unverified central result, or a paper draft that invents methods or values. A technically valid negative result may still be publishable, but its contribution must be stated as the evidence supports.

This workflow adapts the useful staged idea → experiment → writing → review loop seen in AI Scientist, while adding protocol, provenance and adversarial gates. It is this skill's own procedure; it does not embed or require that repository's code. See [source notes](repository-landscape.md) for the inspected upstream implementation and its limits.
