# Novelty, Venue Verification & Rebuttal Protocol (AI/CS/CV/NLP)

Load this guide only for `/10` scoring, accepted-panel novelty comparisons, live venue CFP/fee audits, peer-review fairness checks, or rebuttal drafting and verification.

## 1. Full H1–H17 Reviewer Fairness Firewall (`Meet-Reviewer-2` & ACL Rolling Review)

Cross-check every critique (in Mode A red-teaming, Mode B peer review, or author rebuttal drafting) against all **17 official ARR heuristics**. Flag illegitimate heuristics and block them from serving as primary rejection reasons:

| Rule | Heuristic Critique | Why It Is Illegitimate | Firewall Action |
|---|---|---|---|
| `H1` | *"The results are not surprising"* | Hindsight bias; intuitive hypotheses still require empirical testing before becoming established building blocks | Block as rejection basis; require substantive flaw in design or evidence |
| `H2` | *"Results contradict what I expect"* | Confirmation bias against unexpected empirical findings | Reject dismissal unless reviewer identifies concrete methodological/data defect |
| `H3` | *"The results are not novel"* (ungrounded) | Bare novelty dismissal without citing specific prior art (respecting concurrent-work policy) or ignoring valid analysis/repro CFP scope | Demand exact citation of closing precedent or drop critique |
| `H4` | *"No precedent in existing literature"* | Penalizes genuinely original directions via conservatism bias | Reject conservatism objection; evaluate internal soundness and falsifiability |
| `H5` | *"Does not surpass latest SOTA"* | SOTA is neither necessary nor sufficient; efficiency, calibration, interpretability, fairness, or boundary insights are valid when SOTA is not claimed | Block unless authors claimed SOTA; cite exact claim scope in rebuttal |
| `H6` | *"The results are negative"* | Publication bias fuels hype; systematic well-controlled null/negative findings prevent wasted effort | Keep negative finding valid if apparatus/baselines pass engineering checks |
| `H7` | *"This method is too simple"* | Simplicity is a scientific virtue (less brittle, easier to deploy); solving the problem beats gratuitous complexity | Block gratuitous complexity demands; cite Parsimony Gate & ablations |
| `H8` | *"Doesn't use [my preferred method]"* | Interdisciplinary AI/NLP/CV accepts models, resources, surveys, theory, and error/linguistic analyses | Block method-preference bias unless chosen method fails the stated RQ |
| `H9` | *"The topic is too niche"* | Main-track papers can make deep contributions to specialized subfields or low-resource settings | Block dismissal; evaluate contribution significance within its stated scope |
| `H10` | *"Tested only on [non-English / English]"* | Monolingual work (English or non-English) has valid practical and theoretical value when scoped honestly | Block unless authors claim cross-lingual universality |
| `H11` | *"The paper has language errors"* | Clear scientific content outweighs journalistic polish when claims remain intelligible | Demote to presentation suggestion; never reject solely on grammar |
| `H12` | *"Missing [reference X]"* (recent/preprint) | Published work `3+` months pre-deadline is required; arXiv-only preprints or `<3` month works belong in suggestions (resubmissions anchor to original deadline) | Separate pre-deadline published omissions (fix) from recent preprints (acknowledge politely) |
| `H13` | *"Authors could also do [extra experiment X]"* | Only evidence required for the *claimed* scope is mandatory; follow-ups belong in suggestions unless the core claim fails without X | Show current evidence suffices for stated scope, or explain why X tests a different claim |
| `H14` | *"Should compare to closed model X"* | Closed models suffer test contamination, version drift, and opacity; only required if directly bearing on the paper's claim | Explain contamination/reproducibility boundary unless claim targets proprietary APIs |
| `H15` | *"Authors should have done [X] instead"* | "I would write a different paper" bias; valid only if current choices prevent answering the RQ or mislead | Defend chosen design against RQ criteria; demote alternative framing to optional future work |
| `H16` | *"Limitations != weaknesses"* | Penalizing candid mandatory Limitations sections incentivizes hiding flaws | Block turning disclosed scope/limitations into rejection bullets unless fatal to main claims |
| `H17` | *"Citation count != validity"* | Low-citation papers from smaller groups are not invalid; relying only on famous papers narrows science | Evaluate premise/method validity directly rather than citation popularity |

