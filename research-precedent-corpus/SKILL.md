---
name: research-precedent-corpus
description: "Execute multi-source AI/CS/CV/NLP prior-art retrieval, citation-graph traversal, PDF/OCR layout extraction, and PaperQA2-style corpus Q&A with strict full-text reading gates."
---

# Research Precedent & Corpus Mining

Retrieve, deduplicate, extract, and interrogate AI/CS/CV/NLP literature before any gap, novelty, or writing claim. Never cite unread abstracts as full-text evidence or treat failed/bounded queries as proof of absence.

## Mandatory Integrity & Efficiency Rules

1. **Zero sycophancy & epistemic honesty:** Report missing coverage, rate limits (`rate_limited`), bot blocks (`bot_blocked`), and retraction flags bluntly. Never invent DOIs, arXiv IDs, quotes, or counts.
2. **Known-seed positive controls:** Every campaign must include known prior-art seeds; missing a known seed in `known_seed_checks` hard-blocks positive gap/novelty claims.
3. **Full-text reading basis:** Closest precedents must be resolved and inspected at `full_text` or `selected_full_text` before endorsing novelty.
4. **Disk offloading (`--compact`):** Write raw search dumps, PDF blocks, and QA outputs via `--out` and return `--compact` bounded summaries (`<4096B` stdout) with artifact pointers. Separate read-only retrieval from authorized disk writes.

## Workflow & Shared Tools

| Step | Shared Tool (`../research-scientist/scripts/`) | Purpose |
|---|---|---|
| Multi-source search | [search_papers.py](../research-scientist/scripts/search_papers.py), [search_campaign.py](../research-scientist/scripts/search_campaign.py) | 429 backoff, 4-ID + bare-arXiv dedup, ACL/HF/DBLP/OpenAlex/arXiv/S2 |
| Citation & fulltext | [citation_trails.py](../research-scientist/scripts/citation_trails.py), [citation_graph.py](../research-scientist/scripts/citation_graph.py), [fulltext_mining.py](../research-scientist/scripts/fulltext_mining.py) | Co-citation neighbors, JATS sections, scite tallies, retractions |
| PDF/OCR & Corpus QA | [resolve_fulltext.py](../research-scientist/scripts/resolve_fulltext.py), [extract_pdf_blocks.py](../research-scientist/scripts/extract_pdf_blocks.py), [local_evidence.py](../research-scientist/scripts/local_evidence.py), [check_evidence_map.py](../research-scientist/scripts/check_evidence_map.py) | MinerU Content List V2 JSON, OCR fallback, BM25+MMR Q&A with `ABSTAIN` gate |
| Bundled K-Dense | [verify_citations.py](../research-scientist/modules/kdense-literature-review/scripts/verify_citations.py) | Secondary reference audit |

Load [corpus retrieval protocol](references/corpus-retrieval-protocol.md) on demand for query families, OCR entropy gating, and optional `mineru`/`khoj` boundaries.
