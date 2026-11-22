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

For a proposal, novelty is always provisional until a documented search and domain review. If the closest work for a specific claim has not been checked, report that claim’s novelty as `not assessed`; a low-confidence number is not a substitute for missing prior-art evidence. If some closest work has been inspected but broader coverage remains limited, a requested claim-level score may be given with low confidence, the exact search boundary, and the unsearched threats. Do not compensate with model intuition. If a method recombines existing techniques, score the combination only for its demonstrated new consequence, and separately disclose the components' lineage. A new name does not add novelty points.

### Adapt the profile to genre

Keep the dimensions visible even when the weights change. State the article archetype and choose weights before scoring. Possible starting weights for an overall comparison are:

| Archetype | Importance | Novelty | Method/proof | Evidence/synthesis | Transparency | Clarity |
|---|---:|---:|---:|---:|---:|---:|
| Empirical paper | 15% | 20% | 20% | 20% | 15% | 10% |
| Theory or mathematical paper | 15% | 20% | 25% | 20% | 10% | 10% |
| System or engineering paper | 15% | 15% | 25% | 20% | 15% | 10% |
| Review or synthesis | 15% | 15% | 20% | 25% | 15% | 10% |

These are declared working defaults, not universal standards. Adapt them with a short rationale for another genre or venue, then apply the same weights to every paper in the set. If a dimension cannot be assessed, mark the overall score `not comparable` instead of silently redistributing its weight.

If the user requests one overall score, compute the disclosed weighted mean and round once to the nearest integer. For repeated comparisons, use the optional [score arithmetic helper](../scripts/score_math.py) with declared six-dimension integer weights and ratings; it refuses missing dimensions and invalid weight totals. Its output verifies arithmetic only, never scientific validity. Also show the full dimension profile, the closest-precedent basis for novelty, and fatal concerns. Do not let a high clarity or importance score average away a fatal validity, ethics, authorship, data-integrity, or fabrication concern. Report critical gates separately; do not make accusations without evidence.

For a proposal-stage idea, do not apply completed-paper weights. Score a profile such as `evidence/coverage`, `novelty`, `importance`, `answerability`, `feasibility`, and `falsifiability`; label `methods execution` and `results` not yet assessed. If one overall idea score is requested, disclose the exact weights and do not call it paper quality.

## Mandatory Submission Readiness & Venue Standing Calibration

Never return a bare `/10` score (e.g., `6.35/10` or `6/10`) without translating it into an explicit **Submission Readiness & Venue Standing** verdict. Distinguish **mandatory calibrated submission-readiness guidance** (allowed and required) from **forbidden fabricated `%` acceptance odds** (e.g., *"42% chance of acceptance at NeurIPS"*, which remains strictly banned).

1. **Fatal-Gate Override (`not_ready_fatal_gate`):** Any core defect blocks submission immediately—even if `weighted_unrounded >= 6.5` (clarity or importance cannot average away a fatal flaw):
   - `soundness <= 4` (method or proof defect),
   - `evidence <= 4` (insufficient/invalid validation),
   - `novelty <= 2` (subsumed by prior art or routine tweak),
   - `transparency <= 3` (non-reproducible or missing critical disclosures),
   - any scored dimension `<= 2`, or
   - unrun `idea` stage results (`methods execution` / `results` not yet assessed).
2. **Calibrated Weighted `/10` Bands (only when fatal gates pass):**

| Condition / Weighted `/10` | Band Token (`submission_readiness.band`) | Standing vs All Submissions & Accepted Panel | Realistic Venue-Tier Posture & Action |
|---|---|---|---|
| Fatal gate triggered (or unrun `idea`) | `not_ready_fatal_gate` | Blocked by critical flaw regardless of weighted mean | **Do not submit**; fix `fatal_dimensions` first |
| `< 5.0` | `not_ready_major_rework` | Below all-submissions average (`~4.8–5.5`) and accepted bar | **Not ready**; major redesign or new empirical evidence required |
| `5.0 – 5.99` | `workshop_or_preliminary_only` | Near all-submissions average (`~4.8–5.5`); well below archival main-track bar | **Workshop / early feedback only**; not ready for archival main tracks |
| `6.0 – 6.79` (e.g., `6.35`) | `borderline_top_tier_competitive_findings_tier_a` | Above *all-submissions* average (`~4.8–5.5`), but slightly below / lower-edge vs Top-Tier Main Track *accepted-paper* median (`~6.8–7.6` at `NeurIPS`/`ICML`/`ICLR`/`CVPR`/`ACL`) | **High reviewer-variance risk at Top-Tier Main Track** unless bottleneck dimensions close the gap to `6.80`; **competitive now** for `Findings`, CCF-B / Tier-A conferences, strong workshops, or focused Q1–Q2 journals |
| `6.8 – 7.79` | `competitive_top_tier_main_track` | Solidly inside typical Top-Tier Main Track *accepted-paper* band (`~6.8–7.6`) | **Ready for Top-Tier Main Track** when CFP fit (`fit_score_out_of_10`) and hard constraints hold |
| `>= 7.8` | `strong_top_tier_contender` | Upper-tier *accepted-paper* band | **Strong Top-Tier Main Track contender**; verify formatting, anonymization, and CFP compliance |

