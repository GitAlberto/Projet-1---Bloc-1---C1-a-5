"""
Source 5 : Apache Hive - collecte Big Data depuis un chargement PhishStats.

Cette source represente un stockage analytique massif alimente depuis
PhishStats, puis interroge via HiveServer2. Au premier chargement,
la table Hive est peuplee avec un volume cible de lignes reelles
depuis l'API PhishStats. Les executions suivantes reutilisent les
donnees deja presentes dans Hive pour eviter de repaginer 50k lignes
a chaque run.
"""

import json
import logging
import math
import os
import subprocess
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from collect.classification import classify_signal, join_keywords

load_dotenv()

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
CACHE_PATH = DATA_DIR / "hive_phishstats_cache.json"

HIVE_TABLE = "logs_arnaques"
PHISHSTATS_API_URL = os.getenv(
    "PHISHSTATS_API_URL",
    "https://api.phishstats.info/api/phishing",
)
PHISHSTATS_USER_AGENT = "ArnaqueRadar/1.0 (academic project)"

CREATE_TABLE_QUERY = f"""
    CREATE TABLE IF NOT EXISTS {HIVE_TABLE} (
        url_pattern STRING,
        type_arnaque STRING,
        region STRING,
        event_date DATE,
        nb_signalements INT
    )
"""
CURRENT_YEAR_WHERE = "WHERE YEAR(event_date) = YEAR(CURRENT_DATE)"
HIVE_QUERY_WITH_COUNT_TEMPLATE = f"""
    SELECT url_pattern AS url,
           type_arnaque AS type,
           region,
           SUM(COALESCE(nb_signalements, 1)) AS nb_signalements,
           MIN(event_date) AS date_signalement
    FROM {HIVE_TABLE}
    {{where_clause}}
    GROUP BY url_pattern, type_arnaque, region
"""
HIVE_QUERY_LEGACY_TEMPLATE = f"""
    SELECT url_pattern AS url,
           type_arnaque AS type,
           region,
           COUNT(*) AS nb_signalements,
           MIN(event_date) AS date_signalement
    FROM {HIVE_TABLE}
    {{where_clause}}
    GROUP BY url_pattern, type_arnaque, region
"""
HIVE_QUERY_ROWS_TEMPLATE = f"""
    SELECT url_pattern AS url,
           type_arnaque AS type,
           region,
           COALESCE(nb_signalements, 1) AS nb_signalements,
           event_date AS date_signalement
    FROM {HIVE_TABLE}
    {{where_clause}}
    ORDER BY event_date DESC
"""
HIVE_QUERY_ROWS_LEGACY_TEMPLATE = f"""
    SELECT url_pattern AS url,
           type_arnaque AS type,
           region,
           1 AS nb_signalements,
           event_date AS date_signalement
    FROM {HIVE_TABLE}
    {{where_clause}}
    ORDER BY event_date DESC
"""


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


def _env_bool(name: str, default: bool = False) -> bool:
    """Interprete une variable d'environnement booleenne classique."""
    raw_value = os.getenv(name, "true" if default else "false").strip().lower()
    return raw_value in {"1", "true", "yes", "y", "on"}


def _phishstats_target_rows() -> int:
    """Volume cible de lignes reelles a maintenir dans Hive."""
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
    return _env_bool("HIVE_PHISHSTATS_FORCE_REFRESH", False)


def _hive_fallback_cache_target_rows() -> int:
    """
    Volume minimum attendu pour le cache reel si Hive est indisponible.

    Ce volume reste volontairement plus faible que le bootstrap Hive complet
    afin de conserver des temps de fallback raisonnables.
    """
    return _env_int("HIVE_FALLBACK_CACHE_TARGET_ROWS", 500, minimum=1, maximum=10000)


def _hive_fallback_refresh_rows() -> int:
    """
    Volume cible d'un refresh direct du cache quand Hive est indisponible.

    On garde un objectif volontairement plus raisonnable que le stockage Hive
    complet pour limiter le risque de rate limiting lors d'un simple fallback.
    """
    return _env_int("HIVE_FALLBACK_REFRESH_ROWS", 500, minimum=100, maximum=2000)


