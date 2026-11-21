"""Tests for claim_audit.py doc-vs-code consistency auditing."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "research-scientist"
SCRIPT = SKILL_ROOT / "scripts" / "claim_audit.py"

spec = importlib.util.spec_from_file_location("claim_audit", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _make_temp_skill(base: Path) -> Path:
    sroot = base / "research-scientist"
    (sroot / "scripts").mkdir(parents=True)
    (sroot / "references").mkdir(parents=True)
    (sroot / "SKILL.md").write_text(
        "---\n"
        "name: research-scientist\n"
        'description: "Queries OpenAlex and Europe PMC."\n'
        "---\n\n"
        "# Skill\n\n"
        "Run `scripts/tool.py --valid`.\n",
        encoding="utf-8",
    )
    (sroot / "scripts" / "tool.py").write_text(
        "import argparse\n"
        'API = "https://api.openalex.org/works"\n'
        'EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"\n'
        "STATUSES = ('ok_status',)\n"
        "p = argparse.ArgumentParser()\n"
        "p.add_argument('--valid')\n",
        encoding="utf-8",
    )
    return sroot


class ClaimAuditTests(unittest.TestCase):
    def test_live_research_scientist_self_audit_passes(self):
        proc = run_cli("--root", str(SKILL_ROOT), "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["status"], "passed")
        self.assertEqual(data["finding_count"], 0)
        self.assertNotIn("README.md", data["files_audited"])

        direct = module.audit_skill(SKILL_ROOT)
        self.assertEqual(direct["finding_count"], 0)
        fp = direct["skill_footprint"]
        self.assertLessEqual(fp["lines"], 95)
        self.assertLessEqual(fp["est_tokens"], 1100)
        self.assertLessEqual(fp["frontmatter_est_tokens"], 140)

        compact_proc = run_cli("--root", str(SKILL_ROOT), "--json", "--compact")
        self.assertEqual(compact_proc.returncode, 0, compact_proc.stdout + compact_proc.stderr)
        cmp_data = json.loads(compact_proc.stdout)
        self.assertTrue(cmp_data["compact"])
        self.assertLessEqual(len(cmp_data["files_audited"]), 10)
        self.assertLessEqual(len(cmp_data["scripts_indexed"]), 10)
        self.assertGreater(cmp_data["total_scripts_indexed"], 10)

    def test_skill_bloat_and_frontmatter_bloat_detected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sroot = _make_temp_skill(Path(tmpdir))
            big_body = "\n".join(f"Rule line {i} keeps checking receipts." for i in range(130))
            (sroot / "SKILL.md").write_text(
                "---\nname: test\ndescription: \"Test\"\n---\n\n" + big_body + "\n",
                encoding="utf-8",
            )
            res_bloat = run_cli("--root", str(sroot), "--json")
            self.assertEqual(res_bloat.returncode, 1)
            kinds = {f["kind"] for f in json.loads(res_bloat.stdout)["findings"]}
            self.assertIn("skill-bloat", kinds)

            big_desc = " ".join(f"word{i}" for i in range(130))
            (sroot / "SKILL.md").write_text(
                f"---\nname: test\ndescription: \"{big_desc}\"\n---\n\n# Short\nRun `scripts/tool.py --valid`.\n",
                encoding="utf-8",
            )
            res_fm = run_cli("--root", str(sroot), "--json")
            self.assertEqual(res_fm.returncode, 1)
            kinds_fm = {f["kind"] for f in json.loads(res_fm.stdout)["findings"]}
            self.assertIn("frontmatter-bloat", kinds_fm)

    def test_missing_script_detected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sroot = _make_temp_skill(Path(tmpdir))
            (sroot / "SKILL.md").write_text(
                "---\nname: test\ndescription: \"Test\"\n---\nRun `scripts/does_not_exist.py`.\n",
                encoding="utf-8",
            )
            (sroot / "references" / "ref.md").write_text(
                "Invoke `modules/mod/scripts/missing.py`.\n"
                "Upstream note cites `skills/literature-review/scripts/verify_citations.py`.\n",
                encoding="utf-8",
            )
            res = module.audit_skill(sroot)
            self.assertEqual(res["status"], "failed")
            tokens = {(f["kind"], f["token"]) for f in res["findings"]}
            self.assertIn(("missing-script", "scripts/does_not_exist.py"), tokens)
            self.assertIn(("missing-script", "modules/mod/scripts/missing.py"), tokens)
            self.assertNotIn(("missing-script", "skills/literature-review/scripts/verify_citations.py"), tokens)

    def test_missing_flag_detected_including_multiline_and_modules(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sroot = _make_temp_skill(Path(tmpdir))
            mod_scripts = sroot / "modules" / "pkg" / "scripts"
            mod_scripts.mkdir(parents=True)
            (mod_scripts / "mod.py").write_text(
                "import argparse\n"
                "p = argparse.ArgumentParser()\n"
                "p.add_argument('--ok')\n",
                encoding="utf-8",
            )
            (sroot / "references" / "good.md").write_text(
                "python3 scripts/tool.py --valid --help\n"
                "python3 modules/pkg/scripts/mod.py \\\n"
                "  --ok\n",
                encoding="utf-8",
            )
            self.assertEqual(module.audit_skill(sroot)["finding_count"], 0)

            (sroot / "references" / "bad.md").write_text(
                "python3 scripts/tool.py --bogus\n"
                "python3 modules/pkg/scripts/mod.py \\\n"
                "  --bad-mod-flag\n",
                encoding="utf-8",
            )
            res = module.audit_skill(sroot)
            self.assertEqual(res["status"], "failed")
            flag_tokens = {(f["kind"], f["token"]) for f in res["findings"]}
            self.assertIn(("missing-flag", "--bogus"), flag_tokens)
            self.assertIn(("missing-flag", "--bad-mod-flag"), flag_tokens)

    def test_missing_host_and_service_detected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sroot = _make_temp_skill(Path(tmpdir))
            (sroot / "SKILL.md").write_text(
                "---\n"
                "name: test\n"
                'description: "Queries Unpaywall."\n'
                "compatibility: api.unknownhost.org\n"
                "---\n\n"
                "See https://arxiv.org/abs/2603.10303 and https://github.com/org/repo and https://www.prisma-statement.org/.\n",
                encoding="utf-8",
            )
            (sroot / "references" / "guide.md").write_text(
                "Calls api.phantom.org for records.\n",
                encoding="utf-8",
            )
            res = module.audit_skill(sroot)
            kinds_tokens = {(f["kind"], f["token"]) for f in res["findings"]}
            self.assertIn(("missing-host", "api.unknownhost.org"), kinds_tokens)
            self.assertIn(("missing-service", "unpaywall"), kinds_tokens)
            self.assertIn(("missing-host", "api.phantom.org"), kinds_tokens)
            # Citation URLs should NOT be flagged
            self.assertFalse(any(t in {"arxiv.org", "github.com", "www.prisma-statement.org"} for _, t in kinds_tokens))

    def test_missing_status_token_detected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sroot = _make_temp_skill(Path(tmpdir))
            (sroot / "references" / "guide.md").write_text(
                "| Status | Meaning |\n"
                "|---|---|\n"
                "| `phantom_status` | Not in scripts |\n",
                encoding="utf-8",
            )
            res = module.audit_skill(sroot)
            self.assertIn(("missing-status", "phantom_status"), {(f["kind"], f["token"]) for f in res["findings"]})

            (sroot / "scripts" / "statuses.py").write_text(
                "STATUSES = ('phantom_status',)\n",
                encoding="utf-8",
            )
            self.assertEqual(module.audit_skill(sroot)["finding_count"], 0)

    def test_optional_readme_flag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            sroot = _make_temp_skill(base)
            bad_readme = base / "BAD_README.md"
            bad_readme.write_text("Run `scripts/nonexistent.py --nope`.\n", encoding="utf-8")
            good_readme = base / "README.md"
            good_readme.write_text("Run `scripts/tool.py --valid`.\n", encoding="utf-8")

            self.assertEqual(run_cli("--root", str(sroot)).returncode, 0)
            self.assertEqual(run_cli("--root", str(sroot), "--readme", str(bad_readme)).returncode, 1)
            self.assertEqual(run_cli("--root", str(sroot), "--readme", str(good_readme)).returncode, 0)

    def test_json_file_output_and_invalid_root_exit_2(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            sroot = _make_temp_skill(base)
            out_json = base / "audit.json"
            proc = run_cli("--root", str(sroot), "--json", str(out_json))
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertTrue(out_json.is_file())
            parsed = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(parsed["status"], "passed")

            bad_proc = run_cli("--root", str(base / "does_not_exist"))
            self.assertEqual(bad_proc.returncode, 2)

    def test_missing_progressive_disclosure_reference_detected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sroot = _make_temp_skill(Path(tmpdir))
            (sroot / "references" / "valid-guide.md").write_text("# Valid Guide\n", encoding="utf-8")
            (sroot / "SKILL.md").write_text(
                "---\nname: test\ndescription: \"Test\"\n---\n\n"
                "See [valid](references/valid-guide.md#sec) and [broken](references/nonexistent_guide.md).\n",
                encoding="utf-8",
            )
            res = module.audit_skill(sroot)
            self.assertEqual(res["status"], "failed")
            tokens = {(f["kind"], f["token"]) for f in res["findings"]}
            self.assertIn(("missing-reference", "references/nonexistent_guide.md"), tokens)
            self.assertNotIn(("missing-reference", "references/valid-guide.md"), tokens)

    def test_reference_traversal_outside_root_rejected_while_intra_root_relative_allowed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            sroot = _make_temp_skill(base)
            (sroot / "references" / "a.md").write_text("See [b](../references/b.md).\n", encoding="utf-8")
            (sroot / "references" / "b.md").write_text("# B\n", encoding="utf-8")
            # Outside file that matches ../references/outside.md from SKILL.md
            outside_refs = base / "references"
            outside_refs.mkdir(parents=True)
            (outside_refs / "outside.md").write_text("# Outside\n", encoding="utf-8")

            # Positive: references/a.md linking ../references/b.md within root passes cleanly
            self.assertEqual(module.audit_skill(sroot)["finding_count"], 0)

            # Negative: SKILL.md linking ../references/b.md (escapes root then re-enters via norm_ref)
            # and ../references/outside.md (exists outside root) must both fail
            (sroot / "SKILL.md").write_text(
                "---\nname: test\ndescription: \"Test\"\n---\n\n"
                "See [escaped](../references/b.md) and [outside](../references/outside.md).\n",
                encoding="utf-8",
            )
            res = module.audit_skill(sroot)
            self.assertEqual(res["status"], "failed")
            ref_findings = [(f["kind"], f["token"]) for f in res["findings"] if f["kind"] == "missing-reference"]
            self.assertIn(("missing-reference", "references/b.md"), ref_findings)
            self.assertIn(("missing-reference", "references/outside.md"), ref_findings)

    def test_script_traversal_and_outside_symlink_blocked_while_intra_root_allowed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            outside_scripts = base / "scripts"
            outside_scripts.mkdir(parents=True)
            (outside_scripts / "tool.py").write_text("print('outside')\n", encoding="utf-8")
            (base / "outside_sym.py").write_text("print('sym_outside')\n", encoding="utf-8")

            sroot = _make_temp_skill(base)
            (sroot / "references" / "valid.md").write_text(
                "Run `../scripts/tool.py --valid`.\n",
                encoding="utf-8",
            )
            (sroot / "scripts" / "sym_out.py").symlink_to(base / "outside_sym.py")

            # collect_scripts must ignore outside-root symlink
            collected = module.collect_scripts(sroot)
            self.assertIn("scripts/tool.py", collected)
            self.assertNotIn("scripts/sym_out.py", collected)

            # Positive: intra-root ../scripts/tool.py from references/valid.md passes cleanly
            self.assertEqual(module.audit_skill(sroot)["finding_count"], 0)

            # Negative 1: SKILL.md traversal & symlink escapes must fail
            for bad_line, expected_kind in (
                ("Run `../scripts/tool.py --valid`.\n", "missing-script"),
                ("Run `../../scripts/tool.py --valid`.\n", "missing-script"),
                ("Run `scripts/sym_out.py`.\n", "missing-script"),
                ("See [reenter](../research-scientist/references/valid.md).\n", "missing-reference"),
            ):
                (sroot / "SKILL.md").write_text(
                    "---\nname: test\ndescription: \"Test\"\n---\n\n" + bad_line,
                    encoding="utf-8",
                )
                res = module.audit_skill(sroot)
                self.assertEqual(res["status"], "failed", (bad_line, res))
                self.assertIn(expected_kind, {f["kind"] for f in res["findings"]}, (bad_line, res))

            # Negative 2: references/bad.md ../../scripts/tool.py escaping root fails
            (sroot / "SKILL.md").write_text(
                "---\nname: test\ndescription: \"Test\"\n---\n\nRun `scripts/tool.py --valid`.\n",
                encoding="utf-8",
            )
            (sroot / "references" / "bad.md").write_text(
                "Run `../../scripts/tool.py --valid`.\n",
                encoding="utf-8",
            )
            res_ref = module.audit_skill(sroot)
            self.assertEqual(res_ref["status"], "failed", res_ref)
            self.assertTrue(
                any(f["kind"] == "missing-script" and f["file"] == "references/bad.md" for f in res_ref["findings"]),
                res_ref,
            )

    def test_mid_path_traversal_nested_subpath_and_non_rs_root_prefix(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            (base / "outside.py").write_text("print('outside')\n", encoding="utf-8")
            (base / "outside.md").write_text("# Outside\n", encoding="utf-8")
            sroot = _make_temp_skill(base)
            sub_dir = sroot / "scripts" / "sub"
            sub_dir.mkdir(parents=True)
            (sub_dir / "valid.py").write_text(
                "import argparse\np = argparse.ArgumentParser()\np.add_argument('--ok')\n",
                encoding="utf-8",
            )

            # Positive: valid nested scripts/sub/valid.py passes cleanly
            (sroot / "SKILL.md").write_text(
                "---\nname: test\ndescription: \"Test\"\n---\n\nRun `scripts/sub/valid.py --ok`.\n",
                encoding="utf-8",
            )
            self.assertEqual(module.audit_skill(sroot)["finding_count"], 0)

            # Negative: mid-path traversals & missing nested subpath all fail (and CLI returns 1)
            for doc_rel, bad_line, expected_kind in (
                ("SKILL.md", "Run `scripts/./../../outside.py`.\n", "missing-script"),
                ("SKILL.md", "Run `scripts/sub/missing.py`.\n", "missing-script"),
                ("SKILL.md", "See [x](references/./../../outside.md).\n", "missing-reference"),
                ("references/guide.md", "Run `../scripts/../outside.py`.\n", "missing-script"),
            ):
                (sroot / "SKILL.md").write_text(
                    "---\nname: test\ndescription: \"Test\"\n---\n\nRun `scripts/tool.py --valid`.\n",
                    encoding="utf-8",
                )
                (sroot / "references" / "guide.md").write_text("# Clean\n", encoding="utf-8")
                target_doc = sroot / doc_rel
                if doc_rel == "SKILL.md":
                    target_doc.write_text("---\nname: test\ndescription: \"Test\"\n---\n\n" + bad_line, encoding="utf-8")
                else:
                    target_doc.write_text(bad_line, encoding="utf-8")
                res = module.audit_skill(sroot)
                self.assertEqual(res["status"], "failed", (doc_rel, bad_line, res))
                self.assertIn(expected_kind, {f["kind"] for f in res["findings"]}, (doc_rel, bad_line, res))
                cli_res = run_cli("--root", str(sroot), "--json")
                self.assertEqual(cli_res.returncode, 1, (doc_rel, bad_line, cli_res.stdout))

            # Non-research-scientist root must NOT strip hardcoded "research-scientist/" prefix
            custom_root = base / "custom-skill"
            (custom_root / "scripts").mkdir(parents=True)
            (custom_root / "scripts" / "tool.py").write_text(
                "import argparse\np = argparse.ArgumentParser()\np.add_argument('--valid')\n",
                encoding="utf-8",
            )
            (custom_root / "SKILL.md").write_text(
                "---\nname: custom-skill\ndescription: \"Custom\"\n---\n\n"
                "Run `research-scientist/scripts/tool.py --valid`.\n",
                encoding="utf-8",
            )
            res_custom_bad = module.audit_skill(custom_root)
            self.assertEqual(res_custom_bad["status"], "failed", res_custom_bad)
            self.assertIn(
                ("missing-script", "research-scientist/scripts/tool.py"),
                {(f["kind"], f["token"]) for f in res_custom_bad["findings"]},
            )

            (custom_root / "SKILL.md").write_text(
                "---\nname: custom-skill\ndescription: \"Custom\"\n---\n\n"
                "Run `custom-skill/scripts/tool.py --valid`.\n",
                encoding="utf-8",
            )
            self.assertEqual(module.audit_skill(custom_root)["finding_count"], 0)

    def test_symlink_containment_nested_references_and_json_write_error_exit_2(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            outside_secret = base / "outside_secret.md"
            outside_secret.write_text("Run `scripts/missing_secret_script.py`.\n", encoding="utf-8")

            # 1. Symlinked references/evil.md escaping root is flagged without reading external file
            s_ref = _make_temp_skill(base / "case_sym_ref")
            (s_ref / "references" / "evil.md").symlink_to(outside_secret)
            res_sym_ref = module.audit_skill(s_ref)
            self.assertEqual(res_sym_ref["status"], "failed")
            self.assertNotIn("references/evil.md", res_sym_ref["files_audited"])
            self.assertIn("outside-root-symlink", {f["kind"] for f in res_sym_ref["findings"]})
            self.assertNotIn("scripts/missing_secret_script.py", {f["token"] for f in res_sym_ref["findings"]})

            # 2. Symlinked SKILL.md escaping root is flagged without reading external file
            s_skill = _make_temp_skill(base / "case_sym_skill")
            (s_skill / "SKILL.md").unlink()
            (s_skill / "SKILL.md").symlink_to(outside_secret)
            res_sym_skill = module.audit_skill(s_skill)
            self.assertEqual(res_sym_skill["status"], "failed")
            self.assertNotIn("SKILL.md", res_sym_skill["files_audited"])
            self.assertIn("outside-root-symlink", {f["kind"] for f in res_sym_skill["findings"]})
            self.assertNotIn("scripts/missing_secret_script.py", {f["token"] for f in res_sym_skill["findings"]})

            # 3. Nested references/**/*.md: clean passes, bogus script fails
            s_nested = _make_temp_skill(base / "case_nested")
            (s_nested / "references" / "sub").mkdir(parents=True)
            (s_nested / "SKILL.md").write_text(
                "---\nname: test\ndescription: \"Test\"\n---\n\nSee [sub](references/sub/guide.md).\n",
                encoding="utf-8",
            )
            (s_nested / "references" / "sub" / "guide.md").write_text(
                "Run `../../scripts/tool.py --valid`.\n",
                encoding="utf-8",
            )
            res_nested_ok = module.audit_skill(s_nested)
            self.assertEqual(res_nested_ok["finding_count"], 0, res_nested_ok)
            self.assertIn("references/sub/guide.md", res_nested_ok["files_audited"])

            (s_nested / "references" / "sub" / "guide.md").write_text(
                "Run `scripts/nonexistent_nested.py`.\n",
                encoding="utf-8",
            )
            res_nested_bad = module.audit_skill(s_nested)
            self.assertEqual(res_nested_bad["status"], "failed")
            self.assertIn(
                ("missing-script", "scripts/nonexistent_nested.py"),
                {(f["kind"], f["token"]) for f in res_nested_bad["findings"]},
            )

            # 4. --json PATH with nonexistent parent dir exits cleanly with code 2 and JSON error
            bad_out = base / "no_such_subdir" / "out.json"
            proc_err = run_cli("--root", str(s_nested), "--json", str(bad_out))
            self.assertEqual(proc_err.returncode, 2, proc_err.stdout + proc_err.stderr)
            err_payload = json.loads(proc_err.stderr)
            self.assertIn("error", err_payload)

    def test_json_empty_string_exit_2_and_query_sentence_linear_time(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sroot = _make_temp_skill(Path(tmpdir))
            for empty_arg in ("", "   "):
                proc = run_cli("--root", str(sroot), "--json", empty_arg)
                self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
                payload = json.loads(proc.stderr)
                self.assertIn("error", payload)

        # Linear-time scan for QUERY_SENTENCE_RE on long single-line description without query verbs
        long_desc = "Describes scientific methodology and citation verification " * 60
        t0 = time.perf_counter()
        self.assertEqual(list(module.QUERY_SENTENCE_RE.finditer(long_desc)), [])
        self.assertLess(time.perf_counter() - t0, 0.02)

    def test_iteration12_host_re_redos_empty_cli_paths_and_scripts_modules_symlink_parity(self):
        # 1. HOST_RE linear-time (< 0.02s) and edge-case precision
        for adv in (("a." * 4000) + "!", ("a." * 8000) + "!", ("a-" * 8000) + "!", " " * 8000 + "api.openalex.org"):
            t0 = time.perf_counter()
            matches = [m.group(1) for m in module.HOST_RE.finditer(adv)]
            self.assertLess(time.perf_counter() - t0, 0.02)
            if "api.openalex.org" in adv:
                self.assertEqual(matches, ["api.openalex.org"])
            else:
                self.assertEqual(matches, [])
        self.assertEqual(
            [m.group(1) for m in module.HOST_RE.finditer("https://example.org (api.semanticscholar.org) foo/bar.org `api.scite.ai` www.ebi.ac.uk/europepmc")],
            ["example.org", "api.semanticscholar.org", "bar.org", "api.scite.ai", "www.ebi.ac.uk"],
        )
        self.assertEqual([m.group(1) for m in module.HOST_RE.finditer("foo_bar.org a..example.org")], [])

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            sroot = _make_temp_skill(base / "skill_host")
            (sroot / "references" / "long.md").write_text(("a." * 4000) + "!\n", encoding="utf-8")
            t0 = time.perf_counter()
            res_long = module.audit_skill(sroot)
            self.assertLess(time.perf_counter() - t0, 0.1)
            self.assertEqual(res_long["finding_count"], 0)

            # 2. Empty/whitespace CLI paths exit 2 (including CWD skill root)
            for bad_args in (
                ["--root", ""],
                ["--root", "   "],
                ["--root", str(sroot), "--readme", ""],
                ["--root", str(sroot), "--readme", "   "],
                ["--root", str(sroot), "--json", ""],
                ["--root", str(sroot), "--json", "   "],
            ):
                proc = subprocess.run(
                    [sys.executable, str(SCRIPT), *bad_args],
                    cwd=str(sroot),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(proc.returncode, 2, (bad_args, proc.stdout, proc.stderr))
                self.assertIn("error", json.loads(proc.stderr), (bad_args, proc.stderr))

            # 3. scripts/ and modules/ outside-root directory symlink parity + intra-root positive control
            outside_dir = base / "outside_dir"
            outside_dir.mkdir()
            (outside_dir / "evil.py").write_text("print('evil')\n", encoding="utf-8")

            s_sym_scripts = _make_temp_skill(base / "case_sym_scripts")
            (s_sym_scripts / "SKILL.md").write_text("---\nname: test\ndescription: \"Test\"\n---\n\nClean.\n", encoding="utf-8")
            (s_sym_scripts / "scripts" / "tool.py").unlink()
            (s_sym_scripts / "scripts").rmdir()
            (s_sym_scripts / "scripts").symlink_to(outside_dir)
            self.assertEqual(module.collect_scripts(s_sym_scripts), {})
            r_scripts = module.audit_skill(s_sym_scripts)
            self.assertEqual(r_scripts["status"], "failed")
            self.assertIn(("outside-root-symlink", "scripts"), {(f["kind"], f["token"]) for f in r_scripts["findings"]})
            self.assertEqual(run_cli("--root", str(s_sym_scripts), "--json").returncode, 1)

            s_sym_mods = _make_temp_skill(base / "case_sym_mods")
            (s_sym_mods / "modules").symlink_to(outside_dir)
            r_mods = module.audit_skill(s_sym_mods)
            self.assertIn(("outside-root-symlink", "modules"), {(f["kind"], f["token"]) for f in r_mods["findings"]})
            self.assertEqual(run_cli("--root", str(s_sym_mods), "--json").returncode, 1)

            s_nested_sym = _make_temp_skill(base / "case_nested_sym")
            (s_nested_sym / "scripts" / "sub_out").symlink_to(outside_dir)
            (s_nested_sym / "modules" / "pkg").mkdir(parents=True)
            (s_nested_sym / "modules" / "pkg" / "scripts").symlink_to(outside_dir)
            r_nested = module.audit_skill(s_nested_sym)
            toks = {(f["kind"], f["token"]) for f in r_nested["findings"]}
            self.assertIn(("outside-root-symlink", "scripts/sub_out"), toks)
            self.assertIn(("outside-root-symlink", "modules/pkg/scripts"), toks)

            # Intra-root relative directory symlink inside scripts/ passes cleanly
            s_intra = _make_temp_skill(base / "case_intra")
            (s_intra / "scripts" / "real_sub").mkdir()
            (s_intra / "scripts" / "real_sub" / "helper.py").write_text("print('ok')\n", encoding="utf-8")
            (s_intra / "scripts" / "alias_sub").symlink_to("real_sub")
            self.assertEqual(module.audit_skill(s_intra)["finding_count"], 0)


if __name__ == "__main__":
    unittest.main()
