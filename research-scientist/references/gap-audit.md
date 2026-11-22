# Research-gap and novelty audit

Use this protocol whenever the task asks “what is missing?”, “is this a real gap?”, “is this novel?”, “what should we study next?”, or proposes a literature-derived contribution. This is the highest-risk stage of the research workflow: a false gap contaminates the question, design, proposal, and paper. Prefer a defensible “not established” to a confident-sounding answer unsupported by coverage.

## Governing distinction

The following are different claims and need different evidence:

1. **An author says X remains future work.** Evidence: an exact, correctly attributed passage in that paper. This establishes the author's stated limitation at that time; it does not establish that the issue is important or remains open.
2. **A reviewer asks for X / criticizes X.** Evidence: a real review attached to the correct paper. This establishes reviewer feedback, not field consensus or a scientific gap. Review availability is usually selected and incomplete.
3. **A searched corpus contains little/no work on X.** Evidence: logged queries and returned/inspected records under stated boundaries. This establishes only a corpus/search observation. It can result from vocabulary, database, date, language, access, or retrieval failure.
4. **Independent findings conflict or depend on an untested assumption.** Evidence: source-level results/designs/assumptions from the actual papers, comparability analysis, and counterevidence. This may motivate a scientific question.
5. **An important scientific problem remains unresolved.** Evidence: a synthesis argument that combines the right direct studies, demonstrates consequence/importance, survives adversarial search for closure and alternatives, and fits a question that can resolve the uncertainty. Absence in search results alone cannot prove this.

Do not slide from claims 1–3 into claim 5 without the intervening evidence and inference being shown.

## The evidence-to-gap chain

Every candidate must be reconstructible through this chain:

```text
source and stable locator
    → study/report identity and independence
    → observed result, design limit, assumption, or contradiction
    → cross-study synthesis (or explicit corpus boundary)
    → unresolved claim and who/what it affects
    → answerable research question
```

If one arrow depends on an inference, label it as an inference and explain the warrant. Do not allow an LLM-generated gap sentence to become the evidence for itself. A retrieval score, topic cluster, missing phrase, “future work” sentence, reviewer comment, or novelty-classifier verdict is not the chain.

### Run a candidate through an auditable state transition

For each proposed gap, preserve the original claim and move it through these states. The same candidate can move backward after new evidence; preserve the old record and reason for revision.

| State | Action that advances it | Action that rejects or demotes it |
|---|---|---|
| `lead` | Record the exact source passage, parser output, review comment, anomaly, or user observation that suggested it. | Discard if the lead was misquoted, misattributed, or merely a retrieval artifact. |
| `bounded_uncertainty` | Define population/system, construct, comparison, consequence and a possible closing precedent. | Reframe if the issue is a local implementation fault, vague method preference, or a question already answered by the source. |
| `source_checked` | Verify decisive primary passages, study identity and independence; classify each item as result, method, assumption, limitation, author future work, or context. | Demote if the only evidence is metadata, abstract, author future work, or repeated reports of one study. |
| `challenged` | Run alternate-vocabulary, mechanism, historical, adjacent-field, and citation-trail searches; inspect the closest work and counterevidence. | Mark `not_a_gap` when a direct precedent or a non-consequential difference closes it; use `insufficient_evidence` for unresolved decisive access/search gaps. |
| `supported_candidate` | Explain the unresolved inference and why resolving it matters, state an answer path, and expose remaining blind spots. | Return to an earlier state when new work changes the comparison or the proposed experiment cannot distinguish the accounts. |

Do not collapse `lead` and `supported_candidate` into one LLM step. A source can suggest a candidate; a separate adversarial pass must try to eliminate it. This incorporates the useful staged ideation pattern of the AI Scientist and author-limitation mining systems while refusing their abstract/top-result or single-verification-query output as a novelty certificate.

