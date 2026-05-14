"""
Tests unitaires du connecteur PostgreSQL historique.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from collect.sources import pg_history


def test_build_title_prefers_description():
    """Le titre doit privilegier la description metier quand elle existe."""
    row = {
        "description_signalement": "Signalement interne : faux portail bancaire",
        "canal": "web",
        "source_interne": "portail_web",
    }
    assert pg_history._build_title(row) == "Signalement interne : faux portail bancaire"


def test_normalize_row_preserves_business_fields():
    """La normalisation doit conserver les champs utiles au pipeline."""
    row = {
        "url": "https://alerte-client-12-securite.fr/connexion/",
        "type": "phishing",
        "region": "Ile-de-France",
        "date_signalement": "2026-05-13",
        "verified": True,
        "nb_signalements": 7,
        "description_signalement": "Signalement interne : faux portail de connexion",
        "canal": "web",
        "source_interne": "portail_web",
    }

    normalized = pg_history._normalize_row(row)

    assert normalized["url"] == "https://alerte-client-12-securite.fr/connexion"
    assert normalized["type"] == "phishing"
    assert normalized["source"] == "pg_history"
    assert normalized["verified"] is True
    assert normalized["nb_signalements"] == 7
    assert normalized["titre"] == "Signalement interne : faux portail de connexion"


def test_extraction_query_filters_verified_and_validated_rows():
    """La requete ne doit extraire que les lignes historiques exploitables."""
    query = pg_history.EXTRACTION_QUERY

    assert "COALESCE(verified, FALSE) = TRUE" in query
    assert "IN ('valide', 'confirme')" in query
    assert "CURRENT_DATE - INTERVAL '180 days'" in query
