# Review Triage, Deep Scoring & Calibration Benchmark Guide (AI/CS/CV/NLP)

Load this guide for pre-submission 3-persona adversarial mock reviews, post-reject `H1–H17` triage with 2–4 week Venue B revision planning, `F30#5–8` deep scoring diagnostics, `F31#2` subfield depth presets, or monotonic calibration benchmarks. See [novelty-venue-rebuttal-protocol.md](novelty-venue-rebuttal-protocol.md) for the `H1–H17` / `M1–M5` / `T1–T2` / `R1–R5` / `G1–G4` definitions and [parent scoring & venue guide](../../research-scientist/references/scoring-and-venue-fit.md) for `score_math.py` F23–F25 floors.

## 1. Mode 1: Pre-Submission 3-Persona Adversarial Mock Review (`mock-review`)

Run deterministic adversarial review fusing upstream rigor, ledger, preflight, artifact readiness, venue CFP, and scorecard outputs:

```bash
python3 ../../research-scientist/scripts/triage_reviews.py mock-review --input dossier.json --scorecard scorecards_report.json --venue-novelty novelty_report.json --rigor repro.json rliable.json contamination.json --ledger ledger_report.json --preflight anonymize.json bibtex.json --artifact-readiness readiness.json --venue-sources sources_report.json --venue-plan plan_report.json --engineering-diagnostics eng_diag.json --sections sections.json --anchors anchors.json --venue-tier top_tier_flagship --scale native --subfield-preset nlp_llm --strict --out mock_review.json --compact
```

- **3 Adversarial Personas:** `method_theory` (*Method & Theory*: `soundness`, `M5`, grandiose/overcomplicated methods, `claim_scope_alignment`, `ml_theory` controls), `experiments_baselines` (*Experiments & Baselines*: `evidence`, `transparency`, `repro`, `rliable`, `contamination`, engineering bugs, `contribution_evidence_map`, anonymization, `artifact_readiness`), and `novelty_positioning` (*Novelty & Positioning*: `novelty`, `related_work_differentiation`, `compare_scorecards`, `compare_venue_novelty`, `venue_sources`, `bibtex`).
- **Severity & Exit Codes:** Defects emit `fatal` / `major` / `minor`. Default exit is `0` on valid inputs; `--strict` exits `1` on fatal defects, `fatal_gate_triggered`, or `rejected_below_venue_tier`. Invalid/missing files, `NaN`/`Infinity`, booleans in numeric fields, or unknown `--subfield-preset` exit `2`. `--compact` emits `< 4096` UTF-8 bytes. Never invent `%` acceptance probabilities.

### Deep Scoring Diagnostics (`F30#5–8`) & Subfield Presets (`F31#2`)
- **`F30#5` `side_by_side_anchor_contrast`:** Contrasts target vs `2–3` accepted anchors (both `same_topic` and cross-topic) across `benchmarks_count`, `sota_baselines_covered`, `ablation_depth`, `theoretical_rigor`, `effect_size_ci_stability`, and `code_artifact_openness` (marking unverified fields `"unverified"`/`null`, never fabricating).
- **`F30#6` `merit_vs_publishability`:** Splits `scientific_merit_score` (`importance`, `novelty`, `soundness`, `evidence` with `recommended_evidence_cap`) from `publishability_packaging_score` (`transparency`, `clarity` capped by `recommended_transparency_cap` and penalized for preflight/artifact/CFP failures), classifying `bottleneck_diagnosis` (`science_bottleneck`, `packaging_and_venue_bottleneck`, `both_bottlenecked`, `aligned`).
- **`F30#7` `section_diagnostics`:** Evaluates all 6 sections (`abstract`, `introduction`, `related_work`, `method`, `experiments`, `limitations`) with status (`pass`, `weak`, `fatal`, `not_assessed`), linked issues, and `priority_edit_order`.
- **`F30#8` `worst_case_sensitivity`:** Computes `worst_case_reviewer_floor`, `worst_case_persona`, `deal_breaker_dimensions` (where `-1` triggers fatal gate or tier rejection), and `non_rescuable_dimensions` (where `+1` fails to clear fatal gate or tier rejection).
- **`F31#2` Subfield Depth Presets (`--subfield-preset`):** Matches `gap_pipeline.py` canonical keys:
  - `nlp_llm`: `contamination_check`, `multi_prompt_variance`, `compute_matched_open_weight_baseline`, `eval_harness_parity`
  - `cv_multimodal`: `backbone_resolution_augmentation_parity`, `flops_fps_memory_tradeoff`, `qualitative_failure_analysis`
  - `ml_theory`: `assumption_tightness_realism`, `lower_vs_upper_bound_gap`, `empirical_sanity_validation`
  - `ai_systems`: `end_to_end_vs_microbenchmark`, `tail_latency_p99`, `peak_vram_comm_overhead`, `matched_hardware`
  - `speech_audio`: `speaker_session_disjoint_split`, `audio_metric_and_normalization_parity`, `decoding_vocoder_embedding_parity`, `speech_slice_significance_and_consent`

