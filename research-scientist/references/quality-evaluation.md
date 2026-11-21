# Quality evaluation and regression cases

## Review basis and limitations

A separate reviewing agent inspected the local skill on 2026-11-21 and applied its instructions to the synthetic cases below. This was a one-pass, read-only reasoning exercise: no real paper discovery, live venue lookup, model-to-model benchmark, human expert study, or executable research experiment was performed. The reviewer saw the skill and case inputs; this was not a blinded evaluation. Outputs below are the reviewer's actual bounded dispositions, recorded here for regression use. They are not measured accuracy rates.

The comparative source was [K-Dense scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills), local commit `ec59a29a03d5c40f73ab40878df04860bc00e876`:

- `skills/hypothesis-generation/SKILL.md`, v2.4: read in full; object distinctions, evidence boundary, causal estimands, rivals, measurement, discriminating predictions, prior outcome exposure, and analysis planning.
- `skills/scientific-critical-thinking/SKILL.md`, v1.5: read in full; evidence extraction, missing reporting versus missing conduct, result-specific risk of bias, body-of-evidence certainty, and proportional critique.
- `skills/literature-review/SKILL.md`, v1.11: inspected lines 1–140; source coverage, independent full-text eligibility, records/reports/studies, citation registration versus claim support, and PRISMA count reconciliation.
- `skills/peer-review/SKILL.md`, v2.4: inspected the intake and initial workflow through the start of methods/statistics; claim-evidence mapping, confidentiality, and reporting completeness versus merit.

The comparison covers the named K-Dense files and this skill's gap, engineering, research, prior-art, and scoring references as they stood at review time. It does not assess the full K-Dense library.

## Synthetic cases and observed dispositions

All names, study descriptions, and venue facts in this section are invented fixtures. Do not cite them as real publications or recommendations.

| Case and supplied raw evidence | Reviewer output applying the skill | What this checks |
|---|---|---|
| **Renamed precedent.** Proposal claims a new algorithm that repeatedly selects the observation with largest posterior variance. Supplied older full-text passage defines the same selection rule, assumptions, stopping rule, and target; only the proposal's acronym differs. | `direct_precedent_found`; the central algorithm novelty claim fails. Cite the supplied passage in the fixture and disclose reuse. No claim about field-wide novelty or a new scientific benefit follows from renaming. | Contribution-level equivalence outranks vocabulary difference. |
| **Inaccessible closest work.** Three abstract-only hits include one abstract claiming the exact same result; its full text is inaccessible. The other hits are less close. | `insufficient_search_or_access`; retain the closest paper in the unresolved queue and seek lawful full text. Do not declare novelty, do not assert that the apparent precedent definitely closes the claim, and do not score its proof soundness from the abstract. | Abstention and access-level discipline in both directions. |
| **Local bug.** A reproduction loses accuracy; a supplied run log shows train normalization was omitted while the reference protocol requires it. No corrected run exists. | `implementation_error`; correct and rerun the matched protocol, preserve the failed run and deviation. The existing evidence cannot establish a method weakness or scientific gap. | Engineering diagnosis precedes scientific interpretation. |
| **Unknown venue fee.** A supplied current CFP states a deadline and scope but links to a fee page that is unavailable. User budget is capped. | Scope fit can be described; mandatory cost and budget feasibility are `unverified`. No zero-cost claim, complete fit score, or assured affordable recommendation. Search an official fee source; retain a conditional option if appropriate. | Missing cost is not free, and a hard constraint cannot be averaged away. |
| **Agent disagreement.** Three agents say no precedent after identical title queries. One agent supplies a verifiable full-text passage showing the same mechanism, target, and result. | Inspect that passage and bibliographic/version identity. If equivalence holds, reject that novelty claim regardless of the three-agent majority. Their repeated query is one coverage pattern, not three independent confirmations. | Evidence outranks agent count or confidence. |
| **Unsupported numerical comparison.** Paper A is full-text and B is abstract-only. Requested ranking is overall quality /10. | Do not provide a definitive overall ranking. Give comparable dimensions only, with B's unavailable dimensions `not assessed`; identify which material is needed for comparison. | Missing evidence is not a low score and cannot be hidden by reweighting. |
| **Exploratory result presented as prediction.** Analyst has already inspected all outcomes, then requests a preregistered confirmation of the observed pattern on the same data. | The pattern remains exploratory; timestamp a future analysis plan honestly and use an untouched holdout or new replication for a prospective test. Do not describe the already-seen pattern as an a priori prediction. | Timing and evidence provenance constrain claim language. |

## Improvement findings from the snapshot

