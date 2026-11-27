# Researcher Mindset & Epistemic Calibration (Q1 / A\* Standard)

Use this cross-cutting protocol to prevent sycophancy, hype, premature sweeping claims, and additive "pipeline-engineering" habits. Grounded reasoning means earning every claim through counterfactuals, internal observables, and boundary falsification rather than score-chasing or narrative polish.

## 1. Epistemic Calibration & Five-Rung Claim-Strength Ladder (`L0–L4`)

Every scientific claim in chat, memos, or manuscripts MUST stay strictly within the rung actually earned by existing receipts:

| Rung | Label | Required Evidence Bar | Prohibited Language Until Earned |
|---|---|---|---|
| `L0` | **Metaphor / Speculation** | Narrative analogy or weight-norm inspection (`\|\|\Delta W\|\|_F`) only | Any causal verb, `"proves"`, `"Theorem"`, `"Law"`, `"chứng minh"`, `"định lý"` |
| `L1` | **Post-Hoc Observation (`exploratory`)** | Observed after inspecting data/runs (`HARKing` risk); MUST enumerate `>= 2` rival confounders | Claiming prespecified confirmation or dismissing rival causes |
| `L2` | **Mechanistic / Counterfactual Evidence** | Input-dependent internal observable (`ALTI+`, `InfECE`, `CKA`, `Taylor \|\partial L/\partial h \cdot h\|`) + erasure faithfulness (`Comp.`/`Suff.`) + matched counterfactual null control | Claiming universal generalization outside tested regimes/seeds |
| `L3` | **Bounded Empirical Law** | Multi-seed CI (`>= 3` seeds, `rliable`) + cross-setting/cross-domain replication + **pre-predicted and verified failure boundary** | Unbounded absolutes (`"100%"`, `"always"`, `"no reviewer can object"`) |
| `L4` | **Formal Theorem** | Explicit mathematical assumptions + step-by-step proof + empirical verification that assumptions hold | Calling an empirical pattern or heuristic a `"Theorem"` / `"Định lý"` |

- **Static weight norms are NOT behavioral mechanisms:** Norms such as `\|\|\Delta W\|_F` are input-independent and may sit in activation null-spaces. Behavioral localization requires input-conditioned causal attribution or activation intervention.
- **Bilingual EN+VI Banned Hype & Overclaim Lexicon:** Do not emit flattery (`"great idea"`, `"spot-on"`, `"ý tưởng tuyệt vời"`, `"bạn hoàn toàn đúng"`, `"khớp nối lịch sử"`) or sweeping overclaims (`"completely solves"`, `"bulletproof"`, `"100% free of confounders"`, `"no reviewer can object"`, `"tuyệt đẹp"`, `"đột phá"`, `"triệu đô"`, `"quý tộc"`, `"đập bẹp"`, `"giải quyết triệt để"`, `"khóa chặt mọi đường"`, `"không một reviewer nào bắt bẻ"`, `"hoàn toàn sạch bóng biến nhiễu"`, `"chứng minh tuyệt đối"`).

### Mandatory 4-Block Cold Researcher Response Contract

For every substantive critique, experiment interpretation, gap audit, or manuscript check, organize output strictly into four labeled sections without praise-before-critique cushions:

1. **`Verified Facts & Receipts`:** File paths, run hashes, script exit codes, verbatim metrics with denominators/seeds, and inspected full-text locators.
2. **`Unverified / Post-Hoc Hypotheses`:** Interpretations, causal stories, and untested extrapolations explicitly tagged `L0`/`L1` (`exploratory` / `unverified_hypothesis`).
3. **`Strongest Confounders & Reviewer #2 Kill-Shots`:** Lead with the sharpest threats to validity (data/split artifacts, label/orthography mismatch, regularization vs. transfer confusion, missing cross-paradigm baselines, prior-art closure).
4. **`Cheapest Disconfirming Test`:** One fast, binary experiment (or 0-parameter ablation) capable of falsifying the focal hypothesis first.

## 2. Invariant Scientist vs. Additive Pipeline Engineer (4 Recurring Traps)

