"""
Tests d'integration de l'API ArnaqueRadar.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


FAKE_SIGNAL_ROWS = [
    {
        "id": 1,
        "url": "https://fake-phishing.fr/login",
        "type": "phishing",
        "region": "Ile-de-France",
        "date_signalement": "2026-05-14",
        "source": "urlhaus",
        "verified": True,
        "titre": "Faux portail bancaire",
        "nb_signalements": 4,
        "canal": "web",
        "nature_technique": "phishing",
        "score_confiance": 0.92,
        "type_raw": "phish",
        "source_category_raw": "bank|login",
        "keywords_matched": "login|bank",
        "classifier_version": "urlhaus_rules_v2",
    },
    {
        "id": 2,
        "url": "https://fake-sms-livraison.fr",
        "type": "sms_frauduleux",
        "region": "Bretagne",
        "date_signalement": "2026-05-13",
        "source": "hive_logs",
        "verified": False,
        "titre": "Faux suivi colis",
        "nb_signalements": 2,
        "canal": "sms",
        "nature_technique": "phishing",
        "score_confiance": 0.81,
        "type_raw": "smishing",
        "source_category_raw": "parcel|sms",
        "keywords_matched": "colis|sms",
        "classifier_version": "hive_logs_rules_v2",
    },
]

FAKE_EVIDENCES = {
    1: [
        {
            "source": "urlhaus",
            "date_observation": "2026-05-14",
            "verified": True,
            "titre": "Faux portail bancaire",
            "region_raw": "Ile-de-France",
            "canal": "web",
            "nature_technique": "phishing",
            "score_confiance": 0.92,
            "type_raw": "phish",
            "source_category_raw": "bank|login",
            "keywords_matched": "login|bank",
            "classifier_version": "urlhaus_rules_v2",
            "source_interne": "",
            "nb_signalements": 4,
        },
        {
            "source": "malwaretips",
            "date_observation": "2026-05-14",
            "verified": True,
            "titre": "Scam report",
            "region_raw": "",
            "canal": "web",
            "nature_technique": "phishing",
            "score_confiance": 0.75,
            "type_raw": "bank_scam",
            "source_category_raw": "scam-report",
            "keywords_matched": "bank|scam",
            "classifier_version": "malwaretips_rules_v2",
            "source_interne": "",
            "nb_signalements": 1,
        },
    ],
    2: [
        {
            "source": "hive_logs",
            "date_observation": "2026-05-13",
            "verified": False,
            "titre": "Faux suivi colis",
            "region_raw": "Bretagne",
            "canal": "sms",
            "nature_technique": "phishing",
            "score_confiance": 0.81,
            "type_raw": "smishing",
            "source_category_raw": "parcel|sms",
            "keywords_matched": "colis|sms",
            "classifier_version": "hive_logs_rules_v2",
            "source_interne": "",
            "nb_signalements": 2,
        }
    ],
}


class _FakeMappingsResult:
    """Double minimal pour `.mappings().all()` et `.mappings().first()`."""

    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeResult:
    """Double minimal du resultat SQLAlchemy."""

    def __init__(self, *, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def mappings(self):
        return _FakeMappingsResult(self._rows)

    def all(self):
        return self._rows

    def scalar(self):
        return self._scalar


class _FakeSession:
    """Session factice suffisante pour les endpoints testes."""

    def execute(self, query, *args, **kwargs):
        query_str = str(query)
        lower_query = query_str.lower()

        if "where signalements.id =" in lower_query:
            return _FakeResult(rows=[FAKE_SIGNAL_ROWS[0]])

        if "count(signalement_sources.id)" in lower_query:
            return _FakeResult(scalar=3)

        if "count(signalements.id)" in lower_query and "group by" not in lower_query:
            return _FakeResult(scalar=len(FAKE_SIGNAL_ROWS))

        if "group by types_arnaque.code" in lower_query:
            return _FakeResult(
                rows=[
                    SimpleNamespace(type="phishing", count=1),
                    SimpleNamespace(type="sms_frauduleux", count=1),
                ]
            )

        if "coalesce(regions.nom" in lower_query:
            return _FakeResult(
                rows=[
                    SimpleNamespace(region="Ile-de-France", count=1),
                    SimpleNamespace(region="Bretagne", count=1),
                ]
            )

        if "group by sources.code" in lower_query:
            return _FakeResult(
                rows=[
                    SimpleNamespace(label="urlhaus", count=1),
                    SimpleNamespace(label="malwaretips", count=1),
                    SimpleNamespace(label="hive_logs", count=1),
                ]
            )

        if "coalesce(signalements.canal" in lower_query:
            return _FakeResult(
                rows=[
                    SimpleNamespace(label="web", count=1),
                    SimpleNamespace(label="sms", count=1),
                ]
            )

        if "coalesce(signalements.nature_technique" in lower_query:
            return _FakeResult(rows=[SimpleNamespace(label="phishing", count=2)])

        return _FakeResult(rows=FAKE_SIGNAL_ROWS)

    def close(self):
        return None


def _fake_db_session():
    """Fabrique une session factice pour l'API."""
    return _FakeSession()


