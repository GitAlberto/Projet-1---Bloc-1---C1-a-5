"""
Tests unitaires du module d'agrégation et de contrôle qualité.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from aggregate.aggregate import aggregate_sources, build_other_review_sample, build_quality_report


def test_aggregate_sources_preserves_enrichment_fields():
    """L'agrégation doit conserver et normaliser les champs enrichis utiles au reporting."""
    raw_data = [
        {
            "url": "HTTPS://MAIL.EXAMPLE.COM/login/",
            "type": "phish",
            "source": "urlhaus",
            "date_signalement": "2026-05-14T08:30:00Z",
            "canal": "email",
            "nature_technique": "phishing",
            "score_confiance": "0.87",
            "type_raw": "malware_download",
            "source_category_raw": "phishing_domain|mail",
            "keywords_matched": ["login", "mailbox", "login"],
            "classifier_version": "urlhaus_rules_v2",
            "nb_signalements": "4",
            "verified": "true",
            "titre": "Login alert",
        }
    ]

    df = aggregate_sources(raw_data)

    assert len(df) == 1
    row = df.iloc[0]
    assert row["url"] == "https://mail.example.com/login"
    assert row["type"] == "phishing"
    assert row["type_arnaque"] == "phishing"
    assert row["canal"] == "email"
    assert row["nature_technique"] == "phishing"
    assert row["score_confiance"] == 0.87
    assert row["keywords_matched"] == "login|mailbox"
    assert row["nb_signalements"] == 4
    assert bool(row["verified"]) is True


def test_quality_report_flags_too_many_other_rows():
    """Le rapport qualité doit signaler les dérives quand 'autre' est trop élevé."""
    raw_data = [
        {
            "url": "https://safe-a.example",
            "type": "autre",
            "source": "urlhaus",
            "date_signalement": "2026-05-14",
            "nature_technique": "autre",
            "score_confiance": 0.32,
            "keywords_matched": "",
        },
        {
            "url": "https://safe-b.example",
            "type": "autre",
            "source": "urlhaus",
            "date_signalement": "2026-05-13",
            "nature_technique": "autre",
            "score_confiance": 0.35,
            "keywords_matched": "",
        },
        {
            "url": "https://safe-c.example",
            "type": "phishing",
            "source": "malwaretips",
            "date_signalement": "2026-05-12",
            "nature_technique": "phishing",
            "score_confiance": 0.91,
            "keywords_matched": "login|verify",
        },
    ]

    df = aggregate_sources(raw_data)
    report = build_quality_report(df)
    sample = build_other_review_sample(df, max_total=10, max_per_source=10)

    assert report["autre_global_pct"] > 15.0
    assert any(alert.startswith("autre_global_trop_eleve") for alert in report["alerts"])
    assert "urlhaus" in report["autre_by_source"]
    assert len(sample) == 2
    assert set(sample["source"]) == {"urlhaus"}
