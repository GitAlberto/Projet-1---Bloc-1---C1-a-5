"""
Agrégation, normalisation et contrôle qualité des données brutes ArnaqueRadar.

Ce module :
1. nettoie les entrées brutes multi-sources
2. normalise les champs métier enrichis
3. déduplique le jeu de données
4. produit un rapport qualité et un échantillon de revue des "autres"
"""

from __future__ import annotations

import glob
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from collect.classification import (
    TYPE_TO_CANAL,
    TYPE_TO_NATURE,
    join_keywords,
    normalize_canal,
    normalize_nature,
    normalize_type,
    score_to_float,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("aggregate")

DATA_DIR = PROJECT_ROOT / "data"
QUALITY_REPORT_PATH = DATA_DIR / "quality_report.json"
QUALITY_SAMPLE_PATH = DATA_DIR / "quality_review_autre_sample.csv"

QUALITY_TARGETS = {
    "autre_global_max_pct": 15.0,
    "autre_by_source_max_pct": 25.0,
    "score_confiance_min_for_review": 0.6,
    "min_rows_for_source_alert": 100,
}

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


def aggregate_sources(raw_data: list[dict[str, Any]]) -> pd.DataFrame:
    """
    Nettoie, normalise et déduplique les données brutes.

    Retourne un DataFrame prêt pour l'export CSV et l'import SQL.
    """
    if not raw_data:
        logger.warning("aggregate : aucune donnée brute reçue.")
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    df = pd.DataFrame(raw_data)
    logger.info("aggregate : %d entrées reçues en entrée.", len(df))

    for column in [
        "url",
        "date_signalement",
        "type",
        "source",
        "region",
        "titre",
        "canal",
        "nature_technique",
        "score_confiance",
        "type_raw",
        "source_category_raw",
        "keywords_matched",
        "classifier_version",
        "nb_signalements",
        "verified",
        "source_interne",
    ]:
        if column not in df.columns:
            df[column] = pd.NA

    url_series = df["url"].fillna("").astype(str).str.strip()
    date_series = df["date_signalement"].fillna("").astype(str).str.strip()
    corrupted_mask = (url_series == "") & (date_series == "")
    logger.info("Étape 1 - Entrées corrompues identifiées : %d", int(corrupted_mask.sum()))

    df = df.loc[~corrupted_mask].copy()
    logger.info("Étape 2 - Après suppression corrompus : %d entrées.", len(df))

    non_iso_dates = df["date_signalement"].apply(_is_non_iso_date).sum()
    logger.info("Étape 3 - Dates non normalisées identifiées : %d", int(non_iso_dates))

    df["date_signalement"] = pd.to_datetime(
        df["date_signalement"], errors="coerce", utc=True
    ).dt.date.astype(str)
    df["date_signalement"] = df["date_signalement"].replace("NaT", pd.NA)
    logger.info("Étape 4 - Dates normalisées vers ISO 8601.")

    before_drop_dates = len(df)
    df = df.dropna(subset=["date_signalement"]).copy()
    logger.info(
        "Étape 5 - Entrées supprimées (date non parsable) : %d. Restant : %d.",
        before_drop_dates - len(df),
        len(df),
    )

    df["type_raw"] = df["type_raw"].where(df["type_raw"].notna(), df["type"])
    df["type"] = df["type"].apply(normalize_type)
    df["type_arnaque"] = df["type"]
    logger.info("Étape 6 - Types normalisés vers le vocabulaire contrôlé.")

    df["url"] = df["url"].apply(_normalize_url)
    logger.info("Étape 7 - URLs normalisées.")

    df["source"] = df["source"].apply(_clean_text)
    df["region"] = df["region"].apply(_clean_text_preserve_case)
    df["titre"] = df["titre"].apply(_clean_text_preserve_case)
    df["source_interne"] = df["source_interne"].apply(_clean_text)
    df["type_raw"] = df["type_raw"].apply(_clean_text_preserve_case)
    df["source_category_raw"] = df["source_category_raw"].apply(_clean_text_preserve_case)
    df["keywords_matched"] = df["keywords_matched"].apply(join_keywords)
    df["classifier_version"] = df["classifier_version"].apply(_clean_text)
    df["canal"] = df.apply(_normalize_canal_row, axis=1)
    df["nature_technique"] = df.apply(_normalize_nature_row, axis=1)
    df["score_confiance"] = df.apply(_normalize_score_row, axis=1)
    df["nb_signalements"] = df["nb_signalements"].apply(_normalize_count)
    df["verified"] = df["verified"].apply(_coerce_bool)

    before_dedup = len(df)
    df = df.drop_duplicates(subset=["url", "date_signalement"], keep="first").copy()
    logger.info(
        "Étape 8 - Doublons supprimés : %d. Total final : %d entrées.",
        before_dedup - len(df),
        len(df),
    )

    for column in OUTPUT_COLUMNS:
        if column not in df.columns:
            df[column] = ""

    return df[OUTPUT_COLUMNS].reset_index(drop=True)


def build_quality_report(df: pd.DataFrame) -> dict[str, Any]:
    """Construit un rapport qualité synthétique pour le dernier dataset propre."""
    if df.empty:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_rows": 0,
            "targets": QUALITY_TARGETS,
            "alerts": ["dataset_vide"],
        }

    total_rows = int(len(df))
    autre_mask = df["type"] == "autre"
    empty_region_mask = df["region"].fillna("").astype(str).str.strip() == ""
    low_signal_mask = (
        autre_mask
        & df["nature_technique"].fillna("").astype(str).isin(["", "autre"])
        & (df["keywords_matched"].fillna("").astype(str).str.strip() == "")
    )

    type_distribution = {
        key: int(value)
        for key, value in df["type"].value_counts(dropna=False).sort_values(ascending=False).items()
    }
    nature_distribution = {
        key: int(value)
        for key, value in df["nature_technique"].value_counts(dropna=False).sort_values(ascending=False).items()
    }

    autre_by_source = {}
    empty_region_by_source = {}
    low_signal_by_source = {}
    alerts: list[str] = []
    for source, group in df.groupby("source", dropna=False):
        source_name = str(source)
        source_total = len(group)
        source_autre_pct = round(float((group["type"] == "autre").mean() * 100), 2)
        source_region_empty_pct = round(
            float((group["region"].fillna("").astype(str).str.strip() == "").mean() * 100), 2
        )
        source_low_signal_pct = round(
            float(
                (
                    (group["type"] == "autre")
                    & group["nature_technique"].fillna("").astype(str).isin(["", "autre"])
                    & (group["keywords_matched"].fillna("").astype(str).str.strip() == "")
                ).mean()
                * 100
            ),
            2,
        )

        autre_by_source[source_name] = {
            "rows": int(source_total),
            "autre_pct": source_autre_pct,
        }
        empty_region_by_source[source_name] = {
            "rows": int(source_total),
            "region_vide_pct": source_region_empty_pct,
        }
        low_signal_by_source[source_name] = {
            "rows": int(source_total),
            "sans_signal_exploitable_pct": source_low_signal_pct,
        }

        if (
            source_total >= QUALITY_TARGETS["min_rows_for_source_alert"]
            and source_autre_pct > QUALITY_TARGETS["autre_by_source_max_pct"]
        ):
            alerts.append(f"autre_source_trop_eleve:{source_name}:{source_autre_pct}")

    autre_global_pct = round(float(autre_mask.mean() * 100), 2)
    if autre_global_pct > QUALITY_TARGETS["autre_global_max_pct"]:
        alerts.append(f"autre_global_trop_eleve:{autre_global_pct}")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_rows": total_rows,
        "targets": QUALITY_TARGETS,
        "type_distribution": type_distribution,
        "nature_distribution": nature_distribution,
        "autre_global_pct": autre_global_pct,
        "autre_by_source": autre_by_source,
        "region_vide_global_pct": round(float(empty_region_mask.mean() * 100), 2),
        "region_vide_by_source": empty_region_by_source,
        "sans_signal_exploitable_global_pct": round(float(low_signal_mask.mean() * 100), 2),
        "sans_signal_exploitable_by_source": low_signal_by_source,
        "score_confiance_moyen_global": round(float(df["score_confiance"].mean()), 3),
        "score_confiance_moyen_par_type": {
            str(key): round(float(value), 3)
            for key, value in df.groupby("type")["score_confiance"].mean().items()
        },
        "score_confiance_moyen_par_source": {
            str(key): round(float(value), 3)
            for key, value in df.groupby("source")["score_confiance"].mean().items()
        },
        "alerts": alerts,
    }
    return report


