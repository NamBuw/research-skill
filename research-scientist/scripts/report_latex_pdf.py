#!/usr/bin/env python3
"""Concise, plain-language, multilingual LaTeX-to-PDF executive user report generator.

Supports:
- Code-switching-resilient language detection (`vi`, `en`, `fr`, `de`, `es`,
  plus Latin-script fallback) from `--input-text` or `--input` JSON fields.
- Multi-schema normalization for canonical `research_scientist_executive_report_v1` JSON
  and upstream skill outputs (`gap-record`, `gap_pipeline`, `search_papers`,
  `search_campaign`, `venue-novelty-profile`, `scorecards`, `venue-dossier`,
  `humanizer_lint`, `check_manuscript_ledger`, `check_evidence_map`,
  `check_engineering_diagnostics`, `check_experiment_manifest`, and composite bundles).
- Optional parsimony/anti-problem-inflation check (`simplest_alternative` / `parsimony_check`).
- Strict conciseness, plain-language, anti-sycophancy, and claim-grounding linter
  (`lint_report()`), preserving domain-term exemptions from `humanizer_lint.py`.
- Capability-based LaTeX engine selection (`xelatex` -> `lualatex` -> `pdflatex`) with
  package/font probing, NFC normalization, single-pass safe LaTeX escaping, isolated
  2-pass compilation, and post-compile `pymupdf` (`fitz`) diacritic verification.

CLI:
    python3 research-scientist/scripts/report_latex_pdf.py \
        --input <json> --out <pdf_path> [--tex-out <tex_path>] \
        [--lang <auto|vi|en|...>] [--input-text <prior_user_prompt>] \
        [--engine <auto|pdflatex|xelatex|lualatex>] [--strict] [--json] [--compact]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import importlib.util
import json
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "research_scientist_executive_report_v1"

# ---------------------------------------------------------------------------
# Multilingual Signals & Localization Catalogs
# ---------------------------------------------------------------------------

_VI_UNIQUE_CHARS_RE = re.compile(
    r"[đĐăĂâÂêÊôÔơƠưƯ"
    r"ảãạắằẳẵặấầẩẫậẻẽẹếềểễệỉĩịỏõọốồổỗộớờởỡợủũụứừửữựỷỹỵ"
    r"ẢÃẠẮẰẲẴẶẤẦẨẪẬẺẼẸẾỀỂỄỆỈĨỊỎÕỌỐỒỔỖỘỚỜỞỠỢỦŨỤỨỪỬỮỰỶỸỴ]"
)
_VI_ALL_DIACRITIC_RE = re.compile(
    r"[đĐăĂâÂêÊôÔơƠưƯ"
    r"áàảãạắằẳẵặấầẩẫậéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ"
    r"ÁÀẢÃẠẮẰẲẴẶẤẦẨẪẬÉÈẺẼẸẾỀỂỄỆÍÌỈĨỊÓÒỎÕỌỐỒỔỖỘỚỜỞỠỢÚÙỦŨỤỨỪỬỮỰÝỲỶỸỴ]"
)
_T5_REQUIRED_CHARS_RE = re.compile(
    r"[đĐăĂơƠưƯ"
    r"ảãạắằẳẵặấầẩẫậẻẽẹếềểễệỉĩịỏõọốồổỗộớờởỡợủũụứừửữựỳỷỹỵ"
    r"ẢÃẠẮẰẲẴẶẤẦẨẪẬẺẼẸẾỀỂỄỆỈĨỊỎÕỌỐỒỔỖỘỚỜỞỠỢỦŨỤỨỪỬỮỰỲỶỸỴ]"
)
_T1_ONLY_CHARS_RE = re.compile(r"[äöüßñçœæëïüåøîûÿÄÖÜÑÇŒÆËÏÅØÎÛŸ¿¡]")
_NON_LATIN_SCRIPT_RE = re.compile(
    r"[\u0400-\u04FF\u0600-\u06FF\u0900-\u097F\u3040-\u30FF\u4E00-\u9FFF\uAC00-\uD7AF]"
)

_TECH_LOANWORDS_RE = re.compile(
    r"\b(?:"
    r"rag|llm|llms|transformer|transformers|baseline|baselines|ablation|ablations|"
    r"benchmark|benchmarks|leakage|f1|auc|roc|mrr|ndcg|bleu|rouge|sota|"
    r"fine-tuning|finetuning|zero-shot|few-shot|chain-of-thought|cot|"
    r"prompt|prompts|embedding|embeddings|token|tokens|dataset|datasets|"
    r"pipeline|metric|metrics|split|splits|seed|seeds|attention|encoder|decoder|"
    r"agent|agents|paper|papers|gap|gaps|novelty|venue|cfp|arxiv|pdf|ocr|latex|"
    r"api|json|cli|python|bert|gpt|lora|qlora|rlhf|dpo|ppo|sft|accuracy|"
    r"precision|recall|latency|throughput|dropout|epoch|epochs|hyperparameter|"
    r"overfitting|generalization|hallucination|grounding|retrieval|reranker|"
    r"bm25|mmr|model|models|training|loss|gradient|scorecard|scorecards|doi"
    r")\b",
    re.I,
)

_VI_STOPWORDS = frozenset({
    "của", "và", "là", "các", "những", "trong", "cho", "với", "không", "được",
    "này", "khi", "đã", "để", "nếu", "về", "từ", "trên", "bằng", "nhưng",
    "hoặc", "cần", "hãy", "làm", "dùng", "báo", "cáo", "nghiên", "cứu",
    "đánh", "giá", "kiểm", "tra", "lỗi", "rủi", "ro", "kết", "luận", "chỉ",
    "số", "chứng", "tiền", "lệ", "tài", "liệu", "ngắn", "gọn",
    "hiểu", "tập", "mẫu", "giả", "thuyết", "phương", "pháp",
    "giùm", "giúp", "nhé", "nha", "chính", "xác", "sai", "đúng", "nói",
    "tốt", "rất", "anh", "em", "mình", "bạn", "tôi", "xem", "lại", "quả",
    "nào", "sao", "thế", "vậy", "nhỉ", "chưa", "rồi", "còn", "mà", "thì",
    "cũng", "nên", "phải", "có", "giải", "thích", "tóm", "tắt", "xuất", "tạo",
})
_VI_UNACCENTED_PHRASES = (
    "khong", "duoc", "nhung", "nguon", "bao cao", "kiem tra", "danh gia",
    "ket luan", "bang chung", "rui ro", "nghien cuu", "chi so",
)
_VI_UNACCENTED_DISTINCT = frozenset({
    "xem", "lai", "ket", "qua", "giup", "gium", "toi", "minh", "nay",
    "khong", "duoc", "nhung", "nguon", "kiem", "danh", "rui", "nghien",
    "cuu", "chinh", "xac", "nhe", "nha", "chua", "roi", "cua", "voi",
    "tren", "trong", "nhieu", "tot", "xau", "sua", "loi", "tom", "tat",
    "xuat", "giai", "thich",
})
_VI_UNACCENTED_WORDS = _VI_UNACCENTED_DISTINCT | frozenset({
    "hay", "ban", "anh", "bai", "bao", "cao", "tra", "luan", "bang",
    "chung", "ro", "chi", "so", "sai", "dung", "va", "la", "cho", "ve", "tu",
})
_EN_STOPWORDS = frozenset({
    "the", "is", "are", "was", "were", "and", "for", "with", "this", "that",
    "from", "not", "but", "which", "have", "has", "evaluate", "check", "report",
    "evidence", "flaws", "next", "steps", "verdict", "claim", "claims", "only",
    "between", "without", "before", "after", "under", "based",
})
_FR_CHARS_RE = re.compile(r"[çœæàâéèêëîïôùûüÇŒÆÀÂÉÈÊËÎÏÔÙÛÜ]")
_FR_STOPWORDS = frozenset({
    "le", "la", "les", "des", "est", "avec", "pour", "dans", "une", "sur",
    "par", "pas", "sont", "résultats", "étude", "évaluation", "rapport",
})
_DE_CHARS_RE = re.compile(r"[äöüßÄÖÜ]")
_DE_STOPWORDS = frozenset({
    "der", "die", "das", "und", "ist", "mit", "für", "nicht", "ein", "eine",
    "auf", "von", "zu", "den", "ergebnis", "bericht", "prüfung",
})
_ES_CHARS_RE = re.compile(r"[ñ¿¡áéíóúüÑÁÉÍÓÚÜ]")
_ES_STOPWORDS = frozenset({
    "el", "la", "los", "las", "con", "para", "por", "una", "que", "del",
    "son", "sin", "sobre", "informe", "evaluación", "evidencia",
})

LOCALES: dict[str, dict[str, str]] = {
    "en": {
        "subtitle": "Executive Research Audit",
        "sec_verdict": "Direct Verdict",
        "sec_evidence": "Key Evidence & Numbers",
        "sec_flaws": "Flaws, Risks & Unknowns",
        "sec_next_steps": "Actionable Next Steps",
        "sec_sources": "Verified Sources",
        "sec_metadata": "Scope & Audit Metadata",
        "col_claim": "Claim / Metric",
        "col_value": "Result",
        "col_locator": "Source & Locator",
        "col_status": "Status",
        "lbl_scope": "Scope",
        "lbl_date": "Audit Date",
        "lbl_limits": "Coverage Limits",
        "lbl_basis": "Reading Basis",
        "lbl_lang": "Language",
        "lbl_task": "Audit Type",
        "lbl_parsimony": "Simpler Alternative / Parsimony Check",
        "status_supported": "SUPPORTED CANDIDATE",
        "status_rejected": "REJECTED / NOT A GAP",
        "status_provisional": "PROVISIONAL / UNVERIFIED",
        "status_insufficient": "INSUFFICIENT EVIDENCE",
        "status_pass": "PASS",
        "status_fail": "FAIL",
        "footer_disclaimer": (
            "Bounded to cited sources and verified run logs; passing formatting or "
            "lint checks is not independent scientific proof."
        ),
        "none_reported": "None reported in provided artifacts.",
        "unverified_tag": "unverified",
        "page_label": "Page",
    },
    "vi": {
        "subtitle": "Báo cáo tóm tắt kiểm tra nghiên cứu",
        "sec_verdict": "Kết luận chính",
        "sec_evidence": "Bằng chứng & Số liệu chính",
        "sec_flaws": "Lỗi, Rủi ro & Điểm chưa rõ",
        "sec_next_steps": "Bước tiếp theo cần làm",
        "sec_sources": "Nguồn đối chiếu",
        "sec_metadata": "Phạm vi & Dữ liệu kiểm tra",
        "col_claim": "Nội dung / Chỉ số",
        "col_value": "Giá trị",
        "col_locator": "Nguồn & Vị trí",
        "col_status": "Trạng thái",
        "lbl_scope": "Phạm vi",
        "lbl_date": "Ngày kiểm tra",
        "lbl_limits": "Giới hạn nguồn",
        "lbl_basis": "Mức đọc nguồn",
        "lbl_lang": "Ngôn ngữ",
        "lbl_task": "Loại kiểm tra",
        "lbl_parsimony": "Phương án đơn giản hơn / Kiểm tra tối giản",
        "status_supported": "ĐỦ CĂN CỨ BƯỚC ĐẦU",
        "status_rejected": "BÁC BỎ / KHÔNG PHẢI GAP",
        "status_provisional": "CHƯA ĐỦ BẰNG CHỨNG",
        "status_insufficient": "THIẾU BẰNG CHỨNG",
        "status_pass": "ĐẠT",
        "status_fail": "KHÔNG ĐẠT",
        "footer_disclaimer": (
            "Giới hạn trong nguồn và log đã kiểm; đạt kiểm tra trình bày hoặc từ ngữ "
            "không thay thế thẩm định khoa học độc lập."
        ),
        "none_reported": "Không ghi nhận mục nào trong dữ liệu đầu vào.",
        "unverified_tag": "chưa kiểm chứng",
        "page_label": "Trang",
    },
    "fr": {
        "subtitle": "Rapport exécutif d'audit scientifique",
        "sec_verdict": "Verdict direct",
        "sec_evidence": "Preuves et chiffres clés",
        "sec_flaws": "Défauts, risques et inconnues",
        "sec_next_steps": "Prochaines étapes",
        "sec_sources": "Sources vérifiées",
        "sec_metadata": "Périmètre et métadonnées",
        "col_claim": "Affirmation / Mesure",
        "col_value": "Résultat",
        "col_locator": "Source et emplacement",
        "col_status": "Statut",
        "lbl_scope": "Périmètre",
        "lbl_date": "Date d'audit",
        "lbl_limits": "Limites de couverture",
        "lbl_basis": "Niveau de lecture",
        "lbl_lang": "Langue",
        "lbl_task": "Type d'audit",
        "lbl_parsimony": "Alternative plus simple / Contrôle de parcimonie",
        "status_supported": "CANDIDAT ÉTAYÉ",
        "status_rejected": "REJETÉ / PAS UN ÉCART",
        "status_provisional": "PROVISOIRE / NON VÉRIFIÉ",
        "status_insufficient": "PREUVES INSUFFISANTES",
        "status_pass": "VALIDE",
        "status_fail": "ÉCHEC",
        "footer_disclaimer": (
            "Limité aux sources citées et journaux vérifiés; la validation de forme "
            "ne constitue pas une preuve scientifique."
        ),
        "none_reported": "Aucun élément signalé dans les données fournies.",
        "unverified_tag": "non vérifié",
        "page_label": "Page",
    },
    "de": {
        "subtitle": "Kurzbericht zur Forschungsprüfung",
        "sec_verdict": "Direktes Urteil",
        "sec_evidence": "Wichtige Belege & Kennzahlen",
        "sec_flaws": "Mängel, Risiken & Unbekanntes",
        "sec_next_steps": "Nächste konkrete Schritte",
        "sec_sources": "Geprüfte Quellen",
        "sec_metadata": "Umfang & Prüfmetadaten",
        "col_claim": "Aussage / Kennzahl",
        "col_value": "Ergebnis",
        "col_locator": "Quelle & Fundstelle",
        "col_status": "Status",
        "lbl_scope": "Umfang",
        "lbl_date": "Prüfdatum",
        "lbl_limits": "Abdeckungsgrenzen",
        "lbl_basis": "Lesetiefe",
        "lbl_lang": "Sprache",
        "lbl_task": "Prüftyp",
        "lbl_parsimony": "Einfachere Alternative / Sparsamkeitsprüfung",
        "status_supported": "BELEGTER KANDIDAT",
        "status_rejected": "ABGELEHNT / KEINE LÜCKE",
        "status_provisional": "VORLÄUFIG / UNGEPRÜFT",
        "status_insufficient": "UNZUREICHENDE BELEGE",
        "status_pass": "BESTANDEN",
        "status_fail": "NICHT BESTANDEN",
        "footer_disclaimer": (
            "Beschränkt auf zitierte Quellen und geprüfte Protokolle; formale Prüfung "
            "ersetzt keinen wissenschaftlichen Nachweis."
        ),
        "none_reported": "Keine Einträge in den übergebenen Daten.",
        "unverified_tag": "ungeprüft",
        "page_label": "Seite",
    },
    "es": {
        "subtitle": "Informe ejecutivo de auditoría científica",
        "sec_verdict": "Veredicto directo",
        "sec_evidence": "Evidencia y cifras clave",
        "sec_flaws": "Fallos, riesgos e incógnitas",
        "sec_next_steps": "Siguientes pasos concretos",
        "sec_sources": "Fuentes verificadas",
        "sec_metadata": "Alcance y metadatos",
        "col_claim": "Afirmación / Métrica",
        "col_value": "Resultado",
        "col_locator": "Fuente y ubicación",
        "col_status": "Estado",
        "lbl_scope": "Alcance",
        "lbl_date": "Fecha de auditoría",
        "lbl_limits": "Límites de cobertura",
        "lbl_basis": "Base de lectura",
        "lbl_lang": "Idioma",
        "lbl_task": "Tipo de auditoría",
        "lbl_parsimony": "Alternativa más simple / Control de parsimonia",
        "status_supported": "CANDIDATO RESPALDADO",
        "status_rejected": "RECHAZADO / NO ES BRECHA",
        "status_provisional": "PROVISIONAL / SIN VERIFICAR",
        "status_insufficient": "EVIDENCIA INSUFICIENTE",
        "status_pass": "APROBADO",
        "status_fail": "FALLIDO",
        "footer_disclaimer": (
            "Limitado a las fuentes citadas y registros verificados; aprobar el formato "
            "no equivale a prueba científica."
        ),
        "none_reported": "No se informaron elementos en los datos proporcionados.",
        "unverified_tag": "sin verificar",
        "page_label": "Página",
    },
}


def _nonblank(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _normalize_nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _strip_control_chars(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b\u200c\u200d\ufeff]", "", text)


def _normalize_lang_code(raw_lang: str) -> str:
    cleaned = raw_lang.strip().lower().replace("_", "-")
    if not cleaned or cleaned == "auto":
        return "auto"
    base = cleaned.split("-")[0]
    if not re.fullmatch(r"[a-z]{2,3}", base):
        raise ValueError(f"Unsupported language tag: {raw_lang!r}")
    return base


def _mask_for_lang_detection(text: str) -> str:
    work = _normalize_nfc(text)
    work = re.sub(r"https?://\S+", " ", work)
    work = re.sub(r"\b10\.\d{4,9}/\S+", " ", work)
    work = re.sub(r"\barXiv:\s*\d{4}\.\d{4,5}(?:v\d+)?\b", " ", work, flags=re.I)
    work = re.sub(r"(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+", " ", work)
    work = re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?", " ", work)
    work = _TECH_LOANWORDS_RE.sub(" ", work)
    return re.sub(r"\b\d+(?:[.,:/-]\d+)*%?\b", " ", work)


def _extract_natural_language_strings(payload: Any, *, include_sources: bool = False) -> list[str]:
    texts: list[str] = []
    if not isinstance(payload, dict):
        return texts
    skip_keys = {
        "schema", "format", "lang", "date", "search_date", "checked_at",
        "checked_at_utc", "assessed_at_utc", "id", "status", "disposition",
        "verdict_status", "task_type", "report_type", "url", "official_cfp_url",
        "source_url", "official_acceptance_url", "sha256",
    }
    if not include_sources:
        skip_keys.add("sources")

    def _collect(obj: Any, depth: int = 0) -> None:
        if depth > 4:
            return
        if isinstance(obj, str):
            s = obj.strip()
            if s and not re.fullmatch(r"https?://\S+|10\.\S+|[A-Za-z0-9_.-]+", s):
                texts.append(s)
        elif isinstance(obj, list):
            for item in obj[:25]:
                _collect(item, depth + 1)
        elif isinstance(obj, dict):
            for k, v in obj.items():
                if k not in skip_keys:
                    _collect(v, depth + 1)

    _collect(payload)
    return texts


def _score_language(text: str) -> dict[str, Any]:
    masked = _mask_for_lang_detection(text)
    lowered = masked.lower()
    tokens = re.findall(r"[^\W\d_]+(?:[-'][^\W\d_]+)*", lowered, re.UNICODE)

    vi_unique = len(_VI_UNIQUE_CHARS_RE.findall(masked))
    vi_stops = sum(1 for tok in tokens if tok in _VI_STOPWORDS)
    vi_unacc = sum(1 for ph in _VI_UNACCENTED_PHRASES if re.search(rf"\b{re.escape(ph)}\b", lowered))
    vi_unacc_distinct = sum(1 for tok in tokens if tok in _VI_UNACCENTED_DISTINCT) if vi_unique == 0 else 0
    en_stops = sum(1 for tok in tokens if tok in _EN_STOPWORDS)
    fr_stops = sum(1 for t in tokens if t in _FR_STOPWORDS)
    de_stops = sum(1 for t in tokens if t in _DE_STOPWORDS)
    es_stops = sum(1 for t in tokens if t in _ES_STOPWORDS)

    if vi_unique == 0 and (
        vi_unacc >= 2
        or vi_unacc_distinct >= 3
        or (vi_unacc_distinct >= 2 and en_stops <= 1 and vi_unacc_distinct > en_stops and fr_stops == 0 and de_stops == 0 and es_stops == 0)
    ):
        vi_unacc_score = vi_unacc * 1.5 + max(2.0, vi_unacc_distinct * 1.2)
    else:
        vi_unacc_score = 0.0
    # Guard against isolated VI proper-name diacritics inside English text when zero VI stopwords exist.
    vi_diac_weight = 4.0 if (vi_stops >= 1 or en_stops == 0 or (vi_unique >= 4 and en_stops < 3)) else (0.25 if en_stops >= 3 else 0.5)
    vi_score = vi_unique * vi_diac_weight + vi_stops * 2.0 + vi_unacc_score
    en_score = en_stops * 1.5

    non_vi_tokens = [t for t in tokens if t not in _VI_STOPWORDS]
    non_vi_text = " ".join(non_vi_tokens)
    fr_chars = len(_FR_CHARS_RE.findall(non_vi_text))
    de_chars = len(_DE_CHARS_RE.findall(non_vi_text))
    es_chars = len(_ES_CHARS_RE.findall(non_vi_text))

    fr_score = (0.0 if (vi_stops > fr_stops and fr_stops == 0) else fr_chars * 1.5) + fr_stops * 2.0
    de_score = de_chars * 2.0 + de_stops * 2.0
    es_score = (0.0 if (vi_stops > es_stops and es_stops == 0) else es_chars * 1.2) + es_stops * 2.0

    if vi_unique > 0 or vi_stops >= 2:
        fr_score = max(0.0, fr_score - vi_unique - vi_stops)
        es_score = max(0.0, es_score - vi_unique - vi_stops)

    signals: list[str] = []
    if vi_unique:
        signals.append(f"vi_diacritics:{vi_unique}")
    if vi_stops:
        signals.append(f"vi_stopwords:{vi_stops}")
    if vi_unacc_score > 0 and vi_unacc_distinct >= 2:
        signals.append(f"vi_unaccented:{vi_unacc_distinct}")
    if en_stops:
        signals.append(f"en_stopwords:{en_stops}")
    if fr_score >= 2.0:
        signals.append(f"fr_signals:{fr_chars + fr_stops}")
    if de_score >= 2.0:
        signals.append(f"de_signals:{de_chars + de_stops}")
    if es_score >= 2.0:
        signals.append(f"es_signals:{es_chars + es_stops}")

    if vi_score >= 3.0 and vi_score >= 0.4 * en_score:
        chosen = "vi"
        conf = min(0.99, round(0.65 + 0.34 * (vi_score / max(vi_score + en_score, 1.0)), 2))
    else:
        cands = {"en": en_score, "fr": fr_score, "de": de_score, "es": es_score, "vi": vi_score}
        best_lang, best_score = max(cands.items(), key=lambda kv: kv[1])
        if best_score >= 2.0:
            chosen = best_lang
            conf = min(0.98, round(0.55 + 0.43 * (best_score / (sum(cands.values()) or 1.0)), 2))
        else:
            chosen, conf = "en", 0.5

    return {"lang": chosen, "confidence": conf, "signals": signals or ["default_en"]}


def detect_language(
    text: str = "",
    payload: dict[str, Any] | None = None,
    requested: str = "auto",
) -> dict[str, Any]:
    """Detect user report language from explicit override, `--input-text`, or JSON fields."""
    norm_req = _normalize_lang_code(requested or "auto")
    if norm_req != "auto":
        return {"lang": norm_req, "source": "explicit", "confidence": 1.0, "signals": ["explicit_flag"]}

    if _nonblank(text):
        res = _score_language(text)
        res["source"] = "input_text"
        return res

    if isinstance(payload, dict):
        if _nonblank(payload.get("lang")):
            plang = _normalize_lang_code(payload["lang"])
            if plang != "auto":
                return {"lang": plang, "source": "payload_lang", "confidence": 0.95, "signals": ["payload_lang_field"]}
        extracted = " ".join(_extract_natural_language_strings(payload, include_sources=False))
        if _nonblank(extracted):
            res = _score_language(extracted)
            if res["signals"] != ["default_en"] or re.search(r"[A-Za-z]{2,}", _mask_for_lang_detection(extracted)):
                res["source"] = "payload_text"
                return res
        fallback = " ".join(_extract_natural_language_strings(payload, include_sources=True))
        if _nonblank(fallback):
            res = _score_language(fallback)
            res["source"] = "payload_text"
            return res

    return {"lang": "en", "source": "default", "confidence": 0.5, "signals": ["default_en"]}


# ---------------------------------------------------------------------------
# Multi-Schema Input Normalizer
# ---------------------------------------------------------------------------


def _first_nonblank(*values: Any) -> str:
    for v in values:
        if _nonblank(v):
            return str(v).strip()
    return ""


def _coerce_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return [] if value is None else [value]


def _normalize_status_token(raw: str) -> str:
    low = raw.strip().lower().replace(" ", "_")
    if low in {"supported", "supported_candidate", "verified"}:
        return "supported"
    if low in {"pass", "passed", "ok"}:
        return "pass"
    if low in {"rejected", "not_a_gap"}:
        return "rejected"
    if low in {"fail", "failed", "engineering_bug_detected"}:
        return "fail"
    if low in {"insufficient_evidence", "abstain"}:
        return "insufficient_evidence"
    return "provisional"


def _status_badge_label(status: str, loc: dict[str, str], explicit_label: str = "") -> str:
    if _nonblank(explicit_label):
        return explicit_label.strip()
    norm = _normalize_status_token(status)
    return {
        "supported": loc["status_supported"],
        "rejected": loc["status_rejected"],
        "provisional": loc["status_provisional"],
        "insufficient_evidence": loc["status_insufficient"],
        "pass": loc["status_pass"],
        "fail": loc["status_fail"],
    }.get(norm, status.upper() if status else loc["status_provisional"])


def _extract_ref_list(
    item: dict[str, Any],
    keys: tuple[str, ...] = ("source_refs", "source_ref", "evidence_ids"),
) -> list[str]:
    refs: list[str] = []
    for key in keys:
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            s = val.strip()
            if s not in refs:
                refs.append(s)
        elif isinstance(val, list):
            for x in val:
                if x is not None and _nonblank(str(x)):
                    s = str(x).strip()
                    if s not in refs:
                        refs.append(s)
    return refs


def _has_grounding(item: dict[str, Any], grounded_ref_ids: set[str] | None = None) -> bool:
    for key in ("locator", "locators", "evidence", "source_url", "url"):
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            return True
        if isinstance(val, list) and any(_nonblank(str(x)) for x in val if x is not None):
            return True
    refs = _extract_ref_list(item)
    if not refs or grounded_ref_ids is None:
        return False
    return all(r in grounded_ref_ids for r in refs)


def _parsimony_verdict_fields(payload: dict[str, Any]) -> dict[str, Any]:
    p_note, p_own_grounded, p_in_verdict, p_refs = _extract_parsimony_info(payload)
    return {
        "parsimony_check": p_note,
        "parsimony_grounded": p_own_grounded,
        "parsimony_in_verdict": p_in_verdict,
        "parsimony_refs": p_refs,
    }


def _format_parsimony_value(raw: Any) -> str:
    if isinstance(raw, str):
        return raw.strip()
    if not isinstance(raw, dict):
        return ""
    bits: list[str] = []
    alt = _first_nonblank(raw.get("simplest_alternative"), raw.get("alternative"), raw.get("summary"))
    if alt:
        bits.append(alt.rstrip("."))
    infl = _first_nonblank(raw.get("problem_inflation_check"), raw.get("inflation_check"))
    if infl:
        bits.append(infl.rstrip("."))
    extra = _first_nonblank(raw.get("rationale"), raw.get("reason"), raw.get("explanation"), raw.get("justification"), raw.get("notes"))
    if extra:
        bits.append(extra.rstrip("."))
    verd = _first_nonblank(raw.get("verdict"), raw.get("status"))
    if verd and verd.lower() not in (alt + " " + infl + " " + extra).lower():
        bits.append(f"[{verd}]")
    out = "; ".join(bits).strip()
    return (out + ".") if out and not out.endswith((".", "]", "!", "?")) else out


def _extract_parsimony_info(payload: dict[str, Any]) -> tuple[str, bool, bool, list[str]]:
    containers: list[tuple[dict[str, Any], bool]] = [(payload, False)]
    if isinstance(payload.get("verdict"), dict):
        containers.append((payload["verdict"], True))
    if isinstance(payload.get("metadata"), dict):
        containers.append((payload["metadata"], False))
    cands = payload.get("candidates") or payload.get("surviving_gaps")
    if isinstance(cands, list) and cands and isinstance(cands[0], dict):
        containers.append((cands[0], False))

    for box, in_verdict in containers:
        for key in ("parsimony_check", "simplest_alternative"):
            val = box.get(key)
            formatted = _format_parsimony_value(val)
            if formatted:
                own_grounded = False
                own_refs: list[str] = []
                if isinstance(val, dict):
                    own_grounded = any(
                        (isinstance(val.get(k), str) and bool(val[k].strip()))
                        or (isinstance(val.get(k), list) and any(_nonblank(str(x)) for x in val[k] if x is not None))
                        for k in ("locator", "locators", "source_url", "url", "evidence")
                    )
                    for rk in ("evidence_refs", "source_refs", "evidence_ids", "source_ref"):
                        rv = val.get(rk)
                        if isinstance(rv, str) and rv.strip():
                            s = rv.strip()
                            if s not in own_refs:
                                own_refs.append(s)
                        elif isinstance(rv, list):
                            for r in rv:
                                if r is not None and _nonblank(str(r)):
                                    s = str(r).strip()
                                    if s not in own_refs:
                                        own_refs.append(s)
                return formatted, own_grounded, in_verdict, own_refs
    return "", False, False, []


def _extract_parsimony_note(payload: dict[str, Any]) -> str:
    return _extract_parsimony_info(payload)[0]


def _normalize_evidence_row(item: Any, idx: int) -> dict[str, Any]:
    if isinstance(item, str):
        return {"id": f"K{idx}", "claim": item.strip(), "value": "", "status": "verified", "evidence": "", "source_refs": [], "locator": "", "source_url": ""}
    if not isinstance(item, dict):
        return {"id": f"K{idx}", "claim": str(item), "value": "", "status": "unverified", "evidence": "", "source_refs": [], "locator": "", "source_url": ""}

    refs = item.get("source_refs") or item.get("evidence_ids") or []
    if isinstance(refs, str):
        refs = [refs] if refs.strip() else []
    elif isinstance(refs, list):
        refs = [str(r).strip() for r in refs if _nonblank(str(r))]
    else:
        refs = []
    for extra in ("source_ref", "source_id"):
        if _nonblank(item.get(extra)) and str(item[extra]).strip() not in refs:
            refs.append(str(item[extra]).strip())

    loc = _first_nonblank(item.get("locator"), item.get("note"))
    if not loc and isinstance(item.get("locators"), list) and item["locators"]:
        loc = "; ".join(str(x).strip() for x in item["locators"] if _nonblank(str(x)))

    return {
        "id": _first_nonblank(item.get("id")) or f"K{idx}",
        "claim": _first_nonblank(item.get("claim"), item.get("label"), item.get("name"), item.get("metric"), item.get("title")),
        "value": str(item.get("value", item.get("result", item.get("score", "")))).strip(),
        "status": _first_nonblank(item.get("status"), item.get("role"), item.get("access"))
        or ("verified" if (loc or refs or _nonblank(item.get("evidence")) or _nonblank(item.get("source_url"))) else "unverified"),
        "evidence": _first_nonblank(item.get("evidence"), item.get("citation")),
        "source_refs": refs,
        "locator": loc,
        "source_url": _first_nonblank(item.get("source_url"), item.get("url")),
    }


def _normalize_flaw_row(item: Any, idx: int) -> dict[str, Any]:
    if isinstance(item, str):
        return {"id": f"R{idx}", "severity": "medium", "summary": item.strip(), "source_refs": [], "locator": ""}
    if not isinstance(item, dict):
        return {"id": f"R{idx}", "severity": "medium", "summary": str(item), "source_refs": [], "locator": ""}
    return {
        "id": _first_nonblank(item.get("id")) or f"R{idx}",
        "severity": _first_nonblank(item.get("severity"), item.get("level")) or "medium",
        "summary": _first_nonblank(item.get("summary"), item.get("message"), item.get("description"), item.get("reason"), item.get("claim")),
        "source_refs": _extract_ref_list(item),
        "locator": _first_nonblank(item.get("locator"), item.get("source_url"), item.get("file")),
    }


def _normalize_next_step_row(item: Any, idx: int) -> dict[str, Any]:
    if isinstance(item, str):
        return {"step": idx, "action": item.strip(), "target": "", "locator": ""}
    if not isinstance(item, dict):
        return {"step": idx, "action": str(item), "target": "", "locator": ""}
    return {
        "step": item.get("step", idx),
        "action": _first_nonblank(item.get("action"), item.get("summary"), item.get("description"), item.get("text")),
        "target": _first_nonblank(item.get("target"), item.get("criterion"), item.get("artifact")),
        "locator": _first_nonblank(item.get("locator"), item.get("url")),
    }


def _normalize_canonical(payload: dict[str, Any], *, truncate: bool = True) -> dict[str, Any]:
    raw_verdict = payload.get("verdict") if "verdict" in payload else payload.get("conclusion")
    v_status = _first_nonblank(payload.get("verdict_status"))
    v_label, v_summary, v_conf, v_refs = "", "", "", []

    if isinstance(raw_verdict, dict):
        v_status = _first_nonblank(raw_verdict.get("status"), v_status) or "provisional"
        v_label = _first_nonblank(raw_verdict.get("label"))
        v_summary = _first_nonblank(raw_verdict.get("summary"), raw_verdict.get("text"), raw_verdict.get("conclusion"))
        v_conf = _first_nonblank(raw_verdict.get("confidence"))
        if isinstance(raw_verdict.get("evidence_refs") or raw_verdict.get("source_refs"), list):
            v_refs = [str(x).strip() for x in (raw_verdict.get("evidence_refs") or raw_verdict.get("source_refs")) if _nonblank(str(x))]
    elif isinstance(raw_verdict, str):
        v_summary = raw_verdict.strip()
    v_status = v_status or "provisional"

    raw_ev = payload.get("key_evidence") if payload.get("key_evidence") is not None else payload.get("evidence")
    ev_rows = [_normalize_evidence_row(item, i) for i, item in enumerate(_coerce_list(raw_ev), start=1)]
    if isinstance(payload.get("metrics"), list):
        ev_rows.extend(_normalize_evidence_row(m, len(ev_rows) + i) for i, m in enumerate(payload["metrics"], start=1))

    raw_flaws = payload.get("flaws_and_risks")
    if raw_flaws is None:
        raw_flaws = payload.get("risks") if payload.get("risks") is not None else payload.get("flaws")
    flaw_rows = [_normalize_flaw_row(item, i) for i, item in enumerate(_coerce_list(raw_flaws), start=1)]

    raw_steps = payload.get("next_steps")
    if raw_steps is None:
        raw_steps = payload.get("recommendations") if payload.get("recommendations") is not None else payload.get("actions")
    step_rows = [_normalize_next_step_row(item, i) for i, item in enumerate(_coerce_list(raw_steps), start=1)]

    meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    sources: list[dict[str, str]] = []
    for i, s in enumerate(payload.get("sources") or [], start=1):
        if isinstance(s, dict):
            sources.append({
                "id": _first_nonblank(s.get("id")) or f"S{i}",
                "title": _first_nonblank(s.get("title"), s.get("citation"), s.get("name"), s.get("id")),
                "locator": _first_nonblank(s.get("locator"), s.get("url")),
                "url": _first_nonblank(s.get("url"), s.get("source_url")),
            })
        elif _nonblank(str(s)):
            sources.append({"id": f"S{i}", "title": str(s).strip(), "locator": "", "url": ""})

    return {
        "schema": SCHEMA_VERSION,
        "report_type": _first_nonblank(payload.get("report_type"), payload.get("task_type")) or "general",
        "lang": _first_nonblank(payload.get("lang")) or "auto",
        "title": _first_nonblank(payload.get("title")) or "Research Audit Summary",
        "verdict": {
            "status": _normalize_status_token(v_status),
            "label": v_label,
            "summary": v_summary,
            "confidence": v_conf,
            "evidence_refs": v_refs,
            **_parsimony_verdict_fields(payload),
        },
        "key_evidence": ev_rows[:12] if truncate else ev_rows,
        "flaws_and_risks": flaw_rows[:10] if truncate else flaw_rows,
        "next_steps": step_rows[:8] if truncate else step_rows,
        "metadata": {
            "scope": _first_nonblank(meta.get("scope"), payload.get("scope")),
            "search_date": _first_nonblank(meta.get("search_date"), payload.get("date"), payload.get("search_date")) or _dt.date.today().isoformat(),
            "coverage_limits": _first_nonblank(meta.get("coverage_limits"), payload.get("coverage_limits")),
            "reading_basis": _first_nonblank(meta.get("reading_basis"), payload.get("reading_basis")),
            "sources_checked": meta.get("sources_checked", len(sources)),
        },
        "sources": sources[:12] if truncate else sources,
    }


def _normalize_gap_record(payload: dict[str, Any], *, truncate: bool = True) -> dict[str, Any]:
    candidates = payload.get("candidates") or payload.get("surviving_gaps") or []
    rejected = payload.get("rejected_gaps") or []
    evidence_list = payload.get("evidence") or []
    ev_by_id = {e.get("id"): e for e in evidence_list if isinstance(e, dict) and e.get("id")}
    closest = payload.get("closest_works") or []

    primary = candidates[0] if candidates and isinstance(candidates[0], dict) else (
        rejected[0] if rejected and isinstance(rejected[0], dict) else {}
    )
    v_str = payload.get("verdict") if isinstance(payload.get("verdict"), str) else ""
    disp = _first_nonblank(primary.get("disposition"), primary.get("status"), v_str) or ("rejected" if (rejected and not candidates) else "provisional")
    claim = _first_nonblank(primary.get("claim"), primary.get("title"), payload.get("scope"))
    rationale = _first_nonblank(primary.get("rationale"), primary.get("reason"))
    summary = f"{claim}. {rationale}".strip(". ")
    summary = f"{summary}." if summary else "Gap audit record normalized."

    ev_src = evidence_list[:8] if truncate else evidence_list
    key_ev = [
        {
            "id": _first_nonblank(ev.get("id")) or f"E{i}",
            "claim": _first_nonblank(ev.get("claim")),
            "value": _first_nonblank(ev.get("role"), ev.get("access")),
            "status": _first_nonblank(ev.get("access")) or "verified",
            "evidence": _first_nonblank(ev.get("source_id"), ev.get("study_id")),
            "source_refs": [x for x in (ev.get("source_id"), ev.get("study_id")) if _nonblank(x)],
            "locator": _first_nonblank(ev.get("locator")),
            "source_url": "",
        }
        for i, ev in enumerate(ev_src, start=1) if isinstance(ev, dict)
    ]
    cw_src = closest[:4] if truncate else closest
    for i, cw in enumerate(cw_src, start=1):
        if isinstance(cw, dict):
            cw_refs = [str(x) for x in (cw.get("evidence_ids") or []) if _nonblank(str(x))]
            locs = [ev_by_id[r].get("locator", "") for r in cw_refs if r in ev_by_id]
            key_ev.append({
                "id": _first_nonblank(cw.get("id")) or f"W{i}",
                "claim": _first_nonblank(cw.get("difference"), cw.get("relation")),
                "value": _first_nonblank(cw.get("relation")),
                "status": _first_nonblank(cw.get("access")) or "provisional",
                "evidence": _first_nonblank(cw.get("source_id")),
                "source_refs": [x for x in [cw.get("source_id"), *cw_refs] if _nonblank(x)],
                "locator": "; ".join(p for p in locs if p) or _first_nonblank(cw.get("source_id")),
                "source_url": "",
            })

    rej_src = rejected[:5] if truncate else rejected
    flaws = [
        {
            "id": _first_nonblank(rg.get("id")) or f"R{i}",
            "severity": "high",
            "summary": _first_nonblank(rg.get("reason"), rg.get("claim"), rg.get("drop_code")),
            "source_refs": [],
            "locator": _first_nonblank(rg.get("drop_code"), "gap_pipeline"),
        }
        for i, rg in enumerate(rej_src, start=1) if isinstance(rg, dict)
    ]
    if _nonblank(primary.get("engineering_status")) and primary["engineering_status"] not in {"clean", "passed", "not_applicable"}:
        flaws.append({"id": "R-ENG", "severity": "high", "summary": f"Engineering status: {primary['engineering_status']}", "source_refs": [], "locator": "engineering_status"})
    if _nonblank(payload.get("coverage_limits")):
        flaws.append({"id": "R-COV", "severity": "medium", "summary": str(payload["coverage_limits"]).strip(), "source_refs": [], "locator": "coverage_limits"})

    steps = []
    if _nonblank(primary.get("answer_path")):
        steps.append({"step": 1, "action": str(primary["answer_path"]).strip(), "target": _first_nonblank(primary.get("consequence")), "locator": ""})
    if _nonblank(payload.get("next_check")):
        steps.append({"step": len(steps) + 1, "action": str(payload["next_check"]).strip(), "target": "", "locator": ""})

    ev_refs = [str(x) for x in (primary.get("support_evidence_ids") or []) if _nonblank(str(x))]
    if not ev_refs:
        ev_refs = [e["id"] for e in key_ev[:2] if _has_grounding(e)] or [f["id"] for f in flaws[:2] if _has_grounding(f)]

    return {
        "schema": SCHEMA_VERSION,
        "report_type": "gap_audit",
        "lang": _first_nonblank(payload.get("lang")) or "auto",
        "title": f"Gap Audit: {_first_nonblank(payload.get('scope'), claim)[:70]}",
        "verdict": {
            "status": _normalize_status_token(disp),
            "label": "",
            "summary": summary,
            "confidence": "bounded",
            "evidence_refs": ev_refs,
            **_parsimony_verdict_fields(payload),
        },
        "key_evidence": key_ev[:10] if truncate else key_ev,
        "flaws_and_risks": flaws[:8] if truncate else flaws,
        "next_steps": steps[:6] if truncate else steps,
        "metadata": {
            "scope": _first_nonblank(payload.get("scope")),
            "search_date": _first_nonblank(payload.get("search_date")) or _dt.date.today().isoformat(),
            "coverage_limits": _first_nonblank(payload.get("coverage_limits")),
            "reading_basis": _first_nonblank(primary.get("reading_basis")) or "mixed",
            "sources_checked": len(payload.get("queries") or []),
        },
        "sources": [
            {"id": _first_nonblank(ev.get("source_id"), ev.get("id")) or f"S{i}", "title": _first_nonblank(ev.get("source_id"), ev.get("study_id")), "locator": _first_nonblank(ev.get("locator")), "url": ""}
            for i, ev in enumerate(evidence_list[:10], start=1) if isinstance(ev, dict)
        ],
    }


def _normalize_venue_novelty(payload: dict[str, Any], *, truncate: bool = True) -> dict[str, Any]:
    venue = payload.get("venue") if isinstance(payload.get("venue"), dict) else {}
    target = payload.get("target") if isinstance(payload.get("target"), dict) else {}
    panel = payload.get("accepted_panel") if isinstance(payload.get("accepted_panel"), list) else []
    fit_axes = payload.get("fit_axes") if isinstance(payload.get("fit_axes"), list) else []
    constraints = payload.get("hard_constraints") if isinstance(payload.get("hard_constraints"), list) else []

    v_name = _first_nonblank(venue.get("name"), payload.get("title")) or "Venue & Novelty Assessment"
    title = f"{v_name} ({venue['edition']})".strip() if _nonblank(venue.get("edition")) else v_name

    t_score, t_low, t_high = target.get("score"), target.get("low"), target.get("high")
    p_scores = [p.get("score") for p in panel if isinstance(p, dict) and isinstance(p.get("score"), (int, float))]
    p_med = statistics.median(p_scores) if p_scores else None
    fit_total = sum(a.get("score", 0) for a in fit_axes if isinstance(a, dict) and isinstance(a.get("score"), (int, float)))

    parts: list[str] = []
    if _nonblank(target.get("claim")):
        parts.append(str(target["claim"]).strip().rstrip(".") + ".")
    if t_score is not None:
        band = f" (range {t_low}--{t_high})" if (t_low is not None and t_high is not None) else ""
        med_txt = f" vs panel median {p_med}/10" if p_med is not None else ""
        parts.append(f"Target novelty scores {t_score}/10{band}{med_txt} [{_first_nonblank(target.get('closest_work_locator'), target.get('closest_work_id'), 'target')}].")
    if fit_axes:
        parts.append(f"Venue fit totals {fit_total}/10 [{_first_nonblank(venue.get('official_cfp_url'), 'fit_axes')}].")

    key_ev: list[dict[str, Any]] = []
    if t_score is not None:
        key_ev.append({
            "id": _first_nonblank(target.get("id")) or "TARGET",
            "claim": _first_nonblank(target.get("score_reason"), target.get("contribution_delta"), "Target novelty score"),
            "value": f"{t_score}/10",
            "status": _first_nonblank(target.get("reading_basis")) or "verified",
            "evidence": _first_nonblank(target.get("closest_work_id")),
            "source_refs": [x for x in [target.get("closest_work_id")] if _nonblank(x)],
            "locator": _first_nonblank(target.get("closest_work_locator"), target.get("search_manifest")),
            "source_url": _first_nonblank(venue.get("official_cfp_url")),
        })
    if p_scores:
        key_ev.append({
            "id": "PANEL",
            "claim": f"Accepted panel benchmark ({len(p_scores)} papers)",
            "value": f"median {p_med}/10 ({min(p_scores)}--{max(p_scores)})",
            "status": "verified",
            "evidence": _first_nonblank((payload.get("panel_selection") or {}).get("search_manifest"), "accepted_panel"),
            "source_refs": ["accepted_panel"],
            "locator": _first_nonblank((payload.get("panel_selection") or {}).get("date_window"), "accepted_panel"),
            "source_url": _first_nonblank(panel[0].get("official_acceptance_url")) if panel and isinstance(panel[0], dict) else "",
        })
    for idx, ax in enumerate(fit_axes[:5] if truncate else fit_axes, start=1):
        if isinstance(ax, dict):
            key_ev.append({
                "id": f"FIT{idx}",
                "claim": _first_nonblank(ax.get("reason"), ax.get("name")),
                "value": f"{ax.get('score', 0)}/2",
                "status": "verified",
                "evidence": _first_nonblank(ax.get("name")),
                "source_refs": [],
                "locator": _first_nonblank(ax.get("locator"), ax.get("source_url")),
                "source_url": _first_nonblank(ax.get("source_url")),
            })

    flaws: list[dict[str, Any]] = []
    if len(panel) < 5:
        flaws.append({"id": "R-PANEL", "severity": "high", "summary": f"Accepted panel has only {len(panel)} papers (minimum 5 recommended).", "source_refs": [], "locator": "accepted_panel"})
    for idx, c in enumerate(constraints, start=1):
        if isinstance(c, dict) and str(c.get("status", "")).lower() not in {"met", "pass", "verified"}:
            flaws.append({"id": f"R-C{idx}", "severity": "high", "summary": f"Constraint {c.get('name', idx)}: {c.get('status')} ({c.get('reason', '')})", "source_refs": [], "locator": _first_nonblank(c.get("source_url"), "hard_constraints")})
    bias_note = (payload.get("panel_selection") or {}).get("selection_bias") if isinstance(payload.get("panel_selection"), dict) else ""
    if _nonblank(bias_note):
        flaws.append({"id": "R-BIAS", "severity": "medium", "summary": str(bias_note).strip(), "source_refs": [], "locator": "panel_selection.selection_bias"})

    any_failed = any(str(c.get("status", "")).lower() in {"failed", "unmet", "fail"} for c in constraints if isinstance(c, dict))
    ev_refs = [e["id"] for e in key_ev if _has_grounding(e)][:2] or [f["id"] for f in flaws if _has_grounding(f)][:2] or (["CFP"] if _nonblank(venue.get("official_cfp_url")) else [])
    return {
        "schema": SCHEMA_VERSION,
        "report_type": "novelty_scoring",
        "lang": _first_nonblank(payload.get("lang")) or "auto",
        "title": title,
        "verdict": {
            "status": "fail" if any_failed else ("supported" if len(panel) >= 5 else "provisional"),
            "label": "",
            "summary": " ".join(parts) or "Venue novelty profile normalized.",
            "confidence": "bounded",
            "evidence_refs": ev_refs,
            **_parsimony_verdict_fields(payload),
        },
        "key_evidence": key_ev[:10] if truncate else key_ev,
        "flaws_and_risks": flaws[:8] if truncate else flaws,
        "next_steps": [{"step": 1, "action": "Verify official CFP deadline, fees, and closest-work delta before submission.", "target": _first_nonblank(venue.get("official_cfp_url"), "CFP snapshot"), "locator": _first_nonblank(venue.get("official_cfp_url"))}],
        "metadata": {
            "scope": _first_nonblank(target.get("assessment_boundary"), venue.get("track")),
            "search_date": _first_nonblank(venue.get("checked_at_utc"), target.get("assessed_at_utc"))[:10] or _dt.date.today().isoformat(),
            "coverage_limits": _first_nonblank(bias_note),
            "reading_basis": _first_nonblank(target.get("reading_basis")) or "full_text",
            "sources_checked": len(panel) + 1,
        },
        "sources": [{"id": "CFP", "title": f"{v_name} CFP", "locator": _first_nonblank(venue.get("official_cfp_url")), "url": _first_nonblank(venue.get("official_cfp_url"))}] if _nonblank(venue.get("official_cfp_url")) else [],
    }


def _normalize_search_output(payload: dict[str, Any], *, truncate: bool = True) -> dict[str, Any]:
    results = payload.get("results") or payload.get("combined_results") or payload.get("source_records") or payload.get("top_results") or []
    seeds = payload.get("known_seed_checks") or []
    missed_statuses = {"not_retrieved_in_campaign", "not_retrieved_in_this_run", "source_unavailable", "all_sources_unavailable", "source_not_queried", "missed", "failed"}
    rec = sum(1 for s in seeds if isinstance(s, dict) and (s.get("retrieved") is True or str(s.get("status", "")).lower() == "retrieved"))
    missed = [s for s in seeds if isinstance(s, dict) and (s.get("retrieved") is False or str(s.get("status", "")).lower() in missed_statuses)]
    qtxt = _first_nonblank(payload.get("question"), payload.get("query")) or ", ".join(
        _first_nonblank(q.get("query")) if isinstance(q, dict) else str(q)
        for q in (payload.get("queries") or payload.get("query_runs") or [])[:3]
    )
    summary = f"Precedent search returned {len(results)} records" + (f" ({rec}/{len(seeds)} positive-control seeds recalled)" if seeds else "") + " [search_results]."
    key_ev = []
    for idx, r in enumerate(results[:8], start=1):
        if isinstance(r, dict):
            loc = _first_nonblank(r.get("doi"), r.get("arxiv_id"), r.get("openalex_id"), r.get("source_id"), r.get("url"), r.get("dedup_key")) or f"result_{idx}"
            ev_srcs = r.get("sources_seen") or r.get("discovered_by") or ([r["source"]] if _nonblank(r.get("source")) else [])
            key_ev.append({"id": f"P{idx}", "claim": _first_nonblank(r.get("title"), r.get("dedup_key"), r.get("source_id")) or f"Paper {idx}", "value": str(r.get("year") or ""), "status": "retracted" if r.get("retraction_status") == "retracted" else "verified", "evidence": ", ".join(str(x) for x in ev_srcs if _nonblank(str(x))), "source_refs": [loc], "locator": loc, "source_url": _first_nonblank(r.get("url"))})
    flaws: list[dict[str, Any]] = []
    if missed:
        flaws.append({"id": "R-SEED", "severity": "critical", "summary": f"Missed {len(missed)} positive-control seed papers during search.", "source_refs": [], "locator": "known_seed_checks"})
    partial_runs = (payload.get("coverage") or {}).get("failed_or_partial_source_runs") if isinstance(payload.get("coverage"), dict) else None
    if isinstance(partial_runs, list) and partial_runs:
        flaws.append({"id": "R-PARTIAL", "severity": "medium", "summary": f"{len(partial_runs)} source query runs were bounded_partial or failed.", "source_refs": [], "locator": "coverage.failed_or_partial_source_runs"})
    ev_refs = [e["id"] for e in key_ev[:2] if _has_grounding(e)] or [f["id"] for f in flaws[:2] if _has_grounding(f)]
    return {
        "schema": SCHEMA_VERSION, "report_type": "precedent_search", "lang": _first_nonblank(payload.get("lang")) or "auto",
        "title": f"Precedent Search: {qtxt[:60]}" if qtxt else "Precedent Search Summary",
        "verdict": {"status": "fail" if missed else ("supported" if results else "insufficient_evidence"), "label": "", "summary": summary, "confidence": "bounded", "evidence_refs": ev_refs, **_parsimony_verdict_fields(payload)},
        "key_evidence": key_ev, "flaws_and_risks": flaws,
        "next_steps": [{"step": 1, "action": "Inspect full text of top closest works before declaring any gap.", "target": "top search hits", "locator": ""}],
        "metadata": {"scope": qtxt, "search_date": _first_nonblank(payload.get("checked_at_utc"))[:10] or _dt.date.today().isoformat(), "coverage_limits": _first_nonblank(payload.get("warning")), "reading_basis": "abstract_only", "sources_checked": len(results)},
        "sources": [],
    }


def _format_scorecard_locators(locs: Any) -> str:
    if isinstance(locs, list):
        return "; ".join(str(x).strip() for x in locs if _nonblank(str(x)))
    if isinstance(locs, dict):
        parts: list[str] = []
        for k, v in locs.items():
            if isinstance(v, list):
                txt = ", ".join(str(x).strip() for x in v if _nonblank(str(x)))
            else:
                txt = str(v).strip() if v is not None else ""
            if txt:
                parts.append(f"{k}: {txt}")
        return "; ".join(parts)[:220]
    return _first_nonblank(locs)


def _normalize_scorecards(payload: dict[str, Any], *, truncate: bool = True) -> dict[str, Any]:
    profiles = payload.get("profiles") or []
    key_ev, flaws = [], []
    for idx, p in enumerate(profiles[:8] if truncate else profiles, start=1):
        if not isinstance(p, dict):
            continue
        nov = (p.get("ratings") or {}).get("novelty", "?") if isinstance(p.get("ratings"), dict) else "?"
        cw = p.get("closest_work")
        cw_str = ", ".join(str(x).strip() for x in cw if _nonblank(str(x))) if isinstance(cw, list) else _first_nonblank(cw)
        loc_str = _format_scorecard_locators(p.get("evidence_locators"))
        key_ev.append({"id": _first_nonblank(p.get("id")) or f"SC{idx}", "claim": _first_nonblank(p.get("title"), cw_str, p.get("id")) or f"Profile {idx}", "value": f"novelty {nov}/10", "status": _first_nonblank(p.get("reading_basis")) or "provisional", "evidence": cw_str, "source_refs": [loc_str] if loc_str else [], "locator": loc_str or "scorecards", "source_url": ""})
        if p.get("reading_basis") != "full_text":
            flaws.append({"id": f"R-RB{idx}", "severity": "high", "summary": f"Profile {p.get('id', idx)} reading_basis is {p.get('reading_basis')}, not full_text.", "source_refs": [], "locator": "profiles.reading_basis"})
    ev_refs = [e["id"] for e in key_ev[:2] if _has_grounding(e)] or [f["id"] for f in flaws[:2] if _has_grounding(f)]
    return {
        "schema": SCHEMA_VERSION, "report_type": "novelty_scoring", "lang": _first_nonblank(payload.get("lang")) or "auto", "title": "Scorecard Comparison Summary",
        "verdict": {"status": "provisional" if flaws else "supported", "label": "", "summary": f"Compared {len(profiles)} paper scorecards on 10-point axes [scorecards].", "confidence": "bounded", "evidence_refs": ev_refs, **_parsimony_verdict_fields(payload)},
        "key_evidence": key_ev, "flaws_and_risks": flaws,
        "next_steps": [{"step": 1, "action": "Verify every /10 score anchor against full-text locators.", "target": "evidence_locators", "locator": ""}],
        "metadata": {"scope": f"{len(profiles)} scorecards", "search_date": _dt.date.today().isoformat(), "coverage_limits": "Bounded to supplied scorecards.", "reading_basis": "mixed" if flaws else "full_text", "sources_checked": len(profiles)},
        "sources": [],
    }


def _normalize_scorecard_rankings(payload: dict[str, Any], *, truncate: bool = True) -> dict[str, Any]:
    rankings = payload.get("rankings") or []
    sens = _first_nonblank(payload.get("ranking_sensitivity")) or "unknown"
    key_ev: list[dict[str, Any]] = []
    for idx, r in enumerate(rankings[:8] if truncate else rankings, start=1):
        if isinstance(r, dict):
            scen = r.get("scenario", idx)
            ordered = r.get("ordered") or []
            top = ", ".join(f"{o.get('id', '?')} ({o.get('weighted_unrounded', '?')})" for o in ordered[:4] if isinstance(o, dict))
            key_ev.append({"id": f"SCEN{scen}", "claim": f"Weight scenario {scen} ranking", "value": top or "empty", "status": "tied" if r.get("top_tied") else "verified", "evidence": "compare_scorecards.py", "source_refs": [], "locator": f"rankings[{idx - 1}]", "source_url": ""})
    flaws: list[dict[str, Any]] = []
    if sens == "top_changes_across_supplied_weights":
        flaws.append({"id": "R-SENS", "severity": "medium", "summary": "Top-ranked paper changes across supplied weight scenarios.", "source_refs": [], "locator": "ranking_sensitivity"})
    loc_ver = payload.get("locator_verification")
    if isinstance(loc_ver, dict) and loc_ver.get("failed"):
        flaws.append({"id": "R-LOC", "severity": "high", "summary": f"Locator verification failed for {loc_ver['failed']} entries.", "source_refs": [], "locator": "locator_verification"})
    for i, iss in enumerate((payload.get("issues") or [])[:4], start=1):
        flaws.append(_normalize_flaw_row(iss, i))
    status = "fail" if any(f["severity"] in {"high", "critical"} for f in flaws) else ("provisional" if sens == "top_changes_across_supplied_weights" else "supported")
    ev_refs = [e["id"] for e in key_ev[:2] if _has_grounding(e)] or [f["id"] for f in flaws[:2] if _has_grounding(f)]
    return {
        "schema": SCHEMA_VERSION, "report_type": "novelty_scoring", "lang": _first_nonblank(payload.get("lang")) or "auto", "title": "Scorecard Ranking Sensitivity",
        "verdict": {"status": status, "label": "", "summary": f"Evaluated {len(rankings)} weight scenarios ({sens}).", "confidence": "bounded", "evidence_refs": ev_refs, **_parsimony_verdict_fields(payload)},
        "key_evidence": key_ev, "flaws_and_risks": flaws,
        "next_steps": [{"step": 1, "action": "Verify underlying /10 score anchors in full text.", "target": "compare_scorecards.py", "locator": ""}],
        "metadata": {"scope": f"{len(rankings)} weight scenarios", "search_date": _dt.date.today().isoformat(), "coverage_limits": _first_nonblank(payload.get("warning")) or "Bounded to supplied weight scenarios.", "reading_basis": "mixed", "sources_checked": len(rankings)},
        "sources": [],
    }


def _normalize_audit_or_lint(payload: dict[str, Any], *, truncate: bool = True) -> dict[str, Any]:
    findings = payload.get("findings") or []
    issues = payload.get("issues") or payload.get("errors") or []
    syc, grand = payload.get("sycophancy_hits") or [], payload.get("grandiose_findings") or []
    runs = payload.get("runs") or []
    pairs = payload.get("comparable_run_pairs") or []
    verdict_raw = _first_nonblank(payload.get("verdict"))

    failed_runs = [r for r in runs if isinstance(r, dict) and (r.get("exit_code") not in (None, 0) or str(r.get("status", "")).lower() in {"fail", "failed", "error"})]
    bad_pairs = [p for p in pairs if isinstance(p, dict) and (p.get("comparable") is False or p.get("issues") or p.get("mismatches"))]
    blocking_findings = [f for f in findings if isinstance(f, dict) and str(f.get("severity", "")).upper() in {"RISK", "ERROR", "CRITICAL", "HIGH"}]
    total_defects = len(issues) + len(syc) + len(grand) + len(blocking_findings) + len(failed_runs) + len(bad_pairs)
    status = "fail" if (total_defects > 0 or verdict_raw.upper() in {"FAIL", "ENGINEERING_BUG_DETECTED"}) else "pass"

    flaws = [_normalize_flaw_row(iss, i) for i, iss in enumerate(issues[:6] if truncate else issues, start=1)]
    for f in (findings[:6] if truncate else findings):
        if isinstance(f, dict):
            pid = _first_nonblank(f.get("pattern_id")) or f"F{len(flaws)+1}"
            sev = "high" if str(f.get("severity", "")).upper() in {"RISK", "ERROR", "CRITICAL", "HIGH"} else "medium"
            line_ref = f.get("line", f.get("field", "?"))
            # Use explicit checker message when present; for prose linters (excerpt-only), report pattern/line without echoing raw triggers.
            msg = _first_nonblank(f.get("message")) or f"Line {line_ref}: flagged {pid} ({_first_nonblank(f.get('category'), 'prose')})."
            loc = _first_nonblank(f.get("locator")) or f"line {line_ref}"
            flaws.append({"id": pid, "severity": sev, "summary": msg, "source_refs": [], "locator": loc})
    for sh in (syc[:4] if truncate else syc):
        if isinstance(sh, dict):
            pid = _first_nonblank(sh.get("pattern_id")) or "SYC"
            if not any(fl.get("id") == pid and fl.get("locator") == f"line {sh.get('line', '?')}" for fl in flaws):
                flaws.append({"id": pid, "severity": "high", "summary": f"Line {sh.get('line', '?')}: flagged {pid} (sycophancy).", "source_refs": [], "locator": f"line {sh.get('line', '?')}"})
    flaws.extend(_normalize_flaw_row(g, len(flaws) + i) for i, g in enumerate(grand[:4] if truncate else grand, start=1))
    for i, r in enumerate(failed_runs[:4] if truncate else failed_runs, start=1):
        flaws.append({"id": f"R-RUN{i}", "severity": "high", "summary": f"Run {r.get('run_id', i)} failed with exit_code={r.get('exit_code')}.", "source_refs": [], "locator": f"runs[{i}]"})
    for i, bp in enumerate(bad_pairs[:4] if truncate else bad_pairs, start=1):
        flaws.append({"id": f"R-PAIR{i}", "severity": "high", "summary": f"Run pair {bp.get('pair_id', i)} is not comparable.", "source_refs": [], "locator": f"comparable_run_pairs[{i}]"})

    key_ev = [{"id": "AUD1", "claim": "Audit defect count", "value": str(total_defects), "status": status, "evidence": "Automated checker output", "source_refs": ["audit_findings"], "locator": "findings/issues", "source_url": ""}]
    if runs:
        passed_runs = len(runs) - len(failed_runs)
        key_ev.append({"id": "RUNS", "claim": f"Experiment runs ({_first_nonblank(payload.get('question_id'), 'manifest')})", "value": f"{passed_runs}/{len(runs)} exit_code=0", "status": "fail" if failed_runs else "verified", "evidence": "Experiment manifest", "source_refs": ["runs"], "locator": _first_nonblank(payload.get("protocol_version"), "runs"), "source_url": ""})

    ev_refs = [e["id"] for e in key_ev[:2] if _has_grounding(e)] or [f["id"] for f in flaws[:2] if _has_grounding(f)]
    return {
        "schema": SCHEMA_VERSION, "report_type": "integrity_audit", "lang": _first_nonblank(payload.get("lang")) or "auto",
        "title": _first_nonblank(payload.get("title"), payload.get("question_id")) or "Integrity & Diagnostics Audit",
        "verdict": {"status": status, "label": "", "summary": f"Audit detected {total_defects} blocking integrity/diagnostic issues [audit_findings]." if status == "fail" else "Audit passed structural and diagnostic checks [audit_findings].", "confidence": "verified", "evidence_refs": ev_refs, **_parsimony_verdict_fields(payload)},
        "key_evidence": key_ev,
        "flaws_and_risks": flaws[:10] if truncate else flaws,
        "next_steps": [{"step": 1, "action": "Resolve every blocking issue before advancing manuscript or claim.", "target": "0 blocking defects", "locator": ""}],
        "metadata": {"scope": _first_nonblank(payload.get("source"), payload.get("corpus_boundary"), payload.get("question_id")) or "Input artifact", "search_date": _dt.date.today().isoformat(), "coverage_limits": "Structural and diagnostic checks only.", "reading_basis": "full_text", "sources_checked": max(1, len(runs))},
        "sources": [],
    }


def _normalize_evidence_map(payload: dict[str, Any], *, truncate: bool = True) -> dict[str, Any]:
    sources = payload.get("sources") or []
    evidence = payload.get("evidence") or []
    claims = payload.get("claims") or []
    ev_by_id = {e.get("id"): e for e in evidence if isinstance(e, dict) and e.get("id")}
    supported = [c for c in claims if isinstance(c, dict) and c.get("status") == "supported"]
    unresolved = [c for c in claims if isinstance(c, dict) and c.get("status") == "unresolved"]
    key_ev = []
    for i, c in enumerate(claims[:8] if truncate else claims, start=1):
        if isinstance(c, dict):
            eids = [str(x) for x in (c.get("evidence_ids") or []) if _nonblank(str(x))]
            locs = [ev_by_id[e].get("locator", "") for e in eids if e in ev_by_id]
            key_ev.append({"id": _first_nonblank(c.get("id")) or f"C{i}", "claim": _first_nonblank(c.get("text")), "value": _first_nonblank(c.get("status")), "status": _first_nonblank(c.get("status")) or "unresolved", "evidence": ", ".join(eids), "source_refs": eids, "locator": "; ".join(p for p in locs if p) or ("unresolved" if c.get("status") == "unresolved" else "evidence_map"), "source_url": ""})
    flaws = [{"id": _first_nonblank(c.get("id")) or f"R{i}", "severity": "medium", "summary": f"Unresolved claim: {c.get('text', '')} Next: {c.get('needed_next', '')}".strip(), "source_refs": [], "locator": _first_nonblank(c.get("id"), "claims")} for i, c in enumerate(unresolved[:6] if truncate else unresolved, start=1)]
    steps = [{"step": i, "action": _first_nonblank(c.get("needed_next")) or "Verify unresolved claim.", "target": _first_nonblank(c.get("id")), "locator": ""} for i, c in enumerate(unresolved[:4] if truncate else unresolved, start=1)]
    src_rows = [{"id": _first_nonblank(s.get("id")) or f"S{i}", "title": _first_nonblank(s.get("title")), "locator": _first_nonblank(s.get("identifier")), "url": s.get("identifier", "") if str(s.get("identifier", "")).startswith("http") else ""} for i, s in enumerate(sources[:10], start=1) if isinstance(s, dict)]
    ev_refs = [e["id"] for e in key_ev[:2] if _has_grounding(e)] or [f["id"] for f in flaws[:2] if _has_grounding(f)] or [s["id"] for s in src_rows[:2] if s.get("id")]
    return {
        "schema": SCHEMA_VERSION, "report_type": "evidence_map", "lang": _first_nonblank(payload.get("lang")) or "auto",
        "title": "Evidence Map Summary",
        "verdict": {"status": "provisional" if unresolved else ("supported" if supported else "insufficient_evidence"), "label": "", "summary": f"Evidence map tracks {len(claims)} claims ({len(supported)} supported, {len(unresolved)} unresolved) across {len(sources)} sources [evidence_map].", "confidence": "bounded", "evidence_refs": ev_refs, **_parsimony_verdict_fields(payload)},
        "key_evidence": key_ev, "flaws_and_risks": flaws,
        "next_steps": steps or [{"step": 1, "action": "Resolve open questions against independent full-text sources.", "target": "evidence_map", "locator": ""}],
        "metadata": {"scope": _first_nonblank(payload.get("corpus_boundary"), payload.get("source_mode")), "search_date": _dt.date.today().isoformat(), "coverage_limits": _first_nonblank(payload.get("corpus_boundary")), "reading_basis": "full_text", "sources_checked": len(sources)},
        "sources": src_rows,
    }


def _normalize_venue_dossier(payload: dict[str, Any], *, truncate: bool = True) -> dict[str, Any]:
    v_name = _first_nonblank(payload.get("venue"), payload.get("title")) or "Venue Dossier"
    edition, track, cfp_url = _first_nonblank(payload.get("edition")), _first_nonblank(payload.get("track")), _first_nonblank(payload.get("official_cfp_url"))
    milestones = payload.get("milestones") if isinstance(payload.get("milestones"), dict) else {}
    fees = payload.get("fees") if isinstance(payload.get("fees"), list) else []
    missing_ms = [k for k, v in milestones.items() if v is None]
    missing_fees = [f for f in fees if isinstance(f, dict) and f.get("mandatory") and f.get("amount") is None]
    key_ev = [{"id": f"M{i}", "claim": k.replace("_", " "), "value": str(v), "status": "verified", "evidence": "CFP milestone", "source_refs": ["CFP"], "locator": cfp_url or "milestones", "source_url": cfp_url} for i, (k, v) in enumerate(milestones.items(), start=1) if v is not None]
    for i, f in enumerate(fees[:6] if truncate else fees, start=1):
        if isinstance(f, dict):
            key_ev.append({"id": f"FEE{i}", "claim": _first_nonblank(f.get("name"), f.get("category")), "value": str(f.get("amount")) if f.get("amount") is not None else "unknown", "status": "verified" if f.get("amount") is not None else "unverified", "evidence": "Fee check", "source_refs": [], "locator": _first_nonblank(f.get("source_url"), "fees"), "source_url": _first_nonblank(f.get("source_url"))})
    flaws = [{"id": f"R-MS{i}", "severity": "medium", "summary": f"Milestone {k} is unverified (null).", "source_refs": [], "locator": "milestones"} for i, k in enumerate(missing_ms[:4], start=1)]
    flaws.extend({"id": f"R-FEE{i}", "severity": "high", "summary": f"Mandatory fee '{f.get('name', i)}' amount is unverified (null).", "source_refs": [], "locator": _first_nonblank(f.get("source_url"), "fees")} for i, f in enumerate(missing_fees[:4], start=1))
    ev_refs = [e["id"] for e in key_ev[:2] if _has_grounding(e)] or [f["id"] for f in flaws[:2] if _has_grounding(f)] or (["CFP"] if cfp_url else [])
    return {
        "schema": SCHEMA_VERSION, "report_type": "venue_dossier", "lang": _first_nonblank(payload.get("lang")) or "auto",
        "title": f"{v_name} {edition}".strip(),
        "verdict": {"status": "provisional" if (missing_ms or missing_fees) else "supported", "label": "", "summary": f"{v_name} {edition} ({track}): {len(milestones)-len(missing_ms)}/{len(milestones)} milestones and {len(fees)-len(missing_fees)}/{len(fees)} fees verified [venue_dossier].", "confidence": "bounded", "evidence_refs": ev_refs, **_parsimony_verdict_fields(payload)},
        "key_evidence": key_ev[:10] if truncate else key_ev, "flaws_and_risks": flaws[:8] if truncate else flaws,
        "next_steps": [{"step": 1, "action": "Verify unconfirmed mandatory fees and notification dates from official CFP pages.", "target": cfp_url or "official CFP", "locator": cfp_url}],
        "metadata": {"scope": track or v_name, "search_date": _first_nonblank(payload.get("checked_at"))[:10] or _dt.date.today().isoformat(), "coverage_limits": f"Budget: {payload.get('budget')} {payload.get('currency', '')}".strip(), "reading_basis": "full_text", "sources_checked": max(1, len(fees))},
        "sources": [{"id": "CFP", "title": f"{v_name} {edition} CFP".strip(), "locator": cfp_url, "url": cfp_url}] if cfp_url else [],
    }


def _normalize_manuscript_ledger(payload: dict[str, Any], *, truncate: bool = True) -> dict[str, Any]:
    sources, claims, methods, facts = payload.get("sources") or [], payload.get("claims") or [], payload.get("methods") or [], payload.get("numeric_facts") or []
    src_by_id = {s.get("id"): s for s in sources if isinstance(s, dict) and s.get("id")}
    flaws: list[dict[str, Any]] = []
    for s in sources:
        if isinstance(s, dict) and s.get("verified") is False:
            flaws.append({"id": f"R-SRC-{s.get('id', '?')}", "severity": "high", "summary": f"Source {s.get('id')} is unverified.", "source_refs": [], "locator": _first_nonblank(s.get("locator"), "sources")})
    for m in methods:
        if isinstance(m, dict) and m.get("grand_name") and m.get("origin") in {"reused", "adapted", "combined"}:
            flaws.append({"id": f"R-MTH-{m.get('id', '?')}", "severity": "critical", "summary": f"Method {m.get('id')} uses grand_name with origin={m.get('origin')}.", "source_refs": [], "locator": "methods"})
    key_ev: list[dict[str, Any]] = []
    for i, nf in enumerate(facts[:6] if truncate else facts, start=1):
        if isinstance(nf, dict):
            occ = nf.get("occurrences") or []
            vals = {(str(o.get("value")), str(o.get("unit", ""))) for o in occ if isinstance(o, dict)}
            if len(vals) > 1:
                flaws.append({"id": f"R-NUM-{nf.get('id', i)}", "severity": "critical", "summary": f"Numeric fact {nf.get('id')} has mismatched values across occurrences.", "source_refs": [], "locator": "numeric_facts"})
            first_o = occ[0] if occ and isinstance(occ[0], dict) else {}
            key_ev.append({"id": _first_nonblank(nf.get("id")) or f"N{i}", "claim": f"Numeric fact {nf.get('id', i)}", "value": f"{first_o.get('value', '')} {first_o.get('unit', '')}".strip(), "status": "fail" if len(vals) > 1 else "verified", "evidence": f"{len(occ)} occurrences", "source_refs": [], "locator": _first_nonblank(first_o.get("location"), "numeric_facts"), "source_url": ""})
    for i, m in enumerate(methods[:4] if truncate else methods, start=1):
        if isinstance(m, dict):
            sids = [str(x) for x in (m.get("source_ids") or []) if _nonblank(str(x))]
            locs = [src_by_id[sid].get("locator", "") for sid in sids if sid in src_by_id]
            key_ev.append({"id": _first_nonblank(m.get("id")) or f"M{i}", "claim": _first_nonblank(m.get("exact_change"), f"Method {m.get('id', i)}"), "value": _first_nonblank(m.get("origin")), "status": "fail" if m.get("grand_name") else "verified", "evidence": ", ".join(sids), "source_refs": sids, "locator": "; ".join(p for p in locs if p) or "methods", "source_url": ""})
    has_crit = any(f["severity"] == "critical" for f in flaws)
    src_rows = [{"id": _first_nonblank(s.get("id")) or f"S{i}", "title": _first_nonblank(s.get("type"), s.get("id")), "locator": _first_nonblank(s.get("locator")), "url": ""} for i, s in enumerate(sources[:10], start=1) if isinstance(s, dict)]
    ev_refs = [e["id"] for e in key_ev[:2] if _has_grounding(e)] or [f["id"] for f in flaws[:2] if _has_grounding(f)] or [s["id"] for s in src_rows[:2] if s.get("id")]
    return {
        "schema": SCHEMA_VERSION, "report_type": "manuscript_ledger", "lang": _first_nonblank(payload.get("lang")) or "auto",
        "title": "Manuscript Ledger Audit",
        "verdict": {"status": "fail" if has_crit else ("provisional" if flaws else "supported"), "label": "", "summary": f"Manuscript ledger tracks {len(claims)} claims, {len(methods)} methods, and {len(facts)} numeric facts across {len(sources)} sources [manuscript_ledger].", "confidence": "verified", "evidence_refs": ev_refs, **_parsimony_verdict_fields(payload)},
        "key_evidence": key_ev, "flaws_and_risks": flaws[:10] if truncate else flaws,
        "next_steps": [{"step": 1, "action": "Cross-check manuscript prose against ledger claims and numeric facts.", "target": "check_manuscript_ledger.py", "locator": ""}],
        "metadata": {"scope": f"{len(claims)} claims, {len(methods)} methods", "search_date": _dt.date.today().isoformat(), "coverage_limits": "Bounded to manuscript ledger entries.", "reading_basis": "full_text", "sources_checked": len(sources)},
        "sources": src_rows,
    }


def _normalize_composite_bundle(payload: dict[str, Any], *, truncate: bool = True) -> dict[str, Any]:
    sub_keys = [k for k in ("gap_audit", "precedent_search", "novelty", "venue", "integrity", "manuscript") if isinstance(payload.get(k), dict)]
    merged_ev, merged_flaws, merged_steps, merged_sources, verdict_bits, statuses = [], [], [], [], [], []
    seen_sids: set[str] = set()
    for k in sub_keys:
        norm = normalize_report_input(payload[k], truncate=truncate)
        statuses.append(norm["verdict"]["status"])
        if norm["verdict"]["summary"]:
            verdict_bits.append(f"{k}: {norm['verdict']['summary']}")
        merged_ev.extend(norm["key_evidence"][:3] if truncate else norm["key_evidence"])
        merged_flaws.extend(norm["flaws_and_risks"][:3] if truncate else norm["flaws_and_risks"])
        merged_steps.extend(norm["next_steps"][:2] if truncate else norm["next_steps"])
        for src in norm.get("sources", []):
            sid = src.get("id", "")
            if sid and sid not in seen_sids:
                seen_sids.add(sid)
                merged_sources.append(src)
    overall = "fail" if any(s in {"fail", "rejected"} for s in statuses) else ("provisional" if any(s in {"provisional", "insufficient_evidence"} for s in statuses) else "supported")
    ev_refs = [e["id"] for e in merged_ev[:3] if _has_grounding(e, seen_sids)] or [f["id"] for f in merged_flaws[:2] if _has_grounding(f, seen_sids)] or [s["id"] for s in merged_sources[:2] if s.get("id")]
    return {
        "schema": SCHEMA_VERSION, "report_type": "composite_audit", "lang": _first_nonblank(payload.get("lang")) or "auto",
        "title": _first_nonblank(payload.get("title")) or "Research Audit Summary",
        "verdict": {"status": overall, "label": "", "summary": " ".join(verdict_bits)[:400] or "Composite research audit summary.", "confidence": "bounded", "evidence_refs": ev_refs, **_parsimony_verdict_fields(payload)},
        "key_evidence": merged_ev[:10] if truncate else merged_ev, "flaws_and_risks": merged_flaws[:8] if truncate else merged_flaws, "next_steps": merged_steps[:6] if truncate else merged_steps,
        "metadata": {"scope": ", ".join(sub_keys), "search_date": _dt.date.today().isoformat(), "coverage_limits": "Composite summary capped to top executive items.", "reading_basis": "mixed", "sources_checked": len(sub_keys)},
        "sources": merged_sources[:12] if truncate else merged_sources,
    }


def normalize_report_input(payload: dict[str, Any], lang: str | None = None, *, truncate: bool = True) -> dict[str, Any]:
    """Normalize canonical executive JSON or upstream skill JSON into `research_scientist_executive_report_v1`."""
    if not isinstance(payload, dict) or not payload:
        raise ValueError("Input JSON must be a non-empty JSON object.")

    if payload.get("schema") == SCHEMA_VERSION:
        norm = _normalize_canonical(payload, truncate=truncate)
    elif "candidates" in payload or "surviving_gaps" in payload or "rejected_gaps" in payload:
        norm = _normalize_gap_record(payload, truncate=truncate)
    elif "venue" in payload and "target" in payload and "accepted_panel" in payload:
        norm = _normalize_venue_novelty(payload, truncate=truncate)
    elif "profiles" in payload and isinstance(payload.get("profiles"), list):
        norm = _normalize_scorecards(payload, truncate=truncate)
    elif "known_seed_checks" in payload or payload.get("schema") in {"research_scientist_search_v2", "research_scientist_search_campaign_v1"} or payload.get("format") == "research_scientist_search_campaign_v1" or ("source_records" in payload and "query_runs" in payload):
        norm = _normalize_search_output(payload, truncate=truncate)
    elif "source_mode" in payload and "corpus_boundary" in payload and "claims" in payload and "questions" in payload:
        norm = _normalize_evidence_map(payload, truncate=truncate)
    elif "official_cfp_url" in payload and ("fees" in payload or "milestones" in payload):
        norm = _normalize_venue_dossier(payload, truncate=truncate)
    elif "methods" in payload and "numeric_facts" in payload and "claims" in payload:
        norm = _normalize_manuscript_ledger(payload, truncate=truncate)
    elif "rankings" in payload and "ranking_sensitivity" in payload and payload.get("rankings"):
        norm = _normalize_scorecard_rankings(payload, truncate=truncate)
    elif any(k in payload for k in ("findings", "sycophancy_hits", "grandiose_findings", "issues", "runs", "comparable_run_pairs", "errors")):
        norm = _normalize_audit_or_lint(payload, truncate=truncate)
    elif any(isinstance(payload.get(k), dict) for k in ("gap_audit", "precedent_search", "novelty", "venue", "integrity", "manuscript")):
        norm = _normalize_composite_bundle(payload, truncate=truncate)
    elif any(k in payload for k in ("verdict", "conclusion", "key_evidence", "flaws_and_risks", "next_steps", "recommendations", "title", "metrics", "evidence")):
        norm = _normalize_canonical(payload, truncate=truncate)
    else:
        raise ValueError("Unrecognized JSON schema: missing verdict, candidates, venue/target, search results, or audit findings.")

    if lang and lang != "auto":
        norm["lang"] = lang
    return norm


# ---------------------------------------------------------------------------
# Conciseness, Plain-Language, Anti-Sycophancy & Grounding Linter
# ---------------------------------------------------------------------------

_EXEMPT_DOMAIN_PATTERNS = (
    re.compile(r"\bleverage\s+(?:score|scores|point|points|statistic|statistics|value|values|ratio|effect|sampling)\b", re.I),
    re.compile(r"\bstatistical\s+leverage\b", re.I),
    re.compile(
        r"\b(?:robust\s+(?:statistics|regression|optimization|estimation|estimator|control|pca|"
        r"covariance|loss|huber|inference|standard\s+errors)|adversarial(?:ly)?\s+robust|"
        r"byzantine[- ]robust|robust\s+to\s+(?:noise|outliers|perturbations|distribution\s+shift))\b",
        re.I,
    ),
    re.compile(r"\b(?:(?:loss|energy|fitness|optimization|reward|error|objective)\s+landscape|landscape\s+of\s+(?:local\s+minima|saddle\s+points))\b", re.I),
    re.compile(
        r"\b(?:(?:attention|forget|reset|update|input|output|logic|quantum|xor|nand|nor|and|or|"
        r"moe|mixture-of-experts|evidence|quality|verification|precedent|plan)\s+gat(?:e|ed|ing)|"
        r"gat(?:e|ed|ing)\s+(?:mechanism|unit|network|layer|function|check|logic)|"
        r"gated\s+(?:recurrent|linear|attention|mlp))\b",
        re.I,
    ),
    re.compile(r"\b(?:(?:api|foreign|primary|hash|cache|bibtex|cite|citation|encryption|public|private|secret|dedup|sort|join)\s+key|key[- ]value|keypoint)\b", re.I),
    re.compile(r"\bcatastrophic\s+(?:forgetting|interference)\b", re.I),
)

_PLACEHOLDER_PATTERNS = (
    re.compile(r"\b(?:TODO|TBD|TK|XXXX)\b"),
    re.compile(r"\[insert\s+[^\]]+\]", re.I),
    re.compile(r"\bas\s+an\s+ai(?:\s+language\s+model)?\b", re.I),
    re.compile(r"\bi\s+hope\s+this\s+helps\b", re.I),
    re.compile(r"\bvới\s+tư\s+cách\s+là\s+(?:một\s+)?ai\b", re.I),
    re.compile(r"\btôi\s+là\s+mô\s+hình\s+ngôn\s+ngữ\b", re.I),
    re.compile(r"\bhy\s+vọng\s+(?:điều\s+này|thông\s+tin\s+này)\s+(?:sẽ\s+)?giúp\s+ích\b", re.I),
)

_EN_JARGON_ERROR_PATTERNS = (
    re.compile(r"\bsynergistic\s+paradigm\b", re.I),
    re.compile(r"\bsynergistic\b", re.I),
    re.compile(r"\bontological\b", re.I),
    re.compile(r"\bepistemological\b", re.I),
    re.compile(r"\bubiquitous\b", re.I),
    re.compile(r"\bnotwithstanding\b", re.I),
    re.compile(r"\baforementioned\b", re.I),
    re.compile(r"\bheretofore\b", re.I),
    re.compile(r"\bdelv(?:e|es|ed|ing)\b", re.I),
    re.compile(r"\btapestry\b", re.I),
    re.compile(r"\bmultifaceted\b", re.I),
    re.compile(r"\bparadigm\s+shift\b", re.I),
    re.compile(r"\bholistic\s+ecosystem\b", re.I),
    re.compile(r"\bholistic\b", re.I),
    re.compile(r"\bcognitive\s+synthesis\b", re.I),
    re.compile(r"\bgame[- ]changing\b", re.I),
    re.compile(r"\brevolutionary\b", re.I),
    re.compile(r"\bunprecedented\b", re.I),
    re.compile(r"\bleverag(?:e|es|ed|ing)\b", re.I),
)
_EN_JARGON_WARN_PATTERNS = (
    re.compile(r"\bpivotal\b", re.I),
    re.compile(r"\bmeticulous(?:ly)?\b", re.I),
    re.compile(r"\binterplay\b", re.I),
    re.compile(r"\bintricate\b", re.I),
    re.compile(r"\bseamless(?:ly)?\b", re.I),
    re.compile(r"\bmyriad\b", re.I),
    re.compile(r"\belucidate\b", re.I),
)

_VI_JARGON_ERROR_PATTERNS = (
    re.compile(r"\bmang\s+tính\s+đột\s+phá\b", re.I),
    re.compile(r"\btoàn\s+diện\s+sâu\s+sắc\b", re.I),
    re.compile(r"\bhệ\s+sinh\s+thái\s+đa\s+chiều\b", re.I),
    re.compile(r"\bhệ\s+sinh\s+thái\s+toàn\s+diện\b", re.I),
    re.compile(r"\btối\s+ưu\s+hóa\s+vượt\s+trội\b", re.I),
    re.compile(r"\btrong\s+bối\s+cảnh\s+hiện\s+nay\b", re.I),
    re.compile(r"\bmột\s+cách\s+sâu\s+sắc\s+và\s+toàn\s+diện\b", re.I),
    re.compile(r"\bbước\s+ngoặt\s+mang\s+tính\s+cách\s+mạng\b", re.I),
    re.compile(r"\btính\s+hiệp\s+đồng\b", re.I),
    re.compile(r"\bđột\s+phá\s+chưa\s+từng\s+có\b", re.I),
    re.compile(r"\bkiến\s+tạo\s+giá\s+trị\b", re.I),
    re.compile(r"\bnền\s+tảng\s+toàn\s+diện\s+đa\s+tầng\b", re.I),
)
_VI_JARGON_WARN_PATTERNS = (
    re.compile(r"\bđóng\s+vai\s+trò\s+then\s+chốt\b", re.I),
    re.compile(r"\btiềm\s+năng\s+to\s+lớn\b", re.I),
    re.compile(r"\bhết\s+sức\s+quan\s+trọng\b", re.I),
    re.compile(r"\bxét\s+về\s+mặt\s+tổng\s+thể\b", re.I),
)

_FILLER_PATTERNS = (
    re.compile(r"\bit\s+is\s+worth\s+noting\s+that\b", re.I),
    re.compile(r"\bit\s+is\s+worth\s+noting\b", re.I),
    re.compile(r"\bin\s+light\s+of\s+the\s+fact\s+that\b", re.I),
    re.compile(r"\bneedless\s+to\s+say\b", re.I),
    re.compile(r"\bas\s+a\s+matter\s+of\s+fact\b", re.I),
    re.compile(r"\bit\s+goes\s+without\s+saying\b", re.I),
    re.compile(r"\bwith\s+respect\s+to\s+the\s+aforementioned\b", re.I),
    re.compile(r"\blet'?s\s+dive\s+in\b", re.I),
    re.compile(r"\bat\s+the\s+end\s+of\s+the\s+day\b", re.I),
    re.compile(r"\bdue\s+to\s+the\s+fact\s+that\b", re.I),
    re.compile(r"\bcần\s+lưu\s+ý\s+rằng\b", re.I),
    re.compile(r"\bcó\s+thể\s+thấy\s+một\s+cách\s+rõ\s+ràng\s+rằng\b", re.I),
    re.compile(r"\bkhông\s+thể\s+phủ\s+nhận\s+rằng\b", re.I),
    re.compile(r"\bnhư\s+chúng\s+ta\s+đã\s+biết\b", re.I),
    re.compile(r"\bnhư\s+đã\s+đề\s+cập\s+ở\s+trên\b", re.I),
    re.compile(r"\btừ\s+góc\s+độ\s+tổng\s+quan\s+có\s+thể\s+nhận\s+thấy\b", re.I),
)

_NOMINALIZATION_PATTERNS = (
    (re.compile(r"\butilization\s+of\b", re.I), "Replace 'utilization of' with 'use'."),
    (re.compile(r"\bfacilitation\s+of\b", re.I), "Replace 'facilitation of' with 'enabling'."),
    (re.compile(r"\bconduct\s+an\s+investigation\s+(?:of|into)\b", re.I), "Replace with 'investigate'."),
    (re.compile(r"\bmake\s+a\s+determination\s+regarding\b", re.I), "Replace with 'decide'."),
    (re.compile(r"\bviệc\s+tiến\s+hành\s+thực\s+hiện\b", re.I), "Thay 'việc tiến hành thực hiện' bằng 'thực hiện'."),
    (re.compile(r"\bviệc\s+thực\s+hiện\s+triển\s+khai\b", re.I), "Thay 'việc thực hiện triển khai' bằng 'triển khai'."),
    (re.compile(r"\bthực\s+hiện\s+việc\s+kiểm\s+tra\b", re.I), "Thay 'thực hiện việc kiểm tra' bằng 'kiểm tra'."),
    (re.compile(r"\bsự\s+gia\s+tăng\s+về\s+mặt\b", re.I), "Thay 'sự gia tăng về mặt' bằng 'tăng'."),
)

_SYC_EN_PATTERNS = (
    re.compile(r"\b(?:great|brilliant|excellent|fantastic|amazing|wonderful|awesome|outstanding|superb)\s+(?:idea|work|job|insight|approach|result|results)\b", re.I),
    re.compile(r"\b(?:absolutely|truly|incredibly|remarkably)\s+(?:brilliant|impressive|outstanding|amazing|fantastic|superb)\b", re.I),
    re.compile(r"(?:^|[.!?\n]\s*)(?:awesome|fantastic|brilliant|wonderful|superb|excellent|amazing|congratulations|well\s+done)\s*[!.]", re.I),
    re.compile(r"\bspot[- ]on\b", re.I),
    re.compile(r"\byou(?:'re| are)\s+(?:absolutely|completely|totally)\s+right\b", re.I),
    re.compile(r"\b(?:impressive|outstanding|remarkable)\s+(?:gain|gains|contribution|result|results|achievement|performance)\b", re.I),
    re.compile(r"\bpromising\s+direction\b", re.I),
    re.compile(r"\bwell[- ]motivated\b", re.I),
    re.compile(r"\bgroundbreaking\b", re.I),
)
_SYC_VI_INT = r"(?:(?:rất|quá|cực\s+kỳ|cực|vô\s+cùng|thật\s+sự|hoàn\s+toàn|khá)\s+)?"
_SYC_VI_PATTERNS = (
    re.compile(rf"\b(?:ý\s+tưởng|cách\s+tiếp\s+cận|hướng\s+đi|đóng\s+góp|kết\s+quả|trực\s+giác|phương\s+pháp)\s+{_SYC_VI_INT}(?:tuyệt\s+vời|xuất\s+sắc|ấn\s+tượng|hoàn\s+hảo|đỉnh\s+cao|thông\s+minh|đáng\s+kinh\s+ngạc)\b", re.I),
    re.compile(r"\b(?:rất|quá|cực\s+kỳ|cực|vô\s+cùng|thật\s+sự)\s+(?:tuyệt\s+vời|xuất\s+sắc|ấn\s+tượng|hoàn\s+hảo)\b", re.I),
    re.compile(r"\b(?:tuyệt\s+vời|hoàn\s+hảo|đột\s+phá\s+toàn\s+diện|bạn\s+hoàn\s+toàn\s+đúng|trực\s+giác\s+rất\s+chuẩn|hướng\s+đi\s+đầy\s+hứa\s+hẹn)\b", re.I),
    re.compile(r"(?:^|[.!?\n]\s*)xuất\s+sắc\s*[!.]", re.I),
)
_PROBLEM_INFLATION_PATTERNS = (
    re.compile(r"\b(?:fundamental|existential|unprecedented|systemic|catastrophic|crippling|devastating)\s+(?:crisis|failure|collapse|bottleneck|barrier|threat|flaw|flaws)\b", re.I),
    re.compile(r"\b(?:complete|total)\s+(?:collapse|failure|breakdown)\b", re.I),
    re.compile(r"\b(?:broken\s+beyond\s+repair|fundamentally\s+broken|urgently\s+demands?\s+a\s+complete\s+overhaul|renders?\s+(?:all\s+)?(?:prior|existing|current)\s+\w+(?:\s+\w+){0,2}\s+(?:useless|obsolete|invalid))\b", re.I),
    re.compile(r"\bkhủng\s+hoảng\s+(?:nền\s+tảng|nghiêm\s+trọng|toàn\s+diện|chưa\s+từng\s+có)\b", re.I),
    re.compile(r"\bthất\s+bại\s+(?:thảm\s+hại|nặng\s+nề|toàn\s+diện)\b", re.I),
    re.compile(r"\b(?:sụp\s+đổ\s+hoàn\s+toàn|bế\s+tắc\s+toàn\s+diện|hỏng\s+hóc\s+không\s+thể\s+cứu\s+vãn|phá\s+sản\s+hoàn\s+toàn)\b", re.I),
)
_VI_SANDWICH_PRAISE_RE = re.compile(
    r"\b(?:ý\s+tưởng|cách\s+làm|cách\s+tiếp\s+cận|hướng\s+đi|kết\s+quả|mô\s+hình|phương\s+pháp|thiết\s+kế|đề\s+xuất)\s+"
    r"(?:rất\s+|khá\s+|cực\s+kỳ\s+)?(?:tốt|hay|ổn|khả\s+quan|ấn\s+tượng|xuất\s+sắc|tuyệt\s+vời|thú\s+vị)|\b(?:khá\s+ổn|đáng\s+khen)\b",
    re.I,
)
_VI_SANDWICH_PIVOT_RE = re.compile(r"\b(?:tuy\s+nhiên|nhưng|song)\b", re.I)
_VI_SANDWICH_FLAW_RE = re.compile(
    r"\b(?:lỗi|sai|rò\s+rỉ|thiếu|không\s+đạt|chưa\s+đạt|chưa\s+kiểm|bị\s+trùng|trùng(?:\s+lặp)?|rủi\s+ro|hỏng|yếu|kém|hạn\s+chế|nhược\s+điểm|vấn\s+đề)\b",
    re.I,
)
_EN_SANDWICH_PRAISE_RE = re.compile(
    r"\b(?:(?:nice|good|solid|great|interesting|clever|neat)\s+"
    r"(?:idea|approach|work|method|result|results|direction|attempt)|"
    r"strong\s+(?:idea|approach|work|contribution|paper|insight|proposal))\b",
    re.I,
)
_EN_SANDWICH_PIVOT_RE = re.compile(r"\b(?:but|however|although|though|yet|while|still)\b", re.I)
_EN_SANDWICH_FLAW_RE = re.compile(
    r"\b(?:leak(?:s|ed|ing|y|age)?|bugs?|errors?|fail(?:s|ed|ure)?|flaws?|risks?|missing|broken|weak|incomplete|invalid(?:ates?|ated)?|overfit(?:ting|s)?|contaminat(?:ed|ion)|mismatch(?:ed|es)?|unverified|issues?)\b",
    re.I,
)

_EXEMPT_COMPOUND_FUSION_RE = re.compile(
    r"\b(?:Early|Late|Mid|Feature|Cross|Decision|Multi|Sensor|Score|Modal)-?Fusion\b"
)
_GRAND_BRANDING_PATTERNS = (
    re.compile(r"\b(?:Hyper|Omni|Syner|Neuro)[A-Z][A-Za-z0-9-]{2,}\b"),
    re.compile(r"\b[A-Z][A-Za-z0-9]+(?:Cascade|Fusion|Framework)\b"),
    re.compile(r"\bunified\s+(?:framework|paradigm|architecture|ecosystem)\b", re.I),
    re.compile(r"\bnovel\s+(?:framework|paradigm|architecture)\b", re.I),
    re.compile(r"\bkhung\s+lý\s+thuyết\s+hợp\s+nhất\b", re.I),
    re.compile(r"\bhệ\s+thống\s+siêu\s+hợp\s+nhất\b", re.I),
)

_UPPER_LATIN = "A-ZÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖØÙÚÛÜÝÞĐĂÂÊÔƠƯẠẢẤẦẨẪẬẮẰẲẴẶẸẺẼẾỀỂỄỆỈỊỌỎỐỒỔỖỘỚỜỞỠỢỤỦỨỪỬỮỰỲỴỶỸ"
_LOWER_LATIN = "a-zàáâãäåæçèéêëìíîïðñòóôõöøùúûüýþßđăâêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ"
_ANY_LATIN = _UPPER_LATIN + _LOWER_LATIN
_AUTHOR_SURNAME = rf"(?=[{_ANY_LATIN}'-]*[{_LOWER_LATIN}])[{_UPPER_LATIN}][{_ANY_LATIN}'-]+"
_NON_AUTHOR_TOKENS = frozenset({
    "in", "on", "at", "by", "for", "from", "of", "to", "with", "via", "per", "as", "and", "or",
    "the", "this", "that", "these", "those", "see", "since", "until", "before", "after", "during",
    "however", "moreover", "furthermore", "therefore", "consequently", "additionally", "meanwhile",
    "specifically", "notably", "similarly", "conversely", "nonetheless", "nevertheless", "finally",
    "overall", "indeed", "instead", "recently", "previously", "currently",
    "accuracy", "precision", "recall", "score", "scores", "metric", "metrics", "loss", "gain", "gains",
    "baseline", "baselines", "model", "models", "method", "methods", "dataset", "datasets", "benchmark",
    "eval", "test", "train", "split", "seed", "data", "copyright",
    "table", "figure", "fig", "section", "sec", "equation", "eq", "appendix", "algorithm", "step", "phase",
    "bảng", "hình", "mục", "trang", "bước", "giai", "đoạn", "năm", "từ", "đến", "vào", "theo", "trong",
    "neurips", "icml", "iclr", "cvpr", "iccv", "eccv", "acl", "emnlp", "naacl", "aaai", "kdd", "tmlr", "tacl",
    "arxiv", "workshop", "conference", "journal", "proceedings", "survey", "audit", "report", "version",
    "january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    "spring", "summer", "fall", "winter", "autumn",
})

_STRUCTURAL_REF_SCRUB_RE = re.compile(
    r"\b(?:Section|Sec\.?|Fig\.?|Figure|Table|Eq\.?|Equation|Algorithm|Alg\.?|Appendix|Step|Phase|Stage|Bước|Giai\s+đoạn|Bảng|Hình|Mục)\s*\d+(?:\.\d+)*",
    re.I,
)
_INLINE_LOCATOR_CUE_RE = re.compile(
    r"(?:\[[^\]]*(?:/|\\|\.(?:json|csv|tsv|txt|md|log|py|pdf|yaml|yml)\b|(?i:(?:Table|Fig\.?|Figure|Section|Sec\.?|Eq\.?|Bảng|Hình|Mục|Trang|p\.)\s*\d+|arXiv:|10\.\d{4,9}/|https?://))[^\]]*\]|"
    r"(?i:\barXiv:\s*\d{4}\.\d{4,5}(?:v\d+)?)|\b10\.\d{4,9}/[^\s\]\)\},;\"']*[^\s\]\)\},;\"'.]|"
    r"https?://\S+|\b(?i:logs?|runs?|diagnostics?|artifacts?)/\S+|"
    r"\b(?i:Table|Fig\.?|Figure|Section|Sec\.?|p\.|Bảng|Mục|Trang)\s*\d+\b)"
)
_METRIC_NAME_CORE = (
    r"(?:F1|AUC|ROC-AUC|ROC|MRR|NDCG|Hits|BLEU|ROUGE|mAP|WER|CER|IoU|mIoU|PPL|perplexity|"
    r"RMSE|MAE|Pass@[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)?|Top-[A-Za-z0-9]+|"
    r"accuracy|acc|gain|loss|speedup|score|precision|recall|latency|n)(?:@[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)?|-[A-Za-z0-9]+)*"
)
_METRIC_CLAIM_RE = re.compile(
    r"(?:(?<![\d.])\d+(?:\.\d+)?\s*(?:%|/10\b)|"
    r"\bp\s*[<≤]\s*0?\.\d+|"
    r"\bfrom\s+[+-]?\d+(?:\.\d+)?\s+to\s+[+-]?\d+(?:\.\d+)?\b|"
    r"\btừ\s+[+-]?\d+(?:\.\d+)?\s+(?:đến|tới|lên|xuống)\s+[+-]?\d+(?:\.\d+)?\b|"
    rf"\b{_METRIC_NAME_CORE}(?:\s*[:=]\s*|\s+(?:(?:of|is|was|reaches|achieves|improved\s+by|improves\s+(?:by|from)|drops\s+(?:by|from)|increased\s+by|from|đạt|tăng|giảm|là)\s+)?)[+-]?\d+(?:\.\d+)?|"
    r"(?<![\d.])\d+(?:\.\d+)?\s*(?:F1(?:-score)?|AUC|ROC-AUC|BLEU(?:-\d+)?|ROUGE(?:-[A-Za-z0-9]+)?|mAP(?:@[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)?)?|Pass@[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)?|Top-[A-Za-z0-9]+|RMSE|MAE|WER|CER|IoU|mIoU|PPL|perplexity|accuracy|gain|speedup|pp)\b|"
    r"\$\s*\d+(?:,\d{3})*(?:\.\d+)?)",
    re.I,
)
_INLINE_CITATION_RE = re.compile(
    rf"(?:\(\s*{_AUTHOR_SURNAME}(?:\s+et\s+al\.?|(?:,\s*{_AUTHOR_SURNAME})*(?:\s*,?\s*(?:&|and|và)\s+{_AUTHOR_SURNAME})?)?(?:\s*,\s*|\s+)(?:19|20)\d{{2}}\s*\)|"
    rf"(?<!\w){_AUTHOR_SURNAME}(?:\s+et\s+al\.?(?:,?\s*(?:19|20)\d{{2}}|\s*\((?:19|20)\d{{2}}\))|(?:,\s*{_AUTHOR_SURNAME})*\s*,?\s*(?:&|and|và)\s+{_AUTHOR_SURNAME}\s*\((?:19|20)\d{{2}}\)|\s*\((?:19|20)\d{{2}}\))|"
    r"(?<![A-Za-z0-9_])\[(?:\d{1,4}|[A-Za-z]{1,4}-?\d{1,4})\](?![A-Za-z0-9_])|"
    r"(?i:(?<![A-Za-z0-9_])arXiv:\s*\d{4}\.\d{4,5}(?:v\d+)?)|"
    r"\b10\.\d{4,9}/[^\s\]\)\},;\"']*[^\s\]\)\},;\"'.])"
)
_BRACKET_REF_RE = re.compile(r"(?<![A-Za-z0-9_])\[([A-Za-z0-9_.-]+)\]")


def _extract_inline_citations(text: str) -> list[str]:
    nfc = _normalize_nfc(text)
    out: list[str] = []
    for m in _INLINE_CITATION_RE.finditer(nfc):
        cit = m.group(0)
        low = cit.strip().lower()
        if low.startswith("[") or low.startswith(("arxiv:", "10.")):
            out.append(cit)
            continue
        if cit.lstrip().startswith("("):
            inner = cit.strip()[1:-1].strip()
            while True:
                m_lead = re.match(rf"^({_AUTHOR_SURNAME})\s*,\s*(.+)$", inner)
                if m_lead and m_lead.group(1).lower() in _NON_AUTHOR_TOKENS and re.search(rf"{_AUTHOR_SURNAME}", m_lead.group(2)):
                    inner = m_lead.group(2).strip()
                else:
                    break
            cit = f"({inner})"
        else:
            while True:
                m_lead = re.match(rf"^({_AUTHOR_SURNAME})\s*,\s*(.+)$", cit)
                if m_lead and m_lead.group(1).lower() in _NON_AUTHOR_TOKENS and re.search(rf"{_AUTHOR_SURNAME}", m_lead.group(2)):
                    cit = m_lead.group(2)
                else:
                    break
        has_etal = bool(re.search(r"\bet\s+al\.?\b", cit, re.I))
        au_tokens = [au.group(1).lower() for au in re.finditer(rf"({_AUTHOR_SURNAME})", cit)]
        if not has_etal and au_tokens and all(tok in _NON_AUTHOR_TOKENS for tok in au_tokens):
            continue
        out.append(cit)
    return out


def _strip_exempt_terms(text: str) -> str:
    work = re.sub(r'"[^"\n]{1,220}"', ' "quote" ', text)
    for pat in _EXEMPT_DOMAIN_PATTERNS:
        work = pat.sub(" [term] ", work)
    return work


def _mask_before_sentence_split(text: str) -> str:
    work = _normalize_nfc(text)
    work = re.sub(r"https?://\S+?([.!?])(?=\s|$)", r" URL\1", work)
    work = re.sub(r"https?://\S+", " URL ", work)
    work = re.sub(r"\b10\.\d{4,9}/\S+?([.!?])(?=\s|$)", r" DOI\1", work)
    work = re.sub(r"\b10\.\d{4,9}/\S+", " DOI ", work)
    work = re.sub(r"\bp\.(?=\s*\d)", "p_DOT_", work, flags=re.I)
    work = re.sub(r"\b(?:et\s+al|e\.g|i\.e|Fig|Sec|Eq|Dr|Prof|vs|pp|No|Vol|approx|al)\.", lambda m: m.group(0).replace(".", "_DOT_"), work, flags=re.I)
    work = re.sub(r"\bv(\d+)\.(\d+)", r"v\1_DOT_\2", work)
    return re.sub(r"(\d)\.(\d)", r"\1_DOT_\2", work)


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", _mask_before_sentence_split(text))
    return [p.replace("_DOT_", ".").strip() for p in parts if p.strip()]


def _count_words(text: str) -> int:
    clean = re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?", " ", text)
    clean = re.sub(r"https?://\S+", " URL ", clean)
    return len(re.findall(r"[^\W_]+(?:[-'][^\W_]+)*", clean, re.UNICODE))


def _excerpt(text: str, limit: int = 110) -> str:
    s = " ".join(text.split())
    return s if len(s) <= limit else s[: limit - 3] + "..."


def _load_humanizer_sycophancy(text: str) -> list[dict[str, Any]]:
    hl_path = Path(__file__).with_name("humanizer_lint.py")
    if not hl_path.is_file():
        return []
    try:
        mod_name = "_rs_humanizer_lint_helper"
        mod = sys.modules.get(mod_name)
        if mod is None:
            spec = importlib.util.spec_from_file_location(mod_name, hl_path)
            if spec is None or spec.loader is None:
                return []
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)
        return mod.detect_sycophancy(mod.mask_prose(text))
    except Exception:
        return []


def _add_finding(
    findings: list[dict[str, Any]],
    *,
    field: str,
    category: str,
    pattern_id: str,
    severity: str,
    excerpt: str,
    message: str,
    remediation: str,
) -> None:
    findings.append({
        "field": field,
        "category": category,
        "pattern_id": pattern_id,
        "severity": severity,
        "critical": severity == "error",
        "excerpt": _excerpt(excerpt),
        "message": message,
        "remediation": remediation,
    })


def _scan_prose_block(
    text: str,
    field: str,
    findings: list[dict[str, Any]],
    thresholds: dict[str, int],
) -> int:
    if not _nonblank(text):
        return 0
    nfc = _normalize_nfc(text)

    for para in [p.strip() for p in re.split(r"\n\s*\n", nfc) if p.strip()]:
        pw = _count_words(para)
        if pw > thresholds["paragraph_error"]:
            _add_finding(findings, field=field, category="conciseness", pattern_id="PARAGRAPH_BLOAT", severity="error", excerpt=para, message=f"Paragraph has {pw} words (max {thresholds['paragraph_error']}).", remediation="Split or convert to short bullets (<= 80 words).")
        elif pw > thresholds["paragraph_warn"]:
            _add_finding(findings, field=field, category="conciseness", pattern_id="PARAGRAPH_BLOAT", severity="warn", excerpt=para, message=f"Paragraph has {pw} words (recommended <= {thresholds['paragraph_warn']}).", remediation="Tighten paragraph to <= 80 words.")

    for sent in _split_sentences(nfc):
        sw = _count_words(sent)
        if sw > thresholds["sentence_severe"]:
            _add_finding(findings, field=field, category="conciseness", pattern_id="SENTENCE_SEVERE_BLOAT", severity="error", excerpt=sent, message=f"Sentence has {sw} words (limit {thresholds['sentence_max']}).", remediation=f"Break into shorter sentences (<= {thresholds['sentence_max']} words).")
        elif sw > thresholds["sentence_max"]:
            _add_finding(findings, field=field, category="conciseness", pattern_id="SENTENCE_TOO_LONG", severity="error", excerpt=sent, message=f"Sentence has {sw} words (limit {thresholds['sentence_max']}).", remediation=f"Split into concise sentences (<= {thresholds['sentence_max']} words).")

    for pat in _PLACEHOLDER_PATTERNS:
        m = pat.search(nfc)
        if m:
            _add_finding(findings, field=field, category="structure", pattern_id="RPT_PLACEHOLDER", severity="error", excerpt=nfc, message=f"Placeholder or chatbot residue: {m.group(0)!r}.", remediation="Replace with verified facts.")
            break

    exempted = _strip_exempt_terms(nfc)
    for pat_group, pid, sev, msg, rem in (
        (_EN_JARGON_ERROR_PATTERNS, "JARGON_AI_BUZZWORD", "error", "Obscure jargon or AI buzzword", "Use plain, exact words."),
        (_EN_JARGON_WARN_PATTERNS, "JARGON_AI_BUZZWORD", "warn", "Wordy/vague adjective", "Use direct factual wording."),
        (_VI_JARGON_ERROR_PATTERNS, "JARGON_VI_BUZZWORD", "error", "Cụm từ sáo rỗng / khó hiểu", "Thay bằng số liệu hoặc mô tả trực diện."),
        (_VI_JARGON_WARN_PATTERNS, "JARGON_VI_BUZZWORD", "warn", "Cụm từ chung chung", "Nêu thẳng kết quả hoặc vai trò cụ thể."),
    ):
        for pat in pat_group:
            m = pat.search(exempted)
            if m:
                _add_finding(findings, field=field, category="plain_language", pattern_id=pid, severity=sev, excerpt=nfc, message=f"{msg}: {m.group(0)!r}.", remediation=rem)
                break

    for pat in _FILLER_PATTERNS:
        m = pat.search(nfc)
        if m:
            _add_finding(findings, field=field, category="plain_language", pattern_id="FILLER_TRANSITION", severity="error", excerpt=nfc, message=f"Filler transition detected: {m.group(0)!r}.", remediation="Delete filler opener and state the point directly.")
            break

    for pat, hint in _NOMINALIZATION_PATTERNS:
        m = pat.search(nfc)
        if m:
            _add_finding(findings, field=field, category="plain_language", pattern_id="NOMINALIZATION", severity="error", excerpt=nfc, message=f"Convoluted nominalization: {m.group(0)!r}.", remediation=hint)
            break

    syc_hit = False
    for pat in (*_SYC_EN_PATTERNS, *_SYC_VI_PATTERNS):
        m = pat.search(nfc)
        if m:
            _add_finding(findings, field=field, category="sycophancy", pattern_id="SYC_FLATTERY", severity="error", excerpt=nfc, message=f"Sycophancy/flattery detected: {m.group(0)!r}.", remediation="Remove praise; lead directly with verdict, defect, or metric.")
            syc_hit = True
            break
    if not syc_hit:
        for h in _load_humanizer_sycophancy(nfc):
            if h.get("pattern_id") != "SYC_PRAISE_SANDWICH" and (h.get("critical") or str(h.get("severity", "")).upper() == "RISK"):
                _add_finding(findings, field=field, category="sycophancy", pattern_id=str(h.get("pattern_id", "SYC_PRAISE_SANDWICH")), severity="error", excerpt=nfc, message=f"Sycophancy or praise-sandwich: {h.get('phrase', '')!r}.", remediation=str(h.get("remediation", "Lead directly with flaws.")))
                syc_hit = True
                break
    if not syc_hit:
        sents = _split_sentences(nfc)
        for pm_re, piv_re, fl_re, rem in (
            (_VI_SANDWICH_PRAISE_RE, _VI_SANDWICH_PIVOT_RE, _VI_SANDWICH_FLAW_RE, "Nêu thẳng lỗi hoặc rủi ro trước, bỏ lời khen mở đầu."),
            (_EN_SANDWICH_PRAISE_RE, _EN_SANDWICH_PIVOT_RE, _EN_SANDWICH_FLAW_RE, "Remove praise opener; lead directly with the defect or risk."),
        ):
            matched_praise = None
            for i, s in enumerate(sents):
                pm = pm_re.search(s)
                if not pm or fl_re.search(s[:pm.start()]):
                    continue
                piv = piv_re.search(s, pm.end())
                if piv and fl_re.search(s, piv.end()):
                    matched_praise = pm.group(0)
                    break
                if not piv and i + 1 < len(sents):
                    piv_next = piv_re.search(sents[i + 1])
                    if piv_next and fl_re.search(sents[i + 1], piv_next.end()):
                        matched_praise = pm.group(0)
                        break
            if matched_praise:
                _add_finding(findings, field=field, category="sycophancy", pattern_id="SYC_PRAISE_SANDWICH", severity="error", excerpt=nfc, message=f"Praise-before-critique sandwich ({matched_praise!r}).", remediation=rem)
                break

    grand_text = _EXEMPT_COMPOUND_FUSION_RE.sub(" [term] ", nfc)
    for pat in _GRAND_BRANDING_PATTERNS:
        m = pat.search(grand_text)
        if m:
            _add_finding(findings, field=field, category="integrity", pattern_id="RPT_GRAND_BRANDING", severity="error", excerpt=nfc, message=f"Grandiose or coined method branding: {m.group(0)!r}.", remediation="Use plain component names and cite exact lineage.")
            break

    for pat in _PROBLEM_INFLATION_PATTERNS:
        m = pat.search(exempted)
        if m:
            _add_finding(findings, field=field, category="parsimony", pattern_id="PI01", severity="error", excerpt=nfc, message=f"Dramatized problem-inflation framing: {m.group(0)!r}.", remediation="Replace apocalyptic framing with measured error magnitude and simplest baseline check.")
            break

    return _count_words(nfc)


def _citation_matches_sources(cit: str, sources_list: list[dict[str, Any]]) -> bool:
    if not sources_list:
        return False
    nfc_cit = _normalize_nfc(cit)
    low = nfc_cit.strip().lower()
    src_ids = {_normalize_nfc(str(s.get("id", ""))).strip().lower() for s in sources_list if s.get("id")}
    src_blobs = [
        _normalize_nfc(" ".join(str(s.get(k, "")) for k in ("id", "title", "locator", "url"))).lower()
        for s in sources_list
    ]
    if low.startswith("[") and low.endswith("]"):
        inner = low[1:-1].strip()
        if inner in src_ids or low in src_ids:
            return True
        return any(re.search(rf"(?<!\d){re.escape(low)}(?!\d)", b) for b in src_blobs)
    if low.startswith("arxiv:"):
        clean_id = re.sub(r"^arxiv:\s*", "arxiv:", low)
        arxiv_num = clean_id.split(":", 1)[1]
        return any(
            re.search(rf"(?<![\w.]){re.escape(clean_id)}(?!\w)", b)
            or re.search(rf"(?<![\d.]){re.escape(arxiv_num)}(?!\d)", b)
            for b in src_blobs
        )
    if low.startswith("10."):
        return any(re.search(rf"(?<![\w.]){re.escape(low)}(?!\w)", b) for b in src_blobs)
    all_authors = [m.group(1).lower() for m in re.finditer(rf"({_AUTHOR_SURNAME})", nfc_cit)]
    has_multi_or_etal = bool(re.search(r"\bet\s+al\.?\b|\s(?:&|and|và)\s", nfc_cit, re.I))
    authors = all_authors if has_multi_or_etal else ([a for a in all_authors if a not in _NON_AUTHOR_TOKENS] or all_authors)
    m_yr = re.search(r"((?:19|20)\d{2})", nfc_cit)
    if authors:
        yr = m_yr.group(1) if m_yr else ""
        au_res = [re.compile(rf"(?<!\w){re.escape(au)}(?!\w)", re.UNICODE) for au in authors]
        yr_re = re.compile(rf"(?<!\d){re.escape(yr)}(?!\d)") if yr else None
        return any(all(r.search(b) for r in au_res) and (yr_re is None or yr_re.search(b)) for b in src_blobs)
    return False


def _check_numeric_and_citation_grounding(
    text: str,
    field: str,
    has_struct_grounding: bool,
    sources_list: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    *,
    grounded_ref_ids: set[str] | None = None,
) -> None:
    if not _nonblank(text):
        return
    nfc = _normalize_nfc(text)
    scrubbed = _STRUCTURAL_REF_SCRUB_RE.sub(" ", nfc)
    scrubbed = re.sub(r"\bv\d+(?:\.\d+)+\b|\b(?:19|20)\d{2}(?:-\d{2}-\d{2})?\b|\b10\.\d{4,9}/\S+|\barXiv:\s*\d{4}\.\d{4,5}(?:v\d+)?\b", " ", scrubbed, flags=re.I)

    ref_ids = grounded_ref_ids or set()
    cits = _extract_inline_citations(nfc)
    any_cit_matched = False
    for cit in cits:
        is_bracket_ref = cit.startswith("[") and cit.endswith("]")
        matched = _citation_matches_sources(cit, sources_list) or (
            is_bracket_ref and cit[1:-1].strip() in ref_ids
        )
        if matched:
            any_cit_matched = True
        if not matched and (is_bracket_ref or bool(sources_list) or not has_struct_grounding):
            _add_finding(findings, field=field, category="integrity", pattern_id="UNGROUNDED_CITATION", severity="error", excerpt=text, message=f"Citation {cit!r} has no locator or matching entry in sources.", remediation="Add a matching source record and locator.")
            break

    has_bracket_id_cue = bool(ref_ids) and any(m.group(1) in ref_ids for m in _BRACKET_REF_RE.finditer(nfc))
    has_inline_cue = bool(_INLINE_LOCATOR_CUE_RE.search(nfc)) or has_bracket_id_cue or any_cit_matched
    if _METRIC_CLAIM_RE.search(scrubbed) and not (has_struct_grounding or has_inline_cue):
        _add_finding(findings, field=field, category="integrity", pattern_id="UNGROUNDED_NUMERIC_CLAIM", severity="error", excerpt=text, message="Numeric or metric claim lacks a source reference or locator.", remediation="Attach a locator, source_refs, or inline log/table reference.")


def lint_report(
    report: dict[str, Any] | str,
    lang: str = "auto",
    input_text: str = "",
    thresholds: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Lint a report dict (raw or normalized) or raw string for conciseness, plain language, and grounding."""
    limits = {"sentence_max": 30, "sentence_severe": 40, "paragraph_warn": 80, "paragraph_error": 120, "section_warn": 180, "section_error": 260, "total_warn": 550, "total_error": 750}
    if thresholds:
        limits.update(thresholds)

    findings: list[dict[str, Any]] = []
    if isinstance(report, str):
        resolved_lang = detect_language(text=input_text or report, requested=lang)["lang"]
        total_words = _scan_prose_block(report, "raw_text", findings, limits)
        _check_numeric_and_citation_grounding(report, "raw_text", False, [], findings)
    elif isinstance(report, dict):
        resolved_lang = detect_language(text=input_text, payload=report, requested=lang)["lang"]
        norm = normalize_report_input(report, lang=resolved_lang, truncate=False)
        v_sum = norm["verdict"]["summary"]
        if not _nonblank(v_sum):
            _add_finding(findings, field="verdict.summary", category="structure", pattern_id="STRUCT_MISSING_VERDICT", severity="error", excerpt=norm.get("title", ""), message="Report is missing a direct verdict/conclusion summary.", remediation="Add a 1-2 sentence direct conclusion in `verdict`.")

        sources_list = norm.get("sources", [])
        grounded_ref_ids: set[str] = {
            str(src.get("id", "")).strip() for src in sources_list if _nonblank(src.get("id"))
        }
        ev_items = norm.get("key_evidence", [])
        fl_items = norm.get("flaws_and_risks", [])
        changed = True
        while changed:
            changed = False
            for item in (*ev_items, *fl_items):
                item_id = str(item.get("id", "")).strip() if _nonblank(item.get("id")) else ""
                if item_id and item_id not in grounded_ref_ids and _has_grounding(item, grounded_ref_ids):
                    grounded_ref_ids.add(item_id)
                    changed = True

        w_title = _scan_prose_block(norm.get("title", ""), "title", findings, limits)
        v_label = norm["verdict"].get("label", "")
        w_verdict = _scan_prose_block(v_label, "verdict.label", findings, limits)
        w_verdict += _scan_prose_block(v_sum, "verdict.summary", findings, limits)
        v_refs = [str(r).strip() for r in (norm["verdict"].get("evidence_refs") or []) if _nonblank(str(r))]
        v_grounded = bool(v_refs) and all(r in grounded_ref_ids for r in v_refs)
        _check_numeric_and_citation_grounding(v_label, "verdict.label", v_grounded, sources_list, findings, grounded_ref_ids=grounded_ref_ids)
        _check_numeric_and_citation_grounding(v_sum, "verdict.summary", v_grounded, sources_list, findings, grounded_ref_ids=grounded_ref_ids)

        p_note = norm["verdict"].get("parsimony_check", "")
        p_refs = [str(r).strip() for r in (norm["verdict"].get("parsimony_refs") or []) if _nonblank(str(r))]
        p_grounded = (
            bool(norm["verdict"].get("parsimony_grounded"))
            or (bool(p_refs) and all(r in grounded_ref_ids for r in p_refs))
            or (not p_refs and bool(norm["verdict"].get("parsimony_in_verdict")) and v_grounded)
        )
        if _nonblank(p_note):
            w_verdict += _scan_prose_block(p_note, "verdict.parsimony_check", findings, limits)
            _check_numeric_and_citation_grounding(p_note, "verdict.parsimony_check", p_grounded, sources_list, findings, grounded_ref_ids=grounded_ref_ids)

        w_ev = 0
        for idx, ev in enumerate(ev_items, start=1):
            fp = f"key_evidence[{idx}]"
            w_ev += _scan_prose_block(ev.get("claim", ""), f"{fp}.claim", findings, limits)
            w_ev += _scan_prose_block(ev.get("value", ""), f"{fp}.value", findings, limits)
            grounded = _has_grounding(ev, grounded_ref_ids)
            if not grounded:
                _add_finding(findings, field=fp, category="integrity", pattern_id="MISSING_EVIDENCE_LOCATOR", severity="error", excerpt=f"{ev.get('claim', '')} {ev.get('value', '')}".strip(), message=f"Evidence item {ev.get('id', idx)} lacks locator, source_refs, evidence, or source_url.", remediation="Attach exact locator or source reference.")
            _check_numeric_and_citation_grounding(f"{ev.get('claim', '')} {ev.get('value', '')}".strip(), fp, grounded, sources_list, findings, grounded_ref_ids=grounded_ref_ids)

        w_flaws = 0
        for idx, fl in enumerate(fl_items, start=1):
            fp = f"flaws_and_risks[{idx}]"
            w_flaws += _scan_prose_block(fl.get("summary", ""), f"{fp}.summary", findings, limits)
            _check_numeric_and_citation_grounding(fl.get("summary", ""), fp, _has_grounding(fl, grounded_ref_ids), sources_list, findings, grounded_ref_ids=grounded_ref_ids)

        w_steps = 0
        for idx, st in enumerate(norm.get("next_steps", []), start=1):
            fp = f"next_steps[{idx}].action"
            act = st.get("action", "")
            w_steps += _scan_prose_block(act, fp, findings, limits)
            st_grounded = _has_grounding(st, grounded_ref_ids)
            _check_numeric_and_citation_grounding(act, fp, st_grounded, sources_list, findings, grounded_ref_ids=grounded_ref_ids)
            tgt = st.get("target", "")
            if _nonblank(tgt):
                fp_tgt = f"next_steps[{idx}].target"
                w_steps += _scan_prose_block(tgt, fp_tgt, findings, limits)
                _check_numeric_and_citation_grounding(tgt, fp_tgt, st_grounded, sources_list, findings, grounded_ref_ids=grounded_ref_ids)

        w_meta = 0
        meta = norm.get("metadata", {})
        for mkey in ("scope", "coverage_limits"):
            mval = meta.get(mkey, "")
            if _nonblank(mval):
                w_meta += _scan_prose_block(mval, f"metadata.{mkey}", findings, limits)
                _check_numeric_and_citation_grounding(
                    mval, f"metadata.{mkey}", False, sources_list, findings, grounded_ref_ids=grounded_ref_ids
                )

        sec_words = {"verdict": w_verdict, "key_evidence": w_ev, "flaws_and_risks": w_flaws, "next_steps": w_steps}
        for sname, sw in sec_words.items():
            if sw > limits["section_error"]:
                _add_finding(findings, field=sname, category="conciseness", pattern_id="SECTION_BLOAT", severity="error", excerpt=f"{sname}: {sw} words", message=f"Section '{sname}' has {sw} words (max {limits['section_error']}).", remediation=f"Keep section '{sname}' <= {limits['section_warn']} words.")
            elif sw > limits["section_warn"]:
                _add_finding(findings, field=sname, category="conciseness", pattern_id="SECTION_BLOAT", severity="warn", excerpt=f"{sname}: {sw} words", message=f"Section '{sname}' has {sw} words (recommended <= {limits['section_warn']}).", remediation=f"Trim section '{sname}'.")
        total_words = w_title + sum(sec_words.values()) + w_meta
    else:
        raise TypeError("report must be a dict or str")

    if total_words > limits["total_error"]:
        _add_finding(findings, field="report", category="conciseness", pattern_id="TOTAL_REPORT_BLOAT", severity="error", excerpt=f"total_words={total_words}", message=f"Total report prose is {total_words} words (max {limits['total_error']}).", remediation="Cut background and keep executive report concise (1-2 pages).")
    elif total_words > limits["total_warn"]:
        _add_finding(findings, field="report", category="conciseness", pattern_id="TOTAL_REPORT_BLOAT", severity="warn", excerpt=f"total_words={total_words}", message=f"Total report prose is {total_words} words (recommended <= {limits['total_warn']}).", remediation="Trim to <= 550 prose words.")

    err_count = sum(1 for f in findings if f["severity"] == "error")
    warn_count = sum(1 for f in findings if f["severity"] == "warn")
    return {
        "passed": err_count == 0,
        "lang": resolved_lang,
        "error_count": err_count,
        "warn_count": warn_count,
        "risk_count": err_count,
        "total_words": total_words,
        "findings": findings,
    }


