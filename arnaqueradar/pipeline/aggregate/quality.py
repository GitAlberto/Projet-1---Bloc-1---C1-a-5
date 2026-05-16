"""
Controle qualite des donnees enrichies ArnaqueRadar.

Ce sous-module est responsable uniquement du controle qualite :
- construction du rapport qualite JSON
- generation de l'echantillon de revue manuelle des "autres"
- sauvegarde des artefacts de qualite
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

QUALITY_TARGETS = {
    "autre_global_max_pct": 15.0,
    "autre_by_source_max_pct": 25.0,
    "score_confiance_min_for_review": 0.6,
    "min_rows_for_source_alert": 100,
}


def build_quality_report(df: pd.DataFrame) -> dict[str, Any]:
    """Construit un rapport qualite synthetique pour le dernier dataset propre."""
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

        autre_by_source[source_name] = {"rows": int(source_total), "autre_pct": source_autre_pct}
        empty_region_by_source[source_name] = {"rows": int(source_total), "region_vide_pct": source_region_empty_pct}
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

    return {
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


def build_other_review_sample(df: pd.DataFrame, max_total: int = 100, max_per_source: int = 25) -> pd.DataFrame:
    """Prepare un echantillon de revue manuelle des lignes classees en `autre`."""
    other_df = df.loc[df["type"] == "autre"].copy()
    columns = [
        "source", "url", "date_signalement", "type", "nature_technique",
        "canal", "score_confiance", "type_raw", "source_category_raw",
        "keywords_matched", "titre",
    ]
    if other_df.empty:
        return pd.DataFrame(columns=columns)

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

    return sample_df[columns].reset_index(drop=True)


def save_quality_outputs(
    df: pd.DataFrame,
    report_path: Path,
    sample_path: Path,
) -> tuple[Path, Path]:
    """Sauvegarde le rapport qualite JSON et l'echantillon CSV de revue."""
    report = build_quality_report(df)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    review_sample = build_other_review_sample(df)
    review_sample.to_csv(sample_path, index=False, encoding="utf-8")

    return report_path, sample_path


__all__ = [
    "QUALITY_TARGETS",
    "build_quality_report",
    "build_other_review_sample",
    "save_quality_outputs",
]
