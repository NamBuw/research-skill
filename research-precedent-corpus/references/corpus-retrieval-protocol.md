# Corpus Retrieval & Extraction Protocol (AI/CS/CV/NLP)

Load this guide only during literature discovery, PDF extraction, or evidence-map verification.

## 1. Multi-Source Discovery & Known-Seed Controls
- Query across distinct terminology families (problem, mechanism, adjacent CV/NLP/IR subfields) via `../../research-scientist/scripts/search_campaign.py` with `--compact` and `--out`.
- Supply `known_seeds` (canonical prior-art DOIs/arXiv IDs). A `missed` seed invalidates novelty claims until query terms are repaired.
- Never store `S2_API_KEY` in prompts, files, or logs.

## 2. Citation Graph & Fulltext Mining
- Expand co-citation / co-reference neighbors via `../../research-scientist/scripts/citation_graph.py` (`--seeds`, `--direction`, `--top`, `--out`, `--compact`) and inspect Limitations/Future Work + scite tallies via `../../research-scientist/scripts/fulltext_mining.py`.
- Treat citation trails and review signals as leads only; verify every claim directly in primary PDFs.

## 3. PDF/OCR Extraction & PaperQA2 Corpus Q&A
- Extract PDFs via `../../research-scientist/scripts/extract_pdf_blocks.py` (`--out`, `--tables`, `--ocr`, `--compact`). Low-entropy / garbled chunks are dropped before indexing.
- Optional external `mineru` CLI (`--use-mineru`) and `khoj` HTTP client are supported only when installed/running externally; core PyMuPDF + pdfplumber + Tesseract path runs locally.
- Answer targeted questions via `../../research-scientist/scripts/local_evidence.py` (`--inputs`, `--question`, `--min-studies`, `--min-evidence`, `--out`, `--compact`). Respect `ABSTAIN` when distinct-study support is insufficient, then validate links with `../../research-scientist/scripts/check_evidence_map.py`.
