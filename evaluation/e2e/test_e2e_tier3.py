"""Tier 3 Opaque-Box E2E Cross-Feature Pairwise & Multi-Stage Chains (T3-1 through T3-10)."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

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


def test_t3_1_search_campaign_to_citation_storm_gap_pipeline_and_plan_gate(
    mock_server: MockScholarlyServer, tmp_path: Path
) -> None:
    """T3-1 (Mandatory): F5->F6->F9->F10->F11 search_campaign -> citation_graph/fulltext -> storm -> gap_pipeline -> plan gate."""
    p = _load_payloads()
    mock_server.add_json("/works", p["openalex_gcn"], host="api.openalex.org")
    mock_server.add_route("/api/query", (200, "application/atom+xml", p["arxiv_gcn_xml"]), host="export.arxiv.org")
    mock_server.add_route("/europepmc/webservices/rest/", (200, "application/xml", p["epmc_jats_xml"]), host="www.ebi.ac.uk")
    mock_server.add_json("/tallies/", {"supporting": 12, "mentioning": 30, "contradicting": 0}, host="api.scite.ai")

    plan_doc = {
        "question": "Does OOD degree shift alter rank-fusion calibration?",
        "known_seeds": [{"doi": "10.48550/arxiv.1609.02907"}, {"source": "arxiv", "source_id": "1609.02907"}],
        "queries": [
            {"id": "direct-1", "family": "direct_problem", "query": "graph convolution", "sources": ["openalex"], "size": 10, "pages": 1},
            {"id": "closure-1", "family": "closure", "query": "semi-supervised graph convolutional", "sources": ["arxiv"], "size": 10, "pages": 1},
        ],
    }
    plan_path = tmp_path / "search_plan.json"
    plan_path.write_text(json.dumps(plan_doc), encoding="utf-8")

    camp_res = run_cli(SCRIPTS_DIR / "search_campaign.py", [str(plan_path)], env=mock_server.env())
    assert camp_res.returncode == 0, f"search_campaign failed: {camp_res.stderr}"
    camp_path = tmp_path / "campaign.json"
    camp_path.write_text(camp_res.stdout, encoding="utf-8")

    # Mine fulltext JATS + expand citation graph
    ft_out = tmp_path / "ft.json"
    ft_res = run_cli(SCRIPTS_DIR / "fulltext_mining.py", ["--pmcids", "PMC999001", "--out", str(ft_out)], env=mock_server.env())
    assert ft_res.returncode == 0

    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps([
        {"id": "W2519887557", "source": "openalex", "family": "same_problem", "year": 2016, "title": "GCN", "text": "Renormalized adjacency graph convolution.", "access": "full_text"},
        {"id": "PMC999001", "source": "arxiv", "family": "cross_setting_analogy", "year": 2024, "title": "Graph Convolution Evaluation", "text": "Adaptive edge rewiring under degree shift.", "access": "full_text"},
    ]), encoding="utf-8")
    storm_out = tmp_path / "storm.json"
    st_res = run_cli(SCRIPTS_DIR / "storm_explorer.py", ["--topic", "OOD degree shift graph convolution", "--corpus", str(corpus_path), "--out", str(storm_out)])
    assert st_res.returncode == 0

    # Pass flow in gap_pipeline -> check_ai_cs_research_plan
    digests = tmp_path / "digests.json"
    digests.write_text(json.dumps({
        "W2519887557": {"source_id": "W2519887557", "access": "full_text", "digest": "Does not measure OOD degree shift calibration."},
        "PMC999001": {"source_id": "PMC999001", "access": "full_text", "digest": "Notes future work on degree shift."},
    }), encoding="utf-8")
    cands = tmp_path / "cands.json"
    cands.write_text(json.dumps([
        {"id": "G1", "claim": "OOD degree shift calibration gap", "trigger": "literature_synthesis", "cited_ids": ["W2519887557", "PMC999001"], "support_ids": ["W2519887557", "PMC999001"], "cutoff_year": 2026, "sgha_critics_passed": True, "engineering_checked": True}
    ]), encoding="utf-8")
    gap_out = tmp_path / "gap_out.json"
    gp_ok = run_cli(SCRIPTS_DIR / "gap_pipeline.py", ["--topic", "OOD degree shift", "--corpus", str(corpus_path), "--digests", str(digests), "--candidates", str(cands), "--out", str(gap_out)])
    assert gp_ok.returncode == 0
    assert len(json.loads(gap_out.read_text(encoding="utf-8"))["surviving_gaps"]) == 1

    # Verify check_ai_cs_research_plan --campaign against campaign.json
    gap_rec = json.loads((REFS_DIR / "ai-cs-gap.fixture.json").read_text(encoding="utf-8"))
    rq = json.loads((REFS_DIR / "ai-cs-question.fixture.json").read_text(encoding="utf-8"))
    exp_plan = json.loads((REFS_DIR / "ai-cs-experiment-plan.fixture.json").read_text(encoding="utf-8"))
    gap_rec["queries"] = [
        {"id": "Q1", "campaign_query_id": "direct-1", "source": "openalex", "query": "graph convolution", "family": "direct_problem", "status": "complete", "retrieved": 1, "inspected": 1},
        {"id": "Q2", "campaign_query_id": "closure-1", "source": "arxiv", "query": "semi-supervised graph convolutional", "family": "closure", "status": "complete", "retrieved": 1, "inspected": 1},
    ]
    gap_rec["candidates"][0]["search_query_ids"] = ["Q1", "Q2"]
    gap_rec["candidates"][0]["kill_query_ids"] = ["Q2"]
    exp_plan["claim_mode"] = "confirmatory"
    for k in exp_plan["engineering_checks"]:
        exp_plan["engineering_checks"][k]["status"] = "passed"
    gp_file, rq_file, ep_file = tmp_path / "gap_rec.json", tmp_path / "rq.json", tmp_path / "exp_plan.json"
    gp_file.write_text(json.dumps(gap_rec), encoding="utf-8")
    rq_file.write_text(json.dumps(rq), encoding="utf-8")
    ep_file.write_text(json.dumps(exp_plan), encoding="utf-8")

    p_ok = run_cli(SCRIPTS_DIR / "check_ai_cs_research_plan.py", [str(gp_file), str(rq_file), str(ep_file), "--campaign", str(camp_path)])
    assert p_ok.returncode == 0
    assert p_ok.json_out["status"] == "structurally_reviewable"

    # Fail flow: removing a digest triggers DROP_UNREAD_CITATION; empty known_seed_checks kills confirmatory plan
    digests.write_text(json.dumps({"W2519887557": {"source_id": "W2519887557", "access": "full_text", "digest": "Read."}}), encoding="utf-8")
    gp_bad = run_cli(SCRIPTS_DIR / "gap_pipeline.py", ["--topic", "OOD degree shift", "--corpus", str(corpus_path), "--digests", str(digests), "--candidates", str(cands), "--out", str(gap_out)])
    assert gp_bad.returncode != 0
    codes = {r.get("reason_code") or r.get("code") for r in json.loads(gap_out.read_text(encoding="utf-8"))["rejected_gaps"]}
    assert "DROP_UNREAD_CITATION" in codes

    camp_bad = json.loads(camp_path.read_text(encoding="utf-8"))
    camp_bad["known_seed_checks"] = []
    camp_bad_path = tmp_path / "campaign_empty_seeds.json"
    camp_bad_path.write_text(json.dumps(camp_bad), encoding="utf-8")
    p_bad = run_cli(SCRIPTS_DIR / "check_ai_cs_research_plan.py", [str(gp_file), str(rq_file), str(ep_file), "--campaign", str(camp_bad_path)])
    assert p_bad.returncode == 1


def test_t3_2_pdf_extract_local_evidence_manuscript_ledger_and_humanizer(tmp_path: Path) -> None:
    """T3-2 (Mandatory): F7->F8->F3->F2 extract_pdf_blocks -> local_evidence -> check_manuscript_ledger -> humanizer_lint."""
    quote_txt = "Across Cora and Citeseer, two-layer propagation yields 81.5 percent accuracy without depth collapse."
    pdf_a = PdfFactory.make_clean_paper_pdf(tmp_path / "paper_a.pdf", quote_p2=quote_txt)
    pdf_b = PdfFactory.make_clean_paper_pdf(tmp_path / "paper_b.pdf", title="Study B", quote_p2="Independent validation confirms 81.5 percent accuracy on Cora.")

    blocks_a = tmp_path / "blocks_a.json"
    blocks_b = tmp_path / "blocks_b.json"
    assert run_cli(SCRIPTS_DIR / "extract_pdf_blocks.py", [str(pdf_a), "--out", str(blocks_a)]).returncode == 0
    assert run_cli(SCRIPTS_DIR / "extract_pdf_blocks.py", [str(pdf_b), "--out", str(blocks_b)]).returncode == 0

    qa_out = tmp_path / "qa.json"
    qa_res = run_cli(
        SCRIPTS_DIR / "local_evidence.py",
        ["--inputs", str(blocks_a), str(blocks_b), "--question", "What accuracy does two-layer propagation yield on Cora?", "--min-studies", "2", "--min-evidence", "2", "--out", str(qa_out)],
    )
    assert qa_res.returncode == 0
    qa_data = json.loads(qa_out.read_text(encoding="utf-8"))
    assert qa_data["gate_status"] == "ANSWERABLE"
    top_quote = qa_data["ranked_passages"][0]["quote"]

    sources_dir = tmp_path / "sources_dir"
    sources_dir.mkdir()
    (sources_dir / "paper_a.json").write_text(blocks_a.read_text(encoding="utf-8"), encoding="utf-8")

    ledger = {
        "sources": [{"id": "E1", "type": "paper", "locator": f'paper_a.json "{top_quote[:60]}"', "verified": True, "verified_by": "auditor", "verified_at": "2026-11-21"}],
        "claims": [{"id": "C1", "kind": "reported", "material": True, "source_ids": ["E1"]}],
        "methods": [{"id": "M1", "origin": "reused", "source_ids": ["E1"], "novelty_claimed": False, "grand_name": False}],
        "numeric_facts": [{"id": "N1", "occurrences": [{"location": "results", "value": 81.5, "unit": "percent"}]}],
    }
    lp = tmp_path / "ledger.json"
    lp.write_text(json.dumps(ledger), encoding="utf-8")

    manuscript = tmp_path / "manuscript.md"
    manuscript.write_text(
        "# Evaluation\n"
        "Reusing two-layer normalized adjacency propagation yielded 81.5 percent accuracy on Cora.\n",
        encoding="utf-8",
    )
    assert run_cli(SCRIPTS_DIR / "check_manuscript_ledger.py", ["--ledger", str(lp), "--manuscript", str(manuscript), "--sources-dir", str(sources_dir)]).returncode == 0
    assert run_cli(SCRIPTS_DIR / "humanizer_lint.py", [str(manuscript), "--strict", "--json"]).returncode == 0

    # Fail flows: fabricated 14.2% + grandiose SHNLC fails ledger; AI slop fails humanizer_lint
    bad_ms = tmp_path / "bad_manuscript.md"
    bad_ms.write_text(
        "We introduce SHNLC (Synergistic Hyperbolic Neuro-Lexical Cascade), not merely a model, "
        "which delves into a pivotal tapestry to improve accuracy by 14.2 percent.\n",
        encoding="utf-8",
    )
    assert run_cli(SCRIPTS_DIR / "check_manuscript_ledger.py", ["--ledger", str(lp), "--manuscript", str(bad_ms), "--sources-dir", str(sources_dir)]).returncode == 1
    assert run_cli(SCRIPTS_DIR / "humanizer_lint.py", [str(bad_ms), "--strict", "--json"]).returncode == 1


def test_t3_3_venue_capture_panel_collector_novelty_and_plan_chain(
    mock_server: MockScholarlyServer, tmp_path: Path
) -> None:
    """T3-3 (Mandatory): F13->F14 capture_venue_sources -> check_venue_sources -> venue_panel_collector -> compare_venue_novelty -> check_venue_plan."""
    p = _load_payloads()
    cfp_url = mock_server.url("/icml2027/cfp")
    fee_url = mock_server.url("/icml2027/fees")
    mock_server.add_route("/icml2027/cfp", (200, "text/html", "<html><body>ICML 2027 Main Conference Track. Abstract registration January 28, 2027 AoE. Full paper February 4, 2027 AoE.</body></html>"))
    mock_server.add_route("/icml2027/fees", (200, "text/html", "<html><body>Author registration fee USD 400.</body></html>"))
    mock_server.add_route("/v235/", (200, "text/html", p["pmlr_v235_html"]), host="proceedings.mlr.press")
    mock_server.add_route("/v235", (200, "text/html", p["pmlr_v235_html"]), host="proceedings.mlr.press")

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
            {"field": "fees.author_registration", "source_url": fee_url, "quote": "Author registration fee USD 400"},
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
    assert cap.returncode == 0
    bp = tmp_path / "bundle.json"
    bp.write_text(cap.stdout, encoding="utf-8")
    assert run_cli(SCRIPTS_DIR / "check_venue_sources.py", [str(dp), str(bp)]).returncode == 0

    panel_path = tmp_path / "panel.json"
    assert run_cli(SCRIPTS_DIR / "venue_panel_collector.py", ["--source", "pmlr", "--venue-id", "v235", "--limit", "5", "--out", str(panel_path)], env=mock_server.env()).returncode == 0

    # Merge collected panel into venue-novelty-profile
    profile = json.loads((REFS_DIR / "venue-novelty-profile.fixture.json").read_text(encoding="utf-8"))
    collected = json.loads(panel_path.read_text(encoding="utf-8"))
    collected_items = collected.get("accepted_panel", collected if isinstance(collected, list) else [])
    for idx, row in enumerate(profile["accepted_panel"]):
        if idx < len(collected_items):
            row["official_acceptance_url"] = collected_items[idx]["official_acceptance_url"]
    profile["venue"]["checked_at_utc"] = now_iso
    pp = tmp_path / "profile.json"
    pp.write_text(json.dumps(profile), encoding="utf-8")

    nov_res = run_cli(SCRIPTS_DIR / "compare_venue_novelty.py", [str(pp)])
    assert nov_res.returncode == 0
    assert nov_res.json_out["fit_score_out_of_10"] == 8
    plan_res = run_cli(SCRIPTS_DIR / "check_venue_plan.py", [str(dp)])
    assert plan_res.returncode == 0
    assert plan_res.json_out["within_budget"] is True

    # Fail flow: stale redirect /aaai-27/ -> /aaai-25/ blocks check_venue_sources
    stale_url = mock_server.url("/aaai-27/cfp")
    mock_server.add_route("/aaai-27/cfp", (302, "text/plain", "", {"Location": "/aaai-25/cfp"}))
    mock_server.add_route("/aaai-25/cfp", (200, "text/html", "<html><body>ICML 2027 Main Conference Track</body></html>"))
    dossier["official_cfp_url"] = stale_url
    dossier["evidence_claims"] = [{"field": "venue", "source_url": stale_url, "quote": "ICML 2027"}]
    dp_stale = tmp_path / "dossier_stale.json"
    dp_stale.write_text(json.dumps(dossier), encoding="utf-8")
    cap_s = run_cli(SCRIPTS_DIR / "capture_venue_sources.py", [str(dp_stale)], env=mock_server.env())
    bp_s = tmp_path / "bundle_stale.json"
    bp_s.write_text(cap_s.stdout, encoding="utf-8")
    assert run_cli(SCRIPTS_DIR / "check_venue_sources.py", [str(dp_stale), str(bp_s)]).returncode == 1


def test_t3_4_engineering_diagnostics_manifest_gap_and_plan_rejection_chain(tmp_path: Path) -> None:
    """T3-4 (Mandatory): F12->F10->F11 leaky repo + overlapping splits + disguised trigger fail all 4 gates."""
    ws = WorkspaceFactory.make_ml_repo(tmp_path / "leaky_ws", leaky_preprocessing=True, overlapping_splits=True)
    diag = run_cli(
        SCRIPTS_DIR / "check_engineering_diagnostics.py",
        ["--code-dir", str(ws["code_dir"]), "--splits", str(ws["splits_csv"]), "--metrics", str(ws["metrics_json"])],
    )
    assert diag.returncode == 1
    assert diag.json_out["verdict"] == "ENGINEERING_BUG_DETECTED"

    manifest = WorkspaceFactory.make_verified_experiment_workspace(tmp_path / "exp_ws")
    assert run_cli(SCRIPTS_DIR / "check_experiment_manifest.py", [str(manifest), "--verify-files"]).returncode == 0

    # gap_pipeline rejects candidate with engineering_checked=False (DROP_ENGINEERING_BUG)
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps([
        {"id": "P1", "source": "openalex", "family": "same_problem", "year": 2024, "title": "P1", "abstract": "...", "access": "full_text"},
        {"id": "P2", "source": "arxiv", "family": "cross_setting_analogy", "year": 2025, "title": "P2", "abstract": "...", "access": "full_text"},
    ]), encoding="utf-8")
    digests = tmp_path / "digests.json"
    digests.write_text(json.dumps({
        "P1": {"source_id": "P1", "access": "full_text", "digest": "Read P1."},
        "P2": {"source_id": "P2", "access": "full_text", "digest": "Read P2."},
    }), encoding="utf-8")
    # Feed check_engineering_diagnostics.py's real stdout verdict/findings into gap_pipeline candidate payload
    diag_passed = diag.returncode == 0 and (diag.json_out or {}).get("verdict") == "PASS"
    assert diag_passed is False
    cands = tmp_path / "cands.json"
    cands.write_text(json.dumps([
        {
            "id": "G1",
            "claim": "Leaky benchmark drop claimed as gap",
            "trigger": "benchmark_observation",
            "cited_ids": ["P1", "P2"],
            "support_ids": ["P1", "P2"],
            "cutoff_year": 2026,
            "sgha_critics_passed": True,
            "engineering_checked": diag_passed,
            "engineering_diagnostics": diag.json_out,
        }
    ]), encoding="utf-8")
    gap_out = tmp_path / "gap_out.json"
    gp = run_cli(
        SCRIPTS_DIR / "gap_pipeline.py",
        ["--topic", "benchmark gap", "--corpus", str(corpus), "--digests", str(digests), "--candidates", str(cands), "--out", str(gap_out)],
    )
    assert gp.returncode != 0
    codes = {r.get("reason_code") or r.get("code") for r in json.loads(gap_out.read_text(encoding="utf-8"))["rejected_gaps"]}
    assert "DROP_ENGINEERING_BUG" in codes

    # check_ai_cs_research_plan also blocks confirmatory despite non-failed_implementation trigger
    gap = json.loads((REFS_DIR / "ai-cs-gap.fixture.json").read_text(encoding="utf-8"))
    rq = json.loads((REFS_DIR / "ai-cs-question.fixture.json").read_text(encoding="utf-8"))
    plan = json.loads((REFS_DIR / "ai-cs-experiment-plan.fixture.json").read_text(encoding="utf-8"))
    camp = json.loads((EVAL_FIXTURES_DIR / "gcn-precedent-campaign.json").read_text(encoding="utf-8"))
    gap["queries"] = [
        {"id": "Q1", "campaign_query_id": "direct-1", "source": "openalex", "query": "semi supervised graph convolution normalized adjacency", "family": "direct_problem", "status": "bounded_partial", "retrieved": 10, "inspected": 10},
        {"id": "Q2", "campaign_query_id": "closure-1", "source": "arxiv", "query": "ti:semi-supervised AND ti:graph AND ti:convolutional", "family": "closure", "status": "bounded_partial", "retrieved": 20, "inspected": 20},
    ]
    gap["candidates"][0]["trigger"] = "benchmark_observation"
    gap["candidates"][0]["search_query_ids"] = ["Q1", "Q2"]
    gap["candidates"][0]["kill_query_ids"] = ["Q2"]
    plan["claim_mode"] = "confirmatory"
    for k in plan["engineering_checks"]:
        plan["engineering_checks"][k]["status"] = "passed"
    plan["engineering_checks"]["split_integrity"]["status"] = "failed"
    gp_f, rq_f, pl_f, cp_f = tmp_path / "g.json", tmp_path / "r.json", tmp_path / "p.json", tmp_path / "c.json"
    gp_f.write_text(json.dumps(gap), encoding="utf-8")
    rq_f.write_text(json.dumps(rq), encoding="utf-8")
    pl_f.write_text(json.dumps(plan), encoding="utf-8")
    cp_f.write_text(json.dumps(camp), encoding="utf-8")
    plan_res = run_cli(SCRIPTS_DIR / "check_ai_cs_research_plan.py", [str(gp_f), str(rq_f), str(pl_f), "--campaign", str(cp_f)])
    assert plan_res.returncode == 1, f"failed split_integrity bypassed confirmatory gate: {plan_res.stdout}"
    assert plan_res.json_out["status"] == "invalid"
    plan_errors = plan_res.json_out.get("errors") or []
    pending_or_failed = plan_res.json_out.get("engineering_checks_pending_or_failed") or []
    assert any("engineering" in str(e).lower() or "split_integrity" in str(e).lower() for e in plan_errors), (
        f"expected engineering check failure error, got: {plan_errors}"
    )
    assert (
        "split_integrity" in pending_or_failed
        or any("split_integrity" in str(e) for e in plan_errors)
    ), f"expected split_integrity in engineering_checks_pending_or_failed or errors: {plan_res.json_out}"


def test_t3_5_dedup_retraction_scite_blocks_gap_promotion(
    mock_server: MockScholarlyServer, tmp_path: Path
) -> None:
    """T3-5: F5 dedup + F6 retracted/contradicted DOI flags prevent clean gap promotion in F10."""
    p = _load_payloads()
    mock_server.add_json("/works", p["openalex_gcn"], host="api.openalex.org")
    mock_server.add_route("/api/query", (200, "application/atom+xml", p["arxiv_gcn_xml"]), host="export.arxiv.org")
    mock_server.add_json("/tallies/", {"supporting": 1, "mentioning": 5, "contradicting": 15}, host="api.scite.ai")
    mock_server.add_json("/works/10.48550/arxiv.1609.02907", {
        "status": "ok",
        "message": {"DOI": "10.48550/arxiv.1609.02907", "update-to": [{"type": "retraction"}]},
    }, host="api.crossref.org")

    s_res = run_cli(SCRIPTS_DIR / "search_papers.py", ["graph convolution", "--source", "openalex", "--source", "arxiv"], env=mock_server.env())
    assert s_res.returncode == 0
    assert len(s_res.json_out["dedup_groups"]) == 1

    ft_out = tmp_path / "ft.json"
    ft_res = run_cli(SCRIPTS_DIR / "fulltext_mining.py", ["--dois", "10.48550/arxiv.1609.02907", "--out", str(ft_out)], env=mock_server.env())
    assert ft_res.returncode == 0
    ft_data = json.loads(ft_out.read_text(encoding="utf-8"))
    rec = (ft_data.get("records") or ft_data.get("items") or ft_data.get("dois") or ft_data)[0]
    assert rec["retraction_status"] == "retracted"

    # Feed retracted support into gap_pipeline -> cannot survive cleanly
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps([
        {"id": "10.48550/arxiv.1609.02907", "source": "openalex", "family": "same_problem", "year": 2016, "title": "GCN", "abstract": "...", "access": "full_text", "retraction_status": "retracted"},
        {"id": "P2", "source": "arxiv", "family": "cross_setting_analogy", "year": 2024, "title": "P2", "abstract": "...", "access": "full_text"},
    ]), encoding="utf-8")
    digests = tmp_path / "digests.json"
    digests.write_text(json.dumps({
        "10.48550/arxiv.1609.02907": {"source_id": "10.48550/arxiv.1609.02907", "access": "full_text", "digest": "Retracted."},
        "P2": {"source_id": "P2", "access": "full_text", "digest": "Read P2."},
    }), encoding="utf-8")
    cands = tmp_path / "cands.json"
    cands.write_text(json.dumps([
        {"id": "G1", "claim": "Claim built on retracted support", "trigger": "literature_synthesis", "cited_ids": ["10.48550/arxiv.1609.02907", "P2"], "support_ids": ["10.48550/arxiv.1609.02907", "P2"], "cutoff_year": 2026, "sgha_critics_passed": True, "engineering_checked": True}
    ]), encoding="utf-8")
    gap_out = tmp_path / "gap_out.json"
    gp = run_cli(SCRIPTS_DIR / "gap_pipeline.py", ["--topic", "retracted check", "--corpus", str(corpus), "--digests", str(digests), "--candidates", str(cands), "--out", str(gap_out)])
    assert gp.returncode != 0
    assert json.loads(gap_out.read_text(encoding="utf-8"))["surviving_gaps"] == []


def test_t3_6_storm_uncovered_branches_block_gap_and_evidence_map(tmp_path: Path) -> None:
    """T3-6: F9 storm_explorer uncovered_branches + single-regime 2-paper corpus trigger DROP_INSUFFICIENT_COVERAGE in F10."""
    thin_corpus = tmp_path / "corpus.json"
    thin_corpus.write_text(json.dumps([
        {"id": "P1", "source": "openalex", "family": "same_problem", "year": 2024, "title": "Latency benchmark A", "text": "Only latency benchmark reported on split A.", "access": "full_text"},
        {"id": "P2", "source": "arxiv", "family": "same_problem", "year": 2024, "title": "Latency benchmark B", "text": "Only latency benchmark reported on split B.", "access": "full_text"},
    ]), encoding="utf-8")
    storm_out = tmp_path / "storm.json"
    s_res = run_cli(SCRIPTS_DIR / "storm_explorer.py", ["--topic", "OOD calibration & adversarial robustness", "--corpus", str(thin_corpus), "--out", str(storm_out)])
    assert s_res.returncode == 0
    state = json.loads(storm_out.read_text(encoding="utf-8"))
    state = state.get("storm_state", state)
    assert len(state["uncovered_branches"]) >= 1

    digests = tmp_path / "digests.json"
    digests.write_text(json.dumps({
        "P1": {"source_id": "P1", "access": "full_text", "digest": "Read P1."},
        "P2": {"source_id": "P2", "access": "full_text", "digest": "Read P2."},
    }), encoding="utf-8")
    cands = tmp_path / "cands.json"
    cands.write_text(json.dumps([
        {
            "id": "G1",
            "claim": "OOD calibration gap",
            "trigger": "literature_synthesis",
            "cited_ids": ["P1", "P2"],
            "support_ids": ["P1", "P2"],
            "cutoff_year": 2026,
            "sgha_critics_passed": True,
            "engineering_checked": True,
            "uncovered_branches": state["uncovered_branches"],
        }
    ]), encoding="utf-8")
    gap_out = tmp_path / "gap_out.json"
    gp = run_cli(SCRIPTS_DIR / "gap_pipeline.py", ["--topic", "OOD calibration", "--corpus", str(thin_corpus), "--digests", str(digests), "--candidates", str(cands), "--out", str(gap_out)])
    assert gp.returncode != 0
    codes = {r.get("reason_code") or r.get("code") for r in json.loads(gap_out.read_text(encoding="utf-8"))["rejected_gaps"]}
    assert "DROP_INSUFFICIENT_COVERAGE" in codes
    assert "DROP_SINGLE_PAPER_FRAGILE" not in codes

    ev_map = json.loads((REFS_DIR / "evidence-map.schema-example.json").read_text(encoding="utf-8"))
    ev_map["claims"][0]["status"] = "supported"
    ev_map["claims"][0]["evidence_ids"] = []
    em_path = tmp_path / "ev_map.json"
    em_path.write_text(json.dumps(ev_map), encoding="utf-8")
    assert run_cli(SCRIPTS_DIR / "check_evidence_map.py", [str(em_path)]).returncode == 1


def test_t3_7_pdf_ocr_tables_to_scorecards_locator_and_kdense_sensitivity(tmp_path: Path) -> None:
    """T3-7: F7 extract_pdf_blocks (--tables --ocr) -> F14 compare_scorecards --sources-dir -> F15 K-Dense scholar-evaluation."""
    table_pdf = PdfFactory.make_table_pdf(tmp_path / "table.pdf")
    scan_pdf = PdfFactory.make_scanned_image_pdf(tmp_path / "scan.pdf", text_lines=["Renormalized adjacency reduces variance."])
    sdir = tmp_path / "sources"
    sdir.mkdir()
    assert run_cli(SCRIPTS_DIR / "extract_pdf_blocks.py", [str(table_pdf), "--out", str(sdir / "table.json"), "--tables"]).returncode == 0
    assert run_cli(SCRIPTS_DIR / "extract_pdf_blocks.py", [str(scan_pdf), "--out", str(sdir / "scan.json"), "--ocr"]).returncode == 0

    sc = json.loads((REFS_DIR / "scorecards.schema-example.json").read_text(encoding="utf-8"))
    for p in sc["profiles"]:
        p["evidence_locators"] = {
            "importance": ['table.json "81.5"'],
            "novelty": ['scan.json "Renormalized adjacency"'],
            "soundness": ['table.json "70.3"'],
            "evidence": ['table.json "81.5"'],
            "transparency": ['table.json "GCN"'],
            "clarity": ['scan.json "variance"'],
        }
    sc["profiles"][0]["ratings"] = {"importance": 9, "novelty": 2, "soundness": 7, "evidence": 7, "transparency": 7, "clarity": 7}
    sc["profiles"][1]["ratings"] = {"importance": 2, "novelty": 9, "soundness": 7, "evidence": 7, "transparency": 7, "clarity": 7}
    sc["weight_scenarios"] = [
        {"importance": 35, "novelty": 10, "soundness": 15, "evidence": 15, "transparency": 15, "clarity": 10},
        {"importance": 10, "novelty": 35, "soundness": 15, "evidence": 15, "transparency": 15, "clarity": 10},
    ]
    scp = tmp_path / "sc.json"
    scp.write_text(json.dumps(sc), encoding="utf-8")
    r_sc = run_cli(SCRIPTS_DIR / "compare_scorecards.py", [str(scp), "--sources-dir", str(sdir)])
    assert r_sc.returncode == 0
    assert r_sc.json_out["ranking_sensitivity"] == "top_changes_across_supplied_weights"

    # K-Dense calculate_scores.py
    kd = MODULES_DIR / "kdense-scholar-evaluation"
    assert run_cli(
        kd / "scripts" / "calculate_scores.py",
        ["--rubric", str(kd / "assets" / "rubric_template.json"), "--evaluation", str(kd / "assets" / "evaluation_template.json")],
    ).returncode == 0


def test_t3_8_radar_limits_verify_to_future_work_gap_rejection(
    mock_server: MockScholarlyServer, tmp_path: Path
) -> None:
    """T3-8: F15 radar.py limits & verify succeed on quote, then F10/F11 reject author_future_work-only gap."""
    mock_server.add_route(
        "/html/2310.06825",
        (200, "text/html", "<html><body><article class='ltx_page_main'><h2>Limitations</h2><p>Future work should test on larger graphs with degree shift.</p></article></body></html>"),
        host="arxiv.org",
    )
    lim_res = run_cli(RADAR_SCRIPT, ["limits", "2310.06825"], env=mock_server.env())
    assert lim_res.returncode == 0
    lim_file = tmp_path / "limits.json"
    lim_file.write_text(lim_res.stdout, encoding="utf-8")

    ver_res = run_cli(RADAR_SCRIPT, ["verify", str(lim_file), "Future work should test on larger graphs"])
    assert ver_res.returncode == 0
    assert ver_res.json_out["all_found"] is True

    gap = json.loads((REFS_DIR / "ai-cs-gap.fixture.json").read_text(encoding="utf-8"))
    gap["evidence"][0]["role"] = "author_future_work"
    gap["evidence"][0]["claim"] = "Future work should test on larger graphs"
    gp = tmp_path / "gap_fw.json"
    gp.write_text(json.dumps(gap), encoding="utf-8")
    r_chk = run_cli(SCRIPTS_DIR / "check_gap_record.py", [str(gp)])
    assert r_chk.returncode == 1
    assert "candidates:G1:author_future_work_alone_cannot_establish_gap" in r_chk.json_out["errors"]


def test_t3_9_kdense_scaffold_audit_claims_ledger_and_humanizer_chain(tmp_path: Path) -> None:
    """T3-9: F2 humanizer_lint + F15 K-Dense scaffold/audit_claims/lint_manuscript + F3 check_manuscript_ledger."""
    kd = MODULES_DIR / "kdense-scientific-writing" / "scripts"
    ws = tmp_path / "ws"
    assert run_cli(kd / "scaffold_manuscript.py", ["--output-dir", str(ws), "--document-id", "t3-9", "--study-design", "observational_cohort", "--guideline", "strobe"]).returncode == 0

    orig_line = "Validation accuracy reached 81.5% on Cora across five seeds."
    digest = hashlib.sha256(orig_line.encode("utf-8")).hexdigest()
    orig_ms = tmp_path / "orig.md"
    orig_ms.write_text(f"# Results\n\n{orig_line}\n", encoding="utf-8")

    ms_path = ws / "manuscript.md"
    ms_path.write_text(f"# Results\n\n{orig_line} [claim:C001] [evidence:E001]\n", encoding="utf-8")
    claims_csv = ws / "claims.csv"
    with claims_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["claim_id", "section", "claim_kind", "claim_text_sha256", "evidence_ids", "verification_status", "uncertainty", "analysis_intent"])
        w.writerow(["C001", "results", "result", digest, "E001", "verified", "low", "confirmatory"])

    src_manifest = ws / "source_manifest.json"
    sdata = json.loads(src_manifest.read_text(encoding="utf-8"))
    sdata["sources"][0].update({
        "evidence_id": "E001",
        "title": "Run Log 001",
        "source_type": "dataset",
        "locator": "Table 1",
        "identifiers": {"doi": "10.1000/t39", "isbn": "", "pmcid": "", "pmid": "", "url": "https://example.org/t39"},
        "verification": {"source_opened": True, "status": "verified", "verified_by": "auditor", "verified_on": "2026-11-21"},
        "year": 2026,
    })
    src_manifest.write_text(json.dumps(sdata), encoding="utf-8")

    ledger = {
        "sources": [{"id": "E001", "type": "run_log", "locator": "Validation accuracy reached 81.5%", "verified": True, "verified_by": "auditor", "verified_at": "2026-11-21"}],
        "claims": [{"id": "C001", "kind": "reported", "material": True, "source_ids": ["E001"]}],
        "methods": [{"id": "M1", "origin": "reused", "source_ids": ["E001"], "novelty_claimed": False, "grand_name": False}],
        "numeric_facts": [{"id": "N1", "occurrences": [{"location": "results", "value": 81.5, "unit": "%"}]}],
    }
    lp = tmp_path / "ledger.json"
    lp.write_text(json.dumps(ledger), encoding="utf-8")

    # Clean synchronized pass
    assert run_cli(kd / "audit_claims.py", [str(ms_path), str(claims_csv), str(src_manifest)]).returncode == 0
    assert run_cli(SCRIPTS_DIR / "humanizer_lint.py", [str(ms_path), "--compare-baseline", str(orig_ms), "--strict", "--json"]).returncode == 0
    assert run_cli(SCRIPTS_DIR / "check_manuscript_ledger.py", ["--ledger", str(lp), "--manuscript", str(ms_path)]).returncode == 0

    # Unsynced edit without re-hashing breaks audit_claims; dropping 81.5% breaks humanizer_lint
    ms_path.write_text("# Results\n\nValidation accuracy improved on Cora across five seeds. [claim:C001] [evidence:E001]\n", encoding="utf-8")
    assert run_cli(kd / "audit_claims.py", [str(ms_path), str(claims_csv), str(src_manifest)]).returncode == 1
    assert run_cli(SCRIPTS_DIR / "humanizer_lint.py", [str(ms_path), "--compare-baseline", str(orig_ms), "--strict", "--json"]).returncode == 1


def test_t3_10_skill_md_claim_audit_and_docs_consistency(tmp_path: Path) -> None:
    """T3-10: F1 SKILL.md + F4 claim_audit.py + F16 README/THIRD_PARTY_NOTICES full consistency check."""
    res = run_cli(SCRIPTS_DIR / "claim_audit.py", ["--root", str(SKILL_DIR), "--readme", str(REPO_ROOT / "README.md")])
    assert res.returncode == 0, f"claim_audit failed on live repo: {res.stdout} {res.stderr}"

    # Verify status tokens referenced in docs/contracts actually exist in scripts/
    scripts_blob = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in SCRIPTS_DIR.glob("*.py"))
    for token in ("rate_limited", "bot_blocked", "ABSTAIN", "DROP_UNREAD_CITATION", "DROP_ENGINEERING_BUG"):
        assert token in scripts_blob, f"documented contract token missing in scripts: {token}"

    # Mutating a temp copy with an unimplemented flag triggers exit 1
    bad_root = WorkspaceFactory.copy_skill_tree(tmp_path / "mutated")
    sfile = bad_root / "SKILL.md"
    sfile.write_text(sfile.read_text(encoding="utf-8") + "\nRun `python3 scripts/gap_pipeline.py --invented-flag`.\n", encoding="utf-8")
    bad_res = run_cli(SCRIPTS_DIR / "claim_audit.py", ["--root", str(bad_root), "--readme", str(REPO_ROOT / "README.md")])
    assert bad_res.returncode == 1
