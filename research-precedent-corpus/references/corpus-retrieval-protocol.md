# Corpus Retrieval & Extraction Protocol (AI/CS/CV/NLP)

Load this guide only during multi-source literature discovery, citation-graph expansion, fulltext/retraction mining, PDF/OCR layout extraction, or PaperQA2-style corpus Q&A.

## 1. 9-Source Retrieval Matrix & Live Provider Quirks (`search_papers.py`)

```bash
python3 ../../research-scientist/scripts/search_papers.py "speculative decoding kv cache" --mode quality --fanout --known-doi 10.48550/arXiv.2211.17192 --enrich-scite --enrich-retraction --out search.json --compact
```

| Source Key | Endpoint / Adapter | Default Min Interval | Verified Live Quirks & Rules |
|---|---|---|---|
| `s2` | `api.semanticscholar.org/graph/v1/paper/search` | `1.1s` | Non-Boolean relevance keyword query; optional `S2_API_KEY` header (`x-api-key`). **Never print/commit API keys**; if unset and `rate_limited`, disclose partial S2 coverage in user's language |
| `openalex` | `api.openalex.org/works` | `0.5s` | Reconstructs `abstract_inverted_index`; `per_page <= 100`; `--require-abstract` defaults to `False` (never drop title/PDF-only papers silently) |
| `crossref` | `api.crossref.org/works` | `1.0s` | Rich bibliographic metadata & `relation.is-retracted-by` / `update-to`; `10.48550/arxiv.*` DOIs 404 on Crossref and fall back to OpenAlex |
| `europepmc` | `ebi.ac.uk/europepmc/webservices/rest/search` | `0.5s` | Supplies PMCIDs for JATS `<sec>` fulltext XML mining (`fulltext_mining.py`) |
| `arxiv` | `export.arxiv.org/api/query` | `3.0s` | Atom XML feed; strip version suffix (`v1`, `v2`) during dedup; marks `preprint_only: true` |
| `pubmed` | `eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi` | `0.35s` | E-utilities search + summary for medical AI/ML-for-health intersections |
| `acl` | `api.crossref.org/works` (`prefix:10.18653`) or `aclanthology.org` HTML | `1.0s` | `/api/search/papers/` is 404; keyword queries use Crossref `prefix:10.18653` (often no abstracts), while `event:<id>` or `volume:<id>` fetches ACL Anthology HTML (<=32 MB) with abstracts |
| `huggingface` | `huggingface.co/api/papers/search` | `0.5s` | `/api/papers?q=` ignores `q`; use `/api/papers/search?q=...` returning `item.paper`; marks `preprint_only: true` |
| `dblp` | `dblp.org/search/publ/api` | `2.0s` | May return HTTP `202` HTML Anubis PoW challenge (`anubis_version`); detected before JSON parse and reported as `bot_blocked` (never treated as zero results) |

**6 Canonical Source Statuses:** `complete`, `bounded_partial`, `valid_zero_results`, `rate_limited`, `bot_blocked`, `source_failed`. Failures, rate limits, and bot blocks represent unchecked coverage, never proof of no prior work.

## 2. Multi-Family Search Campaigns, Positive Controls & 4-ID Dedup (`search_campaign.py`)

```bash
python3 ../../research-scientist/scripts/search_campaign.py campaign_plan.json --out campaign.json --compact
```

