"""
Bootstrap dedie pour alimenter Hive avec des donnees reelles PhishStats.

Ce module se lance volontairement en dehors du pipeline de collecte afin de
separer clairement :
- l'alimentation du stockage Big Data (PhishStats -> Hive)
- la lecture de la source 5 pendant `1_collecter.py` (Hive -> pipeline)
"""

from __future__ import annotations

import argparse
import logging
import math
import os
import time
from datetime import date, datetime
from typing import Any

import requests

from bootstrap import load_project_env
from pipeline.collect.classification import classify_signal
from pipeline.collect.sources.hive_logs import (
    CREATE_TABLE_QUERY,
    HIVE_TABLE,
    _ensure_table_schema,
    _get_connection_params,
)

load_project_env()

logger = logging.getLogger("hive_bootstrap")

PHISHSTATS_API_URL = os.getenv(
    "PHISHSTATS_API_URL",
    "https://api.phishstats.info/api/phishing",
)
PHISHSTATS_USER_AGENT = "ArnaqueRadar/1.0 (hive bootstrap)"


def _env_int(name: str, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    """Lit un entier d'environnement avec bornes de securite."""
    raw_value = os.getenv(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError:
        value = default

    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _env_float(name: str, default: float, minimum: float | None = None) -> float:
    """Lit un flottant d'environnement avec borne basse."""
    raw_value = os.getenv(name, str(default)).strip()
    try:
        value = float(raw_value)
    except ValueError:
        value = default

    if minimum is not None:
        value = max(minimum, value)
    return value


def _phishstats_target_rows() -> int:
    """Volume cible de lignes reelles a charger dans Hive."""
    return _env_int("HIVE_PHISHSTATS_TARGET_ROWS", 50000, minimum=1, maximum=50000)


def _phishstats_page_size() -> int:
    """Taille de page API, bornee a la limite officielle PhishStats."""
    return _env_int("HIVE_PHISHSTATS_PAGE_SIZE", 100, minimum=1, maximum=100)


def _phishstats_delay_seconds() -> float:
    """Delai entre 2 appels pour respecter la limite officielle."""
    return _env_float("HIVE_PHISHSTATS_REQUEST_DELAY_SECONDS", 6.5, minimum=0.0)


def _phishstats_timeout_seconds() -> int:
    """Timeout reseau par requete HTTP."""
    return _env_int("HIVE_PHISHSTATS_TIMEOUT_SECONDS", 30, minimum=5, maximum=120)


def _phishstats_retry_after_seconds() -> float:
    """Temps d'attente de secours sur 429 si l'API ne fournit pas de header explicite."""
    return _env_float("HIVE_PHISHSTATS_RETRY_AFTER_SECONDS", 60.0, minimum=5.0)


def _phishstats_max_retries() -> int:
    """Nombre maximal de retries reseau par page."""
    return _env_int("HIVE_PHISHSTATS_MAX_RETRIES", 12, minimum=1, maximum=30)


def _phishstats_insert_batch_size() -> int:
    """Nombre de lignes inserees par requete Hive INSERT."""
    return _env_int("HIVE_PHISHSTATS_INSERT_BATCH_SIZE", 250, minimum=25, maximum=500)


def _phishstats_force_refresh() -> bool:
    """Force un rechargement complet de la table Hive."""
    return os.getenv("HIVE_PHISHSTATS_FORCE_REFRESH", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }


def _safe_int(value: Any, default: int = 1) -> int:
    """Convertit une valeur numerique incertaine vers int positif."""
    try:
        parsed = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _parse_date_to_iso(raw_value: Any) -> str:
    """Transforme une date API vers le format ISO YYYY-MM-DD."""
    if hasattr(raw_value, "date"):
        try:
            return raw_value.date().isoformat()
        except Exception:
            pass

    raw_text = str(raw_value or "").strip()
    if not raw_text:
        return date.today().isoformat()

    candidate = raw_text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(candidate).date().isoformat()
    except ValueError:
        pass

    try:
        return datetime.strptime(raw_text[:10], "%Y-%m-%d").date().isoformat()
    except ValueError:
        return date.today().isoformat()


def _normalize_phishstats_record(record: dict[str, Any]) -> dict[str, Any] | None:
    """Projette un enregistrement PhishStats sur le schema brut Hive."""
    url = str(record.get("url", "") or "").strip().rstrip("/")
    if not url:
        return None

    tags = record.get("tags") or []
    tags_text = "|".join(str(tag).strip() for tag in tags if str(tag).strip()) if isinstance(tags, list) else str(tags).strip()
    title = str(record.get("title", "") or "").strip()
    brand = str(record.get("brand", "") or "").strip()
    family = str(record.get("family", "") or "").strip()
    host = str(record.get("host", "") or "").strip()
    domain = str(record.get("domain", "") or "").strip()
    source_category_raw = "|".join(
        str(value).strip()
        for value in [
            family,
            brand,
            record.get("countrycode"),
            tags_text,
        ]
        if str(value or "").strip()
    )
    classification = classify_signal(
        [
            url,
            title,
            tags_text,
            host,
            domain,
            brand,
            family,
        ],
        type_raw="phishstats",
        source_category_raw=source_category_raw,
        classifier_version="hive_phishstats_rules_v2",
    )

    region = (
        str(record.get("countryname", "") or "").strip()
        or str(record.get("regionname", "") or "").strip()
        or str(record.get("countrycode", "") or "").strip()
    )
    nb_signalements = max(
        _safe_int(record.get("n_times_seen_host"), default=1),
        _safe_int(record.get("n_times_seen_domain"), default=1),
        1,
    )

    return {
        "url_pattern": url,
        "type_arnaque": classification["type"],
        "region": region,
        "event_date": _parse_date_to_iso(record.get("date") or record.get("date_update")),
        "nb_signalements": nb_signalements,
        "title": title,
        "brand": brand,
        "family": family,
        "tags": tags_text,
        "host": host,
        "domain": domain,
    }


def _build_phishstats_params(page: int) -> dict[str, Any]:
    """Construit les parametres officiels de pagination PhishStats."""
    return {
        "_p": page,
        "_size": _phishstats_page_size(),
        "_sort": "-date",
    }


def _fetch_phishstats_page(session: requests.Session, page: int) -> list[dict[str, Any]]:
    """Recupere une page PhishStats avec retries sur 429/5xx."""
    max_attempts = _phishstats_max_retries()
    for attempt in range(1, max_attempts + 1):
        response = session.get(
            PHISHSTATS_API_URL,
            params=_build_phishstats_params(page),
            timeout=_phishstats_timeout_seconds(),
        )

        if response.status_code == 429 and attempt < max_attempts:
            header_value = str(response.headers.get("Retry-After", "") or "").strip()
            try:
                retry_after = float(header_value)
            except ValueError:
                retry_after = _phishstats_retry_after_seconds()
            logger.warning(
                "PhishStats : rate limit sur la page %d (tentative %d/%d), retry dans %.1fs.",
                page,
                attempt,
                max_attempts,
                retry_after,
            )
            time.sleep(retry_after)
            continue

        if response.status_code >= 500 and attempt < max_attempts:
            retry_after = min(_phishstats_retry_after_seconds(), 15.0)
            logger.warning(
                "PhishStats : erreur serveur %d sur la page %d (tentative %d/%d), retry dans %.1fs.",
                response.status_code,
                page,
                attempt,
                max_attempts,
                retry_after,
            )
            time.sleep(retry_after)
            continue

        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("PhishStats : reponse JSON inattendue (liste attendue).")
        return payload

    raise RuntimeError(f"PhishStats : impossible de lire la page {page}.")


def _fetch_phishstats_records(target_rows: int) -> list[dict[str, Any]]:
    """Collecte jusqu'a `target_rows` enregistrements reels depuis PhishStats."""
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/json",
            "User-Agent": PHISHSTATS_USER_AGENT,
        }
    )

    collected: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    page = 1
    page_size = _phishstats_page_size()
    min_pages = math.ceil(target_rows / page_size)

    while len(collected) < target_rows:
        payload = _fetch_phishstats_page(session, page)
        if not payload:
            break

        for record in payload:
            normalized = _normalize_phishstats_record(record)
            if not normalized:
                continue

            dedup_key = (normalized["url_pattern"], normalized["event_date"])
            if dedup_key in seen_keys:
                continue

            seen_keys.add(dedup_key)
            collected.append(normalized)
            if len(collected) >= target_rows:
                break

        if page == 1 or page % 25 == 0:
            logger.info(
                "PhishStats : page %d traitee, %d lignes retenues.",
                page,
                len(collected),
            )

        if len(payload) < page_size:
            break

        page += 1
        if len(collected) < target_rows:
            time.sleep(_phishstats_delay_seconds())

    if len(collected) < target_rows:
        logger.warning(
            "PhishStats : %d lignes obtenues sur %d attendues.",
            len(collected),
            target_rows,
        )
    else:
        logger.info(
            "PhishStats : objectif atteint (%d lignes, environ %d pages).",
            len(collected),
            min_pages,
        )

    return collected[:target_rows]