# ---------------------------------------------------------------------------
# Capability-Based LaTeX Engine Probing & Safe Escaping
# ---------------------------------------------------------------------------

_LATEX_SPECIAL_MAP = {
    "\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "%": r"\%", "&": r"\&",
    "_": r"\_", "$": r"\$", "#": r"\#", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
    "<": r"\textless{}", ">": r"\textgreater{}", "|": r"\textbar{}",
}
_PDFLATEX_UNICODE_MAP = {
    "≤": r"\ensuremath{\le}", "≥": r"\ensuremath{\ge}", "≈": r"\ensuremath{\approx}",
    "≠": r"\ensuremath{\neq}", "−": "-", "⇐": r"\ensuremath{\Leftarrow}",
    "⇒": r"\ensuremath{\Rightarrow}", "∈": r"\ensuremath{\in}", "∞": r"\ensuremath{\infty}",
    "∑": r"\ensuremath{\sum}", "√": r"\ensuremath{\surd}",
    "±": r"\ensuremath{\pm}", "×": r"\ensuremath{\times}", "·": r"\ensuremath{\cdot}",
    "→": r"\ensuremath{\rightarrow}", "←": r"\ensuremath{\leftarrow}",
    "α": r"\ensuremath{\alpha}", "β": r"\ensuremath{\beta}", "γ": r"\ensuremath{\gamma}",
    "δ": r"\ensuremath{\delta}", "ε": r"\ensuremath{\varepsilon}", "ζ": r"\ensuremath{\zeta}",
    "η": r"\ensuremath{\eta}", "θ": r"\ensuremath{\theta}", "ι": r"\ensuremath{\iota}",
    "κ": r"\ensuremath{\kappa}", "λ": r"\ensuremath{\lambda}", "μ": r"\ensuremath{\mu}",
    "ν": r"\ensuremath{\nu}", "ξ": r"\ensuremath{\xi}", "ο": r"\ensuremath{o}",
    "π": r"\ensuremath{\pi}", "ρ": r"\ensuremath{\rho}", "σ": r"\ensuremath{\sigma}",
    "ς": r"\ensuremath{\varsigma}", "τ": r"\ensuremath{\tau}", "υ": r"\ensuremath{\upsilon}",
    "φ": r"\ensuremath{\varphi}", "χ": r"\ensuremath{\chi}", "ψ": r"\ensuremath{\psi}",
    "ω": r"\ensuremath{\omega}",
    "Α": "A", "Β": "B", "Γ": r"\ensuremath{\Gamma}", "Δ": r"\ensuremath{\Delta}",
    "Ε": "E", "Ζ": "Z", "Η": "H", "Θ": r"\ensuremath{\Theta}",
    "Ι": "I", "Κ": "K", "Λ": r"\ensuremath{\Lambda}", "Μ": "M",
    "Ν": "N", "Ξ": r"\ensuremath{\Xi}", "Ο": "O", "Π": r"\ensuremath{\Pi}",
    "Ρ": "P", "Σ": r"\ensuremath{\Sigma}", "Τ": "T", "Υ": "Y",
    "Φ": r"\ensuremath{\Phi}", "Χ": "X", "Ψ": r"\ensuremath{\Psi}",
    "Ω": r"\ensuremath{\Omega}",
}
_METADATA_UNICODE_MAP = {
    "≤": "<=", "≥": ">=", "≈": "~=", "≠": "!=", "−": "-", "⇐": "<=", "⇒": "=>", "→": "->", "←": "<-",
    "±": "+/-", "×": "x", "·": "*",
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "epsilon", "ζ": "zeta",
    "η": "eta", "θ": "theta", "ι": "iota", "κ": "kappa", "λ": "lambda", "μ": "mu",
    "ν": "nu", "ξ": "xi", "ο": "omicron", "π": "pi", "ρ": "rho", "σ": "sigma",
    "ς": "sigma", "τ": "tau", "υ": "upsilon", "φ": "phi", "χ": "chi", "ψ": "psi",
    "ω": "omega",
    "Α": "A", "Β": "B", "Γ": "Gamma", "Δ": "Delta", "Ε": "E", "Ζ": "Z",
    "Η": "H", "Θ": "Theta", "Ι": "I", "Κ": "K", "Λ": "Lambda", "Μ": "M",
    "Ν": "N", "Ξ": "Xi", "Ο": "O", "Π": "Pi", "Ρ": "P", "Σ": "Sigma",
    "Τ": "T", "Υ": "Y", "Φ": "Phi", "Χ": "X", "Ψ": "Psi", "Ω": "Omega",
}
_SINGLE_PASS_SPECIAL_RE = re.compile(r"[\\{}%&_$#~^<>|]")
_PDFLATEX_UNICODE_RE = re.compile("[" + re.escape("".join(_PDFLATEX_UNICODE_MAP)) + "]")
_BRK_SENTINEL = "\uE000"


