"""
Étape 2 - Nettoyage technique des données brutes.

Cette étape est volontairement distincte de l'enrichissement métier.

Ici, on ne cherche PAS encore à mieux classifier les arnaques.
On fait uniquement le travail de "mise au propre" :
- suppression des entrées corrompues
- normalisation des dates
- normalisation des URLs
- nettoyage basique des champs texte
- déduplication

Sortie principale :
- data/2_dataset_nettoye.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.steps import stage_2_clean


if __name__ == "__main__":
    result = stage_2_clean()

    # ------------------------------------------------------------------
    # On affiche très explicitement la sortie d'étape pour éviter que
    # quelqu'un confonde le dataset nettoyé intermédiaire avec le dataset
    # final enrichi utilisé ensuite pour le reporting et l'import SQL.
    # ------------------------------------------------------------------
    print("\n=== Étape 2 terminée : nettoyage technique ===")
    print(f"Lignes après nettoyage : {result['rows']}")
    print(f"Fichier nettoyé intermédiaire : {result['cleaned_path']}")
