"""
Étape 5 - Import du dataset enrichi en base PostgreSQL.

Cette étape lit le fichier final `clean_dataset.csv`
et charge les signalements dans la base relationnelle cible.

On conserve ce point d'entrée séparé pour que l'import
reste complètement dissocié :
- de la collecte
- du nettoyage
- de l'enrichissement
- du contrôle qualité
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.steps import stage_5_import


if __name__ == "__main__":
    result = stage_5_import()

    # ------------------------------------------------------------------
    # Le compteur affiché ici correspond désormais aux vraies insertions.
    # En cas de relance sur le même dataset, il peut donc retomber à 0
    # sans que cela signifie un échec.
    # ------------------------------------------------------------------
    print("\n=== Étape 5 terminée : import SQL ===")
    print(f"Fichier importé : {result['import_source_path']}")
    print(f"Insertions réussies : {result['inserted']}")
    print(f"Erreurs : {result['errors']}")
