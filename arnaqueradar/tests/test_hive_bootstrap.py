"""
Tests unitaires du bootstrap Hive PhishStats.

Valide les defaults de pagination, la projection enrichie des enregistrements
PhishStats et le comportement de pagination jusqu'au volume cible.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.collect import bootstrap_hive_phishstats


def test_phishstats_bootstrap_defaults(monkeypatch):
    """Les defaults du bootstrap doivent rester alignes avec la cible 50k."""
    monkeypatch.delenv("HIVE_PHISHSTATS_TARGET_ROWS", raising=False)
    monkeypatch.delenv("HIVE_PHISHSTATS_PAGE_SIZE", raising=False)
    monkeypatch.delenv("HIVE_PHISHSTATS_REQUEST_DELAY_SECONDS", raising=False)
    monkeypatch.delenv("HIVE_PHISHSTATS_RETRY_AFTER_SECONDS", raising=False)

    assert bootstrap_hive_phishstats._phishstats_target_rows() == 50000
    assert bootstrap_hive_phishstats._phishstats_page_size() == 100
    assert bootstrap_hive_phishstats._phishstats_delay_seconds() == 6.5
    assert bootstrap_hive_phishstats._phishstats_retry_after_seconds() == 60.0


def test_normalize_phishstats_record_infers_type_and_count():
    """La projection Hive doit reutiliser les metadonnees utiles de PhishStats."""
    record = {
        "url": "https://alerte-chronopost-fake.fr/suivi/",
        "title": "Chronopost SMS verification",
        "brand": "Chronopost",
        "family": "postal_scam",
        "tags": ["sms", "delivery", "parcel"],
        "host": "alerte-chronopost-fake.fr",
        "domain": "chronopost-fake.fr",
        "date": "2026-05-13T08:30:00Z",
        "countryname": "France",
        "n_times_seen_host": "7",
    }

    normalized = bootstrap_hive_phishstats._normalize_phishstats_record(record)

    assert normalized is not None
    assert normalized["url_pattern"] == "https://alerte-chronopost-fake.fr/suivi"
    assert normalized["type_arnaque"] == "sms_frauduleux"
    assert normalized["region"] == "France"
    assert normalized["event_date"] == "2026-05-13"
    assert normalized["nb_signalements"] == 7
    assert normalized["title"] == "Chronopost SMS verification"
    assert normalized["brand"] == "Chronopost"
    assert normalized["family"] == "postal_scam"
    assert normalized["tags"] == "sms|delivery|parcel"
    assert normalized["host"] == "alerte-chronopost-fake.fr"
    assert normalized["domain"] == "chronopost-fake.fr"


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
            self.headers = {}

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class _Session:
        def __init__(self):
            self.headers = {}

        def get(self, url, params, timeout):
            assert url == bootstrap_hive_phishstats.PHISHSTATS_API_URL
            assert params["_size"] == 2
            return _Response(payload_by_page.get(int(params["_p"]), []))

    monkeypatch.setenv("HIVE_PHISHSTATS_PAGE_SIZE", "2")
    monkeypatch.setattr(bootstrap_hive_phishstats.requests, "Session", _Session)
    monkeypatch.setattr(bootstrap_hive_phishstats.time, "sleep", lambda _: None)

    rows = bootstrap_hive_phishstats._fetch_phishstats_records(3)

    assert len(rows) == 3
    assert rows[0]["type_arnaque"] == "phishing"
    assert rows[1]["type_arnaque"] == "arnaque_achat"
    assert rows[2]["type_arnaque"] == "faux_support"


def test_bootstrap_skips_reload_when_hive_is_already_populated(monkeypatch):
    """Le bootstrap manuel ne doit pas repaginer inutilement si Hive est deja plein."""

    class _Cursor:
        def __init__(self):
            self.executed = []

        def execute(self, query):
            self.executed.append(" ".join(str(query).split()))

        def fetchone(self):
            return (50000,)

        def fetchall(self):
            return []

        def close(self):
            return None

    class _Conn:
        def __init__(self):
            self.cursor_obj = _Cursor()

        def cursor(self):
            return self.cursor_obj

        def close(self):
            return None

    class _Hive:
        @staticmethod
        def connect(**_params):
            return _Conn()

    monkeypatch.setattr("pyhive.hive.connect", _Hive.connect, raising=False)
    monkeypatch.setattr(bootstrap_hive_phishstats, "_fetch_phishstats_records", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        bootstrap_hive_phishstats,
        "_ensure_table_schema",
        lambda _cursor: None,
    )

    count = bootstrap_hive_phishstats.bootstrap_hive_from_phishstats(target_rows=50000, force_refresh=False)

    assert count == 50000
