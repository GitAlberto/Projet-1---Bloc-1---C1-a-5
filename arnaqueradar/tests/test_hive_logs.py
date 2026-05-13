"""
Tests unitaires du connecteur Hive.

Valide la configuration NOSASL, l'initialisation de la table et le
fallback simule si Hive est indisponible.
"""

import sys
from pathlib import Path

# Ajout de la racine du projet au path pour les imports
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from collect.sources import hive_logs


def test_get_connection_params_defaults_to_nosasl(monkeypatch):
    """La connexion locale doit utiliser NOSASL par defaut."""
    monkeypatch.delenv("HIVE_AUTH", raising=False)

    params = hive_logs._get_connection_params()

    assert params["auth"] == "NOSASL"
    assert params["database"] == "default"
    assert params["username"] == "hive"


def test_ensure_table_ready_seeds_empty_table():
    """Une table vide doit etre initialisee avec les donnees de demonstration."""

    class _Cursor:
        def __init__(self):
            self.executed = []
            self._fetchone = (0,)

        def execute(self, query):
            self.executed.append(" ".join(query.split()))
            if "SELECT COUNT(*)" in query:
                self._fetchone = (0,)

        def fetchone(self):
            return self._fetchone

    cursor = _Cursor()

    hive_logs._ensure_table_ready(cursor)

    assert any("CREATE TABLE IF NOT EXISTS logs_arnaques" in query for query in cursor.executed)
    assert any("INSERT INTO TABLE logs_arnaques" in query for query in cursor.executed)


def test_select_query_for_table_prefers_count_column():
    """Le connecteur doit sommer nb_signalements si la colonne existe."""

    class _Cursor:
        def execute(self, query):
            self.query = query

        def fetchall(self):
            return [
                ("url_pattern", "string", ""),
                ("type_arnaque", "string", ""),
                ("region", "string", ""),
                ("event_date", "date", ""),
                ("nb_signalements", "int", ""),
            ]

    cursor = _Cursor()

    query = hive_logs._select_query_for_table(cursor)

    assert "SUM(COALESCE(nb_signalements, 1))" in query


def test_collect_hive_logs_uses_simulated_fallback_when_hive_import_fails(monkeypatch):
    """Si pyhive est indisponible, le fallback simule doit rester actif."""
    real_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "pyhive":
            raise ModuleNotFoundError("pyhive")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)

    results = hive_logs.collect_hive_logs()

    assert len(results) == len(hive_logs.SIMULATED_ENTRIES)
    assert all(entry["source"] == "hive_logs" for entry in results)
