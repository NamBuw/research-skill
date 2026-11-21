# Document-grounded reading and evidence curation

Use this module when reading supplied papers, a private manuscript corpus, or decisive candidate precedents. It is part of this skill's own workflow. Search output is a navigation aid; a verified passage is a separately recorded scientific judgment.

## Route the question and preserve the source boundary

1. State whether the answer is restricted to **supplied documents**, extends to a **live literature search**, or combines both. An answer from a supplied set must name that set and must not imply field-wide coverage.
2. Decompose the question into answerable subquestions: construct/definition, population or system, intervention/method, comparator, endpoint, result, uncertainty, and boundary condition as relevant. For a novelty task, add the exact claim that a prior paper could close.
3. Assign each subquestion to a source mode: local files, publisher/DOI page, scholarly database, citation graph, or official artifact. Keep the search manifest separate for each mode. Search the complementary sources required by the broader [prior-art protocol](precedent-search.md) when the decision concerns a gap.
4. Collect candidate records, then resolve identity and versions before counting works. An abstract, a snippet, and a full text are distinct access levels. Keep inaccessible close work visible.

## Build the question and perspective map

Create an editable question table before synthesis. Start with a draft outline from the user's task, then revise it only when retrieved evidence changes the map. Use perspectives to expose blind spots, not to manufacture a panel of independent experts:

| Perspective | Required question | Search or reading action | Output if unanswered |
|---|---|---|---|
| Core mechanism or theory | What exact mechanism/claim is asserted, and under which assumptions? | Search original method/theory, later extensions, and alternate vocabulary. | `mechanism_unverified`; remove mechanistic conclusion. |
| Measurement and design | What was observed, on what unit, with which construct, comparator and uncertainty? | Read methods, tables, supplement, protocol and data dictionary. | `measurement_unverified`; do not infer effect or causal target. |
| Independent prior art | Has another group already shown the same contribution under another name? | Run direct/partial/adjacent searches and citation trails; read nearest works. | `novelty_unresolved`; no positive novelty language. |
| Skeptical reviewer | Which contrary result, bias, implementation error or version weakens the story? | Search replications, corrections, negative findings and benchmark failures. | Record a named unresolved threat, not generic optimism. |
| Practitioner or domain user | What decision or behavior would change if the claim were true? | Inspect deployment/clinical/policy context and outcome relevance. | Keep the contribution as technical only if impact is unverified. |

For each perspective, record question ID, exact executed queries, source IDs inspected, status (`answered`, `qualified`, `unresolved`) and next discriminating source/test. A new query must be motivated by a missing cell, a contradictory source, or a newly discovered lineage. Do not count repeated queries against one index as independent coverage. Stop expanding a question only when the stated scope/budget is met and remaining work would not plausibly change the bounded answer; record the stopping reason.

Use an **information table** with rows keyed by question ID and columns for source/study group, result, locator, limitations, contradiction, and access level. Keep a separate question queue for unresolved items. If a perspective produces only a plausible question and no evidence, leave its information cell empty rather than filling it from model memory.

## Find passages in a local corpus

For a paper identified by DOI or OpenAlex work ID, the optional [OA resolver](../scripts/resolve_fulltext.py) queries OpenAlex (with per-host pacing and 429 retry/backoff) for reported open-access PDF locations, `pmcid`, `jats_xml_url`, and `is_retracted`. Run `python scripts/resolve_fulltext.py 10.48550/arxiv.1609.02907` to inspect metadata leads, or add `--download-dir /path/to/reading-workspace` to download the first working HTTPS OA PDF candidate. The resolver verifies that the returned work ID or DOI matches the request, records the source-reported version and license, rejects non-PDF responses, caps download size, does not overwrite an existing file, and returns a PDF hash. If one OA lead fails, it tries the next and records failed attempts. `no_oa_pdf_reported`, an API error and a failed download are different states; none makes the paper irrelevant or absent. OpenAlex metadata can be wrong or incomplete. Check the PDF title, authors, DOI, version, supplement and actual access rights against the original before treating it as the intended work. The downloaded file may be a submitted manuscript rather than the final published version; compare version-specific claims. A reported OA flag is not permission for unrestricted redistribution.

