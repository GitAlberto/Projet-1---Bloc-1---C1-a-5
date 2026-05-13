"""
Source 3 : CNIL Open Data — collecte depuis un fichier CSV.

Ce module lit le fichier de violations RGPD référencé par la CNIL.
Il tente d'abord de lire data/cnil_violations.csv ; si le fichier est absent,
il tente un téléchargement depuis data.gouv.fr. En dernier recours, il génère
un fichier de démonstration local afin de ne jamais interrompre le pipeline.

Encodage attendu : UTF-8, séparateur point-virgule (;).
"""

import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[3] / "data_CNIL"
CSV_PATH = DATA_DIR / "cnil_violations.csv"
DATAGOUV_URL = (
    "https://www.data.gouv.fr/fr/datasets/r/"
    "notified-violations-dataset.csv"
)


def _create_demo_csv() -> None:
    """
    Génère un fichier CSV de démonstration simulant des violations RGPD.

    Ce fichier est créé uniquement si le fichier réel est introuvable et que
    le téléchargement depuis data.gouv.fr a également échoué. Il permet de
    garantir la continuité du pipeline en environnement de développement.
    """
    base_date = date.today()
    rows = []
    domains = [
        "banque-alpha.fr", "assurance-beta.fr", "ecommerce-gamma.fr",
        "cabinet-medecin-delta.fr", "mutuelle-epsilon.fr",
        "telecom-zeta.fr", "mairie-eta.fr", "hopital-theta.fr",
    ]
    types_violation = [
        "Accès non autorisé", "Perte de données", "Divulgation non intentionnelle",
        "Ransomware", "Phishing interne",
    ]
    for i in range(25):
        d = base_date - timedelta(days=i * 12)
        rows.append({
            "url": f"https://{domains[i % len(domains)]}/incident-{i + 1}",
            "organisation": f"Organisation_{i + 1}",
            "type_violation": types_violation[i % len(types_violation)],
            "date_notification": d.isoformat(),
            "nombre_personnes_concernees": (i + 1) * 150,
            "region": "Île-de-France" if i % 3 == 0 else "Auvergne-Rhône-Alpes",
        })
    df = pd.DataFrame(rows)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(CSV_PATH, index=False, sep=";", encoding="utf-8")
    logger.info("CNIL CSV : fichier de démonstration créé (%d lignes).", len(rows))


def _download_from_datagouv() -> bool:
    """
    Tente de télécharger le fichier CNIL depuis data.gouv.fr.

    Retourne :
        bool : True si le téléchargement a réussi, False sinon.
    """
    try:
        import requests
        response = requests.get(DATAGOUV_URL, timeout=30, headers={"User-Agent": "ArnaqueRadar/1.0"})
        response.raise_for_status()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CSV_PATH.write_bytes(response.content)
        logger.info("CNIL CSV : fichier téléchargé depuis data.gouv.fr.")
        return True
    except Exception as exc:
        logger.warning("CNIL CSV : téléchargement data.gouv.fr échoué — %s", exc)
        return False


def _load_csv() -> pd.DataFrame:
    """
    Charge le CSV CNIL avec pandas en gérant l'encodage et le séparateur.

    Retourne :
        pd.DataFrame : données brutes du fichier CSV.

    Lève :
        Exception : si le fichier est illisible ou mal formaté.
    """
    return pd.read_csv(CSV_PATH, sep=";", encoding="utf-8", on_bad_lines="skip")


def _normalize_dataframe(df: pd.DataFrame) -> list[dict[str, Any]]:
    """
    Renomme les colonnes du DataFrame vers le schéma normalisé.

    Paramètres :
        df (pd.DataFrame) : données brutes chargées depuis le CSV.

    Retourne :
        list[dict] : liste des entrées normalisées.
    """
    column_mapping = {
        "url": "url",
        "date_notification": "date_signalement",
        "type_violation": "titre",
        "region": "region",
    }
    available = {k: v for k, v in column_mapping.items() if k in df.columns}
    df_norm = df.rename(columns=available)

    if "url" not in df_norm.columns:
        if "organisation" in df_norm.columns:
            df_norm["url"] = df_norm["organisation"].apply(
                lambda x: f"https://{str(x).lower().replace(' ', '-')}.fr/incident"
            )
        else:
            df_norm["url"] = "https://example.cnil.fr/incident-inconnu"

    if "date_signalement" not in df_norm.columns:
        df_norm["date_signalement"] = date.today().isoformat()

    df_norm["type"] = "violation_rgpd"
    df_norm["source"] = "cnil_csv"
    df_norm["titre"] = df_norm.get("titre", pd.Series(["Violation RGPD"] * len(df_norm)))

    fields = ["url", "type", "source", "date_signalement", "titre"]
    for field in fields:
        if field not in df_norm.columns:
            df_norm[field] = ""

    return df_norm[fields].to_dict(orient="records")


def collect_cnil_csv() -> list[dict[str, Any]]:
    """
    Collecte les violations RGPD depuis le CSV de la CNIL.

    Stratégie :
    1. Lire data/cnil_violations.csv s'il existe.
    2. Tenter le téléchargement depuis data.gouv.fr.
    3. Générer un CSV de démonstration local en dernier recours.

    Retourne :
        list[dict] : liste des entrées normalisées, ou liste vide si toutes
                     les tentatives échouent.
    """
    if not CSV_PATH.exists():
        logger.info("CNIL CSV : fichier local absent, tentative de téléchargement.")
        if not _download_from_datagouv():
            logger.warning("CNIL CSV : génération du fichier de démonstration.")
            _create_demo_csv()

    try:
        df = _load_csv()
        results = _normalize_dataframe(df)
        logger.info("CNIL CSV : %d violations chargées.", len(results))
        return results
    except Exception as exc:
        logger.error("CNIL CSV : impossible de charger le fichier — %s", exc)
        return []
