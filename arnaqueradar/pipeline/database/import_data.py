"""
Import du dataset enrichi en base PostgreSQL.

Le module importe un jeu de donnees enrichi au niveau "evidence" :
une ligne = un constat source. L'import consolide ensuite par couple
`(url, date_signalement)` dans `signalements`, puis conserve chaque
preuve de corroboration dans `signalement_sources`.

Ainsi :
- la table principale reste simple pour l'API
- la provenance multi-sources n'est plus perdue
"""

from __future__ import annotations

import logging
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg2
import psycopg2.extras

PROJECT_ROOT_HINT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT_HINT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_HINT))

from bootstrap import PROJECT_ROOT, load_project_env

load_project_env()

from pipeline.database.connection import get_psycopg2_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("import_data")

CSV_PATH = PROJECT_ROOT / "data" / "clean_dataset.csv"
IMPORT_COMMIT_EVERY_GROUPS = max(int(os.getenv("PG_IMPORT_COMMIT_EVERY_GROUPS", "200")), 1)
IMPORT_PROGRESS_EVERY_GROUPS = max(int(os.getenv("PG_IMPORT_PROGRESS_EVERY_GROUPS", "1000")), 1)

TYPE_CODE_MAP: dict[str, str] = {
    "phishing": "phishing",
    "malware_distribution": "malware_distribution",
    "sms_frauduleux": "sms_frauduleux",
    "violation_rgpd": "violation_rgpd",
    "fraude_cpf": "fraude_cpf",
    "arnaque_achat": "arnaque_achat",
    "faux_support": "faux_support",
    "autre": "autre",
}

SOURCE_CODE_MAP: dict[str, str] = {
    "urlhaus": "urlhaus",
    "malwaretips": "malwaretips",
    "cnil_csv": "cnil_csv",
    "pg_history": "pg_history",
    "hive_logs": "hive_logs",
}

REQUIRED_SIGNAL_TABLES = {"signalements", "signalement_sources", "types_arnaque", "regions", "sources"}
REQUIRED_SIGNAL_COLUMNS: dict[str, set[str]] = {
    "signalements": {
        "id",
        "url",
        "type_id",
        "region_id",
        "source_id",
        "date_signalement",
        "verified",
        "titre",
        "nb_signalements",
        "canal",
        "nature_technique",
        "score_confiance",
        "type_raw",
        "source_category_raw",
        "keywords_matched",
        "classifier_version",
    },
    "signalement_sources": {
        "id",
        "signalement_id",
        "source_id",
        "date_observation",
        "verified",
        "titre",
        "region_raw",
        "canal",
        "nature_technique",
        "score_confiance",
        "type_raw",
        "source_category_raw",
        "keywords_matched",
        "classifier_version",
        "source_interne",
        "nb_signalements",
    },
}


def _get_connection():
    """Cree une connexion psycopg2 via la couche centralisee database.connection."""
    return get_psycopg2_connection()


def _load_lookup_tables(cursor) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    """Charge les tables de reference."""
    cursor.execute("SELECT id, code FROM types_arnaque;")
    types_map = {row["code"]: row["id"] for row in cursor.fetchall()}

    cursor.execute("SELECT id, nom FROM regions;")
    regions_map = {row["nom"].lower(): row["id"] for row in cursor.fetchall()}

    cursor.execute("SELECT id, code FROM sources;")
    sources_map = {row["code"]: row["id"] for row in cursor.fetchall()}

    return types_map, regions_map, sources_map