For a local PDF, extract inspectable layout, table, figure, equation, and OCR blocks locally without uploading confidential files:

```bash
python scripts/extract_pdf_blocks.py /path/to/paper.pdf --out /path/to/paper.blocks.json --tables --ocr --compact
python scripts/local_evidence.py --question "specific mechanism or outcome" --inputs /path/to/paper.blocks.json --mmr-lambda 0.7 --min-studies 2 --min-evidence 2 --compact
```

- **`extract_pdf_blocks.py`**: Accepts `--out` (or `--output`, optional when `--compact` is set), `--max-pages`, `--tables` (`pdfplumber` table HTML/text extraction with duplicate table-cell paragraph suppression), `--ocr` / `--ocr-lang` (`tesseract` OCR fallback on low-text `<50` extracted-char pages), `--v2-only` (writes bare MinerU Content List V2 `list[list[dict]]`), `--overwrite`, `--compact` (writes full JSON to `--out` or an auto-created artifact file and prints bounded summary with `artifact_path`), and `--use-mineru` (invokes an external `mineru` CLI if installed on `PATH`, or exits `2` with `mineru_cli_not_found` JSON — no MinerU or AI-Scientist code is bundled). Emits `research_scientist_pdf_blocks_v1` containing MinerU Content List V2-compatible items (`paragraph`, `table`, `image`, `equation`) with `page_idx`, `bbox`, `text`, `ocr_used`, `visual_check_required: True`, and PaperQA2-style `maybe_is_text` Shannon entropy filtering (dropping `>= 20`-char corrupted blocks while preserving short titles and equations).
- **`local_evidence.py`**: Accepts either positional `query paths...` or `--question` and `--inputs` (plus `--limit`, `--chunk-chars`, `--chunk-overlap`, `--mmr-lambda`, `--min-studies`, `--min-evidence`, `--study-map`, `--out`, `--strict-gate`, `--compact`, and optional clean-room `--khoj-url` / `--khoj-token-env` HTTP client to an external Khoj `/api/search` instance). When `--compact` is passed, writes the full evidence JSON (including `context_packed` and full quotes) to `--out` (or an auto-created artifact file) and prints bounded top-10 passage previews (`<= 240` chars) with `artifact_path`. It reads `.md`, `.txt`, MinerU Content List V2 `.json`, and `research_scientist_pdf_blocks_v1` `.json`; applies overlapping page-aware chunking and Shannon entropy filtering (`dropped_low_entropy_chunks`); ranks with GPT Researcher stemmed BM25 + PaperQA2/SGHA max-ratio normalized TF-IDF cosine MMR (`reranker_mode`: `bm25_mmr` or `bm25_fallback`); counts `distinct_studies`; builds bounded citation-keyed `context_packed`; and enforces an explicit `ANSWERABLE` vs `ABSTAIN` `gate_status` when `distinct_studies < min_studies` or `len(ranked_passages) < min_evidence`.
- **Verification boundaries**: Explicitly supplied invalid JSON fails; when scanning a directory, unrelated or malformed JSON is listed under `skipped_files`. Review `skipped_files` and `dropped_low_entropy_chunks` so omitted coverage stays visible. Every extracted PDF block retains `visual_check_required: True`; inspect the rendered original PDF page before trusting any table, figure, equation, or OCR-recovered number.

Search separately for method terms, outcome phrases, alternative names, negations, limitations, table captions and rival explanations. Inspect more than the highest-ranked paragraph when an assertion depends on nearby qualifiers, a table, an equation, or a supplement. Missing lexical hits are `no match in this local extraction`, not evidence that the original paper or field lacks the idea. A failed parser, unsupported JSON shape, OCR error, omitted figure, or missing full text is unchecked source coverage.

