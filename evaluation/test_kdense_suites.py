"""Offline tests for all bundled K-Dense suites and scripts."""
from __future__ import annotations

import copy
import csv
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MODULES = ROOT / "research-scientist" / "modules"


def run_script(suite: str, script: str, *args: object) -> subprocess.CompletedProcess[str]:
    script_path = MODULES / suite / "scripts" / script
    return subprocess.run(
        [sys.executable, str(script_path), *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
    )


def load_module(path: Path, name: str):
    script_dir = str(path.parent)
    added = False
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
        added = True
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        if added and script_dir in sys.path:
            sys.path.remove(script_dir)


def _valid_source_manifest(verified: bool = True) -> dict:
    return {
        "schema_version": "1.0",
        "sources": [
            {
                "evidence_id": "E001",
                "source_type": "journal_article",
                "title": "Calibrated Evaluation of Graph Models",
                "authors": ["Ada Lovelace"],
                "year": 2024,
                "identifiers": {
                    "doi": "https://doi.org/10.1000/xyz123",
                    "pmid": "12345678",
                    "pmcid": "PMC1234567",
                    "isbn": "978-0-306-40615-7",
                    "url": "https://example.org/paper",
                },
                "locator": "Table 2, page 5",
                "confidentiality": "public",
                "verification": {
                    "status": "verified" if verified else "unverified",
                    "source_opened": bool(verified),
                    "verified_by": "Lead Reviewer" if verified else "",
                    "verified_on": "2026-11-21" if verified else "",
                },
            }
        ],
    }


def _valid_manuscript_manifest(submission_ready: bool = True) -> dict:
    status = "submission_candidate" if submission_ready else "draft"
    stmt = "verified" if submission_ready else "draft"
    return {
        "schema_version": "1.0",
        "document_id": "paper-2026-01",
        "study_design": "randomized_trial",
        "draft_status": status,
        "submission_ready": submission_ready,
        "registries": {
            "source_manifest": "sources.json",
            "claim_evidence": "claims.csv",
            "consistency_manifest": "consistency.json",
            "authorship_manifest": "authorship.json",
            "reporting_coverage": "coverage.json",
        },
        "reporting_guidelines": ["consort-2025"],
        "human_verification": {
            "completed": True,
            "verified_by": "Lead Author",
            "verified_on": "2026-11-21",
        },
        "confidentiality_review": {
            "completed": True,
            "verified_by": "Compliance Officer",
            "verified_on": "2026-11-21",
            "policy_checked": True,
            "external_services_authorized": True,
        },
        "required_statements": {
            "ethics": stmt,
            "consent": stmt,
            "funding": stmt,
            "conflicts": stmt,
            "data_availability": stmt,
            "code_availability": stmt,
            "author_contributions": stmt,
            "ai_disclosure": stmt,
        },
    }


class ScientificWritingRemainingScriptsTests(unittest.TestCase):
    SUITE = "kdense-scientific-writing"

    def test_validate_manifest_positive_negative_and_cli_error(self):
        assets = MODULES / self.SUITE / "assets"
        tpl = run_script(self.SUITE, "validate_manifest.py", assets / "manuscript_manifest_template.json")
        self.assertEqual(tpl.returncode, 1)
        self.assertEqual(json.loads(tpl.stdout)["status"], "fail")

        missing = run_script(self.SUITE, "validate_manifest.py", assets / "does_not_exist.json")
        self.assertEqual(missing.returncode, 1)
        self.assertEqual(json.loads(missing.stdout)["issues"][0]["code"], "INVALID_INPUT")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            ms_ok = tmp_dir / "ms_ok.json"
            ms_ok.write_text(json.dumps(_valid_manuscript_manifest(True)), encoding="utf-8")
            res_ok = run_script(self.SUITE, "validate_manifest.py", ms_ok, "--kind", "auto")
            self.assertEqual(res_ok.returncode, 0, res_ok.stdout)
            self.assertEqual(json.loads(res_ok.stdout)["summary"]["kind"], "manuscript")

            ms_bad = _valid_manuscript_manifest(True)
            ms_bad["draft_status"] = "draft"
            ms_bad["human_verification"]["completed"] = False
            ms_bad_path = tmp_dir / "ms_bad.json"
            ms_bad_path.write_text(json.dumps(ms_bad), encoding="utf-8")
            res_bad = run_script(self.SUITE, "validate_manifest.py", ms_bad_path, "--kind", "manuscript")
            self.assertEqual(res_bad.returncode, 1)
            codes = {i["code"] for i in json.loads(res_bad.stdout)["issues"]}
            self.assertIn("READY_STATUS_MISMATCH", codes)
            self.assertIn("SUBMISSION_GATE_INCOMPLETE", codes)

            src_ok = tmp_dir / "src_ok.json"
            src_ok.write_text(json.dumps(_valid_source_manifest(True)), encoding="utf-8")
            res_src_ok = run_script(self.SUITE, "validate_manifest.py", src_ok, "--require-verified")
            self.assertEqual(res_src_ok.returncode, 0, res_src_ok.stdout)

            src_unver = tmp_dir / "src_unver.json"
            src_unver.write_text(json.dumps(_valid_source_manifest(False)), encoding="utf-8")
            res_src_unver = run_script(self.SUITE, "validate_manifest.py", src_unver, "--require-verified")
            self.assertEqual(res_src_unver.returncode, 1)
            self.assertIn("SOURCE_NOT_VERIFIED", {i["code"] for i in json.loads(res_src_unver.stdout)["issues"]})

    def test_check_references_positive_and_negative(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            ok_path = tmp_dir / "refs_ok.json"
            ok_path.write_text(json.dumps(_valid_source_manifest(True)), encoding="utf-8")
            res_ok = run_script(self.SUITE, "check_references.py", ok_path)
            self.assertEqual(res_ok.returncode, 0, res_ok.stdout)
            payload_ok = json.loads(res_ok.stdout)
            self.assertFalse(payload_ok["summary"]["network_used"])

            bad_data = _valid_source_manifest(True)
            s2 = copy.deepcopy(bad_data["sources"][0])
            s2["evidence_id"] = "E002"
            s2["identifiers"]["isbn"] = "0-306-40615-0"  # bad ISBN-10 check digit
            s2["identifiers"]["url"] = "ftp://invalid"
            bad_data["sources"].append(s2)
            bad_data["sources"][0]["identifiers"]["doi"] = "not-a-doi"
            bad_path = tmp_dir / "refs_bad.json"
            bad_path.write_text(json.dumps(bad_data), encoding="utf-8")
            res_bad = run_script(self.SUITE, "check_references.py", bad_path)
            self.assertEqual(res_bad.returncode, 1)
            codes = {i["code"] for i in json.loads(res_bad.stdout)["issues"]}
            self.assertTrue({"MALFORMED_DOI", "MALFORMED_ISBN", "MALFORMED_URL", "POSSIBLE_DUPLICATE_TITLE"}.issubset(codes))

    def test_check_consistency_positive_and_negative(self):
        valid_registry = {
            "schema_version": "1.0",
            "numeric_facts": [
                {
                    "fact_id": "N001",
                    "concept": "accuracy",
                    "section": "abstract",
                    "value": 80.0,
                    "unit": "percent",
                    "numerator": 80,
                    "denominator": 100,
                    "sample_size": 100,
                    "analysis_set": "test_split",
                    "evidence_ids": ["E001"],
                },
                {
                    "fact_id": "N002",
                    "concept": "accuracy",
                    "section": "results",
                    "value": 80.0,
                    "unit": "percent",
                    "numerator": 80,
                    "denominator": 100,
                    "sample_size": 100,
                    "analysis_set": "test_split",
                    "evidence_ids": ["E001"],
                },
            ],
            "methods": [
                {
                    "method_id": "M001",
                    "name": "Randomized comparison",
                    "analysis_intent": "confirmatory",
                    "protocol_status": "prespecified",
                    "outcome_ids": ["O001"],
                }
            ],
            "results": [
                {
                    "result_id": "R001",
                    "method_id": "M001",
                    "outcome_id": "O001",
                    "analysis_intent": "confirmatory",
                    "sample_size": 100,
                    "evidence_ids": ["E001"],
                    "reported_sections": ["results"],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            ok_path = tmp_dir / "cons_ok.json"
            ok_path.write_text(json.dumps(valid_registry), encoding="utf-8")
            res_ok = run_script(self.SUITE, "check_consistency.py", ok_path)
            self.assertEqual(res_ok.returncode, 0, res_ok.stdout)

            bad = copy.deepcopy(valid_registry)
            bad["numeric_facts"][1]["value"] = 75.0
            bad["numeric_facts"][1]["numerator"] = 110
            bad["results"][0]["analysis_intent"] = "exploratory"
            bad_path = tmp_dir / "cons_bad.json"
            bad_path.write_text(json.dumps(bad), encoding="utf-8")
            res_bad = run_script(self.SUITE, "check_consistency.py", bad_path)
            self.assertEqual(res_bad.returncode, 1)
            codes = {i["code"] for i in json.loads(res_bad.stdout)["issues"]}
            self.assertTrue(
                {"NUMERATOR_EXCEEDS_DENOMINATOR", "CROSS_SECTION_VALUE_MISMATCH", "ANALYSIS_INTENT_MISMATCH"}.issubset(codes)
            )

    def test_validate_authorship_positive_and_negative(self):
        sha = "a" * 64
        valid_auth = {
            "schema_version": "1.0",
            "authors": [
                {
                    "author_id": "A001",
                    "is_human": True,
                    "name": "Ada Lovelace",
                    "authorship_criteria": {
                        "substantial_contribution": True,
                        "drafted_or_critically_revised": True,
                        "final_approval": True,
                        "accountable_for_work": True,
                    },
                    "credit_roles": ["conceptualization", "methodology"],
                }
            ],
            "contributors": [],
            "corresponding_author_id": "A001",
            "accountability": {
                "all_authors_approved": True,
                "guarantor_author_ids": ["A001"],
            },
            "ai_use": {
                "used": False,
                "tools": [],
                "human_verification_complete": True,
                "journal_policy_checked": True,
                "disclosed_in": [],
            },
            "declarations": {
                k: {
                    "status": "verified",
                    "content_sha256": sha,
                    "verified_by": "Ada Lovelace",
                    "verified_on": "2026-11-21",
                }
                for k in ("ai_use", "author_contributions", "conflicts", "funding")
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            ok_path = tmp_dir / "auth_ok.json"
            ok_path.write_text(json.dumps(valid_auth), encoding="utf-8")
            res_ok = run_script(self.SUITE, "validate_authorship.py", ok_path)
            self.assertEqual(res_ok.returncode, 0, res_ok.stdout)

            bad = copy.deepcopy(valid_auth)
            bad["authors"][0]["is_human"] = False
            bad["ai_use"] = {
                "used": True,
                "tools": [
                    {
                        "name": "LLM",
                        "version": "1.0",
                        "provider": "Ext",
                        "purpose": "copyedit",
                        "materials_sent": "unpublished_manuscript",
                        "external_service": True,
                        "explicit_authorization": False,
                        "policy_reviewed": False,
                    }
                ],
                "human_verification_complete": True,
                "journal_policy_checked": True,
                "disclosed_in": ["methods"],
            }
            bad_path = tmp_dir / "auth_bad.json"
            bad_path.write_text(json.dumps(bad), encoding="utf-8")
            res_bad = run_script(self.SUITE, "validate_authorship.py", bad_path)
            self.assertEqual(res_bad.returncode, 1)
            codes = {i["code"] for i in json.loads(res_bad.stdout)["issues"]}
            self.assertIn("NONHUMAN_AUTHOR_PROHIBITED", codes)
            self.assertIn("RESTRICTED_EXTERNAL_TRANSFER_UNAUTHORIZED", codes)

    def test_select_reporting_guidelines_select_and_check(self):
        sel_ok = run_script(
            self.SUITE,
            "select_reporting_guidelines.py",
            "select",
            "--study-design",
            "randomized_trial",
            "--ai",
        )
        self.assertEqual(sel_ok.returncode, 0, sel_ok.stdout)
        summary_ok = json.loads(sel_ok.stdout)["summary"]
        self.assertIn("consort-2025", summary_ok["primary"])
        self.assertIn("consort-ai-2020", summary_ok["extensions"])

        sel_llm_err = run_script(
            self.SUITE,
            "select_reporting_guidelines.py",
            "select",
            "--study-design",
            "randomized_trial",
            "--llm",
        )
        self.assertEqual(sel_llm_err.returncode, 1)
        self.assertIn("LLM_REQUIRES_AI_FLAG", {i["code"] for i in json.loads(sel_llm_err.stdout)["issues"]})

        sel_warn = run_script(
            self.SUITE,
            "select_reporting_guidelines.py",
            "select",
            "--study-design",
            "unrecognized_design",
        )
        self.assertEqual(sel_warn.returncode, 0)
        self.assertIn("NO_PRIMARY_LOCAL_MATCH", {i["code"] for i in json.loads(sel_warn.stdout)["issues"]})

        registry = json.loads(
            (MODULES / self.SUITE / "assets" / "reporting_guidelines.json").read_text(encoding="utf-8")
        )
        consort = next(g for g in registry["guidelines"] if g["id"] == "consort-2025")
        cov_ok = {
            "schema_version": "1.0",
            "guideline_id": "consort-2025",
            "items": [
                {"topic_id": t["id"], "status": "addressed", "locations": ["Methods"]}
                for t in consort["coverage_topics"]
            ],
        }
        cov_bad = copy.deepcopy(cov_ok)
        cov_bad["items"][0] = {"topic_id": consort["coverage_topics"][0]["id"], "status": "missing"}
        cov_bad["items"].pop()

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            p_ok = tmp_dir / "cov_ok.json"
            p_bad = tmp_dir / "cov_bad.json"
            p_ok.write_text(json.dumps(cov_ok), encoding="utf-8")
            p_bad.write_text(json.dumps(cov_bad), encoding="utf-8")

            r_ok = run_script(self.SUITE, "select_reporting_guidelines.py", "check", p_ok)
            self.assertEqual(r_ok.returncode, 0, r_ok.stdout)
            self.assertEqual(json.loads(r_ok.stdout)["summary"]["coverage_status"], "all_bundled_topics_addressed")

            r_bad = run_script(self.SUITE, "select_reporting_guidelines.py", "check", p_bad)
            self.assertEqual(r_bad.returncode, 1)
            codes = {i["code"] for i in json.loads(r_bad.stdout)["issues"]}
            self.assertIn("COVERAGE_TOPIC_MISSING", codes)
            self.assertIn("COVERAGE_TOPIC_NOT_RECORDED", codes)

    def test_audit_claims_positive_and_negative(self):
        claim_text = "Accuracy improved by 5.2 percentage points."
        claim_hash = hashlib.sha256(" ".join(claim_text.split()).encode("utf-8")).hexdigest()
        md_ok = f"# Results\n\n{claim_text} [claim:C001] [evidence:E001]\n"
        md_bad = "# Results\n\nAccuracy improved by 9.9 percentage points. [claim:C001] [evidence:E001]\nUntagged 42 percent.\n"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            src_path = tmp_dir / "sources.json"
            src_path.write_text(json.dumps(_valid_source_manifest(True)), encoding="utf-8")
            claims_path = tmp_dir / "claims.csv"
            with claims_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(
                    [
                        "claim_id",
                        "section",
                        "claim_kind",
                        "claim_text_sha256",
                        "evidence_ids",
                        "verification_status",
                        "uncertainty",
                        "analysis_intent",
                    ]
                )
                writer.writerow(["C001", "results", "numeric", claim_hash, "E001", "verified", "low", "confirmatory"])
            ms_ok_path = tmp_dir / "ms_ok.md"
            ms_bad_path = tmp_dir / "ms_bad.md"
            ms_ok_path.write_text(md_ok, encoding="utf-8")
            ms_bad_path.write_text(md_bad, encoding="utf-8")

            res_ok = run_script(self.SUITE, "audit_claims.py", ms_ok_path, claims_path, src_path)
            self.assertEqual(res_ok.returncode, 0, res_ok.stdout)

            res_bad = run_script(self.SUITE, "audit_claims.py", ms_bad_path, claims_path, src_path)
            self.assertEqual(res_bad.returncode, 1)
            codes = {i["code"] for i in json.loads(res_bad.stdout)["issues"]}
            self.assertIn("CLAIM_TEXT_HASH_MISMATCH", codes)
            self.assertIn("UNTAGGED_NUMERIC_CONTENT", codes)


class HypothesisGenerationTests(unittest.TestCase):
    SUITE = "kdense-hypothesis-generation"

    def test_common_import_and_cli_notice(self):
        common = load_module(MODULES / self.SUITE / "scripts" / "_common.py", "hg_common")
        self.assertTrue(hasattr(common, "ValidationError"))
        res = run_script(self.SUITE, "_common.py")
        self.assertEqual(res.returncode, 0)

    def test_validate_hypothesis_schema(self):
        assets = MODULES / self.SUITE / "assets"
        ok = run_script(self.SUITE, "validate_hypothesis_schema.py", assets / "hypothesis_record_template.json")
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertTrue(json.loads(ok.stdout)["valid"])

        missing = run_script(self.SUITE, "validate_hypothesis_schema.py", assets / "missing.json")
        self.assertEqual(missing.returncode, 2)

        with tempfile.TemporaryDirectory() as tmp:
            bad = json.loads((assets / "hypothesis_record_template.json").read_text(encoding="utf-8"))
            bad["causal_estimands"] = []
            bad["hypotheses"][0]["rival_hypothesis_ids"] = []
            bad_path = Path(tmp) / "bad_record.json"
            bad_path.write_text(json.dumps(bad), encoding="utf-8")
            res = run_script(self.SUITE, "validate_hypothesis_schema.py", bad_path)
            self.assertEqual(res.returncode, 1)
            self.assertFalse(json.loads(res.stdout)["valid"])

    def test_check_operationalization(self):
        assets = MODULES / self.SUITE / "assets"
        ok = run_script(self.SUITE, "check_operationalization.py", assets / "operationalization_template.json")
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertEqual(json.loads(ok.stdout)["status"], "VALID_WITH_MEASUREMENT_GAPS")

        with tempfile.TemporaryDirectory() as tmp:
            bad = json.loads((assets / "operationalization_template.json").read_text(encoding="utf-8"))
            bad["items"][0]["applicability"] = "not_applicable"
            bad["items"][0]["note"] = ""
            bad_path = Path(tmp) / "bad_op.json"
            bad_path.write_text(json.dumps(bad), encoding="utf-8")
            res = run_script(self.SUITE, "check_operationalization.py", bad_path)
            self.assertEqual(res.returncode, 1, res.stderr)
            self.assertIn(
                "NOT_APPLICABLE_RATIONALE_REQUIRED",
                {i["code"] for i in json.loads(res.stdout)["errors"]},
            )

    def test_validate_prediction_matrix(self):
        assets = MODULES / self.SUITE / "assets"
        ok = run_script(
            self.SUITE,
            "validate_prediction_matrix.py",
            assets / "prediction_rival_matrix_template.csv",
            "--record",
            assets / "hypothesis_record_template.json",
        )
        self.assertEqual(ok.returncode, 0, ok.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            rows = list(csv.DictReader((assets / "prediction_rival_matrix_template.csv").open(encoding="utf-8")))
            rows[0]["rival_hypothesis_ids"] = rows[0]["hypothesis_id"]
            rows[0]["expected_if_rivals"] = rows[0]["expected_if_focal"]
            bad_csv = Path(tmp) / "bad_matrix.csv"
            with bad_csv.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
            res = run_script(self.SUITE, "validate_prediction_matrix.py", bad_csv)
            self.assertEqual(res.returncode, 1, res.stderr)
            codes = {i["code"] for i in json.loads(res.stdout)["errors"]}
            self.assertIn("FOCAL_HYPOTHESIS_LISTED_AS_RIVAL", codes)
            self.assertIn("FOCAL_AND_RIVAL_EXPECTATIONS_IDENTICAL", codes)

    def test_lint_causal_claims(self):
        assets = MODULES / self.SUITE / "assets"
        ok = run_script(self.SUITE, "lint_causal_claims.py", assets / "preregistration_scaffold_template.md")
        self.assertEqual(ok.returncode, 0, ok.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            bad_md = Path(tmp) / "causal_bad.md"
            bad_md.write_text("# Claims\n\nTreatment X causes improved outcome Y without tags.\n", encoding="utf-8")
            res = run_script(self.SUITE, "lint_causal_claims.py", bad_md)
            self.assertEqual(res.returncode, 1)
            codes = {i["code"] for i in json.loads(res.stdout)["errors"]}
            self.assertIn("UNMARKED_CAUSAL_LANGUAGE", codes)

    def test_check_falsification_controls(self):
        assets = MODULES / self.SUITE / "assets"
        ok = run_script(
            self.SUITE,
            "check_falsification_controls.py",
            assets / "falsification_controls_template.json",
            "--record",
            assets / "hypothesis_record_template.json",
        )
        self.assertEqual(ok.returncode, 0, ok.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            bad = json.loads((assets / "falsification_controls_template.json").read_text(encoding="utf-8"))
            bad["hypotheses"][0]["controls"] = [bad["hypotheses"][0]["controls"][1]]  # positive_control only
            bad["hypotheses"][0]["discriminating_tests"][0]["rival_hypothesis_id"] = "H1"
            bad_path = Path(tmp) / "bad_fc.json"
            bad_path.write_text(json.dumps(bad), encoding="utf-8")
            res = run_script(self.SUITE, "check_falsification_controls.py", bad_path)
            self.assertEqual(res.returncode, 1, res.stderr)
            codes = {i["code"] for i in json.loads(res.stdout)["errors"]}
            self.assertIn("NEGATIVE_CONTROL_REQUIRED", codes)
            self.assertIn("FOCAL_HYPOTHESIS_LISTED_AS_RIVAL", codes)

    def test_audit_evidence_ledger(self):
        assets = MODULES / self.SUITE / "assets"
        ok = run_script(
            self.SUITE,
            "audit_evidence_ledger.py",
            assets / "evidence_ledger_template.csv",
            assets / "search_boundary_template.json",
            "--record",
            assets / "hypothesis_record_template.json",
        )
        self.assertEqual(ok.returncode, 0, ok.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            boundary = json.loads((assets / "search_boundary_template.json").read_text(encoding="utf-8"))
            boundary["search_boundary_id"] = "SEARCH-MISMATCH"
            bad_b = Path(tmp) / "bad_boundary.json"
            bad_b.write_text(json.dumps(boundary), encoding="utf-8")
            res = run_script(
                self.SUITE,
                "audit_evidence_ledger.py",
                assets / "evidence_ledger_template.csv",
                bad_b,
                "--record",
                assets / "hypothesis_record_template.json",
            )
            self.assertEqual(res.returncode, 1)
            self.assertIn("SEARCH_BOUNDARY_ID_MISMATCH", {i["code"] for i in json.loads(res.stdout)["errors"]})

    def test_generate_preregistration_scaffold(self):
        assets = MODULES / self.SUITE / "assets"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            out_md = tmp_dir / "prereg.md"
            ok = run_script(
                self.SUITE,
                "generate_preregistration_scaffold.py",
                assets / "hypothesis_record_template.json",
                "-o",
                out_md,
            )
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertTrue(out_md.is_file())
            self.assertIn("HG-SYN-001", out_md.read_text(encoding="utf-8"))

            no_force = run_script(
                self.SUITE,
                "generate_preregistration_scaffold.py",
                assets / "hypothesis_record_template.json",
                "-o",
                out_md,
            )
            self.assertEqual(no_force.returncode, 2)

            with_force = run_script(
                self.SUITE,
                "generate_preregistration_scaffold.py",
                assets / "hypothesis_record_template.json",
                "-o",
                out_md,
                "--force",
            )
            self.assertEqual(with_force.returncode, 0)

            blocked = json.loads((assets / "hypothesis_record_template.json").read_text(encoding="utf-8"))
            blocked["ethics_and_feasibility"]["human_subjects_gate"] = "blocked"
            blocked["ethics_and_feasibility"]["unresolved_blocks"] = ["IRB pending"]
            blocked_path = tmp_dir / "blocked.json"
            blocked_path.write_text(json.dumps(blocked), encoding="utf-8")
            res_blocked = run_script(
                self.SUITE,
                "generate_preregistration_scaffold.py",
                blocked_path,
                "-o",
                tmp_dir / "blocked.md",
            )
            self.assertEqual(res_blocked.returncode, 2)


class PeerReviewTests(unittest.TestCase):
    SUITE = "kdense-peer-review"

    @staticmethod
    def _ready_intake(assets: Path) -> dict:
        data = json.loads((assets / "review_intake_template.json").read_text(encoding="utf-8"))
        data["authorization"]["documented"] = True
        data["authorization"]["local_processing_authorized"] = True
        data["reviewer"]["human_accountable"] = True
        data["reviewer"]["conflict_status"] = "none_identified"
        data["venue_policy"]["checked"] = True
        data["venue_policy"]["peer_review_model"] = "double_anonymized"
        data["handling"]["deletion_or_retention_record_planned"] = True
        return data

    def test_common_import(self):
        common = load_module(MODULES / self.SUITE / "scripts" / "_common.py", "pr_common")
        self.assertTrue(hasattr(common, "ValidationError"))

    def test_validate_review_intake_and_generate_scaffold(self):
        assets = MODULES / self.SUITE / "assets"
        blocked = run_script(self.SUITE, "validate_review_intake.py", assets / "review_intake_template.json")
        self.assertEqual(blocked.returncode, 1)
        self.assertEqual(json.loads(blocked.stdout)["status"], "BLOCKED")

        missing = run_script(self.SUITE, "validate_review_intake.py", assets / "missing.json")
        self.assertEqual(missing.returncode, 2)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            ready_path = tmp_dir / "intake_ready.json"
            ready_path.write_text(json.dumps(self._ready_intake(assets)), encoding="utf-8")
            ok = run_script(self.SUITE, "validate_review_intake.py", ready_path)
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertEqual(json.loads(ok.stdout)["status"], "READY_FOR_LOCAL_REVIEW")

            out_md = tmp_dir / "review.md"
            gen_blocked = run_script(
                self.SUITE, "generate_review_scaffold.py", assets / "review_intake_template.json", "-o", out_md
            )
            self.assertEqual(gen_blocked.returncode, 2)

            gen_ok = run_script(self.SUITE, "generate_review_scaffold.py", ready_path, "-o", out_md)
            self.assertEqual(gen_ok.returncode, 0, gen_ok.stderr)
            text = out_md.read_text(encoding="utf-8")
            self.assertIn("# Comments to authors", text)
            self.assertIn("# Confidential comments to editor", text)

            gen_no_force = run_script(self.SUITE, "generate_review_scaffold.py", ready_path, "-o", out_md)
            self.assertEqual(gen_no_force.returncode, 2)

    def test_lint_review_positive_and_negative(self):
        assets = MODULES / self.SUITE / "assets"
        bad_tpl = run_script(self.SUITE, "lint_review.py", assets / "review_scaffold_template.md")
        self.assertEqual(bad_tpl.returncode, 1)
        self.assertEqual(json.loads(bad_tpl.stdout)["status"], "REVISION_REQUIRED")

        good_md = (
            "# Comments to authors\n\n"
            "### Major comment M1\n\n"
            "- Location: Section 4, Table 1\n"
            "- Observation: The ablation omits the matched parameter baseline.\n"
            "- Evidence or criterion: Matched compute and parameter budget is required for attribution.\n"
            "- Why it matters: Observed accuracy gains cannot be attributed to the proposed layer.\n"
            "- Requested action: Add the matched-parameter baseline under the same training schedule.\n\n"
            "# Confidential comments to editor\n\n"
            "No undeclared conflicts.\n"
        )
        bad_tone_md = (
            "# Comments to authors\n\n"
            "This sloppy paper is ridiculous and I recommend acceptance anyway.\n\n"
            "# Confidential comments to editor\n\n"
            "Done.\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            p_ok = tmp_dir / "good_review.md"
            p_bad = tmp_dir / "bad_review.md"
            p_ok.write_text(good_md, encoding="utf-8")
            p_bad.write_text(bad_tone_md, encoding="utf-8")

            r_ok = run_script(self.SUITE, "lint_review.py", p_ok)
            self.assertEqual(r_ok.returncode, 0, r_ok.stdout)
            self.assertEqual(json.loads(r_ok.stdout)["status"], "READY_FOR_HUMAN_REVIEW")

            r_bad = run_script(self.SUITE, "lint_review.py", p_bad)
            self.assertEqual(r_bad.returncode, 1)
            codes = {i["code"] for i in json.loads(r_bad.stdout)["errors"]}
            self.assertIn("ABUSIVE_OR_DISMISSIVE_LANGUAGE", codes)
            self.assertIn("EDITORIAL_DECISION_LANGUAGE", codes)

    def test_select_reporting_guidelines(self):
        assets = MODULES / self.SUITE / "assets"
        ok = run_script(
            self.SUITE,
            "select_reporting_guidelines.py",
            assets / "study_profile_template.json",
            "--coverage",
            assets / "reporting_checklist_template.csv",
        )
        self.assertEqual(ok.returncode, 0, ok.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            rows = list(csv.DictReader((assets / "reporting_checklist_template.csv").open(encoding="utf-8")))
            rows[0]["status"] = "reported"
            rows[0]["location"] = ""
            bad_csv = Path(tmp) / "bad_cov.csv"
            with bad_csv.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
            res = run_script(
                self.SUITE,
                "select_reporting_guidelines.py",
                assets / "study_profile_template.json",
                "--coverage",
                bad_csv,
            )
            self.assertEqual(res.returncode, 1)

    def test_validate_claim_evidence(self):
        assets = MODULES / self.SUITE / "assets"
        ok = run_script(self.SUITE, "validate_claim_evidence.py", assets / "claim_evidence_matrix_template.csv")
        self.assertEqual(ok.returncode, 0, ok.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            rows = list(csv.DictReader((assets / "claim_evidence_matrix_template.csv").open(encoding="utf-8")))
            rows[0]["support_level"] = "supported"
            rows[0]["evidence_ids"] = ""
            rows[0]["alignment_issue"] = "scope"
            bad_csv = Path(tmp) / "bad_matrix.csv"
            with bad_csv.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
            res = run_script(self.SUITE, "validate_claim_evidence.py", bad_csv)
            self.assertEqual(res.returncode, 1, res.stderr)
            codes = {i["code"] for i in json.loads(res.stdout)["errors"]}
            self.assertIn("SUPPORTED_CLAIM_HAS_NO_EVIDENCE", codes)
            self.assertIn("SUPPORTED_CLAIM_HAS_ALIGNMENT_ISSUE", codes)

    def test_audit_statistics_reproducibility(self):
        assets = MODULES / self.SUITE / "assets"
        ok = run_script(
            self.SUITE,
            "audit_statistics_reproducibility.py",
            assets / "statistical_reproducibility_template.json",
        )
        self.assertEqual(ok.returncode, 0, ok.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            bad = json.loads((assets / "statistical_reproducibility_template.json").read_text(encoding="utf-8"))
            bad["items"][0]["status"] = "verified_present"
            bad["items"][0]["evidence_locations"] = []
            bad_path = Path(tmp) / "bad_stats.json"
            bad_path.write_text(json.dumps(bad), encoding="utf-8")
            res = run_script(self.SUITE, "audit_statistics_reproducibility.py", bad_path)
            self.assertEqual(res.returncode, 1)

    def test_audit_citations(self):
        assets = MODULES / self.SUITE / "assets"
        ok = run_script(
            self.SUITE,
            "audit_citations.py",
            assets / "review_scaffold_template.md",
            assets / "citation_references_template.csv",
        )
        self.assertEqual(ok.returncode, 0, ok.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            bad_md = Path(tmp) / "cite_bad.md"
            bad_md.write_text("# Comments to authors\n\nSee missing ref [@NOPE-2026].\n", encoding="utf-8")
            res = run_script(self.SUITE, "audit_citations.py", bad_md, assets / "citation_references_template.csv")
            self.assertEqual(res.returncode, 1)
            self.assertIn("CITATION_WITHOUT_REFERENCE", {i["code"] for i in json.loads(res.stdout)["errors"]})


class ScholarEvaluationTests(unittest.TestCase):
    SUITE = "kdense-scholar-evaluation"

    @staticmethod
    def _rated_evaluation(
        assets: Path,
        *,
        eval_id: str = "EVAL-RATED-001",
        work_id: str = "WORK-RATED-001",
        scores: dict[str, int] | None = None,
    ) -> dict:
        data = json.loads((assets / "evaluation_template.json").read_text(encoding="utf-8"))
        data["evaluation_id"] = eval_id
        data["work_id"] = work_id
        ev_map = {
            "question_scope": "EVIDENCE-SYNTHETIC-QUESTION",
            "literature_contribution": "EVIDENCE-SYNTHETIC-LITERATURE",
            "method_design": "EVIDENCE-SYNTHETIC-METHOD",
            "analysis_claims": "EVIDENCE-SYNTHETIC-ANALYSIS",
            "transparency_integrity": "EVIDENCE-SYNTHETIC-TRANSPARENCY",
        }
        scores = scores or {k: 3 for k in ev_map}
        for rating in data["ratings"]:
            cid = rating["criterion_id"]
            rating["status"] = "rated"
            rating["score"] = scores[cid]
            rating["uncertainty"] = 0.5
            rating["evidence_ids"] = [ev_map[cid]]
            rating["rationale_ref"] = f"LOCAL-RATIONALE-{cid.upper()}"
        return data

    def test_common_import(self):
        common = load_module(MODULES / self.SUITE / "scripts" / "_common.py", "se_common")
        self.assertTrue(hasattr(common, "ValidationError"))

    def test_validate_rubric(self):
        assets = MODULES / self.SUITE / "assets"
        ok = run_script(self.SUITE, "validate_rubric.py", "--rubric", assets / "rubric_template.json")
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertEqual(json.loads(ok.stdout)["status"], "valid")

        with tempfile.TemporaryDirectory() as tmp:
            bad = json.loads((assets / "rubric_template.json").read_text(encoding="utf-8"))
            bad["criteria"][0]["weight"] = 0.99
            bad["construct"]["definition"] = "Uses journal impact factor as proxy."
            bad_path = Path(tmp) / "bad_rubric.json"
            bad_path.write_text(json.dumps(bad), encoding="utf-8")
            res = run_script(self.SUITE, "validate_rubric.py", "--rubric", bad_path)
            self.assertEqual(res.returncode, 2)
            self.assertEqual(json.loads(res.stdout)["status"], "invalid")

    def test_calculate_scores(self):
        assets = MODULES / self.SUITE / "assets"
        tpl = run_script(
            self.SUITE,
            "calculate_scores.py",
            "--rubric",
            assets / "rubric_template.json",
            "--evaluation",
            assets / "evaluation_template.json",
        )
        self.assertEqual(tpl.returncode, 0, tpl.stderr)
        self.assertIsNone(json.loads(tpl.stdout)["aggregates"]["normalized_score"])

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            rated = self._rated_evaluation(assets)
            p_ok = tmp_dir / "eval_ok.json"
            p_ok.write_text(json.dumps(rated), encoding="utf-8")
            res_ok = run_script(
                self.SUITE, "calculate_scores.py", "--rubric", assets / "rubric_template.json", "--evaluation", p_ok
            )
            self.assertEqual(res_ok.returncode, 0, res_ok.stderr)
            agg = json.loads(res_ok.stdout)["aggregates"]
            self.assertAlmostEqual(agg["normalized_score"], 3.0)

            bad = copy.deepcopy(rated)
            bad["rubric_id"] = "WRONG-RUBRIC"
            p_bad = tmp_dir / "eval_bad.json"
            p_bad.write_text(json.dumps(bad), encoding="utf-8")
            res_bad = run_script(
                self.SUITE, "calculate_scores.py", "--rubric", assets / "rubric_template.json", "--evaluation", p_bad
            )
            self.assertEqual(res_bad.returncode, 2)

    def test_check_traceability(self):
        assets = MODULES / self.SUITE / "assets"
        ok = run_script(
            self.SUITE,
            "check_traceability.py",
            "--rubric",
            assets / "rubric_template.json",
            "--evaluation",
            assets / "evaluation_template.json",
            "--evidence",
            assets / "evidence_manifest_template.json",
        )
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertEqual(json.loads(ok.stdout)["status"], "pass")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            rated = self._rated_evaluation(assets, eval_id="EVALUATION-SYNTHETIC-001", work_id="WORK-SYNTHETIC-001")
            rated["ratings"][0]["evidence_ids"] = ["MISSING-EVIDENCE"]
            p_eval = tmp_dir / "eval.json"
            p_eval.write_text(json.dumps(rated), encoding="utf-8")

            ev = json.loads((assets / "evidence_manifest_template.json").read_text(encoding="utf-8"))
            ev["evidence"][1]["access_status"] = "unavailable"
            ev["evidence"][1]["verification_status"] = "unverified"
            p_ev = tmp_dir / "ev.json"
            p_ev.write_text(json.dumps(ev), encoding="utf-8")

            res_bad = run_script(
                self.SUITE,
                "check_traceability.py",
                "--rubric",
                assets / "rubric_template.json",
                "--evaluation",
                p_eval,
                "--evidence",
                p_ev,
            )
            self.assertEqual(res_bad.returncode, 2)
            payload = json.loads(res_bad.stdout)
            self.assertEqual(payload["status"], "fail")
            codes = {i["code"] for i in payload["issues"]}
            self.assertTrue({"EVIDENCE_UNAVAILABLE", "EVIDENCE_UNVERIFIED", "EVIDENCE_REFERENCE_UNRESOLVED"}.issubset(codes))

    def test_summarize_agreement(self):
        assets = MODULES / self.SUITE / "assets"
        ok = run_script(
            self.SUITE,
            "summarize_agreement.py",
            "--rubric",
            assets / "rubric_template.json",
            "--ratings",
            assets / "ratings_template.csv",
        )
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertIn("exact_agreement_rate", json.loads(ok.stdout)["overall"])

        with tempfile.TemporaryDirectory() as tmp:
            rows = list(csv.DictReader((assets / "ratings_template.csv").open(encoding="utf-8")))
            single_rater = [r for r in rows if r["rater_id"] == rows[0]["rater_id"]]
            bad_csv = Path(tmp) / "one_rater.csv"
            with bad_csv.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(single_rater)
            res = run_script(
                self.SUITE,
                "summarize_agreement.py",
                "--rubric",
                assets / "rubric_template.json",
                "--ratings",
                bad_csv,
            )
            self.assertEqual(res.returncode, 2)

    def test_weight_sensitivity(self):
        assets = MODULES / self.SUITE / "assets"
        e1 = self._rated_evaluation(
            assets,
            eval_id="EVAL-1",
            work_id="WORK-1",
            scores={
                "question_scope": 4,
                "literature_contribution": 2,
                "method_design": 4,
                "analysis_claims": 2,
                "transparency_integrity": 2,
            },
        )
        e2 = self._rated_evaluation(
            assets,
            eval_id="EVAL-2",
            work_id="WORK-2",
            scores={
                "question_scope": 2,
                "literature_contribution": 4,
                "method_design": 2,
                "analysis_claims": 4,
                "transparency_integrity": 3,
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            p1 = tmp_dir / "e1.json"
            p2 = tmp_dir / "e2.json"
            p1.write_text(json.dumps(e1), encoding="utf-8")
            p2.write_text(json.dumps(e2), encoding="utf-8")
            res_ok = run_script(
                self.SUITE,
                "weight_sensitivity.py",
                "--rubric",
                assets / "rubric_template.json",
                "--evaluation",
                p1,
                "--evaluation",
                p2,
                "--delta",
                "0.4",
            )
            self.assertEqual(res_ok.returncode, 0, res_ok.stderr)
            self.assertTrue(json.loads(res_ok.stdout)["rank_instability_detected"])

            res_one = run_script(
                self.SUITE,
                "weight_sensitivity.py",
                "--rubric",
                assets / "rubric_template.json",
                "--evaluation",
                p1,
            )
            self.assertEqual(res_one.returncode, 2)

            res_missing = run_script(
                self.SUITE,
                "weight_sensitivity.py",
                "--rubric",
                assets / "rubric_template.json",
                "--evaluation",
                p1,
                "--evaluation",
                assets / "evaluation_template.json",
            )
            self.assertEqual(res_missing.returncode, 2)

    def test_check_process(self):
        assets = MODULES / self.SUITE / "assets"
        blocked = run_script(self.SUITE, "check_process.py", "--process", assets / "process_checklist_template.json")
        self.assertEqual(blocked.returncode, 2)
        self.assertEqual(json.loads(blocked.stdout)["status"], "blocked")

        complete = json.loads((assets / "process_checklist_template.json").read_text(encoding="utf-8"))
        for key, section in complete.items():
            if isinstance(section, dict):
                for k, v in list(section.items()):
                    if isinstance(v, bool):
                        section[k] = True
                    elif isinstance(v, str) and not v:
                        section[k] = f"LOCAL-REF-{key.upper()}-{k.upper()}"
        with tempfile.TemporaryDirectory() as tmp:
            p_ok = Path(tmp) / "process_ok.json"
            p_ok.write_text(json.dumps(complete), encoding="utf-8")
            res_ok = run_script(self.SUITE, "check_process.py", "--process", p_ok)
            self.assertEqual(res_ok.returncode, 0, res_ok.stdout)
            self.assertEqual(json.loads(res_ok.stdout)["status"], "complete_for_low_stakes_process")

    def test_generate_report_scaffold(self):
        assets = MODULES / self.SUITE / "assets"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            out_json = tmp_dir / "report.json"
            ok = run_script(
                self.SUITE,
                "generate_report_scaffold.py",
                "--rubric",
                assets / "rubric_template.json",
                "--evaluation",
                assets / "evaluation_template.json",
                "--output",
                out_json,
            )
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertEqual(json.loads(out_json.read_text(encoding="utf-8"))["work_id"], "WORK-SYNTHETIC-001")

            tr_res = run_script(
                self.SUITE,
                "check_traceability.py",
                "--rubric",
                assets / "rubric_template.json",
                "--evaluation",
                assets / "evaluation_template.json",
                "--evidence",
                assets / "evidence_manifest_template.json",
            )
            tr_data = json.loads(tr_res.stdout)
            tr_data["work_id"] = "OTHER-WORK"
            bad_tr = tmp_dir / "bad_trace.json"
            bad_tr.write_text(json.dumps(tr_data), encoding="utf-8")
            res_bad = run_script(
                self.SUITE,
                "generate_report_scaffold.py",
                "--rubric",
                assets / "rubric_template.json",
                "--evaluation",
                assets / "evaluation_template.json",
                "--traceability",
                bad_tr,
            )
            self.assertEqual(res_bad.returncode, 2)


class LiteratureReviewTests(unittest.TestCase):
    SUITE = "kdense-literature-review"

    def test_search_databases_dedup_filter_rank_format_and_errors(self):
        records = [
            {
                "title": "Paper A",
                "authors": "Smith, A.",
                "first_author": "Smith",
                "year": 2024,
                "source": "OpenAlex",
                "doi": "https://doi.org/10.1000/AAA",
                "citations": 12,
                "relevance_score": 0.9,
            },
            {
                "title": "Paper A Duplicate",
                "authors": "Smith, A.",
                "first_author": "Smith",
                "year": 2024,
                "source": "Crossref",
                "doi": "10.1000/aaa",
                "citations": 99,
            },
            {
                "title": "Paper B",
                "authors": "Doe, J.",
                "first_author": "Doe",
                "year": 2023,
                "source": "arXiv",
                "citations": 30,
                "relevance_score": 0.7,
            },
            {
                "title": "paper b",
                "authors": "Doe, J.",
                "first_author": "Doe",
                "year": 2023,
                "source": "arXiv",
                "citations": 1,
            },
            {
                "title": "Old Paper",
                "authors": "Old, O.",
                "first_author": "Old",
                "year": 2018,
                "source": "arXiv",
                "citations": 500,
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            in_json = tmp_dir / "results.json"
            in_json.write_text(json.dumps(records), encoding="utf-8")
            out_bib = tmp_dir / "out.bib"
            res = run_script(
                self.SUITE,
                "search_databases.py",
                in_json,
                "--deduplicate",
                "--year-start",
                "2022",
                "--year-end",
                "2025",
                "--rank",
                "citations",
                "--format",
                "bibtex",
                "--summary",
                "--output",
                out_bib,
            )
            self.assertEqual(res.returncode, 0, res.stderr)
            bib = out_bib.read_text(encoding="utf-8")
            self.assertIn("Paper B", bib)
            self.assertIn("Paper A", bib)
            self.assertNotIn("Old Paper", bib)
            self.assertLess(bib.index("Paper B"), bib.index("Paper A"))
            self.assertIn('"total_results": 2', res.stderr)

            bad_env = tmp_dir / "envelope.json"
            bad_env.write_text(json.dumps({"results": records}), encoding="utf-8")
            res_env = run_script(self.SUITE, "search_databases.py", bad_env)
            self.assertEqual(res_env.returncode, 1)

            res_yr = run_script(
                self.SUITE, "search_databases.py", in_json, "--year-start", "2025", "--year-end", "2020"
            )
            self.assertEqual(res_yr.returncode, 2)

    def test_verify_citations_doi_extraction_and_requests_mocked_paths(self):
        vc = load_module(MODULES / self.SUITE / "scripts" / "verify_citations.py", "kdense_vc")
        self.assertEqual(vc.normalize_doi("https://dx.doi.org/10.1000/XYZ"), "10.1000/xyz")
        verifier = vc.CitationVerifier(email="test@example.org")
        extracted = verifier.extract_dois(
            "See (https://doi.org/10.1000/abc(1)def.) and [doi:10.1000/ghi] and 10.1000/abc(1)def."
        )
        self.assertEqual(extracted, ["10.1000/abc(1)def", "10.1000/ghi"])

        class FakeResp:
            def __init__(self, status_code, payload, headers=None):
                self.status_code = status_code
                self._payload = payload
                self.headers = headers or {}

            def json(self):
                return self._payload

        def fake_get(url, timeout=20, **kwargs):
            if "api/handles/10.1000/ok" in url:
                return FakeResp(200, {"responseCode": 1, "handle": "10.1000/ok"})
            if "api.crossref.org/works/10.1000/ok" in url:
                return FakeResp(
                    200,
                    {
                        "message": {
                            "DOI": "10.1000/OK",
                            "title": ["Verified Paper"],
                            "author": [{"family": "Turing", "given": "Alan"}],
                            "published-print": {"date-parts": [[2024]]},
                            "container-title": ["Nature"],
                        }
                    },
                )
            if "api/handles/10.1000/missing" in url:
                return FakeResp(404, {"responseCode": 100, "handle": "10.1000/missing"})
            raise vc._REQUEST_EXCEPTIONS[0]("offline network")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            md_ok = tmp_dir / "ok.md"
            md_ok.write_text("Citing 10.1000/ok.", encoding="utf-8")
            md_mix = tmp_dir / "mix.md"
            md_mix.write_text("Missing 10.1000/missing and offline 10.1000/err.", encoding="utf-8")
            md_zero = tmp_dir / "zero.md"
            md_zero.write_text("No DOIs in this text.", encoding="utf-8")

            with mock.patch.object(vc.time, "sleep"):
                if verifier.session is not None:
                    with mock.patch.object(verifier.session, "get", side_effect=fake_get):
                        out_ok = tmp_dir / "ok_report.json"
                        with mock.patch.object(sys, "argv", ["verify_citations.py", str(md_ok), "-o", str(out_ok)]), redirect_stdout(io.StringIO()):
                            with mock.patch.object(vc, "CitationVerifier", return_value=verifier):
                                with self.assertRaises(SystemExit) as cm_ok:
                                    vc.main()
                                self.assertEqual(cm_ok.exception.code, 0)
                        rep_ok = json.loads(out_ok.read_text(encoding="utf-8"))
                        self.assertEqual(rep_ok["verified"], ["10.1000/ok"])
                        self.assertEqual(rep_ok["metadata"]["10.1000/ok"]["title"], "Verified Paper")

                        out_mix = tmp_dir / "mix_report.json"
                        with mock.patch.object(sys, "argv", ["verify_citations.py", str(md_mix), "-o", str(out_mix)]), redirect_stdout(io.StringIO()):
                            with mock.patch.object(vc, "CitationVerifier", return_value=verifier):
                                with self.assertRaises(SystemExit) as cm_mix:
                                    vc.main()
                                self.assertEqual(cm_mix.exception.code, 1)
                        rep_mix = json.loads(out_mix.read_text(encoding="utf-8"))
                        self.assertEqual(rep_mix["missing"], ["10.1000/missing"])
                        self.assertEqual(rep_mix["inconclusive"], ["10.1000/err"])

            out_zero = tmp_dir / "zero_report.json"
            res_zero = run_script(self.SUITE, "verify_citations.py", md_zero, "-o", out_zero)
            self.assertEqual(res_zero.returncode, 0, res_zero.stderr)
            self.assertEqual(json.loads(out_zero.read_text(encoding="utf-8"))["total_dois"], 0)

    def test_verify_citations_stdlib_urllib_fallback_path(self):
        vc = load_module(MODULES / self.SUITE / "scripts" / "verify_citations.py", "kdense_vc_stdlib")

        class FakeUrlopenResp:
            def __init__(self, status, payload, headers=None):
                self.status = status
                self._body = json.dumps(payload).encode("utf-8")
                self.headers = headers or {}

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(req, timeout=20):
            url = req.full_url
            if req.get_method() == "HEAD":
                return FakeUrlopenResp(200, {})
            if "api/handles/10.1000/stdlib" in url:
                return FakeUrlopenResp(200, {"responseCode": 1, "handle": "10.1000/stdlib"})
            if "api.crossref.org/works/10.1000/stdlib" in url:
                return FakeUrlopenResp(
                    200,
                    {"message": {"DOI": "10.1000/stdlib", "title": ["Stdlib Paper"], "author": []}},
                )
            if "api/handles/10.1000/notfound" in url:
                raise urllib.error.HTTPError(
                    url,
                    404,
                    "Not Found",
                    {},
                    io.BytesIO(json.dumps({"responseCode": 100, "handle": "10.1000/notfound"}).encode("utf-8")),
                )
            raise urllib.error.URLError("offline stdlib error")

        with mock.patch.object(vc, "_HAS_REQUESTS", False), mock.patch.object(vc, "requests", None):
            verifier = vc.CitationVerifier(email="stdlib@example.org")
            self.assertIsNone(verifier.session)
            with mock.patch.object(vc.urllib.request, "urlopen", side_effect=fake_urlopen), mock.patch.object(vc.time, "sleep"):
                ok, meta = verifier.verify_doi("10.1000/stdlib")
                self.assertTrue(ok)
                self.assertEqual(meta["status"], "registered")
                self.assertEqual(meta["title"], "Stdlib Paper")

                miss_ok, miss_meta = verifier.verify_doi("10.1000/notfound")
                self.assertFalse(miss_ok)
                self.assertEqual(miss_meta["status"], "missing")

                err_ok, err_meta = verifier.verify_doi("10.1000/offline")
                self.assertFalse(err_ok)
                self.assertEqual(err_meta["status"], "inconclusive")

                head_ok, code = verifier.verify_url("https://example.org")
                self.assertTrue(head_ok)
                self.assertEqual(code, 200)

    def test_verify_citations_subprocess_blocked_requests_incomplete_read_and_bad_date_parts(self):
        script_path = MODULES / self.SUITE / "scripts" / "verify_citations.py"
        harness_code = """\
import builtins
import importlib.abc
import json
import runpy
import sys
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

sys.modules.pop("requests", None)

class _BlockRequestsFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == "requests" or fullname.startswith("requests."):
            raise ImportError(f"blocked {fullname}")
        return None

sys.meta_path.insert(0, _BlockRequestsFinder())
_orig_import = builtins.__import__
def _blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "requests" or name.startswith("requests."):
        raise ImportError(f"blocked {name}")
    return _orig_import(name, globals, locals, fromlist, level)
builtins.__import__ = _blocked_import

class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, format, *args):
        pass
    def do_GET(self):
        if self.path.startswith("/api/handles/10.1000/trunc"):
            self.wfile.write(
                b'HTTP/1.1 200 OK\\r\\nContent-Length: 1000\\r\\nConnection: close\\r\\n\\r\\n{"a":'
            )
            self.wfile.flush()
            return
        if self.path.startswith("/api/handles/10.1000/baddate"):
            body = json.dumps({"responseCode": 1, "handle": "10.1000/baddate"}).encode("utf-8")
        elif self.path.startswith("/works/10.1000/baddate"):
            body = json.dumps({
                "message": {
                    "DOI": "10.1000/baddate",
                    "title": ["Malformed Date Paper"],
                    "author": [{"family": "Ada"}],
                    "published-print": {"date-parts": [123]},
                }
            }).encode("utf-8")
        else:
            body = b"{}"
            self.send_response(404)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
port = server.server_address[1]
Thread(target=server.serve_forever, daemon=True).start()

_orig_urlopen = urllib.request.urlopen
def _rewriting_urlopen(req, *args, **kwargs):
    url = req.full_url if isinstance(req, urllib.request.Request) else str(req)
    for prefix in ("https://doi.org", "https://api.crossref.org"):
        if url.startswith(prefix):
            url = f"http://127.0.0.1:{port}" + url[len(prefix):]
            break
    if isinstance(req, urllib.request.Request):
        req = urllib.request.Request(url, data=req.data, headers=dict(req.headers), method=req.get_method())
    else:
        req = url
    return _orig_urlopen(req, *args, **kwargs)

urllib.request.urlopen = _rewriting_urlopen
time.sleep = lambda _s: None

target_script, md_file, out_file = sys.argv[1], sys.argv[2], sys.argv[3]
sys.argv = [target_script, md_file, "-o", out_file]
try:
    runpy.run_path(target_script, run_name="__main__")
finally:
    assert "requests" not in sys.modules
    server.shutdown()
    server.server_close()
"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            harness = tmp_dir / "harness.py"
            harness.write_text(harness_code, encoding="utf-8")

            md_trunc = tmp_dir / "trunc.md"
            md_trunc.write_text("Truncated DOI 10.1000/trunc.", encoding="utf-8")
            out_trunc = tmp_dir / "trunc_report.json"
            res_trunc = subprocess.run(
                [sys.executable, str(harness), str(script_path), str(md_trunc), str(out_trunc)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(res_trunc.returncode, 1, res_trunc.stderr)
            self.assertNotIn("Traceback", res_trunc.stderr)
            self.assertTrue(out_trunc.is_file())
            rep_trunc = json.loads(out_trunc.read_text(encoding="utf-8"))
            self.assertEqual(rep_trunc["inconclusive"], ["10.1000/trunc"])
            self.assertEqual(rep_trunc["errors"]["10.1000/trunc"]["status"], "inconclusive")
            self.assertIn("IncompleteRead", rep_trunc["errors"]["10.1000/trunc"]["error"])

            md_baddate = tmp_dir / "baddate.md"
            md_baddate.write_text("Bad date DOI 10.1000/baddate.", encoding="utf-8")
            out_baddate = tmp_dir / "baddate_report.json"
            res_baddate = subprocess.run(
                [sys.executable, str(harness), str(script_path), str(md_baddate), str(out_baddate)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(res_baddate.returncode, 0, res_baddate.stderr)
            self.assertNotIn("Traceback", res_baddate.stderr)
            self.assertNotIn("TypeError", res_baddate.stderr)
            self.assertTrue(out_baddate.is_file())
            rep_baddate = json.loads(out_baddate.read_text(encoding="utf-8"))
            self.assertEqual(rep_baddate["verified"], ["10.1000/baddate"])
            self.assertEqual(rep_baddate["metadata"]["10.1000/baddate"]["status"], "registered")
            self.assertEqual(rep_baddate["metadata"]["10.1000/baddate"]["title"], "Malformed Date Paper")
            self.assertEqual(rep_baddate["metadata"]["10.1000/baddate"]["year"], "")


if __name__ == "__main__":
    unittest.main()
