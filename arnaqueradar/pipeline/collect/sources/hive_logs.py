"""
Source 5 : Apache Hive - lecture stricte du stockage Big Data.

Cette source ne contacte pas PhishStats et ne se nourrit pas du pipeline
local. Son unique role est de lire la table Hive `logs_arnaques`, deja
alimentee au prealable par un bootstrap dedie, puis de projeter les lignes
vers le schema commun ArnaqueRadar.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from bootstrap import PROJECT_ROOT, load_project_env
from pipeline.collect.classification import classify_signal, join_keywords

load_project_env()

logger = logging.getLogger(__name__)

DATA_DIR = PROJECT_ROOT / "data"
CACHE_PATH = DATA_DIR / "hive_phishstats_cache.json"
HIVE_BOOTSTRAP_PATH = PROJECT_ROOT / "queries" / "hive_bootstrap.hql"
HIVE_TABLE = "logs_arnaques"
CURRENT_YEAR_WHERE = "WHERE YEAR(event_date) = YEAR(CURRENT_DATE)"
HIVE_METADATA_COLUMNS = ("title", "brand", "family", "tags", "host", "domain")


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


def _env_bool(name: str, default: bool = False) -> bool:
    """Interprete une variable d'environnement booleenne classique."""
    raw_value = os.getenv(name, "true" if default else "false").strip().lower()
    return raw_value in {"1", "true", "yes", "y", "on"}


def _load_hive_bootstrap_query() -> str:
    """Charge la definition de table Hive de reference depuis le HQL du projet."""
    if HIVE_BOOTSTRAP_PATH.exists():
        return HIVE_BOOTSTRAP_PATH.read_text(encoding="utf-8").strip().rstrip(";")

    logger.warning(
        "Hive : fichier de bootstrap introuvable (%s), utilisation du SQL embarque.",
        HIVE_BOOTSTRAP_PATH,
    )
    return f"""
        CREATE TABLE IF NOT EXISTS {HIVE_TABLE} (
            url_pattern STRING,
            type_arnaque STRING,
            region STRING,
            event_date DATE,
            nb_signalements INT,
            title STRING,
            brand STRING,
            family STRING,
            tags STRING,
            host STRING,
            domain STRING
        )
    """.strip()


CREATE_TABLE_QUERY = _load_hive_bootstrap_query()


def _hive_query_mode() -> str:
    """Mode d'extraction Hive : lignes brutes ou agregats."""
    mode = os.getenv("HIVE_QUERY_MODE", "rows").strip().lower()
    return mode if mode in {"rows", "aggregate"} else "rows"


def _current_year_filter_enabled() -> bool:
    """Controle le filtrage annuel optionnel des requetes Hive."""
    raw_value = os.getenv("HIVE_FILTER_CURRENT_YEAR")
    if raw_value is not None and raw_value.strip():
        return _env_bool("HIVE_FILTER_CURRENT_YEAR", False)
    return _hive_query_mode() == "aggregate"


def _hive_cache_max_age_hours() -> int:
    """Age maximal du cache local considere comme recent."""
    return _env_int("HIVE_CACHE_MAX_AGE_HOURS", 24, minimum=1, maximum=168)


def _render_hive_query(template: str, filter_current_year: bool) -> str:
    """Injecte proprement le WHERE optionnel dans un template SQL Hive."""
    where_clause = CURRENT_YEAR_WHERE if filter_current_year else ""
    return template.format(where_clause=where_clause)


def _render_metadata_select(columns: set[str], *, aggregated: bool) -> str:
    """Construit la projection SQL des metadonnees optionnelles de Hive."""
    expressions: list[str] = []
    for column_name in HIVE_METADATA_COLUMNS:
        if column_name in columns:
            if aggregated:
                expressions.append(f"MIN({column_name}) AS {column_name}")
            else:
                expressions.append(column_name)
        else:
            expressions.append(f"'' AS {column_name}")
    return ",\n           ".join(expressions)


