"""
Tests unitaires du connecteur URLhaus.

Valide la requete API, le parsing de la reponse recent URLs et la
normalisation vers les types ArnaqueRadar.
"""

import sys
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from collect.sources import urlhaus


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


def test_recent_limit_is_bounded(monkeypatch):
    """La limite API doit rester comprise entre 1 et 1000."""
    monkeypatch.setenv("URLHAUS_RECENT_LIMIT", "5000")
    assert urlhaus._recent_limit() == 1000

    monkeypatch.setenv("URLHAUS_RECENT_LIMIT", "0")
    assert urlhaus._recent_limit() == 1

    monkeypatch.setenv("URLHAUS_RECENT_LIMIT", "abc")
    assert urlhaus._recent_limit() == 100


def test_fetch_recent_urls_uses_auth_header_and_limit(monkeypatch):
    """La requete URLhaus doit utiliser l'Auth-Key et la limite configuree."""

    def fake_get(url, headers, timeout):
        assert url == "https://urlhaus-api.abuse.ch/v1/urls/recent/limit/3/"
        assert headers["Auth-Key"] == "auth-123"
        return _FakeResponse({"query_status": "ok", "urls": []})

    monkeypatch.setattr(urlhaus.requests, "get", fake_get)

    results = urlhaus._fetch_recent_urls("auth-123", 3)

    assert results == []


def test_collect_urlhaus_normalizes_entries(monkeypatch):
    """Le collecteur doit normaliser les URLs recentes et mapper les types explicites."""

    def fake_get(url, headers, timeout):
        return _FakeResponse(
            {
                "query_status": "ok",
                "urls": [
                    {
                        "url": "https://phish.test/login",
                        "date_added": "2026-05-13 08:22:00 UTC",
                        "threat": "malware_download",
                        "tags": ["phishing"],
                        "blacklists": {"spamhaus_dbl": "phishing_domain"},
                    },
                    {
                        "url": "https://sms.test/confirm",
                        "date_added": "2026-05-13 09:30:00 UTC",
                        "threat": "malware_download",
                        "tags": ["smishing"],
                        "blacklists": {},
                    },
                    {
                        "url": "https://payload.test/file.exe",
                        "date_added": "2026-05-13 10:00:00 UTC",
                        "threat": "malware_download",
                        "tags": ["loader"],
                        "blacklists": {},
                    },
                ],
            }
        )

    monkeypatch.setattr(urlhaus.requests, "get", fake_get)
    monkeypatch.setenv("URLHAUS_AUTH_KEY", "auth-123")
    monkeypatch.setenv("URLHAUS_RECENT_LIMIT", "3")

    results = urlhaus.collect_urlhaus()

    assert len(results) == 3
    assert results[0]["source"] == "urlhaus"
    assert results[0]["type"] == "phishing"
    assert results[0]["date_signalement"] == "2026-05-13"
    assert results[1]["type"] == "sms_frauduleux"
    assert results[2]["type"] == "autre"
    assert results[2]["verified"] is True
    assert results[2]["titre"].startswith("URLhaus")


def test_collect_urlhaus_returns_empty_without_auth_key(monkeypatch):
    """Sans Auth-Key, le connecteur doit s'arreter proprement."""
    monkeypatch.delenv("URLHAUS_AUTH_KEY", raising=False)

    results = urlhaus.collect_urlhaus()

    assert results == []
