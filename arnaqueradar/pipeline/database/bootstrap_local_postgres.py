"""
Bootstrap local PostgreSQL pour ArnaqueRadar.

Objectif :
- creer la base locale si elle n'existe pas encore
- appliquer les migrations SQL idempotentes
- verifier que le schema persistant attendu est bien present

Ce module ne peuple pas par defaut la source 4 avec des donnees de demo.
Le seed historique pgAdmin reste optionnel via `--with-history-seed`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2 import sql

PROJECT_ROOT_HINT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT_HINT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_HINT))

from bootstrap import load_project_env

load_project_env()

from pipeline.database.connection import get_pg_kwargs

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_FILES = [
    PROJECT_ROOT / "pipeline" / "database" / "migrations" / "001_init.sql",
    PROJECT_ROOT / "pipeline" / "database" / "migrations" / "002_align_runtime_schema.sql",
]
OPTIONAL_HISTORY_SEED_FILE = PROJECT_ROOT / "queries" / "pg_history_pgadmin_setup.sql"

REQUIRED_TABLES = [
    "types_arnaque",
    "regions",
    "sources",
    "signalements",
    "signalement_sources",
    "signalements_historique",
]


def _target_db_name() -> str:
    return str(get_pg_kwargs()["dbname"])


def _admin_pg_kwargs() -> dict[str, Any]:
    kwargs = dict(get_pg_kwargs())
    kwargs["dbname"] = "postgres"
    return kwargs


def ensure_database_exists() -> bool:
    """
    Cree la base cible si elle n'existe pas.

    Retour :
        bool : True si la base a ete creee, False si elle existait deja.
    """
    target_db = _target_db_name()
    conn = psycopg2.connect(**_admin_pg_kwargs())
    conn.autocommit = True
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target_db,))
            if cursor.fetchone():
                return False
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_db)))
            return True
    finally:
        conn.close()


def _connect_target_db():
    return psycopg2.connect(**get_pg_kwargs())


def apply_sql_file(path: Path) -> None:
    """
    Execute integralement un fichier SQL sur la base cible.
    """
    if not path.exists():
        raise FileNotFoundError(f"Fichier SQL introuvable : {path}")

    sql_text = path.read_text(encoding="utf-8-sig")
    conn = _connect_target_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql_text)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def verify_postgres_schema() -> dict[str, Any]:
    """
    Verifie que la base persistante expose bien le schema attendu.
    """
    summary: dict[str, Any] = {
        "database": _target_db_name(),
        "tables": [],
        "table_counts": {},
        "sources": [],
    }

    conn = _connect_target_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name
                """
            )
            tables = [row[0] for row in cursor.fetchall()]
            summary["tables"] = tables

            missing = [table for table in REQUIRED_TABLES if table not in tables]
            summary["missing_tables"] = missing

            for table_name in ["signalements_historique", "signalements", "signalement_sources"]:
                if table_name in tables:
                    cursor.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table_name)))
                    summary["table_counts"][table_name] = int(cursor.fetchone()[0])

            if "sources" in tables:
                cursor.execute(
                    """
                    SELECT code, type_source
                    FROM sources
                    ORDER BY code
                    """
                )
                summary["sources"] = cursor.fetchall()
    finally:
        conn.close()

    return summary


def bootstrap_local_postgres(with_history_seed: bool = False) -> dict[str, Any]:
    """
    Initialise ou aligne la base locale PostgreSQL.
    """
    created = ensure_database_exists()

    for path in MIGRATION_FILES:
        apply_sql_file(path)

    if with_history_seed:
        apply_sql_file(OPTIONAL_HISTORY_SEED_FILE)

    summary = verify_postgres_schema()
    summary["created_database"] = created
    summary["applied_migrations"] = [str(path.relative_to(PROJECT_ROOT)) for path in MIGRATION_FILES]
    summary["history_seed_applied"] = with_history_seed
    return summary


def _print_summary(summary: dict[str, Any]) -> None:
    print("\n=== PostgreSQL local - verification ===")
    print(f"Base cible : {summary['database']}")
    if "created_database" in summary:
        print(f"Base creee : {'oui' if summary['created_database'] else 'non'}")
    if "applied_migrations" in summary:
        print("Migrations :")
        for path in summary["applied_migrations"]:
            print(f"  - {path}")
    print(f"History seed applique : {'oui' if summary.get('history_seed_applied') else 'non'}")
    print("Tables detectees :")
    for table_name in summary.get("tables", []):
        count = summary.get("table_counts", {}).get(table_name)
        if count is None:
            print(f"  - {table_name}")
        else:
            print(f"  - {table_name}: {count} lignes")

    missing_tables = summary.get("missing_tables", [])
    if missing_tables:
        print("Tables manquantes :")
        for table_name in missing_tables:
            print(f"  - {table_name}")

    if summary.get("sources"):
        print("Sources referencees :")
        for code, type_source in summary["sources"]:
            print(f"  - {code} ({type_source})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Initialise et verifie la base PostgreSQL locale ArnaqueRadar.")
    parser.add_argument(
        "--with-history-seed",
        action="store_true",
        help="Applique aussi queries/pg_history_pgadmin_setup.sql pour peupler la source 4.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="N'applique aucune migration et affiche seulement l'etat courant de la base.",
    )
    args = parser.parse_args(argv)

    if args.verify_only:
        summary = verify_postgres_schema()
    else:
        summary = bootstrap_local_postgres(with_history_seed=args.with_history_seed)

    _print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