def _get_connection_params() -> dict[str, Any]:
    """Construit les parametres de connexion Hive depuis l'environnement."""
    return {
        "host": os.getenv("HIVE_HOST", "localhost"),
        "port": int(os.getenv("HIVE_PORT", "10000")),
        "username": os.getenv("HIVE_USER", "hive"),
        "database": os.getenv("HIVE_DB", "default"),
        "auth": os.getenv("HIVE_AUTH", "NOSASL"),
    }


def _refine_generic_hive_classification(url: str, classification: dict[str, Any]) -> dict[str, Any]:
    """Requalifie certains `autre` tres techniques en distribution de malware."""
    if classification.get("type") != "autre":
        return classification

    lowered_url = str(url or "").lower()
    malware_signals = []
    if "/arquivo_" in lowered_url:
        malware_signals.append("arquivo_")
    if "get.php?" in lowered_url:
        malware_signals.append("get.php")
    if any(token in lowered_url for token in ("/t/", "/s/", "/b/")):
        malware_signals.append("short_payload_path")
    if any(
        token in lowered_url
        for token in (
            "x86",
            "x64",
            "amd64",
            "386",
            "arm",
            "arm5",
            "arm6",
            "arm7",
            "mips",
            "mipsel",
            "mips64",
            "mips64el",
            "sh4",
            "ppc",
            "m68k",
            "sparc",
            "kal32",
            "kal64",
            "riscv",
        )
    ):
        malware_signals.append("arch_payload")
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


def _normalize_hive_row(row: dict[str, Any]) -> dict[str, Any]:
    """Normalise une ligne extraite de Hive vers le schema commun."""
    date_val = row.get("date_signalement")
    if hasattr(date_val, "isoformat"):
        date_iso = date_val.isoformat()
    else:
        date_iso = str(date_val) if date_val else date.today().isoformat()

    raw_type = str(row.get("type", "autre") or "autre").strip().lower()
    region = str(row.get("region", "") or "").strip()
    url = str(row.get("url", "") or "").strip().rstrip("/")
    title = str(row.get("title", "") or "").strip()
    brand = str(row.get("brand", "") or "").strip()
    family = str(row.get("family", "") or "").strip()
    tags = str(row.get("tags", "") or "").strip()
    host = str(row.get("host", "") or "").strip()
    domain = str(row.get("domain", "") or "").strip()
    source_category_raw = "|".join(
        value
        for value in [family, brand, host, domain, tags]
        if value
    ) or "hive_logs"
    classification = classify_signal(
        [url, raw_type, region, title, brand, family, tags, host, domain],
        seed_type=raw_type,
        type_raw=raw_type,
        source_category_raw=source_category_raw,
        classifier_version="hive_logs_rules_v3",
    )
    classification = _refine_generic_hive_classification(url, classification)

    return {
        "url": url,
        "type": classification["type"],
        "source": "hive_logs",
        "date_signalement": date_iso,
        "region": region,
        "nb_signalements": int(row.get("nb_signalements", 1) or 1),
        "titre": title,
        "canal": classification["canal"],
        "nature_technique": classification["nature_technique"],
        "score_confiance": classification["score_confiance"],
        "type_raw": classification["type_raw"],
        "source_category_raw": classification["source_category_raw"],
        "keywords_matched": join_keywords(classification["keywords_matched"]),
        "classifier_version": classification["classifier_version"],
    }


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


def _ensure_table_exists(cursor) -> None:
    """Cree la table Hive si besoin, sans l'alimenter automatiquement."""
    cursor.execute(CREATE_TABLE_QUERY)


def _ensure_table_schema(cursor) -> list[str]:
    """
    Aligne une table Hive existante sur le schema attendu.

    Cette migration legere permet de conserver les metadonnees PhishStats
    utiles (`title`, `brand`, `family`, `tags`, `host`, `domain`) meme si la
    table a ete creee initialement avec l'ancien schema minimal.
    """
    _ensure_table_exists(cursor)
    existing_columns = _table_columns(cursor)
    missing_columns = [name for name in HIVE_METADATA_COLUMNS if name not in existing_columns]
    if not missing_columns:
        return []

    add_columns_sql = ", ".join(f"{column_name} STRING" for column_name in missing_columns)
    cursor.execute(f"ALTER TABLE {HIVE_TABLE} ADD COLUMNS ({add_columns_sql})")
    logger.info(
        "Hive : schema etendu sur %s avec les colonnes %s.",
        HIVE_TABLE,
        ", ".join(missing_columns),
    )
    return missing_columns


