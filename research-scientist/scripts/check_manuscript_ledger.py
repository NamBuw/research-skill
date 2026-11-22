#!/usr/bin/env python3
"""Offline structural and evidence-grounded audit of manuscript claims, method lineage,
grandiose rebranding, numeric consistency, and local source locators/quotes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

MAX_COMPACT_BYTES = 3800

KINDS = {"reported", "inferred", "proposed", "unknown"}
METHOD_ORIGINS = {"reused", "adapted", "combined", "newly_derived"}

_GRANDIOSE_ADJECTIVES_RE = re.compile(
    r"\b(?:synergistic|groundbreaking|revolutionary|breakthrough|paradigm[- ]shifting|"
    r"transformative|game[- ]changing|unprecedented|holistic|cognitive\s+synthesis|"
    r"hyperbolic\s+\w+\s+cascade)\b",
    re.I,
)
_GRANDIOSE_NOUNS_RE = re.compile(
    r"\b(?:unified\s+(?:framework|architecture|paradigm|pipeline)|"
    r"novel\s+(?:framework|paradigm|architecture)|new\s+paradigm|"
    r"universal\s+(?:framework|architecture))\b",
    re.I,
)
_COINED_BRAND_PREFIX_RE = re.compile(
    r"\b(?:Hyper|Omni|Meta|Neuro|Syner)[A-Z-][A-Za-z0-9-]{2,}\b"
)
_COINED_BRAND_SUFFIX_RE = re.compile(
    r"\b[A-Z][A-Za-z0-9-]+(?:Net|Flow|Cascade|Former|Fusion|Framework|Engine|GPT)\b"
)
_COLON_CLAUSE_STOP = (
    r"(?:achieves?|achieving|evaluates?|evaluating|trains?|training|"
    r"is|are|was|were|uses?|using|runs?|running|serves?|serving|"
    r"tests?|testing|yields?|yielding|obtains?|obtaining|reaches?|reaching|"
    r"attains?|attaining|outperforms?|outperforming|reports?|reporting|"
    r"shows?|showing|demonstrates?|demonstrating)"
)
_COLON_ACRONYM_RE = re.compile(
    rf"\b([A-Z][A-Z0-9-]{{2,22}})[ \t]*:[ \t]*([A-Za-z](?:(?!\s+{_COLON_CLAUSE_STOP}\b)[^\n.;]){{3,89}})"
)
_COINED_ACRONYM_MORPH_RE = re.compile(
    r"^(?:(?:HYPER|OMNI|META|NEURO|SYNER)[A-Z0-9-]{2,}|"
    r"[A-Z0-9-]{3,}(?:FLOW|CASCADE|FORMER|FUSION|FRAMEWORK|ENGINE|RETRIEVER|PIPE)|"
    r"(?:[A-Z0-9]+-[A-Z0-9]*NET|[A-Z0-9]{5,}NET))$"
)
_ACRONYM_CONN = r"(?:of|for|via|with|and|in|on|to|by|the|a|an|from|into|as|at)"
_PAREN_ACRONYM_RE = re.compile(
    rf"\b([A-Z][A-Za-z-]+(?:[ \t]+{_ACRONYM_CONN}(?:[ \t]+{_ACRONYM_CONN})?[ \t]+[A-Z][A-Za-z-]+|[ \t]+[A-Z][A-Za-z-]+){{1,7}})[ \t]*\(([A-Z][A-Z0-9-]{{2,22}})\)"
)
_NOVELTY_OVERCLAIM_RE = re.compile(
    r"\b(?:state[- ]of[- ]the[- ]art|sota|first\s+(?:to|framework|method|system)|"
    r"outperforms\s+all|proves\s+universally)\b",
    re.I,
)
_CATASTROPHIC_FORGETTING_EXEMPT_RE = re.compile(
    r"\bcatastrophic\s+(?:forgetting|interference)\b",
    re.I,
)
_PROBLEM_INFLATION_RE = re.compile(
    r"\b(?:catastrophic|crippling|devastating|existential)\s+(?:bottleneck|barrier|failure|limitation|flaw|crisis|flaws|threat)\b|"
    r"\b(?:plagued\s+by|suffers\s+severely\s+from|desperately\s+needed|urgently\s+demands?\s+a\s+complete\s+overhaul)\b|"
    r"\brenders?\s+(?:all\s+)?(?:prior|existing|current)?\s*\w+(?:\s+\w+){0,3}\s+(?:useless|obsolete|infeasible|invalid)\b|"
    r"\bfundamentally\s+broken\s+(?:across\s+every|in\s+all|at\s+its\s+core)\b",
    re.I,
)
_EXTRANEOUS_PADDING_RE = re.compile(
    r"\b(?:in\s+the\s+(?:modern|current)?\s*(?:era|age)\s+of|in\s+today(?:'s|s)\s+rapidly\s+(?:evolving|changing|advancing))\b|"
    r"\b(?:with\s+the\s+rapid\s+(?:rise|growth|advancement|proliferation)\s+of|since\s+the\s+dawn\s+of)\b|"
    r"\b(?:has\s+revolutionized\s+(?:numerous|countless|many|various)\s+(?:industries|fields|domains|sectors))\b|"
    r"\b(?:needless\s+to\s+say|it\s+goes\s+without\s+saying|as\s+we\s+all\s+know)\b",
    re.I,
)
_NON_OWN_MOD_RE = (
    r"(?!baselines?\b|prior\b|existing\b|standard\b|conventional\b|"
    r"established\b|competing\b|previous\b|earlier\b)[A-Za-z0-9-]+"
)
_METHOD_NOUN_RE = (
    r"(?:method|approach|framework|model|pipeline|system|architecture|"
    r"algorithm|retriever|reranker|ranker|module|router|encoder|decoder|network|"
    r"predictor|classifier|detector|generator|adapter|agent|solver|estimator|"
    r"indexer|backbone|mechanism|filter|verifier|selector|controller|planner|"
    r"parser|extractor|scorer)"
)
_OWN_ADJ_RE = (
    r"(?:(?:newly|recently)\s+)?(?:proposed|new|novel|introduced|presented|developed|designed|"
    r"lightweight|modular|simple|custom|unified|combined|compact)"
)
_OWN_WORK_CUE_RE = re.compile(
    rf"\b(?:we\s+(?:also\s+)?(?:propose|introduce|present|design|develop|combine|integrate|merge|assemble|stack|fuse|unify|chain|build|construct|name|call)|"
    rf"(?:and|then)\s+(?:propose|introduce|present|design|develop|combine|integrate|stack|fuse|unify|chain|build|construct)|"
    rf"our(?:\s+{_NON_OWN_MOD_RE}){{0,5}}\s+{_METHOD_NOUN_RE}|"
    rf"(?:this(?:\s+{_NON_OWN_MOD_RE}){{0,4}}\s+{_METHOD_NOUN_RE}(?:,?\s+(?:called|named|termed|dubbed|denoted|referred\s+to\s+as|known\s+as))?|"
    rf"(?:a|an)(?:\s+{_NON_OWN_MOD_RE}){{0,4}}\s+{_METHOD_NOUN_RE},?\s+(?:called|named|termed|dubbed|denoted|referred\s+to\s+as|known\s+as))|"
    rf"(?:this|our)\s+(?:paper|work|study))\b",
    re.I,
)
_METHOD_CREATION_CUE_RE = re.compile(
    rf"\b(?:we\s+(?:also\s+)?(?:propose|introduce|present|design|develop|combine|integrate|merge|assemble|stack|fuse|unify|chain|build|construct|name|call)|"
    rf"(?:and|then)\s+(?:propose|introduce|present|design|develop|combine|integrate|stack|fuse|unify|chain|build|construct)|"
    rf"our(?:\s+{_NON_OWN_MOD_RE}){{0,5}}\s+{_METHOD_NOUN_RE})\b",
    re.I,
)
_PRIOR_WORK_FRAMING_RE = re.compile(
    r"\b(?:existing|prior|previous|earlier|classic|classical|conventional|traditional|standard|established|competing)\s+"
    r"(?:work|works|studies|study|papers?|methods?|models?|approaches?|systems?|architectures?|frameworks?|pipelines?|baselines?|literature)\b|"
    r"\b(?:in\s+the\s+literature|literature\s+(?:has|have|shows?|uses?|adopts?)|"
    r"adopted\s+from|adapted\s+from|rely\s+on|relies\s+on|relied\s+on|follow(?:s|ed|ing)?\s+prior|"
    r"introduced\s+(?:by\b|in\s+(?:prior|earlier|previous|\[\d+|(?:19|20)\d{2}))|"
    r"proposed\s+(?:by\b|in\s+(?:prior|earlier|previous|\[\d+|(?:19|20)\d{2}))|"
    r"as\s+(?:a|an)\s+(?:standard|common|popular|established|conventional|existing|prior)?\s*baselines?)\b",
    re.I,
)
_SENT_SPLIT_RE = re.compile(
    r"\n{2,}|[!?](?:\s|$)|"
    r"\.(?<!\bSec\.)(?<!\bFig\.)(?<!\bEq\.)(?<!\bTab\.)(?<!\bAlg\.)(?<!\bRef\.)(?<!\bApp\.)"
    r"(?<!\bal\.)(?<!\bvs\.)(?<!\bNo\.)(?<!\bDr\.)(?<!e\.g\.)(?<!i\.e\.)(?:\s|$)"
)
_CITE_TOKEN = r"(?:\[ref\]|\[\d+(?:\s*[,–-]\s*\d+)*\])"
_CAP_ITEM = rf"[A-Z][A-Za-z0-9-]+(?:\s*{_CITE_TOKEN})?(?:\s*\([^()\n]{{1,60}}\))?"
_BASE_LIST_INTRO = (
    r"(?i:"
    r"\bcompar(?:e|ed|ing)\b[^.;]{0,180}?\b(?:against|with|to)|"
    r"\bevaluat(?:e|ed|ing)\b[^.;]{0,120}?\b(?:against|with)|"
    r"\b(?:outperform(?:s|ed|ing)?|surpass(?:es|ed|ing)?|exceed(?:s|ed|ing)?)|"
    r"\b(?:better|higher|lower|faster|stronger|more\s+accurate)\b[^.;]{0,40}\bthan\b|"
    r"\b(?:to\s+(?:replace|improve\s+(?:upon|over)|extend|augment|supersede)|inspired\s+by|building\s+(?:on|upon)|on\s+top\s+of|over\s+prior)\b|"
    r"\b(?:unlike|in\s+contrast\s+to|as\s+opposed\s+to|versus|vs\.?)|"
    r"\bbaselines?\s+(?:include|such\s+as|like|including|are)|"
    r"\b(?:prior|existing)\s+(?:work|methods?|models?|approaches?|systems?|baselines?)"
    r"(?:\s*\(\s*(?:e\.g\.|for\s+example|such\s+as|including),?|\s+(?:such\s+as|like|including))|"
    r"\bagainst(?:\s+(?:standard|prior|existing)\s+baselines?\s+(?:such\s+as|like|including)|\s+baselines?\s+(?:such\s+as|like|including))|"
    r"\bagainst"
    r")"
)
_BASELINE_DESC_NP = rf"(?:(?:a|an|the)\s+(?:(?:[A-Za-z0-9-]+\s+){{0,4}}(?:{_METHOD_NOUN_RE}|baseline|baselines)\s+)?)"
_BASELINE_DESC_NP_OPT_NAME = (
    rf"(?:(?:a|an|the)\s+(?:(?:[A-Za-z0-9-]+\s+){{0,4}}(?:{_METHOD_NOUN_RE}|baseline|baselines)"
    rf"(?:,?\s+(?:called|named|dubbed|denoted|termed|referred\s+to\s+as|known\s+as|namely))?\s+)?)"
)
_BASELINE_LIST_CUE_RE = re.compile(
    rf"{_BASE_LIST_INTRO}\s+"
    rf"(?:{_BASELINE_DESC_NP_OPT_NAME})?"
    rf"(?:$|(?:{_CAP_ITEM}(?:\s*(?:,\s*(?:(?i:and|or)\s+)?|\s+(?i:and|or)\s+)))*(?:{_CAP_ITEM}\s*(?:,\s*)?(?i:and|or)\s+)(?:{_BASELINE_DESC_NP_OPT_NAME})?$)"
)
_BASELINE_COMMA_PREFIX_RE = re.compile(rf"{_BASE_LIST_INTRO}\s+(?:{_CAP_ITEM}\s*,\s*)+$")
_BASELINE_COMMA_FOLLOW_RE = re.compile(
    rf"^(?:"
    rf"\s*{_CITE_TOKEN}(?:\s*(?:(?:,\s*{_CAP_ITEM}\s*)*,\s*(?i:and|or)\s+[A-Z]|,\s*(?i:etc\.))|\s+(?i:and|or)\s+[A-Z])"
    rf"|\s*(?:(?:,\s*{_CAP_ITEM}\s*)*,\s*(?i:and|or)\s+[A-Z]|,\s*(?i:etc\.))"
    rf"|\s+(?i:and|or)\s+[A-Z]"
    rf")"
)
_RIGHT_BASELINE_PRED_RE = re.compile(
    rf"^\s*(?:"
    rf"(?:(?:\([^()\n]{{1,60}}\)|,(?:\s*(?:[^,;.()\n]|\([^()\n]{{1,40}}\)){{1,60}},))\s*)?(?:{_CITE_TOKEN}\s*)?(?i:(?:serve[sd]?\s+as|act[sd]?\s+as|are|is)\s+"
    rf"(?:(?:a|an|another|standard|prior|existing|established|conventional|competitive|strong|popular|common|widely\s+used)\s+)*baselines?\b|"
    rf"as\s+(?:(?:a|an|standard|prior|existing|established|conventional|competitive|strong)\s+)*baselines?\b)"
    rf"|"
    rf"(?:(?:,|(?i:and|or))\s*(?:[A-Z][A-Za-z0-9-]+(?:\s*{_CITE_TOKEN})?|\w+))(?:\s*(?:,|(?i:and|or))\s*(?:[A-Z][A-Za-z0-9-]+(?:\s*{_CITE_TOKEN})?|\w+)){{0,3}}"
    rf"\s*(?:{_CITE_TOKEN}\s*)?"
    rf"(?i:(?:serve\s+as|act\s+as|are)\s+"
    rf"(?:(?:a|an|another|standard|prior|existing|established|conventional|competitive|strong|popular|common|widely\s+used)\s+)*baselines?\b|"
    rf"as\s+(?:(?:a|an|standard|prior|existing|established|conventional|competitive|strong)\s+)*baselines?\b)"
    rf")"
)
_RIGHT_BASELINE_LABEL_RE = re.compile(
    rf"^\s*(?:"
    rf"(?:{_CITE_TOKEN}\s*)?baselines?\b|"
    rf"(?:,|\()\s*(?i:(?:(?:a|an|the)\s+)?(?:(?:standard|prior|existing|established|conventional|competitive|strong)\s+)*baselines?\b)"
    rf")"
)
_RIGHT_LIST_CITED_RE = re.compile(
    r"^(?:\s*(?:,|(?i:and|or))\s*[A-Z][A-Za-z0-9-]+){1,4}\s*"
    r"(?:\([^)\n]*(?:19|20)\d{2}[^)\n]*\)|\[ref\]|\[\d+(?:\s*[,–-]\s*\d+)*\]|\[[^\]\n]*(?:19|20)\d{2}[^\]\n]*\])"
)
_PAREN_CONTRAST_RE = re.compile(
    r",\s*(?:unlike|compared\s+(?:against|with|to)|in\s+contrast\s+to|as\s+opposed\s+to|rather\s+than)\s+"
    r"(?:[^,;.()\n]|\([^()\n]{1,60}\)){1,80},|"
    r"\(\s*(?:unlike|compared\s+(?:against|with|to)|in\s+contrast\s+to|as\s+opposed\s+to|rather\s+than)\s+"
    r"(?:[^()\n]|\([^()\n]{1,40}\)){1,80}\)",
    re.I,
)
_CLAUSE_BREAK_RE = re.compile(
    r";|,\s*(?:whereas|while|although|though|however|instead|conversely|by\s+contrast|on\s+the\s+other\s+hand)\b",
    re.I,
)
_ACTIVE_OWN_VERB_RE = re.compile(
    r"\b(?:we\s+(?:also\s+)?(?:propose|introduce|present|design|develop|combine|integrate|merge|assemble|stack|fuse|unify|chain|build|construct|name|call)|"
    r"(?:and|then)\s+(?:propose|introduce|present|design|develop|combine|integrate|merge|assemble|stack|fuse|unify|chain|build|construct|name|call)|"
    r"(?:this|our)\s+(?:paper|work|study)\s+(?:proposes?|introduces?|presents?|designs?|develops?|combines?|integrates?|merges?|stacks?|fuses?|unifies|chains?))\b",
    re.I,
)
_VERB_TO_BASELINE_BREAK_RE = re.compile(
    r"\b(?:against|unlike|versus|vs\.?|outperform(?:s|ed|ing)?|surpass(?:es|ed|ing)?|exceed(?:s|ed|ing)?|"
    r"compar(?:e|ed|ing)\b[^.;]{0,80}\b(?:against|with|to)|"
    r"(?:better|higher|lower|faster|stronger|more\s+accurate)\b[^.;]{0,40}\bthan|"
    r"to\s+(?:replace|improve\s+(?:upon|over)|extend|augment|supersede)|inspired\s+by|building\s+(?:on|upon)|on\s+top\s+of|over\s+prior)\b",
    re.I,
)
_NAMING_CUE_WORDS = r"(?:called|named|dubbed|denoted|termed|referred\s+to\s+as|known\s+as)"
_NAMING_CUE_OPT = rf"(?:,?\s+(?:(?:is|are)\s+{_NAMING_CUE_WORDS}|{_NAMING_CUE_WORDS}|namely|hereafter(?:\s+{_NAMING_CUE_WORDS})?))?"
_NAMING_CUE_REQ = rf",?\s+(?:(?:is|are)\s+{_NAMING_CUE_WORDS}|{_NAMING_CUE_WORDS}|namely|hereafter(?:\s+{_NAMING_CUE_WORDS})?)"
_OWN_NP_BEFORE_RE = re.compile(
    rf"\b(?:our(?:\s+{_NON_OWN_MOD_RE}){{0,5}}\s+{_METHOD_NOUN_RE}{_NAMING_CUE_OPT}|"
    rf"our(?:\s+{_OWN_ADJ_RE})?|"
    rf"(?:the|this|a|an)\s+(?:(?:newly|recently)\s+)?(?:proposed|new|novel|introduced|presented|developed|designed)"
    rf"(?:(?:\s+{_NON_OWN_MOD_RE}){{0,4}}\s+{_METHOD_NOUN_RE})?{_NAMING_CUE_OPT}|"
    rf"this(?:\s+{_NON_OWN_MOD_RE}){{0,4}}\s+{_METHOD_NOUN_RE}{_NAMING_CUE_OPT}|"
    rf"(?:a|an)(?:\s+{_NON_OWN_MOD_RE}){{0,4}}\s+{_METHOD_NOUN_RE}{_NAMING_CUE_REQ})"
    rf"[\s,(]+$",
    re.I,
)
_PREP_OWN_BEFORE_RE = re.compile(
    r"\bin\s+(?:our|this)\s+(?:work|paper|study)[,\s]+$",
    re.I,
)
_PASSIVE_OWN_AFTER_RE = re.compile(
    r"^\s*(?:(?:\([^()\n]{1,60}\)|,(?:(?:[^.;()\n]|\([^()\n]{1,40}\)){1,110},)?)\s*)?"
    r"(?:is|are)\s+(?:hereby\s+)?(?:proposed|introduced|presented|designed|developed|constructed|built|formulated|named|called|dubbed|denoted|termed|referred\s+to\s+as|known\s+as)\b",
    re.I,
)
_CLAUSE_JOIN_VERBS = r"(?:combines?|integrates?|merges?|fuses?|unifies|chains?|stacks?)"
_PARTICIPLE_JOIN_VERBS = r"(?:combining|integrating|merging|fusing|unifying|chaining|stacking)"
_ACTIVE_JOIN_CLAUSE = (
    rf"(?:{_PARTICIPLE_JOIN_VERBS}|"
    rf"(?:which|that)\s+(?:{_CLAUSE_JOIN_VERBS}|(?:is|are)\s+(?:built|based)\s+(?:on|upon))|"
    rf"(?:built|based)\s+(?:on|upon))\s+(?:[^.;()\n]|\([^()\n]{{1,40}}\)){{1,110}}?"
)
_OWN_APPOSITIVE_AFTER_RE = re.compile(
    rf"^(?:"
    rf"\s*(?:,|\()\s*(?:"
    rf"our(?:\s+{_NON_OWN_MOD_RE}){{0,5}}\s+{_METHOD_NOUN_RE}|"
    rf"(?:a|an|the)\s+(?:(?:newly|recently)\s+)?(?:proposed|new|novel|introduced|presented|developed|designed)(?:\s+{_NON_OWN_MOD_RE}){{0,4}}\s+{_METHOD_NOUN_RE}"
    rf")|"
    rf"\s*,\s*{_ACTIVE_JOIN_CLAUSE}(?:,(?:\s|$)|(?:\s+(?:achieving|obtaining|yielding|reaching|attaining)\b)|[.!?;]|$)|"
    rf"\s*\(\s*{_ACTIVE_JOIN_CLAUSE}\)|"
    rf"\s+(?:is|(?:serves|acts|functions|operates)\s+as)\s+our(?:\s+{_NON_OWN_MOD_RE}){{0,5}}\s+{_METHOD_NOUN_RE}\b|"
    rf"\s+(?:is|are)\s+(?:a|an|the)\s+(?:[A-Za-z0-9-]+\s+){{0,4}}{_METHOD_NOUN_RE}\s+"
    rf"(?:(?:that|which)\s+{_CLAUSE_JOIN_VERBS}|{_PARTICIPLE_JOIN_VERBS}|(?:built|based)\s+(?:on|upon))\b"
    rf")",
    re.I,
)
_SUBJECT_JOIN_INTERR = r"(?:\([^()\n]{1,60}\)|,[^.;()\n]{1,60},)"
_SUBJECT_JOIN_AFTER_RE = re.compile(
    rf"^\s*(?:({_SUBJECT_JOIN_INTERR})\s*|(?<=\s))({_CLAUSE_JOIN_VERBS})\b",
    re.I,
)
_COMP_ADJ = (
    r"(?:better|higher|lower|faster|stronger|simpler|worse|slower|weaker|"
    r"more\s+(?!than\b)[A-Za-z-]+|less\s+(?!than\b)[A-Za-z-]+)"
)
_COMP_THAN_PHRASE = rf"{_COMP_ADJ}(?:(?:,\s*|\s+)[A-Za-z0-9-]+){{0,9}}(?:,\s*|\s+)than\b"
_PRIOR_OR_BASE_NP = (
    r"(?:(?:prior|existing|previous|earlier|standard|conventional|established|competing|current|state-of-the-art|sota)\s+)*"
    r"(?:work|works|studies|methods?|models?|approaches?|systems?|architectures?|frameworks?|pipelines?|baselines?)"
)
_SUBJECT_SUPERIOR_OVER_PRIOR_RE = re.compile(
    rf"^\s*(?:{_SUBJECT_JOIN_INTERR}\s*|,\s*)?"
    rf"(?:"
    rf"(?:is|are|proves?|proving)\s+(?:superior|preferable)\s+to\s+{_PRIOR_OR_BASE_NP}|"
    rf"(?:outperforms?|surpasses?|exceeds?|beats?|replaces?|supersedes?|improv(?:e[sd]?|ing)(?:\s+(?:on|upon|over))?|overcomes?)\s+{_PRIOR_OR_BASE_NP}|"
    rf"(?:yields?|achieves?|obtains?|delivers?|provides?|brings?|shows?|demonstrates?)\s+"
    rf"(?:[A-Za-z0-9%.-]+\s+){{0,4}}(?:gains?|improvements?|advantages?|speedups?|margins?)\s+over\s+{_PRIOR_OR_BASE_NP}|"
    rf"(?:yields?|achieves?|obtains?|delivers?)\s+{_COMP_THAN_PHRASE}\s+{_PRIOR_OR_BASE_NP}"
    rf")\b",
    re.I,
)
_NAMING_CUE_ACRONYM_RE = re.compile(
    rf"(?i:\b(?:our(?:[ \t]+{_NON_OWN_MOD_RE}){{0,5}}[ \t]+{_METHOD_NOUN_RE}|"
    rf"(?:the|this|a|an)(?:[ \t]+{_NON_OWN_MOD_RE}){{0,4}}[ \t]+{_METHOD_NOUN_RE})[ \t]*"
    rf"(?:(?:is|are)[ \t]+{_NAMING_CUE_WORDS}[ \t]+|,?[ \t]*{_NAMING_CUE_WORDS}[ \t]+|,?[ \t]*namely[ \t]+|"
    rf"\([ \t]*(?:hereafter(?:[ \t]+{_NAMING_CUE_WORDS})?|{_NAMING_CUE_WORDS}|namely)[ \t]+))"
    rf"([A-Z][A-Z0-9-]{{2,22}})\b"
)
_YEAR_CITATION_AFTER_RE = re.compile(
    r"^\s*(?:\([^)\n]*(?:19|20)\d{2}[^)\n]*\)|\[ref\]|\[\d+(?:\s*[,–-]\s*\d+)*\]|\[[^\]\n]*(?:19|20)\d{2}[^\]\n]*\])"
)
_SURNAME = r"(?-i:[A-Z][A-Z-]*[a-z][A-Za-z-]*)"
_PAREN_AUTHOR_YEAR_CITE = rf"\({_SURNAME}(?:\s+(?:and|&)\s+{_SURNAME}|\s+et\s+al\.)?,?\s*(?:19|20)\d{{2}}[a-z]?\)"
_NARRATIVE_AUTHOR_YEAR_CITE = (
    rf"(?:\b{_SURNAME}(?:\s+(?:and|&)\s+{_SURNAME}|\s+et\s+al\.),?\s*\((?:19|20)\d{{2}}[a-z]?\)|"
    rf"\b(?:as\s+(?:in|shown\s+in|described\s+in|proposed\s+by|introduced\s+by)|proposed\s+by|introduced\s+by|from)\s+"
    rf"{_SURNAME},?\s*\((?:19|20)\d{{2}}[a-z]?\))"
)
_AUTHOR_YEAR_CITE = rf"(?:{_PAREN_AUTHOR_YEAR_CITE}|{_NARRATIVE_AUTHOR_YEAR_CITE})"
_CITE_ANY_RE = re.compile(rf"\[ref\]|\[\d+(?:\s*[,–-]\s*\d+)*\]|{_AUTHOR_YEAR_CITE}")
_LEFT_PRIOR_CITE_RE = re.compile(
    rf"^\s*(?:(?:in|from|per|by|following|according\s+to|as\s+(?:shown|described|proposed|introduced|reported|noted)\s+in)\s+)?"
    rf"(?:{_SURNAME}(?:\s+(?:and|&)\s+{_SURNAME}|\s+et\s+al\.)?,?\s*\((?:19|20)\d{{2}}[a-z]?\)|\[ref\]|\[\d+(?:\s*[,–-]\s*\d+)*\])"
    rf"\s*,(?:\s*(?:the|a|an)\b)?\s*$",
    re.I,
)
_LEFT_IN_CITE_RE = re.compile(
    rf"^\s*(?:in|from|per|by|following|according\s+to|as\s+(?:shown|described|proposed|introduced|reported|noted)\s+in)\s+"
    rf"(?:{_SURNAME}(?:\s+(?:and|&)\s+{_SURNAME}|\s+et\s+al\.)?,?\s*\((?:19|20)\d{{2}}[a-z]?\)|\[ref\]|\[\d+(?:\s*[,–-]\s*\d+)*\])\s*,",
    re.I,
)
_CONSTITUENT_NAMED_TAIL_RE = re.compile(
    rf"(?:\b(?:and|with|plus|&)\s+|,\s*(?:and\s+)?)"
    rf"(?:[A-Z][A-Za-z0-9-]{{1,25}}|"
    rf"(?:[A-Z][A-Za-z0-9-]*\s+){{0,2}}(?:from|by|of|proposed\s+by|introduced\s+by)\s+{_SURNAME})\s*$"
)
_JOIN_CONTINUE_AFTER_CITE_RE = re.compile(
    r"^\s*(?:with\b|plus\b|"
    r"(?:and|or|,)\s+(?!(?:achieving|obtaining|yielding|reaching|attaining|achieves?|obtains?|yields?|reaches?|attains?|"
    r"outperforms?|surpasses?|exceeds?|reports?|shows?|demonstrates?|which|where|is|are|was|were|has|have|had|serves?|acts?)\b)[A-Za-z0-9])",
    re.I,
)
_OUTER_COMPARE_SPLIT_RE = re.compile(
    r"(?:,\s*(?:and\s+(?!\s))?(?!\s)|(?<!\s)\s+(?!\s))(?:"
    r"(?:to\s+)?(?:outperform(?:s|ed|ing)?|surpass(?:es|ed|ing)?|exceed(?:s|ed|ing)?|"
    r"beat(?:s|ing)?|replace(?:s|d|ing)?|supersede(?:s|d|ing)?|"
    r"improv(?:e[sd]?|ing)(?:\s+(?:on|upon|over))?|overcom(?:e[sd]?|ing))|"
    r"replacing|superseding|"
    r"(?:(?:is|are|proves?|proving)\s+)?(?:superior|preferable)\s+to\b|"
    r"(?:(?:yielding|achieving|with|for)\s+(?:[A-Za-z0-9%.-]+\s+){0,3})?(?:gains?|improvements?|advantages?|speedups?|margins?)\s+over\b|"
    r"(?:as\s+(?:a|an)\s+)?alternative\s+to\b|depart(?:s|ed|ing)?\s+from\b|in\s+place\s+of\b|"
    r"compar(?:e|ed|ing)\b|unlike\b|against\b|versus\b|vs\.?\b|"
    r"in\s+contrast\s+(?:to|with)|as\s+opposed\s+to|instead\s+of|rather\s+than|"
    rf"{_COMP_THAN_PHRASE}"
    r")",
    re.I,
)
_CONTRASTIVE_PRIOR_CUE_RE = re.compile(
    r"\b(?:"
    r"to\s+(?:replace|improv(?:e|ing)(?:\s+(?:on|upon|over))?|extend|augment|supersede|outperform|surpass|exceed|beat|overcome|address|solve|mitigate)|"
    r"replacing|superseding|improv(?:e[sd]?|ing)(?:\s+(?:on|upon|over))?|"
    r"overcom(?:e[sd]?|ing)|extending|"
    r"without(?:\s+(?:relying\s+on|using|requiring|needing))?|"
    r"(?:(?:is|are|proves?|proving)\s+)?(?:superior|preferable)\s+to|"
    r"(?:(?:yielding|achieving|with|for)\s+(?:[A-Za-z0-9%.-]+\s+){0,3})?(?:gains?|improvements?|advantages?|speedups?|margins?)\s+over|"
    r"(?:as\s+(?:a|an)\s+)?alternative\s+to|depart(?:s|ed|ing)?\s+from|in\s+place\s+of|"
    r"outperform(?:s|ed|ing)?|surpass(?:es|ed|ing)?|exceed(?:s|ed|ing)?|beat(?:s|ing)?|"
    r"compar(?:e|ed|ing)(?:\s+(?:against|with|to))?|against|unlike|versus|vs\.?|"
    r"in\s+contrast\s+(?:to|with)|as\s+opposed\s+to|instead\s+of|rather\s+than|different\s+from|beyond|"
    rf"{_COMP_THAN_PHRASE}|"
    r"while|whereas|although|though|even\s+though|despite|in\s+spite\s+of|"
    r"because|since|"
    r"(?:motivated|driven|prompted)\s+by\s+(?:the\s+)?(?:flaws?|limitations?|drawbacks?|weaknesses?|failures?|gaps?|shortcomings?|bottlenecks?|issues?)\s+(?:of|in)|"
    r"(?:overcome|overcoming|address|addressing|solve|solving|mitigate|mitigating|eliminate|eliminating|fix|fixing)\s+"
    r"(?:the\s+)?(?:limitations?|drawbacks?|weaknesses?|flaws?|issues?|shortcomings?|gaps?)\s+(?:of|in)"
    r")\b",
    re.I,
)
_LIMITATION_VERB_RE = re.compile(
    r"\b(?:fail(?:s|ed|ing)?|struggl(?:e[sd]?|ing)|lack(?:s|ed|ing)?|suffer(?:s|ed|ing)?|"
    r"miss(?:es|ed|ing)?|omit(?:s|ted|ting)?|ignor(?:e[sd]?|ing)|cannot|can't|unable|incapable|"
    r"break(?:s|ing)?|broke|degrad(?:e[sd]?|ing)|collaps(?:e[sd]?|ing)|stall(?:s|ed|ing)?|"
    r"overfit(?:s|ting)?|underperform(?:s|ed|ing)?|lag(?:s|ged|ging)?|bottleneck\w*|limitation\w*)\b",
    re.I,
)
_OWN_NP_EXPLICIT_RE = re.compile(
    r"\b(?:our|this|proposed|new|novel|introduced|presented|developed|designed)\b",
    re.I,
)
_TITLE_COLON_BRAND_RE = re.compile(r"\b([A-Z][A-Za-z0-9-]{2,18})[ \t]*:[ \t]*([A-Za-z][^\n.;]{4,90})")
_SUBTITLE_METHOD_NOUN_RE = re.compile(
    r"\b(?:pipeline|framework|architecture|paradigm|system|engine|cascade|"
    r"network|model|method|retriever|reranker|ranker|approach|algorithm|router|encoder|decoder|module)\b",
    re.I,
)
_LOWER_SUBTITLE_HEAD_RE = re.compile(r"^(?:a|an|the|towards?)\s+[a-z]")
_SUBTITLE_NON_BRAND_HEAD_RE = re.compile(
    r"^(?:(?:a|an|the)\s+)?(?:baseline|prior|existing|standard|benchmark|dataset)\b|"
    r"^(?:is|are|was|were|has|have|had|can|could|may|might|will|would|does|do|did|"
    r"uses?|runs?|takes?|fails?|achieves?|evaluates?|compares?)\b",
    re.I,
)
_SUBTITLE_NON_BRAND_BODY_RE = re.compile(
    r"\b(?:baselines?|benchmarks?|datasets?|corpora|corpus|optimizers?|metrics?)\b",
    re.I,
)
_EVAL_TITLE_RE = re.compile(
    r"^\s*(?:evaluating|benchmarking|comparing|analyzing|analysing|studying|"
    r"(?:an?\s+)?(?:evaluation|benchmark|benchmarking|comparison|analysis|study)\s+of)\b",
    re.I,
)

_KNOWN_STANDARD_ACRONYMS = frozenset({
    "BM25", "RRF", "PDF", "OCR", "API", "JSON", "CLI", "SQL", "HTTP", "HTTPS",
    "CPU", "GPU", "TPU", "MLP", "CNN", "RNN", "LSTM", "GRU", "BERT", "LLM",
    "LLMS", "RAG", "DPO", "RLHF", "PPO", "GRPO", "ORPO", "KTO", "SFT", "MCP",
    "AUC", "ROC", "MRR", "NDCG", "BLEU", "ROUGE", "RMSE", "MAE", "MSE", "IID",
    "OOD", "HTML", "XML", "CSV", "SHA", "UUID", "URI", "URL", "DOI", "PMID",
    "PMCID", "NLP", "ML", "AI", "CS", "COCO", "FEVER", "ADAM", "ADAMW",
    "ADAGRAD", "RMSPROP", "LBFGS", "SGD", "VIT", "SWIN", "YOLO", "CLIP", "DINO",
    "LORA", "QLORA", "PEFT", "DETR", "SAM", "SQUAD", "MNLI", "SNLI", "GLUE",
    "SUPERGLUE", "MMLU", "GSM8K", "HUMANEVAL", "MBPP", "BEIR", "MSMARCO",
    "CIFAR", "MNIST", "IMAGENET", "CORA", "CITESEER", "PUBMED", "OGB", "WMT",
    "VQA", "GCN", "GAT", "GNN", "GAN", "VAE", "FAISS", "HNSW", "DPR",
    "COLBERT", "SPLADE", "ROBERTA", "DEBERTA", "LLAMA", "QWEN", "MISTRAL",
    "GEMMA", "RESNET", "DENSENET", "UNET", "CONVNEXT", "EFFICIENTNET", "CUDA",
    "TRITON", "VLLM", "ONNX", "FID", "SSIM", "PSNR", "IOU", "MAP", "PPL",
    "VLM", "VLMS", "SSM", "SSMS", "KAN", "KANS", "MOE", "BGE", "RWKV",
    "MLLM", "MLLMS", "VLA", "COT", "TOT", "DDPM", "DDIM", "NERF", "MCTS",
    "AWQ", "GPTQ", "FP8", "BF16",
})
_KNOWN_STANDARD_BASELINES = frozenset({
    "resnet", "graphnet", "bert", "densenet", "pointnet", "wavenet", "mobilenet",
    "convnext", "efficientnet", "tabnet", "vgg", "alexnet", "unet", "u-net",
    "roberta", "deberta", "t5", "gpt", "llama", "vit", "swin", "yolo",
    "colbert", "pytorch", "tensorflow", "huggingface", "imagenet",
})
_COMMON_COLON_LABELS = frozenset({
    "note", "notes", "results", "result", "methods", "method", "abstract",
    "introduction", "conclusion", "conclusions", "discussion", "setup",
    "dataset", "datasets", "baseline", "baselines", "evaluation", "experiment",
    "experiments", "summary", "overview", "limitation", "limitations", "example",
    "examples", "theorem", "lemma", "proof", "remark", "question", "answer",
    "problem", "solution", "contribution", "contributions", "observation",
    "case", "step", "phase", "stage", "task", "goal", "metric", "metrics",
    "table", "figure", "algorithm", "appendix", "setting", "settings",
    "training", "inference", "ablation", "analysis", "comparison", "details",
    "implementation", "hyperparameters", "study", "warning", "caution",
    "background", "methodology", "motivation", "preliminaries",
    "acknowledgments", "acknowledgements", "references", "takeaway",
    "verdict", "status", "hypothesis", "work", "data", "code", "part",
    "section", "module", "layer", "loss", "testing", "future", "ethics",
    "impact", "protocol",
    "architecture", "pipeline", "related", "terminology", "notation", "reproducibility",
    "todo", "fixme", "tip", "hint", "input", "inputs", "output", "outputs",
    "prompt", "prompts", "response", "responses", "error", "errors",
    "caveat", "caveats", "takeaways", "benchmark", "benchmarks",
    "cuda", "beir", "mmlu", "glue", "cifar", "cora", "sgd", "adam", "adamw",
})


def _nonblank(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


_PLACEHOLDER_RE = re.compile(
    r"^(?:n\.?/?a\.?|not\s+applicable|none(?:\s+yet)?|null|nil|t\.?b\.?[da]\.?|todo|pending|unknown|-+|_+|\.+|\?+)$",
    re.I,
)


def _nonplaceholder(value: Any) -> bool:
    return _nonblank(value) and not _PLACEHOLDER_RE.match(value.strip())


def _is_true_flag(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.strip().lower() in {"true", "yes", "1"})


def _is_false_flag(value: Any) -> bool:
    return value is False or (isinstance(value, str) and value.strip().lower() in {"false", "no", "0"})


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "loc"


def _normalized_ws(value: str) -> str:
    return " ".join(str(value).split())


def _contains_exact_quote(text: str, quote: str) -> bool:
    norm_text = _normalized_ws(text)
    norm_quote = _normalized_ws(quote)
    if not norm_quote:
        return False
    pattern = re.compile(rf"(?<!\w){re.escape(norm_quote)}(?!\w)")
    return bool(pattern.search(norm_text))


# ---------------------------------------------------------------------------
# Manuscript Normalization & Section Extraction
# ---------------------------------------------------------------------------


_LATEX_DELIM_RE = re.compile(r"\\[\[\]{}\\]|[\[\]{}]")
_HEADING_CMD_RE = re.compile(r"\\(?:title|(?:sub)*section|(?:sub)*paragraph)(?:\*|\b)")
_WRAPPER_CMD_RE = re.compile(
    r"\\(?:textbf|textit|emph|texttt|textrm|textsf|textsc|underline|mbox|textsl|mathrm|text)\b"
)
_CAPTION_CMD_RE = re.compile(r"\\caption(?:\*|\b)")
_LEGACY_FONT_OPEN_RE = re.compile(
    r"\{\\(?:bf|it|sc|rm|tt|em|sl|sf|bfseries|itshape|scshape|rmfamily|ttfamily|sffamily|upshape|mdseries)(?![A-Za-z])\s*"
)
_TEX_PROTECT_RE = re.compile(r"\\protect(?![A-Za-z])\s*")
_TEX_CMD_UNWRAP_RE = re.compile(
    r"\\(?P<heading>(?:title|(?:sub)*section|(?:sub)*paragraph)(?:\*|\b))"
    r"|\\(?P<caption_cmd>caption(?:\*|\b))"
    r"|\\(?P<texorpdf>texorpdfstring)\b"
    r"|\\(?P<wrapper>(?:textbf|textit|emph|texttt|textrm|textsf|textsc|underline|mbox|textsl|mathrm|text))\b"
    r"|(?P<legacy>\{\\(?:bf|it|sc|rm|tt|em|sl|sf|bfseries|itshape|scshape|rmfamily|ttfamily|sffamily|upshape|mdseries)(?![A-Za-z])\s*)"
)
_TEX_CMD_UNWRAP_NO_HEADING_RE = re.compile(
    r"\\(?P<caption_cmd>caption(?:\*|\b))"
    r"|\\(?P<texorpdf>texorpdfstring)\b"
    r"|\\(?P<wrapper>(?:textbf|textit|emph|texttt|textrm|textsf|textsc|underline|mbox|textsl|mathrm|text))\b"
    r"|(?P<legacy>\{\\(?:bf|it|sc|rm|tt|em|sl|sf|bfseries|itshape|scshape|rmfamily|ttfamily|sffamily|upshape|mdseries)(?![A-Za-z])\s*)"
)
_TEX_STRUCT_HINT_RE = re.compile(
    r"\\(?:documentclass|usepackage|begin\{|author\{|label\{|eq?ref\{|"
    r"textbf\{|textit\{|emph\{|textsc\{|texttt\{|textrm\{|textsf\{|underline\{|"
    r"texorpdfstring\{)|"
    r"\{\\(?:bf|it|sc|rm|tt|em|sl|sf)(?![A-Za-z])\s|"
    r"(?<!\\)%"
)


def _has_even_preceding_backslashes(text: str, idx: int) -> bool:
    bs = 0
    pos = idx - 1
    while pos >= 0 and text[pos] == "\\":
        bs += 1
        pos -= 1
    return (bs % 2) == 0


def _build_latex_match_tables(text: str) -> tuple[dict[int, int], dict[int, int]]:
    """Build O(N) bracket and brace closing index maps for LaTeX text."""
    bracket_close: dict[int, int] = {}
    brace_close: dict[int, int] = {}
    stack: list[tuple[str, int]] = []
    for m in _LATEX_DELIM_RE.finditer(text):
        tok = m.group(0)
        if len(tok) == 2:
            continue
        pos = m.start()
        if tok in "{[":
            stack.append((tok, pos))
        elif tok == "]":
            if stack and stack[-1][0] == "[":
                _, open_pos = stack.pop()
                bracket_close[open_pos] = pos
        elif tok == "}":
            while stack and stack[-1][0] == "[":
                stack.pop()
            if stack and stack[-1][0] == "{":
                _, open_pos = stack.pop()
                brace_close[open_pos] = pos
    return bracket_close, brace_close


def _match_cmd_args(
    text: str,
    cmd_end: int,
    bracket_close: dict[int, int],
    brace_close: dict[int, int],
    allow_opt: bool = True,
    num_braced: int = 1,
) -> tuple[int, list[tuple[int, int]]] | None:
    """Match optional [...] and num_braced {...} arguments in O(1) via precomputed tables."""
    n = len(text)
    pos = cmd_end
    while pos < n and text[pos].isspace():
        pos += 1
    if allow_opt and pos < n and text[pos] == "[":
        opt_end = bracket_close.get(pos)
        if opt_end is None:
            return None
        pos = opt_end + 1
        while pos < n and text[pos].isspace():
            pos += 1
    spans: list[tuple[int, int]] = []
    for _ in range(num_braced):
        if pos >= n or text[pos] != "{":
            return None
        end_brace = brace_close.get(pos)
        if end_brace is None:
            return None
        spans.append((pos + 1, end_brace))
        pos = end_brace + 1
        if len(spans) < num_braced:
            while pos < n and text[pos].isspace():
                pos += 1
    return pos, spans


def _unwrap_tex_commands(
    text: str,
    unwrap_headings: bool = True,
    max_depth: int = 8,
) -> str:
    """Recursively unwrap LaTeX headings, captions, wrappers, \\texorpdfstring, and legacy braces in O(N)."""
    work = _TEX_PROTECT_RE.sub("", text)
    if max_depth <= 0:
        return work
    cmd_re = _TEX_CMD_UNWRAP_RE if unwrap_headings else _TEX_CMD_UNWRAP_NO_HEADING_RE
    if not cmd_re.search(work):
        return work
    bracket_close, brace_close = _build_latex_match_tables(work)
    out: list[str] = []
    pos = 0
    n = len(work)
    while pos < n:
        m = cmd_re.search(work, pos)
        if m is None:
            out.append(work[pos:])
            break
        if m.start() > pos:
            out.append(work[pos:m.start()])
        if not _has_even_preceding_backslashes(work, m.start()):
            out.append(work[m.start() : m.start() + 1])
            pos = m.start() + 1
            continue
        grp = m.lastgroup
        if grp == "legacy":
            close_pos = brace_close.get(m.start())
            if close_pos is not None:
                out.append(
                    _unwrap_tex_commands(
                        work[m.end() : close_pos],
                        unwrap_headings=False,
                        max_depth=max_depth - 1,
                    )
                )
                pos = close_pos + 1
            else:
                out.append(work[m.start() : m.end()])
                pos = m.end()
        elif grp == "texorpdf":
            matched = _match_cmd_args(
                work, m.end(), bracket_close, brace_close, allow_opt=False, num_braced=2
            )
            if matched is not None:
                next_pos, spans = matched
                s1, e1 = spans[0]
                out.append(
                    _unwrap_tex_commands(
                        work[s1:e1],
                        unwrap_headings=False,
                        max_depth=max_depth - 1,
                    )
                )
                pos = next_pos
            else:
                out.append(work[m.start() : m.end()])
                pos = m.end()
        elif grp == "wrapper":
            matched = _match_cmd_args(
                work, m.end(), bracket_close, brace_close, allow_opt=False, num_braced=1
            )
            if matched is not None:
                next_pos, spans = matched
                s1, e1 = spans[0]
                out.append(
                    _unwrap_tex_commands(
                        work[s1:e1],
                        unwrap_headings=False,
                        max_depth=max_depth - 1,
                    )
                )
                pos = next_pos
            else:
                out.append(work[m.start() : m.end()])
                pos = m.end()
        elif grp == "caption_cmd":
            matched = _match_cmd_args(
                work, m.end(), bracket_close, brace_close, allow_opt=True, num_braced=1
            )
            if matched is not None:
                next_pos, spans = matched
                s1, e1 = spans[0]
                out.append(
                    _unwrap_tex_commands(
                        work[s1:e1],
                        unwrap_headings=False,
                        max_depth=max_depth - 1,
                    )
                )
                pos = next_pos
            else:
                out.append(work[m.start() : m.end()])
                pos = m.end()
        elif grp == "heading":
            matched = _match_cmd_args(
                work, m.end(), bracket_close, brace_close, allow_opt=True, num_braced=1
            )
            if matched is not None:
                next_pos, spans = matched
                s1, e1 = spans[0]
                inner_norm = _unwrap_tex_commands(
                    work[s1:e1],
                    unwrap_headings=False,
                    max_depth=max_depth - 1,
                )
                inner_clean = re.sub(r"\s+", " ", re.sub(r"(?<!\\)[{}]", "", inner_norm)).strip()
                nl_pos = work.find("\n", next_pos)
                rest_before_nl = work[next_pos:] if nl_pos == -1 else work[next_pos:nl_pos]
                if rest_before_nl.strip():
                    out.append(inner_clean + "\n")
                    while next_pos < n and work[next_pos] in " \t":
                        next_pos += 1
                else:
                    out.append(inner_clean)
                pos = next_pos
            else:
                out.append(work[m.start() : m.end()])
                pos = m.end()
        else:
            out.append(work[m.start() : m.end()])
            pos = m.end()
    return "".join(out)


def _looks_like_tex(text: str) -> bool:
    if _TEX_STRUCT_HINT_RE.search(text):
        # Avoid false positive on bare "%" unless there are no digit-% percentages or other TeX hints
        if re.search(
            r"\\(?:documentclass|usepackage|begin\{|author\{|label\{|eq?ref\{|"
            r"textbf\{|textit\{|emph\{|textsc\{|texttt\{|textrm\{|textsf\{|underline\{|"
            r"texorpdfstring\{)|\{\\(?:bf|it|sc|rm|tt|em|sl|sf)(?![A-Za-z])\s",
            text,
        ):
            return True
        if re.search(r"(?:^|\s|[.!?])%", text, re.M) and not re.search(r"\d\s*%", text):
            return True
    if _HEADING_CMD_RE.search(text) or _CAPTION_CMD_RE.search(text):
        bracket_close, brace_close = _build_latex_match_tables(text)
        for pat in (_HEADING_CMD_RE, _CAPTION_CMD_RE):
            for m in pat.finditer(text):
                if _has_even_preceding_backslashes(text, m.start()) and (
                    _match_cmd_args(text, m.end(), bracket_close, brace_close, allow_opt=True, num_braced=1)
                    is not None
                ):
                    return True
    if re.search(r"\\cite[a-zA-Z]*\*?(?:\[[^\[\]]*\]){0,2}\{", text):
        # Avoid stripping unescaped Markdown percentages (e.g. "14.2% recall gain") in cite-only hybrids
        if re.search(r"(?:^|\s|[.!?])%", text, re.M) and not re.search(r"\d\s*%", text):
            return True
    return False


def _normalize_manuscript(text: str, is_tex: bool | None = None) -> str:
    """Normalize LaTeX and Markdown formatting while preserving prose and numbers."""
    tex_mode = _looks_like_tex(text) if is_tex is None else is_tex
    if tex_mode:
        lines = [re.sub(r"(?<!\\)%.*$", "", ln) for ln in text.splitlines()]
        out = "\n".join(lines)
    else:
        out = text
    # Remove bib/references section if clearly demarcated at end
    out = re.sub(r"\\begin\{thebibliography\}[\s\S]*?\\end\{thebibliography\}", " ", out)
    out = re.sub(r"\\bibliography\{[^{}]*\}", " ", out)
    # Normalize LaTeX citations (including preceding ~) to [ref] before unwrapping wrappers
    out = re.sub(
        r"(?<!~)~*\\(?:cite[a-zA-Z]*\*?|textcite|parencite|autocite|footcite|fullcite|nocite)(?:\[[^\[\]]*\]){0,2}\{[^{}]+\}",
        " [ref] ",
        out,
    )
    out = re.sub(r"\\(?:label|index)\{[^{}]*\}", "", out)
    # Unwrap LaTeX formatting macros, captions, headings, \texorpdfstring, \protect, and legacy braces in O(N)
    out = _unwrap_tex_commands(out, unwrap_headings=True, max_depth=8)
    out = out.replace(r"\%", "%").replace("~", " ")
    # Unwrap inline $...$ around numbers/simple expressions
    out = re.sub(r"\$([^$\n]{1,40})\$", r" \1 ", out)
    # Strip Markdown formatting tokens
    out = re.sub(r"^\s{0,3}#{1,6}\s+", "", out, flags=re.M)
    out = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", out)
    out = re.sub(r"\*([^*\n]+)\*", r"\1", out)
    out = re.sub(r"`([^`\n]+)`", r"\1", out)
    return out


def _extract_braced_arg(text: str, macro_name: str) -> str | None:
    """Extract balanced-brace argument for a LaTeX macro such as \\title[Short]{...}."""
    cmd_re = re.compile(rf"\\{re.escape(macro_name)}(?:\*|\b)")
    if not cmd_re.search(text):
        return None
    bracket_close, brace_close = _build_latex_match_tables(text)
    for m in cmd_re.finditer(text):
        if not _has_even_preceding_backslashes(text, m.start()):
            continue
        matched = _match_cmd_args(text, m.end(), bracket_close, brace_close, allow_opt=True, num_braced=1)
        if matched is not None:
            _, spans = matched
            s1, e1 = spans[0]
            return text[s1:e1]
    return None


def _extract_sections(raw_text: str, is_tex: bool | None = None) -> dict[str, str]:
    """Extract normalized logical sections (title, abstract, tables, body)."""
    tex_mode = _looks_like_tex(raw_text) if is_tex is None else is_tex
    if tex_mode:
        clean_raw = "\n".join(re.sub(r"(?<!\\)%.*$", "", ln) for ln in raw_text.splitlines())
    else:
        clean_raw = raw_text

    title_parts: list[str] = []
    tex_title = _extract_braced_arg(clean_raw, "title")
    if tex_title is not None:
        title_parts.append(re.sub(r"\s+", " ", _normalize_manuscript(tex_title, is_tex=tex_mode)).strip())
    for ln in clean_raw.splitlines():
        hm = re.match(r"^\s*#\s+(.+)$", ln)
        if hm:
            title_parts.append(_normalize_manuscript(hm.group(1), is_tex=tex_mode))
            break

    abstract_parts: list[str] = []
    am = re.search(r"\\begin\{abstract\}([\s\S]*?)\\end\{abstract\}", clean_raw, re.I)
    if am:
        abstract_parts.append(_normalize_manuscript(am.group(1), is_tex=tex_mode))
    md_am = re.search(
        r"(?m)^[ \t]*#{1,3}\s+abstract\b[^\n]*\n([\s\S]*?)(?=\n[ \t]*#{1,3}\s+|\Z)",
        clean_raw,
        re.I,
    )
    if md_am:
        abstract_parts.append(_normalize_manuscript(md_am.group(1), is_tex=tex_mode))

    table_parts: list[str] = []
    table_spans: list[tuple[int, int]] = []
    for t_m in re.finditer(r"\\begin\{(table\*?)\}([\s\S]*?)\\end\{\1\}", clean_raw, re.I):
        table_spans.append((t_m.start(), t_m.end()))
        table_parts.append(_normalize_manuscript(t_m.group(2), is_tex=tex_mode))
    for t_m in re.finditer(r"\\begin\{(tabular\*?|tabularx|longtable)\}([\s\S]*?)\\end\{\1\}", clean_raw, re.I):
        if any(s <= t_m.start() and t_m.end() <= e for s, e in table_spans):
            continue
        table_parts.append(_normalize_manuscript(t_m.group(2), is_tex=tex_mode))
    for ln in clean_raw.splitlines():
        if "|" in ln and re.match(r"^\s*\|", ln):
            table_parts.append(_normalize_manuscript(ln, is_tex=tex_mode))

    # Strip references/bibliography tail on raw text before normalizing headers/macros
    split_positions: list[int] = []
    md_ref_m = re.search(
        r"(?m)^[ \t]*#{1,6}[ \t]+(?:\*{1,2})?(?:references|bibliography)(?:\*{1,2})?\b",
        clean_raw,
        flags=re.I,
    )
    if md_ref_m:
        split_positions.append(md_ref_m.start())
    bib_env_m = re.search(r"\\begin\{thebibliography\}", clean_raw, flags=re.I)
    if bib_env_m:
        split_positions.append(bib_env_m.start())
    if re.search(r"\\section(?:\*|\b)", clean_raw, flags=re.I):
        bracket_close_raw, brace_close_raw = _build_latex_match_tables(clean_raw)
        for sm in re.finditer(r"\\section(?:\*|\b)", clean_raw, flags=re.I):
            if not _has_even_preceding_backslashes(clean_raw, sm.start()):
                continue
            matched = _match_cmd_args(
                clean_raw, sm.end(), bracket_close_raw, brace_close_raw, allow_opt=True, num_braced=1
            )
            if matched is not None:
                _, spans = matched
                s1, e1 = spans[0]
                sec_txt = re.sub(
                    r"\s+",
                    " ",
                    re.sub(r"(?<!\\)[{}]", "", _normalize_manuscript(clean_raw[s1:e1], is_tex=True)),
                ).strip().lower()
                if sec_txt in {"references", "bibliography"}:
                    split_positions.append(sm.start())
                    break
    if split_positions:
        raw_no_refs = clean_raw[: min(split_positions)]
        body_no_refs = _normalize_manuscript(raw_no_refs, is_tex=tex_mode)
        norm_full = _normalize_manuscript(clean_raw, is_tex=tex_mode)
    else:
        raw_no_refs = clean_raw
        body_no_refs = _normalize_manuscript(raw_no_refs, is_tex=tex_mode)
        norm_full = body_no_refs

    heading_parts: list[str] = []
    for ln in raw_no_refs.splitlines():
        hm = re.match(r"^\s{0,3}(#{1,6})\s+(.+)$", ln)
        if hm:
            h_norm = _normalize_manuscript(hm.group(2), is_tex=tex_mode).strip()
            unnum = re.sub(r"^(?:\d+(?:\.\d+)*|[A-Z])\.\s+", "", h_norm)
            if h_norm and not _EVAL_TITLE_RE.match(unnum):
                heading_parts.append(h_norm)
    bracket_close_nr, brace_close_nr = _build_latex_match_tables(raw_no_refs)
    for sm in _HEADING_CMD_RE.finditer(raw_no_refs):
        if sm.group(0).startswith("\\title") or not _has_even_preceding_backslashes(raw_no_refs, sm.start()):
            continue
        matched = _match_cmd_args(
            raw_no_refs, sm.end(), bracket_close_nr, brace_close_nr, allow_opt=True, num_braced=1
        )
        if matched is not None:
            _, spans = matched
            s1, e1 = spans[0]
            h_norm = re.sub(
                r"\s+",
                " ",
                re.sub(r"(?<!\\)[{}]", "", _normalize_manuscript(raw_no_refs[s1:e1], is_tex=tex_mode)),
            ).strip()
            unnum = re.sub(r"^(?:\d+(?:\.\d+)*|[A-Z])\.\s+", "", h_norm)
            if h_norm and not _EVAL_TITLE_RE.match(unnum):
                heading_parts.append(h_norm)

    return {
        "title": "\n".join(title_parts),
        "abstract": "\n".join(abstract_parts),
        "tables": "\n".join(table_parts),
        "section_headings": "\n".join(heading_parts),
        "body": body_no_refs,
        "full": norm_full,
    }


def _has_complete_novelty_justification(method: dict[str, Any], source_map: dict[str, dict[str, Any]]) -> bool:
    closest = method.get("closest_work_source_ids")
    adjudication = method.get("human_adjudication")
    return (
        _nonblank(method.get("difference_evidence"))
        and isinstance(closest, list)
        and bool(closest)
        and all(sid in source_map for sid in closest)
        and isinstance(adjudication, dict)
        and _nonblank(adjudication.get("reviewer"))
        and _nonblank(adjudication.get("date"))
        and _nonblank(adjudication.get("rationale"))
    )


def _is_coined_colon_subtitle(acro: str, subtitle: str) -> bool:
    if (
        acro in _KNOWN_STANDARD_ACRONYMS
        or acro.lower() in _COMMON_COLON_LABELS
        or acro.lower() in _KNOWN_STANDARD_BASELINES
    ):
        return False
    if _SUBTITLE_NON_BRAND_HEAD_RE.match(subtitle):
        return False
    if _SUBTITLE_NON_BRAND_BODY_RE.search(subtitle) and not _SUBTITLE_METHOD_NOUN_RE.search(subtitle):
        return False
    if subtitle[0].isupper():
        return True
    return bool(_SUBTITLE_METHOD_NOUN_RE.search(subtitle))


def _name_looks_grandiose(name: str) -> bool:
    if not _nonblank(name):
        return False
    if _GRANDIOSE_ADJECTIVES_RE.search(name) or _GRANDIOSE_NOUNS_RE.search(name):
        return True
    if _COINED_BRAND_PREFIX_RE.search(name) or _COINED_BRAND_SUFFIX_RE.search(name):
        return True
    if any(_is_coined_colon_subtitle(m.group(1), m.group(2)) for m in _COLON_ACRONYM_RE.finditer(name)):
        return True
    return False


# ---------------------------------------------------------------------------
# Grandiose Branding & Overclaim Scanner
# ---------------------------------------------------------------------------


def _sentence_bounds(text: str, pos: int) -> tuple[int, int]:
    """Return [start, end) bounds of the sentence containing pos without splitting abbreviations."""
    start = 0
    end = len(text)
    for m in _SENT_SPLIT_RE.finditer(text):
        sep_end = m.end()
        if sep_end <= pos:
            start = max(start, sep_end)
        else:
            end = min(end, sep_end)
            break
    return start, end


def _is_in_baseline_role(sent: str, rs: int, re_: int) -> bool:
    """Return True iff the token at sent[rs:re_] occupies a baseline grammatical role."""
    left = sent[:rs]
    right = sent[re_:]
    semi_start = left.rfind(";") + 1
    left_semi = left[semi_start:]
    semi_end = right.find(";")
    right_semi = right if semi_end == -1 else right[:semi_end]

    if _RIGHT_BASELINE_PRED_RE.match(right_semi) or _RIGHT_BASELINE_LABEL_RE.match(right_semi):
        return True
    if _BASELINE_LIST_CUE_RE.search(left_semi):
        return True
    if _BASELINE_COMMA_PREFIX_RE.search(left_semi) and _BASELINE_COMMA_FOLLOW_RE.match(right_semi):
        return True
    if _RIGHT_LIST_CITED_RE.match(right_semi):
        if not _ACTIVE_OWN_VERB_RE.search(left_semi) and not _OWN_NP_BEFORE_RE.search(left_semi):
            return True
    return False


def _has_non_contrastive_prior_framing(region: str) -> bool:
    """Return True iff region contains prior-work framing not inside a comparative/contrastive/replacement phrase."""
    for pm in _PRIOR_WORK_FRAMING_RE.finditer(region):
        pre = region[: pm.start()]
        post = region[pm.end() :]
        clause_pre = re.split(r"[;:\n.!?]", pre)[-1]
        clean_pre = re.sub(r"\([^()\n]{0,120}\)", " ", clause_pre)
        last_cm = None
        for cm in _CONTRASTIVE_PRIOR_CUE_RE.finditer(clean_pre):
            last_cm = cm
        if last_cm is None:
            return True
        cue_txt = last_cm.group(0).lower()
        between = clean_pre[last_cm.end() :]
        post_head = re.split(r"[,;\n]", post, maxsplit=1)[0][:80]
        if cue_txt in {"because", "since"}:
            if not (_LIMITATION_VERB_RE.search(between) or _LIMITATION_VERB_RE.search(post_head)):
                return True
        if "," in between:
            is_list_cont = bool(re.search(r",\s*(?:and|or)\s*(?:other\s+)?$", between, re.I))
            is_exemplar_post = bool(
                re.match(
                    r"^\s*(?:such\s+as|like|including|namely|\(\s*(?:e\.g\.|for\s+example|such\s+as))",
                    post,
                    re.I,
                )
            )
            closes_phrase_post = (
                bool(re.match(r"^(?:[^,;.\n()]{0,40})(?:,|\)|$)", post))
                and not is_exemplar_post
            )
            is_concessive = cue_txt in {
                "while",
                "whereas",
                "although",
                "though",
                "even though",
                "because",
                "since",
            }
            clause_lim = is_concessive and bool(
                _LIMITATION_VERB_RE.search(between) or _LIMITATION_VERB_RE.search(post_head)
            )
            before_last_comma = between.rsplit(",", 1)[0]
            has_cap_before_comma = bool(re.search(r"\b[A-Z][A-Za-z0-9-]*\b", before_last_comma))
            has_base_noun_before_comma = bool(
                re.search(
                    r"\b(?:work|works|studies|study|methods?|models?|approaches?|systems?|baselines?)\b",
                    before_last_comma,
                    re.I,
                )
            )
            only_mods_before_comma = (not has_cap_before_comma) and (not has_base_noun_before_comma)
            if not (is_list_cont or closes_phrase_post or clause_lim or only_mods_before_comma):
                return True
    return False


def _is_subject_cited_prior_work(left_clause: str, join_region: str) -> bool:
    """Return True iff citations indicate the subject itself is prior work rather than joined constituents."""
    if _LEFT_PRIOR_CITE_RE.search(left_clause):
        return True
    if _LEFT_IN_CITE_RE.search(left_clause) and not _OWN_NP_EXPLICIT_RE.search(left_clause):
        return True
    cites = list(_CITE_ANY_RE.finditer(join_region))
    if len(cites) != 1:
        return False
    cm = cites[0]
    if _JOIN_CONTINUE_AFTER_CITE_RE.match(join_region[cm.end() :]):
        return False
    before = join_region[: cm.start()]
    if re.search(
        rf"\b(?:{_CLAUSE_JOIN_VERBS}|{_PARTICIPLE_JOIN_VERBS}|built\s+(?:on|upon)|based\s+(?:on|upon))\b",
        before,
        re.I,
    ):
        if re.match(r"^(?:from|by|proposed\s+by|introduced\s+by)\b", cm.group(0), re.I):
            return False
        if _CONSTITUENT_NAMED_TAIL_RE.search(before):
            return False
    return True


def _extract_local_clauses(sent: str, rs: int, re_: int) -> tuple[str, str]:
    """Return (left_clause, right_clause) around sent[rs:re_] with parenthetical contrasts masked."""
    chars = list(sent)
    for pm in _PAREN_CONTRAST_RE.finditer(sent):
        if pm.end() <= rs or pm.start() >= re_:
            for idx in range(pm.start(), pm.end()):
                chars[idx] = " "
    masked = "".join(chars)

    c_start = 0
    for cm in _CLAUSE_BREAK_RE.finditer(masked, 0, rs):
        c_start = max(c_start, cm.end())
    c_end = len(masked)
    cm_after = _CLAUSE_BREAK_RE.search(masked, re_)
    if cm_after:
        c_end = cm_after.start()

    return masked[c_start:rs], masked[re_:c_end]


def _has_own_work_in_sentence(sent: str, rs: int, re_: int) -> bool:
    """Return True iff the token at sent[rs:re_] has own-work framing in its local clause."""
    left_clause, right_clause = _extract_local_clauses(sent, rs, re_)

    for vm in _ACTIVE_OWN_VERB_RE.finditer(left_clause):
        if not _VERB_TO_BASELINE_BREAK_RE.search(left_clause[vm.end():]):
            return True
    np_m = _OWN_NP_BEFORE_RE.search(left_clause)
    if np_m:
        has_explicit_own = bool(_OWN_NP_EXPLICIT_RE.search(np_m.group(0)))
        join_region = _OUTER_COMPARE_SPLIT_RE.split(right_clause, maxsplit=1)[0]
        is_prior_indef = (not has_explicit_own) and (
            _has_non_contrastive_prior_framing(left_clause)
            or _has_non_contrastive_prior_framing(join_region)
            or bool(_LEFT_PRIOR_CITE_RE.search(left_clause))
            or bool(_LEFT_IN_CITE_RE.search(left_clause))
            or bool(re.match(rf"^\s*,?\s*(?:{_CITE_ANY_RE.pattern})", right_clause))
            or _is_subject_cited_prior_work(left_clause, join_region)
        )
        if not is_prior_indef:
            if "(" not in left_clause[np_m.start():]:
                return True
            last_paren = left_clause.rfind("(")
            after_paren = left_clause[last_paren + 1 :]
            close_idx = right_clause.find(")")
            inner_right = right_clause[:close_idx] if close_idx != -1 else ""
            after_ok = (not after_paren.strip()) or bool(
                re.search(
                    rf"(?:hereafter(?:\s+{_NAMING_CUE_WORDS})?|{_NAMING_CUE_WORDS}|namely)\s*$",
                    after_paren,
                    re.I,
                )
            )
            right_ok = (close_idx != -1) and not re.search(
                r"\b(?:baselines?|prior|existing|previous|earlier|adapted|inspired|building)\b|\b(?:19|20)\d{2}\b|\[ref\]|\[\d+\]",
                inner_right,
                re.I,
            )
            if after_ok and right_ok:
                return True
    if _PREP_OWN_BEFORE_RE.search(left_clause):
        return True
    if _PASSIVE_OWN_AFTER_RE.match(right_clause):
        return True
    app_m = _OWN_APPOSITIVE_AFTER_RE.match(right_clause)
    if app_m:
        matched_span = app_m.group(0)
        if re.search(r"\b(?:our|we)\b", matched_span, re.I) or _OWN_NP_EXPLICIT_RE.search(matched_span):
            return True
        if re.match(r"^\s*(?:,|\()", matched_span):
            join_region = _OUTER_COMPARE_SPLIT_RE.split(matched_span, maxsplit=1)[0]
        else:
            join_region = _OUTER_COMPARE_SPLIT_RE.split(right_clause, maxsplit=1)[0]
        if (
            not _has_non_contrastive_prior_framing(left_clause)
            and not _has_non_contrastive_prior_framing(join_region)
            and not _is_subject_cited_prior_work(left_clause, join_region)
        ):
            return True
    subj_join_m = _SUBJECT_JOIN_AFTER_RE.match(right_clause)
    if subj_join_m:
        interr = subj_join_m.group(1) or ""
        interr_is_prior = bool(
            interr
            and (
                _CITE_ANY_RE.search(interr)
                or re.search(r"\b(?:19|20)\d{2}\b", interr)
                or _has_non_contrastive_prior_framing(interr)
                or re.search(
                    r"^\s*[(,]\s*(?:a|an|the)?\s*(?:prior|existing|standard|conventional|popular|widely\s+used)?\s*baselines?\b",
                    interr,
                    re.I,
                )
            )
        )
        if not interr_is_prior:
            if re.search(rf"\b(?:in|for)\s+(?:our|this)\s+(?:{_METHOD_NOUN_RE}|work|paper|study)\b", right_clause, re.I):
                return True
            join_region = _OUTER_COMPARE_SPLIT_RE.split(right_clause[subj_join_m.start(2) :], maxsplit=1)[0]
            if (
                not _has_non_contrastive_prior_framing(left_clause)
                and not _has_non_contrastive_prior_framing(join_region)
                and not _is_subject_cited_prior_work(left_clause, join_region)
            ):
                return True
    if (
        _SUBJECT_SUPERIOR_OVER_PRIOR_RE.match(right_clause)
        and not _has_non_contrastive_prior_framing(left_clause)
        and not _LEFT_PRIOR_CITE_RE.search(left_clause)
        and not _LEFT_IN_CITE_RE.search(left_clause)
        and not _CITE_ANY_RE.search(right_clause)
    ):
        return True
    return False


def _scan_grandiose_branding(
    sections: dict[str, str],
    ledger: dict[str, Any],
    source_map: dict[str, dict[str, Any]],
) -> tuple[list[str], list[dict[str, Any]]]:
    issues: list[str] = []
    findings: list[dict[str, Any]] = []
    text = sections["body"]
    header_zone = (sections["title"] + "\n" + sections["abstract"]).strip()
    heading_zone = sections.get("section_headings", "")
    heading_line_set = {ln.strip() for ln in heading_zone.splitlines() if ln.strip()}

    def _section_body_after(pos: int) -> str:
        nl = text.find("\n", pos)
        if nl == -1:
            return ""
        chunks: list[str] = []
        for ln in text[nl + 1 :].splitlines():
            st = ln.strip()
            if st and st in heading_line_set:
                break
            chunks.append(ln)
            if sum(len(c) for c in chunks) >= 1200:
                break
        return "\n".join(chunks)

    def _classify_heading_section(sec_body: str, head_tokens: tuple[str, ...]) -> tuple[bool, bool]:
        sec_own = False
        for s_m in re.finditer(r"[^\n.!?]+(?:[.!?]|$)", sec_body):
            s_txt = s_m.group(0)
            if _METHOD_CREATION_CUE_RE.search(s_txt):
                is_baseline_mention = False
                for ht in head_tokens:
                    if not ht:
                        continue
                    for hm in re.finditer(rf"\b{re.escape(ht)}\b", s_txt):
                        if _is_in_baseline_role(s_txt, hm.start(), hm.end()) and not _has_own_work_in_sentence(
                            s_txt, hm.start(), hm.end()
                        ):
                            is_baseline_mention = True
                            break
                    if is_baseline_mention:
                        break
                if not is_baseline_mention:
                    sec_own = True
                    break
        if not sec_own:
            for ht in head_tokens:
                if not ht:
                    continue
                for hm in re.finditer(rf"\b{re.escape(ht)}\b", sec_body):
                    hs, he = _sentence_bounds(sec_body, hm.start())
                    h_sent = sec_body[hs:he]
                    hrs = hm.start() - hs
                    hre = hm.end() - hs
                    if not _is_in_baseline_role(h_sent, hrs, hre) and _has_own_work_in_sentence(h_sent, hrs, hre):
                        sec_own = True
                        break
                if sec_own:
                    break
        has_cite = bool(
            re.search(
                rf"\[ref\]|\[\d+(?:\s*[,–-]\s*\d+)*\]|\({_SURNAME}(?:\s+et\s+al\.)?,?\s*(?:19|20)\d{{2}}[a-z]?\)",
                sec_body,
            )
        )
        has_against_head = any(
            re.search(
                rf"\b(?:against|than|to|with|unlike|versus|vs\.?|replace|outperform\w*|surpass\w*|exceed\w*)\s+(?:the\s+)?{re.escape(ht)}\b",
                sec_body,
                re.I,
            )
            for ht in head_tokens
            if ht
        )
        sec_prior = (_has_non_contrastive_prior_framing(sec_body) or has_cite or has_against_head) and not sec_own
        return sec_own, sec_prior

    methods_list = [m for m in ledger.get("methods", []) if isinstance(m, dict)]
    method_origins = {m.get("origin") for m in methods_list if m.get("origin")}
    has_combined_or_adapted = bool(method_origins & {"combined", "adapted"})
    has_unverified_new = any(
        m.get("origin") == "newly_derived"
        and not (
            (_nonblank(m.get("derivation_evidence")) or _nonblank(m.get("difference_evidence")))
            and _has_complete_novelty_justification(m, source_map)
        )
        for m in methods_list
    )
    is_eval_paper = bool(_EVAL_TITLE_RE.match(sections["title"].strip()))

    for m in _GRANDIOSE_ADJECTIVES_RE.finditer(text):
        findings.append({"rule": "G1_hype_modifier", "match": m.group(0)})
    for m in _GRANDIOSE_NOUNS_RE.finditer(text):
        findings.append({"rule": "G1_grandiose_noun", "match": m.group(0)})

    header_own_tokens: set[str] = set()
    for is_title, h_zone in ((True, sections["title"]), (False, sections["abstract"])):
        if not h_zone.strip():
            continue
        for pat in (_COINED_BRAND_PREFIX_RE, _COINED_BRAND_SUFFIX_RE):
            for hm in pat.finditer(h_zone):
                if _YEAR_CITATION_AFTER_RE.match(h_zone[hm.end() : hm.end() + 30]):
                    continue
                hs, he = _sentence_bounds(h_zone, hm.start())
                h_sent = h_zone[hs:he]
                hrs = hm.start() - hs
                hre = hm.end() - hs
                if _is_in_baseline_role(h_sent, hrs, hre):
                    continue
                if is_title and _EVAL_TITLE_RE.match(h_sent) and not _has_own_work_in_sentence(h_sent, hrs, hre):
                    continue
                header_own_tokens.add(hm.group(0))

    # Coined brand compounds (exclude cited prior work and legitimate baselines)
    for pat in (_COINED_BRAND_PREFIX_RE, _COINED_BRAND_SUFFIX_RE):
        for m in pat.finditer(text):
            after = text[m.end() : m.end() + 30]
            if _YEAR_CITATION_AFTER_RE.match(after):
                continue
            tok = m.group(0)
            base_tok = re.sub(r"[-_]?\d+$", "", tok.lower())
            s_start, s_end = _sentence_bounds(text, m.start())
            sent_full = text[s_start:s_end]
            rs = m.start() - s_start
            re_ = m.end() - s_start

            if _is_in_baseline_role(sent_full, rs, re_):
                continue

            if base_tok in _KNOWN_STANDARD_BASELINES:
                claimed_as_own = bool(
                    re.search(
                        rf"\b(?:we\s+(?:propose|introduce|present|design|develop|name|call)|"
                        rf"our\s+(?:proposed|new)\s+(?:method|model|framework|architecture))\b[^.\n]{{0,40}}\b{re.escape(tok)}\b",
                        sent_full,
                        re.I,
                    )
                )
                if not claimed_as_own:
                    continue
            elif tok not in header_own_tokens and not _has_own_work_in_sentence(sent_full, rs, re_):
                continue

            findings.append({"rule": "G1_coined_compound", "match": tok})

    # G2: Coined acronym/brand definitions (ACRO: Expanded Name, Brand: Tagline, or Expanded Name (ACRO))
    for m in _COLON_ACRONYM_RE.finditer(text):
        acro = m.group(1)
        subtitle = m.group(2)
        if not _is_coined_colon_subtitle(acro, subtitle):
            continue
        if _YEAR_CITATION_AFTER_RE.match(text[m.end() : m.end() + 30]):
            continue
        s_start, s_end = _sentence_bounds(text, m.start())
        sent_full = text[s_start:s_end]
        rs = m.start() - s_start
        re_ = m.end() - s_start
        if _is_in_baseline_role(sent_full, rs, re_):
            continue
        has_own = _has_own_work_in_sentence(sent_full, rs, re_) or bool(
            _OWN_WORK_CUE_RE.search(sent_full[:rs]) and not _VERB_TO_BASELINE_BREAK_RE.search(sent_full[:rs])
        )
        has_coined_morph = bool(
            _COINED_BRAND_PREFIX_RE.search(m.group(0))
            or _COINED_BRAND_SUFFIX_RE.search(m.group(0))
            or _COINED_ACRONYM_MORPH_RE.match(acro)
        )
        if _SUBTITLE_NON_BRAND_BODY_RE.search(subtitle) and not has_own and not (
            has_coined_morph and _SUBTITLE_METHOD_NOUN_RE.search(subtitle)
        ):
            continue
        left_c, right_c = _extract_local_clauses(sent_full, rs, re_)
        join_r = _OUTER_COMPARE_SPLIT_RE.split(right_c, maxsplit=1)[0]
        in_prior = _has_non_contrastive_prior_framing(left_c) or _has_non_contrastive_prior_framing(join_r)
        in_header = m.group(0) in header_zone and not (
            _EVAL_TITLE_RE.match(sent_full.strip()) or (in_prior and not has_own)
        )
        in_heading = m.group(0).strip() in heading_zone and not in_header
        if in_prior and not has_own and not in_heading:
            continue
        heading_flagged = False
        if in_heading:
            sec_body = _section_body_after(m.end())
            sec_own, sec_prior = _classify_heading_section(sec_body, (acro,))
            heading_flagged = sec_own or (
                (has_combined_or_adapted or has_unverified_new)
                and not is_eval_paper
                and not sec_prior
            )
        if in_header or heading_flagged or has_own or has_coined_morph:
            findings.append({"rule": "G2_coined_acronym", "match": m.group(0).strip()})

    for m in _TITLE_COLON_BRAND_RE.finditer(text):
        brand = m.group(1)
        subtitle = m.group(2)
        if (
            brand.isupper()
            or brand in _KNOWN_STANDARD_ACRONYMS
            or brand.lower() in _COMMON_COLON_LABELS
            or brand.lower() in _KNOWN_STANDARD_BASELINES
        ):
            continue
        if _SUBTITLE_NON_BRAND_HEAD_RE.match(subtitle):
            continue
        if subtitle[0].islower() and not _SUBTITLE_METHOD_NOUN_RE.search(subtitle):
            continue
        s_start, s_end = _sentence_bounds(text, m.start())
        sent_full = text[s_start:s_end]
        rs = m.start() - s_start
        re_ = m.end() - s_start
        if _is_in_baseline_role(sent_full, rs, re_):
            continue
        in_own_intro = _has_own_work_in_sentence(sent_full, rs, re_) or bool(
            re.search(
                rf"\b(?:we\s+(?:propose|introduce|present|design|develop|combine|name|call)|"
                rf"(?:this|our)\s+(?:paper|work|study)\s+(?:proposes?|introduces?|presents?|designs?|develops?|combines?)|"
                rf"our(?:\s+{_NON_OWN_MOD_RE}){{0,4}}\s+{_METHOD_NOUN_RE})\b",
                sent_full[:rs],
                re.I,
            )
            and not _VERB_TO_BASELINE_BREAK_RE.search(sent_full[:rs])
        )
        if _SUBTITLE_NON_BRAND_BODY_RE.search(subtitle) and not in_own_intro:
            continue
        has_coined_morph = bool(
            _COINED_BRAND_PREFIX_RE.search(m.group(0))
            or _COINED_BRAND_SUFFIX_RE.search(m.group(0))
        )
        left_c, right_c = _extract_local_clauses(sent_full, rs, re_)
        join_r = _OUTER_COMPARE_SPLIT_RE.split(right_c, maxsplit=1)[0]
        in_prior = _has_non_contrastive_prior_framing(left_c) or _has_non_contrastive_prior_framing(join_r)
        in_header = m.group(0) in header_zone and not (
            _EVAL_TITLE_RE.match(sent_full.strip()) or (in_prior and not in_own_intro)
        )
        in_header_tagline = in_header and (
            bool(_SUBTITLE_METHOD_NOUN_RE.search(subtitle)) or has_combined_or_adapted or has_coined_morph
        )
        in_heading = m.group(0).strip() in heading_zone and not in_header
        heading_flagged = False
        if in_heading:
            sec_body = _section_body_after(m.end())
            sec_own, sec_prior = _classify_heading_section(sec_body, (brand,))
            heading_flagged = sec_own or has_coined_morph or (
                (has_combined_or_adapted or has_unverified_new)
                and not is_eval_paper
                and not sec_prior
            )
        if in_own_intro or in_header_tagline or heading_flagged:
            findings.append({"rule": "G2_coined_branding", "match": m.group(0).strip()})

    for m in _PAREN_ACRONYM_RE.finditer(text):
        acro = m.group(2)
        if acro in _KNOWN_STANDARD_ACRONYMS:
            continue
        after = text[m.end() : m.end() + 30]
        if _YEAR_CITATION_AFTER_RE.match(after):
            continue
        s_start, s_end = _sentence_bounds(text, m.start())
        sent_full = text[s_start:s_end]
        rs = m.start() - s_start
        re_ = m.end() - s_start
        if _is_in_baseline_role(sent_full, rs, re_):
            continue
        has_own = _has_own_work_in_sentence(sent_full, rs, re_)
        left_c, right_c = _extract_local_clauses(sent_full, rs, re_)
        join_r = _OUTER_COMPARE_SPLIT_RE.split(right_c, maxsplit=1)[0]
        in_prior = _has_non_contrastive_prior_framing(left_c) or _has_non_contrastive_prior_framing(join_r)
        if in_prior and not has_own:
            continue
        has_coined_morph = bool(
            _COINED_BRAND_PREFIX_RE.search(m.group(0))
            or _COINED_BRAND_SUFFIX_RE.search(m.group(0))
            or _COINED_ACRONYM_MORPH_RE.match(acro)
        )
        in_header = m.group(0) in header_zone and not _EVAL_TITLE_RE.match(sent_full.strip())
        in_heading = m.group(0).strip() in heading_zone and not in_header
        heading_flagged = False
        if in_heading:
            sec_body = _section_body_after(m.end())
            sec_own, sec_prior = _classify_heading_section(sec_body, (acro,))
            heading_flagged = sec_own or (
                (has_combined_or_adapted or has_unverified_new)
                and not is_eval_paper
                and not sec_prior
            )
        if in_header or heading_flagged or has_own or has_coined_morph:
            findings.append({"rule": "G2_coined_acronym", "match": m.group(0).strip()})

    for m in _NAMING_CUE_ACRONYM_RE.finditer(text):
        acro = m.group(1)
        if acro in _KNOWN_STANDARD_ACRONYMS or acro.lower() in _KNOWN_STANDARD_BASELINES:
            continue
        after = text[m.end() : m.end() + 50]
        if _YEAR_CITATION_AFTER_RE.match(after):
            continue
        s_start, s_end = _sentence_bounds(text, m.start())
        sent_full = text[s_start:s_end]
        rs = m.start(1) - s_start
        re_ = m.end(1) - s_start
        if _is_in_baseline_role(sent_full, rs, re_):
            continue
        has_explicit_own_prefix = bool(_OWN_NP_EXPLICIT_RE.search(m.group(0)[: m.start(1) - m.start()]))
        left_c, right_c = _extract_local_clauses(sent_full, rs, re_)
        join_r = _OUTER_COMPARE_SPLIT_RE.split(right_c, maxsplit=1)[0]
        if (
            not has_explicit_own_prefix
            and not _has_own_work_in_sentence(sent_full, rs, re_)
            and (
                _has_non_contrastive_prior_framing(left_c)
                or _has_non_contrastive_prior_framing(join_r)
                or bool(_LEFT_PRIOR_CITE_RE.search(left_c))
                or bool(_LEFT_IN_CITE_RE.search(left_c))
                or _is_subject_cited_prior_work(left_c, join_r)
                or bool(re.match(rf"^\s*,?\s*(?:{_CITE_ANY_RE.pattern})", after))
            )
        ):
            continue
        findings.append({"rule": "G2_coined_acronym", "match": acro})

    # Check declared method names/aliases appearing with framework/novelty language
    for method in ledger.get("methods", []):
        if not isinstance(method, dict):
            continue
        names: list[str] = []
        if _nonblank(method.get("name")):
            names.append(method["name"].strip())
        if isinstance(method.get("aliases"), list):
            names.extend(a.strip() for a in method["aliases"] if _nonblank(a))
        for nm in names:
            if _name_looks_grandiose(nm) and nm.lower() in text.lower():
                findings.append({"rule": "G2_declared_name", "match": nm})

    # Apply gating independent of grand_name boolean
    if findings:
        methods = [m for m in ledger.get("methods", []) if isinstance(m, dict)]
        if not methods:
            issues.append("undeclared_method_branding:manuscript")
        else:
            for m in methods:
                mid = m.get("id", "unknown")
                origin = m.get("origin")
                if origin in {"reused", "adapted", "combined"}:
                    issues.append(f"inflated_method_name:{mid}")
                    issues.append(f"grandiose_branding_detected:{mid}")
                elif origin == "newly_derived":
                    has_deriv = _nonblank(m.get("derivation_evidence")) or _nonblank(m.get("difference_evidence"))
                    if not (has_deriv and _has_complete_novelty_justification(m, source_map)):
                        issues.append(f"unsupported_newly_derived_method:{mid}")
                        issues.append(f"inflated_method_name:{mid}")

    # G3: Unsupported novelty overclaims
    if _NOVELTY_OVERCLAIM_RE.search(text):
        has_verified_novelty = any(
            isinstance(m, dict)
            and m.get("novelty_claimed") is True
            and m.get("origin") != "reused"
            and _has_complete_novelty_justification(m, source_map)
            for m in ledger.get("methods", [])
        )
        if not has_verified_novelty:
            issues.append("unsupported_novelty_overclaim:manuscript")
            findings.append({"rule": "G3_novelty_overclaim", "match": _NOVELTY_OVERCLAIM_RE.search(text).group(0)})

    # G4: Problem inflation / dramatization & extraneous boilerplate padding
    pi_text = _CATASTROPHIC_FORGETTING_EXEMPT_RE.sub(" [term] ", text)
    pi_m = _PROBLEM_INFLATION_RE.search(pi_text)
    if pi_m:
        issues.append("problem_inflation_detected:manuscript")
        findings.append({"rule": "G4_problem_inflation", "match": pi_m.group(0)})
    pad_m = _EXTRANEOUS_PADDING_RE.search(pi_text)
    if pad_m:
        issues.append("extraneous_padding_detected:manuscript")
        findings.append({"rule": "G5_extraneous_padding", "match": pad_m.group(0)})

    return issues, findings


# ---------------------------------------------------------------------------
# Manuscript Numeric & Claim Verification
# ---------------------------------------------------------------------------


def _is_percent_occurrence(value: Any, unit: Any) -> bool:
    vs = str(value).strip()
    us = str(unit).strip()
    if vs.endswith("%") or "%" in us:
        return True
    return bool(re.search(r"\b(?:percent|pct|percentage)\b(?!\s+points?\b)", us, re.I))


def _number_variants(value: Any, unit: str) -> list[str]:
    s = str(value).strip()
    variants = {s}
    try:
        base_s = re.sub(r"\s*(?:%|percent|pct)$", "", s, flags=re.I).strip()
        f = float(base_s.replace(",", ""))
        variants.add(f"{f:g}")
        if _is_percent_occurrence(value, unit):
            variants.add(f"{f:g}%")
            variants.add(f"{f:g} percent")
            variants.add(f"{base_s}%")
            variants.add(f"{base_s} percent")
            variants.add(base_s)
    except ValueError:
        pass
    return sorted(variants, key=len, reverse=True)


def _match_number_in_text(text: str, value: Any, unit: str) -> bool:
    for v in _number_variants(value, unit):
        pat = re.compile(rf"(?<![\d.]){re.escape(v)}(?![\d])")
        if pat.search(text):
            return True
    return False


def _canonical_partitioned_num_sets(ledger: dict[str, Any]) -> tuple[set[float], set[float]]:
    pct_nums: set[float] = set()
    non_pct_nums: set[float] = set()
    for fact in ledger.get("numeric_facts", []):
        if not isinstance(fact, dict):
            continue
        for occ in fact.get("occurrences", []):
            if not isinstance(occ, dict):
                continue
            raw_v = re.sub(r"\s*(?:%|percent|pct)$", "", str(occ.get("value", "")).strip(), flags=re.I)
            raw_v = raw_v.replace(",", "").strip()
            try:
                val_f = float(raw_v)
            except ValueError:
                continue
            if _is_percent_occurrence(occ.get("value", ""), occ.get("unit", "")):
                pct_nums.add(val_f)
            else:
                non_pct_nums.add(val_f)
    return pct_nums, non_pct_nums


def _canonical_num_set(ledger: dict[str, Any]) -> set[float]:
    pct_nums, non_pct_nums = _canonical_partitioned_num_sets(ledger)
    return pct_nums | non_pct_nums


def _check_manuscript_claims_and_numbers(
    sections: dict[str, str],
    ledger: dict[str, Any],
) -> tuple[list[str], list[dict[str, Any]]]:
    issues: list[str] = []
    checks: list[dict[str, Any]] = []
    full_body = sections["body"]

    # 1. Declared numeric_facts vs manuscript
    for fact in ledger.get("numeric_facts", []):
        if not isinstance(fact, dict) or not _nonblank(fact.get("id")):
            continue
        fid = fact["id"]
        for occ in fact.get("occurrences", []):
            if not isinstance(occ, dict) or not _nonblank(occ.get("location")):
                continue
            loc = occ["location"]
            val = occ.get("value")
            unit = str(occ.get("unit", ""))
            if val is None or isinstance(val, bool):
                continue
            loc_low = loc.lower()
            target_text = full_body
            if "abstract" in loc_low and sections["abstract"].strip():
                target_text = sections["abstract"]
            elif "table" in loc_low and sections["tables"].strip():
                target_text = sections["tables"]
            elif "title" in loc_low and sections["title"].strip():
                target_text = sections["title"]

            in_target = _match_number_in_text(target_text, val, unit)
            in_body = _match_number_in_text(full_body, val, unit)
            checks.append({
                "fact_id": fid,
                "location": loc,
                "value": val,
                "in_target": in_target,
                "in_body": in_body,
            })
            if not in_target:
                issues.append(f"manuscript_numeric_fact_missing:{fid}:{_slug(loc)}")

    # 2. Undeclared result numbers in manuscript
    pct_declared_floats, non_pct_declared_floats = _canonical_partitioned_num_sets(ledger)
    # Strip structural references like Section 2.1, Fig. 3.2, Table 1, Eq. (2.1), years, versions, URLs
    _STRUCT_REF_RE = re.compile(
        r"\b(?:Section|Sec|Fig|Figure|Table|Eq|Equation|Algorithm|Alg|Appendix|Chapter|"
        r"Theorem|Thm|Lemma|Proposition|Prop|Corollary|Definition|Def|Remark|Listing|Step)s?"
        r"\.?\s*(?:\(\s*)?\d+(?:\.\d+)*\s*\)?",
        re.I,
    )

    def _scrub_non_result_numbers(zone_raw: str) -> str:
        s = _STRUCT_REF_RE.sub(" ", zone_raw)
        s = re.sub(r"https?://\S+", " ", s)
        s = re.sub(
            r"\b(?:Python|PyTorch|TensorFlow|CUDA|JAX|Llama|Qwen|Mistral|Claude|GPT|v|version)\s*[-:]?\s*\d+(?:\.\d+)+\b",
            " ",
            s,
            flags=re.I,
        )
        s = re.sub(r"\bv?\d+\.\d+(?:\.\d+)+\b", " ", s, flags=re.I)
        s = re.sub(r"\bv\d+(?:\.\d+)+\b", " ", s, flags=re.I)
        s = re.sub(r"\b(?:19|20)\d{2}\b", " ", s)
        s = re.sub(r"\b10\.\d{4,9}/\S+", " ", s)
        s = re.sub(r"\b\d{4}\.\d{4,5}(?:v\d+)?\b", " ", s)
        return s

    scrubbed = _scrub_non_result_numbers(full_body)

    candidates: list[tuple[str, float]] = []
    # Percentages (including "85%" and "85 percent" / "85 pct")
    for m in re.finditer(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:%|percent\b|pct\b)", scrubbed, re.I):
        candidates.append((f"{m.group(1)}%", float(m.group(1))))
    # Metric-paired numbers (excluding percentages already captured above)
    metric_words = r"(?:gain|improvement|accuracy|acc|f1|auc|mrr|ndcg|bleu|rouge|pp|points|sota|score|precision|recall|error|latency|speedup)"
    for m in re.finditer(rf"(?<![\d.])(\d+(?:\.\d+)?)(?!\s*(?:%|percent\b|pct\b))\s*{metric_words}\b", scrubbed, re.I):
        candidates.append((m.group(1), float(m.group(1))))
    for m in re.finditer(rf"\b{metric_words}\s*(?:[:=]|of|is|was|reaches|achieves)\s*(\d+(?:\.\d+)?)(?![\d.]|\s*(?:%|percent\b|pct\b))", scrubbed, re.I):
        candidates.append((m.group(1), float(m.group(1))))
    # Standalone result decimals in body, abstract, or tables (e.g. "obtains 0.88 on MMLU", \textbf{0.85})
    for zone_text in (scrubbed, _scrub_non_result_numbers(sections["abstract"]), _scrub_non_result_numbers(sections["tables"])):
        for m in re.finditer(r"(?<![\d.])(\d+\.\d+)(?![\d]|\s*(?:%|percent\b|pct\b))", zone_text, re.I):
            candidates.append((m.group(1), float(m.group(1))))

    percent_raws = {raw for raw, _ in candidates if raw.endswith("%")}
    seen_undeclared: set[str] = set()
    for raw_num, val_f in candidates:
        is_pct_cand = raw_num.endswith("%")
        if not is_pct_cand and f"{raw_num}%" in percent_raws:
            continue
        target_set = pct_declared_floats if is_pct_cand else non_pct_declared_floats
        matched = any(abs(val_f - d) <= 1e-9 for d in target_set)
        if not matched and raw_num not in seen_undeclared:
            seen_undeclared.add(raw_num)
            issues.append(f"undeclared_manuscript_numeric_claim:{raw_num}")

    # 3. Claim text/excerpt & [claim:C...] markers
    claim_ids = {c.get("id") for c in ledger.get("claims", []) if isinstance(c, dict) and _nonblank(c.get("id"))}
    for claim in ledger.get("claims", []):
        if not isinstance(claim, dict) or not _nonblank(claim.get("id")):
            continue
        cid = claim["id"]
        ctext = claim.get("text") or claim.get("excerpt")
        if _nonblank(ctext):
            if _normalized_ws(ctext).lower() not in _normalized_ws(sections["full"]).lower():
                issues.append(f"manuscript_claim_not_found:{cid}")

    for m in re.finditer(r"\[claim:([A-Za-z0-9_-]+)\]", sections["full"]):
        cid = m.group(1)
        if cid not in claim_ids:
            issues.append(f"unknown_manuscript_claim_marker:{cid}")

    # 4. Unsupported side claims appearing in manuscript without source_ids/evidence_ids
    norm_full_low = _normalized_ws(sections["full"]).lower()
    for claim in ledger.get("claims", []):
        if not isinstance(claim, dict) or not _nonblank(claim.get("id")):
            continue
        cid = claim["id"]
        if claim.get("kind") in {"reported", "inferred"} and not claim.get("source_ids") and not claim.get("evidence_ids"):
            ctext = claim.get("text") or claim.get("excerpt")
            if claim.get("side_claim") is True or (_nonblank(ctext) and _normalized_ws(ctext).lower() in norm_full_low):
                issues.append(f"unsupported_side_claim:{cid}")

    return issues, checks


# ---------------------------------------------------------------------------
# Local --sources-dir Verification
# ---------------------------------------------------------------------------


def _v2_spans_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for span in value:
        if isinstance(span, str):
            parts.append(span)
        elif isinstance(span, dict):
            if isinstance(span.get("content"), str):
                parts.append(span["content"])
            elif isinstance(span.get("text"), str):
                parts.append(span["text"])
            elif isinstance(span.get("content"), list):
                sub = _v2_spans_text(span["content"])
                if sub:
                    parts.append(sub)
    return "".join(parts)


def _v2_extract_text(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        if _nonblank(item.get("text")):
            return item["text"]
        if isinstance(item.get("content"), str):
            return item["content"]
        if isinstance(item.get("content"), dict):
            c = item["content"]
            for k in ("text", "markdown", "latex", "caption"):
                if _nonblank(c.get(k)):
                    return c[k]
            # Native MinerU Content List V2 nested span containers
            for k in ("paragraph_content", "title_content", "page_footnote_content", "algorithm_content", "code_content"):
                txt = _v2_spans_text(c.get(k))
                if _nonblank(txt):
                    return txt
            mc = c.get("math_content")
            if _nonblank(mc):
                return mc
            if isinstance(mc, list):
                txt = _v2_spans_text(mc)
                if _nonblank(txt):
                    return txt
            if isinstance(c.get("list_items"), list):
                list_txt = " ".join(
                    _v2_spans_text(li.get("item_content"))
                    for li in c["list_items"]
                    if isinstance(li, dict)
                ).strip()
                if _nonblank(list_txt):
                    return list_txt
            parts: list[str] = []
            for k in ("table_caption", "table_footnote", "image_caption", "image_footnote", "chart_caption", "chart_footnote"):
                txt = _v2_spans_text(c.get(k))
                if _nonblank(txt):
                    parts.append(txt.strip())
            if _nonblank(c.get("html")):
                parts.append(re.sub(r"<[^>]+>", " ", c["html"]).strip())
            joined = " ".join(p for p in parts if p)
            if _nonblank(joined):
                return joined
    return ""


def _parse_json_source(data: Any) -> tuple[str, dict[int, str], Any]:
    pages: dict[int, str] = {}
    chunks: list[str] = []

    def _blk_page(blk: dict[str, Any], default_page: int | None) -> int | None:
        raw_p = blk.get("page") or blk.get("page_number")
        if isinstance(raw_p, int) and not isinstance(raw_p, bool) and raw_p >= 1:
            return raw_p
        pidx = blk.get("page_idx")
        if isinstance(pidx, int) and not isinstance(pidx, bool) and pidx >= 0:
            return pidx + 1
        return default_page

    if isinstance(data, dict) and data.get("format") == "research_scientist_pdf_blocks_v1":
        raw_pages = data.get("pages")
        if isinstance(raw_pages, list):
            for page_i, elem in enumerate(raw_pages, start=1):
                if isinstance(elem, list):
                    for blk in elem:
                        if isinstance(blk, dict):
                            txt = _v2_extract_text(blk)
                            if txt:
                                chunks.append(txt)
                                p = _blk_page(blk, page_i)
                                if isinstance(p, int) and p >= 1:
                                    pages[p] = (pages.get(p, "") + "\n" + txt).strip()
                elif isinstance(elem, dict):
                    txt = _v2_extract_text(elem)
                    if txt:
                        chunks.append(txt)
                        p = _blk_page(elem, 1)
                        if isinstance(p, int) and p >= 1:
                            pages[p] = (pages.get(p, "") + "\n" + txt).strip()
        raw_blocks = data.get("blocks")
        if isinstance(raw_blocks, list):
            for blk in raw_blocks:
                if isinstance(blk, dict):
                    txt = _v2_extract_text(blk)
                    if txt:
                        chunks.append(txt)
                        p = _blk_page(blk, None)
                        if isinstance(p, int) and p >= 1:
                            pages[p] = (pages.get(p, "") + "\n" + txt).strip()
        return "\n".join(chunks), pages, data
    if isinstance(data, dict) and data.get("format") == "research_scientist_venue_sources_v1":
        raw_sources = data.get("sources")
        if isinstance(raw_sources, list):
            for src in raw_sources:
                if isinstance(src, dict) and _nonblank(src.get("text")):
                    chunks.append(src["text"])
        return "\n".join(chunks), pages, data
    if isinstance(data, list):
        # MinerU Content List V2: flat list of dicts or list of page lists
        for page_i, elem in enumerate(data, start=1):
            if isinstance(elem, list):
                for sub in elem:
                    txt = _v2_extract_text(sub)
                    if txt:
                        chunks.append(txt)
                        p = _blk_page(sub, page_i) if isinstance(sub, dict) else page_i
                        if isinstance(p, int) and p >= 1:
                            pages[p] = (pages.get(p, "") + "\n" + txt).strip()
            elif isinstance(elem, dict):
                txt = _v2_extract_text(elem)
                if txt:
                    chunks.append(txt)
                    p = _blk_page(elem, 1)
                    if isinstance(p, int) and p >= 1:
                        pages[p] = (pages.get(p, "") + "\n" + txt).strip()
        return "\n".join(chunks), pages, data

    def _flatten(obj: Any) -> None:
        if isinstance(obj, str):
            chunks.append(obj)
        elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
            chunks.append(str(obj))
        elif isinstance(obj, dict):
            for v in obj.values():
                _flatten(v)
        elif isinstance(obj, list):
            for v in obj:
                _flatten(v)

    _flatten(data)
    return "\n".join(chunks), pages, data


def _index_sources_dir(sources_dir: Path) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    root_resolved = sources_dir.resolve()
    pdf_entries: list[tuple[Path, str]] = []
    for p in sorted(sources_dir.rglob("*")):
        try:
            resolved_p = p.resolve()
        except OSError:
            continue
        if not resolved_p.is_relative_to(root_resolved):
            continue
        if not resolved_p.is_file():
            continue
        rel = p.relative_to(sources_dir).as_posix()
        suffix = p.suffix.lower()
        if suffix in {".txt", ".md", ".csv", ".log"}:
            txt = p.read_text(encoding="utf-8", errors="replace")
            index[rel] = {"path": p, "text": txt, "pages": {}, "json": None}
        elif suffix == ".json":
            raw_txt = p.read_text(encoding="utf-8", errors="replace")
            try:
                parsed = json.loads(raw_txt)
                txt, pages, obj = _parse_json_source(parsed)
            except json.JSONDecodeError:
                txt, pages, obj = raw_txt, {}, None
            index[rel] = {"path": p, "text": txt, "pages": pages, "json": obj}
        elif suffix == ".pdf":
            pdf_entries.append((p, rel))

    for p, rel in pdf_entries:
        aliased = False
        for ext in (".json", ".txt"):
            sib_rel = p.with_suffix(ext).relative_to(sources_dir).as_posix()
            sib_entry = index.get(sib_rel)
            if sib_entry is not None and (sib_entry["text"] or sib_entry["pages"]):
                index[rel] = sib_entry
                aliased = True
                break
        if aliased:
            continue
        try:
            import fitz  # type: ignore

            doc = fitz.open(p)
            pages = {i + 1: page.get_text("text") for i, page in enumerate(doc)}
            index[rel] = {"path": p, "text": "\n".join(pages.values()), "pages": pages, "json": None}
        except Exception:
            index[rel] = {"path": p, "text": "", "pages": {}, "json": None, "unextracted_pdf": True}
    return index


def _resolve_dotted_fragment(obj: Any, fragment: str) -> tuple[bool, Any]:
    cur = obj
    for part in fragment.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return False, None
    return True, cur


def _fragment_text(val: Any) -> str:
    if isinstance(val, str):
        return val
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return str(val)
    if isinstance(val, bool):
        return "true" if val else "false"
    chunks: list[str] = []
    v2 = _v2_extract_text(val)
    if _nonblank(v2):
        chunks.append(v2)

    def _walk(x: Any) -> None:
        if isinstance(x, str):
            chunks.append(x)
        elif isinstance(x, (int, float)) and not isinstance(x, bool):
            chunks.append(str(x))
        elif isinstance(x, dict):
            for vv in x.values():
                _walk(vv)
        elif isinstance(x, list):
            for vv in x:
                _walk(vv)

    _walk(val)
    return "\n".join(chunks)


def _extract_locator_file_and_fragment(locator: str) -> tuple[str | None, str | None]:
    # Match a path-like token ending in a common extension with optional #fragment
    m = re.search(
        r"((?:[A-Za-z0-9_.~/-]+/)?[A-Za-z0-9_.-]+\.(?:json|md|txt|csv|log|pdf))(?:#([A-Za-z0-9_.-]+))?",
        locator,
    )
    if m:
        return m.group(1), m.group(2)
    return None, None


def _verbatim_locator_matches(locator: str, text: str) -> bool:
    norm_loc = _normalized_ws(locator)
    if len(norm_loc) < 8:
        return False
    return _contains_exact_quote(text, norm_loc)


def _check_sources_dir(
    sources_dir: Path,
    ledger: dict[str, Any],
) -> tuple[list[str], list[dict[str, Any]]]:
    if not sources_dir.is_dir():
        raise ValueError(f"sources_dir is not an existing directory: {sources_dir}")
    root_resolved = sources_dir.resolve()
    index = _index_sources_dir(sources_dir)
    issues: list[str] = []
    checks: list[dict[str, Any]] = []

    for source in ledger.get("sources", []):
        if not isinstance(source, dict) or not _nonblank(source.get("id")):
            continue
        sid = source["id"]
        locator = str(source.get("locator", ""))
        hint = source.get("file") or source.get("path") or source.get("source_file")
        loc_file, loc_frag = _extract_locator_file_and_fragment(locator)
        candidate_rel = str(hint).strip() if _nonblank(hint) else loc_file

        resolved_entry: dict[str, Any] | None = None
        file_confirmed = False
        frag_requested = False
        frag_found = False
        frag_val: Any = None

        if candidate_rel is not None:
            # Traversal & outside-root rejection
            cand_path = Path(candidate_rel)
            if cand_path.is_absolute() or ".." in cand_path.parts:
                issues.append(f"invalid_source_path:{sid}")
                checks.append({"source_id": sid, "status": "invalid_source_path"})
                continue
            full_target = (sources_dir / cand_path).resolve()
            if not full_target.is_relative_to(root_resolved):
                issues.append(f"invalid_source_path:{sid}")
                checks.append({"source_id": sid, "status": "invalid_source_path"})
                continue

            norm_rel = cand_path.as_posix().lstrip("./")
            sibling_cands: list[str] = []
            if cand_path.suffix.lower() == ".pdf":
                sibling_cands = [
                    cand_path.with_suffix(".json").as_posix().lstrip("./"),
                    cand_path.with_suffix(".txt").as_posix().lstrip("./"),
                ]
            elif cand_path.suffix.lower() == ".json":
                sibling_cands = [
                    cand_path.with_suffix(".pdf").as_posix().lstrip("./"),
                ]

            if norm_rel in index:
                resolved_entry = index[norm_rel]
                file_confirmed = True
            elif any(
                sc in index and index[sc]["path"].resolve().is_relative_to(root_resolved)
                for sc in sibling_cands
            ):
                sc_hit = next(
                    sc for sc in sibling_cands
                    if sc in index and index[sc]["path"].resolve().is_relative_to(root_resolved)
                )
                resolved_entry = index[sc_hit]
                file_confirmed = True
            else:
                # Fallback basename match only if unique
                matches = [v for k, v in index.items() if Path(k).name == cand_path.name and norm_rel == cand_path.name]
                if not matches and norm_rel == cand_path.name:
                    for sc in sibling_cands:
                        sc_name = Path(sc).name
                        sc_matches = [v for k, v in index.items() if Path(k).name == sc_name]
                        if len(sc_matches) == 1:
                            matches = sc_matches
                            break
                if len(matches) == 1:
                    resolved_entry = matches[0]
                    file_confirmed = True
                elif not _nonblank(hint) and any(_verbatim_locator_matches(locator, entry["text"]) for entry in index.values()):
                    resolved_entry = next(entry for entry in index.values() if _verbatim_locator_matches(locator, entry["text"]))
                    file_confirmed = True
                else:
                    issues.append(f"source_locator_file_missing:{sid}")
                    checks.append({"source_id": sid, "status": "source_locator_file_missing", "target": norm_rel})
                    continue

            if resolved_entry.get("unextracted_pdf"):
                issues.append(f"source_pdf_unextracted:{sid}")

            if loc_frag and resolved_entry.get("json") is not None:
                frag_requested = True
                frag_found, frag_val = _resolve_dotted_fragment(resolved_entry["json"], loc_frag)
                if not frag_found:
                    issues.append(f"source_locator_fragment_missing:{sid}")
                    file_confirmed = False
        elif any(_verbatim_locator_matches(locator, entry["text"]) for entry in index.values()):
            resolved_entry = next(entry for entry in index.values() if _verbatim_locator_matches(locator, entry["text"]))
            file_confirmed = True

        # Page locator check (supports page, p., pp., pages, and ranges like pp. 1-2)
        page_m = re.search(r"\b(?:pages?|pp?\.?)\s*=?\s*(\d+)(?:\s*[-–—]\s*(\d+))?\b", locator, re.I)
        p_start = int(page_m.group(1)) if page_m else None
        p_end = int(page_m.group(2)) if (page_m and page_m.group(2)) else None
        page_valid = True
        if p_start is not None and resolved_entry is not None and resolved_entry["pages"]:
            if p_end is None:
                if p_start not in resolved_entry["pages"]:
                    issues.append(f"source_locator_page_missing:{sid}")
                    file_confirmed = False
                    page_valid = False
            else:
                if (
                    p_start > p_end
                    or p_start not in resolved_entry["pages"]
                    or p_end not in resolved_entry["pages"]
                ):
                    issues.append(f"source_locator_page_missing:{sid}")
                    file_confirmed = False
                    page_valid = False

        # Quote / excerpt check
        quote = source.get("quote") or source.get("excerpt")
        quote_confirmed = False
        if _nonblank(quote):
            if resolved_entry is not None:
                if frag_requested:
                    if frag_found and _contains_exact_quote(_fragment_text(frag_val), quote):
                        quote_confirmed = True
                    else:
                        issues.append(f"source_quote_not_found:{sid}")
                elif p_start is not None and resolved_entry["pages"]:
                    if not page_valid:
                        if _contains_exact_quote(resolved_entry["text"], quote):
                            issues.append(f"source_quote_page_mismatch:{sid}")
                        else:
                            issues.append(f"source_quote_not_found:{sid}")
                    else:
                        if p_end is None:
                            page_txt = resolved_entry["pages"].get(p_start, "")
                        else:
                            page_txt = "\n".join(
                                resolved_entry["pages"][p]
                                for p in sorted(resolved_entry["pages"])
                                if p_start <= p <= p_end
                            )
                        if page_txt and _contains_exact_quote(page_txt, quote):
                            quote_confirmed = True
                        elif _contains_exact_quote(resolved_entry["text"], quote):
                            issues.append(f"source_quote_page_mismatch:{sid}")
                        else:
                            issues.append(f"source_quote_not_found:{sid}")
                else:
                    if _contains_exact_quote(resolved_entry["text"], quote):
                        quote_confirmed = True
                    else:
                        issues.append(f"source_quote_not_found:{sid}")
            else:
                if any(_contains_exact_quote(entry["text"], quote) for entry in index.values()):
                    quote_confirmed = True
                else:
                    issues.append(f"source_quote_not_found:{sid}")

        if source.get("verified") is True and not (file_confirmed or quote_confirmed):
            issues.append(f"source_unverified_against_sources_dir:{sid}")

        checks.append({
            "source_id": sid,
            "file_confirmed": file_confirmed,
            "quote_confirmed": quote_confirmed,
        })

    return issues, checks


# ---------------------------------------------------------------------------
# F29#4 Deep Paper Argument Audits (Claim-Scope, Contributions, Related Work)
# ---------------------------------------------------------------------------

_RAW_CITE_KEY_RE = re.compile(
    r"\\(?:cite[a-zA-Z]*\*?|textcite|parencite|autocite|footcite|fullcite|nocite)"
    r"(?:\[[^\[\]\n]{0,120}\]){0,2}\{([^{}\n]{1,300})\}"
)
_REF_TOKEN_CITE_RE = re.compile(r"\[ref:([^\]\n]{1,300})\]")
_SCOPE_NEGATION_RE = re.compile(
    r"\b(?:does\s+not\s+generalize|cannot\s+generalize|do\s+not\s+claim|"
    r"do(?:es)?\s+not\s+(?:cover|support|address|include|evaluate|test)|"
    r"only\s+(?:evaluated|tested|validated|applied)\s+(?:on|in|for)|"
    r"restricted\s+to|limited\s+to|remain[s]?\s+limited\s+to|"
    r"(?:leave|left|defer(?:red)?)\b[^.\n]{0,40}\bto\s+future\s+work|"
    r"future\s+work|out\s+of\s+scope|not\s+(?:tested|evaluated|validated)\s+on)\b",
    re.I,
)
_CONCESSIVE_LEAD_RE = re.compile(
    r"^\s*(?:while|although|though|even\s+though|whereas|despite(?:\s+being)?|"
    r"leaving|deferring|reserving|limited\s+to|restricted\s+to)\b",
    re.I,
)
_CLAUSE_SPLIT_RE = re.compile(
    r";|"
    r"(?:,\s*|\b)(?:while|although|though|even\s+though|whereas|however|but|yet)\b|"
    r",\s*(?=(?:leaving|deferring|reserving)\b)|"
    r",\s*(?=(?:(?:it|this|which|our\s+(?:evaluation|work|study|method)|results?)\s+(?:is|are|remains?)\s+)?(?:only\s+(?:evaluated|tested|validated|applied)|limited\s+to|restricted\s+to|left\s+to\s+future\s+work)\b)|"
    r",\s*(?=(?:and\s+(?:we\s+)?(?:leave|left|defer(?:red)?|remain[s]?)|(?:which|that)\s+(?:we\s+)?(?:leave|left|defer(?:red)?|remain[s]?|is\s+left|are\s+left))\b)|"
    r"\b(?=(?:and\s+(?:we\s+)?(?:leave|left|defer(?:red)?|remain[s]?)|(?:which|that)\s+(?:we\s+)?(?:leave|left|defer(?:red)?|remain[s]?|is\s+left|are\s+left))\b)",
    re.I,
)
_AND_POSITIVE_VERB_RE = re.compile(
    r"(?:,\s*|\b)and\s+(?:achieves?|solves?|generalizes?|outperforms?|surpasses?|exceeds?|reaches?|attains?|works?|applies?|scales?)\b",
    re.I,
)
_SCOPE_UNIVERSAL_RE = re.compile(
    r"\b(?:across\s+all\s+(?:tasks|domains|modalities|languages|benchmarks|datasets|settings|regimes)|"
    r"all\s+possible\s+(?:tasks|domains|inputs|datasets|regimes)|"
    r"arbitrary\s+(?:datasets|tasks|domains|scales|inputs)|"
    r"universal\s+generalization|any\s+downstream\s+task|"
    r"provably\s+optimal\s+in\s+all\s+regimes|completely\s+solves|"
    r"regardless\s+of\s+scale|every\s+(?:downstream\s+)?(?:task|domain|benchmark|language))\b",
    re.I,
)
_OOD_CLAIM_RE = re.compile(
    r"\b(?:out-of-distribution|ood|cross-domain)\s+generalization\b|\bgeneralizes?\s+(?:out-of-distribution|ood|across\s+domains)\b",
    re.I,
)
_MULTILINGUAL_CLAIM_RE = re.compile(
    r"\b(?:multilingual|cross-lingual|across\s+(?:all\s+)?languages|many\s+languages)\b",
    re.I,
)
_LARGE_SCALE_CLAIM_RE = re.compile(
    r"\b(?:100B|70B|frontier[- ]scale|arbitrary\s+scale|billion[- ]parameter\s+models?\s+universally)\b",
    re.I,
)
_MULTIMODAL_CLAIM_RE = re.compile(
    r"\b(?:multi[- ]?modal|vision[- ]language|audio[- ]visual)\b",
    re.I,
)
_DATASET_COUNT_CLAIM_RE = re.compile(
    r"\b(?:across|on|over)\s+(\d+|two|three|four|five|six|seven|eight|nine|ten|twelve|twenty)\s+"
    r"(?:diverse\s+|standard\s+)?(?:benchmarks?|datasets?|tasks?)\b",
    re.I,
)
_LIMITATIONS_INLINE_RE = re.compile(
    r"(?:^|\n)[ \t]*(?:\*\*|__)?limitations?(?:\*\*|__)?[.:]",
    re.I,
)
_CONTRIB_CUE_RE = re.compile(
    r"\bcontributions?\s+(?:are|include|can\s+be\s+summarized|as\s+follows)\b|"
    r"\bfollowing\s+contributions?\b|"
    r"(?:^|\n)[ \t]*(?:\*\*|__)?contributions?(?:\*\*|__)?[.:]",
    re.I,
)
_INLINE_EVIDENCE_ANCHOR_RE = re.compile(
    r"\b(?:tab(?:le)?\.?\s*[A-Z]?\d+|fig(?:ure)?\.?\s*[A-Z]?\d+|"
    r"thm\.?(?:\s*[A-Z]?\d+)?|theorem\s+[A-Z]?\d+|lemma\s+[A-Z]?\d+|prop(?:osition)?\.?\s+[A-Z]?\d+|"
    r"cor(?:ollary)?\.?\s+[A-Z]?\d+|proof\b|eq(?:uation)?\.?\s*\(?\d+\)?|"
    r"sec(?:tion)?\.?\s*[A-Z]?\d+|app(?:endix)?\.?\s*[A-Z0-9]+|"
    r"alg(?:orithm)?\.?\s*\d+|run[_-]?id\s*[:=]\s*[A-Za-z0-9._-]+|"
    r"sha256\s*[:=]\s*[0-9a-f]{7,})\b|"
    r"\[claim:[A-Za-z0-9_-]+\]|\\(?:eq)?ref\{[^{}\n]+\}",
    re.I,
)
_DIFF_CONTRAST_RE = re.compile(
    r"\b(?:unlike|in\s+contrast\s+(?:to|with)|whereas|while|however|"
    r"differs?\s+from|different\s+from|compared\s+(?:to|with)|"
    r"instead\s+of|rather\s+than|as\s+opposed\s+to|by\s+contrast|conversely|"
    r"fails?\s+to|assumes?|lacks?|cannot|can't|restricted\s+to|"
    r"higher\s+(?:cost|complexity|overhead)|outperforms?|surpass(?:es)?|"
    r"limitations?|drawbacks?|shortcomings?|we\s+differ)\b",
    re.I,
)

_NUMBER_WORDS = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12, "twenty": 20,
}


def _reject_nonfinite(tok: str) -> Any:
    raise ValueError(f"Non-finite JSON constant not allowed: {tok}")


def _preserve_cite_normalize(text: str, is_tex: bool) -> str:
    """Normalize text like _normalize_manuscript while preserving \\cite{k1,k2} keys as [ref:k1,k2]."""
    out = text
    out = re.sub(r"\\begin\{thebibliography\}[\s\S]*?\\end\{thebibliography\}", " ", out)
    out = re.sub(r"\\bibliography\{[^{}]*\}", " ", out)
    out = _RAW_CITE_KEY_RE.sub(lambda m: f" [ref:{m.group(1)}] ", out)
    return _normalize_manuscript(out, is_tex=is_tex)


def _classify_heading_bucket(heading_text: str) -> str:
    low = re.sub(r"^(?:\d+(?:\.\d+)*|[A-Z])\.\s+", "", heading_text.strip().lower())
    low = re.sub(r"[^a-z0-9\s]+", " ", low).strip()
    if not low:
        return "other"
    if "abstract" in low:
        return "abstract"
    if "limitation" in low or "broader impact" in low or "ethical" in low:
        return "limitations"
    if "related work" in low or "prior work" in low or "literature" in low or low == "background":
        return "related_work"
    if "conclusion" in low or "concluding" in low:
        return "conclusion"
    if "introduction" in low or low == "intro":
        return "introduction"
    if "contribution" in low:
        return "contributions"
    if "experiment" in low or "evaluation" in low or "result" in low:
        return "experiments"
    if "method" in low or "approach" in low or "framework" in low or "model" in low:
        return "method"
    return "other"


def _extract_bullets_from_text(raw_chunk: str, norm_chunk: str) -> list[str]:
    bullets: list[str] = []
    # Check LaTeX \item lines first if present
    if "\\item" in raw_chunk:
        parts = re.split(r"\\item\b(?:\[[^\]\n]{0,60}\])?", raw_chunk)
        for p in parts[1:]:
            end_m = re.search(r"\\end\{(?:itemize|enumerate)\}", p)
            seg = p[: end_m.start()] if end_m else p
            clean = _normalized_ws(_normalize_manuscript(seg, is_tex=True))
            if clean:
                bullets.append(clean)
        if bullets:
            return bullets

    # Markdown / numbered bullets
    cur: list[str] = []
    for ln in norm_chunk.splitlines():
        bm = re.match(r"^[ \t]*(?:[-*+]|(?:\(?\d{1,2}[.)]))[ \t]+(.+)$", ln)
        if bm:
            if cur:
                bullets.append(_normalized_ws(" ".join(cur)))
            cur = [bm.group(1).strip()]
        elif cur and ln.strip() and not re.match(r"^[ \t]*#", ln):
            cur.append(ln.strip())
        elif cur and not ln.strip():
            bullets.append(_normalized_ws(" ".join(cur)))
            cur = []
    if cur:
        bullets.append(_normalized_ws(" ".join(cur)))
    return [b for b in bullets if b]


def _extract_first_list_bullets_with_span(
    raw_tail: str,
    *,
    is_tex: bool,
) -> tuple[list[str], tuple[int, int] | None]:
    """Extract only the first contribution list (LaTeX or Markdown) immediately following a cue."""
    tex_begin_m = re.search(r"\\begin\{(itemize|enumerate)\}", raw_tail)
    md_bullet_m = re.search(r"(?m)^[ \t]*(?:[-*+]|(?:\(?\d{1,2}[.)]))[ \t]+", raw_tail)
    sec_break_m = re.search(r"(?m)^[ \t]*#{1,6}[ \t]+|\\(?:sub)*section(?:\*|\b)", raw_tail)
    sec_break_pos = sec_break_m.start() if sec_break_m else len(raw_tail)

    if tex_begin_m and tex_begin_m.start() < sec_break_pos and (
        md_bullet_m is None or tex_begin_m.start() <= md_bullet_m.start()
    ):
        prefix = raw_tail[: tex_begin_m.start()]
        if not re.search(r"\n[ \t]*\n[ \t]*[^\s\\]", prefix):
            depth = 0
            env_end = len(raw_tail)
            body_end = len(raw_tail)
            for tag_m in re.finditer(r"\\(begin|end)\{(?:itemize|enumerate)\}", raw_tail[tex_begin_m.start() :]):
                if tag_m.group(1) == "begin":
                    depth += 1
                else:
                    depth -= 1
                    if depth == 0:
                        body_end = tex_begin_m.start() + tag_m.start()
                        env_end = tex_begin_m.start() + tag_m.end()
                        break
            list_body = raw_tail[tex_begin_m.end() : body_end]
            bullets: list[str] = []
            if "\\item" in list_body:
                parts = re.split(r"\\item\b(?:\[[^\]\n]{0,60}\])?", list_body)
                for p in parts[1:]:
                    clean = _normalized_ws(_normalize_manuscript(p, is_tex=True))
                    if clean:
                        bullets.append(clean)
            if bullets:
                return bullets, (tex_begin_m.start(), env_end)
        return [], None

    if "\\item" in raw_tail:
        item_m = re.search(r"\\item\b", raw_tail)
        if item_m and item_m.start() < sec_break_pos:
            sub = raw_tail[:sec_break_pos]
            end_m = re.search(r"\\end\{(?:itemize|enumerate)\}|\n[ \t]*\n", sub[item_m.start() :])
            stop = item_m.start() + end_m.end() if end_m else len(sub)
            parts = re.split(r"\\item\b(?:\[[^\]\n]{0,60}\])?", sub[item_m.start() : stop])
            bullets = []
            for p in parts[1:]:
                clean = _normalized_ws(_normalize_manuscript(p, is_tex=True))
                if clean:
                    bullets.append(clean)
            if bullets:
                return bullets, (item_m.start(), stop)

    bullets = []
    cur: list[str] = []
    in_list = False
    saw_pre_blank = False
    saw_list_blank = False
    list_start = -1
    last_end = -1
    pos = 0
    for raw_ln_nl in raw_tail.splitlines(keepends=True):
        raw_ln = raw_ln_nl.rstrip("\r\n")
        ln_len = len(raw_ln_nl)
        if re.match(r"^[ \t]*#|^[ \t]*\\(?:sub)*section(?:\*|\b)", raw_ln):
            break
        bm = re.match(r"^[ \t]*(?:[-*+]|(?:\(?\d{1,2}[.)]))[ \t]+(.+)$", raw_ln)
        if not in_list:
            if not raw_ln.strip():
                saw_pre_blank = True
            elif bm:
                in_list = True
                list_start = pos
                cur = [bm.group(1).strip()]
                last_end = pos + ln_len
                saw_list_blank = False
            elif saw_pre_blank:
                break
        else:
            if not raw_ln.strip():
                if cur:
                    clean = _normalized_ws(_preserve_cite_normalize(" ".join(cur), is_tex=is_tex))
                    if clean:
                        bullets.append(clean)
                    cur = []
                saw_list_blank = True
            elif bm:
                if cur:
                    clean = _normalized_ws(_preserve_cite_normalize(" ".join(cur), is_tex=is_tex))
                    if clean:
                        bullets.append(clean)
                cur = [bm.group(1).strip()]
                last_end = pos + ln_len
                saw_list_blank = False
            elif saw_list_blank:
                break
            elif cur:
                cur.append(raw_ln.strip())
                last_end = pos + ln_len
        pos += ln_len
    if cur:
        clean = _normalized_ws(_preserve_cite_normalize(" ".join(cur), is_tex=is_tex))
        if clean:
            bullets.append(clean)
    if bullets and list_start >= 0 and last_end > list_start:
        return bullets, (list_start, last_end)
    return [], None


def _extract_named_sections(raw_text: str, is_tex: bool | None = None) -> dict[str, Any]:
    tex_mode = _looks_like_tex(raw_text) if is_tex is None else is_tex
    if tex_mode:
        clean_raw = "\n".join(re.sub(r"(?<!\\)%.*$", "", ln) for ln in raw_text.splitlines())
    else:
        clean_raw = raw_text

    # Trim references/bibliography tail
    split_positions: list[int] = []
    md_ref_m = re.search(
        r"(?m)^[ \t]*#{1,6}[ \t]+(?:\*{1,2})?(?:references|bibliography)(?:\*{1,2})?\b",
        clean_raw,
        flags=re.I,
    )
    if md_ref_m:
        split_positions.append(md_ref_m.start())
    bib_env_m = re.search(r"\\begin\{thebibliography\}", clean_raw, flags=re.I)
    if bib_env_m:
        split_positions.append(bib_env_m.start())
    if re.search(r"\\section(?:\*|\b)", clean_raw, flags=re.I):
        bc, brc = _build_latex_match_tables(clean_raw)
        for sm in re.finditer(r"\\section(?:\*|\b)", clean_raw, flags=re.I):
            if not _has_even_preceding_backslashes(clean_raw, sm.start()):
                continue
            matched = _match_cmd_args(clean_raw, sm.end(), bc, brc, allow_opt=True, num_braced=1)
            if matched is not None:
                _, spans = matched
                s1, e1 = spans[0]
                sec_txt = re.sub(
                    r"\s+", " ", re.sub(r"(?<!\\)[{}]", "", _normalize_manuscript(clean_raw[s1:e1], is_tex=True))
                ).strip().lower()
                if sec_txt in {"references", "bibliography"}:
                    split_positions.append(sm.start())
                    break
    raw_no_refs = clean_raw[: min(split_positions)] if split_positions else clean_raw

    # Find all heading boundaries in raw_no_refs
    boundaries: list[tuple[int, int, str]] = []  # (start_idx, body_start_idx, heading_text)
    for m in re.finditer(r"(?m)^[ \t]{0,3}#{1,6}[ \t]+([^\n]+)$", raw_no_refs):
        h_norm = _normalize_manuscript(m.group(1), is_tex=tex_mode).strip()
        if h_norm:
            boundaries.append((m.start(), m.end(), h_norm))
    if tex_mode or "\\" in raw_no_refs:
        bc, brc = _build_latex_match_tables(raw_no_refs)
        for sm in _HEADING_CMD_RE.finditer(raw_no_refs):
            if sm.group(0).startswith("\\title") or not _has_even_preceding_backslashes(raw_no_refs, sm.start()):
                continue
            matched = _match_cmd_args(raw_no_refs, sm.end(), bc, brc, allow_opt=True, num_braced=1)
            if matched is not None:
                next_pos, spans = matched
                s1, e1 = spans[0]
                h_norm = re.sub(
                    r"\s+", " ", re.sub(r"(?<!\\)[{}]", "", _normalize_manuscript(raw_no_refs[s1:e1], is_tex=tex_mode))
                ).strip()
                if h_norm:
                    boundaries.append((sm.start(), next_pos, h_norm))

    boundaries.sort(key=lambda x: x[0])

    buckets: dict[str, list[str]] = {
        "abstract": [],
        "introduction": [],
        "related_work": [],
        "method": [],
        "experiments": [],
        "limitations": [],
        "conclusion": [],
        "contributions": [],
        "other": [],
    }
    ordered_sections: list[tuple[str, str, str]] = []  # (bucket, raw_chunk, norm_cite_chunk)
    section_offsets: list[int] = []  # start offset of raw_chunk inside raw_no_refs
    raw_contrib_chunks: list[tuple[str, str]] = []
    contrib_spans: list[tuple[int, int]] = []

    # Abstract from \begin{abstract}
    am = re.search(r"\\begin\{abstract\}([\s\S]*?)\\end\{abstract\}", raw_no_refs, re.I)
    if am:
        raw_abs = am.group(1)
        norm_abs = _preserve_cite_normalize(raw_abs, is_tex=tex_mode)
        buckets["abstract"].append(norm_abs)
        ordered_sections.append(("abstract", raw_abs, norm_abs))
        section_offsets.append(am.start(1))

    for idx, (h_start, b_start, h_text) in enumerate(boundaries):
        b_end = boundaries[idx + 1][0] if idx + 1 < len(boundaries) else len(raw_no_refs)
        raw_chunk = raw_no_refs[b_start:b_end]
        norm_chunk = _preserve_cite_normalize(raw_chunk, is_tex=tex_mode)
        bucket = _classify_heading_bucket(h_text)
        buckets[bucket].append(norm_chunk)
        ordered_sections.append((bucket, raw_chunk, norm_chunk))
        section_offsets.append(b_start)
        if bucket == "contributions":
            raw_contrib_chunks.append((raw_chunk, norm_chunk))
            contrib_spans.append((h_start, b_end))

    # Fallback if no headings detected
    if not ordered_sections:
        norm_all = _preserve_cite_normalize(raw_no_refs, is_tex=tex_mode)
        ordered_sections.append(("other", raw_no_refs, norm_all))
        section_offsets.append(0)
        buckets["other"].append(norm_all)

    # Extract contribution bullets from dedicated section OR inline cue in intro/other/abstract
    contributions_bullets: list[str] = []
    for rc, nc in raw_contrib_chunks:
        contributions_bullets.extend(_extract_bullets_from_text(rc, nc))
    if not contributions_bullets:
        for (bname, rc, _nc), rc_offset in zip(ordered_sections, section_offsets):
            if bname in {"introduction", "abstract", "other"} and _CONTRIB_CUE_RE.search(rc):
                cm = _CONTRIB_CUE_RE.search(rc)
                assert cm is not None
                tail_raw = rc[cm.end() : cm.end() + 3000]
                ext_bullets, list_span = _extract_first_list_bullets_with_span(tail_raw, is_tex=tex_mode)
                if ext_bullets:
                    contributions_bullets.extend(ext_bullets)
                    if list_span is not None:
                        contrib_spans.append((rc_offset + cm.end() + list_span[0], rc_offset + cm.end() + list_span[1]))
                    break

    # Build non-contribution manuscript views so contribution bullets cannot self-certify anchors
    if contrib_spans:
        merged_spans: list[tuple[int, int]] = []
        for s, e in sorted(contrib_spans):
            if s >= e:
                continue
            if merged_spans and s <= merged_spans[-1][1]:
                merged_spans[-1] = (merged_spans[-1][0], max(merged_spans[-1][1], e))
            else:
                merged_spans.append((s, e))
        nc_parts: list[str] = []
        prev_idx = 0
        for s, e in merged_spans:
            nc_parts.append(raw_no_refs[prev_idx:s])
            nc_parts.append("\n")
            prev_idx = e
        nc_parts.append(raw_no_refs[prev_idx:])
        raw_non_contrib = "".join(nc_parts)
    else:
        raw_non_contrib = raw_no_refs
    norm_non_contrib = _normalize_manuscript(raw_non_contrib, is_tex=tex_mode)
    nc_table_parts: list[str] = []
    nc_table_spans: list[tuple[int, int]] = []
    for t_m in re.finditer(r"\\begin\{(table\*?)\}([\s\S]*?)\\end\{\1\}", raw_non_contrib, re.I):
        nc_table_spans.append((t_m.start(), t_m.end()))
        nc_table_parts.append(_normalize_manuscript(t_m.group(2), is_tex=tex_mode))
    for t_m in re.finditer(r"\\begin\{(tabular\*?|tabularx|longtable)\}([\s\S]*?)\\end\{\1\}", raw_non_contrib, re.I):
        if any(s <= t_m.start() and t_m.end() <= e for s, e in nc_table_spans):
            continue
        nc_table_parts.append(_normalize_manuscript(t_m.group(2), is_tex=tex_mode))
    for ln in raw_non_contrib.splitlines():
        if "|" in ln and re.match(r"^\s*\|", ln):
            nc_table_parts.append(_normalize_manuscript(ln, is_tex=tex_mode))
    non_contrib_tables = "\n".join(nc_table_parts)

    # Raw cite keys
    all_raw_cite_keys: set[str] = set()
    for m in _RAW_CITE_KEY_RE.finditer(raw_no_refs):
        for k in m.group(1).split(","):
            ks = k.strip()
            if ks:
                all_raw_cite_keys.add(ks)

    # Raw tables (preserving \cite keys)
    raw_table_parts: list[str] = []
    for t_m in re.finditer(r"\\begin\{(table\*?|tabular\*?|tabularx|longtable)\}([\s\S]*?)\\end\{\1\}", clean_raw, re.I):
        raw_table_parts.append(t_m.group(2))
    for ln in clean_raw.splitlines():
        if "|" in ln and re.match(r"^\s*\|", ln):
            raw_table_parts.append(ln)

    return {
        "abstract": "\n".join(buckets["abstract"]),
        "introduction": "\n".join(buckets["introduction"]),
        "related_work": "\n".join(buckets["related_work"]),
        "method": "\n".join(buckets["method"]),
        "experiments": "\n".join(buckets["experiments"]),
        "limitations": "\n".join(buckets["limitations"]),
        "conclusion": "\n".join(buckets["conclusion"]),
        "ordered_sections": ordered_sections,
        "contributions_bullets": contributions_bullets,
        "all_raw_cite_keys": all_raw_cite_keys,
        "raw_full": raw_no_refs,
        "raw_non_contrib": raw_non_contrib,
        "norm_non_contrib": norm_non_contrib,
        "non_contrib_tables": non_contrib_tables,
        "raw_tables": "\n".join(raw_table_parts),
    }


def _split_sentences_list(text: str) -> list[str]:
    if not text or not text.strip():
        return []
    out: list[str] = []
    prev = 0
    for m in _SENT_SPLIT_RE.finditer(text):
        seg = text[prev : m.start()].strip()
        if seg:
            out.append(seg)
        prev = m.end()
    tail = text[prev:].strip()
    if tail:
        out.append(tail)
    return out


def _extract_unnegated_scope_clauses(sent: str) -> list[str]:
    """Return clauses of `sent` not locally exempted by a scope negation/future-work cue."""
    active: list[str] = []
    for semi_part in sent.split(";"):
        seg = semi_part.strip()
        if not seg:
            continue
        if _CONCESSIVE_LEAD_RE.match(seg):
            nm = _SCOPE_NEGATION_RE.search(seg)
            if nm:
                comma_idx = seg.find(",", nm.end())
                if comma_idx != -1:
                    seg = seg[comma_idx + 1 :].strip()
                    if not seg:
                        continue
        sub_clauses = [c.strip() for c in _CLAUSE_SPLIT_RE.split(seg) if c and c.strip()]
        for cl in sub_clauses:
            nm = _SCOPE_NEGATION_RE.search(cl)
            if not nm:
                active.append(cl)
            else:
                am = _AND_POSITIVE_VERB_RE.search(cl, nm.end())
                if am:
                    pos_tail = cl[am.start() :].strip()
                    if pos_tail and not _SCOPE_NEGATION_RE.search(pos_tail):
                        active.append(pos_tail)
    return active


def _audit_claim_scope(
    sections: dict[str, str],
    named_secs: dict[str, Any] | None,
    ledger: dict[str, Any],
) -> tuple[list[str], dict[str, Any]]:
    raw_scope = ledger.get("evaluated_scope") if "evaluated_scope" in ledger else ledger.get("experiment_scope")
    if raw_scope is not None and not isinstance(raw_scope, dict):
        raise ValueError("evaluated_scope / experiment_scope must be an object")
    scope_obj: dict[str, Any] = raw_scope if isinstance(raw_scope, dict) else {}
    scope_present = bool(scope_obj)

    zones: list[tuple[str, str]] = []
    if named_secs is not None:
        if sections["title"].strip():
            zones.append(("title", sections["title"]))
        abs_txt = named_secs["abstract"].strip() or sections["abstract"].strip()
        if abs_txt:
            zones.append(("abstract", abs_txt))
        if named_secs["introduction"].strip():
            zones.append(("introduction", named_secs["introduction"]))
        if named_secs["conclusion"].strip():
            zones.append(("conclusion", named_secs["conclusion"]))
        if not (abs_txt or named_secs["introduction"].strip() or named_secs["conclusion"].strip()):
            # Unheaded manuscript fallback: inspect body excluding explicit Limitations paragraph
            body_clean = _LIMITATIONS_INLINE_RE.split(sections["body"], maxsplit=1)[0]
            if body_clean.strip():
                zones.append(("body", body_clean))

    for claim in ledger.get("claims", []):
        if isinstance(claim, dict) and _nonblank(claim.get("id")):
            ctext = claim.get("text") or claim.get("excerpt")
            if _nonblank(ctext):
                zones.append((f"claim:{claim['id']}", str(ctext)))

    issues: list[str] = []
    findings: list[dict[str, Any]] = []

    def _add_f(rule: str, zone: str, excerpt: str, reason: str, issue_code: str) -> None:
        issues.append(issue_code)
        findings.append({
            "rule": rule,
            "zone": zone,
            "excerpt": excerpt[:160],
            "reason": reason,
        })

    def _norm_vals(key: str) -> str:
        val = scope_obj.get(key)
        if isinstance(val, list):
            return " ".join(str(x).lower() for x in val if _nonblank(str(x)))
        if isinstance(val, str):
            return val.lower()
        return ""

    regimes_txt = _norm_vals("regimes")
    conds_txt = f"{_norm_vals('conditions')} {_norm_vals('languages')}".strip()
    scales_txt = _norm_vals("scales")
    mods_txt = _norm_vals("modalities")
    datasets_list = [x for x in scope_obj.get("datasets", []) if _nonblank(str(x))] if isinstance(scope_obj.get("datasets"), list) else []
    excl_claims = [str(x).strip() for x in scope_obj.get("excluded_claims", []) if _nonblank(str(x))] if isinstance(scope_obj.get("excluded_claims"), list) else []

    for zone_name, zone_txt in zones:
        for orig_sent in _split_sentences_list(zone_txt):
            for sent in _extract_unnegated_scope_clauses(orig_sent):
                um = _SCOPE_UNIVERSAL_RE.search(sent)
                if um:
                    _add_f(
                        "universal_overclaim",
                        zone_name,
                        sent,
                        f"Unbounded universal quantifier '{um.group(0)}' exceeds evaluated scope.",
                        f"claim_scope_overclaim:{zone_name}",
                    )

                for excl in excl_claims:
                    if re.search(rf"(?<!\w){re.escape(excl)}(?!\w)", sent, re.I):
                        _add_f(
                            "excluded_claim_violation",
                            zone_name,
                            sent,
                            f"Asserts excluded claim '{excl}' outside limitations/caveats.",
                            f"claim_scope_overclaim:{zone_name}",
                        )

                if regimes_txt and re.search(r"\b(?:in-distribution|id-only|in_distribution)\b", regimes_txt) and not re.search(r"\b(?:ood|out-of-distribution|cross-domain)\b", regimes_txt):
                    if _OOD_CLAIM_RE.search(sent):
                        _add_f(
                            "regime_mismatch",
                            zone_name,
                            sent,
                            f"Claims OOD/cross-domain generalization despite evaluated regimes: '{regimes_txt}'.",
                            f"claim_scope_overclaim:{zone_name}",
                        )

                if conds_txt and re.search(r"\b(?:english[- ]only|monolingual|english)\b", conds_txt) and not re.search(r"\b(?:multilingual|cross[- ]lingual)\b", conds_txt):
                    if _MULTILINGUAL_CLAIM_RE.search(sent):
                        _add_f(
                            "language_condition_mismatch",
                            zone_name,
                            sent,
                            f"Claims multilingual scope despite evaluated condition: '{conds_txt}'.",
                            f"claim_scope_overclaim:{zone_name}",
                        )

                if scales_txt and not re.search(r"\b(?:70b|100b|frontier|arbitrary)\b", scales_txt):
                    if _LARGE_SCALE_CLAIM_RE.search(sent):
                        _add_f(
                            "scale_mismatch",
                            zone_name,
                            sent,
                            f"Claims frontier/100B+ scale despite evaluated scales: '{scales_txt}'.",
                            f"claim_scope_overclaim:{zone_name}",
                        )

                if mods_txt and "text" in mods_txt and not re.search(r"\b(?:vision|image|audio|video|multimodal|multi-modal)\b", mods_txt):
                    if _MULTIMODAL_CLAIM_RE.search(sent):
                        _add_f(
                            "modality_mismatch",
                            zone_name,
                            sent,
                            f"Claims multimodal coverage despite evaluated modalities: '{mods_txt}'.",
                            f"claim_scope_overclaim:{zone_name}",
                        )

                if datasets_list:
                    for dm in _DATASET_COUNT_CLAIM_RE.finditer(sent):
                        raw_cnt = dm.group(1).lower()
                        claimed_n = int(raw_cnt) if raw_cnt.isdigit() else _NUMBER_WORDS.get(raw_cnt, 0)
                        if claimed_n >= 2 and claimed_n > len(datasets_list):
                            _add_f(
                                "dataset_count_mismatch",
                                zone_name,
                                sent,
                                f"Claims {claimed_n} benchmarks/datasets, but evaluated_scope lists only {len(datasets_list)}.",
                                f"claim_scope_dataset_count_mismatch:{zone_name}",
                            )

    if named_secs is not None:
        has_ms_lim = bool(named_secs["limitations"].strip() or _LIMITATIONS_INLINE_RE.search(sections["full"]))
        has_scope_lim = bool(
            (isinstance(scope_obj.get("limitations"), (list, str)) and bool(scope_obj.get("limitations")))
            or excl_claims
            or conds_txt
        )
        if not has_ms_lim and not has_scope_lim:
            _add_f(
                "missing_scope_limitations",
                "manuscript",
                "",
                "Neither manuscript Limitations section nor evaluated_scope boundaries/limitations provided.",
                "missing_scope_limitations:manuscript",
            )

    return issues, {
        "checked": True,
        "status": "FAIL" if issues else "PASS",
        "evaluated_scope_present": scope_present,
        "findings": findings,
    }


def _anchor_present_in_manuscript(
    anchor: str,
    norm_non_contrib: str,
    non_contrib_tables: str,
    raw_non_contrib: str,
    *,
    claim_ids: set[str] | None = None,
    valid_receipt_tokens: set[str] | None = None,
) -> bool:
    anc = _normalized_ws(anchor)
    if not anc:
        return False
    ref_m = re.match(r"^\\(?:eq)?ref\{([^{}\n]+)\}$", anc)
    if ref_m:
        lbl = ref_m.group(1).strip()
        return bool(lbl and re.search(rf"\\label\s*\{{{re.escape(lbl)}\}}", raw_non_contrib))

    claim_m = re.match(r"^\[claim:([A-Za-z0-9_-]+)\]$", anc, re.I)
    if claim_m:
        cid = claim_m.group(1)
        if claim_ids and cid in claim_ids:
            return True
        return bool(re.search(rf"\[claim:{re.escape(cid)}\]", norm_non_contrib, re.I))

    rec_m = re.match(r"^(?:run[_-]?id\s*[:=]\s*([A-Za-z0-9._-]+)|sha256\s*[:=]\s*([0-9a-f]{7,}))$", anc, re.I)
    if rec_m:
        tok = (rec_m.group(1) or rec_m.group(2) or "").strip().lower()
        if valid_receipt_tokens and tok in valid_receipt_tokens:
            return True
        if tok and re.search(rf"(?<!\w){re.escape(tok)}(?!\w)", raw_non_contrib.lower()):
            return True
        return False

    haystacks = (norm_non_contrib.lower(), non_contrib_tables.lower(), raw_non_contrib.lower())
    # Generate normalized variants (Table <-> Tab., Fig. <-> Figure, Eq. <-> Equation, etc.)
    variants = {anc.lower()}
    swaps = (
        (r"\btab\.", "table"),
        (r"\btable\b", "tab."),
        (r"\bfig\.", "figure"),
        (r"\bfigure\b", "fig."),
        (r"\bsec\.", "section"),
        (r"\bsection\b", "sec."),
        (r"\beq\.", "equation"),
        (r"\bequation\b", "eq."),
        (r"\bapp\.", "appendix"),
        (r"\bappendix\b", "app."),
        (r"\bthm\.", "theorem"),
        (r"\btheorem\b", "thm."),
        (r"\balg\.", "algorithm"),
        (r"\balgorithm\b", "alg."),
    )
    low_anc = anc.lower()
    for pat, rep in swaps:
        if re.search(pat, low_anc):
            variants.add(re.sub(pat, rep, low_anc))
    # Handle Eq. (3) vs Eq. 3
    extra: set[str] = set()
    for v in variants:
        extra.add(re.sub(r"\((\d+)\)", r"\1", v))
    variants |= extra

    for h in haystacks:
        for v in variants:
            if re.search(rf"(?<!\w){re.escape(v)}(?!\w)", h):
                return True
    return False


def _token_set(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]{3,}", text.lower()) if t not in {"the", "and", "for", "with", "that", "this", "our", "from", "into"}}


def _audit_contribution_evidence_map(
    sections: dict[str, str],
    named_secs: dict[str, Any] | None,
    ledger: dict[str, Any],
    source_map: dict[str, dict[str, Any]],
    fact_ids_all: set[str],
    claim_ids: set[str],
) -> tuple[list[str], dict[str, Any]]:
    raw_contribs = ledger.get("contributions")
    if raw_contribs is not None and not isinstance(raw_contribs, list):
        raise ValueError("contributions must be a list")

    valid_evidence_ids = set(source_map.keys()) | fact_ids_all | claim_ids
    valid_receipt_tokens: set[str] = {str(x).strip().lower() for x in valid_evidence_ids if _nonblank(x)}
    for rkey in ("receipts", "runs"):
        rlist = ledger.get(rkey)
        if isinstance(rlist, list):
            for ritem in rlist:
                if isinstance(ritem, dict):
                    for rf in ("id", "run_id", "sha256", "receipt_id"):
                        if _nonblank(ritem.get(rf)):
                            valid_receipt_tokens.add(str(ritem[rf]).strip().lower())
                elif _nonblank(ritem):
                    valid_receipt_tokens.add(str(ritem).strip().lower())
    for src in source_map.values():
        if _nonblank(src.get("sha256")):
            valid_receipt_tokens.add(str(src["sha256"]).strip().lower())

    issues: list[str] = []
    mappings: list[dict[str, Any]] = []
    grounded_records: list[tuple[dict[str, Any], set[str], int | None]] = []

    if isinstance(raw_contribs, list):
        for idx, contrib in enumerate(raw_contribs):
            if not isinstance(contrib, dict):
                raise ValueError(f"invalid contribution at index {idx}")
            cid = str(contrib.get("id") or f"CONTRIB_{idx + 1}").strip()
            ctext = str(contrib.get("text") or contrib.get("summary") or "").strip()

            ev_raw: list[str] = []
            for key in ("evidence_ids", "source_ids"):
                val = contrib.get(key)
                if isinstance(val, list):
                    ev_raw.extend(str(x).strip() for x in val if _nonplaceholder(x))

            anc_raw: list[str] = []
            if isinstance(contrib.get("anchors"), list):
                anc_raw.extend(str(x).strip() for x in contrib["anchors"] if _nonplaceholder(x))
            if _nonplaceholder(contrib.get("anchor")):
                anc_raw.append(str(contrib["anchor"]).strip())

            rec_raw: list[str] = []
            for key in ("receipt_ids", "run_ids"):
                val = contrib.get(key)
                if isinstance(val, list):
                    rec_raw.extend(str(x).strip() for x in val if _nonplaceholder(x))
            for key in ("run_id", "sha256"):
                if _nonplaceholder(contrib.get(key)):
                    rec_raw.append(str(contrib[key]).strip())

            c_issues: list[str] = []
            if not (ev_raw or anc_raw or rec_raw):
                c_issues.append(f"orphan_contribution_without_evidence:{cid}")
            else:
                for eid in ev_raw:
                    if eid not in valid_evidence_ids:
                        c_issues.append(f"unknown_contribution_evidence:{cid}:{eid}")
                    elif eid in source_map:
                        src = source_map[eid]
                        if src.get("verified") is not True or not _nonblank(src.get("locator")):
                            c_issues.append(f"contribution_evidence_unverified:{cid}:{eid}")
                if named_secs is not None:
                    for anc in anc_raw:
                        if not _anchor_present_in_manuscript(
                            anc,
                            named_secs["norm_non_contrib"],
                            named_secs["non_contrib_tables"],
                            named_secs["raw_non_contrib"],
                            claim_ids=claim_ids,
                            valid_receipt_tokens=valid_receipt_tokens,
                        ):
                            c_issues.append(f"contribution_anchor_missing_in_manuscript:{cid}:{_slug(anc)}")

            issues.extend(c_issues)
            is_mapped = len(c_issues) == 0
            mappings.append({
                "id": cid,
                "mapped": is_mapped,
                "evidence_ids": ev_raw,
                "anchors": anc_raw,
                "receipt_ids": rec_raw,
                "issues": c_issues,
            })
            if is_mapped:
                mb_idx = contrib.get("manuscript_bullet") if type(contrib.get("manuscript_bullet")) is int else None
                grounded_records.append((contrib, _token_set(ctext), mb_idx))

    unmapped_bullets: list[dict[str, Any]] = []
    ms_bullets = named_secs["contributions_bullets"] if named_secs is not None else []
    for b_idx, b_txt in enumerate(ms_bullets, start=1):
        inline_anchors = [m.group(0).strip() for m in _INLINE_EVIDENCE_ANCHOR_RE.finditer(b_txt)]
        valid_inline_anchors: list[str] = []
        missing_inline_anchors: list[str] = []
        for ianc in inline_anchors:
            if named_secs is None or _anchor_present_in_manuscript(
                ianc,
                named_secs["norm_non_contrib"],
                named_secs["non_contrib_tables"],
                named_secs["raw_non_contrib"],
                claim_ids=claim_ids,
                valid_receipt_tokens=valid_receipt_tokens,
            ):
                valid_inline_anchors.append(ianc)
            else:
                missing_inline_anchors.append(ianc)
                issues.append(f"contribution_anchor_missing_in_manuscript:bullet_{b_idx}:{_slug(ianc)}")
        has_inline_anchor = bool(valid_inline_anchors) and not missing_inline_anchors
        b_tokens = _token_set(b_txt)
        matched_ledger = False
        for _rec, rec_tokens, mb_idx in grounded_records:
            if mb_idx is not None and mb_idx == b_idx:
                matched_ledger = True
                break
            if b_tokens and rec_tokens:
                inter = len(b_tokens & rec_tokens)
                union = len(b_tokens | rec_tokens)
                jacc = inter / union if union else 0.0
                contain = inter / min(len(b_tokens), len(rec_tokens))
                if jacc >= 0.45 or contain >= 0.60:
                    matched_ledger = True
                    break
        if not (has_inline_anchor or matched_ledger):
            issues.append(f"unmapped_manuscript_contribution:bullet_{b_idx}")
            unmapped_bullets.append({"bullet_index": b_idx, "excerpt": b_txt[:160]})

    if not (isinstance(raw_contribs, list) and raw_contribs) and not ms_bullets:
        issues.append("missing_contributions_map:manuscript")

    mapped_count = sum(1 for m in mappings if m["mapped"])
    orphan_count = sum(1 for m in mappings if not m["mapped"])
    return issues, {
        "checked": True,
        "status": "FAIL" if issues else "PASS",
        "total_contributions": len(mappings),
        "mapped_count": mapped_count,
        "orphan_count": orphan_count,
        "mappings": mappings,
        "unmapped_manuscript_bullets": unmapped_bullets,
    }


def _audit_related_work_differentiation(
    sections: dict[str, str],
    named_secs: dict[str, Any] | None,
    ledger: dict[str, Any],
    source_map: dict[str, dict[str, Any]],
    scorecards_obj: dict[str, Any] | None,
    target_id: str | None,
) -> tuple[list[str], dict[str, Any]]:
    issues: list[str] = []
    expected_ids: list[str] = []
    comp_meta: dict[str, dict[str, Any]] = {}
    panel_incomplete: list[str] = []
    eff_target_id: str | None = target_id.strip() if _nonblank(target_id) else None

    def _reg_meta(cid: str, meta: dict[str, Any]) -> None:
        if cid not in expected_ids:
            expected_ids.append(cid)
        entry = comp_meta.setdefault(cid, {"tokens": set(), "cite_keys": set()})
        entry["tokens"].add(cid)
        for fk in ("id", "name", "title", "citation_key", "cite_key", "bibtex_key"):
            v = meta.get(fk)
            if _nonblank(v):
                entry["tokens"].add(str(v).strip())
        for ck in ("citation_key", "cite_key", "bibtex_key"):
            v = meta.get(ck)
            if _nonblank(v):
                entry["cite_keys"].add(str(v).strip())
        if isinstance(meta.get("aliases"), list):
            for a in meta["aliases"]:
                if _nonblank(a):
                    entry["tokens"].add(str(a).strip())
        if isinstance(meta.get("authors"), list) and meta["authors"]:
            first_a = str(meta["authors"][0]).strip()
            if first_a:
                surname = first_a.split()[-1].strip(",")
                if len(surname) >= 3:
                    entry["tokens"].add(surname)
        elif _nonblank(meta.get("authors")):
            surname = str(meta["authors"]).strip().split(",")[0].split()[-1]
            if len(surname) >= 3:
                entry["tokens"].add(surname)

    if scorecards_obj is not None:
        if not isinstance(scorecards_obj, dict):
            raise ValueError("scorecards JSON root must be an object")
        prof_map: dict[str, dict[str, Any]] = {}
        if isinstance(scorecards_obj.get("profiles"), list):
            for p in scorecards_obj["profiles"]:
                if isinstance(p, dict) and _nonblank(p.get("id")):
                    prof_map[p["id"].strip()] = p

        if isinstance(scorecards_obj.get("related_work_comparison"), dict):
            rwc = scorecards_obj["related_work_comparison"]
            if eff_target_id is None and _nonblank(rwc.get("target_id")):
                eff_target_id = str(rwc["target_id"]).strip()
            for cw in rwc.get("scored_related_ids", []):
                if _nonblank(cw):
                    cws = str(cw).strip()
                    _reg_meta(cws, prof_map.get(cws, {}))
            for cw in rwc.get("unscored_closest_work_ids", []):
                if _nonblank(cw):
                    cws = str(cw).strip()
                    _reg_meta(cws, prof_map.get(cws, {}))
                    panel_incomplete.append(cws)
                    issues.append(f"related_work_panel_incomplete:{cws}")
        elif isinstance(scorecards_obj.get("profiles"), list):
            if eff_target_id is None and _nonblank(scorecards_obj.get("target_id")):
                eff_target_id = str(scorecards_obj["target_id"]).strip()
            cw_list: list[str] = []
            if eff_target_id is not None:
                if eff_target_id not in prof_map:
                    issues.append(f"target_profile_not_found:{eff_target_id}")
                else:
                    raw_cw = prof_map[eff_target_id].get("closest_work", [])
                    if isinstance(raw_cw, list):
                        cw_list = [str(x).strip() for x in raw_cw if _nonblank(x)]
            else:
                with_cw = [p for p in prof_map.values() if isinstance(p.get("closest_work"), list) and p.get("closest_work")]
                if len(with_cw) == 1:
                    eff_target_id = with_cw[0]["id"].strip()
                    cw_list = [str(x).strip() for x in with_cw[0]["closest_work"] if _nonblank(x)]
                elif len(with_cw) > 1:
                    issues.append("target_id_required_for_scorecards:scorecards")
                    for p in with_cw:
                        for x in p["closest_work"]:
                            if _nonblank(x) and str(x).strip() not in cw_list:
                                cw_list.append(str(x).strip())
                else:
                    cw_list = list(prof_map.keys())
            for cw in cw_list:
                p = prof_map.get(cw)
                _reg_meta(cw, p or {})
                if p is None or p.get("reading_basis") != "full_text":
                    panel_incomplete.append(cw)
                    issues.append(f"related_work_panel_incomplete:{cw}")

    # Merge ledger closest_work / related_work and methods[*].closest_work_source_ids
    for lkey in ("closest_work", "related_work"):
        items = ledger.get(lkey)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, str) and item.strip():
                    _reg_meta(item.strip(), source_map.get(item.strip(), {}))
                elif isinstance(item, dict) and _nonblank(item.get("id")):
                    cid = item["id"].strip()
                    merged = dict(source_map.get(cid, {}))
                    merged.update(item)
                    _reg_meta(cid, merged)

    for m in ledger.get("methods", []):
        if isinstance(m, dict) and isinstance(m.get("closest_work_source_ids"), list):
            for sid in m["closest_work_source_ids"]:
                if _nonblank(sid):
                    sids = str(sid).strip()
                    _reg_meta(sids, source_map.get(sids, {}))

    for cid in expected_ids:
        if cid in source_map:
            _reg_meta(cid, source_map[cid])

    cited_and_contrasted: list[str] = []
    missing_from_ms: list[str] = []
    uncited_list: list[str] = []
    lacks_diff_list: list[str] = []
    per_competitor: list[dict[str, Any]] = []

    if named_secs is not None and expected_ids:
        raw_tables_low = named_secs["raw_tables"].lower()
        norm_tables_low = sections["tables"].lower()
        ordered_secs = named_secs["ordered_sections"]

        # Pre-split sentences per prose section
        sec_sentences: list[tuple[str, list[str]]] = []
        for bname, _raw_c, norm_c in ordered_secs:
            if bname == "limitations":
                continue
            sents = _split_sentences_list(norm_c)
            if sents:
                sec_sentences.append((bname, sents))

        mentioned_in_prose_non_table = 0
        all_prose_lack_diff = True

        for cid in expected_ids:
            meta = comp_meta[cid]
            tokens = sorted(meta["tokens"], key=len, reverse=True)
            cite_keys = meta["cite_keys"] | {cid}
            tok_res = [re.compile(rf"(?<!\w){re.escape(t)}(?!\w)", re.I) for t in tokens if len(t) >= 2]

            in_table = any(r.search(norm_tables_low) or r.search(raw_tables_low) for r in tok_res) or any(
                ck.lower() in raw_tables_low for ck in cite_keys
            )

            mention_locs: list[tuple[str, int, str]] = []  # (bname, sent_idx, sent_txt)
            for bname, sents in sec_sentences:
                for s_idx, sent in enumerate(sents):
                    hit = any(r.search(sent) for r in tok_res)
                    if not hit:
                        for rm in _REF_TOKEN_CITE_RE.finditer(sent):
                            rkeys = {k.strip().lower() for k in rm.group(1).split(",") if k.strip()}
                            if any(ck.lower() in rkeys for ck in cite_keys):
                                hit = True
                                break
                    if hit:
                        mention_locs.append((bname, s_idx, sent))

            if not in_table and not mention_locs:
                missing_from_ms.append(cid)
                issues.append(f"missing_closest_work_in_manuscript:{cid}")
                per_competitor.append({"id": cid, "status": "missing"})
                continue

            has_cite = in_table
            if not has_cite:
                for _bn, _si, sent in mention_locs:
                    if _CITE_ANY_RE.search(sent) or _REF_TOKEN_CITE_RE.search(sent):
                        has_cite = True
                        break
            if not has_cite:
                uncited_list.append(cid)
                issues.append(f"uncited_closest_work:{cid}")

            has_diff = in_table
            if not has_diff:
                sec_map_lookup = {id(sents): sents for _, sents in sec_sentences}
                for bname, s_idx, sent in mention_locs:
                    if _DIFF_CONTRAST_RE.search(sent):
                        has_diff = True
                        break
                    # Check adjacent sentence in same section
                    for sb, sents in sec_sentences:
                        if sb == bname and 0 <= s_idx < len(sents) and sents[s_idx] == sent:
                            neighbors: list[str] = []
                            if s_idx > 0:
                                neighbors.append(sents[s_idx - 1])
                            if s_idx + 1 < len(sents):
                                neighbors.append(sents[s_idx + 1])
                            if any(_DIFF_CONTRAST_RE.search(nb) for nb in neighbors):
                                has_diff = True
                                break
                    if has_diff:
                        break
                _ = sec_map_lookup

            if not has_diff:
                lacks_diff_list.append(cid)
                issues.append(f"related_work_lacks_differentiation:{cid}")

            if mention_locs and not in_table:
                mentioned_in_prose_non_table += 1
                if has_diff:
                    all_prose_lack_diff = False

            if has_cite and has_diff:
                cited_and_contrasted.append(cid)
            per_competitor.append({
                "id": cid,
                "in_table": in_table,
                "mentioned_in_prose": bool(mention_locs),
                "cited": has_cite,
                "differentiated": has_diff,
            })

        if mentioned_in_prose_non_table >= 2 and all_prose_lack_diff:
            issues.append("generic_related_work_summary:manuscript")

    return issues, {
        "checked": True,
        "status": "FAIL" if issues else "PASS",
        "target_id": eff_target_id,
        "expected_competitors": expected_ids,
        "cited_and_contrasted": cited_and_contrasted,
        "missing_from_manuscript": missing_from_ms,
        "uncited": uncited_list,
        "lacks_differentiation": lacks_diff_list,
        "panel_incomplete": sorted(set(panel_incomplete)),
        "per_competitor": per_competitor,
    }


# ---------------------------------------------------------------------------
# Main Check Entry Point
# ---------------------------------------------------------------------------


def check(
    ledger: dict[str, Any],
    manuscript_text: str | None = None,
    sources_dir: str | Path | None = None,
    manuscript_path: str | Path | None = None,
    *,
    audit_arguments: bool = False,
    check_scope: bool | None = None,
    check_contributions: bool | None = None,
    check_related_work: bool | None = None,
    scorecards: dict[str, Any] | str | Path | None = None,
    target_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(ledger, dict):
        raise ValueError("ledger must be an object")
    for name in ("sources", "claims", "methods", "numeric_facts"):
        if not isinstance(ledger.get(name), list):
            raise ValueError(f"{name} must be a list")

    if isinstance(manuscript_path, str) and not manuscript_path.strip():
        raise ValueError("Invalid empty manuscript_path")
    if isinstance(sources_dir, str) and not sources_dir.strip():
        raise ValueError("Invalid empty sources_dir")
    if isinstance(target_id, str) and not target_id.strip():
        raise ValueError("Invalid empty target_id")

    scorecards_obj: dict[str, Any] | None = None
    if scorecards is not None:
        if isinstance(scorecards, dict):
            scorecards_obj = scorecards
        else:
            if isinstance(scorecards, str) and not scorecards.strip():
                raise ValueError("Invalid empty scorecards path")
            sc_path = Path(scorecards)
            raw_sc = sc_path.read_text(encoding="utf-8")
            scorecards_obj = json.loads(raw_sc, parse_constant=_reject_nonfinite)
            if not isinstance(scorecards_obj, dict):
                raise ValueError("scorecards JSON root must be an object")

    eff_scope = False if check_scope is False else (
        audit_arguments or bool(check_scope) or ("evaluated_scope" in ledger) or ("experiment_scope" in ledger)
    )
    eff_contrib = False if check_contributions is False else (
        audit_arguments or bool(check_contributions) or ("contributions" in ledger)
    )
    eff_related = False if check_related_work is False else (
        audit_arguments or bool(check_related_work) or (scorecards_obj is not None) or ("related_work" in ledger) or ("closest_work" in ledger)
    )

    if manuscript_text is None and manuscript_path is not None:
        manuscript_text = Path(manuscript_path).read_text(encoding="utf-8")

    issues: list[str] = []
    source_map: dict[str, dict[str, Any]] = {}
    for index, source in enumerate(ledger["sources"]):
        if not isinstance(source, dict) or not _nonblank(source.get("id")):
            raise ValueError(f"invalid source at index {index}")
        sid = source["id"]
        if sid in source_map:
            issues.append(f"duplicate_source:{sid}")
        source_map[sid] = source
        if source.get("verified") is True and (
            not _nonblank(source.get("locator"))
            or not _nonblank(source.get("verified_by"))
            or not _nonblank(source.get("verified_at"))
        ):
            issues.append(f"unsupported_verification_declaration:{sid}")

    declared_rqs: set[str] = set()
    raw_rqs = ledger.get("rqs") if isinstance(ledger.get("rqs"), list) else ledger.get("research_questions")
    if isinstance(raw_rqs, list):
        for rq in raw_rqs:
            if isinstance(rq, str) and rq.strip():
                declared_rqs.add(rq.strip())
            elif isinstance(rq, dict) and _nonblank(rq.get("id")):
                declared_rqs.add(rq["id"].strip())

    fact_ids_all = {
        fact["id"]
        for fact in ledger["numeric_facts"]
        if isinstance(fact, dict) and _nonblank(fact.get("id"))
    }
    valid_evidence_ids = set(source_map.keys()) | fact_ids_all

    claim_ids: set[str] = set()
    for index, claim in enumerate(ledger["claims"]):
        if not isinstance(claim, dict) or not _nonblank(claim.get("id")):
            raise ValueError(f"invalid claim at index {index}")
        cid = claim["id"]
        if cid in claim_ids:
            issues.append(f"duplicate_claim:{cid}")
        claim_ids.add(cid)
        if claim.get("kind") not in KINDS or type(claim.get("material")) is not bool:
            issues.append(f"invalid_claim_classification:{cid}")
        supports = claim.get("source_ids")
        if not isinstance(supports, list) or any(not _nonblank(x) for x in supports):
            issues.append(f"invalid_support_list:{cid}")
            continue
        for sid in supports:
            if sid not in source_map:
                issues.append(f"unknown_source:{cid}:{sid}")
        if claim.get("material") and claim.get("kind") in {"reported", "inferred"}:
            if not supports:
                issues.append(f"material_claim_without_source:{cid}")
            elif not any(
                sid in source_map
                and source_map[sid].get("verified") is True
                and _nonblank(source_map[sid].get("locator"))
                and _nonblank(source_map[sid].get("verified_by"))
                and _nonblank(source_map[sid].get("verified_at"))
                for sid in supports
            ):
                issues.append(f"material_claim_without_verified_locator:{cid}")
        if claim.get("material") and claim.get("kind") == "unknown":
            issues.append(f"material_claim_marked_unknown:{cid}")

        # Extraneous / off-scope / missing RQ or evidence link checks
        scope_rel = str(claim.get("scope_relevance", "")).strip().lower()
        if claim.get("extraneous") is True or scope_rel in {"extraneous", "off_scope", "tangential", "out_of_scope", "irrelevant"}:
            issues.append(f"extraneous_claim:{cid}")

        has_rq_key = "rq_id" in claim or "rq_ids" in claim
        claim_rq_list: list[str] = []
        if _nonblank(claim.get("rq_id")):
            claim_rq_list.append(claim["rq_id"].strip())
        if isinstance(claim.get("rq_ids"), list):
            claim_rq_list.extend(str(x).strip() for x in claim["rq_ids"] if _nonblank(x))
        if declared_rqs:
            if claim.get("material") and not claim_rq_list:
                issues.append(f"claim_missing_rq_link:{cid}")
            for rqid in claim_rq_list:
                if rqid not in declared_rqs:
                    issues.append(f"unknown_claim_rq:{cid}:{rqid}")
        elif has_rq_key and not claim_rq_list:
            issues.append(f"claim_missing_rq_link:{cid}")

        if "evidence_ids" in claim:
            ev_ids = claim.get("evidence_ids")
            if not isinstance(ev_ids, list) or not ev_ids or any(not _nonblank(x) for x in ev_ids):
                if claim.get("kind") in {"reported", "inferred"}:
                    issues.append(f"unsupported_side_claim:{cid}")
            else:
                for eid in ev_ids:
                    if eid not in valid_evidence_ids:
                        issues.append(f"unknown_evidence:{cid}:{eid}")

    method_ids: set[str] = set()
    for index, method in enumerate(ledger["methods"]):
        if not isinstance(method, dict) or not _nonblank(method.get("id")):
            raise ValueError(f"invalid method at index {index}")
        mid = method["id"]
        if mid in method_ids:
            issues.append(f"duplicate_method:{mid}")
        method_ids.add(mid)
        origin = method.get("origin")
        if origin not in METHOD_ORIGINS:
            issues.append(f"invalid_method_origin:{mid}")
            continue
        sources = method.get("source_ids")
        if not isinstance(sources, list) or any(not _nonblank(x) for x in sources):
            issues.append(f"invalid_method_sources:{mid}")
            continue
        for sid in sources:
            if sid not in source_map:
                issues.append(f"unknown_method_source:{mid}:{sid}")
            elif origin in {"reused", "adapted", "combined"} and (
                source_map[sid].get("verified") is not True
                or not _nonblank(source_map[sid].get("locator"))
                or not _nonblank(source_map[sid].get("verified_by"))
            ):
                issues.append(f"method_lineage_source_unverified:{mid}:{sid}")
        if origin in {"reused", "adapted", "combined"} and not sources:
            issues.append(f"missing_method_lineage:{mid}")
        if origin != "reused" and not _nonblank(method.get("exact_change")):
            issues.append(f"missing_method_change:{mid}")

        has_derivation = _nonblank(method.get("derivation_evidence")) or _nonblank(
            method.get("difference_evidence")
        )
        if origin == "newly_derived" and not has_derivation:
            issues.append(f"missing_derivation_evidence:{mid}")

        if method.get("novelty_claimed") is True:
            if not _has_complete_novelty_justification(method, source_map):
                issues.append(f"unsupported_method_novelty:{mid}")
            if origin == "reused":
                issues.append(f"reused_method_claimed_as_new:{mid}")

        if method.get("grand_name") is True and origin in {"reused", "adapted", "combined"}:
            issues.append(f"inflated_method_name:{mid}")
        elif method.get("grand_name") is True and origin == "newly_derived":
            if not _has_complete_novelty_justification(method, source_map):
                issues.append(f"unsupported_grand_method_name:{mid}")
            else:
                issues.append(f"grand_method_name_requires_review:{mid}")

        # Inspect method name/aliases independently of grand_name boolean
        declared_names = []
        if _nonblank(method.get("name")):
            declared_names.append(method["name"])
        if isinstance(method.get("aliases"), list):
            declared_names.extend(a for a in method["aliases"] if _nonblank(a))
        if any(_name_looks_grandiose(nm) for nm in declared_names):
            if origin in {"reused", "adapted", "combined"} or (origin == "newly_derived" and not has_derivation):
                issues.append(f"inflated_method_name:{mid}")

        # F19: Mandatory Parsimony / Anti-Overcomplication check on multi-component or parsimony-audited methods
        parsimony = method.get("parsimony_audit")
        components = method.get("components")
        p_dict = parsimony if isinstance(parsimony, dict) else {}
        if (
            _is_false_flag(method.get("complexity_justified"))
            or _is_true_flag(method.get("simpler_equal_or_better"))
            or _is_false_flag(method.get("passed"))
            or _is_true_flag(p_dict.get("simpler_equal_or_better"))
            or _is_false_flag(p_dict.get("passed"))
            or _is_false_flag(p_dict.get("complexity_justified"))
        ):
            issues.append(f"overcomplicated_method:{mid}")

        is_multi_component = (
            (isinstance(components, list) and len(components) >= 2)
            or _is_true_flag(method.get("multi_component"))
            or (origin == "combined" and len(sources) >= 2)
            or isinstance(parsimony, dict)
            or "simpler_equal_or_better" in method
        )
        if is_multi_component:
            has_m_alt = "simplest_alternative" in method
            has_p_alt = "simplest_alternative" in p_dict
            alt_bad = (has_m_alt and not _nonplaceholder(method.get("simplest_alternative"))) or (
                has_p_alt and not _nonplaceholder(p_dict.get("simplest_alternative"))
            )
            if alt_bad or not (
                _nonplaceholder(method.get("simplest_alternative")) or _nonplaceholder(p_dict.get("simplest_alternative"))
            ):
                issues.append(f"missing_simplest_alternative:{mid}")

            def _valid_comp_just(cj: Any) -> bool:
                if isinstance(cj, dict):
                    norm_just = {str(k).strip().lower(): v for k, v in cj.items() if _nonblank(k)}
                    all_vals_ok = bool(norm_just) and all(_nonplaceholder(v) for v in cj.values())
                    if isinstance(components, list) and components:
                        req_comps = [str(c).strip().lower() for c in components if _nonblank(c)]
                        covers_all = all(c in norm_just and _nonplaceholder(norm_just[c]) for c in req_comps)
                        return all_vals_ok and covers_all
                    return all_vals_ok
                if isinstance(cj, list):
                    min_len = len(components) if isinstance(components, list) and components else 1
                    return len(cj) >= min_len and all(_nonplaceholder(v) for v in cj)
                return False

            has_m_abl = "ablation_evidence" in method
            has_p_abl = "ablation_evidence" in p_dict
            has_m_cj = "component_justifications" in method and method.get("component_justifications") is not None
            has_p_cj = "component_justifications" in p_dict and p_dict.get("component_justifications") is not None
            abl_bad = (has_m_abl and not _nonplaceholder(method.get("ablation_evidence"))) or (
                has_p_abl and not _nonplaceholder(p_dict.get("ablation_evidence"))
            )
            cj_bad = (has_m_cj and not _valid_comp_just(method.get("component_justifications"))) or (
                has_p_cj and not _valid_comp_just(p_dict.get("component_justifications"))
            )
            any_valid_abl = _nonplaceholder(method.get("ablation_evidence")) or _nonplaceholder(
                p_dict.get("ablation_evidence")
            )
            any_valid_cj = (has_m_cj and _valid_comp_just(method.get("component_justifications"))) or (
                has_p_cj and _valid_comp_just(p_dict.get("component_justifications"))
            )
            if abl_bad or cj_bad or not (any_valid_abl or any_valid_cj):
                issues.append(f"missing_component_ablation:{mid}")

    fact_ids: set[str] = set()
    for index, fact in enumerate(ledger["numeric_facts"]):
        if not isinstance(fact, dict) or not _nonblank(fact.get("id")):
            raise ValueError(f"invalid numeric fact at index {index}")
        fid = fact["id"]
        if fid in fact_ids:
            issues.append(f"duplicate_numeric_fact:{fid}")
        fact_ids.add(fid)
        observations = fact.get("occurrences")
        if not isinstance(observations, list) or not observations:
            issues.append(f"numeric_fact_without_occurrences:{fid}")
            continue
        if any(
            not isinstance(x, dict)
            or not _nonblank(x.get("location"))
            or x.get("value") is None
            or isinstance(x.get("value"), bool)
            or not _nonblank(str(x.get("value")))
            or not _nonblank(x.get("unit"))
            for x in observations
        ):
            issues.append(f"invalid_numeric_occurrence:{fid}")
            continue
        values = {(str(x["value"]), x["unit"]) for x in observations}
        if len(values) > 1:
            issues.append(f"numeric_fact_mismatch:{fid}")

    manuscript_checked = False
    grandiose_findings: list[dict[str, Any]] = []
    manuscript_numeric_checks: list[dict[str, Any]] = []
    sections: dict[str, str] = {"title": "", "abstract": "", "tables": "", "section_headings": "", "body": "", "full": ""}
    named_secs: dict[str, Any] | None = None
    path_is_tex = True if (manuscript_path is not None and str(manuscript_path).lower().endswith(".tex")) else None
    if manuscript_text is not None:
        manuscript_checked = True
        sections = _extract_sections(manuscript_text, is_tex=path_is_tex)
        g_issues, grandiose_findings = _scan_grandiose_branding(sections, ledger, source_map)
        issues.extend(g_issues)
        n_issues, manuscript_numeric_checks = _check_manuscript_claims_and_numbers(sections, ledger)
        issues.extend(n_issues)
        if eff_scope or eff_contrib or eff_related:
            named_secs = _extract_named_sections(manuscript_text, is_tex=path_is_tex)

    sources_dir_checked = False
    source_locator_checks: list[dict[str, Any]] = []
    if sources_dir is not None:
        sources_dir_checked = True
        s_issues, source_locator_checks = _check_sources_dir(Path(sources_dir), ledger)
        issues.extend(s_issues)

    # F29#4 Deep Paper Argument Audits (opt-in or auto-activated by explicit keys)
    claim_scope_audit: dict[str, Any] = {"checked": False, "status": "NOT_RUN", "evaluated_scope_present": False, "findings": []}
    if eff_scope:
        cs_issues, claim_scope_audit = _audit_claim_scope(sections, named_secs, ledger)
        issues.extend(cs_issues)

    contribution_evidence_map: dict[str, Any] = {
        "checked": False, "status": "NOT_RUN", "total_contributions": 0, "mapped_count": 0, "orphan_count": 0, "mappings": [], "unmapped_manuscript_bullets": []
    }
    if eff_contrib:
        ce_issues, contribution_evidence_map = _audit_contribution_evidence_map(
            sections, named_secs, ledger, source_map, fact_ids_all, claim_ids
        )
        issues.extend(ce_issues)

    related_work_diff: dict[str, Any] = {
        "checked": False, "status": "NOT_RUN", "target_id": target_id, "expected_competitors": [],
        "cited_and_contrasted": [], "missing_from_manuscript": [], "uncited": [],
        "lacks_differentiation": [], "panel_incomplete": [], "per_competitor": [],
    }
    if eff_related:
        rw_issues, related_work_diff = _audit_related_work_differentiation(
            sections, named_secs, ledger, source_map, scorecards_obj, target_id
        )
        issues.extend(rw_issues)

    arg_audits_enabled = bool(eff_scope or eff_contrib or eff_related)
    any_arg_fail = any(
        d["checked"] and d["status"] == "FAIL"
        for d in (claim_scope_audit, contribution_evidence_map, related_work_diff)
    )
    rec_trans_cap = 3 if any_arg_fail else None
    rec_evid_cap = 4 if (
        (contribution_evidence_map["checked"] and contribution_evidence_map["status"] == "FAIL")
        or (claim_scope_audit["checked"] and claim_scope_audit["status"] == "FAIL")
        or (related_work_diff["checked"] and related_work_diff["status"] == "FAIL")
    ) else None

    argument_audit_summary = {
        "enabled": arg_audits_enabled,
        "claim_scope_alignment": {
            "status": claim_scope_audit["status"],
            "finding_count": len(claim_scope_audit["findings"]),
        },
        "contribution_evidence_map": {
            "status": contribution_evidence_map["status"],
            "mapped_count": contribution_evidence_map["mapped_count"],
            "orphan_count": contribution_evidence_map["orphan_count"],
        },
        "related_work_differentiation": {
            "status": related_work_diff["status"],
            "expected_count": len(related_work_diff["expected_competitors"]),
            "missing_count": len(related_work_diff["missing_from_manuscript"]),
            "lacks_differentiation_count": len(related_work_diff["lacks_differentiation"]),
        },
        "recommended_transparency_cap": rec_trans_cap,
        "recommended_evidence_cap": rec_evid_cap,
    }

    unique_issues = sorted(set(issues))
    return {
        "status": "structural_issues" if unique_issues else "structure_passed",
        "issues": unique_issues,
        "counts": {
            key: len(ledger[key])
            for key in ("sources", "claims", "methods", "numeric_facts")
        },
        "manuscript_checked": manuscript_checked,
        "sources_dir_checked": sources_dir_checked,
        "grandiose_findings": grandiose_findings,
        "manuscript_numeric_checks": manuscript_numeric_checks,
        "source_locator_checks": source_locator_checks,
        "argument_audits_enabled": arg_audits_enabled,
        "claim_scope_audit": claim_scope_audit,
        "contribution_evidence_map": contribution_evidence_map,
        "related_work_differentiation": related_work_diff,
        "argument_audit": argument_audit_summary,
        "warning": (
            "A structural pass does not verify scientific truth, causal validity, "
            "or full semantic entailment."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger_json", nargs="?", help="Path to ledger JSON file")
    parser.add_argument("--ledger", help="Path to ledger JSON file")
    parser.add_argument("--manuscript", help="Path to manuscript (.md or .tex) to audit against ledger")
    parser.add_argument("--sources-dir", help="Directory containing local source files/extractions for quote & locator checks")
    parser.add_argument("--audit-arguments", action="store_true", help="Enable all F29#4 deep paper argument audits")
    parser.add_argument("--check-scope", action="store_true", help="Enable Claim-Scope Alignment audit")
    parser.add_argument("--check-contributions", action="store_true", help="Enable Contribution-to-Evidence 1-to-1 Map audit")
    parser.add_argument("--check-related-work", action="store_true", help="Enable Related-Work Differentiation audit")
    parser.add_argument("--scorecards", help="Path to F24 scorecards.json or compare_scorecards.py output JSON")
    parser.add_argument("--target-id", help="Target profile ID inside --scorecards")
    parser.add_argument("--out", help="Write full JSON output to path")
    parser.add_argument("--compact", action="store_true", help="Emit compact bounded JSON summary")
    args = parser.parse_args(argv)

    if args.ledger is not None and not args.ledger.strip():
        print(json.dumps({"error": "Invalid empty path passed to --ledger"}), file=sys.stderr)
        return 2
    if args.ledger_json is not None and not args.ledger_json.strip():
        print(json.dumps({"error": "Invalid empty path passed to ledger_json"}), file=sys.stderr)
        return 2
    if args.manuscript is not None and not args.manuscript.strip():
        print(json.dumps({"error": "Invalid empty path passed to --manuscript"}), file=sys.stderr)
        return 2
    if args.sources_dir is not None and not args.sources_dir.strip():
        print(json.dumps({"error": "Invalid empty path passed to --sources-dir"}), file=sys.stderr)
        return 2
    if args.scorecards is not None and not args.scorecards.strip():
        print(json.dumps({"error": "Invalid empty path passed to --scorecards"}), file=sys.stderr)
        return 2
    if args.target_id is not None and not args.target_id.strip():
        print(json.dumps({"error": "Invalid empty value passed to --target-id"}), file=sys.stderr)
        return 2
    if args.out is not None and not args.out.strip():
        print(json.dumps({"error": "Invalid empty path passed to --out"}), file=sys.stderr)
        return 2

    ledger_path = args.ledger if args.ledger is not None else args.ledger_json
    if not ledger_path:
        print(json.dumps({"error": "ledger JSON path is required (positional or --ledger)"}), file=sys.stderr)
        return 2
    if args.ledger is not None and args.ledger_json is not None and Path(args.ledger).resolve() != Path(args.ledger_json).resolve():
        print(json.dumps({"error": "conflicting positional ledger_json and --ledger paths"}), file=sys.stderr)
        return 2

    try:
        ledger_obj = json.loads(Path(ledger_path).read_text(encoding="utf-8"), parse_constant=_reject_nonfinite)
        manuscript_text = Path(args.manuscript).read_text(encoding="utf-8") if args.manuscript is not None else None
        result = check(
            ledger_obj,
            manuscript_text=manuscript_text,
            sources_dir=args.sources_dir,
            manuscript_path=args.manuscript,
            audit_arguments=args.audit_arguments,
            check_scope=True if args.check_scope else None,
            check_contributions=True if args.check_contributions else None,
            check_related_work=True if args.check_related_work else None,
            scorecards=args.scorecards,
            target_id=args.target_id,
        )
        out_str: str | None = None
        if args.out is not None:
            out_path = Path(args.out.strip())
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            out_str = str(out_path)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2

    if args.compact:
        issues_list = result["issues"]
        compact_out: dict[str, Any] = {
            "compact": True,
            "status": result["status"],
            "counts": result["counts"],
            "total_issues": len(issues_list),
            "issues_truncated": max(0, len(issues_list) - 15),
            "issues": issues_list[:15],
            "manuscript_checked": result["manuscript_checked"],
            "sources_dir_checked": result["sources_dir_checked"],
            "grandiose_finding_count": len(result["grandiose_findings"]),
            "manuscript_numeric_check_count": len(result["manuscript_numeric_checks"]),
            "source_locator_check_count": len(result["source_locator_checks"]),
            "argument_audits_enabled": result["argument_audits_enabled"],
            "argument_audit": result["argument_audit"],
        }
        if out_str is not None:
            compact_out["artifact_path"] = out_str
        raw = json.dumps(compact_out, separators=(",", ":"))
        for cap in (15, 8, 4, 2, 0):
            if len(raw.encode("utf-8")) <= MAX_COMPACT_BYTES:
                break
            compact_out["issues"] = issues_list[:cap]
            compact_out["issues_truncated"] = max(0, len(issues_list) - cap)
            raw = json.dumps(compact_out, separators=(",", ":"))
        print(raw)
    else:
        print(json.dumps(result, indent=2))
    return 0 if result["status"] == "structure_passed" else 1


if __name__ == "__main__":
    sys.exit(main())