def _escape_sql(value: str) -> str:
    """Echappe une chaine simple pour une insertion Hive en SQL."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _render_insert_values(row: dict[str, Any]) -> str:
    """Construit une ligne SQL VALUES compatible Hive."""
    return (
        "('{url}', '{type_arnaque}', '{region}', CAST('{event_date}' AS DATE), {nb_signalements}, "
        "'{title}', '{brand}', '{family}', '{tags}', '{host}', '{domain}')"
    ).format(
        url=_escape_sql(str(row["url_pattern"])),
        type_arnaque=_escape_sql(str(row["type_arnaque"])),
        region=_escape_sql(str(row["region"])),
        event_date=_escape_sql(str(row["event_date"])),
        nb_signalements=int(row["nb_signalements"]),
        title=_escape_sql(str(row.get("title", "") or "")),
        brand=_escape_sql(str(row.get("brand", "") or "")),
        family=_escape_sql(str(row.get("family", "") or "")),
        tags=_escape_sql(str(row.get("tags", "") or "")),
        host=_escape_sql(str(row.get("host", "") or "")),
        domain=_escape_sql(str(row.get("domain", "") or "")),
    )


def _count_rows(cursor) -> int:
    """Compte les lignes presentes dans la table Hive."""
    cursor.execute(f"SELECT COUNT(*) FROM {HIVE_TABLE}")
    return _safe_int(cursor.fetchone()[0], default=0)


def _reset_table(cursor) -> None:
    """Vide la table Hive pour un rechargement complet."""
    try:
        cursor.execute(f"TRUNCATE TABLE {HIVE_TABLE}")
    except Exception:
        logger.warning("Hive bootstrap : TRUNCATE indisponible, recreation de la table.")
        cursor.execute(f"DROP TABLE IF EXISTS {HIVE_TABLE}")
        cursor.execute(CREATE_TABLE_QUERY)


def _load_rows_into_hive(cursor, rows: list[dict[str, Any]]) -> None:
    """Insere les lignes PhishStats dans Hive par lots raisonnables."""
    batch_size = _phishstats_insert_batch_size()
    total_rows = len(rows)
    for start in range(0, total_rows, batch_size):
        batch = rows[start:start + batch_size]
        values_sql = ", ".join(_render_insert_values(row) for row in batch)
        cursor.execute(
            f"""
            INSERT INTO TABLE {HIVE_TABLE}
            VALUES {values_sql}
            """
        )

        batch_index = (start // batch_size) + 1
        if batch_index == 1 or batch_index % 20 == 0 or start + batch_size >= total_rows:
            logger.info(
                "Hive bootstrap : lot %d insere (%d/%d lignes).",
                batch_index,
                min(start + batch_size, total_rows),
                total_rows,
            )


def bootstrap_hive_from_phishstats(*, target_rows: int | None = None, force_refresh: bool | None = None) -> int:
    """
    Alimente explicitement la table Hive avec des donnees reelles PhishStats.

    Retourne le nombre de lignes presentes dans Hive apres l'operation.
    """
    target = target_rows if target_rows is not None else _phishstats_target_rows()
    force = force_refresh if force_refresh is not None else _phishstats_force_refresh()

    from pyhive import hive

    conn = hive.connect(**_get_connection_params())
    cursor = conn.cursor()
    try:
        cursor.execute(CREATE_TABLE_QUERY)
        added_columns = _ensure_table_schema(cursor)
        row_count = _count_rows(cursor)
        if not force and row_count >= target and not added_columns:
            logger.info(
                "Hive bootstrap : table deja suffisamment chargee (%d lignes >= cible %d).",
                row_count,
                target,
            )
            return row_count
        if added_columns and row_count > 0 and not force:
            logger.info(
                "Hive bootstrap : schema etendu (%s), rechargement force pour retroalimenter les metadonnees.",
                ", ".join(added_columns),
            )

        rows = _fetch_phishstats_records(target)
        if not rows:
            raise RuntimeError("PhishStats : aucune ligne reelle recuperee pour Hive.")

        _reset_table(cursor)
        _ensure_table_schema(cursor)
        _load_rows_into_hive(cursor, rows)
        final_count = _count_rows(cursor)
        logger.info("Hive bootstrap : %d lignes presentes dans %s.", final_count, HIVE_TABLE)
        return final_count
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


def main() -> None:
    """Point d'entree CLI du bootstrap Hive PhishStats."""
    parser = argparse.ArgumentParser(description="Charge Hive avec des donnees reelles PhishStats.")
    parser.add_argument(
        "--target",
        type=int,
        default=_phishstats_target_rows(),
        help="Nombre cible de lignes a charger dans Hive (defaut: env HIVE_PHISHSTATS_TARGET_ROWS).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force un rechargement complet meme si Hive contient deja assez de lignes.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    final_count = bootstrap_hive_from_phishstats(target_rows=args.target, force_refresh=args.force)
    print(f"Hive bootstrap termine : {final_count} lignes presentes dans {HIVE_TABLE}.")


if __name__ == "__main__":
    main()
