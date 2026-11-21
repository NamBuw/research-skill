# Public review and limitation signals within the gap audit

Use this module when reviewer concerns, decision letters, rebuttals, or author limitations may reveal a candidate research problem. It is an optional evidence lane inside this skill's own [gap audit](gap-audit.md). The [bundled ResearchRadar component](../modules/researchradar/VENDOR.md) supplies a pure-stdlib local `radar.py` tool (Python 3.10+ required, e.g., `zip(..., strict=False)`) and detailed source/quote formats; it does **not** replace the multi-index `scripts/search_papers.py` / `scripts/search_campaign.py` workflow (`radar.py papers` queries arXiv and OpenAlex only) or original-paper comparison.

## Check source access and boundaries first

Define venue, years, track, accepted/rejected status, topic, inclusion criteria, and the denominator you hope to cover. Public paper metadata does not imply that reviews are public. Start with a bounded source check from the `research-scientist/` folder:

```bash
python3 modules/researchradar/problem-statement-finder/scripts/radar.py check
```

`check` probes six public endpoints (`arxiv`, `openalex`, `neurips_reviews`, `elife`, `semantic_scholar`, `snor_dataset`), inspects the local `$RADAR_CACHE/snor.sqlite3` index (`not built`, `not ready`, or `built (<mode>): N papers`), and records `openreview_notes` as unprobed (`403` human-verification challenge).

### `radar.py` subcommand and source coverage

| Subcommand | Sources & Outcomes | Key Flags & Caveats |
|---|---|---|
| `check` | Live endpoint probes + local SNOR SQLite index status | Does not probe OpenReview notes (`ChallengeRequiredError`). Cache defaults to `~/.cache/problem-statement-finder` unless `RADAR_CACHE` is set. |
| `papers <query>...` | arXiv + OpenAlex (`title_and_abstract.search`) only | `--limit` (default `25`), `--since` (year). Enforces 3s arXiv pace and strict all-words `AND` matching; keep queries to 2–4 words. Does not query Semantic Scholar, Crossref, Europe PMC, or PubMed. |
| `citing <openalex_id>` | OpenAlex forward citations (`cited_by_count:desc`) | `--since` (default `2020`), `--limit` (default `25`). |
| `limits <arxiv_id>` | `https://arxiv.org/html/<arxiv_id>` (strips `vN`) | 3s pace; extracts limitation/future-work headings (max 6000 chars) and up to 25 admission sentences. When HTML is absent (`no HTML version ... Read the PDF instead.`), fall back to `scripts/extract_pdf_blocks.py` and `scripts/local_evidence.py`. |
| `neurips <query>...` | NeurIPS proceedings **2013–2020** (**accepted papers only**) | `--years` (comma-separated within `2013`–`2020`; `2021+` returns HTTP 404), `--limit` (default `12`), `--max-chars` (default `5000`). Title-only whole-word/plural matching; caches `neurips-<year>.html` in `RADAR_CACHE`. |
| `elife <query>...` | Published eLife life-sciences research articles (`decisionLetter` + `authorResponse`) | `--limit` (default `8`), `--max-chars` (default `5000`). Newer reviewed-preprint eLife articles may lack `decisionLetter`; drop editor names in boilerplate. |
| `iclr-build` | Zenodo SNOR v1 (`records/15866613`, CC BY 4.0) into `$RADAR_CACHE/snor.sqlite3` | `--sample` (~90 MB of 30 MB byte-range slices; fragmentary only) or `--yes-download-2.2gb` (~2.2 GB download, ~1.5 GB disk; **ask the user first**). Omitting both flags exits `2`. Ingests `failed_matches` for rejected papers and drops reviewer signatures. |
| `iclr <query>...` | Offline local `snor.sqlite3` query (July 2025 snapshot: ICLR 2017 & 2019–2025, NeurIPS 2021–2024; ICLR 2018 & NeurIPS 2025 absent) | `--outcome` (`accepted`, `rejected`, `withdrawn`, `desk_rejected`, `unclear`, `both`, `all`; default `both` = `accepted` + `rejected` **only**), `--conference` (`iclr` or `neurips`), `--since`, `--limit` (default `10`, **per outcome**), `--max-chars` (default `5000`). Rejected NeurIPS records are ~5% (~670 vs ~16,300 ICLR); compare accepted vs rejected primarily on ICLR. Sample mode emits a warning against drawing conclusions. |
| `verify <file> <quote>...` | Offline exact-quote verification across saved JSON string fields or plain text | Whitespace-collapsed, **case- and punctuation-sensitive** substring match across one or more quotes; exits `0` iff `all_found`, else `1`. |

## Run bounded pilot collection

