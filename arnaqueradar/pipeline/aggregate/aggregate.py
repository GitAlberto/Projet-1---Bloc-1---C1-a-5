"""
Agregation, normalisation et controle qualite des donnees brutes ArnaqueRadar.

Ce module est desormais une facade : il re-exporte toutes les fonctions et
constantes publiques depuis les sous-modules specialises :

    pipeline/aggregate/cleaner.py   <- nettoyage technique (etape 2)
    pipeline/aggregate/enricher.py  <- enrichissement metier (etape 3)
    pipeline/aggregate/quality.py   <- controle qualite et rapports (etape 4)

Tous les imports existants depuis ``aggregate.aggregate`` continuent de
fonctionner sans modification via une facade de compatibilite. Ce module sert
aussi de point d'entree direct (``python -m pipeline.aggregate.aggregate``)
pour les lancements manuels.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bootstrap import load_project_env

load_project_env()

# ---------------------------------------------------------------------------
# Imports depuis les sous-modules — re-exportes pour compatibilite
# ---------------------------------------------------------------------------
from pipeline.aggregate.cleaner import (  # noqa: E402
    EVIDENCE_GRAIN_COLUMNS,
    OUTPUT_COLUMNS,
    clean_raw_dataframe,
    prepare_raw_dataframe,
)
from pipeline.aggregate.enricher import enrich_clean_dataframe  # noqa: E402
from pipeline.aggregate.quality import (  # noqa: E402
    QUALITY_TARGETS,
    build_other_review_sample,
    build_quality_report,
    save_quality_outputs as _save_quality_outputs,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("aggregate")

DATA_DIR = PROJECT_ROOT / "data"
CLEAN_STAGE_PATH = DATA_DIR / "2_dataset_nettoye.csv"
ENRICHED_STAGE_PATH = DATA_DIR / "3_dataset_enrichi.csv"
CLEAN_DATASET_PATH = DATA_DIR / "clean_dataset.csv"
QUALITY_REPORT_PATH = DATA_DIR / "quality_report.json"
QUALITY_SAMPLE_PATH = DATA_DIR / "quality_review_autre_sample.csv"


# ---------------------------------------------------------------------------
# Fonctions de pipeline : chargement, sauvegarde, orchestration
# ---------------------------------------------------------------------------

def load_latest_raw_path() -> Path:
    """Retourne le dernier fichier brut `raw_*.json` disponible."""
    raw_files = sorted(glob.glob(str(DATA_DIR / "raw_*.json")))
    if not raw_files:
        raise FileNotFoundError(f"Aucun fichier raw_*.json trouve dans {DATA_DIR}")
    return Path(raw_files[-1])


def load_raw_payload(raw_path: Path) -> list[dict[str, Any]]:
    """Charge un fichier JSON brut produit par la collecte."""
    with open(raw_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, list):
        raise ValueError(f"Contenu inattendu dans {raw_path.name}: liste attendue.")
    return payload


def aggregate_sources(raw_data: list[dict[str, Any]]) -> pd.DataFrame:
    """
    Pipeline historique conserve pour compatibilite.

    Il enchaine desormais explicitement :
    - preparation du DataFrame
    - nettoyage
    - enrichissement
    """
    prepared_df = prepare_raw_dataframe(raw_data)
    cleaned_df = clean_raw_dataframe(prepared_df)
    return enrich_clean_dataframe(cleaned_df)


def save_quality_outputs(df: pd.DataFrame) -> tuple[Path, Path]:
    """Sauvegarde le rapport qualite JSON et l'echantillon CSV de revue."""
    return _save_quality_outputs(df, QUALITY_REPORT_PATH, QUALITY_SAMPLE_PATH)


def save_clean_stage(df: pd.DataFrame, output_path: Path = CLEAN_STAGE_PATH) -> Path:
    """Sauvegarde le dataset nettoye intermediaire de l'etape 2."""
    df.to_csv(output_path, index=False, encoding="utf-8")
    return output_path


def save_enriched_stage(
    df: pd.DataFrame,
    enriched_path: Path = ENRICHED_STAGE_PATH,
    compatibility_path: Path = CLEAN_DATASET_PATH,
) -> tuple[Path, Path]:
    """
    Sauvegarde le dataset enrichi final.

    On produit a la fois :
    - un fichier explicite d'etape 3
    - le `clean_dataset.csv` historique attendu par l'import existant
    """
    df.to_csv(enriched_path, index=False, encoding="utf-8")

    if compatibility_path.exists():
        compatibility_path.unlink()

    try:
        os.link(enriched_path, compatibility_path)
    except OSError:
        df.to_csv(compatibility_path, index=False, encoding="utf-8")

    return enriched_path, compatibility_path


def run_cleaning_stage(raw_path: Path | None = None) -> tuple[pd.DataFrame, Path]:
    """Execute l'etape 2 a partir du dernier brut ou d'un brut fourni."""
    source_path = raw_path or load_latest_raw_path()
    raw_payload = load_raw_payload(source_path)
    prepared_df = prepare_raw_dataframe(raw_payload)
    cleaned_df = clean_raw_dataframe(prepared_df)
    output_path = save_clean_stage(cleaned_df)
    return cleaned_df, output_path