def escape_latex(text: Any, *, engine: str = "pdflatex") -> str:
    """Safely normalize to NFC and single-pass escape LaTeX specials and unsafe Unicode."""
    if text is None:
        return ""
    clean = _strip_control_chars(_normalize_nfc(str(text)))
    escaped = _SINGLE_PASS_SPECIAL_RE.sub(lambda m: _LATEX_SPECIAL_MAP[m.group(0)], clean)
    if engine == "pdflatex":
        escaped = _PDFLATEX_UNICODE_RE.sub(lambda m: _PDFLATEX_UNICODE_MAP[m.group(0)], escaped)
    return escaped


def escape_latex_url(url: Any) -> str:
    """Escape URL for inside \\href{URL}{label}, percent-encoding non-ASCII UTF-8."""
    if url is None:
        return ""
    from urllib.parse import quote
    clean = _strip_control_chars(_normalize_nfc(str(url))).strip()
    clean = "".join(quote(ch, safe="") if ord(ch) > 127 else ch for ch in clean)
    clean = clean.replace("\\", "%5C")
    for ch in ("#", "%", "&", "{", "}"):
        clean = clean.replace(ch, f"\\{ch}")
    return clean


def escape_latex_metadata(text: Any) -> str:
    """Escape text for \\hypersetup{pdftitle={...}} without \\ensuremath."""
    if text is None:
        return ""
    clean = _strip_control_chars(_normalize_nfc(str(text)))
    for k, v in _METADATA_UNICODE_MAP.items():
        clean = clean.replace(k, v)
    return _SINGLE_PASS_SPECIAL_RE.sub(lambda m: _LATEX_SPECIAL_MAP[m.group(0)], clean)


