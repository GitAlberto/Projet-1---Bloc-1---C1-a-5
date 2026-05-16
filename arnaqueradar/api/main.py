"""
API REST ArnaqueRadar.

Cette API expose :
- les signalements consolides
- leurs evidences de corroboration multi-sources
- des statistiques enrichies pour le reporting
- le dernier rapport qualite produit par le pipeline
"""

from __future__ import annotations

import json
import logging
import sys
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bootstrap import load_project_env

load_project_env()

from api.auth import authenticate_user, create_token, verify_token
from api.schemas import (
    HealthOut,
    QualityStatsOut,
    RegionStatOut,
    SignalementEvidenceOut,
    SignalementOut,
    SimpleStatOut,
    StatsOut,
    TokenOut,
    TypeStatOut,
)
from pipeline.database.models import Region, Signalement, SignalementSource, Source, TypeArnaque, get_engine

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

API_VERSION = "1.1.0"
QUALITY_REPORT_PATH = PROJECT_ROOT / "data" / "quality_report.json"

VALID_TYPES = {
    "phishing",
    "malware_distribution",
    "sms_frauduleux",
    "violation_rgpd",
    "fraude_cpf",
    "arnaque_achat",
    "faux_support",
    "autre",
}

app = FastAPI(
    title="ArnaqueRadar API",
    description=(
        "API REST securisee exposant les signalements d'arnaques numeriques "
        "collectes, consolides et enrichis par le pipeline ArnaqueRadar."
    ),
    version=API_VERSION,
    contact={"name": "ArnaqueRadar", "email": "contact@arnaqueradar.fr"},
    license_info={"name": "MIT"},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Ajoute quelques headers de securite OWASP sur chaque reponse."""
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


def get_db_session() -> Session:
    """Fournit une session SQLAlchemy par requete."""
    engine = get_engine()
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()


def _to_float(value: Any) -> float | None:
    """Convertit proprement un score Decimal/float SQLAlchemy en float JSON."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _serialize_evidences(rows: list[dict[str, Any]]) -> list[SignalementEvidenceOut]:
    """Transforme des lignes SQL en objets Pydantic d'evidence."""
    evidences: list[SignalementEvidenceOut] = []
    for row in rows:
        evidences.append(
            SignalementEvidenceOut(
                source=row["source"],
                date_observation=str(row["date_observation"]),
                verified=bool(row["verified"]),
                titre=row["titre"],
                region_raw=row["region_raw"],
                canal=row["canal"],
                nature_technique=row["nature_technique"],
                score_confiance=_to_float(row["score_confiance"]),
                type_raw=row["type_raw"],
                source_category_raw=row["source_category_raw"],
                keywords_matched=row["keywords_matched"],
                classifier_version=row["classifier_version"],
                source_interne=row["source_interne"],
                nb_signalements=int(row["nb_signalements"] or 1),
            )
        )
    return evidences


def _load_evidences_by_signalement(
    db: Session,
    signalement_ids: list[int],
) -> dict[int, list[SignalementEvidenceOut]]:
    """Charge toutes les evidences associees a une liste de signalements."""
    if not signalement_ids:
        return {}

    evidence_rows = db.execute(
        select(
            SignalementSource.signalement_id,
            Source.code.label("source"),
            SignalementSource.date_observation,
            SignalementSource.verified,
            SignalementSource.titre,
            SignalementSource.region_raw,
            SignalementSource.canal,
            SignalementSource.nature_technique,
            SignalementSource.score_confiance,
            SignalementSource.type_raw,
            SignalementSource.source_category_raw,
            SignalementSource.keywords_matched,
            SignalementSource.classifier_version,
            SignalementSource.source_interne,
            SignalementSource.nb_signalements,
        )
        .join(Source, SignalementSource.source_id == Source.id)
        .where(SignalementSource.signalement_id.in_(signalement_ids))
        .order_by(SignalementSource.signalement_id.asc(), SignalementSource.date_observation.desc())
    ).mappings().all()

    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in evidence_rows:
        grouped[int(row["signalement_id"])].append(dict(row))

    return {
        signalement_id: _serialize_evidences(rows)
        for signalement_id, rows in grouped.items()
    }


def _build_signalement_out(row: dict[str, Any], evidences: list[SignalementEvidenceOut]) -> SignalementOut:
    """Assemble un objet de sortie consolide + liste des corroborations."""
    corroborating_sources = sorted({evidence.source for evidence in evidences})
    return SignalementOut(
        id=int(row["id"]),
        url=row["url"],
        type=row["type"],
        region=row["region"],
        date_signalement=str(row["date_signalement"]),
        source=row["source"],
        verified=bool(row["verified"]),
        titre=row["titre"],
        nb_signalements=int(row["nb_signalements"] or 1),
        canal=row["canal"],
        nature_technique=row["nature_technique"],
        score_confiance=_to_float(row["score_confiance"]),
        type_raw=row["type_raw"],
        source_category_raw=row["source_category_raw"],
        keywords_matched=row["keywords_matched"],
        classifier_version=row["classifier_version"],
        nb_sources=len(corroborating_sources),
        sources_corroborantes=corroborating_sources,
        evidences=evidences,
    )


@app.get("/health", response_model=HealthOut, tags=["Monitoring"], summary="Verifier la disponibilite de l'API")
def health_check() -> HealthOut:
    """Endpoint de sante simple, sans authentification."""
    return HealthOut(status="ok", version=API_VERSION)


@app.post("/token", response_model=TokenOut, tags=["Authentification"], summary="Obtenir un token JWT")
def login(form_data: Annotated[OAuth2PasswordRequestForm, Depends()]) -> TokenOut:
    """Authentifie l'utilisateur admin et renvoie un token Bearer."""
    if not authenticate_user(form_data.username, form_data.password):
        logger.warning("Echec d'authentification pour l'utilisateur '%s'.", form_data.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identifiants incorrects.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_token(data={"sub": form_data.username})
    logger.info("Token JWT emis pour '%s'.", form_data.username)
    return TokenOut(access_token=token, token_type="bearer")


@app.get(
    "/arnaques",
    response_model=list[SignalementOut],
    tags=["Signalements"],
    summary="Lister les signalements consolides avec filtres optionnels",
)
def get_arnaques(
    _: Annotated[dict, Depends(verify_token)],
    db: Annotated[Session, Depends(get_db_session)],
    type: Optional[str] = Query(None, description="Filtrer par type d'arnaque."),
    region: Optional[str] = Query(None, description="Filtrer par nom de region."),
    date_debut: Optional[str] = Query(None, description="Date de debut (YYYY-MM-DD)."),
    date_fin: Optional[str] = Query(None, description="Date de fin (YYYY-MM-DD)."),
    limit: int = Query(100, ge=1, le=1000, description="Nombre maximum de resultats."),
    offset: int = Query(0, ge=0, description="Decalage de pagination."),
) -> list[SignalementOut]:
    """Retourne les signalements consolides avec leurs enrichissements et evidences."""
    if type is not None and type not in VALID_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Type invalide. Valeurs acceptees : {sorted(VALID_TYPES)}",
        )

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
                Signalement.nb_signalements,
                Signalement.canal,
                Signalement.nature_technique,
                Signalement.score_confiance,
                Signalement.type_raw,
                Signalement.source_category_raw,
                Signalement.keywords_matched,
                Signalement.classifier_version,
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
        rows = [dict(row) for row in db.execute(query).mappings().all()]
        evidences_by_signalement = _load_evidences_by_signalement(db, [int(row["id"]) for row in rows])
        return [
            _build_signalement_out(row, evidences_by_signalement.get(int(row["id"]), []))
            for row in rows
        ]
    except Exception as exc:
        logger.error("GET /arnaques : erreur interne - %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur interne du serveur.",
        )


@app.get(
    "/arnaques/{signalement_id}",
    response_model=SignalementOut,
    tags=["Signalements"],
    summary="Obtenir le detail d'un signalement consolide",
)
def get_signalement_by_id(
    signalement_id: int,
    _: Annotated[dict, Depends(verify_token)],
    db: Annotated[Session, Depends(get_db_session)],
) -> SignalementOut:
    """Retourne un signalement consolide et toutes ses evidences."""
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
                Signalement.nb_signalements,
                Signalement.canal,
                Signalement.nature_technique,
                Signalement.score_confiance,
                Signalement.type_raw,
                Signalement.source_category_raw,
                Signalement.keywords_matched,
                Signalement.classifier_version,
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

        row_dict = dict(row)
        evidences_by_signalement = _load_evidences_by_signalement(db, [signalement_id])
        return _build_signalement_out(
            row_dict,
            evidences_by_signalement.get(signalement_id, []),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("GET /arnaques/%s : erreur interne - %s", signalement_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur interne du serveur.",
        )


@app.get(
    "/stats",
    response_model=StatsOut,
    tags=["Statistiques"],
    summary="Obtenir les statistiques consolidees et enrichies",
)
def get_stats(
    _: Annotated[dict, Depends(verify_token)],
    db: Annotated[Session, Depends(get_db_session)],
) -> StatsOut:
    """Retourne des statistiques utiles pour le reporting metier et technique."""
    try:
        total = int(db.execute(select(func.count(Signalement.id))).scalar() or 0)
        total_evidences = int(db.execute(select(func.count(SignalementSource.id))).scalar() or 0)

        type_rows = db.execute(
            select(TypeArnaque.code.label("type"), func.count(Signalement.id).label("count"))
            .join(Signalement, Signalement.type_id == TypeArnaque.id)
            .group_by(TypeArnaque.code)
            .order_by(func.count(Signalement.id).desc())
        ).all()

        region_rows = db.execute(
            select(
                func.coalesce(Region.nom, "inconnue").label("region"),
                func.count(Signalement.id).label("count"),
            )
            .select_from(Signalement)
            .outerjoin(Region, Signalement.region_id == Region.id)
            .group_by(func.coalesce(Region.nom, "inconnue"))
            .order_by(func.count(Signalement.id).desc())
        ).all()

        source_rows = db.execute(
            select(Source.code.label("label"), func.count(SignalementSource.id).label("count"))
            .join(SignalementSource, SignalementSource.source_id == Source.id)
            .group_by(Source.code)
            .order_by(func.count(SignalementSource.id).desc())
        ).all()

        canal_rows = db.execute(
            select(func.coalesce(Signalement.canal, "inconnu").label("label"), func.count(Signalement.id).label("count"))
            .group_by(func.coalesce(Signalement.canal, "inconnu"))
            .order_by(func.count(Signalement.id).desc())
        ).all()

        nature_rows = db.execute(
            select(
                func.coalesce(Signalement.nature_technique, "inconnu").label("label"),
                func.count(Signalement.id).label("count"),
            )
            .group_by(func.coalesce(Signalement.nature_technique, "inconnu"))
            .order_by(func.count(Signalement.id).desc())
        ).all()

        return StatsOut(
            total=total,
            total_evidences=total_evidences,
            par_type=[TypeStatOut(type=row.type, count=int(row.count)) for row in type_rows],
            par_region=[RegionStatOut(region=row.region, count=int(row.count)) for row in region_rows],
            par_source=[SimpleStatOut(label=row.label, count=int(row.count)) for row in source_rows],
            par_canal=[SimpleStatOut(label=row.label, count=int(row.count)) for row in canal_rows],
            par_nature=[SimpleStatOut(label=row.label, count=int(row.count)) for row in nature_rows],
        )
    except Exception as exc:
        logger.error("GET /stats : erreur interne - %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur interne du serveur.",
        )


@app.get(
    "/stats/qualite",
    response_model=QualityStatsOut,
    tags=["Statistiques"],
    summary="Obtenir le dernier rapport qualite du dataset",
)
def get_quality_stats(
    _: Annotated[dict, Depends(verify_token)],
) -> QualityStatsOut:
    """Expose le dernier rapport qualite genere par l'etape 4 du pipeline."""
    if not QUALITY_REPORT_PATH.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Aucun rapport qualite disponible. Executez d'abord pipeline/aggregate/4_controler_qualite.py.",
        )

    try:
        payload = json.loads(QUALITY_REPORT_PATH.read_text(encoding="utf-8"))
        return QualityStatsOut(**payload)
    except Exception as exc:
        logger.error("GET /stats/qualite : erreur interne - %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur interne du serveur.",
        )
