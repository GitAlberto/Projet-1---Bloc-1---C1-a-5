"""
Couche de connexion PostgreSQL unifiee pour ArnaqueRadar.

Ce module centralise la creation des connexions psycopg2 et SQLAlchemy
afin d'eviter la duplication de la logique de connexion dans chaque module.

Regles de conception :
- Les parametres sont toujours passes comme kwargs a psycopg2.connect()
  pour eviter le bug d'encodage Windows avec les mots de passe contenant
  des caracteres speciaux (espaces, accents) via DATABASE_URL en string.
- SQLAlchemy utilise URL.create() pour la meme raison.
- Tous les modules du projet importent depuis ici plutot que de reconstituer
  leur propre logique de connexion.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg2
import psycopg2.extras
from sqlalchemy import create_engine
from sqlalchemy.engine import URL as SqlAlchemyURL
from sqlalchemy.orm import Session

from bootstrap import load_project_env

load_project_env()


def get_pg_kwargs() -> dict:
    """
    Retourne les kwargs de connexion PostgreSQL depuis les variables PG_*.

    Retourne :
        dict : parametres compatibles avec psycopg2.connect(**kwargs).
    """
    return {
        "host": os.getenv("PG_HOST", "localhost"),
        "port": int(os.getenv("PG_PORT", "5432")),
        "dbname": os.getenv("PG_DB", "arnaqueradar"),
        "user": os.getenv("PG_USER", "postgres"),
        "password": os.getenv("PG_PASSWORD", ""),
        "connect_timeout": 10,
    }


def get_psycopg2_connection():
    """
    Cree et retourne une connexion psycopg2 active.

    Les parametres sont passes comme kwargs (jamais via DATABASE_URL en string)
    pour eviter le bug d'encodage Windows avec les mots de passe speciaux.

    Retourne :
        psycopg2.connection : connexion active.

    Leve :
        psycopg2.OperationalError : si la connexion echoue.
    """
    return psycopg2.connect(**get_pg_kwargs())


def get_sqlalchemy_url() -> SqlAlchemyURL:
    """
    Construit l'URL de connexion SQLAlchemy depuis les variables PG_*.

    Utilise URL.create() pour gerer correctement les mots de passe avec
    caracteres speciaux sans URL-encoding manuel.

    Retourne :
        URL : objet URL SQLAlchemy pret a l'emploi.
    """
    return SqlAlchemyURL.create(
        drivername="postgresql+psycopg2",
        host=os.getenv("PG_HOST", "localhost"),
        port=int(os.getenv("PG_PORT", "5432")),
        database=os.getenv("PG_DB", "arnaqueradar"),
        username=os.getenv("PG_USER", "postgres"),
        password=os.getenv("PG_PASSWORD", ""),
    )


def get_engine():
    """
    Cree et retourne le moteur SQLAlchemy configure.

    Retourne :
        Engine : instance du moteur SQLAlchemy pret a l'emploi.
    """
    return create_engine(get_sqlalchemy_url(), pool_pre_ping=True)


def get_session() -> Session:
    """
    Cree et retourne une session SQLAlchemy.

    Retourne :
        Session : session active liee au moteur configure.
    """
    return Session(get_engine())


__all__ = [
    "get_pg_kwargs",
    "get_psycopg2_connection",
    "get_sqlalchemy_url",
    "get_engine",
    "get_session",
]
