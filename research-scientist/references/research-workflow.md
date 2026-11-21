# Research workflow reference

Read the sections needed for the current task. This guide is a working method, not a claim that every field uses one universal standard.

## 1. Frame the research decision

Before searching, state:

- **Domain and object:** field, phenomenon, technology, population, system, or corpus.
- **Decision:** what the user wants to understand, choose, change, explain, test, or build.
- **Question type:** descriptive, causal, mechanistic, comparative, predictive, diagnostic, design/engineering, interpretive, theoretical, mathematical, or another field-specific form.
- **Scope:** context, population/system, outcomes/constructs, period, languages, publication types, and boundaries.
- **Inputs and constraints:** supplied papers/data, access, time, compute, methods, collaborators, funding, ethics, and intended venue/audience.
- **Current state:** existing question/idea, known methods, evidence, assumptions, and decisions already made.

Avoid adding population/outcome/comparator terms mechanically. First identify what the user needs to decide; then define terms that make that decision empirically, conceptually, or formally answerable.

If the topic is broad, split it into search questions such as: What is the central phenomenon? What are the competing explanations? Which settings or methods matter? What evidence is missing or inconsistent? Which assumptions carry the result? Do not let the query list silently redefine the user's problem.

## 2. Pick a fit-for-purpose search and review design

### Review types

| Type | Use | Minimum discipline |
|---|---|---|
| **Orientation / rapid map** | Establish the landscape or answer a bounded question quickly. | State sources, date, query themes, selection limits, and whether papers were read as abstracts or full text. |
| **Narrative review** | Explain a debate, conceptual development, or evidence pattern. | Make the organizing question and selection logic clear; compare evidence instead of listing papers. |
| **Scoping review** | Map concepts, evidence types, or the extent of a field; identify where a later review is warranted. | Predefine scope and eligibility, log sources and selection, map the corpus, report gaps as corpus-bound. |
| **Systematic review** | Answer a focused question under explicit eligibility criteria. | Protocol, reproducible source-specific searches, deduplication, screening and exclusion reasons, structured extraction, risk-of-bias/appraisal method appropriate to design, synthesis plan, and transparent flow/counts. |
| **Meta-analysis** | Statistically combine sufficiently comparable results. | Systematic-review discipline plus effect-size definitions, dependence handling, heterogeneity/model decisions, sensitivity analyses, and publication-bias limits. Do not pool incompatible estimands merely because the software permits it. |
| **Evidence map / living review** | Track a bounded domain over time. | Versioned search date/corpus, stable inclusion rules, update policy, and change log. |

Use a reporting guideline that matches the review (for example, PRISMA 2020 for systematic reviews). A reporting checklist improves transparent reporting; it does not prove that the search was exhaustive, unbiased, or scientifically sound. If the task cannot satisfy systematic-review steps, call the result preliminary/rapid/narrative rather than systematic.

### Source selection

Choose sources according to the field, question, date, languages, and access. Possible sources include disciplinary indexes, PubMed/Europe PMC, OpenAlex, Crossref, Semantic Scholar, arXiv or other preprint servers, OpenReview, institutional repositories, trial registries, standards, government sources, and domain-specific corpora. Web search is useful for discovery and source-chasing, but general search-engine results are not a substitute for a scholarly database search.

Use complementary sources where practical; explain why each source fits and what it misses. Do not say “searched all databases” unless that is literally true. Respect rate limits, access controls, licenses, institutional terms, and privacy. Never bypass a block or human-verification barrier. A rate limit or unavailable full text reduces coverage; it does not count as a zero-hit search.

### Query design and logging

For each concept, build variants from:

1. Preferred terms, synonyms, abbreviations, spelling variants, older terminology, and field-specific vocabulary.
2. Problem/task/phenomenon terms and outcomes or constructs.
3. Methods, mechanism, population/system, setting, and boundary conditions.
4. Nearby discipline terms and wording used by known seminal papers.
5. Disconfirming/closure searches: “already solved”, replications, contrary findings, null results, later work, and named closest methods.

Keep query length appropriate for each backend; broad conceptual clauses can be searched separately. Record each actual query exactly enough to rerun it, with source, date/time and time zone if relevant, filters, source response count, records retrieved, records inspected, and status/errors. Counts at the query, deduplicated-record, report, and underlying-study levels are different. A search that was planned but not executed is not coverage.