def _hive_cache_max_age_hours() -> int:
    """Duree maximale de reutilisation directe du cache local."""
    return _env_int("HIVE_CACHE_MAX_AGE_HOURS", 24, minimum=1, maximum=168)


def _beeline_bridge_enabled() -> bool:
    """Autorise le pont live via beeline si pyhive echoue."""
    return _env_bool("HIVE_ENABLE_BEELINE_BRIDGE", True)


def _beeline_container_name() -> str:
    """Nom du conteneur HiveServer2 utilise pour le pont live beeline."""
    return os.getenv("HIVE_BEELINE_CONTAINER", "arnaqueradar-hive-1").strip() or "arnaqueradar-hive-1"


def _hive_query_mode() -> str:
    """Mode d'extraction Hive : lignes brutes ou agregats."""
    mode = os.getenv("HIVE_QUERY_MODE", "rows").strip().lower()
    return mode if mode in {"rows", "aggregate"} else "rows"


def _current_year_filter_enabled() -> bool:
    """Controle le filtrage annuel des requetes Hive.

    Par defaut, les aggregats restent limites a l'annee courante alors que
    le mode `rows` expose tout le stock live pour l'analyse volumique.
    """
    raw_value = os.getenv("HIVE_FILTER_CURRENT_YEAR")
    if raw_value is not None and raw_value.strip():
        return _env_bool("HIVE_FILTER_CURRENT_YEAR", False)
    return _hive_query_mode() == "aggregate"


def _render_hive_query(template: str, filter_current_year: bool) -> str:
    """Injecte proprement le WHERE optionnel dans un template SQL Hive."""
    where_clause = CURRENT_YEAR_WHERE if filter_current_year else ""
    return template.format(where_clause=where_clause)


def _get_connection_params() -> dict[str, Any]:
    """Construit les parametres de connexion Hive depuis l'environnement."""
    return {
        "host": os.getenv("HIVE_HOST", "localhost"),
        "port": int(os.getenv("HIVE_PORT", "10000")),
        "username": os.getenv("HIVE_USER", "hive"),
        "database": os.getenv("HIVE_DB", "default"),
        "auth": os.getenv("HIVE_AUTH", "NOSASL"),
    }


def _normalize_hive_row(row: dict[str, Any]) -> dict[str, Any]:
    """Normalise une ligne extraite de Hive vers le schema commun."""
    date_val = row.get("date_signalement")
    if hasattr(date_val, "isoformat"):
        date_iso = date_val.isoformat()
    else:
        date_iso = str(date_val) if date_val else date.today().isoformat()

    raw_type = str(row.get("type", "autre") or "autre").strip().lower()
    region = str(row.get("region", "") or "").strip()
    url = str(row.get("url", "")).strip().rstrip("/")
    classification = classify_signal(
        [url, raw_type, region],
        seed_type=raw_type,
        type_raw=raw_type,
        source_category_raw="hive_logs",
        classifier_version="hive_logs_rules_v2",
    )
    classification = _refine_generic_hive_classification(url, classification)

    return {
        "url": url,
        "type": classification["type"],
        "source": "hive_logs",
        "date_signalement": date_iso,
        "region": region,
        "nb_signalements": int(row.get("nb_signalements", 1) or 1),
        "canal": classification["canal"],
        "nature_technique": classification["nature_technique"],
        "score_confiance": classification["score_confiance"],
        "type_raw": classification["type_raw"],
        "source_category_raw": classification["source_category_raw"],
        "keywords_matched": join_keywords(classification["keywords_matched"]),
        "classifier_version": classification["classifier_version"],
    }


