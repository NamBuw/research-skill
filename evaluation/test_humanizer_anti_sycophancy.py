"""Tests for Humanizer prose linting, anti-sycophancy, claim preservation, and 8-gram overlap."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "research-scientist" / "scripts" / "humanizer_lint.py"

spec = importlib.util.spec_from_file_location("humanizer_lint", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


class HumanizerAntiSycophancyTests(unittest.TestCase):
    def test_clean_technical_prose_and_latex_masking_pass_strict(self):
        md_text = (
            "---\n"
            'title: "Pivotal Tapestry"\n'
            "---\n\n"
            "# Experimental setup\n\n"
            "```python\n"
            "# As an AI language model, let's delve into this pivotal tapestry.\n"
            "```\n\n"
            "We compute leverage scores using robust statistics over the loss landscape with an attention gate. "
            "The runtime scales as $\\mathcal{O}(n \\log n)$ under `--strict` and `--compare-baseline` checks. "
            "Prior records from 2020–2024 (pp. 10–15) use a third-party evaluator and a high-quality benchmark. "
            "Our evaluation not only checks split identity, but also verifies metric consistency — without altering labels.\n"
        )
        tex_text = (
            "\\documentclass{article}\n"
            "% delve pivotal groundbreaking\n"
            "\\begin{document}\n"
            "\\section{Method}\n"
            "We measure empirical risk \\cite{delve2024} as documented at \\url{https://example.com/tapestry}.\n"
            "\\begin{equation}\n"
            "L(\\theta) = \\frac{1}{n} \\sum_{i=1}^n \\ell(f_\\theta(x_i), y_i)\n"
            "\\end{equation}\n"
            "\\end{document}\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            md_path = Path(tmpdir) / "clean.md"
            tex_path = Path(tmpdir) / "clean.tex"
            md_path.write_text(md_text, encoding="utf-8")
            tex_path.write_text(tex_text, encoding="utf-8")

            for p in (md_path, tex_path):
                proc = run_cli(str(p), "--strict", "--json")
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                data = json.loads(proc.stdout)
                self.assertEqual(data["risk_count"], 0)
                self.assertEqual(data["warn_count"], 0)
                self.assertEqual(data["sycophancy_hits"], [])

    def test_shnlc_ai_prose_fixture_detected_and_fails_strict(self):
        shnlc_text = (
            "# Stochastic Hierarchical Non-Linear Calibration (SHNLC)\n\n"
            "Let's dive into how SHNLC works. "
            "SHNLC is not just a calibration layer; it is a paradigm shift. "
            "At its core, what really matters is representational alignment. "
            "A tempting approach would be to freeze the encoder, but SHNLC leverages hidden states "
            "and undoubtedly plays a crucial role in calibration, highlighting its effectiveness and underscoring its potential.\n\n"
            "Moreover, we delve into this pivotal architecture because SHNLC serves as a drop-in module "
            "that stands as a testament to clean design.\n\n"
            "Furthermore, the design offers two strengths:\n\n"
            "- **Modularity:** swaps heads cleanly.\n"
            "- **Efficiency:** runs with low overhead.\n\n"
            "That distinction matters.\n\n"
            "I hope this helps!\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "shnlc.md"
            p.write_text(shnlc_text, encoding="utf-8")
            proc = run_cli(str(p), "--strict", "--json")
            self.assertEqual(proc.returncode, 1, proc.stdout)
            data = json.loads(proc.stdout)
            self.assertGreaterEqual(data["risk_count"], 1)
            self.assertGreaterEqual(data["warn_count"], 6)
            pattern_ids = {f["pattern_id"] for f in data["findings"]}
            for expected in ("H01", "H02", "H03", "H04", "H05", "H12", "H13", "H15", "H18", "H19", "H22", "PL02"):
                self.assertIn(expected, pattern_ids, f"Missing expected pattern {expected} in {pattern_ids}")

    def test_sycophancy_and_praise_sandwich_blocked(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            flattery_p = Path(tmpdir) / "flattery.md"
            flattery_p.write_text(
                "Great idea! Your intuition is spot-on. "
                "This novel unified framework is a promising direction that achieves an impressive gain "
                "and groundbreaking, revolutionary, well-motivated and compelling results.\n",
                encoding="utf-8",
            )
            proc_a = run_cli(str(flattery_p), "--strict", "--json")
            self.assertEqual(proc_a.returncode, 1)
            data_a = json.loads(proc_a.stdout)
            self.assertGreaterEqual(data_a["risk_count"], 1)
            syc_ids_a = {h["pattern_id"] for h in data_a["sycophancy_hits"]}
            self.assertIn("SYC_FLATTERY", syc_ids_a)
            self.assertIn("SYC_CHEERLEADING", syc_ids_a)
            self.assertTrue(any(h["critical"] for h in data_a["sycophancy_hits"]))

            sandwich_p = Path(tmpdir) / "sandwich.md"
            sandwich_p.write_text(
                "This is a promising framework with strong potential. "
                "However, the evaluation leaks test labels and omits the baseline.\n",
                encoding="utf-8",
            )
            proc_b = run_cli(str(sandwich_p), "--strict", "--json")
            self.assertEqual(proc_b.returncode, 1)
            data_b = json.loads(proc_b.stdout)
            syc_ids_b = {h["pattern_id"] for h in data_b["sycophancy_hits"]}
            self.assertIn("SYC_PRAISE_SANDWICH", syc_ids_b)

            blunt_p = Path(tmpdir) / "blunt.md"
            blunt_p.write_text(
                "The evaluation fails: test labels leak into normalization (line 42 of train.py) "
                "and the baseline omits weight decay. Accuracy drops from 84.1% to 61.3% once fixed.\n",
                encoding="utf-8",
            )
            proc_c = run_cli(str(blunt_p), "--strict", "--json")
            self.assertEqual(proc_c.returncode, 0, proc_c.stdout)
            data_c = json.loads(proc_c.stdout)
            self.assertEqual(data_c["sycophancy_hits"], [])

    def test_claim_preservation_diff_catches_dropped_facts(self):
        baseline = (
            "SHNLC reduces latency from 18.4 ms to 12.1 ms (94.2% ± 0.3% accuracy, p < 0.01) "
            "only under IID splits \\cite{kipf2017} [C001], and doesn't generalize to OOD graphs.\n"
        )
        clean_paraphrase = (
            "Under IID splits only, SHNLC lowers latency from 18.4 ms to 12.1 ms "
            "with 94.2% ± 0.3% accuracy (p < 0.01) \\cite{kipf2017} [C001], "
            "though it does not generalize to OOD graphs.\n"
        )
        dropped_draft = (
            "SHNLC improves speed from 18.4 to 12.1 and reaches 95.0% accuracy (p < 0.01) "
            "across splits \\cite{kipf2017}, proving generalization to OOD graphs.\n"
        )
        # Verify contraction normalization (doesn't == does not)
        snap_orig = module.extract_claims_snapshot("It doesn't converge under IID splits.")
        snap_new = module.extract_claims_snapshot("It does not converge under IID splits.")
        self.assertEqual(snap_orig["qualifiers"], snap_new["qualifiers"])

        with tempfile.TemporaryDirectory() as tmpdir:
            orig_p = Path(tmpdir) / "orig.md"
            good_p = Path(tmpdir) / "good.md"
            bad_p = Path(tmpdir) / "bad.md"
            orig_p.write_text(baseline, encoding="utf-8")
            good_p.write_text(clean_paraphrase, encoding="utf-8")
            bad_p.write_text(dropped_draft, encoding="utf-8")

            proc_good = run_cli(str(good_p), "--compare-baseline", str(orig_p), "--strict", "--json")
            self.assertEqual(proc_good.returncode, 0, proc_good.stdout)
            data_good = json.loads(proc_good.stdout)
            self.assertTrue(data_good["claim_preservation"]["preserved"])

            proc_bad = run_cli(str(bad_p), "--compare-baseline", str(orig_p), "--strict", "--json")
            self.assertEqual(proc_bad.returncode, 1, proc_bad.stdout)
            data_bad = json.loads(proc_bad.stdout)
            cp = data_bad["claim_preservation"]
            self.assertFalse(cp["preserved"])
            self.assertIn("94.2%", cp["numbers_dropped"])
            self.assertIn("0.3%", cp["numbers_dropped"])
            self.assertIn("ms", cp["units_dropped"])
            self.assertIn("c001", cp["citations_dropped"])
            self.assertIn("only", cp["qualifiers_dropped"])
            self.assertIn("not", cp["qualifiers_dropped"])
            self.assertIn("CP_DROPPED", {f["pattern_id"] for f in data_bad["findings"]})

            # Also verify hedge->certainty escalation detection directly
            esc = module.compare_claims("The method may reduce bias.", "The method proves bias reduction.")
            self.assertFalse(esc["preserved"])
            self.assertIn("may -> proves", esc["certainty_escalations"])

    def test_eight_gram_overlap_check_flags_recycled_prose(self):
        ref_text = (
            "Normalized graph adjacency propagation aggregates neighborhood representations across "
            "discrete spectral bands while bounding variance under uniform node sampling across "
            "sparse citation benchmarks.\n"
        )
        copied_draft = (
            "In our evaluation, normalized graph adjacency propagation aggregates neighborhood "
            "representations across discrete spectral bands while bounding variance under uniform "
            "node sampling across all trials.\n"
        )
        original_draft = (
            "We measure calibration error on held-out graph splits using fixed random seeds, "
            "matched optimizer budgets, and deterministic label hashing across three public benchmarks.\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            ref_p = Path(tmpdir) / "ref.md"
            bad_p = Path(tmpdir) / "copied.md"
            good_p = Path(tmpdir) / "fresh.md"
            ref_p.write_text(ref_text, encoding="utf-8")
            bad_p.write_text(copied_draft, encoding="utf-8")
            good_p.write_text(original_draft, encoding="utf-8")

            proc_bad = run_cli(str(bad_p), "--reference", str(ref_p), "--strict", "--json")
            self.assertEqual(proc_bad.returncode, 1, proc_bad.stdout)
            data_bad = json.loads(proc_bad.stdout)
            self.assertGreaterEqual(data_bad["overlap_score"], 0.15)
            self.assertTrue(data_bad["overlap_details"]["flagged"])
            self.assertIn("OVL_8GRAM", {f["pattern_id"] for f in data_bad["findings"]})

            proc_good = run_cli(str(good_p), "--reference", str(ref_p), "--strict", "--json")
            self.assertEqual(proc_good.returncode, 0, proc_good.stdout)
            data_good = json.loads(proc_good.stdout)
            self.assertEqual(data_good["overlap_score"], 0.0)
            self.assertFalse(data_good["overlap_details"]["flagged"])

    def test_cli_error_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            empty_p = Path(tmpdir) / "empty.md"
            empty_p.write_text("   \n", encoding="utf-8")
            valid_p = Path(tmpdir) / "valid.md"
            valid_p.write_text("We evaluate three baselines on a held-out split.\n", encoding="utf-8")

            self.assertEqual(run_cli(str(Path(tmpdir) / "missing.md")).returncode, 2)
            self.assertEqual(run_cli(str(empty_p)).returncode, 2)
            self.assertEqual(run_cli(str(valid_p), "--compare-baseline", str(Path(tmpdir) / "no_orig.md")).returncode, 2)
            self.assertEqual(run_cli(str(valid_p), "--reference", str(Path(tmpdir) / "no_ref.md")).returncode, 2)

    def test_reply_mode_h26_and_additional_patterns(self):
        reply_text = (
            "Datasets contain heterogeneous label noise across domains. "
            "Models often memorize surface artifacts on small benchmarks. "
            "Standard cross-entropy calibration diverges under covariate shift. "
            "Split contamination occurs when preprocessing runs globally. "
            "Reject the submission until train-only normalization is rerun.\n"
        )
        res_reply = module.lint_text(reply_text, mode="reply")
        self.assertIn("H26", {f["pattern_id"] for f in res_reply["findings"]})

        extra_tells = (
            "## 🚀 Speed matters\n\n"
            "Speed matters for calibration. "
            "The pipeline is high-quality and the schedule is long-term. "
            "Studies show improvements without a citation here. "
            "As of my knowledge cutoff, results are mixed, “maybe” \"so\".\n"
        )
        res_extra = module.lint_text(extra_tells)
        pats = {f["pattern_id"] for f in res_extra["findings"]}
        for expected in ("H10", "H17", "H20", "H21", "H23", "H24"):
            self.assertIn(expected, pats, f"Missing {expected} in {pats}")

        # Long 22-word verbatim passage inside a larger 200-word draft should still trigger OVL_8GRAM
        ref = "Normalized graph adjacency propagation aggregates neighborhood representations across discrete spectral bands while bounding variance under uniform node sampling across benchmarks."
        filler = " ".join(f"token{i}" for i in range(180))
        long_draft = f"{filler} {ref}"
        score, details = module.compute_overlap(long_draft, [("ref.md", ref)], threshold=0.15)
        self.assertLess(score, 0.15)
        self.assertTrue(details["flagged"])

    def test_parsimony_problem_inflation_and_padding_vs_concise_prose(self):
        inflated_text = (
            "In the era of large language models, retrieval is plagued by a catastrophic bottleneck. "
            "It is worth noting that a four-stage reranker is desperately needed.\n"
        )
        res_bad = module.lint_text(inflated_text)
        pats_bad = {f["pattern_id"] for f in res_bad["findings"]}
        self.assertIn("PI01", pats_bad)
        self.assertIn("PAD01", pats_bad)

        concise_text = (
            "BM25 alone attains 0.68 nDCG on SciFact; adding a cross-encoder adds 140 ms latency "
            "for a 0.01 gain and does not justify the extra stage.\n"
        )
        res_ok = module.lint_text(concise_text)
        self.assertEqual(res_ok["risk_count"], 0)
        self.assertEqual(res_ok["warn_count"], 0)

    def test_catastrophic_forgetting_exempt_vs_extreme_dramatization_and_redundant_padding(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            td = Path(tmpdir)
            # Scoped empirical report + continual learning domain term must pass --strict
            valid_cl = td / "continual.md"
            valid_cl.write_text(
                "# Continual Learning Evaluation\n\n"
                "On Split-CIFAR100, sequential fine-tuning exhibits catastrophic forgetting after task 3 "
                "(accuracy drops from 78.2% to 31.4% across 5 seeds).\n\n"
                "Where $L_t$ denotes the task loss, elastic weight consolidation retains 69.1% accuracy.\n",
                encoding="utf-8",
            )
            proc_cl = run_cli(str(valid_cl), "--strict", "--json")
            self.assertEqual(proc_cl.returncode, 0, proc_cl.stdout + proc_cl.stderr)
            self.assertNotIn("PI01", {f["pattern_id"] for f in json.loads(proc_cl.stdout)["findings"]})

            # Extreme crisis dramatization + throat-clearing + cross-paragraph redundant restatement
            bad_p = td / "dramatic_padded.md"
            bad_p.write_text(
                "# Introduction\n\n"
                "In today's rapidly evolving AI landscape, this existential crisis renders all prior work obsolete "
                "and urgently demands a complete overhaul.\n\n"
                "Our adaptive routing mechanism reduces inference latency on long-context benchmarks without sacrificing retrieval accuracy.\n\n"
                "# Conclusion\n\n"
                "Our adaptive routing mechanism reduces inference latency on long-context benchmarks without sacrificing retrieval accuracy.\n",
                encoding="utf-8",
            )
            proc_bad = run_cli(str(bad_p), "--strict", "--json")
            self.assertEqual(proc_bad.returncode, 1, proc_bad.stdout)
            pats = {f["pattern_id"] for f in json.loads(proc_bad.stdout)["findings"]}
            self.assertIn("PI01", pats)
            self.assertIn("PAD01", pats)
            self.assertIn("PAD02", pats)

            # --compact --json bounds verbose findings while preserving --strict exit code
            many_lines = "\n".join(
                f"In the era of AI, line {i} is plagued by a catastrophic bottleneck and leverages bespoke pipelines."
                for i in range(15)
            )
            many_p = td / "many.md"
            many_p.write_text(many_lines + "\n", encoding="utf-8")
            proc_cmp = run_cli(str(many_p), "--strict", "--json", "--compact")
            self.assertEqual(proc_cmp.returncode, 1)
            cmp_data = json.loads(proc_cmp.stdout)
            self.assertTrue(cmp_data["compact"])
            self.assertLessEqual(len(cmp_data["findings"]), 10)
            self.assertGreater(cmp_data["total_findings"], 10)
            self.assertEqual(cmp_data["findings_truncated"], cmp_data["total_findings"] - len(cmp_data["findings"]))

            # Text --compact mode also bounds output and notes truncation
            proc_cmp_txt = run_cli(str(many_p), "--strict", "--compact")
            self.assertEqual(proc_cmp_txt.returncode, 1)
            self.assertIn("more finding(s) truncated", proc_cmp_txt.stdout)
            self.assertLess(len(proc_cmp_txt.stdout.encode("utf-8")), 4096)

    def test_latex_tilde_adversarial_robustness_and_markdown_math_env_masking(self):
        tex_doc = (
            "\\documentclass{article}\n"
            "\\begin{document}\n"
            "We also measure adversarial robustness under $\\ell_\\infty$ perturbations and robustness against shift.\n"
            "We compute leverage~scores using robust~statistics over the loss~landscape with an attention~gate.\n"
            "\\end{document}\n"
        )
        res_tex = module.lint_text(tex_doc, source_name="robust.tex")
        self.assertEqual(res_tex["risk_count"], 0, res_tex["findings"])
        self.assertEqual(res_tex["warn_count"], 0, res_tex["findings"])

        md_math_doc = (
            "# Formulation\n\n"
            "We evaluate two-layer networks on Cora.\n\n"
            "\\begin{equation}\n"
            "L_{leverage} = \\text{robust}(x) + \\text{pivotal}(y)\\text{---}\\text{delve}(z)\n"
            "\\end{equation}\n\n"
            "\\begin{align*}\n"
            "L_2 = \\text{tapestry}(x) + \\text{seamless}(y)\n"
            "\\end{align*}\n\n"
            "$$\n"
            "\\text{groundbreaking}(z) = 0\n"
            "$$\n\n"
            "\\[\n"
            "\\text{revolutionary}(w) = 1\n"
            "\\]\n"
        )
        with tempfile.TemporaryDirectory() as td:
            md_p = Path(td) / "math_envs.md"
            md_p.write_text(md_math_doc, encoding="utf-8")
            proc = run_cli(str(md_p), "--strict", "--json")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(json.loads(proc.stdout)["findings"], [])

        # Multi-tell H12 cluster ("delve" + "tapestry") escalates to RISK
        res_cluster = module.lint_text("We delve into the tapestry of empirical results.\n")
        self.assertGreaterEqual(res_cluster["risk_count"], 1)

    def test_comma_separated_citations_base_escalation_praise_sandwich_pad02_and_tex_overlap(self):
        # 1. [C001, C002] drop + suggest -> prove base-form escalation
        with tempfile.TemporaryDirectory() as td:
            orig_p = Path(td) / "orig.md"
            bad_p = Path(td) / "bad.md"
            orig_p.write_text("Prior results suggest a correlation [C001, C002].\n", encoding="utf-8")
            bad_p.write_text("Prior results prove a correlation.\n", encoding="utf-8")
            proc = run_cli(str(bad_p), "--compare-baseline", str(orig_p), "--strict", "--json")
            self.assertEqual(proc.returncode, 1, proc.stdout)
            cp = json.loads(proc.stdout)["claim_preservation"]
            self.assertFalse(cp["preserved"])
            self.assertEqual(cp["citations_dropped"], ["c001", "c002"])
            self.assertIn("suggest -> prove", cp["certainty_escalations"])

        # 2. Expanded same-paragraph (4-sentence) and cross-paragraph praise sandwiches
        same_para_sw = (
            "Your framing is thoughtful and thorough. We checked all baselines carefully. "
            "The setup covers three datasets. However, the test split leaks training examples.\n"
        )
        res_sp = module.lint_text(same_para_sw)
        self.assertIn("SYC_PRAISE_SANDWICH", {h["pattern_id"] for h in res_sp["sycophancy_hits"]})

        cross_para_sw = (
            "Your intuition on token pruning is great and very clear.\n\n"
            "However, the training split leaks validation labels across folds.\n"
        )
        res_cp = module.lint_text(cross_para_sw)
        self.assertIn("SYC_PRAISE_SANDWICH", {h["pattern_id"] for h in res_cp["sycophancy_hits"]})

        # 3. PAD02 near-duplicate (synonym swap, Jaccard >= 0.70 / 8-gram run)
        near_dup = (
            "Our adaptive spectral propagation preserves structural graph invariants across sparse citation benchmarks during evaluation.\n\n"
            "Our adaptive spectral propagation preserves structural graph invariance across sparse citation datasets during evaluation.\n"
        )
        res_nd = module.lint_text(near_dup)
        self.assertIn("PAD02", {f["pattern_id"] for f in res_nd["findings"]})

        # 4. Multi-line % comments stripped in _overlap_tokens for .tex inputs
        ref_txt = "Normalized graph adjacency propagation aggregates neighborhood representations across discrete spectral bands."
        tex_commented = f"% {ref_txt}\nWe evaluate distinct molecular calibration baselines.\n"
        score, details = module.compute_overlap(tex_commented, [("ref.md", ref_txt)], source_name="draft.tex")
        self.assertEqual(score, 0.0)
        self.assertFalse(details["flagged"])

    def test_markdown_inline_code_bracket_multiline_dollar_and_tex_multiline_dollar_masking(self):
        # 1. Inline code `\[` in Markdown must NOT blank subsequent prose
        md_inline = (
            "We escape display math delimiters such as `\\[` in the parser.\n"
            "This is a groundbreaking, revolutionary, and paradigm-shifting result that delves into a vibrant tapestry.\n"
        )
        res_ic = module.lint_text(md_inline, source_name="inline_code.md")
        self.assertGreaterEqual(res_ic["risk_count"], 1)
        self.assertGreaterEqual(res_ic["warn_count"], 1)

        # 2. Trailing prose after closing $$ on a multi-line Markdown math block must still be linted
        md_trailing = "$$ x = 1\n+ 2 $$ Your idea is brilliant and this is a groundbreaking, revolutionary paradigm shift.\n"
        res_tr = module.lint_text(md_trailing, source_name="trailing.md")
        self.assertGreaterEqual(res_tr["risk_count"], 1)
        self.assertIn("SYC_CHEERLEADING", {h["pattern_id"] for h in res_tr["sycophancy_hits"]})

        # 3. Multi-line $$...$$ in .tex with math on opening/closing lines must NOT emit H12 false positives
        tex_ml = (
            "\\documentclass{article}\n"
            "\\begin{document}\n"
            "$$ x_t = \\text{robust}(x_{t-1}) +\n"
            "\\text{leverage}(x_t) + \\text{holistic}(x_t) $$\n"
            "We evaluate two calibration baselines.\n"
            "\\end{document}\n"
        )
        res_tx = module.lint_text(tex_ml, source_name="ml_dollar.tex")
        self.assertEqual(res_tx["risk_count"], 0, res_tx["findings"])
        self.assertEqual(res_tx["warn_count"], 0, res_tx["findings"])

    def test_multisentence_and_adjective_praise_sandwich_mode_scoping_and_past_tense_escalation(self):
        # 1. Praise in second sentence of paragraph 1 before cross-paragraph pivot
        s2_cp = (
            "We carefully examined the submission draft.\n"
            "Your framing is thoughtful and thorough.\n\n"
            "However, the training split leaks validation labels across folds.\n"
        )
        res_s2 = module.lint_text(s2_cp)
        self.assertIn("SYC_PRAISE_SANDWICH", {h["pattern_id"] for h in res_s2["sycophancy_hits"]})

        # 2. Short adjective praise ("solid and clean") before cross-paragraph pivot
        sc_cp = (
            "The methodology is solid and clean.\n\n"
            "However, the baseline leaks validation labels across folds.\n"
        )
        res_sc = module.lint_text(sc_cp)
        self.assertIn("SYC_PRAISE_SANDWICH", {h["pattern_id"] for h in res_sc["sycophancy_hits"]})

        # 3. Neutral empirical metric + limitation passes in manuscript mode, stays strict in reply/review modes
        neutral_lim = "Our method achieves strong accuracy on CIFAR-10. However, it fails under severe Gaussian noise.\n"
        res_ms = module.lint_text(neutral_lim, mode="manuscript")
        self.assertEqual(res_ms["risk_count"], 0, res_ms["findings"])
        for strict_mode in ("reply", "review"):
            res_strict = module.lint_text(neutral_lim, mode=strict_mode)
            self.assertIn("SYC_PRAISE_SANDWICH", {h["pattern_id"] for h in res_strict["sycophancy_hits"]}, strict_mode)

        # 4. Past-tense hedge -> certainty escalation (suggested/indicated/hypothesized -> proved/confirmed/demonstrated)
        for hedge, booster in (
            ("suggested", "proved"),
            ("indicated", "confirmed"),
            ("hypothesized", "demonstrated"),
        ):
            esc = module.compare_claims(
                f"Experiments {hedge} a correlation [C001].",
                f"Experiments {booster} a correlation [C001].",
            )
            self.assertFalse(esc["preserved"])
            self.assertIn(f"{hedge} -> {booster}", esc["certainty_escalations"])

    def test_iteration4_sycophancy_user_address_flaw_classification_and_p2_pivots(self):
        positives = [
            # 6h: second-person praise with empirical metric qualifier in manuscript mode
            "Your strong empirical results on CIFAR-10 show clear gains.\n\nHowever, the training split leaks validation labels.",
            # 6i: second-person praise with clean dataset qualifier in manuscript mode
            "Your clean dataset and high accuracy are notable.\n\nHowever, the evaluation leaks test labels.",
            # 6j: remediated/prior-work flaw in P1 does not suppress praise sandwich
            "Your framing is thoughtful and thorough, fixing a flaw in prior work.\n\nHowever, your own split leaks validation labels.",
            "By addressing an error in existing methods, your framing is thoughtful.\n\nHowever, your split leaks labels.",
            "Your framing is thoughtful. It fixes a flaw in prior work.\n\nHowever, your split leaks labels.",
            # 6k: P2 2nd sentence pivot with genuine flaw + nonetheless / even so
            "The methodology is solid and clean.\n\nWe first review the hyperparameters. However, the baseline leaks validation labels.",
            "The methodology is solid and clean.\n\nWe first review the hyperparameters. Nonetheless, the baseline leaks validation labels.",
            "The methodology is solid and clean.\n\nWe first review the hyperparameters. Even so, the baseline leaks validation labels.",
            # 6l: prepositional concessive pivot with praise back-reference / flaw
            "The methodology is solid and clean.\n\nDespite these merits, the baseline leaks validation labels.",
            "The methodology is solid and clean.\n\nNotwithstanding these strengths, the baseline leaks validation labels.",
        ]
        for txt in positives:
            res = module.lint_text(txt, mode="manuscript")
            syc_ids = {h["pattern_id"] for h in res["sycophancy_hits"]}
            self.assertIn("SYC_PRAISE_SANDWICH", syc_ids, (txt, res))

        # Negative controls: must pass clean in mode="manuscript"
        negatives = [
            "Our method achieves strong accuracy on CIFAR-10. However, it fails under severe Gaussian noise.\n",
            "Your paper fails to beat prior work on ImageNet. The writing is clear.\n\nHowever, the experiments are incomplete.\n",
            "Your framing is clear. It fixes a flaw in prior work.\n",
            "Our model uses a clear two-stage architecture.\n\nDespite using only two layers, the encoder generalizes across 12 datasets without extra tuning.\n",
            "Our model uses a clear residual block.\n\nWe train with AdamW for 50 epochs. Nonetheless, batch size varies across datasets.\n",
        ]
        for txt in negatives:
            res = module.lint_text(txt, mode="manuscript")
            self.assertNotIn("SYC_PRAISE_SANDWICH", {h["pattern_id"] for h in res["sycophancy_hits"]}, (txt, res))

    def test_iteration4_tex_same_line_verbatim_verb_and_commonmark_nested_backticks(self):
        # 5G: same-line verbatim / lstlisting / minted / trailing prose / % inside verbatim
        tex_cases = [
            "\\documentclass{article}\n\\begin{document}\n\\begin{verbatim} \\[ \\end{verbatim}\nThis groundbreaking tapestry delves deep.\n\\end{document}\n",
            "\\documentclass{article}\n\\begin{document}\n\\begin{lstlisting} \\[ \\end{lstlisting}\nThis groundbreaking tapestry delves deep.\n\\end{document}\n",
            "\\documentclass{article}\n\\begin{document}\n\\begin{minted}{tex} \\[ \\end{minted}\nThis groundbreaking tapestry delves deep.\n\\end{document}\n",
            "\\documentclass{article}\n\\begin{document}\nUse \\begin{verbatim}\\[\\end{verbatim} here. This groundbreaking tapestry delves deep.\n\\end{document}\n",
            "\\documentclass{article}\n\\begin{document}\n\\begin{verbatim} 50% \\[ \\end{verbatim}\nThis groundbreaking tapestry delves deep.\n\\end{document}\n",
            # Multi-line verbatim containing unclosed \begin{equation} and % must not corrupt env_stack
            "\\documentclass{article}\n\\begin{document}\n\\begin{verbatim}\n\\begin{equation}\n\\[ %\n\\end{verbatim}\nThis groundbreaking tapestry delves deep.\n\\end{document}\n",
            # 5H: inline \verb|\[| and \verb*|% \[| plus non-verb macro \verbose
            "\\documentclass{article}\n\\begin{document}\nUse \\verb|\\[| and \\verb*|% \\[| for display math (not \\verbose).\nThis groundbreaking tapestry delves deep.\n\\end{document}\n",
        ]
        for tex_src in tex_cases:
            res = module.lint_text(tex_src, source_name="edge.tex")
            pats = {f["pattern_id"] for f in res["findings"]}
            self.assertIn("H12", pats, (tex_src, pats))
            self.assertIn("H16", pats, (tex_src, pats))
            self.assertIn("SYC_CHEERLEADING", pats, (tex_src, pats))

        # Standalone verbatim with no outer prose must still raise 0-prose ValueError
        with self.assertRaises(ValueError):
            module.lint_text("\\begin{document}\n\\begin{verbatim} \\[ \\end{verbatim}\n\\end{document}\n", source_name="only_verb.tex")

        # 5C: CommonMark multi-backtick inline code spans containing inner backticks & \[
        md_nested = (
            "We escape `` `\\[` `` and ``` ``\\[`` ``` in the parser.\n\n"
            "This groundbreaking, revolutionary paradigm shift delves into a vibrant tapestry.\n"
        )
        res_md = module.lint_text(md_nested, source_name="nested_backticks.md")
        pats_md = {f["pattern_id"] for f in res_md["findings"]}
        self.assertIn("H12", pats_md)
        self.assertIn("H16", pats_md)
        self.assertIn("SYC_CHEERLEADING", pats_md)

        # Escaped opening backtick is NOT an inline code opener; literal backslash inside `\` IS closed
        self.assertEqual(module._mask_inline_code_spans(r"\`foo`", " [code] "), r"\`foo`")
        self.assertEqual(module._mask_inline_code_spans(r"`\`", " [code] "), " [code] ")

        # Pathological 5,000-backtick line finishes cleanly in linear time
        import time
        t0 = time.monotonic()
        pathological = " ".join("`" * ((i % 7) + 1) for i in range(1500))
        masked_patho = module._mask_inline_code_spans(pathological, " [code] ")
        self.assertLess(time.monotonic() - t0, 1.0)
        self.assertIn("[code]", masked_patho)

    def test_iteration5_concessive_clean_prose_you_s1_abbrev_and_tex_close_edges(self):
        # 1. Defect 1 (ADV_B1a-d): benign concessive transitions in P2 sentence 1 (and 1-para) with zero flaws pass clean
        benign_concessives = [
            "The attention mechanism provides a clean formulation of token routing.\n\nEven so, sequence length scales quadratically with context size.",
            "Our model uses a clear two-stage architecture.\n\nNonetheless, runtime grows quadratically with sequence length.",
            "Our model uses a clear two-stage architecture.\n\nHowever, runtime grows quadratically with sequence length.",
            "The derivation is clear and concise.\n\nNevertheless, memory consumption scales with batch size.",
            "The derivation is clear and concise. Even so, memory consumption scales with batch size.",
        ]
        for txt in benign_concessives:
            res = module.lint_text(txt, mode="manuscript")
            self.assertEqual(res["sycophancy_hits"], [], (txt, res))

        # Positive control: P2 opens with concessive transition and sentence 2 contains a genuine flaw
        p2_later_flaw = (
            "Our model uses a clear two-stage architecture.\n\n"
            "However, we evaluate runtime first. The baseline leaks validation labels."
        )
        self.assertIn(
            "SYC_PRAISE_SANDWICH",
            {h["pattern_id"] for h in module.lint_text(p2_later_flaw, mode="manuscript")["sycophancy_hits"]},
        )

        # 2. Defect 3 (ADV_B2, ADV_B3): "You" in S1 + empirical praise in S2, and P2 abbreviation before pivot
        adv_b2 = (
            "You propose a retriever.\n"
            "The strong empirical results on CIFAR-10 stand out.\n\n"
            "However, the split leaks validation labels."
        )
        self.assertIn(
            "SYC_PRAISE_SANDWICH",
            {h["pattern_id"] for h in module.lint_text(adv_b2, mode="manuscript")["sycophancy_hits"]},
        )

        adv_b3 = (
            "The methodology is solid and clean.\n\n"
            "We evaluate on Fig. 1 and CIFAR-10. However, the baseline leaks validation labels."
        )
        self.assertIn(
            "SYC_PRAISE_SANDWICH",
            {h["pattern_id"] for h in module.lint_text(adv_b3, mode="manuscript")["sycophancy_hits"]},
        )

        adv_b3_clean = (
            "The methodology is solid and clean.\n\n"
            "We evaluate on Fig. 1 and Eq. 2. Nonetheless, batch size varies across datasets."
        )
        self.assertEqual(module.lint_text(adv_b3_clean, mode="manuscript")["sycophancy_hits"], [])

        # 3. Defect 4a + Reviewer 2 minor: trailing prose on \end{equation} and mid-line math close before \verb|\[|
        tex_edges = [
            "\\begin{document}\n\\begin{equation}\nx = 1\n\\end{equation} This groundbreaking tapestry delves deep.\n\\end{document}\n",
            "\\begin{document}\n$$ x = 1\n+ 2 $$ We use \\verb|\\[| here.\nThis groundbreaking tapestry delves deep.\n\\end{document}\n",
            "\\begin{document}\n\\[\nx = 1\n+ 2 \\] We use \\begin{verbatim}\\[\\end{verbatim} here.\nThis groundbreaking tapestry delves deep.\n\\end{document}\n",
        ]
        for tex_src in tex_edges:
            res_tex = module.lint_text(tex_src, source_name="close_edge.tex")
            pats = {f["pattern_id"] for f in res_tex["findings"]}
            self.assertIn("H12", pats, (tex_src, pats))
            self.assertIn("H16", pats, (tex_src, pats))
            self.assertIn("SYC_CHEERLEADING", pats, (tex_src, pats))

        clean_midline = (
            "\\begin{document}\n$$ x = 1\n+ 2 $$ We use \\verb|\\[| here.\n"
            "We evaluate two baselines on CIFAR-10.\n\\end{document}\n"
        )
        res_clean_mid = module.lint_text(clean_midline, source_name="clean_midline.tex")
        self.assertEqual(res_clean_mid["risk_count"], 0, res_clean_mid["findings"])
        self.assertEqual(res_clean_mid["warn_count"], 0, res_clean_mid["findings"])

    def test_iteration6_ref_and_app_abbreviations_preserve_sentence_boundary(self):
        for txt in (
            "The methodology is solid and clean.\n\nWe follow Ref. [1] on CIFAR-10. However, the baseline leaks validation labels.",
            "The methodology is solid and clean.\n\nWe prove this in App. A on CIFAR-10. However, the baseline leaks validation labels.",
        ):
            res = module.lint_text(txt, mode="manuscript")
            self.assertIn(
                "SYC_PRAISE_SANDWICH",
                {h["pattern_id"] for h in res["sycophancy_hits"]},
                (txt, res),
            )

        clean_txt = (
            "The methodology is solid and clean.\n\n"
            "We follow Ref. [1] and App. A on CIFAR-10. Nonetheless, batch size varies across datasets."
        )
        self.assertEqual(module.lint_text(clean_txt, mode="manuscript")["sycophancy_hits"], [])

    def test_iteration8_inline_math_redos_linear_time_and_escaped_math_preserved(self):
        import time

        for src_name, txt in (
            ("redos_dollar.md", "The cost is $a " + ("\\" * 40) + " end\n\nClean prose here.\n"),
            ("redos_dollar_100.md", "The cost is $a " + ("\\" * 100) + " end\n\nClean prose here.\n"),
            ("redos_paren.tex", "Math \\(a " + ("\\" * 40) + " end\n\nNormal prose achieving 0.71 score.\n"),
            ("redos_paren_100.tex", "Math \\(a " + ("\\" * 100) + " end\n\nNormal prose achieving 0.71 score.\n"),
        ):
            t0 = time.monotonic()
            res = module.lint_text(txt, source_name=src_name)
            elapsed = time.monotonic() - t0
            self.assertLess(elapsed, 0.1, f"{src_name} took {elapsed:.4f}s")
            self.assertGreater(res["stats"]["words"], 0)

        # Valid escaped inline math ($...$ and \(...\)) masks cleanly without false positives
        valid_math = (
            "We spend $\\$5$ on compute and bound error as \\( \\mathcal{O}(n \\log n) \\) across splits.\n"
        )
        res_valid = module.lint_text(valid_math, source_name="valid_math.tex")
        self.assertEqual(res_valid["risk_count"], 0, res_valid["findings"])
        self.assertEqual(res_valid["warn_count"], 0, res_valid["findings"])

    def test_iteration9_cross_format_compare_baseline_md_and_tex(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            td = Path(tmpdir)
            orig_md = td / "orig.md"
            draft_tex = td / "draft.tex"
            dropped_tex = td / "dropped.tex"
            orig_md.write_text("81.4% ± 0.3% recall in 10 seconds.\n", encoding="utf-8")
            draft_tex.write_text(
                "\\documentclass{article}\n\\begin{document}\n"
                "81.4\\% \\pm 0.3\\% recall in 10 s.\n"
                "\\end{document}\n",
                encoding="utf-8",
            )
            dropped_tex.write_text(
                "\\documentclass{article}\n\\begin{document}\n"
                "81.4\\% recall in 10 s.\n"
                "\\end{document}\n",
                encoding="utf-8",
            )

            proc_ok = run_cli(str(draft_tex), "--compare-baseline", str(orig_md), "--strict", "--json")
            self.assertEqual(proc_ok.returncode, 0, proc_ok.stdout + proc_ok.stderr)
            cp_ok = json.loads(proc_ok.stdout)["claim_preservation"]
            self.assertTrue(cp_ok["preserved"], cp_ok)
            self.assertEqual(cp_ok["numbers_dropped"], [])

            proc_drop = run_cli(str(dropped_tex), "--compare-baseline", str(orig_md), "--strict", "--json")
            self.assertEqual(proc_drop.returncode, 1, proc_drop.stdout + proc_drop.stderr)
            cp_drop = json.loads(proc_drop.stdout)["claim_preservation"]
            self.assertFalse(cp_drop["preserved"])
            self.assertIn("0.3%", cp_drop["numbers_dropped"])

            # Direct compare_claims backward compatibility (single is_tex=True)
            cp_direct = module.compare_claims("14.2\\% gain", "14.2\\% gain", is_tex=True)
            self.assertTrue(cp_direct["preserved"])

    def test_iteration12_tex_short_titles_h24_redos_and_empty_nan_cli_validation(self):
        import time

        # 1. LaTeX optional [Short] titles, nested brackets, multiline short titles, \texorpdfstring, and _is_tex
        tex_h24_cases = [
            "\\begin{document}\n\\section[Short]{Overview}\n\nOverview.\n\nWe evaluate BM25 on BEIR.\n\\end{document}\n",
            "\\begin{document}\n\\section[Overview of \\cite[p.~1]{a}]{Overview}\n\nOverview.\n\nWe evaluate BM25 on BEIR.\n\\end{document}\n",
            "\\begin{document}\n\\section[\n  Short Title\n]{Overview}\n\nOverview.\n\nWe evaluate BM25 on BEIR.\n\\end{document}\n",
            "\\begin{document}\n\\section[Short]{\\texorpdfstring{Overview}{Short}}\n\nOverview.\n\nWe evaluate BM25 on BEIR.\n\\end{document}\n",
        ]
        for tex in tex_h24_cases:
            res = module.lint_text(tex, source_name="paper.tex")
            self.assertIn("H24", {f["pattern_id"] for f in res["findings"]}, (tex, res))
        self.assertTrue(
            module._is_tex(None, "\\section[Short]{Adaptive Precision}\n\nAdaptive precision achieves 0.71 on BEIR.")
        )

        # 2. Uncertainty pair extraction preserved without None formatting errors
        snap_pct = module.extract_claims_snapshot("Accuracy is 94.2% ± 0.3% and F1 is 81.4 +/- 0.3.")
        self.assertEqual(snap_pct["numbers"]["94.2%"], 1)
        self.assertEqual(snap_pct["numbers"]["0.3%"], 1)
        self.assertEqual(snap_pct["numbers"]["81.4"], 1)
        self.assertEqual(snap_pct["numbers"]["0.3"], 1)

        # 3. Linear-time ReDoS checks (< 0.02s) on extract_claims_snapshot & lint_text
        for s in ("100" + " " * 5000 + "x", ("1" + " " * 500 + "x ") * 50):
            t0 = time.perf_counter()
            module.extract_claims_snapshot(s)
            self.assertLess(time.perf_counter() - t0, 0.02)
        for s, lint_budget in (("\\section" + " " * 10000 + "X", 0.02), ("\\section[" + "[a" * 2500, 0.1)):
            t0 = time.perf_counter()
            module.mask_prose(s + "\n\nClean prose here.", source_path="stress.tex")
            self.assertLess(time.perf_counter() - t0, 0.02)
            t1 = time.perf_counter()
            module.lint_text(s + "\n\nClean prose here.", source_name="stress.tex")
            self.assertLess(time.perf_counter() - t1, lint_budget)

        # 4. Empty/whitespace CLI paths & invalid --overlap-threshold exit 2 + Python ValueError
        with tempfile.TemporaryDirectory() as tmpdir:
            td = Path(tmpdir)
            clean_md = td / "clean.md"
            ref_md = td / "ref.md"
            clean_md.write_text("Two-layer propagation yields 0.71 score across benchmarks.\n", encoding="utf-8")
            ref_md.write_text("Completely disjoint background text about optimization algorithms.\n", encoding="utf-8")

            for bad_args in (
                [""],
                ["   "],
                ["", "--json"],
                [str(clean_md), "--compare-baseline", ""],
                [str(clean_md), "--compare-baseline", "   ", "--json"],
                [str(clean_md), "--reference", ""],
                [str(clean_md), "--reference", "   ", "--json"],
                [str(clean_md), "--overlap-threshold", "nan"],
                [str(clean_md), "--overlap-threshold", "inf", "--json"],
                [str(clean_md), "--overlap-threshold", "-inf"],
                [str(clean_md), "--overlap-threshold", "-0.1"],
                [str(clean_md), "--overlap-threshold", "1.5"],
            ):
                proc = run_cli(*bad_args)
                self.assertEqual(proc.returncode, 2, (bad_args, proc.stdout, proc.stderr))
                if "--json" in bad_args:
                    self.assertIn("error", json.loads(proc.stderr), (bad_args, proc.stderr))

            for ok_args in (
                [str(clean_md), "--reference", str(ref_md), "--overlap-threshold", "0.01", "--strict"],
                [str(clean_md), "--reference", str(ref_md), "--overlap-threshold", "1.0", "--strict"],
                [str(clean_md), "--overlap-threshold", "0.0", "--strict"],
            ):
                proc_ok = run_cli(*ok_args)
                self.assertEqual(proc_ok.returncode, 0, (ok_args, proc_ok.stdout, proc_ok.stderr))

        for bad_t in (float("nan"), float("inf"), float("-inf"), -0.1, 1.5, True):
            with self.assertRaises(ValueError):
                module.lint_text("Clean prose sentence.", overlap_threshold=bad_t)
            with self.assertRaises(ValueError):
                module.compute_overlap("Clean prose sentence.", [("r", "Other prose.")], threshold=bad_t)

    def test_redos_unclosed_latex_delimiters_and_newline_runs_linear_time(self):
        import time

        # Warm up any lazy patterns
        module.lint_text("We evaluate BM25 on BEIR.\n", source_name="warm.tex")
        module.extract_claims_snapshot("We evaluate BM25 on BEIR.\n", is_tex=True)

        regex_probes = [
            (module._TEX_CMD_BARE_RE.sub, (" ", "\\section[" * 5000)),
            (module._CITE_RE.sub, (" ", "\\cite[" * 5000)),
            (module._CITE_RE.sub, (" ", "\\cite{" * 5000)),
            (module._TEX_CMD_WRAPPER_RE.sub, (" ", "\\textbf{" * 5000)),
            (module._DISPLAY_MATH_INLINE_RE.sub, (" ", "\\[a" * 5000)),
            (module._DISPLAY_MATH_INLINE_RE.sub, (" ", "$$a" * 5000)),
            (module._INLINE_MATH_RE.sub, (" ", "\\(a" * 5000)),
            (module._BEGIN_ENV_RE.findall, ("\\begin{" * 5000,)),
            (module._END_ENV_RE.findall, ("\\end{" * 5000,)),
            (module._URL_CMD_RE.sub, (" ", "\\url{" * 5000)),
            (module._MD_LINK_URL_RE.sub, (" ", "](" * 5000)),
        ]
        for fn, args in regex_probes:
            t0 = time.perf_counter()
            fn(*args)
            self.assertLess(time.perf_counter() - t0, 0.02, args[0][:30] if args else "")

        for opener in (
            "\\section[" * 5000,
            "\\cite[" * 5000,
            "\\textbf{" * 5000,
            "\\[a" * 5000,
            "$$a" * 5000,
            r"\[a\]a" * 5000,
        ):
            t0 = time.perf_counter()
            module.mask_prose(opener + "\nWe evaluate BM25 on BEIR.\n", source_path="stress.tex")
            self.assertLess(time.perf_counter() - t0, 0.02, opener[:20])

        # Verify O(N) linear scaling on hl.lint_text for $$a*n and \[a\]a*n (would be ~16x if O(N^2))
        for tok in ("$$a", r"\[a\]a"):
            t0 = time.perf_counter()
            module.lint_text(tok * 1000 + "\nWe evaluate BM25 on BEIR.\n", source_name="test.tex")
            t_1k = time.perf_counter() - t0
            t1 = time.perf_counter()
            module.lint_text(tok * 8000 + "\nWe evaluate BM25 on BEIR.\n", source_name="test.tex")
            t_8k = time.perf_counter() - t1
            self.assertLess(t_8k, 0.5, (tok, t_8k))
            self.assertLess(t_8k / max(t_1k, 1e-4), 14.0, (tok, t_1k, t_8k))

        for claim_probe in (
            "\n" * 5000 + "We evaluate BM25 on BEIR.\n",
            "\\cite[" * 5000 + "\nWe evaluate BM25 on BEIR.\n",
            "\\cite{" * 5000 + "\nWe evaluate BM25 on BEIR.\n",
        ):
            t0 = time.perf_counter()
            snap = module.extract_claims_snapshot(claim_probe, is_tex=True)
            self.assertLess(time.perf_counter() - t0, 0.02, claim_probe[:20])
            self.assertEqual(snap["numbers"], {})

        # Functional equivalence on legitimate LaTeX citations, math brackets/parens, and list numbering
        tex_sample = r"We cite \cite[see][p.~1]{smith2020,lee2021}, compute \[ x \in [0, 1] \], and test \( f(x) = \alpha \)."
        masked = module.mask_prose(tex_sample, source_path="eq.tex")
        joined = " ".join(masked["masked_lines"])
        self.assertIn("[ref]", joined)
        self.assertIn("[math]", joined)
        self.assertNotIn("smith2020", joined)
        snap_tex = module.extract_claims_snapshot(
            "1. First item reports 2.5 ms latency \\cite[see][p.~1]{smith2020,lee2021}.\n",
            is_tex=True,
        )
        self.assertEqual(snap_tex["citations"], {"smith2020", "lee2021"})
        self.assertEqual(snap_tex["numbers"], {"2.5": 1})

        # Display-math line masking preserves outer prose and drops pure math/whitespace lines
        self.assertEqual(module._mask_display_math_line("$$a$$ b $$c$$", False, False), (" b ", False, False))
        self.assertEqual(module._mask_display_math_line("$$a$$   $$b$$", False, False), ("", False, False))
        self.assertEqual(module._mask_display_math_line("x $$a$$ y", False, False), ("x  [math]  y", False, False))
        self.assertEqual(module._mask_display_math_line(r"\[a\] b \[c\]", False, False), (" b ", False, False))

    def test_oversized_unclosed_heading_skips_accumulation_and_multiline_heading_preserved(self):
        import time

        module.mask_prose("We evaluate BM25 on BEIR.\n", source_path="warm.tex")
        for probe in (
            "\\section[" * 5000 + "\nline" * 25,
            "\\section[Short\n" + "\\section[" * 5000 + "\nline" * 25,
        ):
            t0 = time.perf_counter()
            masked = module.mask_prose(probe, source_path="oversized.tex")
            elapsed = time.perf_counter() - t0
            self.assertLess(elapsed, 0.02, f"elapsed={elapsed:.4f}s")
            self.assertEqual(len(masked["masked_lines"]), 27 if probe.startswith("\\section[Short") else 26)

        multiline_tex = "\\section[Short\nTitle]{Full\nTitle}\nWe evaluate BM25 on BEIR.\n"
        masked_ok = module.mask_prose(multiline_tex, source_path="heading.tex")
        self.assertEqual(masked_ok["headings"], [(3, "Full Title")])
        self.assertIn("Full Title", " ".join(masked_ok["masked_lines"]))


if __name__ == "__main__":
    unittest.main()