Use backward/forward citation chaining from a small seed set, review articles, corrections/retractions, and related terminology. Citation counts and “cited by” are discovery signals, not evidence quality. De-duplicate preprint/published versions, conference/journal extensions, and multiple reports of one study while retaining the relationship and version actually read.

## 3. Read and extract evidence

### Access ladder

Label each source as one of: **full text inspected**, **selected full-text sections**, **abstract only**, **metadata/snippet only**, **unavailable**, or **not checked**. A result derived from an abstract cannot be upgraded to full-paper appraisal because a tool summarized it. If OCR/parser output is used, inspect layout-sensitive passages, equations, tables, figures, references, page breaks, and footnotes when they affect the claim.

### Evidence units

Keep records, reports, studies, and claims distinct:

- **Record:** one database result.
- **Report:** a publication/preprint/abstract/protocol about work.
- **Study or dataset:** the underlying empirical or theoretical work; one study may have several reports.
- **Evidence claim:** one bounded statement supported or challenged by a particular source passage/result.

For each central source extract as applicable:

| Field | Questions to answer |
|---|---|
| Identity/status | Exact title, authors, year, venue or preprint, DOI/URL, version, corrections/retraction, related reports? |
| Question and contribution | What problem does the work actually pose and claim to add? |
| Theory/assumptions | Which construct, causal structure, mechanism, formal assumptions, or scope conditions are presupposed? |
| Design | Experimental, observational, qualitative, formal, computational, interpretive, engineering, or mixed? What is the unit of analysis? |
| Data/material | Population/system, setting, sample, dataset, corpus, provenance, inclusion, exclusions, and missingness? |
| Measures/method | Operationalization, instruments, model, procedure, baseline/comparator, controls, implementation? |
| Result | What was observed or proved? Is the result estimate-specific, conditional, or exploratory? |
| Uncertainty/validity | Precision, power, robustness, confounding, alternative explanations, assumptions, generalizability? |
| Limitations | What authors state, what reviewers state, and what your analysis infers—kept separate? |
| Locator/provenance | Which page, section, table/figure, equation, supplement, or stable passage supports this extraction? |

Attach unique source and claim IDs. Use exact quotations only when wording matters; otherwise paraphrase faithfully and cite the locator. Keep contradictory evidence alongside supporting evidence. Mark missing fields unknown; never fill an extraction schema from model expectations.

### Synthesis

Organize by claims, mechanisms, assumptions, findings, methods, and boundary conditions. For each theme ask: What do results agree on? Where do they diverge? Could differences arise from population, measurement, implementation, setting, power, estimand, or study quality? What would discriminate explanations? Which claim depends on one group, one dataset, or one method family? State whether the synthesis is descriptive, interpretive, causal, or quantitative.

Do not count repeated papers by the same underlying study as independent confirmation. Assess quality using field-appropriate tools and the unit relevant to the conclusion. No single universal quality score is appropriate across randomized trials, ethnographies, formal proofs, engineering studies, and theory papers.

## 4. Gap and novelty audit

### Attack-first audit sequence (mandatory before endorsing any gap)

Do not begin by listing what is "interesting" or "promising" about a candidate idea. Run an adversarial falsification pass in strict order:

1. **Reject self-inflicted engineering & protocol defects:** Check whether an observed failure, low baseline score, or surprise comes from train/test leakage, duplicate IDs across splits, broken/untuned baselines, metric bugs, or unequal compute/tuning budgets ([engineering diagnosis](engineering-vs-gap.md)). Fixing bad engineering is a bug fix, not a scientific gap.
2. **Reject common non-gap failure traps:** Explicitly test and kill candidates that fall into known pseudo-gap patterns:
   - *Method-first novelty:* starting with a trendy tool/architecture and inventing a problem around it without a real failure mode or stake.
   - *Gap without stake / grant grandiosity:* "nobody has applied X to Y yet" or sweeping macro slogans where answering the question changes no decision, prediction, or mechanism.
   - *Benchmark without deployment or prediction without scientific leverage:* high accuracy on a static split with no causal/mechanistic discrimination or operational boundary.
   - *Filling domain gaps from memory:* asserting field absence from model priors rather than verified multi-source searches and read full texts.
3. **Kill via direct & disguised prior art:** Restate the mechanism in plain language (stripping coined names/acronyms) and search alternate terminology, component combinations, and adjacent fields.
4. **Verify coverage & reading basis:** Confirm `known_seed_checks` passed and all closest precedents were read at full text (never abstract-only). Only after surviving steps 1–4 may a candidate be evaluated as `supported_candidate`.

