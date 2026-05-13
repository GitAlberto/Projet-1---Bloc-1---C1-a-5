"""
Source 1 : Google Web Risk - verification stricte via l'API Lookup.

Ce module ne telecharge pas de feed. Il lit une liste locale d'URLs candidates,
verifie chaque URL via l'API Google Web Risk, puis ne conserve que celles
classees en SOCIAL_ENGINEERING.
"""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

GOOGLE_WEB_RISK_API_URL = "https://webrisk.googleapis.com/v1/uris:search"
THREAT_TYPE = "SOCIAL_ENGINEERING"
REQUEST_TIMEOUT = 20
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CANDIDATES_PATH = PROJECT_ROOT / "data" / "google_web_risk_candidates.txt"


def _default_date_iso() -> str:
    """Retourne la date UTC du jour au format ISO."""
    return datetime.now(timezone.utc).date().isoformat()


def _candidate_path() -> Path:
    """Retourne le chemin du fichier d'URLs candidates a verifier."""
    raw_path = os.getenv("GOOGLE_WEB_RISK_CANDIDATES_PATH", "").strip()
    if not raw_path:
        return DEFAULT_CANDIDATES_PATH

    path = Path(raw_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def _load_candidate_urls(path: Path) -> list[str]:
    """Charge les URLs candidates depuis un fichier texte local."""
    if not path.exists():
        logger.error("Google Web Risk : fichier de candidats introuvable - %s", path)
        return []

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.error("Google Web Risk : fichier de candidats illisible - %s", exc)
        return []

    urls: list[str] = []
    seen: set[str] = set()
    for raw_line in content.splitlines():
        url = raw_line.strip()
        if not url or url.startswith("#"):
            continue
        if not (url.startswith("http://") or url.startswith("https://")):
            continue
        normalized_url = url.rstrip("/")
        if normalized_url in seen:
            continue
        seen.add(normalized_url)
        urls.append(normalized_url)
    return urls


def _search_url(url: str, api_key: str) -> tuple[list[str], str | None]:
    """Interroge Google Web Risk pour une URL et retourne les menaces detectees."""
    response = requests.get(
        GOOGLE_WEB_RISK_API_URL,
        params={
            "uri": url,
            "threatTypes": THREAT_TYPE,
            "key": api_key,
        },
        headers={"User-Agent": "ArnaqueRadar/1.0"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("reponse JSON inattendue")

    threat = payload.get("threat") or {}
    if not isinstance(threat, dict):
        raise ValueError("champ 'threat' invalide")

    threat_types = threat.get("threatTypes", [])
    if threat_types is None:
        threat_types = []
    if not isinstance(threat_types, list):
        raise ValueError("champ 'threatTypes' invalide")

    expire_time = threat.get("expireTime")
    expire_time_text = str(expire_time).strip() if expire_time else None
    return [str(item) for item in threat_types], expire_time_text or None


def _normalize_entry(url: str, expire_time: str | None = None) -> dict[str, Any]:
    """Normalise une URL signalee par Google Web Risk vers le schema commun."""
    normalized = {
        "url": url.rstrip("/"),
        "type": "phishing",
        "source": "google_web_risk",
        "date_signalement": _default_date_iso(),
        "verified": True,
        "titre": "Google Web Risk - SOCIAL_ENGINEERING",
    }
    if expire_time:
        normalized["cache_expire_time"] = expire_time
    return normalized


def collect_google_web_risk() -> list[dict[str, Any]]:
    """
    Verifie une liste d'URLs candidates via Google Web Risk.

    L'API Lookup supporte une seule URL par requete. Le connecteur lit donc
    un fichier local d'URLs candidates puis ne conserve que les URL classees
    en SOCIAL_ENGINEERING par Google.
    """
    api_key = os.getenv("GOOGLE_WEB_RISK_API_KEY", "").strip()
    if not api_key:
        logger.error("Google Web Risk : GOOGLE_WEB_RISK_API_KEY manquante.")
        return []

    candidate_urls = _load_candidate_urls(_candidate_path())
    if not candidate_urls:
        logger.warning("Google Web Risk : aucune URL candidate a verifier.")
        return []

    results: list[dict[str, Any]] = []
    for url in candidate_urls:
        try:
            threat_types, expire_time = _search_url(url, api_key)
        except requests.RequestException as exc:
            logger.warning("Google Web Risk : verification echouee pour %s (%s).", url, exc)
            continue
        except ValueError as exc:
            logger.warning("Google Web Risk : reponse invalide pour %s (%s).", url, exc)
            continue

        if THREAT_TYPE in threat_types:
            results.append(_normalize_entry(url, expire_time))

    logger.info(
        "Google Web Risk : %d URLs confirmees en %s sur %d candidates.",
        len(results),
        THREAT_TYPE,
        len(candidate_urls),
    )
    return results
