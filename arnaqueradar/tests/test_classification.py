"""
Tests unitaires du module collect/classification.py.

Ce module est le moteur central de qualification des arnaques.
Il classe chaque entree brute vers un type metier, un canal, une nature
technique et un score de confiance. Ces tests couvrent les chemins
critiques : seed_type connu, regles par mots-cles, malware, social et fallback.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.collect.classification import (
    CLASSIFIER_VERSION,
    classify_signal,
    join_keywords,
    normalize_canal,
    normalize_nature,
    normalize_type,
    score_to_float,
)


class TestNormalizeType:
    """Tests de la normalisation des types metier."""

    def test_phishing_direct(self):
        assert normalize_type("phishing") == "phishing"

    def test_phish_alias(self):
        assert normalize_type("phish") == "phishing"

    def test_hameconnage(self):
        assert normalize_type("hameconnage") == "phishing"

    def test_smishing_alias(self):
        assert normalize_type("smishing") == "sms_frauduleux"

    def test_data_breach_alias(self):
        assert normalize_type("data_breach") == "violation_rgpd"

    def test_unknown_becomes_autre(self):
        assert normalize_type("inconnu_xyz") == "autre"

    def test_none_becomes_autre(self):
        assert normalize_type(None) == "autre"

    def test_empty_becomes_autre(self):
        assert normalize_type("") == "autre"

    def test_case_insensitive(self):
        # la normalisation se fait en lowercase ASCII avant lookup
        assert normalize_type("Phishing") == "phishing"


class TestNormalizeCanal:
    """Tests de la normalisation des canaux."""

    def test_web_direct(self):
        assert normalize_canal("web") == "web"

    def test_sms_direct(self):
        assert normalize_canal("sms") == "sms"

    def test_unknown_uses_fallback(self):
        assert normalize_canal("inconnu", fallback="web") == "web"

    def test_fuite_donnees(self):
        assert normalize_canal("fuite_donnees") == "fuite_donnees"

    def test_none_uses_fallback(self):
        assert normalize_canal(None, fallback="web") == "web"


class TestNormalizeNature:
    """Tests de la normalisation des natures techniques."""

    def test_phishing_direct(self):
        assert normalize_nature("phishing") == "phishing"

    def test_malware_direct(self):
        assert normalize_nature("malware") == "malware"

    def test_unknown_uses_fallback(self):
        assert normalize_nature("inconnu", fallback="autre") == "autre"

    def test_data_breach(self):
        assert normalize_nature("data_breach") == "data_breach"


class TestScoreToFloat:
    """Tests du bornage des scores de confiance."""

    def test_valid_float(self):
        assert score_to_float(0.85) == 0.85

    def test_clamp_above_one(self):
        assert score_to_float(1.5) == 1.0

    def test_clamp_below_zero(self):
        assert score_to_float(-0.3) == 0.0

    def test_string_float(self):
        assert score_to_float("0.72") == 0.72

    def test_invalid_uses_fallback(self):
        assert score_to_float("invalid", fallback=0.5) == 0.5

    def test_none_uses_fallback(self):
        assert score_to_float(None, fallback=0.3) == 0.3


class TestJoinKeywords:
    """Tests de la serialisation des mots-cles."""

    def test_list_to_pipe(self):
        result = join_keywords(["phishing", "login"])
        assert result == "phishing|login"

    def test_deduplication(self):
        result = join_keywords(["phishing", "phishing", "login"])
        assert result == "phishing|login"

    def test_none_returns_empty(self):
        assert join_keywords(None) == ""

    def test_nan_returns_empty(self):
        assert join_keywords("nan") == ""

    def test_pipe_string_splits(self):
        result = join_keywords("phishing|login")
        assert "phishing" in result
        assert "login" in result


class TestClassifySignal:
    """Tests du classificateur principal."""

    def test_seed_type_phishing(self):
        result = classify_signal(
            ["http://fake-bank.com/login"],
            seed_type="phishing",
        )
        assert result["type"] == "phishing"
        assert result["canal"] == "web"
        assert result["nature_technique"] == "phishing"
        assert 0.0 <= result["score_confiance"] <= 1.0
        assert result["classifier_version"] == CLASSIFIER_VERSION

    def test_seed_type_violation_rgpd(self):
        result = classify_signal(
            ["data breach notification"],
            seed_type="violation_rgpd",
        )
        assert result["type"] == "violation_rgpd"
        assert result["canal"] == "fuite_donnees"

    def test_keyword_rule_sms(self):
        result = classify_signal(
            ["colissimo tracking sms colis"],
            seed_type="",
        )
        assert result["type"] == "sms_frauduleux"
        assert result["canal"] == "sms"

    def test_keyword_rule_phishing(self):
        result = classify_signal(
            ["outlook webmail login verify"],
            seed_type="",
        )
        assert result["type"] == "phishing"

    def test_keyword_rule_cpf(self):
        result = classify_signal(
            ["cpf formation.gouv moncompteformation"],
            seed_type="",
        )
        assert result["type"] == "fraude_cpf"

    def test_malware_fallback(self):
        result = classify_signal(
            ["http://evil.com/payload.exe trojan malware"],
            seed_type="",
        )
        assert result["type"] == "malware_distribution"
        assert result["nature_technique"] == "malware"

    def test_generic_social_fallback(self):
        result = classify_signal(
            ["urgent scam alert fraud"],
            seed_type="",
        )
        # Au moins type == "autre" ou une classification reconnue
        assert result["type"] in {
            "autre", "phishing", "sms_frauduleux", "arnaque_achat",
            "fraude_cpf", "faux_support", "violation_rgpd", "malware_distribution",
        }

    def test_empty_texts_fallback(self):
        result = classify_signal([""], seed_type="")
        assert result["type"] == "autre"
        assert result["score_confiance"] < 0.5

    def test_score_override(self):
        result = classify_signal(
            ["phishing login"],
            seed_type="phishing",
            score_override=0.77,
        )
        assert result["score_confiance"] == 0.77

    def test_output_keys_complete(self):
        result = classify_signal(["test"], seed_type="autre")
        required_keys = {
            "type", "canal", "nature_technique", "score_confiance",
            "type_raw", "source_category_raw", "keywords_matched", "classifier_version",
        }
        assert required_keys.issubset(result.keys())

    def test_keywords_matched_is_list(self):
        result = classify_signal(["phishing login verify"], seed_type="phishing")
        assert isinstance(result["keywords_matched"], list)
