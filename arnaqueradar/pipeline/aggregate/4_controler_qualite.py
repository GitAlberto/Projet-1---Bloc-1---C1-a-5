"""
Étape 4 - Contrôle qualité du dataset enrichi.

Cette étape génère des artefacts d'audit très utiles :
- un rapport qualité global au format JSON
- un échantillon CSV des lignes à relire manuellement

Pourquoi c'est important :
- éviter de se contenter d'un gros volume de données
- suivre la dérive éventuelle des sources
- garder une boucle d'amélioration continue sur les règles métier
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.steps import stage_4_quality


if __name__ == "__main__":
    result = stage_4_quality()
    report = result["quality_report"]

    # ------------------------------------------------------------------
    # On affiche quelques indicateurs de synthèse immédiatement utiles.
    # Le détail complet reste dans le JSON, mais la console doit déjà
    # permettre une lecture rapide du niveau de qualité.
    # ------------------------------------------------------------------
    print("\n=== Étape 4 terminée : contrôle qualité ===")
    print(f"Rapport qualité : {result['report_path']}")
    print(f"Échantillon de revue : {result['sample_path']}")
    print(f"Total lignes : {report['total_rows']}")
    print(f"% autre global : {report['autre_global_pct']}")
    print(f"% régions vides : {report['region_vide_global_pct']}")
    print(f"Alertes : {report['alerts']}")
