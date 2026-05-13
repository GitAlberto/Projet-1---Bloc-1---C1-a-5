"""
Module d'agrégation et de normalisation des données brutes ArnaqueRadar.

Ce module prend en entrée la liste brute de toutes les entrées collectées
par le pipeline (collect.py) et produit un DataFrame pandas nettoyé,
dédupliqué et normalisé prêt pour l'import en base de données.

Pipeline de nettoyage en 8 étapes :
  1. Identification des entrées corrompues (url ET date absents)
  2. Suppression des entrées corrompues
  3. Identification des formats de date non normalisés
  4. Normalisation des dates vers ISO 8601 (YYYY-MM-DD)
  5. Suppression des dates non parsables
  6. Normalisation des types d'arnaque vers un vocabulaire contrôlé
  7. Normalisation des URLs (lowercase, strip trailing slash)
  8. Déduplication sur (url, date_signalement)

Usage direct : python aggregate/aggregate.py
"""

import glob
import json
import logging
import logging.config
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("aggregate")

DATA_DIR = PROJECT_ROOT / "data"

TYPE_MAPPING: dict[str, str] = {
    "phishing": "phishing",
    "hameçonnage": "phishing",
    "hameconnage": "phishing",
    "smishing": "sms_frauduleux",
    "sms_fraud": "sms_frauduleux",
    "sms_frauduleux": "sms_frauduleux",
    "violation_rgpd": "violation_rgpd",
    "fraude_cpf": "fraude_cpf",
    "arnaque_achat": "arnaque_achat",
    "faux_support": "faux_support",
    "arnaque": "autre",
    "autre": "autre",
}


def aggregate_sources(raw_data: list[dict[str, Any]]) -> pd.DataFrame:
    """
    Nettoie, normalise et déduplique les données brutes de toutes les sources.

    Paramètres :
        raw_data (list[dict]) : liste brute des entrées collectées.

    Retourne :
        pd.DataFrame : DataFrame nettoyé avec les colonnes normalisées.
                       Retourne un DataFrame vide si raw_data est vide.
    """
    if not raw_data:
        logger.warning("aggregate : aucune donnée brute reçue.")
        return pd.DataFrame()

    df = pd.DataFrame(raw_data)
    logger.info("aggregate : %d entrées reçues en entrée.", len(df))

    # ----------------------------------------------------------------
    # Étape 1 : Identification des entrées corrompues
    # Une entrée est corrompue si url ET date_signalement sont absents
    # ----------------------------------------------------------------
    url_missing = df.get("url", pd.Series()).isna() | (df.get("url", pd.Series("")) == "")
    date_missing = df.get("date_signalement", pd.Series()).isna() | (df.get("date_signalement", pd.Series("")) == "")
    corrupted_mask = url_missing & date_missing
    nb_corrupted = corrupted_mask.sum()
    logger.info("Étape 1 — Entrées corrompues identifiées : %d", nb_corrupted)

    # ----------------------------------------------------------------
    # Étape 2 : Suppression des entrées corrompues
    # ----------------------------------------------------------------
    df = df[~corrupted_mask].copy()
    logger.info("Étape 2 — Après suppression corrompus : %d entrées.", len(df))

    # Assurer que les colonnes obligatoires existent
    for col in ["url", "date_signalement", "type", "source"]:
        if col not in df.columns:
            df[col] = ""

    # ----------------------------------------------------------------
    # Étape 3 : Identification des formats de date non normalisés
    # ----------------------------------------------------------------
    dates_avant = df["date_signalement"].copy()
    nb_non_iso = df["date_signalement"].apply(
        lambda x: not (isinstance(x, str) and len(x) >= 10 and x[4] == "-" and x[7] == "-")
    ).sum()
    logger.info("Étape 3 — Dates non normalisées identifiées : %d", nb_non_iso)

    # ----------------------------------------------------------------
    # Étape 4 : Normalisation des dates vers ISO 8601 YYYY-MM-DD
    # ----------------------------------------------------------------
    df["date_signalement"] = pd.to_datetime(
        df["date_signalement"], errors="coerce", utc=True
    ).dt.date.astype(str)

    # Remplacer "NaT" (converti en str par .astype(str)) par NaN réel
    df["date_signalement"] = df["date_signalement"].replace("NaT", pd.NA)
    logger.info("Étape 4 — Dates normalisées vers ISO 8601.")

    # ----------------------------------------------------------------
    # Étape 5 : Suppression des entrées dont la date est non parsable
    # ----------------------------------------------------------------
    nb_avant_date = len(df)
    df = df.dropna(subset=["date_signalement"])
    nb_apres_date = len(df)
    logger.info(
        "Étape 5 — Entrées supprimées (date non parsable) : %d. Restant : %d.",
        nb_avant_date - nb_apres_date,
        nb_apres_date,
    )

    # ----------------------------------------------------------------
    # Étape 6 : Normalisation des types d'arnaque vers vocabulaire contrôlé
    # ----------------------------------------------------------------
    def normalize_type(raw_type: Any) -> str:
        if pd.isna(raw_type) or raw_type == "":
            return "autre"
        raw_lower = str(raw_type).lower().strip()
        return TYPE_MAPPING.get(raw_lower, "autre")

    df["type"] = df["type"].apply(normalize_type)
    logger.info("Étape 6 — Types normalisés vers le vocabulaire contrôlé.")

    # ----------------------------------------------------------------
    # Étape 7 : Normalisation des URLs (lowercase, suppression du slash final)
    # ----------------------------------------------------------------
    df["url"] = df["url"].apply(
        lambda u: str(u).strip().lower().rstrip("/") if pd.notna(u) else u
    )
    logger.info("Étape 7 — URLs normalisées.")

    # ----------------------------------------------------------------
    # Étape 8 : Déduplication sur (url, date_signalement)
    # ----------------------------------------------------------------
    nb_avant_dedup = len(df)
    df = df.drop_duplicates(subset=["url", "date_signalement"], keep="first")
    nb_apres_dedup = len(df)
    logger.info(
        "Étape 8 — Doublons supprimés : %d. Total final : %d entrées.",
        nb_avant_dedup - nb_apres_dedup,
        nb_apres_dedup,
    )

    df = df.reset_index(drop=True)
    return df


if __name__ == "__main__":
    # Charger le dernier fichier raw_*.json produit par collect.py
    raw_files = sorted(glob.glob(str(DATA_DIR / "raw_*.json")))
    if not raw_files:
        logger.error("Aucun fichier raw_*.json trouvé dans %s. Exécutez d'abord collect.py.", DATA_DIR)
        sys.exit(1)

    latest_raw = raw_files[-1]
    logger.info("Chargement du fichier brut : %s", latest_raw)

    with open(latest_raw, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    df_clean = aggregate_sources(raw_data)

    if df_clean.empty:
        logger.warning("Le DataFrame nettoyé est vide — vérifiez les sources.")
        sys.exit(1)

    output_path = DATA_DIR / "clean_dataset.csv"
    df_clean.to_csv(output_path, index=False, encoding="utf-8")
    logger.info("Dataset nettoyé sauvegardé dans : %s (%d lignes).", output_path, len(df_clean))
    print(f"\nAgrégation terminée : {len(df_clean)} entrées dans {output_path}")