def _segment_mixed_token(token: str, lang: str) -> str:
    if lang != "vi":
        parts = re.split(f"({_T5_REQUIRED_CHARS_RE.pattern}+)", token)
        return "".join(
            (r"{\fontencoding{T5}\selectfont " + escape_latex(seg, engine="pdflatex") + "}") if _T5_REQUIRED_CHARS_RE.search(seg) else escape_latex(seg, engine="pdflatex")
            for seg in parts if seg
        )
    parts = re.split(f"({_T1_ONLY_CHARS_RE.pattern}+)", token)
    return "".join(
        (r"{\fontencoding{T1}\selectfont " + escape_latex(seg, engine="pdflatex") + "}") if _T1_ONLY_CHARS_RE.search(seg) else escape_latex(seg, engine="pdflatex")
        for seg in parts if seg
    )


def _format_pdflatex_text(text: Any, lang: str) -> str:
    if text is None:
        return ""
    clean = _strip_control_chars(_normalize_nfc(str(text)))
    if lang != "vi":
        if not _T5_REQUIRED_CHARS_RE.search(clean):
            return escape_latex(clean, engine="pdflatex")
        out: list[str] = []
        for p in re.split(r"(\s+|[-_/—(),:;]+)", clean):
            if not p:
                continue
            if _T5_REQUIRED_CHARS_RE.search(p):
                if _T1_ONLY_CHARS_RE.search(p):
                    out.append(_segment_mixed_token(p, lang))
                else:
                    out.append(r"{\fontencoding{T5}\selectfont " + escape_latex(p, engine="pdflatex") + "}")
            else:
                out.append(escape_latex(p, engine="pdflatex"))
        return "".join(out)
    if not _T1_ONLY_CHARS_RE.search(clean):
        return escape_latex(clean, engine="pdflatex")
    out_vi: list[str] = []
    for p in re.split(r"(\s+|[-_/—(),:;]+)", clean):
        if not p:
            continue
        if _T1_ONLY_CHARS_RE.search(p):
            if _VI_ALL_DIACRITIC_RE.search(p):
                out_vi.append(_segment_mixed_token(p, lang))
            else:
                out_vi.append(r"{\fontencoding{T1}\selectfont " + escape_latex(p, engine="pdflatex") + "}")
        else:
            out_vi.append(escape_latex(p, engine="pdflatex"))
    return "".join(out_vi)


