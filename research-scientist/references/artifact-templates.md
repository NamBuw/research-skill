# Reusable research artifacts

Use only the artifacts that help the current task. Keep one canonical record per project and update it rather than regenerating contradictory copies. These formats work in Markdown, CSV, or a project database.

## 1. Research brief

```markdown
# Research brief
- Project / version:
- Updated (date, timezone):
- Researcher / agent:
- Domain and question type:
- Intended decision / audience:
- Topic:
- Problem to resolve:
- Scope: population/system, setting, period, languages, materials
- Out of scope:
- Existing evidence / seed papers:
- Constraints: access, data, time, compute, skills, ethics
- Assumptions (mark each as verified, provisional, or unknown):
- Requested mode and deliverable:
- Unresolved decisions:
```

## 2. Search log

Use one row per executed query. A planned query belongs in a separate “not run” list.

| Run ID | Date/time | Source/database | Exact query | Fields/filters/date range/language | Returned | Exported | Inspected | Status/error | Notes / next query |
|---|---|---|---|---|---:|---:|---:|---|---|

Also record: source version/interface if relevant; deduplication key/rule; records removed as duplicates; preprint/publication relationships; citation-chaining seeds; and any blocked, inaccessible, unavailable, or rate-limited sources. Never infer a count from a search page you did not inspect.

## 3. Screening log (systematic/scoping review)

### Protocol fields

| Field | Definition before screening |
|---|---|
| Review question | One bounded question or set of linked questions |
| Eligible evidence | Study/report types, design, time, languages, setting, population/system |
| Exclusions | Explicit reasons and scope rationale |
| Screening unit | Record/report/study, with cross-report linkage plan |
| Screening stages | Deduplication, title/abstract, full text, other |
| Decision labels | Include / exclude / uncertain, with reason codes |
| Appraisal | Tool/criteria matched to design and inference |
| Synthesis plan | Narrative, thematic, evidence map, meta-analysis; prespecified where appropriate |
| Deviations | Date, change, reason, affected records/analysis |

| Record ID | Report ID / study ID | Stage | Decision | Reason code and brief rationale | Reviewer(s) | Conflict resolution | Full text? |
|---|---|---|---|---|---|---|---|

Report record, report, and study counts separately. In single-reviewer screening, disclose that fact and the checks used; do not imply independent double screening. Preserve unresolved cases instead of silently resolving them by model output.

## 4. Evidence ledger

One row per claim or observation, not one row per paper. Keep the source text and the analyst's conclusion distinct.

| Claim ID | Source ID / citation | Version/status | Access level | Locator | Claim or observation | Exact quote or faithful paraphrase | Direction | Design/unit | Supports/limits which inference? | Quality/caveats | Independent study group? |
|---|---|---|---|---|---|---|---|---|---|---|---|

Recommended access labels: full text inspected; selected full-text sections; abstract only; metadata/snippet only; unavailable; not checked. Recommended direction labels: supports; contradicts; qualifies/bounds; methods-only; context-only; author-suggested future work. “Author-suggested future work” is not itself independent evidence that the gap remains open.

## 5. Cross-paper comparison matrix

| Study group | Question | Theory / assumptions | Population/system/context | Data/material and unit | Design/method | Measures / estimand | Comparison/baseline | Main result | Uncertainty/robustness | Stated limitation | Analyst inference / open issue |
|---|---|---|---|---|---|---|---|---|---|---|---|

Use source IDs in cells, then keep citations and locators in the evidence ledger. Group multiple reports of one study; note shared authors or data where confirmation is not independent.

## 6. Candidate-gap register

| Gap ID | Type | Precise unresolved claim and boundary | Why it matters | Supporting independent works (claim IDs) | Counterevidence / later work / nearest precedent | Search coverage and date | Alternative explanation | Status | Confidence reasons | What would resolve it? |
|---|---|---|---|---|---|---|---|---|---|---|

Allowed status values: `supported_candidate`, `early_signal`, `not_a_gap`, `insufficient_evidence`. Add a prose rationale; do not average into one score. Use “candidate” unless a defensible scope and domain review support a stronger claim. A coverage gap is explicitly about the reviewed corpus, not the entire field.

