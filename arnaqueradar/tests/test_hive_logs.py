"""
Tests unitaires du connecteur Hive/PhishStats.

Valide la configuration NOSASL, le bootstrap massif PhishStats et le
repli sur cache reel si Hive est indisponible.
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from collect.sources import hive_logs


def test_get_connection_params_defaults_and_phishstats_limits(monkeypatch):
    """Les defaults Hive/PhishStats doivent rester alignes sur la doc officielle."""
    monkeypatch.delenv("HIVE_AUTH", raising=False)
    monkeypatch.delenv("HIVE_PHISHSTATS_TARGET_ROWS", raising=False)
    monkeypatch.delenv("HIVE_PHISHSTATS_PAGE_SIZE", raising=False)
    monkeypatch.delenv("HIVE_FALLBACK_CACHE_TARGET_ROWS", raising=False)
    monkeypatch.delenv("HIVE_FALLBACK_REFRESH_ROWS", raising=False)
    monkeypatch.delenv("HIVE_CACHE_MAX_AGE_HOURS", raising=False)
    monkeypatch.delenv("HIVE_ENABLE_BEELINE_BRIDGE", raising=False)
    monkeypatch.delenv("HIVE_BEELINE_CONTAINER", raising=False)
    monkeypatch.delenv("HIVE_QUERY_MODE", raising=False)

    params = hive_logs._get_connection_params()

    assert params["auth"] == "NOSASL"
    assert params["database"] == "default"
    assert params["username"] == "hive"
    assert hive_logs._phishstats_target_rows() == 50000
    assert hive_logs._phishstats_page_size() == 100
    assert hive_logs._hive_fallback_cache_target_rows() == 500
    assert hive_logs._hive_fallback_refresh_rows() == 500
    assert hive_logs._hive_cache_max_age_hours() == 24
    assert hive_logs._beeline_bridge_enabled() is True
    assert hive_logs._beeline_container_name() == "arnaqueradar-hive-1"
    assert hive_logs._hive_query_mode() == "rows"
    assert hive_logs._current_year_filter_enabled() is False


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
    monkeypatch.setattr(hive_logs, "_table_columns", lambda _cursor: {"url_pattern", "type_arnaque", "region", "event_date", "nb_signalements"})

    query = hive_logs._select_query_for_table(object())

    assert "WHERE YEAR(event_date) = YEAR(CURRENT_DATE)" not in query
    assert "ORDER BY event_date DESC" in query


def test_filter_beeline_output_keeps_only_data_lines():
    """Le parseur beeline doit eliminer le bruit JDBC/SLF4J et garder les resultats."""
    stdout = "\n".join(
        [
            "SLF4J: Class path contains multiple SLF4J bindings.",
            "Connecting to jdbc:hive2://localhost:10000/default;auth=noSasl",
            "Connected to: Apache Hive (version 4.0.0)",
            "INFO  : Executing command(queryId=abc): show tables",
            "logs_arnaques",
            "https://a.example\tphishing\tFrance\t3\t2026-05-14",
            "[WARN] Failed to create directory: /home/hive/.beeline",
            "No such file or directory",
            "Closing: 0: jdbc:hive2://localhost:10000/default;auth=noSasl",
        ]
    )

    lines = hive_logs._filter_beeline_output(stdout)

    assert lines == [
        "logs_arnaques",
        "https://a.example\tphishing\tFrance\t3\t2026-05-14",
    ]


def test_normalize_phishstats_record_infers_type_and_count():
    """La projection Hive doit reutiliser les metadonnees utiles de PhishStats."""
    record = {
        "url": "https://alerte-chronopost-fake.fr/suivi/",
        "title": "Chronopost SMS verification",
        "date": "2026-05-13T08:30:00Z",
        "countryname": "France",
        "n_times_seen_host": "7",
    }

    normalized = hive_logs._normalize_phishstats_record(record)

    assert normalized is not None
    assert normalized["url_pattern"] == "https://alerte-chronopost-fake.fr/suivi"
    assert normalized["type_arnaque"] == "sms_frauduleux"
    assert normalized["region"] == "France"
    assert normalized["event_date"] == "2026-05-13"
    assert normalized["nb_signalements"] == 7


def test_fetch_phishstats_records_paginates_until_target(monkeypatch):
    """Le bootstrap doit paginer jusqu'au volume cible sans depasser la limite."""

    payload_by_page = {
        1: [
            {
                "url": "https://fake-bank-a.com/login",
                "title": "Bank login",
                "date": "2026-05-13T08:00:00Z",
                "countryname": "United States",
                "n_times_seen_host": 2,
            },
            {
                "url": "https://fake-shop-b.com/payment",
                "title": "Payment page",
                "date": "2026-05-13T07:30:00Z",
                "countryname": "Canada",
                "n_times_seen_host": 3,
            },
        ],
        2: [
            {
                "url": "https://microsoft-support-fake.net/help",
                "title": "Tech support alert",
                "date": "2026-05-13T07:00:00Z",
                "countryname": "United Kingdom",
                "n_times_seen_host": 4,
            },
            {
                "url": "https://duplicate-bank-a.com/login",
                "title": "Bank login",
                "date": "2026-05-13T08:00:00Z",
                "countryname": "United States",
                "n_times_seen_host": 2,
            },
        ],
    }

    class _Response:
        def __init__(self, payload):
            self.payload = payload
            self.status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class _Session:
        def __init__(self):
            self.headers = {}

        def get(self, url, params, timeout):
            assert url == hive_logs.PHISHSTATS_API_URL
            assert params["_size"] == 2
            return _Response(payload_by_page.get(int(params["_p"]), []))

    monkeypatch.setenv("HIVE_PHISHSTATS_PAGE_SIZE", "2")
    monkeypatch.setattr(hive_logs.requests, "Session", _Session)
    monkeypatch.setattr(hive_logs.time, "sleep", lambda _: None)

    rows = hive_logs._fetch_phishstats_records(3)

    assert len(rows) == 3
    assert rows[0]["type_arnaque"] == "phishing"
    assert rows[1]["type_arnaque"] == "arnaque_achat"
    assert rows[2]["type_arnaque"] == "faux_support"


