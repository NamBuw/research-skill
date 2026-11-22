# Research Scientist Agent Skill Suite

Portable, falsification-first AI/CS/CV/NLP research workflow for Codex, Claude Code, and Gemini CLI, organized as a **Hub-and-Spoke suite** (`research-scientist` parent orchestrator + 6 specialist sibling sub-skills).

See [parent orchestrator instructions](research-scientist/SKILL.md), [installation and multi-skill sync](research-scientist/INSTALL.md), [third-party license notices](research-scientist/THIRD_PARTY_NOTICES.md), [33-repo source landscape](research-scientist/references/repository-landscape.md), and [agent work division](research-scientist/references/agent-orchestration.md).

## Architecture: Hub-and-Spoke Suite & Core Guarantees

The suite uses **3-layer progressive disclosure (F20)**—compact YAML frontmatter, lean `<50`-line (`<900`-token; `22–41` lines actual) `SKILL.md` routers, and on-demand `references/`—with all shared Python CLI tools (`41` scripts) under `research-scientist/scripts/` and bundled MIT modules under `research-scientist/modules/` (zero script duplication in sub-skills). All 7 skills include `agents/openai.yaml` metadata for Codex discovery.

| Skill | Role | Core Capabilities & Gates |
|---|---|---|
| [`research-scientist`](research-scientist/SKILL.md) | **Parent Orchestrator** | Global zero-sycophancy & falsification-first laws, **Parsimony Gate (F19, "least is best")**, 6-spoke routing, zero-friction auto-builder (`build_research_inputs.py`), canonical lineage graph & Interactive Advisor (`project_state.py`), connected submission orchestrator (`evaluate_submission.py`), `--out` + `--compact` disk offloading (F20), `claim_audit.py`, `sync_skills.py` |
| [`research-precedent-corpus`](research-precedent-corpus/SKILL.md) | **Spoke 1: Retrieval & Corpus** | 9-source discovery (`search_papers.py`, `search_campaign.py`), 4-ID + bare-arXiv dedup, known-seed checks, co-citation graph, JATS/scite/retractions, PyMuPDF/OCR MinerU-V2 blocks, PaperQA2 BM25+MMR Q&A (`ABSTAIN` gate) |
| [`research-gap-rq-audit`](research-gap-rq-audit/SKILL.md) | **Spoke 2: Gap, RQ & Parsimony** | STORM/Co-STORM exploration (`storm_explorer.py` contradiction matrix, method×setting×metric×regime holes, failure-first & P4 isomorphic transfer leads), `gap_pipeline.py` (read-before-cite, cross-vocab kill-search, temporal cutoff, 5-role skeptic, 4 deep lenses F32, `gap_tier_ceiling`, scoop/resource feasibility, `code_prior_art`, 3–4 angle idea portfolio + 1–2d `killer_experiment`, `idea_seed_bundle`), engineering-vs-gap separation, **Parsimony/anti-inflation gate (F19)**, falsifiable RQ cards |
| [`research-experiment-coding`](research-experiment-coding/SKILL.md) | **Spoke 3: Coding & Rigor (F22)** | 4-phase root-cause debugging, TDD, verification-before-completion, PyTorch/leakage AST diagnostics, `repro` essentials, `rliable` IQM + stratified bootstrap 95% CIs, n-gram contamination checks, SHA-256 run receipts, post-experiment error-slice & HARKing-blocked pivot analysis (`analyze_experiment_outcome.py`) |
| [`research-novelty-venue`](research-novelty-venue/SKILL.md) | **Spoke 4: Novelty, Venue & Rebuttal (F22)** | Locator-verified /10 scorecards, `submission_readiness` calibration, `>=3` closest-work anchor (`--strict-related-panel`), `>=5` same-track accepted-panel novelty (PMLR/ACL/DBLP), cross-topic `venue_contribution_bar` + hard `rejected_below_venue_tier`, multi-venue `--portfolio` auto-retargeting, Scoring Engine v2 (venue profiles, ARR/NeurIPS/ICLR/Journal scales, `mode="idea"` Pareto, What-If ROI, `--revision-diff`, halo guard), `triage_reviews.py` (`mock-review`, `post-reject` H1–H17 + 2–4wk Venue B plan), connected `evaluate_submission.py`, 5 subfield presets (`--subfield-preset`), live CFP/fee capture, OpenReview/CVPR rebuttal (`check_rebuttal.py`) |
| [`research-paper-writing`](research-paper-writing/SKILL.md) | **Spoke 5: Writing, Figures & Preflight (F22)** | Humanizer §1–§26 + anti-sycophancy/padding/overlap lint, anti-fabrication & anti-grandiose method ledger + deep argument audits (`--audit-arguments`: claim-scope, 1-to-1 contributions, related-work differentiation), release-artifact license/PII/repro/secret/anonymization readiness (`check_artifact_readiness.py`), WCAG/grayscale/DPI/Type3 figure QA, double-blind anonymization, arXiv cleaner, BibTeX cap protection & online DOI check |
| [`research-user-report`](research-user-report/SKILL.md) | **Spoke 6: Multilingual PDF Report (F18)** | Concise, plain-language executive LaTeX-to-PDF reports auto-matching user input language (`vi`, `en`, etc.) with verified intact UTF-8/Vietnamese diacritics, `--strict` conciseness linting, and F23–F25 `submission_readiness`, `venue_contribution_bar`, tier-rejection & portfolio verdicts |