For a durable machine-readable record, copy [the fictional gap-record example](gap-record.schema-example.json), replace every fixture value, and run `python scripts/check_gap_record.py your-gap-record.json --evidence-dir extracted_blocks/`. The checker verifies ID links, full-text access for a positive candidate, **all** `closest_work_ids` read at full text with linked source locators, local quote/locator verification against extracted PDF/JSON blocks when `--evidence-dir` is supplied, a screened adversarial query, at least two successful source/query families or an explicit coverage exception, and engineering triage when the trigger is a failed implementation. It flags an author future-work statement used as the only support. Cross-check against the recorded search campaign via `python scripts/check_gap_campaign.py your-gap-record.json campaign.json`, which rejects empty `known_seed_checks` on any `supported_candidate` and tracks canonical statuses (`rate_limited`, `bot_blocked`, `source_failed`). Counts mean *retrieved into the local run* and *screened in that run*, not provider-wide totals. A source name does not prove index independence, and an exception needs scientific review. Passing is **only structural**: source truth, passage entailment, search recall, relevance, independence, scientific importance, and inference still require primary-source and expert review. Use `early_signal` or `insufficient_evidence` when those remain unresolved.

### Automated Multi-Perspective Exploration & Gap Gate Pipeline

1. **Multi-perspective exploration (STORM/Co-STORM):** Run `python scripts/storm_explorer.py --topic "<topic>" --corpus corpus.json --out storm.json --compact` to generate complementary AI/CS/CV/NLP perspectives, deduplicated `information_table`, hierarchical `outline`, and `uncovered_branches`.
2. **Deterministic gap & parsimony gating:** Run `python scripts/gap_pipeline.py --topic "<topic>" --corpus corpus.json --digests digests.json --candidates candidates.json --out gap_out.json --compact` (or `--workspace <dir> --compact` with optional `--feedback-store` and `--allow-partial`). Candidates are screened sequentially through:
   - `DROP_TEMPORAL_LEAK` (post-cutoff citation leak)
   - `DROP_UNREAD_CITATION` / `DROP_RETRACTED_SUPPORT` (read-before-cite and retraction block)
   - `DROP_ENGINEERING_BUG` (unchecked/failed engineering diagnostics)
   - `DROP_ALREADY_SOLVED` (per-candidate kill-search across titles + abstracts/texts with `require_abstract=False`)
   - `DROP_PROBLEM_INFLATION` / `DROP_OVERCOMPLICATED` (F19 parsimony self-interrogation: rejects dramatized minor variance or >=3-module stacks lacking a concrete `simplest_alternative` and positive ablation)
   - `DROP_INSUFFICIENT_COVERAGE` (non-empty STORM `uncovered_branches` or single-regime corpus)
   - `DROP_SINGLE_PAPER_FRAGILE` (<2 independent supporting papers)
   - `DROP_ARTIFICIAL_SCOPE` / `DROP_SGHA_CRITIC_REJECT` (5-role skeptic/critic gate)
   - `DROP_DUPLICATE` (token-Jaccard dedup and feedback memory)

### Structured Mining, Tier Triage, Deep Lenses & `idea_seed_bundle` (F27, F28, F30, F31, F32)

1. **Structured Gap Discovery (`scripts/storm_explorer.py`):** Optionally pass `--failure-cases` and `--target-regime` to extract `contradiction_matrix` (`cross_regime_conflict` vs `same_regime_conflict`), `coverage_hole_matrix` (`genuine_coverage_hole` vs `trivial_reskin_risk`), `assumption_violations`, chronological `research_trajectory` (`Gen1 -> bottleneck -> Gen2 -> tradeoff -> open_root_limit`, never inventing missing years), `failure_first_patterns`, and P4 `isomorphic_transfer_leads` (strictly tagged `evidence_level: "lead"`, never supporting evidence).
2. **Cross-Vocab & Code Kill-Search (`scripts/gap_pipeline.py`):** Pass `--storm`, `--campaign`, `--citation-graph`, `--failure-cases`, `--code-prior-art`, `--target-venue-tier`, `--user-resources`, `--author-profile`, `--as-of-date`, `--subfield-preset`, and `--seed-bundle-out`. Gate 4 expands `mechanism_aliases` / `alternate_vocabularies`, cross-checks `search_campaign.py` (`combined_results` / `source_records`) and `citation_graph.py` co-citation clusters, and drops shipped GitHub/HuggingFace equivalents (`code_prior_art` `direct_equivalent` / `solved`). Gate 3 blocks `failure_cases` candidates whose engineering checks are unresolved.
3. **Venue Tier, Feasibility & Deep Gap Lenses:**