def _refine_generic_hive_classification(url: str, classification: dict[str, Any]) -> dict[str, Any]:
    """Requalifie certains `autre` Hive tres techniques en distribution de malware."""
    if classification.get("type") != "autre":
        return classification

    lowered_url = str(url or "").lower()
    malware_signals = []
    if "/arquivo_" in lowered_url:
        malware_signals.append("arquivo_")
    if "get.php?" in lowered_url:
        malware_signals.append("get.php")
    if any(lowered_url.endswith(ext) for ext in (".txt", ".png", ".jpg", ".jpeg", ".gif", ".apk")):
        malware_signals.append("payload_extension")

    if not malware_signals:
        return classification

    refined = dict(classification)
    refined["type"] = "malware_distribution"
    refined["nature_technique"] = "malware"
    refined["score_confiance"] = max(float(classification.get("score_confiance", 0.0) or 0.0), 0.62)
    refined["keywords_matched"] = list(classification.get("keywords_matched", [])) + malware_signals
    return refined


def _escape_sql(value: str) -> str:
    """Echappe une chaine simple pour une insertion Hive en SQL."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


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


def _infer_type_from_record(record: dict[str, Any]) -> str:
    """Infere un type d'arnaque coherent depuis les champs PhishStats."""
    tags = record.get("tags") or []
    if isinstance(tags, list):
        tags_text = " ".join(str(tag) for tag in tags)
    else:
        tags_text = str(tags)

    haystack = " ".join(
        [
            str(record.get("url", "") or ""),
            str(record.get("title", "") or ""),
            tags_text,
            str(record.get("host", "") or ""),
            str(record.get("domain", "") or ""),
        ]
    ).lower()

    sms_keywords = ["sms", "smishing", "chronopost", "colis", "livraison", "ups", "dhl", "fedex"]
    cpf_keywords = ["cpf", "compte formation", "formation.gouv", "moncompteformation"]
    support_keywords = ["tech support", "support", "microsoft", "windows defender", "help desk"]
    shop_keywords = ["leboncoin", "marketplace", "commande", "order", "payment", "paiement", "invoice", "shop"]

    if any(keyword in haystack for keyword in sms_keywords):
        return "sms_frauduleux"
    if any(keyword in haystack for keyword in cpf_keywords):
        return "fraude_cpf"
    if any(keyword in haystack for keyword in support_keywords):
        return "faux_support"
    if any(keyword in haystack for keyword in shop_keywords):
        return "arnaque_achat"
    return "phishing"


def _normalize_phishstats_record(record: dict[str, Any]) -> dict[str, Any] | None:
    """Projette un enregistrement PhishStats sur le schema brut Hive."""
    url = str(record.get("url", "") or "").strip().rstrip("/")
    if not url:
        return None

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
    tags = record.get("tags") or []
    tags_text = " ".join(str(tag) for tag in tags) if isinstance(tags, list) else str(tags)
    source_category_raw = "|".join(
        str(value).strip()
        for value in [
            record.get("family"),
            record.get("brand"),
            record.get("countrycode"),
            tags_text,
        ]
        if str(value or "").strip()
    )
    classification = classify_signal(
        [
            url,
            record.get("title", ""),
            tags_text,
            record.get("host", ""),
            record.get("domain", ""),
            record.get("brand", ""),
        ],
        type_raw="phishstats",
        source_category_raw=source_category_raw,
        classifier_version="hive_phishstats_rules_v2",
    )

    return {
        "url_pattern": url,
        "type_arnaque": classification["type"],
        "region": region,
        "event_date": _parse_date_to_iso(record.get("date") or record.get("date_update")),
        "nb_signalements": nb_signalements,
    }


def _build_phishstats_params(page: int) -> dict[str, Any]:
    """Construit les parametres officiels de pagination PhishStats."""
    return {
        "_p": page,
        "_size": _phishstats_page_size(),
        "_sort": "-date",
    }