### Cross-Cutting Guardrails (F1, F18, F19, F20)
- **Zero Sycophancy & Falsification-First (F1):** Explicitly bans flattery and praise sandwiches; attacks every claim across prior art, engineering defects, missing receipts, grandiose method rebranding, and overcomplication before acknowledging merit.
- **Parsimony Gate — "Least Is Best" (F19):** Rejects dramatized problem inflation and complex multi-module proposals lacking a concrete `simplest_alternative` and single-component ablation justification over the simplest strong baseline.
- **Token-Frugal Context Efficiency (F20):** Scripts offload bulky payloads to disk via `--out` and return bounded `<4KB` `--compact` JSON summaries with file pointers.
- **Concise Multilingual LaTeX-PDF Reports (F18):** `report_latex_pdf.py` compiles crisp verdict-first PDFs in the user's language (`xelatex` → `lualatex` → `pdflatex`) and checks extracted PDF text for intact diacritics via PyMuPDF.

## Quickstart & Local CLI Helpers

Install or sync all 7 skills to Codex, Claude Code, and Gemini CLI, then audit the suite:

```bash
python3 research-scientist/scripts/sync_skills.py --dry-run --compact
python3 research-scientist/scripts/sync_skills.py --suite-root . --check --compact --out /tmp/sync-check.json
python3 research-scientist/scripts/claim_audit.py --suite-root . --readme README.md --compact
python3 research-scientist/scripts/claim_audit.py --root research-scientist --readme README.md --compact
```

### Lock an Entire Research Workspace / Chat Session

Copy the reusable workspace rules and lifecycle hooks into any target research project directory (never overwrites existing files):

```bash
cp -rn templates/session-lock/. /path/to/your-research-project/
```

See [session-lock templates](templates/session-lock/README.md) for `AGENTS.md`, `CLAUDE.md`, `.agents/hooks.json`, and `SessionStart`/`Stop` provenance guard details.

Run individual pipeline tools from `research-scientist/`:

