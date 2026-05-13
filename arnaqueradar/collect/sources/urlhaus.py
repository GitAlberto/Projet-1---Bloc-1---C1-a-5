"""
Source 1 : URLhaus API - collecte stricte via l'API officielle.

Ce module interroge l'endpoint recent URLs de URLhaus pour recuperer les
ajouts recents et les normaliser vers le schema commun ArnaqueRadar.
Contrairement a un feed local ou a un fallback de demonstration, cette
source depend exclusivement de l'API HTTP officielle et de son Auth-Key.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

URLHAUS_RECENT_URL = "https://urlhaus-api.abuse.ch/v1/urls/recent/"
REQUEST_TIMEOUT = 20
DEFAULT_LIMIT = 100
MAX_LIMIT = 1000


def _default_date_iso() -> str:
    """Retourne la date UTC du jour au format ISO."""
    return datetime.now(timezone.utc).date().isoformat()


def _recent_limit() -> int:
    """Retourne une limite API bornee entre 1 et 1000."""
    raw_limit = os.getenv("URLHAUS_RECENT_LIMIT", str(DEFAULT_LIMIT)).strip()
    try:
        limit = int(raw_limit)
    except ValueError:
        return DEFAULT_LIMIT

    if limit < 1:
        return 1
    return min(limit, MAX_LIMIT)


def _build_recent_url(limit: int) -> str:
    """Construit l'URL de l'endpoint recent avec sa limite."""
    return f"{URLHAUS_RECENT_URL}limit/{limit}/"


def _coerce_tags(entry: dict[str, Any]) -> list[str]:
    """Normalise la liste de tags URLhaus en minuscules."""
    raw_tags = entry.get("tags", [])
    if not isinstance(raw_tags, list):
        return []
    return [str(tag).strip().lower() for tag in raw_tags if str(tag).strip()]


def _infer_type(entry: dict[str, Any]) -> str:
    """
    Deduit le type d'arnaque ArnaqueRadar a partir des tags et metadonnees.

    URLhaus est surtout oriente malware. On mappe seulement les cas assez
    explicites et on range le reste dans "autre".
    """
    blacklists = entry.get("blacklists", {})
    if not isinstance(blacklists, dict):
        blacklists = {}

    indicators = [
        * _coerce_tags(entry),
        str(blacklists.get("spamhaus_dbl", "")).strip().lower(),
        str(blacklists.get("surbl", "")).strip().lower(),
        str(entry.get("threat", "")).strip().lower(),
        str(entry.get("url", "")).strip().lower(),
    ]
    indicator_text = " ".join(item for item in indicators if item)

    if "smish" in indicator_text or "sms" in indicator_text:
        return "sms_frauduleux"
    if "phish" in indicator_text:
        return "phishing"
    if "support" in indicator_text or "helpdesk" in indicator_text:
        return "faux_support"
    if "cpf" in indicator_text:
        return "fraude_cpf"
    if any(token in indicator_text for token in ("marketplace", "leboncoin", "checkout", "payment", "paiement")):
        return "arnaque_achat"
    return "autre"


def _parse_date(date_added: Any) -> str:
    """Convertit la date URLhaus vers YYYY-MM-DD."""
    text = str(date_added or "").strip()
    if not text:
        return _default_date_iso()

    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S UTC").date().isoformat()
    except ValueError:
        return _default_date_iso()


def _build_title(entry: dict[str, Any]) -> str:
    """Construit un titre court a partir des metadonnees URLhaus."""
    tags = _coerce_tags(entry)
    blacklists = entry.get("blacklists", {})
    if not isinstance(blacklists, dict):
        blacklists = {}

    parts: list[str] = []
    threat = str(entry.get("threat", "")).strip()
    if threat:
        parts.append(f"threat: {threat}")
    if tags:
        parts.append(f"tags: {', '.join(tags)}")

    spamhaus_status = str(blacklists.get("spamhaus_dbl", "")).strip()
    if spamhaus_status:
        parts.append(f"spamhaus_dbl: {spamhaus_status}")

    return "URLhaus" if not parts else f"URLhaus - {' | '.join(parts)}"


def _normalize_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Normalise une entree URLhaus vers le schema commun."""
    url = str(entry.get("url", "")).strip().rstrip("/")
    if not url:
        return None

    return {
        "url": url,
        "type": _infer_type(entry),
        "source": "urlhaus",
        "date_signalement": _parse_date(entry.get("date_added")),
        "verified": True,
        "titre": _build_title(entry),
    }


def _fetch_recent_urls(auth_key: str, limit: int) -> list[dict[str, Any]]:
    """Interroge URLhaus et retourne la liste brute des URLs recentes."""
    response = requests.get(
        _build_recent_url(limit),
        headers={
            "Auth-Key": auth_key,
            "User-Agent": "ArnaqueRadar/1.0",
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("reponse JSON inattendue")

    status = str(payload.get("query_status", "")).strip().lower()
    if status == "no_results":
        return []
    if status != "ok":
        raise ValueError(f"query_status inattendu: {status or 'vide'}")

    urls = payload.get("urls", [])
    if not isinstance(urls, list):
        raise ValueError("champ 'urls' invalide")
    return [row for row in urls if isinstance(row, dict)]


def collect_urlhaus() -> list[dict[str, Any]]:
    """
    Collecte les URLs recentes depuis l'API officielle URLhaus.

    Sans Auth-Key valide ou si l'API est indisponible, la source retourne une
    liste vide. Aucun fallback local n'est applique afin de conserver une
    definition stricte d'API source.
    """
    auth_key = os.getenv("URLHAUS_AUTH_KEY", "").strip()
    if not auth_key:
        logger.error("URLhaus : URLHAUS_AUTH_KEY manquante.")
        return []

    limit = _recent_limit()

    try:
        raw_entries = _fetch_recent_urls(auth_key, limit)
    except requests.RequestException as exc:
        logger.error("URLhaus : appel API impossible - %s", exc)
        return []
    except ValueError as exc:
        logger.error("URLhaus : reponse invalide - %s", exc)
        return []

    results: list[dict[str, Any]] = []
    for entry in raw_entries:
        normalized = _normalize_entry(entry)
        if normalized is not None:
            results.append(normalized)

    logger.info("URLhaus : %d URLs recentes collectees via l'API.", len(results))
    return results