def _fetch_phishstats_page(session: requests.Session, page: int) -> list[dict[str, Any]]:
    """Recupere une page PhishStats avec retries simples sur 429/5xx."""
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
                "Hive/PhishStats : rate limit sur la page %d (tentative %d/%d), nouvelle tentative dans %.1fs.",
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
                "Hive/PhishStats : erreur serveur %d sur la page %d (tentative %d/%d), retry dans %.1fs.",
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
                "Hive/PhishStats : page %d traitee, %d lignes retenues.",
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
            "Hive/PhishStats : %d lignes obtenues sur %d attendues.",
            len(collected),
            target_rows,
        )
    else:
        logger.info(
            "Hive/PhishStats : objectif atteint (%d lignes, environ %d pages).",
            len(collected),
            min_pages,
        )

    return collected[:target_rows]


def _render_insert_values(row: dict[str, Any]) -> str:
    """Construit une ligne SQL VALUES compatible Hive."""
    return (
        "('{url}', '{type_arnaque}', '{region}', CAST('{event_date}' AS DATE), {nb_signalements})"
    ).format(
        url=_escape_sql(str(row["url_pattern"])),
        type_arnaque=_escape_sql(str(row["type_arnaque"])),
        region=_escape_sql(str(row["region"])),
        event_date=_escape_sql(str(row["event_date"])),
        nb_signalements=int(row["nb_signalements"]),
    )


def _latest_raw_dataset_path() -> Path | None:
    """Retourne le dernier brut raw_*.json disponible localement."""
    candidates = sorted(DATA_DIR.glob("raw_*.json"), reverse=True)
    return candidates[0] if candidates else None


