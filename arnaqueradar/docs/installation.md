# Guide d'installation - ArnaqueRadar

## Prerequis systeme

| Composant | Version minimale | Verification |
|---|---|---|
| Python | 3.11+ | `python --version` |
| pgAdmin4 + PostgreSQL | PostgreSQL 15+ | via pgAdmin4 |
| Docker | 24+ | `docker --version` |
| Docker Compose | v2 | `docker compose version` |
| Git | 2.40+ | `git --version` |

---

## 1. Cloner le depot

```bash
git clone https://github.com/votre-compte/arnaqueradar.git
cd arnaqueradar
```

---

## 2. Installer les dependances Python

```bash
python -m venv venv
# Linux / macOS
source venv/bin/activate
# Windows
venv\Scripts\activate

pip install -r requirements.txt
```

---

## 3. Creer la base PostgreSQL via pgAdmin4

1. Ouvrez pgAdmin4.
2. Clic droit sur `Databases` -> `Create` -> `Database...`
3. Nom : `arnaqueradar`
4. Proprietaire : votre utilisateur PostgreSQL, souvent `postgres`

---

## 4. Configurer `.env`

```bash
cp .env.example .env
```

Exemple minimal a verifier :

```env
PG_HOST=localhost
PG_PORT=5432
PG_DB=arnaqueradar
PG_USER=postgres
PG_PASSWORD=VOTRE_MOT_DE_PASSE

HIVE_HOST=localhost
HIVE_PORT=10000
HIVE_USER=hive
HIVE_DB=default
HIVE_AUTH=NOSASL
HIVE_QUERY_MODE=rows
HIVE_FILTER_CURRENT_YEAR=false

URLHAUS_AUTH_KEY=VOTRE_AUTH_KEY_URLHAUS
CNIL_MAX_AGE_DAYS=30

DATABASE_URL=postgresql://postgres:VOTRE_MOT_DE_PASSE@localhost/arnaqueradar
SECRET_KEY=...
ADMIN_USERNAME=admin
ADMIN_PASSWORD=arnaqueradar2024
```

Ne committez jamais le vrai fichier `.env`.

---

## 5. Initialiser le schema PostgreSQL

### Option A - pgAdmin4

1. Ouvrez le `Query Tool` sur la base `arnaqueradar`.
2. Executez `pipeline/database/migrations/001_init.sql`.
3. Si votre base existe deja depuis une ancienne version, executez aussi `pipeline/database/migrations/002_align_runtime_schema.sql`.

### Option B - ligne de commande

```bash
psql postgresql://postgres:VOTRE_MOT_DE_PASSE@localhost/arnaqueradar -f pipeline/database/migrations/001_init.sql
psql postgresql://postgres:VOTRE_MOT_DE_PASSE@localhost/arnaqueradar -f pipeline/database/migrations/002_align_runtime_schema.sql
```

---

## 6. Demarrer Hive

```bash
docker compose up -d
```

Ensuite :

- HiveServer2 ecoute sur `localhost:10000`
- l'interface web HiveServer2 est disponible sur `http://localhost:10002`

### Hue

Hue demarre avec la commande Compose standard et sera disponible sur
`http://localhost:8888`.

---

## 7. Charger Hive avec PhishStats

La source 5 lit strictement Hive. Le chargement PhishStats -> Hive se fait donc a part :

```bash
python -m collect.bootstrap_hive_phishstats --target 50000
```

Cette commande :

- telecharge des lignes reelles PhishStats
- cree `logs_arnaques` si besoin
- recharge Hive par lots

Le premier bootstrap peut etre long a cause du rate limiting PhishStats.

---

## 8. Lancer le pipeline

Version pedagogique, etape par etape :

```bash
python pipeline/collect/1_collecter.py
python pipeline/aggregate/2_nettoyer.py
python pipeline/aggregate/3_enrichir.py
python pipeline/aggregate/4_controler_qualite.py
python pipeline/database/5_importer.py
python pipeline/ml/6_preparer_dataset_ml.py
```

Version complete :

```bash
python pipeline/7_pipeline_complet.py
```

Version historique compatible :

```bash
python pipeline/collect/1_collecter.py
```

---

## 9. Agreger et importer

```bash
python -m pipeline.aggregate.aggregate
python -m pipeline.database.import_data
```

---

## 10. Lancer l'API

```bash
uvicorn api.main:app --reload --port 8000
```

L'API est ensuite disponible sur `http://localhost:8000`.
