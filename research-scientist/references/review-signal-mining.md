# Public review and limitation signals within the gap audit

Use this module when reviewer concerns, decision letters, rebuttals, or author limitations may reveal a candidate research problem. It is an optional evidence lane inside this skill's own [gap audit](gap-audit.md). The [bundled ResearchRadar component](../modules/researchradar/VENDOR.md) supplies a local `radar.py` tool and detailed source/quote formats; it does not replace the multi-index literature search or original-paper comparison.

## Collect only the corpus actually accessible

Define venue, years, track, accepted/rejected status, topic, inclusion criteria, and the denominator you hope to cover. Public paper metadata does not imply that reviews are public. Start with a bounded source check from the skill folder:

```bash
python modules/researchradar/problem-statement-finder/scripts/radar.py check
```

The bundled tool can search arXiv/OpenAlex papers, follow OpenAlex citing works, inspect accessible arXiv limitation text, collect specified public NeurIPS review years and eLife decision letters, and query a local ICLR/review index when it has been built. Check its command help and source-specific status before use. A full ICLR index requires a large optional download; do not trigger it merely to answer a small question. If OpenReview notes require a user identity or challenge, record that access state and use lawful accessible sources. Do not attempt challenge bypass, guessed invitation names or reviewer identification.

For a narrow pilot, run commands with the actual topic and save raw JSON locally:

```bash
python modules/researchradar/problem-statement-finder/scripts/radar.py papers "specific topic" --limit 10 > papers.json
python modules/researchradar/problem-statement-finder/scripts/radar.py citing W123456789 --since 2023 > citing.json
python modules/researchradar/problem-statement-finder/scripts/radar.py neurips "specific topic" > reviews.json
```

The `W123456789` and topic are placeholders; verify the real seed and command output before interpretation. The tool reports source failures separately from empty results. Preserve the source JSON, query, run date, status and actual record count. If output is redirected, ensure the file contains a valid complete JSON response before using it. Do not share unpublished data through public search terms.

## Convert text to auditable signals

For each short review or limitation passage, record paper/version, review or decision URL, outcome if available, exact quote, location, category, response status and what the passage actually claims. Use the bundled exact-quote checker on saved JSON:

```bash
python modules/researchradar/problem-statement-finder/scripts/radar.py verify reviews.json "exact short quotation"
```

Keep review questions, criticisms, preferences, requested experiments, methodological observations, and author future work separate. A rebuttal response is not proof that a concern was resolved. Several comments on one paper count as one work for cross-paper recurrence; preprint and later publication are linked versions, not independent support. Record how many in-scope papers had readable reviews and whether rejected papers were included. Selection and availability bias can make a frequent concern look more general than it is.

Group signals by underlying scientific limitation only after reading the passages. For every candidate, search later papers and citing work that may have resolved it, then inspect the closest full texts. Run the [engineering diagnosis](engineering-vs-gap.md) when the concern could be a local bug, protocol mismatch, weak baseline or omitted implementation detail. Carry surviving candidates into the [gap record](gap-record.schema-example.json) with source IDs and a specific closure test. The positive gap disposition still requires scientific consequence, valid evidence, adversarial prior-art search and a feasible discriminating question. Quote verification proves a string occurs in saved text; it does not prove reviewer accuracy, claim entailment, or a live research gap.

If source coverage is poor, reviews conflict, or the closest later paper is unread, report a candidate signal or `insufficient_evidence`. A valid output may be that no defensible gap survived this lane. Source-specific details and upstream limitations are in the bundled [ResearchRadar notice](../modules/researchradar/VENDOR.md) and this skill's [source inventory](repository-landscape.md).
