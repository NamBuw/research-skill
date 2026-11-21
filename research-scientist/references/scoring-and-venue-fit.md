# Scoring research ideas, papers, novelty, and venue fit

Use this reference when the user asks for scores out of 10, a ranked comparison, a paper critique, a novelty comparison, or submission venues. Scores organize evidence and judgment; they do not turn subjective review into measurement. Show the dimensions, evidence, access level, and uncertainty. Never report a single number as a verdict on scientific truth or acceptance.

## Choose the object before scoring

Name which object is being assessed:

- **Idea or question:** assess its evidence base, novelty relative to searched prior art, importance, answerability, feasibility, and falsifiability. Methods/results that have not been run are `not yet assessed`.
- **Completed manuscript:** assess claims against the actual full text, data/results, methods, appendices, and cited work that is accessible. A title, abstract, or introduction cannot support a full-paper score.
- **Published paper:** score the paper's contribution as of its publication date when judging historical novelty. A present-day prior-art search can identify later related work, but cannot retroactively make the original paper less novel at publication.
- **Venue fit:** assess alignment with a specific current call or venue, independently of paper quality and predicted acceptance.

If the user provides multiple papers, freeze the same question, date boundary, rubric, score anchors, and access standard for all of them before comparing. A paper read from full text cannot be ranked confidently against one seen only as an abstract; label the comparison provisional or leave unavailable dimensions unscored.

## Score dimensions and anchors

For completed research papers, provide this profile unless the field or genre calls for a justified adaptation:

| Dimension | Assess |
|---|---|
| Importance | Whether resolving the question changes scientific understanding, a method choice, a decision, or an affected stakeholder outcome. |
| Novelty | The contribution delta from the closest direct and partial prior work, based on the [prior-art search](precedent-search.md). |
| Method or proof soundness | Whether the design, assumptions, algorithm, derivation, analysis, controls, and comparisons support the claims. Use genre-appropriate standards. |
| Evidence strength | Whether results, uncertainty, replication, ablations, validation, or synthesis support the scope and magnitude of the claims. |
| Transparency and reproducibility | Whether data, materials, code, versions, protocol, analysis, and limitations are disclosed enough for scrutiny or reproduction, as appropriate and permitted. |
| Clarity | Whether the argument, definitions, evidence, figures, and limitations let the intended reader understand and inspect the contribution. |

Use integer scores and attach a concrete reason and source locator to every material score. Apply these common anchors:

| Score | Anchor |
|---|---|
| 0 | The dimension is absent, contradicted, or wholly unsupported in the material reviewed. |
| 1–2 | A fatal or pervasive problem prevents the paper from meeting the dimension's basic standard. |
| 3–4 | Major weaknesses substantially limit the claim or its usefulness. |
| 5–6 | Adequate or mixed: the contribution is credible within a narrow scope, with consequential weaknesses. |
| 7–8 | Strong: the evidence or reasoning supports a substantial, well-bounded contribution; remaining limitations are identifiable. |
| 9 | Exceptional against current field standards, with independent or unusually strong corroboration where the dimension requires it. |
| 10 | Exceptional fulfillment of the dimension-specific standard, supported by the reviewed evidence. Field-changing impact is relevant to importance/novelty, not a prerequisite for excellent clarity or transparency. |

`not assessed` and `insufficient evidence` are not zeroes. A 0 means evidence supports a serious deficiency; an unknown means the relevant material was not available or checked. Give a confidence label (`low`, `medium`, `high`) and, when helpful, a plausible interval such as `6/10, likely 5–7`. Confidence describes the review basis, not statistical uncertainty.

### Novelty-specific anchors

Novelty is the degree of supported contribution difference, not the number of new words or components. Score the central claim against named closest work:

| Score | Novelty anchor |
|---|---|
| 0–1 | A direct prior work already states and establishes essentially the same contribution. |
| 2 | The difference is mostly a label, implementation detail, routine combination, metric, or setting with no shown change in inference or decision. |
| 3–4 | A recognizable incremental extension or adaptation; the difference is specific but its scientific consequence is limited or not established. |
| 5–6 | A distinct, useful contribution with a bounded new test, context, combination, or result; its importance or non-obviousness remains moderate. |
| 7–8 | A substantial, non-obvious contribution in mechanism, theory, method, evidence, or boundary, supported by a strong prior-art search and evidence that the distinction matters. |
| 9 | A major advance that changes important explanations, methods, or decisions, with strong expert and field-level corroboration. |
| 10 | Rare field-changing novelty. Reserve for exceptional retrospective cases, not proposal-stage prediction. |

For a proposal, novelty is always provisional until a documented search and domain review. If search coverage is weak, the score should be low-confidence or `not assessed`; do not compensate with model intuition. If a method recombines existing techniques, score the combination only for its demonstrated new consequence, and separately disclose the components' lineage. A new name does not add novelty points.

### Adapt the profile to genre

