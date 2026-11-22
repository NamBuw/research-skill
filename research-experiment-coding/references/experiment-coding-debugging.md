# Experiment Coding, Debugging & Statistical Rigor (AI/CS/CV/NLP)

Load this guide only when debugging ML pipelines, writing experiment scripts, or auditing multi-seed results, contamination, or run receipts.

## 1. 4-Phase Root-Cause Debugging, Isolation & TDD (`obra/superpowers`)

Never propose a research modification or "stabilization module" until the failure has passed all four phases:

1. **Phase 1 — Reproduce & Freeze:** Record exact failing command, commit SHA, seed, dataset slice, hardware/precision, and full traceback before editing code.
2. **Phase 2 — Binary Bisection & Isolation:**
   - **Data/input bisection:** Shrink batch/dataset to a 4–16 example hand-checkable slice; verify shapes, label range, mask polarity, and zero NaN/Inf inputs.
   - **Test-order bisection (`find-polluter`):** When a test passes alone but fails in a suite, bisect the preceding tests in halves (`0..n/2`, `n/2..n`) until the single state-mutating test (global RNG, `torch.backends`, env var, temp file) is isolated.
3. **Phase 3 — Red-Green TDD:** Write a minimal deterministic regression test reproducing the exact failure mode. Run it and confirm it **fails** (Red) for the expected reason before patching, apply the minimal root-cause fix, then confirm it **passes** (Green).
4. **Phase 4 — Verification-Before-Completion (Iron Law):** No fix claim is valid without a fresh, post-edit command execution quoting exact exit code, pass/fail counts, and artifact paths. Fixing a broken baseline or training loop yields `repaired_engineering_bug`, never `genuine_scientific_novelty`.

## 2. PyTorch / HF / DDP / AMP & Data-Contract Checklists (`affaan-m/ECC`)

Distinguish **AST-verified checks** (enforced by `../../research-scientist/scripts/check_engineering_diagnostics.py`) from **manual coding hygiene** items inspected directly in code review:

### 2.1 AST-Checked by `check_engineering_diagnostics.py`
- **Split-before-fit:** Fit `_PREPROC_CLASSES` (`StandardScaler`, `MinMaxScaler`, `TfidfVectorizer`, `PCA`, `OneHotEncoder`, etc.) or receivers matching `*scaler|*vectorizer|*encoder|*imputer|*pca|*svd|*selector|*smote|*normalizer` strictly on `train` split; call `.transform()` on `val`/`test`. Never fit on full unsplit data before `train_test_split` (generic `tokenizers` not matching `*encoder*`/`*vectorizer*` are verified manually in §2.2).
- **No test-set tuning:** Never pass `X_test`, `y_test`, or `split="test"` to `_TUNER_CLASSES` (`GridSearchCV`, `RandomizedSearchCV`, `HalvingGridSearchCV`, `HalvingRandomSearchCV`, `BayesSearchCV`, Optuna `create_study`) or `tune*`/`search*`/`optimize*` calls; freeze configs before evaluating held-out test splits (arbitrary helper names such as `select_prompts(X_test)` require manual review in §2.2).
- **Eval mode & `no_grad`:** Every `eval*`/`validate*`/`test*` function calling a PyTorch/HF model must set `model.eval()` (or `model.train(False)`) and wrap forward passes in `with torch.no_grad():` or `@torch.inference_mode()`. Omitting **both** emits `pytorch_missing_eval_or_no_grad` (`severity="error"`, exit `1`), whereas omitting **only one** emits `pytorch_eval_without_no_grad` or `pytorch_no_grad_without_eval` (`severity="warning"`, exit `0`).
- **Gradient accumulation scaling:** Whenever `accum_steps` or `gradient_accumulation_steps` is used with `.backward()`, normalize loss via `loss = loss / accum_steps` before `.backward()`.
- **Contamination flags:** Never hardcode `contamination_check = False` or `skip_contamination = True`, and never evaluate NLP tasks on `split="train"`.