For a machine-readable audit, use [the fictional JSON example](gap-record.schema-example.json) with [the local structural checker](../scripts/check_gap_record.py). Preserve query IDs and status, source/study IDs and exact locators, access levels, closest-work relations, kill-search query IDs, counterevidence, engineering status, and revision history. The example's fictional content is a schema illustration, not a real gap or literature finding. The checker cannot validate source-to-claim entailment or certify novelty.

## 7. Novelty comparison record

```markdown
## Proposal under audit
[One paragraph that names the problem, core mechanism, setting, assumptions, evidence and claimed contribution.]

## Search record
- Date and sources actually searched:
- Foundational/alternate-wording/adjacent/disconfirming queries:
- Citation trails checked:
- Sources that failed or were not searched:

## Closest precedents
| Work | Relation: direct / partial / adjacent / counterevidence | Problem | Setting | Assumptions | Mechanism | Data | Evaluation | What it establishes | What remains different |
|---|---|---|---|---|---|---|---|---|---|

## Verdict
- Status: already_explored / partially_explored / potentially_underexplored / insufficient_evidence
- Evidence for verdict:
- Strongest case against the proposed novelty:
- Material difference that could change a prediction or decision:
- Unchecked search boundaries:
- Next human/expert check:
```

“Potentially underexplored” means no direct precedent was found within the documented searches. It does not mean the work is novel.

## 8. Good Question Card

```markdown
## RQ-[ID]: [short title]
- Research question:
- Question type / domain standard:
- Problem and stake: what decision, explanation, or outcome changes?
- Candidate gap (ID) and evidence claims (IDs/locators):
- Closest precedent(s) and precise difference:
- Target: population/system/context/time:
- Construct, mechanism, comparison/counterfactual, and outcome/evidence:
- Assumptions and strongest rival explanation:
- Answer path: design/material, unit, measures, comparison, analysis/proof/interpretive method:
- Unit observed versus unit analyzed; dependence structure:
- Measurement validity/reliability and invariance; causal identification assumptions if relevant:
- Prior exposure to data/results; prospective versus exploratory decisions:
- Discriminating observation or argument:
- Falsifier / result that would weaken or stop the project:
- Indeterminate outcome and follow-up evidence needed:
- Feasibility: data/access, skills, time, compute, cost, dependencies:
- Ethics, privacy, safety, permissions, and required review:
- Cheapest useful pilot and decision gate:
- Novelty-search status and unchecked boundaries:
- Strongest reviewer objection and response evidence:
- User priority/tradeoff that would change the choice:
```

For explanatory hypotheses, also state the mechanism and a prediction that differs from each serious alternative. For exploratory or interpretive projects, do not force a directional hypothesis; define what evidence would support, qualify, or challenge the interpretation.

## 9. Study/proposal protocol

```markdown
# Protocol [version/date]
- Question / target claim:
- Confirmatory, exploratory, interpretive, design, or formal:
- Rationale and evidence boundary:
- Population/system/material and unit of analysis:
- Inclusion/exclusion and sample/data provenance:
- Design and setting:
- Outcomes/constructs/estimand/measures:
- Comparator, baseline, controls, or rival evidence:
- Procedures and implementation/version details:
- Analysis/proof/interpretation plan and assumptions:
- Missingness, confounding, multiplicity, power/precision, uncertainty:
- Robustness, sensitivity, negative controls, ablations, replications:
- What supports / weakens / leaves the claim unresolved:
- Stop/continue criteria and low-cost pilot:
- Ethics, privacy, safety, licensing and data-management review:
- Deviations and change log:
- Claims the resulting paper may and may not make:
```

Do not claim preregistration unless the protocol was actually registered before relevant observations or outcome-dependent choices.

## 10. Prior-art search record

```markdown
# Prior-art search — [claim ID]
- Candidate claim in plain language, without a coined name:
- Contribution atoms: problem / insight / method / assumptions / data / evidence / consequence
- What would count as a direct precedent:
- Search date and novelty-as-of date:
- Sources and why each fits the field:
- Query families and exact executed queries:
- Filters / language / date / sort / result limits:
- Returned / inspected / deduplicated records by source:
- Known seed papers retrieved (smoke check only):
- Reference and cited-by trails checked:
- Full-text papers read, access level, and stable locators:
- Source errors, inaccessible work, and unchecked coverage:

| Closest work (verified ID) | Relationship | Problem/insight/method overlap | Exact difference | Why it could matter | Evidence locators |
|---|---|---|---|---|---|

- Strongest direct-precedent case:
- Kill-search queries and what they closed or failed to close:
- Method lineage: component / source / reused, adapted, combined, or derived / actual change
- Conclusion: direct_precedent_found / partial_precedent_found / candidate_difference_survives_search / insufficient_search_or_access
- Confidence and reason:
- Next source, expert, or test most likely to change the conclusion:
```