def _assert_required_tables(cursor) -> None:
    """
    Verifie que les tables attendues existent.

    On refuse de muter le schema a chaud : les migrations restent la seule
    source de verite.
    """
    cursor.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        """
    )
    available = {row["table_name"] for row in cursor.fetchall()}
    missing = sorted(REQUIRED_SIGNAL_TABLES - available)
    if missing:
        raise RuntimeError(
            "Schema incomplet. Executez la migration pipeline/database/migrations/001_init.sql "
            "ou, pour une base deja existante, pipeline/database/migrations/002_align_runtime_schema.sql "
            f"avant l'import. Tables manquantes : {', '.join(missing)}"
        )


def _assert_required_columns(cursor) -> None:
    """
    Verifie que les colonnes du schema enrichi existent bien.

    Cette verification est importante pour les bases deja creees avant
    l'introduction du modele consolide + evidences.
    """
    cursor.execute(
        """
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = ANY(%s)
        """,
        (list(REQUIRED_SIGNAL_COLUMNS.keys()),),
    )
    columns_by_table: dict[str, set[str]] = {}
    for row in cursor.fetchall():
        columns_by_table.setdefault(row["table_name"], set()).add(row["column_name"])

    missing_by_table: list[str] = []
    for table_name, required_columns in REQUIRED_SIGNAL_COLUMNS.items():
        available_columns = columns_by_table.get(table_name, set())
        missing_columns = sorted(required_columns - available_columns)
        if missing_columns:
            missing_by_table.append(f"{table_name} -> {', '.join(missing_columns)}")

    if missing_by_table:
        raise RuntimeError(
            "Schema SQL obsolescent detecte. Executez "
            "pipeline/database/migrations/002_align_runtime_schema.sql avant l'import. "
            f"Colonnes manquantes : {' | '.join(missing_by_table)}"
        )


def _resolve_region_id(region_raw: str, regions_map: dict[str, int]) -> int | None:
    """Resout une region libre vers son ID."""
    if not region_raw or str(region_raw) in {"nan", ""}:
        return regions_map.get("inconnue")
    return regions_map.get(str(region_raw).strip().lower(), regions_map.get("inconnue"))


def _coerce_text(value: Any, default: str | None = None) -> str | None:
    """Nettoie une valeur texte pandas/CSV."""
    if value is None:
        return default
    text = str(value).strip()
    if text.lower() == "nan" or text == "":
        return default
    return text


def _coerce_bool(value: Any) -> bool:
    """Convertit proprement une valeur libre en bool."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "vrai", "yes", "oui"}


def _coerce_int(value: Any, default: int = 1) -> int:
    """Convertit un compteur libre en entier positif."""
    try:
        parsed = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _coerce_float(value: Any, default: float | None = None) -> float | None:
    """Borne un score dans [0, 1]."""
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return default
    return round(min(max(parsed, 0.0), 1.0), 3)


def _normalize_source_code(value: Any) -> str:
    """Normalise un code source et leve si la source est inconnue."""
    raw = str(value or "").strip().lower()
    if raw not in SOURCE_CODE_MAP:
        raise ValueError(f"source inconnue ou non autorisee: {raw!r}")
    return SOURCE_CODE_MAP[raw]


def _normalize_type_code(value: Any) -> str:
    """Normalise un type d'arnaque au vocabulaire controle."""
    raw = str(value or "autre").strip().lower()
    return TYPE_CODE_MAP.get(raw, "autre")


def _normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Garantit les colonnes attendues et nettoie les types de base."""
    working = df.copy()
    required_columns = [
        "url",
        "type",
        "source",
        "date_signalement",
        "region",
        "verified",
        "titre",
        "nb_signalements",
        "canal",
        "nature_technique",
        "score_confiance",
        "type_raw",
        "source_category_raw",
        "keywords_matched",
        "classifier_version",
        "source_interne",
    ]
    for column in required_columns:
        if column not in working.columns:
            working[column] = ""

    working["url"] = working["url"].fillna("").astype(str).str.strip()
    working["date_signalement"] = working["date_signalement"].fillna("").astype(str).str.strip()
    working = working.loc[(working["url"] != "") & (working["date_signalement"] != "")].copy()

    working["type"] = working["type"].apply(_normalize_type_code)
    working["source"] = working["source"].apply(_normalize_source_code)
    working["verified"] = working["verified"].apply(_coerce_bool)
    working["nb_signalements"] = working["nb_signalements"].apply(_coerce_int)
    working["score_confiance"] = working["score_confiance"].apply(_coerce_float)

    text_columns = [
        "region",
        "titre",
        "canal",
        "nature_technique",
        "type_raw",
        "source_category_raw",
        "keywords_matched",
        "classifier_version",
        "source_interne",
    ]
    for column in text_columns:
        working[column] = working[column].apply(_coerce_text, default="")

    return working.reset_index(drop=True)


def _row_priority(row: dict[str, Any]) -> tuple[float, int, int]:
    """
    Retourne une cle de tri pour choisir la meilleure evidence d'un groupe.

    Priorites :
    1. meilleur score de confiance
    2. type explicite non 'autre'
    3. titre present
    """
    return (
        float(row.get("score_confiance") or 0.0),
        0 if row.get("type") == "autre" else 1,
        1 if row.get("titre") else 0,
    )


def _pick_primary_row(group_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Choisit l'evidence la plus pertinente pour representer le signalement consolide."""
    return max(group_rows, key=_row_priority)


def _pick_region(group_rows: list[dict[str, Any]]) -> str:
    """Choisit la region la plus frequente et non vide."""
    values = [str(row.get("region", "") or "").strip() for row in group_rows]
    values = [value for value in values if value]
    if not values:
        return ""
    return Counter(values).most_common(1)[0][0]


