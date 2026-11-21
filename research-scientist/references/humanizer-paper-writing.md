# Humanizer and scientific paper writing

Use this reference when drafting or editing a manuscript, abstract, related-work section, proposal, review, figure caption, rebuttal, or other scholarly prose. Treat Humanizer as an editorial pass, never as a way to strengthen a claim or disguise weak evidence. Apply the editorial procedure in this document. The [bundled local paper-writing toolkit](../modules/kdense-scientific-writing/VENDOR.md) supplies executable manuscript checks inside this skill; the root workflow and scientific decisions remain here. See [Source notes](repository-landscape.md) for provenance.

## Complete paper-production path

For a full paper, start from the accepted RQ, protocol, run receipts, source ledger, closest-work matrix, and actual figures/tables. Record the intended article type and the current target venue instructions. If these are missing, create an evidence and writing plan before drafting a conclusion. Select the reporting guideline by the actual study design, then open the current official statement and venue policy. The bundled selector gives candidate routes, not compliance certification:

```bash
python modules/kdense-scientific-writing/scripts/select_reporting_guidelines.py select --study-design randomized_trial
```

For a new local draft, use the bundled scaffold with an unused output directory. It creates a manuscript, claim and source records, a consistency manifest, authorship record and guideline coverage file. All contents remain incomplete until verified:

```bash
python modules/kdense-scientific-writing/scripts/scaffold_manuscript.py --output-dir ./draft-workspace --document-id local-draft --study-design randomized_trial --guideline consort-2025
```

Run the bundled checks from the manuscript workspace after filling records with real evidence. The paths below assume the current working directory is `research-scientist/` and the workspace is `draft-workspace/`:

```bash
python modules/kdense-scientific-writing/scripts/validate_manifest.py draft-workspace/source_manifest.json --kind source --require-verified
python modules/kdense-scientific-writing/scripts/audit_claims.py draft-workspace/manuscript.md draft-workspace/claims.csv draft-workspace/source_manifest.json
python modules/kdense-scientific-writing/scripts/check_consistency.py draft-workspace/consistency_manifest.json
python modules/kdense-scientific-writing/scripts/check_references.py draft-workspace/source_manifest.json
python modules/kdense-scientific-writing/scripts/validate_authorship.py draft-workspace/authorship.json
python modules/kdense-scientific-writing/scripts/select_reporting_guidelines.py check draft-workspace/reporting_coverage.json
python modules/kdense-scientific-writing/scripts/validate_manifest.py draft-workspace/manuscript_manifest.json --kind manuscript
python modules/kdense-scientific-writing/scripts/lint_manuscript.py draft-workspace/manuscript.md --manifest draft-workspace/manuscript_manifest.json
```

The bundled audit binds marked manuscript lines to claim-text hashes and declared evidence IDs. Re-run it after rewriting a claim, including after Humanizer editing; a prior verification does not transfer automatically to new wording. Resolve every structural finding by opening the original passage, result artifact or policy. Never treat a clean linter as proof of passage entailment, valid study conduct, ethical approval or venue compliance. The [toolkit CLI reference](../modules/kdense-scientific-writing/references/cli_reference.md) gives exact input fields and exit states.

Write results and methods before the abstract. For each result, reconcile analysis population, comparator, metric, estimate, uncertainty, figure/table values and run receipt. For each methods paragraph, reconcile data provenance, sampling, preprocessing, exclusions, split, controls, parameters, software and deviations with the protocol and actual execution. Keep a method-lineage table so reused and combined parts are credited and cannot be renamed as a new invention. Use an evidence-linked outline for introduction and discussion; cite close competing and contrary work with source locators, not title-level summaries. Write the title and abstract only after those claims stabilize.

For tables and figures, preserve the source data and transformation script, verify axis/row labels, units, denominators, uncertainty, missing runs and caption claims, and inspect the final rendered output. Include only displays that answer a question or establish a result; a decorative diagram cannot repair a missing experiment. In revision or rebuttal, classify each comment, identify affected claims/methods/results, update the ledgers before prose, rerun the affected checks and write a point-by-point response with exact manuscript locations. Keep confidential review material within its authorized boundary. Human authors approve declarations, author order and submission.

## Order of work: argument, evidence, prose

Do not humanize an unstable scientific argument. First settle the evidence, contribution, and intended reader. Then edit.

