"""
API REST ArnaqueRadar — Point d'entrée principal FastAPI.

Expose les signalements d'arnaques numériques collectés via le pipeline.
Tous les endpoints (sauf /health et /token) requièrent une authentification
JWT Bearer. Les mesures de sécurité OWASP sont appliquées :
  - Validation stricte des paramètres d'entrée via Pydantic.
  - Messages d'erreur génériques (pas d'exposition de détails internes).
  - Headers de sécurité HTTP via middleware.
  - OAuth2 Bearer sur tous les endpoints protégés.

Démarrage : uvicorn api.main:app --reload --port 8000
Documentation : http://localhost:8000/docs
"""

import logging
import os
import sys
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from api.auth import authenticate_user, create_token, verify_token
from api.schemas import HealthOut, RegionStatOut, SignalementOut, StatsOut, TokenOut, TypeStatOut
from database.models import Region, Signalement, Source, TypeArnaque, get_engine

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

API_VERSION = "1.0.0"

app = FastAPI(
    title="ArnaqueRadar API",
    description=(
        "API REST sécurisée exposant les signalements d'arnaques numériques "
        "collectés et normalisés par le pipeline ArnaqueRadar. "
        "Authentification : OAuth2 Bearer JWT (POST /token)."
    ),
    version=API_VERSION,
    contact={
        "name": "ArnaqueRadar",
        "email": "contact@arnaqueradar.fr",
    },
    license_info={
        "name": "MIT",
    },
)

# -------------------------
# Middleware CORS
# -------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


# -------------------------
# Middleware : Headers de sécurité OWASP
# -------------------------
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """
    Ajoute les headers de sécurité HTTP recommandés par OWASP sur chaque réponse.

    Headers appliqués :
        X-Content-Type-Options : empêche le MIME sniffing.
        X-Frame-Options        : protège contre le clickjacking.
        X-XSS-Protection       : active le filtre XSS des navigateurs.
        Referrer-Policy        : limite les informations de référent.
    """
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


# -------------------------
# Dépendance : session SQLAlchemy
# -------------------------
def get_db_session() -> Session:
    """
    Dépendance FastAPI fournissant une session SQLAlchemy par requête.

    Retourne :
        Session : session active fermée après chaque requête.
    """
    engine = get_engine()
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()


VALID_TYPES = {
    "phishing", "sms_frauduleux", "violation_rgpd",
    "fraude_cpf", "arnaque_achat", "faux_support", "autre",
}


# ============================================================
# Endpoint : GET /health — Santé de l'API (sans authentification)
# ============================================================
@app.get(
    "/health",
    response_model=HealthOut,
    tags=["Monitoring"],
    summary="Vérification de la disponibilité de l'API",
)
def health_check() -> HealthOut:
    """
    Retourne le statut de l'API sans authentification.

    Utilisé par les outils de monitoring (load balancer, Prometheus)
    pour vérifier que le service est opérationnel.

    Retourne :
        HealthOut : statut 'ok' et version de l'API.
    """
    return HealthOut(status="ok", version=API_VERSION)


# ============================================================
# Endpoint : POST /token — Authentification OAuth2
# ============================================================
@app.post(
    "/token",
    response_model=TokenOut,
    tags=["Authentification"],
    summary="Obtenir un token JWT",
)
def login(form_data: Annotated[OAuth2PasswordRequestForm, Depends()]) -> TokenOut:
    """
    Authentifie l'utilisateur et retourne un token JWT valable 24 heures.

    Paramètres (form-data) :
        username (str) : identifiant utilisateur.
        password (str) : mot de passe.

    Retourne :
        TokenOut : token JWT Bearer à utiliser sur les endpoints protégés.

    Lève :
        HTTPException 401 : si les identifiants sont incorrects.
    """
    if not authenticate_user(form_data.username, form_data.password):
        logger.warning("Échec d'authentification pour l'utilisateur '%s'.", form_data.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identifiants incorrects.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_token(data={"sub": form_data.username})
    logger.info("Token JWT émis pour '%s'.", form_data.username)
    return TokenOut(access_token=token, token_type="bearer")


# ============================================================
# Endpoint : GET /arnaques — Liste avec filtres
# ============================================================
@app.get(
    "/arnaques",
    response_model=list[SignalementOut],
    tags=["Signalements"],
    summary="Lister les signalements d'arnaques avec filtres optionnels",
)
def get_arnaques(
    _: Annotated[dict, Depends(verify_token)],
    db: Annotated[Session, Depends(get_db_session)],
    type: Optional[str] = Query(None, description="Filtrer par type d'arnaque."),
    region: Optional[str] = Query(None, description="Filtrer par nom de région."),
    date_debut: Optional[str] = Query(None, description="Date de début (YYYY-MM-DD)."),
    date_fin: Optional[str] = Query(None, description="Date de fin (YYYY-MM-DD)."),
    limit: int = Query(100, ge=1, le=1000, description="Nombre maximum de résultats."),
    offset: int = Query(0, ge=0, description="Décalage pour la pagination."),
) -> list[SignalementOut]:
    """
    Retourne la liste des signalements avec filtres optionnels.

    Validation OWASP : le paramètre type est validé contre un ensemble
    de valeurs autorisées pour prévenir toute injection.

    Paramètres :
        type (str)       : filtre sur le type d'arnaque (valeurs du vocabulaire contrôlé).
        region (str)     : filtre partiel sur le nom de région.
        date_debut (str) : borne inférieure de date (incluse).
        date_fin (str)   : borne supérieure de date (incluse).
        limit (int)      : pagination — nombre de résultats max (1–1000).
        offset (int)     : pagination — décalage.

    Retourne :
        list[SignalementOut] : liste des signalements correspondant aux filtres.
    """
    # Validation stricte du paramètre type (sécurité OWASP)
    if type is not None and type not in VALID_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Type invalide. Valeurs acceptées : {sorted(VALID_TYPES)}",
        )

    # Validation des dates
    date_debut_parsed: Optional[date] = None
    date_fin_parsed: Optional[date] = None
    try:
        if date_debut:
            date_debut_parsed = date.fromisoformat(date_debut)
        if date_fin:
            date_fin_parsed = date.fromisoformat(date_fin)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Format de date invalide. Utilisez YYYY-MM-DD.",
        )

    try:
        query = (
            select(
                Signalement.id,
                Signalement.url,
                TypeArnaque.code.label("type"),
                Region.nom.label("region"),
                Signalement.date_signalement,
                Source.code.label("source"),
                Signalement.verified,
                Signalement.titre,
            )
            .join(TypeArnaque, Signalement.type_id == TypeArnaque.id)
            .outerjoin(Region, Signalement.region_id == Region.id)
            .join(Source, Signalement.source_id == Source.id)
        )

        if type:
            query = query.where(TypeArnaque.code == type)
        if region:
            query = query.where(Region.nom.ilike(f"%{region}%"))
        if date_debut_parsed:
            query = query.where(Signalement.date_signalement >= date_debut_parsed)
        if date_fin_parsed:
            query = query.where(Signalement.date_signalement <= date_fin_parsed)

        query = query.order_by(Signalement.date_signalement.desc()).limit(limit).offset(offset)
        rows = db.execute(query).mappings().all()

        return [
            SignalementOut(
                id=row["id"],
                url=row["url"],
                type=row["type"],
                region=row["region"],
                date_signalement=str(row["date_signalement"]),
                source=row["source"],
                verified=bool(row["verified"]),
                titre=row["titre"],
            )
            for row in rows
        ]
    except Exception as exc:
        logger.error("GET /arnaques : erreur interne — %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur interne du serveur.",
        )