def _guard_leading_bracket(tex: str) -> str:
    return "{[}" + tex[1:] if tex.startswith("[") else tex


def _insert_allowbreak_markers(
    text: str,
    *,
    min_len: int = 16,
    punct_min_len: int = 14,
    chunk_len: int = 10,
) -> str:
    if not text:
        return ""
    parts = re.split(r"(\s+)", _strip_control_chars(_normalize_nfc(text)))
    out: list[str] = []
    for tok in parts:
        if not tok or tok.isspace():
            out.append(tok)
            continue
        has_punct = bool(re.search(r"[/?&=_\-#.]", tok))
        if len(tok) < (punct_min_len if has_punct else min_len):
            out.append(tok)
            continue
        marked = tok.replace("://", "://" + _BRK_SENTINEL)
        marked = re.sub(r"(?<![:/])([/?&=_\-#])(?![/])", lambda m: m.group(1) + _BRK_SENTINEL, marked)
        marked = re.sub(r"(?<![0-9])\.(?![0-9])", "." + _BRK_SENTINEL, marked)
        chunks = [
            re.sub(rf"([^\uE000]{{{chunk_len}}})(?=[^\uE000])", r"\1" + _BRK_SENTINEL, ch)
            if len(ch) >= min_len else ch
            for ch in marked.split(_BRK_SENTINEL)
        ]
        out.append(_BRK_SENTINEL.join(chunks))
    return "".join(out)