def run_enrichment_stage(cleaned_df: pd.DataFrame | None = None) -> tuple[pd.DataFrame, Path, Path]:
    """Execute l'etape 3 a partir d'un DataFrame nettoye ou du dernier fichier d'etape 2."""
    if cleaned_df is None:
        if not CLEAN_STAGE_PATH.exists():
            raise FileNotFoundError(
                f"Le fichier d'etape 2 est introuvable: {CLEAN_STAGE_PATH}. Executez d'abord pipeline/aggregate/2_nettoyer.py."
            )
        cleaned_df = pd.read_csv(CLEAN_STAGE_PATH, encoding="utf-8", low_memory=False)

    enriched_df = enrich_clean_dataframe(cleaned_df)
    enriched_path, compatibility_path = save_enriched_stage(enriched_df)
    return enriched_df, enriched_path, compatibility_path


def run_quality_stage(enriched_df: pd.DataFrame | None = None) -> tuple[dict[str, Any], pd.DataFrame, Path, Path]:
    """Execute l'etape 4 de controle qualite."""
    if enriched_df is None:
        if not CLEAN_DATASET_PATH.exists():
            raise FileNotFoundError(
                f"Le dataset enrichi est introuvable: {CLEAN_DATASET_PATH}. Executez d'abord pipeline/aggregate/3_enrichir.py."
            )
        enriched_df = pd.read_csv(CLEAN_DATASET_PATH, encoding="utf-8", low_memory=False)

    report = build_quality_report(enriched_df)
    review_sample = build_other_review_sample(enriched_df)
    report_path, sample_path = save_quality_outputs(enriched_df)
    return report, review_sample, report_path, sample_path


def run_full_aggregation_pipeline(raw_path: Path | None = None) -> dict[str, Any]:
    """Execute en sequence nettoyage, enrichissement puis controle qualite."""
    cleaned_df, cleaned_path = run_cleaning_stage(raw_path=raw_path)
    enriched_df, enriched_path, compatibility_path = run_enrichment_stage(cleaned_df=cleaned_df)
    report, review_sample, report_path, sample_path = run_quality_stage(enriched_df=enriched_df)
    return {
        "cleaned_df": cleaned_df,
        "enriched_df": enriched_df,
        "quality_report": report,
        "quality_review_sample": review_sample,
        "cleaned_path": cleaned_path,
        "enriched_path": enriched_path,
        "compatibility_path": compatibility_path,
        "quality_report_path": report_path,
        "quality_sample_path": sample_path,
    }


# ---------------------------------------------------------------------------
# Fonctions utilitaires internes (conservees pour les tests existants)
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
    """Nettoie une chaine simple."""
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


def _normalize_canal_row(row: pd.Series) -> str:
    """Deduit un canal propre si la source n'en a pas fourni un."""
    from pipeline.collect.classification import TYPE_TO_CANAL, normalize_canal
    existing = normalize_canal(row.get("canal", ""), fallback="")
    if existing:
        return existing
    return TYPE_TO_CANAL.get(str(row.get("type", "autre")), "web")


def _normalize_nature_row(row: pd.Series) -> str:
    """Deduit une nature technique propre si elle n'est pas fournie."""
    from pipeline.collect.classification import TYPE_TO_NATURE, normalize_nature
    existing = normalize_nature(row.get("nature_technique", ""), fallback="")
    if existing:
        return existing
    return TYPE_TO_NATURE.get(str(row.get("type", "autre")), "autre")


def _normalize_score_row(row: pd.Series) -> float:
    """Borne et complete un score de confiance par defaut."""
    from pipeline.collect.classification import score_to_float
    raw_score = row.get("score_confiance", None)
    if pd.notna(raw_score) and str(raw_score).strip() not in {"", "nan"}:
        return score_to_float(raw_score)
    type_name = str(row.get("type", "autre"))
    defaults = {
        "violation_rgpd": 0.99, "phishing": 0.85, "malware_distribution": 0.72,
        "sms_frauduleux": 0.85, "fraude_cpf": 0.88, "arnaque_achat": 0.8,
        "faux_support": 0.83, "autre": 0.45,
    }
    return score_to_float(defaults.get(type_name, 0.5))


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


if __name__ == "__main__":
    try:
        latest_raw = load_latest_raw_path()
    except FileNotFoundError as exc:
        logger.error(str(exc))
        sys.exit(1)

    logger.info("Chargement du fichier brut : %s", latest_raw)
    results = run_full_aggregation_pipeline(raw_path=latest_raw)
    df_clean = results["enriched_df"]

    if df_clean.empty:
        logger.warning("Le DataFrame nettoye est vide - verifiez les sources.")
        sys.exit(1)

    logger.info(
        "Dataset nettoye sauvegarde dans : %s (%d lignes).",
        results["compatibility_path"],
        len(df_clean),
    )
    logger.info("Rapport qualite sauvegarde dans : %s", results["quality_report_path"])
    logger.info("Echantillon de revue des 'autre' sauvegarde dans : %s", results["quality_sample_path"])
    print(f"\nAgregation terminee : {len(df_clean)} entrees dans {results['compatibility_path']}")