Keep the dimensions visible even when the weights change. State the article archetype and choose weights before scoring. Possible starting weights for an overall comparison are:

| Archetype | Importance | Novelty | Method/proof | Evidence/synthesis | Transparency | Clarity |
|---|---:|---:|---:|---:|---:|---:|
| Empirical paper | 15% | 20% | 20% | 20% | 15% | 10% |
| Theory or mathematical paper | 15% | 20% | 25% | 20% | 10% | 10% |
| System or engineering paper | 15% | 15% | 25% | 20% | 15% | 10% |
| Review or synthesis | 15% | 15% | 20% | 25% | 15% | 10% |

These are declared working defaults, not universal standards. Adapt them with a short rationale for another genre or venue, then apply the same weights to every paper in the set. If a dimension cannot be assessed, mark the overall score `not comparable` instead of silently redistributing its weight.

If the user requests one overall score, compute the disclosed weighted mean and round once to the nearest integer. Also show the full dimension profile, the closest-precedent basis for novelty, and fatal concerns. Do not let a high clarity or importance score average away a fatal validity, ethics, authorship, data-integrity, or fabrication concern. Report critical gates separately; do not make accusations without evidence.

For a proposal-stage idea, do not apply completed-paper weights. Score a profile such as `evidence/coverage`, `novelty`, `importance`, `answerability`, `feasibility`, and `falsifiability`; label `methods execution` and `results` not yet assessed. If one overall idea score is requested, disclose the exact weights and do not call it paper quality.

## Compare novelty across papers without false precision

Use the same date boundary and prior-art protocol for each paper. First construct a closest-work matrix that compares problem, insight, method/mechanism, assumptions, data/measurement, evaluation, and consequence. Then give a per-paper novelty score with:

- exact nearest precedents and source locators;
- the component or claim that overlaps;
- the material difference, if any, and what changes because of it;
- search sources, date, query coverage, and full-text access;
- whether scores describe novelty at publication or present-day overlap; and
- confidence and unsearched boundaries.

Do not average novelty scores over several unrelated claims. Do not derive novelty from embedding similarity, keyword overlap, citation counts, a topic's sparsity, search-result rank, an LLM judge, or a count of queries. A single exact precedent can defeat one novelty claim; many nonmatches cannot prove field-wide originality.

## Venue fit is a separate score

Recommend venues only after the manuscript's contribution type, evidence maturity, audience, constraints, and requested publishing timeframe are known. For every specific recommendation, browse current official venue pages and the current call for papers; record the access date. Use recent accepted papers as context for contribution type and evidence bar, not as a guarantee of acceptance.

Score fit on five axes, 0–2 each:

| Axis | 0 | 1 | 2 |
|---|---|---|---|
| Scope and audience | Out of scope or no evidence of audience fit | Related topic, uncertain readership | Current official scope clearly names the topic and intended audience |
| Contribution and track | Contribution type is not accepted | Possible fit, track unclear | Current call explicitly accepts this article/contribution type |
| Evidence maturity | Central claims miss an explicit bar or required evidence | Partial match with a named weakness | Evidence and study type match the stated bar and recent comparable work |
| Format and eligibility | Violates a hard rule or eligibility condition | A rule remains uncertain | Current format, length, eligibility, and policy requirements are met |
| User constraints | Conflicts with a stated hard constraint | Constraint or cost remains unresolved | Fits the stated timing, access, cost, language, and practical constraints |

Only compute `/10` when all axes are checked. Use `unverified` where an official source was unavailable; do not silently turn missing information into a zero or a perfect score. A 2 means documented fit, not likely acceptance. Report desk-reject risks and the best evidence that would strengthen fit. Do not use impact factor or venue prestige as a substitute for scope, evidence, and audience fit.

Give a short list of usually 3–5 options when enough current information exists. For each, include the fit score, article type/track, official scope or CFP links, deadline and fee/open-access facts only if currently verified, key mismatch, and confidence. Keep `paper quality`, `novelty`, `venue fit`, and `acceptance probability` separate. Do not estimate acceptance probability from the fit score alone.

## Submission opportunity dossier and calendar

For a substantial venue request, produce a submission plan as well as fit scores. Research the exact year, edition, track, or special issue. A recurring conference's previous CFP is historical evidence only; never project its dates or prices into the current cycle. Separate confirmed, tentative, expired, rolling, and not-announced opportunities.

For every shortlisted venue, provide:

