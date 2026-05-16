"""
Étape 6 - Préparation d'un dataset orienté analyse avancée / machine learning.

Ce script ne lance aucun modèle.
Son rôle est de préparer un dataset plat, plus simple à exploiter
dans un notebook, un dashboard avancé ou une future expérimentation ML.

Exemples de colonnes ajoutées :
- longueur d'URL
- profondeur de path
- présence de query string
- host sous forme d'IP ou non
- extension de fichier éventuelle
- nombre de mots-clés déclenchés
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.steps import stage_6_prepare_ml_dataset


if __name__ == "__main__":
    result = stage_6_prepare_ml_dataset()

    # ------------------------------------------------------------------
    # Le but est de rendre cette étape très lisible :
    # la personne qui prépare la partie data science doit savoir
    # exactement quel fichier ouvrir ensuite.
    # ------------------------------------------------------------------
    print("\n=== Étape 6 terminée : dataset analyse / ML ===")
    print(f"Lignes exportées : {result['rows']}")
    print(f"Fichier ML prêt à l'emploi : {result['ml_dataset_path']}")
