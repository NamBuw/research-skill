# Third-Party Notices and License Attribution

This document records third-party software, skill suites, adapted algorithms, and explicit exclusion boundaries for the `research-scientist` Hub-and-Spoke suite (`research-scientist/` and its six sibling specialist sub-skills: `research-precedent-corpus`, `research-gap-rq-audit`, `research-experiment-coding`, `research-novelty-venue`, `research-paper-writing`, and `research-user-report`).

**License boundary policy:** Only **MIT** and **Apache-2.0** licensed components are bundled or adapted. Repositories under **AGPL-3.0** (`khoj-ai/khoj`), **Custom RAILS** (`SakanaAI/AI-Scientist`), **Apache-2.0 with Commercial/Attribution Additional Terms** (`opendatalab/MinerU`), **CC BY-NC 4.0** (`Imbad0202/academic-research-skills`), or **no license / unlicensed snapshots** (`Lit-Gap`, `ResearchAgent`, `Awesome-Conference-Skills`) are **never copied** into this repository.

---

## 1. Bundled MIT Modules (`research-scientist/modules/`)

Each directory below contains an explicit `VENDOR.md` and `LICENSE.md` preserving upstream copyright and MIT license terms. Upstream `SKILL.md` files are renamed to `UPSTREAM_SKILL.md` so `research-scientist/SKILL.md` and its 6 sub-skills remain the sole agent entrypoints.

