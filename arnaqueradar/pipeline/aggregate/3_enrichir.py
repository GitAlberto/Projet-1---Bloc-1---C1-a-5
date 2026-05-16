"""
Étape 3 - Enrichissement métier du dataset nettoyé.

Cette étape sert à consolider les champs analytiques utiles :
- type_arnaque
- canal
- nature_technique
- score_confiance
- type_raw
- source_category_raw
- keywords_matched
- classifier_version

Important :
- les connecteurs enrichissent déjà beaucoup à la collecte
- cette étape ne refait pas une "seconde collecte"
- elle harmonise et complète ce qui vient des sources

Sorties :
- data/3_dataset_enrichi.csv
- data/clean_dataset.csv  (copie de compatibilité pour l'import existant)
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.steps import stage_3_enrich


if __name__ == "__main__":
    result = stage_3_enrich()

    # ------------------------------------------------------------------
    # On garde les deux chemins visibles :
    # - le fichier d'étape 3 pour la lecture pédagogique du pipeline
    # - le fichier historique `clean_dataset.csv` pour ne rien casser
    #   dans les scripts déjà existants.
    # ------------------------------------------------------------------
    print("\n=== Étape 3 terminée : enrichissement métier ===")
    print(f"Lignes enrichies : {result['rows']}")
    print(f"Fichier enrichi d'étape : {result['enriched_path']}")
    print(f"Fichier final compatible import : {result['compatibility_path']}")
