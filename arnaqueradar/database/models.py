"""
Module de définition des modèles SQLAlchemy pour ArnaqueRadar.

Ce module décrit le schéma de la base de données via l'ORM SQLAlchemy,
en reflétant le modèle physique issu de la migration 001_init.sql.
Il est utilisé par import_data.py et l'API pour les opérations de lecture/écriture.
"""

import os
from datetime import date, datetime
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

from sqlalchemy.engine import URL as SqlAlchemyURL

load_dotenv()


def _build_engine_url() -> SqlAlchemyURL:
    """
    Construit l'URL de connexion SQLAlchemy depuis les variables PG_*.

    Utilise sqlalchemy.engine.URL.create() plutot qu'une URL brute pour
    gerer correctement les caracteres speciaux (espaces, accents) dans
    le mot de passe sans necessiter d'URL-encoding manuel.

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

class Base(DeclarativeBase):
    """Classe de base commune à tous les modèles ORM."""
    pass


class TypeArnaque(Base):
    """
    Table de référence pour les types d'arnaques.

    Chaque type possède un code normalisé unique (ex: 'phishing', 'sms_frauduleux')
    utilisé comme vocabulaire contrôlé dans le pipeline.
    """

    __tablename__ = "types_arnaque"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    libelle: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    signalements: Mapped[list["Signalement"]] = relationship(back_populates="type_arnaque")

    def __repr__(self) -> str:
        return f"<TypeArnaque code={self.code!r}>"


class Region(Base):
    """
    Table de référence pour les régions françaises (métropole + DROM).

    Le code région suit la codification officielle INSEE.
    """

    __tablename__ = "regions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)
    nom: Mapped[str] = mapped_column(String(100), nullable=False)

    signalements: Mapped[list["Signalement"]] = relationship(back_populates="region")

    def __repr__(self) -> str:
        return f"<Region code={self.code!r} nom={self.nom!r}>"


class Source(Base):
    """
    Table de référence pour les sources de collecte.

    Chaque source est identifiée par un code unique et un type parmi :
    api, scraping, csv, sql, bigdata.
    """

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    libelle: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(255))
    type_source: Mapped[str] = mapped_column(
        String(20),
        CheckConstraint("type_source IN ('api', 'scraping', 'csv', 'sql', 'bigdata')"),
        nullable=False,
    )

    signalements: Mapped[list["Signalement"]] = relationship(back_populates="source")

    def __repr__(self) -> str:
        return f"<Source code={self.code!r}>"


class Signalement(Base):
    """
    Table principale stockant chaque signalement d'arnaque.

    Chaque enregistrement est lié à un type d'arnaque, une région et une source.
    La contrainte d'unicité (url, date_signalement) évite les doublons.
    """

    __tablename__ = "signalements"
    __table_args__ = (
        UniqueConstraint("url", "date_signalement", name="uq_signalement_url_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    type_id: Mapped[int] = mapped_column(Integer, ForeignKey("types_arnaque.id"), nullable=False)
    region_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("regions.id"))
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("sources.id"), nullable=False)
    date_signalement: Mapped[date] = mapped_column(Date, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    titre: Mapped[Optional[str]] = mapped_column(String(500))
    nb_signalements: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())

    type_arnaque: Mapped["TypeArnaque"] = relationship(back_populates="signalements")
    region: Mapped[Optional["Region"]] = relationship(back_populates="signalements")
    source: Mapped["Source"] = relationship(back_populates="signalements")

    def __repr__(self) -> str:
        return f"<Signalement id={self.id} url={self.url[:40]!r}>"


class SignalementHistorique(Base):
    """
    Table historique des signalements, alimentée par la source pg_history.

    Elle conserve les données brutes historiques sans les clés étrangères
    normalisées, ce qui facilite l'alimentation par des scripts externes.
    """

    __tablename__ = "signalements_historique"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    type_arnaque: Mapped[str] = mapped_column(String(50), nullable=False)
    region: Mapped[Optional[str]] = mapped_column(String(100))
    date_signalement: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="pg_history")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())

    def __repr__(self) -> str:
        return f"<SignalementHistorique id={self.id}>"


def get_engine():
    """
    Cree et retourne le moteur SQLAlchemy configure depuis les variables PG_*.

    Utilise URL.create() pour gerer les mots de passe avec caracteres speciaux
    (espaces, accents) sans necessiter d'URL-encoding dans le fichier .env.

    Retourne :
        Engine : instance du moteur SQLAlchemy pret a l'emploi.
    """
    return create_engine(_build_engine_url(), pool_pre_ping=True)


def get_session() -> Session:
    """
    Crée et retourne une session SQLAlchemy.

    Retourne :
        Session : session active liée au moteur configuré.
    """
    engine = get_engine()
    return Session(engine)
