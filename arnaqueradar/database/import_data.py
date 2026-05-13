"""
Script d'import des données nettoyées en base PostgreSQL.
Dépendances : psycopg2-binary, PostgreSQL >= 15
Pré-requis : avoir exécuté 001_init.sql et aggregate.py
Commande : python database/import_data.py

Ce script lit data/clean_dataset.csv et insère chaque ligne dans la table
signalements via une résolution des clés étrangères (type_id, region_id,
source_id). Les conflits sur (url, date_signalement) sont ignorés grâce
à ON CONFLICT DO NOTHING. Les compteurs d'insertions réussies et d'erreurs
sont affichés en fin d'exécution.
"""

import logging
import os
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("import_data")

CSV_PATH = PROJECT_ROOT / "data" / "clean_dataset.csv"

# Mapping du vocabulaire contrôlé vers les codes des types connus
TYPE_CODE_MAP: dict[str, str] = {
    "phishing": "phishing",
    "sms_frauduleux": "sms_frauduleux",
    "violation_rgpd": "violation_rgpd",
    "fraude_cpf": "fraude_cpf",
    "arnaque_achat": "arnaque_achat",
    "faux_support": "faux_support",
    "autre": "autre",
}

SOURCE_CODE_MAP: dict[str, str] = {
    "urlhaus": "urlhaus",
    "google_web_risk": "google_web_risk",
    "openphish": "openphish",
    "phishtank": "phishtank",
    "cybermalveillance": "cybermalveillance",
    "cnil_csv": "cnil_csv",
    "pg_history": "pg_history",
    "hive_logs": "hive_logs",
}

SOURCE_REFERENCE_ROWS: dict[str, tuple[str, str | None, str]] = {
    "urlhaus": (
        "URLhaus API",
        "https://urlhaus-api.abuse.ch/v1/urls/recent/",
        "api",
    ),
    "google_web_risk": (
        "Google Web Risk (legacy)",
        "https://webrisk.googleapis.com/v1/uris:search",
        "api",
    ),
    "openphish": (
        "OpenPhish (legacy)",
        "https://raw.githubusercontent.com/openphish/public_feed/refs/heads/main/feed.txt",
        "api",
    ),
    "phishtank": (
        "PhishTank (legacy)",
        "http://data.phishtank.com/data/online-valid.json",
        "api",
    ),
    "cybermalveillance": (
        "Cybermalveillance.gouv",
        "https://www.cybermalveillance.gouv.fr",
        "scraping",
    ),
    "cnil_csv": (
        "CNIL Open Data",
        "https://data.gouv.fr",
        "csv",
    ),
    "pg_history": (
        "Historique PostgreSQL",
        None,
        "sql",
    ),
    "hive_logs": (
        "Logs Big Data Hive",
        None,
        "bigdata",
    ),
}


def _get_connection():
    """
    Cree et retourne une connexion psycopg2 via les parametres individuels PG_*.

    Les parametres sont passes comme arguments keyword a psycopg2.connect(),
    ce qui evite le bug d'encodage Windows lorsque le mot de passe contient
    des caracteres speciaux (espaces, accents). Ne pas passer DATABASE_URL
    comme chaine brute a psycopg2 sur Windows.

    Retourne :
        psycopg2.connection : connexion active.

    Leve :
        psycopg2.OperationalError : si la connexion echoue.
    """
    return psycopg2.connect(
        host=os.getenv("PG_HOST", "localhost"),
        port=int(os.getenv("PG_PORT", "5432")),
        dbname=os.getenv("PG_DB", "arnaqueradar"),
        user=os.getenv("PG_USER", "postgres"),
        password=os.getenv("PG_PASSWORD", ""),
        connect_timeout=10,
    )


def _load_lookup_tables(cursor) -> tuple[dict, dict, dict]:
    """
    Charge les tables de référence pour résoudre les clés étrangères.

    Paramètres :
        cursor : curseur psycopg2 actif.

    Retourne :
        tuple : (types_map, regions_map, sources_map) — dictionnaires code → id.
    """
    cursor.execute("SELECT id, code FROM types_arnaque;")
    types_map = {row["code"]: row["id"] for row in cursor.fetchall()}

    cursor.execute("SELECT id, nom FROM regions;")
    # On indexe par nom complet en minuscules pour la correspondance souple
    regions_map = {row["nom"].lower(): row["id"] for row in cursor.fetchall()}

    cursor.execute("SELECT id, code FROM sources;")
    sources_map = {row["code"]: row["id"] for row in cursor.fetchall()}

    return types_map, regions_map, sources_map


