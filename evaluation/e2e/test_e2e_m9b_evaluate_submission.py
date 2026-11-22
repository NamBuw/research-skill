"""Opaque-box E2E tests for M9B evaluate_submission.py chaining real repo CLI outputs."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from helpers import (
    MockScholarlyServer,
    REFS_DIR,
    SCRIPTS_DIR,
    T123_FIXTURES_DIR,
    WorkspaceFactory,
    iso_utc,
    run_cli,
)

MAX_COMPACT_BYTES = 4096
FABRICATED_ODDS_RE = re.compile(
    r"\b\d+(?:\.\d+)?%\s*(?:acceptance|chance|odds|probability)",
    re.IGNORECASE,
)


def _weights():
    return {"importance": 15, "novelty": 20, "soundness": 20, "evidence": 20, "transparency": 15, "clarity": 10}


def _ratings(vals):
    return dict(zip(_weights().keys(), vals))


def _make_clean_repo(repo_dir: Path, *, leak_author: bool = False) -> Path:
    repo_dir.mkdir(parents=True, exist_ok=True)
    (repo_dir / "data").mkdir(parents=True, exist_ok=True)
    (repo_dir / "README.md").write_text(
        "# Clean Repo\n"
        "## Dataset\n"
        "Uses data/splits.csv.\n"
        "## Reproduce\n"
        "Run `python3 train.py --seed 42`\n",
        encoding="utf-8",
    )
    (repo_dir / "requirements.txt").write_text("numpy==1.26.4\n", encoding="utf-8")
    (repo_dir / "LICENSE").write_text("MIT License\nPermission is hereby granted, free of charge...\n", encoding="utf-8")
    (repo_dir / "train.py").write_text(
        "import random\n"
        "def set_seed(seed=42):\n"
        "    random.seed(seed)\n"
        "if __name__ == '__main__':\n"
        "    set_seed(42)\n",
        encoding="utf-8",
    )
    if leak_author:
        (repo_dir / "NOTES.md").write_text("Author: Alice Researcher <alice@university.edu>\n", encoding="utf-8")
    return repo_dir


def _make_clean_tex(tex_dir: Path, *, leak_author: bool = False) -> tuple[Path, Path]:
    tex_dir.mkdir(parents=True, exist_ok=True)
    bib = tex_dir / "refs.bib"
    bib.write_text(
        "@inproceedings{smith2024graph,\n"
        "  title={Graph Propagation Analysis},\n"
        "  author={Smith, Jane},\n"
        "  booktitle={Proceedings of NeurIPS},\n"
        "  year={2024}\n"
        "}\n",
        encoding="utf-8",
    )
    tex = tex_dir / "paper.tex"
    author_line = "\\author{Alice Researcher (alice@university.edu)}" if leak_author else "\\author{Anonymous Authors}"
    tex.write_text(
        "\\documentclass{article}\n"
        "\\usepackage{neurips_2026}\n"
        "\\begin{document}\n"
        f"{author_line}\n"
        "\\cite{smith2024graph}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    return tex, bib


def test_e2e_m9b_happy_path_chain_with_gap_pipeline_and_readiness(tmp_path: Path) -> None:
    """E2E Pass: real score_math + gap_pipeline + repro + diagnostics + ledger + readiness + preflight -> evaluate_submission."""
    # 1. Score input
    sc_in = tmp_path / "scorecard.json"
    sc_in.write_text(json.dumps({"weights": _weights(), "ratings": _ratings((8, 7, 8, 8, 7, 8))}), encoding="utf-8")

    # 2. Clean ML repo -> check_experiment_rigor repro + check_engineering_diagnostics + check_artifact_readiness
    ml_dir = tmp_path / "ml_repo"
    ws_files = WorkspaceFactory.make_ml_repo(ml_dir)
    _make_clean_repo(ml_dir)

    repro_out = tmp_path / "repro.json"
    r_repro = run_cli(SCRIPTS_DIR / "check_experiment_rigor.py", ["repro", str(ml_dir), "--out", str(repro_out)])
    assert r_repro.returncode == 0, r_repro.stderr + r_repro.stdout

    eng_out = tmp_path / "eng.json"
    r_eng = run_cli(
        SCRIPTS_DIR / "check_engineering_diagnostics.py",
        ["--code-dir", str(ml_dir), "--splits", str(ws_files["splits_csv"]), "--metrics", str(ws_files["metrics_json"]), "--out", str(eng_out)],
    )
    assert r_eng.returncode == 0, r_eng.stderr + r_eng.stdout

    art_out = tmp_path / "art.json"
    r_art = run_cli(SCRIPTS_DIR / "check_artifact_readiness.py", ["--repo-dir", str(ml_dir), "--anonymous", "--out", str(art_out)])
    assert r_art.returncode == 0, r_art.stderr + r_art.stdout

    # 3. Clean manuscript ledger
    led_in = tmp_path / "ledger_in.json"
    led_in.write_text((REFS_DIR / "manuscript-ledger.schema-example.json").read_text(encoding="utf-8"), encoding="utf-8")
    led_out = tmp_path / "ledger.json"
    r_led = run_cli(SCRIPTS_DIR / "check_manuscript_ledger.py", ["--ledger", str(led_in), "--out", str(led_out)])
    assert r_led.returncode == 0, r_led.stderr + r_led.stdout

    # 4. Clean preflight (anonymize + bibtex)
    tex, bib = _make_clean_tex(tmp_path / "tex")
    anon_out = tmp_path / "anon.json"
    r_anon = run_cli(SCRIPTS_DIR / "check_submission_preflight.py", ["anonymize", str(tex), "--out", str(anon_out)])
    assert r_anon.returncode == 0, r_anon.stderr + r_anon.stdout
    bib_out = tmp_path / "bib.json"
    r_bib = run_cli(SCRIPTS_DIR / "check_submission_preflight.py", ["bibtex", str(bib), "--tex", str(tex), "--out", str(bib_out)])
    assert r_bib.returncode == 0, r_bib.stderr + r_bib.stdout

    # 5. Real gap_pipeline.py producing canonical idea_seed_bundle
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps({
        "cutoff_date": "2026-01-01",
        "papers": [
            {
                "id": "P1", "source": "openalex", "family": "same_problem", "year": 2024, "published_date": "2024-03-01",
                "title": "Long-Context Retrieval Calibration",
                "abstract": "Studies retrieval drift across 32k tokens.",
                "methods": ["calibration"], "settings": ["long_context"], "metrics": ["f1"], "regimes": ["single_turn"],
                "retraction_status": "clean",
            },
            {
                "id": "P2", "source": "arxiv", "family": "cross_setting_analogy", "year": 2023, "published_date": "2023-09-01",
                "title": "Position Interpolation Bounds",
                "abstract": "Analyzes position scaling in multi-turn windows.",
                "methods": ["interpolation"], "settings": ["long_context"], "metrics": ["accuracy"], "regimes": ["multi_turn"],
                "retraction_status": "clean",
            },
        ],
    }), encoding="utf-8")
    digests_path = tmp_path / "digests.json"
    digests_path.write_text(json.dumps({
        "P1": {"source_id": "P1", "access": "full_text", "digest": "Retrieval drift increases beyond 16k tokens."},
        "P2": {"source_id": "P2", "access": "full_text", "digest": "Interpolation fails without multi-turn calibration."},
    }), encoding="utf-8")
    cands_path = tmp_path / "candidates.json"
    cands_path.write_text(json.dumps({
        "target_venue_tier": "q1_or_tier_a",
        "candidates": [{
            "id": "G1",
            "claim": "Existing long-context calibration overlooks multi-turn entity tracking beyond 32k tokens.",
            "closest_work_ids": ["P1", "P2"],
            "cited_ids": ["P1", "P2"],
            "support_ids": ["P1", "P2"],
            "cutoff_year": 2026,
            "sgha_critics_passed": True,
            "engineering_checked": True,
            "root_cause_barrier": "measurement_gap",
            "why_now_enabler": "Open 128k models now allow controlled multi-turn probes.",
            "so_what_decision_impact": "decision_changing",
            "durability_12_24m": "durable_structural_limit",
            "code_prior_art_screened": True,
            "code_prior_art": [{"id": "CPA1", "platform": "github", "repo_or_url": "https://github.com/org/none", "relation": "none_found", "status": "no_match"}],
        }],
    }), encoding="utf-8")
    seed_bundle_out = tmp_path / "seed_bundle.json"
    gap_out = tmp_path / "gap_out.json"
    r_gap = run_cli(
        SCRIPTS_DIR / "gap_pipeline.py",
        [
            "--topic", "Long-context entity tracking",
            "--corpus", str(corpus_path),
            "--digests", str(digests_path),
            "--candidates", str(cands_path),
            "--subfield-preset", "nlp_llm",
            "--seed-bundle-out", str(seed_bundle_out),
            "--out", str(gap_out),
        ],
    )
    assert r_gap.returncode == 0, r_gap.stderr + r_gap.stdout

    # 6. Evaluate submission!
    final_out = tmp_path / "final_eval.json"
    res = run_cli(
        SCRIPTS_DIR / "evaluate_submission.py",
        [
            "--scorecard", str(sc_in),
            "--rigor", str(repro_out),
            "--engineering-diagnostics", str(eng_out),
            "--ledger", str(led_out),
            "--artifact-readiness", str(art_out),
            "--preflight", str(anon_out),
            "--preflight", str(bib_out),
            "--idea-seed-bundle", str(seed_bundle_out),
            "--subfield-preset", "nlp_llm",
            "--out", str(final_out),
            "--compact",
        ],
    )
    assert res.returncode == 0, res.stderr + res.stdout
    assert len(res.stdout.encode("utf-8")) < MAX_COMPACT_BYTES
    assert res.json_out["ready_to_submit"] is True
    assert res.json_out["verdict"] == "READY_TO_SUBMIT"
    full = json.loads(final_out.read_text(encoding="utf-8"))
    assert full["subfield_preset"] == "nlp_llm"
    assert full["upstream_downstream_linkage"]["idea_seed_bundle"]["schema"] == "research_scientist_idea_seed_bundle_v1"
    assert FABRICATED_ODDS_RE.search(final_out.read_text(encoding="utf-8")) is None


def test_e2e_m9b_cross_tool_fatal_gate_and_desk_reject(tmp_path: Path) -> None:
    """E2E Fatal Gate & Desk-Reject: real contamination + tampered manifest + leaky preflight."""
    sc_in = tmp_path / "scorecard.json"
    sc_in.write_text(json.dumps({"weights": _weights(), "ratings": _ratings((9, 8, 9, 9, 8, 8))}), encoding="utf-8")

    # 1. Contamination via check_experiment_rigor.py
    train_p = tmp_path / "train.jsonl"
    eval_p = tmp_path / "eval.jsonl"
    shared = "renormalized graph convolution propagates features across two layers without depth collapse on cora"
    train_p.write_text(json.dumps({"text": shared}) + "\n", encoding="utf-8")
    eval_p.write_text(json.dumps({"text": shared}) + "\n", encoding="utf-8")
    contam_out = tmp_path / "contam.json"
    r_contam = run_cli(
        SCRIPTS_DIR / "check_experiment_rigor.py",
        ["contamination", "--train", str(train_p), "--eval", str(eval_p), "--out", str(contam_out)],
    )
    assert r_contam.returncode == 1

    # 2. Tampered experiment manifest via check_experiment_manifest.py --verify-files
    exp_ws = WorkspaceFactory.make_verified_experiment_workspace(tmp_path / "exp_ws", tamper_artifact_bytes=True)
    exp_out = tmp_path / "exp_check.json"
    r_exp = run_cli(
        SCRIPTS_DIR / "check_experiment_manifest.py",
        [str(exp_ws / "experiment_manifest.json"), "--verify-files", "--out", str(exp_out)],
    )
    assert r_exp.returncode == 2

    # 3. Leaky preflight anonymize
    tex, _ = _make_clean_tex(tmp_path / "leaky_tex", leak_author=True)
    anon_out = tmp_path / "anon_leak.json"
    r_anon = run_cli(SCRIPTS_DIR / "check_submission_preflight.py", ["anonymize", str(tex), "--out", str(anon_out)])
    assert r_anon.returncode == 1

    res = run_cli(
        SCRIPTS_DIR / "evaluate_submission.py",
        [
            "--scorecard", str(sc_in),
            "--rigor", str(contam_out),
            "--experiment-manifest", str(exp_out),
            "--preflight", str(anon_out),
        ],
    )
    assert res.returncode == 1
    assert res.json_out["ready_to_submit"] is False
    assert res.json_out["cross_tool_fatal_gate"] is True
    assert res.json_out["desk_reject_blocked"] is True
    assert res.json_out["score_evaluation"]["ratings_post_cap"]["evidence"] <= 4
    assert res.json_out["score_evaluation"]["ratings_post_cap"]["soundness"] <= 4
    assert res.json_out["band"] == "not_ready_fatal_gate"


def test_e2e_m9b_portfolio_disqualification_auto_retarget_and_exit2(
    mock_server: MockScholarlyServer, tmp_path: Path
) -> None:
    """E2E Portfolio Retargeting: real MockScholarlyServer CFP capture + stale redirect + check_venue_plan + compare_venue_novelty."""
    # Serve stale redirect for NeurIPS and clean CFP on localhost for EMNLP Findings & Workshop
    mock_server.add_route("/neurips/2027/cfp", (302, "text/html", "", {"Location": "https://cfp.example.org/neurips/2025/cfp"}), host="cfp.example.org")
    mock_server.add_route("/neurips/2025/cfp", (200, "text/html", "<html><body><p>Old 2025 NeurIPS CFP.</p></body></html>"), host="cfp.example.org")
    mock_server.add_route(
        "/emnlp/2027/cfp",
        (200, "text/html", "<html><body><h1>EMNLP 2027 Findings</h1><p>Venue EMNLP Findings Edition 2027 Track Findings. Submission open. Author registration USD 0.</p></body></html>"),
        host="localhost",
    )
    mock_server.add_route(
        "/ws/2027/cfp",
        (200, "text/html", "<html><body><h1>Eval Workshop 2027</h1><p>Venue Eval Workshop Edition 2027 Track Workshop. Submission open. Author registration USD 0.</p></body></html>"),
        host="localhost",
    )
    payloads = json.loads((T123_FIXTURES_DIR / "mock_scholarly_payloads.json").read_text(encoding="utf-8"))
    mock_server.add_route("/v235/", (200, "text/html", payloads["pmlr_v235_html"]), host="proceedings.mlr.press")

    env = mock_server.env()
    emnlp_url = mock_server.url("/emnlp/2027/cfp", host="localhost")
    ws_url = mock_server.url("/ws/2027/cfp", host="localhost")
    neurips_url = mock_server.url("/neurips/2027/cfp", host="localhost")
    mock_server.add_route(
        "/neurips/2027/cfp",
        (200, "text/html", "<html><body><h1>NeurIPS 2027 Main</h1><p>Venue NeurIPS Edition 2027 Track Main. Author registration USD 500.</p></body></html>"),
        host="localhost",
    )

    # 1. Capture + verify NeurIPS stale redirect bundle (for check_venue_sources -> verification_passed=False)
    dos_neurips = tmp_path / "dos_neurips.json"
    dos_neurips.write_text(json.dumps({
        "venue": "NeurIPS",
        "edition": "2027",
        "official_cfp_url": "https://cfp.example.org/neurips/2027/cfp",
        "checked_at": iso_utc(0),
        "evidence_claims": [
            {"field": "cfp", "source_url": "https://cfp.example.org/neurips/2027/cfp", "quote": "Old 2025 NeurIPS CFP."}
        ],
    }), encoding="utf-8")
    cap_neurips = tmp_path / "cap_neurips.json"
    run_cli(SCRIPTS_DIR / "capture_venue_sources.py", [str(dos_neurips), "--out", str(cap_neurips)], env=env)
    vs_neurips = tmp_path / "vs_neurips.json"
    r_vs_n = run_cli(SCRIPTS_DIR / "check_venue_sources.py", [str(dos_neurips), str(cap_neurips), "--out", str(vs_neurips)])
    assert r_vs_n.returncode == 1

    # 2. Capture + verify EMNLP Findings (clean localhost capture -> verification_passed=True)
    dos_emnlp = tmp_path / "dos_emnlp.json"
    dos_emnlp.write_text(json.dumps({
        "venue": "EMNLP Findings",
        "edition": "2027",
        "track": "Findings",
        "official_cfp_url": emnlp_url,
        "checked_at": iso_utc(0),
        "evidence_claims": [
            {"field": "venue", "source_url": emnlp_url, "quote": "EMNLP 2027 Findings"},
            {"field": "edition", "source_url": emnlp_url, "quote": "Edition 2027"},
            {"field": "track", "source_url": emnlp_url, "quote": "Track Findings"},
        ],
    }), encoding="utf-8")
    cap_emnlp = tmp_path / "cap_emnlp.json"
    r_cap_e = run_cli(SCRIPTS_DIR / "capture_venue_sources.py", [str(dos_emnlp), "--out", str(cap_emnlp)], env=env)
    assert r_cap_e.returncode == 0, r_cap_e.stderr
    vs_emnlp = tmp_path / "vs_emnlp.json"
    r_vs_e = run_cli(SCRIPTS_DIR / "check_venue_sources.py", [str(dos_emnlp), str(cap_emnlp), "--out", str(vs_emnlp)])
    assert r_vs_e.returncode == 0, r_vs_e.stderr + r_vs_e.stdout

    # Capture unified snapshot bundle into sources/venue-sources.json for compare_venue_novelty --sources-dir
    src_dir = tmp_path / "sources"
    src_dir.mkdir()
    dos_bundle = tmp_path / "dos_bundle.json"
    dos_bundle.write_text(json.dumps({
        "venue": "Portfolio",
        "edition": "2027",
        "official_cfp_url": emnlp_url,
        "checked_at": iso_utc(0),
        "evidence_claims": [
            {"field": "n", "source_url": neurips_url, "quote": "NeurIPS 2027 Main"},
            {"field": "e", "source_url": emnlp_url, "quote": "Submission open. Author registration USD 0."},
            {"field": "w", "source_url": ws_url, "quote": "Submission open. Author registration USD 0."},
        ],
    }), encoding="utf-8")
    r_cap_b = run_cli(SCRIPTS_DIR / "capture_venue_sources.py", [str(dos_bundle), "--out", str(src_dir / "venue-sources.json")], env=env)
    assert r_cap_b.returncode == 0, r_cap_b.stderr

    # 3. check_venue_plan for NeurIPS (over budget + passed deadline -> check_venue_plan exits 0!)
    plan_n_in = tmp_path / "plan_n_in.json"
    plan_n_in.write_text(json.dumps({
        "venue": "NeurIPS",
        "edition": "2027",
        "track": "Main",
        "official_cfp_url": "https://cfp.example.org/neurips/2027/cfp",
        "checked_at": iso_utc(0),
        "user_timezone": "UTC",
        "presentation_mode": "online",
        "currency": "USD",
        "budget_currency": "USD",
        "budget": 100,
        "fees": [
            {"name": "Submission", "category": "submission", "mandatory": True, "amount": 0, "source_url": "https://cfp.example.org/neurips/2027/cfp", "checked_at": iso_utc(0)},
            {"name": "Publication", "category": "publication", "mandatory": True, "amount": 0, "source_url": "https://cfp.example.org/neurips/2027/cfp", "checked_at": iso_utc(0)},
            {"name": "Author Reg", "category": "author_registration", "mandatory": True, "amount": 500, "source_url": "https://cfp.example.org/neurips/2027/cfp", "checked_at": iso_utc(0)},
            {"name": "Overlength", "category": "overlength", "mandatory": False, "amount": 0, "source_url": "https://cfp.example.org/neurips/2027/cfp", "checked_at": iso_utc(0)},
            {"name": "Tax", "category": "tax", "mandatory": True, "amount": 0, "source_url": "https://cfp.example.org/neurips/2027/cfp", "checked_at": iso_utc(0)},
        ],
        "milestones": {"abstract_registration": iso_utc(-5), "full_paper": iso_utc(-1)},
    }), encoding="utf-8")
    vp_neurips = tmp_path / "vp_neurips.json"
    r_vp_n = run_cli(SCRIPTS_DIR / "check_venue_plan.py", [str(plan_n_in), "--out", str(vp_neurips)])
    assert r_vp_n.returncode == 0  # Important: check_venue_plan exits 0 even on over_budget + passed deadline!

    # 4. Scorecard + portfolio evaluation using real venue_panel_collector + compare_venue_novelty
    sc_in = tmp_path / "sc.json"
    sc_in.write_text(json.dumps({"weights": _weights(), "ratings": _ratings((7, 6, 7, 7, 6, 7))}), encoding="utf-8")

    panel_out = tmp_path / "panel.json"
    r_panel = run_cli(
        SCRIPTS_DIR / "venue_panel_collector.py",
        ["--source", "pmlr", "--venue-id", "v235", "--limit", "5", "--out", str(panel_out)],
        env=env,
    )
    assert r_panel.returncode == 0, r_panel.stderr
    collected = json.loads(panel_out.read_text(encoding="utf-8"))["accepted_panel"]

    (src_dir / "target.txt").write_text("Full text evidence for target paper.\n", encoding="utf-8")
    base_fix = json.loads((REFS_DIR / "venue-novelty-profile.fixture.json").read_text(encoding="utf-8"))
    target = copy.deepcopy(base_fix["target"])
    target.update({
        "id": "target",
        "score": 6,
        "low": 5,
        "high": 7,
        "closest_work_id": "target",
        "closest_work_locator": 'target.txt#L1 "Full text evidence"',
        "assessed_at_utc": iso_utc(0),
    })

    def _build_panel(prefix: str, track_name: str, panel_score: int = 6, panel_overall: float = 6.4):
        rows = copy.deepcopy(base_fix["accepted_panel"])
        for i, row in enumerate(rows):
            pid = f"{prefix}_P{i+1}"
            (src_dir / f"{pid}.txt").write_text(f"Accepted full text evidence for {pid}.\n", encoding="utf-8")
            row["id"] = pid
            row["track"] = track_name
            row["score"] = panel_score
            row["low"] = max(1, panel_score - 1)
            row["high"] = min(10, panel_score + 1)
            row["overall_score"] = panel_overall
            row["topic_relation"] = "different_topic"
            row["closest_work_id"] = pid
            row["closest_work_locator"] = f'{pid}.txt#L1 "Accepted full text evidence"'
            row["assessed_at_utc"] = iso_utc(0)
            if i < len(collected):
                row["official_acceptance_url"] = collected[i]["official_acceptance_url"]
        return rows

    def _cand(vid: str, name: str, track: str, url: str, quote: str, role: str, tier_exp: str, deadline_days: int, notif_days: int, p_score: int = 6, p_ov: float = 6.4):
        psel = copy.deepcopy(base_fix["panel_selection"])
        psel["track"] = track
        return {
            "venue_id": vid,
            "role": role,
            "tier_expectation": tier_exp,
            "venue": {
                "name": name,
                "edition": "2027",
                "track": track,
                "official_cfp_url": url,
                "checked_at_utc": iso_utc(0),
                "max_source_age_days": 14,
                "submission_deadline_utc": iso_utc(deadline_days),
                "notification_date_utc": iso_utc(notif_days),
                "simultaneous_submission_allowed": False,
            },
            "panel_selection": psel,
            "accepted_panel": _build_panel(vid, track, p_score, p_ov),
            "fit_axes": [
                {"name": ax, "score": 2, "source_url": url, "locator": f'"{quote}"', "reason": f"{ax} verified"}
                for ax in ("scope_audience", "contribution_track", "evidence_maturity", "format_eligibility", "user_constraints")
            ],
            "hard_constraints": [
                {"name": cn, "status": "met", "source_url": url, "reason": f"{cn} open"}
                for cn in ("deadline", "budget", "eligibility")
            ],
        }

    vn_in = tmp_path / "vn_in.json"
    vn_in.write_text(json.dumps({
        "target": target,
        "target_scorecard": {"weights": _weights(), "ratings": _ratings((7, 6, 7, 7, 6, 7))},
        "candidate_venues": [
            _cand("neurips_main", "NeurIPS", "Main", neurips_url, "NeurIPS 2027 Main", "primary", "top_tier_flagship", 30, 90, 6, 6.4),
            _cand("emnlp_findings", "EMNLP Findings", "Findings", emnlp_url, "Submission open. Author registration USD 0.", "fallback", "q1_or_tier_a", 120, 160, 6, 6.4),
            _cand("eval_workshop", "Eval Workshop", "Workshop", ws_url, "Submission open. Author registration USD 0.", "fallback", "workshop_or_preliminary", 180, 210, 4, 5.4),
        ],
    }), encoding="utf-8")
    vn_out = tmp_path / "vn_out.json"
    r_vn = run_cli(
        SCRIPTS_DIR / "compare_venue_novelty.py",
        [str(vn_in), "--portfolio", "--sources-dir", str(src_dir), "--target-overall", "6.65", "--out", str(vn_out)],
    )
    assert r_vn.returncode == 0, r_vn.stderr + r_vn.stdout

    # 5. evaluate_submission disqualifies NeurIPS (venue_plan + venue_sources) and auto-retargets to EMNLP Findings (highest surviving tier over Workshop)!
    eval_out = tmp_path / "eval_retarget.json"
    res = run_cli(
        SCRIPTS_DIR / "evaluate_submission.py",
        [
            "--scorecard", str(sc_in),
            "--venue-novelty", str(vn_out),
            "--venue-plan", str(vp_neurips),
            "--venue-sources", str(vs_neurips),
            "--venue-sources", str(vs_emnlp),
            "--target-venue", "NeurIPS",
            "--out", str(eval_out),
            "--compact",
        ],
    )
    assert res.returncode == 0, res.stderr + res.stdout
    assert len(res.stdout.encode("utf-8")) < MAX_COMPACT_BYTES
    assert res.json_out["ready_to_submit"] is True
    assert res.json_out["verdict"] == "RETARGETED_READY"
    assert res.json_out["selected_venue"]["venue_id"] == "emnlp_findings"
    assert res.json_out["selected_venue"]["retargeted_from"] == "neurips_main"

    # 6. Strict exit 2 checks: NaN and empty --out without mkdir
    bad_sc = tmp_path / "bad_nan.json"
    bad_sc.write_text('{"weights":{"importance":15,"novelty":20,"soundness":20,"evidence":20,"transparency":15,"clarity":10},"ratings":{"importance":7,"novelty":7,"soundness":7,"evidence":7,"transparency":7,"clarity":NaN}}', encoding="utf-8")
    no_dir = tmp_path / "no_mkdir_dir"
    r_nan = run_cli(SCRIPTS_DIR / "evaluate_submission.py", ["--scorecard", str(bad_sc), "--out", str(no_dir / "out.json")])
    assert r_nan.returncode == 2
    assert "Traceback" not in r_nan.stderr
    assert "error" in json.loads(r_nan.stderr)
    assert not no_dir.exists()


def test_e2e_m9b_real_upstream_schemas_raw_manifest_and_non_collision(tmp_path: Path) -> None:
    """E2E Regression: raw manifest, real triage mock-review/post-reject, project_state --audit, score_math v2, compare_scorecards post-cap, and ACL vs ACL Findings."""
    # 1. Verified raw experiment manifest passes without crash
    raw_manifest = WorkspaceFactory.make_verified_experiment_workspace(tmp_path / "exp_ws_ok", tamper_artifact_bytes=False)
    sc_pass = tmp_path / "sc_pass.json"
    sc_pass.write_text(json.dumps({"weights": _weights(), "ratings": _ratings((8, 7, 8, 8, 7, 8))}), encoding="utf-8")

    # 2. score_math.py real output preserves M9A v2 keys
    sm_out = tmp_path / "sm_out.json"
    r_sm = run_cli(SCRIPTS_DIR / "score_math.py", [str(sc_pass), "--what-if"])
    assert r_sm.returncode == 0
    sm_out.write_text(r_sm.stdout, encoding="utf-8")

    # 3. Real project_state --audit --strict output
    ps_file = tmp_path / "ps.json"
    r_ps_init = run_cli(SCRIPTS_DIR / "project_state.py", ["--state", str(ps_file), "--init", "--project-id", "PRJ-E2E", "--title", "Faithfulness"])
    assert r_ps_init.returncode == 0, r_ps_init.stderr + r_ps_init.stdout
    st = json.loads(ps_file.read_text(encoding="utf-8"))
    st["manuscript_claims"] = {"C1": {"id": "C1", "text": "Unlinked claim", "material": True, "kind": "reported", "rq_id": None, "run_ids": []}}
    ps_file.write_text(json.dumps(st), encoding="utf-8")
    ps_audit = tmp_path / "ps_audit.json"
    run_cli(SCRIPTS_DIR / "project_state.py", ["--state", str(ps_file), "--audit", "--strict", "--out", str(ps_audit)])

    # 4. Run evaluate_submission with raw manifest + score_math output + project_state audit
    res_ok = run_cli(
        SCRIPTS_DIR / "evaluate_submission.py",
        ["--scorecard", str(sm_out), "--experiment-manifest", str(raw_manifest), "--project-state", str(ps_audit)],
    )
    assert res_ok.returncode == 0, res_ok.stderr + res_ok.stdout
    assert res_ok.json_out["ready_to_submit"] is True
    assert res_ok.json_out["score_evaluation"]["native_scales"]["source"] == "m9a_v2"
    assert res_ok.json_out["upstream_downstream_linkage"]["project_state"]["errors"]

    # 5. Real triage_reviews.py mock-review fatal defect blocks readiness
    sc_fatal = tmp_path / "sc_fatal.json"
    sc_fatal.write_text(json.dumps({"weights": _weights(), "ratings": _ratings((8, 7, 4, 4, 8, 8))}), encoding="utf-8")
    mr_out = tmp_path / "mr_out.json"
    run_cli(SCRIPTS_DIR / "triage_reviews.py", ["mock-review", "--scorecard", str(sc_fatal), "--out", str(mr_out)])
    res_mr = run_cli(SCRIPTS_DIR / "evaluate_submission.py", ["--scorecard", str(sc_pass), "--triage-reviews", str(mr_out)])
    assert res_mr.returncode == 1
    assert res_mr.json_out["ready_to_submit"] is False
    assert res_mr.json_out["upstream_downstream_linkage"]["triage_reviews"]["blocking"] is True
    assert res_mr.json_out["upstream_downstream_linkage"]["triage_reviews"]["fatal_count"] >= 1

    # 6. ACL vs ACL Findings non-collision
    vn = tmp_path / "vn_acl.json"
    vn.write_text(json.dumps({
        "mode": "portfolio",
        "venue_evaluations": [
            {"venue_id": "acl_main", "venue_name": "ACL", "edition": "2027", "track": "Main", "role": "primary", "venue_tier": "top_tier_flagship", "classification": "recommended_now", "fit_score_out_of_10": 9},
            {"venue_id": "acl_findings", "venue_name": "ACL Findings", "edition": "2027", "track": "Findings", "role": "fallback", "venue_tier": "q1_or_tier_a", "classification": "viable_fallback", "fit_score_out_of_10": 8},
        ],
    }), encoding="utf-8")
    vs_acl = tmp_path / "vs_acl.json"
    vs_acl.write_text(json.dumps({
        "venue": "ACL",
        "verification_passed": False,
        "source_text_status": "verification_blocked",
        "blocking_source_issues": [{"issue": "same_host_path_redirect_year_mismatch"}],
        "critical_fields_without_matched_quote": ["deadline"],
    }), encoding="utf-8")
    res_acl = run_cli(
        SCRIPTS_DIR / "evaluate_submission.py",
        ["--scorecard", str(sc_pass), "--venue-novelty", str(vn), "--venue-sources", str(vs_acl), "--target-venue", "ACL"],
    )
    assert res_acl.returncode == 0, res_acl.stderr + res_acl.stdout
    assert res_acl.json_out["ready_to_submit"] is True
    assert res_acl.json_out["verdict"] == "RETARGETED_READY"
    assert res_acl.json_out["selected_venue"]["venue_id"] == "acl_findings"
    assert res_acl.json_out["selected_venue"]["retargeted_from"] == "acl_main"


def test_e2e_m9b_compact_outputs_full_parity_and_venue_profile_gates(
    mock_server: MockScholarlyServer, tmp_path: Path
) -> None:
    """E2E Parity: real --compact upstream outputs match full outputs across venue_plan, portfolio, scorecards, triage, readiness, ledger, project_state, and dataset_benchmark."""
    # 1. Real score_math dataset_benchmark with ethics_license_verified=False triggers fatal gate
    sc_db = tmp_path / "sc_db.json"
    sc_db.write_text(json.dumps({
        "venue_type": "dataset_benchmark",
        "ethics_license_verified": False,
        "ratings": _ratings((8, 8, 8, 8, 8, 8)),
    }), encoding="utf-8")
    res_db = run_cli(SCRIPTS_DIR / "evaluate_submission.py", ["--scorecard", str(sc_db), "--target-venue", "NeurIPS"])
    assert res_db.returncode == 1, res_db.stderr + res_db.stdout
    assert res_db.json_out["ready_to_submit"] is False
    assert res_db.json_out["band"] == "not_ready_fatal_gate"
    assert res_db.json_out["recommended_matched_tier"] == "none_hold_for_rework"
    assert res_db.json_out["selected_venue"] is None

    # 2. Real check_venue_plan.py --compact schedule_status parity with full output
    mock_server.add_route("/neurips/2027/cfp", (200, "text/html", "<html><body><p>NeurIPS 2027 Main. Submission open.</p></body></html>"), host="localhost")
    mock_server.add_route("/emnlp/2027/cfp", (200, "text/html", "<html><body><p>EMNLP Findings 2027. Submission open.</p></body></html>"), host="localhost")
    env = mock_server.env()
    neurips_url = mock_server.url("/neurips/2027/cfp", host="localhost")
    emnlp_url = mock_server.url("/emnlp/2027/cfp", host="localhost")

    dos_vp = tmp_path / "dos_vp.json"
    dos_vp.write_text(json.dumps({
        "venue": "NeurIPS", "edition": "2027", "track": "Main", "official_cfp_url": neurips_url, "checked_at": iso_utc(0),
        "evidence_claims": [{"field": "cfp", "source_url": neurips_url, "quote": "NeurIPS 2027 Main. Submission open."}],
    }), encoding="utf-8")
    vp_bundle = tmp_path / "vp_bundle.json"
    r_cap_vp = run_cli(SCRIPTS_DIR / "capture_venue_sources.py", [str(dos_vp), "--out", str(vp_bundle)], env=env)
    assert r_cap_vp.returncode == 0, r_cap_vp.stderr

    sc_ok = tmp_path / "sc_ok.json"
    sc_ok.write_text(json.dumps({"weights": _weights(), "ratings": _ratings((8, 8, 8, 8, 8, 8))}), encoding="utf-8")
    plan_in = tmp_path / "plan_sched.json"
    plan_in.write_text(json.dumps({
        "venue": "NeurIPS",
        "edition": "2027",
        "track": "Main",
        "official_cfp_url": neurips_url,
        "checked_at": iso_utc(0),
        "user_timezone": "UTC",
        "presentation_mode": "online",
        "currency": "USD",
        "budget_currency": "USD",
        "budget": 1000,
        "fees": [
            {"name": "Submission", "category": "submission", "mandatory": True, "amount": 0, "source_url": neurips_url, "checked_at": iso_utc(0)},
            {"name": "Publication", "category": "publication", "mandatory": True, "amount": 0, "source_url": neurips_url, "checked_at": iso_utc(0)},
            {"name": "Author Reg", "category": "author_registration", "mandatory": True, "amount": 100, "source_url": neurips_url, "checked_at": iso_utc(0)},
            {"name": "Overlength", "category": "overlength", "mandatory": False, "amount": 0, "source_url": neurips_url, "checked_at": iso_utc(0)},
            {"name": "Tax", "category": "tax", "mandatory": True, "amount": 0, "source_url": neurips_url, "checked_at": iso_utc(0)},
        ],
        "milestones": {"abstract_registration": iso_utc(5), "full_paper": iso_utc(10)},
        "work_plan": {"buffer_days": 2, "tasks": [{"name": "Run ablations", "days": 20}]},
    }), encoding="utf-8")
    vp_full = tmp_path / "vp_full.json"
    vp_compact = tmp_path / "vp_compact.json"
    r_vp_c = run_cli(SCRIPTS_DIR / "check_venue_plan.py", [str(plan_in), "--sources", str(vp_bundle), "--out", str(vp_full), "--compact"])
    assert r_vp_c.returncode == 0, r_vp_c.stderr + r_vp_c.stdout
    # Strip report_path to verify direct --compact fallback parity too
    vp_c_obj = json.loads(r_vp_c.stdout)
    assert vp_c_obj.get("cfp_verified") is True
    assert vp_c_obj.get("within_budget") is True
    assert vp_c_obj.get("warnings") == []
    assert vp_c_obj.get("schedule_status") == "start_already_passed_under_serial_assumption"
    vp_c_obj.pop("report_path", None)
    vp_compact.write_text(json.dumps(vp_c_obj), encoding="utf-8")

    r_ev_full = run_cli(SCRIPTS_DIR / "evaluate_submission.py", ["--scorecard", str(sc_ok), "--venue-plan", str(vp_full), "--target-venue", "NeurIPS"])
    r_ev_comp = run_cli(SCRIPTS_DIR / "evaluate_submission.py", ["--scorecard", str(sc_ok), "--venue-plan", str(vp_compact), "--target-venue", "NeurIPS"])
    assert r_ev_full.returncode == 1 and r_ev_comp.returncode == 1
    assert r_ev_full.json_out["verdict"] == r_ev_comp.json_out["verdict"] == "BLOCKED_NO_VIABLE_VENUE"
    assert r_ev_full.json_out["ready_to_submit"] is r_ev_comp.json_out["ready_to_submit"] is False

    # 3. Real compare_scorecards --mode idea --compact + pareto_frontier & linkage_summary
    idea_locs_a = {d: [f'idea_a.txt#L1 "Evidence {d}"'] for d in ("evidence_coverage", "novelty", "importance", "answerability", "feasibility", "falsifiability")}
    idea_locs_b = {d: [f'idea_b.txt#L1 "Evidence {d}"'] for d in ("evidence_coverage", "novelty", "importance", "answerability", "feasibility", "falsifiability")}
    idea_in = tmp_path / "idea_cs.json"
    idea_in.write_text(json.dumps({
        "mode": "idea",
        "goal": "high_risk_q1_top_tier",
        "profiles": [
            {"id": "idea_a", "reading_basis": "full_text", "closest_work": ["idea_b"], "evidence_locators": idea_locs_a, "ratings": {"evidence_coverage": 8, "novelty": 9, "importance": 8, "answerability": 8, "feasibility": 7, "falsifiability": 8}},
            {"id": "idea_b", "reading_basis": "full_text", "closest_work": ["idea_a"], "evidence_locators": idea_locs_b, "ratings": {"evidence_coverage": 6, "novelty": 6, "importance": 6, "answerability": 6, "feasibility": 6, "falsifiability": 6}},
        ],
    }), encoding="utf-8")
    cs_idea_full = tmp_path / "cs_idea_full.json"
    r_cs_i = run_cli(SCRIPTS_DIR / "compare_scorecards.py", [str(idea_in), "--mode", "idea", "--target-id", "idea_a", "--out", str(cs_idea_full), "--compact"])
    assert r_cs_i.returncode == 0, r_cs_i.stderr + r_cs_i.stdout
    cs_idea_comp = tmp_path / "cs_idea_comp.json"
    cs_i_obj = json.loads(r_cs_i.stdout)
    cs_i_obj.pop("artifact_path", None)
    cs_idea_comp.write_text(json.dumps(cs_i_obj), encoding="utf-8")
    r_ev_i = run_cli(SCRIPTS_DIR / "evaluate_submission.py", ["--scorecard", str(cs_idea_comp), "--target-id", "idea_a"])
    assert r_ev_i.returncode == 1
    assert r_ev_i.json_out["ready_to_submit"] is False
    assert r_ev_i.json_out["score_evaluation"]["mode"] == "idea"
    assert "pareto_frontier" in r_ev_i.json_out["score_evaluation"]

    # 4. Real check_artifact_readiness --compact (with --out on disk recovering anonymization) + triage_reviews --compact
    leaky_repo = tmp_path / "leaky_repo"
    WorkspaceFactory.make_ml_repo(leaky_repo)
    _make_clean_repo(leaky_repo, leak_author=True)
    art_full = tmp_path / "art_full.json"
    r_art_c = run_cli(SCRIPTS_DIR / "check_artifact_readiness.py", ["--repo-dir", str(leaky_repo), "--anonymous", "--out", str(art_full), "--compact"])
    assert r_art_c.returncode == 1
    art_wrap = tmp_path / "art_wrap.json"
    art_wrap.write_text(r_art_c.stdout, encoding="utf-8")

    revs = tmp_path / "revs.json"
    revs.write_text(json.dumps({"comments": [{"id": "R1.1", "reviewer": "R1", "text": "Need more ablations."}]}), encoding="utf-8")
    vb = tmp_path / "vb.json"
    vb.write_text(json.dumps({"name": "EMNLP", "resubmission_allowed": False}), encoding="utf-8")
    tri_full = tmp_path / "tri_full.json"
    r_tri_c = run_cli(SCRIPTS_DIR / "triage_reviews.py", ["post-reject", "--reviews", str(revs), "--venue-b", str(vb), "--out", str(tri_full), "--compact"])
    assert r_tri_c.returncode == 0
    tri_wrap = tmp_path / "tri_wrap.json"
    tri_wrap.write_text(r_tri_c.stdout, encoding="utf-8")

    r_ev_wrap = run_cli(SCRIPTS_DIR / "evaluate_submission.py", ["--scorecard", str(sc_ok), "--artifact-readiness", str(art_wrap), "--triage-reviews", str(tri_wrap)])
    assert r_ev_wrap.returncode == 1
    assert r_ev_wrap.json_out["desk_reject_blocked"] is True
    assert r_ev_wrap.json_out["verdict"] == "BLOCKED_FATAL_GATE_AND_DESK_REJECT"
    assert r_ev_wrap.json_out["upstream_downstream_linkage"]["triage_reviews"]["blocking"] is True

    # 5. Real compare_venue_novelty --portfolio --compact parity
    mock_server.add_route("/ws/2027/cfp", (200, "text/html", "<html><body><p>Eval Workshop 2027. Submission open.</p></body></html>"), host="localhost")
    ws_url = mock_server.url("/ws/2027/cfp", host="localhost")
    payloads = json.loads((T123_FIXTURES_DIR / "mock_scholarly_payloads.json").read_text(encoding="utf-8"))
    mock_server.add_route("/v235/", (200, "text/html", payloads["pmlr_v235_html"]), host="proceedings.mlr.press")
    src_dir = tmp_path / "sources_p"
    src_dir.mkdir()
    dos_b = tmp_path / "dos_b.json"
    dos_b.write_text(json.dumps({
        "venue": "Portfolio", "edition": "2027", "official_cfp_url": emnlp_url, "checked_at": iso_utc(0),
        "evidence_claims": [
            {"field": "n", "source_url": neurips_url, "quote": "NeurIPS 2027 Main. Submission open."},
            {"field": "e", "source_url": emnlp_url, "quote": "EMNLP Findings 2027. Submission open."},
            {"field": "w", "source_url": ws_url, "quote": "Eval Workshop 2027. Submission open."},
        ],
    }), encoding="utf-8")
    run_cli(SCRIPTS_DIR / "capture_venue_sources.py", [str(dos_b), "--out", str(src_dir / "venue-sources.json")], env=env)
    (src_dir / "target.txt").write_text("Full text target evidence.\n", encoding="utf-8")
    base_fix = json.loads((REFS_DIR / "venue-novelty-profile.fixture.json").read_text(encoding="utf-8"))
    tgt = copy.deepcopy(base_fix["target"])
    tgt.update({"id": "target", "score": 6, "low": 5, "high": 7, "closest_work_id": "target", "closest_work_locator": 'target.txt#L1 "Full text target"', "assessed_at_utc": iso_utc(0)})

    def _mk_panel(prefix: str, trk: str, p_ov: float):
        rows = copy.deepcopy(base_fix["accepted_panel"])
        for i, row in enumerate(rows):
            pid = f"{prefix}_{i}"
            (src_dir / f"{pid}.txt").write_text("Accepted evidence.\n", encoding="utf-8")
            row.update({"id": pid, "track": trk, "score": 6, "low": 5, "high": 7, "overall_score": p_ov, "topic_relation": "different_topic", "closest_work_id": pid, "closest_work_locator": f'{pid}.txt#L1 "Accepted evidence"', "assessed_at_utc": iso_utc(0)})
        return rows

    def _mk_cand(vid: str, name: str, trk: str, url: str, quote: str, role: str, tier: str, dl: int, nt: int, p_ov: float):
        psel = copy.deepcopy(base_fix["panel_selection"])
        psel["track"] = trk
        return {
            "venue_id": vid, "role": role, "tier_expectation": tier,
            "venue": {"name": name, "edition": "2027", "track": trk, "official_cfp_url": url, "checked_at_utc": iso_utc(0), "max_source_age_days": 14, "submission_deadline_utc": iso_utc(dl), "notification_date_utc": iso_utc(nt), "simultaneous_submission_allowed": False},
            "panel_selection": psel, "accepted_panel": _mk_panel(vid, trk, p_ov),
            "fit_axes": [{"name": ax, "score": 2, "source_url": url, "locator": f'"{quote}"', "reason": "ok"} for ax in ("scope_audience", "contribution_track", "evidence_maturity", "format_eligibility", "user_constraints")],
            "hard_constraints": [{"name": cn, "status": "met", "source_url": url, "reason": "open"} for cn in ("deadline", "budget", "eligibility")],
        }

    vn_in = tmp_path / "vn_in.json"
    vn_in.write_text(json.dumps({
        "target": tgt, "target_scorecard": {"weights": _weights(), "ratings": _ratings((7, 6, 7, 7, 6, 7))},
        "candidate_venues": [
            _mk_cand("neurips_main", "NeurIPS", "Main", neurips_url, "NeurIPS 2027 Main. Submission open.", "primary", "top_tier_flagship", 30, 90, 7.7),
            _mk_cand("emnlp_findings", "EMNLP Findings", "Findings", emnlp_url, "EMNLP Findings 2027. Submission open.", "fallback", "q1_or_tier_a", 120, 160, 6.3),
            _mk_cand("eval_workshop", "Eval Workshop", "Workshop", ws_url, "Eval Workshop 2027. Submission open.", "fallback", "workshop_or_preliminary", 180, 210, 5.4),
        ],
    }), encoding="utf-8")
    vn_full = tmp_path / "vn_full.json"
    r_vn_c = run_cli(SCRIPTS_DIR / "compare_venue_novelty.py", [str(vn_in), "--portfolio", "--sources-dir", str(src_dir), "--target-overall", "6.65", "--out", str(vn_full), "--compact"])
    assert r_vn_c.returncode == 0, r_vn_c.stderr + r_vn_c.stdout
    vn_comp = tmp_path / "vn_comp.json"
    vn_c_obj = json.loads(r_vn_c.stdout)
    vn_c_obj.pop("artifact_path", None)
    vn_comp.write_text(json.dumps(vn_c_obj), encoding="utf-8")

    sc_665 = tmp_path / "sc_665.json"
    sc_665.write_text(json.dumps({"weights": _weights(), "ratings": _ratings((7, 6, 7, 7, 6, 7))}), encoding="utf-8")
    r_p_full = run_cli(SCRIPTS_DIR / "evaluate_submission.py", ["--scorecard", str(sc_665), "--venue-novelty", str(vn_full), "--target-venue", "NeurIPS"])
    r_p_comp = run_cli(SCRIPTS_DIR / "evaluate_submission.py", ["--scorecard", str(sc_665), "--venue-novelty", str(vn_comp), "--target-venue", "NeurIPS"])
    assert r_p_full.returncode == 0 and r_p_comp.returncode == 0
    assert r_p_full.json_out["verdict"] == r_p_comp.json_out["verdict"] == "RETARGETED_READY"
    assert r_p_full.json_out["selected_venue"]["venue_id"] == r_p_comp.json_out["selected_venue"]["venue_id"] == "emnlp_findings"
    assert r_p_full.json_out["selected_venue"]["retargeted_from"] == r_p_comp.json_out["selected_venue"]["retargeted_from"] == "neurips_main"


def test_e2e_m9b_single_venue_non_ccf_plan_block_and_trim_stage3_portfolio_parity(
    mock_server: MockScholarlyServer, tmp_path: Path
) -> None:
    """E2E Regression: real single-venue non-CCF compare_venue_novelty + failing venue_plan without --target-venue, plus real trim_stage>=3 --portfolio --compact parity."""
    mock_server.add_route(
        "/custom/2027/cfp",
        (200, "text/html", "<html><body><p>CustomML Conf 2027 Main. Submission open.</p></body></html>"),
        host="localhost",
    )
    payloads = json.loads((T123_FIXTURES_DIR / "mock_scholarly_payloads.json").read_text(encoding="utf-8"))
    mock_server.add_route("/v235/", (200, "text/html", payloads["pmlr_v235_html"]), host="proceedings.mlr.press")
    env = mock_server.env()
    custom_url = mock_server.url("/custom/2027/cfp", host="localhost")

    src_dir = tmp_path / "sources_r4"
    src_dir.mkdir()
    dos = tmp_path / "dos_custom.json"
    dos.write_text(json.dumps({
        "venue": "CustomML Conf",
        "edition": "2027",
        "official_cfp_url": custom_url,
        "checked_at": iso_utc(0),
        "evidence_claims": [{"field": "cfp", "source_url": custom_url, "quote": "CustomML Conf 2027 Main. Submission open."}],
    }), encoding="utf-8")
    r_cap = run_cli(SCRIPTS_DIR / "capture_venue_sources.py", [str(dos), "--out", str(src_dir / "venue-sources.json")], env=env)
    assert r_cap.returncode == 0, r_cap.stderr

    (src_dir / "target.txt").write_text("Full text target evidence.\n", encoding="utf-8")
    base_fix = json.loads((REFS_DIR / "venue-novelty-profile.fixture.json").read_text(encoding="utf-8"))
    tgt = copy.deepcopy(base_fix["target"])
    tgt.update({"id": "target", "score": 8, "low": 7, "high": 9, "closest_work_id": "target", "closest_work_locator": 'target.txt#L1 "Full text target"', "assessed_at_utc": iso_utc(0)})
    panel = copy.deepcopy(base_fix["accepted_panel"])
    for i, row in enumerate(panel):
        pid = f"cust_{i}"
        (src_dir / f"{pid}.txt").write_text("Accepted evidence.\n", encoding="utf-8")
        row.update({"id": pid, "track": "Main", "score": 7, "low": 6, "high": 8, "overall_score": 7.0, "topic_relation": "different_topic", "closest_work_id": pid, "closest_work_locator": f'{pid}.txt#L1 "Accepted evidence"', "assessed_at_utc": iso_utc(0)})
    psel = copy.deepcopy(base_fix["panel_selection"])
    psel["track"] = "Main"

    vn_s_in = tmp_path / "vn_single_in.json"
    vn_s_in.write_text(json.dumps({
        "target": tgt,
        "venue": {"name": "CustomML Conf", "edition": "2027", "track": "Main", "official_cfp_url": custom_url, "checked_at_utc": iso_utc(0), "max_source_age_days": 14, "submission_deadline_utc": iso_utc(30), "notification_date_utc": iso_utc(90)},
        "panel_selection": psel,
        "accepted_panel": panel,
        "fit_axes": [{"name": ax, "score": 2, "source_url": custom_url, "locator": '"CustomML Conf 2027 Main. Submission open."', "reason": "ok"} for ax in ("scope_audience", "contribution_track", "evidence_maturity", "format_eligibility", "user_constraints")],
        "hard_constraints": [{"name": cn, "status": "met", "source_url": custom_url, "reason": "open"} for cn in ("deadline", "budget", "eligibility")],
    }), encoding="utf-8")
    vn_s_full = tmp_path / "vn_s_full.json"
    r_vn_s = run_cli(SCRIPTS_DIR / "compare_venue_novelty.py", [str(vn_s_in), "--sources-dir", str(src_dir), "--target-overall", "8.0", "--out", str(vn_s_full), "--compact"])
    assert r_vn_s.returncode == 0, r_vn_s.stderr + r_vn_s.stdout
    vn_s_c_obj = json.loads(r_vn_s.stdout)
    vn_s_c_obj.pop("artifact_path", None)
    vn_s_comp = tmp_path / "vn_s_comp.json"
    vn_s_comp.write_text(json.dumps(vn_s_c_obj), encoding="utf-8")

    # Real failing check_venue_plan (schedule_status past) for CustomML Conf
    plan_in = tmp_path / "plan_custom.json"
    plan_in.write_text(json.dumps({
        "venue": "CustomML Conf", "edition": "2027", "track": "Main",
        "official_cfp_url": custom_url, "checked_at": iso_utc(0), "user_timezone": "UTC",
        "presentation_mode": "online", "currency": "USD", "budget_currency": "USD", "budget": 1000,
        "fees": [
            {"name": "Sub", "category": "submission", "mandatory": True, "amount": 0, "source_url": custom_url, "checked_at": iso_utc(0)},
            {"name": "Pub", "category": "publication", "mandatory": True, "amount": 0, "source_url": custom_url, "checked_at": iso_utc(0)},
            {"name": "Reg", "category": "author_registration", "mandatory": True, "amount": 100, "source_url": custom_url, "checked_at": iso_utc(0)},
            {"name": "Ov", "category": "overlength", "mandatory": False, "amount": 0, "source_url": custom_url, "checked_at": iso_utc(0)},
            {"name": "Tax", "category": "tax", "mandatory": True, "amount": 0, "source_url": custom_url, "checked_at": iso_utc(0)},
        ],
        "milestones": {"abstract_registration": iso_utc(5), "full_paper": iso_utc(10)},
        "work_plan": {"buffer_days": 2, "tasks": [{"name": "Ablations", "days": 20}]},
    }), encoding="utf-8")
    vp_custom = tmp_path / "vp_custom.json"
    run_cli(SCRIPTS_DIR / "check_venue_plan.py", [str(plan_in), "--sources", str(src_dir / "venue-sources.json"), "--out", str(vp_custom)])

    sc_pass = tmp_path / "sc_pass.json"
    sc_pass.write_text(json.dumps({"weights": _weights(), "ratings": _ratings((8, 8, 8, 8, 8, 8))}), encoding="utf-8")
    for vn_p in (vn_s_full, vn_s_comp):
        r_ev = run_cli(SCRIPTS_DIR / "evaluate_submission.py", ["--scorecard", str(sc_pass), "--venue-novelty", str(vn_p), "--venue-plan", str(vp_custom)])
        assert r_ev.returncode == 1
        assert r_ev.json_out["ready_to_submit"] is False
        assert r_ev.json_out["verdict"] == "BLOCKED_NO_VIABLE_VENUE"

    # Real portfolio --compact hitting trim_stage >= 3 (venue_summaries == []) without --target-venue
    def _mk_c(vid: str, name: str, trk: str, role: str, tier: str, dl: int, nt: int, p_ov: float):
        p_rows = copy.deepcopy(panel)
        for pr in p_rows:
            pr["track"] = trk
            pr["overall_score"] = p_ov
        ps2 = copy.deepcopy(psel)
        ps2["track"] = trk
        return {
            "venue_id": vid, "role": role, "tier_expectation": tier,
            "venue": {"name": name, "edition": "2027", "track": trk, "official_cfp_url": custom_url, "checked_at_utc": iso_utc(0), "max_source_age_days": 14, "submission_deadline_utc": iso_utc(dl), "notification_date_utc": iso_utc(nt), "simultaneous_submission_allowed": False},
            "panel_selection": ps2, "accepted_panel": p_rows,
            "fit_axes": [{"name": ax, "score": 2, "source_url": custom_url, "locator": '"CustomML Conf 2027 Main. Submission open."', "reason": "ok"} for ax in ("scope_audience", "contribution_track", "evidence_maturity", "format_eligibility", "user_constraints")],
            "hard_constraints": [{"name": cn, "status": "met", "source_url": custom_url, "reason": "open"} for cn in ("deadline", "budget", "eligibility")],
        }

    cands = [_mk_c("neurips_main_" + ("a" * 180), "NeurIPS", "Main", "primary", "top_tier_flagship", 30, 90, 7.8)]
    for i in range(1, 15):
        cands.append(_mk_c(f"emnlp_findings_{i}_" + ("b" * 180), f"EMNLP Findings {i}", "Findings", "fallback", "q1_or_tier_a", 120 + i * 5, 160 + i * 5, 6.3))
    vn_p_in = tmp_path / "vn_p_in.json"
    vn_p_in.write_text(json.dumps({
        "target": {**tgt, "score": 6, "low": 5, "high": 7},
        "target_scorecard": {"weights": _weights(), "ratings": _ratings((7, 6, 7, 7, 6, 7))},
        "candidate_venues": cands,
    }), encoding="utf-8")
    vn_p_full = tmp_path / "vn_p_full.json"
    r_p_c = run_cli(SCRIPTS_DIR / "compare_venue_novelty.py", [str(vn_p_in), "--portfolio", "--sources-dir", str(src_dir), "--target-overall", "6.65", "--out", str(vn_p_full), "--compact"])
    assert r_p_c.returncode == 0, r_p_c.stderr + r_p_c.stdout
    p_c_obj = json.loads(r_p_c.stdout)
    assert p_c_obj["venue_summaries"] == []
    p_c_obj.pop("artifact_path", None)
    vn_p_comp = tmp_path / "vn_p_comp.json"
    vn_p_comp.write_text(json.dumps(p_c_obj), encoding="utf-8")

    sc_665 = tmp_path / "sc_665.json"
    sc_665.write_text(json.dumps({"weights": _weights(), "ratings": _ratings((7, 6, 7, 7, 6, 7))}), encoding="utf-8")
    r_ev_f = run_cli(SCRIPTS_DIR / "evaluate_submission.py", ["--scorecard", str(sc_665), "--venue-novelty", str(vn_p_full)])
    r_ev_c = run_cli(SCRIPTS_DIR / "evaluate_submission.py", ["--scorecard", str(sc_665), "--venue-novelty", str(vn_p_comp)])
    assert r_ev_f.returncode == 0 and r_ev_c.returncode == 0
    assert r_ev_f.json_out["verdict"] == r_ev_c.json_out["verdict"] == "RETARGETED_READY"
    assert r_ev_f.json_out["venue_portfolio"]["retargeted"] is r_ev_c.json_out["venue_portfolio"]["retargeted"] is True
    assert r_ev_c.json_out["selected_venue"]["retargeted_from"].startswith("neurips_main_aaa")


def test_e2e_m9b_r5_double_colon_conflict_venue_type_post_cap_and_31venue_trim3(
    mock_server: MockScholarlyServer, tmp_path: Path
) -> None:
    """E2E Regression for R5: ACL Findings::2027::Findings conflict, journal_q1/dataset_benchmark/survey_review post-cap & standalone min_dimensions, and 31-venue trim_stage==3 top_venue_id."""
    for path_s, title in (
        ("/acl/2027/cfp", "ACL 2027 Main. Submission open."),
        ("/acl-findings/2027/cfp", "ACL Findings 2027. Submission open."),
        ("/emnlp/2027/cfp", "EMNLP 2027 Main. Submission open."),
        ("/tpami/2027/cfp", "TPAMI 2027 Main. Submission open."),
        ("/ndb/2027/cfp", "NeurIPS D&B 2027 Main. Submission open."),
    ):
        mock_server.add_route(path_s, (200, "text/html", f"<html><body><p>{title}</p></body></html>"), host="localhost")
    env = mock_server.env()
    urls = {
        "acl": mock_server.url("/acl/2027/cfp", host="localhost"),
        "aclf": mock_server.url("/acl-findings/2027/cfp", host="localhost"),
        "emnlp": mock_server.url("/emnlp/2027/cfp", host="localhost"),
        "tpami": mock_server.url("/tpami/2027/cfp", host="localhost"),
        "ndb": mock_server.url("/ndb/2027/cfp", host="localhost"),
    }

    src_dir = tmp_path / "sources_r5"
    src_dir.mkdir()
    dos = tmp_path / "dos_r5.json"
    dos.write_text(json.dumps({
        "venue": "R5 Bundle", "edition": "2027", "official_cfp_url": urls["acl"], "checked_at": iso_utc(0),
        "evidence_claims": [
            {"field": k, "source_url": u, "quote": "Submission open."}
            for k, u in urls.items()
        ],
    }), encoding="utf-8")
    r_cap = run_cli(SCRIPTS_DIR / "capture_venue_sources.py", [str(dos), "--out", str(src_dir / "venue-sources.json")], env=env)
    assert r_cap.returncode == 0, r_cap.stderr

    (src_dir / "target.txt").write_text("Full text target evidence.\n", encoding="utf-8")
    base_fix = json.loads((REFS_DIR / "venue-novelty-profile.fixture.json").read_text(encoding="utf-8"))
    tgt = copy.deepcopy(base_fix["target"])
    tgt.update({"id": "target", "score": 8, "low": 7, "high": 9, "closest_work_id": "target", "closest_work_locator": 'target.txt#L1 "Full text target"', "assessed_at_utc": iso_utc(0)})

    def _mk_panel(prefix: str, trk: str, p_ov: float = 6.5, p_sc: int = 6):
        rows = copy.deepcopy(base_fix["accepted_panel"])
        for i, row in enumerate(rows):
            pid = f"{prefix}_{i}"
            (src_dir / f"{pid}.txt").write_text("Accepted evidence.\n", encoding="utf-8")
            row.update({"id": pid, "track": trk, "score": p_sc, "low": max(1, p_sc - 1), "high": min(10, p_sc + 1), "overall_score": p_ov, "topic_relation": "different_topic", "closest_work_id": pid, "closest_work_locator": f'{pid}.txt#L1 "Accepted evidence"', "assessed_at_utc": iso_utc(0)})
        return rows

    def _mk_cand(vid: str | None, name: str, trk: str, url: str, quote: str, role: str, tier: str, dl: int, nt: int, p_ov: float = 6.5, p_sc: int = 6, failed_c: bool = False, stale: bool = False):
        psel = copy.deepcopy(base_fix["panel_selection"])
        psel["track"] = trk
        c = {
            "role": role, "tier_expectation": tier,
            "venue": {"name": name, "edition": "2027", "track": trk, "official_cfp_url": url, "checked_at_utc": iso_utc(-30 if stale else 0), "max_source_age_days": 14, "submission_deadline_utc": iso_utc(dl), "notification_date_utc": iso_utc(nt), "simultaneous_submission_allowed": False},
            "panel_selection": psel, "accepted_panel": _mk_panel(vid or f"{name}_{trk}".replace(" ", "_"), trk, p_ov, p_sc),
            "fit_axes": [{"name": ax, "score": 2, "source_url": url, "locator": f'"{quote}"', "reason": "ok"} for ax in ("scope_audience", "contribution_track", "evidence_maturity", "format_eligibility", "user_constraints")],
            "hard_constraints": [{"name": cn, "status": ("failed" if failed_c and cn == "budget" else "met"), "source_url": url, "reason": "ok"} for cn in ("deadline", "budget", "eligibility")],
        }
        if vid is not None:
            c["venue_id"] = vid
        return c

    # 1. Auto-generated "::" conflicted_fallback ("ACL Findings::2027::Findings")
    vn_acl_in = tmp_path / "vn_acl_in.json"
    vn_acl_in.write_text(json.dumps({
        "target": tgt,
        "candidate_venues": [
            _mk_cand(None, "ACL", "Main", urls["acl"], "ACL 2027 Main. Submission open.", "primary", "top_tier_flagship", 30, 90),
            _mk_cand(None, "ACL Findings", "Findings", urls["aclf"], "ACL Findings 2027. Submission open.", "fallback", "q1_or_tier_a", 60, 120),
            _mk_cand(None, "EMNLP", "Main", urls["emnlp"], "EMNLP 2027 Main. Submission open.", "fallback", "top_tier_flagship", 120, 180),
        ],
    }), encoding="utf-8")
    vn_acl_full = tmp_path / "vn_acl_full.json"
    r_vn_acl = run_cli(SCRIPTS_DIR / "compare_venue_novelty.py", [str(vn_acl_in), "--portfolio", "--sources-dir", str(src_dir), "--target-overall", "8.0", "--out", str(vn_acl_full), "--compact"])
    assert r_vn_acl.returncode == 0, r_vn_acl.stderr + r_vn_acl.stdout
    acl_c_obj = json.loads(r_vn_acl.stdout)
    assert acl_c_obj["venue_portfolio_recommendations"]["conflicted_fallback"] == ["ACL Findings::2027::Findings"]
    acl_c_obj.pop("artifact_path", None)
    vn_acl_comp = tmp_path / "vn_acl_comp.json"
    vn_acl_comp.write_text(json.dumps(acl_c_obj), encoding="utf-8")

    sc8 = tmp_path / "sc8.json"
    sc8.write_text(json.dumps({"weights": _weights(), "ratings": _ratings((8, 8, 8, 8, 8, 8))}), encoding="utf-8")
    for vnp in (vn_acl_full, vn_acl_comp):
        r_blk = run_cli(SCRIPTS_DIR / "evaluate_submission.py", ["--scorecard", str(sc8), "--venue-novelty", str(vnp), "--target-venue", "ACL Findings"])
        assert r_blk.returncode == 1
        assert r_blk.json_out["desk_reject_blocked"] is True
        assert "venue_portfolio:selected_venue_conflicted_fallback" in r_blk.json_out["desk_reject_audit"]["reasons"]
        r_ok = run_cli(SCRIPTS_DIR / "evaluate_submission.py", ["--scorecard", str(sc8), "--venue-novelty", str(vnp), "--target-venue", "ACL"])
        assert r_ok.returncode == 0
        assert r_ok.json_out["desk_reject_blocked"] is False

    # 2. Real check_artifact_readiness WARN (cap=5) + real compare_venue_novelty (journal_q1 / dataset_benchmark) + standalone & survey_review
    warn_repo = tmp_path / "warn_repo"
    WorkspaceFactory.make_ml_repo(warn_repo)
    _make_clean_repo(warn_repo)
    (warn_repo / "requirements.txt").write_text("numpy\n", encoding="utf-8")  # unpinned -> WARN + cap=5
    art_warn = tmp_path / "art_warn.json"
    r_art_w = run_cli(SCRIPTS_DIR / "check_artifact_readiness.py", ["--repo-dir", str(warn_repo), "--anonymous", "--out", str(art_warn)])
    assert r_art_w.returncode == 0
    assert json.loads(art_warn.read_text(encoding="utf-8"))["recommended_transparency_cap"] == 5

    ps_main = copy.deepcopy(base_fix["panel_selection"])
    ps_main["track"] = "Main"
    vn_jq1_in = tmp_path / "vn_jq1_in.json"
    vn_jq1_in.write_text(json.dumps({
        "target": tgt,
        "venue_type": "journal_q1",
        "venue_checks": {"comprehensive_ablations": True, "reproducibility_details": True},
        "target_scorecard": {"venue_type": "journal_q1", "venue_checks": {"comprehensive_ablations": True, "reproducibility_details": True}, "ratings": _ratings((8, 7, 8, 8, 7, 8))},
        "venue": {"name": "TPAMI", "edition": "2027", "track": "Main", "official_cfp_url": urls["tpami"], "checked_at_utc": iso_utc(0), "max_source_age_days": 14},
        "panel_selection": ps_main,
        "accepted_panel": _mk_panel("tpami", "Main", 6.5),
        "fit_axes": [{"name": ax, "score": 2, "source_url": urls["tpami"], "locator": '"TPAMI 2027 Main. Submission open."', "reason": "ok"} for ax in ("scope_audience", "contribution_track", "evidence_maturity", "format_eligibility", "user_constraints")],
        "hard_constraints": [{"name": cn, "status": "met", "source_url": urls["tpami"], "reason": "open"} for cn in ("deadline", "budget", "eligibility")],
    }), encoding="utf-8")
    vn_jq1_out = tmp_path / "vn_jq1_out.json"
    r_vn_j = run_cli(SCRIPTS_DIR / "compare_venue_novelty.py", [str(vn_jq1_in), "--sources-dir", str(src_dir), "--out", str(vn_jq1_out)])
    assert r_vn_j.returncode == 0, r_vn_j.stderr + r_vn_j.stdout

    sc_jq1 = tmp_path / "sc_jq1.json"
    sc_jq1.write_text(json.dumps({"venue_type": "journal_q1", "venue_checks": {"comprehensive_ablations": True, "reproducibility_details": True}, "ratings": _ratings((8, 7, 8, 8, 7, 8))}), encoding="utf-8")
    r_ev_j = run_cli(SCRIPTS_DIR / "evaluate_submission.py", ["--scorecard", str(sc_jq1), "--venue-novelty", str(vn_jq1_out), "--artifact-readiness", str(art_warn)])
    assert r_ev_j.returncode == 1
    assert r_ev_j.json_out["ready_to_submit"] is False
    assert any("post_cap_tier_fit:transparency_5_below_journal_q1_min_6" in r for v in r_ev_j.json_out["venue_portfolio"]["disqualified_venues"] for r in v["disqualification_reasons"])

    r_ev_st = run_cli(SCRIPTS_DIR / "evaluate_submission.py", ["--scorecard", str(sc_jq1), "--artifact-readiness", str(art_warn)])
    assert r_ev_st.returncode == 1
    assert r_ev_st.json_out["ready_to_submit"] is False
    assert r_ev_st.json_out["verdict"] == "NOT_READY_BELOW_BAR"
    assert r_ev_st.json_out["upgrade_gaps_to_target_tier"].get("transparency") == 1

    sc_srv5 = tmp_path / "sc_srv5.json"
    sc_srv5.write_text(json.dumps({"venue_type": "survey_review", "venue_checks": {"systematic_coverage_protocol": True}, "ratings": _ratings((8, 7, 8, 8, 7, 5))}), encoding="utf-8")
    r_ev_srv = run_cli(SCRIPTS_DIR / "evaluate_submission.py", ["--scorecard", str(sc_srv5), "--target-venue", "ACM CSUR"])
    assert r_ev_srv.returncode == 1
    assert r_ev_srv.json_out["ready_to_submit"] is False
    assert any("post_cap_tier_fit:clarity_5_below_survey_review_min_6" in r for v in r_ev_srv.json_out["venue_portfolio"]["disqualified_venues"] for r in v["disqualification_reasons"])

    # 3. Real 31-venue trim_stage==3 portfolio where top_venue_id (emnlp_findings_0_...) is outside viable_fallback[:3]
    tgt665 = copy.deepcopy(base_fix["target"])
    tgt665.update({"id": "target", "score": 6, "low": 5, "high": 7, "closest_work_id": "target", "closest_work_locator": 'target.txt#L1 "Full text target"', "assessed_at_utc": iso_utc(0)})
    top_fid = "emnlp_findings_0_" + ("a" * 45)
    cands31 = [
        _mk_cand("neurips_main_" + ("a" * 45), "NeurIPS", "Main", urls["emnlp"], "EMNLP 2027 Main. Submission open.", "primary", "top_tier_flagship", 30, 90, 7.8, 6),
        _mk_cand(top_fid, "EMNLP Findings", "Findings", urls["emnlp"], "EMNLP 2027 Main. Submission open.", "fallback", "q1_or_tier_a", 120, 160, 6.9, 7),
    ]
    for i in range(1, 7):
        cands31.append(_mk_cand(f"conf_ws_{i:02d}_" + ("a" * 45), f"ConfW{i}", "Workshop", urls["emnlp"], "EMNLP 2027 Main. Submission open.", "fallback", "workshop_or_preliminary", 160 + i * 5, 220 + i * 5, 5.2, 5))
    for i in range(1, 6):
        cands31.append(_mk_cand(f"workshop_{i:02d}_" + ("a" * 45), f"WorkS{i}", "Workshop", urls["emnlp"], "EMNLP 2027 Main. Submission open.", "fallback", "workshop_or_preliminary", 260 + i * 5, 320 + i * 5, 5.2, 5))
    for i in range(1, 7):
        cands31.append(_mk_cand(f"rej_top_{i:02d}_" + ("a" * 45), f"RejT{i}", "Main", urls["emnlp"], "EMNLP 2027 Main. Submission open.", "fallback", "top_tier_flagship", 340 + i * 5, 400 + i * 5, 7.9, 8))
    for i in range(1, 7):
        cands31.append(_mk_cand(f"disq_ws_{i:02d}_" + ("a" * 45), f"DisqW{i}", "Workshop", urls["emnlp"], "EMNLP 2027 Main. Submission open.", "fallback", "workshop_or_preliminary", 420 + i * 5, 480 + i * 5, 5.2, 5, failed_c=True))
    for i in range(1, 7):
        cands31.append(_mk_cand(f"unv_ws_{i:02d}_" + ("a" * 45), f"UnvW{i}", "Workshop", urls["emnlp"], "EMNLP 2027 Main. Submission open.", "fallback", "workshop_or_preliminary", 500 + i * 5, 560 + i * 5, 5.2, 5, stale=True))

    vn31_in = tmp_path / "vn31_in.json"
    vn31_in.write_text(json.dumps({
        "target": tgt665,
        "target_scorecard": {"weights": _weights(), "ratings": _ratings((7, 6, 7, 7, 6, 7))},
        "candidate_venues": cands31,
    }), encoding="utf-8")
    vn31_full = tmp_path / "vn31_full.json"
    r_31 = run_cli(SCRIPTS_DIR / "compare_venue_novelty.py", [str(vn31_in), "--portfolio", "--sources-dir", str(src_dir), "--target-overall", "6.65", "--out", str(vn31_full), "--compact"])
    assert r_31.returncode == 0, r_31.stderr + r_31.stdout
    c31_obj = json.loads(r_31.stdout)
    assert c31_obj["venue_summaries"] == []
    c31_obj.pop("artifact_path", None)
    vn31_comp = tmp_path / "vn31_comp.json"
    vn31_comp.write_text(json.dumps(c31_obj), encoding="utf-8")

    sc_665 = tmp_path / "sc_665.json"
    sc_665.write_text(json.dumps({"weights": _weights(), "ratings": _ratings((7, 6, 7, 7, 6, 7))}), encoding="utf-8")
    r_31f = run_cli(SCRIPTS_DIR / "evaluate_submission.py", ["--scorecard", str(sc_665), "--venue-novelty", str(vn31_full)])
    r_31c = run_cli(SCRIPTS_DIR / "evaluate_submission.py", ["--scorecard", str(sc_665), "--venue-novelty", str(vn31_comp)])
    assert r_31f.returncode == 0 and r_31c.returncode == 0
    assert r_31f.json_out["selected_venue"]["venue_id"] == r_31c.json_out["selected_venue"]["venue_id"] == top_fid
    assert r_31f.json_out["selected_venue"]["venue_tier"] == r_31c.json_out["selected_venue"]["venue_tier"] == "q1_or_tier_a"
    for sv in r_31c.json_out["venue_portfolio"]["surviving_venues"]:
        if sv["venue_id"].startswith("conf_ws_"):
            assert sv["venue_tier"] != "q1_or_tier_a"


def test_e2e_m9b_r6_portfolio_ccf_a_flagship_q1_db_cap5_retargets_to_workshop(
    mock_server: MockScholarlyServer, tmp_path: Path
) -> None:
    """E2E Regression for R6: real compare_venue_novelty --portfolio (TPAMI journal_q1 & NeurIPS D&B dataset_benchmark + 2 workshops) + check_artifact_readiness WARN (cap=5) retargets to Workshop in full & --compact modes."""
    for path_s, title in (
        ("/tpami/2027/cfp", "TPAMI 2027 Main. Submission open. Fee USD 0."),
        ("/ndb/2027/cfp", "NeurIPS 2027 Datasets and Benchmarks. Submission open. Fee USD 0."),
        ("/nws/2027/cfp", "NeurIPS Workshop 2027. Submission open. Fee USD 0."),
        ("/iws/2027/cfp", "ICML Workshop 2027. Submission open. Fee USD 0."),
    ):
        mock_server.add_route(path_s, (200, "text/html", f"<html><body><p>{title}</p></body></html>"), host="localhost")
    env = mock_server.env()
    urls = {
        "tpami": mock_server.url("/tpami/2027/cfp", host="localhost"),
        "ndb": mock_server.url("/ndb/2027/cfp", host="localhost"),
        "nws": mock_server.url("/nws/2027/cfp", host="localhost"),
        "iws": mock_server.url("/iws/2027/cfp", host="localhost"),
    }

    src_dir = tmp_path / "sources_r6"
    src_dir.mkdir()
    dos = tmp_path / "dos_r6.json"
    dos.write_text(json.dumps({
        "venue": "R6 Portfolio", "edition": "2027", "official_cfp_url": urls["tpami"], "checked_at": iso_utc(0),
        "evidence_claims": [{"field": k, "source_url": u, "quote": "Submission open."} for k, u in urls.items()],
    }), encoding="utf-8")
    r_cap = run_cli(SCRIPTS_DIR / "capture_venue_sources.py", [str(dos), "--out", str(src_dir / "venue-sources.json")], env=env)
    assert r_cap.returncode == 0, r_cap.stderr

    warn_repo = tmp_path / "warn_repo_r6"
    WorkspaceFactory.make_ml_repo(warn_repo)
    _make_clean_repo(warn_repo)
    (warn_repo / "requirements.txt").write_text("numpy\n", encoding="utf-8")
    art_warn = tmp_path / "art_warn_r6.json"
    r_art = run_cli(SCRIPTS_DIR / "check_artifact_readiness.py", ["--repo-dir", str(warn_repo), "--anonymous", "--out", str(art_warn)])
    assert r_art.returncode == 0, r_art.stderr + r_art.stdout
    assert json.loads(art_warn.read_text(encoding="utf-8"))["recommended_transparency_cap"] == 5

    (src_dir / "target.txt").write_text("Full text target evidence.\n", encoding="utf-8")
    base_fix = json.loads((REFS_DIR / "venue-novelty-profile.fixture.json").read_text(encoding="utf-8"))
    tgt = copy.deepcopy(base_fix["target"])
    tgt.update({
        "id": "target", "score": 8, "low": 7, "high": 9,
        "closest_work_id": "target", "closest_work_locator": 'target.txt#L1 "Full text target"',
        "assessed_at_utc": iso_utc(0),
    })

    def _mk_panel(prefix: str, trk: str):
        rows = copy.deepcopy(base_fix["accepted_panel"])
        for i, row in enumerate(rows):
            pid = f"{prefix}_{i}"
            (src_dir / f"{pid}.txt").write_text("Accepted evidence.\n", encoding="utf-8")
            row.update({
                "id": pid, "track": trk, "score": 6, "low": 5, "high": 7,
                "overall_score": 6.5, "topic_relation": "different_topic",
                "closest_work_id": pid, "closest_work_locator": f'{pid}.txt#L1 "Accepted evidence"',
                "assessed_at_utc": iso_utc(0),
            })
        return rows

    def _mk_cand(vid: str, name: str, trk: str, url: str, role: str, dl: int, nt: int):
        psel = copy.deepcopy(base_fix["panel_selection"])
        psel["track"] = trk
        return {
            "venue_id": vid, "role": role,
            "venue": {
                "name": name, "edition": "2027", "track": trk,
                "official_cfp_url": url, "checked_at_utc": iso_utc(0),
                "max_source_age_days": 14,
                "submission_deadline_utc": iso_utc(dl), "notification_date_utc": iso_utc(nt),
                "simultaneous_submission_allowed": False,
            },
            "panel_selection": psel, "accepted_panel": _mk_panel(vid, trk),
            "fit_axes": [{"name": ax, "score": 2, "source_url": url, "locator": '"Submission open."', "reason": "ok"} for ax in ("scope_audience", "contribution_track", "evidence_maturity", "format_eligibility", "user_constraints")],
            "hard_constraints": [{"name": cn, "status": "met", "source_url": url, "reason": "ok"} for cn in ("deadline", "budget", "eligibility")],
        }

    ratings = _ratings((8, 7, 8, 8, 7, 8))
    scenarios = [
        (
            "tpami_jq1", "journal_q1", "tpami_main", "TPAMI", "Main", urls["tpami"], "TPAMI",
            {"comprehensive_ablations": True, "reproducibility_details": True},
            "post_cap_tier_fit:transparency_5_below_journal_q1_min_6",
        ),
        (
            "ndb_db", "dataset_benchmark", "neurips_db", "NeurIPS", "Datasets and Benchmarks", urls["ndb"], "NeurIPS",
            {"data_quality_audit": True, "annotation_protocol": True, "ethics_and_license_t1_t2": True},
            "post_cap_tier_fit:transparency_5_below_dataset_benchmark_min_6",
        ),
    ]
    for tag, vtype, vid0, name0, trk0, url0, tgt_arg, checks, exp_reason in scenarios:
        sc_p = tmp_path / f"sc_{tag}.json"
        sc_p.write_text(json.dumps({"venue_type": vtype, "venue_checks": checks, "ratings": ratings}), encoding="utf-8")
        port_in = tmp_path / f"port_{tag}.json"
        port_in.write_text(json.dumps({
            "venue_type": vtype,
            "venue_checks": checks,
            "target": tgt,
            "target_scorecard": {"venue_type": vtype, "venue_checks": checks, "ratings": ratings},
            "candidate_venues": [
                _mk_cand(vid0, name0, trk0, url0, "primary", 30, 90),
                _mk_cand("neurips_ws", "NeurIPS Workshop", "Workshop", urls["nws"], "fallback", 120, 150),
                _mk_cand("icml_ws", "ICML Workshop", "Workshop", urls["iws"], "fallback", 180, 210),
            ],
        }), encoding="utf-8")

        vn_full = tmp_path / f"vn_{tag}_full.json"
        r_vn = run_cli(SCRIPTS_DIR / "compare_venue_novelty.py", [str(port_in), "--portfolio", "--sources-dir", str(src_dir), "--out", str(vn_full), "--compact"])
        assert r_vn.returncode == 0, r_vn.stderr + r_vn.stdout
        vn_comp_obj = json.loads(r_vn.stdout)
        vn_comp_obj.pop("artifact_path", None)
        vn_comp = tmp_path / f"vn_{tag}_comp.json"
        vn_comp.write_text(json.dumps(vn_comp_obj), encoding="utf-8")

        for mode_lbl, vn_p in (("full", vn_full), ("vn_compact", vn_comp)):
            r_ev = run_cli(SCRIPTS_DIR / "evaluate_submission.py", ["--scorecard", str(sc_p), "--venue-novelty", str(vn_p), "--artifact-readiness", str(art_warn), "--target-venue", tgt_arg])
            assert r_ev.returncode == 0, f"{tag} {mode_lbl}: {r_ev.stderr + r_ev.stdout}"
            d_ev = r_ev.json_out
            assert d_ev["ready_to_submit"] is True
            assert d_ev["verdict"] == "RETARGETED_READY"
            assert d_ev["selected_venue"]["venue_tier"] == "workshop_or_preliminary"
            assert d_ev["selected_venue"]["retargeted_from"] == vid0
            disq = next(v for v in d_ev["venue_portfolio"]["disqualified_venues"] if v["venue_id"] == vid0)
            assert exp_reason in disq["disqualification_reasons"]

            ev_out = tmp_path / f"ev_{tag}_{mode_lbl}.json"
            r_ev_c = run_cli(SCRIPTS_DIR / "evaluate_submission.py", ["--scorecard", str(sc_p), "--venue-novelty", str(vn_p), "--artifact-readiness", str(art_warn), "--target-venue", tgt_arg, "--out", str(ev_out), "--compact"])
            assert r_ev_c.returncode == 0, f"{tag} {mode_lbl} compact: {r_ev_c.stderr + r_ev_c.stdout}"
            assert len(r_ev_c.stdout.encode("utf-8")) < MAX_COMPACT_BYTES
            dc = r_ev_c.json_out
            assert dc["ready_to_submit"] is True
            assert dc["verdict"] == "RETARGETED_READY"
            assert dc["selected_venue"]["venue_tier"] == "workshop_or_preliminary"
            assert dc["selected_venue"]["retargeted_from"] == vid0


def test_e2e_m9b_r7_single_and_synthesized_venue_rank_aware_compatibility(
    mock_server: MockScholarlyServer, tmp_path: Path
) -> None:
    """E2E Regression for R7 Cases A-D: single-venue & synthesized-venue paths respect rank-aware venue_type guard."""
    for path_s, title in (
        ("/neurips/2027/cfp", "NeurIPS 2027 Main. Submission open. Fee USD 0."),
        ("/evalws/2027/cfp", "Eval Workshop 2027. Submission open. Fee USD 0."),
    ):
        mock_server.add_route(path_s, (200, "text/html", f"<html><body><p>{title}</p></body></html>"), host="localhost")
    env = mock_server.env()
    urls = {
        "neurips": mock_server.url("/neurips/2027/cfp", host="localhost"),
        "evalws": mock_server.url("/evalws/2027/cfp", host="localhost"),
    }

    src_dir = tmp_path / "sources_r7_single"
    src_dir.mkdir()
    dos = tmp_path / "dos_r7_single.json"
    dos.write_text(json.dumps({
        "venue": "R7 Single", "edition": "2027", "official_cfp_url": urls["neurips"], "checked_at": iso_utc(0),
        "evidence_claims": [{"field": k, "source_url": u, "quote": "Submission open."} for k, u in urls.items()],
    }), encoding="utf-8")
    r_cap = run_cli(SCRIPTS_DIR / "capture_venue_sources.py", [str(dos), "--out", str(src_dir / "venue-sources.json")], env=env)
    assert r_cap.returncode == 0, r_cap.stderr

    (src_dir / "target.txt").write_text("Full text target evidence.\n", encoding="utf-8")
    base_fix = json.loads((REFS_DIR / "venue-novelty-profile.fixture.json").read_text(encoding="utf-8"))
    tgt = copy.deepcopy(base_fix["target"])
    tgt.update({
        "id": "target", "score": 8, "low": 7, "high": 9,
        "closest_work_id": "target", "closest_work_locator": 'target.txt#L1 "Full text target"',
        "assessed_at_utc": iso_utc(0),
    })

    def _mk_panel(prefix: str, trk: str):
        rows = copy.deepcopy(base_fix["accepted_panel"])
        for i, row in enumerate(rows):
            pid = f"{prefix}_{i}"
            (src_dir / f"{pid}.txt").write_text("Accepted evidence.\n", encoding="utf-8")
            row.update({
                "id": pid, "track": trk, "score": 6, "low": 5, "high": 7,
                "overall_score": 6.5, "topic_relation": "different_topic",
                "closest_work_id": pid, "closest_work_locator": f'{pid}.txt#L1 "Accepted evidence"',
                "assessed_at_utc": iso_utc(0),
            })
        return rows

    ps_main = copy.deepcopy(base_fix["panel_selection"])
    ps_main["track"] = "Main"
    vn_top_in = tmp_path / "vn_top_in.json"
    vn_top_in.write_text(json.dumps({
        "venue": {"name": "NeurIPS", "edition": "2027", "track": "Main", "official_cfp_url": urls["neurips"], "checked_at_utc": iso_utc(0), "max_source_age_days": 14, "tier_expectation": "top_tier_flagship"},
        "target": tgt,
        "target_scorecard": {"ratings": _ratings((8, 7, 5, 5, 7, 8))},
        "panel_selection": ps_main,
        "accepted_panel": _mk_panel("neurips", "Main"),
        "fit_axes": [{"name": ax, "score": 2, "source_url": urls["neurips"], "locator": '"Submission open."', "reason": "ok"} for ax in ("scope_audience", "contribution_track", "evidence_maturity", "format_eligibility", "user_constraints")],
        "hard_constraints": [{"name": cn, "status": "met", "source_url": urls["neurips"], "reason": "ok"} for cn in ("deadline", "budget", "eligibility")],
    }), encoding="utf-8")
    vn_top_out = tmp_path / "vn_top_out.json"
    r_vnt = run_cli(SCRIPTS_DIR / "compare_venue_novelty.py", [str(vn_top_in), "--sources-dir", str(src_dir), "--out", str(vn_top_out)])
    assert r_vnt.returncode in (0, 1), r_vnt.stderr + r_vnt.stdout

    # Cases A & B: workshop_preliminary (soundness=5, evidence=5) targeting top_tier_flagship
    sc_ws = tmp_path / "sc_ws.json"
    sc_ws.write_text(json.dumps({"venue_type": "workshop_preliminary", "ratings": _ratings((8, 7, 5, 5, 7, 8))}), encoding="utf-8")
    for args in (
        ["--scorecard", str(sc_ws), "--target-venue", "NeurIPS", "--target-venue-tier", "top_tier_flagship"],
        ["--scorecard", str(sc_ws), "--venue-novelty", str(vn_top_out), "--target-venue", "NeurIPS"],
    ):
        r_ev = run_cli(SCRIPTS_DIR / "evaluate_submission.py", args)
        assert r_ev.returncode == 1, r_ev.stderr + r_ev.stdout
        assert r_ev.json_out["ready_to_submit"] is False
        assert r_ev.json_out["verdict"] == "BLOCKED_NO_VIABLE_VENUE"
        disq_r = r_ev.json_out["venue_portfolio"]["disqualified_venues"][0]["disqualification_reasons"]
        assert "post_cap_tier_fit:soundness_5_below_top_tier_flagship_min_6" in disq_r
        assert "post_cap_tier_fit:evidence_5_below_top_tier_flagship_min_6" in disq_r

    # Cases C & D: journal_q1 (transparency=5) targeting Eval Workshop (workshop_or_preliminary)
    ps_ws = copy.deepcopy(base_fix["panel_selection"])
    ps_ws["track"] = "Workshop"
    vn_ws_in = tmp_path / "vn_ws_in.json"
    vn_ws_in.write_text(json.dumps({
        "venue": {"name": "Eval Workshop", "edition": "2027", "track": "Workshop", "official_cfp_url": urls["evalws"], "checked_at_utc": iso_utc(0), "max_source_age_days": 14},
        "target": tgt,
        "target_scorecard": {"ratings": _ratings((8, 7, 8, 8, 5, 8))},
        "panel_selection": ps_ws,
        "accepted_panel": _mk_panel("evalws", "Workshop"),
        "fit_axes": [{"name": ax, "score": 2, "source_url": urls["evalws"], "locator": '"Submission open."', "reason": "ok"} for ax in ("scope_audience", "contribution_track", "evidence_maturity", "format_eligibility", "user_constraints")],
        "hard_constraints": [{"name": cn, "status": "met", "source_url": urls["evalws"], "reason": "ok"} for cn in ("deadline", "budget", "eligibility")],
    }), encoding="utf-8")
    vn_ws_out = tmp_path / "vn_ws_out.json"
    r_vnw = run_cli(SCRIPTS_DIR / "compare_venue_novelty.py", [str(vn_ws_in), "--sources-dir", str(src_dir), "--out", str(vn_ws_out)])
    assert r_vnw.returncode == 0, r_vnw.stderr + r_vnw.stdout

    sc_jq1 = tmp_path / "sc_jq1.json"
    sc_jq1.write_text(json.dumps({
        "venue_type": "journal_q1",
        "venue_checks": {"comprehensive_ablations": True, "reproducibility_details": True},
        "ratings": _ratings((8, 7, 8, 8, 5, 8)),
    }), encoding="utf-8")
    for args in (
        ["--scorecard", str(sc_jq1), "--target-venue", "Eval Workshop"],
        ["--scorecard", str(sc_jq1), "--venue-novelty", str(vn_ws_out), "--target-venue", "Eval Workshop"],
    ):
        r_ev = run_cli(SCRIPTS_DIR / "evaluate_submission.py", args)
        assert r_ev.returncode == 0, r_ev.stderr + r_ev.stdout
        assert r_ev.json_out["ready_to_submit"] is True
        assert r_ev.json_out["verdict"] == "READY_TO_SUBMIT"
        assert r_ev.json_out["selected_venue"]["venue_tier"] == "workshop_or_preliminary"

    # Real contamination check failing must not appear in subfield_criteria.covered_checks
    train_p = tmp_path / "train.jsonl"
    eval_p = tmp_path / "eval.jsonl"
    sample = json.dumps({"text": "Exact benchmark prompt example that triggers contamination detection."})
    train_p.write_text(sample + "\n", encoding="utf-8")
    eval_p.write_text(sample + "\n", encoding="utf-8")
    contam_out = tmp_path / "contam.json"
    r_ct = run_cli(SCRIPTS_DIR / "check_experiment_rigor.py", ["contamination", "--train", str(train_p), "--eval", str(eval_p), "--out", str(contam_out)])
    assert r_ct.returncode != 0
    r_cb = run_cli(SCRIPTS_DIR / "evaluate_submission.py", ["--scorecard", str(sc_jq1), "--rigor", str(contam_out), "--subfield-preset", "nlp_llm"])
    assert r_cb.returncode == 1
    assert "contamination_check" not in r_cb.json_out["subfield_criteria"]["covered_checks"]
    assert "contamination_check" in r_cb.json_out["subfield_criteria"]["missing_checks"]


def test_e2e_m9b_r7_trim_stage3_compact_without_out_and_nodisk_parity(
    mock_server: MockScholarlyServer, tmp_path: Path
) -> None:
    """E2E Regression for R7: trim_stage >= 3 --compact without --out (artifact_path is None) and nodisk enforce venue_type & floor across Scenarios A, B, dataset_benchmark, and conference_top_tier."""
    cfp_url = mock_server.url("/r7-port/2027/cfp", host="localhost")
    mock_server.add_route(
        "/r7-port/2027/cfp",
        (200, "text/html", "<html><body><p>TPAMI AAAI NeurIPS ICML LREC Workshop 2027. Submission open. Fee USD 0.</p></body></html>"),
        host="localhost",
    )
    env = mock_server.env()

    src_dir = tmp_path / "sources_r7_port"
    src_dir.mkdir()
    dos = tmp_path / "dos_r7_port.json"
    dos.write_text(json.dumps({
        "venue": "R7 Portfolio", "edition": "2027", "official_cfp_url": cfp_url, "checked_at": iso_utc(0),
        "evidence_claims": [{"field": "cfp", "source_url": cfp_url, "quote": "Submission open."}],
    }), encoding="utf-8")
    r_cap = run_cli(SCRIPTS_DIR / "capture_venue_sources.py", [str(dos), "--out", str(src_dir / "venue-sources.json")], env=env)
    assert r_cap.returncode == 0, r_cap.stderr

    warn_repo = tmp_path / "warn_repo_r7"
    WorkspaceFactory.make_ml_repo(warn_repo)
    _make_clean_repo(warn_repo)
    (warn_repo / "requirements.txt").write_text("numpy\n", encoding="utf-8")
    art_warn = tmp_path / "art_warn_r7.json"
    r_art = run_cli(SCRIPTS_DIR / "check_artifact_readiness.py", ["--repo-dir", str(warn_repo), "--anonymous", "--out", str(art_warn)])
    assert r_art.returncode == 0, r_art.stderr + r_art.stdout
    assert json.loads(art_warn.read_text(encoding="utf-8"))["recommended_transparency_cap"] == 5

    (src_dir / "target.txt").write_text("Full text target evidence.\n", encoding="utf-8")
    base_fix = json.loads((REFS_DIR / "venue-novelty-profile.fixture.json").read_text(encoding="utf-8"))
    tgt = copy.deepcopy(base_fix["target"])
    tgt.update({
        "id": "target", "score": 8, "low": 7, "high": 9,
        "closest_work_id": "target", "closest_work_locator": 'target.txt#L1 "Full text target"',
        "assessed_at_utc": iso_utc(0),
    })

    def _mk_panel(prefix: str, trk: str):
        rows = copy.deepcopy(base_fix["accepted_panel"])
        for i, row in enumerate(rows):
            pid = f"{prefix}_{i}"
            (src_dir / f"{pid}.txt").write_text("Accepted evidence.\n", encoding="utf-8")
            row.update({
                "id": pid, "track": trk, "score": 6, "low": 5, "high": 7,
                "overall_score": 6.5, "topic_relation": "different_topic",
                "closest_work_id": pid, "closest_work_locator": f'{pid}.txt#L1 "Accepted evidence"',
                "assessed_at_utc": iso_utc(0),
            })
        return rows

    def _mk_cand(vid: str, name: str, trk: str, role: str, dl: int, nt: int):
        psel = copy.deepcopy(base_fix["panel_selection"])
        psel["track"] = trk
        return {
            "venue_id": vid, "role": role,
            "venue": {
                "name": name, "edition": "2027", "track": trk,
                "official_cfp_url": cfp_url, "checked_at_utc": iso_utc(0),
                "max_source_age_days": 14,
                "submission_deadline_utc": iso_utc(dl), "notification_date_utc": iso_utc(nt),
                "simultaneous_submission_allowed": False,
            },
            "panel_selection": psel, "accepted_panel": _mk_panel(vid, trk),
            "fit_axes": [{"name": ax, "score": 2, "source_url": cfp_url, "locator": '"Submission open."', "reason": "ok"} for ax in ("scope_audience", "contribution_track", "evidence_maturity", "format_eligibility", "user_constraints")],
            "hard_constraints": [{"name": cn, "status": "met", "source_url": cfp_url, "reason": "ok"} for cn in ("deadline", "budget", "eligibility")],
        }

    ratings_good = _ratings((8, 7, 8, 8, 7, 8))
    jq1_checks = {"comprehensive_ablations": True, "reproducibility_details": True}

    # Scenario A: TPAMI + 25 workshops, no weights, --compact WITHOUT --out
    cands_a = [_mk_cand("tpami_main_" + "p" * 120, "TPAMI", "Main", "primary", 30, 90)]
    for i in range(25):
        cands_a.append(_mk_cand(f"neurips_workshop_id_{i:02d}_" + "w" * 100, f"NeurIPS Workshop {i}", "Workshop", "fallback", 120 + i * 3, 150 + i * 3))
    port_a = tmp_path / "port_a.json"
    port_a.write_text(json.dumps({
        "venue_type": "journal_q1", "venue_checks": jq1_checks, "target": tgt,
        "target_scorecard": {"venue_type": "journal_q1", "venue_checks": jq1_checks, "ratings": ratings_good},
        "candidate_venues": cands_a,
    }), encoding="utf-8")
    r_vna = run_cli(SCRIPTS_DIR / "compare_venue_novelty.py", [str(port_a), "--portfolio", "--sources-dir", str(src_dir), "--compact"])
    assert r_vna.returncode == 0, r_vna.stderr + r_vna.stdout
    assert r_vna.json_out["venue_summaries"] == [] and r_vna.json_out.get("artifact_path") is None
    vn_a = tmp_path / "vn_a.json"
    vn_a.write_text(r_vna.stdout, encoding="utf-8")
    sc_a = tmp_path / "sc_a.json"
    sc_a.write_text(json.dumps({"venue_type": "journal_q1", "venue_checks": jq1_checks, "ratings": ratings_good}), encoding="utf-8")
    r_eva = run_cli(SCRIPTS_DIR / "evaluate_submission.py", ["--scorecard", str(sc_a), "--venue-novelty", str(vn_a), "--artifact-readiness", str(art_warn), "--target-venue", "TPAMI"])
    assert r_eva.returncode == 0, r_eva.stderr + r_eva.stdout
    assert r_eva.json_out["verdict"] == "RETARGETED_READY"
    assert r_eva.json_out["selected_venue"]["venue_tier"] == "workshop_or_preliminary"
    assert r_eva.json_out["selected_venue"]["retargeted_from"].startswith("tpami_main_")

    # Scenario B: AAAI + TPAMI + 25 workshops, WITH weights, --compact WITHOUT --out
    w_jq1 = {"importance": 15, "novelty": 15, "soundness": 25, "evidence": 25, "transparency": 10, "clarity": 10}
    cands_b = [
        _mk_cand("aaai_main_venue_top_00_" + "a" * 100, "AAAI", "Main", "primary", 30, 90),
        _mk_cand("tpami_main_venue_01_" + "p" * 100, "TPAMI", "Main", "primary", 60, 120),
    ]
    for i in range(25):
        cands_b.append(_mk_cand(f"neurips_workshop_id_{i:02d}_" + "w" * 100, f"NeurIPS Workshop {i}", "Workshop", "fallback", 150 + i * 3, 180 + i * 3))
    port_b = tmp_path / "port_b.json"
    port_b.write_text(json.dumps({
        "venue_type": "journal_q1", "venue_checks": jq1_checks, "target": tgt,
        "target_scorecard": {"venue_type": "journal_q1", "venue_checks": jq1_checks, "weights": w_jq1, "ratings": ratings_good},
        "candidate_venues": cands_b,
    }), encoding="utf-8")
    r_vnb = run_cli(SCRIPTS_DIR / "compare_venue_novelty.py", [str(port_b), "--portfolio", "--sources-dir", str(src_dir), "--compact"])
    assert r_vnb.returncode == 0, r_vnb.stderr + r_vnb.stdout
    assert r_vnb.json_out["venue_summaries"] == [] and r_vnb.json_out.get("artifact_path") is None
    vn_b = tmp_path / "vn_b.json"
    vn_b.write_text(r_vnb.stdout, encoding="utf-8")
    r_evb = run_cli(SCRIPTS_DIR / "evaluate_submission.py", ["--scorecard", str(sc_a), "--venue-novelty", str(vn_b), "--artifact-readiness", str(art_warn), "--target-venue", "TPAMI"])
    assert r_evb.returncode == 0, r_evb.stderr + r_evb.stdout
    assert r_evb.json_out["verdict"] == "RETARGETED_READY"
    assert r_evb.json_out["selected_venue"]["retargeted_from"].startswith("tpami_main_venue_01_")
    disq_b_ids = {v["venue_id"] for v in r_evb.json_out["venue_portfolio"]["disqualified_venues"]}
    assert any(x.startswith("aaai_main_venue_top_00_") for x in disq_b_ids)
    assert any(x.startswith("tpami_main_venue_01_") for x in disq_b_ids)

    # Probe E: dataset_benchmark (NeurIPS D&B + LREC + 45 conf_ws workshops, --compact WITHOUT --out)
    db_checks = {"data_quality_audit": True, "annotation_protocol": True, "ethics_and_license_t1_t2": True}
    cands_e = [
        _mk_cand("neurips_db_" + "d" * 100, "NeurIPS", "Datasets and Benchmarks", "primary", 30, 90),
        _mk_cand("lrec_main_" + "l" * 100, "LREC", "Main", "primary", 60, 120),
    ]
    for i in range(45):
        cands_e.append(_mk_cand(f"conf_ws_{i:02d}_" + "w" * 100, f"ConfWS {i}", "Workshop", "fallback", 150 + i * 2, 180 + i * 2))
    port_e = tmp_path / "port_e.json"
    port_e.write_text(json.dumps({
        "venue_type": "dataset_benchmark", "venue_checks": db_checks, "target": tgt,
        "target_scorecard": {"venue_type": "dataset_benchmark", "venue_checks": db_checks, "ratings": ratings_good},
        "candidate_venues": cands_e,
    }), encoding="utf-8")
    r_vne = run_cli(SCRIPTS_DIR / "compare_venue_novelty.py", [str(port_e), "--portfolio", "--sources-dir", str(src_dir), "--compact"])
    assert r_vne.returncode == 0, r_vne.stderr + r_vne.stdout
    assert r_vne.json_out["venue_summaries"] == [] and r_vne.json_out.get("artifact_path") is None
    vn_e = tmp_path / "vn_e.json"
    vn_e.write_text(r_vne.stdout, encoding="utf-8")
    sc_e = tmp_path / "sc_e.json"
    sc_e.write_text(json.dumps({"venue_type": "dataset_benchmark", "venue_checks": db_checks, "ratings": ratings_good}), encoding="utf-8")
    r_eve = run_cli(SCRIPTS_DIR / "evaluate_submission.py", ["--scorecard", str(sc_e), "--venue-novelty", str(vn_e), "--artifact-readiness", str(art_warn), "--target-venue", "NeurIPS", "--compact"])
    assert r_eve.returncode == 0, r_eve.stderr + r_eve.stdout
    assert len(r_eve.stdout.encode("utf-8")) < MAX_COMPACT_BYTES
    assert r_eve.json_out["verdict"] == "RETARGETED_READY"
    assert r_eve.json_out["selected_venue"]["venue_id"].startswith("conf_ws_")
    assert r_eve.json_out["selected_venue"]["retargeted_from"].startswith("neurips_db_")

    # Probe F: conference_top_tier (NeurIPS Main + ICML + 45 conf_ws, 6.10 -> 5.90 via cap=5, full == compact_disk == compact_nodisk)
    ratings_f = _ratings((6, 6, 6, 6, 7, 6))
    cands_f = [
        _mk_cand("neurips_main_" + "n" * 100, "NeurIPS", "Main", "primary", 30, 90),
        _mk_cand("icml_main_" + "i" * 100, "ICML", "Main", "primary", 60, 120),
    ]
    for i in range(45):
        cands_f.append(_mk_cand(f"conf_ws_{i:02d}_" + "w" * 100, f"ConfWS {i}", "Workshop", "fallback", 150 + i * 2, 180 + i * 2))
    port_f = tmp_path / "port_f.json"
    port_f.write_text(json.dumps({
        "venue_type": "conference_top_tier", "target": tgt,
        "target_scorecard": {"venue_type": "conference_top_tier", "ratings": ratings_f},
        "candidate_venues": cands_f,
    }), encoding="utf-8")
    vn_f_full = tmp_path / "vn_f_full.json"
    r_vnf = run_cli(SCRIPTS_DIR / "compare_venue_novelty.py", [str(port_f), "--portfolio", "--sources-dir", str(src_dir), "--out", str(vn_f_full), "--compact"])
    assert r_vnf.returncode == 0, r_vnf.stderr + r_vnf.stdout
    vn_f_disk = tmp_path / "vn_f_disk.json"
    vn_f_disk.write_text(r_vnf.stdout, encoding="utf-8")
    vn_f_nodisk_obj = json.loads(r_vnf.stdout)
    assert vn_f_nodisk_obj["venue_summaries"] == []
    vn_f_nodisk_obj.pop("artifact_path", None)
    vn_f_nodisk = tmp_path / "vn_f_nodisk.json"
    vn_f_nodisk.write_text(json.dumps(vn_f_nodisk_obj), encoding="utf-8")
    sc_f = tmp_path / "sc_f.json"
    sc_f.write_text(json.dumps({"venue_type": "conference_top_tier", "ratings": ratings_f}), encoding="utf-8")

    for lbl, vnp in (("full", vn_f_full), ("compact_disk", vn_f_disk), ("compact_nodisk", vn_f_nodisk)):
        r_evf = run_cli(SCRIPTS_DIR / "evaluate_submission.py", ["--scorecard", str(sc_f), "--venue-novelty", str(vnp), "--artifact-readiness", str(art_warn), "--target-venue", "NeurIPS", "--compact"])
        assert r_evf.returncode == 0, f"{lbl}: {r_evf.stderr + r_evf.stdout}"
        assert len(r_evf.stdout.encode("utf-8")) < MAX_COMPACT_BYTES
        assert r_evf.json_out["verdict"] == "RETARGETED_READY", lbl
        assert r_evf.json_out["weighted_unrounded"] == "5.9", lbl
        assert r_evf.json_out["selected_venue"]["venue_id"].startswith("conf_ws_"), lbl
        assert r_evf.json_out["selected_venue"]["retargeted_from"].startswith("neurips_main_"), lbl


def test_e2e_m9b_r8_venue_leads_fallback_and_tier_preservation_4mode_parity(
    mock_server: MockScholarlyServer, tmp_path: Path
) -> None:
    """E2E Regression for R8: 4-mode parity (full/compact_disk/compact_noout/compact_nodisk) across tpami_q1, journal_q1, conf_q2, acl_findings, tier_b_conf, workshop_preliminary NeurIPS, and non-conflicted acl_main fallback."""
    cfp_url = mock_server.url("/r8-port/2027/cfp", host="localhost")
    mock_server.add_route(
        "/r8-port/2027/cfp",
        (200, "text/html", "<html><body><p>TPAMI AAAI Journal Q1 NeurIPS ACL Tier-B Conf Workshop 2027. Submission open. Fee USD 0.</p></body></html>"),
        host="localhost",
    )
    env = mock_server.env()

    src_dir = tmp_path / "sources_r8"
    src_dir.mkdir()
    dos = tmp_path / "dos_r8.json"
    dos.write_text(json.dumps({
        "venue": "R8 Portfolio", "edition": "2027", "official_cfp_url": cfp_url, "checked_at": iso_utc(0),
        "evidence_claims": [{"field": "cfp", "source_url": cfp_url, "quote": "Submission open."}],
    }), encoding="utf-8")
    r_cap = run_cli(SCRIPTS_DIR / "capture_venue_sources.py", [str(dos), "--out", str(src_dir / "venue-sources.json")], env=env)
    assert r_cap.returncode == 0, r_cap.stderr

    warn_repo = tmp_path / "warn_repo_r8"
    WorkspaceFactory.make_ml_repo(warn_repo)
    _make_clean_repo(warn_repo)
    (warn_repo / "requirements.txt").write_text("numpy\n", encoding="utf-8")
    art5 = tmp_path / "art5_r8.json"
    r_art5 = run_cli(SCRIPTS_DIR / "check_artifact_readiness.py", ["--repo-dir", str(warn_repo), "--anonymous", "--out", str(art5)])
    assert r_art5.returncode == 0, r_art5.stderr + r_art5.stdout
    assert json.loads(art5.read_text(encoding="utf-8"))["recommended_transparency_cap"] == 5

    art4 = tmp_path / "art4_r8.json"
    art4.write_text(json.dumps({"schema": "artifact_readiness_v1", "verdict": "WARN", "ready_to_submit": True, "recommended_transparency_cap": 4, "blocking_reasons": []}), encoding="utf-8")

    # Clean ledger + real check_manuscript_ledger output with argument_audit evidence cap = 5
    led_src = tmp_path / "led_in_r8.json"
    led_src.write_text((REFS_DIR / "manuscript-ledger.schema-example.json").read_text(encoding="utf-8"), encoding="utf-8")
    led_out = tmp_path / "led_out_r8.json"
    r_led = run_cli(SCRIPTS_DIR / "check_manuscript_ledger.py", ["--ledger", str(led_src), "--out", str(led_out)])
    assert r_led.returncode == 0, r_led.stderr + r_led.stdout
    led_doc = json.loads(led_out.read_text(encoding="utf-8"))
    led_doc["argument_audit"] = {"enabled": True, "recommended_evidence_cap": 5}
    led5 = tmp_path / "led5_r8.json"
    led5.write_text(json.dumps(led_doc), encoding="utf-8")

    (src_dir / "target.txt").write_text("Full text target evidence.\n", encoding="utf-8")
    base_fix = json.loads((REFS_DIR / "venue-novelty-profile.fixture.json").read_text(encoding="utf-8"))
    tgt = copy.deepcopy(base_fix["target"])
    tgt.update({
        "id": "target", "score": 8, "low": 7, "high": 9,
        "closest_work_id": "target", "closest_work_locator": 'target.txt#L1 "Full text target"',
        "assessed_at_utc": iso_utc(0),
    })

    def _mk_panel(prefix: str, trk: str, ov: float = 6.5, sc_val: int = 6):
        rows = copy.deepcopy(base_fix["accepted_panel"])
        for i, row in enumerate(rows):
            pid = f"{prefix}_{i}"
            (src_dir / f"{pid}.txt").write_text("Accepted evidence.\n", encoding="utf-8")
            row.update({
                "id": pid, "track": trk, "score": sc_val, "low": max(1, sc_val - 1), "high": min(10, sc_val + 1),
                "overall_score": ov, "topic_relation": "different_topic",
                "closest_work_id": pid, "closest_work_locator": f'{pid}.txt#L1 "Accepted evidence"',
                "assessed_at_utc": iso_utc(0),
            })
        return rows

    def _mk_cand(vid: str, name: str, trk: str, role: str, dl: int, nt: int, ov: float = 6.5, sc_val: int = 6):
        psel = copy.deepcopy(base_fix["panel_selection"])
        psel["track"] = trk
        return {
            "venue_id": vid, "role": role,
            "venue": {
                "name": name, "edition": "2027", "track": trk,
                "official_cfp_url": cfp_url, "checked_at_utc": iso_utc(0), "max_source_age_days": 14,
                "submission_deadline_utc": iso_utc(dl), "notification_date_utc": iso_utc(nt), "simultaneous_submission_allowed": False,
            },
            "panel_selection": psel, "accepted_panel": _mk_panel(vid, trk, ov=ov, sc_val=sc_val),
            "fit_axes": [{"name": ax, "score": 2, "source_url": cfp_url, "locator": '"Submission open."', "reason": "ok"} for ax in ("scope_audience", "contribution_track", "evidence_maturity", "format_eligibility", "user_constraints")],
            "hard_constraints": [{"name": cn, "status": "met", "source_url": cfp_url, "reason": "ok"} for cn in ("deadline", "budget", "eligibility")],
        }

    def _run_4mode(tag: str, port_obj: dict, sc_obj: dict, *, tgt_venue: str, extra_args: list[str] | tuple[str, ...] = ()):
        pf = tmp_path / f"{tag}_port.json"
        pf.write_text(json.dumps(port_obj), encoding="utf-8")
        vn_full = tmp_path / f"{tag}_vn_full.json"
        r1 = run_cli(SCRIPTS_DIR / "compare_venue_novelty.py", [str(pf), "--portfolio", "--sources-dir", str(src_dir), "--out", str(vn_full), "--compact"])
        assert r1.returncode == 0, tag + ": " + r1.stderr + r1.stdout
        vn_disk = tmp_path / f"{tag}_vn_disk.json"
        vn_disk.write_text(r1.stdout, encoding="utf-8")
        r2 = run_cli(SCRIPTS_DIR / "compare_venue_novelty.py", [str(pf), "--portfolio", "--sources-dir", str(src_dir), "--compact"])
        assert r2.returncode == 0, tag + ": " + r2.stderr + r2.stdout
        vn_noout = tmp_path / f"{tag}_vn_noout.json"
        vn_noout.write_text(r2.stdout, encoding="utf-8")
        nodisk_obj = json.loads(r1.stdout)
        assert nodisk_obj["venue_summaries"] == [], tag
        nodisk_obj.pop("artifact_path", None)
        vn_nodisk = tmp_path / f"{tag}_vn_nodisk.json"
        vn_nodisk.write_text(json.dumps(nodisk_obj), encoding="utf-8")

        scf = tmp_path / f"{tag}_sc.json"
        scf.write_text(json.dumps(sc_obj), encoding="utf-8")
        docs = {}
        sigs = {}
        for mode, vnp in (("full", vn_full), ("compact_disk", vn_disk), ("compact_noout", vn_noout), ("compact_nodisk", vn_nodisk)):
            ev = run_cli(SCRIPTS_DIR / "evaluate_submission.py", ["--scorecard", str(scf), "--venue-novelty", str(vnp), "--target-venue", tgt_venue, *extra_args])
            d = ev.json_out
            docs[mode] = d
            sel = d.get("selected_venue") or {}
            sigs[mode] = (ev.returncode, d["ready_to_submit"], d["verdict"], sel.get("venue_id"), sel.get("retargeted_from"))
        assert len(set(sigs.values())) == 1, f"{tag} 4-mode mismatch: {sigs}"
        return sigs["full"], docs

    jq1_chk = {"comprehensive_ablations": True, "reproducibility_details": True}
    w_std = _weights()
    r_good = _ratings((8, 7, 8, 8, 7, 8))

    # 1. tpami_q1_01_...
    c1 = [_mk_cand("tpami_q1_01_" + "p" * 100, "TPAMI", "Main", "primary", 30, 90)] + [_mk_cand(f"conf_ws_{i:02d}_" + "w" * 100, f"ConfWS {i}", "Workshop", "fallback", 120 + i * 2, 140 + i * 2, ov=5.5, sc_val=5) for i in range(25)]
    s1, d1 = _run_4mode("tpami_q1", {"venue_type": "journal_q1", "venue_checks": jq1_chk, "target": tgt, "target_scorecard": {"venue_type": "journal_q1", "venue_checks": jq1_chk, "weights": w_std, "ratings": r_good}, "candidate_venues": c1}, {"venue_type": "journal_q1", "venue_checks": jq1_chk, "weights": w_std, "ratings": r_good}, tgt_venue="TPAMI", extra_args=["--artifact-readiness", str(art5)])
    assert s1[0] == 0 and s1[2] == "RETARGETED_READY" and s1[3].startswith("conf_ws_00_") and s1[4].startswith("tpami_q1_01_")
    assert "post_cap_tier_fit:transparency_5_below_journal_q1_min_6" in d1["compact_nodisk"]["venue_portfolio"]["disqualified_venues"][0]["disqualification_reasons"]

    # 2. aaai_main_00_... + journal_q1_01_...
    c2 = [_mk_cand("aaai_main_00_" + "a" * 100, "AAAI", "Main", "primary", 30, 90), _mk_cand("journal_q1_01_" + "j" * 100, "Journal Q1", "Main", "primary", 60, 120)] + [_mk_cand(f"conf_ws_{i:02d}_" + "w" * 100, f"ConfWS {i}", "Workshop", "fallback", 150 + i * 2, 170 + i * 2, ov=5.5, sc_val=5) for i in range(25)]
    s2, d2 = _run_4mode("journal_q1", {"venue_type": "journal_q1", "venue_checks": jq1_chk, "target": tgt, "target_scorecard": {"venue_type": "journal_q1", "venue_checks": jq1_chk, "weights": w_std, "ratings": r_good}, "candidate_venues": c2}, {"venue_type": "journal_q1", "venue_checks": jq1_chk, "weights": w_std, "ratings": r_good}, tgt_venue="Journal Q1", extra_args=["--artifact-readiness", str(art5)])
    assert s2[0] == 0 and s2[2] == "RETARGETED_READY" and s2[3].startswith("conf_ws_00_") and len(d2["compact_nodisk"]["venue_portfolio"]["disqualified_venues"]) == 2

    # 3. conf_q2_00_...
    w_t50 = {"importance": 10, "novelty": 10, "soundness": 10, "evidence": 10, "transparency": 50, "clarity": 10}
    c3 = [_mk_cand("neurips_main_00_" + "n" * 100, "NeurIPS", "Main", "primary", 30, 90), _mk_cand("conf_q2_00_" + "q" * 100, "Conf Q2", "Main", "fallback", 100, 120, ov=5.5, sc_val=5)] + [_mk_cand(f"conf_ws_{i:02d}_" + "w" * 100, f"ConfWS {i}", "Workshop", "fallback", 140 + i * 2, 160 + i * 2, ov=5.5, sc_val=5) for i in range(25)]
    s3, d3 = _run_4mode("conf_q2", {"target": tgt, "target_scorecard": {"weights": w_t50, "ratings": _ratings((6, 6, 6, 6, 6, 6))}, "candidate_venues": c3}, {"weights": w_t50, "ratings": _ratings((6, 6, 6, 6, 6, 6))}, tgt_venue="NeurIPS", extra_args=["--artifact-readiness", str(art4)])
    assert s3[0] == 0 and s3[2] == "RETARGETED_READY" and s3[3].startswith("conf_ws_00_") and s3[4].startswith("neurips_main_00_")
    q2_disq = next(v for v in d3["compact_nodisk"]["venue_portfolio"]["disqualified_venues"] if v["venue_id"].startswith("conf_q2_00_"))
    assert "post_cap_tier_fit:weighted_5_below_q2_q3_or_tier_b_min_5.50" in q2_disq["disqualification_reasons"]

    # 4a. acl_findings_00_... + --ledger cap=5 -> BLOCKED_NO_VIABLE_VENUE
    c4a = [_mk_cand("neurips_main_" + "n" * 100, "NeurIPS", "Main", "primary", 30, 90)] + [_mk_cand(f"acl_findings_{i:02d}_" + "f" * 100, f"ACL {i}", "Findings", "fallback", 120 + i * 2, 140 + i * 2) for i in range(25)]
    s4a, d4a = _run_4mode("acl_findings_blk", {"target": tgt, "target_scorecard": {"weights": w_std, "ratings": r_good}, "candidate_venues": c4a}, {"weights": w_std, "ratings": r_good}, tgt_venue="NeurIPS", extra_args=["--ledger", str(led5)])
    assert s4a[0] == 1 and s4a[2] == "BLOCKED_NO_VIABLE_VENUE"
    f0_disq = next(v for v in d4a["compact_nodisk"]["venue_portfolio"]["disqualified_venues"] if v["venue_id"].startswith("acl_findings_00_"))
    assert "post_cap_tier_fit:evidence_5_below_q1_or_tier_a_min_6" in f0_disq["disqualification_reasons"]

    # 4b. acl_findings_2027_... (soundness=5 < 6) -> RETARGETED_READY to conf_ws_00_...
    c4b = [_mk_cand("neurips_main_2027_" + "n" * 100, "NeurIPS", "Main", "primary", 30, 90), _mk_cand("acl_findings_2027_" + "a" * 100, "ACL Findings", "Findings", "fallback", 100, 120)] + [_mk_cand(f"conf_ws_{i:02d}_" + "w" * 100, f"ConfWS {i}", "Workshop", "fallback", 140 + i * 2, 160 + i * 2, ov=5.5, sc_val=5) for i in range(45)]
    s4b, _ = _run_4mode("acl_findings_ret", {"target": tgt, "target_scorecard": {"weights": w_std, "ratings": _ratings((8, 7, 6, 8, 8, 8))}, "candidate_venues": c4b}, {"weights": w_std, "ratings": _ratings((8, 7, 5, 8, 8, 8))}, tgt_venue="ACL Findings")
    assert s4b[0] == 0 and s4b[2] == "RETARGETED_READY" and s4b[3].startswith("conf_ws_00_") and s4b[4].startswith("acl_findings_2027_")

    # 5. tier_b_conf_2027_... (weighted=5.20 < 5.50)
    c5 = [_mk_cand("tier_b_conf_2027_" + "b" * 100, "Tier-B Conf", "Main", "primary", 30, 90, ov=5.5, sc_val=5)] + [_mk_cand(f"conf_ws_{i:02d}_" + "w" * 100, f"ConfWS {i}", "Workshop", "fallback", 120 + i * 2, 140 + i * 2, ov=5.5, sc_val=5) for i in range(46)]
    s5, _ = _run_4mode("tier_b_ret", {"target": tgt, "target_scorecard": {"weights": w_std, "ratings": _ratings((6, 6, 5, 6, 5, 5))}, "candidate_venues": c5}, {"weights": w_std, "ratings": _ratings((5, 5, 5, 6, 5, 5))}, tgt_venue="Tier-B Conf")
    assert s5[0] == 0 and s5[2] == "RETARGETED_READY" and s5[3].startswith("conf_ws_00_") and s5[4].startswith("tier_b_conf_2027_")

    # 6. neurips_main_... with workshop_preliminary, raw ratings=(8,7,5,5,7,8), matched_tier=None
    c6 = [_mk_cand("neurips_main_" + "n" * 100, "NeurIPS", "Main", "primary", 30, 90)] + [_mk_cand(f"conf_ws_{i:02d}_" + "w" * 100, f"ConfWS {i}", "Workshop", "fallback", 120 + i * 2, 140 + i * 2, ov=5.5, sc_val=5) for i in range(25)]
    s6, _ = _run_4mode("neurips_ws_prelim", {"venue_type": "workshop_preliminary", "target": tgt, "target_scorecard": {"venue_type": "workshop_preliminary", "ratings": _ratings((8, 7, 5, 5, 7, 8))}, "candidate_venues": c6}, {"venue_type": "workshop_preliminary", "ratings": _ratings((8, 7, 5, 5, 7, 8))}, tgt_venue="NeurIPS")
    assert s6[0] == 0 and s6[2] == "RETARGETED_READY" and s6[3].startswith("conf_ws_00_") and s6[4].startswith("neurips_main_")

    # 7. Non-conflicted acl_main_... in viable_fallback (conference_top_tier, 6.10 -> 5.90 via cap=5)
    c7 = [_mk_cand("neurips_main_" + "n" * 100, "NeurIPS", "Main", "primary", 30, 90), _mk_cand("acl_main_" + "a" * 100, "ACL", "Main", "fallback", 100, 120)] + [_mk_cand(f"conf_ws_{i:02d}_" + "w" * 100, f"ConfWS {i}", "Workshop", "fallback", 140 + i * 2, 160 + i * 2, ov=5.5, sc_val=5) for i in range(45)]
    s7, d7 = _run_4mode("acl_main_fb", {"venue_type": "conference_top_tier", "target": tgt, "target_scorecard": {"venue_type": "conference_top_tier", "ratings": _ratings((6, 6, 6, 6, 7, 6))}, "candidate_venues": c7}, {"venue_type": "conference_top_tier", "ratings": _ratings((6, 6, 6, 6, 7, 6))}, tgt_venue="NeurIPS", extra_args=["--artifact-readiness", str(art5)])
    assert s7[0] == 0 and s7[2] == "RETARGETED_READY" and s7[3].startswith("conf_ws_00_") and s7[4].startswith("neurips_main_")
    assert any(v["venue_id"].startswith("acl_main_") for v in d7["compact_nodisk"]["venue_portfolio"]["disqualified_venues"])