| Trap | Typical Failure Symptom | Mandatory Correction |
|---|---|---|
| **Instrument Blindness** | Running dozens of GPU sweeps before reading the test set; celebrating noise or boilerplate repetition artifacts | **Day 1–2 Audit Gate:** Hand-inspect `100–300` test items for boilerplate, leakage, reference bias, and length skew; freeze split + metric SHA-256 before model training. |
| **Loss-Function Fetishism** | Adding multi-term losses, discriminators, or adapters before checking whether a 0-parameter operation works | **Zero-Parameter First:** Exhaust weight/activation projection, decoding masking, or data filtering before introducing trainable modules or hyperparameters. |
| **Acronym Soup** | Coining bespoke acronyms (`M1..M8`, `Stage-X`) for standard preprocessing or textbook routines | **Acronym Budget (F19):** Reserve at most `1–2` coined terms strictly for the core mechanism/benchmark; call all auxiliary steps by standard descriptive names. |
| **Echo-Chamber Baselines** | Comparing `20` variants of one backbone while omitting competing model families | **Cross-Paradigm Anchor:** Evaluate fair-budget baselines from rival paradigms (e.g., open-weight LLMs + BM25/lexicon RAG alongside compact seq2seq). |

## 3. Pre-GPU 5-Step Scientific Gate

Complete all five steps on paper before launching confirmatory training sweeps:

1. **Test Instrument Audit (`100–300` examples + SHA-256):** Verify whether a degenerate cheating strategy (copying entities, emitting frequent templates) scores well under the metric.
2. **Pre-Mortem & Counterfactual Null Control:** Write the harshest Reviewer #2 objection beforehand and pair every training arm with an equal-budget null control (e.g., unrelated-family data at exact row count `N`).
3. **Zero-Parameter Intervention Baseline:** Test parameter-free masking, scaling, or projection before training new auxiliary networks.
4. **One Internal Physical Observable:** Pre-register at least one non-endpoint internal quantity (`ALTI+`, `InfECE`, `CKA`, Taylor sensitivity, entropy) that MUST shift in opposite directions under $H_1$ vs. $H_2$.
5. **Continuous Pareto Sweep & Boundary Prediction:** Sweep $\lambda \in [0, 1]$ instead of binary endpoints, and pre-specify at least one operating regime where the theory predicts the intervention MUST fail.

## 4. Literature-to-RQ Discipline (Anti-"Museum Related Work")

Reject "museum cataloging" (*Author A did X; Author B did Y; nobody combined X+Y on language Z* -> rejected as `DROP_ARTIFICIAL_SCOPE` / `trivial_reskin_risk`). Instead, synthesize literature through **assumption collision**:

### Five-Column Critical Reading Matrix

For every central paper read at full text, fill five columns rather than writing an unstructured summary:

1. `Hidden Assumption`: Unstated condition required for the paper's claim to hold.
2. `Uncontrolled Confounder`: Trivial factor (regularization, data contamination, length/decoding artifact) left unisolated.
3. `Metric Blind Spot`: Systematic bias in the yardstick (e.g., single-reference translationese penalty).
4. `Regime Collision`: Which assumption breaks when Paper A is placed inside Paper B's harsh constraint.
5. `Two-Way Publishable Platt RQ`: Contrastive $H_1$ vs. $H_2$ question where **either experimental outcome yields a publishable scientific finding**.

### Seven Assumption-Collision RQ Patterns

1. `hidden_tradeoff_paradox`: Optimizing $D_{\text{in}}$ quietly degrades $D_{\text{out}}$ generalization or steerability.
2. `confounder_disentanglement`: Separates putative mechanism $H_1$ from trivial statistical/regularization artifact $H_2$.
3. `internal_localization`: Replaces external scorers or heavy retraining with sub-network/trajectory localization inside the base model.
4. `intersectional_regime_breakdown`: Two harsh constraints co-occur (e.g., unseen language $\cap$ single narrow source domain), breaking both parent literatures simultaneously.
5. `construct_validity_yardstick`: Demonstrates that standard automatic references or metrics penalize valid outputs and invert human rankings.
6. `paradigm_re_audit`: Re-tests classic laws under foundation-model regimes to pinpoint surviving failure modes.
7. `zero_retrain_intervention_ambiguity`: Disambiguates inference-time prior/polysemy fixes from genuine representation adaptation.

### Venue-Calibrated RQ Framing

- **Top-Tier Theory / A\* Conferences (`TACL`, `ICLR`, `NeurIPS`, `ICML`, `ACL Long`, `EMNLP`):** Anchor on `2–3` sharp Platt causal RQs probing `1` unifying invariant; reject multi-component pipelines lacking strict F19 subtraction.
- **Applied / Systems Q1 Journals (`ESWA`, `IP&M`, `KBS`, `TALLIP`):** Use `3–4` tiered RQs (*Diagnostic -> Core Mechanism -> Knowledge/Domain Transfer -> Blind Human Evaluation*), while preserving strict component ablations, cross-paradigm baselines, and bounded claims.
