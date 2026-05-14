"""
Source 4 : PostgreSQL historique - lecture de signalements internes.

Cette source represente une base metier relationnelle deja alimentee par un
systeme interne de signalements. Le connecteur ne fabrique plus de donnees de
demonstration : il s'appuie sur la table `signalements_historique`, enrichie
avec quelques colonnes metier (canal, statut, analyste, nb_signalements,
source_interne), puis n'extrait que les lignes verifiees et traitees.
"""

import logging
import os
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

from collect.classification import classify_signal, join_keywords

load_dotenv()

logger = logging.getLogger(__name__)

CREATE_TABLE_QUERY = """
    CREATE TABLE IF NOT EXISTS signalements_historique (
        id                     SERIAL PRIMARY KEY,
        url                    VARCHAR(2048) NOT NULL,
        type_arnaque           VARCHAR(50)   NOT NULL,
        region                 VARCHAR(100),
        date_signalement       DATE          NOT NULL,
        source                 VARCHAR(50)   NOT NULL DEFAULT 'pg_history',
        verified               BOOLEAN       DEFAULT FALSE,
        canal                  VARCHAR(30)   NOT NULL DEFAULT 'web',
        statut_traitement      VARCHAR(30)   NOT NULL DEFAULT 'nouveau',
        description_signalement TEXT,
        analyste               VARCHAR(100),
        source_interne         VARCHAR(100)  NOT NULL DEFAULT 'portail_web',
        nb_signalements        INTEGER       NOT NULL DEFAULT 1,
        created_at             TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );
"""

ALTER_TABLE_STATEMENTS = [
    "ALTER TABLE signalements_historique ADD COLUMN IF NOT EXISTS canal VARCHAR(30) NOT NULL DEFAULT 'web';",
    "ALTER TABLE signalements_historique ADD COLUMN IF NOT EXISTS statut_traitement VARCHAR(30) NOT NULL DEFAULT 'nouveau';",
    "ALTER TABLE signalements_historique ADD COLUMN IF NOT EXISTS description_signalement TEXT;",
    "ALTER TABLE signalements_historique ADD COLUMN IF NOT EXISTS analyste VARCHAR(100);",
    "ALTER TABLE signalements_historique ADD COLUMN IF NOT EXISTS source_interne VARCHAR(100) NOT NULL DEFAULT 'portail_web';",
    "ALTER TABLE signalements_historique ADD COLUMN IF NOT EXISTS nb_signalements INTEGER NOT NULL DEFAULT 1;",
    "CREATE INDEX IF NOT EXISTS idx_hist_date ON signalements_historique (date_signalement);",
    "CREATE INDEX IF NOT EXISTS idx_hist_status ON signalements_historique (statut_traitement);",
    "CREATE INDEX IF NOT EXISTS idx_hist_verified ON signalements_historique (verified);",
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_hist_url_date_source_interne "
        "ON signalements_historique (url, date_signalement, source_interne);"
    ),
]

EXTRACTION_QUERY = """
    SELECT
        url,
        type_arnaque AS type,
        region,
        date_signalement,
        source,
        COALESCE(verified, FALSE) AS verified,
        COALESCE(canal, 'web') AS canal,
        COALESCE(description_signalement, '') AS description_signalement,
        COALESCE(source_interne, 'portail_web') AS source_interne,
        COALESCE(nb_signalements, 1) AS nb_signalements
    FROM signalements_historique
    WHERE date_signalement >= CURRENT_DATE - INTERVAL '180 days'
      AND COALESCE(verified, FALSE) = TRUE
      AND COALESCE(statut_traitement, 'nouveau') IN ('valide', 'confirme')
    ORDER BY date_signalement DESC, nb_signalements DESC, id DESC
"""


def _get_connection():
    """
    Cree une connexion psycopg2 via les parametres individuels PG_*.
    """
    return psycopg2.connect(
        host=os.getenv("PG_HOST", "localhost"),
        port=int(os.getenv("PG_PORT", "5432")),
        dbname=os.getenv("PG_DB", "arnaqueradar"),
        user=os.getenv("PG_USER", "postgres"),
        password=os.getenv("PG_PASSWORD", ""),
        connect_timeout=10,
    )


def _ensure_history_table(cursor) -> None:
    """
    Cree la table historique si besoin et aligne sa structure metier.
    """
    cursor.execute(CREATE_TABLE_QUERY)
    for statement in ALTER_TABLE_STATEMENTS:
        cursor.execute(statement)


def _build_title(row: dict[str, Any]) -> str:
    """
    Construit un titre metier lisible pour l'entree issue de PostgreSQL.
    """
    description = str(row.get("description_signalement", "") or "").strip()
    canal = str(row.get("canal", "") or "").strip()
    source_interne = str(row.get("source_interne", "") or "").strip()

    if description:
        return description

    parts = ["Historique interne"]
    if canal:
        parts.append(f"canal: {canal}")
    if source_interne:
        parts.append(f"origine: {source_interne}")
    return " - ".join(parts)


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """
    Normalise une ligne extraite de PostgreSQL vers le schema commun.
    """
    date_val = row.get("date_signalement")
    date_iso = date_val.isoformat() if hasattr(date_val, "isoformat") else str(date_val)
    raw_type = str(row.get("type", "autre") or "autre").strip().lower()
    canal = str(row.get("canal", "") or "").strip()
    description = str(row.get("description_signalement", "") or "").strip()
    source_interne = str(row.get("source_interne", "") or "").strip()
    region = str(row.get("region", "") or "").strip()
    url = str(row.get("url", "")).strip().rstrip("/")
    classification = classify_signal(
        [url, raw_type, description, source_interne, region],
        seed_type=raw_type,
        seed_canal=canal,
        type_raw=raw_type,
        source_category_raw=source_interne,
        score_override=0.95,
        classifier_version="pg_history_rules_v2",
    )
    return {
        "url": url,
        "type": classification["type"],
        "source": "pg_history",
        "date_signalement": date_iso,
        "region": region,
        "verified": bool(row.get("verified", False)),
        "nb_signalements": int(row.get("nb_signalements", 1) or 1),
        "titre": _build_title(row),
        "canal": classification["canal"],
        "source_interne": source_interne,
        "nature_technique": classification["nature_technique"],
        "score_confiance": classification["score_confiance"],
        "type_raw": classification["type_raw"],
        "source_category_raw": classification["source_category_raw"],
        "keywords_matched": join_keywords(classification["keywords_matched"]),
        "classifier_version": classification["classifier_version"],
    }


def collect_pg_history() -> list[dict[str, Any]]:
    """
    Extrait les signalements historiques internes depuis PostgreSQL.

    Le connecteur lit uniquement les lignes metier exploitablees :
    - verifiees
    - traitees (`valide` / `confirme`)
    - datant des 180 derniers jours
    """
    conn = None
    try:
        conn = _get_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            _ensure_history_table(cursor)
            conn.commit()

            cursor.execute(EXTRACTION_QUERY)
            rows = cursor.fetchall()

        results = [_normalize_row(dict(row)) for row in rows]
        if not results:
            logger.warning(
                "pg_history : aucun signalement historique valide trouve. "
                "Alimentez la table via pgAdmin4 pour activer la source 4."
            )
            return []

        logger.info("pg_history : %d signalements extraits.", len(results))
        return results

    except psycopg2.OperationalError as exc:
        logger.error("pg_history : connexion PostgreSQL impossible - %s", exc)
        return []
    except psycopg2.Error as exc:
        logger.error("pg_history : erreur SQL - %s", exc)
        return []
    finally:
        if conn is not None:
            conn.close()