### 2.2 Manual PyTorch / HF / DDP / AMP Coding Hygiene Checklist
- **Tokenizer & prompt-selection split hygiene:** Fit generic/HF `tokenizer` trainers strictly on the `train` split (never on full unsplit corpora unless named `*encoder*`/`*vectorizer*` where AST also checks), and never run prompt-selection helpers (e.g., `select_prompts(X_test)`) on held-out `test` splits.
- **Device & determinism:** Use explicit `.to(device)` everywhere (no hardcoded `.cuda()` assumptions); set `random.seed`, `np.random.seed`, `torch.manual_seed`, `torch.cuda.manual_seed_all`, plus `torch.backends.cudnn.deterministic = True` and `benchmark = False` for exact reproduction runs.
- **AMP & optimization loop:** Call `optimizer.zero_grad(set_to_none=True)`. With FP16 `torch.amp.autocast("cuda")`, use `GradScaler`: `scaler.scale(loss).backward()` -> `scaler.unscale_(optimizer)` -> `torch.nn.utils.clip_grad_norm_(...)` -> `scaler.step(optimizer)` -> `scaler.update()`. Omit `GradScaler` when using `bfloat16`. Avoid in-place autograd ops (`+=`, `inplace=True`) and calling `.item()` before `.backward()`.
- **DDP correctness:** Call `DistributedSampler.set_epoch(epoch)` each epoch; guard checkpoint writes and metric logging with `rank == 0` plus `dist.barrier()` where needed; aggregate global validation numerators/denominators via `dist.all_reduce()` before dividing; verify `find_unused_parameters` only when conditional branches exist.
- **DataLoader & checkpointing:** Use `pin_memory=True` with CUDA, `drop_last=True` when `BatchNorm` could receive a 1-sample tail batch, deterministic `worker_init_fn`, and `torch.load(..., weights_only=True)` for untrusted checkpoints (use `safetensors` where supported).
- **Sample-weighted metrics & GPU timing:** Accumulate `loss_sum += loss.item() * batch_size` and divide by total sample/token count (not unweighted batch mean across uneven final batches). Call `torch.cuda.synchronize()` before start/end `time.perf_counter()` calls when benchmarking latency.

## 3. Leakage, Baseline Parity & Sanity-Control Diagnostics

Run automated diagnostics across code, splits CSV, and metrics JSON:

```bash
python3 ../../research-scientist/scripts/check_engineering_diagnostics.py --code-dir src --splits splits.csv --metrics metrics.json --out diag.json --compact
python3 ../../research-scientist/scripts/audit_alignment.py features.csv labels.csv --id-column sample_id --split-column split --group-column patient_id --out align.json --compact
```

| Finding Category (`check_engineering_diagnostics.py`) | Failure Exposed | Required Remediation |
|---|---|---|
| `preprocessing_before_split_leakage`, `test_set_tuning_leakage` | Fit on full data/val/test or HPO on test split | Move scaler/vectorizer inside CV or post-split `train` only; freeze HPO on `val` |
| `split_overlap_leakage`, `group_leakage_across_splits`, `duplicate_sample_ids` | Same ID or group (`user_id`, `doc_id`, `patient_id`) across splits | Re-split via `GroupKFold`/grouped hash; re-run `audit_alignment.py` until overlap=0 |
| `pytorch_train_mode_in_eval`, `pytorch_missing_eval_or_no_grad` (`error`, exit `1`); `pytorch_eval_without_no_grad` / `pytorch_no_grad_without_eval` (`warning`, exit `0`); `gradient_accumulation_unscaled_loss` | Dropout/BN active or gradients tracked at test time, or unscaled accum gradients | Add `model.eval()` + `torch.inference_mode()`; divide loss by `accum_steps` |
| `metric_direction_mismatch`, `metric_averaging_mismatch` | Lower-is-better metric compared as higher-is-better, or macro vs micro mix | Align metric direction and exact averaging formula across all methods |
| `hpo_budget_asymmetry`, `budget_or_config_mismatch` | Unequal `tuning_trials`, `backbone`, `resolution`, `crop_size`, `augmentation`, `epochs`, or data budget | Match baseline and candidate budgets identically; isolate 1 variable per ablation |
| `missing_baseline`, `missing_sanity_control`, `failed_sanity_control` | No simple baseline, or missing/non-random constant/shuffled-label control | Add tuned simple baseline (`ItemKNN`/linear/BM25) + shuffled-label sanity test |
| `excluded_failed_runs`, `single_seed_cherry_picking`, `seed_count_mismatch` | Diverged seeds dropped or candidate uses more/cherry-picked seeds | Report all attempted runs and matched multi-seed stats (`>= 3` seeds) |
| `nlp_benchmark_contamination`, `nlp_eval_on_train_split`, `nlp_prompt_template_sensitivity_missing` | Disabled contamination check, train-split eval, or `<= 1` prompt tested | Enable contamination screen, use held-out split, test `>= 3` prompt paraphrases |

