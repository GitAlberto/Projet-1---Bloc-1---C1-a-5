"""
Etape 0 - Initialisation locale de la base PostgreSQL.

Ce point d'entree prepare la base persistante du projet :
- creation de la base si necessaire
- application des migrations SQL
- verification du schema

Par defaut, aucune donnee de demonstration n'est ajoutee a la source 4.
Utilisez `--with-history-seed` seulement si vous voulez peupler
`signalements_historique` avec le script pgAdmin fourni.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.database.bootstrap_local_postgres import main


if __name__ == "__main__":
    raise SystemExit(main())