| Status | Audit Meaning (`subfield_preset_audit` / `venue_b_checks`) |
|---|---|
| `PASS` | All required controls verified for active preset |
| `WARN` | One or more required controls missing (`missing_checks`) |
| `FAIL` | One or more required controls explicitly failed (`failed_checks`) |
| `NOT_SELECTED` | No `--subfield-preset` selected |
| `ready_for_resubmission` | Venue B timing, anonymity, CFP sources, and tier floor clear |
| `resubmission_blocked` | Blocked by passed/short deadline, cooldown, anonymity leak, CFP block, or tier mismatch |
| `unverified` | Venue B metadata/constraints not provided |

## 2. Mode 2: Post-Reject `H1–H17` Triage & 2–4 Week Venue B Plan (`post-reject`)

Filter illegitimate reviewer heuristics from substantive `M1–M5`, `T1–T2`, `R1–R5`, and `G1–G4` defects and schedule a bounded 2–4 week Venue B plan:

```bash
python3 ../../research-scientist/scripts/triage_reviews.py post-reject --reviews venue_a_reviews.json --venue-a "NeurIPS 2026" --venue-b venue_b.json --venue-sources sources_report.json --venue-plan plan_report.json --preflight anonymize.json --artifact-readiness readiness.json --scorecard scorecard.json --as-of 2026-11-22T00:00:00Z --weeks 3 --subfield-preset nlp_llm --strict --out triage_plan.json --compact
```

| Disposition | Post-Reject Triage Action |
|---|---|
| `filtered_illegitimate_heuristic` | Quarantined `H1–H17` bias (respecting caveats: `H3` with cited prior art, `H5` if SOTA claimed, `H12` `>=3` months published promoted to `G3`, `H14` if targeting proprietary API) |
| `substantive_defect` | Actionable `M1–M5` / `T1–T2` / `R1–R5` / `G1–G4` defect scheduled into `Week 1..N` (`2 <= N <= 4`) by empirical impact (framing/soundness first) |
| `presentation_minor` | `H11` grammar/typo polish scheduled outside blocking rework |

## 3. Monotonic 5-Tier Calibration Benchmark (`F29#7`)

Calibrated benchmark dossiers in `evaluation/fixtures/calibration_benchmark/` verify strict monotonic ordering and F23–F25 tier consistency via `../../research-scientist/scripts/score_math.py`, `../../research-scientist/scripts/compare_scorecards.py`, and `../../research-scientist/scripts/compare_venue_novelty.py`:

| Tier | Weighted `/10` Anchor | Canonical `score_math.py` Band | Expected Venue Posture |
|---|---|---|---|
| Tier 1 (`Oral / Spotlight`) | `8.35` (`9,8,8,9,8,8`) | `strong_top_tier_contender` | `recommended_now` at `top_tier_flagship` |
| Tier 2 (`Main-Track Accept`) | `7.15` (`8,7,7,7,7,7`) | `competitive_top_tier_main_track` | `recommended_now` at `top_tier_flagship` |
| Tier 3 (`Borderline / Findings`) | `6.35` (`7,6,7,6,6,6`) | `borderline_top_tier_competitive_findings_tier_a` | `stretch_high_risk` at flagship; `recommended_now` at `q1_or_tier_a` |
| Tier 4 (`Workshop Accept`) | `5.40` (`6,4,6,5,6,6`) | `workshop_or_preliminary_only` | `rejected_below_venue_tier` at flagship & `q1_or_tier_a`; retargeted to `workshop_or_preliminary` |
| Tier 5a (`Clear Reject`) | `4.50` (`4,4,5,5,4,5`) | `not_ready_major_rework` | `rejected_below_venue_tier` everywhere (`no_viable_venue_in_portfolio`) |
| Tier 5b (`Fatal-Gate Trap`) | `7.20` (`8,8,4,8,8,8`) | `not_ready_fatal_gate` | `soundness=4` fatal gate overrides mean (`hold_for_rework`) |
