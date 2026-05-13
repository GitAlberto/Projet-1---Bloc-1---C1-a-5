"""
Tests unitaires du connecteur CNIL CSV.

Valide la logique de rafraichissement conditionnel du fichier local
avant lecture et normalisation.
"""

import sys
from pathlib import Path
import shutil
import uuid

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from collect.sources import cnil_csv


def _make_workspace_dir() -> Path:
    """Cree un dossier de test local dans le workspace."""
    path = PROJECT_ROOT / "tests" / "fixtures" / f"cnil_runtime_{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_minimal_cnil_csv(path: Path) -> None:
    """Ecrit un fichier CNIL minimal exploitable par le connecteur."""
    path.write_text(
        "url;type_violation;date_notification;region\n"
        "https://cnil.test/incident-1;Acces non autorise;2026-05-01;Ile-de-France\n",
        encoding="utf-8",
    )


def _write_real_export_cnil_csv(path: Path) -> None:
    """Ecrit un extrait representatif de l'export CNIL reel."""
    path.write_text(
        "Extraction générée le 2 décembre 2025;;;;;;;\n"
        "Date de réception de la notification\xa0;"
        "Secteur d'activité de l'organisme concerné;"
        "Natures de la violation;"
        "Nombre de personnes impactées;"
        "Typologies des données impactées;"
        "Données sensibles;"
        "Origines de l'incident;"
        "Causes de l'incident;"
        "Information des personnes\n"
        "2025-09;"
        "Activités spécialisées, scientifiques et techniques;"
        "Perte de la confidentialité;"
        "Entre 0 et 5 personnes;"
        "Coordonnées;"
        ";"
        "Données personnelles envoyées à un mauvais destinataire;"
        "Acte interne accidentel;"
        "Non ils ne le seront pas\n",
        encoding="cp1252",
    )


