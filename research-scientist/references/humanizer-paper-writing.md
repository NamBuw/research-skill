# Humanizer and scientific paper writing

Use this reference when drafting or editing a manuscript, abstract, related-work section, proposal, review, figure caption, rebuttal, or other scholarly prose. Treat Humanizer as an editorial pass, never as a way to strengthen a claim or disguise weak evidence. Apply the editorial procedure in this document. External writing skills are background references only; see [Source notes](repository-landscape.md) for provenance.

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

## Humanizer pass for scholarly prose

Read the full draft and flag patterns that make the writing sound formulaic, inflated, or detached from the evidence. Look at the document as a whole, not one sentence at a time. Common structural signs include:

- staged openings that announce an important point before making it;
- repeated “not X, but Y” contrasts when the rejected alternative was never claimed;
- one-line closers that restate a paragraph, forced groups of three, or a repeated sentence/paragraph template;
- vague authorities, unsupported claims of importance, sales language, or abstract metaphors in place of a concrete scientific relation;
- trailing participle phrases that add significance without adding a mechanism or result;
- redundant headings, decorative bold labels, chat residue, and explanations of what the document itself contains;
- synonym cycling, weak abstract nouns, or passive and nominalized phrasing that hide who did what; and
- uniform sentence length or a voice that is more polished, emphatic, or certain than the authors' actual argument.

Rebuild a paragraph around its inferential point when local word substitutions leave it mechanical. Use a direct subject and verb when they clarify agency. Vary sentence length where the argument allows it. Preserve a deliberate contrast when it names a real comparator, a negative result, an assumption, or a claim boundary. Keep a technical term, passive construction, repetition, dash, or list when the discipline, logic, or author's voice needs it. Never apply a banlist mechanically.

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
