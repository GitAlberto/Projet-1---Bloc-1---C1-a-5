"""
Source 3: CNIL Open Data - collecte depuis un fichier CSV.

Ce module lit le fichier de violations RGPD reference par la CNIL.
Si le fichier local est absent, il le telecharge depuis data.gouv.fr.
S'il existe deja mais devient trop ancien, il tente un rafraichissement
automatique. En dernier recours, il genere un fichier de demonstration local
afin de ne jamais interrompre le pipeline.

Le fichier local peut etre un CSV UTF-8 interne au projet ou un export CNIL
avec une ligne de preambule et un encodage Windows-1252.
"""

import logging
import os
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[3] / "data_CNIL"
CSV_PATH = DATA_DIR / "cnil_violations.csv"
DATAGOUV_URL = (
    "https://www.data.gouv.fr/api/1/datasets/r/"
    "4c176588-a444-4dc7-b6bf-60390ae7e5be"
)
DEFAULT_MAX_AGE_DAYS = 30
DEMO_URL_PREFIX = "https://banque-alpha.fr/incident-1"
DEMO_ORG_PREFIX = "Organisation_"
ENCODING_CANDIDATES = ("utf-8", "utf-8-sig", "cp1252", "latin-1")
REAL_EXPORT_PREFIX = "Extraction générée"


def _create_demo_csv() -> None:
    """
    Genere un fichier CSV de demonstration simulant des violations RGPD.

    Ce fichier est cree uniquement si le fichier reel est introuvable et que
    le telechargement depuis data.gouv.fr a egalement echoue. Il permet de
    garantir la continuite du pipeline en environnement de developpement.
    """
    base_date = date.today()
    rows = []
    domains = [
        "banque-alpha.fr",
        "assurance-beta.fr",
        "ecommerce-gamma.fr",
        "cabinet-medecin-delta.fr",
        "mutuelle-epsilon.fr",
        "telecom-zeta.fr",
        "mairie-eta.fr",
        "hopital-theta.fr",
    ]
    types_violation = [
        "Acces non autorise",
        "Perte de donnees",
        "Divulgation non intentionnelle",
        "Ransomware",
        "Phishing interne",
    ]
    for i in range(25):
        current_date = base_date - timedelta(days=i * 12)
        rows.append(
            {
                "url": f"https://{domains[i % len(domains)]}/incident-{i + 1}",
                "organisation": f"Organisation_{i + 1}",
                "type_violation": types_violation[i % len(types_violation)],
                "date_notification": current_date.isoformat(),
                "nombre_personnes_concernees": (i + 1) * 150,
                "region": "Ile-de-France" if i % 3 == 0 else "Auvergne-Rhone-Alpes",
            }
        )
    df = pd.DataFrame(rows)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(CSV_PATH, index=False, sep=";", encoding="utf-8")
    logger.info("CNIL CSV : fichier de demonstration cree (%d lignes).", len(rows))


def _download_from_datagouv() -> bool:
    """
    Tente de telecharger le fichier CNIL depuis data.gouv.fr.

    Retourne :
        bool : True si le telechargement a reussi, False sinon.
    """
    try:
        import requests

        response = requests.get(
            DATAGOUV_URL,
            timeout=30,
            headers={"User-Agent": "ArnaqueRadar/1.0"},
        )
        response.raise_for_status()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CSV_PATH.write_bytes(response.content)
        logger.info("CNIL CSV : fichier telecharge depuis data.gouv.fr.")
        return True
    except Exception as exc:
        logger.warning("CNIL CSV : telechargement data.gouv.fr echoue - %s", exc)
        return False


