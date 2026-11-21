# AI and computer-science gap, RQ, and experiment path

Use this path when the proposed contribution concerns an AI model, agent, dataset, benchmark, evaluation method, software system, or formal claim. It specializes the [gap audit](gap-audit.md), [engineering diagnosis](engineering-vs-gap.md), [prior-art search](precedent-search.md), and [RQ workflow](research-workflow.md). It is a decision protocol for this skill, not a source of ready-made novelty claims. Do not use the empirical-plan checker for a purely theoretical result; a theorem needs a formal statement, assumptions, proof/counterexample search, and independent proof review instead of invented benchmark fields.

## 1. Split the proposed contribution before searching

Write separate claims for **problem**, **mechanism or algorithm**, **data/benchmark**, **evaluation protocol**, **observed result**, **boundary condition**, and **deployment or systems consequence**. Record what is reused and what is changed. A proposed pipeline with known retrieval, reranking and prompting components may have a valid evaluation or systems contribution, but do not rename it as a new model family. For each claim, ask what exact older result would defeat *that claim* and what empirical or theoretical difference would matter.

Keep three dates distinct: first public version, peer-reviewed publication, and the date at which the current proposal is being assessed. A paper's novelty at publication is a historical judgment; a new proposal's overlap is a current search decision. Link preprint, proceedings and journal versions but inspect claim changes by version.

## 2. Search for equivalent work, not only the preferred acronym

Use separate query families for the task/outcome, algorithmic operations, assumptions, dataset/metric, older terminology, adjacent CS fields, failures/replications, and direct closure. For fast-moving AI work include arXiv and the relevant official proceedings or review platform; for NLP include the ACL Anthology where appropriate; for systems include systems venues and artifacts; for theory include relevant mathematical and CS indexes. Use the [multi-query campaign](../scripts/search_campaign.py) for an auditable first pass, verified known-paper controls, and source-failure visibility. Then inspect references, citing work, author code, benchmark versions, and full texts. Do not infer method equivalence from title embeddings, abstract similarities, a top-five panel, or a model's binary novelty judgment.

For the closest work, compare: inputs/outputs, training and inference information, objective, mathematical operation, data flow, assumptions, evaluation population, comparator, resource budget, and actual result. State exact overlap, difference, and consequence with page/equation/code locators. An implementation detail, additional component, new acronym, or leaderboard point is not a distinct scientific contribution by itself. An unread or inaccessible closest paper remains an unresolved threat. A direct verified precedent kills only the matched claim; it need not kill a different boundary or measurement claim.

Search benchmark and data **lineage**, not only paper lineage: benchmark papers, dataset revisions, sample overlap, contamination reports, leaked labels, public test-set tuning, benchmark-specific tricks, and prior code/artifact releases. A gain on a widely reused test set can be real but its interpretation depends on exposure and selection history. Capture query failures, returned versus screened records, close works read at full text, and the stopping reason. A low-yield query triggers reformulation, not a novelty score increase.

## 3. Prove the observed failure is technically valid before promoting a gap

When the trigger is a weak local score, failed reproduction, or broken agent/system, freeze the failing commit, dataset version, split manifest, preprocessing, prompts/configuration, model/API version, metric code, seeds, logs and hardware. Check in this order:

1. **Identity and leakage:** stable sample IDs; duplicates and near duplicates; train/validation/test, temporal or group separation; data or answer contamination; evaluator answer access; external retrieval corpus boundaries. A hash or split name alone does not prove separation.
2. **Metric and task:** hand-checkable examples; label mapping; direction, denominator and aggregation unit; task-specific scoring; uncertainty. For LLM judges, verify reference answers, judge prompt/version, order effects, inter-rater disagreement and a human audit where feasible.
3. **Reference fidelity:** paper and official-code versions, defaults, model weights, tokenizer, prompt template, retrieval index, optimizer, early stopping, seeds, precision, libraries and hardware. Mark undisclosed parameters unknown.
4. **Fair comparison:** equal information access, training data, search space, tuning attempts, prompt iterations, token/compute/time budget and stopping rules; disclose unequal resources if the research question explicitly studies that tradeoff.
5. **Reproduction and isolation:** reproduce a known baseline under matched conditions; change one suspected defect at a time; preserve failed and repaired runs; rerun the comparison only after the apparatus is valid.

Classify `implementation_error`, `protocol_mismatch`, `under_specified_reproducibility`, `candidate_method_boundary`, `candidate_nonreplication`, or `unresolved`. A repaired bug is useful engineering but not a gap. An invalid baseline cannot support a method superiority claim. If a technical defect remains, design a diagnostic experiment and withhold the scientific conclusion. A negative result after matched independent checks may become a valid reproducibility or boundary study, subject to prior-art and consequence checks.

## 4. Turn one surviving uncertainty into an RQ

An RQ must specify the system/task and unit, manipulated or compared condition, outcome/metric or formal property, target population/distribution, strongest rival explanation, and what observation would distinguish them. Separate **performance RQ** (“does X improve Y under Z?”) from **mechanism RQ** (“is the improvement caused by A rather than B?”), **boundary RQ**, **measurement RQ**, **systems RQ**, and **theory RQ**. A leaderboard question is legitimate when its decision consequence and fair protocol are clear; it does not automatically answer why a method works.