def test_ensure_table_ready_bootstraps_when_table_is_under_target(monkeypatch):
    """Une table vide ou trop petite doit lancer le chargement PhishStats."""

    class _Cursor:
        def __init__(self):
            self.executed = []

        def execute(self, query):
            self.executed.append(" ".join(query.split()))

        def fetchone(self):
            return (0,)

    cursor = _Cursor()
    called = []

    def fake_bootstrap(cur, target_rows):
        called.append((cur, target_rows))
        return target_rows

    monkeypatch.setattr(
        hive_logs,
        "_bootstrap_local_raw_table",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("no raw available")),
    )
    monkeypatch.setattr(hive_logs, "_bootstrap_phishstats_table", fake_bootstrap)
    monkeypatch.setenv("HIVE_PHISHSTATS_TARGET_ROWS", "50000")

    hive_logs._ensure_table_ready(cursor)

    assert any("CREATE TABLE IF NOT EXISTS logs_arnaques" in query for query in cursor.executed)
    assert any("SELECT COUNT(*) FROM logs_arnaques" in query for query in cursor.executed)
    assert called == [(cursor, 50000)]


def test_collect_hive_logs_uses_real_cache_when_hive_is_unavailable(monkeypatch):
    """Sans Hive, le connecteur doit reutiliser le dernier cache reel plutot qu'un faux dataset."""
    cache_path = PROJECT_ROOT / "data" / "_test_hive_phishstats_cache.json"
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
        monkeypatch.setenv("HIVE_FALLBACK_CACHE_TARGET_ROWS", "1")
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


def test_collect_hive_logs_refreshes_cache_when_hive_is_unavailable_and_cache_too_small(monkeypatch):
    """Sans Hive, un cache trop petit doit etre reconstruit via PhishStats."""
    cache_path = PROJECT_ROOT / "data" / "_test_hive_refresh_cache.json"
    cache_entries = [
        {
            "url": "https://cached-small.example/login",
            "type": "phishing",
            "source": "hive_logs",
            "date_signalement": "2026-05-13",
            "region": "France",
            "nb_signalements": 2,
        }
    ]
    refreshed_entries = [
        {
            "url": "https://refresh-a.example/login",
            "type": "phishing",
            "source": "hive_logs",
            "date_signalement": "2026-05-13",
            "region": "France",
            "nb_signalements": 3,
        },
        {
            "url": "https://refresh-b.example/help",
            "type": "faux_support",
            "source": "hive_logs",
            "date_signalement": "2026-05-13",
            "region": "Canada",
            "nb_signalements": 4,
        },
    ]
    try:
        cache_path.write_text(json.dumps(cache_entries), encoding="utf-8")
        monkeypatch.setattr(hive_logs, "CACHE_PATH", cache_path)
        monkeypatch.setenv("HIVE_FALLBACK_CACHE_TARGET_ROWS", "2")
        monkeypatch.setenv("HIVE_CACHE_MAX_AGE_HOURS", "0")
        monkeypatch.setenv("HIVE_FALLBACK_REFRESH_ROWS", "100")
        monkeypatch.setattr(hive_logs, "_is_cache_recent", lambda: False)

        def fake_refresh(target_rows):
            assert target_rows == 100
            return refreshed_entries

        monkeypatch.setattr(hive_logs, "_refresh_cache_without_hive", fake_refresh)

        real_import = __import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "pyhive":
                raise ModuleNotFoundError("pyhive")
            return real_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr("builtins.__import__", fake_import)

        results = hive_logs.collect_hive_logs()

        assert results == refreshed_entries
    finally:
        cache_path.unlink(missing_ok=True)