@pytest.fixture(scope="module")
def client():
    """Client HTTP de test avec base et evidences mockees."""
    from api.main import QUALITY_REPORT_PATH, _load_evidences_by_signalement, app, get_db_session

    quality_path = PROJECT_ROOT / "data" / "_test_quality_report.json"
    quality_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-14T12:00:00Z",
                "total_rows": 123,
                "autre_global_pct": 0.5,
                "region_vide_global_pct": 10.0,
                "sans_signal_exploitable_global_pct": 2.0,
                "score_confiance_moyen_global": 0.82,
                "alerts": [],
                "targets": {"autre_global_max_pct": 15.0},
                "type_distribution": {"phishing": 80, "sms_frauduleux": 43},
                "nature_distribution": {"phishing": 100, "data_breach": 23},
                "autre_by_source": {},
                "region_vide_by_source": {},
                "sans_signal_exploitable_by_source": {},
                "score_confiance_moyen_par_type": {"phishing": 0.8},
                "score_confiance_moyen_par_source": {"urlhaus": 0.9},
            }
        ),
        encoding="utf-8",
    )

    app.dependency_overrides[get_db_session] = _fake_db_session

    import api.main as api_main_module

    old_loader = api_main_module._load_evidences_by_signalement
    old_quality_path = api_main_module.QUALITY_REPORT_PATH
    from api.schemas import SignalementEvidenceOut

    api_main_module._load_evidences_by_signalement = lambda _db, ids: {
        sid: [SignalementEvidenceOut(**payload) for payload in FAKE_EVIDENCES.get(sid, [])]
        for sid in ids
    }
    api_main_module.QUALITY_REPORT_PATH = quality_path

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client

    api_main_module._load_evidences_by_signalement = old_loader
    api_main_module.QUALITY_REPORT_PATH = old_quality_path
    app.dependency_overrides.clear()
    quality_path.unlink(missing_ok=True)


@pytest.fixture(scope="module")
def auth_token(client):
    """Obtient un token JWT valide via POST /token."""
    response = client.post(
        "/token",
        data={"username": "admin", "password": "arnaqueradar2024"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_health(client):
    """GET /health doit retourner 200 sans authentification."""
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_login_success(client):
    """POST /token avec les bons identifiants doit retourner un access_token."""
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
        data={"username": "admin", "password": "mauvais"},
    )
    assert response.status_code == 401


def test_get_arnaques_authenticated(client, auth_token):
    """GET /arnaques doit maintenant exposer enrichissement + corroborations."""
    response = client.get("/arnaques", headers={"Authorization": f"Bearer {auth_token}"})
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert body[0]["type"] == "phishing"
    assert body[0]["nb_sources"] == 2
    assert body[0]["sources_corroborantes"] == ["malwaretips", "urlhaus"]
    assert len(body[0]["evidences"]) == 2
    assert body[0]["canal"] == "web"


def test_get_arnaques_unauthenticated(client):
    """GET /arnaques sans token doit retourner 401."""
    response = client.get("/arnaques")
    assert response.status_code == 401


def test_get_arnaques_invalid_type(client, auth_token):
    """Le filtre type doit rester strictement valide."""
    response = client.get(
        "/arnaques?type=INJECTION_SQL_ICI",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 422


def test_get_stats_authenticated(client, auth_token):
    """GET /stats doit retourner les stats consolidees et enrichies."""
    response = client.get("/stats", headers={"Authorization": f"Bearer {auth_token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["total_evidences"] == 3
    assert "par_type" in body
    assert "par_region" in body
    assert "par_source" in body
    assert "par_canal" in body
    assert "par_nature" in body


def test_get_quality_stats(client, auth_token):
    """GET /stats/qualite doit exposer le dernier rapport qualite."""
    response = client.get("/stats/qualite", headers={"Authorization": f"Bearer {auth_token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["total_rows"] == 123
    assert body["autre_global_pct"] == 0.5


def test_get_arnaque_not_found(client, auth_token):
    """GET /arnaques/{id} doit retourner 404 si l'ID n'existe pas."""
    from api.main import app, get_db_session

    class _EmptySession(_FakeSession):
        def execute(self, query, *args, **kwargs):
            query_str = str(query).lower()
            if "where signalements.id =" in query_str:
                return _FakeResult(rows=[])
            return super().execute(query, *args, **kwargs)

    app.dependency_overrides[get_db_session] = lambda: _EmptySession()
    response = client.get("/arnaques/99999", headers={"Authorization": f"Bearer {auth_token}"})
    app.dependency_overrides[get_db_session] = _fake_db_session
    assert response.status_code == 404


def test_security_headers_present(client):
    """GET /health doit inclure les headers de securite OWASP."""
    response = client.get("/health")
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"