def _ensure_source_reference_rows(cursor, sources_map: dict) -> dict:
    """
    Insere les sources de reference manquantes et retourne le mapping recharge.

    Ceci permet d'ajouter les nouvelles sources de reference automatiquement
    sur une base deja initialisee avant evolution des connecteurs.
    """
    missing_codes = [code for code in SOURCE_REFERENCE_ROWS if code not in sources_map]
    if not missing_codes:
        return sources_map

    for code in missing_codes:
        libelle, url, type_source = SOURCE_REFERENCE_ROWS[code]
        cursor.execute(
            """
            INSERT INTO sources (code, libelle, url, type_source)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (code) DO NOTHING
            """,
            (code, libelle, url, type_source),
        )

    cursor.execute("SELECT id, code FROM sources;")
    return {row["code"]: row["id"] for row in cursor.fetchall()}


def _resolve_region_id(region_raw: str, regions_map: dict) -> int | None:
    """
    Résout l'ID de région depuis un nom brut, avec correspondance souple.

    Paramètres :
        region_raw (str)   : nom de région tel qu'extrait du CSV.
        regions_map (dict) : dictionnaire nom_lowercase → id.

    Retourne :
        int | None : ID de la région, ou None si inconnue.
    """
    if not region_raw or str(region_raw) in ("nan", ""):
        return regions_map.get("inconnue")
    return regions_map.get(str(region_raw).strip().lower(), regions_map.get("inconnue"))


def import_clean_data() -> tuple[int, int]:
    """
    Importe le fichier clean_dataset.csv en base PostgreSQL.

    Lit chaque ligne du CSV, résout les clés étrangères via les tables de
    référence, et insère dans signalements avec ON CONFLICT DO NOTHING.

    Retourne :
        tuple[int, int] : (nb_inserts_reussis, nb_erreurs).
    """
    import pandas as pd

    if not CSV_PATH.exists():
        logger.error("Fichier introuvable : %s — exécutez d'abord aggregate.py.", CSV_PATH)
        return 0, 0

    df = pd.read_csv(CSV_PATH, encoding="utf-8")
    logger.info("import_data : %d lignes lues depuis %s.", len(df), CSV_PATH)

    conn = None
    nb_ok = 0
    nb_err = 0

    try:
        conn = _get_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            types_map, regions_map, sources_map = _load_lookup_tables(cursor)
            sources_map = _ensure_source_reference_rows(cursor, sources_map)
            conn.commit()

        with conn.cursor() as cursor:
            for idx, row in df.iterrows():
                try:
                    type_code = TYPE_CODE_MAP.get(str(row.get("type", "autre")).lower(), "autre")
                    type_id = types_map.get(type_code, types_map.get("autre"))
                    if type_id is None:
                        logger.error("Ligne %d : type inconnu '%s', ignorée.", idx, row.get("type"))
                        nb_err += 1
                        continue

                    source_code = SOURCE_CODE_MAP.get(str(row.get("source", "")).lower())
                    source_id = sources_map.get(source_code) if source_code else None
                    if source_id is None:
                        # Source inconnue : utiliser pg_history par défaut
                        source_id = sources_map.get("pg_history")

                    region_id = _resolve_region_id(str(row.get("region", "")), regions_map)

                    url = str(row.get("url", "")).strip()
                    date_sig = str(row.get("date_signalement", "")).strip()
                    titre = str(row.get("titre", "")) if "titre" in row else None
                    verified = bool(row.get("verified", False))

                    if not url or not date_sig or date_sig in ("nan", ""):
                        nb_err += 1
                        continue

                    cursor.execute(
                        """
                        INSERT INTO signalements
                            (url, type_id, region_id, source_id, date_signalement, verified, titre)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT ON CONSTRAINT uq_signalement_url_date DO NOTHING
                        """,
                        (url, type_id, region_id, source_id, date_sig, verified,
                         None if titre in ("nan", "", None) else titre),
                    )
                    nb_ok += 1

                except psycopg2.Error as exc:
                    logger.error("Ligne %d : erreur SQL — %s", idx, exc)
                    conn.rollback()
                    nb_err += 1
                    continue

            conn.commit()

    except psycopg2.OperationalError as exc:
        logger.error("import_data : connexion PostgreSQL impossible — %s", exc)
    finally:
        if conn is not None:
            conn.close()

    return nb_ok, nb_err


if __name__ == "__main__":
    logger.info("Démarrage de l'import des données nettoyées en base.")
    ok, err = import_clean_data()
    logger.info("Import terminé — Insertions réussies : %d | Erreurs : %d", ok, err)
    print(f"\nImport terminé : {ok} insertions réussies, {err} erreurs.")
