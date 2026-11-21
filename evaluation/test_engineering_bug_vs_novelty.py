"""Unit and adversarial tests for check_engineering_diagnostics.py (F12, F20)."""
from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'research-scientist/scripts'
sys.path.insert(0, str(SCRIPTS))

import check_engineering_diagnostics as diag


class EngineeringDiagnosticsTests(unittest.TestCase):
    def _write_clean_repo(self, tmp: Path):
        code_dir = tmp / 'code'
        code_dir.mkdir()
        (code_dir / 'train.py').write_text(
            "import torch\n"
            "from sklearn.model_selection import train_test_split\n"
            "from sklearn.preprocessing import StandardScaler\n"
            "def prep(X, y):\n"
            "    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=42)\n"
            "    sc = StandardScaler()\n"
            "    return sc.fit_transform(X_tr), sc.transform(X_te)\n"
            "def evaluate(model, loader):\n"
            "    model.eval()\n"
            "    with torch.no_grad():\n"
            "        return sum(model(x) for x in loader)\n"
            "def train_step(loss, accum_steps=4):\n"
            "    scaled = loss / accum_steps\n"
            "    scaled.backward()\n",
            encoding='utf-8',
        )
        splits = tmp / 'splits.csv'
        with splits.open('w', newline='', encoding='utf-8') as fh:
            csv.writer(fh).writerows([
                ['sample_id', 'split', 'group_id'],
                ['S1', 'train', 'G1'],
                ['S2', 'train', 'G1'],
                ['S3', 'val', 'G2'],
                ['S4', 'test', 'G3'],
            ])
        metrics = tmp / 'metrics.json'
        metrics.write_text(json.dumps({
            'metric_id': 'accuracy',
            'metric_direction': 'higher',
            'hpo_trials': {'baseline': 20, 'candidate': 20},
            'sanity_controls': ['dummy_majority', 'shuffled_label'],
            'runs': [
                {'model': 'dummy_majority', 'seed': 1, 'status': 'ok', 'value': 0.50},
                {'model': 'shuffled_label', 'seed': 1, 'status': 'ok', 'value': 0.49},
                {'model': 'baseline', 'seed': 1, 'status': 'ok', 'value': 0.78},
                {'model': 'baseline', 'seed': 2, 'status': 'ok', 'value': 0.79},
                {'model': 'candidate', 'seed': 1, 'status': 'ok', 'value': 0.84},
                {'model': 'candidate', 'seed': 2, 'status': 'ok', 'value': 0.85},
            ],
        }), encoding='utf-8')
        return code_dir, splits, metrics

    def test_clean_ml_cv_pytorch_pipeline_passes_and_classifies_novelty(self):
        with tempfile.TemporaryDirectory() as tmp:
            code_dir, splits, metrics = self._write_clean_repo(Path(tmp))
            res = diag.diagnose(code_dir=code_dir, splits_path=splits, metrics_path=metrics)
            self.assertEqual(res['verdict'], 'PASS')
            self.assertEqual(res['findings'], [])
            self.assertEqual(res['triage_classification'], 'genuine_scientific_novelty')

    def test_preprocessing_before_split_and_test_tuning_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            cdir = Path(tmp)
            (cdir / 'leaky.py').write_text(
                "from sklearn.feature_extraction.text import TfidfVectorizer\n"
                "from sklearn.model_selection import train_test_split\n"
                "def run(texts, y, X_test, y_test):\n"
                "    vec = TfidfVectorizer()\n"
                "    X = vec.fit_transform(texts)\n"
                "    X_tr, X_te = train_test_split(X, test_size=0.2)\n"
                "    best = tune_model(X_test, y_test)\n"
                "    return X_tr, X_te, best\n",
                encoding='utf-8',
            )
            res = diag.diagnose(code_dir=cdir)
            cats = {f['category'] for f in res['findings']}
            self.assertEqual(res['verdict'], 'ENGINEERING_BUG_DETECTED')
            self.assertIn('preprocessing_before_split_leakage', cats)
            self.assertIn('test_set_tuning_leakage', cats)

    def test_group_and_split_overlap_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            sp = Path(tmp) / 'splits.csv'
            with sp.open('w', newline='', encoding='utf-8') as fh:
                csv.writer(fh).writerows([
                    ['sample_id', 'split', 'group_id'],
                    ['S1', 'train', 'P1'],
                    ['S2', 'test', 'P1'],
                    ['S1', 'test', 'P2'],
                ])
            res = diag.diagnose(splits_path=sp)
            cats = {f['category'] for f in res['findings']}
            self.assertEqual(res['verdict'], 'ENGINEERING_BUG_DETECTED')
            self.assertIn('split_overlap_leakage', cats)
            self.assertIn('group_leakage_across_splits', cats)

    def test_nlp_contamination_and_cv_config_mismatch_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            (t / 'eval_nlp.py').write_text(
                "skip_contamination = True\n"
                "def evaluate_nlp():\n"
                "    ds = load_dataset('gsm8k', split='train')\n"
                "    return ds\n",
                encoding='utf-8',
            )
            m = t / 'metrics.json'
            m.write_text(json.dumps({
                'metric_id': 'accuracy',
                'prompt_template_count': 1,
                'backbone': {'baseline': 'resnet18', 'candidate': 'resnet50'},
                'resolution': {'baseline': 224, 'candidate': 384},
                'sanity_controls': {'constant': 0.2},
                'runs': [
                    {'model': 'baseline', 'seed': 1, 'status': 'ok', 'value': 0.70},
                    {'model': 'baseline', 'seed': 2, 'status': 'ok', 'value': 0.71},
                    {'model': 'candidate', 'seed': 1, 'status': 'ok', 'value': 0.80},
                    {'model': 'candidate', 'seed': 2, 'status': 'ok', 'value': 0.81},
                ],
            }), encoding='utf-8')
            res = diag.diagnose(code_dir=t, metrics_path=m)
            cats = {f['category'] for f in res['findings']}
            self.assertIn('nlp_benchmark_contamination', cats)
            self.assertIn('nlp_eval_on_train_split', cats)
            self.assertIn('nlp_prompt_template_sensitivity_missing', cats)
            self.assertIn('budget_or_config_mismatch', cats)

    def test_pytorch_eval_mode_grad_accum_and_metric_bugs(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            (t / 'pt_bug.py').write_text(
                "import torch\n"
                "def evaluate_epoch(model, loader):\n"
                "    model.train()\n"
                "    return sum(model(x) for x in loader)\n"
                "def train_loop(loss, grad_accum_steps=4):\n"
                "    loss.backward()\n",
                encoding='utf-8',
            )
            m = t / 'metrics.json'
            m.write_text(json.dumps({
                'metric_id': 'cross_entropy_loss',
                'metric_direction': 'higher',
                'averaging_mismatch': {'baseline': 'micro', 'candidate': 'macro'},
                'sanity_controls': ['constant'],
                'runs': [
                    {'model': 'baseline', 'seed': 1, 'status': 'ok', 'value': 0.4},
                    {'model': 'candidate', 'seed': 1, 'status': 'ok', 'value': 0.3},
                    {'model': 'candidate', 'seed': 2, 'status': 'failed', 'exit_code': 1, 'excluded': True},
                ],
            }), encoding='utf-8')
            res = diag.diagnose(code_dir=t, metrics_path=m)
            cats = {f['category'] for f in res['findings']}
            self.assertIn('pytorch_train_mode_in_eval', cats)
            self.assertIn('gradient_accumulation_unscaled_loss', cats)
            self.assertIn('metric_direction_mismatch', cats)
            self.assertIn('metric_averaging_mismatch', cats)
            self.assertIn('excluded_failed_runs', cats)
            self.assertIn('single_seed_cherry_picking', cats)

    def test_triage_repaired_engineering_bug_vs_novelty_and_compact(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            m = t / 'metrics_repair.json'
            m.write_text(json.dumps({
                'metric_id': 'ndcg@10',
                'metric_direction': 'higher',
                'prior_bug_repaired': True,
                'sanity_controls': {'shuffled': 0.05},
                'models': [
                    {'name': 'baseline', 'role': 'baseline', 'ndcg@10': 0.30, 'tuning_trials': 20, 'seed_count': 3},
                    {'name': 'candidate', 'role': 'candidate', 'ndcg@10': 0.31, 'tuning_trials': 20, 'seed_count': 3},
                    {'name': 'ref', 'role': 'reference_baseline', 'ndcg@10': 0.34, 'tuning_trials': 20, 'seed_count': 3},
                ],
            }), encoding='utf-8')
            out_p = t / 'diag.json'
            proc = subprocess.run(
                [sys.executable, str(SCRIPTS / 'check_engineering_diagnostics.py'),
                 '--metrics', str(m), '--out', str(out_p), '--compact'],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertLess(len(proc.stdout.encode('utf-8')), 4096)
            summary = json.loads(proc.stdout)
            self.assertTrue(summary['compact'])
            self.assertEqual(summary['verdict'], 'PASS')
            self.assertEqual(summary['triage_classification'], 'repaired_engineering_bug')
            self.assertTrue(out_p.is_file())

    def test_a3a_to_a3d_clean_pytorch_patterns_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            cdir = Path(tmp) / 'clean_pt'
            cdir.mkdir()
            (cdir / 'pt_clean.py').write_text(
                "import torch\n"
                "@torch.no_grad()\n"
                "def evaluate_dec(model, loader):\n"
                "    model.eval()\n"
                "    return sum(model(x) for x in loader)\n"
                "def evaluate_train_false(model, loader):\n"
                "    model.train(False)\n"
                "    with torch.inference_mode():\n"
                "        return sum(model(x) for x in loader)\n"
                "def train_aug(loss, accum_steps=4):\n"
                "    loss /= accum_steps\n"
                "    loss.backward()\n"
                "def train_float(loss, accum_steps=4):\n"
                "    scaled = loss / float(accum_steps)\n"
                "    scaled.backward()\n",
                encoding='utf-8',
            )
            res = diag.diagnose(code_dir=cdir)
            self.assertEqual(res['verdict'], 'PASS', res['findings'])
            self.assertEqual(res['findings'], [])

            cdir_warn = Path(tmp) / 'nograd_only'
            cdir_warn.mkdir()
            (cdir_warn / 'pt_nograd.py').write_text(
                "import torch\n"
                "@torch.no_grad()\n"
                "def evaluate(model, loader):\n"
                "    return sum(model(x) for x in loader)\n",
                encoding='utf-8',
            )
            res_w = diag.diagnose(code_dir=cdir_warn)
            self.assertEqual(res_w['verdict'], 'PASS')
            self.assertIn('pytorch_no_grad_without_eval', {f['category'] for f in res_w['findings']})

    def test_b1c_b1d_b2b_b5c_b5f_and_dict_hpo_detections(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            c1 = t / 'c1'
            c1.mkdir()
            (c1 / 'leak.py').write_text(
                "from sklearn.model_selection import train_test_split, GridSearchCV\n"
                "from sklearn.preprocessing import StandardScaler\n"
                "from sklearn.feature_extraction.text import TfidfVectorizer\n"
                "from sklearn.linear_model import LogisticRegression\n"
                "try:\n"
                "    import torch\n"
                "except ImportError:\n"
                "    torch = None\n"
                "def run_split_leak(X, y):\n"
                "    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)\n"
                "    sc = StandardScaler()\n"
                "    X_train = sc.fit_transform(X_train)\n"
                "    X_test = sc.fit_transform(X_test)\n"
                "    gs = GridSearchCV(LogisticRegression(), {'C': [0.1, 1.0]})\n"
                "    gs.fit(X_test, y_test)\n"
                "def evaluate_bad(model, loader):\n"
                "    model.train()\n"
                "    return sum(model(x) for x in loader)\n"
                "def evaluate_no_nograd(model, loader):\n"
                "    model.eval()\n"
                "    return sum(model(x) for x in loader)\n",
                encoding='utf-8',
            )
            (c1 / 'vec.py').write_text(
                "from sklearn.feature_extraction.text import TfidfVectorizer\n"
                "def encode(all_documents):\n"
                "    return TfidfVectorizer().fit_transform(all_documents)\n",
                encoding='utf-8',
            )
            m = t / 'metrics_dict_hpo.json'
            m.write_text(json.dumps({
                'metric_id': 'accuracy',
                'sanity_controls': {'constant': 0.5},
                'baseline': {'value': 0.72, 'seed_count': 3, 'tuning_trials': 1},
                'candidate': {'value': 0.81, 'seed_count': 3, 'tuning_trials': 50},
            }), encoding='utf-8')
            res = diag.diagnose(code_dir=c1, metrics_path=m)
            self.assertEqual(res['verdict'], 'ENGINEERING_BUG_DETECTED')
            cats = {f['category'] for f in res['findings']}
            self.assertIn('preprocessing_before_split_leakage', cats)
            self.assertIn('test_set_tuning_leakage', cats)
            self.assertIn('pytorch_train_mode_in_eval', cats)
            self.assertIn('pytorch_eval_without_no_grad', cats)
            self.assertIn('hpo_budget_asymmetry', cats)
            preproc_locs = [f['location'] for f in res['findings'] if f['category'] == 'preprocessing_before_split_leakage']
            self.assertTrue(any('leak.py' in loc for loc in preproc_locs))
            self.assertTrue(any('vec.py' in loc for loc in preproc_locs))

    def test_d3b_audit_alignment_cross_file_group_split_disagreement(self):
        import audit_alignment
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            feat = t / 'features.csv'
            lbl = t / 'labels.csv'
            feat.write_text('sample_id,split,group_id\nS1,train,SECRET_GRP_X\n', encoding='utf-8')
            lbl.write_text('sample_id,split,group_id\nS3,test,SECRET_GRP_X\n', encoding='utf-8')
            fids, fsplits, fgroups = audit_alignment.load_with_groups(feat, 'sample_id', 'split', 'group_id')
            lids, lsplits, lgroups = audit_alignment.load_with_groups(lbl, 'sample_id', 'split', 'group_id')
            rep = audit_alignment.audit(fids, lids, fsplits, lsplits, fgroups, lgroups)
            self.assertEqual(rep['shared_groups_with_split_disagreement'], 1)
            self.assertEqual(rep['shared_ids_with_split_disagreement'], 0)
            self.assertNotIn('SECRET_GRP_X', json.dumps(rep))

    def test_r3_2_bug2_compact_bounded_under_4096_bytes_on_long_locations(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            deep_dir = t / ('subdir_' + 'A' * 150) / ('nested_' + 'B' * 150) / ('leaf_' + 'C' * 150) / ('deep_' + 'D' * 150)
            deep_dir.mkdir(parents=True)
            for i in range(5):
                (deep_dir / f'leaky_{i}_{"X" * 100}.py').write_text(
                    'import torch\ndef evaluate(model, loader):\n    model.train()\n    return model(loader)\n',
                    encoding='utf-8',
                )
            proc = subprocess.run(
                [sys.executable, str(SCRIPTS / 'check_engineering_diagnostics.py'),
                 '--code-dir', str(t), '--compact'],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertLess(len(proc.stdout.encode('utf-8')), 4096)
            summary = json.loads(proc.stdout)
            self.assertTrue(summary['compact'])
            self.assertEqual(summary['verdict'], 'ENGINEERING_BUG_DETECTED')


if __name__ == '__main__':
    unittest.main()