def _kpsewhich(filename: str) -> str | None:
    if not shutil.which("kpsewhich"):
        return None
    try:
        proc = subprocess.run(["kpsewhich", filename], capture_output=True, text=True, timeout=5, check=False)
        return proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else None
    except (OSError, subprocess.SubprocessError):
        return None


def _available_vi_fonts() -> list[str]:
    if not shutil.which("fc-list"):
        return []
    try:
        proc = subprocess.run(["fc-list", ":lang=vi", "family"], capture_output=True, text=True, timeout=5, check=False)
        if proc.returncode != 0:
            return []
        families: list[str] = []
        for line in proc.stdout.splitlines():
            for fam in line.split(","):
                f = fam.strip()
                if f and f not in families:
                    families.append(f)
        return families
    except (OSError, subprocess.SubprocessError):
        return []


def _pick_unicode_font(vi_fonts: list[str], preferred_list: list[str]) -> str | None:
    lower_map = {f.lower(): f for f in vi_fonts}
    for cand in preferred_list:
        if cand.lower() in lower_map:
            return lower_map[cand.lower()]
    return vi_fonts[0] if vi_fonts else None


def select_latex_engine(
    lang: str = "en",
    has_vi_chars: bool = False,
    preferred: str = "auto",
    needs_unicode_non_latin: bool = False,
) -> dict[str, Any]:
    """Probe installed TeX engines and supporting packages; never select broken engines."""
    pref = (preferred or "auto").strip().lower()
    if pref not in {"auto", "xelatex", "lualatex", "pdflatex"}:
        raise ValueError(f"Invalid LaTeX engine choice: {preferred!r}")

    candidates = ["xelatex", "lualatex", "pdflatex"] if pref == "auto" else [pref]
    vi_needed = lang == "vi" or has_vi_chars
    reasons: list[str] = []

    for eng in candidates:
        exe = shutil.which(eng)
        if not exe:
            reasons.append(f"{eng}: binary not found in PATH")
            continue
        if eng == "xelatex":
            if not _kpsewhich("fontspec.sty"):
                reasons.append("xelatex: fontspec.sty not found")
                continue
            font = _pick_unicode_font(_available_vi_fonts() if vi_needed else [], ["Be Vietnam Pro", "IBM Plex Sans", "Liberation Sans", "DejaVu Sans", "FreeSans"])
            if vi_needed and not font:
                reasons.append("xelatex: no Vietnamese TTF/OTF font found via fc-list")
                continue
            return {"engine": "xelatex", "path": exe, "font": font or "Latin Modern", "probe_reasons": reasons}
        if eng == "lualatex":
            if not _kpsewhich("fontspec.sty"):
                reasons.append("lualatex: fontspec.sty not found")
                continue
            if not _kpsewhich("luaotfload-main.lua"):
                reasons.append("lualatex: luaotfload-main.lua missing (texlive-luatex not installed)")
                continue
            font = _pick_unicode_font(_available_vi_fonts() if vi_needed else [], ["Be Vietnam Pro", "IBM Plex Sans", "Liberation Sans", "DejaVu Sans", "FreeSans"])
            if vi_needed and not font:
                reasons.append("lualatex: no Vietnamese TTF/OTF font found via fc-list")
                continue
            return {"engine": "lualatex", "path": exe, "font": font or "Latin Modern", "probe_reasons": reasons}
        if eng == "pdflatex":
            if needs_unicode_non_latin:
                reasons.append("pdflatex: cannot render non-Latin scripts (requires xelatex or lualatex+luaotfload)")
                continue
            if vi_needed and not (_kpsewhich("t5enc.def") or _kpsewhich("vietnam.sty")):
                reasons.append("pdflatex: t5enc.def/vietnam.sty (vntex) not found for Vietnamese T5 encoding")
                continue
            has_lm = bool(_kpsewhich("lmodern.sty"))
            return {"engine": "pdflatex", "path": exe, "font": "lmodern" if has_lm else "default", "has_lmodern": has_lm, "probe_reasons": reasons}

    raise RuntimeError("No working LaTeX engine available: " + "; ".join(reasons))