Exit codes for `check_engineering_diagnostics.py`: `0` (`PASS`, including warning-only runs), `1` (`ENGINEERING_BUG_DETECTED` when any `error` finding exists), `2` (bad args/IO/JSON). `audit_alignment.py` exits `0` on any valid CSV run (even with non-zero alignment mismatch counts — inspect JSON output counts) and `2` on argument/file/parse errors. See [engineering vs gap protocol](../../research-scientist/references/engineering-vs-gap.md).

## 4. Statistical Rigor (`rliable`), Contamination & Run-Receipt Verification

### 4.1 Reproducibility Essentials (`repro`)
```bash
python3 ../../research-scientist/scripts/check_experiment_rigor.py repro . --strict --max-files 2000 --out repro.json --compact
```
Checks 6 essentials: `README`, `ENV` (with pinned dependencies or lockfile), `SEED` (AST-parsed, comment/docstring/BOM-stripped code plus `.ipynb` cell magic stripping), `ENTRYPOINT`, `DATA`, and `RESULTS_CMD` (including fenced README code blocks). `repro` decodes `.py`/`.ipynb` with `utf-8-sig` and `errors="replace"` (`exit 1` on missing essentials or `--strict` warnings; `exit 2` on invalid args, missing directory, or non-positive `--max-files`), whereas `rliable` and `contamination` exit `2` on invalid UTF-8 inputs (`rliable` also rejects UTF-8 BOM JSON with `exit 2`).

### 4.2 Multi-Seed `rliable` Statistics (`rliable`)
```bash
python3 ../../research-scientist/scripts/check_experiment_rigor.py rliable scores.json --baseline BaseModel --tau 1.0 --reps 1000 --seed 0 --strict --out rliable.json --compact
```
Input schema requires `methods` mapping each method name to a rectangular `[n_seeds][n_tasks]` matrix of finite floats (`bool`, `null`, `NaN`, `Infinity`, ragged rows, UTF-8 BOM/invalid UTF-8, or `--reps < 10` fail immediately with exit `2`). Outputs:
- **25% trimmed IQM (`iqm`)** with **stratified bootstrap 95% CI (`iqm_ci95`)**;
- **Optimality gap (`optimality_gap`)** relative to `--tau`;
- **Probability of improvement `P(X > Y)` (`prob_improvement_vs_baseline`)** and 95% CI against `--baseline`.
- Warnings: `underpowered_seeds` when `n_seeds < 3`, and `no_clear_improvement` when `P(X > Y) <= 0.5`. `--strict` turns warnings into exit `1`.

### 4.3 Train/Eval N-Gram Contamination (`contamination`)
```bash
python3 ../../research-scientist/scripts/check_experiment_rigor.py contamination --train train.jsonl --eval eval.jsonl --ngram 8 --threshold 0.05 --out contam.json --compact
```
Computes deterministic exact and word n-gram (`--ngram >= 3`) overlap across `.jsonl`/`.json`/`.csv` or text directories (rejects binary/NUL or invalid UTF-8 files with exit `2`; skips outside-root symlinks). Returns `CONTAMINATION_DETECTED` (exit `1`) if `exact_match_count > 0` or `contaminated_fraction >= threshold`, else `PASS` (exit `0`).

### 4.4 Run-Log & On-Disk SHA-256 Receipts (`check_experiment_manifest.py`)
```bash
python3 ../../research-scientist/scripts/check_experiment_manifest.py manifest.json --verify-files --claims claims.json --rel-tol 0.001 --abs-tol 0.0005 --audit-repo . --blind double --strict-repo --out manifest_check.json --compact
```
- Manifest requires `question_id`, `protocol_version`, timezone-aware `protocol_frozen_at_utc`, and non-empty `runs[]` (16 required fields including 64-hex SHA-256 hashes for `split_manifest_sha256`, `metric_script_sha256`, `result_artifact_sha256`, `role` in `{baseline, candidate, control}`, `decision_timing` in `{prespecified, amended, exploratory}`).
- Prespecified runs must have `started_at_utc >= protocol_frozen_at_utc` and matching `protocol_version`, `data_version`, `split_manifest_sha256`, `metric_id`, and `metric_script_sha256` across baseline/candidate pairs.
- `--verify-files` checks on-disk SHA-256 hashes, `run_log_path` (`run_id`, `exit_code`, `result_value`), and numeric match between `result_value` and artifact JSON/CSV/TSV (`--claims` checks paper claim tables within tolerance).
- `--audit-repo` checks train/eval scripts, `tests/`, README reproducibility commands, archival DOIs, and `--blind double` leaks (emails, non-anonymous GitHub URLs).
- **Exit codes:** `0` (`structurally_checked`), `2` (`invalid` or CLI/file error — note exit `2`, not `1`).

