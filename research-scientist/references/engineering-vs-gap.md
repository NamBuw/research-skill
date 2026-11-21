# Engineering failure versus research gap

Use this diagnostic whenever a proposed “gap” begins with code that does not run, a result that failed to reproduce, a weak benchmark score, a broken pipeline, or an implementation the author dislikes. A local failure is evidence about that run. It is not evidence that the scientific method is deficient or that the field has an open problem.

## Triage before interpretation

Freeze the failure before changing the implementation. Record:

- the exact claim or reference result being tested;
- repository, commit, package, model, data, and protocol versions;
- hardware, dependencies, environment, seeds, configuration, and resource budget;
- data provenance, preprocessing, splits, exclusions, units, and evaluation script;
- the exact command, logs, outputs, and error state;
- any deviations from the paper, official code, benchmark, or protocol; and
- when the implementation or analysis was changed relative to seeing the result.

Then check, in this order:

1. **Input and data integrity:** correct files, IDs, schema, units, labels, splits, and transformations.
2. **Implementation fidelity:** compare the code path, defaults, model variants, formulas, pseudocode, and appendix with the source. Treat undisclosed details as unknown.
3. **Configuration and protocol:** match seeds or seed policy, optimizer, compute, stopping rules, evaluation population, metrics, baselines, and information available to each method.
4. **Mechanical sanity:** run tiny hand-checkable cases, invariants, dimensional/unit checks, edge cases, and tests of the metric against known outputs.
5. **Reference result:** reproduce a known result or baseline in the same environment before interpreting a new comparison.
6. **Independent check:** where the claim is consequential, ask another implementer to inspect or reproduce the failure without inheriting the first investigator's undocumented assumptions.

Do not tune, patch, change metrics, drop failed cases, or widen the claim after seeing the outcome without recording the change. A post-result repair can be useful engineering; it cannot retroactively turn the observation into a preregistered prediction. Preserve the original run and report deviations.

## Classify what the failure supports

| Finding | What it supports | Gap status |
|---|---|---|
| Local bug, wrong flag, dependency mismatch, stale cache, incorrect data path, or metric bug | A defect in this implementation/run | `implementation_error`; repair it. It is not a research gap. |
| The local setup differs materially from the paper or benchmark protocol | A protocol mismatch | `protocol_mismatch`; align the protocol or limit the claim. |
| The paper omits a detail needed to reproduce the result | A disclosure or reproducibility concern | `under_specified_reproducibility`; report the missing detail. It is not automatically a new scientific question. |
| The method's stated assumptions do not hold in a target regime | A testable boundary-condition question | `candidate_method_boundary`; verify assumptions and search for prior boundary analyses. |
| Correct independent implementations under matched conditions repeatedly fail to reproduce a central claim | A reproducibility result or evidence against the claim | `candidate_nonreplication`; seek independent confirmation and quantify whether the difference matters. |
| Correctly implemented methods show systematic fragility across a prespecified, relevant perturbation | A robustness question | `candidate_robustness`; test whether the fragility is already known and whether it changes a decision. |
| A systematic engineering diagnosis yields a reusable tool, measurement, or validated method that changes what researchers can infer | A possible engineering or methodological contribution | State that contribution directly; do not rename the original bug as a scientific gap. Establish generality, comparison, and evidence. |
| The problem remains unresolved in the literature and a valid design could distinguish live explanations | A candidate scientific gap | Run the full [prior-art search](precedent-search.md) and [gap audit](gap-audit.md). |

Use `unresolved` when the source, environment, or protocol is not sufficient to classify the failure. Do not force a scientific interpretation to avoid that answer.

## Decide whether a valid failure is scientifically consequential

For a failure that survives technical diagnosis, ask:

- Does it challenge a central claim, or only a secondary implementation detail?
- Is the expected behavior part of the paper's stated scope and assumptions?
- Is the comparison fair on data, information, resources, tuning budget, baselines, and metric implementation?
- Could a known factor explain the failure (distribution shift, variance, label noise, numerical precision, evaluation leakage, dependency drift, or a hidden protocol difference)?
- Does the result generalize beyond one local run, dataset, or implementation?
- What observation would distinguish method fragility from residual engineering error?
- Would resolving it change a scientific conclusion, a method choice, or a real decision?
- What independent replication, stress test, reanalysis, proof, or counterexample is the smallest credible next step?

A failed reproduction may be a valuable result. It becomes a research contribution when the failure is technically credible, properly scoped, connected to prior claims, independently checked where possible, and consequential. “We could not make it work” alone establishes none of those conditions.

## Keep the report honest

Separate these layers in every write-up:

1. **Observed:** what the specific run produced, with logs and provenance.
2. **Diagnosed:** which implementation or protocol checks passed, failed, or remain unknown.
3. **Inferred:** what the result suggests about the method or its boundary, with alternative explanations.
4. **Literature status:** which sources directly support or challenge that inference and what was searched.
5. **Next claim:** the narrowest statement a proposed follow-up could actually test.

Never call a reproduction “independent” if it copied undocumented fixes, configs, or decisions from the first run. Do not hide engineering defects behind a grand method label or novelty score. Use [artifact templates](artifact-templates.md#11-failure-diagnosis-record) to preserve the triage.
