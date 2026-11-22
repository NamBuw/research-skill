---
name: research-novelty-venue
description: "Run /10 paper/idea scoring with locator checks, accepted-panel novelty comparison, live CFP/fee verification, and AI/CS peer-review rebuttal budget, coverage, and H1-H17 fairness checks."
---

# Research Novelty, Venue Audit & Rebuttal

Evaluate novelty against same-track accepted papers, verify live venue CFPs/fees, and audit peer reviews or rebuttals without sycophancy or unverified assertions.

## Non-Negotiable Integrity Rules

1. **Full-text basis & >=3 closest-work anchoring:** Never score Novelty or Overall in isolation. Positive `/10` verdicts require `reading_basis == "full_text"`, local locators, scoring `>= 3` closest related papers (`closest_work`) on the same 6-dim rubric (`--target-id`, `--strict-related-panel`), and `>= 5` same-track accepted papers (PMLR/ACL/DBLP).
2. **Verified live venue facts:** Never rely on stale redirects (`/2027/` -> `/2025/`), guessed deadlines/TZ, or unrendered JS pricing pages; unknown fees/dates block venue fit scores.
3. **Rebuttal non-fabrication (`chtc66`, MIT):** Never present planned or unrun experiments as completed. Distinguish verified manuscript evidence (`Sec./Table/Fig.`), planned camera-ready runs, and honest concessions.
4. **Fairness firewall (`Meet-Reviewer-2`, MIT):** Reject illegitimate critiques (e.g., demanding gratuitous complexity when simple baselines work, rejecting explicit limitations, or novelty claims without precedent citations).
5. **Submission Readiness, Cross-Topic Bar & Hard Tier Rejection:** Every `/10` scorecard or venue check MUST state fatal-gate status, standing vs *all submissions*, same-topic closest work, and cross-topic `venue_contribution_bar`, reject mismatched targets bluntly (`rejected_below_venue_tier`, never viable stretch for Q1/flagship when workshop-scale), and list top fixes — never invented `%` acceptance odds.
6. **Strict multi-venue portfolio evaluation:** Score `>= 3–5` concrete venues (`--portfolio`, `--require-panels`) across primary, peer/Tier-A, and fallback options under identical CFP, 5-axis fit, hard-constraint, tier-floor, and timeline-conflict gates (`hold_for_rework`, `disqualified`, `withheld_unverified`, `rejected_below_venue_tier`); retarget via `recommended_matched_tier` or `no_viable_venue_in_portfolio`, never recommending unverified venues casually.

## Shared Tools (`../research-scientist/scripts/` & `modules/`)

| Task | Shared Tool | Gate Output |
|---|---|---|
| Accepted panel & novelty | [venue_panel_collector.py](../research-scientist/scripts/venue_panel_collector.py), [compare_scorecards.py](../research-scientist/scripts/compare_scorecards.py) (`--target-id`, `--strict-related-panel`, `--min-related`), [compare_venue_novelty.py](../research-scientist/scripts/compare_venue_novelty.py) (`--portfolio`, `--require-panels`, `--min-venues`, `--target-overall`), [score_math.py](../research-scientist/scripts/score_math.py) | Verified /10 scorecards, `>=3` related-work deltas & `>=5` panel / portfolio |
| Live CFP & fee audit | [venue_leads.py](../research-scientist/scripts/venue_leads.py), [capture_venue_sources.py](../research-scientist/scripts/capture_venue_sources.py), [check_venue_sources.py](../research-scientist/scripts/check_venue_sources.py), [check_venue_plan.py](../research-scientist/scripts/check_venue_plan.py) | Exact quote match, redirect/JS checks, TZ/fees |
| Rebuttal budget & coverage | [check_rebuttal.py](../research-scientist/scripts/check_rebuttal.py) (`budget`, `coverage`) | OpenReview char / CVPR-1p PDF + `R1.1`/`AC.1` anchors |
| K-Dense evaluation | [calculate_scores.py](../research-scientist/modules/kdense-scholar-evaluation/scripts/calculate_scores.py), [validate_claim_evidence.py](../research-scientist/modules/kdense-peer-review/scripts/validate_claim_evidence.py) | Weighted rubric & review claim-evidence audit |
| Connected submission pipeline | [evaluate_submission.py](../research-scientist/scripts/evaluate_submission.py) (`--out`, `--compact`, `--subfield-preset`) | Cross-tool gates, desk-reject & retarget plan |

Load [novelty, venue & rebuttal protocol](references/novelty-venue-rebuttal-protocol.md) on demand for H1–H17 fairness rules, readiness bands, two-axis panel/tier calibration, portfolio gates, and rebuttal templates.
