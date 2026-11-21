#!/usr/bin/env python3
"""AI/CS/CV/NLP engineering-bug vs genuine-novelty diagnostic checker (pure stdlib).

Detects preprocessing-before-split leakage, test-set tuning, split/group overlap,
missing baselines or sanity controls, NLP contamination/prompt sensitivity, CV
backbone/resolution/crop/augmentation/HPO asymmetries, PyTorch eval/grad-accum/metric
bugs, and seed cherry-picking. Explicitly separates repaired engineering bugs from
genuine scientific novelty.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from audit_alignment import inspect_splits_csv

_SKIP_DIRS = frozenset({'__pycache__', '.git', '.venv', 'venv', 'node_modules', 'tests'})
_PREPROC_CLASSES = frozenset({
    'StandardScaler', 'MinMaxScaler', 'RobustScaler', 'MaxAbsScaler', 'Normalizer',
    'TfidfVectorizer', 'CountVectorizer', 'HashingVectorizer', 'PCA', 'TruncatedSVD',
    'SelectKBest', 'SMOTE', 'SimpleImputer', 'KNNImputer', 'OrdinalEncoder',
    'OneHotEncoder', 'LabelEncoder', 'QuantileTransformer', 'PowerTransformer',
})
_PREPROC_VAR_RE = re.compile(r'(?:scaler|vectorizer|encoder|imputer|pca|svd|selector|smote|normalizer)', re.I)
_SPLIT_FUNCS = frozenset({
    'train_test_split', 'KFold', 'StratifiedKFold', 'GroupKFold',
    'TimeSeriesSplit', 'ShuffleSplit', 'StratifiedShuffleSplit', 'random_split',
})
_FULL_DATA_ARG_RE = re.compile(r'^(?:all_|full_|raw_)?(?:X|x|df|data|features|corpus|texts|documents|dataset|inputs)$')
_TRAIN_ARG_RE = re.compile(r'(?:train|_tr$|_tr_|^tr_)', re.I)
_TEST_ARG_NAMES = frozenset({'X_test', 'x_test', 'y_test', 'test_loader', 'test_ds', 'test_data', 'test_df'})
_TEST_OR_VAL_ARG_RE = re.compile(r'(?:^(?:[xy]_?)?(?:test|val|valid|validation|dev|eval|holdout)(?:_|$)|_(?:test|val|valid|validation|dev|eval|holdout)$)', re.I)
_TEST_TUNING_RE = re.compile(r'(?:^(?:[xy]_?)?test(?:_|$)|_test$)', re.I)
_TUNER_CLASSES = frozenset({
    'GridSearchCV', 'RandomizedSearchCV', 'HalvingGridSearchCV',
    'HalvingRandomSearchCV', 'BayesSearchCV', 'create_study',
})
_LOWER_BETTER_TOKENS = frozenset({'loss', 'cross', 'entropy', 'mse', 'mae', 'rmse', 'perplexity', 'ppl', 'wer', 'cer', 'error', 'brier', 'ece', 'nll'})
_HIGHER_BETTER_TOKENS = frozenset({'accuracy', 'acc', 'f1', 'auroc', 'auc', 'ndcg', 'map', 'miou', 'bleu', 'rouge', 'em'})
_SANITY_NAME_RE = re.compile(r'(?:dummy|constant|majority|shuffled|random)', re.I)
_CONFIG_PARITY_KEYS = ('backbone', 'resolution', 'image_size', 'crop_size', 'augmentation', 'epochs', 'compute_budget', 'training_data_budget')


def _auto_artifact_path(prefix: str) -> Path:
    art_dir = Path(tempfile.gettempdir()) / 'research_scientist_artifacts'
    art_dir.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(prefix=f'{prefix}_', suffix='.json', dir=str(art_dir))
    os.close(fd)
    return Path(raw_path)


def _add_finding(findings: list[dict[str, Any]], category: str, location: str, detail: str,
                 remediation: str, severity: str = 'error') -> None:
    findings.append({
        'id': f'ENG-{len(findings) + 1:03d}',
        'category': category,
        'severity': severity,
        'location': location,
        'detail': detail,
        'remediation': remediation,
    })


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ''


def _receiver_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return _call_name(node)
    return ''


def _arg_names(node: ast.Call) -> list[str]:
    names: list[str] = []
    for arg in node.args:
        if isinstance(arg, ast.Name):
            names.append(arg.id)
    for kw in node.keywords:
        if isinstance(kw.value, ast.Name):
            names.append(kw.value.id)
    return names


def _is_eval_train_call(node: ast.Call) -> bool:
    if node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value is False:
        return True
    return any(
        kw.arg == 'mode' and isinstance(kw.value, ast.Constant) and kw.value.value is False
        for kw in node.keywords
    )


def _analyze_scope(stmts: list[ast.AST], rel_path: str, uses_torch: bool,
                   func_name: str | None, findings: list[dict[str, Any]],
                   func_args: list[str] | None = None,
                   decorators: list[ast.AST] | None = None) -> None:
    pipeline_vars: set[str] = set()
    preproc_vars: set[str] = set()
    tuner_vars: set[str] = set()
    split_lines: list[int] = []
    fit_calls: list[tuple[int, str, list[str]]] = []

    for stmt in stmts:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Assign):
                if isinstance(node.value, ast.Call):
                    cname = _call_name(node.value)
                    if cname in {'Pipeline', 'make_pipeline'}:
                        for t in node.targets:
                            if isinstance(t, ast.Name):
                                pipeline_vars.add(t.id)
                    elif cname in _PREPROC_CLASSES:
                        for t in node.targets:
                            if isinstance(t, ast.Name):
                                preproc_vars.add(t.id)
                    elif cname in _TUNER_CLASSES:
                        for t in node.targets:
                            if isinstance(t, ast.Name):
                                tuner_vars.add(t.id)
            if not isinstance(node, ast.Call):
                continue
            cname = _call_name(node)
            if cname in _SPLIT_FUNCS:
                split_lines.append(node.lineno)
            if cname in {'fit', 'fit_transform'} and isinstance(node.func, ast.Attribute):
                recv = _receiver_name(node.func.value)
                if recv not in pipeline_vars and (recv in _PREPROC_CLASSES or recv in preproc_vars or _PREPROC_VAR_RE.search(recv)):
                    fit_calls.append((node.lineno, recv, _arg_names(node)))
            if (
                re.match(r'^(?:tune|search|GridSearchCV|RandomizedSearchCV|optimize)', cname, re.I)
                or (
                    cname in {'fit', 'optimize'}
                    and isinstance(node.func, ast.Attribute)
                    and (
                        _receiver_name(node.func.value) in tuner_vars
                        or _receiver_name(node.func.value) in _TUNER_CLASSES
                        or re.search(r'(?:grid_?search|random_?search|tuner|study)', _receiver_name(node.func.value), re.I)
                    )
                )
            ):
                args = _arg_names(node)
                test_hit = sorted({a for a in args if a in _TEST_ARG_NAMES or _TEST_TUNING_RE.search(a)})
                split_test = any(
                    kw.arg == 'split' and isinstance(kw.value, ast.Constant) and str(kw.value.value).lower() == 'test'
                    for kw in node.keywords
                )
                if test_hit or split_test:
                    _add_finding(
                        findings, 'test_set_tuning_leakage', f'{rel_path}:{node.lineno}',
                        f'Hyperparameter tuning call {cname}() accesses held-out test data ({", ".join(test_hit) or "split=test"}).',
                        'Tune strictly on training/validation folds and freeze hyperparameters before evaluating on test.',
                    )
            if func_name and re.match(r'^(?:eval|evaluate|validate|test)', func_name, re.I) and cname == 'load_dataset':
                if any(kw.arg == 'split' and isinstance(kw.value, ast.Constant) and str(kw.value.value).lower() == 'train' for kw in node.keywords):
                    _add_finding(
                        findings, 'nlp_eval_on_train_split', f'{rel_path}:{node.lineno}',
                        f'Evaluation function {func_name}() loads split="train" for evaluation.',
                        'Evaluate strictly on validation or held-out test splits with contamination verification.',
                    )

    first_split = min(split_lines) if split_lines else None
    for lineno, recv, args in fit_calls:
        first_arg = args[0] if args else ''
        arg_is_train = bool(first_arg and _TRAIN_ARG_RE.search(first_arg))
        if first_arg and (first_arg in _TEST_ARG_NAMES or _TEST_OR_VAL_ARG_RE.search(first_arg)):
            _add_finding(
                findings, 'preprocessing_before_split_leakage', f'{rel_path}:{lineno}',
                f'{recv} fit/fit_transform runs on held-out/validation variable {first_arg} instead of .transform().',
                'Fit preprocessors strictly on training data and use .transform() on validation/test splits.',
            )
        elif first_split is not None and lineno < first_split and not arg_is_train:
            _add_finding(
                findings, 'preprocessing_before_split_leakage', f'{rel_path}:{lineno}',
                f'{recv} fit/fit_transform runs on full data ({first_arg or "input"}) before train/test split at line {first_split}.',
                'Split data first, then fit preprocessing strictly on the training fold (or wrap inside sklearn Pipeline).',
            )
        elif first_split is None and first_arg and _FULL_DATA_ARG_RE.match(first_arg):
            _add_finding(
                findings, 'preprocessing_before_split_leakage', f'{rel_path}:{lineno}',
                f'{recv} fit/fit_transform runs on unsplit variable {first_arg}.',
                'Fit preprocessors only on explicit train-split variables (e.g. X_train).',
            )

    if uses_torch and func_name:
        src_dump = '\n'.join(ast.dump(s) for s in stmts)
        if re.match(r'^(?:eval|evaluate|validate|test)', func_name, re.I):
            has_model_call = any(
                isinstance(n, ast.Call) and _call_name(n) in {'model', 'net', 'backbone', 'forward'}
                for s in stmts for n in ast.walk(s)
            ) or bool(re.search(r"attr='(?:model|net)'", src_dump))
            has_train_mode = any(
                isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'train'
                and not _is_eval_train_call(n)
                for s in stmts for n in ast.walk(s)
            )
            has_eval_mode = any(
                isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and (
                    n.func.attr == 'eval' or (n.func.attr == 'train' and _is_eval_train_call(n))
                )
                for s in stmts for n in ast.walk(s)
            )
            has_decorator_no_grad = any(
                (isinstance(d, ast.Call) and _call_name(d) in {'no_grad', 'inference_mode'})
                or (isinstance(d, ast.Attribute) and d.attr in {'no_grad', 'inference_mode'})
                or (isinstance(d, ast.Name) and d.id in {'no_grad', 'inference_mode'})
                for d in (decorators or [])
            )
            has_no_grad = has_decorator_no_grad or any(
                isinstance(n, ast.Call) and _call_name(n) in {'no_grad', 'inference_mode'}
                for s in stmts for n in ast.walk(s)
            )
            if has_train_mode and not has_eval_mode:
                _add_finding(
                    findings, 'pytorch_train_mode_in_eval', f'{rel_path}:{stmts[0].lineno}',
                    f'Evaluation function {func_name}() invokes .train() instead of .eval().',
                    'Call model.eval() and wrap inference in torch.no_grad() / torch.inference_mode().',
                )
            elif has_model_call and not (has_eval_mode or has_no_grad):
                _add_finding(
                    findings, 'pytorch_missing_eval_or_no_grad', f'{rel_path}:{stmts[0].lineno}',
                    f'PyTorch evaluation function {func_name}() lacks model.eval() and torch.no_grad().',
                    'Set model.eval() and use with torch.no_grad(): during evaluation.',
                )
            elif has_model_call and has_eval_mode and not has_no_grad:
                _add_finding(
                    findings, 'pytorch_eval_without_no_grad', f'{rel_path}:{stmts[0].lineno}',
                    f'PyTorch evaluation function {func_name}() calls .eval() without torch.no_grad() or torch.inference_mode().',
                    'Wrap evaluation forward passes in with torch.no_grad(): or @torch.inference_mode().',
                    severity='warning',
                )
            elif has_model_call and has_no_grad and not has_eval_mode:
                _add_finding(
                    findings, 'pytorch_no_grad_without_eval', f'{rel_path}:{stmts[0].lineno}',
                    f'PyTorch evaluation function {func_name}() uses no_grad/inference_mode without model.eval().',
                    'Call model.eval() before evaluation so Dropout and BatchNorm run in inference mode.',
                    severity='warning',
                )
        # Gradient accumulation scaling check
        accum_var = next((a for a in (func_args or []) if re.search(r'(?:accum_steps|gradient_accumulation_steps)', a)), None)
        has_backward = False
        has_scaled_loss = False
        for s in stmts:
            for n in ast.walk(s):
                if isinstance(n, ast.Name) and re.search(r'(?:accum_steps|gradient_accumulation_steps)', n.id):
                    accum_var = n.id
                elif isinstance(n, ast.arg) and re.search(r'(?:accum_steps|gradient_accumulation_steps)', n.arg):
                    accum_var = n.arg
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'backward':
                    has_backward = True
                if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div):
                    if any(isinstance(sub, ast.Name) and re.search(r'(?:accum_steps|gradient_accumulation_steps)', sub.id) for sub in ast.walk(n.right)):
                        has_scaled_loss = True
                elif isinstance(n, ast.AugAssign) and isinstance(n.op, ast.Div):
                    if any(isinstance(sub, ast.Name) and re.search(r'(?:accum_steps|gradient_accumulation_steps)', sub.id) for sub in ast.walk(n.value)):
                        has_scaled_loss = True
        if accum_var and has_backward and not has_scaled_loss:
            _add_finding(
                findings, 'gradient_accumulation_unscaled_loss', f'{rel_path}:{stmts[0].lineno}',
                f'Gradient accumulation with {accum_var} calls .backward() without dividing loss by {accum_var}.',
                f'Normalize loss as loss = loss / {accum_var} before loss.backward().',
            )


def _check_code_dir(code_dir: Path, findings: list[dict[str, Any]], has_metrics: bool) -> None:
    if not code_dir.is_dir():
        raise ValueError(f'code_dir not found: {code_dir}')
    for root, dirs, files in os.walk(code_dir):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS)
        for fname in sorted(files):
            fpath = Path(root) / fname
            rel = str(fpath.relative_to(code_dir))
            if fname == 'baseline_config.json' and not has_metrics:
                cfg = json.loads(fpath.read_text(encoding='utf-8'))
                baselines = cfg.get('baselines') if isinstance(cfg, dict) else None
                if isinstance(baselines, dict) and len(baselines) >= 2:
                    trials = [v.get('tuning_trials') for v in baselines.values() if isinstance(v, dict) and isinstance(v.get('tuning_trials'), int)]
                    if trials and min(trials) <= 1 and max(trials) >= 5:
                        _add_finding(
                            findings, 'hpo_budget_asymmetry', rel,
                            f'Asymmetric tuning_trials in baseline_config.json ({min(trials)} vs {max(trials)}).',
                            'Match hyperparameter tuning trials across baseline and candidate methods.',
                        )
            if not fname.endswith('.py'):
                continue
            src = fpath.read_text(encoding='utf-8', errors='replace')
            try:
                tree = ast.parse(src)
            except SyntaxError as exc:
                _add_finding(findings, 'python_syntax_error', f'{rel}:{exc.lineno or 1}', str(exc), 'Fix syntax error before diagnostics.')
                continue
            uses_torch = any(
                (isinstance(n, ast.Import) and any(a.name.startswith(('torch', 'transformers')) for a in n.names))
                or (isinstance(n, ast.ImportFrom) and str(n.module or '').startswith(('torch', 'transformers')))
                for n in ast.walk(tree)
            )
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            if t.id in {'contamination_check', 'check_contamination'} and isinstance(node.value, ast.Constant) and node.value.value is False:
                                _add_finding(findings, 'nlp_benchmark_contamination', f'{rel}:{node.lineno}',
                                             f'{t.id} explicitly set to False.', 'Enable benchmark contamination verification.')
                            if t.id == 'skip_contamination' and isinstance(node.value, ast.Constant) and node.value.value is True:
                                _add_finding(findings, 'nlp_benchmark_contamination', f'{rel}:{node.lineno}',
                                             'skip_contamination set to True.', 'Run contamination checks against training corpora.')
            top_stmts = [s for s in tree.body if not isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
            if top_stmts:
                _analyze_scope(top_stmts, rel, uses_torch, None, findings)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    fargs = [a.arg for a in getattr(node.args, 'args', [])]
                    _analyze_scope(node.body, rel, uses_torch, node.name, findings, func_args=fargs, decorators=node.decorator_list)


def _metric_val(entry: dict[str, Any]) -> float | None:
    for k in ('value', 'result_value', 'score', 'ndcg@10', 'ndcg10', 'accuracy', 'f1'):
        v = entry.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return None


def _check_metrics(metrics_path: Path, findings: list[dict[str, Any]]) -> dict[str, Any]:
    if not metrics_path.is_file():
        raise ValueError(f'metrics JSON not found: {metrics_path}')
    data = json.loads(metrics_path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('metrics JSON must be an object')

    metric_id = str(data.get('metric_id') or data.get('metric') or '')
    metric_toks = set(re.split(r'[\W_]+', metric_id.casefold())) - {''}
    is_lower_metric = bool(metric_toks & _LOWER_BETTER_TOKENS)
    is_higher_metric = bool(metric_toks & _HIGHER_BETTER_TOKENS) and not is_lower_metric
    direction = str(data.get('metric_direction') or ('lower' if is_lower_metric else 'higher'))
    if metric_id and data.get('metric_direction'):
        if is_lower_metric and direction == 'higher':
            _add_finding(findings, 'metric_direction_mismatch', 'metric_direction',
                         f'Metric {metric_id} is lower-is-better but metric_direction is "higher".',
                         'Set metric_direction="lower" and re-verify comparisons.')
        elif is_higher_metric and direction == 'lower':
            _add_finding(findings, 'metric_direction_mismatch', 'metric_direction',
                         f'Metric {metric_id} is higher-is-better but metric_direction is "lower".',
                         'Set metric_direction="higher" and re-verify comparisons.')

    avg = data.get('averaging_mismatch')
    if isinstance(avg, dict) and len(set(str(v) for v in avg.values())) > 1:
        _add_finding(findings, 'metric_averaging_mismatch', 'averaging_mismatch',
                     f'Baseline and candidate use different metric averaging: {avg}.',
                     'Use identical metric averaging (e.g. both macro) across baseline and candidate.')

    if data.get('contamination_check') in {False, 'none', 'failed', 'skipped'} or data.get('benchmark_contamination_detected') is True:
        _add_finding(findings, 'nlp_benchmark_contamination', 'contamination_check',
                     'NLP benchmark contamination check missing, failed, or detected leakage.',
                     'Audit train/pretrain vs eval overlap and report decontaminated splits.')

    pt_count = data.get('prompt_template_count')
    if pt_count is None and isinstance(data.get('prompt_templates'), list):
        pt_count = len(data['prompt_templates'])
    if isinstance(pt_count, int) and pt_count <= 1 and not data.get('prompt_sensitivity_tested'):
        _add_finding(findings, 'nlp_prompt_template_sensitivity_missing', 'prompt_templates',
                     f'Only {pt_count} prompt template evaluated without sensitivity testing.',
                     'Evaluate across >=3 prompt paraphrases/templates and report mean and variance.')

    tuning_split = data.get('tuning_split')
    if isinstance(tuning_split, dict):
        for role, sp in tuning_split.items():
            if isinstance(sp, str) and sp.strip().lower() in {'test', 'test_set', 'heldout_test'}:
                _add_finding(findings, 'test_set_tuning_leakage', f'tuning_split.{role}',
                             f'{role} tuned directly on {sp} split.',
                             'Tune exclusively on train/validation splits.')

    hpo = data.get('hpo_trials')
    if isinstance(hpo, dict) and 'baseline' in hpo and 'candidate' in hpo:
        bt, ct = hpo['baseline'], hpo['candidate']
        if isinstance(bt, (int, float)) and isinstance(ct, (int, float)):
            if (bt <= 1 and ct > 1) or (bt > 0 and ct / bt >= 3.0):
                _add_finding(findings, 'hpo_budget_asymmetry', 'hpo_trials',
                             f'Asymmetric HPO tuning budget (baseline={bt}, candidate={ct}).',
                             'Allocate equal hyperparameter tuning trials to baseline and candidate.')

    intentional = set(data.get('intentional_ablation_variable') or []) if isinstance(data.get('intentional_ablation_variable'), list) else (
        {str(data['intentional_ablation_variable'])} if data.get('intentional_ablation_variable') else set()
    )
    for key in _CONFIG_PARITY_KEYS:
        val = data.get(key)
        if isinstance(val, dict) and 'baseline' in val and 'candidate' in val and key not in intentional:
            if val['baseline'] != val['candidate']:
                _add_finding(findings, 'budget_or_config_mismatch', key,
                             f'Mismatched {key} between baseline ({val["baseline"]}) and candidate ({val["candidate"]}).',
                             f'Match {key} across baseline and candidate or run an isolated ablation.')

    # Normalize runs/models/dict schemas into role buckets
    runs = data.get('runs') if isinstance(data.get('runs'), list) else None
    models = data.get('models') if isinstance(data.get('models'), list) else None
    role_ok_vals: dict[str, list[float]] = {'baseline': [], 'candidate': [], 'reference_baseline': [], 'sanity': []}
    role_seed_counts: dict[str, int] = {}
    has_baseline = False
    has_candidate = False
    has_sanity_run = False

    if runs is not None:
        ok_seeds: dict[str, set[Any]] = {'baseline': set(), 'candidate': set()}
        ok_counts: dict[str, int] = {'baseline': 0, 'candidate': 0}
        for idx, r in enumerate(runs):
            if not isinstance(r, dict):
                continue
            model = str(r.get('role') or r.get('model') or '')
            status = str(r.get('status') or 'ok').lower()
            if r.get('excluded') is True or status in {'failed', 'error'} or (isinstance(r.get('exit_code'), int) and r['exit_code'] != 0):
                _add_finding(findings, 'excluded_failed_runs', f'runs[{idx}]',
                             f'Failed/excluded run recorded for {model or "model"} (seed={r.get("seed")}).',
                             'Diagnose and report all attempted seeds rather than selectively excluding failures.')
                continue
            val = _metric_val(r)
            if _SANITY_NAME_RE.search(model) or r.get('role') in {'control', 'sanity'}:
                has_sanity_run = True
                if val is not None:
                    role_ok_vals['sanity'].append(val)
                continue
            bucket = 'reference_baseline' if 'reference' in model else ('baseline' if 'baseline' in model else ('candidate' if 'candidate' in model else model))
            if bucket == 'baseline':
                has_baseline = True
            elif bucket == 'candidate':
                has_candidate = True
            if bucket in role_ok_vals and val is not None:
                role_ok_vals[bucket].append(val)
            if bucket in ok_seeds:
                ok_counts[bucket] += 1
                if r.get('seed') is not None:
                    ok_seeds[bucket].add(r['seed'])
        for b in ('baseline', 'candidate'):
            if ok_counts[b] > 0:
                role_seed_counts[b] = len(ok_seeds[b]) if ok_seeds[b] else ok_counts[b]
    elif models is not None:
        model_trials: dict[str, int] = {}
        for idx, m in enumerate(models):
            if not isinstance(m, dict):
                continue
            name = str(m.get('name') or '')
            role = str(m.get('role') or ('baseline' if 'baseline' in name.lower() else 'candidate'))
            if _SANITY_NAME_RE.search(name) or role in {'control', 'sanity'}:
                has_sanity_run = True
                v = _metric_val(m)
                if v is not None:
                    role_ok_vals['sanity'].append(v)
                continue
            if role == 'baseline':
                has_baseline = True
            elif role == 'candidate':
                has_candidate = True
            v = _metric_val(m)
            if role in role_ok_vals and v is not None:
                role_ok_vals[role].append(v)
            if isinstance(m.get('seed_count'), int) and role in {'baseline', 'candidate'}:
                role_seed_counts[role] = m['seed_count']
            if isinstance(m.get('tuning_trials'), int) and role in {'baseline', 'candidate'}:
                model_trials[role] = m['tuning_trials']
        if 'baseline' in model_trials and 'candidate' in model_trials:
            bt, ct = model_trials['baseline'], model_trials['candidate']
            if (bt <= 1 and ct > 1) or (bt > 0 and ct / bt >= 3.0):
                _add_finding(findings, 'hpo_budget_asymmetry', 'models.tuning_trials',
                             f'Asymmetric tuning_trials (baseline={bt}, candidate={ct}).',
                             'Match HPO budget between baseline and candidate.')
        # Compare config parity between baseline and candidate entries in models list
        base_m = next((m for m in models if isinstance(m, dict) and m.get('role') == 'baseline'), {})
        cand_m = next((m for m in models if isinstance(m, dict) and m.get('role') == 'candidate'), {})
        for key in _CONFIG_PARITY_KEYS:
            if key in base_m and key in cand_m and base_m[key] != cand_m[key] and key not in intentional:
                _add_finding(findings, 'budget_or_config_mismatch', f'models.{key}',
                             f'Mismatched {key}: baseline={base_m[key]} vs candidate={cand_m[key]}.',
                             f'Match {key} across baseline and candidate.')
    elif isinstance(data.get('baseline'), dict) and isinstance(data.get('candidate'), dict):
        has_baseline = True
        has_candidate = True
        for role in ('baseline', 'candidate'):
            entry = data[role]
            v = _metric_val(entry)
            if v is not None:
                role_ok_vals[role].append(v)
            if isinstance(entry.get('seeds'), list):
                role_seed_counts[role] = len(entry['seeds'])
            elif isinstance(entry.get('seed_count'), int):
                role_seed_counts[role] = entry['seed_count']
        for key in _CONFIG_PARITY_KEYS:
            if key in data['baseline'] and key in data['candidate'] and data['baseline'][key] != data['candidate'][key] and key not in intentional:
                _add_finding(findings, 'budget_or_config_mismatch', key,
                             f'Mismatched {key}: baseline={data["baseline"][key]} vs candidate={data["candidate"][key]}.',
                             f'Match {key} across baseline and candidate.')
        bt, ct = data['baseline'].get('tuning_trials'), data['candidate'].get('tuning_trials')
        if (isinstance(bt, (int, float)) and not isinstance(bt, bool)
                and isinstance(ct, (int, float)) and not isinstance(ct, bool)):
            if (bt <= 1 and ct > 1) or (bt > 0 and ct / bt >= 3.0):
                _add_finding(findings, 'hpo_budget_asymmetry', 'tuning_trials',
                             f'Asymmetric tuning_trials (baseline={bt}, candidate={ct}).',
                             'Match hyperparameter tuning budget between baseline and candidate.')

    # Baseline & sanity controls
    if has_candidate and not has_baseline and not role_ok_vals['reference_baseline']:
        _add_finding(findings, 'missing_baseline', 'runs',
                     'Candidate runs reported without a matched baseline.',
                     'Include an adequately tuned simple baseline under identical splits and budgets.')

    sc = data.get('sanity_controls')
    has_sanity = has_sanity_run or (isinstance(sc, list) and len(sc) > 0) or (isinstance(sc, dict) and len(sc) > 0)
    if isinstance(sc, dict):
        for k, v in sc.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                role_ok_vals['sanity'].append(float(v))
    if (runs is not None or models is not None or has_candidate) and not has_sanity:
        _add_finding(findings, 'missing_sanity_control', 'sanity_controls',
                     'Missing constant/majority or shuffled-label sanity control receipt.',
                     'Add dummy/constant and shuffled-label sanity baselines to verify pipeline signal.')

    if role_ok_vals['candidate'] and role_ok_vals['sanity']:
        cand_mean = sum(role_ok_vals['candidate']) / len(role_ok_vals['candidate'])
        for sv in role_ok_vals['sanity']:
            failed = (cand_mean >= sv) if direction == 'lower' else (cand_mean <= sv)
            if failed:
                _add_finding(findings, 'failed_sanity_control', 'sanity_controls',
                             f'Candidate mean ({cand_mean:.4f}) fails to outperform sanity control ({sv:.4f}).',
                             'Debug model/pipeline before claiming improvement.')
                break

    # Seed parity checks
    if 'baseline' in role_seed_counts and 'candidate' in role_seed_counts:
        if role_seed_counts['baseline'] != role_seed_counts['candidate']:
            _add_finding(findings, 'seed_count_mismatch', 'seeds',
                         f'Unequal seed count: baseline={role_seed_counts["baseline"]} vs candidate={role_seed_counts["candidate"]}.',
                         'Run identical multi-seed sets across baseline and candidate.')
    if role_seed_counts.get('candidate') == 1 and not data.get('deterministic'):
        _add_finding(findings, 'single_seed_cherry_picking', 'seeds',
                     'Candidate evaluated on a single seed without deterministic=true.',
                     'Evaluate across >=3 fixed seeds and report mean and variance.')

    return {
        'direction': direction,
        'role_means': {k: (sum(v) / len(v)) for k, v in role_ok_vals.items() if v},
        'candidate_seeds': role_seed_counts.get('candidate', 0),
        'prior_bug_repaired': bool(data.get('prior_bug_repaired') or data.get('repair_only') or data.get('baseline_bug_fixed')),
        'deterministic': bool(data.get('deterministic')),
    }


def diagnose(
    code_dir: Path | None = None,
    splits_path: Path | None = None,
    metrics_path: Path | None = None,
) -> dict[str, Any]:
    if code_dir is None and splits_path is None and metrics_path is None:
        raise ValueError('Provide at least one of --code-dir, --splits, or --metrics')
    findings: list[dict[str, Any]] = []
    if code_dir is not None:
        _check_code_dir(code_dir, findings, has_metrics=(metrics_path is not None))
    if splits_path is not None:
        sp = inspect_splits_csv(splits_path, group_column='auto')
        if sp['ids_in_multiple_splits'] > 0:
            _add_finding(findings, 'split_overlap_leakage', str(splits_path),
                         f'{sp["ids_in_multiple_splits"]} sample ID(s) span multiple splits.',
                         'Enforce disjoint sample IDs across train, validation, and test splits.')
        if sp['groups_in_multiple_splits'] > 0:
            _add_finding(findings, 'group_leakage_across_splits', str(splits_path),
                         f'{sp["groups_in_multiple_splits"]} group ID(s) span multiple splits.',
                         'Use GroupKFold / group-disjoint splitting so entities never cross splits.')
        if sp['duplicate_id_rows'] > 0 and sp['ids_in_multiple_splits'] == 0:
            _add_finding(findings, 'duplicate_sample_ids', str(splits_path),
                         f'{sp["duplicate_id_rows"]} duplicate sample ID row(s) detected.',
                         'Deduplicate samples or verify repeated-measurement grouping.')
    metrics_meta = _check_metrics(metrics_path, findings) if metrics_path is not None else None

    has_errors = any(f['severity'] == 'error' for f in findings)
    verdict = 'ENGINEERING_BUG_DETECTED' if has_errors else 'PASS'
    if has_errors:
        triage = 'engineering_bug'
    elif metrics_meta is not None:
        means = metrics_meta['role_means']
        direction = metrics_meta['direction']
        cand = means.get('candidate')
        base = means.get('baseline')
        ref = means.get('reference_baseline')

        def _beats(a: float | None, b: float | None) -> bool:
            if a is None or b is None:
                return False
            return a < b if direction == 'lower' else a > b

        if metrics_meta['prior_bug_repaired']:
            triage = 'repaired_engineering_bug'
        elif ref is not None and not _beats(cand, ref):
            triage = 'repaired_engineering_bug'
        elif _beats(cand, base) and (ref is None or _beats(cand, ref)) and (metrics_meta['candidate_seeds'] >= 2 or metrics_meta['deterministic']):
            triage = 'genuine_scientific_novelty'
        else:
            triage = 'repaired_engineering_bug'
    else:
        triage = 'engineering_checks_clean'

    return {
        'schema': 'research_scientist_engineering_diagnostics_v1',
        'verdict': verdict,
        'triage_classification': triage,
        'finding_count': len(findings),
        'findings': findings,
        'disclaimer': (
            'Engineering checks screen for code, split, metric, and parity defects only. '
            'PASS or genuine_scientific_novelty still requires independent prior-art verification.'
        ),
    }


def compact_summary(report: dict[str, Any], artifact_path: Path) -> dict[str, Any]:
    shown = [
        {
            'id': str(f['id'])[:32],
            'category': str(f['category'])[:80],
            'location': str(f['location'])[:160],
            'detail': str(f['detail'])[:140],
        }
        for f in report['findings'][:5]
    ]
    out: dict[str, Any] = {
        'compact': True,
        'schema': report['schema'],
        'artifact_path': str(artifact_path),
        'verdict': report['verdict'],
        'triage_classification': report['triage_classification'],
        'finding_count': report['finding_count'],
        'findings_truncated': max(0, len(report['findings']) - len(shown)),
        'findings': shown,
    }
    while len(json.dumps(out, separators=(',', ':'), ensure_ascii=False).encode('utf-8')) >= 4095 and out['findings']:
        out['findings'].pop()
        out['findings_truncated'] = max(0, len(report['findings']) - len(out['findings']))
    if len(json.dumps(out, separators=(',', ':'), ensure_ascii=False).encode('utf-8')) >= 4095:
        out['artifact_path'] = out['artifact_path'][-200:]
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--code-dir', type=Path, default=None, help='Directory of Python training/eval scripts')
    parser.add_argument('--splits', type=Path, default=None, help='Splits CSV (sample_id,split[,group_id])')
    parser.add_argument('--metrics', type=Path, default=None, help='Metrics/runs JSON file')
    parser.add_argument('--out', type=Path, default=None, help='Optional output JSON path')
    parser.add_argument('--compact', action='store_true', help='Emit bounded <4096B stdout summary + disk artifact path')
    args = parser.parse_args()
    try:
        report = diagnose(code_dir=args.code_dir, splits_path=args.splits, metrics_path=args.metrics)
        out_path = args.out
        if args.compact and out_path is None:
            out_path = _auto_artifact_path('engineering_diagnostics')
        if out_path is not None:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
        if args.compact:
            print(json.dumps(compact_summary(report, out_path), separators=(',', ':'), ensure_ascii=False))
        else:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report['verdict'] == 'PASS' else 1
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