### ARR Common Paper Issues Taxonomy & Calibration
When acting as reviewer/red-teamer, separate illegitimate `H1–H17` bias from real defects coded under ARR's issue taxonomy:
- **Methodology (`M1–M5`):** `M1` unvalidated LLM-only evaluation; `M2` reproducibility gaps (distinguish *reproducibility* of same code/data from *replicability*); `M3` undisclosed data quality defects; `M4` unmotivated model/benchmark selection; `M5` incomplete theorem assumptions or proofs.
- **Artifact Sourcing/Release (`T1–T2`):** `T1` human-annotation ethics/compensation gaps (flag for ethics review); `T2` unclear dataset/model release license terms.
- **Experimental Results (`R1–R5`):** `R1` p-hacking, cherry-picking best-of-N prompts/runs, untuned baselines; `R2` overgeneralizing sample to whole capability (`a few QA tasks != reasoning`); `R3` hypotheses stated as conclusions; `R4` construct-validity overclaiming; `R5` missing statistical significance, CIs, or effect sizes.
- **General (`G1–G4`):** `G1` unclear RQ/contribution; `G2` reliance on discredited precedent; `G3` missing/misrepresented `3+` month published related work; `G4` undefined key technical terms.
- **Scale & Fatality Calibration (`Meet-Reviewer-2`):** Map scales cleanly — ARR Overall `1–5` (`>=3.5` strong, `3.0` borderline), NeurIPS `1–6` (`4` borderline accept), ICLR `1–10` (`6` weak accept, `8` strong accept). Empirically (ICLR 2024, `n=2956`), weaknesses on *positioning, scope, novelty, and related work* carry `-0.50` to `-0.77` score drops, far outweighing isolated *"add extra experiment X"* requests (`-0.02`). Fix framing and positioning first.

## 2. Structured Rebuttal Patterns & Executable Verification (`chtc66` + `check_rebuttal.py`)

### 2.1 Allowed Per-Point Response Dispositions
Every addressed point (`R1.1`, `AC.1`, `MR.1`, `Q1`, `W1`) must resolve via one of three grounded paths — **never** invent unrun experiments, hallucinated numbers, or vague *"we will polish this"* promises:
1. **Existing Manuscript Anchor:** Point directly to `Sec.`, `Table`, `Fig.`, `Eq.`, `App.`, `Alg.`, `L##`, `Abstract`, or cite `[N]` + verified artifact receipt (`run_id:`, `sha256:`, `.json`/`.csv`/`.log`).
2. **Explicitly Scoped Planned Revision:** State exact added text/table/experiment using explicit future markers (`will run/add/include`, `planned for camera-ready`, `deferred to revision`) without claiming completion.
3. **Direct Non-Sycophantic Concession:** Accept a valid limitation concisely, narrow the claim accordingly, and show why core claims remain intact (or drop the claim).

**Before/After Rebuttal Examples:**
- *Weak / Violates Integrity:* *"Thank you for this brilliant insight! We ran new experiments confirming our method dominates all baselines across every setting, and we will improve the writing."* (Triggers `sycophancy_warnings`, `unverified_experiment_claims`, `vague_promise_warnings`, and `unanchored_sections` in `check_rebuttal.py`, plus `SYC_FLATTERY` in `../../research-scientist/scripts/humanizer_lint.py --mode reply`.)
- *Strong / Anchored:* *"**R1.1** (Missing recent baseline): We added Baseline-X (`[14]`, Table 2, Sec. 4.2) using matched 5-seed budget (`runs/exp_04.json`); our method maintains `+1.8%` F1 (`95% CI [1.1, 2.5]`). **R1.2** (`H5`/SOTA scope): Our claim targets 4-bit edge inference latency rather than unconstrained cloud SOTA (Abstract, Sec. 1, L42–48); we will add an explicit scope sentence in Sec. 5 for camera-ready."*

### 2.2 Rebuttal Budget & Coverage CLI
```bash
# OpenReview character/section budget or CVPR 1-page PDF check:
python3 ../../research-scientist/scripts/check_rebuttal.py budget responses.md --sections --limit 10000 --out budget.json --compact
python3 ../../research-scientist/scripts/check_rebuttal.py budget rebuttal.pdf --mode pdf --max-pages 1 --compact

# Strict point coverage, anchor/receipt presence, and anti-fabrication check:
python3 ../../research-scientist/scripts/check_rebuttal.py coverage points.md responses.md --strict --out coverage.json --compact
```
`coverage` strips `>` blockquotes and `Reviewer comment: "..."` / `Original comment: "..."` prefixes (`_REV_QUOTE_PREFIX_RE`, not arbitrary `"..."` quotes) before auditing author prose, splits per-point sub-blocks (`- **R1.1**: ...`), verifies anchors (`ANCHOR_RE`) or receipts (`RECEIPT_RE`), flags unanchored new-experiment claims (`NEW_EXP_CLAIM_RE` lacking anchor/receipt/planned-caveat), and warns on sycophancy (`sycophancy_warnings` via `SYCOPHANCY_RE`) or vague promises (`vague_promise_warnings` via `VAGUE_PROMISE_RE`). Exit `1` on missing points or `--strict` violations (`unanchored_sections` / `unverified_experiment_claims`), `2` on invalid/binary inputs.

## 3. /10 Scorecards & Accepted-Panel Novelty Comparison