# ---------------------------------------------------------------------------
# LaTeX Document Rendering
# ---------------------------------------------------------------------------


def _collect_report_text(norm: dict[str, Any]) -> str:
    meta = norm.get("metadata", {})
    verdict = norm.get("verdict", {})
    parts = [
        norm.get("report_type", ""),
        norm.get("title", ""),
        verdict.get("label", ""),
        verdict.get("summary", ""),
        verdict.get("parsimony_check", ""),
        meta.get("scope", ""),
        meta.get("coverage_limits", ""),
        meta.get("reading_basis", ""),
        meta.get("search_date", ""),
    ]
    for ev in norm.get("key_evidence", []):
        parts.extend([ev.get("claim", ""), ev.get("value", ""), ev.get("evidence", ""), ev.get("locator", ""), ev.get("status", "")])
        parts.extend(str(r) for r in (ev.get("source_refs") or []) if _nonblank(str(r)))
    for fl in norm.get("flaws_and_risks", []):
        parts.extend([fl.get("summary", ""), fl.get("locator", ""), fl.get("severity", "")])
        parts.extend(str(r) for r in (fl.get("source_refs") or []) if _nonblank(str(r)))
    for st in norm.get("next_steps", []):
        parts.extend([st.get("action", ""), st.get("target", ""), st.get("locator", "")])
    for src in norm.get("sources", []):
        parts.extend([src.get("id", ""), src.get("title", ""), src.get("locator", "")])
    return "\n".join(str(p) for p in parts if p)


def _verdict_colors(status: str) -> tuple[str, str]:
    s = _normalize_status_token(status)
    if s in {"supported", "pass"}:
        return ("ForestGreen!6!White", "ForestGreen!75!Black")
    if s in {"rejected", "fail"}:
        return ("BrickRed!6!White", "BrickRed!80!Black")
    return ("BurntOrange!7!White", "BurntOrange!80!Black")


