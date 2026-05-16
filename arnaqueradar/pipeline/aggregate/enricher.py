"""
Enrichissement metier des donnees nettoyees ArnaqueRadar.

Ce sous-module est responsable uniquement de l'enrichissement :
- harmonisation des types metier
- consolidation des champs canal, nature_technique, score_confiance
- normalisation du vocabulaire avant import en base
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from pipeline.collect.classification import (
    TYPE_TO_CANAL,
    TYPE_TO_NATURE,
    join_keywords,
    normalize_canal,
    normalize_nature,
    normalize_type,
    score_to_float,
)
from pipeline.aggregate.cleaner import OUTPUT_COLUMNS

logger = logging.getLogger(__name__)


def enrich_clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Etape 3 : enrichissement / harmonisation metier globale.

    Les connecteurs enrichissent deja au maximum des la collecte.
    Cette etape sert donc surtout a :
    - consolider les champs enrichis
    - completer les trous eventuels
    - harmoniser le vocabulaire final avant import
    """
    if df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    enriched = df.copy()
    enriched["type_raw"] = enriched["type_raw"].where(enriched["type_raw"].notna(), enriched["type"])
    enriched["type"] = enriched["type"].apply(normalize_type)
    enriched["type_arnaque"] = enriched["type"]
    logger.info("Etape 9 - Types metier harmonises.")

    enriched["keywords_matched"] = enriched["keywords_matched"].apply(join_keywords)
    enriched["classifier_version"] = enriched["classifier_version"].apply(_clean_text)
    enriched["canal"] = enriched.apply(_normalize_canal_row, axis=1)
    enriched["nature_technique"] = enriched.apply(_normalize_nature_row, axis=1)
    enriched["score_confiance"] = enriched.apply(_normalize_score_row, axis=1)
    enriched = _filter_low_quality_hive_rows(enriched)

    for column in OUTPUT_COLUMNS:
        if column not in enriched.columns:
            enriched[column] = ""

    return enriched[OUTPUT_COLUMNS].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Fonctions utilitaires internes
# ---------------------------------------------------------------------------

def _clean_text(value: Any) -> str:
    """Nettoie une chaine simple."""
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _normalize_canal_row(row: pd.Series) -> str:
    """Deduit un canal propre si la source n'en a pas fourni un."""
    existing = normalize_canal(row.get("canal", ""), fallback="")
    if existing:
        return existing
    return TYPE_TO_CANAL.get(str(row.get("type", "autre")), "web")


def _normalize_nature_row(row: pd.Series) -> str:
    """Deduit une nature technique propre si elle n'est pas fournie."""
    existing = normalize_nature(row.get("nature_technique", ""), fallback="")
    if existing:
        return existing
    return TYPE_TO_NATURE.get(str(row.get("type", "autre")), "autre")


def _normalize_score_row(row: pd.Series) -> float:
    """Borne et complete un score de confiance par defaut."""
    raw_score = row.get("score_confiance", None)
    if pd.notna(raw_score) and str(raw_score).strip() not in {"", "nan"}:
        return score_to_float(raw_score)

    type_name = str(row.get("type", "autre"))
    defaults = {
        "violation_rgpd": 0.99,
        "phishing": 0.85,
        "malware_distribution": 0.72,
        "sms_frauduleux": 0.85,
        "fraude_cpf": 0.88,
        "arnaque_achat": 0.8,
        "faux_support": 0.83,
        "autre": 0.45,
    }
    return score_to_float(defaults.get(type_name, 0.5))


def _filter_low_quality_hive_rows(df: pd.DataFrame) -> pd.DataFrame:
    """
    Retire du dataset final les lignes Hive encore trop peu qualifiees.

    Le stockage Big Data Hive conserve beaucoup de volume et d'historique, mais
    lorsqu'une ligne `hive_logs` ressort encore en `autre` apres enrichissement,
    elle degrade fortement la lisibilite analytique. On preserve donc ces lignes
    dans le brut et l'etape 2, mais on les exclut du dataset final enrichi.
    """
    if df.empty:
        return df

    filtered = df.copy()
    source_series = filtered["source"].fillna("").astype(str).str.strip().str.lower()
    type_series = filtered["type"].fillna("").astype(str).str.strip().str.lower()
    low_quality_mask = (source_series == "hive_logs") & (type_series == "autre")
    dropped_rows = int(low_quality_mask.sum())

    if dropped_rows:
        logger.info(
            "Etape 10 - Filtre qualite Hive : %d lignes 'hive_logs/autre' exclues du dataset final.",
            dropped_rows,
        )
        filtered = filtered.loc[~low_quality_mask].copy()

    return filtered.reset_index(drop=True)


__all__ = [
    "enrich_clean_dataframe",
]