## Verify the decisive source

For every central claim, use a claim-to-passage record:

| Field | Required entry |
|---|---|
| Claim ID and exact wording | One atomic proposition, with its scope and quantifiers. |
| Source identity | DOI/official URL, title, authors, document type, publication/version dates, correction/retraction state where relevant. |
| Access and locator | `abstract`, `extracted_full_text`, or `original_full_text`; page/section/figure/table/supplement, plus extracted segment ID/hash when used. |
| Original passage and result | A short compliant excerpt or precise paraphrase, numeric values, denominator, units and uncertainty. |
| Entailment judgment | `supports`, `contradicts`, `mixed`, or `unresolved`, with the exact reason. |
| Extraction check | Whether the source PDF page, table, figure, equation, footnote or layout was visually checked. |
| Independence | Same study/cohort/data/codebase or an independent replication? |

Three gates must pass separately: the citation key resolves to a candidate document; bibliographic identity and version are checked; the **original passage entails the exact claim**. DOI registration or a plausible abstract does not pass the third gate. A passage can support a narrower claim while failing a broad one; rewrite the claim rather than stretching the citation.

For a table, figure, equation, multicolumn page, footnote, or OCR-sensitive number, compare extraction to the rendered original. Check row and column headers, units, signs, confidence intervals, baseline definition and whether a caption's statement is an author's interpretation rather than the underlying result. A parser coordinate is a locator, not proof of extraction accuracy. If the original is unavailable, mark `unresolved` and do not manufacture a quote, number or method detail.

## Synthesize without losing provenance

Build an evidence matrix by subquestion, not a pile of snippets. Pair supportive and conflicting results, then separate study design, reported result, authors' interpretation and your inference. Count distinct **studies**, not passages, reports or citations. Downweight or flag shared samples and common source lineages. If a well-supported contradiction remains, state it and inspect measurement, setting, versions and design before averaging it away.

Revise the draft outline from the information table. Each section must name the question IDs it answers and the claim IDs it will make. Put unsupported background or attractive but unverified explanations in an `unresolved` section or cut them. The order should expose the decision path: what is known, what contradicts it, what remains unresolved, and which result would change the conclusion. Do not convert a perspective's generated question into a factual section heading that presumes an answer.

For a durable machine-readable map, copy [the fictional example](evidence-map.schema-example.json), replace every fixture with actual source identities and passages, then run `python scripts/check_evidence_map.py path/to/map.json`. The checker catches broken source/question/claim references, absent locators and passages, abstract-only or unchecked evidence asserted as original-full-text support, and unsupported claims. It reports distinct `study_group` labels separately from passage counts. A pass confirms **structure only**: it cannot inspect a PDF or decide whether a passage actually entails a claim. The `original_checked` and `identity_verified` booleans are human or agent assertions that need audit.

Write the answer from the matrix. Keep each decisive claim attached to its source locator; preserve unknowns and access limits. If retrieved evidence is empty or only abstract-level for a decisive point, abstain from that point and say exactly which document or page is needed. Use the answer states `supported`, `qualified`, and `unresolved` per claim; do not let a supported neighboring claim make an unresolved question sound settled. A fluent answer generated from retrieved context is not an evidence check. When only a supplied corpus was searched, conclude within that corpus and state that broader prior art remains unchecked.

## Curation checks before delivery

- Does each central claim have a verified identity and an original passage at the needed access level?
- Were tables, figures, formulas and numerical claims checked against original rendering?
- Did a search mode silently replace another (local files versus live literature, one web engine versus multiple scholarly indexes)?
- Were source failures, retrieval caps, duplicate versions and unread close work disclosed?
- Are the final wording and citation scope no stronger than the evidence?

Use the [gap audit](gap-audit.md), [engineering diagnosis](engineering-vs-gap.md), and [research question workflow](research-workflow.md) after document reading when those decisions are requested.
