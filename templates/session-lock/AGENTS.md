# Research Scientist Session Lock (Workspace Rule)

Every turn in this workspace MUST operate under the `research-scientist` Hub-and-Spoke research methodology (`~/.agents/skills/research-scientist/SKILL.md`; fallbacks: `~/.claude/skills/research-scientist/SKILL.md` or `~/.codex/skills/research-scientist/SKILL.md`).

## 1. Session Startup & Compaction Anchor

- On a new conversation or after context compaction, read `research-scientist/SKILL.md` first and load `./project_state.json` if present (or initialize it with `~/.agents/skills/research-scientist/scripts/project_state.py --init` once scope is confirmed).
- If target venue/tier, compute/data/deadline constraints, or starting artifact/comparative advantage are unsettled, start with at most **2–3 concrete Socratic intake questions** before recommending experiments or venues.

## 2. Six-Spoke Phase Routing

Execute stages in order; never skip an invalidating gate:

1. **Precedent & Corpus (`research-precedent-corpus`):** Run retrieval/citation trails and read primary full text for decisive claims (`search_papers.py`, `search_campaign.py`, `resolve_fulltext.py`, `extract_pdf_blocks.py`, `local_evidence.py`).
2. **Gap, RQ & Parsimony (`research-gap-rq-audit`):** Separate engineering defects from scientific gaps (`storm_explorer.py`, `gap_pipeline.py`, `check_gap_record.py`, `check_question_card.py`). When using cross-domain analogies (§7), strip domain nouns, check prior transfer in the target domain, tag `isomorphic_transfer_leads` strictly as `lead`, and test a cheap pilot first.
3. **Experiment Coding & Rigor (`research-experiment-coding`):** Apply 4-phase root-cause debugging, leakage/split parity checks, `rliable` multi-seed IQM+CI stats, contamination checks, and SHA-256 run receipts (`check_engineering_diagnostics.py`, `audit_alignment.py`, `check_experiment_rigor.py`, `analyze_experiment_outcome.py`). For Speech/Audio, pass `--subfield-preset speech_audio` (speaker/session disjoint splits, decoding/LM/vocoder/normalization parity).
4. **Novelty, Venue & Rebuttal (`research-novelty-venue`):** Anchor scores against `>=3` closest works and `>=5` same-track accepted papers with live CFP/fee verification (`score_math.py`, `compare_scorecards.py`, `compare_venue_novelty.py`, `triage_reviews.py`, `evaluate_submission.py`, `check_rebuttal.py`).
5. **Writing, Figures & Preflight (`research-paper-writing`):** Audit claims 1-to-1, eliminate AI tells/sycophancy, check figure contrast/DPI, anonymize, and clean TeX/BibTeX (`humanizer_lint.py`, `check_manuscript_ledger.py`, `check_artifact_readiness.py`, `check_figure_qa.py`, `check_submission_preflight.py`).
6. **User Report (`research-user-report`):** Compile concise verdict-first reports in the user's language (`report_latex_pdf.py`).

## 3. Non-Negotiable Invariants

- **Zero Sycophancy & Falsification-First (F1):** Attack claims across prior art, engineering defects, missing receipts, grandiose rebranding, and overcomplication before stating merit. Never praise intuition or use praise-sandwiches.
- **Read-Before-Cite & Zero Fabrication:** Papers not read at full text remain `metadata_only` with `ratings: null` (and full-text digests require a verified non-placeholder `locator`). Never invent acceptance percentages (`%`), citations, numbers, or CLI results; unverified CFP dates/fees stay `unverified`.
- **Engineering-Before-Novelty & Parsimony (F19, "Least Is Best"):** Block novelty endorsement when splits, leakage, baselines, or receipts are unverified, or when a simpler baseline/minimal fix matches complex multi-module stacks without positive component ablation.
- **Token-Frugal Disk Offloading (F20):** Prefer `--out <file> --compact` when invoking suite scripts in `~/.agents/skills/research-scientist/scripts/`, and persist validated state transitions into `./project_state.json`.