1. **RQ operationalization needs more depth.** Add unit of observation versus analysis; construct validity, reliability, calibration and invariance when relevant; explicit causal target and identification assumptions; predictions that discriminate rivals; indeterminate outcomes; and the analyst's prior exposure to outcomes. The existing card is a useful frame but can be completed with scientifically vague entries.
2. **Scoring needs dimensional anchors and calibration.** A universal 10 described as “field-shaping” is inappropriate for clarity or transparency. Use dimension-specific endpoints, disclose that /10 ratings are judgments rather than validated measurements, calibrate with relevant worked examples, and do not force an ordering when uncertainty or reasonable weights reverse it.
3. **Keep appraisal constructs separate.** Reporting completeness, conduct, result-specific risk of bias, and certainty of a body of evidence are different. An unreported procedure is not evidence it was not performed. A checklist total must not become a scientific quality score.
4. **Resolve instruction conflict.** The snapshot's question card says “never a novelty score” while the scoring reference permits user-requested provisional novelty ratings. Preserve mandatory categorical evidence status; clarify that an optional explained score cannot replace it or certify originality.
5. **Make agent integration explicit.** Assign different query families and evidence tasks, give independent critics the claim and raw sources rather than the proposed favorable verdict, preserve source IDs and locators, and resolve conflicting assertions by inspection rather than voting. Repeated outputs from one evidence lineage are not independent support.

The linked research-workflow, artifact-template, scoring, and agent-orchestration references now address these findings; this review did not retest those changes.

## A defensible comparison plan

To assess whether the skill matches or improves on a baseline, freeze both versions, the agent/model/tool access, budget, source snapshot or search date, and evaluation tasks. Include several fields and negative cases where no gap survives. Keep development tasks separate from held-out evaluation tasks. Run both workflows on the same inputs; do not give one broader retrieval or an answer key.

Have domain reviewers blinded to workflow identity evaluate source-to-claim support, closest-precedent detection, false-gap claims, appropriate abstention, meaningful RQ answerability, measurement/design validity, and venue fact accuracy. Count search records separately from unique eligible studies and fully inspected decisive works. Include time, retrieval/API failures, token/tool cost, and unresolved full texts. Report disagreements and adjudication with evidence. Track false novelty assertions separately: one persuasive but false gap can be more consequential than several missed suggestions.

For numerical score reliability, use independently rated common examples, record dimension-level disagreements, and test whether rankings persist under justified alternative weights. Do not label confidence “calibrated” without held-out outcome evidence and a specified calibration target. Never convert LLM judge agreement into expert validation.

Until that comparison is performed, describe concrete workflow improvements and their checks. Do not claim parity or superiority to K-Dense or any other research system.

## Deterministic arithmetic check

The optional `scripts/score_math.py` passed local arithmetic and missing-dimension checks on 2026-11-21; [`evaluation/test_score_math.py`](../../evaluation/test_score_math.py) records the subsequent regression for an invalid score masked by a missing dimension. These checks cannot establish rating reliability, novelty, venue accuracy, or agent compliance.

## Multi-index discovery probe

On 2026-11-21, the bundled `scripts/search_papers.py` was run against the query `graph neural networks` with two records requested per source. The first-page probe returned two records each from OpenAlex, Crossref, and Europe PMC; keyless Semantic Scholar returned HTTP 429 and was marked unchecked. A two-page Europe PMC probe first exposed repeated records because the helper incorrectly sent a `page` parameter. The helper now follows the response's `nextCursorMark`; a repeated two-page probe returned four distinct source IDs. Local tests cover score, identity/split, and search helpers, including HTTP failure versus valid zero, malformed body, bounded result, repeated page, and Europe PMC cursor handling. These probes check API plumbing for one query, not literature recall, source independence, or novelty accuracy.

The OpenAlex helper initially placed an optional key in the query URL. The official API also supports bearer authorization, so the helper now sends `OPENALEX_API_KEY` in an `Authorization` header to keep it out of URLs. No real key was used in the probes.

The structured RQ checker was tested on a complete synthetic card, identical focal/rival expectations, missing causal identification assumptions, and unchecked closest work. These checks verify input handling and selected structural invariants, not scientific validity.

The venue dossier helper was tested on fictional AoE deadlines, unknown mandatory fees, complete fee schedules above/below budget, an omitted fee category, currency mismatch, and a timezone-free timestamp. The helper does not verify a CFP, fee page, track policy, or paper fit.

## Citation and experiment receipt probes

On 2026-11-21, the OpenAlex one-hop citation helper was probed with documented example work ID `W2741809807`, one forward page and two records requested. It reported 47 matched backward work IDs, two returned citing records against provider total 1,613, and `bounded_partial`. These are API response counts for one seed, not a complete bibliography, a paper relevance set, or a novelty check. Mocked tests distinguish a valid zero from an HTTP failure, repeated pages and missing totals. The incoming citation API and the seed's `referenced_works` field are leads; inspect the original papers and bibliography.

The experiment manifest checker was tested on fictional matched baseline/candidate receipts, a split hash mismatch, a failed candidate run and a protocol frozen after a run was retrospectively labeled prespecified. These checks can catch missing or internally inconsistent declarations. They do not execute code, verify hashes against files, assess leakage, or establish that a result is real.

On 2026-11-21, the full local suite had 75 passing tests after the additions in this release. The suite also exercises local passage extraction, question/evidence maps, gap-record cross-links, manuscript ledgers, scorecard weight sensitivity, and venue cost/time gates. These are software regression checks and synthetic fixtures. They are not a measured false-gap rate, paper-writing quality test, reviewer calibration study, or parity benchmark against the upstream projects.