For a narrow pilot, run commands with the real topic or OpenAlex/arXiv ID (the values below are syntax examples) and save raw JSON locally:

```bash
python3 modules/researchradar/problem-statement-finder/scripts/radar.py papers "graph oversmoothing" --limit 10 --since 2022 > papers.json
python3 modules/researchradar/problem-statement-finder/scripts/radar.py citing W123456789 --since 2023 --limit 25 > citing.json
python3 modules/researchradar/problem-statement-finder/scripts/radar.py limits 2310.06825 > limits.json
python3 modules/researchradar/problem-statement-finder/scripts/radar.py neurips "graph neural" --years 2019,2020 --limit 10 --max-chars 5000 > reviews.json
python3 modules/researchradar/problem-statement-finder/scripts/radar.py elife "working memory" --limit 5 --max-chars 5000 > elife_reviews.json
python3 modules/researchradar/problem-statement-finder/scripts/radar.py iclr "graph neural" --outcome both --conference iclr --limit 10 > iclr_reviews.json
```

The tool reports source failures (`HTTP 429`, `HTTP 500`, `HTTP 0`, unreadable JSON) separately from empty results. Preserve the source JSON, query, run date, status, and actual record count. If output is redirected, ensure the file contains a valid complete JSON response before using it. Never share unpublished data through public search terms.

## Offline mode, OpenReview barriers, and access states

- **Offline operation:** `verify` and `iclr` (once `snor.sqlite3` is built) run strictly offline. `neurips` reuses cached `neurips-<year>.html` listings in `RADAR_CACHE` if present, though individual review pages require HTTPS. Set `RADAR_CACHE` to isolate test or project caches from `~/.cache/problem-statement-finder`.
- **OpenReview barrier:** Anonymous OpenReview `/notes` requests receive `403 ChallengeRequiredError`. Never attempt challenge bypass, headless browser automation, or invitation-name guessing. If a user supplies `OPENREVIEW_TOKEN` or a local export, keep whole reviews local, quote briefly with CC BY 4.0 attribution, and ignore or strip `signatures`, `tauthor`, `writers`, and reviewer identities.
- **Access states & schema notes:** Record exact retrieval coverage using the ResearchRadar taxonomy in [access states](../modules/researchradar/openreview-miner/references/access-states.md) (`retrieved`, `not_returned`, `inaccessible`, `no_record_exists`, `not_declared_by_venue`, `permission_denied`, `auth_required`, `challenge_required`, `api_unsupported`, `rate_limited`, `retrieval_failed`, `malformed_response`, `not_requested`, `not_configured`, `unknown`) and [OpenReview API notes](../modules/researchradar/openreview-miner/references/openreview-api-notes.md).

## Convert text to auditable signals

For each short review or limitation passage, record paper/version, review or decision URL, outcome if available, exact quote, location, category, response status, and what the passage actually claims. Check one or more quotes in one call with the offline verifier:

```bash
python3 modules/researchradar/problem-statement-finder/scripts/radar.py verify reviews.json "exact short quotation" "second exact quotation"
```

Apply the ResearchRadar analytical frames in [problem lenses](../modules/researchradar/problem-statement-finder/references/lenses.md) (tolerated vs fatal flaws, selection bias) and [review taxonomy](../modules/researchradar/review-intelligence/references/taxonomy.md): keep criticisms, questions, requested experiments, methodological observations, preferences, praise, and author future work separate. A rebuttal response is not proof that a concern was resolved, and when no rebuttal was retrieved, classify response status as `indeterminate` rather than `unaddressed`. Several comments on one paper count as one work for cross-paper recurrence; preprint and later publication are linked versions, not independent support. Record how many in-scope papers had readable reviews and whether rejected papers were included.

Group signals by underlying scientific limitation only after reading the passages. For every candidate, run multi-index closure search (`scripts/search_papers.py` / `scripts/search_campaign.py`) and inspect the closest full texts. Run the [engineering diagnosis](engineering-vs-gap.md) when the concern could be a local bug, protocol mismatch, weak baseline, or omitted implementation detail. Carry surviving candidates into the [gap record](gap-record.schema-example.json) validated by `scripts/check_gap_record.py` (author future-work alone cannot stand as gap support). Quote verification proves only that a string occurs in saved text; it does not prove reviewer accuracy, claim entailment, or a live research gap.

If source coverage is poor, reviews conflict, or the closest later paper is unread, report a candidate signal or `insufficient_evidence`. Source-specific details and upstream limitations are in [ResearchRadar sources](../modules/researchradar/problem-statement-finder/references/sources.md), the bundled [ResearchRadar notice](../modules/researchradar/VENDOR.md), and this skill's [source inventory](repository-landscape.md).