def _consolidate_group(group_df: pd.DataFrame) -> dict[str, Any]:
    """
    Consolide plusieurs evidences source par source en un signalement cible.
    """
    rows = group_df.to_dict(orient="records")
    primary = _pick_primary_row(rows)
    region = _pick_region(rows)
    nb_signalements = sum(_coerce_int(row.get("nb_signalements", 1), default=1) for row in rows)

    consolidated = {
        "url": primary["url"],
        "date_signalement": primary["date_signalement"],
        "type": primary["type"],
        "source": primary["source"],
        "region": region,
        "verified": any(bool(row.get("verified", False)) for row in rows),
        "titre": primary.get("titre", ""),
        "nb_signalements": nb_signalements,
        "canal": primary.get("canal", ""),
        "nature_technique": primary.get("nature_technique", ""),
        "score_confiance": primary.get("score_confiance", None),
        "type_raw": primary.get("type_raw", ""),
        "source_category_raw": primary.get("source_category_raw", ""),
        "keywords_matched": primary.get("keywords_matched", ""),
        "classifier_version": primary.get("classifier_version", ""),
    }
    return consolidated


def _insert_or_refresh_signalement(
    cursor,
    consolidated: dict[str, Any],
    types_map: dict[str, int],
    regions_map: dict[str, int],
    sources_map: dict[str, int],
) -> tuple[int, bool]:
    """
    Cree le signalement consolide s'il n'existe pas, sinon le met a jour.

    Retour :
        tuple[id_signalement, est_nouvelle_insertion]
    """
    type_id = types_map[consolidated["type"]]
    region_id = _resolve_region_id(consolidated["region"], regions_map)
    source_id = sources_map[consolidated["source"]]

    cursor.execute(
        """
        INSERT INTO signalements
            (
                url, type_id, region_id, source_id, date_signalement, verified,
                titre, nb_signalements, canal, nature_technique, score_confiance,
                type_raw, source_category_raw, keywords_matched, classifier_version
            )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT ON CONSTRAINT uq_signalement_url_date DO NOTHING
        RETURNING id
        """,
        (
            consolidated["url"],
            type_id,
            region_id,
            source_id,
            consolidated["date_signalement"],
            consolidated["verified"],
            consolidated["titre"] or None,
            consolidated["nb_signalements"],
            consolidated["canal"] or None,
            consolidated["nature_technique"] or None,
            consolidated["score_confiance"],
            consolidated["type_raw"] or None,
            consolidated["source_category_raw"] or None,
            consolidated["keywords_matched"] or None,
            consolidated["classifier_version"] or None,
        ),
    )
    inserted = cursor.fetchone()
    if inserted:
        return int(inserted[0]), True

    cursor.execute(
        """
        SELECT id
        FROM signalements
        WHERE url = %s AND date_signalement = %s
        """,
        (consolidated["url"], consolidated["date_signalement"]),
    )
    existing_id = int(cursor.fetchone()[0])

    cursor.execute(
        """
        UPDATE signalements
        SET
            type_id = %s,
            region_id = %s,
            source_id = %s,
            verified = %s,
            titre = %s,
            nb_signalements = %s,
            canal = %s,
            nature_technique = %s,
            score_confiance = %s,
            type_raw = %s,
            source_category_raw = %s,
            keywords_matched = %s,
            classifier_version = %s
        WHERE id = %s
        """,
        (
            type_id,
            region_id,
            source_id,
            consolidated["verified"],
            consolidated["titre"] or None,
            consolidated["nb_signalements"],
            consolidated["canal"] or None,
            consolidated["nature_technique"] or None,
            consolidated["score_confiance"],
            consolidated["type_raw"] or None,
            consolidated["source_category_raw"] or None,
            consolidated["keywords_matched"] or None,
            consolidated["classifier_version"] or None,
            existing_id,
        ),
    )
    return existing_id, False


def _insert_evidence_row(
    cursor,
    signalement_id: int,
    row: dict[str, Any],
    sources_map: dict[str, int],
) -> int:
    """Insere une evidence source par source si elle n'existe pas deja."""
    cursor.execute(
        """
        INSERT INTO signalement_sources
            (
                signalement_id, source_id, date_observation, verified, titre, region_raw,
                canal, nature_technique, score_confiance, type_raw, source_category_raw,
                keywords_matched, classifier_version, source_interne, nb_signalements
            )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT ON CONSTRAINT uq_signalement_source_observation DO NOTHING
        """,
        (
            signalement_id,
            sources_map[row["source"]],
            row["date_signalement"],
            bool(row["verified"]),
            row["titre"] or None,
            row["region"] or None,
            row["canal"] or None,
            row["nature_technique"] or None,
            row["score_confiance"],
            row["type_raw"] or "",
            row["source_category_raw"] or None,
            row["keywords_matched"] or None,
            row["classifier_version"] or None,
            row["source_interne"] or "",
            row["nb_signalements"],
        ),
    )
    return max(cursor.rowcount, 0)


