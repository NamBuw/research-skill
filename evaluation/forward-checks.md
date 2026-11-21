# Development checks (synthetic fixtures, 2026-11-21)

Two agents applied the skill to fictional inputs without intended verdicts. These same-model development checks did not use real papers, live search, blinded domain reviewers, or a K-Dense baseline. The observed responses are [engineering](engineering-response.md) and [scoring/venue](scoring-venue-response.md).

| Fixture | Acceptance checks set before reading the response | Observed outcome |
|---|---|---|
| Failed reproduction, 0.41 vs 0.89 | Separate the reported normalization deviation from possible row-label mismatch; verify evaluator and identities; preserve the run; neither diagnose a scientific gap nor invent a novelty score or recovery after fixes. | Passed these checks. It also noted that `fit_transform` alone does not prove the transformer is stateful. |
| Papers A/B/C and venue Z | Recognize C as a direct algorithm precedent; leave A's unchecked context contribution and abstract-only B unranked; treat possible patient leakage and missing fees as unknown; retain abstract deadline and calculate both AoE conversions; invent no acceptance odds. | **Failed one check:** it assigned A's unsearched context contribution a provisional novelty **2/10**. It correctly withheld an overall ranking and budget/fit verdict; time conversions passed. The skill's claim-specific novelty gate was then strengthened. This run remains a recorded failure; it does not turn into a pass after the instruction changed. |

The independently computed fixture conversions were 2027-01-28 23:59 AoE → 2027-01-29 18:59 Asia/Saigon and 2027-02-04 23:59 AoE → 2027-02-05 18:59 Asia/Saigon. These are not real venue dates.

## Score helper regression

The helper initially returned `not_comparable` on a missing score before checking the other scores, letting `12/10` slip through. It now validates every non-null value first. All four reproducible checks in [`test_score_math.py`](test_score_math.py) passed: valid arithmetic, missing dimension, invalid weights, and invalid score alongside a missing dimension. This checks computation only, not scientific judgment.