- **5 Independent Query Families (never search only a coined name):** (1) *Direct problem & outcome*, (2) *Mechanism & assumptions*, (3) *Components & combinations in plain terms*, (4) *Historical synonyms & adjacent CS/math/IR subfields*, (5) *Closure, replications, negative results & named closest authors*.
- **Modes & Vane Fan-Out:** `../../research-scientist/scripts/search_papers.py` exposes CLI flags `--mode speed|balanced|quality` (`quality` activates Vane-style 3-query `--fanout` or explicit `--fanout-query`), whereas `search_campaign.py` reads per-query `mode` and `fanout` fields from `campaign_plan.json`. Ranking always uses truthful `ranking_basis: "provider_order"` — never fabricate `similarity = 1.0`.
- **Positive Controls (`known_seed_checks`):** Pass `--known-doi` or `--known-source-id` (`SOURCE=ID`) to `../../research-scientist/scripts/search_papers.py` (or configure `seeds` in `campaign_plan.json`). Any `missed` canonical prior work invalidates novelty/gap claims until query terms are repaired (`check_gap_campaign.py` blocks empty `known_seed_checks` in confirmatory mode).
- **Transitive 4-ID + Title Dedup (`SGHA`):** Deduplicates across normalized DOI (mapping `10.48550/arxiv.<id>` -> `arxiv_id`), version-stripped `arxiv_id`, `openalex_id`, `s2_id`, `dblp_key`, `acl_id`, `pmid`, and collision-guarded `normalized_title`, preserving `dedup_groups`, `preprint_only`, and `unresolved-keep` flags. `--compact` writes full payload to `--out` (or auto-artifact) and emits bounded `<= 200`-char abstract previews.

## 3. Citation-Graph Expansion, JATS Fulltext & Retraction Screening

```bash
# Single-seed 1-hop OpenAlex W-ID trails or multi-seed CoCite / cluster-diverse expansion:
python3 ../../research-scientist/scripts/citation_trails.py W2626778328 --pages 1 --page-size 25 --out trails.json
python3 ../../research-scientist/scripts/citation_graph.py --seeds seeds.json --direction both --top 25 --min-overlap 2 --cluster-diverse --similarity-threshold 0.25 --out graph.json --compact

# Fulltext JATS/PDF section mining, Scite tallies & retraction checks:
python3 ../../research-scientist/scripts/fulltext_mining.py --dois 10.18653/v1/2023.acl-long.1 --pmcids PMC123456 --pdfs paper.pdf --out mining.json --compact
python3 ../../research-scientist/scripts/resolve_fulltext.py 10.48550/arXiv.2211.17192 --download-dir pdfs/
```
- `citation_trails.py` enforces `^W[0-9]+$` (short OpenAlex `W`-number, e.g., `W2626778328`; DOIs or URLs exit `2` with `work_id must be a short OpenAlex W-number`). `citation_graph.py` ports `SciPIP` `UnionFind` + `CoCite` cluster-diverse selection (`--cluster-diverse`), ranks by `seed_overlap_count`, and emits explicit `COMPLETE` vs `PARTIAL` status (`exit 2` if zero seeds resolve).
- `fulltext_mining.py` extracts Europe PMC JATS `<sec>` (`Discussion`, `Limitations`, `Future Work`) or local PDF sections, queries `api.scite.ai/tallies/{doi}`, and verifies retractions via Crossref -> OpenAlex `is_retracted` -> optional `--retraction-csv`. Any network/HTTP/parse error yields `retraction_status: "unchecked"` — **never** `"clean"`.
- `resolve_fulltext.py` resolves OA PDFs with DOI/title match verification, content-type validation (rejecting HTML paywalls), and SHA-256 recording. Treat trails and mining outputs as leads; verify key claims directly in primary PDFs.

## 4. Hybrid PDF/OCR Extraction & PaperQA2 Corpus Q&A (`extract_pdf_blocks.py`, `local_evidence.py`, `check_evidence_map.py`)

