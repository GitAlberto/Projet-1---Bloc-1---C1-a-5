"""
Source 4 : PostgreSQL historique - lecture de signalements internes.

Cette source represente une base metier relationnelle deja alimentee par un
systeme interne de signalements. Le connecteur ne fabrique plus de donnees de
demonstration : il s'appuie sur la table `signalements_historique`, enrichie
avec quelques colonnes metier (canal, statut, analyste, nb_signalements,
source_interne), puis n'extrait que les lignes verifiees et traitees.
"""

import logging
from typing import Any

import psycopg2
import psycopg2.extras

from pipeline.collect.classification import classify_signal, join_keywords
from bootstrap import load_project_env
from pipeline.database.connection import get_psycopg2_connection

load_project_env()

logger = logging.getLogger(__name__)

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

REQUIRED_HISTORY_COLUMNS = {
    "url",
    "type_arnaque",
    "region",
    "date_signalement",
    "source",
    "verified",
    "canal",
    "statut_traitement",
    "description_signalement",
    "analyste",
    "source_interne",
    "nb_signalements",
}


def _get_connection():
    """
    Cree une connexion psycopg2 via la couche centralisee database.connection.

    Delegue a get_psycopg2_connection() pour garantir la coherence des
    parametres de connexion dans tout le projet.
    """
    return get_psycopg2_connection()


def _assert_history_schema(cursor) -> None:
    """
    Verifie que la table historique existe deja et expose le bon schema.

    Le connecteur PostgreSQL ne modifie plus la structure a chaud. La table
    doit etre creee via les migrations SQL ou le script pgAdmin dedie.
    """
    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'signalements_historique'
        """
    )
    available = {row["column_name"] for row in cursor.fetchall()}
    if not available:
        raise RuntimeError(
            "La table signalements_historique est absente. "
            "Executez pipeline/database/migrations/001_init.sql puis "
            "queries/pg_history_pgadmin_setup.sql avant d'activer la source 4."
        )

    missing = sorted(REQUIRED_HISTORY_COLUMNS - available)
    if missing:
        raise RuntimeError(
            "Le schema de signalements_historique est incomplet. "
            "Executez pipeline/database/migrations/002_align_runtime_schema.sql puis "
            "queries/pg_history_pgadmin_setup.sql. "
            f"Colonnes manquantes : {', '.join(missing)}"
        )


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
            _assert_history_schema(cursor)
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
    except RuntimeError as exc:
        logger.error("pg_history : %s", exc)
        return []
    except psycopg2.Error as exc:
        logger.error("pg_history : erreur SQL - %s", exc)
        return []
    finally:
        if conn is not None:
            conn.close()
