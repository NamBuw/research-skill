# Research Scientist Agent Skill

Portable evidence-grounded research workflow for Codex, Claude Code and Gemini CLI.

See [skill instructions](research-scientist/SKILL.md), [installation and credentials](research-scientist/INSTALL.md), and [agent work division](research-scientist/references/agent-orchestration.md).

Version 2.0.0 includes a bundled four-source paper discovery helper and complementary literature retrieval, prior-art and gap audits, operational research questions, scientific integrity, paper editing, scored assessments and venue submission planning. Supply your own S2_API_KEY through runtime configuration; no personal credentials are included.

[Evaluation scope](research-scientist/references/quality-evaluation.md): structural checks and synthetic review scenarios are not evidence of parity or superiority to K-Dense or any research system.

## Built-in capabilities and evidence limits

| Capability in this repository | Built-in implementation | What still requires source or expert review |
|---|---|---|
| Literature discovery | Four-source search helper with query/page counts, DOI candidate groups, and explicit API failure states | Broader field-specific indexes, citation chaining, full-text reading, and recall assessment |
| Gap and novelty audit | Own search, closest-precedent, counterevidence, and abstention protocols | Reading decisive prior work and domain judgment; no field-wide completeness guarantee |
| Research questions | Own question-card workflow and structural JSON checker | Whether constructs, causal assumptions, predictions, and scientific importance are valid |
| Engineering failure diagnosis | Own failure protocol and local sample-ID/split diagnostic | Correctness of the implementation, benchmark, and causal explanation of a failure |
| Paper comparison and scores | Own six-dimension rubric and guarded arithmetic helper | Evidence-based ratings, calibration, and human/domain disagreement resolution |
| Submission planning | Own current-CFP, deadline, cost, fit, and backward-schedule protocol; local calendar/cost checker | Live official venue facts and the manuscript's actual readiness |
| Scientific writing | Own evidence-first editing, method-lineage, and semantic-consistency rules | Author verification of methods, results, citations, and venue policy |

The skill runs in Codex, Claude Code, and Gemini CLI using each host's available tools. External repositories cited in the source notes are not installation requirements. No single parser or search index is silently treated as comprehensive.

## Evaluate and contribute

If you have tried the skill, [open an issue](https://github.com/NamBuw/research-skill/issues) with the skill commit, agent/model, task, accessible sources and tools, actual output, and the specific conclusion you believe is right or wrong. For false gap claims, include the closest precedent and supporting passage. For scores or venues, identify the disputed claim, rubric item, or official date/fee source. Remove API keys and research data you cannot share.

Assess source-to-claim accuracy, detection of prior art, separation of implementation errors from research gaps, defensibility of /10 scores, and accuracy of CFPs, deadlines, and costs. Answer length and paper count are not quality measures. See the [evaluation limits](research-scientist/references/quality-evaluation.md) and [development checks](evaluation/forward-checks.md).

If the skill is useful, you may [star the repository](https://github.com/NamBuw/research-skill). A star is voluntary support, not evidence of scientific quality.