def test_collect_hive_logs_refreshes_recent_cache_when_it_is_too_small(monkeypatch):
    """Un cache recent mais trop petit ne doit plus bloquer indefiniment la source a 200 lignes."""
    cache_path = PROJECT_ROOT / "data" / "_test_hive_recent_cache.json"
    cache_entries = [
        {
            "url": "https://recent-cache.example/login",
            "type": "phishing",
            "source": "hive_logs",
            "date_signalement": "2026-05-13",
            "region": "France",
            "nb_signalements": 2,
        }
    ]
    refreshed_entries = [
        {
            "url": "https://recent-refresh-a.example/login",
            "type": "phishing",
            "source": "hive_logs",
            "date_signalement": "2026-05-13",
            "region": "France",
            "nb_signalements": 3,
        },
        {
            "url": "https://recent-refresh-b.example/help",
            "type": "faux_support",
            "source": "hive_logs",
            "date_signalement": "2026-05-13",
            "region": "Canada",
            "nb_signalements": 4,
        },
    ]
    try:
        cache_path.write_text(json.dumps(cache_entries), encoding="utf-8")
        monkeypatch.setattr(hive_logs, "CACHE_PATH", cache_path)
        monkeypatch.setenv("HIVE_FALLBACK_CACHE_TARGET_ROWS", "500")
        monkeypatch.setenv("HIVE_CACHE_MAX_AGE_HOURS", "24")
        monkeypatch.setenv("HIVE_FALLBACK_REFRESH_ROWS", "600")
        monkeypatch.setattr(hive_logs, "_is_cache_recent", lambda: True)

        def fake_refresh(target_rows):
            assert target_rows == 600
            return refreshed_entries

        monkeypatch.setattr(hive_logs, "_refresh_cache_without_hive", fake_refresh)

        real_import = __import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "pyhive":
                raise ModuleNotFoundError("pyhive")
            return real_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr("builtins.__import__", fake_import)

        results = hive_logs.collect_hive_logs()

        assert results == refreshed_entries
    finally:
        cache_path.unlink(missing_ok=True)


def test_collect_hive_logs_uses_beeline_bridge_before_cache(monkeypatch):
    """Si pyhive echoue mais que Hive live reste accessible via beeline, on doit preferer ce mode."""
    bridge_entries = [
        {
            "url": "https://live-hive.example/login",
            "type": "phishing",
            "source": "hive_logs",
            "date_signalement": "2026-05-14",
            "region": "France",
            "nb_signalements": 8,
        }
    ]

    monkeypatch.setattr(hive_logs, "_collect_hive_logs_via_beeline_bridge", lambda: bridge_entries)

    real_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "pyhive":
            raise RuntimeError("TSocket read 0 bytes")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)

    results = hive_logs.collect_hive_logs()

    assert results == bridge_entries


def test_load_rows_from_latest_raw_reuses_local_pipeline_dump(monkeypatch):
    """Le bootstrap local doit pouvoir puiser dans un raw existant pour nourrir Hive live."""
    payload = [
        {
            "url": "https://source-1.example/login",
            "type": "phishing",
            "source": "urlhaus",
            "date_signalement": "2026-05-14",
            "region": "France",
            "nb_signalements": 4,
        },
        {
            "url": "https://source-2.example/help",
            "type": "faux_support",
            "source": "malwaretips",
            "date_signalement": "2026-05-13",
            "region": "Canada",
            "nb_signalements": 2,
        },
        {
            "url": "https://ignored.example/from-hive",
            "type": "phishing",
            "source": "hive_logs",
            "date_signalement": "2026-05-13",
            "region": "France",
            "nb_signalements": 9,
        },
    ]

    raw_path = PROJECT_ROOT / "data" / "_test_raw_20260514_101931.json"
    try:
        raw_path.write_text(json.dumps(payload), encoding="utf-8")
        monkeypatch.setattr(hive_logs, "DATA_DIR", PROJECT_ROOT / "data")
        monkeypatch.setattr(hive_logs, "_latest_raw_dataset_path", lambda: raw_path)

        rows = hive_logs._load_rows_from_latest_raw(10)

        assert len(rows) == 2
        assert rows[0]["url_pattern"] == "https://source-1.example/login"
        assert rows[1]["type_arnaque"] == "faux_support"
    finally:
        raw_path.unlink(missing_ok=True)