### Classify the signal before calling it a gap

Useful candidate types include:

- **Unresolved disagreement:** independent results or interpretations conflict under apparently comparable conditions.
- **Boundary/coverage:** an established result has not been tested in a consequential population, context, scale, time period, language, regime, or operating condition. Absence in one search corpus is only a corpus-coverage observation.
- **Measurement/construct:** the field's operationalization may not capture the target construct or decision.
- **Identification/causal:** the design cannot distinguish the stated causal claim from credible alternatives.
- **Mechanism/theory:** an outcome is observed but competing mechanisms, predictions, or scope conditions remain unresolved.
- **Method/assumption:** a conclusion depends on an assumption, baseline, estimator, benchmark, or procedure whose failure could change the result.
- **Reproducibility/robustness:** results have not been independently reproduced or survive plausible analytic/implementation choices.
- **Translation/implementation:** demonstrated effects do not answer a real deployment, decision, scale, safety, or stakeholder question.
- **Reporting/access:** evidence is unavailable or insufficiently described. This may be a reporting/research infrastructure problem rather than an unstudied scientific phenomenon.
- **Conceptual/problematisation:** a dominant assumption or framing may be wrong or overly narrow. Ask what would change if the field's premise were challenged, not only what subgroup has not been sampled.

Keep the following separate: author-declared future work (a lead from one paper), reviewer request/criticism (a review signal), repeated methodological limitation (an observed pattern), missing term/result in a bounded corpus (a search observation), and an unresolved, important scientific question (a synthesis claim requiring evidence). Reviewer repetition can reflect venue norms, author concentration, sampling bias, or stale expectations.

### Candidate-gap record

For each proposed gap, record:

1. **Claim:** one precise sentence about what is unresolved and for whom/which system/under what conditions.
2. **Type and consequence:** why the missing knowledge matters; what explanation, decision, method, or outcome could change.
3. **Support:** independent papers and source-located findings/limitations, identifying one study's multiple reports and author overlap.
4. **Counterevidence and nearest work:** later work, alternative terminology, adjacent fields, null/contrary findings, replications, and strongest precedent.
5. **Search coverage:** sources, actual queries, date, filters, results inspected, full-text availability, failed sources, and unchecked vocabularies.
6. **Alternatives:** already solved, local flaw not a field gap, irrelevant difference, resource/access limitation, measurement artifact, or reviewer fashion.
7. **Disposition:** `supported_candidate`, `early_signal`, `not_a_gap`, or `insufficient_evidence`, with a reason. Do not turn these labels into numeric novelty scores.
8. **What could resolve it:** a query, source, expert, replication, dataset, or experiment that would most change the disposition.

Do not use a universal “three papers means real gap” rule. The number of independent sources is useful context; sufficiency depends on field size, study type, evidence quality, scope, and the claim. If only one or two papers support it, label it an early signal. Do not kill an idea as already explored without naming the direct precedent. Do not label it potentially underexplored unless meaningful foundational, alternate-wording, adjacent-field, and disconfirming searches were actually performed. Even then it is not proof of novelty.

### Novelty comparison

Search the *claim* and mechanism under different vocabulary, including adjacent fields and later citations. Compare the closest studies on:

| Dimension | Check |
|---|---|
| Problem/question | Is the underlying question the same, even if names differ? |
| Target and setting | Same population/system, use case, regime, scale, or boundary? |
| Construct/estimand | Same outcome, quantity, interpretation, or causal target? |
| Mechanism/method | Same core mechanism, algorithm, theory, or design? |
| Assumptions | Which assumptions are shared, relaxed, or changed? |
| Data/material | Same dataset/corpus, type, source, or unit? |
| Comparison/evaluation | Same baseline, metric, controls, analysis, and success criterion? |
| Contribution/claim | What was established, and what remains untested? |
| Failure case/limitations | Does the proposed question address a real limitation or merely change labels? |

Use reasoned labels such as `direct_precedent`, `partial_precedent`, `adjacent_precedent`, `counterevidence`, and `no_match_found_in_searched_scope`. A difference is meaningful only if it could change a prediction, inference, decision, or capability. A recombination of two methods, a new dataset, a trendy setting, or a larger model is not automatically a scientific contribution.

