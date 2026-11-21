# Novelty, Venue Verification & Rebuttal Protocol (AI/CS/CV/NLP)

Load this guide only for /10 scoring, venue CFP/fee audits, peer review, or rebuttal preparation.

## 1. /10 Scorecards & Accepted-Panel Novelty
- Collect `>= 5` same-track accepted papers via `../../research-scientist/scripts/venue_panel_collector.py` (`--source`, `--venue-id`, `--limit`, `--out`, `--compact`).
- Run `../../research-scientist/scripts/compare_scorecards.py` (`--sources-dir`) and `../../research-scientist/scripts/compare_venue_novelty.py`. Every dimension requires `full_text` reading basis and verifiable local locators.

## 2. Live CFP & Fee Verification
- Capture official pages via `../../research-scientist/scripts/capture_venue_sources.py` (`--out`, `--compact`) and verify quotes via `../../research-scientist/scripts/check_venue_sources.py` + `../../research-scientist/scripts/check_venue_plan.py`.
- Fail closed on `same_host_path_redirect_year_mismatch` or `js_rendered_suspected` empty fee tables.

## 3. Peer-Review Fairness (H1–H17) & Rebuttal Checks
- **Fairness firewall (`Meet-Reviewer-2`):** Flag illegitimate reviewer critiques: (H1–H4) vague non-actionable claims or unsupported novelty rejections without citing prior art; (H5–H8) attacking parsimony/simplicity when results hold or demanding out-of-scope baselines; (H9–H17) penalizing candid limitations, assuming hidden SOTA thresholds, or ignoring rebuttal evidence.
- **Rebuttal non-fabrication (`chtc66`):** Every point (`R1.1`, `AC.1`, `MR.1`) must map to (a) existing manuscript anchor (`Sec./Table/Fig./Eq.`), (b) explicitly labeled planned change, or (c) direct concession. Never claim unrun experiments as completed.
- Check char/PDF budgets: `python3 ../../research-scientist/scripts/check_rebuttal.py budget responses.md --sections --limit 10000 --compact` (or `rebuttal.pdf --max-pages 1`).
- Check coverage & anchors: `python3 ../../research-scientist/scripts/check_rebuttal.py coverage points.md responses.md --strict --compact`.
