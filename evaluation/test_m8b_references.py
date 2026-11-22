"""Tests for Milestone M8B: Expanded Layer-3 sub-skill references & SKILL.md frugality."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PARENT_DIR = REPO_ROOT / "research-scientist"
CLAIM_AUDIT_PATH = PARENT_DIR / "scripts" / "claim_audit.py"

_SPEC = importlib.util.spec_from_file_location("claim_audit", CLAIM_AUDIT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
claim_audit = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(claim_audit)

ALL_SKILLS = (
    "research-scientist",
    "research-precedent-corpus",
    "research-gap-rq-audit",
    "research-experiment-coding",
    "research-novelty-venue",
    "research-paper-writing",
    "research-user-report",
)

SUB_REF_FILES = {
    "research-experiment-coding": REPO_ROOT / "research-experiment-coding" / "references" / "experiment-coding-debugging.md",
    "research-novelty-venue": REPO_ROOT / "research-novelty-venue" / "references" / "novelty-venue-rebuttal-protocol.md",
    "research-paper-writing": REPO_ROOT / "research-paper-writing" / "references" / "paper-writing-preflight-guide.md",
    "research-gap-rq-audit": REPO_ROOT / "research-gap-rq-audit" / "references" / "gap-rq-parsimony-protocol.md",
    "research-precedent-corpus": REPO_ROOT / "research-precedent-corpus" / "references" / "corpus-retrieval-protocol.md",
    "research-user-report": REPO_ROOT / "research-user-report" / "references" / "user-report-pdf-guide.md",
}

MD_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)#\s]+)(?:#[^)\s]*)?\)")
SINGLE_DOTDOT_RS_RE = re.compile(r"(?<!\.\./)\.\./research-scientist/")


class TestM8BReferences(unittest.TestCase):
    def test_all_7_skills_stay_under_50_lines_and_900_est_tokens(self) -> None:
        for skill in ALL_SKILLS:
            skill_md = REPO_ROOT / skill / "SKILL.md"
            self.assertTrue(skill_md.is_file(), f"Missing {skill_md}")
            fp = claim_audit._measure_skill_footprint(skill_md.read_text(encoding="utf-8"))
            self.assertLess(fp["lines"], 50, f"{skill}/SKILL.md has {fp['lines']} lines (must be < 50)")
            self.assertLess(fp["est_tokens"], 900, f"{skill}/SKILL.md has {fp['est_tokens']} est_tokens (must be < 900)")
            self.assertLess(fp["frontmatter_est_tokens"], 140, f"{skill}/SKILL.md frontmatter tokens too high")

    def test_all_6_references_have_substantial_depth_and_clean_links(self) -> None:
        for skill, ref_path in SUB_REF_FILES.items():
            self.assertTrue(ref_path.is_file(), f"Missing reference manual: {ref_path}")
            text = ref_path.read_text(encoding="utf-8")
            lines = text.splitlines()
            self.assertGreaterEqual(len(lines), 75, f"{ref_path} too short ({len(lines)} lines)")
            self.assertGreaterEqual(len(text.encode("utf-8")), 5000, f"{ref_path} too thin ({len(text)} bytes)")

            self.assertIsNone(
                SINGLE_DOTDOT_RS_RE.search(text),
                f"{ref_path} contains forbidden single-dot-dot ../research-scientist/ path; must use ../../research-scientist/",
            )

            for match in MD_LINK_RE.finditer(text):
                target = match.group(1)
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                resolved = (ref_path.parent / target).resolve()
                self.assertTrue(
                    resolved.exists(),
                    f"Broken relative markdown link in {skill}/{ref_path.name}: {target} -> {resolved}",
                )

    def test_experiment_coding_manual_coverage(self) -> None:
        text = SUB_REF_FILES["research-experiment-coding"].read_text(encoding="utf-8")
        required = (
            "Phase 1", "Phase 2", "Phase 3", "Phase 4",
            "Red-Green TDD", "find-polluter",
            "GradScaler", "DistributedSampler.set_epoch", "weights_only=True", "torch.cuda.synchronize()",
            "../../research-scientist/scripts/check_engineering_diagnostics.py",
            "../../research-scientist/scripts/audit_alignment.py",
            "../../research-scientist/scripts/check_experiment_rigor.py",
            "../../research-scientist/scripts/check_experiment_manifest.py",
            "_PREPROC_CLASSES", "_TUNER_CLASSES",
            "pytorch_missing_eval_or_no_grad",
            "pytorch_eval_without_no_grad",
            "pytorch_no_grad_without_eval",
            "repro", "utf-8-sig", "rliable", "iqm_ci95", "optimality_gap", "P(X > Y)", "contamination",
            "--verify-files", "--claims", "--audit-repo", "--blind", "--strict-repo",
            "preprocessing_before_split_leakage", "hpo_budget_asymmetry",
        )
        for token in required:
            self.assertIn(token, text, f"Missing '{token}' in experiment-coding-debugging.md")

    def test_novelty_venue_manual_coverage_all_h1_to_h17(self) -> None:
        text = SUB_REF_FILES["research-novelty-venue"].read_text(encoding="utf-8")
        for idx in range(1, 18):
            self.assertIn(f"`H{idx}`", text, f"Missing firewall rule H{idx} in novelty-venue-rebuttal-protocol.md")
        required = (
            "M1–M5", "T1–T2", "R1–R5", "G1–G4",
            "R1.1", "AC.1", "MR.1",
            "../../research-scientist/scripts/check_rebuttal.py",
            "budget", "coverage", "--strict",
            "sycophancy_warnings", "unverified_experiment_claims", "_REV_QUOTE_PREFIX_RE",
            "../../research-scientist/scripts/venue_panel_collector.py",
            "../../research-scientist/scripts/compare_scorecards.py",
            "../../research-scientist/scripts/compare_venue_novelty.py",
            "../../research-scientist/scripts/capture_venue_sources.py",
            "../../research-scientist/scripts/check_venue_sources.py",
            "../../research-scientist/scripts/check_venue_plan.py",
            "../../research-scientist/modules/kdense-scholar-evaluation/scripts/calculate_scores.py",
            "../../research-scientist/modules/kdense-peer-review/scripts/validate_claim_evidence.py",
            "same_host_path_redirect_year_mismatch", "js_rendered_suspected", "AoE",
            "Never use scoring tools to rank people",
        )
        for token in required:
            self.assertIn(token, text, f"Missing '{token}' in novelty-venue-rebuttal-protocol.md")

    def test_novelty_venue_weak_rebuttal_example_triggers_check_rebuttal(self) -> None:
        text = SUB_REF_FILES["research-novelty-venue"].read_text(encoding="utf-8")
        m = re.search(r'\*Weak / Violates Integrity:\*\s+\*"([^"]+)"\*', text)
        self.assertIsNotNone(m, "Could not locate Weak / Violates Integrity example in novelty-venue-rebuttal-protocol.md")
        assert m is not None
        weak_prose = m.group(1)
        check_rebuttal_path = PARENT_DIR / "scripts" / "check_rebuttal.py"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            pts = tmp_dir / "points.md"
            resp = tmp_dir / "responses.md"
            pts.write_text("- **R1.1**: Please add baseline comparison.\n", encoding="utf-8")
            resp.write_text(f"- **R1.1**: {weak_prose}\n", encoding="utf-8")
            res = subprocess.run(
                [sys.executable, str(check_rebuttal_path), "coverage", str(pts), str(resp), "--strict", "--json"],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(res.returncode, 1, f"Expected exit 1 on weak example, got {res.returncode}: {res.stdout} {res.stderr}")
        payload = json.loads(res.stdout)
        self.assertTrue(payload["unverified_experiment_claims"], "Weak example must trigger unverified_experiment_claims")
        self.assertTrue(payload["sycophancy_warnings"], "Weak example must trigger sycophancy_warnings")
        self.assertTrue(payload["vague_promise_warnings"], "Weak example must trigger vague_promise_warnings")
        self.assertTrue(payload["unanchored_sections"], "Weak example must trigger unanchored_sections")

    def test_paper_writing_manual_coverage_exact_7_compression_patterns(self) -> None:
        text = SUB_REF_FILES["research-paper-writing"].read_text(encoding="utf-8")
        required = (
            "Sentence Shortening",
            "Paragraph Merging",
            "Removal of Generic Adjectives",
            "Removal of Tutorial Explanation",
            "Conversion to Claim-First Sentences",
            "Evaluation Compression via Takeaways",
            "Figure/Table Promotion",
            "Expansion-Compression Arc",
            "Group A", "Group B", "Group C", "Group D", "Group E", "Group F", "§1", "§26",
            "../../research-scientist/scripts/humanizer_lint.py",
            "../../research-scientist/scripts/check_manuscript_ledger.py",
            "../../research-scientist/scripts/check_figure_qa.py",
            "../../research-scientist/scripts/check_submission_preflight.py",
            "../../research-scientist/modules/kdense-scientific-writing/scripts/audit_claims.py",
            "okabe_ito", "tol_bright", "tol_muted", "viridis_6",
            "pdf.fonttype", "Type3",
            "anonymize", "arxiv-clean", "bibtex",
            "--strip-comments-out", "--prune-unused", "--protect-caps", "--verify-online",
        )
        for token in required:
            self.assertIn(token, text, f"Missing '{token}' in paper-writing-preflight-guide.md")

    def test_gap_rq_parsimony_manual_coverage_all_drop_codes(self) -> None:
        text = SUB_REF_FILES["research-gap-rq-audit"].read_text(encoding="utf-8")
        drop_codes = (
            "DROP_TEMPORAL_LEAK",
            "DROP_UNREAD_CITATION",
            "DROP_RETRACTED_SUPPORT",
            "DROP_ENGINEERING_BUG",
            "DROP_ALREADY_SOLVED",
            "DROP_PROBLEM_INFLATION",
            "DROP_OVERCOMPLICATED",
            "DROP_INSUFFICIENT_COVERAGE",
            "DROP_SINGLE_PAPER_FRAGILE",
            "DROP_ARTIFICIAL_SCOPE",
            "DROP_SGHA_CRITIC_REJECT",
            "DROP_DUPLICATE",
        )
        for code in drop_codes:
            self.assertIn(code, text, f"Missing '{code}' in gap-rq-parsimony-protocol.md")
        required = (
            "../../research-scientist/scripts/storm_explorer.py",
            "../../research-scientist/scripts/gap_pipeline.py",
            "../../research-scientist/scripts/check_gap_record.py",
            "../../research-scientist/scripts/check_gap_campaign.py",
            "../../research-scientist/scripts/check_question_card.py",
            "../../research-scientist/scripts/check_ai_cs_research_plan.py",
            "../../research-scientist/modules/kdense-hypothesis-generation/scripts/check_falsification_controls.py",
            "../../research-scientist/modules/researchradar/problem-statement-finder/scripts/radar.py",
            "cross_setting_analogy", "information_table", "uncovered_branches",
            "simplest_alternative", "marginal_gain > 0", "identification_assumptions",
            "data_identity", "split_integrity", "preprocessing", "metric_sanity",
            "baseline_fidelity", "reference_reproduction",
        )
        for token in required:
            self.assertIn(token, text, f"Missing '{token}' in gap-rq-parsimony-protocol.md")

    def test_precedent_corpus_manual_coverage(self) -> None:
        text = SUB_REF_FILES["research-precedent-corpus"].read_text(encoding="utf-8")
        sources = ("s2", "openalex", "crossref", "europepmc", "arxiv", "pubmed", "acl", "huggingface", "dblp")
        for src in sources:
            self.assertIn(f"`{src}`", text, f"Missing source '{src}' in corpus-retrieval-protocol.md")
        statuses = ("complete", "bounded_partial", "valid_zero_results", "rate_limited", "bot_blocked", "source_failed")
        for st in statuses:
            self.assertIn(f"`{st}`", text, f"Missing status '{st}' in corpus-retrieval-protocol.md")
        required = (
            "../../research-scientist/scripts/search_papers.py",
            "../../research-scientist/scripts/search_campaign.py",
            "../../research-scientist/scripts/citation_trails.py",
            "../../research-scientist/scripts/citation_graph.py",
            "../../research-scientist/scripts/fulltext_mining.py",
            "../../research-scientist/scripts/resolve_fulltext.py",
            "../../research-scientist/scripts/extract_pdf_blocks.py",
            "../../research-scientist/scripts/local_evidence.py",
            "../../research-scientist/scripts/check_evidence_map.py",
            "../../research-scientist/modules/kdense-literature-review/scripts/verify_citations.py",
            "campaign_plan.json", "^W[0-9]+$",
            "10.48550/arxiv.", "chunk_chars=1200", "chunk_overlap=200",
            "mmr_lambda=0.7", "min_studies", "min_evidence", "maybe_is_text",
            "ANSWERABLE", "ABSTAIN", "--khoj-url", "AGPL-3.0", "mineru_cli_not_found",
            "visual_check_required", "< 50",
        )
        for token in required:
            self.assertIn(token, text, f"Missing '{token}' in corpus-retrieval-protocol.md")

        # Verify documented citation_trails.py CLI example uses a valid OpenAlex W-number, not a DOI.
        trails_match = re.search(r"citation_trails\.py\s+(\S+)", text)
        self.assertIsNotNone(trails_match, "Missing citation_trails.py CLI example in corpus-retrieval-protocol.md")
        assert trails_match is not None
        self.assertRegex(
            trails_match.group(1),
            r"^W[0-9]+$",
            f"citation_trails.py CLI example must use a ^W[0-9]+$ OpenAlex ID, got {trails_match.group(1)!r}",
        )

    def test_user_report_manual_coverage(self) -> None:
        text = SUB_REF_FILES["research-user-report"].read_text(encoding="utf-8")
        required = (
            "../../research-scientist/scripts/report_latex_pdf.py",
            "research_scientist_executive_report_v1",
            "parsimony_check", "simplest_alternative",
            "STRUCT_MISSING_VERDICT", "RPT_PLACEHOLDER",
            "SENTENCE_TOO_LONG", "SENTENCE_SEVERE_BLOAT",
            "PARAGRAPH_BLOAT", "SECTION_BLOAT", "TOTAL_REPORT_BLOAT",
            "JARGON_AI_BUZZWORD", "JARGON_VI_BUZZWORD",
            "FILLER_TRANSITION", "NOMINALIZATION",
            "SYC_FLATTERY", "SYC_CHEERLEADING", "SYC_PRAISE_SANDWICH",
            "PI01", "RPT_GRAND_BRANDING",
            "UNGROUNDED_NUMERIC_CLAIM", "UNGROUNDED_CITATION", "MISSING_EVIDENCE_LOCATOR",
            "xelatex", "lualatex", "pdflatex", "T1,T5", "babel[vietnamese]",
            "pymupdf", "diacritics_verified",
            "lint_failed", "compile_failed", "verify_failed",
        )
        for token in required:
            self.assertIn(token, text, f"Missing '{token}' in user-report-pdf-guide.md")

    def test_claim_audit_suite_root_passes_with_zero_findings(self) -> None:
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        res = subprocess.run(
            [
                sys.executable,
                str(CLAIM_AUDIT_PATH),
                "--suite-root",
                str(REPO_ROOT),
                "--readme",
                str(REPO_ROOT / "README.md"),
                "--json",
            ],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 0, f"claim_audit failed:\n{res.stdout}\n{res.stderr}")
        payload = json.loads(res.stdout)
        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["finding_count"], 0)


if __name__ == "__main__":
    unittest.main()