Large language model novelty/quality judgments are not independent verification. The RINoBench paper introduces expert-labeled novelty judgments precisely as a benchmark problem; treat its results and other benchmarks as scoped evaluations, not proof that a model can certify novelty in an arbitrary discipline.

For any live novelty claim, follow [prior-art and precedent search](precedent-search.md), including alternate terminology, component-level queries, citation chasing, full-text checks of closest work, and a kill search. If the candidate arose from a failed implementation or reproduction, first classify it with [engineering failure versus research gap](engineering-vs-gap.md). Do not coin a method name that obscures reused components or treat a new combination as novel without evidence of a meaningful consequence.

## 5. Formulate research questions and hypotheses

### Build a question from the evidence

Separate these objects explicitly:

- **Topic:** broad subject area.
- **Problem:** consequential unresolved state, failure, disagreement, or decision.
- **Research question (RQ):** the answerable inquiry that would reduce the uncertainty.
- **Hypothesis:** a tentative prediction or explanation with observable consequences; omit it when the study is exploratory, interpretive, or not hypothesis-testing.
- **Project/method:** a plan for answering the RQ; a tool build is not by itself a research problem.

State the target population/system/context, focal construct or mechanism, comparison or counterfactual when appropriate, outcome/evidence, and boundary. Use a causal form only if the design can identify a causal effect. Avoid questions that bundle several estimands, presuppose a desired result, imply causation from association, or cannot be answered with an available observation, argument, proof, or interpretation.

Use a question grammar appropriate to the field:

- **Causal/effect:** Under which conditions does X change Y relative to what comparator, for which units and over what period?
- **Mechanistic:** Which process accounts for Y, and what observation distinguishes that process from rival mechanisms?
- **Descriptive/measurement:** How common/structured is X in a defined population/corpus, and what valid measurement identifies it?
- **Comparative/predictive:** Which approach performs better for the defined target and decision, against which baseline and metric, under what distribution shift?
- **Design/engineering:** Which requirements/constraints can a design satisfy, and what tradeoff or failure mode is measured against a meaningful baseline?
- **Interpretive/historical:** How does a bounded set of sources support or challenge competing readings, periodizations, or explanations?
- **Formal/theoretical:** Under what assumptions does a claim hold, and what counterexample or boundary would falsify/generalize it?

These are prompts, not templates to force every question into.

### Diverge, then converge

Generate candidates from distinct lenses, not merely wording variants:

1. Resolve a consequential evidence disagreement.
2. Test a hidden assumption or a boundary condition.
3. Find a mechanism that distinguishes rival explanations.
4. Improve measurement, benchmark validity, or identification.
5. Study a consequential population/system/setting that changes the theory or decision.
6. Replicate, stress-test, or explain a surprising/null result.
7. Transfer a mechanism across fields only after explaining the structural analogy and its limits.
8. Challenge whether the field is asking the right question.

Then discard candidates that have no consequential stake, no answer path, no meaningful difference from precedent, no falsifier/disconfirming evidence, impossible access/resources, unacceptable risk, or no decision that changes. Kill weak, duplicate, or unfalsifiable ideas plainly as `not_a_gap` or `implementation_error`—never soften a fatal flaw into *"promising with minor tweaks"*, present every candidate as viable, give generic objections, or bloat project scope instead of sharpening the test. Novelty without importance is not enough; feasibility without value is not enough.

### Good Question Card

Apply the [field-specific question checks](rq-field-checks.md) when the target domain changes the relevant units, evidence, validation, ethics, or counter-reading. Use them to sharpen the same question card, not as a substitute for reading field sources.

For a reusable structured card, use [the JSON example](question-card.schema-example.json) and the [local checker](../scripts/check_question_card.py). Replace every example field with actual study details and source IDs. The checker flags empty fields and identical focal/rival predictions; a passing check does not establish novelty, identification, validity, or feasibility.

If the RQ rests on a claimed gap, retain its candidate ID and [gap audit record](gap-record.schema-example.json). Run `python scripts/check_gap_record.py your-gap-record.json` before promoting `supported_candidate`; inspect the returned errors and warnings, then read the sources yourself. A passed structural check is a readiness aid, never a positive scientific verdict. Formulate the RQ even when the honest gap status is `early_signal` if the question would still produce useful evidence, but remove unsupported originality language.

