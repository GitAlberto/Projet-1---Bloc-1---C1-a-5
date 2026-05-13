"""
Tests unitaires du connecteur Google Web Risk.

Valide le chargement des candidats, le parsing de la reponse Lookup API
et le filtrage exclusif sur SOCIAL_ENGINEERING.
"""

import sys
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from collect.sources import google_web_risk


class _FakeResponse:
    """Double minimal de requests.Response pour les tests du connecteur."""

    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error", response=self)

    def json(self):
        return self._payload


def test_load_candidate_urls_filters_comments_and_deduplicates():
    """Le fichier de candidats doit ignorer les commentaires, lignes vides et doublons."""
    candidates_path = PROJECT_ROOT / "tests" / "fixtures" / "google_web_risk_candidates_mixed.txt"

    results = google_web_risk._load_candidate_urls(candidates_path)

    assert results == [
        "https://phish.test/login",
        "http://smish.test/path",
    ]


def test_search_url_returns_detected_threat_types(monkeypatch):
    """Le parseur de reponse doit restituer la liste des menaces et l'expiration."""

    def fake_get(url, params, headers, timeout):
        assert params["threatTypes"] == "SOCIAL_ENGINEERING"
        return _FakeResponse(
            {
                "threat": {
                    "threatTypes": ["SOCIAL_ENGINEERING"],
                    "expireTime": "2026-05-11T12:00:00Z",
                }
            }
        )

    monkeypatch.setattr(google_web_risk.requests, "get", fake_get)

    threat_types, expire_time = google_web_risk._search_url("https://phish.test/login", "key-123")

    assert threat_types == ["SOCIAL_ENGINEERING"]
    assert expire_time == "2026-05-11T12:00:00Z"


def test_collect_google_web_risk_keeps_only_social_engineering(monkeypatch):
    """Le collecteur ne doit conserver que les URL classees SOCIAL_ENGINEERING."""
    candidates_path = PROJECT_ROOT / "tests" / "fixtures" / "google_web_risk_candidates_simple.txt"

    def fake_get(url, params, headers, timeout):
        uri = params["uri"]
        if uri == "https://phish.test/login":
            return _FakeResponse({"threat": {"threatTypes": ["SOCIAL_ENGINEERING"]}})
        return _FakeResponse({})

    monkeypatch.setattr(google_web_risk.requests, "get", fake_get)
    monkeypatch.setenv("GOOGLE_WEB_RISK_API_KEY", "key-123")
    monkeypatch.setenv("GOOGLE_WEB_RISK_CANDIDATES_PATH", str(candidates_path))

    results = google_web_risk.collect_google_web_risk()

    assert len(results) == 1
    assert results[0]["url"] == "https://phish.test/login"
    assert results[0]["source"] == "google_web_risk"
    assert results[0]["type"] == "phishing"


def test_collect_google_web_risk_returns_empty_without_api_key(monkeypatch):
    """Sans cle API, le connecteur doit s'arreter proprement."""
    candidates_path = PROJECT_ROOT / "tests" / "fixtures" / "google_web_risk_candidates_simple.txt"

    monkeypatch.delenv("GOOGLE_WEB_RISK_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_WEB_RISK_CANDIDATES_PATH", str(candidates_path))

    results = google_web_risk.collect_google_web_risk()

    assert results == []
