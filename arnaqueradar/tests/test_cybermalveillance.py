"""
Tests unitaires du connecteur Cybermalveillance.

Valide le parsing du flux Atom officiel et le fallback CSV.
"""

import sys
from pathlib import Path

import requests

# Ajout de la racine du projet au path pour les imports
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from collect.sources import cybermalveillance


class _FakeResponse:
    """Double minimal de requests.Response pour les tests du connecteur."""

    def __init__(self, text: str, status_code: int = 200, url: str = ""):
        self.text = text
        self.status_code = status_code
        self.url = url

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error", response=self)


SAMPLE_ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>https://www.cybermalveillance.gouv.fr/tous-nos-contenus/actualites/article-1</id>
    <title><![CDATA[Premier article]]></title>
    <link href="https://www.cybermalveillance.gouv.fr/tous-nos-contenus/actualites/article-1"/>
    <updated>2026-05-11T12:27:32+02:00</updated>
    <published>2026-05-06 09:44:45</published>
  </entry>
  <entry>
    <id>https://www.cybermalveillance.gouv.fr/tous-nos-contenus/actualites/article-2</id>
    <title><![CDATA[Deuxieme &amp; article]]></title>
    <link href="https://www.cybermalveillance.gouv.fr/tous-nos-contenus/actualites/article-2"/>
    <updated>2026-05-07T08:12:00+02:00</updated>
  </entry>
</feed>
"""


def test_parse_atom_feed_extracts_articles():
    """Le parseur Atom doit extraire les URLs, titres et dates."""
    results = cybermalveillance._parse_atom_feed(SAMPLE_ATOM)

    assert len(results) == 2
    assert results[0]["url"] == "https://www.cybermalveillance.gouv.fr/tous-nos-contenus/actualites/article-1"
    assert results[0]["date_signalement"] == "2026-05-06"
    assert results[1]["titre"] == "Deuxieme & article"


def test_parse_atom_feed_rejects_empty_feed():
    """Un flux sans entree doit etre refuse explicitement."""
    try:
        cybermalveillance._parse_atom_feed("<feed xmlns='http://www.w3.org/2005/Atom'></feed>")
    except ValueError as exc:
        assert "aucune entree" in str(exc)
    else:
        raise AssertionError("Le parseur aurait du lever ValueError")


def test_collect_cybermalveillance_uses_atom_feed(monkeypatch):
    """Le collecteur doit utiliser le flux Atom officiel quand il est disponible."""

    def fake_get(url, timeout, headers):
        return _FakeResponse(SAMPLE_ATOM, status_code=200, url=url)

    monkeypatch.setattr(cybermalveillance.requests, "get", fake_get)

    results = cybermalveillance.collect_cybermalveillance()

    assert len(results) == 2
    assert all(entry["source"] == "cybermalveillance" for entry in results)


def test_collect_cybermalveillance_uses_fallback_when_feed_fails(monkeypatch):
    """En cas d'erreur reseau, le fallback CSV doit etre utilise."""

    def fake_get(url, timeout, headers):
        return _FakeResponse("", status_code=410, url=url)

    monkeypatch.setattr(cybermalveillance.requests, "get", fake_get)

    results = cybermalveillance.collect_cybermalveillance()

    assert len(results) >= 1
    assert all(entry["source"] == "cybermalveillance" for entry in results)
