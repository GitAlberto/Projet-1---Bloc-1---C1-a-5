"""
Socle commun de bootstrap pour ArnaqueRadar.

Ce module centralise :
- la resolution de la racine projet
- le chargement du fichier `.env`

L'objectif est d'eviter de dupliquer partout la meme logique de boot.
Les scripts d'entree peuvent encore ajouter ponctuellement la racine projet
au `sys.path` s'ils sont executes directement depuis un sous-dossier, mais
la resolution de configuration doit rester unifiee ici.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
ENV_PATH = PROJECT_ROOT / ".env"


def load_project_env() -> Path:
    """
    Charge le fichier `.env` du projet et retourne sa racine.

    Retour :
        Path : racine du projet `arnaqueradar`.
    """
    load_dotenv(ENV_PATH)
    return PROJECT_ROOT


__all__ = ["ENV_PATH", "PROJECT_ROOT", "load_project_env"]
