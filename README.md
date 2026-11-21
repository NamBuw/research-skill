# Research Scientist Agent Skill

Portable evidence-grounded research workflow for Codex, Claude Code and Gemini CLI.

See [skill instructions](research-scientist/SKILL.md), [installation and credentials](research-scientist/INSTALL.md), and [agent work division](research-scientist/references/agent-orchestration.md).

Invoke `research-scientist` in your Codex, Claude Code, or Gemini CLI session with the topic, decision you need, supplied papers/data, field, date boundary, and constraints. For a gap claim, ask the agent to show the executed search manifest, closest-work passages, failed source calls, engineering diagnosis, and surviving RQ card. For a paper review or venue recommendation, ask for the reading basis and current official CFP/fee sources.

The package also has local helpers. Run these from `research-scientist/`:

```bash
python scripts/search_papers.py "your topic and mechanism" --size 20 --pages 2
python scripts/citation_trails.py W2741809807 --pages 2 --page-size 50
python scripts/local_evidence.py "mechanism or outcome" /path/to/extracted/papers --limit 20
python scripts/check_gap_record.py /path/to/gap-record.json
python scripts/check_question_card.py /path/to/question-card.json
python scripts/check_experiment_manifest.py /path/to/experiment-manifest.json
python scripts/check_manuscript_ledger.py /path/to/manuscript-ledger.json
python scripts/compare_scorecards.py /path/to/scorecards.json
python scripts/venue_leads.py "specific contribution and field" --page-size 50 --pages 2
python scripts/check_venue_plan.py /path/to/venue-dossier.json
python modules/kdense-scientific-writing/scripts/scaffold_manuscript.py --output-dir ./draft-workspace --document-id local-draft --study-design observational
python modules/researchradar/problem-statement-finder/scripts/radar.py check
```

The example OpenAlex ID is only a syntax example. Replace it and every fictional JSON fixture before a real audit. Each checker enforces declared structure or arithmetic; the agent must still read the original papers, verify factual inputs, and make a reasoned scientific judgment.

Version 2.3.0 includes six-source paper discovery, bounded citation and local passage retrieval, public-review/limitation mining, evidence and gap records, operational research questions, experiment receipts, bundled scientific-writing and Humanizer components, scored comparisons, and venue planning. Supply your own `S2_API_KEY` through runtime configuration; no personal credentials are included.

[Evaluation scope](research-scientist/references/quality-evaluation.md): structural checks and synthetic review scenarios are not evidence of parity or superiority to K-Dense or any research system.

## Built-in capabilities and evidence limits

| Capability in this repository | Built-in implementation | What still requires source or expert review |
|---|---|---|
| Literature discovery | Semantic Scholar, OpenAlex, Crossref, Europe PMC, arXiv and PubMed helper with query/page counts, DOI candidate groups and explicit API failure states; bounded OpenAlex citation trails, local passage retrieval, and a structural evidence-map checker | Broader field-specific indexes, cross-provider citation checks, original full-text reading, and recall assessment |
| Gap and novelty audit | Own search, closest-precedent, counterevidence, and abstention protocols; linked gap-record checker; bundled ResearchRadar review/limitation/quote tools | Reading decisive prior work and domain judgment; no field-wide completeness guarantee |
| Research questions | Own question-card workflow, field-specific validity checks and structural JSON checker | Whether constructs, causal assumptions, predictions, and scientific importance are valid |
| Engineering failure diagnosis | Own failure protocol and local sample-ID/split diagnostic | Correctness of the implementation, benchmark, and causal explanation of a failure |
| Experiment lifecycle | Own frozen-protocol, apparatus, run-receipt, matched-comparison, analysis and review procedure; structural receipt checker | Execution, reproduction, statistical validity and domain review |
| Paper comparison and scores | Own six-dimension rubric, guarded arithmetic helper, declared-evidence comparator and weight-sensitivity check | Evidence-based ratings, calibration, and human/domain disagreement resolution |
| Submission planning | Related-paper publication-source leads, current-CFP/deadline/cost/fit protocol, and local calendar/cost checker | Live official venue facts, track eligibility, and the manuscript's actual readiness |
| Scientific writing | Own evidence-first paper and Humanizer workflow, method-lineage ledger, and bundled MIT offline toolkit for manuscript scaffolding, claim hashes, references, consistency, reporting, authorship and lint | Author verification of methods, results, citations, current policy, and final approval |

The skill runs in Codex, Claude Code, and Gemini CLI using each host's available tools. External repositories cited in the source notes are not installation requirements. No single parser or search index is silently treated as comprehensive.

## Source references and integration map

The skill implements its own research workflow and small local checkers. The references below identify the inspected upstream sources and the functions brought into this package. A source mention does not mean that the upstream application, models, indexes, user interface, or benchmark data are bundled. See the [code-reading inventory](research-scientist/references/repository-landscape.md), [retrieval code paths](research-scientist/references/retrieval-source-details.md), [gap/RQ code paths](research-scientist/references/gap-rq-source-details.md), and [writing/scoring/venue code paths](research-scientist/references/writing-score-venue-source-details.md) for snapshots and limitations.