def _resolve_csv_path() -> Path:
    """
    Retourne le meilleur fichier CSV CNIL disponible localement.

    Si le nom canonique n'existe pas, on reutilise la variante la plus recente
    du type cnil_violations_1.csv.
    """
    if CSV_PATH.exists():
        return CSV_PATH

    candidates = sorted(
        DATA_DIR.glob("cnil_violations*.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return candidates[0]

    return CSV_PATH


def _max_file_age_days() -> int:
    """Retourne l'age maximal autorise du CSV local avant rafraichissement."""
    raw_value = str(os.getenv("CNIL_MAX_AGE_DAYS", DEFAULT_MAX_AGE_DAYS)).strip()
    try:
        age_days = int(raw_value)
    except ValueError:
        return DEFAULT_MAX_AGE_DAYS
    return max(age_days, 0)


def _is_file_stale(path: Path) -> bool:
    """Indique si le fichier local est plus ancien que le seuil configure."""
    if not path.exists():
        return True

    max_age_days = _max_file_age_days()
    modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    age = datetime.now(timezone.utc) - modified_at
    return age > timedelta(days=max_age_days)


def _is_demo_csv(path: Path) -> bool:
    """Detecte si le fichier local ressemble au CSV de demonstration interne."""
    if not path.exists():
        return False

    try:
        preview = _read_csv_with_fallbacks(path, nrows=3)
    except Exception:
        return False

    if preview.empty:
        return False

    first_url = str(preview.iloc[0].get("url", "")).strip()
    first_org = str(preview.iloc[0].get("organisation", "")).strip()
    return first_url.startswith(DEMO_URL_PREFIX) and first_org.startswith(DEMO_ORG_PREFIX)


def _load_csv() -> pd.DataFrame:
    """
    Charge le CSV CNIL avec pandas en gerant l'encodage et le separateur.

    Retourne :
        pd.DataFrame : donnees brutes du fichier CSV.

    Leve :
        Exception : si le fichier est illisible ou mal formate.
    """
    csv_path = _resolve_csv_path()
    return _read_csv_with_fallbacks(csv_path)


def _read_csv_with_fallbacks(path: Path, nrows: int | None = None) -> pd.DataFrame:
    """
    Lit le CSV CNIL en essayant plusieurs encodages et positions d'en-tete.
    """
    last_error: Exception | None = None

    for encoding in ENCODING_CANDIDATES:
        for skiprows in (0, 1):
            try:
                df = pd.read_csv(
                    path,
                    sep=";",
                    encoding=encoding,
                    skiprows=skiprows,
                    nrows=nrows,
                    on_bad_lines="skip",
                )
                df.columns = [_clean_column_name(column) for column in df.columns]

                if df.empty and skiprows == 1:
                    continue

                first_column = str(df.columns[0]).strip() if len(df.columns) else ""
                if skiprows == 0 and first_column.startswith(REAL_EXPORT_PREFIX):
                    continue

                return df
            except Exception as exc:
                last_error = exc

    if last_error is None:
        raise ValueError(f"Impossible de lire le CSV CNIL: {path}")
    raise last_error


def _clean_column_name(column_name: Any) -> str:
    """
    Supprime les espaces parasites et les espaces insécables des en-tetes.
    """
    return str(column_name).replace("\xa0", " ").strip()


def _slugify(value: Any) -> str:
    """
    Genere un slug ASCII stable pour construire une URL synthetique.
    """
    text = unicodedata.normalize("NFKD", str(value))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return text or "incident"


def _normalize_notification_date(value: Any) -> str:
    """
    Normalise une date CNIL vers le format ISO YYYY-MM-DD.
    """
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return date.today().isoformat()

    if re.fullmatch(r"\d{4}-\d{2}", text):
        return f"{text}-01"

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text

    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return date.today().isoformat()

    return parsed.date().isoformat()


def _normalize_dataframe(df: pd.DataFrame) -> list[dict[str, Any]]:
    """
    Renomme les colonnes du DataFrame vers le schema normalise.

    Parametres :
        df (pd.DataFrame) : donnees brutes chargees depuis le CSV.

    Retourne :
        list[dict] : liste des entrees normalisees.
    """
    column_mapping = {
        "url": "url",
        "date_notification": "date_signalement",
        "type_violation": "titre",
        "region": "region",
        "Date de réception de la notification": "date_signalement",
        "Secteur d'activité de l'organisme concerné": "organisation",
        "Natures de la violation": "titre",
    }
    available = {k: v for k, v in column_mapping.items() if k in df.columns}
    df_norm = df.rename(columns=available)

    if "url" not in df_norm.columns:
        if "organisation" in df_norm.columns:
            df_norm["url"] = [
                (
                    f"https://cnil.local/violations/"
                    f"{_slugify(df_norm.iloc[idx].get('organisation', 'incident'))}-"
                    f"{_normalize_notification_date(df_norm.iloc[idx].get('date_signalement', ''))}-"
                    f"{idx + 1}"
                )
                for idx in range(len(df_norm))
            ]
        else:
            df_norm["url"] = "https://example.cnil.fr/incident-inconnu"

    if "date_signalement" not in df_norm.columns:
        df_norm["date_signalement"] = date.today().isoformat()
    else:
        df_norm["date_signalement"] = df_norm["date_signalement"].apply(_normalize_notification_date)

    df_norm["type"] = "violation_rgpd"
    df_norm["source"] = "cnil_csv"
    df_norm["titre"] = df_norm.get("titre", pd.Series(["Violation RGPD"] * len(df_norm)))

    fields = ["url", "type", "source", "date_signalement", "titre"]
    for field in fields:
        if field not in df_norm.columns:
            df_norm[field] = ""

    return df_norm[fields].to_dict(orient="records")


def collect_cnil_csv() -> list[dict[str, Any]]:
    """
    Collecte les violations RGPD depuis le CSV de la CNIL.

    Strategie :
    1. Telecharger le fichier s'il est absent.
    2. Tenter un rafraichissement s'il existe mais est trop ancien.
    3. Conserver le fichier local si le rafraichissement echoue.
    4. Generer un CSV de demonstration en dernier recours si aucun fichier
       exploitable n'est disponible.

    Retourne :
        list[dict] : liste des entrees normalisees, ou liste vide si toutes
                     les tentatives echouent.
    """
    csv_path = _resolve_csv_path()
    file_exists = csv_path.exists()
    if not file_exists:
        logger.info("CNIL CSV : fichier local absent, tentative de telechargement.")
        if not _download_from_datagouv():
            logger.warning("CNIL CSV : generation du fichier de demonstration.")
            _create_demo_csv()
            csv_path = _resolve_csv_path()
    elif _is_demo_csv(csv_path):
        logger.warning(
            "CNIL CSV : fichier local de demonstration detecte, tentative de telechargement du vrai dataset."
        )
        if not _download_from_datagouv():
            logger.warning(
                "CNIL CSV : telechargement impossible, conservation temporaire du fichier de demonstration."
            )
        csv_path = _resolve_csv_path()
    elif _is_file_stale(csv_path):
        logger.info(
            "CNIL CSV : fichier local ancien (%s), tentative de rafraichissement.",
            csv_path,
        )
        if not _download_from_datagouv():
            logger.warning("CNIL CSV : rafraichissement impossible, conservation du fichier local.")
        csv_path = _resolve_csv_path()
    else:
        logger.info("CNIL CSV : fichier local recent conserve (%s).", csv_path)

    try:
        df = _load_csv()
        results = _normalize_dataframe(df)
        logger.info("CNIL CSV : %d violations chargees.", len(results))
        return results
    except Exception as exc:
        logger.error("CNIL CSV : impossible de charger le fichier - %s", exc)
        return []
