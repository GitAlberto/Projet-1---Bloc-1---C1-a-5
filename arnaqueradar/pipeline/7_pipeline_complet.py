"""
Étape 7 - Exécution complète du pipeline ArnaqueRadar.

Ce script chaÎne toutes les étapes dans l'ordre :
1. collecte
2. nettoyage
3. enrichissement
4. contrôle qualité
5. import PostgreSQL
6. préparation du dataset d'analyse / ML

Il sert surtout pour :
- rejouer tout le pipeline d'un coup
- préparer rapidement une démo
- vérifier qu'aucune étape ne s'est cassée dans l'enchaînement complet
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.steps import stage_7_full_pipeline


if __name__ == "__main__":
    result = stage_7_full_pipeline()

    # ------------------------------------------------------------------
    # On résume ici les chemins et volumes clés de tout le pipeline.
    # L'idée est qu'en une seule exécution on puisse vérifier
    # l'ensemble de la chaîne sans relire tous les logs détaillés.
    # ------------------------------------------------------------------
    print("\n=== Pipeline complet terminé ===")
    print(f"Brut : {result['stage_1']['raw_path']} ({result['stage_1']['rows']} lignes)")
    print(f"Nettoyé : {result['stage_2']['cleaned_path']} ({result['stage_2']['rows']} lignes)")
    print(f"Enrichi : {result['stage_3']['enriched_path']} ({result['stage_3']['rows']} lignes)")
    print(f"Qualité JSON : {result['stage_4']['quality_report_path']}")
    print(f"Qualité sample : {result['stage_4']['quality_sample_path']}")
    print(f"Import SQL : {result['stage_5']['inserted']} insertions, {result['stage_5']['errors']} erreurs")
    print(f"Dataset ML : {result['stage_6']['ml_dataset_path']} ({result['stage_6']['rows']} lignes)")
