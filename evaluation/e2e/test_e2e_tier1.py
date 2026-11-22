"""Tier 1 Opaque-Box E2E Tests (49 isolated feature tests covering F1-F16 across Areas A-G)."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path

import pytest

from helpers import (
    EVAL_FIXTURES_DIR,
    MODULES_DIR,
    RADAR_SCRIPT,
    REFS_DIR,
    REPO_ROOT,
    SCRIPTS_DIR,
    SKILL_DIR,
    T123_FIXTURES_DIR,
    MockScholarlyServer,
    PdfFactory,
    WorkspaceFactory,
    iso_utc,
    run_cli,
)


def _load_payloads() -> dict:
    return json.loads((T123_FIXTURES_DIR / "mock_scholarly_payloads.json").read_text(encoding="utf-8"))


# =============================================================================
# Area A: Core Governance, Humanizer, Manuscript Ledger & Self-Audit (8 tests)
# =============================================================================


def test_t1_a1_skill_md_zero_sycophancy_and_falsification_first() -> None:
    """T1-A1 (F1): SKILL.md enforces zero-sycophancy, falsification-first, anti-fabrication, and anti-rebranding."""
    skill_text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8").casefold()
    # Anti-sycophancy / zero-flattery
    assert any(tok in skill_text for tok in ("sycophanc", "flatter", "cheerlead", "no praise", "ban praise", "never flatter"))
    # Falsification-first posture before merit
    assert any(tok in skill_text for tok in ("falsif", "disprove", "attack", "skeptic"))
    # Anti-fabrication & receipt / verification gates
    assert any(tok in skill_text for tok in ("fabricat", "hallucinat"))
    assert "receipt" in skill_text or "verified" in skill_text
    # Anti-grandiose rebranding of stitched/reused methods
    assert any(tok in skill_text for tok in ("grandiose", "coined", "rebrand", "stitched"))


def test_t1_a2_humanizer_lint_clean_prose_passes_strict(tmp_path: Path) -> None:
    """T1-A2 (F2): Clean scholarly prose passes humanizer_lint.py --strict --json with zero risks/warnings."""
    clean_md = tmp_path / "clean.md"
    clean_md.write_text(
        "# Graph Convolution Evaluation\n\n"
        "We evaluated two-layer graph convolutional networks on Cora and Citeseer using fixed public splits.\n"
        "On Cora, validation accuracy reached 81.5% across 10 random seeds (std 0.4%).\n"
        "The baseline multilayer perceptron scored 55.1% under identical preprocessing.\n",
        encoding="utf-8",
    )
    res = run_cli(SCRIPTS_DIR / "humanizer_lint.py", [str(clean_md), "--strict", "--json"])
    assert res.returncode == 0, f"stderr={res.stderr} stdout={res.stdout}"
    assert isinstance(res.json_out, dict)
    assert res.json_out["risk_count"] == 0
    assert res.json_out["warn_count"] == 0
    assert res.json_out["findings"] == []
    assert res.json_out["sycophancy_hits"] == []


def test_t1_a3_humanizer_lint_flags_ai_slop_patterns(tmp_path: Path) -> None:
    """T1-A3 (F2): Representative Humanizer §1-§26 AI tells trigger exit 1 with line/category/pattern_id/severity."""
    slop_md = tmp_path / "ai_slop.md"
    slop_md.write_text(
        "# Overview\n"
        "This framework is not merely retrieval, but cognitive synthesis.\n"
        "That is the real win.\n"
        "At its core, what really matters is alignment, speed, and clarity.\n"
        "We delve into a pivotal tapestry — a meticulous — underscore — of innovation — today.\n"
        "Our groundbreaking revolutionary solution transforms the landscape.\n"
        "As an AI language model, I hope this helps!\n",
        encoding="utf-8",
    )
    res = run_cli(SCRIPTS_DIR / "humanizer_lint.py", [str(slop_md), "--strict", "--json"])
    assert res.returncode == 1, f"expected exit 1, got {res.returncode}: {res.stdout} {res.stderr}"
    data = res.json_out
    assert isinstance(data, dict)
    assert data["risk_count"] >= 1
    findings = data["findings"]
    assert len(findings) >= 4
    for item in findings:
        assert isinstance(item["line"], int) and item["line"] >= 1
        assert item.get("category")
        assert item.get("pattern_id")
        assert item.get("severity")
        assert item.get("excerpt")
    pattern_blob = " ".join(str(f.get("pattern_id", "")) + " " + str(f.get("category", "")) for f in findings).casefold()
    assert any(k in pattern_blob for k in ("1", "§1", "negative", "parallel"))
    assert any(k in pattern_blob for k in ("12", "§12", "vocab", "ai"))
    assert any(k in pattern_blob for k in ("22", "§22", "chatbot", "meta", "ai"))


def test_t1_a4_humanizer_lint_claim_preservation_diff(tmp_path: Path) -> None:
    """T1-A4 (F2): --compare-baseline --strict passes when numbers/citations are preserved and fails if dropped."""
    orig = tmp_path / "orig.md"
    edited = tmp_path / "edited.md"
    dropped = tmp_path / "dropped.md"
    orig.write_text("Accuracy improved from 71.4% to 74.2% [12] on Cora.\n", encoding="utf-8")
    edited.write_text("On Cora, measured accuracy increased from 71.4% to 74.2% [12].\n", encoding="utf-8")
    dropped.write_text("On Cora, measured accuracy increased from 71.4% in our evaluation.\n", encoding="utf-8")

    ok = run_cli(SCRIPTS_DIR / "humanizer_lint.py", [str(edited), "--compare-baseline", str(orig), "--strict", "--json"])
    assert ok.returncode == 0, f"stderr={ok.stderr} stdout={ok.stdout}"
    assert ok.json_out["claim_preservation"]["preserved"] is True

    bad = run_cli(SCRIPTS_DIR / "humanizer_lint.py", [str(dropped), "--compare-baseline", str(orig), "--strict", "--json"])
    assert bad.returncode == 1, f"expected exit 1, got {bad.returncode}: {bad.stdout}"
    assert bad.json_out["claim_preservation"]["preserved"] is False


def test_t1_a5_humanizer_lint_eight_gram_overlap(tmp_path: Path) -> None:
    """T1-A5 (F2): --reference --strict detects shared 12-word (8-gram) overlap (exit 1 + OVL_8GRAM) vs disjoint text."""
    prior = tmp_path / "prior.md"
    draft_overlap = tmp_path / "draft_overlap.md"
    draft_disjoint = tmp_path / "draft_disjoint.md"

    shared = "renormalized adjacency matrix propagation prevents numerical instability across deep graph neural layers"
    prior.write_text(f"Prior paper notes that {shared} in practice.\n", encoding="utf-8")
    draft_overlap.write_text(f"Our draft argues {shared} on benchmarks.\n", encoding="utf-8")
    draft_disjoint.write_text("Empirical evaluation across molecular datasets reveals distinct calibration trade-offs.\n", encoding="utf-8")

    hit = run_cli(SCRIPTS_DIR / "humanizer_lint.py", [str(draft_overlap), "--reference", str(prior), "--strict", "--json"])
    assert hit.returncode == 1, f"expected exit 1 on 12-word verbatim overlap under --strict: {hit.stdout}"
    assert isinstance(hit.json_out, dict)
    assert hit.json_out["overlap_score"] > 0
    assert hit.json_out["overlap_details"]["flagged"] is True
    assert any(f.get("pattern_id") == "OVL_8GRAM" for f in hit.json_out["findings"])

    clean = run_cli(SCRIPTS_DIR / "humanizer_lint.py", [str(draft_disjoint), "--reference", str(prior), "--strict", "--json"])
    assert clean.returncode == 0
    assert clean.json_out["overlap_score"] == 0.0
    assert clean.json_out["findings"] == []


def test_t1_a6_check_manuscript_ledger_passes_clean_workspace(tmp_path: Path) -> None:
    """T1-A6 (F3): check_manuscript_ledger.py passes with matching --ledger, --manuscript, and --sources-dir."""
    ledger = json.loads((REFS_DIR / "manuscript-ledger.schema-example.json").read_text(encoding="utf-8"))
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    sources_dir = tmp_path / "sources"
    (sources_dir / "fictional" / "logs").mkdir(parents=True)
    (sources_dir / "fictional" / "logs" / "run-001.json").write_text(
        json.dumps({"metric": 0.71, "unit": "fictional score"}),
        encoding="utf-8",
    )
    (sources_dir / "fictional-paper.txt").write_text(
        "fictional-paper, section 3: Fictional input transformation; scientific consequence has not been established.\n",
        encoding="utf-8",
    )
    manuscript = tmp_path / "manuscript.md"
    manuscript.write_text(
        "# Results\n"
        "The adapted input transformation achieved 0.71 fictional score in abstract and results table.\n",
        encoding="utf-8",
    )
    res = run_cli(
        SCRIPTS_DIR / "check_manuscript_ledger.py",
        ["--ledger", str(ledger_path), "--manuscript", str(manuscript), "--sources-dir", str(sources_dir)],
    )
    assert res.returncode == 0, f"stderr={res.stderr} stdout={res.stdout}"
    assert res.json_out["status"] == "structure_passed"
    assert res.json_out["issues"] == []


def test_t1_a7_check_manuscript_ledger_rejects_numeric_drift_and_missing_quote(tmp_path: Path) -> None:
    """T1-A7 (F3): check_manuscript_ledger.py fails (exit 1) on numeric drift or missing source locator."""
    ledger = json.loads((REFS_DIR / "manuscript-ledger.schema-example.json").read_text(encoding="utf-8"))
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    (sources_dir / "paper.txt").write_text("Unrelated text without the declared locator.\n", encoding="utf-8")

    manuscript = tmp_path / "manuscript.md"
    manuscript.write_text("In the results table, our model reached 0.84 fictional score.\n", encoding="utf-8")

    res = run_cli(
        SCRIPTS_DIR / "check_manuscript_ledger.py",
        ["--ledger", str(ledger_path), "--manuscript", str(manuscript), "--sources-dir", str(sources_dir)],
    )
    assert res.returncode != 0
    assert res.json_out is not None
    assert res.json_out["issues"]


def test_t1_a8_claim_audit_detects_missing_script_or_flag(tmp_path: Path) -> None:
    """T1-A8 (F4): claim_audit.py passes on valid skill tree and fails when bogus flag/script is injected."""
    ok_root = WorkspaceFactory.copy_skill_tree(tmp_path / "ok")
    readme_copy = tmp_path / "README_ok.md"
    readme_copy.write_text((REPO_ROOT / "README.md").read_text(encoding="utf-8"), encoding="utf-8")

    ok_res = run_cli(SCRIPTS_DIR / "claim_audit.py", ["--root", str(ok_root), "--readme", str(readme_copy)])
    assert ok_res.returncode == 0, f"stderr={ok_res.stderr} stdout={ok_res.stdout}"

    bad_root = WorkspaceFactory.copy_skill_tree(tmp_path / "bad")
    skill_md = bad_root / "SKILL.md"
    skill_md.write_text(
        skill_md.read_text(encoding="utf-8") + "\nRun `python3 scripts/ghost_tool.py --nonexistent-flag`.\n",
        encoding="utf-8",
    )
    bad_res = run_cli(SCRIPTS_DIR / "claim_audit.py", ["--root", str(bad_root), "--readme", str(readme_copy)])
    assert bad_res.returncode == 1
    combined = (bad_res.stdout + bad_res.stderr).lower()
    assert "ghost_tool.py" in combined or "nonexistent-flag" in combined


# =============================================================================
# Area B: Multi-Source Search, Campaign Dedup, Citation Graph & Fulltext (7 tests)
# =============================================================================


def test_t1_b1_search_papers_v2_multi_source_complete(mock_server: MockScholarlyServer) -> None:
    """T1-B1 (F5): search_papers.py queries openalex/arxiv/crossref/acl/hf/dblp and emits research_scientist_search_v2."""
    p = _load_payloads()
    mock_server.add_json("/works", p["openalex_gcn"], host="api.openalex.org")
    mock_server.add_route("/api/query", (200, "application/atom+xml", p["arxiv_gcn_xml"]), host="export.arxiv.org")
    mock_server.add_json("/works", p["crossref_gcn"], host="api.crossref.org")
    mock_server.add_route("/search", (200, "text/html", p["acl_gcn_html"]), host="aclanthology.org")
    mock_server.add_json("/api/papers/search", p["hf_gcn_json"], host="huggingface.co")
    mock_server.add_json("/api/papers", p["hf_gcn_json"], host="huggingface.co")
    mock_server.add_json("/search/publ/api", p["dblp_gcn_json"], host="dblp.org")
    mock_server.add_json("/tallies/", {"supporting": 10, "mentioning": 20, "contradicting": 1}, host="api.scite.ai")

    res = run_cli(
        SCRIPTS_DIR / "search_papers.py",
        [
            "graph convolution",
            "--source", "openalex",
            "--source", "arxiv",
            "--source", "crossref",
            "--source", "acl",
            "--source", "hf",
            "--source", "dblp",
        ],
        env=mock_server.env(),
    )
    assert res.returncode == 0, f"stderr={res.stderr} stdout={res.stdout}"
    data = res.json_out
    assert isinstance(data, dict)
    assert data.get("schema") == "research_scientist_search_v2"
    for src in ("openalex", "arxiv", "crossref", "acl", "dblp"):
        assert data["sources"][src]["status"] == "complete"
    hf_state = data["sources"].get("huggingface") or data["sources"].get("hf")
    assert hf_state is not None and hf_state["status"] == "complete"
    assert len(data["results"]) >= 1
    required_fields = {
        "dedup_key", "doi", "arxiv_id", "openalex_id", "s2_id", "dblp_key",
        "normalized_title", "sources_seen", "preprint_only", "retraction_status",
        "scite_tallies", "abstract",
    }
    assert required_fields.issubset(data["results"][0].keys())


def test_t1_b2_search_papers_4id_bare_arxiv_dedup_and_seed_check(mock_server: MockScholarlyServer) -> None:
    """T1-B2 (F5): OpenAlex bare-arXiv DOI + arXiv versioned ID + S2 punctuation variant collapse to 1 dedup_group."""
    p = _load_payloads()
    mock_server.add_json("/works", p["openalex_gcn"], host="api.openalex.org")
    mock_server.add_route("/api/query", (200, "application/atom+xml", p["arxiv_gcn_xml"]), host="export.arxiv.org")
    mock_server.add_json("/graph/v1/paper/search", p["s2_gcn"], host="api.semanticscholar.org")
    mock_server.add_json("/tallies/", {"supporting": 4, "mentioning": 12, "contradicting": 0}, host="api.scite.ai")

    res = run_cli(
        SCRIPTS_DIR / "search_papers.py",
        [
            "graph convolution",
            "--source", "openalex",
            "--source", "arxiv",
            "--source", "s2",
            "--known-doi", "10.48550/arxiv.1609.02907",
            "--known-source-id", "arxiv=1609.02907",
        ],
        env=mock_server.env(),
    )
    assert res.returncode == 0, f"stderr={res.stderr}"
    data = res.json_out
    assert data.get("schema") == "research_scientist_search_v2"
    groups = data.get("dedup_groups", [])
    assert len(groups) == 1
    rec = data["results"][0]
    assert set(rec["sources_seen"]) >= {"openalex", "arxiv", "s2"}
    assert rec["arxiv_id"] == "1609.02907"
    assert all(chk["status"] == "retrieved" for chk in data["known_seed_checks"])


def test_t1_b3_search_campaign_cross_query_dedup_and_v1_compat(
    mock_server: MockScholarlyServer, tmp_path: Path
) -> None:
    """T1-B3 (F5): search_campaign.py collapses OpenAlex + arXiv hits across query families while preserving v1 fields."""
    p = _load_payloads()
    mock_server.add_json("/works", p["openalex_gcn"], host="api.openalex.org")
    mock_server.add_route("/api/query", (200, "application/atom+xml", p["arxiv_gcn_xml"]), host="export.arxiv.org")

    plan = {
        "question": "Has normalized adjacency GCN been published?",
        "known_seeds": [
            {"doi": "10.48550/arxiv.1609.02907"},
            {"source": "arxiv", "source_id": "1609.02907"},
        ],
        "queries": [
            {"id": "direct-1", "family": "direct_problem", "query": "graph convolution", "sources": ["openalex"], "size": 10, "pages": 1},
            {"id": "closure-1", "family": "closure", "query": "semi-supervised graph convolutional", "sources": ["arxiv"], "size": 10, "pages": 1},
        ],
    }
    plan_path = tmp_path / "campaign_plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    res = run_cli(SCRIPTS_DIR / "search_campaign.py", [str(plan_path)], env=mock_server.env())
    assert res.returncode == 0, f"stderr={res.stderr}"
    data = res.json_out
    assert data.get("schema") == "research_scientist_search_campaign_v1" or data.get("format") == "research_scientist_search_campaign_v1"
    assert "query_runs" in data and "known_seed_checks" in data and "coverage" in data
    assert len(data.get("dedup_groups", [])) >= 1
    assert len(data.get("combined_results", [])) == 1


def test_t1_b4_search_papers_distinguishes_zero_results_vs_bounded_partial(
    mock_server: MockScholarlyServer,
) -> None:
    """T1-B4 (F5): valid_zero_results (0 hits) is strictly distinct from bounded_partial (truncated)."""
    mock_server.add_json("/works", {"meta": {"count": 100}, "results": [
        {"id": "https://openalex.org/W1", "doi": None, "display_name": "Paper 1", "publication_year": 2024}
    ]}, host="api.openalex.org")
    empty_arxiv = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">'
        '<opensearch:totalResults>0</opensearch:totalResults></feed>'
    )
    mock_server.add_route("/api/query", (200, "application/atom+xml", empty_arxiv), host="export.arxiv.org")

    res = run_cli(
        SCRIPTS_DIR / "search_papers.py",
        ["obscure term", "--source", "openalex", "--source", "arxiv", "--size", "10", "--pages", "1"],
        env=mock_server.env(),
    )
    assert res.returncode == 0, f"stderr={res.stderr}"
    assert res.json_out["sources"]["arxiv"]["status"] == "valid_zero_results"
    assert res.json_out["sources"]["openalex"]["status"] == "bounded_partial"


def test_t1_b5_citation_graph_multi_seed_cocitation_overlap(
    mock_server: MockScholarlyServer, tmp_path: Path
) -> None:
    """T1-B5 (F6): citation_graph.py ranks seed_overlap_count==2 co-cited/co-referenced neighbors above overlap==1."""
    def oa_handler(ctx: dict) -> tuple[int, str, str]:
        path = ctx["path"]
        q = ctx["query"]
        if path.endswith("/W100"):
            return 200, "application/json", json.dumps({
                "id": "https://openalex.org/W100",
                "title": "Seed Paper 100",
                "publication_year": 2020,
                "referenced_works": ["https://openalex.org/W300", "https://openalex.org/W301", "https://openalex.org/W500"],
            })
        if path.endswith("/W200"):
            return 200, "application/json", json.dumps({
                "id": "https://openalex.org/W200",
                "title": "Seed Paper 200",
                "publication_year": 2021,
                "referenced_works": ["https://openalex.org/W300", "https://openalex.org/W301"],
            })
        if "cites:W100" in q or "cites%3AW100" in q:
            return 200, "application/json", json.dumps({
                "meta": {"count": 2},
                "results": [
                    {"id": "https://openalex.org/W400", "title": "Citing Both", "publication_year": 2024},
                    {"id": "https://openalex.org/W500", "title": "Single Seed Neighbor", "publication_year": 2023},
                ],
            })
        if "cites:W200" in q or "cites%3AW200" in q:
            return 200, "application/json", json.dumps({
                "meta": {"count": 1},
                "results": [{"id": "https://openalex.org/W400", "title": "Citing Both", "publication_year": 2024}],
            })
        return 200, "application/json", json.dumps({"meta": {"count": 0}, "results": []})

    mock_server.add_route("/works", oa_handler, host="api.openalex.org")
    out_path = tmp_path / "graph.json"
    res = run_cli(
        SCRIPTS_DIR / "citation_graph.py",
        ["--seeds", "W100,W200", "--direction", "both", "--top", "5", "--out", str(out_path)],
        env=mock_server.env(),
    )
    assert res.returncode == 0, f"stderr={res.stderr} stdout={res.stdout}"
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["status"] == "COMPLETE"
    neighbors = data.get("neighbors", data.get("results", []))
    assert len(neighbors) >= 3
    by_id = {n.get("id") or n.get("work_id") or n.get("openalex_id"): n for n in neighbors}
    assert any(by_id[k]["seed_overlap_count"] == 2 for k in ("W300", "W301", "W400") if k in by_id)
    assert neighbors[0]["seed_overlap_count"] == 2
    if "W500" in by_id:
        assert by_id["W500"]["seed_overlap_count"] == 1


def test_t1_b6_fulltext_mining_extracts_epmc_jats_sections(
    mock_server: MockScholarlyServer, tmp_path: Path
) -> None:
    """T1-B6 (F6): fulltext_mining.py extracts structured Discussion, Limitations, Future Work from JATS XML."""
    p = _load_payloads()
    mock_server.add_route(
        "/europepmc/webservices/rest/",
        (200, "application/xml", p["epmc_jats_xml"]),
        host="www.ebi.ac.uk",
    )
    out_path = tmp_path / "ft.json"
    res = run_cli(
        SCRIPTS_DIR / "fulltext_mining.py",
        ["--pmcids", "PMC999001", "--out", str(out_path)],
        env=mock_server.env(),
    )
    assert res.returncode == 0, f"stderr={res.stderr}"
    data = json.loads(out_path.read_text(encoding="utf-8"))
    items = data.get("items") or data.get("records")
    assert isinstance(items, list) and len(items) == 1
    item = items[0]
    assert item.get("fulltext_status") == "ok"
    sections = item.get("sections")
    assert isinstance(sections, dict)
    for sec_name in ("Discussion", "Limitations", "Future Work"):
        assert sec_name in sections and isinstance(sections[sec_name], list) and len(sections[sec_name]) >= 1
    assert "renormalized adjacency" in " ".join(sections["Discussion"]).lower()
    assert "ten million edges" in " ".join(sections["Limitations"]).lower()
    assert "adaptive edge rewiring" in " ".join(sections["Future Work"]).lower()
    assert "<sec>" not in json.dumps(sections)


def test_t1_b7_fulltext_mining_scite_tallies_and_retraction_status(
    mock_server: MockScholarlyServer, tmp_path: Path
) -> None:
    """T1-B7 (F6): fulltext_mining.py reports scite tallies and flags retracted vs clean DOIs."""
    def scite_handler(ctx: dict) -> tuple[int, str, str]:
        return 200, "application/json", json.dumps({"supporting": 12, "mentioning": 40, "contradicting": 5})

    def crossref_handler(ctx: dict) -> tuple[int, str, str]:
        if "retracted" in ctx["path"]:
            return 200, "application/json", json.dumps({
                "status": "ok",
                "message": {"DOI": "10.1000/retracted", "update-to": [{"type": "retraction", "DOI": "10.1000/notice"}]},
            })
        return 200, "application/json", json.dumps({
            "status": "ok",
            "message": {"DOI": "10.1000/clean", "title": ["Clean Paper"]},
        })

    def oa_handler(ctx: dict) -> tuple[int, str, str]:
        retracted = "10.1000/retracted" in ctx["path"]
        return 200, "application/json", json.dumps({
            "id": "https://openalex.org/W1",
            "is_retracted": retracted,
        })

    mock_server.add_route("/tallies/", scite_handler, host="api.scite.ai")
    mock_server.add_route("/works", crossref_handler, host="api.crossref.org")
    mock_server.add_route("/works", oa_handler, host="api.openalex.org")

    out_path = tmp_path / "ft_dois.json"
    res = run_cli(
        SCRIPTS_DIR / "fulltext_mining.py",
        ["--dois", "10.1000/retracted", "10.1000/clean", "--out", str(out_path)],
        env=mock_server.env(),
    )
    assert res.returncode == 0, f"stderr={res.stderr}"
    data = json.loads(out_path.read_text(encoding="utf-8"))
    items = data.get("records") or data.get("items") or data.get("dois") or data
    by_doi = {row["doi"]: row for row in items}
    assert by_doi["10.1000/retracted"]["retraction_status"] == "retracted"
    assert by_doi["10.1000/retracted"]["scite_tallies"]["status"] == "ok"
    assert by_doi["10.1000/retracted"]["scite_tallies"]["contradicting"] == 5
    assert by_doi["10.1000/clean"]["retraction_status"] == "clean"


# =============================================================================
# Area C: PDF/OCR/MinerU V2 Extraction & PaperQA2/Khoj Corpus Q&A (6 tests)
# =============================================================================


def _flatten_v2_blocks(payload: object) -> list[dict]:
    pages = payload["pages"] if isinstance(payload, dict) and "pages" in payload else payload
    assert isinstance(pages, list)
    blocks: list[dict] = []
    for item in pages:
        if isinstance(item, list):
            blocks.extend(item)
        elif isinstance(item, dict):
            blocks.append(item)
    return blocks


def test_t1_c1_extract_pdf_blocks_mineru_v2_schema(tmp_path: Path) -> None:
    """T1-C1 (F7): extract_pdf_blocks.py emits MinerU Content List V2-compatible JSON."""
    pdf = PdfFactory.make_clean_paper_pdf(tmp_path / "paper.pdf")
    out = tmp_path / "blocks.json"
    res = run_cli(SCRIPTS_DIR / "extract_pdf_blocks.py", [str(pdf), "--out", str(out)])
    assert res.returncode == 0, f"stderr={res.stderr}"
    blocks = _flatten_v2_blocks(json.loads(out.read_text(encoding="utf-8")))
    assert len(blocks) >= 2
    for blk in blocks:
        assert blk["type"] in {"paragraph", "table", "image", "equation"}
        assert isinstance(blk["page_idx"], int)
        assert isinstance(blk["bbox"], list) and len(blk["bbox"]) == 4
        assert "text" in blk or "content" in blk
        assert blk["ocr_used"] is False
        assert blk["visual_check_required"] is True
    p0_text = " ".join(str(b.get("text") or "") for b in blocks if b["page_idx"] == 0)
    p1_text = " ".join(str(b.get("text") or "") for b in blocks if b["page_idx"] == 1)
    assert "Equation 8" in p0_text
    assert "Limitations" in p1_text


def test_t1_c2_extract_pdf_blocks_table_extraction(tmp_path: Path) -> None:
    """T1-C2 (F7): extract_pdf_blocks.py --tables extracts table blocks containing cell numbers."""
    pdf = PdfFactory.make_table_pdf(tmp_path / "table_paper.pdf")
    out = tmp_path / "blocks.json"
    res = run_cli(SCRIPTS_DIR / "extract_pdf_blocks.py", [str(pdf), "--out", str(out), "--tables"])
    assert res.returncode == 0, f"stderr={res.stderr}"
    blocks = _flatten_v2_blocks(json.loads(out.read_text(encoding="utf-8")))
    table_blocks = [b for b in blocks if b.get("type") == "table"]
    assert len(table_blocks) >= 1
    blob = json.dumps(table_blocks)
    assert "81.5" in blob and "70.3" in blob


def test_t1_c3_extract_pdf_blocks_tesseract_ocr_fallback(tmp_path: Path) -> None:
    """T1-C3 (F7): extract_pdf_blocks.py --ocr runs tesseract fallback on scanned image-only PDF."""
    pdf = PdfFactory.make_scanned_image_pdf(tmp_path / "scan.pdf")
    out = tmp_path / "blocks.json"
    res = run_cli(SCRIPTS_DIR / "extract_pdf_blocks.py", [str(pdf), "--out", str(out), "--ocr"])
    assert res.returncode == 0, f"stderr={res.stderr}"
    blocks = _flatten_v2_blocks(json.loads(out.read_text(encoding="utf-8")))
    assert any(b.get("ocr_used") is True for b in blocks)
    text_all = " ".join(str(b.get("text") or b.get("content") or "") for b in blocks).lower()
    assert "renormalized" in text_all or "variance" in text_all


def test_t1_c4_local_evidence_paperqa2_mmr_and_answerable_gate(tmp_path: Path) -> None:
    """T1-C4 (F8): local_evidence.py ranks across >=2 distinct studies with MMR diversity and ANSWERABLE gate."""
    study_a = tmp_path / "study_a.json"
    study_b = tmp_path / "study_b.json"
    study_a.write_text(json.dumps([
        {"type": "paragraph", "page_idx": 0, "bbox": [0, 0, 100, 20], "text": "Normalized adjacency prevents exploding activations across stacked graph convolution layers."},
        {"type": "paragraph", "page_idx": 1, "bbox": [0, 0, 100, 20], "text": "Normalized adjacency also stabilizes spectral eigenvalue bounds during training."},
    ]), encoding="utf-8")
    study_b.write_text(json.dumps([
        {"type": "paragraph", "page_idx": 0, "bbox": [0, 0, 100, 20], "text": "Without symmetric normalization, activations grow exponentially with node degree variance."},
    ]), encoding="utf-8")
    out = tmp_path / "qa.json"
    res = run_cli(
        SCRIPTS_DIR / "local_evidence.py",
        [
            "--inputs", str(study_a), str(study_b),
            "--question", "How does normalized adjacency prevent exploding activations?",
            "--mmr-lambda", "0.7",
            "--min-studies", "2",
            "--min-evidence", "2",
            "--out", str(out),
        ],
    )
    assert res.returncode == 0, f"stderr={res.stderr} stdout={res.stdout}"
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["gate_status"] == "ANSWERABLE"
    assert data["distinct_studies"] >= 2
    passages = data["ranked_passages"]
    assert len(passages) >= 2
    sources = {p["source_id"] for p in passages}
    assert len(sources) >= 2
    for p in passages:
        assert {"source_id", "page_idx", "quote", "score"}.issubset(p.keys())
    assert data["reranker_mode"] in {"bm25_mmr", "bm25_fallback"}


def test_t1_c5_local_evidence_stemming_and_mmr_diversity(tmp_path: Path) -> None:
    """T1-C5 (F8): Stemmed BM25 matches morphological variants and mmr_lambda=0.5 surfaces multiple files."""
    cdir = tmp_path / "corpus"
    cdir.mkdir()
    (cdir / "doc1.json").write_text(json.dumps([
        {"type": "paragraph", "page_idx": 0, "bbox": [0, 0, 10, 10], "text": "Symmetric normalization bounds activation variance."},
        {"type": "paragraph", "page_idx": 1, "bbox": [0, 0, 10, 10], "text": "Symmetric normalization bounds activation variance in layer two."},
    ]), encoding="utf-8")
    (cdir / "doc2.json").write_text(json.dumps([
        {"type": "paragraph", "page_idx": 0, "bbox": [0, 0, 10, 10], "text": "Spectral normalize operations stabilize activation magnitudes."},
    ]), encoding="utf-8")
    out = tmp_path / "qa.json"
    res = run_cli(
        SCRIPTS_DIR / "local_evidence.py",
        [
            "--inputs", str(cdir),
            "--question", "normalized activations",
            "--mmr-lambda", "0.5",
            "--min-studies", "1",
            "--min-evidence", "2",
            "--out", str(out),
        ],
    )
    assert res.returncode == 0, f"stderr={res.stderr}"
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data["ranked_passages"]) >= 2
    assert len({p["source_id"] for p in data["ranked_passages"]}) >= 2


def test_t1_c6_local_evidence_optional_khoj_client_and_503_fallback(
    mock_server: MockScholarlyServer, tmp_path: Path
) -> None:
    """T1-C6 (F8): local_evidence.py integrates --khoj-url hits and handles Khoj 503 explicitly without silent success."""
    study_a = tmp_path / "study_a.json"
    study_a.write_text(json.dumps([
        {"type": "paragraph", "page_idx": 0, "bbox": [0, 0, 10, 10], "text": "Adjacency normalization stabilizes training."}
    ]), encoding="utf-8")
    mock_server.add_json("/api/search", [
        {"entry": "Khoj indexed adjacency passage.", "file": "khoj_note.md", "score": 0.91}
    ])
    out_ok = tmp_path / "qa_ok.json"
    res_ok = run_cli(
        SCRIPTS_DIR / "local_evidence.py",
        [
            "--inputs", str(study_a),
            "--question", "adjacency",
            "--khoj-url", mock_server.url("/"),
            "--min-studies", "1",
            "--min-evidence", "1",
            "--out", str(out_ok),
        ],
        env=mock_server.env(),
    )
    assert res_ok.returncode == 0, f"stderr={res_ok.stderr}"
    assert any(r["path"] == "/api/search" for r in mock_server.requests)
    ok_data = json.loads(out_ok.read_text(encoding="utf-8"))
    assert ok_data.get("khoj_status") == "ok"
    passages_blob = " ".join(str(p.get("quote") or p.get("entry") or "") for p in ok_data.get("ranked_passages", []))
    assert "Khoj indexed adjacency passage" in passages_blob

    mock_server.reset()
    mock_server.add_route("/api/search", (503, "application/json", '{"error":"unavailable"}'))
    out_err = tmp_path / "qa_503.json"
    res_err = run_cli(
        SCRIPTS_DIR / "local_evidence.py",
        [
            "--inputs", str(study_a),
            "--question", "adjacency",
            "--khoj-url", mock_server.url("/"),
            "--min-studies", "1",
            "--min-evidence", "1",
            "--out", str(out_err),
        ],
        env=mock_server.env(),
    )
    assert any(r["path"] == "/api/search" for r in mock_server.requests)
    err_data = json.loads(out_err.read_text(encoding="utf-8")) if out_err.exists() else (res_err.json_out or {})
    # Must either exit non-zero or record an explicit non-ok khoj_status / warning / fallback field (never silently claim Khoj succeeded)
    assert res_err.returncode != 0 or (
        isinstance(err_data, dict)
        and err_data.get("khoj_status") in {"http_error", "unavailable", "fallback", "failed", "503"}
        and not err_data.get("khoj_results")
    )


# =============================================================================
# Area D: STORM Explorer, Gap Pipeline & Plan Gates (7 tests)
# =============================================================================


def test_t1_d1_storm_explorer_perspectives_info_table_and_uncovered_branches(tmp_path: Path) -> None:
    """T1-D1 (F9): storm_explorer.py builds >=2 perspectives, qa_turns, deduplicated information_table, outline, uncovered_branches."""
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps([
        {"id": "P1", "title": "Fast Retrieval with RRF", "text": "Reciprocal Rank Fusion achieves low latency without learned weights."},
        {"id": "P2", "title": "Calibration Error in Learned Fusion", "text": "Learned neural fusion exhibits calibration error under distribution shift."},
        {"id": "P3", "title": "OOD Shift in Hybrid Search", "text": "Out-of-distribution queries degrade learned score fusion compared to rank-based RRF."},
    ]), encoding="utf-8")
    out = tmp_path / "storm.json"
    res = run_cli(
        SCRIPTS_DIR / "storm_explorer.py",
        ["--topic", "RRF vs learned fusion under OOD shift", "--corpus", str(corpus), "--out", str(out)],
    )
    assert res.returncode == 0, f"stderr={res.stderr} stdout={res.stdout}"
    data = json.loads(out.read_text(encoding="utf-8"))
    state = data.get("storm_state", data)
    assert len(state["perspectives"]) >= 2
    assert len(state["qa_turns"]) >= 1
    assert isinstance(state["information_table"], list)
    assert isinstance(state["outline"], list) and len(state["outline"]) >= 1
    assert isinstance(state["uncovered_branches"], list)


def test_t1_d2_gap_pipeline_passes_supported_bounded_gap(tmp_path: Path) -> None:
    """T1-D2 (F10): gap_pipeline.py passes a bounded gap with full-text digests, dual-regime coverage, and clean kill-search."""
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps([
        {"id": "P1", "source": "openalex", "family": "same_problem", "year": 2024, "title": "Rank Fusion Latency", "abstract": "Measures latency only.", "access": "full_text"},
        {"id": "P2", "source": "arxiv", "family": "cross_setting_analogy", "year": 2025, "title": "Calibration Under Shift", "abstract": "Studies calibration in vision.", "access": "full_text"},
    ]), encoding="utf-8")
    digests = tmp_path / "digests.json"
    digests.write_text(json.dumps({
        "P1": {"source_id": "P1", "access": "full_text", "digest": "Tests latency in-domain only."},
        "P2": {"source_id": "P2", "access": "full_text", "digest": "Tests calibration on images, not RRF."},
    }), encoding="utf-8")
    candidates = tmp_path / "candidates.json"
    candidates.write_text(json.dumps([
        {
            "id": "G1",
            "claim": "Bounded variance of RRF vs learned fusion under OOD query shift remains uncharacterized.",
            "trigger": "literature_synthesis",
            "cited_ids": ["P1", "P2"],
            "support_ids": ["P1", "P2"],
            "cutoff_year": 2026,
            "sgha_critics_passed": True,
            "engineering_checked": True,
        }
    ]), encoding="utf-8")
    out = tmp_path / "gap_out.json"
    res = run_cli(
        SCRIPTS_DIR / "gap_pipeline.py",
        ["--topic", "OOD fusion", "--corpus", str(corpus), "--digests", str(digests), "--candidates", str(candidates), "--out", str(out)],
    )
    assert res.returncode == 0, f"stderr={res.stderr} stdout={res.stdout}"
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data["surviving_gaps"]) == 1
    assert data["rejected_gaps"] == []
    assert data["exit_code"] == 0


def test_t1_d3_gap_pipeline_rejects_solved_fragile_and_temporal_leak(tmp_path: Path) -> None:
    """T1-D3 (F10): gap_pipeline.py emits DROP_ALREADY_SOLVED (abstractless hit), DROP_SINGLE_PAPER_FRAGILE, DROP_TEMPORAL_LEAK."""
    corpus = tmp_path / "corpus_with_kill.json"
    corpus.write_text(json.dumps([
        {"id": "P1", "source": "openalex", "family": "same_problem", "year": 2023, "title": "Sparse Routing Baseline", "abstract": "Baseline study.", "access": "full_text"},
        {"id": "P2", "source": "arxiv", "family": "cross_setting_analogy", "year": 2024, "title": "Entropy Routing Analogy", "abstract": "Analogy study.", "access": "full_text"},
        {"id": "KILL1", "source": "acl", "family": "kill_search", "year": 2024, "title": "Dynamic Temperature Scaling for OOD Reciprocal Rank Fusion", "abstract": None, "access": "full_text"},
        {"id": "FUTURE1", "source": "arxiv", "family": "same_problem", "year": 2027, "title": "Post-cutoff Future Paper", "abstract": "Published after cutoff.", "access": "full_text"},
    ]), encoding="utf-8")
    digests = tmp_path / "digests.json"
    digests.write_text(json.dumps({
        k: {"source_id": k, "access": "full_text", "digest": f"Read digest for {k}"}
        for k in ("P1", "P2", "KILL1", "FUTURE1")
    }), encoding="utf-8")
    candidates = tmp_path / "cands.json"
    candidates.write_text(json.dumps([
        {"id": "C1", "claim": "Dynamic temperature scaling for OOD reciprocal rank fusion", "trigger": "literature_synthesis", "cited_ids": ["P1", "P2"], "support_ids": ["P1", "P2"], "cutoff_year": 2025, "sgha_critics_passed": True, "engineering_checked": True},
        {"id": "C2", "claim": "Single paper brittle observation", "trigger": "literature_synthesis", "cited_ids": ["P1"], "support_ids": ["P1"], "cutoff_year": 2025, "sgha_critics_passed": True, "engineering_checked": True},
        {"id": "C3", "claim": "Retrospective claim citing 2027 future paper", "trigger": "literature_synthesis", "cited_ids": ["P1", "FUTURE1"], "support_ids": ["P1", "FUTURE1"], "cutoff_year": 2025, "sgha_critics_passed": True, "engineering_checked": True},
    ]), encoding="utf-8")
    out = tmp_path / "gap_out.json"
    res = run_cli(
        SCRIPTS_DIR / "gap_pipeline.py",
        ["--topic", "OOD fusion", "--corpus", str(corpus), "--digests", str(digests), "--candidates", str(candidates), "--out", str(out)],
    )
    assert res.returncode != 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["surviving_gaps"] == []
    codes = {r["reason_code"] if "reason_code" in r else r.get("code") for r in data["rejected_gaps"]}
    assert {"DROP_ALREADY_SOLVED", "DROP_SINGLE_PAPER_FRAGILE", "DROP_TEMPORAL_LEAK"}.issubset(codes)


def test_t1_d4_gap_pipeline_rejects_unread_citation(tmp_path: Path) -> None:
    """T1-D4 (F10): gap_pipeline.py rejects candidate citing paper missing from digests.json with DROP_UNREAD_CITATION."""
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps([
        {"id": "arxiv:1609.02907", "source": "arxiv", "family": "same_problem", "year": 2016, "title": "GCN", "abstract": "...", "access": "abstract"},
        {"id": "P2", "source": "openalex", "family": "cross_setting_analogy", "year": 2020, "title": "P2", "abstract": "...", "access": "full_text"},
    ]), encoding="utf-8")
    empty_digests = tmp_path / "empty_digests.json"
    empty_digests.write_text(json.dumps({"P2": {"source_id": "P2", "access": "full_text", "digest": "Read."}}), encoding="utf-8")
    cands = tmp_path / "cands.json"
    cands.write_text(json.dumps([
        {"id": "C1", "claim": "Unread citation gap", "trigger": "literature_synthesis", "cited_ids": ["arxiv:1609.02907", "P2"], "support_ids": ["arxiv:1609.02907", "P2"], "cutoff_year": 2026, "sgha_critics_passed": True, "engineering_checked": True}
    ]), encoding="utf-8")
    out = tmp_path / "gap_out.json"
    res = run_cli(
        SCRIPTS_DIR / "gap_pipeline.py",
        ["--topic", "GCN", "--corpus", str(corpus), "--digests", str(empty_digests), "--candidates", str(cands), "--out", str(out)],
    )
    assert res.returncode != 0
    data = json.loads(out.read_text(encoding="utf-8"))
    codes = {r.get("reason_code") or r.get("code") for r in data["rejected_gaps"]}
    assert "DROP_UNREAD_CITATION" in codes


def test_t1_d5_check_gap_record_evidence_dir_quote_verification(tmp_path: Path) -> None:
    """T1-D5 (F11): check_gap_record.py --evidence-dir passes when quote exists and exits 1 when locator quote missing."""
    gap = json.loads((REFS_DIR / "gap-record.schema-example.json").read_text(encoding="utf-8"))
    ev_dir = tmp_path / "evidence_dir"
    ev_dir.mkdir()
    (ev_dir / "FictionalStudy-A.json").write_text(
        json.dumps([{"type": "paragraph", "page_idx": 2, "text": "Section 3, fictional fixture: The comparison cannot distinguish two explanations in this setting."}]),
        encoding="utf-8",
    )
    gap_ok = tmp_path / "gap_ok.json"
    gap_ok.write_text(json.dumps(gap), encoding="utf-8")
    ok = run_cli(SCRIPTS_DIR / "check_gap_record.py", [str(gap_ok), "--evidence-dir", str(ev_dir)])
    assert ok.returncode == 0, f"stderr={ok.stderr} stdout={ok.stdout}"
    assert ok.json_out["valid_structure"] is True

    gap_bad = json.loads(json.dumps(gap))
    gap_bad["evidence"][0]["claim"] = "Completely fabricated claim absent from any local extracted block."
    gap_bad_path = tmp_path / "gap_bad.json"
    gap_bad_path.write_text(json.dumps(gap_bad), encoding="utf-8")
    bad = run_cli(SCRIPTS_DIR / "check_gap_record.py", [str(gap_bad_path), "--evidence-dir", str(ev_dir)])
    assert bad.returncode == 1
    assert bad.json_out["valid_structure"] is False


def test_t1_d6_check_gap_campaign_gcn_precedent_gate(tmp_path: Path) -> None:
    """T1-D6 (F11): check_gap_campaign.py passes not_a_gap and rejects mutated supported_candidate against direct_precedent."""
    rec_path = EVAL_FIXTURES_DIR / "gcn-direct-precedent-record.json"
    camp_path = EVAL_FIXTURES_DIR / "gcn-precedent-campaign.json"
    ok = run_cli(SCRIPTS_DIR / "check_gap_campaign.py", [str(rec_path), str(camp_path)])
    assert ok.returncode == 0, f"stderr={ok.stderr}"
    assert ok.json_out["valid_structure_and_manifest"] is True

    mutated = json.loads(rec_path.read_text(encoding="utf-8"))
    mutated["candidates"][0]["disposition"] = "supported_candidate"
    mutated["candidates"][0]["consequence"] = "Would alter model design"
    mutated["candidates"][0]["answer_path"] = "Controlled benchmark"
    mut_path = tmp_path / "mutated_gap.json"
    mut_path.write_text(json.dumps(mutated), encoding="utf-8")
    bad = run_cli(SCRIPTS_DIR / "check_gap_campaign.py", [str(mut_path), str(camp_path)])
    assert bad.returncode == 1
    assert "candidates:G1:direct_precedent_conflicts_with_positive_gap" in bad.json_out["errors"]


def test_t1_d7_check_ai_cs_research_plan_confirmatory_with_campaign(tmp_path: Path) -> None:
    """T1-D7 (F11): check_ai_cs_research_plan.py passes confirmatory plan with all 6 passed engineering checks and --campaign."""
    gap = json.loads((REFS_DIR / "ai-cs-gap.fixture.json").read_text(encoding="utf-8"))
    rq = json.loads((REFS_DIR / "ai-cs-question.fixture.json").read_text(encoding="utf-8"))
    plan = json.loads((REFS_DIR / "ai-cs-experiment-plan.fixture.json").read_text(encoding="utf-8"))
    camp = json.loads((EVAL_FIXTURES_DIR / "gcn-precedent-campaign.json").read_text(encoding="utf-8"))

    # Align gap queries & candidate search_query_ids with campaign
    gap["queries"] = [
        {"id": "Q1", "campaign_query_id": "direct-1", "source": "openalex", "query": "semi supervised graph convolution normalized adjacency", "family": "direct_problem", "status": "bounded_partial", "retrieved": 10, "inspected": 10},
        {"id": "Q2", "campaign_query_id": "closure-1", "source": "arxiv", "query": "ti:semi-supervised AND ti:graph AND ti:convolutional", "family": "closure", "status": "bounded_partial", "retrieved": 20, "inspected": 20},
    ]
    gap["candidates"][0]["search_query_ids"] = ["Q1", "Q2"]
    gap["candidates"][0]["kill_query_ids"] = ["Q2"]

    plan["claim_mode"] = "confirmatory"
    for k in plan["engineering_checks"]:
        plan["engineering_checks"][k]["status"] = "passed"

    gp, rqp, pp, cp = tmp_path / "gap.json", tmp_path / "rq.json", tmp_path / "plan.json", tmp_path / "camp.json"
    gp.write_text(json.dumps(gap), encoding="utf-8")
    rqp.write_text(json.dumps(rq), encoding="utf-8")
    pp.write_text(json.dumps(plan), encoding="utf-8")
    cp.write_text(json.dumps(camp), encoding="utf-8")

    res = run_cli(SCRIPTS_DIR / "check_ai_cs_research_plan.py", [str(gp), str(rqp), str(pp), "--campaign", str(cp)])
    assert res.returncode == 0, f"stderr={res.stderr} stdout={res.stdout}"
    assert res.json_out["status"] == "structurally_reviewable"
    assert res.json_out["campaign_manifest_check"]["valid_structure_and_manifest"] is True


# =============================================================================
# Area E: Engineering Diagnostics, Alignment & Experiment Manifests (6 tests)
# =============================================================================


def test_t1_e1_engineering_diagnostics_clean_repo_passes(tmp_path: Path) -> None:
    """T1-E1 (F12): check_engineering_diagnostics.py returns PASS on clean ML repo + splits + metrics."""
    ws = WorkspaceFactory.make_ml_repo(tmp_path / "clean_repo")
    res = run_cli(
        SCRIPTS_DIR / "check_engineering_diagnostics.py",
        ["--code-dir", str(ws["code_dir"]), "--splits", str(ws["splits_csv"]), "--metrics", str(ws["metrics_json"])],
    )
    assert res.returncode == 0, f"stderr={res.stderr} stdout={res.stdout}"
    assert res.json_out["verdict"] == "PASS"
    assert res.json_out["findings"] == []


def test_t1_e2_engineering_diagnostics_detects_preprocessing_before_split(tmp_path: Path) -> None:
    """T1-E2 (F12): check_engineering_diagnostics.py detects scaler.fit_transform(X) before train_test_split."""
    ws = WorkspaceFactory.make_ml_repo(tmp_path / "leaky_repo", leaky_preprocessing=True)
    res = run_cli(SCRIPTS_DIR / "check_engineering_diagnostics.py", ["--code-dir", str(ws["code_dir"])])
    assert res.returncode == 1, f"expected exit 1, got {res.returncode}: {res.stdout}"
    assert res.json_out["verdict"] == "ENGINEERING_BUG_DETECTED"
    assert len(res.json_out["findings"]) >= 1
    blob = json.dumps(res.json_out["findings"]).lower()
    assert "fit_transform" in blob or "leak" in blob or "preprocess" in blob


def test_t1_e3_engineering_diagnostics_detects_split_overlap_and_missing_baseline(tmp_path: Path) -> None:
    """T1-E3 (F12): check_engineering_diagnostics.py detects overlapping split IDs and missing baseline/sanity control."""
    ws = WorkspaceFactory.make_ml_repo(tmp_path / "bad_splits", overlapping_splits=True, missing_baseline=True)
    res = run_cli(
        SCRIPTS_DIR / "check_engineering_diagnostics.py",
        ["--splits", str(ws["splits_csv"]), "--metrics", str(ws["metrics_json"])],
    )
    assert res.returncode == 1
    assert res.json_out["verdict"] == "ENGINEERING_BUG_DETECTED"
    blob = json.dumps(res.json_out["findings"]).lower()
    assert any(k in blob for k in ("overlap", "duplicate", "split"))
    assert any(k in blob for k in ("baseline", "sanity", "control"))


def test_t1_e4_audit_alignment_counts_mismatches_duplicates_and_split_disagreement(tmp_path: Path) -> None:
    """T1-E4 (F12): audit_alignment.py computes exact positionwise mismatches, duplicates, and split disagreements."""
    feat = tmp_path / "features.csv"
    lbl = tmp_path / "labels.csv"
    with feat.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerows([["sample_id", "split"], ["S1", "train"], ["S2", "train"], ["S2", "val"], ["S3", "test"]])
    with lbl.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerows([["sample_id", "split"], ["S3", "train"], ["S1", "train"], ["S2", "train"], ["S4", "test"]])

    res = run_cli(SCRIPTS_DIR / "audit_alignment.py", [str(feat), str(lbl), "--split-column", "split"])
    assert res.returncode == 0, f"stderr={res.stderr}"
    d = res.json_out
    assert d["feature_duplicate_id_rows"] == 1
    assert d["positionwise_id_mismatches"] == 3
    assert d["shared_ids_with_split_disagreement"] == 2
    assert d["feature_ids_without_labels"] == 0
    assert d["label_ids_without_features"] == 1


def test_t1_e5_check_experiment_manifest_verify_files_passes(tmp_path: Path) -> None:
    """T1-E5 (F12): check_experiment_manifest.py --verify-files passes on valid SHA-256 and matching on-disk run outputs."""
    manifest = WorkspaceFactory.make_verified_experiment_workspace(tmp_path / "exp_ok")
    res = run_cli(SCRIPTS_DIR / "check_experiment_manifest.py", [str(manifest), "--verify-files"])
    assert res.returncode == 0, f"stderr={res.stderr} stdout={res.stdout}"
    assert res.json_out["status"] == "structurally_checked"
    assert res.json_out["comparison_status"] == "matched_receipts_found"
    assert res.json_out["errors"] == []


def test_t1_e6_check_experiment_manifest_verify_files_catches_tampered_value_and_hash(tmp_path: Path) -> None:
    """T1-E6 (F12): check_experiment_manifest.py --verify-files rejects numeric discrepancy and SHA-256 mismatch."""
    m_val = WorkspaceFactory.make_verified_experiment_workspace(tmp_path / "exp_val", tamper_result_value=True)
    r_val = run_cli(SCRIPTS_DIR / "check_experiment_manifest.py", [str(m_val), "--verify-files"])
    assert r_val.returncode in (1, 2)
    assert r_val.json_out["status"] == "invalid"
    assert r_val.json_out["errors"]

    m_hash = WorkspaceFactory.make_verified_experiment_workspace(tmp_path / "exp_hash", tamper_artifact_bytes=True)
    r_hash = run_cli(SCRIPTS_DIR / "check_experiment_manifest.py", [str(m_hash), "--verify-files"])
    assert r_hash.returncode in (1, 2)
    assert r_hash.json_out["status"] == "invalid"
    assert any("sha" in e.lower() or "hash" in e.lower() or "mismatch" in e.lower() for e in r_hash.json_out["errors"])


# =============================================================================
# Area F: Venue Capture, Plans, Panels & Scorecards (7 tests)
# =============================================================================


def test_t1_f1_capture_and_check_venue_sources_clean_html(
    mock_server: MockScholarlyServer, tmp_path: Path
) -> None:
    """T1-F1 (F13): capture_venue_sources + check_venue_sources verify clean ICML 2027 HTML CFP & fees."""
    cfp_url = mock_server.url("/icml2027/cfp")
    fee_url = mock_server.url("/icml2027/fees")
    mock_server.add_route(
        "/icml2027/cfp",
        (200, "text/html", "<html><body><h1>ICML 2027</h1><p>Main Conference Track. Abstract registration January 28, 2027 AoE. Full paper February 4, 2027 AoE.</p></body></html>"),
    )
    mock_server.add_route(
        "/icml2027/fees",
        (200, "text/html", "<html><body><p>Author registration fee is USD 400.</p></body></html>"),
    )
    now_iso = iso_utc(0)
    dossier = {
        "venue": "ICML",
        "edition": "2027",
        "track": "Main Conference Track",
        "official_cfp_url": cfp_url,
        "checked_at": now_iso,
        "user_timezone": "Asia/Saigon",
        "milestones": {"abstract_registration": "2027-01-28T23:59:00 AoE", "full_paper": "2027-02-04T23:59:00 AoE"},
        "currency": "USD",
        "budget_currency": "USD",
        "budget": 500,
        "presentation_mode": "online",
        "evidence_claims": [
            {"field": "venue", "source_url": cfp_url, "quote": "ICML 2027"},
            {"field": "edition", "source_url": cfp_url, "quote": "ICML 2027"},
            {"field": "track", "source_url": cfp_url, "quote": "Main Conference Track"},
            {"field": "milestones.abstract_registration", "source_url": cfp_url, "quote": "Abstract registration January 28, 2027 AoE"},
            {"field": "milestones.full_paper", "source_url": cfp_url, "quote": "Full paper February 4, 2027 AoE"},
            {"field": "fees.author_registration", "source_url": fee_url, "quote": "Author registration fee is USD 400"},
        ],
        "fees": [
            {"category": "submission", "name": "Submission fee", "mandatory": False, "amount": 0},
            {"category": "publication", "name": "Publication fee", "mandatory": False, "amount": 0},
            {"category": "author_registration", "name": "Author registration", "mandatory": True, "amount": 400, "source_url": fee_url, "checked_at": now_iso},
            {"category": "overlength", "name": "Overlength", "mandatory": False, "amount": 0},
            {"category": "tax", "name": "Tax", "mandatory": False, "amount": 0},
        ],
    }
    dp = tmp_path / "dossier.json"
    dp.write_text(json.dumps(dossier), encoding="utf-8")

    cap = run_cli(SCRIPTS_DIR / "capture_venue_sources.py", [str(dp)], env=mock_server.env())
    assert cap.returncode == 0, f"stderr={cap.stderr}"
    assert all(s["extraction_status"] == "html_text_extracted" for s in cap.json_out["sources"])

    bp = tmp_path / "bundle.json"
    bp.write_text(cap.stdout, encoding="utf-8")
    chk = run_cli(SCRIPTS_DIR / "check_venue_sources.py", [str(dp), str(bp)])
    assert chk.returncode == 0, f"stderr={chk.stderr}"
    assert chk.json_out["source_text_status"] == "all_supplied_critical_quotes_found"
    assert all(c["status"] == "quote_found" for c in chk.json_out["claims"])


def test_t1_f2_check_venue_plan_aoe_conversion_and_budget(tmp_path: Path) -> None:
    """T1-F2 (F13): check_venue_plan.py converts AoE to Asia/Saigon (+19h), sums mandatory fees, computes schedule."""
    dossier = json.loads((REFS_DIR / "venue-dossier.schema-example.json").read_text(encoding="utf-8"))
    now_iso = iso_utc(0)
    dossier["checked_at"] = now_iso
    for fee in dossier["fees"]:
        cat = fee["category"]
        fee["amount"] = 400 if cat == "author_registration" else 0
        if fee["mandatory"]:
            fee["checked_at"] = now_iso
    dp = tmp_path / "dossier.json"
    dp.write_text(json.dumps(dossier), encoding="utf-8")

    res = run_cli(SCRIPTS_DIR / "check_venue_plan.py", [str(dp)])
    assert res.returncode == 0, f"stderr={res.stderr}"
    d = res.json_out
    assert d["milestones_user_timezone"]["abstract_registration"].startswith("2027-01-29T18:59:00+07:00")
    assert d["within_budget"] is True
    assert d["mandatory_known_total"] == 400
    assert len(d["backward_schedule"]["tasks"]) == 2


def test_t1_f3_venue_panel_collector_pmlr_panel(mock_server: MockScholarlyServer, tmp_path: Path) -> None:
    """T1-F3 (F14): venue_panel_collector.py scrapes mock PMLR v235 index into 5-paper compare_venue_novelty panel."""
    p = _load_payloads()
    mock_server.add_route("/v235/", (200, "text/html", p["pmlr_v235_html"]), host="proceedings.mlr.press")
    mock_server.add_route("/v235", (200, "text/html", p["pmlr_v235_html"]), host="proceedings.mlr.press")

    out = tmp_path / "panel.json"
    res = run_cli(
        SCRIPTS_DIR / "venue_panel_collector.py",
        ["--source", "pmlr", "--venue-id", "v235", "--limit", "5", "--out", str(out)],
        env=mock_server.env(),
    )
    assert res.returncode == 0, f"stderr={res.stderr} stdout={res.stdout}"
    data = json.loads(out.read_text(encoding="utf-8"))
    panel = data.get("accepted_panel", data if isinstance(data, list) else [])
    assert len(panel) == 5
    for item in panel:
        assert item["official_acceptance_url"].startswith("https://")
        assert item.get("track")
        assert isinstance(item.get("year"), int)


def test_t1_f4_compare_venue_novelty_fixture_passes(tmp_path: Path) -> None:
    """T1-F4 (F14): compare_venue_novelty.py passes valid 5-paper full_text panel with fit_score=8, median=6."""
    profile = json.loads((REFS_DIR / "venue-novelty-profile.fixture.json").read_text(encoding="utf-8"))
    profile["venue"]["checked_at_utc"] = iso_utc(0)
    pp = tmp_path / "profile.json"
    pp.write_text(json.dumps(profile), encoding="utf-8")

    res = run_cli(SCRIPTS_DIR / "compare_venue_novelty.py", [str(pp)])
    assert res.returncode == 0, f"stderr={res.stderr}"
    d = res.json_out
    assert d["status"] == "structurally_checked"
    assert d["fit_score_out_of_10"] == 8
    assert d["novelty_comparison"]["accepted_panel_size"] == 5
    assert d["novelty_comparison"]["accepted_panel_median_score"] == 6


def test_t1_f5_compare_scorecards_with_verified_sources_dir(tmp_path: Path) -> None:
    """T1-F5 (F14): compare_scorecards.py --sources-dir passes when all evidence_locators match local source files."""
    sc = json.loads((REFS_DIR / "scorecards.schema-example.json").read_text(encoding="utf-8"))
    sc["weight_scenarios"] = [sc["weight_scenarios"][0]]
    sdir = tmp_path / "sources_dir"
    sdir.mkdir()
    for prof in sc["profiles"]:
        lines = []
        for locs in prof["evidence_locators"].values():
            for loc in locs:
                lines.append(loc)
                lines.append(re.sub(r"[\s:;,|\-]+", " ", loc).strip())
        (sdir / f"{prof['id']}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    sp = tmp_path / "scorecards.json"
    sp.write_text(json.dumps(sc), encoding="utf-8")

    res = run_cli(SCRIPTS_DIR / "compare_scorecards.py", [str(sp), "--sources-dir", str(sdir)])
    assert res.returncode == 0, f"stderr={res.stderr}"
    assert res.json_out["status"] == "structurally_comparable"
    assert res.json_out["ranking_sensitivity"] == "stable_top_within_supplied_weights"


def test_t1_f6_compare_scorecards_rejects_missing_locator_or_abstract_basis(tmp_path: Path) -> None:
    """T1-F6 (F14): compare_scorecards.py --sources-dir exits 1 on unverified locator or abstract reading_basis."""
    sc = json.loads((REFS_DIR / "scorecards.schema-example.json").read_text(encoding="utf-8"))
    sdir = tmp_path / "sources_dir"
    sdir.mkdir()
    (sdir / "partial.md").write_text("only unrelated text\n", encoding="utf-8")
    sp = tmp_path / "scorecards.json"
    sp.write_text(json.dumps(sc), encoding="utf-8")

    res_loc = run_cli(SCRIPTS_DIR / "compare_scorecards.py", [str(sp), "--sources-dir", str(sdir)])
    assert res_loc.returncode != 0
    assert res_loc.json_out["status"] == "not_comparable"

    sc_abs = json.loads((REFS_DIR / "scorecards.schema-example.json").read_text(encoding="utf-8"))
    sc_abs["profiles"][0]["reading_basis"] = "abstract"
    sp_abs = tmp_path / "scorecards_abs.json"
    sp_abs.write_text(json.dumps(sc_abs), encoding="utf-8")
    res_abs = run_cli(SCRIPTS_DIR / "compare_scorecards.py", [str(sp_abs)])
    assert res_abs.returncode != 0
    assert res_abs.json_out["status"] == "not_comparable"


def test_t1_f7_capture_and_check_venue_sources_pdf_cfp(
    mock_server: MockScholarlyServer, tmp_path: Path
) -> None:
    """T1-F7 (F13): capture_venue_sources + check_venue_sources extract and verify an application/pdf CFP."""
    cfp_pdf = PdfFactory.make_clean_paper_pdf(
        tmp_path / "cfp.pdf",
        title="ICML 2027 Call for Papers",
        quote_p1="Main Conference Track. Full paper deadline February 4, 2027 AoE.",
    )
    cfp_url = mock_server.url("/icml2027/cfp.pdf")
    mock_server.add_route("/icml2027/cfp.pdf", (200, "application/pdf", cfp_pdf.read_bytes()))
    now_iso = iso_utc(0)
    dossier = {
        "venue": "ICML",
        "edition": "2027",
        "track": "Main Conference Track",
        "official_cfp_url": cfp_url,
        "checked_at": now_iso,
        "user_timezone": "UTC",
        "milestones": {"abstract_registration": None, "full_paper": "2027-02-04T23:59:00 AoE"},
        "currency": "USD",
        "budget_currency": "USD",
        "budget": 100,
        "presentation_mode": "online",
        "evidence_claims": [
            {"field": "venue", "source_url": cfp_url, "quote": "ICML 2027"},
            {"field": "edition", "source_url": cfp_url, "quote": "ICML 2027"},
            {"field": "track", "source_url": cfp_url, "quote": "Main Conference Track"},
            {"field": "milestones.full_paper", "source_url": cfp_url, "quote": "Full paper deadline February 4, 2027 AoE"},
        ],
        "fees": [],
    }
    dp = tmp_path / "pdf_dossier.json"
    dp.write_text(json.dumps(dossier), encoding="utf-8")

    cap = run_cli(SCRIPTS_DIR / "capture_venue_sources.py", [str(dp)], env=mock_server.env())
    assert cap.returncode == 0, f"stderr={cap.stderr}"
    assert cap.json_out["sources"][0]["extraction_status"] == "pdf_text_extracted"

    bp = tmp_path / "bundle.json"
    bp.write_text(cap.stdout, encoding="utf-8")
    chk = run_cli(SCRIPTS_DIR / "check_venue_sources.py", [str(dp), str(bp)])
    assert chk.returncode == 0
    assert chk.json_out["source_text_status"] == "all_supplied_critical_quotes_found"


# =============================================================================
# Area G: K-Dense Suites, ResearchRadar, Attribution & CLI Help (8 tests)
# =============================================================================


def test_t1_g1_kdense_scientific_writing_suite_and_tamper_detection(tmp_path: Path) -> None:
    """T1-G1 (F15): All 6 K-Dense scientific-writing scripts run via CLI; claim tampering causes audit_claims.py exit 1."""
    kd = MODULES_DIR / "kdense-scientific-writing" / "scripts"
    ws = tmp_path / "draft"
    scaf = run_cli(
        kd / "scaffold_manuscript.py",
        ["--output-dir", str(ws), "--document-id", "e2e-doc", "--study-design", "observational_cohort", "--guideline", "strobe"],
    )
    assert scaf.returncode == 0, f"stderr={scaf.stderr}"

    # Populate verified source_manifest, manuscript, claims.csv, consistency, authorship, reporting_coverage
    claim_line = "Cohort accuracy reached 81.5% across 200 samples."
    digest = hashlib.sha256(claim_line.encode("utf-8")).hexdigest()
    manuscript_path = ws / "manuscript.md"
    manuscript_path.write_text(f"# Results\n\n{claim_line} [claim:C001] [evidence:E001]\n", encoding="utf-8")

    claims_csv = ws / "claims.csv"
    with claims_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["claim_id", "section", "claim_kind", "claim_text_sha256", "evidence_ids", "verification_status", "uncertainty", "analysis_intent"])
        w.writerow(["C001", "results", "result", digest, "E001", "verified", "low", "confirmatory"])

    src_manifest = ws / "source_manifest.json"
    src_data = json.loads(src_manifest.read_text(encoding="utf-8"))
    src_data["sources"][0].update({
        "evidence_id": "E001",
        "title": "Benchmark Graph Study",
        "source_type": "journal_article",
        "locator": "Section 4, Table 1",
        "identifiers": {"doi": "10.1000/e2e-001", "isbn": "", "pmcid": "", "pmid": "", "url": "https://example.org/e2e-001"},
        "verification": {"source_opened": True, "status": "verified", "verified_by": "author", "verified_on": "2026-11-21"},
        "year": 2026,
    })
    src_manifest.write_text(json.dumps(src_data, indent=2), encoding="utf-8")

    # Run validate_manifest, check_references, audit_claims
    r_val = run_cli(kd / "validate_manifest.py", [str(src_manifest), "--kind", "source", "--require-verified"])
    assert r_val.returncode == 0, f"validate_manifest: {r_val.stdout} {r_val.stderr}"
    r_ref = run_cli(kd / "check_references.py", [str(src_manifest)])
    assert r_ref.returncode == 0, f"check_references: {r_ref.stdout} {r_ref.stderr}"
    r_aud = run_cli(kd / "audit_claims.py", [str(manuscript_path), str(claims_csv), str(src_manifest)])
    assert r_aud.returncode == 0, f"audit_claims: {r_aud.stdout} {r_aud.stderr}"

    # Check scaffolded consistency / authorship / reporting scripts run cleanly on valid payloads
    for script_name, arg_file in (
        ("check_consistency.py", ws / "consistency_manifest.json"),
        ("validate_authorship.py", ws / "authorship.json"),
        ("select_reporting_guidelines.py", ws / "reporting_coverage.json"),
    ):
        assert arg_file.exists(), f"missing scaffolded file: {arg_file}"
        cmd_args = ["check", str(arg_file)] if script_name == "select_reporting_guidelines.py" else [str(arg_file)]
        sub_res = run_cli(kd / script_name, cmd_args)
        assert sub_res.returncode in (0, 1) and isinstance(sub_res.json_out, dict)
        assert sub_res.json_out.get("status") in {"pass", "fail", "warn"}, (
            f"{script_name} missing valid status: {sub_res.json_out!r}"
        )
        assert sub_res.json_out.get("tool") == Path(script_name).stem, (
            f"{script_name} unexpected tool field: {sub_res.json_out!r}"
        )

    # Tamper claim line without re-hashing -> audit_claims.py MUST exit 1
    manuscript_path.write_text("# Results\n\nCohort accuracy reached 95.0% across 200 samples. [claim:C001] [evidence:E001]\n", encoding="utf-8")
    r_bad = run_cli(kd / "audit_claims.py", [str(manuscript_path), str(claims_csv), str(src_manifest)])
    assert r_bad.returncode == 1


def test_t1_g2_kdense_hypothesis_generation_scripts(tmp_path: Path) -> None:
    """T1-G2 (F15): Bundled K-Dense hypothesis-generation scripts validate good fixtures and reject defects."""
    mod = MODULES_DIR / "kdense-hypothesis-generation"
    scripts = mod / "scripts"
    assets = mod / "assets"

    assert run_cli(scripts / "validate_hypothesis_schema.py", [str(assets / "hypothesis_record_template.json")]).returncode == 0
    assert run_cli(scripts / "check_falsification_controls.py", [str(assets / "falsification_controls_template.json"), "--record", str(assets / "hypothesis_record_template.json")]).returncode == 0
    assert run_cli(scripts / "check_operationalization.py", [str(assets / "operationalization_template.json")]).returncode == 0
    assert run_cli(scripts / "audit_evidence_ledger.py", [str(assets / "evidence_ledger_template.csv"), str(assets / "search_boundary_template.json")]).returncode == 0
    assert run_cli(scripts / "validate_prediction_matrix.py", [str(assets / "prediction_rival_matrix_template.csv")]).returncode == 0

    good_md = tmp_path / "good_causal.md"
    good_md.write_text(
        "Random assignment to X causes outcome Y [claim:causal] [estimand:E1] "
        "[identification:randomized] [confounding:not_applicable] [selection:assessed] "
        "[collider:not_applicable] [reverse-causation:not_applicable].\n",
        encoding="utf-8",
    )
    assert run_cli(scripts / "lint_causal_claims.py", [str(good_md)]).returncode == 0

    bad_md = tmp_path / "bad_causal.md"
    bad_md.write_text("Condition X causes outcome Y without any tags.\n", encoding="utf-8")
    assert run_cli(scripts / "lint_causal_claims.py", [str(bad_md)]).returncode == 1

    bad_fc = json.loads((assets / "falsification_controls_template.json").read_text(encoding="utf-8"))
    bad_fc["hypotheses"][0]["controls"] = []
    bad_fc_path = tmp_path / "bad_fc.json"
    bad_fc_path.write_text(json.dumps(bad_fc), encoding="utf-8")
    assert run_cli(scripts / "check_falsification_controls.py", [str(bad_fc_path)]).returncode != 0


def test_t1_g3_kdense_peer_review_scripts(tmp_path: Path) -> None:
    """T1-G3 (F15): Bundled K-Dense peer-review scripts validate structured reviews and reject abusive/incomplete reviews."""
    mod = MODULES_DIR / "kdense-peer-review"
    scripts = mod / "scripts"
    assets = mod / "assets"

    # Intake, claim_evidence, citations, statistics scripts execute cleanly (rc == 0) and produce structured JSON
    intake_payload = json.loads((assets / "review_intake_template.json").read_text(encoding="utf-8"))
    intake_payload["authorization"]["documented"] = True
    intake_payload["authorization"]["local_processing_authorized"] = True
    intake_payload["reviewer"]["human_accountable"] = True
    intake_payload["reviewer"]["conflict_status"] = "none_identified"
    intake_payload["venue_policy"]["checked"] = True
    intake_payload["venue_policy"]["peer_review_model"] = "double_anonymized"
    intake_payload["ai_use"]["policy"] = "permitted_with_disclosure"
    intake_payload["handling"]["deletion_or_retention_record_planned"] = True
    valid_intake = tmp_path / "valid_intake.json"
    valid_intake.write_text(json.dumps(intake_payload), encoding="utf-8")

    r_int = run_cli(scripts / "validate_review_intake.py", [str(valid_intake)])
    assert r_int.returncode == 0, f"stderr={r_int.stderr} stdout={r_int.stdout}"
    assert r_int.json_out is not None and r_int.json_out["valid"] is True
    r_ce = run_cli(scripts / "validate_claim_evidence.py", [str(assets / "claim_evidence_matrix_template.csv")])
    assert r_ce.returncode == 0, f"stderr={r_ce.stderr} stdout={r_ce.stdout}"
    r_stat = run_cli(scripts / "audit_statistics_reproducibility.py", [str(assets / "statistical_reproducibility_template.json")])
    assert r_stat.returncode == 0, f"stderr={r_stat.stderr} stdout={r_stat.stdout}"
    assert r_stat.json_out is not None

    ref_md = tmp_path / "manuscript_ref.md"
    ref_md.write_text("Prior study [@ref-synthetic-2026] reports baseline metrics.\n", encoding="utf-8")
    r_cit = run_cli(scripts / "audit_citations.py", [str(ref_md), str(assets / "citation_references_template.csv")])
    assert r_cit.returncode == 0, f"stdout={r_cit.stdout} stderr={r_cit.stderr}"

    valid_rev = tmp_path / "valid_review.md"
    valid_rev.write_text(
        "# Comments to authors\n\n"
        "## Summary\nThe manuscript evaluates graph normalization on two benchmarks.\n\n"
        "## Major comments\n\n"
        "### Major comment M1\n"
        "- Location: Section 4, Table 1\n"
        "- Observation: Baseline hyperparameter tuning budget is omitted.\n"
        "- Evidence or criterion: Fair benchmark comparison requires matched tuning budgets.\n"
        "- Why it matters: An untuned baseline exaggerates the apparent gain.\n"
        "- Requested action: Report tuning trials and runtime for all baselines.\n\n"
        "# Confidential comments to editor\n\n"
        "No undisclosed conflicts identified.\n",
        encoding="utf-8",
    )
    assert run_cli(scripts / "lint_review.py", [str(valid_rev)]).returncode == 0

    bad_rev = tmp_path / "bad_review.md"
    bad_rev.write_text(
        "# Comments to authors\n\n### Major comment M1\n- Location: Intro\nThe authors are incompetent and this is garbage.\n\n"
        "# Confidential comments to editor\nNone.\n",
        encoding="utf-8",
    )
    r_bad = run_cli(scripts / "lint_review.py", [str(bad_rev)])
    assert r_bad.returncode == 1
    assert "ABUSIVE_OR_DISMISSIVE_LANGUAGE" in r_bad.stdout


def test_t1_g4_kdense_scholar_evaluation_and_verify_citations(
    mock_server: MockScholarlyServer, tmp_path: Path
) -> None:
    """T1-G4 (F15): Bundled K-Dense scholar-evaluation scripts & verify_citations.py run end-to-end."""
    mod = MODULES_DIR / "kdense-scholar-evaluation"
    scripts = mod / "scripts"
    assets = mod / "assets"

    assert run_cli(scripts / "validate_rubric.py", ["--rubric", str(assets / "rubric_template.json")]).returncode == 0
    assert run_cli(scripts / "calculate_scores.py", ["--rubric", str(assets / "rubric_template.json"), "--evaluation", str(assets / "evaluation_template.json")]).returncode == 0
    assert run_cli(scripts / "summarize_agreement.py", ["--rubric", str(assets / "rubric_template.json"), "--ratings", str(assets / "ratings_template.csv")]).returncode == 0
    assert run_cli(scripts / "check_traceability.py", ["--rubric", str(assets / "rubric_template.json"), "--evaluation", str(assets / "evaluation_template.json"), "--evidence", str(assets / "evidence_manifest_template.json")]).returncode == 0
    proc_payload = json.loads((assets / "process_checklist_template.json").read_text(encoding="utf-8"))
    for sec_key, sec_val in proc_payload.items():
        if isinstance(sec_val, dict):
            for k, v in list(sec_val.items()):
                if isinstance(v, bool):
                    sec_val[k] = True
                elif v == "":
                    sec_val[k] = "REF-E2E-001"
    valid_proc = tmp_path / "valid_process.json"
    valid_proc.write_text(json.dumps(proc_payload), encoding="utf-8")
    r_proc = run_cli(scripts / "check_process.py", ["--process", str(valid_proc)])
    assert r_proc.returncode == 0, f"stderr={r_proc.stderr} stdout={r_proc.stdout}"
    assert r_proc.json_out is not None and r_proc.json_out["status"] == "complete_for_low_stakes_process"

    # Create two complete evaluations whose rankings flip under weight perturbation
    base_eval = json.loads((assets / "evaluation_template.json").read_text(encoding="utf-8"))
    eval_a = json.loads(json.dumps(base_eval))
    eval_b = json.loads(json.dumps(base_eval))
    eval_a["evaluation_id"], eval_a["work_id"] = "EVAL-A", "WORK-A"
    eval_b["evaluation_id"], eval_b["work_id"] = "EVAL-B", "WORK-B"
    scores_a = {"question_scope": 4, "literature_contribution": 2, "method_design": 3, "analysis_claims": 3, "transparency_integrity": 2}
    scores_b = {"question_scope": 2, "literature_contribution": 4, "method_design": 3, "analysis_claims": 2, "transparency_integrity": 3}
    for row in eval_a["ratings"]:
        row["status"] = "rated"
        row["score"] = scores_a[row["criterion_id"]]
        row["uncertainty"] = 0
        row["evidence_ids"] = ["EV-1"]
    for row in eval_b["ratings"]:
        row["status"] = "rated"
        row["score"] = scores_b[row["criterion_id"]]
        row["uncertainty"] = 0
        row["evidence_ids"] = ["EV-2"]
    pa, pb = tmp_path / "eval_a.json", tmp_path / "eval_b.json"
    pa.write_text(json.dumps(eval_a), encoding="utf-8")
    pb.write_text(json.dumps(eval_b), encoding="utf-8")

    r_ws = run_cli(
        scripts / "weight_sensitivity.py",
        ["--rubric", str(assets / "rubric_template.json"), "--evaluation", str(pa), "--evaluation", str(pb), "--delta", "0.5"],
    )
    assert r_ws.returncode == 0, f"stderr={r_ws.stderr} stdout={r_ws.stdout}"
    assert r_ws.json_out is not None

    # verify_citations.py against mock doi.org & Crossref
    vc = MODULES_DIR / "kdense-literature-review" / "scripts" / "verify_citations.py"
    mock_server.add_json("/api/handles/10.48550/arxiv.1609.02907", {"responseCode": 1, "handle": "10.48550/arxiv.1609.02907"}, host="doi.org")
    mock_server.add_json("/works/10.48550/arxiv.1609.02907", {"status": "ok", "message": {"DOI": "10.48550/arxiv.1609.02907", "title": ["GCN"]}}, host="api.crossref.org")
    cit_md = tmp_path / "cits.md"
    cit_md.write_text("See https://doi.org/10.48550/arxiv.1609.02907 for GCN.\n", encoding="utf-8")
    r_vc = run_cli(vc, [str(cit_md)], env=mock_server.env())
    assert r_vc.returncode == 0, f"stderr={r_vc.stderr} stdout={r_vc.stdout}"


def test_t1_g5_radar_cli_papers_citing_limits_and_check(mock_server: MockScholarlyServer) -> None:
    """T1-G5 (F15): radar.py papers, citing, limits, and check work cleanly against mock HTTPS endpoints."""
    p = _load_payloads()
    mock_server.add_route("/api/query", (200, "application/atom+xml", p["arxiv_gcn_xml"]), host="export.arxiv.org")
    mock_server.add_json("/works", p["openalex_gcn"], host="api.openalex.org")
    mock_server.add_route(
        "/html/1609.02907",
        (200, "text/html", "<html><body><article class='ltx_page_main'><h2>Limitations</h2><p>Our method does not scale to billion-edge graphs. Future work should test streaming.</p></article></body></html>"),
        host="arxiv.org",
    )
    mock_server.add_route("/paper_files/", (200, "text/html", "<html>Reviewer 1: OK</html>"), host="proceedings.neurips.cc")
    mock_server.add_json("/search", {"items": []}, host="api.elifesciences.org")
    mock_server.add_json("/graph/v1/paper/search", {"data": []}, host="api.semanticscholar.org")
    mock_server.add_json("/api/records/15866613", {"id": 15866613}, host="zenodo.org")

    env = mock_server.env()
    for sub_args, key in (
        (["papers", "graph", "convolution"], "papers"),
        (["citing", "W2519887557"], "papers"),
        (["limits", "1609.02907"], "sections"),
        (["check"], "arxiv"),
    ):
        res = run_cli(RADAR_SCRIPT, sub_args, env=env)
        assert res.returncode == 0, f"{sub_args} failed: stderr={res.stderr}"
        assert isinstance(res.json_out, dict) and key in res.json_out


def test_t1_g6_radar_verify_quote_matching(tmp_path: Path) -> None:
    """T1-G6 (F15): radar.py verify passes exact/whitespace-folded quotes and exits 1 on case mismatch."""
    rev = tmp_path / "reviews.json"
    rev.write_text(json.dumps({"text": "Renormalized   adjacency\nreduces degree variance."}), encoding="utf-8")

    ok = run_cli(RADAR_SCRIPT, ["verify", str(rev), "Renormalized adjacency reduces degree variance."])
    assert ok.returncode == 0
    assert ok.json_out["all_found"] is True

    bad = run_cli(RADAR_SCRIPT, ["verify", str(rev), "renormalized adjacency reduces degree variance."])
    assert bad.returncode == 1
    assert bad.json_out["all_found"] is False


def test_t1_g7_upstream_attribution_and_claim_audit_repo() -> None:
    """T1-G7 (F16): README, THIRD_PARTY_NOTICES, repository-landscape map all upstream repos & pass claim_audit.py."""
    res = run_cli(SCRIPTS_DIR / "claim_audit.py", ["--suite-root", str(REPO_ROOT), "--readme", str(REPO_ROOT / "README.md")])
    assert res.returncode == 0, f"stderr={res.stderr} stdout={res.stdout}"

    combined = (
        (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        + "\n"
        + (SKILL_DIR / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        + "\n"
        + (REFS_DIR / "repository-landscape.md").read_text(encoding="utf-8")
    ).casefold()
    for repo_token in (
        "gpt researcher", "storm", "paperqa2", "ai-scientist", "perplexica",
        "mineru", "khoj", "k-dense", "humanizer", "researchradar",
        "ai-researcher", "good question", "lit-gap", "scipip", "researchagent", "iris", "ckm-hypogen",
        "obra/superpowers", "affaan-m/ecc", "agent-skills-for-context-engineering",
        "tw93/waza", "scipilot-figure-skill", "codex-claude-academic-skills",
        "yilaai/paper-quality-filter",
    ):
        assert repo_token in combined or repo_token.replace("-", " ") in combined, f"missing attribution for {repo_token}"
    assert "journal_scores.json" in combined
    assert "agpl" in combined and "rails" in combined


def test_t1_cli_help_contract_across_all_scripts() -> None:
    """T1-CLI-HELP (Contract): Every script in research-scientist/scripts/*.py emits real --help usage and rejects invalid flags."""
    scripts = sorted(p for p in SCRIPTS_DIR.glob("*.py") if p.name != "__init__.py")
    assert len(scripts) >= 21
    for script in scripts:
        res = run_cli(script, ["--help"], stdin_text="", timeout=5)
        assert res.returncode == 0, f"{script.name} --help failed (rc={res.returncode}): {res.stderr}"
        help_text = (res.stdout + res.stderr).strip()
        assert len(help_text) >= 100, f"{script.name} --help output too short ({len(help_text)} chars): {help_text!r}"
        assert "usage:" in help_text.lower(), f"{script.name} --help missing 'usage:': {help_text!r}"
        assert "-h" in help_text and "--" in help_text, f"{script.name} --help missing option flags: {help_text!r}"
        assert script.name in help_text, f"{script.name} --help missing script name: {help_text!r}"

        bad = run_cli(script, ["--__nonexistent_e2e_flag__"], stdin_text="", timeout=5)
        err_text = (bad.stderr + bad.stdout).strip()
        assert bad.returncode != 0, f"{script.name} unexpectedly exited 0 on invalid flag"
        assert "error:" in err_text.lower() and script.name in err_text, (
            f"{script.name} invalid-flag output missing error diagnostic: {err_text!r}"
        )