Build a small **decision table** before selecting an experiment or proof: rows are focal account, strongest rival, and conservative/null account; columns are predicted observation, required assumptions, plausible artifact, and what a negative or indeterminate result teaches. Keep genuinely distinct accounts; do not manufacture symmetry. When all accounts predict the same result, revise the measure or contrast before claiming the design tests the mechanism. Test a cheap pilot's measurement reliability, sample/data access, and baseline fidelity before funding a large study. State the pilot's go/no-go criterion in advance when possible.

For each candidate that survives, present:

- **Question:** one sentence, with target/system, relation/mechanism, and boundary.
- **Problem and stake:** who/what is affected and what changes if answered?
- **Evidence and gap:** claim IDs and locators; observed facts vs inference; access level.
- **Closest work:** direct/partial/adjacent precedents and the precise difference.
- **Rivals and assumptions:** strongest competing explanations or interpretations; assumptions at risk.
- **Answer path:** design/material/data, unit, measures, comparison/control, analysis or proof.
- **Discriminating result:** what observation would favor one account over another?
- **Falsifier / stop rule:** what result would weaken or kill the proposed account or project?
- **Pilot:** cheapest informative next action, with prerequisites, expected duration/cost if known.
- **Feasibility and ethics:** data/access, skills, compute, human/animal review, privacy, safety, reproducibility.
- **Novelty status:** search boundary, closest precedents, unresolved uncertainty. If a user requests a /10 assessment, report it separately under the scoring rubric; a score cannot replace this status.
- **Strongest reviewer objection:** the best reason a knowledgeable skeptic would reject it, and what evidence addresses that objection.

FINER (feasible, interesting, novel, ethical, relevant) can prompt discussion, but should not be summed into a universal score. Prefer transparent tradeoffs and user priorities. Offer fewer than the requested number when weaker candidates fail.

## 6. Study/proposal planning

Translate the selected RQ into a plan that makes evidence inspectable:

1. State the target claim, hypothesis (if appropriate), and scope conditions.
2. Define the unit, sample/material, recruitment or selection, inclusion/exclusion, and data provenance.
3. Define constructs, measures/instruments, outcomes, estimand, metrics, and meaningful effect/interpretive standard.
4. Specify comparator, baseline, controls, negative controls, ablations, counterfactual, or rival texts as the question requires.
5. Choose design and analysis before observing outcomes where confirmatory inference matters; name assumptions, confounders, missingness, multiplicity, power/precision, and sensitivity/robustness checks.
6. State what result would support, weaken, or leave the claim unresolved; distinguish exploratory from confirmatory evidence.
7. Define a cheap pilot, stop/continue criteria, expected resource bounds, and dependencies.
8. Address domain-specific ethics, human/animal review, consent, privacy, data/IP rights, biosafety, and safety. Flag required institutional/professional review; do not imply it has been granted.
9. Preserve protocol versions, data/code/model versions, deviations, and provenance so later claims match the actual execution.

For observational studies, do not infer causation without an identification strategy. For machine learning, include a meaningful baseline, leakage-resistant split, uncertainty, implementation details, and failure/robustness analysis. For qualitative/humanities research, fit evidence-selection, positionality/reflexivity, interpretation, and rival readings to the discipline rather than imposing experimental language. For mathematical work, define assumptions and proof obligations. These are starting points; use the field's recognized standards and consult domain experts.

## 7. Cross-field adaptation and problematisation

Do not treat all disciplines as if they were experimental ML. Choose evidence and standards that fit the question: proof, archival source, ethnographic material, clinical trial, observational design, engineering benchmark, computational experiment, or a combination. Use domain playbooks when available (for example, clinical PICO is not a default for humanities; FINER does not validate a causal design).

When proposing cross-field transfer:

- Remove domain nouns and describe the structural challenge in neutral terms.
- Search for mechanisms that solved a comparable constraint in at least one other field; for a substantial technical ideation proposal, search more than one adjacent field.
- Explain what structural features are shared and what does not transfer (assumptions, measurement, incentives, scale, theory, ethics).
- Search the target field for prior transfer/near-miss and test whether the mechanism solves the named challenge rather than adding a fashionable component.
- State predictions and a cheap disconfirming test.

Gap spotting is only one way to make a contribution. Ask what a dominant explanation assumes; what observation it cannot explain; which competing framing changes the question; and what evidence could adjudicate between framings. Do not manufacture a radical reframing where the evidence only supports incremental mapping.

## 8. Source and tool handling

