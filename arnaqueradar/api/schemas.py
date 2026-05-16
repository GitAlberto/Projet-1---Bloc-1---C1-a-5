"""
Schemas Pydantic pour l'API ArnaqueRadar.

L'API expose maintenant :
- le signalement consolide
- les metadonnees enrichies utiles au reporting
- la liste des evidences / corroborations par source
- un resume des indicateurs qualite du dataset
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class SignalementEvidenceOut(BaseModel):
    """Representation d'une evidence source par source pour un signalement."""

    source: str = Field(..., description="Code de la source ayant observe le signalement.")
    date_observation: str = Field(..., description="Date d'observation de l'evidence au format YYYY-MM-DD.")
    verified: bool = Field(False, description="Indique si cette evidence est marquee comme verifiee.")
    titre: Optional[str] = Field(None, description="Titre, description courte ou libelle observe sur la source.")
    region_raw: Optional[str] = Field(None, description="Region brute telle que remontee par la source.")
    canal: Optional[str] = Field(None, description="Canal estime pour cette evidence (web, sms, email, tel, fuite_donnees).")
    nature_technique: Optional[str] = Field(None, description="Nature technique de l'evidence (phishing, malware, data_breach, etc.).")
    score_confiance: Optional[float] = Field(None, description="Score de confiance associe a cette evidence.")
    type_raw: Optional[str] = Field(None, description="Type ou libelle brut fourni par la source.")
    source_category_raw: Optional[str] = Field(None, description="Categorie brute ou tag source conserve pour audit.")
    keywords_matched: Optional[str] = Field(None, description="Mots-cles ou signaux ayant contribue au classement.")
    classifier_version: Optional[str] = Field(None, description="Version du classifieur utilise pour enrichir la ligne.")
    source_interne: Optional[str] = Field(None, description="Origine interne detaillee pour les sources SQL / historiques.")
    nb_signalements: int = Field(1, description="Intensite remontee pour cette evidence.")


class SignalementOut(BaseModel):
    """Schema de sortie principal d'un signalement consolide."""

    id: int = Field(..., description="Identifiant unique du signalement consolide.")
    url: str = Field(..., description="URL signalee comme frauduleuse ou malveillante.")
    type: str = Field(..., description="Type d'arnaque consolide et normalise.")
    region: Optional[str] = Field(None, description="Region consolidee associee au signalement.")
    date_signalement: str = Field(..., description="Date du signalement au format YYYY-MM-DD.")
    source: str = Field(..., description="Source primaire retenue pour representer le signalement consolide.")
    verified: bool = Field(False, description="Indique si au moins une evidence est marquee comme verifiee.")
    titre: Optional[str] = Field(None, description="Titre ou description courte retenue pour la ligne consolidee.")
    nb_signalements: int = Field(1, description="Volume consolide de signalements observes pour ce couple URL / date.")
    canal: Optional[str] = Field(None, description="Canal consolide associe au signalement.")
    nature_technique: Optional[str] = Field(None, description="Nature technique consolidee.")
    score_confiance: Optional[float] = Field(None, description="Score de confiance consolide.")
    type_raw: Optional[str] = Field(None, description="Type brut conserve pour audit.")
    source_category_raw: Optional[str] = Field(None, description="Categorie brute conservee pour audit.")
    keywords_matched: Optional[str] = Field(None, description="Signaux textuels ayant motive la classification.")
    classifier_version: Optional[str] = Field(None, description="Version du classifieur ayant produit les enrichissements.")
    nb_sources: int = Field(0, description="Nombre de sources distinctes corroborant le signalement.")
    sources_corroborantes: list[str] = Field(
        default_factory=list,
        description="Liste des sources distinctes ayant corrobore le signalement.",
    )
    evidences: list[SignalementEvidenceOut] = Field(
        default_factory=list,
        description="Liste detaillee des evidences source par source associees a ce signalement.",
    )

    model_config = ConfigDict(from_attributes=True)


class TypeStatOut(BaseModel):
    """Statistique agregee par type d'arnaque."""

    type: str = Field(..., description="Code du type d'arnaque.")
    count: int = Field(..., description="Nombre de signalements.")


class RegionStatOut(BaseModel):
    """Statistique agregee par region."""

    region: str = Field(..., description="Nom de la region.")
    count: int = Field(..., description="Nombre de signalements.")


class SimpleStatOut(BaseModel):
    """Statistique simple label -> count pour les dimensions enrichies."""

    label: str = Field(..., description="Valeur de la dimension analysee.")
    count: int = Field(..., description="Nombre d'occurrences.")


class StatsOut(BaseModel):
    """Schema des statistiques globales exposees par l'API."""

    total: int = Field(..., description="Nombre total de signalements consolides.")
    total_evidences: int = Field(..., description="Nombre total d'evidences source par source.")
    par_type: list[TypeStatOut] = Field(..., description="Distribution des signalements par type d'arnaque.")
    par_region: list[RegionStatOut] = Field(..., description="Distribution des signalements par region.")
    par_source: list[SimpleStatOut] = Field(..., description="Distribution des evidences par source.")
    par_canal: list[SimpleStatOut] = Field(..., description="Distribution des signalements par canal.")
    par_nature: list[SimpleStatOut] = Field(..., description="Distribution des signalements par nature technique.")


class QualityStatsOut(BaseModel):
    """Schema de synthese pour le rapport qualite du dernier dataset."""

    generated_at: str = Field(..., description="Horodatage de generation du rapport.")
    total_rows: int = Field(..., description="Nombre total de lignes dans le dataset enrichi.")
    autre_global_pct: Optional[float] = Field(None, description="Pourcentage global de lignes encore classees en 'autre'.")
    region_vide_global_pct: Optional[float] = Field(None, description="Pourcentage global de lignes sans region exploitable.")
    sans_signal_exploitable_global_pct: Optional[float] = Field(
        None,
        description="Pourcentage global de lignes sans signal metier exploitable.",
    )
    score_confiance_moyen_global: Optional[float] = Field(None, description="Score de confiance moyen global.")
    alerts: list[str] = Field(default_factory=list, description="Liste des alertes qualite emises.")
    targets: dict[str, Any] = Field(default_factory=dict, description="Objectifs qualite vises par le pipeline.")
    type_distribution: dict[str, int] = Field(default_factory=dict, description="Distribution des lignes par type.")
    nature_distribution: dict[str, int] = Field(default_factory=dict, description="Distribution des lignes par nature technique.")
    autre_by_source: dict[str, Any] = Field(default_factory=dict, description="Detail du taux de 'autre' par source.")
    region_vide_by_source: dict[str, Any] = Field(default_factory=dict, description="Detail du taux de region vide par source.")
    sans_signal_exploitable_by_source: dict[str, Any] = Field(
        default_factory=dict,
        description="Detail du taux de lignes peu exploitables par source.",
    )
    score_confiance_moyen_par_type: dict[str, float] = Field(
        default_factory=dict,
        description="Score moyen par type consolide.",
    )
    score_confiance_moyen_par_source: dict[str, float] = Field(
        default_factory=dict,
        description="Score moyen par source.",
    )


class TokenOut(BaseModel):
    """Schema de sortie pour l'authentification JWT."""

    access_token: str = Field(..., description="Token JWT signe, valable 24 heures.")
    token_type: str = Field(default="bearer", description="Type de token.")


class HealthOut(BaseModel):
    """Schema de sortie pour l'endpoint /health."""

    status: str = Field(..., description="Statut de l'API.")
    version: str = Field(..., description="Version de l'API.")
