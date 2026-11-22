# Paper Writing, Compression, Figure QA & Submission Preflight (AI/CS/CV/NLP)

Load this guide only when drafting, tightening, visualizing, linting, or packaging an AI/CS/CV/NLP manuscript for submission or arXiv camera-ready release.

## 1. Argument-First Drafting, Reverse Outlining & Module Motivation

Follow this strict order of operations (`Research-Paper-Writing-Skills` + `../../research-scientist/references/humanizer-paper-writing.md`):
1. **Contract & Evidence First:** Freeze paper contract (field, venue, main RQ, central claim, supported scope, limitations), map every central claim to verified run receipts/locators, and record exact method lineage (`reused`, `adapted`, `combined`, `newly_derived`).
2. **Argument Skeleton:** Problem -> concrete empirical/theoretical limit in prior work -> smallest sufficient contribution (must pass F19 Parsimony Gate) -> decisive evidence -> calibrated limitations.
3. **Drafting Order:** Methods & Results (reconciling splits, metrics, seeds, CIs, denominators, and receipts) -> Introduction & Related Work (direct overlap vs material delta per closest work) -> Title & Abstract last (never summarize unrun plans).
4. **Reverse Outlining & Module Motivation Triad:** Extract the single governing claim of every paragraph; prune or merge any paragraph whose claim is off-RQ or redundant. For every architectural module/loss term, state *(a) why existing mechanism fails without it -> (b) exact mathematical/algorithmic mechanism -> (c) why this minimal choice beats simpler alternatives (with positive ablation)*.
5. **Humanize & Re-Audit:** Apply compression and Humanizer edits only after technical claims stabilize, then re-run claim/ledger checks so wording edits never drop caveats, numbers, or citations.

## 2. The 7 Late-Stage Compression Patterns (`zLanqing/codex-claude-academic-skills`)

Apply the **Expansion-Compression Arc** (expand for complete technical accuracy during drafting, then compress systematically before submission). Target `30–50%` length reduction from draft to submission; use `10–20%` for light polish, `50–65%` for short-paper/page-limit cuts, and `>65%` only when migrating to an extended abstract/workshop format.

| # | Compression Pattern | Before (Bloated Draft) | After (Compressed AI/CS/CV/NLP Prose) |
|---|---|---|---|
| 1 | **Sentence Shortening** (cut throat-clearing, meta-commentary & nested filler) | *"It is worth noting that in order to mitigate the issue of gradient explosion during the training of deep Transformer layers, we make use of gradient clipping at 1.0."* | *"We clip gradient norms at 1.0 to prevent Transformer training instability."* |
| 2 | **Paragraph Merging** (collapse parallel examples into 1 strongest case) | *Three separate 4-line paragraphs describing token truncation on BoolQ, TriviaQA, and HotpotQA with identical mechanics.* | *"Long-context inputs exceed 4k tokens on BoolQ (12%), TriviaQA (18%), and HotpotQA (31%); we apply sliding-window chunking (`stride=512`), retaining full-context evaluation on shorter examples."* |
| 3 | **Removal of Generic Adjectives** (replace *"significant / novel / SOTA"* with numbers) | *"Our novel, highly efficient attention mechanism achieves significantly superior state-of-the-art performance on ImageNet."* | *"Sparse window attention improves ImageNet-1K top-1 accuracy from 81.2% to 82.4% (`+1.2 pp`, 3 seeds) at 1.4x lower FLOPs."* |
| 4 | **Removal of Tutorial Explanation** (cut textbook background known to venue reviewers) | *Two paragraphs defining scaled dot-product attention $\text{softmax}(QK^\top/\sqrt{d})V$ and standard AdamW momentum updates.* | *"Following Vaswani et al. (2017), we modify only the key-projection stride in Eq. (2)."* |
| 5 | **Conversion to Claim-First Sentences** (turn topic openers/headings into findings) | *"In this section, we present the ablation results of our loss components in Table 3."* | *"Removing the auxiliary contrast loss drops out-of-distribution AUROC by 4.1 points (Table 3), confirming its role in boundary calibration."* |
| 6 | **Evaluation Compression via Takeaways** (group raw comparisons + 1 synthesis takeaway) | *Six sentences narrating every row of Table 2 across 4 datasets and 3 baselines.* | *"Across 4 benchmarks (Table 2), linear probing matches 3-layer adapters within `0.2%` F1 (`p=0.41`) while cutting trainable parameters by `94%`. **Takeaway:** Extra adapter depth adds cost without generalization gain."* |
| 7 | **Figure/Table Promotion (Text -> Visual)** (move dense hyperparameter/metric lists to tables/figs) | *A 140-word prose paragraph listing 8 hyperparameter settings, 5 baseline numbers, and per-class IoU values.* | *Summarize setup in Table 1 and per-class IoU in Fig. 2; spend prose strictly on causal interpretation and failure cases.* |

