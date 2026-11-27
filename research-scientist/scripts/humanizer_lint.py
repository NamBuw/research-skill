#!/usr/bin/env python3
"""Humanizer, scholarly prose, anti-sycophancy, claim-preservation, and 8-gram overlap linter.

Attributions & License Notices:
- Pattern taxonomy (sections 1-26), weak-alone/cluster philosophy, quotation/proper-name
  guards, and claim-preservation rules are adapted from `blader/humanizer` (MIT License,
  Copyright (c) 2025 Siqi Chen; bundled reference in modules/humanizer/UPSTREAM_SKILL.md).
- LaTeX/Markdown prose masking, AI-tell/hedging/booster/connective-stacking/rhythm rules,
  and 8-gram originality overlap detection are adapted and extended from
  `research-paper-lifecycle-skills` (Apache License 2.0, Copyright 2026 Shaishav Maisuria):
    "This product includes research-paper lifecycle agent skills originally developed by
     Shaishav Maisuria."
  Modified and extended for `research-scientist` with anti-sycophancy checks, technical
  domain-term exemptions, and claim-preservation diffing.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Masking constants (adapted from research-paper-lifecycle-skills texprose.py)
# ---------------------------------------------------------------------------

MASK_ENVS = frozenset({
    "verbatim", "verbatim*", "lstlisting", "minted", "alltt",
    "equation", "equation*", "align", "align*", "gather", "gather*",
    "multline", "multline*", "eqnarray", "eqnarray*", "displaymath",
    "tikzpicture", "algorithmic", "algorithm", "algorithm2e",
    "thebibliography", "filecontents", "filecontents*", "CCSXML",
    "tabular", "tabularx", "tabular*", "longtable", "array",
})

_BEGIN_ENV_RE = re.compile(r"\\begin\{([^{}]+)\}")
_END_ENV_RE = re.compile(r"\\end\{([^{}]+)\}")
_CITE_RE = re.compile(
    r"\\(?:cite[a-zA-Z]*\*?|textcite|parencite|autocite|footcite|fullcite|"
    r"nocite|ref|eqref|autoref|cref|Cref|pageref|label|input|include|"
    r"bibliography|bibliographystyle)(?:\[[^\[\]]*\]){0,2}\{[^{}]*\}"
)
_URL_CMD_RE = re.compile(r"\\(?:url|href)\{[^{}]*\}(?:\{[^{}]*\})?")
_BARE_URL_RE = re.compile(r"https?://\S+")
_TEX_COMMENT_RE = re.compile(r"(?<!\\)%.*$")
_BACKTICK_RUN_RE = re.compile(r"`+")
_TEX_VERBATIM_ENVS = frozenset({"verbatim", "verbatim*", "lstlisting", "minted", "alltt"})
_TEX_VERB_RE = re.compile(r"\\verb(?:\*([^\n])|([^A-Za-z*\n]))")
_DISPLAY_DOLLAR_RE = re.compile(r"(?<!\\)\$\$")
_DISPLAY_BRACKET_OPEN_RE = re.compile(r"(?<!\\)\\\[")
_DISPLAY_BRACKET_CLOSE_RE = re.compile(r"(?<!\\)\\\]")
_DISPLAY_OPEN_RE = re.compile(r"(?<!\\)(?:\$\$|\\\[)")
_DISPLAY_MATH_INLINE_RE = re.compile(r"\$\$[^$]++\$\$|\\\[(?:[^\\]|\\(?!\[|\]))++\\\]")
_INLINE_MATH_RE = re.compile(r"\$(?:\\.|[^$\\\n])+\$|\\\((?:[^\\\n]|\\(?!\(|\))[^\n])++\\\)")
_MD_LINK_URL_RE = re.compile(r"\]\((?:[^()\n]|(?<!\])\()+\)")
_MD_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$")
_MD_HR_RE = re.compile(r"^\s{0,3}(?:---+|\*\*\*+|___+)\s*$")
_TEX_SECTION_RE = re.compile(
    r"\\(?:part|chapter|section|subsection|subsubsection|paragraph)\*?\{([^{}]*)\}"
)
_TEX_HEADING_CMD_RE = re.compile(
    r"\\(?:part|chapter|(?:sub)*section|(?:sub)*paragraph)(?:\*|\b)"
)
_TEX_DETECT_CMD_RE = re.compile(
    r"\\(?:title|part|chapter|(?:sub)*section|(?:sub)*paragraph)(?:\*|\b)"
)
_TEX_PROSE_CMD_RE = re.compile(
    r"\\(?P<heading>(?:part|chapter|(?:sub)*section|(?:sub)*paragraph)(?:\*|\b))"
    r"|\\(?P<texorpdf>texorpdfstring)\b"
    r"|\\(?P<wrapper>(?:textbf|textit|emph|texttt|textrm|textsf|textsc|underline|title|mbox|textsl|mathrm|text))\b"
    r"|(?P<legacy>\{\\(?:bf|it|sc|rm|tt|em|sl|sf|bfseries|itshape|scshape|rmfamily|ttfamily|sffamily|upshape|mdseries)(?![A-Za-z])\s*)"
)
_TEX_PROSE_CMD_NO_HEADING_RE = re.compile(
    r"\\(?P<texorpdf>texorpdfstring)\b"
    r"|\\(?P<wrapper>(?:textbf|textit|emph|texttt|textrm|textsf|textsc|underline|title|mbox|textsl|mathrm|text))\b"
    r"|(?P<legacy>\{\\(?:bf|it|sc|rm|tt|em|sl|sf|bfseries|itshape|scshape|rmfamily|ttfamily|sffamily|upshape|mdseries)(?![A-Za-z])\s*)"
)
_LATEX_DELIM_RE = re.compile(r"\\[\[\]{}\\]|[\[\]{}]")
_TEX_PROTECT_RE = re.compile(r"\\protect(?![A-Za-z])\s*")
_TEX_CMD_WRAPPER_RE = re.compile(
    r"\\(?:textbf|textit|emph|texttt|textrm|textsf|textsc|underline|title)\{([^{}]*)\}"
)
_TEX_CMD_BARE_RE = re.compile(r"\\[A-Za-z]+\*?(?:\[[^\[\]]*\])?")
_DOUBLE_QUOTE_SPAN_RE = re.compile(r'"[^"\n]{1,220}"')

# ---------------------------------------------------------------------------
# Domain-term exemptions & technical context guards
# ---------------------------------------------------------------------------

_LEVERAGE_EXEMPT_RE = re.compile(
    r"\bleverage\s+(?:score|scores|point|points|statistic|statistics|value|values|ratio|effect|sampling)\b",
    re.I,
)
_STATISTICAL_LEVERAGE_RE = re.compile(r"\bstatistical\s+leverage\b", re.I)
_ROBUST_EXEMPT_RE = re.compile(
    r"\b(?:robust\s+(?:statistics|regression|optimization|estimation|estimator|control|pca|"
    r"covariance|loss|huber|inference|standard\s+errors)|"
    r"adversarial(?:ly)?\s+robust(?:ness)?|byzantine[- ]robust(?:ness)?|"
    r"robust\s+to\s+(?:noise|outliers|perturbations|distribution\s+shift)|"
    r"robustness\s+(?:to|against|under|of|in))\b",
    re.I,
)
_LANDSCAPE_EXEMPT_RE = re.compile(
    r"\b(?:(?:loss|energy|fitness|optimization|reward|error|objective)\s+landscape|"
    r"landscape\s+of\s+(?:local\s+minima|saddle\s+points))\b",
    re.I,
)
_GATE_EXEMPT_RE = re.compile(
    r"\b(?:(?:attention|forget|reset|update|input|output|logic|quantum|xor|nand|nor|and|or|"
    r"moe|mixture-of-experts|evidence|quality|verification|precedent|plan)\s+gat(?:e|ed|ing)|"
    r"gat(?:e|ed|ing)\s+(?:mechanism|unit|network|layer|function|check|logic)|"
    r"gated\s+(?:recurrent|linear|attention|mlp))\b",
    re.I,
)
_KEY_EXEMPT_RE = re.compile(
    r"\b(?:(?:api|foreign|primary|hash|cache|bibtex|cite|citation|encryption|public|private|"
    r"secret|dedup|sort|join)\s+key|key[- ]value|keypoint)\b",
    re.I,
)
_REPRESENTS_MATH_EXEMPT_RE = re.compile(
    r"\b(?:marks|represents)\s+an?\s+(?:graph|node|edge|tree|vector|matrix|tensor|"
    r"distribution|state|action|policy|function|mapping|set|sequence|token|layer|"
    r"parameter|bound|lower\s+bound|upper\s+bound|scalar|operator|space|manifold)\b",
    re.I,
)

# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------

# H01: Not X but Y
_H01_STRONG_PATTERNS = [
    re.compile(r"\bnot\s+(?:just|merely|simply)\s+[^.;:\n]{2,90}[,;:]?\s+but\s+(?:also\s+|rather\s+)?[a-z]", re.I),
    re.compile(r"\bnot\s+(?:just|merely|simply)\s+[^.;:\n]{2,90};\s*(?:it(?:'s| is)|they(?:'re| are)|this\s+is)\b", re.I),
    re.compile(r"\bit(?:'s| is)\s+not\s+[^.;:\n]{2,70}[,;]\s+it(?:'s| is)\s+[^.;:\n]{2,70}", re.I),
    re.compile(r"\bisn't\s+[^.;:\n]{2,70}[,;]\s+it(?:'s| is)\s+", re.I),
    re.compile(r"\bthis\s+does\s+not\s+mean\b[^.\n]{1,120}\.\s+it\s+means\b", re.I),
    re.compile(r",\s*(?:no\s+guessing|no\s+filler|not\s+a\s+guess|nothing\s+more)\s*[.!]?$", re.I),
]
_H01_NOT_ONLY_RE = re.compile(r"\bnot\s+only\b[^.;:\n]{2,120}\bbut\s+(?:also\s+)?", re.I)
_H01_RATHER_THAN_RE = re.compile(r"\brather\s+than\b", re.I)

# H02: One-line closers and dramatic fragments
_H02_CLOSER_PATTERNS = [
    re.compile(r"\bthat(?:'s| is)\s+the\s+real\s+(?:win|lesson|issue|difference|shift|story)\b", re.I),
    re.compile(r"\blet\s+that\s+sink\s+in\b", re.I),
    re.compile(r"\bthis\s+(?:shows|demonstrates|underscores|highlights)\s+the\s+importance\s+of\b", re.I),
    re.compile(r"^\s*(?:that\s+distinction\s+matters|this\s+matters|and\s+that\s+matters|"
               r"everything\s+else\s+is\s+noise|the\s+rest\s+is\s+details|period)\s*[.!]?\s*$", re.I),
    re.compile(r"^\s*(?:overall|ultimately),?\s+[^.?!\n]{4,140}[.!]?\s*$", re.I),
    re.compile(r"\b[a-z]+\.\s+[a-z]+\.\s+[a-z]+\.", re.I),
]

# H03: Sayings that sound deep
_H03_STRONG_PATTERNS = [
    re.compile(r"\bat\s+its\s+core\b", re.I),
    re.compile(r"\bthe\s+real\s+question\s+is\b", re.I),
    re.compile(r"\bwhat\s+really\s+matters\b", re.I),
    re.compile(r"\bthe\s+deeper\s+issue\b", re.I),
    re.compile(r"\bheart\s+of\s+the\s+matter\b", re.I),
    re.compile(r"\bbecomes\s+a\s+trap\b", re.I),
    re.compile(r"\bthe\s+(?:language|currency|architecture|grammar|anatomy)\s+of\b", re.I),
]
_H03_SOFT_RE = re.compile(r"\b(?:in\s+reality|fundamentally)\b", re.I)

# H04: Staged run-up
_H04_PATTERNS = [
    re.compile(r"\blet(?:'s| us)\s+(?:dive\s+in(?:to)?|explore|break\s+this\s+down|unpack|take\s+a\s+closer\s+look)\b", re.I),
    re.compile(r"\bhere(?:'s| is)\s+what\s+you\s+need\s+to\s+know\b", re.I),
    re.compile(r"\bwithout\s+further\s+ado\b", re.I),
    re.compile(r"^\s*(?:honestly\?|look,|here(?:'s| is)\s+the\s+thing[: ,])\b", re.I),
    re.compile(r"\bthe\s+(?:hard|slow|new|tricky|interesting|crucial)\s+part\s+is\b(?!\s+of\b)", re.I),
]

# H05: Arguing with no one
_H05_PATTERNS = [
    re.compile(r"\bthis\s+isn't\s+(?:mainly\s+)?about\b", re.I),
    re.compile(r"\bi(?:'m| am)\s+not\s+saying\b", re.I),
    re.compile(r"\bto\s+be\s+clear\b", re.I),
    re.compile(r"\bdon't\s+get\s+me\s+wrong\b", re.I),
    re.compile(r"\bsome\s+might\s+(?:say|argue|assume|think)\b[^.\n]{0,120}\bbut\b", re.I),
    re.compile(r"\ba\s+(?:tempting|naive|obvious|simple)\s+approach\s+would\s+be\b", re.I),
    re.compile(r"\bone\s+might\s+be\s+tempted\s+to\b", re.I),
    re.compile(r"\bit\s+would\s+be\s+easy\s+to\s+just\b", re.I),
]

# H06: Forced triads
_H06_BUZZWORDS = frozenset({
    "efficiency", "scalability", "modularity", "flexibility", "robustness", "simplicity",
    "clarity", "speed", "accuracy", "reliability", "adaptability", "transparency",
    "generalizability", "interpretability", "composability", "sustainability",
    "innovation", "empowerment", "alignment", "synergy", "precision",
})
_H06_TRIAD_RE = re.compile(r"\b([a-z][a-z-]{2,24}),\s+([a-z][a-z-]{2,24}),\s+and\s+([a-z][a-z-]{2,24})\b", re.I)

# H08: Dashes
_EM_DASH_RE = re.compile(r"—|(?<!-)---(?!-)|\s(?:–|--)\s")

# H09: Stacked qualifiers & hedges
_H09_DOUBLE_HEDGE_PATTERNS = [
    re.compile(r"\bmay\s+potentially\b", re.I),
    re.compile(r"\bcould\s+possibly\b", re.I),
    re.compile(r"\bmight\s+arguably\b", re.I),
    re.compile(r"\bseems\s+to\s+suggest\b", re.I),
    re.compile(r"\bappears\s+to\s+indicate\b", re.I),
    re.compile(r"\bit\s+is\s+possible\s+that\b[^.\n]{0,80}\b(?:may|might|could)\b", re.I),
    re.compile(r"\bto\s+be\s+fair\b", re.I),
]
_HEDGE_WORDS_RE = re.compile(
    r"\b(?:may|might|could|possibly|potentially|arguably|seemingly|appears|seems|suggests|indicates|likely)\b",
    re.I,
)

# H10: Predicative hyphenated pairs
_H10_HYPHEN_EXEMPT = frozenset({
    "third-party", "cross-functional", "real-time", "end-to-end", "fine-grained",
    "open-source", "full-text", "zero-shot", "few-shot", "self-supervised",
    "large-scale", "cross-entropy", "state-of-the-art", "out-of-distribution",
})
_H10_PREDICATIVE_RE = re.compile(
    r"\b(?:is|are|was|were|be|become|becomes|became|seems|appears|remains)\s+"
    r"([a-z]{2,15}-[a-z]{2,18})(?=\s*(?:[.,;:!?]|and\b|or\b|but\b|because\b|when\b|while\b|that\b|$))",
    re.I,
)

# H11: Passive voice & missing subjects
_H11_PASSIVE_CONTRIB_RE = re.compile(
    r"\b(?:is|are|was|were)\s+(?:proposed|presented|introduced|developed|designed|evaluated|investigated)\s+"
    r"in\s+this\s+(?:paper|work|study|article|section)\b|"
    r"\bthis\s+(?:paper|work|study)\s+(?:proposes|presents|introduces|investigates|evaluates|demonstrates)\b",
    re.I,
)
_H11_VERBLESS_RE = re.compile(
    r"^\s*no\s+[a-z0-9 _-]{3,40}\s+(?:needed|required)\s*[.!]?\s*$",
    re.I,
)
_H11_PASSIVE_AUX_RE = re.compile(
    r"\b(?:is|are|was|were|been|being)\s+[a-z]+(?:ed|en)\b",
    re.I,
)

# H12: Overused AI words & boosters
_H12_WORDS = [
    ("delve", re.compile(r"\bdelv(?:e|es|ed|ing)\b", re.I)),
    ("tapestry", re.compile(r"\btapestr(?:y|ies)\b", re.I)),
    ("showcase", re.compile(r"\bshowcas(?:e|es|ed|ing)\b", re.I)),
    ("underscore", re.compile(r"\bunderscor(?:e|es|ed|ing)\b", re.I)),
    ("embark", re.compile(r"\bembark(?:s|ed|ing)?\b", re.I)),
    ("unveil", re.compile(r"\bunveil(?:s|ed|ing)?\b", re.I)),
    ("boast", re.compile(r"\bboast(?:s|ed|ing)?\b", re.I)),
    ("multifaceted", re.compile(r"\bmultifaceted\b", re.I)),
    ("holistic", re.compile(r"\bholistic(?:ally)?\b", re.I)),
    ("seamless", re.compile(r"\bseamless(?:ly)?\b", re.I)),
    ("pivotal", re.compile(r"\bpivotal\b", re.I)),
    ("meticulous", re.compile(r"\bmeticulous(?:ly)?\b", re.I)),
    ("garner", re.compile(r"\bgarner(?:s|ed|ing)?\b", re.I)),
    ("interplay", re.compile(r"\binterplay\b", re.I)),
    ("intricate", re.compile(r"\bintricate(?:ly)?\b", re.I)),
    ("enduring", re.compile(r"\benduring\b", re.I)),
    ("vibrant", re.compile(r"\bvibrant\b", re.I)),
    ("deep dive", re.compile(r"\bdeep\s+dive\b", re.I)),
    ("crucial", re.compile(r"\bcrucial(?:ly)?\b", re.I)),
    ("leverage", re.compile(r"\bleverag(?:e|es|ed|ing)\b", re.I)),
    ("robust", re.compile(r"\brobust(?:ly|ness)?\b", re.I)),
    ("landscape", re.compile(r"\blandscapes?\b", re.I)),
]
_H12_BOOSTERS_RE = re.compile(
    r"\b(?:clearly|obviously|undoubtedly|certainly|definitely|dramatically|"
    r"drastically|remarkably|incredibly|immensely|of\s+course|it\s+is\s+well-known\s+that)\b",
    re.I,
)

# H13: Inflated significance
_H13_PATTERNS = [
    re.compile(r"\bstands?\s+as\s+a\s+testament\b", re.I),
    re.compile(r"\b(?:pivotal|crucial|defining)\s+moment\b", re.I),
    re.compile(r"\bplays?\s+a\s+(?:crucial|key|vital|pivotal)\s+role\b", re.I),
    re.compile(r"\bunderscores?\s+its\s+(?:importance|potential|significance)\b", re.I),
    re.compile(r"\breflects?\s+a\s+broader\b", re.I),
    re.compile(r"\blasting\s+legacy\b", re.I),
    re.compile(r"\b(?:paving|setting)\s+the\s+(?:way|stage)\b", re.I),
    re.compile(r"\bevolving\s+landscape\b", re.I),
    re.compile(r"\bshed(?:s|ding)?\s+light\s+on\b", re.I),
    re.compile(r"\bat\s+the\s+forefront\s+of\b", re.I),
    re.compile(r"\bgarnered\s+significant\s+attention\b", re.I),
    re.compile(r"\bin\s+recent\s+years,\s+there\s+has\s+been\b", re.I),
    re.compile(r"\bfuture\s+looks?\s+bright\b", re.I),
    re.compile(r"^\s*(?:#{1,6}\s+)?(?:future\s+outlook|challenges\s+and\s+legacy)\s*$", re.I),
]

# H14: Vague connection/association
_H14_RE = re.compile(
    r"\b(?:in\s+association\s+with|in\s+connection\s+with|associated\s+with|"
    r"connected\s+to|linked\s+to|tied\s+to)\b",
    re.I,
)

# H15: Shallow -ing phrases
_H15_STRONG_RE = re.compile(
    r",\s+(?:highlighting|underscoring|emphasizing|ensuring|reflecting|symbolizing|"
    r"contributing\s+to|cultivating|fostering|encompassing|showcasing)\b",
    re.I,
)

# H16: Sales language
_H16_RE = re.compile(
    r"\b(?:groundbreaking|cutting-edge|game-changing|revolutionary|unprecedented|"
    r"breathtaking|stunning|renowned|nestled|in\s+the\s+heart\s+of|diverse\s+array|"
    r"a\s+wide\s+range\s+of|a\s+myriad\s+of|myriad\s+of|profound\s+impact|"
    r"rich\s+(?:heritage|tapestry)|paradigm\s+shift)\b",
    re.I,
)

# H17: Borrowed authority
_H17_AUTHORITY_RE = re.compile(
    r"\b(?:experts|researchers|observers|analysts|scholars)\s+(?:argue|believe|claim|note|suggest)\b|"
    r"\b(?:industry\s+reports|several\s+publications|studies\s+show)\b",
    re.I,
)
_H17_PRESTIGE_RE = re.compile(
    r"\b(?:cited|featured|published)\s+in\b[^.\n]{1,60},\s+[^.\n]{1,40},\s+and\s+",
    re.I,
)
_H17_FOLLOWERS_RE = re.compile(r"\bover\s+\d[\d,]*\s+followers\b", re.I)

# H18: Avoiding is/are/has
_H18_STRONG_RE = re.compile(r"\b(?:serves|stands|functions|operates)\s+as\b|\bboasts\b", re.I)
_H18_SOFT_RE = re.compile(r"\b(?:features|offers|maintains|marks|represents)\s+an?\b", re.I)

# H19: Bold as decoration
_H19_BOLD_BULLET_RE = re.compile(r"^\s*[-*+]\s+\*\*[^*\n]{2,50}:\*\*")
_H19_INLINE_BOLD_RE = re.compile(r"\*\*[^*\n]+\*\*")

# H20: Decorative headings & rules
_H20_EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")
_H20_ARROW_RE = re.compile(r"[→➔➤]")

# H21: Curly quotes
_H21_CURLY_RE = re.compile(r"[“”‘’]")
_H21_STRAIGHT_RE = re.compile(r'["\']')

# H22: Chatbot residue & placeholders (RISK)
_H22_PATTERNS = [
    re.compile(r"\bas\s+an\s+ai(?:\s+language)?\s+model\b", re.I),
    re.compile(r"\bi\s+hope\s+this\s+helps\b", re.I),
    re.compile(r"^\s*(?:certainly!|of\s+course!|great\s+question!|absolutely!)", re.I),
    re.compile(r"\byou(?:'re| are)\s+absolutely\s+right\b", re.I),
    re.compile(r"\b(?:would\s+you\s+like\s+me\s+to|want\s+me\s+to)\b", re.I),
    re.compile(r"\bhere\s+is\s+(?:a\s+)?(?:revised|updated|rewritten)\s+version\b", re.I),
    re.compile(r"\[insert\s+[^\]\n]{1,60}\]", re.I),
    re.compile(r"\b(?:TODO|TBD|TK|XXXX)\b"),
    re.compile(r"\blorem\s+ipsum\b", re.I),
    re.compile(r"</?(?:skill|system|instructions|prompt)>", re.I),
]

# H23: Knowledge-limit disclaimers & guesses
_H23_RISK_PATTERNS = [
    re.compile(r"\bas\s+of\s+my\s+(?:last\s+)?(?:training|knowledge)\s+(?:update|cutoff)\b", re.I),
    re.compile(r"\bknowledge\s+cutoff\b", re.I),
]
_H23_WARN_PATTERNS = [
    re.compile(r"\bwhile\s+specific\s+details\b[^.\n]{0,80}\bare\s+limited\b", re.I),
    re.compile(r"\bnot\s+publicly\s+available\b[^.\n]{0,80}\b(?:likely|appears\s+to\s+have\s+been)\b", re.I),
    re.compile(r"\bit\s+is\s+believed\s+that\b", re.I),
    re.compile(r"\bmaintains?\s+a\s+low\s+profile\b", re.I),
]

# H25: Meta-document narration
_H25_RE = re.compile(
    r"\b(?:was\s+added\s+to\s+replace|compiled\s+from|generated\s+from|"
    r"anything\s+unconfirmed\s+is\s+flagged\s+rather\s+than\s+guessed|"
    r"this\s+(?:section|document)\s+is\s+organized\s+by)\b",
    re.I,
)

# PL01-PL06
_CONNECTIVES_LIST = (
    "moreover", "furthermore", "additionally", "consequently",
    "notably", "importantly", "hence", "thus",
)
_CONNECTIVES_RE = re.compile(r"\b(?:" + "|".join(_CONNECTIVES_LIST) + r")\b", re.I)
_CONNECTIVE_OPENER_RE = re.compile(r"^\s*(?:" + "|".join(_CONNECTIVES_LIST) + r")\b[,:]?", re.I)
_SIGNIFICANT_RE = re.compile(r"\bsignificant(?:ly)?\b", re.I)
_STATS_CONTEXT_RE = re.compile(r"(?:p\s*[<=>]\s*0?\.\d+|statistically\s+significant|ci\b|confidence\s+interval|t\s*=|f\s*=|z\s*=)", re.I)
_VAGUE_OPENER_RE = re.compile(r"^\s*(?:this|it|there)\s+(?:is|are|was|were|shows|suggests|indicates|remains)\b", re.I)

# Sycophancy (SYC_*)
_SYC_FLATTERY_PATTERNS = [
    re.compile(r"\b(?:great|excellent|brilliant|fantastic|wonderful|amazing|awesome|superb|outstanding|terrific|insightful|clever|smart)\s+(?:idea|question|point|insight|observation|approach|intuition|direction|suggestion|proposal|work|catch)\b", re.I),
    re.compile(r"\byou(?:'re| are)\s+(?:absolutely|completely|totally|entirely|100%)\s+right\b", re.I),
    re.compile(r"\byour\s+(?:intuition|instinct|hypothesis|framing|analysis)\s+is\s+(?:spot[- ]on|exact|brilliant|compelling)\b", re.I),
    re.compile(r"\bwhat\s+a\s+(?:great|clever|smart|novel|elegant)\s+(?:idea|approach|insight)\b", re.I),
    re.compile(r"\bi\s+(?:love|really\s+like)\s+(?:this|your)\s+(?:idea|approach|framing|direction)\b", re.I),
    re.compile(r"\bthank\s+you\s+for\s+(?:sharing|pointing\s+out|raising)\s+(?:such\s+a|this)\s+(?:great|thoughtful|important)\b", re.I),
    re.compile(r"\bý\s+tưởng\s+(?:tuyệt\s+vời|xuất\s+sắc|đỉnh\s+cao|quá\s+đỉnh)\b", re.I),
    re.compile(r"\bbạn\s+(?:hoàn\s+toàn\s+đúng|nói\s+(?:rất|quá)\s+đúng|nhìn\s+ra\s+quá\s+chuẩn)\b", re.I),
    re.compile(r"\bbạn\s+thấy\s+điều\s+gì\s+vừa\s+khớp\s+nối\s+lịch\s+sử\s+chưa\b", re.I),
]
_SYC_CHEER_CRITICAL_PATTERNS = [
    re.compile(r"\b(?:groundbreaking|revolutionary|paradigm[- ]shifting|transformative|game[- ]changing|trailblazing)\b", re.I),
    re.compile(r"\bnovel\s+unified\s+framework\b", re.I),
    re.compile(r"\b(?:well[- ]motivated\s+and\s+compelling|compelling\s+and\s+well[- ]motivated)\b", re.I),
    re.compile(r"\bpromising\s+(?:direction|framework|approach|avenue|line\s+of\s+(?:work|research)|results?)\b", re.I),
    re.compile(r"\bimpressive\s+(?:gain|gains|improvement|improvements|results?|performance|accuracy|speedup)s?\b", re.I),
    re.compile(r"\bhighly\s+(?:promising|innovative|original|novel|compelling|impactful)\b", re.I),
    re.compile(r"\bclear(?:ly)?\s+superior\b|\bunquestionably\s+(?:better|superior|novel)\b", re.I),
    re.compile(r"\bexciting\s+(?:breakthrough|opportunity|direction|avenue|findings?)\b", re.I),
    re.compile(r"\b(?:completely|fully|definitively|conclusively|irrefutably)\s+(?:solves?|resolves?|proves?|eliminates?|closes?)\b", re.I),
    re.compile(r"(?:(?<!\d)100%|completely\s+free\s+of)\s+(?:clean\s+of\s+)?confounders?\b", re.I),
    re.compile(r"\bno\s+reviewer\s+(?:can|could|will)\s+(?:object|challenge|question|fault)\b", re.I),
    re.compile(r"\b(?:bulletproof|airtight|unassailable)\s+(?:proof|evidence|argument|contribution|paper|rqs?)\b", re.I),
    re.compile(r"\bgiải\s+quyết\s+triệt\s+để\b", re.I),
    re.compile(r"\bkhóa\s+chặt\s+mọi\s+đường\b", re.I),
    re.compile(r"\bkhông\s+một\s+reviewer\s+nào\s+(?:có\s+thể\s+)?bắt\s+bẻ\b", re.I),
    re.compile(r"\bhoàn\s+toàn\s+sạch\s+bóng\s+biến\s+nhiễu\b", re.I),
    re.compile(r"(?<!\d)100%\s*(?:sạch(?:\s+bóng)?|chứng\s+minh)\b", re.I),
    re.compile(r"\bphát\s+hiện\s+(?:đột\s+phá|lý\s+thuyết\s+cực\s+lớn)\b", re.I),
    re.compile(r"\bđột\s+phá\s+ngay\s+lúc\s+này\b", re.I),
    re.compile(r"\bbài\s+học\s+triệu\s+đô\b", re.I),
    re.compile(r"\bdòng\s+huyết\s+thống\s+quý\s+tộc\b", re.I),
    re.compile(r"\b(?:đối\s+nghịch\s+)?tuyệt\s+đẹp\b", re.I),
    re.compile(r"\bhoàn\s+hảo\s+đến\s+từng\s+chữ\b", re.I),
    re.compile(r"\bchứng\s+minh\s+tuyệt\s+đối\b", re.I),
    re.compile(r"\b(?:đập\s+bẹp\s+tất\s+cả|đè\s+bẹp)\b", re.I),
]
_SYC_CHEER_SOFT_PATTERNS = [
    re.compile(r"\bpioneering\s+(?:work|study|paper|method|approach)\b|\bseminal\b", re.I),
    re.compile(r"\b(?:solid\s+foundation|meaningful\s+advance|significant\s+step\s+forward)\b", re.I),
    re.compile(r"\bstrong\s+(?:contribution|novelty|candidate)\b", re.I),
]
_SYC_SANDWICH_PRAISE_RE = re.compile(
    r"\b(?:great|good|excellent|promising|strong|interesting|compelling|well[- ]motivated|well[- ]written|"
    r"nice|solid|valuable|impressive|clever|neat|appreciate|"
    r"thoughtful|thorough|clear|insightful|careful|clean)\b",
    re.I,
)
_SYC_SANDWICH_STRONG_OR_USER_RE = re.compile(
    r"\b(?:your|you|this\s+(?:work|idea|approach|framing|paper|draft|proposal|direction)|"
    r"great|good|excellent|promising|strong|interesting|compelling|well[- ]motivated|well[- ]written|"
    r"nice|solid|valuable|impressive|clever|neat|appreciate|"
    r"thoughtful|thorough|clear|insightful|careful|clean)\b",
    re.I,
)
_USER_ADDRESS_RE = re.compile(r"\b(?:your|you)\b", re.I)
_YOUR_ADDRESS_RE = re.compile(r"\byour\b", re.I)
_EMPIRICAL_METRIC_QUAL_RE = re.compile(
    r"\b(?:strong|good|clear|high)\s+(?:empirical\s+)?"
    r"(?:accuracy|precision|recall|f1|auc|mrr|ndcg|bleu|rouge|performance|scores?|results?|gains?|speedups?|convergence|calibration|generalization|separability|signal)\b|"
    r"\bclean\s+(?:data|dataset|datasets|labels|split|splits|images|samples|inputs?)\b",
    re.I,
)
_SYC_SANDWICH_PIVOT_RE = re.compile(
    r"\b(?:however|but|although|yet|that\s+said|nevertheless|nonetheless|even\s+so|"
    r"unfortunately|on\s+the\s+other\s+hand|at\s+the\s+same\s+time)\b",
    re.I,
)
_SYC_SANDWICH_PREP_PIVOT_RE = re.compile(r"\b(?:despite|notwithstanding|in\s+spite\s+of)\b", re.I)
_SYC_PRAISE_BACKREF_RE = re.compile(
    r"^(?:despite|notwithstanding|in\s+spite\s+of)\s+"
    r"(?:this|these|those|such|its|their|the|your)\s+"
    r"(?:merits?|strengths?|positives?|qualit(?:y|ies)|advantages?|clarity|promise|care|"
    r"thoroughness|effort|efforts|framing|intuition|gains?|results?)\b",
    re.I,
)
_SYC_SANDWICH_FLAW_RE = re.compile(
    r"\b(?:bug|bugs|leak|leaks|leaked|leaking|leakage|fail|fails|failed|failing|failure|failures|"
    r"missing|omits|omitted|omission|omitting|wrong|invalid|invalidates|invalidated|"
    r"error|errors|erroneous|flaw|flaws|flawed|weak|weakness|weaknesses|weaker|"
    r"unverified|untested|unsupported|unfounded|incomplete|insufficient|"
    r"broken|breaks|broke|defect|defects|defective|"
    r"contaminated|contamination|fabricated|fabrication|hallucinated)\b",
    re.I,
)
_SOLVER_VERB_RE = re.compile(
    r"\b(?:fix(?:es|ed|ing)?|address(?:es|ed|ing)?|solv(?:e[sd]?|ing)|resolv(?:e[sd]?|ing)|"
    r"overcom(?:e[sd]?|ing)|avoid(?:s|ed|ing)?|prevent(?:s|ed|ing)?|eliminat(?:e[sd]?|ing)|"
    r"mitigat(?:e[sd]?|ing)|catch(?:es|ing)?|caught|correct(?:s|ed|ing)?|remediat(?:e[sd]?|ing)|"
    r"expos(?:e[sd]?|ing)|uncover(?:s|ed|ing)?|detect(?:s|ed|ing)?)\b",
    re.I,
)
_NEGATED_SOLVER_RE = re.compile(
    r"\b(?:not|never|fail(?:s|ed)?\s+to|unable\s+to|cannot|can't|does\s+not|do\s+not|did\s+not|without)\b",
    re.I,
)
_PRIOR_WORK_NP_RE = re.compile(
    r"\b(?:prior|existing|previous|earlier|baseline|competing)\s+"
    r"(?:work|works|methods?|models?|approaches?|systems?|baselines?|literature|studies|papers?)\b",
    re.I,
)
_PRIOR_WORK_AFTER_FLAW_RE = re.compile(
    r"^\s*(?:of|in|from|among)\s+(?:prior|existing|previous|earlier|baseline|competing)\s+"
    r"(?:work|works|methods?|models?|approaches?|systems?|baselines?|literature|studies|papers?)\b",
    re.I,
)
_TARGET_WORK_RE = re.compile(
    r"\b(?:your|this\s+(?:paper|work|study|draft|submission|method|approach|model|pipeline)|the\s+(?:draft|submission))\b",
    re.I,
)

# PI01 / PAD01: Problem inflation & extraneous boilerplate padding (F19 / paper-writing rigor)
_CATASTROPHIC_FORGETTING_EXEMPT_RE = re.compile(
    r"\bcatastrophic\s+(?:forgetting|interference)\b",
    re.I,
)
_PI01_PATTERNS = [
    re.compile(r"\b(?:catastrophic|crippling|devastating|existential)\s+(?:bottleneck|barrier|failure|limitation|flaw|crisis|flaws|threat)\b", re.I),
    re.compile(r"\b(?:plagued\s+by|suffers\s+severely\s+from|desperately\s+needed|urgently\s+demands?\s+a\s+complete\s+overhaul)\b", re.I),
    re.compile(r"\brenders?\s+(?:all\s+)?(?:prior|existing|current)?\s*\w+(?:\s+\w+){0,3}\s+(?:useless|obsolete|infeasible|invalid)\b", re.I),
    re.compile(r"\bfundamentally\s+broken\s+(?:across\s+every|in\s+all|at\s+its\s+core)\b", re.I),
    re.compile(r"\b(?:severe|fundamental|critical)\s+(?:bottleneck|crisis|flaw|limitation)\b(?![^.\n]*(?:\d+(?:\.\d+)?%|\[ref\]|\[C\d+\]|\[\d+\]))", re.I),
]
_PAD01_PATTERNS = [
    re.compile(r"\b(?:in\s+the\s+(?:modern|current)?\s*(?:era|age)\s+of|in\s+today(?:'s|s)\s+rapidly\s+(?:evolving|changing|advancing))\b", re.I),
    re.compile(r"\b(?:with\s+the\s+rapid\s+(?:rise|growth|advancement|proliferation)\s+of|since\s+the\s+dawn\s+of)\b", re.I),
    re.compile(r"\b(?:has\s+become\s+increasingly\s+(?:important|popular|ubiquitous)\s+in\s+recent\s+years|has\s+revolutionized\s+(?:numerous|countless|many|various)\s+(?:industries|fields|domains|sectors))\b", re.I),
    re.compile(r"\b(?:in\s+recent\s+decades,\s+researchers\s+have\s+increasingly|it\s+is\s+worth\s+(?:noting|mentioning)\s+that|needless\s+to\s+say|it\s+goes\s+without\s+saying|as\s+we\s+all\s+know)\b", re.I),
]
_MATH_OR_CAPTION_BOILERPLATE_RE = re.compile(
    r"^(?:table|figure|fig\.?)\s+\d+\b|\b(?:where|let|here)\s+\[math\]\s+(?:denotes?|be|is|represents?)\b",
    re.I,
)

# ---------------------------------------------------------------------------
# Utilities & Masking
# ---------------------------------------------------------------------------


def _excerpt(text: str, limit: int = 140) -> str:
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3] + "..."


def _has_even_preceding_backslashes(text: str, idx: int) -> bool:
    bs = 0
    pos = idx - 1
    while pos >= 0 and text[pos] == "\\":
        bs += 1
        pos -= 1
    return (bs % 2) == 0


def _mask_inline_code_spans(line: str, repl: str = " [code] ") -> str:
    """Mask CommonMark inline code spans (arbitrary N >= 1 backtick fences) in O(n) time."""
    if "`" not in line:
        return line
    runs = [(m.start(), m.end(), m.end() - m.start()) for m in _BACKTICK_RUN_RE.finditer(line)]
    if len(runs) < 2:
        return line

    by_len: dict[int, list[int]] = {}
    for idx, (_, _, length) in enumerate(runs):
        by_len.setdefault(length, []).append(idx)
    bucket_pos: dict[int, int] = {length: 0 for length in by_len}

    out: list[str] = []
    cursor = 0
    r_idx = 0
    n_runs = len(runs)
    while r_idx < n_runs:
        start, _, length = runs[r_idx]
        if not _has_even_preceding_backslashes(line, start):
            r_idx += 1
            continue
        bucket = by_len[length]
        bpos = bucket_pos[length]
        while bpos < len(bucket) and bucket[bpos] <= r_idx:
            bpos += 1
        bucket_pos[length] = bpos
        if bpos < len(bucket):
            close_idx = bucket[bpos]
            bucket_pos[length] = bpos + 1
            out.append(line[cursor:start])
            out.append(repl)
            cursor = runs[close_idx][1]
            r_idx = close_idx + 1
        else:
            r_idx += 1
    if cursor == 0:
        return line
    out.append(line[cursor:])
    return "".join(out)


def _find_unescaped_percent(text: str, start: int = 0) -> int:
    pos = start
    while True:
        idx = text.find("%", pos)
        if idx == -1 or _has_even_preceding_backslashes(text, idx):
            return idx
        pos = idx + 1


def _strip_unescaped_tex_comment(line: str) -> str:
    idx = _find_unescaped_percent(line, 0)
    return line if idx == -1 else line[:idx]


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
    """Match optional [...] and num_braced {...} arguments in O(1) using match tables."""
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


def _unwrap_tex_prose(
    text: str,
    extract_headings: bool = False,
    headings_out: list[tuple[int, str]] | None = None,
    line_no: int = 0,
    max_depth: int = 8,
) -> str:
    """Recursively unwrap LaTeX headings, wrappers, \\texorpdfstring, and legacy font braces in O(N)."""
    work = _TEX_PROTECT_RE.sub("", text)
    if max_depth <= 0:
        return work
    cmd_re = _TEX_PROSE_CMD_RE if extract_headings else _TEX_PROSE_CMD_NO_HEADING_RE
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
                    _unwrap_tex_prose(
                        work[m.end() : close_pos],
                        extract_headings=False,
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
                    _unwrap_tex_prose(
                        work[s1:e1],
                        extract_headings=False,
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
                    _unwrap_tex_prose(
                        work[s1:e1],
                        extract_headings=False,
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
                inner = _unwrap_tex_prose(
                    work[s1:e1],
                    extract_headings=False,
                    max_depth=max_depth - 1,
                )
                inner = " ".join(inner.split()).replace("{", "").replace("}", "")
                if headings_out is not None and inner:
                    headings_out.append((line_no, inner))
                out.append(inner)
                pos = next_pos
            else:
                out.append(work[m.start() : m.end()])
                pos = m.end()
        else:
            out.append(work[m.start() : m.end()])
            pos = m.end()
    return "".join(out)


def _has_incomplete_heading_cmd(line: str) -> bool:
    """Return True iff line ends with an unclosed heading command/optional/braced arg."""
    matches = list(_TEX_HEADING_CMD_RE.finditer(line))
    if not matches:
        return False
    bracket_close, brace_close = _build_latex_match_tables(line)
    n = len(line)
    for m in reversed(matches):
        if not _has_even_preceding_backslashes(line, m.start()):
            continue
        if _match_cmd_args(line, m.end(), bracket_close, brace_close, allow_opt=True, num_braced=1) is None:
            pos = m.end()
            while pos < n and line[pos].isspace():
                pos += 1
            if pos == n:
                return True
            if line[pos] == "[":
                opt_end = bracket_close.get(pos)
                if opt_end is None:
                    return True
                pos = opt_end + 1
                while pos < n and line[pos].isspace():
                    pos += 1
                if pos == n:
                    return True
            if line[pos] == "{" and brace_close.get(pos) is None:
                return True
    return False


def _is_tex(path: str | None, raw: str) -> bool:
    if path and path.lower().endswith(".tex"):
        return True
    if path and path.lower().endswith((".md", ".markdown", ".txt")):
        return False
    if re.search(r"\\begin\{document\}|\\documentclass", raw):
        return True
    if _TEX_DETECT_CMD_RE.search(raw):
        bracket_close, brace_close = _build_latex_match_tables(raw)
        for m in _TEX_DETECT_CMD_RE.finditer(raw):
            if _has_even_preceding_backslashes(raw, m.start()) and (
                _match_cmd_args(raw, m.end(), bracket_close, brace_close, allow_opt=True, num_braced=1)
                is not None
            ):
                return True
    return False


def _split_sentences(text: str) -> list[str]:
    cleaned = " ".join(text.split())
    if not cleaned:
        return []
    parts = re.split(
        r"(?<=[!?])\s+(?=[A-Z0-9\[(])|"
        r"(?<!\bSec\.)(?<!\bFig\.)(?<!\bEq\.)(?<!\bTab\.)(?<!\bAlg\.)"
        r"(?<!\bRef\.)(?<!\bApp\.)"
        r"(?<!\bal\.)(?<!\bvs\.)(?<!\bNo\.)(?<!\bDr\.)(?<!e\.g\.)(?<!i\.e\.)"
        r"(?<=\.)\s+(?=[A-Z0-9\[(])",
        cleaned,
    )
    return [p.strip() for p in parts if p.strip()]


def _mask_display_math_line(
    work: str,
    in_dollar: bool,
    in_bracket: bool,
) -> tuple[str, bool, bool]:
    """Mask multi-line or inline $$...$$ and \\[...\\] while preserving prose on opening/closing lines."""
    parts: list[str] = []
    pos = 0
    n = len(work)
    last_non_ws = len(work.rstrip())
    has_prose_before = False
    while pos < n:
        if in_dollar:
            m = _DISPLAY_DOLLAR_RE.search(work, pos)
            if not m:
                pos = n
                break
            in_dollar = False
            pos = m.end()
            if has_prose_before and pos < last_non_ws:
                parts.append(" [math] ")
        elif in_bracket:
            m = _DISPLAY_BRACKET_CLOSE_RE.search(work, pos)
            if not m:
                pos = n
                break
            in_bracket = False
            pos = m.end()
            if has_prose_before and pos < last_non_ws:
                parts.append(" [math] ")
        else:
            m = _DISPLAY_OPEN_RE.search(work, pos)
            if m is None:
                parts.append(work[pos:])
                if pos < last_non_ws:
                    has_prose_before = True
                break
            if m.start() > pos and work[pos:m.start()].strip():
                parts.append(work[pos:m.start()])
                has_prose_before = True
            if m.group(0) == "$$":
                in_dollar = True
            else:
                in_bracket = True
            pos = m.end()
    if not has_prose_before:
        return "", in_dollar, in_bracket
    if in_dollar or in_bracket:
        parts.append(" [math] ")
    return "".join(parts), in_dollar, in_bracket


def _preprocess_tex_line(
    line: str,
    skip_envs: frozenset[str],
    env_stack: list[str],
) -> tuple[str, bool]:
    """Strip unescaped % comments, \\verb spans, and same-line/opening skip_envs left-to-right."""
    out_parts: list[str] = []
    pos = 0
    n = len(line)
    had_skip_env_placeholder = False

    while pos < n:
        # 1. Earliest unescaped %
        pct_idx = -1
        pct_scan = pos
        while True:
            cand = line.find("%", pct_scan)
            if cand == -1:
                break
            if _has_even_preceding_backslashes(line, cand):
                pct_idx = cand
                break
            pct_scan = cand + 1

        # 2. Earliest unescaped \verb / \verb*
        verb_m = None
        v_scan = pos
        while True:
            vm = _TEX_VERB_RE.search(line, v_scan)
            if vm is None:
                break
            if _has_even_preceding_backslashes(line, vm.start()):
                verb_m = vm
                break
            v_scan = vm.start() + 1

        # 3. Earliest unescaped \begin{env} where env in skip_envs
        env_m = None
        e_scan = pos
        while True:
            em = _BEGIN_ENV_RE.search(line, e_scan)
            if em is None:
                break
            if _has_even_preceding_backslashes(line, em.start()) and em.group(1) in skip_envs:
                env_m = em
                break
            e_scan = em.start() + 1

        candidates: list[tuple[int, str]] = []
        if pct_idx != -1:
            candidates.append((pct_idx, "pct"))
        if verb_m is not None:
            candidates.append((verb_m.start(), "verb"))
        if env_m is not None:
            candidates.append((env_m.start(), "env"))

        if not candidates:
            out_parts.append(line[pos:])
            break

        cand_pos, kind = min(candidates, key=lambda x: x[0])
        out_parts.append(line[pos:cand_pos])

        if kind == "pct":
            break
        if kind == "verb":
            assert verb_m is not None
            delim = verb_m.group(1) if verb_m.group(1) is not None else verb_m.group(2)
            close_idx = line.find(delim, verb_m.end())
            if close_idx != -1:
                out_parts.append(" [code] ")
                pos = close_idx + 1
            else:
                pos = verb_m.end()
        else:
            assert env_m is not None
            env = env_m.group(1)
            end_tag = f"\\end{{{env}}}"
            end_idx = line.find(end_tag, env_m.end())
            if end_idx != -1:
                if env in _TEX_VERBATIM_ENVS:
                    out_parts.append(" [code] ")
                elif env in _MD_MATH_ENVS:
                    out_parts.append(" [math] ")
                else:
                    out_parts.append(" ")
                had_skip_env_placeholder = True
                pos = end_idx + len(end_tag)
            else:
                env_stack.append(env)
                break

    pre_line = "".join(out_parts)
    if had_skip_env_placeholder and not re.sub(r"\[(?:code|math)\]", "", pre_line).strip():
        return "", True
    return pre_line, had_skip_env_placeholder


def _mask_tex_lines(raw_lines: list[str], keep_tables: bool = False) -> tuple[list[str], list[tuple[int, str]]]:
    """Mask LaTeX preamble, comments, non-prose envs, math, URLs, and citations preserving 1-based line numbers."""
    has_begin_doc = any(re.search(r"\\begin\{document\}", ln) for ln in raw_lines)
    in_doc = not has_begin_doc
    env_stack: list[str] = []
    in_display_bracket = False
    in_dollar_display = False
    headings: list[tuple[int, str]] = []
    out: list[str] = []

    skip_envs = MASK_ENVS - ({"tabular", "tabularx", "tabular*", "longtable", "array"} if keep_tables else set())
    pending_heading_parts: list[tuple[int, str]] = []
    max_pending_heading_chars = 4096

    def _finalize_tex_prose(chunk: str, line_no: int, record_headings: bool) -> str:
        w = _URL_CMD_RE.sub(" [url] ", chunk)
        w = _BARE_URL_RE.sub(" [url] ", w)
        w = _CITE_RE.sub(" [ref] ", w)
        w = _DISPLAY_MATH_INLINE_RE.sub(" [math] ", w)
        w = _INLINE_MATH_RE.sub(" [math] ", w)
        w = _unwrap_tex_prose(
            w,
            extract_headings=record_headings,
            headings_out=headings if record_headings else None,
            line_no=line_no,
        )
        w = re.sub(r"\\(?:begin|end)\{[^{}]*\}(?:\[[^\[\]]*\])?", " ", w)
        w = _TEX_CMD_BARE_RE.sub(" ", w)
        w = re.sub(r"(?<!\\)~", " ", w)
        w = w.replace("{", "").replace("}", "")
        return w

    def _flush_pending_headings() -> None:
        if not pending_heading_parts:
            return
        for out_pos, p_chunk in pending_heading_parts:
            out[out_pos] = _finalize_tex_prose(p_chunk, out_pos + 1, record_headings=True)
        pending_heading_parts.clear()

    for idx, line in enumerate(raw_lines, start=1):
        if not in_doc:
            no_comment = _strip_unescaped_tex_comment(line)
            if re.search(r"\\begin\{document\}", no_comment):
                in_doc = True
            out.append("")
            continue

        work_line = line
        # If already inside a masked environment, close/update stack before touching math delimiters
        if env_stack:
            _flush_pending_headings()
            if env_stack[-1] in _TEX_VERBATIM_ENVS:
                end_tag = f"\\end{{{env_stack[-1]}}}"
                end_idx = work_line.find(end_tag)
                if end_idx == -1:
                    out.append("")
                    continue
                env_stack.pop()
                work_line = work_line[end_idx + len(end_tag) :]
                if not work_line.strip():
                    out.append("")
                    continue
            else:
                scan_pos = 0
                n_len = len(work_line)
                while scan_pos < n_len and env_stack:
                    pct_idx = _find_unescaped_percent(work_line, scan_pos)
                    bm = None
                    b_scan = scan_pos
                    while True:
                        cand_b = _BEGIN_ENV_RE.search(work_line, b_scan)
                        if cand_b is None:
                            break
                        if _has_even_preceding_backslashes(work_line, cand_b.start()):
                            bm = cand_b
                            break
                        b_scan = cand_b.start() + 1
                    em = None
                    e_scan = scan_pos
                    while True:
                        cand_e = _END_ENV_RE.search(work_line, e_scan)
                        if cand_e is None:
                            break
                        if _has_even_preceding_backslashes(work_line, cand_e.start()):
                            em = cand_e
                            break
                        e_scan = cand_e.start() + 1
                    cands: list[tuple[int, str, re.Match[str] | None]] = []
                    if pct_idx != -1:
                        cands.append((pct_idx, "pct", None))
                    if bm is not None:
                        cands.append((bm.start(), "begin", bm))
                    if em is not None:
                        cands.append((em.start(), "end", em))
                    if not cands:
                        break
                    _, kind, match_obj = min(cands, key=lambda x: x[0])
                    if kind == "pct":
                        break
                    assert match_obj is not None
                    env_name = match_obj.group(1)
                    scan_pos = match_obj.end()
                    if kind == "begin":
                        if env_name in skip_envs:
                            env_stack.append(env_name)
                    else:
                        for pos_s in range(len(env_stack) - 1, -1, -1):
                            if env_stack[pos_s] == env_name:
                                env_stack.pop(pos_s)
                                break
                if env_stack:
                    out.append("")
                    continue
                work_line = work_line[scan_pos:]
                if not work_line.strip():
                    out.append("")
                    continue

        # If already inside multi-line display math, close math first and pass post-close tail to _preprocess_tex_line
        if in_dollar_display or in_display_bracket:
            _flush_pending_headings()
            pct_idx = _find_unescaped_percent(work_line, 0)
            search_limit = pct_idx if pct_idx != -1 else len(work_line)
            close_re = _DISPLAY_DOLLAR_RE if in_dollar_display else _DISPLAY_BRACKET_CLOSE_RE
            close_m = close_re.search(work_line, 0, search_limit)
            if close_m is None:
                out.append("")
                continue
            in_dollar_display = False
            in_display_bracket = False
            work_line = work_line[close_m.end() :]
            if not work_line.strip():
                out.append("")
                continue

        # Left-to-right pre-pass for unescaped %, \verb, and same-line/opening skip_envs BEFORE display-math scanning
        pre_line, _ = _preprocess_tex_line(work_line, skip_envs, env_stack)
        if not pre_line.strip():
            _flush_pending_headings()
            out.append("")
            continue

        # Mask multi-line and inline \[ ... \] and $$ ... $$ while preserving outer prose
        work_math, in_dollar_display, in_display_bracket = _mask_display_math_line(
            pre_line, in_dollar_display, in_display_bracket
        )
        if not work_math.strip():
            _flush_pending_headings()
            out.append("")
            continue

        if pending_heading_parts:
            pending_len = sum(len(p) for _, p in pending_heading_parts) + len(pending_heading_parts)
            if (
                len(pending_heading_parts) >= 20
                or pending_len + len(work_math) > max_pending_heading_chars
                or re.search(r"\\(?:begin|end)\{", work_math)
            ):
                _flush_pending_headings()
            else:
                combined = "\n".join([p for _, p in pending_heading_parts] + [work_math])
                if not _has_incomplete_heading_cmd(combined):
                    pending_heading_parts.clear()
                    out.append(_finalize_tex_prose(combined, idx, record_headings=True))
                else:
                    pending_heading_parts.append((len(out), work_math))
                    out.append("")
                continue

        if len(work_math) <= max_pending_heading_chars and _has_incomplete_heading_cmd(work_math):
            pending_heading_parts.append((len(out), work_math))
            out.append("")
            continue

        out.append(_finalize_tex_prose(work_math, idx, record_headings=True))

    _flush_pending_headings()
    return out, headings


_MD_MATH_ENVS = frozenset({
    "equation", "equation*", "align", "align*", "gather", "gather*",
    "multline", "multline*", "eqnarray", "eqnarray*", "displaymath",
})


def _mask_markdown_lines(raw_lines: list[str]) -> tuple[list[str], list[tuple[int, str]], list[int], list[bool]]:
    """Mask YAML frontmatter, fenced code blocks, inline code, math blocks/envs, and URLs preserving line numbers."""
    out: list[str] = []
    headings: list[tuple[int, str]] = []
    hr_lines: list[int] = []
    in_code_mask: list[bool] = []
    fence_char: str | None = None
    in_frontmatter = False

    if raw_lines and raw_lines[0].strip() == "---":
        for j in range(1, min(len(raw_lines), 80)):
            if raw_lines[j].strip() in {"---", "..."}:
                in_frontmatter = True
                frontmatter_end = j
                break
        else:
            frontmatter_end = -1
    else:
        frontmatter_end = -1

    in_dollar_display = False
    in_bracket_display = False
    math_env_stack: list[str] = []
    for idx, line in enumerate(raw_lines, start=1):
        if in_frontmatter:
            out.append("")
            in_code_mask.append(True)
            if idx - 1 == frontmatter_end:
                in_frontmatter = False
            continue

        stripped = line.strip()
        if fence_char is None:
            fm = re.match(r"^(`{3,}|~{3,})", stripped)
            if fm:
                fence_char = fm.group(1)[0]
                out.append("")
                in_code_mask.append(True)
                continue
        else:
            if stripped.startswith(fence_char * 3):
                fence_char = None
            out.append("")
            in_code_mask.append(True)
            continue

        # Mask inline code BEFORE inspecting math envs / \[ / $$ so `\[` in prose does not open math mode
        in_multiline_math = bool(math_env_stack) or in_dollar_display or in_bracket_display
        scan_line = line if in_multiline_math else _mask_inline_code_spans(line, " [code] ")

        # Multi-line LaTeX math environments inside Markdown (e.g. \begin{equation}...\end{equation})
        begins = [e for e in _BEGIN_ENV_RE.findall(scan_line) if e in _MD_MATH_ENVS]
        ends = [e for e in _END_ENV_RE.findall(scan_line) if e in _MD_MATH_ENVS]
        was_math_env = bool(math_env_stack)
        for env in begins:
            math_env_stack.append(env)
        now_math_env = bool(math_env_stack)
        for env in ends:
            for pos in range(len(math_env_stack) - 1, -1, -1):
                if math_env_stack[pos] == env:
                    math_env_stack.pop(pos)
                    break
        if was_math_env or now_math_env or (begins and not ends):
            out.append("")
            in_code_mask.append(False)
            continue

        # Multi-line & inline \[ ... \] and $$ ... $$ display math (preserves prose outside delimiters)
        work, in_dollar_display, in_bracket_display = _mask_display_math_line(
            scan_line, in_dollar_display, in_bracket_display
        )
        if not work.strip():
            out.append("")
            in_code_mask.append(False)
            continue

        if _MD_HR_RE.match(work):
            hr_lines.append(idx)
            out.append("")
            in_code_mask.append(False)
            continue

        hm = _MD_HEADING_RE.match(work)
        if hm:
            headings.append((idx, hm.group(2).strip()))

        work = _MD_LINK_URL_RE.sub("]([url])", work)
        work = _BARE_URL_RE.sub(" [url] ", work)
        work = _CITE_RE.sub(" [ref] ", work)
        work = _DISPLAY_MATH_INLINE_RE.sub(" [math] ", work)
        work = _INLINE_MATH_RE.sub(" [math] ", work)
        out.append(work)
        in_code_mask.append(False)

    return out, headings, hr_lines, in_code_mask


def mask_prose(raw: str, source_path: str | None = None) -> dict[str, Any]:
    """Return masked 1-indexed lines, headings, HRs, and paragraphs for prose linting."""
    raw_lines = raw.splitlines()
    tex_mode = _is_tex(source_path, raw)
    if tex_mode:
        masked_lines, headings = _mask_tex_lines(raw_lines, keep_tables=False)
        hr_lines: list[int] = []
        in_code_mask = [False] * len(raw_lines)
    else:
        masked_lines, headings, hr_lines, in_code_mask = _mask_markdown_lines(raw_lines)

    # Group non-empty masked lines into paragraphs with start line
    paragraphs: list[tuple[int, str]] = []
    buf: list[str] = []
    start_ln = 0
    for idx, line in enumerate(masked_lines, start=1):
        # Clean markdown heading marker for paragraph flow
        clean_ln = re.sub(r"^\s{0,3}#{1,6}\s+", "", line).strip()
        if clean_ln:
            if not buf:
                start_ln = idx
            buf.append(clean_ln)
        else:
            if buf:
                paragraphs.append((start_ln, " ".join(buf)))
                buf = []
    if buf:
        paragraphs.append((start_ln, " ".join(buf)))

    return {
        "is_tex": tex_mode,
        "raw_lines": raw_lines,
        "masked_lines": masked_lines,
        "headings": headings,
        "hr_lines": hr_lines,
        "in_code_mask": in_code_mask,
        "paragraphs": paragraphs,
    }


def _strip_exempt_domain_terms(line: str) -> str:
    """Mask approved domain-specific technical terms before lexical tell and inflation scanning."""
    work = _DOUBLE_QUOTE_SPAN_RE.sub(" [quote] ", line)
    work = _CATASTROPHIC_FORGETTING_EXEMPT_RE.sub(" [term] ", work)
    work = _LEVERAGE_EXEMPT_RE.sub(" [term] ", work)
    work = _STATISTICAL_LEVERAGE_RE.sub(" [term] ", work)
    work = _ROBUST_EXEMPT_RE.sub(" [term] ", work)
    work = _LANDSCAPE_EXEMPT_RE.sub(" [term] ", work)
    work = _GATE_EXEMPT_RE.sub(" [term] ", work)
    work = _KEY_EXEMPT_RE.sub(" [term] ", work)
    work = _REPRESENTS_MATH_EXEMPT_RE.sub(" [term] ", work)
    return work


# ---------------------------------------------------------------------------
# Sycophancy detection (SYC_FLATTERY, SYC_CHEERLEADING, SYC_PRAISE_SANDWICH)
# ---------------------------------------------------------------------------


def _genuine_flaw_matches(text: str) -> list[re.Match[str]]:
    """Return flaw matches that are not remediated/prior-work flaw mentions within their local clause."""
    out: list[re.Match[str]] = []
    for m in _SYC_SANDWICH_FLAW_RE.finditer(text):
        c_start = 0
        for sep in ".;!?\n,":
            idx = text.rfind(sep, 0, m.start())
            if idx != -1:
                c_start = max(c_start, idx + 1)
        c_end = len(text)
        for sep in ".;!?\n,":
            idx = text.find(sep, m.end())
            if idx != -1:
                c_end = min(c_end, idx)

        before = text[c_start:m.start()]
        after = text[m.end():c_end]

        solved = False
        for sm in _SOLVER_VERB_RE.finditer(before):
            ctx = before[max(0, sm.start() - 25) : sm.start()]
            if not _NEGATED_SOLVER_RE.search(ctx):
                solved = True
                break
        if solved:
            continue

        if _PRIOR_WORK_AFTER_FLAW_RE.match(after):
            continue

        prior_attributed = False
        for pm in _PRIOR_WORK_NP_RE.finditer(before):
            if not _TARGET_WORK_RE.search(before[pm.end():]):
                prior_attributed = True
                break
        if prior_attributed:
            continue

        out.append(m)
    return out


def detect_sycophancy(masked: dict[str, Any], mode: str = "manuscript") -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    masked_lines = masked["masked_lines"]

    for lineno, line in enumerate(masked_lines, start=1):
        if not line.strip():
            continue
        clean_line = re.sub(r"^\s{0,3}#{1,6}\s+", "", line)
        # Skip text inside explicit citations/quotes if clearly quoted prior work?
        # Keep sycophancy active on non-quoted prose; strip double-quoted excerpts only when cited.
        scan_line = clean_line

        for pat in _SYC_FLATTERY_PATTERNS:
            m = pat.search(scan_line)
            if m:
                hits.append({
                    "line": lineno,
                    "pattern_id": "SYC_FLATTERY",
                    "category": "flattery",
                    "severity": "RISK",
                    "critical": True,
                    "phrase": m.group(0),
                    "excerpt": _excerpt(clean_line),
                    "remediation": "Delete flattery and user validation; state the falsification check or empirical claim directly.",
                })
                break

        matched_crit = False
        for pat in _SYC_CHEER_CRITICAL_PATTERNS:
            m = pat.search(scan_line)
            if m:
                hits.append({
                    "line": lineno,
                    "pattern_id": "SYC_CHEERLEADING",
                    "category": "cheerleading",
                    "severity": "RISK",
                    "critical": True,
                    "phrase": m.group(0),
                    "excerpt": _excerpt(clean_line),
                    "remediation": "Replace unverified praise with exact metric deltas, named baselines, and unresolved failure modes.",
                })
                matched_crit = True
                break

        if not matched_crit:
            has_evidence = bool(re.search(r"(?:\d+(?:\.\d+)?%?|\[ref\]|\[C\d+\]|\[\d+\])", scan_line))
            for pat in _SYC_CHEER_SOFT_PATTERNS:
                m = pat.search(scan_line)
                if m and not has_evidence:
                    hits.append({
                        "line": lineno,
                        "pattern_id": "SYC_CHEERLEADING",
                        "category": "cheerleading",
                        "severity": "WARN",
                        "critical": False,
                        "phrase": m.group(0),
                        "excerpt": _excerpt(clean_line),
                        "remediation": "Provide cited evidence or measured comparisons before characterizing contribution strength.",
                    })
                    break

    # Praise-before-critique sandwich check (same-paragraph and adjacent cross-paragraph)
    paragraphs = masked["paragraphs"]
    flagged_sandwich_lines: set[int] = set()
    for p_idx, (start_ln, para) in enumerate(paragraphs):
        sents = _split_sentences(para)
        if not sents:
            continue
        para_has_your = bool(_USER_ADDRESS_RE.search(para))
        has_any_flaw_p1 = any(_genuine_flaw_matches(s) for s in sents)
        for s_idx, sent in enumerate(sents):
            # If an earlier sentence in paragraph 1 already stated a genuine flaw, critique came first
            if any(_genuine_flaw_matches(prev) for prev in sents[:s_idx]):
                break
            user_addressed = para_has_your or bool(_USER_ADDRESS_RE.search(sent))
            sent_for_praise = (
                _EMPIRICAL_METRIC_QUAL_RE.sub(" [metric] ", sent)
                if (mode == "manuscript" and not user_addressed)
                else sent
            )
            praise_m = _SYC_SANDWICH_PRAISE_RE.search(sent_for_praise)
            if not praise_m:
                continue
            # If this sentence already leads with a genuine flaw before any praise, don't flag
            flaws_in_sent = _genuine_flaw_matches(sent)
            if flaws_in_sent and flaws_in_sent[0].start() < praise_m.start():
                continue
            same_sent_pivot = bool(
                (_SYC_SANDWICH_PIVOT_RE.search(sent) or _SYC_SANDWICH_PREP_PIVOT_RE.search(sent))
                and (
                    bool(flaws_in_sent)
                    or (
                        bool(_SYC_SANDWICH_PIVOT_RE.search(sent))
                        and s_idx + 1 < len(sents)
                        and (mode != "manuscript" or user_addressed)
                    )
                )
            )
            next_sent_pivot = False
            for nxt in sents[s_idx + 1 : s_idx + 5]:
                st = nxt.strip()
                nxt_flaws = _genuine_flaw_matches(nxt)
                if (
                    (_SYC_SANDWICH_PIVOT_RE.match(st) and (bool(nxt_flaws) or mode != "manuscript" or user_addressed))
                    or (_SYC_SANDWICH_PREP_PIVOT_RE.match(st) and (_SYC_PRAISE_BACKREF_RE.match(st) or nxt_flaws))
                    or nxt_flaws
                ):
                    next_sent_pivot = True
                    break
            cross_para_pivot = False
            if not (same_sent_pivot or next_sent_pivot) and p_idx + 1 < len(paragraphs):
                if not has_any_flaw_p1 and _SYC_SANDWICH_STRONG_OR_USER_RE.search(sent_for_praise):
                    nxt_sents = _split_sentences(paragraphs[p_idx + 1][1])
                    p2_has_any_flaw = any(_genuine_flaw_matches(s) for s in nxt_sents[:3])
                    for p2_idx, raw_p2_s in enumerate(nxt_sents[:2]):
                        p2_s = raw_p2_s.strip()
                        p2_flaws = _genuine_flaw_matches(p2_s)
                        has_adverb_opener = bool(_SYC_SANDWICH_PIVOT_RE.match(p2_s))
                        has_prep_pivot = bool(_SYC_SANDWICH_PREP_PIVOT_RE.match(p2_s)) and (
                            bool(_SYC_PRAISE_BACKREF_RE.match(p2_s)) or p2_has_any_flaw
                        )
                        has_mid_pivot_flaw = bool(
                            (_SYC_SANDWICH_PIVOT_RE.search(p2_s) or _SYC_SANDWICH_PREP_PIVOT_RE.search(p2_s))
                            and p2_flaws
                        )
                        has_flaw_opener = bool(_SYC_SANDWICH_FLAW_RE.match(p2_s) and p2_flaws)
                        if has_adverb_opener or has_prep_pivot or has_mid_pivot_flaw or has_flaw_opener:
                            if not (
                                p2_has_any_flaw
                                or _SYC_PRAISE_BACKREF_RE.match(p2_s)
                                or mode != "manuscript"
                                or user_addressed
                            ):
                                continue
                            if p2_idx == 1 and not (
                                p2_flaws
                                or _SYC_PRAISE_BACKREF_RE.match(p2_s)
                                or mode != "manuscript"
                                or user_addressed
                            ):
                                continue
                            cross_para_pivot = True
                            break
            if (same_sent_pivot or next_sent_pivot or cross_para_pivot) and start_ln not in flagged_sandwich_lines:
                flagged_sandwich_lines.add(start_ln)
                hits.append({
                    "line": start_ln,
                    "pattern_id": "SYC_PRAISE_SANDWICH",
                    "category": "praise_sandwich",
                    "severity": "RISK",
                    "critical": True,
                    "phrase": praise_m.group(0),
                    "excerpt": _excerpt(sent),
                    "remediation": "Lead immediately with the fatal defect, prior-art threat, or missing receipt without softening praise.",
                })
                break

    return hits


# ---------------------------------------------------------------------------
# Claim Preservation (--compare-baseline)
# ---------------------------------------------------------------------------

_CONTRACTION_MAP = [
    (re.compile(r"\bdoesn't\b", re.I), "does not"),
    (re.compile(r"\bdon't\b", re.I), "do not"),
    (re.compile(r"\bdidn't\b", re.I), "did not"),
    (re.compile(r"\bisn't\b", re.I), "is not"),
    (re.compile(r"\baren't\b", re.I), "are not"),
    (re.compile(r"\bwasn't\b", re.I), "was not"),
    (re.compile(r"\bweren't\b", re.I), "were not"),
    (re.compile(r"\bcan't\b|\bcannot\b", re.I), "can not"),
    (re.compile(r"\bwon't\b", re.I), "will not"),
    (re.compile(r"\bwouldn't\b", re.I), "would not"),
    (re.compile(r"\bshouldn't\b", re.I), "should not"),
    (re.compile(r"\bcouldn't\b", re.I), "could not"),
    (re.compile(r"\bhasn't\b", re.I), "has not"),
    (re.compile(r"\bhaven't\b", re.I), "have not"),
    (re.compile(r"\bhadn't\b", re.I), "had not"),
]

_UNIT_CANON = {
    "%": "%",
    "\\%": "%",
    "percent": "%",
    "pct": "%",
    "ms": "ms",
    "s": "s",
    "sec": "s",
    "secs": "s",
    "second": "s",
    "seconds": "s",
    "min": "min",
    "mins": "min",
    "minute": "min",
    "minutes": "min",
    "h": "h",
    "hr": "h",
    "hrs": "h",
    "hour": "h",
    "hours": "h",
    "kb": "KB",
    "mb": "MB",
    "gb": "GB",
    "tb": "TB",
    "epoch": "epochs",
    "epochs": "epochs",
    "seed": "seeds",
    "seeds": "seeds",
    "param": "params",
    "params": "params",
    "parameter": "params",
    "parameters": "params",
    "token": "tokens",
    "tokens": "tokens",
    "sample": "samples",
    "samples": "samples",
    "step": "steps",
    "steps": "steps",
    "pp": "pp",
}

_NEGATIONS = ("not", "no", "never", "neither", "nor", "without")
_SCOPE_MARKERS = ("only", "under", "except", "unless", "assuming", "limited to", "bounded", "subject to", "at most", "at least")
_HEDGES = (
    "may", "might", "could", "likely", "unlikely",
    "suggest", "suggests", "suggested", "indicate", "indicates", "indicated",
    "hypothesize", "hypothesizes", "hypothesized", "conjecture", "exploratory", "preliminary", "post hoc",
    "correlational", "observational", "statistically significant",
    "non-significant", "inconclusive", "unknown",
)
_CERTAINTY_BOOSTERS = (
    "prove", "proves", "proved", "proven", "demonstrate", "demonstrates", "demonstrated",
    "confirm", "confirms", "confirmed", "establish", "establishes", "established",
    "guarantee", "guarantees", "guaranteed", "always", "clearly", "definitively", "undoubtedly",
)
_QUALIFIERS_RE = re.compile(
    r"\b(?:"
    + "|".join(re.escape(w) for w in sorted((*_NEGATIONS, *_SCOPE_MARKERS, *_HEDGES), key=len, reverse=True))
    + r")\b"
)
_CERTAINTY_RE = re.compile(
    r"\b(?:"
    + "|".join(re.escape(w) for w in sorted(_CERTAINTY_BOOSTERS, key=len, reverse=True))
    + r")\b"
)
_CE_LIST_RE = re.compile(
    r"\[((?:claim:|evidence:|@)?[CE]\d{1,8}(?:\s*[,;]\s*(?:claim:|evidence:|@)?[CE]\d{1,8})*)\]",
    re.I,
)
_UNIT_PAT = "|".join(
    sorted((re.escape(k) for k in _UNIT_CANON if k not in {"%", "\\%", "percent", "pct"}), key=len, reverse=True)
)
_UNIT_NUM_FIND_RE = re.compile(rf"\b(\d+(?:,\d{{3}})*(?:\.\d+)?)\s*({_UNIT_PAT})\b", re.I)
_UNIT_NUM_STRIP_RE = re.compile(rf"\b\d+(?:,\d{{3}})*(?:\.\d+)?\s*(?:{_UNIT_PAT})\b", re.I)


def _normalize_for_claims(raw: str, is_tex: bool) -> str:
    lines = raw.splitlines()
    out: list[str] = []
    fence_char: str | None = None
    in_fm = bool(lines and lines[0].strip() == "---")
    fm_end = -1
    if in_fm:
        for j in range(1, min(len(lines), 80)):
            if lines[j].strip() in {"---", "..."}:
                fm_end = j
                break
        if fm_end == -1:
            in_fm = False
    for idx, line in enumerate(lines):
        if in_fm:
            if idx == fm_end:
                in_fm = False
            continue
        if is_tex:
            line = _TEX_COMMENT_RE.sub("", line)
        else:
            st = line.strip()
            if fence_char is None:
                fm = re.match(r"^(`{3,}|~{3,})", st)
                if fm:
                    fence_char = fm.group(1)[0]
                    continue
            else:
                if st.startswith(fence_char * 3):
                    fence_char = None
                continue
            line = _mask_inline_code_spans(line, " ")
        line = _BARE_URL_RE.sub(" ", line)
        line = re.sub(r"\$([^$]+)\$", r" \1 ", line)
        if is_tex:
            line = re.sub(r"(?<!\\)~", " ", line)
        line = line.replace(r"\%", "%").replace(r"\pm", " ± ")
        out.append(line)
    text = "\n".join(out)
    if "'" in text or "cannot" in text.lower():
        for pat, repl in _CONTRACTION_MAP:
            text = pat.sub(repl, text)
    return text


def extract_claims_snapshot(raw: str, is_tex: bool = False) -> dict[str, Any]:
    """Extract normalized numbers, units, citations, qualifiers, and certainty tokens."""
    text = _normalize_for_claims(raw, is_tex=is_tex)

    # Citations first (so arXiv IDs or [1] don't pollute standalone numbers)
    citations: set[str] = set()
    for m in re.finditer(r"\\cite[a-zA-Z]*\*?(?:\[[^\[\]]*\]){0,2}\{([^{}]+)\}", text):
        for key in m.group(1).split(","):
            k = key.strip().lower()
            if k:
                citations.add(k)
    for m in _CE_LIST_RE.finditer(text):
        for item in re.split(r"\s*[,;]\s*", m.group(1)):
            cleaned = re.sub(r"^(?:claim:|evidence:|@)", "", item.strip(), flags=re.I).lower()
            if cleaned:
                citations.add(cleaned)
    for m in re.finditer(r"(?<![A-Za-z0-9_])\[(\d+(?:\s*,\s*\d+)*)\]", text):
        for num in m.group(1).split(","):
            citations.add(f"[{num.strip()}]")
    for m in re.finditer(r"\(([A-Z][A-Za-z-]+(?:\s+et\s+al\.)?),?\s*((?:19|20)\d{2}[a-z]?)\)", text):
        citations.add(f"{m.group(1).lower()} {m.group(2).lower()}")
    for m in re.finditer(r"\b(10\.\d{4,9}/[^\s,;)\]}]+)", text, re.I):
        citations.add(m.group(1).rstrip(".").lower())
    for m in re.finditer(r"(?:arXiv:)?(\d{4}\.\d{4,5})(?:v\d+)?", text, re.I):
        citations.add(f"arxiv:{m.group(1)}")

    # Strip citations before scanning numbers
    num_text = re.sub(r"\\cite[a-zA-Z]*\*?(?:\[[^\[\]]*\]){0,2}\{[^{}]+\}", " ", text)
    num_text = _CE_LIST_RE.sub(" ", num_text)
    num_text = re.sub(r"(?<![A-Za-z0-9_])\[\d+(?:\s*,\s*\d+)*\]", " ", num_text)
    num_text = re.sub(r"\b10\.\d{4,9}/[^\s,;)\]}]+", " ", num_text, flags=re.I)
    num_text = re.sub(r"(?:arXiv:)?\d{4}\.\d{4,5}(?:v\d+)?", " ", num_text, flags=re.I)
    # Strip markdown list markers & heading prefixes
    num_text = re.sub(r"^[ \t]*\d+\.[ \t]+", " ", num_text, flags=re.M)
    num_text = re.sub(r"[ \t]{2,}", " ", num_text)

    numbers: Counter[str] = Counter()
    units: Counter[str] = Counter()

    # Uncertainty pairs: e.g. 94.2% ± 0.3% or 81.4 +/- 0.3
    for m in re.finditer(
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:(%)\s*)?(?:±|\+/-)\s*(\d+(?:,\d{3})*(?:\.\d+)?)(?:\s*(%))?",
        num_text,
    ):
        v1 = m.group(1).replace(",", "")
        u2 = m.group(4) or ""
        u1 = (m.group(2) or "") or u2
        v2 = m.group(3).replace(",", "")
        numbers[f"{v1}{u1}"] += 1
        numbers[f"{v2}{u2}"] += 1
        if u1 or u2:
            units["%"] += 1

    # Remove consumed ± patterns to avoid double counting
    rem = re.sub(
        r"\d+(?:,\d{3})*(?:\.\d+)?\s*(?:%\s*)?(?:±|\+/-)\s*\d+(?:,\d{3})*(?:\.\d+)?(?:\s*%)?",
        " ",
        num_text,
    )

    # p-values
    for m in re.finditer(r"\bp\s*([<=>]=?)\s*(0?\.\d+)\b", rem, re.I):
        numbers[f"p{m.group(1)}{m.group(2)}"] += 1
    rem = re.sub(r"\bp\s*[<=>]=?\s*0?\.\d+\b", " ", rem, flags=re.I)

    # Multipliers (e.g. 2.3x)
    for m in re.finditer(r"\b(\d+(?:\.\d+)?)\s*(?:x|×|\\times)\b", rem, re.I):
        numbers[f"{m.group(1)}x"] += 1
    rem = re.sub(r"\b\d+(?:\.\d+)?\s*(?:x|×|\\times)\b", " ", rem, flags=re.I)

    # Percentages
    for m in re.finditer(r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:%|percent\b|pct\b)", rem, re.I):
        numbers[f"{m.group(1).replace(',', '')}%"] += 1
        units["%"] += 1
    rem = re.sub(r"\d+(?:,\d{3})*(?:\.\d+)?\s*(?:%|percent\b|pct\b)", " ", rem, flags=re.I)

    # Number + unit
    for m in _UNIT_NUM_FIND_RE.finditer(rem):
        val = m.group(1).replace(",", "")
        u = _UNIT_CANON[m.group(2).lower()]
        numbers[val] += 1
        units[u] += 1
    rem = _UNIT_NUM_STRIP_RE.sub(" ", rem)

    # Remaining standalone numbers
    for m in re.finditer(r"\b\d+(?:,\d{3})*(?:\.\d+)?(?:[eE][+-]?\d+)?\b", rem):
        numbers[m.group(0).replace(",", "")] += 1

    lower_text = " ".join(text.lower().split())
    qualifiers: Counter[str] = Counter(_QUALIFIERS_RE.findall(lower_text))
    certainty: Counter[str] = Counter(_CERTAINTY_RE.findall(lower_text))

    return {
        "numbers": numbers,
        "units": units,
        "citations": citations,
        "qualifiers": qualifiers,
        "certainty": certainty,
    }


def compare_claims(
    orig_raw: str,
    draft_raw: str,
    baseline_path: str = "",
    is_tex: bool | None = None,
    orig_is_tex: bool | None = None,
    draft_is_tex: bool | None = None,
) -> dict[str, Any]:
    """Compare draft claims against baseline text for dropped numbers, units, citations, or qualifiers."""
    if orig_is_tex is None:
        orig_is_tex = is_tex if is_tex is not None else _is_tex(baseline_path or None, orig_raw)
    if draft_is_tex is None:
        draft_is_tex = is_tex if is_tex is not None else _is_tex(None, draft_raw)
    orig = extract_claims_snapshot(orig_raw, is_tex=orig_is_tex)
    draft = extract_claims_snapshot(draft_raw, is_tex=draft_is_tex)

    numbers_dropped: list[str] = []
    for k, cnt in (orig["numbers"] - draft["numbers"]).items():
        numbers_dropped.extend([k] * cnt)
    numbers_added: list[str] = []
    for k, cnt in (draft["numbers"] - orig["numbers"]).items():
        numbers_added.extend([k] * cnt)

    units_dropped = sorted((orig["units"] - draft["units"]).keys())
    citations_dropped = sorted(orig["citations"] - draft["citations"])
    citations_added = sorted(draft["citations"] - orig["citations"])
    qualifiers_dropped = sorted((orig["qualifiers"] - draft["qualifiers"]).keys())

    dropped_hedges = [h for h in _HEDGES if draft["qualifiers"][h] < orig["qualifiers"][h]]
    increased_cert = [c for c in _CERTAINTY_BOOSTERS if draft["certainty"][c] > orig["certainty"][c]]
    certainty_escalations: list[str] = []
    if dropped_hedges and increased_cert:
        for h in dropped_hedges:
            for c in increased_cert:
                certainty_escalations.append(f"{h} -> {c}")

    preserved = not (
        numbers_dropped or units_dropped or citations_dropped or qualifiers_dropped or certainty_escalations
    )
    parts: list[str] = []
    if numbers_dropped:
        parts.append(f"{len(numbers_dropped)} number(s)")
    if units_dropped:
        parts.append(f"{len(units_dropped)} unit(s)")
    if citations_dropped:
        parts.append(f"{len(citations_dropped)} citation(s)")
    if qualifiers_dropped:
        parts.append(f"{len(qualifiers_dropped)} qualifier(s)")
    summary_parts = []
    if parts:
        summary_parts.append(", ".join(parts) + " dropped")
    if certainty_escalations:
        summary_parts.append(f"{len(certainty_escalations)} certainty escalation(s)")
    summary = "; ".join(summary_parts) if summary_parts else "all tracked claims preserved"

    return {
        "baseline_path": baseline_path,
        "preserved": preserved,
        "numbers_dropped": sorted(numbers_dropped),
        "numbers_added": sorted(numbers_added),
        "units_dropped": units_dropped,
        "citations_dropped": citations_dropped,
        "citations_added": citations_added,
        "qualifiers_dropped": qualifiers_dropped,
        "certainty_escalations": certainty_escalations,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# 8-gram Originality Overlap (adapted from overlap_check.py)
# ---------------------------------------------------------------------------


def _overlap_tokens(raw: str, source_name: str | None = None) -> list[str]:
    text = raw
    if _is_tex(source_name, raw):
        text = "\n".join(_TEX_COMMENT_RE.sub("", ln) for ln in raw.splitlines())
    text = _CITE_RE.sub(" ", text)
    text = _URL_CMD_RE.sub(" ", text)
    text = _BARE_URL_RE.sub(" ", text)
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = _TEX_CMD_BARE_RE.sub(" ", text)
    text = re.sub(r"(?<!\\)~", " ", text)
    return re.findall(r"[A-Za-z0-9]+", text.lower())


def _validate_overlap_threshold(threshold: float) -> None:
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not math.isfinite(threshold)
        or threshold < 0.0
        or threshold > 1.0
    ):
        raise ValueError(f"overlap_threshold must be a finite number in [0.0, 1.0], got {threshold!r}")


def compute_overlap(
    draft_raw: str,
    references: list[tuple[str, str]],
    threshold: float = 0.15,
    k: int = 8,
    source_name: str | None = None,
) -> tuple[float, dict[str, Any]]:
    """Compute k-gram overlap between draft and reference documents."""
    _validate_overlap_threshold(threshold)
    draft_toks = _overlap_tokens(draft_raw, source_name=source_name)
    matches_out: list[dict[str, Any]] = []
    max_score = 0.0
    any_flagged = False

    for ref_label, ref_raw in references:
        ref_toks = _overlap_tokens(ref_raw, source_name=ref_label)
        if len(draft_toks) < k or len(ref_toks) < k:
            matches_out.append({
                "reference": ref_label,
                "overlap_score": 0.0,
                "passage_count": 0,
                "passages": [],
            })
            continue
        ref_shingles = {tuple(ref_toks[i : i + k]) for i in range(len(ref_toks) - k + 1)}
        matched = [False] * len(draft_toks)
        for i in range(len(draft_toks) - k + 1):
            if tuple(draft_toks[i : i + k]) in ref_shingles:
                for j in range(i, i + k):
                    matched[j] = True
        passages: list[str] = []
        run_start: int | None = None
        for idx, flag in enumerate(matched):
            if flag and run_start is None:
                run_start = idx
            elif not flag and run_start is not None:
                if idx - run_start >= k:
                    passages.append(" ".join(draft_toks[run_start:idx]))
                run_start = None
        if run_start is not None and len(matched) - run_start >= k:
            passages.append(" ".join(draft_toks[run_start:]))

        score = round(sum(matched) / len(matched), 4)
        max_score = max(max_score, score)
        if score >= threshold or any(len(p.split()) >= 20 for p in passages):
            any_flagged = True
        matches_out.append({
            "reference": ref_label,
            "overlap_score": score,
            "passage_count": len(passages),
            "passages": passages[:10],
        })

    return max_score, {
        "shingle_k": k,
        "threshold": threshold,
        "flagged": any_flagged,
        "matches": matches_out,
    }


# ---------------------------------------------------------------------------
# Core Prose Linting (H01-H26, PL01-PL06, SYC_*, CP_DROPPED, OVL_8GRAM)
# ---------------------------------------------------------------------------


def _add_finding(
    findings: list[dict[str, Any]],
    line: int,
    category: str,
    pattern_id: str,
    severity: str,
    excerpt: str,
) -> None:
    findings.append({
        "line": line,
        "category": category,
        "pattern_id": pattern_id,
        "severity": severity,
        "excerpt": _excerpt(excerpt),
    })


def lint_text(
    raw: str,
    source_name: str = "<string>",
    mode: str = "manuscript",
    baseline_raw: str | None = None,
    baseline_path: str = "",
    references: list[tuple[str, str]] | None = None,
    overlap_threshold: float = 0.15,
) -> dict[str, Any]:
    """Run all Humanizer (H01-H26), prose-lint (PL01-PL06), sycophancy, claim, and overlap checks."""
    _validate_overlap_threshold(overlap_threshold)
    masked = mask_prose(raw, source_path=source_name)
    masked_lines = masked["masked_lines"]
    raw_lines = masked["raw_lines"]
    paragraphs = masked["paragraphs"]
    headings = masked["headings"]

    prose_words = sum(len(re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*", ln)) for ln in masked_lines)
    if prose_words == 0:
        raise ValueError("Source contains 0 prose words after masking.")

    findings: list[dict[str, Any]] = []

    # Pre-check H21 (curly quotes outside code fences & inline code)
    curly_lines: list[int] = []
    has_straight = False
    for idx, raw_ln in enumerate(raw_lines, start=1):
        if masked["in_code_mask"][idx - 1]:
            continue
        no_inline_code = _mask_inline_code_spans(raw_ln, " ")
        if _H21_CURLY_RE.search(no_inline_code):
            curly_lines.append(idx)
        if _H21_STRAIGHT_RE.search(no_inline_code):
            has_straight = True
    if curly_lines:
        sev = "WARN" if has_straight else "INFO"
        _add_finding(findings, curly_lines[0], "formatting", "H21", sev, raw_lines[curly_lines[0] - 1])

    # Pre-check H19 (bold as decoration) & H20 (decorative headings/HRs)
    bold_bullet_lines: list[int] = []
    consec_bold_bullets = 0
    max_consec_bold_bullets = 0
    for idx, ln in enumerate(masked_lines, start=1):
        if _H19_BOLD_BULLET_RE.match(ln):
            bold_bullet_lines.append(idx)
            consec_bold_bullets += 1
            max_consec_bold_bullets = max(max_consec_bold_bullets, consec_bold_bullets)
        elif ln.strip():
            consec_bold_bullets = 0
    if max_consec_bold_bullets >= 2 or len(bold_bullet_lines) >= 3:
        _add_finding(findings, bold_bullet_lines[0], "formatting", "H19", "WARN", masked_lines[bold_bullet_lines[0] - 1])
    for start_ln, para in paragraphs:
        if len(_H19_INLINE_BOLD_RE.findall(para)) >= 4:
            _add_finding(findings, start_ln, "formatting", "H19", "WARN", para)
            break

    title_case_headings = 0
    seen_h1: set[str] = set()
    for ln_no, htext in headings:
        if _H20_EMOJI_RE.search(htext) or _H20_ARROW_RE.search(htext):
            _add_finding(findings, ln_no, "formatting", "H20", "WARN", htext)
        words = [w for w in re.findall(r"[A-Za-z]+", htext) if len(w) > 3]
        if len(words) >= 3 and all(w[0].isupper() for w in words):
            title_case_headings += 1
        norm_h = htext.strip().lower()
        if not masked["is_tex"] and _MD_HEADING_RE.match(raw_lines[ln_no - 1]) and _MD_HEADING_RE.match(raw_lines[ln_no - 1]).group(1) == "#":
            if norm_h in seen_h1:
                _add_finding(findings, ln_no, "formatting", "H20", "INFO", htext)
            seen_h1.add(norm_h)
    if title_case_headings >= 3:
        _add_finding(findings, headings[0][0], "formatting", "H20", "INFO", headings[0][1])
    if len(masked["hr_lines"]) >= 3:
        _add_finding(findings, masked["hr_lines"][0], "formatting", "H20", "INFO", "---")

    # H24: Heading repeated in first sentence of next paragraph
    for ln_no, htext in headings:
        h_words = set(re.findall(r"[a-z]{3,}", htext.lower()))
        if not h_words:
            continue
        for p_ln, para in paragraphs:
            if p_ln > ln_no and p_ln - ln_no <= 3:
                first_s = _split_sentences(para)[0] if _split_sentences(para) else para
                s_words = re.findall(r"[a-z]{3,}", first_s.lower())
                if len(first_s.split()) <= 8 and s_words:
                    s_set = set(s_words)
                    jacc = len(h_words & s_set) / len(h_words | s_set)
                    if jacc >= 0.65 or (len(h_words) >= 2 and h_words.issubset(s_set)):
                        _add_finding(findings, p_ln, "leftovers", "H24", "WARN", f"{htext} -> {first_s}")
                break

    # Counters for aggregate stats & thresholded patterns
    not_only_lines: list[int] = []
    rather_than_lines: list[int] = []
    soft_h03_lines: list[int] = []
    triad_lines: list[int] = []
    em_dash_total = 0
    em_dash_first_ln = 0
    hedge_total = 0
    hedge_first_ln = 0
    h10_lines: list[int] = []
    h12_hits: dict[str, list[int]] = {}
    h12_first_excerpt: dict[str, str] = {}
    booster_lines: list[int] = []
    h14_lines: list[int] = []
    h15_lines: list[int] = []
    h18_soft_lines: list[int] = []
    h25_lines: list[int] = []
    connective_total = 0
    connective_first_ln = 0
    vague_opener_lines: list[int] = []

    # Line-by-line checks
    for lineno, raw_masked in enumerate(masked_lines, start=1):
        if not raw_masked.strip():
            continue
        clean_ln = re.sub(r"^\s{0,3}#{1,6}\s+", "", raw_masked).strip()
        raw_orig_ln = raw_lines[lineno - 1]

        # H22 Chatbot residue & placeholders (check before quote masking!)
        for pat in _H22_PATTERNS:
            if pat.search(clean_ln):
                _add_finding(findings, lineno, "leftovers", "H22", "RISK", clean_ln)
                break

        # H23 Knowledge-limit disclaimers & guesses
        if any(p.search(clean_ln) for p in _H23_RISK_PATTERNS):
            _add_finding(findings, lineno, "leftovers", "H23", "RISK", clean_ln)
        elif any(p.search(clean_ln) for p in _H23_WARN_PATTERNS):
            _add_finding(findings, lineno, "leftovers", "H23", "WARN", clean_ln)

        # H01 Not X but Y
        if any(p.search(clean_ln) for p in _H01_STRONG_PATTERNS):
            _add_finding(findings, lineno, "staging", "H01", "WARN", clean_ln)
        elif _H01_NOT_ONLY_RE.search(clean_ln):
            not_only_lines.append(lineno)
        if _H01_RATHER_THAN_RE.search(clean_ln):
            rather_than_lines.append(lineno)

        # H02 One-line closers & fragments
        if any(p.search(clean_ln) for p in _H02_CLOSER_PATTERNS):
            _add_finding(findings, lineno, "staging", "H02", "WARN", clean_ln)

        # H03 Sayings that sound deep
        if any(p.search(clean_ln) for p in _H03_STRONG_PATTERNS):
            _add_finding(findings, lineno, "staging", "H03", "WARN", clean_ln)
        elif _H03_SOFT_RE.search(clean_ln):
            soft_h03_lines.append(lineno)

        # H04 Staged run-up
        if any(p.search(clean_ln) for p in _H04_PATTERNS):
            _add_finding(findings, lineno, "staging", "H04", "WARN", clean_ln)

        # H05 Arguing with no one
        if any(p.search(clean_ln) for p in _H05_PATTERNS):
            _add_finding(findings, lineno, "staging", "H05", "WARN", clean_ln)

        # H08 Dashes (ignore numeric ranges like 2020-2024 or 2020–2024)
        no_num_range = re.sub(r"\d+[–-]\d+", " ", clean_ln)
        dashes = _EM_DASH_RE.findall(no_num_range)
        if dashes:
            em_dash_total += len(dashes)
            if not em_dash_first_ln:
                em_dash_first_ln = lineno

        # H09 Double hedges & hedge inventory
        if any(p.search(clean_ln) for p in _H09_DOUBLE_HEDGE_PATTERNS):
            _add_finding(findings, lineno, "rhythm", "H09", "WARN", clean_ln)
        h_cnt = len(_HEDGE_WORDS_RE.findall(clean_ln))
        if h_cnt:
            hedge_total += h_cnt
            if not hedge_first_ln:
                hedge_first_ln = lineno

        # H10 Predicative hyphenated pairs
        for hm in _H10_PREDICATIVE_RE.finditer(clean_ln):
            if hm.group(1).lower() not in _H10_HYPHEN_EXEMPT:
                h10_lines.append(lineno)

        # H11 Passive contribution & verbless fragments
        if _H11_PASSIVE_CONTRIB_RE.search(clean_ln) or _H11_VERBLESS_RE.match(clean_ln):
            _add_finding(findings, lineno, "rhythm", "H11", "WARN", clean_ln)

        # Strip quoted spans and domain terms for lexical tell checks H12-H18
        lex_ln = _strip_exempt_domain_terms(clean_ln)

        # H12 Overused AI words & boosters
        for label, pat in _H12_WORDS:
            if pat.search(lex_ln):
                h12_hits.setdefault(label, []).append(lineno)
                h12_first_excerpt.setdefault(label, clean_ln)
        if _H12_BOOSTERS_RE.search(lex_ln):
            booster_lines.append(lineno)

        # H13 Inflated significance
        if any(p.search(lex_ln) for p in _H13_PATTERNS):
            _add_finding(findings, lineno, "inflation", "H13", "WARN", clean_ln)

        # H14 Vague connection
        if _H14_RE.search(lex_ln):
            h14_lines.append(lineno)

        # H15 Shallow -ing phrases
        if _H15_STRONG_RE.search(lex_ln):
            h15_lines.append(lineno)

        # H16 Sales language
        if _H16_RE.search(lex_ln):
            _add_finding(findings, lineno, "inflation", "H16", "WARN", clean_ln)

        # H17 Borrowed authority (only when sentence/line lacks citation)
        has_cite = bool(re.search(r"(\[ref\]|\[\d+\]|\[C\d+\]|\[url\]|\([A-Z][A-Za-z-]+,?\s*(?:19|20)\d{2}\))", raw_orig_ln) or "[ref]" in clean_ln or "[url]" in clean_ln)
        if (_H17_AUTHORITY_RE.search(lex_ln) and not has_cite) or _H17_PRESTIGE_RE.search(lex_ln) or _H17_FOLLOWERS_RE.search(lex_ln):
            _add_finding(findings, lineno, "inflation", "H17", "WARN", clean_ln)

        # H18 Avoiding is/are/has
        if _H18_STRONG_RE.search(lex_ln):
            _add_finding(findings, lineno, "inflation", "H18", "WARN", clean_ln)
        elif _H18_SOFT_RE.search(lex_ln):
            h18_soft_lines.append(lineno)

        # H25 Meta-document narration
        if _H25_RE.search(clean_ln):
            h25_lines.append(lineno)

        # PL01 Connective count
        c_matches = _CONNECTIVES_RE.findall(clean_ln)
        if c_matches:
            connective_total += len(c_matches)
            if not connective_first_ln:
                connective_first_ln = lineno

        # PL03 significant without stats
        if _SIGNIFICANT_RE.search(clean_ln) and not _STATS_CONTEXT_RE.search(clean_ln):
            _add_finding(findings, lineno, "prose_density", "PL03", "INFO", clean_ln)

        # PI01 problem inflation & PAD01 extraneous boilerplate padding
        if any(p.search(lex_ln) for p in _PI01_PATTERNS):
            _add_finding(findings, lineno, "problem_inflation", "PI01", "WARN", clean_ln)
        if any(p.search(lex_ln) for p in _PAD01_PATTERNS):
            _add_finding(findings, lineno, "padding", "PAD01", "WARN", clean_ln)

    # Aggregate line findings
    if len(not_only_lines) == 1:
        _add_finding(findings, not_only_lines[0], "staging", "H01", "INFO", masked_lines[not_only_lines[0] - 1])
    elif len(not_only_lines) >= 2:
        _add_finding(findings, not_only_lines[0], "staging", "H01", "WARN", masked_lines[not_only_lines[0] - 1])
    if len(rather_than_lines) >= 3:
        _add_finding(findings, rather_than_lines[0], "staging", "H01", "WARN", masked_lines[rather_than_lines[0] - 1])

    if len(soft_h03_lines) == 1:
        _add_finding(findings, soft_h03_lines[0], "staging", "H03", "INFO", masked_lines[soft_h03_lines[0] - 1])
    elif len(soft_h03_lines) >= 2:
        _add_finding(findings, soft_h03_lines[0], "staging", "H03", "WARN", masked_lines[soft_h03_lines[0] - 1])

    em_rate = em_dash_total * 1000.0 / prose_words
    if em_dash_total >= 4 and em_rate > 5.0:
        _add_finding(findings, em_dash_first_ln, "rhythm", "H08", "WARN", masked_lines[em_dash_first_ln - 1])
    elif em_dash_total > 0 and prose_words <= 100 and em_dash_total >= 3:
        _add_finding(findings, em_dash_first_ln, "rhythm", "H08", "WARN", masked_lines[em_dash_first_ln - 1])
    elif em_dash_total > 0:
        _add_finding(findings, em_dash_first_ln, "rhythm", "H08", "INFO", masked_lines[em_dash_first_ln - 1])

    if hedge_total > 0:
        _add_finding(findings, hedge_first_ln, "rhythm", "H09", "INFO", f"Hedge inventory: {hedge_total} hedge token(s)")

    if len(h10_lines) == 1:
        _add_finding(findings, h10_lines[0], "rhythm", "H10", "INFO", masked_lines[h10_lines[0] - 1])
    elif len(h10_lines) >= 2:
        _add_finding(findings, h10_lines[0], "rhythm", "H10", "WARN", masked_lines[h10_lines[0] - 1])

    h12_sev = "RISK" if len(h12_hits) >= 2 else "WARN"
    for label, lines_hit in h12_hits.items():
        _add_finding(findings, lines_hit[0], "inflation", "H12", h12_sev, f"[{label}] {h12_first_excerpt[label]}")
    if booster_lines:
        _add_finding(findings, booster_lines[0], "inflation", "H12", "WARN", masked_lines[booster_lines[0] - 1])

    if len(h14_lines) >= 3:
        _add_finding(findings, h14_lines[0], "inflation", "H14", "WARN", masked_lines[h14_lines[0] - 1])
    elif len(h14_lines) > 0:
        _add_finding(findings, h14_lines[0], "inflation", "H14", "INFO", masked_lines[h14_lines[0] - 1])

    if len(h15_lines) >= 1:
        _add_finding(findings, h15_lines[0], "inflation", "H15", "WARN", masked_lines[h15_lines[0] - 1])

    if h18_soft_lines:
        _add_finding(findings, h18_soft_lines[0], "inflation", "H18", "INFO", masked_lines[h18_soft_lines[0] - 1])

    if len(h25_lines) >= 2:
        _add_finding(findings, h25_lines[0], "leftovers", "H25", "WARN", masked_lines[h25_lines[0] - 1])
    elif h25_lines:
        _add_finding(findings, h25_lines[0], "leftovers", "H25", "INFO", masked_lines[h25_lines[0] - 1])

    # Paragraph & sentence-level checks (H06, H07, H26, PL01, PL02, PL04, PL05, PL06)
    all_sentences: list[tuple[int, str]] = []
    para_sent_counts: list[int] = []
    consec_connective_paras: list[int] = []

    for start_ln, para in paragraphs:
        sents = _split_sentences(para)
        para_sent_counts.append(len(sents))
        for s in sents:
            all_sentences.append((start_ln, s))
            if _VAGUE_OPENER_RE.match(s):
                vague_opener_lines.append(start_ln)
            if len(s.split()) > 60:
                _add_finding(findings, start_ln, "prose_density", "PL05", "WARN", s)

        # H06 Forced triads
        for tm in _H06_TRIAD_RE.finditer(para):
            items = {tm.group(1).lower(), tm.group(2).lower(), tm.group(3).lower()}
            if len(items & _H06_BUZZWORDS) >= 2:
                triad_lines.append(start_ln)

        # H07 Repeated sentence openings
        if len(sents) >= 3:
            first_words = [re.findall(r"[A-Za-z]+", s.lower())[:2] for s in sents]
            run = 1
            for i in range(1, len(first_words)):
                if first_words[i] and first_words[i - 1] and first_words[i][0] == first_words[i - 1][0]:
                    run += 1
                    w0 = first_words[i][0]
                    same_two = len(first_words[i]) > 1 and len(first_words[i - 1]) > 1 and first_words[i][1] == first_words[i - 1][1]
                    if (run >= 4) or (run >= 3 and (w0 not in {"we", "the", "in"} or same_two)):
                        _add_finding(findings, start_ln, "rhythm", "H07", "WARN" if run >= 4 or same_two else "INFO", sents[i])
                        break
                else:
                    run = 1

        # PL02 Consecutive connective-opening paragraphs
        if _CONNECTIVE_OPENER_RE.match(para):
            consec_connective_paras.append(start_ln)
        else:
            if len(consec_connective_paras) >= 2:
                _add_finding(findings, consec_connective_paras[0], "prose_density", "PL02", "WARN", para)
            consec_connective_paras = []

    if len(consec_connective_paras) >= 2:
        _add_finding(findings, consec_connective_paras[0], "prose_density", "PL02", "WARN", masked_lines[consec_connective_paras[0] - 1])

    if len(triad_lines) >= 2:
        _add_finding(findings, triad_lines[0], "rhythm", "H06", "WARN", masked_lines[triad_lines[0] - 1])
    elif len(triad_lines) == 1:
        _add_finding(findings, triad_lines[0], "rhythm", "H06", "INFO", masked_lines[triad_lines[0] - 1])

    # PL01 Connective density
    conn_rate = connective_total * 1000.0 / prose_words
    if connective_total >= 5 and conn_rate > 8.0:
        _add_finding(findings, connective_first_ln, "prose_density", "PL01", "WARN", masked_lines[connective_first_ln - 1])

    # PL04 Vague openers
    if len(vague_opener_lines) >= 3:
        _add_finding(findings, vague_opener_lines[0], "prose_density", "PL04", "INFO", masked_lines[vague_opener_lines[0] - 1])

    # PL06 Uniform paragraphs
    multi_sent_paras = [c for c in para_sent_counts if c >= 2]
    if len(multi_sent_paras) >= 6:
        mean_len = statistics.mean(multi_sent_paras)
        stdev_len = statistics.pstdev(multi_sent_paras)
        if mean_len > 0 and (stdev_len / mean_len) < 0.25:
            _add_finding(findings, paragraphs[0][0], "prose_density", "PL06", "INFO", "Uniform paragraph sentence counts")

    # H11 passive density INFO
    passive_hits = sum(len(_H11_PASSIVE_AUX_RE.findall(ln)) for ln in masked_lines)
    if len(all_sentences) >= 4 and passive_hits / max(len(all_sentences), 1) >= 0.5:
        _add_finding(findings, 1, "rhythm", "H11", "INFO", f"Passive density {passive_hits}/{len(all_sentences)} sentences")

    # H26 Re-explaining known context (reply mode)
    if mode == "reply" and len(all_sentences) >= 4:
        decision_re = re.compile(r"\b(?:use|run|reject|accept|drop|fail|pass|recommend|fix|stop|choose)\b", re.I)
        cutoff = int(math.floor(len(all_sentences) * 0.75))
        early_decisions = sum(1 for _, s in all_sentences[:cutoff] if decision_re.search(s))
        late_decisions = sum(1 for _, s in all_sentences[cutoff:] if decision_re.search(s))
        if early_decisions == 0 and late_decisions > 0 and cutoff >= 3:
            _add_finding(findings, all_sentences[0][0], "wrong_reader", "H26", "WARN", all_sentences[0][1])

    # PAD02 Redundant cross-section/paragraph self-restatement
    heading_texts = {ht.strip().lower() for _, ht in headings if ht.strip()}
    seen_para_sents: list[tuple[int, int, list[str], set[str], set[tuple[str, ...]], str]] = []
    seen_8grams: dict[tuple[str, ...], int] = {}
    flagged_pad02_lines: set[int] = set()
    for p_idx, (start_ln, para) in enumerate(paragraphs):
        if para.strip().lower() in heading_texts:
            continue
        p_toks: list[str] = []
        for s in _split_sentences(para):
            if s.strip().lower() in heading_texts or _MATH_OR_CAPTION_BOILERPLATE_RE.search(s):
                continue
            s_clean = re.sub(r"\[(?:math|ref|url|code)\]", " ", s)
            toks = re.findall(r"[a-z0-9]+", s_clean.lower())
            p_toks.extend(toks)
            if len(toks) < 8:
                continue
            tset = set(toks)
            shingles8 = {tuple(toks[i : i + 8]) for i in range(len(toks) - 7)}
            matched_prev = False
            for prev_idx, _, prev_toks, prev_set, prev_shingles8, _ in seen_para_sents:
                if prev_idx == p_idx:
                    continue
                if toks == prev_toks:
                    matched_prev = True
                    break
                inter = len(tset & prev_set)
                union = len(tset | prev_set)
                if union and inter >= 8 and (inter / union) >= 0.70:
                    matched_prev = True
                    break
                if shingles8 & prev_shingles8:
                    matched_prev = True
                    break
            if matched_prev and start_ln not in flagged_pad02_lines:
                _add_finding(findings, start_ln, "padding", "PAD02", "WARN", s)
                flagged_pad02_lines.add(start_ln)
            seen_para_sents.append((p_idx, start_ln, toks, tset, shingles8, s))
        if len(p_toks) >= 8 and start_ln not in flagged_pad02_lines:
            run_len = 0
            for i in range(len(p_toks) - 7):
                ng = tuple(p_toks[i : i + 8])
                prev_p = seen_8grams.get(ng)
                if prev_p is not None and prev_p != p_idx:
                    run_len = run_len + 1 if run_len else 8
                    if run_len >= 8:
                        _add_finding(findings, start_ln, "padding", "PAD02", "WARN", para)
                        flagged_pad02_lines.add(start_ln)
                        break
                else:
                    run_len = 0
            for i in range(len(p_toks) - 7):
                seen_8grams.setdefault(tuple(p_toks[i : i + 8]), p_idx)

    # Sycophancy checks
    syc_hits = detect_sycophancy(masked, mode=mode)
    for sh in syc_hits:
        _add_finding(findings, sh["line"], "sycophancy", sh["pattern_id"], sh["severity"], sh["excerpt"])

    # Claim preservation
    claim_pres: dict[str, Any] | None = None
    if baseline_raw is not None:
        orig_is_tex = _is_tex(baseline_path or None, baseline_raw)
        claim_pres = compare_claims(
            baseline_raw,
            raw,
            baseline_path=baseline_path,
            orig_is_tex=orig_is_tex,
            draft_is_tex=masked["is_tex"],
        )
        if not claim_pres["preserved"]:
            _add_finding(findings, 1, "claim_preservation", "CP_DROPPED", "RISK", claim_pres["summary"])

    # Overlap check
    overlap_score: float | None = None
    overlap_details: dict[str, Any] | None = None
    if references:
        overlap_score, overlap_details = compute_overlap(
            raw,
            references,
            threshold=overlap_threshold,
            k=8,
            source_name=source_name,
        )
        if overlap_details["flagged"]:
            top_passage = ""
            for m in overlap_details["matches"]:
                if m["passages"]:
                    top_passage = m["passages"][0]
                    break
            _add_finding(
                findings,
                1,
                "originality_overlap",
                "OVL_8GRAM",
                "RISK",
                top_passage or f"8-gram overlap {overlap_score} >= {overlap_threshold}",
            )
    elif baseline_raw is not None:
        overlap_score, overlap_details = compute_overlap(
            raw,
            [(baseline_path or "baseline", baseline_raw)],
            threshold=overlap_threshold,
            k=8,
            source_name=source_name,
        )

    risk_count = sum(1 for f in findings if f["severity"] == "RISK")
    warn_count = sum(1 for f in findings if f["severity"] == "WARN")
    info_count = sum(1 for f in findings if f["severity"] == "INFO")

    return {
        "source": source_name,
        "mode": mode,
        "stats": {
            "words": prose_words,
            "sentences": len(all_sentences),
            "paragraphs": len(paragraphs),
            "connectives": connective_total,
            "em_dashes": em_dash_total,
            "hedges": hedge_total,
        },
        "risk_count": risk_count,
        "warn_count": warn_count,
        "info_count": info_count,
        "findings": findings,
        "sycophancy_hits": syc_hits,
        "overlap_score": overlap_score,
        "overlap_details": overlap_details,
        "claim_preservation": claim_pres,
    }


def _format_markdown_report(result: dict[str, Any]) -> str:
    lines = [
        f"# Humanizer & Integrity Lint Report: `{result['source']}`",
        "",
        f"- Mode: `{result['mode']}`",
        f"- Counts: `RISK={result['risk_count']}`, `WARN={result['warn_count']}`, `INFO={result['info_count']}`",
        f"- Stats: {result['stats']}",
    ]
    if result["claim_preservation"] is not None:
        cp = result["claim_preservation"]
        lines.append(f"- Claim preservation (`{cp['baseline_path']}`): `preserved={cp['preserved']}` ({cp['summary']})")
    if result["overlap_details"] is not None:
        ov = result["overlap_details"]
        lines.append(f"- 8-gram overlap: `score={result['overlap_score']}`, `flagged={ov['flagged']}`")
    if result["findings"]:
        lines.append("")
        lines.append("| Line | Severity | Pattern | Category | Excerpt |")
        lines.append("|---|---|---|---|---|")
        for f in result["findings"]:
            ex = f["excerpt"].replace("|", "\\|")
            lines.append(f"| {f['line']} | {f['severity']} | `{f['pattern_id']}` | {f['category']} | {ex} |")
    return "\n".join(lines)


def _compact_result(result: dict[str, Any], limit: int = 10) -> dict[str, Any]:
    """Return a token-frugal bounded summary of lint_text output."""
    sev_rank = {"RISK": 0, "WARN": 1, "INFO": 2}
    ordered_findings = sorted(result["findings"], key=lambda f: (sev_rank.get(f["severity"], 9), f["line"]))
    syc_hits = result["sycophancy_hits"]
    cp = result["claim_preservation"]
    ov = result["overlap_details"]
    return {
        "compact": True,
        "source": result["source"],
        "mode": result["mode"],
        "stats": result["stats"],
        "risk_count": result["risk_count"],
        "warn_count": result["warn_count"],
        "info_count": result["info_count"],
        "total_findings": len(result["findings"]),
        "findings_truncated": max(0, len(result["findings"]) - limit),
        "findings": ordered_findings[:limit],
        "total_sycophancy_hits": len(syc_hits),
        "sycophancy_truncated": max(0, len(syc_hits) - limit),
        "sycophancy_hits": syc_hits[:limit],
        "overlap_score": result["overlap_score"],
        "overlap_flagged": ov["flagged"] if isinstance(ov, dict) else None,
        "claim_preservation": (
            {"preserved": cp["preserved"], "summary": cp["summary"]} if isinstance(cp, dict) else None
        ),
    }


def _read_text_file(path_str: str) -> str:
    if not isinstance(path_str, str) or not path_str.strip():
        raise ValueError("Invalid empty file path")
    p = Path(path_str)
    if not p.is_file():
        raise FileNotFoundError(f"File not found: {path_str}")
    text = p.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"File is empty: {path_str}")
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Lint scholarly prose for Humanizer AI tells, sycophancy, claim preservation, and 8-gram overlap."
    )
    parser.add_argument("source", help="Path to .md, .tex, .txt file or '-' for stdin")
    parser.add_argument("--strict", action="store_true", help="Exit 1 on RISK, WARN, critical sycophancy, dropped claims, or flagged overlap")
    parser.add_argument("--compare-baseline", metavar="ORIG", help="Baseline file to verify numbers, units, citations, and qualifiers are preserved")
    parser.add_argument("--reference", action="extend", nargs="+", metavar="REF", help="Reference file(s) for 8-gram overlap check")
    parser.add_argument("--overlap-threshold", type=float, default=0.15, help="8-gram matched token fraction threshold (default: 0.15)")
    parser.add_argument("--mode", choices=("manuscript", "reply", "review"), default="manuscript", help="Document mode")
    parser.add_argument("--json", action="store_true", help="Output JSON report to stdout")
    parser.add_argument("--compact", action="store_true", help="Emit compact bounded summary capping verbose lists")

    args = parser.parse_args(argv)
    try:
        _validate_overlap_threshold(args.overlap_threshold)
        if args.source == "-":
            raw = sys.stdin.read()
            if not raw.strip():
                raise ValueError("Stdin input is empty.")
            source_name = "<stdin>"
        else:
            if not args.source.strip():
                raise ValueError("Invalid empty source path")
            raw = _read_text_file(args.source)
            source_name = args.source

        baseline_raw = None
        if args.compare_baseline is not None:
            if not args.compare_baseline.strip():
                raise ValueError("Invalid empty path passed to --compare-baseline")
            baseline_raw = _read_text_file(args.compare_baseline)

        references: list[tuple[str, str]] | None = None
        if args.reference is not None:
            references = [(ref, _read_text_file(ref)) for ref in args.reference]

        result = lint_text(
            raw=raw,
            source_name=source_name,
            mode=args.mode,
            baseline_raw=baseline_raw,
            baseline_path=args.compare_baseline or "",
            references=references,
            overlap_threshold=args.overlap_threshold,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        payload = _compact_result(result) if args.compact else result
        print(json.dumps(payload, separators=(",", ":")) if args.compact else json.dumps(payload, indent=2))
    else:
        if args.compact:
            comp = _compact_result(result)
            print(f"humanizer_lint: RISK={comp['risk_count']} WARN={comp['warn_count']} INFO={comp['info_count']} (showing {len(comp['findings'])}/{comp['total_findings']})")
            for f in comp["findings"]:
                print(f"- L{f['line']} [{f['severity']}] {f['pattern_id']}: {f['excerpt']}")
            if comp["findings_truncated"]:
                print(f"... ({comp['findings_truncated']} more finding(s) truncated)")
        else:
            print(_format_markdown_report(result))

    if args.strict:
        has_critical_syc = any(hit.get("critical") for hit in result["sycophancy_hits"])
        cp_failed = result["claim_preservation"] is not None and not result["claim_preservation"]["preserved"]
        ov_failed = bool(args.reference) and result["overlap_details"] is not None and result["overlap_details"]["flagged"]
        if result["risk_count"] > 0 or result["warn_count"] > 0 or has_critical_syc or cp_failed or ov_failed:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
