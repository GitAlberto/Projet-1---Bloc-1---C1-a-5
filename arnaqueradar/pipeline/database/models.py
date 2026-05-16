"""
Modeles SQLAlchemy du projet ArnaqueRadar.

Le schema distingue desormais :
- `signalements` : enregistrement consolide par couple (url, date_signalement)
- `signalement_sources` : preuves / corroborations source par source

Cette separation permet de conserver la tracabilite multi-sources sans
polluer les usages simples de l'API qui continuent a lire `signalements`.
"""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

PROJECT_ROOT_HINT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT_HINT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_HINT))

from bootstrap import load_project_env

load_project_env()

from pipeline.database.connection import get_engine, get_session, get_sqlalchemy_url  # noqa: E402



class Base(DeclarativeBase):
    """Base declarative commune."""


class TypeArnaque(Base):
    """Table de reference des types d'arnaque."""

    __tablename__ = "types_arnaque"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    libelle: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    signalements: Mapped[list["Signalement"]] = relationship(back_populates="type_arnaque")

    def __repr__(self) -> str:
        return f"<TypeArnaque code={self.code!r}>"


class Region(Base):
    """Table de reference des regions."""

    __tablename__ = "regions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)
    nom: Mapped[str] = mapped_column(String(100), nullable=False)

    signalements: Mapped[list["Signalement"]] = relationship(back_populates="region")

    def __repr__(self) -> str:
        return f"<Region code={self.code!r} nom={self.nom!r}>"


class Source(Base):
    """Table de reference des sources de collecte."""

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

    signalements_primaires: Mapped[list["Signalement"]] = relationship(back_populates="source_primaire")
    evidences: Mapped[list["SignalementSource"]] = relationship(back_populates="source")

    def __repr__(self) -> str:
        return f"<Source code={self.code!r}>"


class Signalement(Base):
    """
    Table consolidee des signalements.

    Un signalement est unique par couple (url, date_signalement).
    Les corroborations detaillees par source sont conservees dans
    `signalement_sources`.
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
    canal: Mapped[Optional[str]] = mapped_column(String(30))
    nature_technique: Mapped[Optional[str]] = mapped_column(String(50))
    score_confiance: Mapped[Optional[float]] = mapped_column(Numeric(4, 3))
    type_raw: Mapped[Optional[str]] = mapped_column(String(100))
    source_category_raw: Mapped[Optional[str]] = mapped_column(String(255))
    keywords_matched: Mapped[Optional[str]] = mapped_column(Text)
    classifier_version: Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())

    type_arnaque: Mapped["TypeArnaque"] = relationship(back_populates="signalements")
    region: Mapped[Optional["Region"]] = relationship(back_populates="signalements")
    source_primaire: Mapped["Source"] = relationship(back_populates="signalements_primaires")
    evidences: Mapped[list["SignalementSource"]] = relationship(
        back_populates="signalement",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Signalement id={self.id} url={self.url[:40]!r}>"


class SignalementSource(Base):
    """
    Table de preuves par source.

    Chaque ligne de cette table capture le fait qu'une source donnee a observe
    ou classe un signalement consolide.
    """

    __tablename__ = "signalement_sources"
    __table_args__ = (
        UniqueConstraint(
            "signalement_id",
            "source_id",
            "date_observation",
            "source_interne",
            "type_raw",
            name="uq_signalement_source_observation",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signalement_id: Mapped[int] = mapped_column(Integer, ForeignKey("signalements.id"), nullable=False)
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("sources.id"), nullable=False)
    date_observation: Mapped[date] = mapped_column(Date, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    titre: Mapped[Optional[str]] = mapped_column(String(500))
    region_raw: Mapped[Optional[str]] = mapped_column(String(100))
    canal: Mapped[Optional[str]] = mapped_column(String(30))
    nature_technique: Mapped[Optional[str]] = mapped_column(String(50))
    score_confiance: Mapped[Optional[float]] = mapped_column(Numeric(4, 3))
    type_raw: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    source_category_raw: Mapped[Optional[str]] = mapped_column(String(255))
    keywords_matched: Mapped[Optional[str]] = mapped_column(Text)
    classifier_version: Mapped[Optional[str]] = mapped_column(String(50))
    source_interne: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    nb_signalements: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())

    signalement: Mapped["Signalement"] = relationship(back_populates="evidences")
    source: Mapped["Source"] = relationship(back_populates="evidences")

    def __repr__(self) -> str:
        return f"<SignalementSource signalement_id={self.signalement_id} source_id={self.source_id}>"


class SignalementHistorique(Base):
    """Table source de la collecte PostgreSQL historique."""

    __tablename__ = "signalements_historique"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    type_arnaque: Mapped[str] = mapped_column(String(50), nullable=False)
    region: Mapped[Optional[str]] = mapped_column(String(100))
    date_signalement: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="pg_history")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    canal: Mapped[str] = mapped_column(String(30), nullable=False, default="web")
    statut_traitement: Mapped[str] = mapped_column(String(30), nullable=False, default="nouveau")
    description_signalement: Mapped[Optional[str]] = mapped_column(Text)
    analyste: Mapped[Optional[str]] = mapped_column(String(100))
    source_interne: Mapped[str] = mapped_column(String(100), nullable=False, default="portail_web")
    nb_signalements: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())

    def __repr__(self) -> str:
        return f"<SignalementHistorique id={self.id}>"


# get_engine() et get_session() sont desormais fournis par database.connection
# et re-exportes ici pour la compatibilite avec les imports existants.
# Les deux fonctions referent au meme moteur configure depuis les variables PG_*.

__all__ = [
    "Base",
    "TypeArnaque",
    "Region",
    "Source",
    "Signalement",
    "SignalementSource",
    "SignalementHistorique",
    "get_engine",
    "get_session",
    "get_sqlalchemy_url",
]
