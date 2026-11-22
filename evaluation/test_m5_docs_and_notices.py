"""Unmocked tests for Milestone M5/M8C: Docs, Notices, Attribution, 35-Script Inventory & License Isolation."""

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
    ("Stanford STORM / Co-STORM", ("storm",)),
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
        prohibited = (
            re.compile(r"\bfrom\s+magic_pdf\b"),
            re.compile(r"\bimport\s+magic_pdf\b"),
            re.compile(r"\bfrom\s+khoj\b"),
            re.compile(r"\bimport\s+khoj\b"),
            re.compile(r"\bfrom\s+ai_scientist\b"),
            re.compile(r"\bimport\s+ai_scientist\b"),
            re.compile(r"GNU AFFERO GENERAL PUBLIC LICENSE", re.IGNORECASE),
            re.compile(r"Creative Commons Attribution-NonCommercial", re.IGNORECASE),
            re.compile(r"CC\s*BY-NC\s*4\.0", re.IGNORECASE),
            re.compile(r"\bRAILS\s+License\b", re.IGNORECASE),
        )
        for sname in ALL_SKILLS:
            sdir = REPO_ROOT / sname
            self.assertTrue(sdir.is_dir(), f"Missing skill dir: {sdir}")
            for py_file in sdir.rglob("*.py"):
                code = py_file.read_text(encoding="utf-8", errors="replace")
                for pat in prohibited:
                    self.assertIsNone(pat.search(code), f"Restricted license/code leak in {py_file}: {pat.pattern}")

    def test_all_relative_markdown_links_resolve(self) -> None:
        doc_paths = (
            REPO_ROOT / "README.md",
            PARENT_DIR / "INSTALL.md",
            PARENT_DIR / "THIRD_PARTY_NOTICES.md",
            REFS_DIR / "repository-landscape.md",
            REFS_DIR / "retrieval-source-details.md",
            REFS_DIR / "gap-rq-source-details.md",
            MODULES_DIR / "researchradar" / "VENDOR.md",
        )
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

    def test_all_35_scripts_m8a_flags_router_bound_and_claim_audit_pass(self) -> None:
        expected_35_scripts = (
            "audit_alignment.py",
            "capture_venue_sources.py",
            "check_ai_cs_research_plan.py",
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
            "extract_pdf_blocks.py",
            "fulltext_mining.py",
            "gap_pipeline.py",
            "humanizer_lint.py",
            "local_evidence.py",
            "report_latex_pdf.py",
            "resolve_fulltext.py",
            "score_math.py",
            "search_campaign.py",
            "search_papers.py",
            "storm_explorer.py",
            "sync_skills.py",
            "venue_leads.py",
            "venue_panel_collector.py",
        )
        scripts = sorted(p.name for p in SCRIPTS_DIR.glob("*.py") if p.name != "__init__.py")
        self.assertGreaterEqual(len(scripts), 35, f"Expected >=35 scripts, found {len(scripts)}: {scripts}")
        for script_name in expected_35_scripts:
            self.assertIn(script_name, scripts, f"Missing expected M5 script on disk: {script_name}")
            self.assertIn(script_name, self.readme, f"README.md missing script {script_name}")
            self.assertIn(script_name, self.install, f"INSTALL.md missing script {script_name}")

        for flag in ("--check", "--prune-unused", "--verify-online"):
            self.assertIn(flag, self.readme, f"README.md missing M8A flag {flag}")
        self.assertIn("--check", self.install)
        self.assertIn("--out", self.install)
        self.assertNotIn("<95", self.readme, "README.md still has stale <95-line router bound")
        self.assertIn("<50", self.readme)

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


if __name__ == "__main__":
    unittest.main()
