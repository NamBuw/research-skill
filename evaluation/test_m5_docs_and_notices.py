"""Unmocked tests for Milestone M5/M8C/M10: Docs, Notices, Attribution, 41-Script Inventory & License Isolation."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PARENT_DIR = REPO_ROOT / "research-scientist"
SCRIPTS_DIR = PARENT_DIR / "scripts"
MODULES_DIR = PARENT_DIR / "modules"
REFS_DIR = PARENT_DIR / "references"

ALL_SKILLS = (
    "research-scientist",
    "research-precedent-corpus",
    "research-gap-rq-audit",
    "research-experiment-coding",
    "research-novelty-venue",
    "research-paper-writing",
    "research-user-report",
)

REQUESTED_23_REPOS = (
    ("GPT Researcher", ("gpt researcher", "gpt-researcher")),
    ("Stanford STORM / Co-STORM", ("stanford storm",)),
    ("PaperQA2", ("paperqa2", "paper-qa")),
    ("The AI Scientist", ("ai scientist", "ai-scientist")),
    ("Perplexica / Vane", ("perplexica", "vane")),
    ("MinerU", ("mineru",)),
    ("Khoj", ("khoj",)),
    ("K-Dense Scientific Skills", ("k-dense",)),
    ("Humanizer", ("humanizer",)),
    ("ResearchRadar", ("researchradar",)),
    ("AI-Researcher", ("ai-researcher",)),
    ("Good Question", ("good question", "good-question")),
    ("Lit-Gap", ("lit-gap",)),
    ("SciPIP", ("scipip",)),
    ("ResearchAgent", ("researchagent",)),
    ("IRIS", ("iris",)),
    ("CKM-HypoGen", ("ckm-hypogen",)),
    ("obra/superpowers", ("obra/superpowers",)),
    ("affaan-m/ECC", ("affaan-m/ecc",)),
    ("Agent-Skills-for-Context-Engineering", ("agent-skills-for-context-engineering",)),
    ("tw93/Waza", ("tw93/waza",)),
    ("scipilot-figure-skill", ("scipilot-figure-skill",)),
    ("codex-claude-academic-skills", ("codex-claude-academic-skills",)),
)

MD_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)#\s]+)(?:#[^)\s]*)?\)")


def _run_claim_audit(args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "claim_audit.py"), *args],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


class TestM5DocsAndNotices(unittest.TestCase):
    def setUp(self) -> None:
        self.readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.install = (PARENT_DIR / "INSTALL.md").read_text(encoding="utf-8")
        self.notices = (PARENT_DIR / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        self.landscape = (REFS_DIR / "repository-landscape.md").read_text(encoding="utf-8")
        self.retrieval_src = (REFS_DIR / "retrieval-source-details.md").read_text(encoding="utf-8")
        self.gap_src = (REFS_DIR / "gap-rq-source-details.md").read_text(encoding="utf-8")
        self.radar_vendor = (MODULES_DIR / "researchradar" / "VENDOR.md").read_text(encoding="utf-8")

    def test_23_upstream_repos_consistent_across_docs(self) -> None:
        docs = {
            "README.md": self.readme.casefold(),
            "THIRD_PARTY_NOTICES.md": self.notices.casefold(),
            "repository-landscape.md": self.landscape.casefold(),
        }
        for doc_name, text in docs.items():
            for label, aliases in REQUESTED_23_REPOS:
                self.assertTrue(
                    any(alias in text for alias in aliases),
                    f"{doc_name} missing attribution for {label} (aliases={aliases})",
                )
        # Cross-doc consistency on RE-research-design, blader/humanizer, SGHA-Research/sgha, and IRIS/ShaishavMaisuria fixes
        for doc_name, text in docs.items():
            self.assertIn("re-research-design", text, f"{doc_name} missing Research-Equality/RE-research-design")
            self.assertIn("humanizer", text, f"{doc_name} missing blader/humanizer")
            self.assertIn("sgha", text, f"{doc_name} missing SGHA-Research/sgha")
        self.assertIn("a32f244", self.landscape)
        self.assertIn("ShaishavMaisuria/research-paper-lifecycle-skills", self.retrieval_src)
        self.assertNotIn("Kalaris/research-paper-lifecycle-skills", self.retrieval_src)
        self.assertIn("Anikethh/IRIS-Interactive-Research-Ideation-System", self.gap_src)
        self.assertNotIn("HKUDS/IRIS", self.gap_src)
        self.assertNotIn("without functional changes", self.radar_vendor.casefold())
        self.assertIn("conn.close()", self.radar_vendor)
        self.assertIn("https://github.com/SGHA-Research/sgha", self.retrieval_src)
        self.assertIn("https://github.com/cheerss/SciPIP", self.retrieval_src)
        self.assertIn("https://github.com/saulmcphd/lit-gap", self.retrieval_src)
        self.assertNotIn("https://github.com/Azeem2002/SGHA", self.retrieval_src)
        self.assertNotIn("https://github.com/scipip)", self.retrieval_src)
        self.assertNotIn("https://github.com/lit-gap)", self.retrieval_src)

    def test_paper_quality_filter_mit_attribution_and_exclusion_consistent(self) -> None:
        for doc_name, text in (
            ("README.md", self.readme),
            ("THIRD_PARTY_NOTICES.md", self.notices),
            ("repository-landscape.md", self.landscape),
        ):
            low = text.casefold()
            self.assertIn("yilaai/paper-quality-filter", low, f"{doc_name} missing yilaai/paper-quality-filter")
            self.assertIn("journal_scores.json", low, f"{doc_name} missing journal_scores.json exclusion")
            self.assertIn("venue_leads.py", low, f"{doc_name} missing venue_leads.py mapping")
            self.assertIn("compare_venue_novelty.py", low, f"{doc_name} missing compare_venue_novelty.py mapping")
            self.assertIn("--quality-refs-dir", low, f"{doc_name} missing --quality-refs-dir boundary")
        self.assertIn("679cdf3", self.notices)
        self.assertIn("679cdf3", self.readme)
        self.assertIn("679cdf3", self.landscape)

    def test_all_7_bundled_modules_have_vendor_license_and_renamed_upstream_skill(self) -> None:
        mod_dirs = sorted(p for p in MODULES_DIR.iterdir() if p.is_dir())
        self.assertEqual(len(mod_dirs), 7, f"Expected 7 bundled modules, got {[p.name for p in mod_dirs]}")
        for mod in mod_dirs:
            self.assertTrue((mod / "VENDOR.md").is_file(), f"Missing VENDOR.md in {mod}")
            self.assertTrue((mod / "LICENSE.md").is_file(), f"Missing LICENSE.md in {mod}")
            self.assertFalse((mod / "SKILL.md").exists(), f"Unrenamed SKILL.md in {mod}")
            if mod.name == "researchradar":
                sub_skills = [p for p in mod.iterdir() if p.is_dir()]
                self.assertEqual(len(sub_skills), 6)
                for sub in sub_skills:
                    self.assertTrue((sub / "UPSTREAM_SKILL.md").is_file(), f"Missing UPSTREAM_SKILL.md in {sub}")
                    self.assertFalse((sub / "SKILL.md").exists(), f"Unrenamed SKILL.md in {sub}")
            else:
                self.assertTrue((mod / "UPSTREAM_SKILL.md").is_file(), f"Missing UPSTREAM_SKILL.md in {mod}")
        self.assertEqual(list(MODULES_DIR.rglob("SKILL.md")), [])

    def test_zero_restricted_license_code_leaks_across_all_7_skills(self) -> None:
        unconditional_prohibited = (
            re.compile(r"\bfrom\s+magic_pdf\b"),
            re.compile(r"\bimport\s+magic_pdf\b"),
            re.compile(r"\bfrom\s+khoj\b"),
            re.compile(r"\bimport\s+khoj\b"),
            re.compile(r"\bfrom\s+ai_scientist\b"),
            re.compile(r"\bimport\s+ai_scientist\b"),
            re.compile(r"GNU AFFERO GENERAL PUBLIC LICENSE", re.IGNORECASE),
            re.compile(r"Creative Commons Attribution-NonCommercial", re.IGNORECASE),
        )
        boundary_token_prohibited = (
            ("AGPL-3.0", re.compile(r"\bAGPL-3\.0\b", re.IGNORECASE)),
            ("CC BY-NC 4.0", re.compile(r"CC\s*BY-NC\s*4\.0", re.IGNORECASE)),
            ("RAILS License", re.compile(r"\bRAILS\s+License\b", re.IGNORECASE)),
            ("magic_pdf", re.compile(r"\bmagic_pdf\b")),
            ("journal_scores.json", re.compile(r"\bjournal_scores\.json\b")),
        )
        boundary_disclaimer_docs = {
            "research-scientist/THIRD_PARTY_NOTICES.md",
            "research-scientist/references/repository-landscape.md",
            "research-scientist/references/retrieval-source-details.md",
            "research-scientist/references/writing-score-venue-source-details.md",
            "research-precedent-corpus/references/corpus-retrieval-protocol.md",
        }
        # Clean-room .py exceptions: AGPL-3.0 detector/boundary comment & optional external --quality-refs-dir filename
        py_token_exceptions = {
            "AGPL-3.0": {
                "research-scientist/scripts/check_artifact_readiness.py",
                "research-scientist/scripts/local_evidence.py",
            },
            "journal_scores.json": {
                "research-scientist/scripts/venue_leads.py",
            },
        }
        scanned_files = 0
        for sname in ALL_SKILLS:
            sdir = REPO_ROOT / sname
            self.assertTrue(sdir.is_dir(), f"Missing skill dir: {sdir}")
            for path in sorted(sdir.rglob("*")):
                if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                    continue
                self.assertNotEqual(path.name, "journal_scores.json", f"Excluded file present: {path}")
                try:
                    content = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                scanned_files += 1
                rel = path.relative_to(REPO_ROOT).as_posix()
                for pat in unconditional_prohibited:
                    self.assertIsNone(
                        pat.search(content),
                        f"Restricted license/code leak in {rel}: {pat.pattern}",
                    )
                in_modules = rel.startswith("research-scientist/modules/")
                is_skill_md = path.name == "SKILL.md"
                for tok_name, pat in boundary_token_prohibited:
                    if in_modules or is_skill_md:
                        allowed = False
                    elif path.suffix == ".py":
                        allowed = rel in py_token_exceptions.get(tok_name, set())
                    else:
                        allowed = rel in boundary_disclaimer_docs
                    if not allowed:
                        self.assertIsNone(
                            pat.search(content),
                            f"Restricted boundary token `{tok_name}` leaked in {rel}",
                        )
        self.assertGreater(scanned_files, 150)

    def test_all_relative_markdown_links_resolve(self) -> None:
        doc_paths = [REPO_ROOT / "README.md"]
        for sname in ALL_SKILLS:
            sdir = REPO_ROOT / sname
            for md_path in sorted(sdir.rglob("*.md")):
                if "modules" not in md_path.parts:
                    doc_paths.append(md_path)
        self.assertGreaterEqual(len(doc_paths), 38)
        for doc_path in doc_paths:
            text = doc_path.read_text(encoding="utf-8")
            for match in MD_LINK_RE.finditer(text):
                target = match.group(1)
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                resolved = (doc_path.parent / target).resolve()
                self.assertTrue(
                    resolved.exists(),
                    f"Broken relative markdown link in {doc_path.relative_to(REPO_ROOT)}: {target} -> {resolved}",
                )

    def test_all_41_scripts_f23_f32_flags_router_bound_and_claim_audit_pass(self) -> None:
        expected_41_scripts = (
            "analyze_experiment_outcome.py",
            "audit_alignment.py",
            "build_research_inputs.py",
            "capture_venue_sources.py",
            "check_ai_cs_research_plan.py",
            "check_artifact_readiness.py",
            "check_engineering_diagnostics.py",
            "check_evidence_map.py",
            "check_experiment_manifest.py",
            "check_experiment_rigor.py",
            "check_figure_qa.py",
            "check_gap_campaign.py",
            "check_gap_record.py",
            "check_manuscript_ledger.py",
            "check_question_card.py",
            "check_rebuttal.py",
            "check_submission_preflight.py",
            "check_venue_plan.py",
            "check_venue_sources.py",
            "citation_graph.py",
            "citation_trails.py",
            "claim_audit.py",
            "compare_scorecards.py",
            "compare_venue_novelty.py",
            "evaluate_submission.py",
            "extract_pdf_blocks.py",
            "fulltext_mining.py",
            "gap_pipeline.py",
            "humanizer_lint.py",
            "local_evidence.py",
            "project_state.py",
            "report_latex_pdf.py",
            "resolve_fulltext.py",
            "score_math.py",
            "search_campaign.py",
            "search_papers.py",
            "storm_explorer.py",
            "sync_skills.py",
            "triage_reviews.py",
            "venue_leads.py",
            "venue_panel_collector.py",
        )
        scripts = sorted(p.name for p in SCRIPTS_DIR.glob("*.py") if p.name != "__init__.py")
        self.assertEqual(set(scripts), set(expected_41_scripts), f"Expected exact 41 scripts, got {scripts}")
        for script_name in expected_41_scripts:
            self.assertIn(script_name, self.readme, f"README.md missing script {script_name}")
            self.assertIn(script_name, self.install, f"INSTALL.md missing script {script_name}")

        for flag in (
            "--check",
            "--prune-unused",
            "--verify-online",
            "--strict-related-panel",
            "--portfolio",
            "--venue-type",
            "--revision-diff",
            "--subfield-preset",
            "--audit-arguments",
            "--anonymous",
            "--strict-triage",
            "--advise",
            "mock-review",
            "post-reject",
        ):
            self.assertIn(flag, self.readme, f"README.md missing F23-F32/M8A flag or subcommand {flag}")
        self.assertIn("--check", self.install)
        self.assertIn("--out", self.install)
        self.assertNotIn("<95", self.readme, "README.md still has stale <95-line router bound")
        self.assertNotIn("21–41", self.readme, "README.md still has stale 21-41 line bound")
        self.assertIn("<50", self.readme)
        self.assertIn("22–41", self.readme)

        novelty_skill = (REPO_ROOT / "research-novelty-venue" / "SKILL.md").read_text(encoding="utf-8")
        novelty_proto = (REPO_ROOT / "research-novelty-venue" / "references" / "novelty-venue-rebuttal-protocol.md").read_text(encoding="utf-8")
        self.assertIn("references/review-triage-calibration.md", novelty_skill)
        self.assertIn("triage_reviews.py", novelty_skill)
        self.assertIn("review-triage-calibration.md", novelty_proto)
        self.assertIn("xf686/Meet-Reviewer-2", self.notices)
        self.assertIn("scripts/triage_reviews.py", self.notices)
        self.assertIn("scripts/triage_reviews.py", self.landscape)

        for args in (
            ["--suite-root", str(REPO_ROOT), "--readme", str(REPO_ROOT / "README.md"), "--json"],
            ["--root", str(PARENT_DIR), "--readme", str(PARENT_DIR / "INSTALL.md"), "--json"],
            ["--root", str(PARENT_DIR), "--readme", str(PARENT_DIR / "THIRD_PARTY_NOTICES.md"), "--json"],
        ):
            proc = _run_claim_audit(args)
            self.assertEqual(proc.returncode, 0, f"claim_audit failed for {args}: {proc.stdout}\n{proc.stderr}")
            data = json.loads(proc.stdout)
            self.assertEqual(data["status"], "passed")
            self.assertEqual(data["finding_count"], 0)
            if "skills_audited" in data:
                for sk in data["skills_audited"]:
                    fp = sk["footprint"]
                    self.assertLess(fp["lines"], 50, f"{sk['name']} SKILL.md lines >= 50: {fp}")
                    self.assertLess(fp["est_tokens"], 900, f"{sk['name']} SKILL.md est_tokens >= 900: {fp}")
                    self.assertLess(fp["frontmatter_est_tokens"], 140, f"{sk['name']} SKILL.md fm_tokens >= 140: {fp}")


if __name__ == "__main__":
    unittest.main()