- Official name, publisher/society, conference edition or journal/issue, track, article type, location or online format, official homepage, CFP and submission portal links, and date checked.
- Scope, audience, explicit topic match, recent comparable accepted papers, contribution-type fit, evidence readiness, the disclosed fit score and confidence, and the strongest mismatch or desk-reject risk. State the manuscript changes needed for that venue.
- Abstract registration, full-paper submission, supplementary material, rebuttal, notification, revision, camera-ready, author registration, and event dates where officially published. Distinguish these deadlines; identify mandatory early registration of an abstract. For journals, identify rolling submission or special-issue closing dates and distinguish publisher-reported turnaround statistics from promises.
- The exact official date/time/timezone and a conversion to the user's timezone when useful. Preserve AoE or another stated convention explicitly. If time or timezone is absent, mark it unknown rather than inventing midnight. Track extensions from official announcements and recheck before submission.
- Page/word limits, what counts toward them, template, anonymization, submission format, supplements, artifact/code/data requirements, ethics or reporting checklists, AI disclosure, preprint policy, and simultaneous-submission restrictions. Check current policies before applying them.
- Charges by category: submission fee, APC or other publication fee, mandatory author registration, page/color/overlength charges, membership requirements, taxes, and optional charges. Record currency, official fee year, fee source, and whether the charge is confirmed or estimated. Include waivers, discounts, institutional agreements, and eligibility when verified. Never infer zero cost from a missing price page.
- For an event, estimate travel, visa, accommodation, and local costs separately from mandatory publishing costs, with explicit assumptions and ranges. An exchange-rate conversion must include its source/date. Do not silently count APC and conference registration as interchangeable or double-count bundled fees.
- Archiving/indexing, proceedings or journal publication route, open-access/license choices, artifact visibility, presentation obligations, and credible publisher/society identity. Verify indexing claims with the relevant authoritative index when this affects the decision.

Use separate compact tables for opportunities, milestones, and costs so the result remains readable. Cite each date, price, or policy near the field it supports. If reliable sources conflict, report the conflict, prefer the current official venue/track announcement, and leave unresolved facts explicitly unverified.

Build a backward schedule from each feasible deadline: remaining evidence/experiments, analysis freeze, claim and prior-art refresh, full draft, internal review, coauthor sign-off, reporting and reference checks, anonymization/formatting, and submission buffer. Set durations from the actual work remaining and user constraints; do not assume experiments can finish in an arbitrary week. Highlight dependencies, the critical path, decision dates, and work that cannot be responsibly compressed. Include the current manuscript readiness and a go/no-go point before submission.

Offer primary and fallback routes with their next available cycles, cost ranges, revision burden, and timeline conflicts. Do not recommend prohibited concurrent submissions. Flag fallback plans whose deadlines precede the primary venue's notification. Submission, registration, payment, contacting organizers, and recurring deadline monitoring require their own user authorization; a recommendation does not execute them.

End with the best-fitting feasible route, the main tradeoff, the next milestone, and facts still requiring confirmation. Do not invent acceptance odds or guaranteed review times. A strong fit may still be impractical because of budget, timing, evidence maturity, or policy constraints.

## Required scorecard output

For paper comparisons, use a compact profile such as:

| Paper | Reading basis | Importance | Novelty | Soundness | Evidence | Transparency | Clarity | Overall* | Confidence |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| [verified short citation] | full text / abstract / metadata | x/10 | x/10 | x/10 | x/10 | x/10 | x/10 | x/10 or not comparable | low / medium / high |

`*` State the archetype, weights, assessment date, and any fatal gate below the table. Follow the table with the evidence behind the novelty and soundness scores, the strongest counterargument, and what missing information could change the ranking. Do not rank papers with materially different reading bases as if the scores were equally grounded.

## Calibrating judgments and handling disagreement

These /10 ratings are declared reviewer judgments, not a validated measurement instrument, GRADE certainty rating, or acceptance model. Before comparing consequential cases, select field- and genre-matched anchor examples, explain why they instantiate the rubric, and fix the rubric before looking at preferred outcomes. If independent reviewers are available, obtain initial dimension-level ratings before sharing a synthesis; preserve original reasons and changed ratings. Resolve disagreement by inspecting the disputed passage, design or precedent, not by voting or averaging confidence.

Separate reporting completeness, risk of bias in a particular result, and certainty across a body of evidence. Failure to report randomization is not proof randomization was not performed; it is an unresolved design fact and a reporting limitation. An elegant paper can still have a biased result. Use recognized domain appraisal tools when appropriate, with their own criteria and outputs, rather than converting this rubric into them.

If a ranking drives a decision, vary plausible disclosed weights and show whether the ordering changes. Overlapping plausible ranges, unequal access, or unresolved decisive claims warrant a tie or no defensible ranking. Report what additional evidence would distinguish them. Never inflate novelty because search was sparse, or penalize replication merely for honestly identifying itself as replication.

## Claim-specific access gate for novelty numbers

Apply the evidence gate separately to each contribution. A verified supplied precedent can justify a low numerical novelty assessment for the exact matched claim without proving exhaustive coverage of every other claim. It cannot justify a number for a separate dataset, population, mechanism, or context whose closest work has not been checked. In that case report `novelty: not assessed` and describe the **demonstrated contribution** separately, for example “the provided text has not established why this context changes inference.” Do not turn absent evidence of consequence into a numerical estimate of literature originality. Calling a score provisional or low-confidence does not bypass this gate.
