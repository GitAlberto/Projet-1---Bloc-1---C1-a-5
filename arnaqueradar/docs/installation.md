# Guide d'installation — ArnaqueRadar

## Prérequis système

| Composant | Version minimale | Vérification |
|---|---|---|
| Python | 3.11+ | `python --version` |
| pgAdmin4 + PostgreSQL | PostgreSQL 15+ | via pgAdmin4 |
| Docker | 24+ | `docker --version` *(optionnel — uniquement pour Hive)* |
| Docker Compose | v2 | `docker compose version` *(optionnel)* |
| Git | 2.40+ | `git --version` |

---

## 1. Cloner le dépôt

```bash
git clone https://github.com/votre-compte/arnaqueradar.git
cd arnaqueradar
```

---

## 2. Installer les dépendances Python

Il est fortement recommandé d'utiliser un environnement virtuel :

```bash
python -m venv venv
# Linux / macOS
source venv/bin/activate
# Windows
venv\Scripts\activate

pip install -r requirements.txt
```

---

## 3. Créer la base de données via pgAdmin4

Ouvrez **pgAdmin4** et effectuez les étapes suivantes :

1. Dans l'arborescence, faites un clic droit sur **Databases** → **Create → Database…**
2. Nom de la base : `arnaqueradar`
3. Propriétaire : votre utilisateur PostgreSQL (souvent `postgres`)
4. Cliquez **Save**

> Si vous souhaitez créer un utilisateur dédié au projet :
> ```sql
> CREATE USER arnaqueradar_user WITH PASSWORD 'monmotdepasse';
> GRANT ALL PRIVILEGES ON DATABASE arnaqueradar TO arnaqueradar_user;
> ```

---

## 4. Configurer les variables d'environnement

```bash
cp .env.example .env
```

Ouvrez `.env` et renseignez :

```env
PG_HOST=localhost
PG_PORT=5432
PG_DB=arnaqueradar
PG_USER=postgres              # ou votre utilisateur pgAdmin4
PG_PASSWORD=VOTRE_MOT_DE_PASSE
URLHAUS_AUTH_KEY=VOTRE_AUTH_KEY_URLHAUS
URLHAUS_RECENT_LIMIT=100
CNIL_MAX_AGE_DAYS=30
DATABASE_URL=postgresql://postgres:VOTRE_MOT_DE_PASSE@localhost/arnaqueradar
SECRET_KEY=...                # générer avec : python -c "import secrets; print(secrets.token_hex(32))"
ADMIN_USERNAME=admin
ADMIN_PASSWORD=arnaqueradar2024
```

> `URLHAUS_AUTH_KEY` s'obtient gratuitement via le portail abuse.ch.
> La source 1 interroge ensuite l'API `recent URLs` et récupère les ajouts
> récents des 3 derniers jours, dans la limite définie par `URLHAUS_RECENT_LIMIT`.

> `CNIL_MAX_AGE_DAYS` definit au bout de combien de jours le fichier
> `data_CNIL/cnil_violations.csv` est considere comme ancien et doit
> etre retelecharge automatiquement.

> **Important** : ne committez jamais le fichier `.env`. Il est exclu par `.gitignore`.

---

## 5. Créer le schéma de base de données

### Option A — Via pgAdmin4 (recommandée)

1. Dans pgAdmin4, faites un clic droit sur la base `arnaqueradar` → **Query Tool**
2. Ouvrez le fichier `database/migrations/001_init.sql`
3. Exécutez-le (**F5** ou bouton ▶)

### Option B — Via ligne de commande

```bash
psql postgresql://postgres:VOTRE_MOT_DE_PASSE@localhost/arnaqueradar -f database/migrations/001_init.sql
```

Cette migration crée les tables, les index et insère les données de référence
(types d'arnaques, régions françaises, sources de collecte).

---

## 6. Démarrer Apache Hive (optionnel)

Hive est la source Big Data (Source 5). Le pipeline fonctionne **sans Hive** grâce
au fallback automatique (10 entrées simulées réalistes). Pour activer Hive réellement :

```bash
docker compose up -d
```

---

## 7. Collecter les données

```bash
python collect/collecter.py
```

Le pipeline interroge les 5 sources. Si Hive est indisponible, le fallback
s'active automatiquement. Un fichier `data/raw_YYYYMMDD_HHMMSS.json` est créé.

---

## 8. Agréger et nettoyer les données

```bash
python aggregate/aggregate.py
```

Applique le pipeline de nettoyage en 8 étapes sur le dernier `raw_*.json`
et produit `data/clean_dataset.csv`.

---

## 9. Importer les données en base

```bash
python database/import_data.py
```

Insère les lignes de `clean_dataset.csv` dans la table `signalements` de votre
PostgreSQL local. Les doublons sont ignorés (`ON CONFLICT DO NOTHING`).

---

## 10. Lancer l'API REST

```bash
uvicorn api.main:app --reload --port 8000
```

L'API est disponible sur `http://localhost:8000`.

---

## 11. Exécuter les tests

```bash
pytest tests/ -v
```

Tous les tests passent sans connexion PostgreSQL réelle (mocks de base de données).

---

## 12. Explorer la documentation API

```
http://localhost:8000/docs
```

---

## Résumé des commandes (ordre d'exécution)

```bash
# Installation
python -m venv venv && source venv/bin/activate   # ou venv\Scripts\activate sous Windows
pip install -r requirements.txt
cp .env.example .env                               # Éditer .env avec vos identifiants pgAdmin4

# Base de données (via pgAdmin4 Query Tool ou psql)
# → Exécuter database/migrations/001_init.sql sur la base 'arnaqueradar'

# Pipeline de données
python collect/collecter.py
python aggregate/aggregate.py
python database/import_data.py

# API et tests
uvicorn api.main:app --reload --port 8000
pytest tests/ -v
```

---

## Dépannage

| Problème | Cause probable | Solution |
|---|---|---|
| `connection refused` port 5432 | PostgreSQL local non démarré | Démarrer le service PostgreSQL depuis pgAdmin4 ou Windows Services |
| `password authentication failed` | Mauvais identifiants dans `.env` | Vérifier `PG_USER` et `PG_PASSWORD` dans `.env` |
| `database "arnaqueradar" does not exist` | Base non créée | Créer la base via pgAdmin4 (étape 3) |
| `relation "signalements" does not exist` | Migration non exécutée | Exécuter `001_init.sql` (étape 5) |
| `ModuleNotFoundError` | Virtualenv non activé | `venv\Scripts\activate` |
| `clean_dataset.csv` vide | Aucun fichier `raw_*.json` | Exécuter `python collect/collecter.py` d'abord |
| Tests échouent sur `auth_token` | Mauvais `ADMIN_PASSWORD` | Vérifier `.env` : `ADMIN_PASSWORD=arnaqueradar2024` |