```bash
# 0. Auto-builder & canonical project-state lifecycle (F29, F31)
python3 scripts/build_research_inputs.py --topic "your topic" --target-venue "NeurIPS" --subfield-preset nlp_llm --out-dir ./inputs --out build_inputs.json --compact
python3 scripts/project_state.py --state project_state.json --init --project-id proj-001 --subfield-preset nlp_llm --advise --compact

# 1. Precedent search, citation graph, fulltext, PDF/OCR blocks & local corpus Q&A
python3 scripts/search_papers.py "your topic and mechanism" --size 20 --pages 2 --compact
python3 scripts/search_papers.py "your topic and mechanism" --known-doi 10.48550/arxiv.1609.02907 --known-source-id arxiv=1609.02907
python3 scripts/search_campaign.py references/search-campaign.example.json --out campaign.json --compact
python3 scripts/resolve_fulltext.py 10.48550/arxiv.1609.02907 --download-dir /path/to/reading-workspace
python3 scripts/citation_trails.py W2741809807 --pages 2 --page-size 50 --out trails.json
python3 scripts/citation_graph.py --seeds W100,W200 --direction both --top 20 --out graph.json --compact
python3 scripts/fulltext_mining.py --dois 10.48550/arxiv.1609.02907 --out fulltext.json --compact
python3 scripts/extract_pdf_blocks.py /path/to/paper.pdf --out /path/to/paper.blocks.json --tables --ocr --compact
python3 scripts/local_evidence.py --question "mechanism or outcome" --inputs /path/to/extracted/papers --limit 20 --compact
python3 scripts/check_evidence_map.py /path/to/evidence-map.json

# 2. STORM exploration, gap pipeline, RQ, experiment-bug & post-experiment diagnostics
python3 scripts/storm_explorer.py --topic "your topic" --corpus corpus.json --failure-cases failure_cases.json --target-regime "zero-shot OOD" --out storm.json --compact
python3 scripts/gap_pipeline.py --topic "your topic" --corpus corpus.json --digests digests.json --candidates candidates.json --target-venue-tier q1_or_tier_a --subfield-preset nlp_llm --strict-triage --seed-bundle-out idea_seed_bundle.json --out gap_out.json --compact
python3 scripts/check_gap_record.py /path/to/gap-record.json --evidence-dir /path/to/blocks
python3 scripts/check_gap_campaign.py /path/to/gap-record.json campaign.json
python3 scripts/check_question_card.py /path/to/question-card.json
python3 scripts/check_ai_cs_research_plan.py /path/to/gap-record.json /path/to/question-card.json /path/to/ai-cs-experiment-plan.json --campaign campaign.json
python3 scripts/check_engineering_diagnostics.py --code-dir /path/to/repo --splits /path/to/splits.csv --metrics /path/to/metrics.json --compact
python3 scripts/audit_alignment.py /path/to/features.csv /path/to/labels.csv --compact
python3 scripts/check_experiment_manifest.py /path/to/experiment-manifest.json --verify-files --compact
python3 scripts/check_experiment_rigor.py repro /path/to/repo --strict --compact
python3 scripts/check_experiment_rigor.py rliable /path/to/scores.json --strict --compact
python3 scripts/check_experiment_rigor.py contamination --train train.jsonl --eval eval.jsonl --compact
python3 scripts/analyze_experiment_outcome.py --question-card /path/to/question-card.json --outcomes /path/to/outcomes.json --manifest /path/to/experiment-manifest.json --verify-files --export-failure-cases failure_cases.json --out outcome.json --compact

# 3. /10 scoring, portfolio, mock/post-reject triage, connected evaluation & rebuttal checks
python3 scripts/score_math.py /path/to/score-input.json --venue-type conference_top_tier --mode paper --subfield-preset nlp_llm --what-if
python3 scripts/compare_scorecards.py /path/to/scorecards.json --target-id target_paper --strict-related-panel --min-related 3 --venue-type conference_top_tier --sources-dir /path/to/sources --out scorecards_out.json --compact
python3 scripts/compare_scorecards.py /path/to/ideas.json --mode idea --goal high_risk_q1_top_tier --idea-seed-bundle idea_seed_bundle.json --require-idea-portfolio --require-pre-mortem --out idea_rank.json --compact
python3 scripts/compare_scorecards.py --revision-diff /path/to/v1_scorecards.json /path/to/v2_scorecards.json --out rev_diff.json --compact
python3 scripts/venue_leads.py "specific contribution and field" --page-size 50 --pages 2 --compact
python3 scripts/venue_panel_collector.py --source pmlr --venue-id v235 --limit 5 --out panel.json --compact
python3 scripts/capture_venue_sources.py /path/to/venue-dossier.json --out venue-sources.json --compact
python3 scripts/check_venue_sources.py /path/to/venue-dossier.json venue-sources.json --compact
python3 scripts/check_venue_plan.py /path/to/venue-dossier.json --sources venue-sources.json --compact
python3 scripts/compare_venue_novelty.py /path/to/portfolio.json --portfolio --require-panels --min-venues 3 --target-overall 6.35 --sources-dir /path/to/sources --out portfolio_out.json --compact
python3 scripts/triage_reviews.py mock-review --scorecard scorecards_out.json --venue-novelty portfolio_out.json --scale iclr_1_10 --subfield-preset nlp_llm --strict --out mock_review.json --compact
python3 scripts/triage_reviews.py post-reject --reviews /path/to/reviews.json --venue-b /path/to/venue_b.json --weeks 3 --subfield-preset nlp_llm --strict --out post_reject.json --compact
python3 scripts/evaluate_submission.py --scorecard scorecards_out.json --venue-novelty portfolio_out.json --artifact-readiness readiness.json --subfield-preset nlp_llm --out submission_eval.json --compact
python3 scripts/check_rebuttal.py coverage /path/to/points.md /path/to/rebuttal.md --strict --compact

# 4. Paper writing, argument & artifact readiness audits, figure QA, preflight & PDF report
python3 scripts/humanizer_lint.py /path/to/manuscript.md --strict --compact
python3 scripts/check_manuscript_ledger.py --ledger /path/to/manuscript-ledger.json --manuscript /path/to/manuscript.md --sources-dir /path/to/sources --audit-arguments --scorecards scorecards_out.json --target-id target_paper --out ledger_out.json --compact
python3 scripts/check_artifact_readiness.py --repo-dir /path/to/repo --anonymous --strict --out readiness.json --compact
python3 scripts/check_figure_qa.py figure /path/to/figures --strict --compact
python3 scripts/check_submission_preflight.py anonymize /path/to/paper.tex --strict --compact
python3 scripts/check_submission_preflight.py arxiv-clean /path/to/tex_dir --strip-comments-out /path/to/clean-arxiv --prune-unused --strict --compact
python3 scripts/check_submission_preflight.py bibtex /path/to/refs.bib --tex /path/to/paper.tex --protect-caps --verify-online --compact
python3 scripts/report_latex_pdf.py --input /path/to/findings.json --out /path/to/report.pdf --lang auto --strict --compact
python3 modules/kdense-scientific-writing/scripts/scaffold_manuscript.py --output-dir ./draft-workspace --document-id local-draft --study-design observational
python3 modules/researchradar/problem-statement-finder/scripts/radar.py check
```