3. **Required Submission Readiness Output Block:** Append this block beneath every `/10` scorecard or venue evaluation (machine-checked via `../scripts/score_math.py`, `../scripts/compare_scorecards.py --compact`, and `../scripts/compare_venue_novelty.py --compact`):
   - **Fatal-gate status:** `PASS` vs `not_ready_fatal_gate` (list `fatal_dimensions`).
   - **Standing vs all submissions & accepted panel:** Anchor the weighted `/10` score against both all-submissions norms (`~4.8–5.5`) and the target venue's same-track accepted panel (`standing_vs_accepted_panel`: `above_panel_median`, `at_or_overlapping_panel_median`, or `below_panel_median`, plus `delta_to_competitive_top_tier` relative to `6.80`).
   - **Realistic venue-tier posture now:** Explicitly separate `ready_for_top_tier_main_track` vs `ready_for_findings_or_tier_a` vs workshop/rework, conditioned on verified CFP fit and hard constraints (`deadline`, `budget`, `eligibility`).
   - **Highest-leverage pre-submission fixes:** List `bottleneck_dimensions` (lowest-scoring / fatal axes) and concrete missing experiments, ablations, or disclosures needed before submission (never invented `%` acceptance odds).

## Compare novelty across papers without false precision

Use the same date boundary and prior-art protocol for each paper. First construct a closest-work matrix that compares problem, insight, method/mechanism, assumptions, data/measurement, evaluation, and consequence. Then give a per-paper novelty score only for claims that pass the claim-specific evidence gate below; otherwise mark novelty `not assessed`. A permissible score must include:

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
| User constraints | Verified conflict with a stated hard constraint | A nonbinding preference is only partly met; an unresolved hard constraint is `unverified`, outside the numerical score | Verified fit to the stated timing, access, cost, language, and practical constraints |

Only compute `/10` when all axes have verifiable evidence. An unresolved hard constraint (such as a strict budget, eligibility rule, or deadline) blocks a complete fit score even if the other axes are known; report the verified axes and a conditional option instead. Use `unverified` where an official source was unavailable; do not silently turn missing information into a zero, a one, or a perfect score. A 2 means documented fit, not likely acceptance. Report desk-reject risks and the best evidence that would strengthen fit. Do not use impact factor or venue prestige as a substitute for scope, evidence, and audience fit.

Give a short list of usually 3–5 options when enough current information exists. For each, include the fit score, article type/track, official scope or CFP links, deadline and fee/open-access facts only if currently verified, key mismatch, and confidence. Keep `paper quality`, `novelty`, `venue fit`, and `acceptance probability` separate. Do not estimate acceptance probability from the fit score alone.

### Compare the paper's novelty with a venue's recent accepted work

Do not assign a venue an intrinsic “novelty score” or infer an acceptance cutoff. To answer whether the user's *specific contribution* resembles what a track has recently published, assemble a transparent panel of at least five recent accepted papers from that exact track and contribution type. Verify each paper's accepted status from official proceedings or the venue, read its full text, and score its central contribution against the closest prior work available before that paper's publication. Use the same [novelty anchors](#novelty-specific-anchors) and record the assessment date, passages, contribution delta, uncertainty interval and search boundary. Score the user's claim separately against current prior art; do not score an unrun proposal as though it had results. Historical and current novelty assessments use different time boundaries, so compare contribution scale cautiously.

Record the panel search manifest, screened count, inclusion/exclusion rules and all close exclusions. A convenience sample of highly cited, oral, award-winning or easily accessible papers is biased. A small same-track panel is descriptive, not the venue's full accepted-paper distribution or a prediction of acceptance. Paper quality, fit, evidence maturity, reviewer preferences and submission competition can dominate the decision even when novelty scores look similar.