| Lens / Triage Axis | Canonical Values & Rules |
|---|---|
| `gap_tier_ceiling` | `q1_top_tier_potential`, `tier_a_findings_potential`, `workshop_incremental_only`, `low_impact_dead_end` (`gap_below_target_venue_tier` warning when target exceeds ceiling; `--strict-triage` hard-drops) |
| `scoop_and_obsolescence_risk` | `low`, `moderate`, `high_scoop_risk`, `high_scaling_obsolescence_risk`, `unknown` (requires `unknown_disclosures` and `null` preprint counts when `published_date` is absent) |
| `resource_feasibility` | `feasible`, `infeasible_under_user_resources`, `unverified_missing_constraints` (checked against GPU/VRAM, budget, dataset access, timeline) |
| `root_cause_barrier` & `why_now_enabler` | `theoretical_limit`, `measurement_gap`, `data_supervision_gap`, `compute_infra_barrier`; warns `missing_or_weak_why_now_enabler` when missing or weak |
| `evaluation_validity_gap` | `shortcut_exploitation`, `dataset_bias_or_contamination`, `metric_saturation`, `construct_validity_mismatch` |
| `so_what_decision_impact` & `durability_12_24m` | `decision_changing` vs `marginal_gain`; `durable_structural_limit` vs `high_scaling_erasure_risk` |
| `author_advantage_fit` & `subfield_preset` | Socratic fit (`math_theory` vs `systems_engineering`, data/GPU/time); presets `nlp_llm`, `cv_multimodal`, `ml_theory`, `ai_systems` |

4. **F28 Portfolio, Pre-Mortem & `idea_seed_bundle`:** On `scripts/gap_pipeline.py`, pass `--require-idea-portfolio` (3–4 distinct ideas across `minimal_fix` / `minimal_fix_f19`, `high_novelty_mechanism` / `high_novelty_mechanism_q1`, `benchmark_diagnostic_analysis`, `low_gpu_fallback`), `--require-pre-mortem` (`>= 3` `top_failure_modes`, 1–2 day `killer_experiment` with `kill_threshold`, `pivot_path`), and `--require-code-prior-art`.
   Separately, `scripts/check_gap_record.py` validates these optional fields when present while keeping legacy M3 records compatible. Surviving gaps emit `idea_seed_bundle` (`research_scientist_idea_seed_bundle_v1`) with unassessed idea `ratings` left strictly `null`.

## Gate 0 — Is the request actually answerable as a gap audit?

Before claiming anything:

- Define the **problem**, target phenomenon/system/population, context, likely synonyms, time boundary, and the decision or conclusion that could change.
- Separate the candidate **scientific question** from a product feature, method preference, thesis theme, or broad topic.
- Check whether the question is about **absence**, **contradiction**, **boundary**, **mechanism**, **measurement**, **method**, **reproducibility**, **translation**, or **framing**. Do not relabel generic “more work is needed” as a research gap.
- State current assumptions and uncertainty. If the user has not provided enough domain definition, infer a narrow starting scope and label it; ask only if the choice materially affects the corpus or claim.
- If no live scholarly retrieval or source documents are available, stop short of a field-specific gap claim. Offer a provisional gap hypothesis and the exact verification needed.
- If the proposed gap is motivated by the user's own failed implementation, weak benchmark result, or failed reproduction, read [engineering failure versus research gap](engineering-vs-gap.md) before scientific interpretation. Do not let an engineering fault pass this gate as a gap.