Example DOIs, OpenAlex IDs, and JSON fixtures are syntax examples only; replace them with verified run inputs. An absent known seed means the executed query or source coverage needs repair—never proof that prior work is absent.

## Built-In Capabilities & Environment Limits

| Capability | Built-In Implementation | Required External / Environment / Expert Limits |
|---|---|---|
| Auto-builder, lifecycle & Interactive Advisor | Zero-friction input orchestrator (`build_research_inputs.py`) turning topics or local PDF/LaTeX into verified scaffolds with strict null/unverified provenance, plus canonical `project_state.json` lineage graph & Interactive Advisor (`project_state.py`) | Offline mode uses local/mock files; live collection requires network access and verified user constraints; generated scaffolds never invent ratings or claims |
| Literature & citation graph | 9-source discovery (Semantic Scholar, OpenAlex, Crossref, Europe PMC, arXiv, PubMed, ACL Anthology, HuggingFace Papers, DBLP) with 429 backoff, 4-ID + bare-arXiv dedup, known-seed positive controls, co-citation clustering (`citation_graph.py`), JATS sections, scite tallies & retractions (`fulltext_mining.py`) | Supply `S2_API_KEY` via runtime env for higher Semantic Scholar quota; DBLP may return HTTP `202` Anubis challenges (`bot_blocked`); ACL keyword queries use Crossref deposit metadata (often missing abstracts); primary full-text reading remains mandatory |
| PDF/OCR & corpus Q&A | PyMuPDF + optional `pdfplumber` (`--tables`) + optional `tesseract` (`--ocr`) emitting MinerU Content List V2 JSON with Shannon entropy gating (`extract_pdf_blocks.py`); stemmed BM25 + MMR + `min_studies` `ABSTAIN` gate (`local_evidence.py`) | Optional external `mineru` CLI (`--use-mineru`) and user-hosted `khoj` server (`--khoj-url`) are not bundled; visual verification of complex tables/equations remains required |
| Gap, RQ, parsimony & experiment rigor | STORM explorer (contradiction matrix, coverage holes, failure-first, P4 isomorphic transfers), `gap_pipeline.py` (4 deep lenses F32, tier-ceiling/scoop/resource/`code_prior_art` triage, 3–4 angle idea portfolio + `killer_experiment`, `idea_seed_bundle`), engineering AST/split checks (`check_engineering_diagnostics.py`), `repro`/`rliable`/`contamination` (`check_experiment_rigor.py`), SHA-256 run receipts & post-experiment HARKing-blocked pivot analysis (`analyze_experiment_outcome.py`) | Actual ML training execution runs externally; deterministic checks verify receipts and structural contracts, not causal truth |
| /10 scoring, portfolio, triage & connected venue pipeline | Guarded 6-dim scorecards (`submission_readiness`, `>=3` closest-work anchor, cross-topic `venue_contribution_bar` + `rejected_below_venue_tier`), Scoring Engine v2 (venue profiles, ARR/NeurIPS/ICLR/Journal scales, `mode="idea"` Pareto, What-If ROI, `--revision-diff`, halo guard), `>=3–5` venue `--portfolio`, `triage_reviews.py` (`mock-review`, `post-reject` H1–H17 + 2–4wk Venue B plan), 5 subfield presets (`nlp_llm`, `cv_multimodal`, `ml_theory`, `ai_systems`, `speech_audio`), connected `evaluate_submission.py`, PMLR/ACL/DBLP panels, CFP/fee snapshotter & rebuttal checks | Live HTTPS access needed for fresh CFP/panel fetches; JS-rendered fee portals still require manual inspection; scoring tools never invent `%` acceptance odds and final track/fit judgment rests with authors |
| Writing, artifact readiness, figures, preflight & PDF report | Humanizer §1–§26 + anti-sycophancy/padding/overlap lint, method-lineage/numeric ledger & argument audits (`--audit-arguments`), repo license/PII/repro/secret/anonymization readiness (`check_artifact_readiness.py`), WCAG/grayscale/DPI/Type3 figure QA, double-blind anonymization, arXiv cleaner (`--prune-unused` + unsafe-symlink exclusion), BibTeX cap/DOI check (`--verify-online`), multilingual LaTeX-to-PDF generator (`report_latex_pdf.py`) | PDF compilation requires a local TeX engine (`xelatex`, `lualatex`, or `pdflatex` with UTF-8/T5 `vntex` support for Vietnamese) plus `PyMuPDF` (`fitz`) for text/diacritic verification |