## 3. Humanizer §1–§26 & Four Hard Manuscript Integrity Gates

### 3.1 Humanizer Pattern Groups (`modules/humanizer/UPSTREAM_SKILL.md`)
Scan the entire manuscript (title, abstract, headings, captions, prose). Act on one sighting for Group A/E; require clustered evidence for weak-alone Group B tells. **Do not break domain terminology** (`leverage score`, `robust optimization`, `loss landscape`, `attention gate`, `catastrophic forgetting`):
- **Group A — Staging Instead of Stating (`§1–§5`):** `§1` Not-X-but-Y contrasts; `§2` one-line closers & dramatic fragments; `§3` pseudo-deep aphorisms (*"at its core"*, *"the architecture of"*); `§4` staged run-ups (*"let's dive in"*, *"the part that matters"*); `§5` arguing with unstated objections (*"to be clear"*, *"it would be easy to just"*).
- **Group B — Rhythm by Rule (`§6–§11`):** `§6` Forced triads; `§7` repeated sentence openings; `§8` em/en dashes (`—`/`--`) as universal connectors; `§9` stacked qualifiers (*"could potentially arguably"*); `§10` post-noun hyphenation; `§11` subjectless passive voice.
- **Group C — Inflation & Borrowed Authority (`§12–§18`):** `§12` Overused AI words (*delve, showcase, tapestry, testament, pivotal, meticulous, landscape*); `§13` inflated significance; `§14` vague connections (*"associated with"*); `§15` shallow `-ing` tails (*"highlighting..."*); `§16` sales language (*"groundbreaking", "breathtaking"*); `§17` unnamed authorities (*"experts argue"*); `§18` avoiding *is/are/has* (*"serves as"*).
- **Group D — Formatting (`§19–§21`):** `§19` Decorative bold label lists; `§20` title-case/emoji headings; `§21` curly quotes.
- **Group E — Chat & Draft Leftovers (`§22–§25`):** `§22` Chatbot residue; `§23` knowledge-cutoff disclaimers/guesses; `§24` heading echoed in first sentence; `§25` narrating the document itself.
- **Group F — Wrong Reader (`§26`):** Re-explaining known background before stating the decision/finding.

### 3.2 Executable Prose & Manuscript Ledger Gates
```bash
# Humanizer, sycophancy, claim-preservation, and 8-gram originality check:
python3 ../../research-scientist/scripts/humanizer_lint.py draft.md --strict --compare-baseline orig.md --reference prior.md --overlap-threshold 0.15 --mode manuscript --json --compact

# Four Hard Manuscript Gates (Anti-fabrication, Anti-padding, Anti-grandiose, Rigor):
python3 ../../research-scientist/scripts/check_manuscript_ledger.py --ledger ledger.json --manuscript draft.md --sources-dir sources/ --compact
```
- **`humanizer_lint.py`:** Scans `§1–§26` (`H01`–`H26`), padding (`PAD01`, `PAD02`), sycophancy (`SYC_FLATTERY`, `SYC_CHEERLEADING`), dropped numbers/citations/caveats (`CP_DROPPED` via `--compare-baseline`), and 8-gram overlap (`OVL_8GRAM` via `--reference`, default threshold `0.15`). `--strict` exits `1` on any `RISK`/`WARN`, critical sycophancy, dropped claim, or overlap.
- **`check_manuscript_ledger.py`:** Enforces all **4 Paper-Writing Gates**: (1) **Anti-fabrication** (`numeric_facts` consistency, `[claim:C...]` locators, `--sources-dir` quote/page verification); (2) **Anti-padding** (`extraneous_padding_detected`, off-RQ filler pruning); (3) **Anti-grandiose** (requires honest `reused`/`adapted`/`combined`/`newly_derived` lineage, bans coined `-Net`/`-Cascade`/`Unified Framework`/`Hyper-` labels on stitched pipelines, blocks `problem_inflation_detected`, and enforces F19 `simplest_alternative` + positive component ablation on combined/multi-module methods); (4) **Publication rigor** (calibrated scope & limitations). Exits `0` clean, `1` issues, `2` error.