def render_latex(
    normalized: dict[str, Any],
    lang: str,
    engine: str = "pdflatex",
    font_family: str | None = None,
) -> str:
    """Render normalized executive report dict into clean LaTeX source."""
    loc = LOCALES.get(lang, LOCALES["en"])
    has_vi = bool(_T5_REQUIRED_CHARS_RE.search(_collect_report_text(normalized) + "\n" + "\n".join(loc.values())))

    def _fmt_raw(val: Any) -> str:
        return _format_pdflatex_text(val, lang) if engine == "pdflatex" else escape_latex(val, engine=engine)

    def fmt(val: Any) -> str:
        marked = _insert_allowbreak_markers(str(val or ""), min_len=16, punct_min_len=14, chunk_len=10)
        return _fmt_raw(marked).replace(_BRK_SENTINEL, r"\allowbreak{}")

    def fmt_cell(val: Any, *, chunk_len: int = 8) -> str:
        marked = _insert_allowbreak_markers(str(val or ""), min_len=chunk_len + 1, punct_min_len=8, chunk_len=chunk_len)
        return _guard_leading_bracket(_fmt_raw(marked)).replace(_BRK_SENTINEL, r"\allowbreak{}")

    lines: list[str] = [r"\documentclass[11pt,a4paper]{article}"]
    if engine == "pdflatex":
        if _kpsewhich("cmap.sty"):
            lines.append(r"\usepackage{cmap}")
        lines.append(r"\usepackage[utf8]{inputenc}")
        lines.append(r"\usepackage[T1,T5]{fontenc}" if lang == "vi" else (r"\usepackage[T5,T1]{fontenc}" if has_vi else r"\usepackage[T1]{fontenc}"))
        if _kpsewhich("lmodern.sty"):
            lines.append(r"\usepackage{lmodern}")
    else:
        lines.append(r"\usepackage{fontspec}")
        if font_family and font_family != "Latin Modern":
            opt = "[Renderer=HarfBuzz]" if engine == "lualatex" else ""
            lines.extend([rf"\setmainfont{{{font_family}}}{opt}", rf"\setsansfont{{{font_family}}}{opt}"])

    lines.extend([
        r"\usepackage[margin=2cm,top=1.8cm,bottom=2.0cm]{geometry}",
        r"\setlength{\emergencystretch}{3em}",
        r"\usepackage{booktabs,tabularx,longtable,array,enumitem,parskip}",
        r"\usepackage[dvipsnames]{xcolor}",
        r"\usepackage{tcolorbox,fancyhdr,microtype}",
        r"\DisableLigatures[-]{encoding = *, family = tt*}",
        r"\usepackage[pdfencoding=auto,psdextra,colorlinks=true,linkcolor=NavyBlue,urlcolor=NavyBlue]{hyperref}",
        rf"\hypersetup{{pdftitle={{{escape_latex_metadata(normalized.get('title', ''))}}},pdfauthor={{research-scientist}}}}",
        r"\newcolumntype{L}[1]{>{\raggedright\arraybackslash}p{#1}}",
        r"\pagestyle{fancy}",
        r"\fancyhf{}",
        r"\renewcommand{\headrulewidth}{0pt}",
        rf"\fancyfoot[C]{{\footnotesize\color{{Gray}} {fmt(loc['page_label'])} \thepage}}",
        r"\begin{document}",
    ])

    meta = normalized.get("metadata", {})
    audit_date = meta.get("search_date") or _dt.date.today().isoformat()
    report_type = normalized.get("report_type") or "general"
    lines.extend([
        rf"{{\Large\bfseries {fmt(normalized.get('title', ''))}}}\par",
        rf"{{\small\color{{Gray}} {fmt(loc['subtitle'])} \textbar{{}} {fmt(loc['lbl_task'])}: \texttt{{{fmt(report_type)}}} \textbar{{}} {fmt(loc['lbl_date'])}: {fmt(audit_date)} \textbar{{}} {fmt(loc['lbl_lang'])}: \texttt{{{fmt(lang)}}}}}\par",
        r"\vspace{2pt}\hrule\vspace{8pt}",
    ])

    verdict = normalized["verdict"]
    v_status = verdict.get("status", "provisional")
    v_badge = _status_badge_label(v_status, loc, verdict.get("label", ""))
    col_back, col_frame = _verdict_colors(v_status)
    lines.extend([
        rf"\begin{{tcolorbox}}[colback={col_back},colframe={col_frame},boxrule=0.8pt,leftrule=3pt,arc=2pt,left=8pt,right=8pt,top=6pt,bottom=6pt]",
        rf"\textbf{{{fmt(loc['sec_verdict'])}}} \quad \colorbox{{{col_frame}}}{{\textcolor{{white}}{{\footnotesize\bfseries\ {fmt(v_badge)}\ }}}}\par\vspace{{4pt}}",
        fmt(verdict.get("summary", "")),
    ])
    if _nonblank(verdict.get("parsimony_check")):
        lines.append(rf"\par\vspace{{4pt}}{{\small\textbf{{{fmt(loc['lbl_parsimony'])}:}} {fmt(verdict['parsimony_check'])}}}")
    lines.extend([r"\end{tcolorbox}", r"\vspace{4pt}"])

    lines.append(rf"\subsection*{{{fmt(loc['sec_evidence'])}}}")
    ev_rows = normalized.get("key_evidence", [])
    if ev_rows:
        lines.extend([
            r"{\small\setlength{\tabcolsep}{4pt}",
            r"\begin{tabularx}{\linewidth}{@{}L{0.34\linewidth} L{0.17\linewidth} L{0.30\linewidth} L{0.14\linewidth}@{}}",
            r"\toprule",
            rf"\textbf{{{fmt(loc['col_claim'])}}} & \textbf{{{fmt(loc['col_value'])}}} & \textbf{{{fmt(loc['col_locator'])}}} & \textbf{{{fmt(loc['col_status'])}}} \\",
            r"\midrule",
        ])
        for row in ev_rows:
            loc_parts = [p for p in (row.get("evidence", ""), row.get("locator", "")) if p] or ([", ".join(row["source_refs"])] if row.get("source_refs") else [])
            loc_text = "; ".join(loc_parts) or loc["unverified_tag"]
            loc_cell = rf"\href{{{escape_latex_url(row['source_url'])}}}{{{fmt_cell(loc_text, chunk_len=8)}}}" if _nonblank(row.get("source_url")) else fmt_cell(loc_text, chunk_len=8)
            lines.append(rf"{fmt_cell(row.get('claim', ''), chunk_len=10)} & {fmt_cell(row.get('value', '') or '--', chunk_len=6)} & {loc_cell} & {fmt_cell(row.get('status', ''), chunk_len=5)} \\")
        lines.extend([r"\bottomrule", r"\end{tabularx}", r"}"])
    else:
        lines.append(fmt(loc["none_reported"]))

    lines.append(rf"\subsection*{{{fmt(loc['sec_flaws'])}}}")
    flaws = normalized.get("flaws_and_risks", [])
    if flaws:
        lines.append(r"\begin{itemize}[leftmargin=1.3em,itemsep=2pt,parsep=0pt]")
        for fl in flaws:
            sev = str(fl.get("severity", "medium")).upper()
            loc_sfx = f" ({fmt(fl['locator'])})" if _nonblank(fl.get("locator")) else ""
            lines.append(rf"\item \textbf{{[{fmt(sev)}]}} {fmt(fl.get('summary', ''))}{loc_sfx}")
        lines.append(r"\end{itemize}")
    else:
        lines.append(fmt(loc["none_reported"]))

    lines.append(rf"\subsection*{{{fmt(loc['sec_next_steps'])}}}")
    steps = normalized.get("next_steps", [])
    if steps:
        lines.append(r"\begin{enumerate}[leftmargin=1.5em,itemsep=2pt,parsep=0pt]")
        for st in steps:
            tgt = f" --- \\textit{{{fmt(st['target'])}}}" if _nonblank(st.get("target")) else ""
            lines.append(rf"\item\relax {_guard_leading_bracket(fmt(st.get('action', '')))}{tgt}")
        lines.append(r"\end{enumerate}")
    else:
        lines.append(fmt(loc["none_reported"]))

    sources = normalized.get("sources", [])
    if sources:
        lines.append(rf"\subsection*{{{fmt(loc['sec_sources'])}}}")
        lines.append(r"\begin{itemize}[leftmargin=1.3em,itemsep=1pt,parsep=0pt]")
        for src in sources:
            surl = src.get("url", "")
            tpart = rf"\href{{{escape_latex_url(surl)}}}{{{fmt(src.get('title', ''))}}}" if _nonblank(surl) else fmt(src.get("title", ""))
            lpart = f" — {fmt(src['locator'])}" if _nonblank(src.get("locator")) and src.get("locator") != surl else ""
            lines.append(rf"\item \texttt{{[{fmt(src.get('id', ''))}]}} {tpart}{lpart}")
        lines.append(r"\end{itemize}")

    meta_bits = []
    if _nonblank(meta.get("scope")):
        meta_bits.append(rf"\textbf{{{fmt(loc['lbl_scope'])}}}: {fmt(meta['scope'])}")
    if _nonblank(meta.get("reading_basis")):
        meta_bits.append(rf"\textbf{{{fmt(loc['lbl_basis'])}}}: \texttt{{{fmt(meta['reading_basis'])}}}")
    if _nonblank(meta.get("coverage_limits")):
        meta_bits.append(rf"\textbf{{{fmt(loc['lbl_limits'])}}}: {fmt(meta['coverage_limits'])}")
    lines.extend([
        r"\vspace{6pt}",
        r"\begin{tcolorbox}[colback=Gray!6!White,colframe=Gray!40!White,boxrule=0.5pt,arc=2pt,left=7pt,right=7pt,top=5pt,bottom=5pt]",
        rf"{{\footnotesize \textbf{{{fmt(loc['sec_metadata'])}}}: " + (" \\textbar{} ".join(meta_bits) if meta_bits else fmt(audit_date)) + r"\par",
        rf"\vspace{{2pt}}\textit{{{fmt(loc['footer_disclaimer'])}}}}}",
        r"\end{tcolorbox}",
        r"\end{document}",
        "",
    ])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Isolated Compilation & Post-Compile PyMuPDF Verification
# ---------------------------------------------------------------------------


def compile_pdf(
    tex_source: str,
    pdf_out: Path,
    tex_out: Path | None = None,
    engine: str = "pdflatex",
    timeout: int = 60,
) -> dict[str, Any]:
    """Compile LaTeX source inside an isolated temp directory (2 passes) and copy outputs."""
    pdf_out = Path(pdf_out)
    if tex_out is not None:
        tex_out = Path(tex_out)
        tex_out.parent.mkdir(parents=True, exist_ok=True)
        tex_out.write_text(tex_source, encoding="utf-8")

    with tempfile.TemporaryDirectory(prefix="rs_latex_") as tmpdir:
        tmp_path = Path(tmpdir)
        tex_file, pdf_file = tmp_path / "report.tex", tmp_path / "report.pdf"
        tex_file.write_text(tex_source, encoding="utf-8")

        last_proc: subprocess.CompletedProcess[str] | None = None
        for pass_idx in (1, 2):
            try:
                last_proc = subprocess.run(
                    [engine, "-interaction=nonstopmode", "-halt-on-error", "report.tex"],
                    cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False,
                )
            except subprocess.TimeoutExpired:
                return {
                    "compiled": False, "engine": engine, "pass": pass_idx,
                    "error": f"{engine} timed out after {timeout}s", "log_tail": "",
                }
            if last_proc.returncode != 0:
                log_file = tmp_path / "report.log"
                log_tail = ""
                if log_file.is_file():
                    log_lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
                    err_blocks = [
                        "\n".join(log_lines[max(0, i - 1):min(len(log_lines), i + 3)])
                        for i, ln in enumerate(log_lines) if ln.startswith("!")
                    ]
                    log_tail = "\n---\n".join(err_blocks[:2]) if err_blocks else "\n".join(log_lines[-15:])
                return {
                    "compiled": False, "engine": engine, "pass": pass_idx, "returncode": last_proc.returncode,
                    "error": f"{engine} failed on pass {pass_idx} (rc={last_proc.returncode})",
                    "log_tail": (log_tail or last_proc.stdout)[-800:],
                }

        if not pdf_file.is_file() or pdf_file.stat().st_size == 0:
            return {"compiled": False, "engine": engine, "error": f"{engine} exited 0 but produced missing or empty PDF.", "log_tail": ""}

        pdf_out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(pdf_file, pdf_out)

    return {"compiled": True, "engine": engine, "pdf_path": str(pdf_out), "tex_path": str(tex_out) if tex_out is not None else None}


def verify_pdf_output(pdf_path: Path, expected_text_samples: list[str], lang: str) -> dict[str, Any]:
    """Verify compiled PDF via PyMuPDF (`fitz`): non-empty, >=1 page, zero U+FFFD, intact diacritics."""
    try:
        import fitz  # type: ignore
    except ImportError as exc:
        raise RuntimeError("PyMuPDF (fitz) is required for PDF verification.") from exc

    pdf_path = Path(pdf_path)
    if not pdf_path.is_file() or pdf_path.stat().st_size == 0:
        return {"verified": False, "page_count": 0, "has_replacement_char": False, "missing_chars": [], "missing_phrases": ["<empty_or_missing_pdf>"], "extracted_char_count": 0}

    with fitz.open(str(pdf_path)) as doc:
        page_count = len(doc)
        extracted_nfc = _normalize_nfc("\n".join(page.get_text("text") for page in doc))

    _greek_homoglyphs = str.maketrans("οΑΒΕΖΗΙΚΜΝΟΡΤΥΧ", "oABEZHIKMNOPTYX")

    def _norm_phrase(txt: str) -> str:
        s = unicodedata.normalize("NFKC", txt).replace("\ufe00", "").replace("\u2212", "-")
        s = re.sub(r"\u0338\s*=", "≠", s)
        s = s.translate(_greek_homoglyphs)
        return re.sub(r"\s+", "", s).lower()

    has_replacement = "\ufffd" in extracted_nfc
    extracted_compact = _norm_phrase(extracted_nfc)
    expected_joined = _normalize_nfc("\n".join(s for s in expected_text_samples if _nonblank(s)))
    missing_chars = [ch for ch in sorted(set(_VI_ALL_DIACRITIC_RE.findall(expected_joined))) if ch not in extracted_nfc]
    for ch in sorted(set(re.findall(r"[\u0370-\u03FF]", expected_joined))):
        norm_ch = _norm_phrase(ch)
        if norm_ch and norm_ch not in extracted_compact and ch not in missing_chars:
            missing_chars.append(ch)

    missing_phrases: list[str] = []
    for sample in expected_text_samples[:5]:
        s_nfc = _normalize_nfc(sample).strip()
        if len(s_nfc) < 4:
            continue
        probe = re.sub(r"https?://\S+", "", s_nfc)
        probe_compact = _norm_phrase(probe)
        if len(probe_compact) >= 6 and probe_compact[:36] not in extracted_compact:
            words = [nw for w in re.findall(r"[^\W_]{3,}", probe, re.UNICODE)[:4] if (nw := _norm_phrase(w))]
            if words and not all(w in extracted_compact for w in words):
                missing_phrases.append(s_nfc[:60])

    verified = page_count >= 1 and bool(extracted_nfc.strip()) and not has_replacement and not missing_chars and not missing_phrases
    return {"verified": verified, "page_count": page_count, "has_replacement_char": has_replacement, "missing_chars": missing_chars, "missing_phrases": missing_phrases, "extracted_char_count": len(extracted_nfc)}


# ---------------------------------------------------------------------------
# End-to-End Orchestrator & CLI
# ---------------------------------------------------------------------------


def generate_report(
    payload: dict[str, Any],
    pdf_out: Path,
    *,
    tex_out: Path | None = None,
    lang: str = "auto",
    input_text: str = "",
    engine: str = "auto",
    strict: bool = False,
    compact: bool = False,
) -> dict[str, Any]:
    """Normalize, detect language, lint, probe engine, render LaTeX, compile, and verify PDF."""
    lang_info = detect_language(text=input_text, payload=payload, requested=lang)
    resolved_lang = lang_info["lang"]
    lint_res = lint_report(payload, lang=resolved_lang, input_text=input_text)
    normalized = normalize_report_input(payload, lang=resolved_lang, truncate=True)

    receipt: dict[str, Any] = {
        "status": "ok",
        "pdf_path": None,
        "tex_path": None,
        "lang": resolved_lang,
        "engine": None,
        "page_count": 0,
        "diacritics_verified": False,
        "lint_summary": {"error_count": lint_res["error_count"], "warn_count": lint_res["warn_count"], "total_words": lint_res["total_words"]},
        "lint_findings": lint_res["findings"],
    }
    if not compact:
        receipt["lang_detection"] = lang_info

    if strict and not lint_res["passed"]:
        receipt["status"] = "lint_failed"
    else:
        receipt["tex_path"] = str(tex_out) if tex_out is not None else None
        full_text = _collect_report_text(normalized)
        loc_text = "\n".join(LOCALES.get(resolved_lang, LOCALES["en"]).values())
        eng_info = select_latex_engine(
            lang=resolved_lang,
            has_vi_chars=bool(_T5_REQUIRED_CHARS_RE.search(full_text + "\n" + loc_text)),
            preferred=engine,
            needs_unicode_non_latin=bool(_NON_LATIN_SCRIPT_RE.search(full_text)),
        )
        chosen_engine, chosen_font = eng_info["engine"], eng_info.get("font")
        receipt["engine"] = chosen_engine
        if not compact:
            receipt["font"] = chosen_font

        tex_source = render_latex(normalized, lang=resolved_lang, engine=chosen_engine, font_family=chosen_font)
        comp_res = compile_pdf(tex_source, Path(pdf_out), tex_out=Path(tex_out) if tex_out is not None else None, engine=chosen_engine)
        if not comp_res.get("compiled"):
            receipt["status"] = "compile_failed"
            receipt["compile_error"] = comp_res.get("error", "LaTeX compilation failed")
            receipt["log_tail"] = comp_res.get("log_tail", "")
        else:
            samples = [
                normalized.get("title", ""),
                normalized["verdict"].get("summary", ""),
                normalized["verdict"].get("parsimony_check", ""),
                *[ev.get("claim", "") for ev in normalized.get("key_evidence", [])[:3]],
                *[fl.get("summary", "") for fl in normalized.get("flaws_and_risks", [])[:2]],
            ]
            ver_res = verify_pdf_output(Path(pdf_out), samples, lang=resolved_lang)
            receipt["pdf_path"] = str(pdf_out)
            receipt["page_count"] = ver_res["page_count"]
            receipt["diacritics_verified"] = ver_res["verified"]
            if not compact:
                receipt["verification"] = ver_res
            if not ver_res["verified"]:
                receipt["status"] = "verify_failed"

    if compact and len(receipt["lint_findings"]) > 5:
        receipt["lint_findings_total"] = len(receipt["lint_findings"])
        receipt["lint_findings_truncated"] = True
        receipt["lint_findings"] = receipt["lint_findings"][:5]

    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate concise, plain-language, multilingual LaTeX-to-PDF research reports.")
    parser.add_argument("--input", required=True, help="Path to input JSON report or skill output artifact")
    parser.add_argument("--out", required=True, help="Output PDF file path")
    parser.add_argument("--tex-out", help="Optional path to save generated .tex source")
    parser.add_argument("--lang", default="auto", help="Target report language (auto|vi|en|fr|de|es|...)")
    parser.add_argument("--input-text", default="", help="Optional prior user prompt for language detection")
    parser.add_argument("--engine", default="auto", choices=("auto", "pdflatex", "xelatex", "lualatex"), help="LaTeX engine preference")
    parser.add_argument("--strict", action="store_true", help="Exit 1 on any error/critical lint finding without emitting PDF")
    parser.add_argument("--json", action="store_true", help="Print structured JSON receipt to stdout")
    parser.add_argument("--compact", action="store_true", help="Emit bounded compact stdout receipt (caps lint_findings to 5)")

    args = parser.parse_args(argv)
    try:
        if not isinstance(args.input, str) or not args.input.strip():
            raise ValueError("Empty or invalid path for --input")
        if not isinstance(args.out, str) or not args.out.strip():
            raise ValueError("Empty or invalid path for --out")
        if args.tex_out is not None and (not isinstance(args.tex_out, str) or not args.tex_out.strip()):
            raise ValueError("Empty or invalid path for --tex-out")
        if not isinstance(args.lang, str) or not args.lang.strip():
            raise ValueError("Empty or invalid value for --lang")
        in_path = Path(args.input.strip())
        if not in_path.is_file():
            raise FileNotFoundError(f"Input JSON file not found: {args.input}")
        raw_text = in_path.read_text(encoding="utf-8")
        if not raw_text.strip():
            raise ValueError(f"Input JSON file is empty: {args.input}")
        payload = json.loads(raw_text, parse_constant=lambda tok: (_ for _ in ()).throw(ValueError(f"Non-finite JSON constant not allowed: {tok}")))
        if not isinstance(payload, dict):
            raise ValueError("Input JSON root must be an object.")
        receipt = generate_report(
            payload, Path(args.out.strip()),
            tex_out=Path(args.tex_out.strip()) if args.tex_out is not None else None,
            lang=args.lang.strip(), input_text=args.input_text,
            engine=args.engine, strict=args.strict, compact=args.compact,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, RuntimeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(receipt, ensure_ascii=False, indent=None if args.compact else 2))
    else:
        print(
            f"status={receipt['status']} lang={receipt['lang']} engine={receipt['engine']} "
            f"pages={receipt['page_count']} diacritics_verified={receipt['diacritics_verified']} "
            f"errors={receipt['lint_summary']['error_count']} warns={receipt['lint_summary']['warn_count']}"
        )
    return 0 if receipt["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