- Prefer native scholarly APIs/database tools for discovery and citation metadata; record the backend actually used. Use search aggregators for leads and follow links to original sources.
- For a local paper collection, use local search/QA to locate candidates, then inspect the source passage and original PDF when the claim matters. Retrieval ranking is not scientific appraisal.
- A PDF parser/OCR system improves extraction and navigation; check tables, equations, multi-column reading order, citations, figures, and page locators when material. Parsing does not establish correctness.
- Review screening models can prioritize records but should retain inclusion/exclusion reasons, an uncertain category, and human checks proportionate to review stakes. Do not hide borderline decisions or let a black-box screen create the reported flow counts.
- For agent/tool execution involving generated code, preserve user authorization and isolation. A plan is not execution; arbitrary research code must not run in an unsafe environment.
- Minimize collection and persistence of private, sensitive, unpublished, or participant data. Do not upload it to third-party services unless the user has chosen and authorized that route.

## 9. Recommended result shape

For small requests: direct answer + directly relevant sources + uncertainty.

For substantial review/gap/RQ work:

1. Scope, review type, search date, sources, and limitations.
2. Funnel with actual records/reports/studies searched, inspected, deduplicated, and screened where those counts exist.
3. Evidence map organized by themes/claims, not one paragraph per paper.
4. Gap register with support, counterevidence, precedent, status, and coverage.
5. A few distinct Good Question Cards and the strongest objection to each.
6. Recommended next decision/pilot and what evidence would change the recommendation.

For requested manuscript prose, finish the argument and evidence map first, then apply [Humanizer and paper-writing](humanizer-paper-writing.md) and recheck all edited claims. For requested ratings or venue recommendations, load [Scoring and venue fit](scoring-and-venue-fit.md) and state the rubric, weights, evidence basis, and limits.

Use tables only where comparison helps. Cite the primary paper or stable source near the claim. Clearly label access limitations and non-executed plans.

## References for methodological context

- PRISMA 2020 is a reporting guideline for systematic reviews: <https://www.prisma-statement.org/>.
- FINER criteria overview (use as a prompt, not a scoring instrument): <https://pmc.ncbi.nlm.nih.gov/articles/pmid/37838572/>.
- Sandberg & Alvesson, “Ways of constructing research questions: gap-spotting or problematization?”: <https://doi.org/10.1177/1350508410372151>.
- RINoBench, expert-labeled research-idea novelty judgment benchmark: <https://arxiv.org/abs/2603.10303>.

## Operationalization before promoting a question

For each shortlisted RQ, distinguish the unit observed from the unit analyzed; define target population, estimand or interpretive target, measurement validity/reliability, and relevant cross-group or temporal measurement invariance. For a causal question, specify exposure/intervention, comparator, outcome, time horizon, effect scale, and identification assumptions; an association alone does not identify that effect.

Make a prediction–rival matrix: each explanation, expected observable outcome, discriminating comparison, assumptions, and failure/control checks. Define supportive, disconfirming, and **indeterminate** outcomes before collecting confirmatory evidence. Low power or a failed manipulation may leave the question unresolved; do not relabel it a successful falsification. For qualitative/formal work adapt to rival interpretations/counterexamples rather than forcing statistical thresholds.

Disclose which data/results were already viewed. Mark exploratory analyses as exploratory; a later preregistration cannot retroactively make them prospective. Register amendments and rationale. Confirmatory analysis plans should specify exclusions, missingness, multiplicity, stopping, dependence, and sensitivity checks proportionate to the design. Map every central claim to the evidence it requires and the decision that follows each outcome.

For a parsed PDF, record parser name/version, mode (native text versus OCR where available), document version, page count, and extraction errors when material. Verify a decisive passage on the rendered page, including its table headers, equation symbols, negations, footnotes and reading order. If the parser omits a block or locator, mark it unresolved and inspect the original page; do not infer that absent extracted text means the paper lacks the claim.

## Citation verification levels

For each consequential claim, distinguish: (1) a citation key is present in the answer and maps to a retrieved chunk; (2) the chunk maps to the correct bibliographic work/version; and (3) the original passage, with its methods, qualifiers, tables and context, actually supports the precise claim. A formatting or DOI-registration check addresses only parts of level 2. Model-generated citations and DOI fields must be independently resolved; a plausible key must never be promoted directly to verified evidence. If the closest precedent or a score rests on one citation, read that primary passage or mark the conclusion unresolved. Record failures at the level they occur.
