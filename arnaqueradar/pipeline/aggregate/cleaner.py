"""
Nettoyage technique des donnees brutes ArnaqueRadar.

Ce sous-module est responsable uniquement du nettoyage :
- correction de forme
- suppression des lignes inexploitables
- normalisation des dates et URLs
- deduplication au niveau preuve

Il n'enrichit pas les donnees metier.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from pipeline.collect.classification import join_keywords

logger = logging.getLogger(__name__)

EVIDENCE_GRAIN_COLUMNS = [
    "url",
    "date_signalement",
    "source",
    "source_interne",
    "type_raw",
]

OUTPUT_COLUMNS = [
    "url",
    "type",
    "type_arnaque",
    "canal",
    "nature_technique",
    "score_confiance",
    "type_raw",
    "source_category_raw",
    "keywords_matched",
    "classifier_version",
    "source",
    "date_signalement",
    "region",
    "nb_signalements",
    "verified",
    "titre",
    "source_interne",
]


def prepare_raw_dataframe(raw_data: list[dict[str, Any]]) -> pd.DataFrame:
    """Construit le DataFrame de travail et garantit les colonnes de base."""
    if not raw_data:
        logger.warning("aggregate : aucune donnee brute recue.")
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    df = pd.DataFrame(raw_data)
    logger.info("aggregate : %d entrees recues en entree.", len(df))

    for column in [
        "url", "date_signalement", "type", "source", "region", "titre",
        "canal", "nature_technique", "score_confiance", "type_raw",
        "source_category_raw", "keywords_matched", "classifier_version",
        "nb_signalements", "verified", "source_interne",
    ]:
        if column not in df.columns:
            df[column] = pd.NA
    return df


def clean_raw_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Etape 2 : nettoyage technique uniquement.

    Ici on ne reclasse pas metierement les donnees. On se limite a :
    - securiser les colonnes
    - supprimer les lignes inutilisables
    - normaliser dates / URLs
    - nettoyer les champs texte
    - dedupliquer
    """
    if df.empty:
        return df.copy()

    url_series = df["url"].fillna("").astype(str).str.strip()
    date_series = df["date_signalement"].fillna("").astype(str).str.strip()
    corrupted_mask = (url_series == "") & (date_series == "")
    logger.info("Etape 1 - Entrees corrompues identifiees : %d", int(corrupted_mask.sum()))

    df = df.loc[~corrupted_mask].copy()
    logger.info("Etape 2 - Apres suppression corrompus : %d entrees.", len(df))

    non_iso_dates = df["date_signalement"].apply(_is_non_iso_date).sum()
    logger.info("Etape 3 - Dates non normalisees identifiees : %d", int(non_iso_dates))

    df["date_signalement"] = pd.to_datetime(
        df["date_signalement"], errors="coerce", utc=True
    ).dt.date.astype(str)
    df["date_signalement"] = df["date_signalement"].replace("NaT", pd.NA)
    logger.info("Etape 4 - Dates normalisees vers ISO 8601.")

    before_drop_dates = len(df)
    df = df.dropna(subset=["date_signalement"]).copy()
    logger.info(
        "Etape 5 - Entrees supprimees (date non parsable) : %d. Restant : %d.",
        before_drop_dates - len(df),
        len(df),
    )

    df["url"] = df["url"].apply(_normalize_url)
    logger.info("Etape 7 - URLs normalisees.")

    df["source"] = df["source"].apply(_clean_text)
    df["region"] = df["region"].apply(_clean_text_preserve_case)
    df["titre"] = df["titre"].apply(_clean_text_preserve_case)
    df["source_interne"] = df["source_interne"].apply(_clean_text)
    df["type_raw"] = df["type_raw"].apply(_clean_text_preserve_case)
    df["source_category_raw"] = df["source_category_raw"].apply(_clean_text_preserve_case)
    df["nb_signalements"] = df["nb_signalements"].apply(_normalize_count)
    df["verified"] = df["verified"].apply(_coerce_bool)

    before_dedup = len(df)
    df = df.drop_duplicates(subset=EVIDENCE_GRAIN_COLUMNS, keep="first").copy()
    logger.info(
        "Etape 8 - Doublons supprimes : %d. Total final : %d entrees.",
        before_dedup - len(df),
        len(df),
    )
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Fonctions utilitaires internes
# ---------------------------------------------------------------------------

def _is_non_iso_date(value: Any) -> bool:
    """Retourne True si une date n'est pas deja sous forme ISO simple."""
    if not isinstance(value, str):
        return True
    text = value.strip()
    return not (len(text) >= 10 and text[4] == "-" and text[7] == "-")


def _normalize_url(value: Any) -> str:
    """Normalise l'URL vers une forme basse et sans slash final parasite."""
    text = str(value or "").strip().lower()
    return text.rstrip("/")


def _clean_text(value: Any) -> str:
    """Nettoie une chaine simple en conservant uniquement sa forme trim."""
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _clean_text_preserve_case(value: Any) -> str:
    """Nettoie une chaine sans la forcer en minuscule."""
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _normalize_count(value: Any) -> int:
    """Normalise un compteur de signalements vers un entier positif."""
    try:
        parsed = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 1
    return parsed if parsed > 0 else 1


def _coerce_bool(value: Any) -> bool:
    """Interprete proprement un booleen venu du CSV/pandas."""
    if isinstance(value, bool):
        return value
    if value is None:
        text = ""
    else:
        text = str(value).strip().lower()
        if text in {"<na>", "nan", "none"}:
            text = ""
    return text in {"1", "true", "vrai", "yes", "oui"}


__all__ = [
    "OUTPUT_COLUMNS",
    "EVIDENCE_GRAIN_COLUMNS",
    "prepare_raw_dataframe",
    "clean_raw_dataframe",
]
