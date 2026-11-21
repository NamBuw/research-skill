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

For a local text-based PDF, create a page/block extraction without uploading the file. This optional route requires PyMuPDF in the host environment:

```bash
python scripts/extract_pdf_blocks.py /path/to/paper.pdf --output /path/to/paper.blocks.json
python scripts/local_evidence.py "specific mechanism or outcome" /path/to/paper.blocks.json --limit 20
```

The extractor records a SHA-256 of the source PDF, page counts, text-block bounding boxes, pages with little extracted text, image-block counts and truncation at `--max-pages`. Its JSON is this skill's own `research_scientist_pdf_blocks_v1` format, **not MinerU output**. Empty or image-heavy pages may require OCR; tables, formulas, reading order and footnotes may be distorted. Inspect the original rendered page before using any decisive passage. Do not call an extraction full text if the reported page limit truncated it.

Run the bundled standard-library helper from the skill folder:

```bash
python scripts/local_evidence.py "specific mechanism or outcome" /path/to/papers --limit 20
```

It reads `.md` and `.txt` paragraphs, MinerU **Content List V2** `.json` (page lists or a flat item list), and this skill's PDF block JSON. Its lexical BM25-style ranking returns file SHA-256, segment ID, matched terms, a bounded excerpt, source lines for text files, and page index/bounding box when present. Explicitly supplied invalid JSON fails; when scanning a directory, unrelated or malformed JSON is listed under `skipped_files` with the error. Review this list: a skipped relevant extraction is missing coverage. The helper does not itself parse PDF, use embeddings, fetch online sources, or infer semantic entailment. Do not upload a confidential document to a remote parser without permission. Record the parser/version, source PDF hash and extraction date beside the output. The helper hashes the extracted file, which does **not** prove it matches a particular PDF; an exported `source_pdf_sha256` is a declaration to check against the original file.

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