| Source | Function integrated in this skill | Local implementation |
|---|---|---|
| [GPT Researcher](https://github.com/assafelovic/gpt-researcher) | Query decomposition, complementary retrieval lanes, evidence curation, cited report stages | [Research workflow](research-scientist/references/research-workflow.md), [agent division](research-scientist/references/agent-orchestration.md) |
| [Stanford STORM / Co-STORM](https://github.com/stanford-oval/storm) | Multi-perspective questions, evolving evidence map, outline before synthesis, human correction | [Document evidence](research-scientist/references/document-evidence.md), [research workflow](research-scientist/references/research-workflow.md) |
| [PaperQA2](https://github.com/Future-House/paper-qa) | Question-conditioned passage retrieval, corpus-bound answers, citation and abstention gates | [Local evidence search](research-scientist/scripts/local_evidence.py), [document evidence](research-scientist/references/document-evidence.md) |
| [The AI Scientist](https://github.com/SakanaAI/AI-Scientist) | Ideation → experiment → writing → skeptical review loop, with stronger protocol and provenance gates | [Experiment-to-paper](research-scientist/references/experiment-to-paper.md), [run receipt checker](research-scientist/scripts/check_experiment_manifest.py) |
| [Perplexica / Vane](https://github.com/ItzCrazyKns/Vane) | Search-mode selection, iterative follow-up, source-scoped answers | [Research workflow](research-scientist/references/research-workflow.md), [prior-art search](research-scientist/references/precedent-search.md) |
| [MinerU](https://github.com/opendatalab/MinerU) | Structured page/block evidence locators and visual verification of tables and equations | [Content List V2 passage search](research-scientist/scripts/local_evidence.py), [document evidence](research-scientist/references/document-evidence.md) |
| [Khoj](https://github.com/khoj-ai/khoj) | Local-corpus boundary, personal document retrieval, explicit source handoff | [Local evidence search](research-scientist/scripts/local_evidence.py), [document evidence](research-scientist/references/document-evidence.md) |
| [K-Dense Scientific Agent Skills](https://github.com/K-Dense-AI/scientific-agent-skills) | Task-specific scientific appraisal, literature review, hypothesis design and citation checks; its MIT scientific-writing toolkit is bundled locally with notice | [Gap audit](research-scientist/references/gap-audit.md), [RQ workflow](research-scientist/references/research-workflow.md), [scoring](research-scientist/references/scoring-and-venue-fit.md), [paper-writing toolkit](research-scientist/modules/kdense-scientific-writing/VENDOR.md) |
| [Humanizer](https://github.com/blader/humanizer) | Its MIT 26-pattern catalog is bundled locally for the final prose pass after factual and method-lineage checks | [Scientific paper writing](research-scientist/references/humanizer-paper-writing.md), [bundled catalog](research-scientist/modules/humanizer/VENDOR.md) |

The MIT-licensed [ResearchRadar components](research-scientist/modules/researchradar/VENDOR.md) are bundled for public-review collection, limitation signals and exact-quote checks. Additional question and ideation sources include [Good Question](https://github.com/Rimagination/good-question), [Lit-Gap](https://github.com/saulmcphd/lit-gap), [SciPIP](https://github.com/cheerss/SciPIP), [ResearchAgent](https://github.com/JinheonBaek/ResearchAgent), [IRIS](https://github.com/Anikethh/IRIS-Interactive-Research-Ideation-System), and [CKM-HypoGen](https://github.com/TaoJinkai/ckm-hypogen). Their contributions and evidence limits are mapped in the [source inventory](research-scientist/references/repository-landscape.md).

The upstream repositories use different licenses and have distinct runtime, model, and data requirements. This package vendors MIT-licensed K-Dense scientific-writing, Humanizer, and ResearchRadar components, each with its own license and source notice. AI Scientist has a custom source license, Khoj is AGPL, and MinerU has additional terms; their application source is not bundled. Source attribution documents design provenance and the actual bundled components; it is not a claim of full application parity. The skill's own gates deliberately prevent an autonomous loop, citation, parser output, or review score from certifying a scientific result by itself.

## Evaluate and contribute

If you have tried the skill, [open an issue](https://github.com/NamBuw/research-skill/issues) with the skill commit, agent/model, task, accessible sources and tools, actual output, and the specific conclusion you believe is right or wrong. For false gap claims, include the closest precedent and supporting passage. For scores or venues, identify the disputed claim, rubric item, or official date/fee source. Remove API keys and research data you cannot share.

Assess source-to-claim accuracy, detection of prior art, separation of implementation errors from research gaps, defensibility of /10 scores, and accuracy of CFPs, deadlines, and costs. Answer length and paper count are not quality measures. See the [evaluation limits](research-scientist/references/quality-evaluation.md) and [development checks](evaluation/forward-checks.md).

If the skill is useful, you may [star the repository](https://github.com/NamBuw/research-skill). A star is voluntary support, not evidence of scientific quality.