| Module Directory | Upstream Project & URL | Snapshot | SPDX License | Copyright Notice | Bundled Scope |
|---|---|---|---|---|---|
| `modules/humanizer/` | [blader/humanizer](https://github.com/blader/humanizer) | `a32f24407364c74c812b43c15926d638bee1e072` | `MIT` | Copyright (c) 2025 Siqi Chen | 26-pattern AI-writing taxonomy (`UPSTREAM_SKILL.md`) |
| `modules/kdense-scientific-writing/` | [K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills) (`skills/scientific-writing`) | `ec59a29a03d5c40f73ab40878df04860bc00e876` | `MIT` | Copyright (c) 2025 K-Dense Inc. | Full offline stdlib manuscript, claim-hash, consistency, reference, authorship & lint toolkit |
| `modules/kdense-hypothesis-generation/` | [K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills) (`skills/hypothesis-generation`) | `ec59a29a03d5c40f73ab40878df04860bc00e876` | `MIT` | Copyright (c) 2025 K-Dense Inc. | Full offline stdlib hypothesis schema, operationalization, rival matrix, causal lint & falsification scripts |
| `modules/kdense-peer-review/` | [K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills) (`skills/peer-review`) | `ec59a29a03d5c40f73ab40878df04860bc00e876` | `MIT` | Copyright (c) 2025 K-Dense Inc. | Full offline stdlib review intake, scaffold, lint, claim-evidence, stats-repro & citation scripts |
| `modules/kdense-scholar-evaluation/` | [K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills) (`skills/scholar-evaluation`) | `ec59a29a03d5c40f73ab40878df04860bc00e876` | `MIT` | Copyright (c) 2025 K-Dense Inc. | Full offline stdlib rubric, scoring, traceability, agreement, sensitivity & process scripts |
| `modules/kdense-literature-review/` | [K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills) (`skills/literature-review`) | `ec59a29a03d5c40f73ab40878df04860bc00e876` | `MIT` | Copyright (c) 2025 K-Dense Inc. | Curated subset: `search_databases.py`, `verify_citations.py` (stdlib `urllib.request` fallback added), references (`generate_pdf.py` & `generate_schematic*.py` excluded) |
| `modules/researchradar/` | [diptiman-mohanta/ResearchRadar](https://github.com/diptiman-mohanta/ResearchRadar) | `c47d8b1` | `MIT` | Copyright (c) 2026 Diptiman Mohanta | Six `.claude/skills` components including `problem-statement-finder/scripts/radar.py` |

---

## 2. Adapted MIT and Apache-2.0 Projects (`research-scientist/scripts/` and Sub-Skills)

### 2.1 Apache-2.0 Attributions & Required Notices

1. **`ShaishavMaisuria/research-paper-lifecycle-skills`** — <https://github.com/ShaishavMaisuria/research-paper-lifecycle-skills>
   - **License:** Apache License 2.0 (`Apache-2.0`), Copyright 2026 Shaishav Maisuria (commit `cf30d6452cc6fd0570dd760eb65696f4a3485398`).
   - **NOTICE:** *"This product includes research-paper lifecycle agent skills originally developed by Shaishav Maisuria."*
   - **Adapted components:**
     - `skills/parse-cfp/scripts/fetch_cfp.py` & `skills/select-venue/scripts/dblp_venue_lookup.py` → `scripts/capture_venue_sources.py` (with added redirect-chain, stale-year, and JS-SPA detection); verification conventions → `scripts/check_venue_plan.py`, `scripts/check_venue_sources.py`.
     - `polite_http.py`, `dblp_search.py`, `resolve_papers.py`, `citation_graph.py` → `scripts/search_papers.py`, `scripts/citation_trails.py`, `scripts/resolve_fulltext.py`, `scripts/citation_graph.py`.
     - `texprose.py` → `scripts/humanizer_lint.py` (LaTeX/Markdown masking, hedging/booster/rhythm rules, 8-gram overlap).
     - `skills/verify-results/scripts/{compare_metrics.py,audit_repo.py}` → `scripts/check_experiment_manifest.py`.
     - `skills/test-research-code/scripts/repro_check.py` → `scripts/check_experiment_rigor.py` (`repro`).
     - `skills/write-rebuttal/scripts/{check_budget.py,check_coverage.py}` → `scripts/check_rebuttal.py` (hardened with per-point `R1.1`/`AC.1` evidence-anchor & per-claim new-experiment non-fabrication checks).
     - `skills/anonymize-paper/scripts/scan_anonymization.py` & `skills/preflight-check/scripts/run_preflight.py` → `scripts/check_submission_preflight.py`.

2. **`Future-House/paper-qa` (PaperQA2)** — <https://github.com/Future-House/paper-qa>
   - **License:** Apache License 2.0 (`Apache-2.0`).
   - **Adapted components:** `clean_invalid_unicode`, Shannon entropy text gate (`maybe_is_text`), overlapping page-aware chunking, citation-keyed context packing, hard `ABSTAIN` gate on insufficient studies/evidence, and Crossref/Retraction checks in `scripts/extract_pdf_blocks.py`, `scripts/local_evidence.py`, and `scripts/fulltext_mining.py`.

3. **`assafelovic/gpt-researcher` (GPT Researcher)** — <https://github.com/assafelovic/gpt-researcher>
   - **License:** Apache License 2.0 (`Apache-2.0`).
   - **Adapted components:** Lightweight English plural stemming (`_stem`), stopword filtering (`_STOPWORDS`), and lexical BM25 scoring in `scripts/local_evidence.py`, plus multi-lane query decomposition and source-curation workflow architecture.

4. **`SGHA` (`SGHA-Research/sgha` / `Azeem2002/SGHA`)** — <https://github.com/SGHA-Research/sgha>
   - **License:** Apache License 2.0 (`Apache-2.0`).
   - **Adapted components:** Multi-key transitive record deduplication (`search_papers.py`), max-ratio normalized MMR reranking (`local_evidence.py`), and 5-role skeptic/critic verification + `counterevidence_linking` (`gap_pipeline.py`).

5. **`google-research/rliable`** — <https://github.com/google-research/rliable>
   - **License:** Apache License 2.0 (`Apache-2.0`).
   - **Adapted components:** Pure-stdlib implementation of 25% trimmed Interquartile Mean (IQM), stratified bootstrap 95% CIs, optimality gap, and probability of improvement `P(X > Y)` in `scripts/check_experiment_rigor.py` (`rliable`).

6. **`google-research/arxiv-latex-cleaner`** — <https://github.com/google-research/arxiv-latex-cleaner>
   - **License:** Apache License 2.0 (`Apache-2.0`).
   - **Adapted components:** `%` comment stripping (preserving `\%`), unused `.tex`/figure pruning (`arxiv-clean --prune-unused`), unsafe-symlink exclusion, and oversized image checks in `scripts/check_submission_preflight.py` (`arxiv-clean`).

### 2.2 MIT Attributions

| Project & URL | SPDX License | Adapted / Integrated Capability | Local Target |
|---|---|---|---|
| [KalarisLabs/research-agent-skills](https://github.com/KalarisLabs/research-agent-skills) | `MIT` (Copyright (c) 2026 Kalaris Labs) | `tools/claim_audit.py` & `tools/common.py` adapted for pure-stdlib AST flag checks, symlink containment & multi-skill `--suite-root` | `scripts/claim_audit.py` |
| [blader/humanizer](https://github.com/blader/humanizer) | `MIT` (Copyright (c) 2025 Siqi Chen) | §1–§26 AI-tell taxonomy, cluster philosophy, quotation guards, claim-preservation rules | `scripts/humanizer_lint.py`, `modules/humanizer/` |
| [diptiman-mohanta/ResearchRadar](https://github.com/diptiman-mohanta/ResearchRadar) | `MIT` (Copyright (c) 2026 Diptiman Mohanta) | Whole-word plural-boundary matching, limitation separation, exact-quote verification | `scripts/gap_pipeline.py`, `scripts/check_gap_record.py`, `modules/researchradar/` |
| [stanford-oval/storm](https://github.com/stanford-oval/storm) (Stanford STORM / Co-STORM) | `MIT` | Multi-perspective question planning, deduplicated `InformationTable`, hierarchical outline, `uncovered_branches` | `scripts/storm_explorer.py` |
| [ItzCrazyKns/Vane](https://github.com/ItzCrazyKns/Vane) (Perplexica / Vane) | `MIT` | `speed`/`balanced`/`quality` mode routing and 3-query fan-out (explicitly rejecting silent `similarity=1.0` fallback) | `scripts/search_papers.py` |
| [cheerss/SciPIP](https://github.com/cheerss/SciPIP) | `MIT` | `UnionFind`, complete-linkage `can_merge`, symmetric `CoCite` matrix, cluster-diverse selection | `scripts/citation_graph.py` |
| [Hopotta/grounded-research-ideation](https://github.com/Hopotta/grounded-research-ideation) | `MIT` | Read-before-cite digest gate & dual-regime (`same_problem` vs `cross_setting_analogy`) coverage checks | `scripts/gap_pipeline.py` |
| [TaoJinkai/ckm-hypogen](https://github.com/TaoJinkai/ckm-hypogen) | `MIT` | Temporal cutoff leak detection (`DROP_TEMPORAL_LEAK`) and hindsight closure checks | `scripts/gap_pipeline.py` |
| [NoviScl/AI-Researcher](https://github.com/NoviScl/AI-Researcher) (Stanford AI-Researcher) | `MIT` | Stopword-filtered token-Jaccard deduplication (`DROP_DUPLICATE`) & experiment-plan gating | `scripts/gap_pipeline.py`, `scripts/check_ai_cs_research_plan.py` |
| [Rimagination/good-question](https://github.com/Rimagination/good-question) (Good Question) | `MIT` | Information-sufficiency gate, pressure cases, Platt Strong Inference RQ cards | `references/good-question-pressure-cases.md`, `scripts/check_question_card.py` |
| [obra/superpowers](https://github.com/obra/superpowers) | `MIT` | 4-phase root-cause debugging, Iron Law verification-before-completion, red-green TDD | `research-experiment-coding/` |
| [affaan-m/ECC](https://github.com/affaan-m/ECC) (`everything-claude-code`) | `MIT` | PyTorch device/seed/shape hygiene, MLE data-contract/leakage rules, verification loop, strategic compaction | `research-experiment-coding/`, `research-scientist/` |
| [muratcankoylan/Agent-Skills-for-Context-Engineering](https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering) | `MIT` | 3-layer progressive disclosure, filesystem offloading (`--out`/`--compact`), observation masking, anchored handoffs | `research-scientist/` (cross-cutting) |
| [tw93/Waza](https://github.com/tw93/Waza) | `MIT` | Read-only vs write authorization contract, completion ledger, symlink-escape & secret hygiene checks | `research-scientist/SKILL.md`, `scripts/claim_audit.py` |
| [K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills) | `MIT` (Copyright (c) 2025 K-Dense Inc.) | `palette_audit.py` WCAG + CIE L* grayscale rules; statistical assumption checks & GPU benchmarking parity | `scripts/check_figure_qa.py`, `research-experiment-coding/` |
| [Haojae/scipilot-figure-skill](https://github.com/Haojae/scipilot-figure-skill) | `MIT` | Figure & plotting-script QA rules (blocks JPEG, Type3 fonts, rainbow colormaps, low DPI; `pdf.fonttype=42`) | `scripts/check_figure_qa.py` |
| [yuchenlin/rebiber](https://github.com/yuchenlin/rebiber) | `MIT` | `protect_title_caps` BibTeX acronym preservation (`BERT`, `ResNet`, `3D`) without `{{...}}` | `scripts/check_submission_preflight.py` |
| [amos689/paper-preflight](https://github.com/amos689/paper-preflight) & [Altman-conquer/bibtex-verifier](https://github.com/Altman-conquer/bibtex-verifier) | `MIT` | Deterministic BibTeX hygiene & online Crossref/arXiv/OpenAlex DOI field verification (`--verify-online` with `eprint` fallback) | `scripts/check_submission_preflight.py` |
| [Master-cai/Research-Paper-Writing-Skills](https://github.com/Master-cai/Research-Paper-Writing-Skills) | `MIT` | Reverse outlining (one message per paragraph) & module motivation triad | `research-paper-writing/` |
| [zLanqing/codex-claude-academic-skills](https://github.com/zLanqing/codex-claude-academic-skills) | `MIT` | 7 late-stage compression patterns & metric-backed anti-vagueness rules | `research-paper-writing/` |
| [chtc66/academic-skills](https://github.com/chtc66/academic-skills) | `MIT` | Peer-review rebuttal non-fabrication guard & per-point (`R1.1`/`AC.1`) anchor enforcement (never present unrun experiments as completed) | `research-novelty-venue/`, `scripts/check_rebuttal.py` |
| [xf686/Meet-Reviewer-2](https://github.com/xf686/Meet-Reviewer-2) | `MIT` | H1–H17 ACL reviewer legitimacy & fairness firewall | `research-novelty-venue/`, `scripts/triage_reviews.py` |
| [yilaai/paper-quality-filter](https://github.com/yilaai/paper-quality-filter) | `MIT` (Copyright (c) 2026 yilaai, snapshot `679cdf3`) | Ported two-stage venue normalization, compact matching, and `S`/`A`/`B`/`C`/`Unknown` advisory classification rules (raw `journal_scores.json` excluded; optional `--quality-refs-dir` only; never substitutes for live CFP + accepted panels) | `scripts/venue_leads.py`, `scripts/compare_venue_novelty.py` |

---

## 3. Explicitly Excluded & Clean-Room Boundary Repositories (Never Copied)

No source code from any repository in this section is copied or bundled inside `research-scientist/` or its sibling sub-skills.

### 3.1 License-Restricted or Unlicensed Projects (Clean-Room / External Interface Only)

| Repository & URL | License / Status | Exclusion & Clean-Room Boundary |
|---|---|---|
| [khoj-ai/khoj](https://github.com/khoj-ai/khoj) | `AGPL-3.0` | **Never copied.** Integrated strictly via optional clean-room stdlib `urllib.request` HTTP client (`scripts/local_evidence.py --khoj-url`). |
| [SakanaAI/AI-Scientist](https://github.com/SakanaAI/AI-Scientist) | Custom `RAILS` License | **Never copied.** Clean-room PyMuPDF figure/caption detection + `visual_check_required: True` and strict verification gates. |
| [opendatalab/MinerU](https://github.com/opendatalab/MinerU) | `Apache-2.0` + Commercial/Attribution Additional Terms | **Never copied** (`magic_pdf` absent). Local PyMuPDF + `pdfplumber` + `tesseract` emits Content List V2-compatible JSON; optional external `mineru` CLI subprocess (`--use-mineru`). |
| [saulmcphd/lit-gap](https://github.com/saulmcphd/lit-gap) | No License | **Never copied.** Clean-room behavioral specifications only (`require_abstract=False`, OpenAlex `abstract_inverted_index`, EPMC JATS `<sec>`). |
| [JinheonBaek/ResearchAgent](https://github.com/JinheonBaek/ResearchAgent) | No License in inspected snapshot | **Never copied.** Cited as literature provenance only. |
| [Anikethh/IRIS-Interactive-Research-Ideation-System](https://github.com/Anikethh/IRIS-Interactive-Research-Ideation-System) | Clean-room behavioral inspiration | **Never copied.** Clean-room `--feedback-store` hypothesis feedback memory in `scripts/gap_pipeline.py`. |
| [Imbad0202/academic-research-skills](https://github.com/Imbad0202/academic-research-skills) | `CC BY-NC 4.0` (Non-Commercial) | **Rejected & excluded.** Non-commercial restriction incompatible with open distribution; 2,880-file bloat. |
| [CHB-learner/Awesome-Conference-Skills](https://github.com/CHB-learner/Awesome-Conference-Skills) | `None` (No `LICENSE` file) | **Rejected & excluded.** No license; superseded by live `scripts/venue_panel_collector.py`. |

### 3.2 Evaluated MIT / Apache-2.0 Repositories Explicitly Rejected (Excluded to Preserve Rigor & Parsimony)

| Repository | License | Exclusion Reason |
|---|---|---|
| `Adkid-Zephyr/anti-defensive-writing-Skill` | `MIT` | **Scientific-integrity conflict:** instructs hiding weaknesses and treating papers as a "press conference." |
| `dwzhu-pku/PaperBanana` & `llmsresearch/paperbanana` | `Apache-2.0` / `MIT` | **Hallucination risk & heavy API deps:** external VLM/image-gen unsuitable for empirical quantitative plots. |
| `KINGSTAR-OMEGA/claude-token-optimizer` | `MIT` | **Auditability conflict:** "Zero-English JSON-only mode" strips explanatory scientific provenance. |
| `K-Dense-AI/claude-scientific-writer` | `MIT` | **Redundant:** 22/26 skills duplicate `K-Dense-AI/scientific-agent-skills` already bundled; remaining 4 are generic Office handlers. |
| `TingxiYu/academic-figure-skill` | `Apache-2.0` | **Overlap & domain mismatch:** 217-file CNS/bio asset pack superseded by `scipilot-figure-skill` QA rules. |
| `lishix520/academic-paper-skills` | `MIT` | **Low signal:** manual score summing superseded by deterministic `humanizer_lint.py` & `check_manuscript_ledger.py`. |
| `appautomaton/latex-arxiv-SKILL` | `MIT` | **Redundant:** superseded by `search_papers.py` + `check_submission_preflight.py`. |
| `WenyuChiou/academic-writing-skills`, `xingtaxueshu/literature-review-skills`, `msimchowitz/writing-skills`, `rand/cc-polymath`, `JosephElvisMaman1/ResearchPilot-Skills`, `Research-Equality/RE-research-design` (`RE-idea-generation`) | `MIT` | **Overlap / non-AI-CS focus / catalog bloat:** prompt-only workflows or general software catalogs duplicating existing gates. |
| `stephenturner/skill-research-question-validator` | `MIT` | **External paid key + weaker:** wraps paid Consensus API (`CONSENSUS_API_KEY`); superseded by local/multi-source `research-gap-rq-audit`. |
| `yilaai/paper-quality-filter` *(data & ranking excluded; normalization/tiering ported in §2.2)* | `MIT` | **Partial exclusion boundary:** raw `journal_scores.json` (Clarivate JCR/CAS metrics) is never redistributed (optional local `scripts/venue_leads.py` / `scripts/compare_venue_novelty.py` `--quality-refs-dir` only); static JCR/CCF tables never substitute for live CFP + accepted panels (`scripts/venue_panel_collector.py`). |

---

## 4. Standard License Texts

### MIT License (Summary Template)

> Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

Full upstream MIT license texts and copyright headers for bundled suites are preserved verbatim in `research-scientist/modules/*/LICENSE.md`.

### Apache License, Version 2.0 (Summary Notice)

> Licensed under the Apache License, Version 2.0 (the "License"); you may not use adapted Apache-2.0 files except in compliance with the License. You may obtain a copy of the License at <https://www.apache.org/licenses/LICENSE-2.0>.
>
> Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the specific language governing permissions and limitations under the License.