## Gate 1 — Define the gap claim before searching for support

Write one candidate claim in a falsifiable, bounded form, without relying on a newly coined method name, acronym, or promotional phrasing, for example:

> “For [system/population/context] under [boundary], existing evidence cannot distinguish [explanation A] from [explanation B], so [decision/prediction] remains uncertain.”

or, when the signal is about coverage:

> “In [defined corpus/sources/date/languages], we found few studies that measure [construct] in [population/context]; whether this is a field-wide evidence gap remains unknown.”

Ask:

- What would count as a **direct precedent** that closes this gap?
- Which wording, construct, mechanism, and adjacent field could hide such a precedent?
- What finding would show the candidate is unimportant, already resolved, or an artifact of search/design?
- What claim is the user tempted to make that the evidence cannot support?

Do not write an open-ended query (“research gaps in X”) and accept its generated response. Search for the candidate proposition and its possible closure.

## Gate 2 — Build a coverage plan, not just a query

Select a discipline-appropriate, complementary search set. Record why each source is relevant and what it omits. Depending on the field and scope this may include major scholarly indexes, preprint repositories, clinical/trial registries, standards, theses/dissertations, proceedings, cited-by graphs, domain corpora, or primary archives. Don't force sources that do not cover the field.

Create and log separate query families:

1. **Direct/problem queries:** exact problem, task, population/system, outcome/construct, methods, and known term variants.
2. **Synonym/history queries:** abbreviations, alternate spelling, renamed constructs, older nomenclature, discipline-specific terms, and local/non-English language variants when relevant.
3. **Mechanism/method queries:** the same unresolved mechanism, assumption, design, or outcome without the candidate's fashionable label.
4. **Near-neighbor/adjacent-field queries:** different fields or settings that may have addressed the same structure.
5. **Closure queries:** “already solved”, replications, extensions, review papers, benchmarks, null/negative findings, responses, corrections, registered work, and the names of closest authors/methods.
6. **Citation trails:** inspect references and cited-by records for seed papers and direct/partial precedents.

Run broad discovery first, then retrieve the closest records at full text. Once candidate wording emerges, run a separate adversarial “kill search” using alternate terms and named precedents. Log returned vs inspected records separately. Record exact executed queries, filters, dates, language, sort/ranking, source/API errors, and why a search stopped. Never report planned-but-unrun searches as completed.

For a consequential or systematic claim, add a search-strategy review by a domain expert or information specialist when possible. For clinical/biomedical review work, include sources appropriate to the intervention/condition, trial registrations and grey literature as the protocol requires. For a rapidly moving ML topic, include current preprints, conferences, benchmarks/code, and temporal boundary; for humanities/social sciences, use appropriate archives, books, theses, non-English terms, and disciplinary indexes. Search design is field-specific.

Apply the full [prior-art search protocol](precedent-search.md) for query families, source selection, version/identity resolution, contribution-level comparison, and method-lineage checks. If a candidate comes from a technical failure, also apply [engineering failure versus research gap](engineering-vs-gap.md). A semantic search rank or API non-hit is a lead, never a closure result.

## Gate 3 — Resolve records to studies and inspect the evidence

When review text, author limitations, or public decision letters are part of the evidence, use the [review-signal lane](review-signal-mining.md) to preserve exact quotes, response status, denominator and later-work checks. Such text creates a candidate problem; it does not itself establish that the issue remains open or that the authors' interpretation is correct.

