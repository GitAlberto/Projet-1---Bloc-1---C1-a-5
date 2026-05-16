"""
Tests unitaires du connecteur URLhaus.

Valide la collecte historique via les feeds officiels et le fallback `recent`
de l'API URLhaus.
"""

import sys
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.collect.sources import urlhaus


class _FakeResponse:
    """Double minimal de requests.Response pour les tests JSON."""

    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error", response=self)

    def json(self):
        return self._payload


class _FakeStreamResponse:
    """Double minimal de Response pour les feeds CSV streamés."""

    def __init__(self, lines: list[str], status_code: int = 200):
        self._lines = lines
        self.status_code = status_code

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error", response=self)

    def iter_lines(self, decode_unicode: bool = False):
        for line in self._lines:
            yield line


def test_recent_limit_is_bounded(monkeypatch):
    """La limite `recent` doit rester comprise entre 1 et 1000."""
    monkeypatch.setenv("URLHAUS_RECENT_LIMIT", "5000")
    assert urlhaus._recent_limit() == 1000

    monkeypatch.setenv("URLHAUS_RECENT_LIMIT", "0")
    assert urlhaus._recent_limit() == 1

    monkeypatch.setenv("URLHAUS_RECENT_LIMIT", "abc")
    assert urlhaus._recent_limit() == 100


def test_max_entries_is_bounded(monkeypatch):
    """Le plafond global doit rester strictement borne sous 15 000."""
    monkeypatch.setenv("URLHAUS_MAX_ENTRIES", "50000")
    assert urlhaus._max_entries() == 14999

    monkeypatch.setenv("URLHAUS_MAX_ENTRIES", "0")
    assert urlhaus._max_entries() == 1

    monkeypatch.setenv("URLHAUS_MAX_ENTRIES", "abc")
    assert urlhaus._max_entries() == 14999


def test_fetch_recent_urls_uses_auth_header_and_limit(monkeypatch):
    """La requete `recent` doit utiliser l'Auth-Key et la limite configuree."""

    def fake_get(url, headers, timeout):
        assert url == "https://urlhaus-api.abuse.ch/v1/urls/recent/limit/3/"
        assert headers["Auth-Key"] == "auth-123"
        return _FakeResponse({"query_status": "ok", "urls": []})

    monkeypatch.setattr(urlhaus.requests, "get", fake_get)

    results = urlhaus._fetch_recent_urls("auth-123", 3)

    assert results == []


def test_fetch_country_feed_parses_official_csv_rows(monkeypatch):
    """Le feed CSV officiel doit etre parse et normalise correctement."""

    def fake_get(url, headers, timeout, stream):
        assert "country=FR" in url
        assert headers["User-Agent"] == "ArnaqueRadar/1.0"
        assert stream is True
        return _FakeStreamResponse(
            [
                "##############################################################################",
                "# URLhaus Country CSV Feed",
                '"2026-05-08 12:20:11","http://176.31.142.221/hFkkIhF.txt","offline","malware_download","176.31.142.221","176.31.142.221","16276","FR"',
                '"2026-05-08 10:38:21","https://nmturc.cyou/Senior4/img_101400.png","offline","malware_download","nmturc.cyou","185.8.51.164","199653","FR"',
            ]
        )

    monkeypatch.setattr(urlhaus.requests, "get", fake_get)

    results = urlhaus._fetch_country_feed("FR", 10)

    assert len(results) == 2
    assert results[0]["source"] == "urlhaus"
    assert results[0]["date_signalement"] == "2026-05-08"
    assert results[0]["titre"].startswith("URLhaus - threat: malware_download")


def test_collect_urlhaus_prefers_historical_feeds(monkeypatch):
    """Les feeds historiques doivent etre preferes au fallback API."""
    monkeypatch.setattr(
        urlhaus,
        "_collect_feed_entries",
        lambda limit: [
            {
                "url": "https://feed.test/payload.exe",
                "type": "autre",
                "source": "urlhaus",
                "date_signalement": "2026-05-13",
                "verified": True,
                "titre": "URLhaus - threat: malware_download | status: offline | country: FR",
            }
        ],
    )
    monkeypatch.delenv("URLHAUS_AUTH_KEY", raising=False)

    results = urlhaus.collect_urlhaus()

    assert len(results) == 1
    assert results[0]["url"] == "https://feed.test/payload.exe"


def test_collect_urlhaus_falls_back_to_recent_api_when_feeds_empty(monkeypatch):
    """Si les feeds sont vides, le collecteur doit basculer sur l'API recent."""
    monkeypatch.setattr(urlhaus, "_collect_feed_entries", lambda limit: [])
    monkeypatch.setattr(
        urlhaus,
        "_fetch_recent_urls",
        lambda auth_key, limit: [
            {
                "url": "https://phish.test/login",
                "date_added": "2026-05-13 08:22:00 UTC",
                "threat": "malware_download",
                "tags": ["phishing"],
                "blacklists": {"spamhaus_dbl": "phishing_domain"},
            }
        ],
    )
    monkeypatch.setenv("URLHAUS_AUTH_KEY", "auth-123")
    monkeypatch.setenv("URLHAUS_RECENT_LIMIT", "3")

    results = urlhaus.collect_urlhaus()

    assert len(results) == 1
    assert results[0]["type"] == "phishing"
    assert results[0]["verified"] is True


def test_collect_urlhaus_returns_empty_when_feeds_empty_and_auth_missing(monkeypatch):
    """Sans feed exploitable ni Auth-Key, le collecteur doit s'arreter proprement."""
    monkeypatch.setattr(urlhaus, "_collect_feed_entries", lambda limit: [])
    monkeypatch.delenv("URLHAUS_AUTH_KEY", raising=False)

    results = urlhaus.collect_urlhaus()

    assert results == []
