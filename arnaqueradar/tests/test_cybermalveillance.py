"""
Tests unitaires du connecteur Cybermalveillance.

Valide l'extraction depuis les pages officielles, le repli sur le flux Atom
et le fallback CSV final.
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

SAMPLE_BLOG_HTML = """
<html>
  <body>
    <article class="post-small audience-tous-publics alt-layout">
      <a href="/tous-nos-contenus/actualites/article-1">
        <div class="main">
          <h3>Premier article HTML</h3>
          <p class="secondary-metas"><span class="date">13/05/2026</span></p>
        </div>
      </a>
    </article>
    <article class="post-small audience-tous-publics alt-layout">
      <a href="/tous-nos-contenus/actualites/article-2">
        <div class="main">
          <h3>Deuxieme article HTML</h3>
          <p class="secondary-metas"><span class="date">12/05/2026</span></p>
        </div>
      </a>
    </article>
    <article class="post-small audience-tous-publics alt-layout">
      <a href="/tous-nos-contenus/actualites/article-1">
        <div class="main">
          <h3>Premier article HTML</h3>
          <p class="secondary-metas"><span class="date">13/05/2026</span></p>
        </div>
      </a>
    </article>
  </body>
</html>
"""


def test_parse_blog_page_extracts_articles_and_deduplicates():
    """Le parseur HTML doit extraire les articles et dedoublonner les URLs."""
    results = cybermalveillance._parse_blog_page(
        SAMPLE_BLOG_HTML,
        "https://www.cybermalveillance.gouv.fr/blog/cybermenace",
    )

    assert len(results) == 2
    assert results[0]["url"] == "https://www.cybermalveillance.gouv.fr/tous-nos-contenus/actualites/article-1"
    assert results[0]["date_signalement"] == "2026-05-13"
    assert results[1]["titre"] == "Deuxieme article HTML"


def test_parse_atom_feed_rejects_empty_feed():
    """Un flux sans entree doit etre refuse explicitement."""
    try:
        cybermalveillance._parse_atom_feed("<feed xmlns='http://www.w3.org/2005/Atom'></feed>")
    except ValueError as exc:
        assert "aucune entree" in str(exc)
    else:
        raise AssertionError("Le parseur aurait du lever ValueError")


def test_collect_cybermalveillance_uses_blog_pages_first(monkeypatch):
    """Le collecteur doit privilegier les pages HTML officielles."""

    def fake_get(url, timeout, headers):
        return _FakeResponse(SAMPLE_BLOG_HTML, status_code=200, url=url)

    monkeypatch.setattr(cybermalveillance.requests, "get", fake_get)

    results = cybermalveillance.collect_cybermalveillance()

    assert len(results) == 2
    assert all(entry["source"] == "cybermalveillance" for entry in results)
    assert results[0]["titre"] == "Premier article HTML"


def test_collect_cybermalveillance_falls_back_to_atom_when_html_fails(monkeypatch):
    """En cas d'echec HTML, le connecteur doit retomber sur le flux Atom."""

    def fake_get(url, timeout, headers):
        if "feed/atom-flux-actualites" in url:
            return _FakeResponse(SAMPLE_ATOM, status_code=200, url=url)
        return _FakeResponse("", status_code=500, url=url)

    monkeypatch.setattr(cybermalveillance.requests, "get", fake_get)

    results = cybermalveillance.collect_cybermalveillance()

    assert len(results) == 2
    assert results[1]["titre"] == "Deuxieme & article"


def test_collect_cybermalveillance_uses_fallback_when_html_and_atom_fail(monkeypatch):
    """En cas d'erreurs reseau HTML + Atom, le fallback CSV doit etre utilise."""

    def fake_get(url, timeout, headers):
        return _FakeResponse("", status_code=410, url=url)

    monkeypatch.setattr(cybermalveillance.requests, "get", fake_get)

    results = cybermalveillance.collect_cybermalveillance()

    assert len(results) >= 1
    assert all(entry["source"] == "cybermalveillance" for entry in results)