### 4.1 Layout, Table, Equation & OCR Extraction
```bash
python3 ../../research-scientist/scripts/extract_pdf_blocks.py paper.pdf --out blocks.json --tables --ocr --v2-only --compact
```
- **MinerU Content List V2 Schema:** Outputs typed page blocks (`paragraph`, `table` via `pdfplumber` with cell-overlap suppression, `image`/figure paired with `Fig. N` captions, `equation` via math symbol/equation-number heuristic) with `page_idx`, `bbox`, `ocr_used`, `source_pdf_sha256`, and mandatory `visual_check_required: True` (inspect decisive original PDF pages/figures visually before citing).
- **Thresholds & Optional External MinerU Boundary:** Pages yielding `< 50` extracted characters trigger `tesseract` OCR when `--ocr` is passed. Low-entropy / garbled blocks are dropped via `maybe_is_text()`. Passing `--use-mineru` invokes an external `mineru` CLI subprocess cleanly without bundling MinerU code (exits `2` with `status: "mineru_cli_not_found"` if `mineru` is absent on `PATH`).

### 4.2 PaperQA2 + GPT-Researcher + Optional Khoj Local Corpus Q&A
```bash
python3 ../../research-scientist/scripts/local_evidence.py --inputs blocks.json paper2.md --question "What calibration loss is ablated?" --chunk-chars 1200 --chunk-overlap 200 --mmr-lambda 0.7 --min-studies 2 --min-evidence 2 --strict-gate --out qa.json --compact
python3 ../../research-scientist/scripts/check_evidence_map.py evidence_map.json
python3 ../../research-scientist/modules/kdense-literature-review/scripts/verify_citations.py draft.md --output doi_check.json
```
- **Exact Numeric Defaults & Entropy Gate (`local_evidence.py`):**
  - Chunking: `chunk_chars=1200`, `chunk_overlap=200` (atomic `table`/`image`/`chart`/`equation`/`algorithm`/`code` blocks stay intact).
  - `maybe_is_text()` Shannon entropy filter: drops text with `len >= 20` and `entropy <= 2.5` or `entropy >= 8.0` (or `len >= 8` with `<= 2` distinct chars), while preserving short `< 20`-char titles and equations.
  - Lexical reranker: `GPT Researcher` plural-stemmed BM25 (retaining 1-char variables like `x`) + `SGHA` max-ratio normalized MMR (`mmr_lambda=0.7`, `reranker_mode`: `bm25_mmr` or `bm25_fallback`).
  - **Abstention Gate:** Requires `distinct_studies >= min_studies` (default `2`) and `len(ranked_passages) >= min_evidence` (default `2`), else emits `gate_status: "ABSTAIN"` (instead of `ANSWERABLE`); `--strict-gate` exits `1` on `ABSTAIN`.
  - **Optional External Khoj Boundary:** `--khoj-url` (with `--khoj-token-env`) queries an external AGPL-3.0 Khoj server over clean-room HTTP `GET /api/search` without bundling Khoj code.
- **Evidence Map & Citation Verification:** `check_evidence_map.py` enforces `study_group`, `original_checked`, and `original_full_text` provenance links (`exit 0` `ready_for_sourced_answer`). `verify_citations.py` checks DOI handle/Crossref existence only — always verify independently that key exists -> identity matches -> original passage entails the claim.

### 4.3 Retrieval & Evidence Boundary Rules
| Failure Mode | Prohibited Shortcut | Required Guardrail |
|---|---|---|
| Silent `require_abstract=True` drop | Skipping title/PDF-only papers | Keep `--require-abstract` off by default; inspect non-abstract hits |
| Missing `S2_API_KEY` or Anubis `202` | Treating `rate_limited`/`bot_blocked` as 0 prior work | Report canonical status + partial-coverage disclosure in user's language |
| Retraction lookup error | Defaulting failed checks to `clean` | Always emit `retraction_status: "unchecked"` on API/network errors |
| Confusing preprint & published | Counting arXiv v1 + NeurIPS paper as 2 studies | Resolve transitive `dedup_groups` and group by `study_group` |
| Abstract-only / OCR blind trust | Citing extracted snippets without page check | Require `visual_check_required` inspection of tables/figures in primary PDFs |

See [parent precedent-search guide](../../research-scientist/references/precedent-search.md) and [document evidence guide](../../research-scientist/references/document-evidence.md).