Write supportive, falsifying, and indeterminate outcomes separately. “No statistically significant difference” may be indeterminate if the interval is too wide; it is not automatically evidence of equivalence. State the smallest useful effect or decision threshold **before** seeing the held-out result when making a confirmatory claim. Name the independent unit for uncertainty: examples, users, tasks, graphs, datasets, seeds, machines, or sites are not interchangeable. Cluster repeated observations correctly.

For causal or mechanism language, specify an intervention and identification assumptions. An ablation can show that a component is necessary in a particular implementation; it rarely proves the claimed causal mechanism by itself. Pair it with a rival-specific control, alternative mechanism or predicted interaction. A prompt or configuration that was chosen after examining test outcomes makes the resulting claim exploratory until tested on untouched data or a new independent evaluation.

## 5. Generate experiments as a portfolio of decisive tests

Create at least three candidate plans before choosing the main one:

| Candidate | Purpose | Minimum design | Stop or revise if |
|---|---|---|---|
| Small diagnostic | Kill an engineering explanation cheaply | Tiny hand-checkable cases, reference baseline, metric/split/contamination tests | The apparatus is wrong or the failure disappears after repair. |
| Primary discriminating test | Separate focal and rival explanations | Matched conditions, prespecified primary contrast, independent evaluation units, uncertainty and resource parity | The predicted patterns are identical, the contrast is not measurable, or closest prior work already did it. |
| Robustness and mechanism follow-up | Test whether the effect survives and why | Ablation plus negative control, stress or boundary test, alternate data/implementation where justified | Only one cherry-picked setting works, controls fail, or the mechanism prediction does not survive. |

For each plan record **information gain per cost** in words: which live explanation can the result eliminate, what resource it needs, and whether a cheaper analysis can answer the same question. Do not use a single expected-improvement score as the decision rule. Prefer the smallest test that can change the research decision, then a stronger confirmation on an untouched split or independent benchmark. Include a fallback: if the proposed method fails but the apparatus is valid, report the negative or boundary result honestly, narrow the RQ, or stop; do not fabricate a new method name to rescue the paper.

Each executable experiment needs: exact intervention and comparator, dataset/version and split hash, feature/label/retrieval access, baseline source and implementation, metric script/hash, tuning and compute budget, stochastic seed policy, primary analysis and interval, failed-run/exclusion policy, artifact path, and a result that would falsify the focal explanation. Log amendments and every attempted run. Use [the run-receipt checker](../scripts/check_experiment_manifest.py) after execution, while recognizing that it cannot verify files or reproduce results.

### AI/CS-specific design attacks

| Work type | Decisive confound to attack | Minimum useful control or comparison |
|---|---|---|
| New model or training method | Extra data, parameters, compute, tuning or hidden preprocessing | Strong tuned simple baseline, matched budget, learning curves, ablations and multiple seeds/independent units. |
| LLM prompt, agent or tool use | Test-set/prompt exposure, model version drift, retrieval leakage, judge bias, unequal token/tool budget | Frozen prompts/model/tool versions, task-level analysis, blind or audited judging, cost and failure accounting, no test-driven prompt selection. |
| Retrieval or RAG | Index/corpus leakage, oracle retrieval, answer-in-context contamination, changed retriever rather than generator | Same corpus snapshot and retriever, answerable/unanswerable cases, citation entailment and abstention, per-stage ablation. |
| New dataset or benchmark | Duplicate samples, weak labels, unintended shortcuts, unrepresentative tasks, public-test reuse | Dataset lineage, label audit, near-duplicate and contamination checks, simple baselines, external or prospective validity test. |
| Systems or infrastructure | Hardware, load shape, warm-up, caching, correctness, tail latency and energy accounting | Same hardware/workload, correctness gate, throughput/latency distribution, cost/energy and failure-injection receipts. |
| AI for science | Proxy metric mistaken for scientific discovery, confounding, unit mismatch or invalid assay | Domain-valid measurement, independent external validation, negative controls and domain expert review. |

When human subjects, private data, security-sensitive evaluation or deployment risk enters the plan, apply current institutional, venue and domain rules; do not infer approval from a technically valid experiment.

## 6. Link the artifacts and stop unsafe claims

Maintain a gap record, RQ card, and empirical AI/CS experiment plan with matching IDs. Start from the [fictional gap](ai-cs-gap.fixture.json), [RQ](ai-cs-question.fixture.json), and [experiment plan](ai-cs-experiment-plan.fixture.json) only as schema examples; replace every invented source, hash and result. Run:

```bash
python scripts/check_ai_cs_research_plan.py gap.json question.json experiment-plan.json
```

The checker reuses the gap and RQ structural checks, verifies cross-links, blocks confirmatory novelty with unread closest work, catches a failed-implementation claim before engineering checks pass, rejects test-set tuning and non-discriminating predictions, and requires a primary test and mechanism follow-up. A structural pass is **not** a validated gap, RQ or experiment. A plan with engineering checks still `planned` cannot be interpreted as completed evidence. Before a positive claim, inspect actual source passages, code, data, receipts and uncertainty; obtain independent technical or domain review for consequential work.

The experiment-plan generator in [AI-Researcher](https://github.com/NoviScl/AI-Researcher) expands an idea into detailed proposed experiments, and [AI Scientist](https://github.com/SakanaAI/AI-Scientist) iterates code, plots, writing and reviews within templates. The useful pattern here is an executable, revisable plan. The generated plan is not evidence that its motivating baseline failure, novelty or causal explanation is true. This skill requires engineering and prior-art gates before interpreting the loop and preserves negative or invalid outcomes instead of turning them into a positive story.