## 4. Publication Figure & Palette QA (`scipilot-figure-skill` + `K-Dense`)

```bash
# Check colorblind-safe palette contrast (WCAG) & grayscale luminance separation:
python3 ../../research-scientist/scripts/check_figure_qa.py palette --palette okabe_ito --background #FFFFFF --role graphical --fail-on any --compact

# Audit rendered PNG/PDF/SVG/EPS figures and matplotlib/seaborn .py plot scripts:
python3 ../../research-scientist/scripts/check_figure_qa.py figure figs/ --min-dpi 300 --strict --out fig_qa.json --compact
```
- **Palette QA:** Bundled palettes `okabe_ito`, `tol_bright`, `tol_muted`, `viridis_6` (inspect via `--list-palettes`). WCAG contrast minimums: `3.0` (`graphical`, `large-text`), `4.5` (`normal-text`), `7.0` (`enhanced-text`). Grayscale legibility requires CIE `delta-L* >= 10.0` (`--grayscale-min-delta`).
- **Figure & Plot-Script QA:** Rejects `.jpg`/`.jpeg` (`ERROR`), Type3 fonts in PDFs including `FlateDecode`/`ObjStm` streams (`ERROR`), `jet`/`rainbow`/`hsv` colormaps in `.py` scripts (`ERROR`), corrupt PNG chunks/CRC (`ERROR`), `< 300` DPI or `< 600` px PNG width (`WARN`), missing `pdf.fonttype = 42` (`WARN`), missing SVG `viewBox` without explicit `width`/`height` (`WARN`), and truncated bar chart axes (`WARN`). Export charts as vector PDF/SVG with `pdf.fonttype = 42` or `>= 300` DPI PNG; never upscale low-res plots. `--strict` fails on warnings as well as errors (`exit 1`).

## 5. Double-Blind Anonymization, arXiv Cleanup, BibTeX & K-Dense Preflight

```bash
# 1. Double-blind (or camera-ready) anonymization audit across .tex, PDF, and supplements:
python3 ../../research-scientist/scripts/check_submission_preflight.py anonymize paper.tex --mode submission --names "Author One,Lab Name" --pdf paper.pdf --supplementary supp/ --strict --compact

# 2. Strip LaTeX comments (preserving \% and verbatim), prune unused files, check image sizes:
python3 ../../research-scientist/scripts/check_submission_preflight.py arxiv-clean src_tex/ --strip-comments-out arxiv_src/ --prune-unused --max-image-mb 5.0 --strict --compact

# 3. Linear-time BibTeX audit, acronym braces ({BERT}/{3D}), & Crossref->arXiv->OpenAlex verification:
python3 ../../research-scientist/scripts/check_submission_preflight.py bibtex refs.bib --tex paper.tex --protect-caps --fix-out refs_clean.bib --verify-online --strict --compact
```
- **`anonymize`:** Flattens `\input`/`\include` safely (blocking escaping symlinks), flags author names, institutional/grant hints, self-citations (`our prior work \cite{}`), emails, `/home/<user>` paths, non-anon `neurips`/`icml`/`iclr` `\iclrfinalcopy`/`[final]`/`[preprint]`/`[accepted]`, PDF `/Author` metadata (including UTF-16 hex), `.git`/`AUTHORS`/`NOTICE` in supplements, and link status (only `anonymous.4open.science`/`anonymous.science` receive `INFO anonymization/link-ok`, `_IDENTITY_HOSTS` or `/~[a-z]` trigger `ERROR anonymization/identifying-link`, while spoofed non-identity hosts receive neither `link-ok` nor `ERROR`).
- **`arxiv-clean`:** Rejects `.git`, `.ipynb_checkpoints`, `__pycache__`, outside symlinks, oversized images (`> 5.0` MB), and leaking comments; `--strip-comments-out` preserves `\%`, `\verb|...|`, and `verbatim` blocks while `--prune-unused` drops unreferenced `.tex`/images.
- **`bibtex`:** Catches duplicate keys, missing/placeholder fields, undefined/unused `\cite{}` keys, unprotected acronyms (`--protect-caps` wraps `{BERT}`, `{3D}` in single braces without `{{...}}` double-bracing), and verifies entries online (`--verify-online`).
- **K-Dense Writing Suite:** Complement with `../../research-scientist/modules/kdense-scientific-writing/scripts/audit_claims.py`, `check_references.py`, `check_consistency.py`, `validate_manifest.py`, and `select_reporting_guidelines.py` for structured claim-hash tracking.
