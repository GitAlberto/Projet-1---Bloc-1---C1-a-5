"""
Source 2 : Cybermalveillance.gouv.fr - collecte via flux Atom officiel.

Ce module telecharge le flux Atom des actualites publie par
Cybermalveillance.gouv.fr pour extraire les articles recents. En cas
d'echec reseau ou de reponse invalide, un mecanisme de fallback lit le
fichier CSV local data/fallback_cybermalveillance.csv.
"""

import csv
import logging
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

ATOM_FEED_URL = "https://www.cybermalveillance.gouv.fr/feed/atom-flux-actualites"
FALLBACK_PATH = Path(__file__).resolve().parents[2] / "data" / "fallback_cybermalveillance.csv"
REQUEST_TIMEOUT = 20
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


def _normalize_article(url: str, titre: str, date_str: str) -> dict[str, Any]:
    """
    Normalise un article extrait du flux Atom vers le schema commun.
    """
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        date_iso = dt.date().isoformat()
    except (ValueError, TypeError, AttributeError):
        date_iso = datetime.now(timezone.utc).date().isoformat()

    return {
        "url": url.strip().rstrip("/"),
        "type": "phishing",
        "source": "cybermalveillance",
        "date_signalement": date_iso,
        "titre": unescape(titre.strip()),
    }


def _parse_atom_feed(xml_text: str) -> list[dict[str, Any]]:
    """
    Parse le flux Atom officiel Cybermalveillance.

    Retourne :
        list[dict] : liste d'articles normalises.

    Leve :
        ValueError : si la reponse XML est invalide ou vide.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"flux Atom invalide ({exc})") from exc

    entries = root.findall("atom:entry", ATOM_NS)
    if not entries:
        raise ValueError("aucune entree trouvee dans le flux Atom")

    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    for entry in entries:
        title_text = entry.findtext("atom:title", default="", namespaces=ATOM_NS).strip()
        link_node = entry.find("atom:link[@href]", ATOM_NS)
        url = ""
        if link_node is not None:
            url = str(link_node.get("href", "")).strip()
        if not url:
            url = entry.findtext("atom:id", default="", namespaces=ATOM_NS).strip()
        if not url:
            continue

        normalized_url = url.rstrip("/")
        if normalized_url in seen:
            continue
        seen.add(normalized_url)

        published = entry.findtext("atom:published", default="", namespaces=ATOM_NS).strip()
        updated = entry.findtext("atom:updated", default="", namespaces=ATOM_NS).strip()
        date_str = published or updated

        results.append(_normalize_article(normalized_url, title_text or "Sans titre", date_str))

    if not results:
        raise ValueError("aucune URL exploitable trouvee dans le flux Atom")

    return results


def _fetch_articles() -> list[dict[str, Any]]:
    """
    Telecharge puis parse le flux Atom des actualites Cybermalveillance.
    """
    response = requests.get(
        ATOM_FEED_URL,
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": "ArnaqueRadar/1.0"},
    )
    response.raise_for_status()
    return _parse_atom_feed(response.text)


def _load_fallback() -> list[dict[str, Any]]:
    """
    Charge les entrees de secours depuis le fichier CSV local.
    """
    results = []
    if not FALLBACK_PATH.exists():
        logger.error("Cybermalveillance : fichier fallback introuvable - %s", FALLBACK_PATH)
        return results

    with open(FALLBACK_PATH, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            results.append(
                {
                    "url": row.get("url", "").strip().rstrip("/"),
                    "type": row.get("type", "phishing"),
                    "source": "cybermalveillance",
                    "date_signalement": row.get("date_signalement", ""),
                    "titre": row.get("titre", ""),
                }
            )

    return results


def collect_cybermalveillance() -> list[dict[str, Any]]:
    """
    Collecte les actualites Cybermalveillance depuis leur flux Atom officiel.

    En cas d'echec reseau ou de flux invalide, active automatiquement
    le fallback CSV local et enregistre un WARNING.
    """
    try:
        results = _fetch_articles()
        logger.info("Cybermalveillance : %d articles collectes via le flux Atom.", len(results))
        return results
    except (requests.RequestException, ValueError, Exception) as exc:
        logger.warning(
            "Cybermalveillance : flux Atom indisponible (%s), activation du fallback CSV.", exc
        )
        results = _load_fallback()
        logger.info("Cybermalveillance : %d entrees chargees depuis le fallback.", len(results))
        return results
