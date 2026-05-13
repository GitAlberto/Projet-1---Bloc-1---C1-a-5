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
   │ Google Web   │  │Cybermalveil. │  │   CNIL CSV   │
   │ Risk (API)   │  │  (Scraping)  │  │  (Fichier)   │
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
          │  collect.py     │   ← C1 : Collecte multi-sources
          │  (Orchestrateur)│
          └────────┬────────┘
                   │  raw_YYYYMMDD_HHMMSS.json
          ┌────────▼────────┐
          │  aggregate.py   │   ← C2 : Nettoyage / Normalisation
          │  (8 étapes)     │
          └────────┬────────┘
                   │  clean_dataset.csv
          ┌────────▼────────┐
          │  import_data.py │   ← C3 : Stockage PostgreSQL
          │  (psycopg2)     │
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

  Stockage Big Data : Apache Hive (HiveServer2)
  Base relationnelle : PostgreSQL 15 (Docker)
  Sécurité : JWT Bearer / OWASP headers / Validation Pydantic
  RGPD : Registre → docs/rgpd_registre.md
```

---

## Compétences couvertes

| Code | Compétence | Fichiers principaux |
|---|---|---|
| **C1** | Collecter des données depuis sources hétérogènes | `collect/collect.py`, `collect/sources/` |
| **C2** | Nettoyer et normaliser les données | `aggregate/aggregate.py` |
| **C3** | Stocker les données en base relationnelle | `database/models.py`, `database/import_data.py`, `database/migrations/` |
| **C4** | Exposer les données via une API REST sécurisée | `api/main.py`, `api/auth.py`, `api/schemas.py` |
| **C5** | Tester et valider le pipeline | `tests/test_api.py` |

---

## Démarrage rapide

```bash
# 1. Cloner et installer
git clone https://github.com/votre-compte/arnaqueradar.git && cd arnaqueradar
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Configurer
cp .env.example .env  # Éditer SECRET_KEY et ADMIN_PASSWORD

# 3. Démarrer PostgreSQL
docker compose up -d

# 4. Initialiser la base
psql postgresql://postgres:Mot%20de%20passe@localhost:5433/arnaqueradar -f database/migrations/001_init.sql

# 5. Exécuter le pipeline complet
python collect/collect.py
python aggregate/aggregate.py
python database/import_data.py

# 6. Lancer l'API
uvicorn api.main:app --reload --port 8000

# 7. Tester
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
- **Docker Compose** — infrastructure locale (PostgreSQL + Hive)
- **pytest + httpx** — tests d'intégration
