# ArnaqueRadar

> Pipeline de détection et d'analyse des arnaques numériques en France.
> Collecte automatique depuis 5 sources hétérogènes, normalisation des données,
> stockage PostgreSQL et exposition via une API REST sécurisée JWT.

![Compétences couvertes](https://img.shields.io/badge/Compétences%20couvertes-C1%20%7C%20C2%20%7C%20C3%20%7C%20C4%20%7C%20C5-blue)
![Python](https://img.shields.io/badge/Python-3.11+-green)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-336791)
![Docker](https://img.shields.io/badge/Docker-Compose%20v2-2496ED)

---

## Documentation

- [Guide d'installation](docs/installation.md)
- [Registre RGPD](docs/rgpd_registre.md)
- Documentation API interactive : `http://localhost:8000/docs` (après démarrage)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        PIPELINE ARNAQUERADAR                    │
└─────────────────────────────────────────────────────────────────┘

   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
   │ URLhaus API  │  │ MalwareTips  │  │   CNIL CSV   │
   │ (Feeds+API)  │  │  (Scraping)  │  │  (Open Data) │
   └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
          │                 │                  │
   ┌──────┴───────┐  ┌──────┴───────┐
   │  PostgreSQL  │  │  Apache Hive │
   │  Historique  │  │  (Big Data)  │
   └──────┬───────┘  └──────┬───────┘
          │                 │
          └────────┬────────┘
                   │
          ┌────────▼────────┐
          │ pipeline/collect│   ← C1 : Collecte multi-sources
          │ /1_collecter.py │
          └────────┬────────┘
                   │  raw_YYYYMMDD_HHMMSS.json
          ┌────────▼────────┐
          │ 2 → 4 pipeline  │   ← C2 : Nettoyage / Enrichissement / Qualité
          │ (nettoyer,      │
          │ enrichir, QA)   │
          └────────┬────────┘
          │  clean_dataset.csv
          ┌────────▼────────┐
          │ pipeline/databas│   ← C3 : Stockage PostgreSQL consolidé
          │ e/5_importer.py │
          └────────┬────────┘
                   │
          ┌────────▼────────┐
          │   FastAPI       │   ← C4 : API REST sécurisée (JWT)
          │   api/main.py   │
          └────────┬────────┘
                   │
          ┌────────▼────────┐
          │  pytest tests/  │   ← C5 : Tests d'intégration
          └─────────────────┘

  Stockage Big Data : Apache Hive (HiveServer2) + Hue
  Base relationnelle : PostgreSQL 15
  Sécurité : JWT Bearer / OWASP headers / Validation Pydantic
  RGPD : Registre → docs/rgpd_registre.md
```

---

## Compétences couvertes

| Code | Compétence | Fichiers principaux |
|---|---|---|
| **C1** | Collecter des données depuis sources hétérogènes | `pipeline/collect/1_collecter.py`, `pipeline/collect/sources/` |
| **C2** | Nettoyer, enrichir et contrôler la qualité | `pipeline/aggregate/2_nettoyer.py`, `pipeline/aggregate/3_enrichir.py`, `pipeline/aggregate/4_controler_qualite.py`, `pipeline/aggregate/aggregate.py` |
| **C3** | Stocker les données consolidées et les evidences en base | `pipeline/database/5_importer.py`, `pipeline/database/models.py`, `pipeline/database/import_data.py`, `pipeline/database/migrations/` |
| **C4** | Exposer les données via une API REST sécurisée | `api/main.py`, `api/auth.py`, `api/schemas.py` |
| **C5** | Tester et valider le pipeline | `tests/`, `pipeline/7_pipeline_complet.py` |

---

## Modèle de données

Le stockage PostgreSQL distingue maintenant deux grains complémentaires :

- `signalements` : une ligne consolidée par couple `(url, date_signalement)`
- `signalement_sources` : les evidences source par source qui corroborent un signalement

Cette séparation permet :

- de garder une API simple côté consultation
- de ne plus perdre la provenance multi-sources
- d'alimenter un reporting et un futur machine learning avec les preuves détaillées

---

## Démarrage rapide

```bash
# 1. Cloner et installer
git clone https://github.com/votre-compte/arnaqueradar.git && cd arnaqueradar
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Configurer
cp .env.example .env  # Éditer SECRET_KEY et ADMIN_PASSWORD

# 3. Démarrer Hive
docker compose up -d

# 4. Initialiser la base PostgreSQL locale
psql postgresql://postgres:VOTRE_MOT_DE_PASSE@localhost/arnaqueradar -f pipeline/database/migrations/001_init.sql
psql postgresql://postgres:VOTRE_MOT_DE_PASSE@localhost/arnaqueradar -f pipeline/database/migrations/002_align_runtime_schema.sql

# 5. Charger Hive avec PhishStats (une fois, ou à la demande)
python -m collect.bootstrap_hive_phishstats --target 50000

# 6. Exécuter le pipeline complet
python pipeline/7_pipeline_complet.py

# 7. Lancer l'API
uvicorn api.main:app --reload --port 8000

# 8. Tester
pytest tests/ -v
```

---

## Technologies utilisées

- **Python 3.11** — langage principal
- **FastAPI + Uvicorn** — API REST asynchrone
- **SQLAlchemy 2** — ORM PostgreSQL
- **psycopg2** — connecteur PostgreSQL bas niveau
- **pyhive** — connecteur Apache Hive
- **pandas** — traitement et nettoyage des données
- **BeautifulSoup4** — scraping HTML
- **python-jose** — JWT / authentification
- **Docker Compose** — infrastructure locale (Hive, metastore, Hue)
- **pytest + httpx** — tests d'intégration
