"""
Module d'authentification JWT pour l'API ArnaqueRadar.

Implémente la génération et la vérification de tokens JWT (JSON Web Tokens)
à l'aide de python-jose. La validation des identifiants est statique
(utilisateur admin défini via variables d'environnement) afin de simplifier
l'architecture du projet sans base d'utilisateurs.

Endpoints associés : POST /token
Dépendance FastAPI : verify_token (OAuth2 Bearer)
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

load_dotenv()

logger = logging.getLogger(__name__)

SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production-use-openssl-rand-hex-32")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "arnaqueradar2024")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")


def verify_password(plain_password: str, stored_password: str) -> bool:
    """
    Vérifie un mot de passe en clair contre le mot de passe stocké.

    Pour ce projet, le mot de passe est stocké en clair dans .env.
    En production, il devrait être haché avec bcrypt.

    Paramètres :
        plain_password (str)  : mot de passe soumis par l'utilisateur.
        stored_password (str) : mot de passe de référence depuis .env.

    Retourne :
        bool : True si les mots de passe correspondent, False sinon.
    """
    return plain_password == stored_password


def authenticate_user(username: str, password: str) -> bool:
    """
    Valide les identifiants de l'utilisateur admin.

    La validation est statique sur les variables d'environnement
    ADMIN_USERNAME et ADMIN_PASSWORD pour ce projet.

    Paramètres :
        username (str) : nom d'utilisateur soumis.
        password (str) : mot de passe soumis.

    Retourne :
        bool : True si les identifiants sont corrects, False sinon.
    """
    return username == ADMIN_USERNAME and verify_password(password, ADMIN_PASSWORD)


def create_token(data: dict[str, Any]) -> str:
    """
    Génère un token JWT signé avec une expiration de 24 heures.

    Paramètres :
        data (dict) : payload à encoder dans le token (ex: {"sub": "admin"}).

    Retourne :
        str : token JWT signé sous forme de chaîne de caractères.
    """
    payload = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload.update({"exp": expire})
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    logger.info("auth : token JWT créé pour le sujet '%s'.", data.get("sub", "inconnu"))
    return token


def verify_token(token: Annotated[str, Depends(oauth2_scheme)]) -> dict[str, Any]:
    """
    Dépendance FastAPI : vérifie et décode le token JWT Bearer.

    Utilisée comme dépendance sur les endpoints protégés via
    Depends(verify_token). Lève une exception HTTP 401 si le token
    est absent, invalide ou expiré.

    Paramètres :
        token (str) : token JWT extrait de l'en-tête Authorization: Bearer.

    Retourne :
        dict : payload décodé du token (claims JWT).

    Lève :
        HTTPException 401 : si le token est invalide ou expiré.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token invalide ou expiré.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        subject: str = payload.get("sub", "")
        if not subject:
            raise credentials_exception
        return payload
    except JWTError as exc:
        logger.warning("auth : token JWT rejeté — %s", exc)
        raise credentials_exception