# ============================================================
# Endpoint : GET /stats — Statistiques agrégées
# ============================================================
@app.get(
    "/stats",
    response_model=StatsOut,
    tags=["Statistiques"],
    summary="Obtenir les statistiques agrégées des signalements",
)
def get_stats(
    _: Annotated[dict, Depends(verify_token)],
    db: Annotated[Session, Depends(get_db_session)],
) -> StatsOut:
    """
    Retourne les statistiques globales : total, distribution par type et par région.

    Retourne :
        StatsOut : total des signalements, répartition par type, répartition par région.
    """
    try:
        total = db.execute(select(func.count(Signalement.id))).scalar() or 0

        type_rows = db.execute(
            select(TypeArnaque.code.label("type"), func.count(Signalement.id).label("count"))
            .join(Signalement, Signalement.type_id == TypeArnaque.id)
            .group_by(TypeArnaque.code)
            .order_by(func.count(Signalement.id).desc())
        ).all()

        region_rows = db.execute(
            select(Region.nom.label("region"), func.count(Signalement.id).label("count"))
            .join(Signalement, Signalement.region_id == Region.id)
            .group_by(Region.nom)
            .order_by(func.count(Signalement.id).desc())
        ).all()

        return StatsOut(
            total=total,
            par_type=[TypeStatOut(type=r.type, count=r.count) for r in type_rows],
            par_region=[RegionStatOut(region=r.region, count=r.count) for r in region_rows],
        )
    except Exception as exc:
        logger.error("GET /stats : erreur interne — %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur interne du serveur.",
        )


# ============================================================
# Endpoint : GET /arnaques/{id} — Détail d'un signalement
# ============================================================
@app.get(
    "/arnaques/{signalement_id}",
    response_model=SignalementOut,
    tags=["Signalements"],
    summary="Obtenir le détail d'un signalement par son ID",
)
def get_signalement_by_id(
    signalement_id: int,
    _: Annotated[dict, Depends(verify_token)],
    db: Annotated[Session, Depends(get_db_session)],
) -> SignalementOut:
    """
    Retourne le détail complet d'un signalement identifié par son ID.

    Paramètres :
        signalement_id (int) : identifiant unique du signalement.

    Retourne :
        SignalementOut : données complètes du signalement.

    Lève :
        HTTPException 404 : si l'ID n'existe pas en base.
    """
    try:
        row = db.execute(
            select(
                Signalement.id,
                Signalement.url,
                TypeArnaque.code.label("type"),
                Region.nom.label("region"),
                Signalement.date_signalement,
                Source.code.label("source"),
                Signalement.verified,
                Signalement.titre,
            )
            .join(TypeArnaque, Signalement.type_id == TypeArnaque.id)
            .outerjoin(Region, Signalement.region_id == Region.id)
            .join(Source, Signalement.source_id == Source.id)
            .where(Signalement.id == signalement_id)
        ).mappings().first()

        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Signalement introuvable.",
            )

        return SignalementOut(
            id=row["id"],
            url=row["url"],
            type=row["type"],
            region=row["region"],
            date_signalement=str(row["date_signalement"]),
            source=row["source"],
            verified=bool(row["verified"]),
            titre=row["titre"],
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("GET /arnaques/%s : erreur interne — %s", signalement_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur interne du serveur.",
        )