`candidate_difference_survives_search` means no closing precedent was located in this documented search. It is not proof of originality.

## 11. Failure diagnosis record

```markdown
# Failure diagnosis — [run or claim ID]
- Claim/result being checked:
- Source paper, code, protocol, and version:
- Local code commit, dependencies, hardware, seed/config, and command:
- Data provenance, preprocessing, splits, exclusions, and metric:
- Resource/tuning budget and exact comparator:
- Observed output and log/source locator:
- Deviations from the source protocol:
- Input/data integrity checks:
- Implementation fidelity checks:
- Configuration/protocol checks:
- Hand-checkable invariants and baseline reproduced:
- Independent implementation or reviewer:
- Classification: implementation_error / protocol_mismatch / under_specified_reproducibility / candidate_method_boundary / candidate_nonreplication / candidate_robustness / unresolved
- Alternative explanations still live:
- What new evidence would distinguish them:
- Literature precedents checked:
- Narrowest claim supported:
```

The record describes an observed run and its diagnostic status. It does not label a research gap by itself.

## 12. Paper scorecard

```markdown
# Paper assessment — [paper ID]
- Assessment date and novelty-as-of date:
- Article archetype and target question/venue:
- Material read: full text / selected sections / abstract / metadata
- Search boundary and closest-work matrix:
- Rubric version and weights fixed before scoring:
- Critical gate concerns (validity, ethics, integrity, authorship, data):

| Dimension | Score / 10 or not assessed | Confidence | Evidence and locator | Main uncertainty |
|---|---:|---|---|---|
| Importance | | | | |
| Novelty | | | | |
| Method/proof soundness | | | | |
| Evidence strength | | | | |
| Transparency/reproducibility | | | | |
| Clarity | | | | |

- Weighted overall (if requested):
- Exact weights and calculation:
- Strongest counterargument:
- Missing material that could change the scores:
- Venue fit: assess separately in the venue table.
```

Use the same rubric and reading standard for every paper in a comparison. `Not assessed` is not zero. A weighted total cannot erase a critical flaw.

## 13. Venue-fit comparison

```markdown
| Venue and track | Scope /2 | Contribution /2 | Evidence /2 | Format /2 | Constraints /2 | Fit /10 | Current official sources checked | Key mismatch or desk-reject risk | Confidence |
|---|---:|---:|---:|---:|---:|---:|---|---|---|
```

Browse the current official scope, call, author instructions, and eligibility information before assigning scores. Mark a venue `unverified` when current criteria could not be checked; fit is not acceptance probability.

## 14. Venue submission plan

| Venue/edition/track | Official CFP and checked date | Status | Fit evidence and /10 or unverified | Principal mismatch | Manuscript changes | Primary/fallback role |
|---|---|---|---|---|---|---|

| Venue | Milestone | Official timestamp/timezone + source | User-local time | Confirmed/tentative/unknown | Dependency / responsible person |
|---|---|---|---|---|---|

| Venue | Cost category | Mandatory/optional | Amount/range + currency | Tax/bundle assumptions | Waiver eligibility | Official source/date or estimate basis |
|---|---|---|---|---|---|---|

| Work package | Required input | Estimated effort and basis | Start/finish | Critical dependency | Go/no-go evidence | Buffer |
|---|---|---|---|---|---|---|

Unknown fees are not zero. An expired CFP is not the next cycle. State fallback conflicts with primary notification and simultaneous-submission policy.

## 15. Search expansion round

| Round/source/query IDs | Raw records | New unique records | Newly eligible | New decisive precedents | Full texts pending | Missing seeds / coverage holes | Next expansion or stopping rationale |
|---|---|---|---|---|---|---|---|

Keep discovery, deduplication, screening and included-study counts distinct. Counts describe logged work; they are not evidence of exhaustive recall.
