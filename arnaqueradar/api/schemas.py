"""
Schémas Pydantic pour l'API ArnaqueRadar.

Définit les modèles de validation et de sérialisation des données
échangées entre l'API et ses clients. Chaque schéma correspond à
un type de réponse ou de requête documenté dans l'interface OpenAPI.
"""

from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SignalementOut(BaseModel):
    """
    Schéma de sortie pour un signalement d'arnaque.

    Représente une entrée normalisée telle que retournée par l'API.
    Les champs correspondent aux colonnes de la table signalements.
    """

    id: int = Field(..., description="Identifiant unique du signalement.")
    url: str = Field(..., description="URL signalée comme frauduleuse.")
    type: str = Field(..., description="Type d'arnaque normalisé (phishing, sms_frauduleux, etc.).")
    region: Optional[str] = Field(None, description="Région française associée au signalement.")
    date_signalement: str = Field(..., description="Date du signalement au format YYYY-MM-DD.")
    source: str = Field(..., description="Code de la source de collecte (google_web_risk, hive_logs, etc.).")
    verified: bool = Field(False, description="Indique si le signalement a été vérifié.")
    titre: Optional[str] = Field(None, description="Titre ou description courte de l'arnaque.")

    model_config = ConfigDict(from_attributes=True)


class TypeStatOut(BaseModel):
    """
    Statistique par type d'arnaque.

    Paramètres :
        type (str) : code du type d'arnaque.
        count (int) : nombre de signalements pour ce type.
    """

    type: str = Field(..., description="Code du type d'arnaque.")
    count: int = Field(..., description="Nombre de signalements.")


class RegionStatOut(BaseModel):
    """
    Statistique par région.

    Paramètres :
        region (str) : nom de la région.
        count (int)  : nombre de signalements dans cette région.
    """

    region: str = Field(..., description="Nom de la région française.")
    count: int = Field(..., description="Nombre de signalements.")


class StatsOut(BaseModel):
    """
    Schéma de sortie pour les statistiques agrégées.

    Retourné par GET /stats, fournit un résumé global du volume de
    signalements ainsi que les distributions par type et par région.
    """

    total: int = Field(..., description="Nombre total de signalements en base.")
    par_type: list[TypeStatOut] = Field(..., description="Distribution des signalements par type d'arnaque.")
    par_region: list[RegionStatOut] = Field(..., description="Distribution des signalements par région.")


class TokenOut(BaseModel):
    """
    Schéma de sortie pour l'authentification JWT.

    Retourné par POST /token après une authentification réussie.
    Le champ access_token contient le JWT à utiliser dans les headers
    Authorization: Bearer <token>.
    """

    access_token: str = Field(..., description="Token JWT signé, valable 24 heures.")
    token_type: str = Field(default="bearer", description="Type de token (toujours 'bearer').")


class HealthOut(BaseModel):
    """
    Schéma de sortie pour l'endpoint de santé GET /health.

    Utilisé par les outils de monitoring (Prometheus, load balancer)
    pour vérifier que l'API est disponible.
    """

    status: str = Field(..., description="Statut de l'API ('ok' si opérationnelle).")
    version: str = Field(..., description="Version de l'API.")
