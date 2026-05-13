"""
Source 2 : Cybermalveillance.gouv.fr - collecte via pages officielles.

Ce module privilegie l'extraction des articles depuis plusieurs pages
officielles du blog Cybermalveillance.gouv.fr afin de recuperer un jeu de
donnees plus riche que le flux Atom, limite a 20 entrees. En cas d'echec
reseau ou de changement de structure HTML, un repli est tente sur le flux
Atom officiel, puis sur le fichier CSV local
data/fallback_cybermalveillance.csv.
"""

import csv
import logging
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

BLOG_SECTION_URLS = [
    "https://www.cybermalveillance.gouv.fr/blog",
    "https://www.cybermalveillance.gouv.fr/blog/cybermenace",
    "https://www.cybermalveillance.gouv.fr/blog/a-la-une",
    "https://www.cybermalveillance.gouv.fr/blog/gip",
]
ATOM_FEED_URL = "https://www.cybermalveillance.gouv.fr/feed/atom-flux-actualites"
FALLBACK_PATH = Path(__file__).resolve().parents[2] / "data" / "fallback_cybermalveillance.csv"
REQUEST_TIMEOUT = 20
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


def _normalize_date(date_str: str) -> str:
    """
    Convertit une date Atom ou une date francaise JJ/MM/AAAA en ISO.
    """
    raw_date = date_str.strip()
    if not raw_date:
        return datetime.now(timezone.utc).date().isoformat()

    try:
        return datetime.fromisoformat(raw_date.replace("Z", "+00:00")).date().isoformat()
    except (ValueError, TypeError, AttributeError):
        pass

    for fmt in ("%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw_date, fmt).date().isoformat()
        except ValueError:
            continue

    return datetime.now(timezone.utc).date().isoformat()


def _normalize_article(url: str, titre: str, date_str: str) -> dict[str, Any]:
    """
    Normalise un article extrait du flux Atom vers le schema commun.
    """
    return {
        "url": url.strip().rstrip("/"),
        "type": "phishing",
        "source": "cybermalveillance",
        "date_signalement": _normalize_date(date_str),
        "titre": unescape(titre.strip()),
    }


def _parse_blog_page(html_text: str, page_url: str) -> list[dict[str, Any]]:
    """
    Parse une page officielle du blog Cybermalveillance.

    Seules les cartes d'articles sont conservees afin d'eviter les liens du
    menu, des encarts et des alertes permanentes du site.
    """
    soup = BeautifulSoup(html_text, "html.parser")
    cards = soup.select("article.post-small")
    if not cards:
        raise ValueError("aucune carte d'article trouvee dans la page HTML")

    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    for card in cards:
        link_node = card.select_one("a[href*='/tous-nos-contenus/actualites/']")
        title_node = card.select_one("h1, h2, h3, h4")
        if link_node is None or title_node is None:
            continue

        url = urljoin(page_url, str(link_node.get("href", "")).strip()).rstrip("/")
        if not url or url in seen:
            continue

        date_node = card.select_one(".date")
        date_str = date_node.get_text(" ", strip=True) if date_node else ""
        title_text = title_node.get_text(" ", strip=True)
        if not title_text:
            continue

        seen.add(url)
        results.append(_normalize_article(url, title_text, date_str))

    if not results:
        raise ValueError("aucune URL exploitable trouvee dans la page HTML")

    return results


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


def _fetch_articles_from_blog() -> list[dict[str, Any]]:
    """
    Telecharge plusieurs pages officielles du blog et agrege les articles.
    """
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    for section_url in BLOG_SECTION_URLS:
        response = requests.get(
            section_url,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": "ArnaqueRadar/1.0"},
        )
        response.raise_for_status()

        for entry in _parse_blog_page(response.text, section_url):
            url = entry["url"]
            if url in seen:
                continue
            seen.add(url)
            results.append(entry)

    if not results:
        raise ValueError("aucun article collecte depuis les pages officielles")

    return results


def _fetch_articles_from_atom() -> list[dict[str, Any]]:
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
    Collecte les actualites Cybermalveillance depuis les pages officielles.

    Ordre de priorite :
    1. Pages HTML officielles du blog
    2. Flux Atom officiel
    3. Fallback CSV local
    """
    try:
        results = _fetch_articles_from_blog()
        logger.info(
            "Cybermalveillance : %d articles collectes via les pages officielles.",
            len(results),
        )
        return results
    except (requests.RequestException, ValueError) as exc:
        logger.warning(
            "Cybermalveillance : pages officielles indisponibles (%s), tentative via flux Atom.",
            exc,
        )
        try:
            results = _fetch_articles_from_atom()
            logger.info("Cybermalveillance : %d articles collectes via le flux Atom.", len(results))
            return results
        except (requests.RequestException, ValueError) as atom_exc:
            logger.warning(
                "Cybermalveillance : flux Atom indisponible (%s), activation du fallback CSV.",
                atom_exc,
            )
            results = _load_fallback()
            logger.info("Cybermalveillance : %d entrees chargees depuis le fallback.", len(results))
            return results
