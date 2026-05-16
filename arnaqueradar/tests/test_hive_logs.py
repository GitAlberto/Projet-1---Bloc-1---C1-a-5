"""
Tests unitaires du connecteur Hive en lecture stricte.

Valide la configuration NOSASL, le choix des requetes Hive, la projection des
metadonnees conservees dans Hive et le repli sur cache local.
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.collect.sources import hive_logs


def test_get_connection_params_defaults_and_cache_age(monkeypatch):
    """Les defaults Hive de lecture doivent rester simples et coherents."""
    monkeypatch.delenv("HIVE_AUTH", raising=False)
    monkeypatch.delenv("HIVE_QUERY_MODE", raising=False)
    monkeypatch.delenv("HIVE_FILTER_CURRENT_YEAR", raising=False)
    monkeypatch.delenv("HIVE_CACHE_MAX_AGE_HOURS", raising=False)

    params = hive_logs._get_connection_params()

    assert params["auth"] == "NOSASL"
    assert params["database"] == "default"
    assert params["username"] == "hive"
    assert hive_logs._hive_query_mode() == "rows"
    assert hive_logs._current_year_filter_enabled() is False
    assert hive_logs._hive_cache_max_age_hours() == 24


def test_current_year_filter_defaults_follow_query_mode(monkeypatch):
    """Le filtrage annuel doit rester optionnel en rows et actif par defaut en aggregate."""
    monkeypatch.delenv("HIVE_FILTER_CURRENT_YEAR", raising=False)
    monkeypatch.setenv("HIVE_QUERY_MODE", "aggregate")
    assert hive_logs._current_year_filter_enabled() is True

    monkeypatch.setenv("HIVE_QUERY_MODE", "rows")
    assert hive_logs._current_year_filter_enabled() is False

    monkeypatch.setenv("HIVE_FILTER_CURRENT_YEAR", "true")
    assert hive_logs._current_year_filter_enabled() is True


def test_select_query_for_table_uses_all_rows_by_default(monkeypatch):
    """En mode rows, la requete live ne doit pas jeter l'historique hors annee courante."""
    monkeypatch.delenv("HIVE_FILTER_CURRENT_YEAR", raising=False)
    monkeypatch.setenv("HIVE_QUERY_MODE", "rows")
    monkeypatch.setattr(
        hive_logs,
        "_table_columns",
        lambda _cursor: {"url_pattern", "type_arnaque", "region", "event_date", "nb_signalements"},
    )

    query = hive_logs._select_query_for_table(object())

    assert "WHERE YEAR(event_date) = YEAR(CURRENT_DATE)" not in query
    assert "ORDER BY event_date DESC" in query
    assert "'' AS title" in query


def test_normalize_hive_row_enriches_output():
    """La projection Hive doit reutiliser les metadonnees pour mieux qualifier la ligne."""
    row = {
        "url": "https://fake-microsoft-help.example/help/",
        "type": "autre",
        "region": "France",
        "date_signalement": "2026-05-14",
        "nb_signalements": 6,
        "title": "Microsoft support warning",
        "brand": "Microsoft",
        "family": "support_scam",
        "tags": "support|call",
        "host": "fake-microsoft-help.example",
        "domain": "microsoft-help.example",
    }

    normalized = hive_logs._normalize_hive_row(row)

    assert normalized["url"] == "https://fake-microsoft-help.example/help"
    assert normalized["source"] == "hive_logs"
    assert normalized["nb_signalements"] == 6
    assert normalized["type"] == "faux_support"
    assert normalized["titre"] == "Microsoft support warning"
    assert "Microsoft" in normalized["source_category_raw"]
    assert "classifier_version" in normalized


def test_collect_hive_logs_uses_real_cache_when_hive_is_unavailable(monkeypatch):
    """Sans Hive, le connecteur doit reutiliser le dernier cache reel plutot qu'une source externe."""
    cache_path = PROJECT_ROOT / "data" / "_test_hive_cache.json"
    cache_entries = [
        {
            "url": "https://cached-phish.example/login",
            "type": "phishing",
            "source": "hive_logs",
            "date_signalement": "2026-05-13",
            "region": "France",
            "nb_signalements": 9,
        }
    ]
    try:
        cache_path.write_text(json.dumps(cache_entries), encoding="utf-8")
        monkeypatch.setattr(hive_logs, "CACHE_PATH", cache_path)
        monkeypatch.setenv("HIVE_CACHE_MAX_AGE_HOURS", "24")

        real_import = __import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "pyhive":
                raise ModuleNotFoundError("pyhive")
            return real_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr("builtins.__import__", fake_import)

        results = hive_logs.collect_hive_logs()

        assert results == cache_entries
    finally:
        cache_path.unlink(missing_ok=True)