### 3.1 6-Dimension /10 Rubric & Genre Weights
Score only after naming the assessed object (`idea`, `completed manuscript`, `published paper`) and reading full text (abstract-only items cannot receive full-paper scores; unverified dimensions are `not assessed`, never `0`).
- **6 Dimensions:** `importance`, `novelty`, `soundness` (method/proof), `evidence`, `transparency`, `clarity`.
- **Common Anchors:** `0` absent/contradicted; `1–2` fatal defect; `3–4` major weakness; `5–6` adequate within narrow scope; `7–8` strong bounded contribution; `9` exceptional with strong corroboration; `10` rare field-changing standard (never assign `10` to proposals).
- **Novelty Anchors:** `0–1` direct prior work establishes same contribution; `2` label/routine combo/setting tweak; `3–4` recognizable incremental extension; `5–6` distinct bounded contribution; `7–8` substantial non-obvious advance; `9` major field shift; `10` rare retrospective landmark.
- **Default Archetype Weights (`Importance / Novelty / Soundness / Evidence / Transparency / Clarity`):** Empirical `15/20/20/20/15/10`, Theory `15/20/25/20/10/10`, Systems `15/15/25/20/15/10`, Review `15/15/20/25/15/10`. Verify weighted arithmetic via `../../research-scientist/scripts/score_math.py`.

### 3.2 `>= 5` Same-Track Accepted-Panel Workflow & K-Dense Integration
1. **Collect official same-track panel (`>= 5` recent papers):**
   ```bash
   python3 ../../research-scientist/scripts/venue_panel_collector.py --source pmlr --venue-id v235 --limit 5 --track Main --year 2024 --out panel.json --compact
   ```
   Supports `--source pmlr|acl|dblp` (use `--offline-html` when DBLP/Cloudflare triggers `bot_challenge_anubis` or `bot_challenge_cloudflare`). Every collected paper starts as `reading_basis: "metadata_only"` — read each full text before scoring.
2. **Compare scorecards & venue novelty with local locator verification:**
   ```bash
   python3 ../../research-scientist/scripts/compare_scorecards.py scorecards.json --sources-dir sources/ --out scorecard_report.json --compact
   python3 ../../research-scientist/scripts/compare_venue_novelty.py profile.json --sources-dir sources/ --quality-refs-dir quality_refs/ --out novelty_report.json --compact
   ```
   `compare_scorecards.py` requires `>= 2` profiles, all 6 integer dimensions, weights summing to `100`, `reading_basis == "full_text"`, and locators verified inside `--sources-dir`. `compare_venue_novelty.py` requires `>= 5` recent (`<= 3` years) same-track `full_text` accepted papers, all 5 fit axes (`0..2`), and hard constraints (`deadline`, `budget`, `eligibility`). Rejects `NaN`/`Infinity` (`exit 2`).
3. **K-Dense Evaluation & Peer-Review CLIs (Person-Ranking Ban):**
   Run `../../research-scientist/modules/kdense-scholar-evaluation/scripts/calculate_scores.py` (`--rubric`, `--evaluation`, `--output`), `check_traceability.py`, `weight_sensitivity.py`, plus `../../research-scientist/modules/kdense-peer-review/scripts/validate_claim_evidence.py` and `lint_review.py`. **Strict ethical ban:** Never use scoring tools to rank people or automate hiring, tenure, promotion, grant, admissions, or editorial decisions.

## 4. 5-Axis Venue Fit & Live CFP / Deadline / Fee Verification

- **5 Venue-Fit Axes (`0–2` each, sum `/10`):** (1) *Scope & audience*, (2) *Contribution & track*, (3) *Evidence maturity*, (4) *Format & eligibility*, (5) *User constraints* (timing, cost, open access, language). Any unresolved hard constraint or missing official source becomes `unverified` and blocks computing `/10`.
- **Advisory Venue Screening (`paper-quality-filter` limits):** `../../research-scientist/scripts/venue_leads.py` (`--quality-refs-dir`) attaches `S`/`A`/`B`/`C`/`Unknown` priority tags from built-in CCF 7th Ed. tables + optional JSONs. `Unknown` (including preprints like `arXiv`/`OpenReview`) never implies low quality, and an `S`/`A` tag never overrides CFP scope or fee checks.
- **Live Capture & Fail-Closed Checks:**
  ```bash
  python3 ../../research-scientist/scripts/capture_venue_sources.py dossier.json --out sources.json --artifacts-dir venue_artifacts/ --compact
  python3 ../../research-scientist/scripts/check_venue_sources.py dossier.json sources.json --out sources_report.json --compact
  python3 ../../research-scientist/scripts/check_venue_plan.py dossier.json --sources sources.json --out plan_report.json --compact
  ```
  - Fails closed (`exit 1`) on `same_host_path_redirect_year_mismatch` (e.g. `/aaai-27/` redirecting to `/aaai-25/`), `js_rendered_suspected` / `unverified_dynamic_page` (empty SPA pricing widgets), Anubis/bot blocks, stale snapshots (`> max_source_age_days`, default `30`), cross-host redirects, or missing quotes.
  - Validates exact deadline timezone conversion (preserving `AoE` / `UTC-12H`), backward work schedules, and mandatory fee categories (`submission`, `publication`, `author_registration`, `overlength`, `tax`, plus `travel`, `visa`, `lodging`, `local_transport` when `presentation_mode == "in_person"`). See [parent scoring & venue guide](../../research-scientist/references/scoring-and-venue-fit.md).
