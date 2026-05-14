"""
Utilitaires de classification metier communs aux sources ArnaqueRadar.

Le but est double :
1. conserver un type d'arnaque business compatible avec la base existante
2. enrichir chaque entree avec des signaux plus utiles au reporting
   (`canal`, `nature_technique`, `score_confiance`, preuves de classement)
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

CLASSIFIER_VERSION = "rules_2026_05_v1"

TYPE_ALIASES = {
    "phishing": "phishing",
    "phish": "phishing",
    "hameconnage": "phishing",
    "hameconnage ": "phishing",
    "malware_distribution": "malware_distribution",
    "malware_url": "malware_distribution",
    "malware_download": "malware_distribution",
    "sms_frauduleux": "sms_frauduleux",
    "sms_fraud": "sms_frauduleux",
    "smishing": "sms_frauduleux",
    "violation_rgpd": "violation_rgpd",
    "data_breach": "violation_rgpd",
    "fraude_cpf": "fraude_cpf",
    "arnaque_achat": "arnaque_achat",
    "faux_support": "faux_support",
    "autre": "autre",
}

TYPE_TO_NATURE = {
    "phishing": "phishing",
    "malware_distribution": "malware",
    "sms_frauduleux": "social_engineering",
    "violation_rgpd": "data_breach",
    "fraude_cpf": "identity_fraud",
    "arnaque_achat": "ecommerce_fraud",
    "faux_support": "support_fraud",
    "autre": "autre",
}

TYPE_TO_CANAL = {
    "phishing": "web",
    "malware_distribution": "web",
    "sms_frauduleux": "sms",
    "violation_rgpd": "fuite_donnees",
    "fraude_cpf": "web",
    "arnaque_achat": "web",
    "faux_support": "tel",
    "autre": "web",
}

RULES: list[dict[str, Any]] = [
    {
        "type": "fraude_cpf",
        "nature": "identity_fraud",
        "default_canal": "web",
        "priority": 100,
        "keywords": [
            "cpf",
            "compte formation",
            "moncompteformation",
            "formation.gouv",
        ],
    },
    {
        "type": "faux_support",
        "nature": "support_fraud",
        "default_canal": "tel",
        "priority": 95,
        "keywords": [
            "tech support",
            "support scam",
            "help desk",
            "helpdesk",
            "microsoft support",
            "windows defender",
            "call support",
            "remote access",
            "fake antivirus",
            "apple support",
        ],
    },
    {
        "type": "sms_frauduleux",
        "nature": "social_engineering",
        "default_canal": "sms",
        "priority": 90,
        "keywords": [
            "sms",
            "smishing",
            "text scam",
            "text message",
            "chronopost",
            "colissimo",
            "colis",
            "ups",
            "dhl",
            "fedex",
            "delivery scam",
            "parcel",
            "tracking",
            "voicemail",
        ],
    },
    {
        "type": "arnaque_achat",
        "nature": "ecommerce_fraud",
        "default_canal": "web",
        "priority": 85,
        "keywords": [
            "store scam",
            "shopping scam",
            "fake order",
            "fake invoice",
            "marketplace",
            "leboncoin",
            "vinted",
            "shop scam",
            "payment page",
            "checkout",
            "order call",
            "delivery fee",
            "scam or legit",
            "full review",
            "full investigation",
            "product review",
            "exposed",
            "supplement",
            "commande",
            "paiement",
            "payment",
            "stripe",
            "paypal",
        ],
    },
    {
        "type": "phishing",
        "nature": "phishing",
        "default_canal": "web",
        "priority": 80,
        "keywords": [
            "phish",
            "phishing",
            "login",
            "signin",
            "sign in",
            "verify",
            "verification",
            "webmail",
            "outlook",
            "office365",
            "o365",
            "credential",
            "password",
            "bank account",
            "docusign",
            "secure message",
            "mailbox",
            "impots",
            "ameli",
            "tax refund",
            "account suspended",
        ],
    },
    {
        "type": "violation_rgpd",
        "nature": "data_breach",
        "default_canal": "fuite_donnees",
        "priority": 75,
        "keywords": [
            "data breach",
            "breach",
            "violation",
            "confidentialite",
            "confidentiality",
            "personal data",
            "donnees personnelles",
            "ransomware",
            "unauthorised access",
        ],
    },
]

EMAIL_HINTS = [
    "email",
    "mail",
    "mailbox",
    "webmail",
    "outlook",
    "office365",
    "o365",
    "docusign",
    "invoice",
]
SMS_HINTS = [
    "sms",
    "smishing",
    "text scam",
    "text message",
    "chronopost",
    "colissimo",
    "ups",
    "dhl",
    "fedex",
    "voicemail",
]
PHONE_HINTS = [
    "phone scam",
    "phone",
    "call",
    "hotline",
    "support",
    "help desk",
    "helpdesk",
    "voicemail",
]
DATA_BREACH_HINTS = [
    "data breach",
    "breach",
    "ransomware",
    "leak",
    "fuite",
    "confidentialite",
    "personal data",
    "donnees personnelles",
]
MALWARE_HINTS = [
    "malware",
    "malware_download",
    "trojan",
    "stealer",
    "loader",
    "botnet",
    "payload",
    ".exe",
    ".dll",
    ".msi",
    ".iso",
    ".zip",
    ".rar",
    ".apk",
    "hiddenbin",
]
GENERIC_SOCIAL_HINTS = [
    "scam",
    "fraud",
    "fake",
    "alert",
    "urgent",
]


def normalize_type(raw_type: Any) -> str:
    """Normalise un type business vers le vocabulaire controle du projet."""
    text = _normalize_text(raw_type)
    return TYPE_ALIASES.get(text, "autre")


def normalize_canal(raw_canal: Any, fallback: str = "web") -> str:
    """Force un canal vers le vocabulaire controle attendu."""
    normalized = _normalize_text(raw_canal)
    if normalized in {"web", "sms", "email", "tel", "fuite_donnees"}:
        return normalized
    return fallback


def normalize_nature(raw_nature: Any, fallback: str = "autre") -> str:
    """Force une nature technique vers un vocabulaire court et stable."""
    normalized = _normalize_text(raw_nature)
    allowed = {
        "phishing",
        "malware",
        "data_breach",
        "support_fraud",
        "ecommerce_fraud",
        "identity_fraud",
        "social_engineering",
        "autre",
    }
    if normalized in allowed:
        return normalized
    return fallback


def score_to_float(raw_score: Any, fallback: float = 0.5) -> float:
    """Borne un score de confiance dans [0.0, 1.0]."""
    try:
        score = float(raw_score)
    except (TypeError, ValueError):
        score = fallback
    return round(min(max(score, 0.0), 1.0), 3)


def join_keywords(values: Any) -> str:
    """Convertit une liste de mots-clés vers une chaine stable dedoublonnee."""
    if values is None:
        raw_values: list[str] = []
    elif str(values) in {"<NA>", "nan", "None"}:
        raw_values = []
    elif isinstance(values, str):
        raw_values = [chunk.strip() for chunk in re.split(r"[|,;]+", values)]
    elif isinstance(values, list):
        raw_values = [str(item).strip() for item in values]
    else:
        raw_values = [str(values).strip()]

    seen: set[str] = set()
    results: list[str] = []
    for value in raw_values:
        if not value or value in seen:
            continue
        seen.add(value)
        results.append(value)
    return "|".join(results)


def classify_signal(
    texts: list[Any],
    *,
    seed_type: Any = "",
    seed_canal: Any = "",
    type_raw: Any = "",
    source_category_raw: Any = "",
    score_override: float | None = None,
    classifier_version: str = CLASSIFIER_VERSION,
) -> dict[str, Any]:
    """
    Classe un signal brut vers le schema metier enrichi ArnaqueRadar.

    Le type business reste volontairement borne au vocabulaire existant.
    La richesse analytique est surtout apportee par `nature_technique`,
    `canal`, `score_confiance` et les preuves de classement.
    """
    haystack = " ".join(_normalize_text(value) for value in texts if str(value or "").strip())
    seed_type_norm = normalize_type(seed_type)
    all_matched_keywords: list[str] = []

    if seed_type_norm != "autre":
        matched = _gather_keywords(haystack, _keywords_for_type(seed_type_norm))
        canal = normalize_canal(seed_canal, fallback=_infer_canal(haystack, seed_type_norm))
        nature = TYPE_TO_NATURE.get(seed_type_norm, "autre")
        score = score_to_float(score_override, fallback=0.96 if matched else 0.9)
        all_matched_keywords.extend(matched)
        return {
            "type": seed_type_norm,
            "canal": canal,
            "nature_technique": nature,
            "score_confiance": score,
            "type_raw": _stringify(type_raw) or _stringify(seed_type),
            "source_category_raw": _stringify(source_category_raw),
            "keywords_matched": _dedupe_keywords(all_matched_keywords),
            "classifier_version": classifier_version,
        }

    best_rule: dict[str, Any] | None = None
    best_matches: list[str] = []
    for rule in RULES:
        matched = _gather_keywords(haystack, rule["keywords"])
        if not matched:
            continue
        if best_rule is None:
            best_rule = rule
            best_matches = matched
            continue
        current_score = (len(matched), int(rule["priority"]))
        best_score = (len(best_matches), int(best_rule["priority"]))
        if current_score > best_score:
            best_rule = rule
            best_matches = matched

    if best_rule is not None:
        all_matched_keywords.extend(best_matches)
        score = score_to_float(score_override, fallback=min(0.96, 0.72 + 0.08 * len(best_matches)))
        return {
            "type": best_rule["type"],
            "canal": normalize_canal(seed_canal, fallback=_infer_canal(haystack, best_rule["type"])),
            "nature_technique": best_rule["nature"],
            "score_confiance": score,
            "type_raw": _stringify(type_raw) or _stringify(seed_type),
            "source_category_raw": _stringify(source_category_raw),
            "keywords_matched": _dedupe_keywords(all_matched_keywords),
            "classifier_version": classifier_version,
        }

    malware_matches = _gather_keywords(haystack, MALWARE_HINTS)
    if malware_matches:
        score = score_to_float(score_override, fallback=min(0.85, 0.64 + 0.04 * len(malware_matches)))
        return {
            "type": "malware_distribution",
            "canal": normalize_canal(seed_canal, fallback="web"),
            "nature_technique": "malware",
            "score_confiance": score,
            "type_raw": _stringify(type_raw) or _stringify(seed_type),
            "source_category_raw": _stringify(source_category_raw),
            "keywords_matched": _dedupe_keywords(malware_matches),
            "classifier_version": classifier_version,
        }

    social_matches = _gather_keywords(haystack, GENERIC_SOCIAL_HINTS)
    if social_matches:
        score = score_to_float(score_override, fallback=min(0.7, 0.5 + 0.03 * len(social_matches)))
        return {
            "type": "autre",
            "canal": normalize_canal(seed_canal, fallback=_infer_canal(haystack, "autre")),
            "nature_technique": "social_engineering",
            "score_confiance": score,
            "type_raw": _stringify(type_raw) or _stringify(seed_type),
            "source_category_raw": _stringify(source_category_raw),
            "keywords_matched": _dedupe_keywords(social_matches),
            "classifier_version": classifier_version,
        }

    return {
        "type": "autre",
        "canal": normalize_canal(seed_canal, fallback=_infer_canal(haystack, "autre")),
        "nature_technique": "autre",
        "score_confiance": score_to_float(score_override, fallback=0.35),
        "type_raw": _stringify(type_raw) or _stringify(seed_type),
        "source_category_raw": _stringify(source_category_raw),
        "keywords_matched": [],
        "classifier_version": classifier_version,
    }


def _keywords_for_type(type_name: str) -> list[str]:
    """Retourne la liste de mots-clés associee a un type business."""
    for rule in RULES:
        if rule["type"] == type_name:
            return list(rule["keywords"])
    return []


def _infer_canal(haystack: str, type_name: str) -> str:
    """Deduit un canal plausible a partir du texte et du type retenu."""
    if _gather_keywords(haystack, DATA_BREACH_HINTS) or type_name == "violation_rgpd":
        return "fuite_donnees"
    if _gather_keywords(haystack, SMS_HINTS) or type_name == "sms_frauduleux":
        return "sms"
    if _gather_keywords(haystack, EMAIL_HINTS):
        return "email"
    if _gather_keywords(haystack, PHONE_HINTS) or type_name == "faux_support":
        return "tel"
    return TYPE_TO_CANAL.get(type_name, "web")


def _gather_keywords(haystack: str, keywords: list[str]) -> list[str]:
    """Retourne les mots-clés effectivement presents dans le texte."""
    matched: list[str] = []
    for keyword in keywords:
        if keyword and keyword in haystack:
            matched.append(keyword)
    return _dedupe_keywords(matched)


def _dedupe_keywords(keywords: list[str]) -> list[str]:
    """Dedoublonne en conservant l'ordre d'apparition."""
    seen: set[str] = set()
    results: list[str] = []
    for keyword in keywords:
        if not keyword or keyword in seen:
            continue
        seen.add(keyword)
        results.append(keyword)
    return results


def _normalize_text(value: Any) -> str:
    """Normalise un texte vers une forme lowercase ASCII simple."""
    if value is None:
        raw_text = ""
    else:
        raw_text = str(value)
        if raw_text in {"<NA>", "nan", "None"}:
            raw_text = ""

    text = unicodedata.normalize("NFKD", raw_text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9./:_ -]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _stringify(value: Any) -> str:
    """Convertit une valeur quelconque vers une chaine propre."""
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "<na>", "none"} else text
