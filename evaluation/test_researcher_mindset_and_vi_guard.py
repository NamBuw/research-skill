"""Regression tests for Q1/A* researcher mindset docs, EN+VI overclaim linting, and RQ checks."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "research-scientist" / "scripts"
MINDSET_DOC = REPO_ROOT / "research-scientist" / "references" / "researcher-mindset-and-epistemic-calibration.md"
EXAMPLE_CARD = REPO_ROOT / "research-scientist" / "references" / "question-card.schema-example.json"


def _load_mod(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class TestResearcherMindsetAndViGuard(unittest.TestCase):
    def test_mindset_doc_exists_and_is_linked_across_suite(self) -> None:
        self.assertTrue(MINDSET_DOC.is_file(), f"Missing {MINDSET_DOC}")
        mindset_text = MINDSET_DOC.read_text(encoding="utf-8")
        for token in (
            "L0",
            "L4",
            "Verified Facts & Receipts",
            "Strongest Confounders & Reviewer #2 Kill-Shots",
            "Instrument Blindness",
            "Loss-Function Fetishism",
            "Acronym Soup",
            "Echo-Chamber Baselines",
            "hidden_tradeoff_paradox",
        ):
            self.assertIn(token, mindset_text)

        linked_files = (
            REPO_ROOT / "research-scientist" / "SKILL.md",
            REPO_ROOT / "research-scientist" / "references" / "integrity-and-quality.md",
            REPO_ROOT / "research-gap-rq-audit" / "references" / "gap-rq-parsimony-protocol.md",
            REPO_ROOT / "research-experiment-coding" / "references" / "experiment-coding-debugging.md",
            REPO_ROOT / "templates" / "session-lock" / "AGENTS.md",
        )
        for path in linked_files:
            content = path.read_text(encoding="utf-8")
            self.assertIn(
                "researcher-mindset-and-epistemic-calibration.md",
                content,
                f"Missing researcher-mindset reference link in {path}",
            )

    def test_humanizer_lint_catches_vi_flattery_hype_and_overclaims(self) -> None:
        bad_vi_reply = (
            "Ý tưởng tuyệt vời, bạn hoàn toàn đúng!\n\n"
            "Đây là một phát hiện đột phá ngay lúc này.\n\n"
            "Đây là bài học triệu đô và dòng huyết thống quý tộc.\n\n"
            "Kết quả đối nghịch tuyệt đẹp chứng minh mô hình giải quyết triệt để vấn đề.\n\n"
            "Phương pháp hoàn toàn sạch bóng biến nhiễu và khóa chặt mọi đường bắt bẻ nên không một reviewer nào bắt bẻ được.\n"
        )
        clean_vi_reply = (
            "### Verified Facts & Receipts\n"
            "- Trên tập kiểm thử NXB v3 (n = 982), cấu hình maskdec đạt 35.64 chrF++ (seed 42).\n\n"
            "### Unverified / Post-Hoc Hypotheses\n"
            "- Giả thuyết rằng decoder LoRA hấp thụ văn phong Kinh Thánh hiện mới dừng ở mức exploratory (L1).\n\n"
            "### Strongest Confounders & Reviewer #2 Kill-Shots\n"
            "- Chưa loại trừ biến nhiễu từ chuẩn hóa chính tả ở encoder và thiếu đối chứng LLM đa ngữ ngang ngân sách.\n\n"
            "### Cheapest Disconfirming Test\n"
            "- Đo ALTI+ source contribution trên 84 câu bị lệch nghĩa trước và sau maskdec (chỉ 1 lượt inference).\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_p = Path(tmpdir) / "bad_vi.md"
            clean_p = Path(tmpdir) / "clean_vi.md"
            bad_p.write_text(bad_vi_reply, encoding="utf-8")
            clean_p.write_text(clean_vi_reply, encoding="utf-8")

            p_bad = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "humanizer_lint.py"), str(bad_p), "--mode", "reply", "--strict", "--json"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(p_bad.returncode, 1, p_bad.stdout + p_bad.stderr)
            d_bad = json.loads(p_bad.stdout)
            syc_ids = {h["pattern_id"] for h in d_bad["sycophancy_hits"]}
            self.assertIn("SYC_FLATTERY", syc_ids)
            self.assertIn("SYC_CHEERLEADING", syc_ids)
            self.assertGreaterEqual(len(d_bad["sycophancy_hits"]), 5)

            p_clean = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "humanizer_lint.py"), str(clean_p), "--mode", "reply", "--strict", "--json"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(p_clean.returncode, 0, p_clean.stdout + p_clean.stderr)
            d_clean = json.loads(p_clean.stdout)
            self.assertEqual(d_clean["sycophancy_hits"], [])
            self.assertEqual(d_clean["risk_count"], 0)

    def test_question_card_checks_collision_pattern_and_overclaim_warnings(self) -> None:
        qmod = _load_mod("check_question_card", SCRIPTS_DIR / "check_question_card.py")
        base = json.loads(EXAMPLE_CARD.read_text(encoding="utf-8"))

        # Valid optional collision_pattern passes cleanly
        good = {
            **base,
            "collision_pattern": "confounder_disentanglement",
            "internal_observable": "ALTI+ source contribution ratio across decoder layers",
            "predicted_failure_boundary": "Degrades on unseen target languages when tau_dec is zeroed",
        }
        res_good = qmod.check(good)
        self.assertTrue(res_good["valid_structure"], res_good)
        self.assertEqual(res_good["warnings"], [])

        # Invalid collision_pattern errors
        bad_pat = {**base, "collision_pattern": "nonexistent_pattern"}
        res_bad_pat = qmod.check(bad_pat)
        self.assertFalse(res_bad_pat["valid_structure"])
        self.assertIn("invalid_collision_pattern:nonexistent_pattern", res_bad_pat["errors"])

        # Descriptive score-chasing & overclaim language warn without breaking legacy schema
        warn_card = {
            **base,
            "question": "How much does our pipeline improve chrF++ when nobody has applied it to X?",
            "expected_if_focal": "Our intervention completely solves the bottleneck and is 100% free of confounders.",
            "internal_observable": "TBD",
        }
        res_warn = qmod.check(warn_card)
        self.assertTrue(res_warn["valid_structure"])
        self.assertIn("descriptive_or_non_falsifiable_question", res_warn["warnings"])
        self.assertIn("overclaim_language_in_rq_card", res_warn["warnings"])
        self.assertIn("weak_or_blank_internal_observable", res_warn["warnings"])


if __name__ == "__main__":
    unittest.main()
