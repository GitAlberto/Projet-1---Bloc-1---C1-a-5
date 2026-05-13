"""
Source 5 : Apache Hive - collecte Big Data depuis les logs d'arnaques.

Ce module interroge HiveServer2 via pyhive pour agreger les patterns
d'URLs d'arnaques enregistres dans la table logs_arnaques. En local,
si la table est absente ou vide, elle est creee puis alimentee avec
des donnees de demonstration. Si Hive est indisponible, un fallback
retourne des entrees simulees pour ne jamais interrompre le pipeline.
"""

import logging
import os
from datetime import date, timedelta
from typing import Any

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

HIVE_TABLE = "logs_arnaques"
CREATE_TABLE_QUERY = f"""
    CREATE TABLE IF NOT EXISTS {HIVE_TABLE} (
        url_pattern STRING,
        type_arnaque STRING,
        region STRING,
        event_date DATE,
        nb_signalements INT
    )
"""
HIVE_QUERY_WITH_COUNT = f"""
    SELECT url_pattern AS url,
           type_arnaque AS type,
           region,
           SUM(COALESCE(nb_signalements, 1)) AS nb_signalements,
           MIN(event_date) AS date_signalement
    FROM {HIVE_TABLE}
    WHERE YEAR(event_date) = YEAR(CURRENT_DATE)
    GROUP BY url_pattern, type_arnaque, region
"""
HIVE_QUERY_LEGACY = f"""
    SELECT url_pattern AS url,
           type_arnaque AS type,
           region,
           COUNT(*) AS nb_signalements,
           MIN(event_date) AS date_signalement
    FROM {HIVE_TABLE}
    WHERE YEAR(event_date) = YEAR(CURRENT_DATE)
    GROUP BY url_pattern, type_arnaque, region
"""

DEMO_ROWS = [
    (
        "https://hive-arnaque-banque-populaire.fr/connexion",
        "phishing",
        "\u00cele-de-France",
        5,
        312,
    ),
    (
        "https://hive-remboursement-caf.net/formulaire",
        "phishing",
        "Auvergne-Rh\u00f4ne-Alpes",
        12,
        189,
    ),
    (
        "https://hive-sms-livraison-fake.fr/suivi",
        "sms_frauduleux",
        "Bretagne",
        8,
        445,
    ),
    (
        "https://hive-cpf-formation-fraude.com/valider",
        "fraude_cpf",
        "Grand Est",
        20,
        78,
    ),
    (
        "https://hive-assurance-maladie-arnaque.fr",
        "phishing",
        "Hauts-de-France",
        3,
        201,
    ),
    (
        "https://hive-ursaff-cotisations-fraude.net",
        "phishing",
        "Normandie",
        15,
        134,
    ),
    (
        "https://hive-orange-remboursement-client.fr",
        "sms_frauduleux",
        "Nouvelle-Aquitaine",
        6,
        97,
    ),
    (
        "https://hive-leboncoin-paiement-securise.net",
        "arnaque_achat",
        "Occitanie",
        25,
        562,
    ),
    (
        "https://hive-support-microsoft-fraude.com/help",
        "faux_support",
        "Pays de la Loire",
        9,
        43,
    ),
    (
        "https://hive-amazon-compte-suspendu.fr/reactiver",
        "phishing",
        "Provence-Alpes-C\u00f4te d'Azur",
        2,
        288,
    ),
]

SIMULATED_ENTRIES = [
    {
        "url": url,
        "type": type_arnaque,
        "source": "hive_logs",
        "date_signalement": (date.today() - timedelta(days=days_ago)).isoformat(),
        "region": region,
        "nb_signalements": nb_signalements,
    }
    for url, type_arnaque, region, days_ago, nb_signalements in DEMO_ROWS
]


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
    """
    Normalise une ligne extraite de Hive vers le schema commun.
    """
    date_val = row.get("date_signalement")
    if hasattr(date_val, "isoformat"):
        date_iso = date_val.isoformat()
    else:
        date_iso = str(date_val) if date_val else date.today().isoformat()

    return {
        "url": str(row.get("url", "")).strip().rstrip("/"),
        "type": str(row.get("type", "autre")),
        "source": "hive_logs",
        "date_signalement": date_iso,
        "region": str(row.get("region", "")),
        "nb_signalements": int(row.get("nb_signalements", 1)),
    }


def _escape_sql(value: str) -> str:
    """Echappe une chaine simple pour une insertion Hive en SQL."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _seed_demo_rows(cursor) -> None:
    """Insere les donnees de demonstration dans Hive si la table est vide."""
    values_sql: list[str] = []
    today = date.today()
    for url, type_arnaque, region, days_ago, nb_signalements in DEMO_ROWS:
        event_date = (today - timedelta(days=days_ago)).isoformat()
        values_sql.append(
            "('{url}', '{type_arnaque}', '{region}', CAST('{event_date}' AS DATE), {nb_signalements})".format(
                url=_escape_sql(url),
                type_arnaque=_escape_sql(type_arnaque),
                region=_escape_sql(region),
                event_date=event_date,
                nb_signalements=nb_signalements,
            )
        )

    cursor.execute(
        f"""
        INSERT INTO TABLE {HIVE_TABLE}
        VALUES
        {", ".join(values_sql)}
        """
    )


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
    """
    Cree la table si besoin et l'alimente en donnees de demonstration.
    """
    cursor.execute(CREATE_TABLE_QUERY)
    cursor.execute(f"SELECT COUNT(*) FROM {HIVE_TABLE}")
    row_count = int(cursor.fetchone()[0])
    if row_count == 0:
        logger.info("Hive : table vide, insertion des donnees de demonstration.")
        _seed_demo_rows(cursor)


def _select_query_for_table(cursor) -> str:
    """Choisit la requete adaptee selon le schema reel de la table."""
    columns = _table_columns(cursor)
    if "nb_signalements" in columns:
        return HIVE_QUERY_WITH_COUNT
    return HIVE_QUERY_LEGACY


def collect_hive_logs() -> list[dict[str, Any]]:
    """
    Interroge HiveServer2 pour agreger les patterns d'URLs frauduleuses.

    Tente une connexion a Hive via les variables d'environnement HIVE_*.
    Si la table est absente ou vide, elle est creee puis alimentee avec
    des donnees de demonstration. Si Hive est indisponible, retourne 10
    entrees simulees realistes et enregistre un WARNING.
    """
    params = _get_connection_params()

    try:
        from pyhive import hive

        conn = hive.connect(**params)
        cursor = conn.cursor()

        _ensure_table_ready(cursor)
        query = _select_query_for_table(cursor)
        cursor.execute(query)
        columns = [desc[0] for desc in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        cursor.close()
        conn.close()

        results = [_normalize_hive_row(row) for row in rows]
        logger.info("Hive : %d patterns d'arnaques agreges.", len(results))
        return results

    except Exception as exc:
        logger.warning(
            "Hive : connexion impossible (%s) - utilisation des donnees simulees.", exc
        )
        logger.info("Hive : %d entrees simulees retournees.", len(SIMULATED_ENTRIES))
        return list(SIMULATED_ENTRIES)
