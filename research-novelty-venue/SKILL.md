---
name: research-novelty-venue
description: "Run /10 paper/idea scoring with locator checks, accepted-panel novelty comparison, live CFP/fee verification, and AI/CS peer-review rebuttal budget, coverage, and H1-H17 fairness checks."
---

# Research Novelty, Venue Audit & Rebuttal

Evaluate novelty against same-track accepted papers, verify live venue CFPs/fees, and audit peer reviews or rebuttals without sycophancy or unverified assertions.

## Non-Negotiable Integrity Rules

1. **Full-text basis for /10 scores:** Positive novelty/score verdicts require `reading_basis == "full_text"`, local evidence locators, and `>= 5` same-track accepted papers (PMLR/ACL/DBLP).
2. **Verified live venue facts:** Never rely on stale redirects (`/2027/` -> `/2025/`), guessed deadlines/TZ, or unrendered JS pricing pages; unknown fees/dates block venue fit scores.
3. **Rebuttal non-fabrication (`chtc66`, MIT):** Never present planned or unrun experiments as completed. Distinguish verified manuscript evidence (`Sec./Table/Fig.`), planned camera-ready runs, and honest concessions.
4. **Fairness firewall (`Meet-Reviewer-2`, MIT):** Reject illegitimate critiques (e.g., demanding gratuitous complexity when simple baselines work, rejecting explicit limitations, or novelty claims without precedent citations).

## Shared Tools (`../research-scientist/scripts/` & `modules/`)

| Task | Shared Tool | Gate Output |
|---|---|---|
| Accepted panel & novelty | [venue_panel_collector.py](../research-scientist/scripts/venue_panel_collector.py), [compare_scorecards.py](../research-scientist/scripts/compare_scorecards.py), [compare_venue_novelty.py](../research-scientist/scripts/compare_venue_novelty.py), [score_math.py](../research-scientist/scripts/score_math.py) | Verified /10 scorecards & `>=5` panel novelty |
| Live CFP & fee audit | [venue_leads.py](../research-scientist/scripts/venue_leads.py), [capture_venue_sources.py](../research-scientist/scripts/capture_venue_sources.py), [check_venue_sources.py](../research-scientist/scripts/check_venue_sources.py), [check_venue_plan.py](../research-scientist/scripts/check_venue_plan.py) | Exact quote match, redirect/JS checks, TZ/fees |
| Rebuttal budget & coverage | [check_rebuttal.py](../research-scientist/scripts/check_rebuttal.py) (`budget`, `coverage`) | OpenReview char / CVPR-1p PDF + `R1.1`/`AC.1` anchors |
| K-Dense evaluation | [calculate_scores.py](../research-scientist/modules/kdense-scholar-evaluation/scripts/calculate_scores.py), [validate_claim_evidence.py](../research-scientist/modules/kdense-peer-review/scripts/validate_claim_evidence.py) | Weighted rubric & review claim-evidence audit |

Load [novelty, venue & rebuttal protocol](references/novelty-venue-rebuttal-protocol.md) on demand for H1–H17 fairness rules and rebuttal templates.