1. **Set the paper contract:** field, paper type, target reader/venue, main question, central answer, demonstrated scope, and main limitation.
2. **Map claims to evidence:** tie each central claim to the actual result, proof, source, figure, table, or analysis that supports it. Mark assumptions and unresolved evidence explicitly.
3. **State the contribution lineage:** identify prior methods, data, theory, and text the paper relies on. See the [prior-art search](precedent-search.md) and [scientific-integrity gate](precedent-search.md#scientific-integrity-gate-for-methods-and-names).
4. **Build the argument before drafting:** problem → what existing evidence or method leaves unresolved → the smallest contribution that addresses it → decisive evidence → supported scope and limitation. Change this order when the genre or evidence calls for another structure.
5. **Draft from verified evidence:** describe methods as performed; use results that exist; use future tense only for planned work. Do not invent an experiment, method detail, theorem condition, result, citation, reason, or limitation to fill a prose gap.
6. **Humanize after technical revision:** read the complete text, including the title, abstract, headings, captions, tables, labels, and callouts. Edit paragraph structure and rhythm, not just flagged words.
7. **Re-audit the final draft:** compare every edited factual or technical claim with the source and confirm that scope, uncertainty, citations, values, conditions, and method lineage survived.

For a completed paper, write the abstract after the body and claim hierarchy are stable. It should state the actual problem, central answer, decisive evidence, and conditions on the claim; it is not a list of sections or a promise about planned experiments.

### Local manuscript ledger

For a consequential draft, create a ledger from [the fictional JSON example](manuscript-ledger.schema-example.json) and run `python scripts/check_manuscript_ledger.py manuscript-ledger.json`. Give each material claim a stable ID and an exact source/result locator. Record a human verifier and date only after the passage, output, or analysis has actually been opened and checked. Record each method as reused, adapted, combined, or newly derived, with its sources and exact change. A proposed method novelty claim needs closest-work source IDs, a specific difference, and an accountable human review record; none of these declarations proves novelty by itself. A grand name for reused, adapted, or combined methods is always flagged, even if the author claims a difference. Track repeated numerical facts across the abstract, body, figures, tables, and supplements. The checker flags missing links, unsupported novelty declarations, and mismatched repeated values; it does not read the manuscript or judge source entailment. When wording changes, re-check the claim against the source rather than carrying a stale verified label forward.

Keep the ledger local when it contains unpublished work or restricted evidence. Do not send confidential manuscripts or peer-review material to an external model, search API, or parser unless the owner and applicable venue policy authorize that processing. Human authors retain responsibility for the methods, results, citations, authorship, and final submission.

## Humanizer pass for scholarly prose

Use the [bundled Humanizer pattern catalog](../modules/humanizer/UPSTREAM_SKILL.md) for this stage; it is part of this package, with its [source and license notice](../modules/humanizer/VENDOR.md). Read the full draft and flag patterns that make the writing sound formulaic, inflated, or detached from the evidence. Look at the document as a whole, not one sentence at a time. Common structural signs include:

- staged openings that announce an important point before making it;
- repeated “not X, but Y” contrasts when the rejected alternative was never claimed;
- one-line closers that restate a paragraph, forced groups of three, or a repeated sentence/paragraph template;
- vague authorities, unsupported claims of importance, sales language, or abstract metaphors in place of a concrete scientific relation;
- trailing participle phrases that add significance without adding a mechanism or result;
- redundant headings, decorative bold labels, chat residue, and explanations of what the document itself contains;
- synonym cycling, weak abstract nouns, or passive and nominalized phrasing that hide who did what; and
- uniform sentence length or a voice that is more polished, emphatic, or certain than the authors' actual argument.

Rebuild a paragraph around its inferential point when local word substitutions leave it mechanical. Use a direct subject and verb when they clarify agency. Vary sentence length where the argument allows it. Preserve a deliberate contrast when it names a real comparator, a negative result, an assumption, or a claim boundary. Keep a technical term, passive construction, repetition, dash, or list when the discipline, logic, or author's voice needs it. Never apply a banlist mechanically.

After the edit, re-run claim and consistency checks because changing wording can invalidate a prior claim hash or alter a causal, numerical, temporal, or methodological statement. Compare before and after at paragraph and claim level. Reject a smoother sentence when it drops a limitation, changes an estimate, alters a cited relation, or makes a hypothesis sound like a result.

If the authors provide a writing sample, use it to calibrate vocabulary, cadence, punctuation, formality, and first-person use. The sample informs voice, not facts or scientific claims. Without a sample, use a clear, restrained academic register appropriate to the field and genre. Avoid corporate, promotional, social-media, and generic assistant language.

The goal is readable scholarly writing that accurately represents the authors' work. Do not promise to bypass AI detectors or make an authorship claim based on style. Keep any AI-use or authorship disclosure accurate and follow the current venue policy.

## Scientific integrity: methods, names, and novelty claims

This gate applies before a contribution is named or described in the abstract, title, introduction, or contribution list.

- **Never invent a method.** Do not fabricate steps, equations, components, ablations, datasets, results, or implementation details to make the paper sound complete. Record undisclosed or unknown details as unknown.
- **Never inflate recombination into invention.** If the work joins, sequences, adapts, or reuses known methods, cite each source and describe those operations plainly. State the exact new component, mechanism, assumption, theorem, measurement, evaluation, or empirical finding that the authors actually add.
- **Do not use a grand name to conceal the lineage.** Avoid new acronyms and branded labels for routine combinations, pipelines, wrappers, or repackaging. If a short label improves readability, define it as a shorthand and explicitly identify the known methods it contains. A name is not evidence of novelty.
- **Separate implementation from contribution.** Code organization, prompt wording, a convenient workflow, or ordinary parameter selection may be useful engineering; do not call it a new scientific method without a demonstrated, non-obvious consequence and appropriate comparison.
- **Make novelty claims proportional to the search.** “First,” “novel,” “unprecedented,” “state of the art,” and “new framework” require source-backed comparison. If the search was bounded or the distinction is uncertain, use a bounded description such as “we combine A and B for setting C; we evaluate …” and state the search limit.
- **Do not hide borrowed ideas behind vague verbs.** Say whether the authors reuse, adapt, extend, derive, combine, or independently implement a component. Cite the closest source where the relation is first explained.
- **Do not write around a missing scientific result.** Mark a missing test, unverified method detail, or unsupported claim for the authors to resolve. Do not invent a plausible explanation or make a weak result sound decisive.

When a proposed name or contribution label appears new, search the label and its expanded mechanism in prior work. Record the paper lineage before keeping the label. If the method is a combination, state the combination; call it a new method only if its substantive new logic and evidence are identifiable.

## Claim-level language and evidence

- Use *shows* or *demonstrates* for direct evidence, a proved result, or an experiment whose design supports that claim. Use *supports*, *is consistent with*, or *suggests* for partial or indirect evidence. State when the result is exploratory.
- Keep observation, mechanism interpretation, and implication distinct. For example: “We observe X under condition C. We hypothesize mechanism M because evidence E distinguishes it from rival R.” Do not turn temporal order, predictive accuracy, correlation, or a model-generated explanation into causation.
- In quantitative prose, name the comparator, metric, result, setting, sample/seed basis, and uncertainty when available. Preserve denominators, units, intervals, and whether the number is a point estimate, average, or bound.
- In theory, preserve theorem assumptions, quantifiers, conditions, and asymptotic scope. Keep intuition and conjecture separate from proved statements.
- In methods, name software, versions, data, preprocessing, parameters, deviations, and analysis decisions only as verified. Distinguish a proposed protocol from a completed one.
- In related work, compare the actual contribution and evidence. Do not praise or dismiss a paper through venue prestige, author reputation, or an isolated metric.
- Keep limitations concrete. State the population, system, regime, measurement, design, sample, compute, or source boundary that limits the inference.

## Final integrity and voice check

Before returning edited prose, check the original and final side by side for:

1. Every factual claim, author name, method name, acronym, citation, quotation, date, number, ranking, negation, and causal or temporal relation.
2. Every condition, assumption, caveat, uncertainty marker, denominator, unit, and limitation that governs the claim.
3. Whether method and data lineage are credited and whether the purported new contribution is specific.
4. Whether the abstract and title match the final body, and whether captions, tables, figures, and prose make the same claim.
5. Whether the rewrite added an unsupported detail, removed a meaningful contrast, erased author voice, or made an uncertain result sound certain.

If an edit changes a scientific claim or method description, do not treat it as line editing. Flag the change, restore the source-supported wording, or ask the author to verify it. A polished sentence cannot repair an unsupported contribution.

### Section audit when drafting a full paper

- **Title and abstract:** compare every outcome, magnitude, comparator, qualifier, and novelty phrase against the results and closest-work matrix. A planned experiment has no result to summarize.
- **Introduction and related work:** distinguish background from direct competitors. For each closest paper, state the exact overlap and the material difference, then cite the original passage. Include relevant contrary and null work.
- **Methods:** reconcile the declared study unit, data source, inclusion rules, preprocessing, split, reference protocol, controls, parameters, software, deviations, and method lineage with the actual run record. Do not fill gaps with plausible implementation details.
- **Results:** verify each figure and table exists, matches the analysis population and metric, and is cited in the right place. Preserve negative and failed runs when they affect interpretation. Explain inconsistent denominators, units, or sample counts rather than silently harmonizing them.
- **Discussion and limitations:** compare findings with rivals and prior results; state the supported scope and concrete failure modes. Mark speculative mechanisms as hypotheses.
- **Declarations and references:** verify bibliography keys and source identity separately from claim support. Obtain current venue rules for author contributions, ethics, conflicts, data availability, and AI disclosure; do not invent boilerplate declarations.