def _select_query_for_table(cursor) -> str:
    """Choisit la requete adaptee selon le schema reel de la table."""
    columns = _table_columns(cursor)
    query_mode = _hive_query_mode()
    filter_current_year = _current_year_filter_enabled()
    where_clause = CURRENT_YEAR_WHERE if filter_current_year else ""
    metadata_select = _render_metadata_select(columns, aggregated=query_mode == "aggregate")

    if query_mode == "aggregate":
        count_expression = "SUM(COALESCE(nb_signalements, 1))" if "nb_signalements" in columns else "COUNT(*)"
        return f"""
            SELECT url_pattern AS url,
                   type_arnaque AS type,
                   region,
                   {count_expression} AS nb_signalements,
                   MIN(event_date) AS date_signalement,
                   {metadata_select}
            FROM {HIVE_TABLE}
            {where_clause}
            GROUP BY url_pattern, type_arnaque, region
        """.strip()

    count_expression = "COALESCE(nb_signalements, 1)" if "nb_signalements" in columns else "1"
    return f"""
        SELECT url_pattern AS url,
               type_arnaque AS type,
               region,
               {count_expression} AS nb_signalements,
               event_date AS date_signalement,
               {metadata_select}
        FROM {HIVE_TABLE}
        {where_clause}
        ORDER BY event_date DESC
    """.strip()


def _save_cache(entries: list[dict[str, Any]]) -> None:
    """Sauvegarde le dernier resultat Hive reussi pour repli local."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as handle:
        json.dump(entries, handle, ensure_ascii=False, indent=2)


def _load_cache() -> list[dict[str, Any]]:
    """Relit le dernier cache local de resultats Hive si disponible."""
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
    """Indique si le cache local est recent au regard du seuil configure."""
    if not CACHE_PATH.exists():
        return False

    max_age = timedelta(hours=_hive_cache_max_age_hours())
    modified_at = datetime.fromtimestamp(CACHE_PATH.stat().st_mtime, tz=timezone.utc)
    return (datetime.now(timezone.utc) - modified_at) <= max_age


def collect_hive_logs() -> list[dict[str, Any]]:
    """
    Lit HiveServer2 pour extraire la source Big Data du pipeline.

    Preconditions :
    - Hive doit etre demarre
    - la table `logs_arnaques` doit avoir ete chargee au prealable
      via le bootstrap PhishStats dedie

    Si Hive est indisponible, le connecteur reutilise le dernier cache local
    de lecture Hive quand il existe. Aucun appel direct a PhishStats n'est
    effectue ici.
    """
    params = _get_connection_params()
    conn = None
    cursor = None

    try:
        from pyhive import hive

        conn = hive.connect(**params)
        cursor = conn.cursor()

        _ensure_table_schema(cursor)
        query = _select_query_for_table(cursor)
        cursor.execute(query)
        columns = [desc[0] for desc in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

        results = [_normalize_hive_row(row) for row in rows]
        if not results:
            logger.warning(
                "Hive : table %s vide. Lancez le bootstrap PhishStats avant la collecte.",
                HIVE_TABLE,
            )
            return []

        _save_cache(results)
        logger.info("Hive : %d entrees lues depuis %s.", len(results), HIVE_TABLE)
        return results

    except Exception as exc:
        cached_entries = _load_cache()
        if cached_entries:
            cache_state = "recent" if _is_cache_recent() else "ancien"
            logger.warning(
                "Hive : lecture impossible (%s) - reutilisation du cache %s (%d entrees).",
                exc,
                cache_state,
                len(cached_entries),
            )
            return cached_entries

        logger.error(
            "Hive : lecture impossible (%s) et aucun cache local disponible. "
            "Demarrez Hive puis lancez le bootstrap PhishStats.",
            exc,
        )
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