## 5. Artifact, License, PII & Release Readiness (`check_artifact_readiness.py`)

Run unified release-readiness verification across the code repository and optional dataset/model manifest before public or double-blind release:

```bash
python3 ../../research-scientist/scripts/check_artifact_readiness.py --repo-dir . --manifest manifest.json --anonymous --strict --max-files 2000 --out readiness.json --compact
```

### 5.1 Six Deterministic Release Checks
1. **`license`:** Verifies root `LICENSE*`/`COPYING*`/`pyproject.toml`/`package.json` plus manifest `datasets[]`, `pretrained_models[]`/`models[]`, and `dependencies[]`; blocks missing, placeholder, or proprietary licenses, non-commercial conflicts with permissive/commercial releases, and strong copyleft (`GPL`/`AGPL`/`CC-BY-SA`) incompatibility with permissive code (`MIT`/`Apache-2.0`/`BSD`); warns on undocumented `RAIL`/`OpenRAIL` or unrecognized custom licenses.
2. **`pii`:** Scans text, notebooks, and data files (`.csv`, `.tsv`, `.jsonl`, `.json`) for SSNs, Luhn-validated credit cards, phone numbers, non-allowlisted emails in data files, sensitive schema columns (`ssn`, `passport`, `credit_card`, `dob`, `mrn`), and public IPv4s (exempting `example.{com,org,net,edu}`, `127.0.0.1`, RFC 5737 IPs). All matched PII is **redacted** in `findings[*].message`.
3. **`reproducibility`:** Strips Python comments and docstrings via AST/`tokenize` (and `#` comments in shell/R/Julia and `.ipynb` code cells) so `# torch.manual_seed(42)` fails `reproducibility/missing-seed`; requires dependency manifest + version pins/lockfile (`uv.lock`, `poetry.lock`, `==`), runnable entrypoint (`run.sh`/`train.py`/`__main__`), and `README*` with explicit reproduction commands.
4. **`local_paths`:** Blocks hardcoded `/home/<user>`, `/Users/<user>`, `C:\Users\<user>`, and `file:///` paths while exempting generic placeholders (`user`, `username`, `yourname`, `anon`). Enforces `os.walk(..., followlinks=False)`, symlink root containment, and `..` manifest path traversal rejection.
5. **`secrets`:** Detects leaked API keys/tokens (short examples: `sk-...`, `sk-ant-...`, `hf_...`, `AKIA...`, `ghp_<redacted>`, `AIza...`, `xoxb-...`, `pypi-...`, PEM private keys, hardcoded `*_API_KEY`/`*_TOKEN` literals, and non-template `.env` files), ignoring `os.environ.get(...)` and placeholders. All secrets are **masked** in `findings[*].message` and `blocking_reasons`.
6. **`anonymization` (`--anonymous`):** Inspects `.git/` and `.git/config` remotes/user before skipping `.git` internals; matches manifest `authors`/`affiliations`/`institution` across files; flags non-example emails, `_IDENTITY_HOSTS` / `.edu` / `/~user` URLs (allowing `anonymous.4open.science` / `anonymous.science`), `CITATION.cff`/`AUTHORS*`/`NOTICE`/package metadata, and unredacted `Acknowledgments`/grant lines.

### 5.2 Readiness Status & `evaluate_submission.py` Contract

| Status | Meaning | Exit Code | `ready_to_submit` / Cap |
|---|---|---|---|
| `PASS` | Zero `FAIL` and zero `WARN` findings across active checks | `0` | `true` / `null` |
| `WARN` | Zero `FAIL` blockers; non-blocking warnings remain (exits `1` if `--strict`) | `0` (`1` with `--strict`) | `true` / `recommended_transparency_cap = 5` |
| `FAIL` | One or more blocking license, PII, secret, path, repro, or anonymity failures | `1` | `false` / `recommended_transparency_cap = 3` |

CLI/IO/JSON errors (empty/whitespace flags, missing paths, `NaN`/`Infinity`, `..` traversal) emit `{"error": ...}` to `stderr` and exit `2` without tracebacks. Outputs `"schema": "artifact_readiness_v1"` with `status`, `verdict`, `ready_to_submit`, `ready_for_release`, `recommended_transparency_cap`, `blocking_reasons`, `warnings`, `summary`, `checks`, and redacted `findings` (`--compact` stays strictly `<= 3800` bytes).
