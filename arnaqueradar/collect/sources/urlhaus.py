"""
Source 1 : URLhaus - collecte historique via les feeds officiels.

Le connecteur privilegie les feeds CSV officiels par pays afin de recuperer
un volume de donnees bien plus large que l'endpoint `recent`, limite aux
3 derniers jours et a 1000 entrees. La collecte reste bornee a moins de
15 000 lignes pour conserver un volume raisonnable.

En secours, si les feeds ne renvoient rien, le connecteur retombe sur
l'endpoint API `recent` de URLhaus avec Auth-Key.
"""

import csv
import logging
import os
from datetime import datetime, timezone
from typing import Any

import requests
from dotenv import load_dotenv

from collect.classification import classify_signal, join_keywords

load_dotenv()

logger = logging.getLogger(__name__)

URLHAUS_RECENT_URL = "https://urlhaus-api.abuse.ch/v1/urls/recent/"
URLHAUS_FEEDS_URL = "https://urlhaus.abuse.ch/feeds/"
REQUEST_TIMEOUT = 20
STREAM_TIMEOUT = (20, 60)
DEFAULT_LIMIT = 100
MAX_LIMIT = 1000
DEFAULT_MAX_ENTRIES = 14999
MAX_ENTRIES = 14999
DEFAULT_FEED_COUNTRIES = (
    "FR",
    "DE",
    "NL",
    "CH",
    "PL",
    "IT",
    "ES",
    "GB",
    "BE",
    "AT",
    "CZ",
    "RO",
    "UA",
    "SE",
    "NO",
    "DK",
    "CA",
    "AU",
    "JP",
    "SG",
    "BR",
    "PT",
    "IE",
    "HU",
    "GR",
    "SK",
    "FI",
    "BG",
    "LT",
    "LV",
)


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


def _max_entries() -> int:
    """Retourne le plafond global de collecte, strictement borne sous 15 000."""
    raw_limit = os.getenv("URLHAUS_MAX_ENTRIES", str(DEFAULT_MAX_ENTRIES)).strip()
    try:
        limit = int(raw_limit)
    except ValueError:
        return DEFAULT_MAX_ENTRIES

    if limit < 1:
        return 1
    return min(limit, MAX_ENTRIES)


def _feed_countries() -> list[str]:
    """Retourne la liste des pays a interroger via les feeds URLhaus."""
    raw = os.getenv("URLHAUS_FEED_COUNTRIES", ",".join(DEFAULT_FEED_COUNTRIES))
    results: list[str] = []
    seen: set[str] = set()

    for item in raw.split(","):
        country = item.strip().upper()
        if len(country) != 2 or not country.isalpha() or country in seen:
            continue
        seen.add(country)
        results.append(country)

    return results or list(DEFAULT_FEED_COUNTRIES)


def _build_recent_url(limit: int) -> str:
    """Construit l'URL de l'endpoint recent avec sa limite."""
    return f"{URLHAUS_RECENT_URL}limit/{limit}/"


def _build_country_feed_url(country: str) -> str:
    """Construit l'URL du feed CSV URLhaus pour un pays."""
    return f"{URLHAUS_FEEDS_URL}?country={country}&format=csv"


def _coerce_tags(entry: dict[str, Any]) -> list[str]:
    """Normalise la liste de tags URLhaus en minuscules."""
    raw_tags = entry.get("tags", [])
    if not isinstance(raw_tags, list):
        return []
    return [str(tag).strip().lower() for tag in raw_tags if str(tag).strip()]