1. Deduplicate versions and connect conference/journal/preprint reports of the same work. Count independent **studies/work**, not database hits, versions, reviewer comments, authors, or repeated model runs as separate confirmations.
2. Note shared datasets, author groups, research programs, and dependent analyses. Several papers can be one evidentiary lineage.
3. Inspect full text for every source carrying a central gap claim, whenever available. Abstract-only evidence may locate a candidate but rarely supports a subtle limitation, method, or result claim. Label the access level explicitly.
4. Extract the actual question, assumptions, design, data/population, measures/estimand, comparator, results, uncertainty, limitations, and claim-relevant passages with page/section/table/figure locators.
5. Check corrections/retractions and newer versions where relevant. Separate published, preprint, protocol, registered, and unpublished evidence; do not imply peer review from a repository record.
6. Verify key quotes against the source. OCR, PDF parsers, RAG passages, and secondary summaries can omit negation, conditions, table context, footnotes, and caveats.

Maintain one evidence row per claim and one study identity map. Use [artifact templates](artifact-templates.md#4-evidence-ledger) and [cross-paper matrix](artifact-templates.md#5-cross-paper-comparison-matrix) when the set is large enough.

## Gate 4 — Classify the signal and test alternatives

### A. Understudied population/context/period

Demonstrate the scope of the actual evidence base and why the omitted context could change the theory, estimate, safety, access, implementation, or decision. A new demographic, location, language, scale, dataset, or time window is not inherently important. Check whether existing papers already report subgroup, robustness, or relevant secondary analyses.

### B. Contradictory findings

First verify that the studies address comparable constructs/estimands and are not merely differently named. Compare sample/system, exposure/intervention, baseline, outcome, timeframe, methods, inclusion, implementation, and uncertainty. Look for moderators and analytical choices that can explain the disagreement. Conflicting signs are not a paradox if populations, estimands, or measurement differ. A synthesis that finds heterogeneity can itself be the contribution only if it has an appropriate review question and method.

### C. Theoretical or mechanistic uncertainty

Name competing accounts and their distinct predictions. Show what each existing study can and cannot discriminate. “Mechanism not studied” is weak if no observed result depends on the mechanism or if no possible evidence would separate the accounts.

### D. Method/assumption/measurement gap

Point to the assumption or operationalization in the primary source. Explain how relaxing/changing it could alter the result or decision; search for sensitivity analyses, alternative measurements, better baselines, replications, or methods that already address the issue. A new estimator/tool is not a gap until the current inferential weakness matters.

### E. Replication/robustness gap

Check registered reports, replication attempts, code/data releases, benchmark variants, external validations, and later citations. Distinguish “not reproduced” from “reproducibility failed”; distinguish a small evidence base from evidence of instability.

### F. Translation/implementation gap

Name the actual user/decision, workflow, external validity, safety, cost, scale, or deployment condition not established. Do not infer real-world impact from a lab metric or benchmark score alone.

### G. Conceptual/problematisation

State the dominant framing/assumption and the evidence it cannot explain. Formulate a consequential alternative frame, identify what observations distinguish it, and search prior conceptual/theoretical work. “Nobody challenged this assumption” is an absence claim and needs broad conceptual search, not just a paper database query.

### Always test rival explanations

- **Vocabulary miss:** does the same idea use different terms or older language?
- **Boundary mismatch:** are the studies answering a different population, setting, or estimand than the proposed claim?
- **Solved later:** did subsequent work, an adjacent field, a standard, or a dataset close it?
- **Insufficient power/access:** is this a resource limitation rather than an unknown phenomenon?
- **Publication/review bias:** are only positive, accepted, or openly reviewed studies visible?
- **Researcher preference:** is the “gap” merely a desired method, subgroup, model, or venue trend?
- **Artificial novelty:** is the proposed combination different in name but not in mechanism, prediction, or decision?
- **Method-name inflation:** does a newly branded method actually consist of known components with no demonstrated new logic or consequence?
- **Implementation failure:** is the apparent flaw caused by local code, configuration, preprocessing, an invalid metric, or a protocol mismatch?
- **Importance failure:** if resolved, would anything material change?

## Gate 5 — Make an adversarial closure pass

Do not let the same framing that generated a gap be the only framing used to audit it.

1. Write the strongest plausible direct paper/result that would close the gap.
2. Search the closure statement in alternate wording and search the closest known methods, authors, datasets, outcomes, and mechanisms.
3. Inspect review/meta-analysis papers and then primary studies they cite; reviews can also be outdated or wrong.
4. Search forward from the closest direct/partial precedent and inspect extensions, replications, rebuttals, registered work, and newer preprints.
5. Search at least one meaningful neighboring discipline or context if transfer is plausible.
6. Ask whether a more mature vocabulary exists (for instance, the gap may already be called measurement invariance, external validation, calibration, transportability, negative results, replication, or mechanism identification).
7. Record sources that did not answer, not only sources that did.
8. Re-read the candidate after the kill search. Narrow or reject it if the difference is only setting, sample size, metric, or method name without a consequence.

For high-impact/high-stakes gaps, a second knowledgeable reader should try to close the claim. If that review is not available, say so as an unresolved validation risk. More queries improve coverage but never prove omniscience.

## Gate 6 — Assess scientific value separately from open-ness

For a candidate that survives searching, answer in prose:

- What explanation, prediction, decision, design, policy, clinical practice, or user outcome could change if it were resolved?
- Which affected stakeholders care, and what evidence establishes that stake?
- Does the proposed difference have a theoretical, inferential, practical, or methodological consequence?
- Could a simple replication, reanalysis, or existing dataset resolve it more directly than a new complex method?
- What is the smallest study, proof, archive analysis, or comparison that could answer it?
- What would make this line of work not worth pursuing?

Do not hide tradeoffs in a single score. Report open-ness evidence, importance, tractability, feasibility, and ethics separately. A gap can be open but trivial, important but already addressed, important and unresolved but infeasible, or simply not established.

Do not use proposal-stage “novelty” or “excitement” ratings as a proxy for a valuable project. Keep at least four validation questions separate: **(1)** is the literature search/evidence base adequate for the claim, **(2)** does the question appear distinct from closest prior work, **(3)** do domain experts judge the question important/feasible, and **(4)** does executing a pilot support the predicted value? A Stanford human study of NLP ideation and its later execution follow-up illustrate why these stages can diverge: idea-only ratings and reviews after executing a subset of projects did not tell the same story. This is a caution from scoped NLP studies, not a universal performance estimate. See [the human ideation study](https://arxiv.org/abs/2409.04109) and [the execution follow-up](https://arxiv.org/abs/2506.20803).

## Disposition rules

Use the strongest status that the actual evidence supports:

| Status | Minimum meaning |
|---|---|
| `not_a_gap` | A named direct precedent closes the claim, the claim is a non-consequential difference, the issue is a local weakness rather than a research problem, or the signal is explained by review/search artifact. Say which. |
| `early_signal` | A credible lead exists, often from one or two independent works, author-stated limitations, a surprising result, or incomplete coverage; importance or open status still needs checking. |
| `supported_candidate` | Source-level evidence and a defensible synthesis support a precisely bounded unresolved issue; meaningful closure/counter-search was run; consequence and an answer path are explained. It remains a candidate, not certified novelty. |
| `insufficient_evidence` | Search/access/reading/independence/comparability/contradiction or importance is too weak to decide. State the specific next evidence needed. |

Use `potentially_underexplored` only as a clearly bounded novelty-audit conclusion when foundational, alternate-wording, adjacent and disconfirming searches have all answered sufficiently and no direct precedent is found. Translate it as “not found within these searches,” not “novel.”

For claims of **recurrence across studies**, three independent studies can be a useful minimum screening floor, not a universal law and not enough by itself. A single formal proof/counterexample, authoritative dataset, or pivotal study may be decisive for some questions; a broad population-level synthesis may require much more. Explain the evidentiary logic instead of counting papers mechanically.

## Gap-to-RQ bridge

Do not let a gap label dictate the question. For each surviving candidate:

1. State the uncertainty to resolve as a proposition or decision, not as a paper title.
2. Name the target (population/system/context) and scope at which the uncertainty matters.
3. Identify at least two plausible alternatives or explain why only one is credible.
4. Define the evidence that discriminates alternatives (or state why the question is descriptive/interpretive and does not use competing hypotheses).
5. State which result would change a conclusion and what would count as a null/negative answer.
6. Match methods, units, measures, controls/baselines, analysis, and resources to that answer.
7. Verify that the closest precedent does not already answer the question under another name.

Then use the [Good Question Card](artifact-templates.md#8-good-question-card). If the evidence supports an important question but not a novelty claim, keep the question and remove the novelty claim.

Before promoting the card to a study proposal, run a two-sided prediction check. Write what the focal account and strongest rival each predict for the *same* observable, comparison, timing and units. If both predict the observed pattern, the proposed test cannot discriminate them. Add a better measure, negative control, intervention, setting contrast, proof obligation, or archival source as appropriate, or state that the RQ remains descriptive/exploratory. Name the result that would weaken the focal account and the result that would be indeterminate because of low precision, invalid measurement, noncompliance, or missing data. Freeze confirmatory choices before seeing outcome data; if outcomes were already seen, label the analysis exploratory and seek an untouched test.

## Required report for a substantial gap audit

Report:

1. **Scope and date:** exact field/problem, boundary, sources, languages/time range, review type, and user assumptions.
2. **Actual search funnel:** executed searches and returned/inspected/deduplicated records, reports, and underlying studies where known; source failures/coverage limits.
3. **Candidate ledger:** type, specific chain of source evidence, independence, support/counterevidence, nearest precedent, status, and confidence reasons.
4. **What was killed or narrowed:** name evidence that closed or weakened a plausible candidate; this demonstrates that an adversarial pass occurred.
5. **Survivor RQs:** only if the gap survived; connect each card to evidence, method and falsifier.
6. **What could not be checked:** missing full text, source/rate limit, languages, unindexed venues, private work, lack of expert review, or later work.
7. **Next check:** the paper, database, expert, evidence, or pilot that would most change the conclusion.

Use real counts only. If the search is small, say “scoping pass.” If no candidate survives, report that directly. Never invent a positive finding to satisfy a requested number of gaps.

## Fast reject list

Reject or downgrade a candidate when its only basis is:

- an LLM's generated “gap” paragraph, novelty score, or self-critique;
- the fact that no exact phrase/result appeared in one search;
- one paper's “future work” boilerplate without checking later literature;
- reviewer comments treated as scientific consensus;
- absence of a subgroup without a reason that subgroup changes the inference;
- low citation count, newness, low venue prestige, or a missing keyword;
- a topic cluster with low density or an embedding similarity number;
- combining known methods without a distinct prediction, mechanism, or decision;
- a local dataset/document collection presented as the whole field;
- an abstract-only scan presented as a full-text critical review;
- a single “novelty auditor” verdict with no named closest work or recorded search boundary.
- a newly coined acronym, “framework,” or “unified method” whose underlying steps are known, uncited, or not compared with their closest precedents.
- the user's own coding or engineering mistake presented as a scientific gap before technical diagnosis.

## Methodological anchors

- Sandberg & Alvesson's critique of gap-spotting motivates an assumption/challenge lens alongside coverage claims: <https://doi.org/10.1177/1350508410372151>.
- RINoBench provides a human-expert-centered novelty-judgment benchmark; use it as a reminder that judge performance must be evaluated, not as a runtime certificate: <https://arxiv.org/abs/2603.10303>.
- CKM-HypoGen demonstrates a temporal future-literature evaluation design with explicit topic/corpus boundaries: <https://github.com/TaoJinkai/ckm-hypogen>.
- Paper-Lector's novelty workflow is a useful model for freezing the claim and kill rule before search, recording a bounded verdict, and separating literature originality from technical feasibility. Its paper-specific implementation is not a general novelty benchmark: <https://github.com/huguryildiz/paper-lector>.
