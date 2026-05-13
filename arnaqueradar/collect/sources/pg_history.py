"""
Source 4 : PostgreSQL historique — collecte depuis la base de données interne.

Ce module interroge la table signalements_historique de PostgreSQL pour extraire
les signalements des 90 derniers jours. Si la table n'existe pas (première
exécution), elle est créée et alimentée avec 20 entrées de démonstration réalistes.

Connexion : psycopg2, paramètres lus depuis les variables d'environnement.
"""

import logging
import os
from datetime import date, timedelta
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

REGIONS = [
    "Île-de-France", "Auvergne-Rhône-Alpes", "Bretagne",
    "Grand Est", "Hauts-de-France", "Normandie",
    "Nouvelle-Aquitaine", "Occitanie", "Pays de la Loire",
    "Provence-Alpes-Côte d'Azur",
]

DEMO_ENTRIES = [
    ("https://fake-livraison-colissimo.fr/suivi-colis", "phishing", "Île-de-France", 10),
    ("https://impots-remboursement-2024.fr/formulaire", "phishing", "Auvergne-Rhône-Alpes", 20),
    ("https://ameli-cpam-validation.net/dossier", "phishing", "Bretagne", 30),
    ("https://fake-pole-emploi-allocation.com/compte", "phishing", "Grand Est", 15),
    ("https://prix-energie-edf-remise.fr/offre", "phishing", "Hauts-de-France", 5),
    ("https://sms-chronopost-faux.net/", "sms_frauduleux", "Normandie", 45),
    ("https://free-mobile-arnaque-facture.fr", "sms_frauduleux", "Nouvelle-Aquitaine", 8),
    ("https://sfr-remboursement-fake.com/solde", "sms_frauduleux", "Occitanie", 12),
    ("https://boursorama-phishing-clone.net", "phishing", "Pays de la Loire", 25),
    ("https://credit-agricole-securite-compte.fr", "phishing", "Provence-Alpes-Côte d'Azur", 18),
    ("https://societe-generale-alerte-fraude.net", "phishing", "Île-de-France", 33),
    ("https://paypal-verification-urgent.fr/confirm", "phishing", "Auvergne-Rhône-Alpes", 7),
    ("https://amazon-remboursement-commande.fr", "phishing", "Bretagne", 40),
    ("https://doctolib-arnaque-rdv.fr/annulation", "phishing", "Grand Est", 6),
    ("https://carte-vitale-renouvellement-fraude.fr", "phishing", "Hauts-de-France", 22),
    ("https://caisse-retraite-complement.com/dossier", "phishing", "Normandie", 9),
    ("https://cpf-formation-fraude-2024.net", "fraude_cpf", "Nouvelle-Aquitaine", 50),
    ("https://compte-cpf-arnaque-demarchage.fr", "fraude_cpf", "Occitanie", 35),
    ("https://microsoft-support-fraude-tech.net", "faux_support", "Pays de la Loire", 14),
    ("https://apple-support-icloud-phishing.fr/verify", "phishing", "Provence-Alpes-Côte d'Azur", 11),
]

EXTRACTION_QUERY = """
    SELECT url, type_arnaque AS type, region, date_signalement, source
    FROM signalements_historique
    WHERE date_signalement >= NOW() - INTERVAL '90 days'
"""

CREATE_TABLE_QUERY = """
    CREATE TABLE IF NOT EXISTS signalements_historique (
        id               SERIAL PRIMARY KEY,
        url              VARCHAR(2048) NOT NULL,
        type_arnaque     VARCHAR(50)   NOT NULL,
        region           VARCHAR(100),
        date_signalement DATE          NOT NULL,
        source           VARCHAR(50)   NOT NULL DEFAULT 'pg_history',
        verified         BOOLEAN       DEFAULT FALSE,
        created_at       TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );
"""


def _get_connection():
    """
    Cree une connexion psycopg2 via les parametres individuels PG_*.

    Les parametres sont passes comme arguments keyword a psycopg2.connect(),
    ce qui evite le bug d'encodage Windows lorsque le mot de passe contient
    des caracteres speciaux (espaces, accents). Ne jamais passer DATABASE_URL
    comme chaine brute a psycopg2 sur Windows.

    Retourne :
        psycopg2.connection : connexion active a PostgreSQL.

    Leve :
        psycopg2.OperationalError : si la connexion est impossible.
    """
    return psycopg2.connect(
        host=os.getenv("PG_HOST", "localhost"),
        port=int(os.getenv("PG_PORT", "5432")),
        dbname=os.getenv("PG_DB", "arnaqueradar"),
        user=os.getenv("PG_USER", "postgres"),
        password=os.getenv("PG_PASSWORD", ""),
        connect_timeout=10,
    )


def _insert_demo_entries(cursor) -> None:
    """
    Insère 20 entrées de démonstration dans signalements_historique.

    Paramètres :
        cursor : curseur psycopg2 actif sur la connexion en cours.
    """
    today = date.today()
    for i, (url, type_arnaque, region, days_ago) in enumerate(DEMO_ENTRIES):
        d = today - timedelta(days=days_ago)
        cursor.execute(
            """
            INSERT INTO signalements_historique (url, type_arnaque, region, date_signalement, source)
            VALUES (%s, %s, %s, %s, 'pg_history')
            ON CONFLICT DO NOTHING
            """,
            (url, type_arnaque, region, d),
        )
    logger.info("pg_history : 20 entrées de démonstration insérées.")


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """
    Normalise une ligne extraite de PostgreSQL vers le schéma commun.

    Paramètres :
        row (dict) : ligne issue de psycopg2 RealDictCursor.

    Retourne :
        dict : entrée normalisée.
    """
    date_val = row.get("date_signalement")
    date_iso = date_val.isoformat() if hasattr(date_val, "isoformat") else str(date_val)
    return {
        "url": str(row.get("url", "")).strip().rstrip("/"),
        "type": str(row.get("type", "autre")),
        "source": "pg_history",
        "date_signalement": date_iso,
        "region": str(row.get("region", "")),
    }


def collect_pg_history() -> list[dict[str, Any]]:
    """
    Extrait les signalements des 90 derniers jours depuis PostgreSQL.

    Si la table signalements_historique n'existe pas, elle est créée et
    alimentée avec des données de démonstration avant l'extraction.
    La connexion est toujours fermée dans un bloc finally.

    Retourne :
        list[dict] : liste des signalements normalisés, ou liste vide si
                     la connexion à PostgreSQL est impossible.
    """
    conn = None
    try:
        conn = _get_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # Créer la table si elle n'existe pas (première exécution)
            cursor.execute(CREATE_TABLE_QUERY)
            conn.commit()

            # Vérifier si la table est vide pour y insérer les données de démo
            cursor.execute("SELECT COUNT(*) AS cnt FROM signalements_historique;")
            count = cursor.fetchone()["cnt"]
            if count == 0:
                logger.info("pg_history : table vide, insertion des données de démonstration.")
                _insert_demo_entries(cursor)
                conn.commit()

            cursor.execute(EXTRACTION_QUERY)
            rows = cursor.fetchall()

        results = [_normalize_row(dict(row)) for row in rows]
        logger.info("pg_history : %d signalements extraits.", len(results))
        return results

    except psycopg2.OperationalError as exc:
        logger.error("pg_history : connexion PostgreSQL impossible — %s", exc)
        return []
    except psycopg2.Error as exc:
        logger.error("pg_history : erreur SQL — %s", exc)
        return []
    finally:
        if conn is not None:
            conn.close()
