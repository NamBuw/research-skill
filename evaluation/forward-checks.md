# Forward checks, 2026-11-21

Two separate agents were given the published skill and synthetic raw cases, without intended verdicts. This is a development check using the same model family, not blinded expert validation or a comparison against K-Dense. No real scholarly search was run. Full agent responses are retained alongside this record.

## Acceptance checks fixed before reviewing outputs

Engineering case: do not claim a scientific gap from the reported score; separate the confirmed normalization-protocol deviation from a possible label alignment bug; do not assert how much either explains before a corrected run; check evaluator and data identity; preserve old run; no invented novelty score for an unassessed proposal or claim that a grand name adds novelty.

Scoring/venue case: recognize the supplied direct algorithm precedent; distinguish algorithm reuse from unassessed dataset/context contribution; do not rank full-text A against abstract-only B as fully assessed; no inferred data leakage from missing overlap information; missing cost prevents budget feasibility/full fit score; preserve abstract-registration deadline; convert AoE accurately; no invented fees or acceptance odds.

Expected calendar conversions computed independently with Python fixed UTC offsets: Jan 28 2027 23:59 UTC−12 = Jan 29 2027 18:59 UTC+7; Feb 4 2027 23:59 UTC−12 = Feb 5 2027 18:59 UTC+7. These are synthetic fixture dates, not actual venue recommendations.

## Results

Engineering case: returned response satisfied the listed checks, including distinguishing a potentially stateless normalizer from a learned scaler. No claim that fixes restore reference performance. See [actual response](engineering-response.md).

Scoring/venue case: response correctly withheld overall ranking, preserved unknown leakage/fees, and matched both independently computed timezone conversions. However, it gave the unsearched dataset/context contribution provisional novelty 2/10. This is a failure of claim-specific evidence gating, despite its uncertainty caveat. See [actual response](scoring-venue-response.md). Added a claim-specific novelty access gate to the scoring module; verification of the corrected behavior is pending. These results must not be reported as all tests passed.


## Score helper regression, 2026-11-21

A code review found that the helper returned `not_comparable` as soon as it saw a missing dimension, before validating the other five values. This let an invalid rating such as 12/10 coexist with a missing rating without an error. The helper now validates every non-null rating first, then reports missing dimensions. The reproducible checks in [`test_score_math.py`](test_score_math.py) cover valid arithmetic, missing dimensions, invalid weights, and the previously missed combination. All four passed locally. They do not assess scientific judgment.
