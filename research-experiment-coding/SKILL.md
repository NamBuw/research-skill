---
name: research-experiment-coding
description: "Enforce systematic root-cause debugging, TDD, verification-before-completion, PyTorch/HF hygiene, reproducibility checks, rliable multi-seed IQM/CI stats, contamination checks, and SHA-256 run receipts."
---

# Research Experiment Coding & Rigor

Prevent self-inflicted ML engineering bugs from masquerading as scientific phenomena. Never report experiments as passing or complete without fresh command execution receipts and verified SHA-256 artifacts.

## Non-Negotiable Coding & Debugging Laws

1. **4-Phase Root-Cause Debugging (`obra/superpowers`, MIT):** No code patch until root cause is reproduced and isolated: (1) inspect failing trace/data contract, (2) compare clean vs failing state, (3) test single minimal hypothesis, (4) write failing test before fixing.
2. **Iron Law of Verification-Before-Completion:** Never claim tests pass, metrics improved, or leaks are fixed without running the exact verification command after the final edit and citing its observed output/exit code.
3. **Zero-Sycophancy & Parsimony:** Reject over-engineered 3+ module wrappers when a clean minimal script/baseline matches or beats IQM.
4. **AI/CS/CV/NLP Engineering Hygiene (`affaan-m/ECC`, MIT):** Enforce train-only preprocessor `.fit()`, disjoint split IDs, `model.eval()` + `torch.no_grad()`, synchronized GPU timing, fixed seeds, and explicit tensor shape/dtype assertions.

## Shared Verification Tools (`../research-scientist/scripts/`)

| Check | Shared Tool & Mode | Gate Criteria |
|---|---|---|
| Leakage & PyTorch AST | [check_engineering_diagnostics.py](../research-scientist/scripts/check_engineering_diagnostics.py), [audit_alignment.py](../research-scientist/scripts/audit_alignment.py) | `PASS` (no split leak, eval bug, or missing sanity control) |
| Reproducibility essentials | [check_experiment_rigor.py](../research-scientist/scripts/check_experiment_rigor.py) `repro` | `README`, pinned `ENV`, `SEED`, `ENTRYPOINT`, `DATA`, `RESULTS_CMD` |
| Multi-seed IQM & 95% CI | [check_experiment_rigor.py](../research-scientist/scripts/check_experiment_rigor.py) `rliable` | 25% trimmed IQM, stratified bootstrap CI, optimality gap, `P(X>Y)` |
| Benchmark contamination | [check_experiment_rigor.py](../research-scientist/scripts/check_experiment_rigor.py) `contamination` | Zero exact matches; n-gram overlap below threshold |
| Run-log SHA-256 receipts | [check_experiment_manifest.py](../research-scientist/scripts/check_experiment_manifest.py) (`--verify-files`) | Exact SHA-256 & numeric claim match against logs |

Load [experiment coding & debugging guide](references/experiment-coding-debugging.md) on demand for the 4-phase checklist, PyTorch/GPU rules, and CLI examples.