def _classify_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Construit une classification enrichie depuis les metadonnees URLhaus."""
    blacklists = entry.get("blacklists", {})
    if not isinstance(blacklists, dict):
        blacklists = {}

    tags = _coerce_tags(entry)
    threat = str(entry.get("threat", "") or "").strip().lower()
    url_status = str(entry.get("url_status", "") or "").strip().lower()
    raw_category = "|".join(
        value
        for value in [
            threat,
            url_status,
            *tags,
            str(blacklists.get("spamhaus_dbl", "") or "").strip().lower(),
            str(blacklists.get("surbl", "") or "").strip().lower(),
        ]
        if value
    )

    return classify_signal(
        [
            entry.get("url", ""),
            threat,
            url_status,
            blacklists.get("spamhaus_dbl", ""),
            blacklists.get("surbl", ""),
            " ".join(tags),
        ],
        seed_canal="web",
        type_raw=threat,
        source_category_raw=raw_category,
        classifier_version="urlhaus_rules_v2",
    )


def _infer_type(entry: dict[str, Any]) -> str:
    """Compatibilite historique : retourne uniquement le type business."""
    return _classify_entry(entry)["type"]


def _parse_date(date_added: Any) -> str:
    """Convertit la date URLhaus vers YYYY-MM-DD."""
    text = str(date_added or "").strip()
    if not text:
        return _default_date_iso()

    for fmt in ("%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue

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

    url_status = str(entry.get("url_status", "")).strip()
    if url_status:
        parts.append(f"status: {url_status}")

    feed_country = str(entry.get("feed_country", "")).strip()
    if feed_country:
        parts.append(f"country: {feed_country}")

    feed_asn = str(entry.get("feed_asn", "")).strip()
    if feed_asn:
        parts.append(f"asn: {feed_asn}")

    spamhaus_status = str(blacklists.get("spamhaus_dbl", "")).strip()
    if spamhaus_status:
        parts.append(f"spamhaus_dbl: {spamhaus_status}")

    return "URLhaus" if not parts else f"URLhaus - {' | '.join(parts)}"


def _normalize_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Normalise une entree URLhaus vers le schema commun."""
    url = str(entry.get("url", "")).strip().rstrip("/")
    if not url:
        return None

    classification = _classify_entry(entry)

    return {
        "url": url,
        "type": classification["type"],
        "source": "urlhaus",
        "date_signalement": _parse_date(entry.get("date_added")),
        "verified": True,
        "titre": _build_title(entry),
        "canal": classification["canal"],
        "nature_technique": classification["nature_technique"],
        "score_confiance": classification["score_confiance"],
        "type_raw": classification["type_raw"],
        "source_category_raw": classification["source_category_raw"],
        "keywords_matched": join_keywords(classification["keywords_matched"]),
        "classifier_version": classification["classifier_version"],
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


def _parse_feed_row(row: list[str], country: str) -> dict[str, Any] | None:
    """Convertit une ligne de feed URLhaus en entree normalisee."""
    if len(row) < 4:
        return None

    entry: dict[str, Any] = {
        "date_added": row[0].strip(),
        "url": row[1].strip(),
        "url_status": row[2].strip(),
        "threat": row[3].strip(),
        "tags": [],
        "blacklists": {},
        "feed_asn": row[6].strip() if len(row) > 6 else "",
        "feed_country": row[7].strip() if len(row) > 7 else country,
    }
    return _normalize_entry(entry)


def _fetch_country_feed(country: str, limit: int) -> list[dict[str, Any]]:
    """
    Lit un feed CSV URLhaus officiel et en extrait au plus `limit` entrees.
    """
    results: list[dict[str, Any]] = []
    if limit <= 0:
        return results

    with requests.get(
        _build_country_feed_url(country),
        headers={"User-Agent": "ArnaqueRadar/1.0"},
        timeout=STREAM_TIMEOUT,
        stream=True,
    ) as response:
        response.raise_for_status()

        for raw_line in response.iter_lines(decode_unicode=True):
            if len(results) >= limit:
                break

            if raw_line is None:
                continue

            line = str(raw_line).strip("\ufeff").strip()
            if not line or line.startswith("#"):
                continue

            parsed = next(csv.reader([line]))
            normalized = _parse_feed_row(parsed, country)
            if normalized is not None:
                results.append(normalized)

    return results


def _collect_feed_entries(limit: int) -> list[dict[str, Any]]:
    """
    Agrège plusieurs feeds URLhaus jusqu'au plafond global configure.
    """
    results: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for country in _feed_countries():
        if len(results) >= limit:
            break

        remaining = limit - len(results)
        try:
            feed_entries = _fetch_country_feed(country, remaining)
        except requests.RequestException as exc:
            logger.warning("URLhaus : feed pays %s indisponible - %s", country, exc)
            continue
        except ValueError as exc:
            logger.warning("URLhaus : feed pays %s invalide - %s", country, exc)
            continue

        for entry in feed_entries:
            url = str(entry.get("url", "")).strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            results.append(entry)
            if len(results) >= limit:
                break

    return results


def collect_urlhaus() -> list[dict[str, Any]]:
    """
    Collecte les URLs URLhaus via les feeds historiques officiels.

    Strategie :
    1. Feeds CSV par pays, cumules jusqu'au plafond configure
    2. API `recent` en secours si aucun feed n'est exploitable
    """
    max_entries = _max_entries()

    feed_results = _collect_feed_entries(max_entries)
    if feed_results:
        logger.info("URLhaus : %d URLs historiques collectees via les feeds.", len(feed_results))
        return feed_results

    auth_key = os.getenv("URLHAUS_AUTH_KEY", "").strip()
    if not auth_key:
        logger.error(
            "URLhaus : aucun feed exploitable et URLHAUS_AUTH_KEY manquante pour le fallback recent."
        )
        return []

    limit = min(_recent_limit(), max_entries)

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

    logger.info("URLhaus : %d URLs recentes collectees via l'API de secours.", len(results))
    return results