## Upstream Pipeline Map & 33-Repo Triage Summary (Include / Absorb / Reject)

Only **MIT** and **Apache-2.0** repositories are bundled or adapted. Repositories under **AGPL-3.0** (`Khoj`), **Custom RAILS** (`The AI Scientist`), **Apache-2.0 + Commercial/Attribution Additional Terms** (`MinerU`), **CC BY-NC 4.0**, or **no license** (`Lit-Gap`, `ResearchAgent`, `Awesome-Conference-Skills`) are **never copied**—where used, they appear strictly via clean-room behavioral specs or optional external CLI/HTTP interfaces. See [third-party notices](research-scientist/THIRD_PARTY_NOTICES.md) and the full [33-repo code-reading landscape](research-scientist/references/repository-landscape.md).

### Core Research Pipeline Attributions

| Upstream Source (License) | Mechanism Integrated or Clean-Room Boundary | Local Implementation |
|---|---|---|
| [GPT Researcher](https://github.com/assafelovic/gpt-researcher) (`Apache-2.0`) | Plural stemmer, stopwords, lexical BM25; multi-lane query curation workflow | [local_evidence.py](research-scientist/scripts/local_evidence.py), [research-workflow.md](research-scientist/references/research-workflow.md) |
| [Stanford STORM / Co-STORM](https://github.com/stanford-oval/storm) (`MIT`) | Multi-perspective question planning, deduplicated `InformationTable`, outline & uncovered branches | [storm_explorer.py](research-scientist/scripts/storm_explorer.py), [document-evidence.md](research-scientist/references/document-evidence.md) |
| [PaperQA2](https://github.com/Future-House/paper-qa) (`Apache-2.0`) | `clean_invalid_unicode`, Shannon entropy gate, overlapping chunks, MMR, `ABSTAIN` gate, retractions | [extract_pdf_blocks.py](research-scientist/scripts/extract_pdf_blocks.py), [local_evidence.py](research-scientist/scripts/local_evidence.py), [fulltext_mining.py](research-scientist/scripts/fulltext_mining.py) |
| [The AI Scientist](https://github.com/SakanaAI/AI-Scientist) (`Custom RAILS` — **not copied**) | Clean-room figure/caption detection + `visual_check_required`; strict provenance & scorecard gates | [extract_pdf_blocks.py](research-scientist/scripts/extract_pdf_blocks.py), [check_experiment_manifest.py](research-scientist/scripts/check_experiment_manifest.py) |
| [Perplexica / Vane](https://github.com/ItzCrazyKns/Vane) (`MIT`) | `speed`/`balanced`/`quality` mode routing & 3-query fan-out (without silent `similarity=1.0` fallback) | [search_papers.py](research-scientist/scripts/search_papers.py), [precedent-search.md](research-scientist/references/precedent-search.md) |
| [MinerU](https://github.com/opendatalab/MinerU) (`Apache-2.0 + Add. Terms` — **not copied**) | Clean-room PyMuPDF/`pdfplumber`/`tesseract` V2 JSON blocks; optional external `mineru` CLI wrapper | [extract_pdf_blocks.py](research-scientist/scripts/extract_pdf_blocks.py) (`--use-mineru`), [local_evidence.py](research-scientist/scripts/local_evidence.py) |
| [Khoj](https://github.com/khoj-ai/khoj) (`AGPL-3.0` — **not copied**) | Clean-room stdlib `urllib.request` HTTP client for optional user-hosted server | [local_evidence.py](research-scientist/scripts/local_evidence.py) (`--khoj-url`), [document-evidence.md](research-scientist/references/document-evidence.md) |
| [K-Dense Scientific Agent Skills](https://github.com/K-Dense-AI/scientific-agent-skills) (`MIT`) | 5 bundled offline/citation suites (`modules/kdense-*`) + `palette_audit.py` WCAG/CIE L* logic + GPU/stats checks | [check_figure_qa.py](research-scientist/scripts/check_figure_qa.py), [writing/scoring details](research-scientist/references/writing-score-venue-source-details.md) |
| [Humanizer](https://github.com/blader/humanizer) (`MIT`) | Bundled 26-pattern catalog + runnable AI-tell, sycophancy & overlap linter | [humanizer_lint.py](research-scientist/scripts/humanizer_lint.py), [modules/humanizer/VENDOR.md](research-scientist/modules/humanizer/VENDOR.md) |
| [ResearchRadar](https://github.com/diptiman-mohanta/ResearchRadar) (`MIT`) | Bundled 6-skill suite (`radar.py`) + plural-boundary & quote verification | [gap_pipeline.py](research-scientist/scripts/gap_pipeline.py), [modules/researchradar/VENDOR.md](research-scientist/modules/researchradar/VENDOR.md) |
| [Stanford AI-Researcher](https://github.com/NoviScl/AI-Researcher) (`MIT`), [Good Question](https://github.com/Rimagination/good-question) (`MIT`), [CKM-HypoGen](https://github.com/TaoJinkai/ckm-hypogen) (`MIT`), [SciPIP](https://github.com/cheerss/SciPIP) (`MIT`), [grounded-research-ideation](https://github.com/Hopotta/grounded-research-ideation) (`MIT`), [SGHA](https://github.com/SGHA-Research/sgha) (`Apache-2.0`) | Token-Jaccard dedup, pressure cases & rival RQ cards, temporal-cutoff checks, `UnionFind` `CoCite` matrix, read-before-cite gate, 5-role critic & transitive 4-ID dedup | [gap_pipeline.py](research-scientist/scripts/gap_pipeline.py), [citation_graph.py](research-scientist/scripts/citation_graph.py), [check_question_card.py](research-scientist/scripts/check_question_card.py), [gap-rq-source-details.md](research-scientist/references/gap-rq-source-details.md) |
| [Lit-Gap](https://github.com/saulmcphd/lit-gap) (`No License` — **not copied**), [ResearchAgent](https://github.com/JinheonBaek/ResearchAgent) (`No License` — **not copied**), [IRIS](https://github.com/Anikethh/IRIS-Interactive-Research-Ideation-System) (**not copied**) | Clean-room behavioral specifications: `require_abstract=False` kill-search, JATS `<sec>` mining, rejected-hypothesis feedback memory | [search_papers.py](research-scientist/scripts/search_papers.py), [fulltext_mining.py](research-scientist/scripts/fulltext_mining.py), [gap_pipeline.py](research-scientist/scripts/gap_pipeline.py) (`--feedback-store`) |

### 33-Repo Agent-Skill Scout & Triage Summary (M7/M5)

Full stars, SPDX licenses, and per-repo rationales are recorded in [repository-landscape.md](research-scientist/references/repository-landscape.md).

- **`INCLUDE_AS_SUBSKILL` (1 repo — co-anchor of `research-experiment-coding`):** `obra/superpowers` (`MIT`, 4-phase root-cause debugging, Iron Law verification-before-completion, red-green TDD).
- **`ABSORB_INTO_EXISTING_SUBSKILL` (15 repos — cherry-picked into parent or 6 spokes):**
  - *Context & governance (`research-scientist`):* `muratcankoylan/Agent-Skills-for-Context-Engineering` (`MIT`), `tw93/Waza` (`MIT`), `affaan-m/ECC` (`MIT`, strategic compaction + PyTorch/MLE rules).
  - *Experiment coding (`research-experiment-coding`):* `ShaishavMaisuria/research-paper-lifecycle-skills` (`Apache-2.0`, `repro` + metrics/repo checks), `google-research/rliable` (`Apache-2.0`, IQM + stratified bootstrap CIs), `K-Dense-AI/scientific-agent-skills` (`MIT`, GPU/stats rules).
  - *Novelty & rebuttal (`research-novelty-venue`):* `ShaishavMaisuria/research-paper-lifecycle-skills` (`Apache-2.0`, CFP/DBLP + rebuttal budget/coverage), `chtc66/academic-skills` (`MIT`, anti-fabrication rebuttal), `xf686/Meet-Reviewer-2` (`MIT`, H1–H17 fairness firewall in `check_rebuttal.py` & `scripts/triage_reviews.py`).
  - *Writing, figures & preflight (`research-paper-writing`):* `Haojae/scipilot-figure-skill` (`MIT`), `K-Dense-AI/scientific-agent-skills` (`MIT`, WCAG/CIE L* palette audit), `ShaishavMaisuria/research-paper-lifecycle-skills` (`Apache-2.0`, anonymize + preflight), `google-research/arxiv-latex-cleaner` (`Apache-2.0`), `yuchenlin/rebiber` (`MIT`), `amos689/paper-preflight` (`MIT`), `Altman-conquer/bibtex-verifier` (`MIT`), `Master-cai/Research-Paper-Writing-Skills` (`MIT`), `zLanqing/codex-claude-academic-skills` (`MIT`).
  - *Note on `KalarisLabs/research-agent-skills` (`MIT`):* `claim_audit.py` was ported in M1; the remaining 280+ general catalog was rejected to prevent frontmatter bloat.
  - *Note on `yilaai/paper-quality-filter` (`MIT`, snapshot `679cdf3`):* Two-stage venue normalization & `S`/`A`/`B`/`C`/`Unknown` advisory classification rules were ported into `venue_leads.py` & `compare_venue_novelty.py`; raw `journal_scores.json` (Clarivate JCR/CAS metrics) is never redistributed (optional local `--quality-refs-dir` only) and static ranking is rejected as a substitute for live CFP + accepted panels.
- **`REJECT` (19 repos — 17 from the 33-repo matrix + 2 prompt-only overlap catalogs, excluded for integrity, license, hallucination, or bloat):**
  - *License blocks:* `Imbad0202/academic-research-skills` (`CC BY-NC 4.0`), `CHB-learner/Awesome-Conference-Skills` (`None`).
  - *Scientific-integrity / auditability conflicts:* `Adkid-Zephyr/anti-defensive-writing-Skill` (instructs hiding weaknesses), `KINGSTAR-OMEGA/claude-token-optimizer` (strips explanatory provenance).
  - *Hallucination / external-API / domain-mismatch / redundancy:* `PaperBanana` (`dwzhu-pku` & `llmsresearch`), `K-Dense-AI/claude-scientific-writer`, `TingxiYu/academic-figure-skill`, `lishix520/academic-paper-skills`, `appautomaton/latex-arxiv-SKILL`, `WenyuChiou/academic-writing-skills`, `rand/cc-polymath`, `KalarisLabs/research-agent-skills` (280+ catalog), `xingtaxueshu/literature-review-skills`, `msimchowitz/writing-skills`, `stephenturner/skill-research-question-validator`, `yilaai/paper-quality-filter` (`journal_scores.json` & static ranking), `JosephElvisMaman1/ResearchPilot-Skills`, `Research-Equality/RE-research-design` (`RE-idea-generation`).

## Evaluate and Contribute

See [evaluation limits](research-scientist/references/quality-evaluation.md) and [development checks](evaluation/forward-checks.md). Structural tests and synthetic fixtures verify contracts and failure modes; they are not proof of universal scientific correctness. Report issues with exact commit hash, accessible sources, executed commands, and verified precedent or CFP evidence (removing any API keys or private data).