def test_is_file_stale_respects_max_age_days(monkeypatch):
    """Un fichier recent ne doit pas etre marque comme ancien."""
    work_dir = _make_workspace_dir()
    try:
        csv_path = work_dir / "cnil_violations.csv"
        _write_minimal_cnil_csv(csv_path)
        monkeypatch.setenv("CNIL_MAX_AGE_DAYS", "30")

        assert cnil_csv._is_file_stale(csv_path) is False
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def test_collect_cnil_csv_skips_download_when_file_is_recent(monkeypatch):
    """Le telechargement ne doit pas etre tente si le fichier local est recent."""
    work_dir = _make_workspace_dir()
    try:
        csv_path = work_dir / "cnil_violations.csv"
        _write_minimal_cnil_csv(csv_path)

        monkeypatch.setattr(cnil_csv, "CSV_PATH", csv_path)
        monkeypatch.setattr(cnil_csv, "DATA_DIR", work_dir)
        monkeypatch.setattr(cnil_csv, "_is_file_stale", lambda path: False)

        def fail_download():
            raise AssertionError("Le telechargement ne devait pas etre appele.")

        monkeypatch.setattr(cnil_csv, "_download_from_datagouv", fail_download)

        results = cnil_csv.collect_cnil_csv()

        assert len(results) == 1
        assert results[0]["source"] == "cnil_csv"
        assert results[0]["type"] == "violation_rgpd"
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def test_collect_cnil_csv_keeps_local_file_if_refresh_fails(monkeypatch):
    """Un fichier local ancien doit rester utilisable si le refresh echoue."""
    work_dir = _make_workspace_dir()
    try:
        csv_path = work_dir / "cnil_violations.csv"
        _write_minimal_cnil_csv(csv_path)

        monkeypatch.setattr(cnil_csv, "CSV_PATH", csv_path)
        monkeypatch.setattr(cnil_csv, "DATA_DIR", work_dir)
        monkeypatch.setattr(cnil_csv, "_is_file_stale", lambda path: True)

        download_calls = {"count": 0}
        demo_calls = {"count": 0}

        def fake_download():
            download_calls["count"] += 1
            return False

        def fake_demo():
            demo_calls["count"] += 1

        monkeypatch.setattr(cnil_csv, "_download_from_datagouv", fake_download)
        monkeypatch.setattr(cnil_csv, "_create_demo_csv", fake_demo)

        results = cnil_csv.collect_cnil_csv()

        assert download_calls["count"] == 1
        assert demo_calls["count"] == 0
        assert len(results) == 1
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def test_is_demo_csv_detects_internal_seed_file(monkeypatch):
    """Le detecteur doit reconnaitre le CSV de demonstration genere par le projet."""
    work_dir = _make_workspace_dir()
    try:
        csv_path = work_dir / "cnil_violations.csv"
        monkeypatch.setattr(cnil_csv, "CSV_PATH", csv_path)
        monkeypatch.setattr(cnil_csv, "DATA_DIR", work_dir)
        cnil_csv._create_demo_csv()

        assert cnil_csv._is_demo_csv(csv_path) is True
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def test_collect_cnil_csv_refreshes_even_if_demo_file_is_recent(monkeypatch):
    """Un fichier de demonstration recent doit forcer une tentative de refresh."""
    work_dir = _make_workspace_dir()
    try:
        csv_path = work_dir / "cnil_violations.csv"
        csv_path.write_text(
            "url;organisation;type_violation;date_notification;nombre_personnes_concernees;region\n"
            "https://banque-alpha.fr/incident-1;Organisation_1;Acces non autorise;2026-05-13;150;Ile-de-France\n",
            encoding="utf-8",
        )

        monkeypatch.setattr(cnil_csv, "CSV_PATH", csv_path)
        monkeypatch.setattr(cnil_csv, "DATA_DIR", work_dir)
        monkeypatch.setattr(cnil_csv, "_is_file_stale", lambda path: False)

        download_calls = {"count": 0}

        def fake_download():
            download_calls["count"] += 1
            return False

        monkeypatch.setattr(cnil_csv, "_download_from_datagouv", fake_download)

        results = cnil_csv.collect_cnil_csv()

        assert download_calls["count"] == 1
        assert len(results) == 1
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def test_load_csv_supports_real_export_encoding_and_preamble(monkeypatch):
    """Le connecteur doit lire l'export CNIL CP1252 avec ligne de preambule."""
    work_dir = _make_workspace_dir()
    try:
        csv_path = work_dir / "cnil_violations_1.csv"
        _write_real_export_cnil_csv(csv_path)

        monkeypatch.setattr(cnil_csv, "CSV_PATH", work_dir / "cnil_violations.csv")
        monkeypatch.setattr(cnil_csv, "DATA_DIR", work_dir)

        df = cnil_csv._load_csv()

        assert len(df) == 1
        assert "Date de réception de la notification" in df.columns
        assert df.iloc[0]["Natures de la violation"] == "Perte de la confidentialité"
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def test_collect_cnil_csv_normalizes_real_export(monkeypatch):
    """Le collecteur doit normaliser correctement un export CNIL reel."""
    work_dir = _make_workspace_dir()
    try:
        csv_path = work_dir / "cnil_violations_1.csv"
        _write_real_export_cnil_csv(csv_path)

        monkeypatch.setattr(cnil_csv, "CSV_PATH", work_dir / "cnil_violations.csv")
        monkeypatch.setattr(cnil_csv, "DATA_DIR", work_dir)
        monkeypatch.setattr(cnil_csv, "_is_file_stale", lambda path: False)

        results = cnil_csv.collect_cnil_csv()

        assert len(results) == 1
        assert results[0]["source"] == "cnil_csv"
        assert results[0]["type"] == "violation_rgpd"
        assert results[0]["date_signalement"] == "2025-09-01"
        assert results[0]["titre"] == "Perte de la confidentialité"
        assert results[0]["url"].startswith("https://cnil.local/violations/")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
