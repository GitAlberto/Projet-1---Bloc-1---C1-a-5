"""
Tests d'intégration pour l'API ArnaqueRadar.

Suite de tests pytest utilisant fastapi.testclient.TestClient pour valider
l'ensemble des endpoints de l'API sans dépendance à une base de données
réelle. Les tests couvrent l'authentification, les accès autorisés et refusés,
les filtres et les cas limites (ressource introuvable).

Exécution : pytest tests/ -v
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Ajout de la racine du projet au path pour les imports
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


# -------------------------
# Mocks de la base de données
# -------------------------

def _make_fake_signalement(
    sid: int = 1,
    url: str = "https://fake-phishing.fr/login",
    type_code: str = "phishing",
    region_nom: str = "Île-de-France",
    date_sig: str = "2024-11-15",
    source_code: str = "urlhaus",
    verified: bool = True,
    titre: str = "Faux site bancaire",
) -> dict:
    """
    Construit un mapping simulant une ligne retournée par SQLAlchemy.

    Paramètres :
        sid (int)        : identifiant unique.
        url (str)        : URL signalée.
        type_code (str)  : code du type d'arnaque.
        region_nom (str) : nom de la région.
        date_sig (str)   : date au format YYYY-MM-DD.
        source_code (str): code de la source.
        verified (bool)  : statut de vérification.
        titre (str)      : titre de l'arnaque.

    Retourne :
        dict : mapping compatible avec le schéma SignalementOut.
    """
    return {
        "id": sid,
        "url": url,
        "type": type_code,
        "region": region_nom,
        "date_signalement": date_sig,
        "source": source_code,
        "verified": verified,
        "titre": titre,
    }


FAKE_SIGNALEMENTS = [
    _make_fake_signalement(1, "https://fake-phishing.fr/login", "phishing"),
    _make_fake_signalement(2, "https://fake-sms-livraison.fr", "sms_frauduleux",
                           region_nom="Bretagne", source_code="hive_logs"),
]


def _mock_db_session():
    """
    Retourne un mock de session SQLAlchemy simulant les réponses de la base.

    Retourne :
        MagicMock : session factice avec les méthodes execute et close.
    """
    session = MagicMock()

    def fake_execute(query, *args, **kwargs):
        result = MagicMock()
        query_str = str(query)

        # Simulation COUNT pour /stats
        if "count" in query_str.lower():
            scalar_result = MagicMock()
            scalar_result.scalar.return_value = len(FAKE_SIGNALEMENTS)
            result.scalar.return_value = len(FAKE_SIGNALEMENTS)
            result.mappings.return_value.all.return_value = []
            result.all.return_value = []
            return result

        # Simulation des résultats pour /arnaques et /arnaques/{id}
        mappings_mock = MagicMock()
        mappings_mock.all.return_value = [MagicMock(**s, **{"__getitem__": lambda self, k: s[k]})
                                           for s in FAKE_SIGNALEMENTS]
        mappings_mock.first.return_value = MagicMock(
            **FAKE_SIGNALEMENTS[0],
            **{"__getitem__": lambda self, k: FAKE_SIGNALEMENTS[0][k]}
        )
        result.mappings.return_value = mappings_mock
        result.all.return_value = []
        return result

    session.execute.side_effect = fake_execute
    return session


# -------------------------
# Fixture client
# -------------------------

@pytest.fixture(scope="module")
def client():
    """
    Fixture module-scoped : crée un TestClient FastAPI avec injection de dépendances mockées.

    Retourne :
        TestClient : client HTTP de test prêt à l'emploi.
    """
    from api.main import app, get_db_session

    app.dependency_overrides[get_db_session] = _mock_db_session
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="module")
def auth_token(client):
    """
    Fixture module-scoped : obtient un token JWT valide via POST /token.

    Paramètres :
        client : fixture TestClient.

    Retourne :
        str : valeur du token JWT (sans le préfixe 'Bearer').
    """
    response = client.post(
        "/token",
        data={"username": "admin", "password": "arnaqueradar2024"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


# ============================================================
# Tests
# ============================================================

def test_health(client):
    """GET /health doit retourner 200 sans authentification."""
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_login_success(client):
    """POST /token avec les bons identifiants doit retourner 200 et un access_token."""
    response = client.post(
        "/token",
        data={"username": "admin", "password": "arnaqueradar2024"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


def test_login_failure(client):
    """POST /token avec un mauvais mot de passe doit retourner 401."""
    response = client.post(
        "/token",
        data={"username": "admin", "password": "mauvais_mot_de_passe"},
    )
    assert response.status_code == 401


def test_get_arnaques_authenticated(client, auth_token):
    """GET /arnaques avec un token valide doit retourner 200 et une liste."""
    response = client.get(
        "/arnaques",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)


def test_get_arnaques_unauthenticated(client):
    """GET /arnaques sans token doit retourner 401."""
    response = client.get("/arnaques")
    assert response.status_code == 401


def test_get_arnaques_filter_type(client, auth_token):
    """GET /arnaques?type=phishing avec token valide doit retourner 200."""
    response = client.get(
        "/arnaques?type=phishing",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)


def test_get_arnaques_invalid_type(client, auth_token):
    """GET /arnaques?type=invalide doit retourner 422 (validation OWASP)."""
    response = client.get(
        "/arnaques?type=INJECTION_SQL_ICI",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 422


def test_get_stats_authenticated(client, auth_token):
    """GET /stats avec token valide doit retourner 200 et le champ 'total'."""
    response = client.get(
        "/stats",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "total" in body
    assert "par_type" in body
    assert "par_region" in body


def test_get_arnaque_not_found(client, auth_token):
    """GET /arnaques/99999 doit retourner 404 si l'ID n'existe pas."""
    # On override pour simuler un résultat vide
    from api.main import app, get_db_session

    def mock_empty_session():
        session = MagicMock()
        result = MagicMock()
        result.mappings.return_value.first.return_value = None
        session.execute.return_value = result
        return session

    app.dependency_overrides[get_db_session] = mock_empty_session
    response = client.get(
        "/arnaques/99999",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    app.dependency_overrides[get_db_session] = _mock_db_session
    assert response.status_code == 404


def test_security_headers_present(client):
    """GET /health doit inclure les headers de sécurité OWASP."""
    response = client.get("/health")
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"
