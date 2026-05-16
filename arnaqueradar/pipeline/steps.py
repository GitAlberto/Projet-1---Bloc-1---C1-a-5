"""
Orchestrateur pédagogique du pipeline ArnaqueRadar, découpé en étapes claires.

Ce module ne remplace pas les modules métier du projet.
Il sert de point d'appui aux scripts numérotés rangés sous `pipeline/` :

- `pipeline/collect/1_collecter.py`
- `pipeline/aggregate/2_nettoyer.py`
- `pipeline/aggregate/3_enrichir.py`
- `pipeline/aggregate/4_controler_qualite.py`
- `pipeline/database/5_importer.py`
- `pipeline/ml/6_preparer_dataset_ml.py`
- `pipeline/7_pipeline_complet.py`

Le but est de garder :
- l'existant compatible
- une lecture beaucoup plus claire pour un rapport, une soutenance
  ou une reprise de projet
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bootstrap import load_project_env

load_project_env()

from pipeline.aggregate.aggregate import (
    CLEAN_DATASET_PATH,
    CLEAN_STAGE_PATH,
    DATA_DIR,
    ENRICHED_STAGE_PATH,
    QUALITY_REPORT_PATH,
    QUALITY_SAMPLE_PATH,
    load_latest_raw_path,
    run_cleaning_stage,
    run_enrichment_stage,
    run_full_aggregation_pipeline,
    run_quality_stage,
)
from pipeline.collect import run_collection
from pipeline.database.import_data import CSV_PATH as IMPORT_CSV_PATH, import_clean_data

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("pipeline_steps")

ML_DATASET_PATH = DATA_DIR / "6_dataset_ml.csv"


def stage_1_collect() -> dict[str, Any]:
    """
    Étape 1 - Collecte brute.

    Cette étape interroge les sources, récupère les lignes brutes
    et laisse le collecteur historique générer automatiquement
    un fichier `raw_YYYYMMDD_HHMMSS.json`.
    """
    logger.info("Étape 1 - Lancement de la collecte brute.")
    entries = run_collection()
    latest_raw_path = load_latest_raw_path()
    return {
        "entries": entries,
        "rows": len(entries),
        "raw_path": latest_raw_path,
    }


def stage_2_clean(raw_path: Path | None = None) -> dict[str, Any]:
    """
    Étape 2 - Nettoyage technique.

    Cette étape se limite volontairement à :
    - corriger la forme
    - supprimer l'inexploitable
    - dédupliquer

    Elle ne cherche pas encore à “mieux comprendre” la donnée.
    """
    logger.info("Étape 2 - Nettoyage technique du brut.")
    cleaned_df, cleaned_path = run_cleaning_stage(raw_path=raw_path)
    return {
        "rows": len(cleaned_df),
        "cleaned_df": cleaned_df,
        "cleaned_path": cleaned_path,
    }


def stage_3_enrich(cleaned_df: pd.DataFrame | None = None) -> dict[str, Any]:
    """
    Étape 3 - Enrichissement métier.

    À ce stade :
    - on harmonise les types métier
    - on consolide `canal`, `nature_technique`, `score_confiance`
    - on conserve la preuve du classement pour audit et reporting
    """
    logger.info("Étape 3 - Enrichissement métier du dataset nettoyé.")
    enriched_df, enriched_path, compatibility_path = run_enrichment_stage(cleaned_df=cleaned_df)
    return {
        "rows": len(enriched_df),
        "enriched_df": enriched_df,
        "enriched_path": enriched_path,
        "compatibility_path": compatibility_path,
    }


def stage_4_quality(enriched_df: pd.DataFrame | None = None) -> dict[str, Any]:
    """
    Étape 4 - Contrôle qualité.

    Cette étape produit des artefacts d'analyse :
    - un rapport qualité JSON
    - un échantillon CSV de lignes à relire manuellement
    """
    logger.info("Étape 4 - Contrôle qualité du dataset enrichi.")
    report, review_sample, report_path, sample_path = run_quality_stage(enriched_df=enriched_df)
    return {
        "quality_report": report,
        "review_sample": review_sample,
        "report_path": report_path,
        "sample_path": sample_path,
    }


def stage_5_import() -> dict[str, Any]:
    """
    Étape 5 - Import en base PostgreSQL.

    Cette étape lit le dataset enrichi final (`clean_dataset.csv`)
    puis alimente la base relationnelle cible.
    """
    logger.info("Étape 5 - Import du dataset enrichi en base PostgreSQL.")
    inserted, errors = import_clean_data()
    return {
        "inserted": inserted,
        "errors": errors,
        "import_source_path": IMPORT_CSV_PATH,
    }


def stage_6_prepare_ml_dataset(enriched_df: pd.DataFrame | None = None) -> dict[str, Any]:
    """
    Étape 6 - Préparation d'un dataset orienté analyse avancée / ML.

    Ici on garde un fichier plat, lisible et exploitable,
    avec quelques variables techniques supplémentaires dérivées de l'URL.
    L'idée n'est pas encore d'entraîner un modèle, mais de préparer
    un dataset beaucoup plus simple à brancher dans une phase de ML.
    """
    logger.info("Étape 6 - Préparation du dataset d'analyse / ML.")
    if enriched_df is None:
        if not CLEAN_DATASET_PATH.exists():
            raise FileNotFoundError(
                f"Le dataset enrichi est introuvable: {CLEAN_DATASET_PATH}. Executez d'abord pipeline/aggregate/3_enrichir.py."
            )
        enriched_df = pd.read_csv(CLEAN_DATASET_PATH, encoding="utf-8", low_memory=False)

    ml_df = _build_ml_dataset(enriched_df)
    ml_df.to_csv(ML_DATASET_PATH, index=False, encoding="utf-8")

    return {
        "rows": len(ml_df),
        "ml_df": ml_df,
        "ml_dataset_path": ML_DATASET_PATH,
    }


def stage_7_full_pipeline() -> dict[str, Any]:
    """
    Étape 7 - Pipeline complet, de bout en bout.

    Cette étape chaîne tout :
    collecte -> nettoyage -> enrichissement -> qualité -> import -> dataset ML
    """
    logger.info("Étape 7 - Exécution complète du pipeline.")
    stage1 = stage_1_collect()
    aggregation = run_full_aggregation_pipeline(raw_path=stage1["raw_path"])
    stage5 = stage_5_import()
    stage6 = stage_6_prepare_ml_dataset(enriched_df=aggregation["enriched_df"])

    return {
        "stage_1": stage1,
        "stage_2": {
            "rows": len(aggregation["cleaned_df"]),
            "cleaned_path": aggregation["cleaned_path"],
        },
        "stage_3": {
            "rows": len(aggregation["enriched_df"]),
            "enriched_path": aggregation["enriched_path"],
            "compatibility_path": aggregation["compatibility_path"],
        },
        "stage_4": {
            "quality_report_path": aggregation["quality_report_path"],
            "quality_sample_path": aggregation["quality_sample_path"],
        },
        "stage_5": stage5,
        "stage_6": {
            "rows": stage6["rows"],
            "ml_dataset_path": stage6["ml_dataset_path"],
        },
    }


def _build_ml_dataset(df: pd.DataFrame) -> pd.DataFrame:
    """
    Construit un dataset plat plus confortable pour la data science.

    On évite ici toute magie opaque :
    les variables ajoutées sont volontairement simples et explicables.
    """
    working_df = df.copy()

    # ------------------------------------------------------------------
    # Variables directement utiles pour le machine learning supervisé :
    # - `type_arnaque` comme cible potentielle
    # - `canal`, `nature_technique`, `source`, `score_confiance`
    # - preuves de classement et intensité du signal
    # ------------------------------------------------------------------
    working_df["keywords_matched_count"] = (
        working_df["keywords_matched"]
        .fillna("")
        .astype(str)
        .apply(lambda value: len([item for item in value.split("|") if item.strip()]))
    )

    # ------------------------------------------------------------------
    # Variables techniques dérivées de l'URL :
    # - longueur
    # - profondeur du path
    # - présence d'une query string
    # - présence d'une IP dans le host
    # - extension potentielle de fichier
    # ------------------------------------------------------------------
    parsed_urls = working_df["url"].fillna("").astype(str).apply(urlparse)
    working_df["url_host"] = parsed_urls.apply(lambda parsed: parsed.netloc.lower())
    working_df["url_scheme"] = parsed_urls.apply(lambda parsed: parsed.scheme.lower())
    working_df["url_path"] = parsed_urls.apply(lambda parsed: parsed.path)
    working_df["url_query"] = parsed_urls.apply(lambda parsed: parsed.query)
    working_df["url_length"] = working_df["url"].fillna("").astype(str).str.len()
    working_df["url_path_depth"] = working_df["url_path"].apply(_path_depth)
    working_df["url_has_query"] = working_df["url_query"].apply(lambda query: bool(str(query).strip()))
    working_df["url_has_ip_host"] = working_df["url_host"].apply(_looks_like_ip_host)
    working_df["url_file_extension"] = working_df["url_path"].apply(_extract_extension)

    # ------------------------------------------------------------------
    # Colonnes retenues :
    # on garde à la fois le signal “métier” et un minimum de signal “technique”.
    # ------------------------------------------------------------------
    ml_columns = [
        "url",
        "url_host",
        "url_scheme",
        "url_path_depth",
        "url_has_query",
        "url_has_ip_host",
        "url_file_extension",
        "url_length",
        "type",
        "type_arnaque",
        "canal",
        "nature_technique",
        "score_confiance",
        "type_raw",
        "source_category_raw",
        "keywords_matched",
        "keywords_matched_count",
        "classifier_version",
        "source",
        "date_signalement",
        "region",
        "nb_signalements",
        "verified",
        "titre",
        "source_interne",
    ]

    for column in ml_columns:
        if column not in working_df.columns:
            working_df[column] = ""

    return working_df[ml_columns].reset_index(drop=True)


def _path_depth(path: str) -> int:
    """Compte combien de segments un path d'URL contient."""
    return len([segment for segment in str(path or "").split("/") if segment.strip()])


def _looks_like_ip_host(host: str) -> bool:
    """Détecte simplement si le host ressemble à une IPv4 brute."""
    parts = str(host or "").split(".")
    if len(parts) != 4:
        return False
    try:
        return all(0 <= int(part) <= 255 for part in parts)
    except ValueError:
        return False


def _extract_extension(path: str) -> str:
    """Extrait une extension de fichier basique depuis le path URL."""
    leaf = str(path or "").rsplit("/", 1)[-1].lower()
    if "." not in leaf:
        return ""
    extension = "." + leaf.rsplit(".", 1)[-1]
    return extension if len(extension) <= 10 else ""


__all__ = [
    "CLEAN_DATASET_PATH",
    "CLEAN_STAGE_PATH",
    "DATA_DIR",
    "ENRICHED_STAGE_PATH",
    "ML_DATASET_PATH",
    "QUALITY_REPORT_PATH",
    "QUALITY_SAMPLE_PATH",
    "stage_1_collect",
    "stage_2_clean",
    "stage_3_enrich",
    "stage_4_quality",
    "stage_5_import",
    "stage_6_prepare_ml_dataset",
    "stage_7_full_pipeline",
]