def build_other_review_sample(df: pd.DataFrame, max_total: int = 100, max_per_source: int = 25) -> pd.DataFrame:
    """Prépare un échantillon de revue manuelle des lignes classées en `autre`."""
    other_df = df.loc[df["type"] == "autre"].copy()
    if other_df.empty:
        return pd.DataFrame(
            columns=[
                "source",
                "url",
                "date_signalement",
                "type",
                "nature_technique",
                "canal",
                "score_confiance",
                "type_raw",
                "source_category_raw",
                "keywords_matched",
                "titre",
            ]
        )

    samples: list[pd.DataFrame] = []
    for _, group in other_df.groupby("source", dropna=False):
        ordered = group.sort_values(
            by=["score_confiance", "date_signalement"],
            ascending=[True, False],
        )
        samples.append(ordered.head(max_per_source))

    sample_df = pd.concat(samples, ignore_index=True)
    sample_df = sample_df.sort_values(
        by=["score_confiance", "source", "date_signalement"],
        ascending=[True, True, False],
    ).head(max_total)

    columns = [
        "source",
        "url",
        "date_signalement",
        "type",
        "nature_technique",
        "canal",
        "score_confiance",
        "type_raw",
        "source_category_raw",
        "keywords_matched",
        "titre",
    ]
    return sample_df[columns].reset_index(drop=True)


