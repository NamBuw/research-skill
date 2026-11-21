# Experiment Coding, Debugging & Statistical Rigor (AI/CS/CV/NLP)

Load this guide only when debugging ML pipelines, writing experiment scripts, or auditing multi-seed results.

## 1. 4-Phase Root-Cause Debugging & TDD (`obra/superpowers`)
1. **Reproduce & read:** Capture exact failing command, seed, dataset slice, and traceback before guessing.
2. **Isolate:** Bisect minimal failing input or test polluter; verify data shapes, label range, and split disjointness.
3. **Red-Green TDD:** Add a deterministic unit/smoke test reproducing the bug; confirm it fails before fixing, then passes after the minimal patch.
4. **Verification-Before-Completion:** Re-run the full relevant suite (`--strict` / `pytest`) after final edits; cite actual exit code and counts.

## 2. PyTorch / HF & MLE Data-Contract Hygiene (`affaan-m/ECC` & `K-Dense/optimize-for-gpu`)
- Fit scalers/tokenizers/imputers strictly on `train` split; verify zero ID/group overlap across `train`/`val`/`test`.
- Evaluation functions MUST set `model.eval()` and `torch.no_grad()` (or `torch.inference_mode()`), divide accumulated loss by sample/token count, and use `torch.cuda.synchronize()` before latency timing.
- Keep equal compute, backbone, resolution, crop, augmentation, and HPO budgets between candidate and baseline.

## 3. Executable Verification Commands
- Code & split diagnostics: `python3 ../../research-scientist/scripts/check_engineering_diagnostics.py --code-dir src --splits splits.csv --metrics metrics.json --compact`
- Reproducibility essentials: `python3 ../../research-scientist/scripts/check_experiment_rigor.py repro . --strict --compact`
- Multi-seed `rliable` IQM + 95% CI: `python3 ../../research-scientist/scripts/check_experiment_rigor.py rliable scores.json --baseline ItemKNN --reps 1000 --compact`
- Train/eval n-gram contamination: `python3 ../../research-scientist/scripts/check_experiment_rigor.py contamination --train train.jsonl --eval eval.jsonl --compact`
- Run-log SHA-256 receipts: `python3 ../../research-scientist/scripts/check_experiment_manifest.py --verify-files manifest.json`