def import_clean_data() -> tuple[int, int]:
    """
    Importe le dataset enrichi en base.

    Retour :
        tuple[int, int] : (nb_nouveaux_signalements, nb_erreurs)
    """
    if not CSV_PATH.exists():
        logger.error(
            "Fichier introuvable : %s - executez d'abord pipeline/aggregate/3_enrichir.py.",
            CSV_PATH,
        )
        return 0, 0

    raw_df = pd.read_csv(CSV_PATH, encoding="utf-8", low_memory=False)
    df = _normalize_dataframe(raw_df)
    logger.info("import_data : %d lignes evidence lues depuis %s.", len(df), CSV_PATH)

    conn = None
    nb_signalements_insertes = 0
    nb_evidences_inserees = 0
    nb_erreurs = 0

    try:
        conn = _get_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            _assert_required_tables(cursor)
            _assert_required_columns(cursor)
            types_map, regions_map, sources_map = _load_lookup_tables(cursor)

        with conn.cursor() as cursor:
            grouped = df.groupby(["url", "date_signalement"], sort=False, dropna=False)
            total_groups = grouped.ngroups
            groups_since_commit = 0
            processed_groups = 0

            for (_, _), group in grouped:
                cursor.execute("SAVEPOINT signalement_group")
                try:
                    consolidated = _consolidate_group(group)
                    signalement_id, inserted = _insert_or_refresh_signalement(
                        cursor,
                        consolidated,
                        types_map,
                        regions_map,
                        sources_map,
                    )
                    if inserted:
                        nb_signalements_insertes += 1

                    for evidence in group.to_dict(orient="records"):
                        nb_evidences_inserees += _insert_evidence_row(
                            cursor,
                            signalement_id,
                            evidence,
                            sources_map,
                        )
                except Exception as exc:
                    logger.error(
                        "Import groupe (%s, %s) en erreur - %s",
                        group.iloc[0]["url"],
                        group.iloc[0]["date_signalement"],
                        exc,
                    )
                    cursor.execute("ROLLBACK TO SAVEPOINT signalement_group")
                    nb_erreurs += 1
                finally:
                    processed_groups += 1
                    groups_since_commit += 1

                # ------------------------------------------------------------------
                # On borne la taille de la transaction pour eviter :
                # - l'accumulation de milliers de SAVEPOINTS
                # - la saturation `max_locks_per_transaction` dans PostgreSQL
                # - un rollback geant si un incident survient tardivement
                # ------------------------------------------------------------------
                if groups_since_commit >= IMPORT_COMMIT_EVERY_GROUPS:
                    conn.commit()
                    groups_since_commit = 0
                    if (
                        processed_groups % IMPORT_PROGRESS_EVERY_GROUPS == 0
                        or processed_groups == total_groups
                    ):
                        logger.info(
                            "import_data : progression %d/%d groupes importes (%d signalements, %d evidences, %d erreurs).",
                            processed_groups,
                            total_groups,
                            nb_signalements_insertes,
                            nb_evidences_inserees,
                            nb_erreurs,
                        )
                elif processed_groups % IMPORT_PROGRESS_EVERY_GROUPS == 0:
                    logger.info(
                        "import_data : progression %d/%d groupes traites (%d signalements, %d evidences, %d erreurs).",
                        processed_groups,
                        total_groups,
                        nb_signalements_insertes,
                        nb_evidences_inserees,
                        nb_erreurs,
                    )

            if groups_since_commit > 0:
                conn.commit()

    except psycopg2.OperationalError as exc:
        logger.error("import_data : connexion PostgreSQL impossible - %s", exc)
        nb_erreurs = max(nb_erreurs, 1)
    except RuntimeError as exc:
        logger.error(str(exc))
        nb_erreurs = max(nb_erreurs, 1)
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        logger.error("import_data : erreur inattendue durant l'import - %s", exc)
        nb_erreurs = max(nb_erreurs, 1)
    finally:
        if conn is not None:
            conn.close()

    logger.info(
        "import_data : %d nouveaux signalements consolides, %d evidences inserees, %d erreurs.",
        nb_signalements_insertes,
        nb_evidences_inserees,
        nb_erreurs,
    )
    return nb_signalements_insertes, nb_erreurs


if __name__ == "__main__":
    logger.info("Demarrage de l'import des donnees enrichies en base.")
    ok, err = import_clean_data()
    logger.info("Import termine - Nouveaux signalements : %d | Erreurs : %d", ok, err)
    print(f"\nImport termine : {ok} nouveaux signalements, {err} erreurs.")