def save_quality_outputs(df: pd.DataFrame) -> tuple[Path, Path]:
    """Sauvegarde le rapport qualité JSON et l'échantillon CSV de revue."""
    report = build_quality_report(df)
    QUALITY_REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    review_sample = build_other_review_sample(df)
    review_sample.to_csv(QUALITY_SAMPLE_PATH, index=False, encoding="utf-8")

    return QUALITY_REPORT_PATH, QUALITY_SAMPLE_PATH


def _is_non_iso_date(value: Any) -> bool:
    """Retourne True si une date n'est pas déjà sous forme ISO simple."""
    if not isinstance(value, str):
        return True
    text = value.strip()
    return not (len(text) >= 10 and text[4] == "-" and text[7] == "-")


def _normalize_url(value: Any) -> str:
    """Normalise l'URL vers une forme basse et sans slash final parasite."""
    text = str(value or "").strip().lower()
    return text.rstrip("/")


def _clean_text(value: Any) -> str:
    """Nettoie une chaîne simple en conservant uniquement sa forme trim."""
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _clean_text_preserve_case(value: Any) -> str:
    """Nettoie une chaîne sans la forcer en minuscule."""
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _normalize_canal_row(row: pd.Series) -> str:
    """Déduit un canal propre si la source n'en a pas fourni un."""
    existing = normalize_canal(row.get("canal", ""), fallback="")
    if existing:
        return existing
    return TYPE_TO_CANAL.get(str(row.get("type", "autre")), "web")


def _normalize_nature_row(row: pd.Series) -> str:
    """Déduit une nature technique propre si elle n'est pas fournie."""
    existing = normalize_nature(row.get("nature_technique", ""), fallback="")
    if existing:
        return existing
    return TYPE_TO_NATURE.get(str(row.get("type", "autre")), "autre")


def _normalize_score_row(row: pd.Series) -> float:
    """Borne et complète un score de confiance par défaut."""
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


def _normalize_count(value: Any) -> int:
    """Normalise un compteur de signalements vers un entier positif."""
    try:
        parsed = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 1
    return parsed if parsed > 0 else 1


def _coerce_bool(value: Any) -> bool:
    """Interprète proprement un booléen venu du CSV/pandas."""
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
    raw_files = sorted(glob.glob(str(DATA_DIR / "raw_*.json")))
    if not raw_files:
        logger.error("Aucun fichier raw_*.json trouvé dans %s. Exécutez d'abord collecter.py.", DATA_DIR)
        sys.exit(1)

    latest_raw = raw_files[-1]
    logger.info("Chargement du fichier brut : %s", latest_raw)

    with open(latest_raw, "r", encoding="utf-8") as handle:
        raw_data = json.load(handle)

    df_clean = aggregate_sources(raw_data)
    if df_clean.empty:
        logger.warning("Le DataFrame nettoyé est vide - vérifiez les sources.")
        sys.exit(1)

    output_path = DATA_DIR / "clean_dataset.csv"
    df_clean.to_csv(output_path, index=False, encoding="utf-8")
    report_path, sample_path = save_quality_outputs(df_clean)

    logger.info("Dataset nettoyé sauvegardé dans : %s (%d lignes).", output_path, len(df_clean))
    logger.info("Rapport qualité sauvegardé dans : %s", report_path)
    logger.info("Échantillon de revue des 'autre' sauvegardé dans : %s", sample_path)
    print(f"\nAgrégation terminée : {len(df_clean)} entrées dans {output_path}")