For a structured comparison, adapt [the fictional profile](venue-novelty-profile.fixture.json) and run `python scripts/compare_venue_novelty.py profile.json [--sources-dir /path/to/sources] [--quality-refs-dir /path/to/refs] [--target-overall 6.35] [--out report.json] [--compact]`. The helper requires full-text and closest-work locators for every supplied /10 novelty rating, at least five recent same-track accepted papers for a panel comparison, current CFP metadata, five fit axes and explicit deadline/budget/eligibility states. When `--sources-dir` is provided, it verifies `target` and `accepted_panel[*]` `closest_work_locator` strings (plus `fit_axes[*].locator`, `hard_constraints[*].source_url` snapshots, and any supplied quote fields) against local `.txt`, `.md`, `.json` (including `extract_pdf_blocks.py`, MinerU Content List V2, and `capture_venue_sources.py` bundles), and `.pdf` files, blocking (`invalid`) missing files, symlinks outside `--sources-dir`, out-of-bounds page/line anchors, bare page numbers without text, unmatched quotes, or stale/JS-rendered/bot-blocked venue snapshots (`locator_verification` summarizes checked/verified/failed counts). When `--sources-dir` is omitted, checks remain structural-only. It also attaches an advisory `venue_quality_context` lookup (`S`/`A`/`B`/`C`/`Unknown` from `paper-quality-filter` rules) that never adds points to `fit_score_out_of_10` or `novelty_comparison`. Pass `--out` to persist the full JSON artifact on disk and `--compact` to print only a bounded summary (`fit_score_out_of_10`, `novelty_comparison` summary, `venue_contribution_bar`, `venue_quality_context`, `submission_readiness`, `locator_verification`, truncated error/warning counts, and `artifact_path`) to stdout for token-frugal runs. It reports the panel median/range and counts whose uncertainty intervals are strictly above, below or overlapping the target; it withholds the fit score for stale CFP metadata or unresolved hard constraints. A median is descriptive, not a “required novelty score.” Its arithmetic and field checks do not verify any rating, fee, or scientific result. Use [venue source capture](#submission-opportunity-dossier-and-calendar) and original-paper reading to audit the supplied inputs.

### Two-Axis Panel Calibration & Hard Tier-Mismatch Rejection

Separate two orthogonal comparison panels whenever judging a paper against a venue:

1. **Axis 1 — Same-Topic Closest Related Work (`compare_scorecards.py --target-id`):** Calibrates *Novelty* and contribution delta against `>= 3` direct topical competitors read in `full_text`.
2. **Axis 2 — Cross-Topic Same-Venue Accepted Panel (`venue_contribution_bar` in `compare_venue_novelty.py`):** Even when accepted papers at the target venue/track cover completely different topics (`topic_relation`: `"same_topic"`, `"adjacent_topic"`, or `"different_topic"`), supply optional `overall_score` or 6-dimension `ratings` on `accepted_panel` items (plus `--target-overall` or `target_scorecard`) to calibrate how substantial a typical accepted contribution is (`panel_median_overall`, `target_vs_venue_overall_delta`, `cross_topic_count`). Never fabricate `panel_median_overall` when panel entries lack overall scores/ratings.

**Canonical Venue-Tier Contribution Floors (Single Source of Truth in `../scripts/score_math.py`):**
- `top_tier_flagship` (`S` / `Top-Tier Flagship` / `CCF-A` / flagship Q1): competitive `>= 6.80`, min viable stretch `>= 6.00`, `soundness >= 6`, `evidence >= 6`, `novelty >= 5`, no dimension `<= 4`.
- `q1_or_tier_a` (`Q1 Journal` / `Tier-A` / `CCF-B` / `Findings`): min viable `>= 6.00`, `soundness >= 6`, `evidence >= 6`, `novelty >= 5`, no dimension `<= 4`.
- `q2_q3_or_tier_b` (`Q2-Q3 Journal` / `Tier-B` / `CCF-C`): min viable `>= 5.50`, `soundness >= 5`, `evidence >= 5`, no dimension `<= 3`.
- `workshop_or_preliminary` (`Workshop` / `Preliminary`): viable down to `5.00–5.99` when no fatal integrity/soundness failure triggers.

**Hard Rejection (`rejected_below_venue_tier`, NEVER `"stretch_high_risk"`):** Reject submission (`ready_to_submit = False`, blunt `upgrade_gaps_to_target_tier`) whenever (a) `weighted_unrounded < venue_min_viable_floor` (e.g., workshop-scale `< 6.00` targeting `q1_or_tier_a` or `top_tier_flagship`), (b) critical tier dimension shortage (`soundness <= 5`, `evidence <= 5`, `novelty <= 4`, or any dim `<= 4` targeting `q1_or_tier_a`/`top_tier_flagship`), (c) `target_vs_venue_overall_delta <= -1.0`, or (d) `target_novelty` trails `panel_median_novelty` by `>= 2` points at `top_tier_flagship`/`q1_or_tier_a`.

### Strict Multi-Venue Portfolio Evaluation (>= 3–5 Candidate Venues)

Whenever evaluating venue options—especially when the primary target is borderline, mismatched, or rejected (`rejected_below_venue_tier`)—score a portfolio of `>= 3–5` concrete venues spanning **Primary Target**, **Realistic Peer / Findings / Tier-A Alternatives**, and **Grounded Fallback**. Never suggest unverified venue names casually.

Run `python scripts/compare_venue_novelty.py portfolio.json --portfolio [--require-panels] [--min-venues 3] [--target-overall 6.35] [--sources-dir /path/to/sources] [--quality-refs-dir /path/to/refs] [--out portfolio_report.json] [--compact]` with `candidate_venues: [...]`. Every candidate must clear full 5-axis fit, 3 hard constraints, HTTPS CFP freshness, `--sources-dir` snapshot/redirect/JS checks, and `>= 5` same-track `accepted_panel` verification when supplied or required (`--require-panels`). Automatically emits `recommended_matched_tier` (highest surviving verified tier-matched venue + `upgrade_gaps_to_target_tier` for rejected targets) or `no_viable_venue_in_portfolio` (advising a verified `Workshop` or `Q2-Q3 / CCF-C` search).

| Status | Portfolio Classification & Trigger |
|---|---|
| `hold_for_rework` | Target triggers `fatal_gate_triggered` (`soundness <= 4`, `evidence <= 4`, `novelty <= 2`, `transparency <= 3`, any dim `<= 2`, or unrun `idea`) — blocks all archival venues |
| `disqualified` | Duplicate venue, failed hard constraint (`deadline`, `budget`, `eligibility`), or `fit_score_out_of_10 <= 4` — never recommended |
| `withheld_unverified` | Stale CFP, `same_host_path_redirect_year_mismatch`, `js_rendered_suspected`, locator error, `unverified` constraint, or missing panel under `--require-panels` |
| `rejected_below_venue_tier` | Fails target venue's contribution tier floor or trails cross-topic panel bar by `>= 1.0` — hard rejected (never labeled `stretch_high_risk`) |
| `conflicted_fallback` | Fallback deadline precedes primary notification while simultaneous submission is prohibited (`timeline_conflicts`) |
| `recommended_now` | All constraints `met`, `fit_score_out_of_10 >= 7`, clears tier floor, and meets accepted-panel standing |
| `stretch_high_risk` | Constraints & fit `met` and clears min viable tier floor, yet `< 6.80` for `top_tier_flagship`, `below_panel_median` (`< 2` gap), or moderate fit (`5` or primary `6`) |
| `viable_fallback` | Verified fit & constraints `met`, clears tier floor, and clean post-notification fallback timeline |

#### Collecting a same-track accepted-paper panel (`venue_panel_collector.py`)

To avoid convenience sampling from ad-hoc search hits or oral/spotlight papers, build a reproducible panel scaffold from official proceedings indexes (`pmlr`, `acl`, `dblp`) with:

```bash
python scripts/venue_panel_collector.py --source <pmlr|acl|dblp> --venue-id <id> --limit 5 --out panel.json [--track <track>] [--year <YYYY>] [--offline-html <path>] [--timeout 20] [--compact]
```

Examples: `--source pmlr --venue-id v235`, `--source acl --venue-id acl-2025 --track Main`, `--source dblp --venue-id conf/icml/icml2024`. The collector enforces `--limit >= 5` and same-track consistency (`item['track'] == venue['track']`), skips proceedings frontmatter rows, records explicit fetch provenance (`source_url`, `final_url`, `sha256`, `http_status`), and emits `compare_venue_novelty.py`-compatible `venue`, `panel_selection`, and `accepted_panel` fields; pass `--compact` alongside `--out` to keep stdout bounded to 5 sample items plus `artifact_path`. Every collected item is honestly marked `reading_basis: "metadata_only"` with `null` reviewer ratings so an un-read panel can never pass `compare_venue_novelty.py` silently; read the full texts and supply genuine locators and `/10` intervals before running novelty comparison. The collector fails explicitly (never writing a partial `--out` file) on HTTP errors, Anubis PoW or Cloudflare bot challenges (`bot_challenge_anubis`, `bot_challenge_cloudflare`), JS-rendered shells (`js_rendered_shell`), or fewer than `max(5, limit)` matching same-track papers (`insufficient_panel_papers`); for bot-challenged hosts such as `dblp.org`, save the official proceedings page locally in a browser and pass `--offline-html`.

## Submission opportunity dossier and calendar

For a candidate list, search the actual contribution and the closest related papers, then inspect where the most similar *eligible* papers appeared. The optional `scripts/venue_leads.py "specific contribution" --page-size 50 --pages 2 [--quality-refs-dir /path/to/refs] [--out leads.json] [--compact]` groups a bounded OpenAlex result by primary publication source and retains work IDs, sample years, and advisory `venue_quality` / `venue_quality_coverage` metadata (use `--out` + `--compact` to save full `related_work_ids` on disk and emit at most 10 compact lead rows to stdout). Treat it as a lead generator only: OpenAlex search ranking, missing primary locations, preprints, and historical publication patterns bias the list. A frequent source may be closed, out of scope for the current track, too costly, or inappropriate for the manuscript. Verify each serious candidate against its own current official CFP or aims and author instructions before assigning fit.

### Venue tier screening limits (`paper-quality-filter`)

`venue_leads.py` and `compare_venue_novelty.py` use deterministic two-stage normalization (`normalize_venue_name` + `compact_venue_name`, plus parenthetical-acronym and proceedings-prefix probes, ported from MIT-licensed `yilaai/paper-quality-filter`) against a curated built-in CCF 7th Edition (March 2026) CS/AI/CV/NLP table (`NeurIPS`, `ICML`, `ICLR`, `CVPR`, `ICCV`, `ECCV`, `ACL`, `EMNLP`, `NAACL`, `AAAI`, `IJCAI`, `KDD`, `TPAMI`, `TACL`, etc.) and optional local `paper-quality-filter` JSON tables supplied via `--quality-refs-dir` (CCF ranks, JCR quartile/IF/CAS zone, EI, and Chinese core tags), assigning reading-priority tiers `S` (`Strongly Recommended`), `A` (`Worth Keeping`), `B`/`C` (`Supplementary`), or `Unknown` (`Insufficient Venue Evidence`). Apply these strict boundaries:

- **`Unknown` (`Insufficient Venue Evidence`) never implies low quality:** Unmatched venues and preprint servers (`arXiv`, `CoRR`, `bioRxiv`, `medRxiv`, `SSRN`, `chemRxiv`, `OpenReview`) always remain `Unknown`.
- **Tier tags never establish venue fit:** An `S` or `A` tier is a reading-priority signal only; it never overrides scope, track match, current CFP eligibility, deadlines, or mandatory fee verification.

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

For a structured dossier, adapt [the fictional JSON example](venue-dossier.schema-example.json) and run [the local calendar and cost checker](../scripts/check_venue_plan.py) (`python scripts/check_venue_plan.py dossier.json [--sources venue-sources.json] [--out plan-report.json] [--compact]`). Supply official links and timezone-aware checked timestamps yourself; the script cannot validate whether they are real/current or actually official. Mark each mandatory fee unknown unless checked, and add travel/visa/lodging/local transport when in-person presentation is required. A positive budget verdict requires a source URL and checked timestamp for each mandatory amount. The checker reports source age and blocks a positive affordability verdict for fee facts older than its declared `max_source_age_days` threshold (30 by default), but freshness alone is not proof. A fresh known lower bound above budget disproves affordability before remaining costs are resolved. Its optional `work_plan` builds a serial backward schedule from the declared task durations and buffer; review dependencies, parallel work and scientific readiness manually. It will not return a positive budget verdict with missing required categories, unknown mandatory amounts, or a currency mismatch.

To preserve the actual source reading, add `evidence_claims` to the dossier: each item needs `field` (for example `milestones.full_paper` or `fees.author_registration`), `source_url`, and a short exact `quote` from the relevant official page. Then run `python scripts/capture_venue_sources.py [dossier.json] [--out venue-sources.json] [--artifacts-dir artifacts/] [--dblp-lookup QUERY] [--dblp-year YYYY] [--compact]` (or redirect `> venue-sources.json`) and `python scripts/check_venue_sources.py dossier.json venue-sources.json [--out sources-report.json] [--compact]`. The capture helper fetches each distinct HTTPS CFP, fee, and additional evidence URL once, records `final_url`, `redirect_chain`, timestamp, response hash, content type and extracted HTML/plain/PDF text, and leaves failed URLs visible. It also flags `same_host_path_redirect_year_mismatch` whenever a redirect on the same host alters the URL path year or edition segment (for example `/aaai-27/` redirecting to `/aaai-25/` or `/2027/` redirecting to `/2025/`), and flags `js_rendered_suspected` when an HTML response looks like a SPA shell, `<noscript>`-gated page, or dynamic JS pricing/CFP widget without static tabular content. Its PDF text extraction requires PyMuPDF and may miss scanned content, tables or layout. The quote checker distinguishes absent snapshots, failed extraction, stale snapshots, cross-host redirects, same-host stale-year redirects, `unverified_dynamic_page` snapshots, and quotes not present; it treats `same_host_path_redirect_year_mismatch` and `js_rendered_suspected` / `unverified_dynamic_page` as blocking verification failures (never `quote_found` or `all_supplied_critical_quotes_found`), so an empty JS-rendered fee table or a prior-year redirected CFP can never certify current deadlines or zero cost. It checks word boundaries so a quote saying `USD 50` does not match `USD 500`. These are source-provenance checks, not semantic fact verification: inspect the original page or PDF (and perform manual browser/PDF inspection for any `unverified_dynamic_page`) and confirm the quote refers to the correct edition, track, deadline convention, fee category and author situation. A matching quote on a stale or unofficial page must not be promoted to a current recommendation. The capture JSON contains page text; use only authorized public pages and keep private URLs or credentials out of a shared dossier.

Use separate compact tables for opportunities, milestones, and costs so the result remains readable. Cite each date, price, or policy near the field it supports. If reliable sources conflict, report the conflict, prefer the current official venue/track announcement, and leave unresolved facts explicitly unverified.

Build a backward schedule from each feasible deadline: remaining evidence/experiments, analysis freeze, claim and prior-art refresh, full draft, internal review, coauthor sign-off, reporting and reference checks, anonymization/formatting, and submission buffer. Set durations from the actual work remaining and user constraints; do not assume experiments can finish in an arbitrary week. Highlight dependencies, the critical path, decision dates, and work that cannot be responsibly compressed. Include the current manuscript readiness and a go/no-go point before submission.

Offer primary and fallback routes with their next available cycles, cost ranges, revision burden, and timeline conflicts. Do not recommend prohibited concurrent submissions. Flag fallback plans whose deadlines precede the primary venue's notification. Submission, registration, payment, contacting organizers, and recurring deadline monitoring require their own user authorization; a recommendation does not execute them.

End with the best-fitting feasible route, the main tradeoff, the next milestone, and facts still requiring confirmation. Do not invent acceptance odds or guaranteed review times. A strong fit may still be impractical because of budget, timing, evidence maturity, or policy constraints.

## Required scorecard output

For paper comparisons, use a compact profile such as:

| Paper | Reading basis | Importance | Novelty | Soundness | Evidence | Transparency | Clarity | Overall* | Confidence |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| [verified short citation] | full text / abstract / metadata | x/10 | x/10 | x/10 | x/10 | x/10 | x/10 | x/10 or not comparable | low / medium / high |

`*` State the archetype, weights, assessment date, any fatal gate, and the mandatory **Submission Readiness & Venue Standing** block below the table (never raw `/10` alone, and never invented `%` acceptance odds). Follow the table with the evidence behind the novelty and soundness scores, the strongest counterargument, and what missing information could change the ranking. Do not rank papers with materially different reading bases as if the scores were equally grounded.

## Calibrating judgments and handling disagreement

These /10 ratings are declared reviewer judgments, not a validated measurement instrument, GRADE certainty rating, or acceptance model. Before comparing consequential cases, select field- and genre-matched anchor examples, explain why they instantiate the rubric, and fix the rubric before looking at preferred outcomes. If independent reviewers are available, obtain initial dimension-level ratings before sharing a synthesis; preserve original reasons and changed ratings. Resolve disagreement by inspecting the disputed passage, design or precedent, not by voting or averaging confidence.

Separate reporting completeness, risk of bias in a particular result, and certainty across a body of evidence. Failure to report randomization is not proof randomization was not performed; it is an unresolved design fact and a reporting limitation. An elegant paper can still have a biased result. Use recognized domain appraisal tools when appropriate, with their own criteria and outputs, rather than converting this rubric into them.

If a ranking drives a decision, vary plausible disclosed weights and show whether the ordering changes. Overlapping plausible ranges, unequal access, or unresolved decisive claims warrant a tie or no defensible ranking. Report what additional evidence would distinguish them. Never inflate novelty because search was sparse, or penalize replication merely for honestly identifying itself as replication.

For a structured comparison, adapt [the fictional scorecard example](scorecards.schema-example.json) and run `python scripts/compare_scorecards.py scorecards.json [--target-id target] [--strict-related-panel] [--min-related 3] [--sources-dir /path/to/sources] [--out report.json] [--compact]` after full texts and each closest novelty threat have been checked. The checker requires a locator for every scored dimension and compares raw weighted results across the supplied weight scenarios. When `--sources-dir` is provided, it verifies every locator against local `.txt`, `.md`, `.json` (MinerU Content List V2 / `extract_pdf_blocks.py` / `capture_venue_sources.py`), or `.pdf` files (blocking missing files, path traversal, symlinks outside `--sources-dir`, out-of-bounds page/line anchors, bare page numbers without text, or unmatched quotes by returning `status: "not_comparable"` with explicit `locator_verification` counts and exiting `1`). When `--sources-dir` is omitted, checks remain structural-only. Pass `--out` to persist the full JSON report and `--compact` for a bounded `<4096B` summary with `artifact_path`. It reports when the top-ranked paper changes across those scenarios; it cannot decide whether locators support the ratings or whether the chosen scenarios span all reasonable priorities. Record independent reviewer disagreement and the exact contested passage alongside the numeric output. A stable ordering under arbitrary weights is weak evidence if the underlying ratings or closest-work search are wrong.

### Mandatory Closest-Related-Work Anchoring (>= 3 Full-Text Papers)

Never score a target paper's `/10` Novelty or Overall in isolation. Score the target alongside at least `3` closest related prior-art papers (`closest_work`) read in `full_text` on the exact same 6-dimension `/10` rubric with verified local locators:

1. **Side-by-side matrix & deltas:** Compare `Target` vs `>= 3` closest works across all 6 dimensions and weighted `/10`, reporting `contribution_delta`, `best_related_overall`, `target_delta_vs_best_related_overall`, and `dimension_deltas_vs_max_related`.
2. **Executable strict gate:** Pass `--target-id <target_id> --strict-related-panel --min-related 3 --sources-dir /path/to/sources`.
   - Fails closed (`status: "not_comparable"`, exit `1`) with `unscored_closest_work:<id>` if any ID in `target['closest_work']` lacks a qualified full-text, locator-verified 6-dimension profile in `profiles[]`, `insufficient_scored_related_papers:<count><min>` if `< 3` distinct qualified related profiles exist, or `closest_work_self_reference:<id>` on self-citation.
   - Emits `novelty_inflation_warnings` when `target` claims `novelty >= 7` with blank `contribution_delta` or while `soundness`/`evidence` trails the strongest related baseline without explanation.
   - When `--target-id` is omitted, backward compatibility holds while surfacing `unscored_closest_work_ids` per profile.

## Claim-specific access gate for novelty numbers

Apply the evidence gate separately to each contribution. A verified supplied precedent can justify a low numerical novelty assessment for the exact matched claim without proving exhaustive coverage of every other claim. It cannot justify a number for a separate dataset, population, mechanism, or context whose closest work has not been checked. In that case report `novelty: not assessed` and describe the **demonstrated contribution** separately, for example “the provided text has not established why this context changes inference.” Do not turn absent evidence of consequence into a numerical estimate of literature originality. Calling a score provisional or low-confidence does not bypass this gate.

### Evidence checklist before a score is published

For each dimension, write the source locator, claim or design feature it bears on, objection, and reason for the integer anchor. For novelty, include the exact closest-work claim and your proposed contribution delta. For soundness, trace the main inference from unit and design through measurement, controls, analysis and uncertainty. For evidence strength, distinguish a reported result from an independently reproduced result. For transparency, distinguish unavailable material from a documented refusal or a genuinely absent protocol. For clarity, score the actual prose/figures against the intended audience; clarity does not repair validity. A fatal defect is a separate gate even if weighted arithmetic yields a high number.

## Scoring Engine v2: Venue-Type Profiles & Native Scales

Use `../scripts/score_math.py [--venue-type ...] [--venue-profile ...] [--subfield-preset ...] [--what-if]` (and forward `--venue-type` / `--venue-profile` / `--subfield-preset` to `../scripts/compare_scorecards.py` and `../scripts/compare_venue_novelty.py`) to select a venue-appropriate weighting profile and deterministic native-scale calibration—**with zero invented `%` acceptance odds**:

| Venue Type (`--venue-type`) | Default Weights (`Imp/Nov/Snd/Evd/Trn/Clr`) | Profile Emphasis & Required Checks |
|---|---|---|
| `conference_top_tier` | `15/25/20/20/10/10` | Heavy novelty/insight and matched-SOTA depth (`competitive_overall >= 6.80`) |
| `journal_q1` | `15/15/25/25/10/10` | Heavy soundness, comprehensive ablations, and full reproducibility (`comprehensive_ablations`, `reproducibility_details`) |
| `dataset_benchmark` | `15/15/20/20/20/10` | Heavy transparency/data quality, annotation protocol, and `T1–T2` ethics/license verification (`data_quality_audit`, `annotation_protocol`, `ethics_and_license_t1_t2`) |
| `survey_review` | `15/15/20/25/15/10` | Systematic coverage protocol, taxonomy, and synthesis breadth (`systematic_coverage_protocol`) |
| `workshop_preliminary` | `15/20/20/15/15/15` | Early mechanism/diagnostic viability (`min_viable_overall >= 5.00`) |

For `dataset_benchmark`, missing or failed mandatory `T1–T2` checks (`data_quality_audit`, `annotation_protocol`, `ethics_and_license_t1_t2`) fail closed (`not_ready_fatal_gate`) until explicitly verified.

### Deterministic Native Scale Translations (`native_venue_scales`)

`../scripts/score_math.py` deterministically translates `/10` weighted scores and fatal gates into venue-native review scales (capped below acceptance bar whenever `fatal_gate_triggered` is `True`):

- **ARR (`1–5`, 0.5 steps):** `>= 3.5` strong, `3.0` borderline, `<= 2.5` below bar (capped `<= 2.5` on fatal gate).
- **NeurIPS (`1–6`):** `4` = borderline accept, `5` = accept, `6` = strong accept (capped `<= 3` on fatal gate).
- **ICLR (`1–10`) + Confidence (`1–5`):** `6` = weak accept, `8` = strong accept (capped `<= 3` on fatal gate); `confidence` is populated strictly from `reviewer_panel` or declared integer `reviewer_confidence` (`null` otherwise, never fabricated).
- **Journal Decisions:** `Accept`, `Minor Revision`, `Major Revision`, `Reject`.

## Multi-Reviewer Simulation & Area Chair Synthesis

Attach an optional `reviewer_panel` (`>= 3` role-based reviewers such as `method_theory`, `experiments_baselines`, `novelty_positioning`, each with 6-dimension integer `ratings` and `confidence` in `1..5`) to compute `confidence_weighted_mean`, `unweighted_mean`, `spread`, `std_dev`, `variance_risk` (`low`, `moderate`, `high_disagreement`), `assassin_reviewer_flag`, `champion_flag`, `worst_case_reviewer_floor`, and Area Chair `meta_review_verdict`.

| Status (`meta_review_verdict`) | Trigger & AC Rule |
|---|---|
| `reject_fatal_defect` | Triggered whenever `fatal_gate_triggered` or a confident (`>= 3`) reviewer exposes a verified fatal defect (`never_averaged_away` by champion scores) |
| `reject` | `confidence_weighted_mean < 5.00` |
| `reject_workshop_level` | `confidence_weighted_mean` in `5.00–5.99` |
| `borderline_high_variance_risk` | `confidence_weighted_mean` in `6.00–6.79` with `high_disagreement` or `assassin_reviewer_flag` |
| `borderline_discussion_needed` | `confidence_weighted_mean` in `6.00–6.79` without high disagreement/assassin flag |
| `accept_pending_rebuttal` | `confidence_weighted_mean >= 6.80` with `high_disagreement` or `assassin_reviewer_flag` |
| `accept` | `confidence_weighted_mean >= 6.80`, no fatal defects, and low/moderate variance |

## Dedicated Idea Scoring, Goal-Conditioned Pareto Ranking & Gap Linkage

Score pre-execution research ideas separately from completed manuscripts using `--mode idea` (`IDEA_DIMENSIONS`: `evidence_coverage`, `novelty`, `importance`, `answerability`, `feasibility`, `falsifiability`). Unrun ideas ALWAYS enforce `ready_for_top_tier_main_track: False`, `ready_for_findings_or_tier_a: False`, and `archival_submission_blocked: True` (while legacy `status="idea"` with paper 6-dimensions still returns `not_ready_fatal_gate` with `unrun_idea_results`).

| Status (`idea_viability_band`) | Idea Triage Criteria |
|---|---|
| `pursue_high_priority` | Weighted idea score `>= 7.20` and all 6 idea dimensions `>= 6` |
| `refine_and_de_risk` | Weighted idea score in `6.00–7.19` or at least one dimension `<= 5` above fatal floor |
| `pivot_or_narrow` | Weighted idea score in `4.80–5.99` or `feasibility <= 4` or `falsifiability <= 4` |
| `kill_early` | Any idea fatal threshold hit (`<= 2` on `evidence_coverage`/`novelty`/`importance`; `<= 3` on `answerability`/`feasibility`/`falsifiability`), `< 4.80`, or `gap_tier_ceiling == "low_impact_dead_end"` |

Run multi-idea ranking and cross-artifact linkage via:

```bash
python3 ../scripts/compare_scorecards.py ideas.json --mode idea --goal safe_fast_publish --gap-record gap.json --question-card qc.json --idea-seed-bundle bundle.json --require-idea-portfolio --require-pre-mortem --sources-dir sources/ --out idea_report.json --compact
```

- **Direct `research_scientist_idea_seed_bundle_v1` ingestion:** Pass a `gap_pipeline.py` bundle (via `ideas.json` or `--idea-seed-bundle` / `--seed-bundle`); unrated scaffolds (`ratings: null` or `{}` locators) fail closed (`not_comparable`) rather than fabricating ratings.
- **Goal-Conditioned Pareto Frontier (`--goal`):** Computes non-dominated frontier sets for `safe_fast_publish`, `high_risk_q1_top_tier`, and `low_compute_constrained` (under `low_compute_constrained`, report explicit `required_gpu_hours`; omitted compute never dominates finite reported GPU hours).
- **Portfolio & Pre-Mortem Checks:** `--require-idea-portfolio` enforces `3–4` non-redundant ideas per `gap_id` across `>= 3` canonical angles (`minimal_fix`, `high_novelty_mechanism`, `benchmark_diagnostic_analysis`, `low_gpu_fallback`); `--require-pre-mortem` enforces `top_failure_modes >= 3`, `killer_experiment` (`0 < duration_days <= 2` + `kill_threshold`), and `pivot_path`.

## What-If ROI, Revision Diff, Halo Guard & Deep Diagnostics

- **What-If Score-Lift ROI (`--what-if`):** `../scripts/score_math.py` and `../scripts/compare_scorecards.py` compute minimal `+1`/`+2` single-axis upgrades and minimal multi-axis paths to clear `fatal_gate_triggered`, `rejected_below_venue_tier`, `6.00`, `6.80`, and the venue bar, ranked by ROI leverage (`weight / 100` + blocking-gate priority).
- **Revision Diff & Anti-Grade-Inflation Audit:** `../scripts/compare_scorecards.py --revision-diff v1.json v2.json [--sources-dir sources/ --target-id target --out diff.json --compact]` audits per-dimension and weighted deltas, tracks resolved vs remaining `v1` defects, and flags `suspected_grade_inflation` (`grade_inflation_suspected`, exit `1`) if any positive score delta lacks a NEW verified locator or NEW valid 64-hex SHA-256 run receipt (`verified_revision` exits `0`).
- **Halo-Effect Guard (`sanity_warnings`):** Emits non-blocking consistency warnings when `soundness >= 8` and `transparency <= 4`, `evidence >= 8` without CI/seed/ablation support, `novelty >= 8` with thin/unread closest work, or `feasibility >= 8` despite `infeasible_under_user_resources`.
- **Deep Scoring Diagnostics:**
  1. **Side-by-Side Evidence Anchor Table (`evidence_anchor_table`):** Compares target against `2–3` full-text accepted papers (supporting `same_topic`, `adjacent_topic`, `different_topic`) across `benchmarks_count`, `sota_baselines_covered`, `ablation_depth`, `theoretical_rigor`, `effect_size_ci_stability`, and `code_artifact_openness` (missing stays `null` / `unreported`).
  2. **Scientific Merit vs Publishability Packaging (`merit_vs_packaging`):** Splits `scientific_merit_score` (`importance`, `novelty`, `soundness`, `evidence`) from `publishability_packaging_score` (`transparency`, `clarity`).
  3. **Section-by-Section Diagnostic Scoring (`section_diagnostics`):** Optional integer `/10` breakdown across `abstract`, `introduction`, `related_work`, `method`, `experiments`, and `limitations` with `prioritized_edit_order`.
  4. **Worst-Case Floor & Deal-Breaker Sensitivity (`deal_breaker_sensitivity`):** Reports `worst_case_reviewer_floor` plus `-1` deal-breaker triggers and `+1` non-rescuing axes.
- **4 Subfield Depth Presets (`--subfield-preset`):** `nlp_llm`, `cv_multimodal`, `ml_theory`, and `ai_systems` readiness packs surfaced across `../scripts/score_math.py`, `../scripts/compare_scorecards.py`, and `../scripts/compare_venue_novelty.py`.
