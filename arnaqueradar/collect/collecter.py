"""
Point d'entree principal du pipeline de collecte ArnaqueRadar (C1).

Ce module orchestre la collecte multi-sources en appelant successivement
les 5 connecteurs (URLhaus API, MalwareTips, CNIL CSV, PostgreSQL,
Hive). Chaque source est executee dans un bloc try/except independant :
une source defaillante n'interrompt pas les autres.

Le resultat brut est sauvegarde dans data/raw_YYYYMMDD_HHMMSS.json
avec horodatage, puis le total collecte est journalise.

Usage direct : python collect/collecter.py
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Resolution des chemins relatifs au projet, quel que soit le repertoire d'appel
PROJECT_ROOT = Path(__file__).resolve().parents[1] # parent[0] est collect, parent[1] est arnaqueradar
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(
    level=logging.INFO, # logging.INFO, logging.DEBUG, logging.WARNING, logging.ERROR, logging.CRITICAL
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s", # %(asctime)s : date et heure
    datefmt="%Y-%m-%d %H:%M:%S", # format de date et heure
)
logger = logging.getLogger("collect")

DATA_DIR = PROJECT_ROOT / "data" # dossier data


# Fonctions utilitaires - sauvegarde des donnees
def _save_raw_data(entries: list[dict]) -> Path:
    """
    Sauvegarde les donnees brutes collectees dans un fichier JSON horodate.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True) # parents=True : creer les dossiers parents si besoin, exist_ok=True : ne pas lever d'erreur si le dossier existe deja
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") # horodatage actuel
    output_path = DATA_DIR / f"raw_{timestamp}.json" # fichier JSON avec horodatage
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(entries, handle, ensure_ascii=False, indent=2) # indent=2 pour formater le JSON avec indentation
    logger.info("Donnees brutes sauvegardees dans : %s", output_path)
    return output_path

# Fonction principale - orchestration de la collecte
def run_collection() -> list[dict]:
    """
    Orchestre la collecte depuis les 5 sources heterogenes selon les criteres definis dans le cahier des charges.
    """
    logger.info("=" * 60) # affiche 60 signes =
    logger.info("Demarrage du pipeline de collecte ArnaqueRadar") # affiche le message de demarrage
    logger.info("=" * 60) # affiche 60 signes =

    all_entries: list[dict] = [] # liste pour stocker toutes les entrees, chaque entree est un dictionnaire.

    # ---- Source 1 : URLhaus (feeds historiques + API recent en secours) ----
    try:
        from collect.sources.urlhaus import collect_urlhaus

        urlhaus_data = collect_urlhaus()
        logger.info("Source 1 [URLhaus] : %d entrees collectees.", len(urlhaus_data))
        all_entries.extend(urlhaus_data)
    except Exception as exc: # en cas d'erreur, affiche un message d'erreur
        logger.error("Source 1 [URLhaus] : echec inattendu - %s", exc)

    # ---- Source 2 : MalwareTips (scraping HTML plafonne a 10k) ----
    try:
        from collect.sources.malwaretips import collect_malwaretips

        malwaretips_data = collect_malwaretips()
        logger.info("Source 2 [MalwareTips] : %d entrees collectees.", len(malwaretips_data))
        all_entries.extend(malwaretips_data)
    except Exception as exc: # en cas d'erreur, affiche un message d'erreur
        logger.error("Source 2 [MalwareTips] : echec inattendu - %s", exc)

    # ---- Source 3 : CNIL CSV ----
    try:
        from collect.sources.cnil_csv import collect_cnil_csv # import de la fonction collect_cnil_csv

        cnil_data = collect_cnil_csv() # appel de la fonction collect_cnil_csv
        logger.info("Source 3 [CNIL CSV] : %d entrees collectees.", len(cnil_data)) # affiche le nombre d'entrees collectees
        all_entries.extend(cnil_data) # ajoute les entrees collectees a la liste all_entries
    except Exception as exc: # en cas d'erreur, affiche un message d'erreur
        logger.error("Source 3 [CNIL CSV] : echec inattendu - %s", exc)

    # ---- Source 4 : PostgreSQL historique ----
    try:
        from collect.sources.pg_history import collect_pg_history

        pg_data = collect_pg_history()
        logger.info("Source 4 [PostgreSQL] : %d entrees collectees.", len(pg_data))
        all_entries.extend(pg_data)
    except Exception as exc:
        logger.error("Source 4 [PostgreSQL] : echec inattendu - %s", exc)

    # ---- Source 5 : Hive Big Data (bootstrap PhishStats 50k) ----
    try:
        from collect.sources.hive_logs import collect_hive_logs

        hive_data = collect_hive_logs()
        logger.info("Source 5 [Hive] : %d entrees collectees.", len(hive_data))
        all_entries.extend(hive_data)
    except Exception as exc:
        logger.error("Source 5 [Hive] : echec inattendu - %s", exc)

    logger.info("=" * 60)
    logger.info("TOTAL collecte : %d entrees toutes sources confondues.", len(all_entries))
    logger.info("=" * 60)

    _save_raw_data(all_entries)
    return all_entries


if __name__ == "__main__":
    results = run_collection()
    print(f"\nCollecte terminee : {len(results)} entrees sauvegardees.")