def _raw_entry_to_hive_row(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Projette une entree brute existante vers le schema Hive live."""
    url = str(entry.get("url", "") or "").strip().rstrip("/")
    if not url:
        return None

    source = str(entry.get("source", "") or "").strip().lower()
    if source == "hive_logs":
        return None

    return {
        "url_pattern": url,
        "type_arnaque": str(entry.get("type", "autre") or "autre").strip().lower(),
        "region": str(entry.get("region", "") or "").strip(),
        "event_date": _parse_date_to_iso(entry.get("date_signalement")),
        "nb_signalements": _safe_int(entry.get("nb_signalements"), default=1),
    }


def _load_rows_from_latest_raw(target_rows: int) -> list[dict[str, Any]]:
    """Construit un jeu de lignes Hive depuis le dernier brut local du pipeline."""
    raw_path = _latest_raw_dataset_path()
    if raw_path is None:
        raise RuntimeError("Aucun raw_*.json local disponible pour enrichir Hive.")

    with open(raw_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if not isinstance(payload, list):
        raise RuntimeError(f"Contenu inattendu dans {raw_path.name}: liste attendue.")

    rows: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        row = _raw_entry_to_hive_row(entry)
        if row is None:
            continue

        dedup_key = (row["url_pattern"], row["event_date"])
        if dedup_key in seen_keys:
            continue

        seen_keys.add(dedup_key)
        rows.append(row)
        if len(rows) >= target_rows:
            break

    if not rows:
        raise RuntimeError(f"Le brut local {raw_path.name} ne contient aucune ligne exploitable pour Hive.")

    logger.info(
        "Hive : %d lignes preparees depuis le brut local %s pour completer le stockage live.",
        len(rows),
        raw_path.name,
    )
    return rows


def _reset_table(cursor) -> None:
    """Vide la table Hive pour un rechargement complet."""
    try:
        cursor.execute(f"TRUNCATE TABLE {HIVE_TABLE}")
    except Exception:
        logger.warning("Hive : TRUNCATE indisponible, recreation de la table.")
        cursor.execute(f"DROP TABLE IF EXISTS {HIVE_TABLE}")
        cursor.execute(CREATE_TABLE_QUERY)


def _load_rows_into_hive(cursor, rows: list[dict[str, Any]]) -> None:
    """Insere des lignes reelles dans Hive par lots raisonnables."""
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
                "Hive : lot %d insere (%d/%d lignes).",
                batch_index,
                min(start + batch_size, total_rows),
                total_rows,
            )


def _bootstrap_phishstats_table(cursor, target_rows: int) -> int:
    """Recharge completement la table Hive avec des donnees reelles PhishStats."""
    rows = _fetch_phishstats_records(target_rows)
    if not rows:
        raise RuntimeError("Hive/PhishStats : aucune ligne reelle recuperee.")

    _reset_table(cursor)
    _load_rows_into_hive(cursor, rows)
    return len(rows)


def _bootstrap_local_raw_table(cursor, target_rows: int) -> int:
    """Recharge la table Hive a partir du dernier brut local du pipeline."""
    rows = _load_rows_from_latest_raw(target_rows)
    _reset_table(cursor)
    _load_rows_into_hive(cursor, rows)
    return len(rows)


def _table_columns(cursor) -> set[str]:
    """Retourne l'ensemble des colonnes declarees sur logs_arnaques."""
    cursor.execute(f"DESCRIBE {HIVE_TABLE}")
    columns: set[str] = set()
    for row in cursor.fetchall():
        column_name = str(row[0]).strip()
        if not column_name or column_name.startswith("#"):
            continue
        columns.add(column_name)
    return columns


def _ensure_table_ready(cursor) -> None:
    """Cree la table si besoin puis garantit un stock massif PhishStats."""
    cursor.execute(CREATE_TABLE_QUERY)
    cursor.execute(f"SELECT COUNT(*) FROM {HIVE_TABLE}")
    row_count = _safe_int(cursor.fetchone()[0], default=0)

    target_rows = _phishstats_target_rows()
    force_refresh = _phishstats_force_refresh()
    needs_reload = force_refresh or row_count < target_rows

    if not needs_reload:
        logger.info(
            "Hive : table deja chargee (%d lignes >= cible %d).",
            row_count,
            target_rows,
        )
        return

    reason = "rechargement force" if force_refresh else f"stock insuffisant ({row_count} < {target_rows})"
    logger.info("Hive : %s, bootstrap PhishStats en cours.", reason)

    try:
        loaded_rows = _bootstrap_local_raw_table(cursor, target_rows)
        logger.info("Hive : %d lignes chargees depuis le dernier brut local dans %s.", loaded_rows, HIVE_TABLE)
        return
    except Exception as raw_exc:
        logger.info("Hive : bootstrap depuis le brut local indisponible (%s), tentative PhishStats.", raw_exc)

    try:
        loaded_rows = _bootstrap_phishstats_table(cursor, target_rows)
        logger.info("Hive : %d lignes PhishStats chargees dans %s.", loaded_rows, HIVE_TABLE)
    except Exception as exc:
        try:
            loaded_rows = _bootstrap_local_raw_table(cursor, target_rows)
            logger.warning(
                "Hive : rechargement PhishStats echoue (%s). Bootstrap live depuis le dernier brut local (%d lignes).",
                exc,
                loaded_rows,
            )
            return
        except Exception as raw_exc:
            logger.warning(
                "Hive : bootstrap local depuis raw impossible (%s).",
                raw_exc,
            )

        if row_count > 0:
            logger.warning(
                "Hive : rechargement PhishStats echoue (%s). Reutilisation des %d lignes deja presentes.",
                exc,
                row_count,
            )
            return
        raise


def _select_query_for_table(cursor) -> str:
    """Choisit la requete adaptee selon le schema reel de la table."""
    columns = _table_columns(cursor)
    query_mode = _hive_query_mode()
    filter_current_year = _current_year_filter_enabled()

    if query_mode == "aggregate":
        if "nb_signalements" in columns:
            return _render_hive_query(HIVE_QUERY_WITH_COUNT_TEMPLATE, filter_current_year)
        return _render_hive_query(HIVE_QUERY_LEGACY_TEMPLATE, filter_current_year)

    if "nb_signalements" in columns:
        return _render_hive_query(HIVE_QUERY_ROWS_TEMPLATE, filter_current_year)
    return _render_hive_query(HIVE_QUERY_ROWS_LEGACY_TEMPLATE, filter_current_year)


def _save_cache(entries: list[dict[str, Any]]) -> None:
    """Sauvegarde le dernier resultat reel Hive pour repli honnete."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as handle:
        json.dump(entries, handle, ensure_ascii=False, indent=2)


def _load_cache() -> list[dict[str, Any]]:
    """Relit le dernier cache de resultats reels si disponible."""
    if not CACHE_PATH.exists():
        return []

    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(payload, list):
        return []
    return [entry for entry in payload if isinstance(entry, dict)]


def _is_cache_recent() -> bool:
    """Indique si le cache local est suffisamment recent pour etre reutilise tel quel."""
    if not CACHE_PATH.exists():
        return False

    max_age = timedelta(hours=_hive_cache_max_age_hours())
    modified_at = datetime.fromtimestamp(CACHE_PATH.stat().st_mtime, tz=timezone.utc)
    return (datetime.now(timezone.utc) - modified_at) <= max_age


def _rows_to_cache_entries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convertit les lignes brutes PhishStats/Hive vers le schema cache final."""
    entries: list[dict[str, Any]] = []
    for row in rows:
        classification = classify_signal(
            [
                row.get("url_pattern", ""),
                row.get("type_arnaque", ""),
                row.get("region", ""),
            ],
            seed_type=row.get("type_arnaque", ""),
            type_raw=row.get("type_arnaque", ""),
            source_category_raw="phishstats_cache",
            classifier_version="hive_cache_rules_v2",
        )
        entries.append(
            {
                "url": str(row.get("url_pattern", "")).strip().rstrip("/"),
                "type": classification["type"],
                "source": "hive_logs",
                "date_signalement": str(row.get("event_date", "") or date.today().isoformat()),
                "region": str(row.get("region", "") or "").strip(),
                "nb_signalements": int(row.get("nb_signalements", 1) or 1),
                "canal": classification["canal"],
                "nature_technique": classification["nature_technique"],
                "score_confiance": classification["score_confiance"],
                "type_raw": classification["type_raw"],
                "source_category_raw": classification["source_category_raw"],
                "keywords_matched": join_keywords(classification["keywords_matched"]),
                "classifier_version": classification["classifier_version"],
            }
        )
    return [entry for entry in entries if entry["url"]]


def _refresh_cache_without_hive(target_rows: int) -> list[dict[str, Any]]:
    """
    Recharge directement le cache local depuis PhishStats si Hive est KO.

    Cela permet de faire grossir la source 5 meme lorsque HiveServer2 n'est
    pas demarre, tout en conservant un cache honnete base sur des donnees
    reelles et non sur un faux dataset.
    """
    rows = _fetch_phishstats_records(target_rows)
    entries = _rows_to_cache_entries(rows)
    if not entries:
        raise RuntimeError("Hive/PhishStats : aucun resultat exploitable pour le cache local.")
    _save_cache(entries)
    return entries


def _beeline_jdbc_url() -> str:
    """URL JDBC utilisee pour le pont live beeline vers HiveServer2."""
    return "jdbc:hive2://localhost:10000/default;auth=noSasl"


def _beeline_command() -> list[str]:
    """Commande docker exec beeline pour interroger HiveServer2 en live."""
    return [
        "docker",
        "exec",
        "-i",
        _beeline_container_name(),
        "beeline",
        "--silent=true",
        "--showHeader=false",
        "--outputformat=tsv2",
        "-u",
        _beeline_jdbc_url(),
    ]


def _filter_beeline_output(stdout: str) -> list[str]:
    """Nettoie la sortie beeline pour ne garder que les lignes de resultats."""
    ignored_prefixes = (
        "SLF4J:",
        "Connecting to ",
        "Connected to:",
        "Driver:",
        "Transaction isolation:",
        "INFO  :",
        "WARN  :",
        "[WARN]",
        "Beeline version",
        "Closing:",
    )
    ignored_exact = {
        "No such file or directory",
    }

    lines: list[str] = []
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line in ignored_exact:
            continue
        if any(line.startswith(prefix) for prefix in ignored_prefixes):
            continue
        lines.append(line)
    return lines


def _run_beeline_sql(sql: str) -> list[str]:
    """
    Execute une requete SQL sur HiveServer2 via beeline dans le conteneur Docker.

    Ce pont live est active quand pyhive echoue a negocier correctement la
    session Thrift, mais que HiveServer2 reste joignable avec le client JDBC
    natif `beeline`.
    """
    completed = subprocess.run(
        _beeline_command(),
        input=sql,
        text=True,
        capture_output=True,
        check=False,
        timeout=max(_phishstats_timeout_seconds() * 4, 120),
    )

    if completed.returncode != 0:
        stderr = "\n".join(_filter_beeline_output(completed.stderr))
        stdout = "\n".join(_filter_beeline_output(completed.stdout))
        details = stderr or stdout or f"exit code {completed.returncode}"
        raise RuntimeError(f"Beeline live bridge failed: {details}")

    return _filter_beeline_output(completed.stdout)


def _beeline_count_rows() -> int:
    """Compte les lignes presentes dans la table Hive via beeline."""
    lines = _run_beeline_sql(f"SELECT COUNT(*) FROM {HIVE_TABLE};\n")
    if not lines:
        return 0
    return _safe_int(lines[-1], default=0)


def _bootstrap_hive_via_beeline(target_rows: int) -> int:
    """Charge Hive live via un script beeline lorsque pyhive est inutilisable."""
    try:
        rows = _load_rows_from_latest_raw(target_rows)
        source_label = "raw local"
    except Exception as raw_exc:
        logger.info(
            "Hive/beeline : bootstrap depuis le brut local indisponible (%s), tentative PhishStats.",
            raw_exc,
        )
        rows = _fetch_phishstats_records(target_rows)
        source_label = "PhishStats"

    if not rows:
        raise RuntimeError("Hive : aucune ligne exploitable pour le bridge beeline.")

    script_parts = [CREATE_TABLE_QUERY.strip() + ";", f"TRUNCATE TABLE {HIVE_TABLE};"]
    batch_size = _phishstats_insert_batch_size()
    total_rows = len(rows)

    for start in range(0, total_rows, batch_size):
        batch = rows[start:start + batch_size]
        values_sql = ", ".join(_render_insert_values(row) for row in batch)
        script_parts.append(f"INSERT INTO TABLE {HIVE_TABLE} VALUES {values_sql};")

    _run_beeline_sql("\n".join(script_parts) + "\n")
    logger.info("Hive/beeline : chargement live effectue depuis %s.", source_label)
    return len(rows)


def _select_rows_via_beeline() -> list[dict[str, Any]]:
    """Lit les resultats agregees Hive live via beeline en format tsv."""
    if _hive_query_mode() == "aggregate":
        query = _render_hive_query(HIVE_QUERY_WITH_COUNT_TEMPLATE, _current_year_filter_enabled())
    else:
        query = _render_hive_query(HIVE_QUERY_ROWS_TEMPLATE, _current_year_filter_enabled())

    lines = _run_beeline_sql(query.strip() + ";\n")
    rows: list[dict[str, Any]] = []
    for line in lines:
        parts = line.split("\t")
        if len(parts) != 5:
            continue
        rows.append(
            {
                "url": parts[0],
                "type": parts[1],
                "region": parts[2],
                "nb_signalements": _safe_int(parts[3], default=1),
                "date_signalement": parts[4],
            }
        )
    return rows


def _collect_hive_logs_via_beeline_bridge() -> list[dict[str, Any]]:
    """Mode live alternatif : HiveServer2 via beeline/JDBC natif dans le conteneur."""
    _run_beeline_sql(CREATE_TABLE_QUERY.strip() + ";\n")

    row_count = _beeline_count_rows()
    target_rows = _phishstats_target_rows()
    force_refresh = _phishstats_force_refresh()
    needs_reload = force_refresh or row_count < target_rows

    if needs_reload:
        reason = "rechargement force" if force_refresh else f"stock insuffisant ({row_count} < {target_rows})"
        logger.info("Hive/beeline : %s, bootstrap PhishStats en cours.", reason)
        loaded_rows = _bootstrap_hive_via_beeline(target_rows)
        logger.info("Hive/beeline : %d lignes PhishStats chargees dans %s.", loaded_rows, HIVE_TABLE)
    else:
        logger.info(
            "Hive/beeline : table deja chargee (%d lignes >= cible %d).",
            row_count,
            target_rows,
        )

    rows = _select_rows_via_beeline()
    results = [_normalize_hive_row(row) for row in rows]
    _save_cache(results)
    logger.info("Hive/beeline : %d entrees live lues.", len(results))
    return results


def collect_hive_logs() -> list[dict[str, Any]]:
    """
    Interroge HiveServer2 pour agreger les patterns d'URLs frauduleuses.

    La table Hive est alimentee au premier run par des donnees reelles
    PhishStats (cible par defaut : 50k lignes). En cas de panne Hive,
    un cache local des derniers resultats reels est reutilise s'il existe.
    """
    params = _get_connection_params()
    conn = None
    cursor = None

    try:
        from pyhive import hive

        conn = hive.connect(**params)
        cursor = conn.cursor()

        _ensure_table_ready(cursor)
        query = _select_query_for_table(cursor)
        cursor.execute(query)
        columns = [desc[0] for desc in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

        results = [_normalize_hive_row(row) for row in rows]
        _save_cache(results)
        logger.info("Hive : %d entrees live lues.", len(results))
        return results

    except Exception as exc:
        if _beeline_bridge_enabled():
            try:
                bridge_results = _collect_hive_logs_via_beeline_bridge()
                logger.warning(
                    "Hive : pyhive indisponible (%s) - bascule vers le bridge live beeline (%d entrees).",
                    exc,
                    len(bridge_results),
                )
                return bridge_results
            except Exception as bridge_exc:
                logger.warning(
                    "Hive : pyhive indisponible (%s) et bridge beeline en echec (%s).",
                    exc,
                    bridge_exc,
                )

        cached_entries = _load_cache()
        fallback_target = _hive_fallback_cache_target_rows()

        if cached_entries and _is_cache_recent() and len(cached_entries) >= fallback_target:
            logger.warning(
                "Hive : connexion ou bootstrap impossible (%s) - reutilisation immediate du cache recent (%d entrees).",
                exc,
                len(cached_entries),
            )
            return cached_entries

        if cached_entries and _is_cache_recent() and len(cached_entries) < fallback_target:
            logger.warning(
                "Hive : connexion ou bootstrap impossible (%s) - cache recent mais sous la cible (%d < %d), tentative de refresh.",
                exc,
                len(cached_entries),
                fallback_target,
            )

        if len(cached_entries) >= fallback_target:
            logger.warning(
                "Hive : connexion ou bootstrap impossible (%s) - utilisation du cache reel (%d entrees).",
                exc,
                len(cached_entries),
            )
            return cached_entries

        try:
            refresh_target = _hive_fallback_refresh_rows()
            refreshed_entries = _refresh_cache_without_hive(refresh_target)
            logger.warning(
                "Hive : connexion ou bootstrap impossible (%s) - cache reel reconstruit via PhishStats (%d entrees).",
                exc,
                len(refreshed_entries),
            )
            return refreshed_entries
        except Exception as refresh_exc:
            if cached_entries:
                logger.warning(
                    "Hive : connexion ou bootstrap impossible (%s) - refresh cache echoue (%s), reutilisation du cache reel existant (%d entrees).",
                    exc,
                    refresh_exc,
                    len(cached_entries),
                )
                return cached_entries

        logger.error("Hive : connexion ou chargement PhishStats impossible - %s", exc)
        return []
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
